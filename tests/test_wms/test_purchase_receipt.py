"""Purchase-order receiving: from a status flip to booked stock.

``receive_goods()`` used to be two lines — set ``status='received'``, commit.
It added nothing to inventory, so the delivered quantity did not exist
anywhere, a delivery of 3 against an order of 100 looked identical to a
complete delivery, and a PDA that confirmed a receipt left the warehouse
looking exactly as it had before.

Three things had to be fixed together for a receipt to mean anything:

* ``PurchaseOrderLine`` needed a landed quantity (``received_qty``) — partial
  delivery is a physical fact the model could not represent;
* ``PurchaseOrderCreate`` dropped ``lines`` on ``model_dump()``, so every PO
  created through the API was empty, and the response carried no lines either,
  so a receiving screen had nothing to type quantities into;
* the receipt needs a destination.  With no warehouse/location there was no
  inventory row to book, which is precisely why "flip the status" was the only
  thing it could do.

Also pinned: the whole receipt lands in one transaction, so a failure cannot
leave stock booked that no order accounts for.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.wms.models import PurchaseOrderLine


@pytest.fixture
async def auth_client(async_client):
    """async_client with a bearer token, mirroring test_wms_router."""
    uname = f"po_{uuid.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname,
        "email": f"{uname}@test.com",
        "password": "test123456",
    })
    resp = await async_client.post(
        "/api/v1/auth/login", json={"username": uname, "password": "test123456"}
    )
    async_client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return async_client


async def _warehouse(client, name: str = "Receiving WH") -> str:
    resp = await client.post("/api/v1/warehouses", json={
        "code": f"WH-{uuid.uuid4().hex[:6]}", "name": name, "address": "",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _location(client, wh_id: str, bin_label: str = "1") -> str:
    resp = await client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
        "zone": "A", "aisle": "1", "shelf": "1", "bin": bin_label,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_po(client, *, lines: list[dict], **extra) -> dict:
    resp = await client.post("/api/v1/warehouses/purchase-orders", json={
        "po_number": f"PO-{uuid.uuid4().hex[:8]}",
        "lines": lines,
        **extra,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _inventory_qty(client, wh_id: str, sku: str) -> Decimal:
    resp = await client.get(f"/api/v1/warehouses/inventory?warehouse_id={wh_id}")
    assert resp.status_code == 200, resp.text
    rows = [r for r in resp.json() if r["sku"] == sku]
    return sum((Decimal(str(r["quantity"])) for r in rows), Decimal("0"))


# ══════════════════════════════════════════════════════════════════════════════
# Creating an order that can actually be received
# ══════════════════════════════════════════════════════════════════════════════


class TestPurchaseOrderCreate:
    @pytest.mark.asyncio
    async def test_lines_survive_the_request(self, auth_client):
        """create_purchase_order() looped over data["lines"], which the schema had dropped."""
        po = await _create_po(auth_client, lines=[
            {"sku": "SKU-CARTON", "quantity": 10, "unit_price": 4.5},
            {"sku": "SKU-PALLET", "quantity": 2, "unit_price": 100},
        ])

        assert len(po["lines"]) == 2
        assert {line["sku"] for line in po["lines"]} == {"SKU-CARTON", "SKU-PALLET"}
        assert all(Decimal(str(line["received_qty"])) == 0 for line in po["lines"])
        assert po["total_amount"] == 10 * 4.5 + 2 * 100

    @pytest.mark.asyncio
    async def test_expected_date_does_not_500(self, auth_client):
        """model_to_dict() returns a date; the response field was typed `str`, so pydantic refused it."""
        resp = await auth_client.post("/api/v1/warehouses/purchase-orders", json={
            "po_number": f"PO-{uuid.uuid4().hex[:8]}",
            "expected_date": "2027-03-31",
            "lines": [{"sku": "SKU-DATED", "quantity": 1, "unit_price": 1}],
        })

        assert resp.status_code == 201, resp.text
        assert resp.json()["expected_date"] == "2027-03-31"

    @pytest.mark.asyncio
    async def test_bad_expected_date_is_422_not_500(self, auth_client):
        resp = await auth_client.post("/api/v1/warehouses/purchase-orders", json={
            "po_number": f"PO-{uuid.uuid4().hex[:8]}",
            "expected_date": "31/03/2027",
        })
        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_status_filter_is_applied(self, auth_client):
        """?status=pending returned whatever was in the table, unfiltered."""
        po = await _create_po(auth_client, lines=[{"sku": "SKU-FILTER", "quantity": 1, "unit_price": 1}])

        drafts = await auth_client.get("/api/v1/warehouses/purchase-orders?status=draft")
        assert any(item["id"] == po["id"] for item in drafts.json()["items"])

        # "pending" is not a status this table stores; it now means
        # approved+partial, so an unapproved order must not show up as receivable.
        awaiting = await auth_client.get("/api/v1/warehouses/purchase-orders?status=pending")
        assert all(item["id"] != po["id"] for item in awaiting.json()["items"])

        await auth_client.post(f"/api/v1/warehouses/purchase-orders/{po['id']}/approve")
        awaiting = await auth_client.get("/api/v1/warehouses/purchase-orders?status=pending")
        assert any(item["id"] == po["id"] for item in awaiting.json()["items"])


# ══════════════════════════════════════════════════════════════════════════════
# Receiving
# ══════════════════════════════════════════════════════════════════════════════


async def _approved_po(client, sku: str, quantity: int) -> tuple[dict, str]:
    po = await _create_po(client, lines=[{"sku": sku, "quantity": quantity, "unit_price": 1}])
    resp = await client.post(f"/api/v1/warehouses/purchase-orders/{po['id']}/approve")
    assert resp.status_code == 200, resp.text
    return resp.json(), po["id"]


class TestReceiveGoods:
    @pytest.mark.asyncio
    async def test_receipt_books_the_stock_that_arrived(self, auth_client):
        _po, po_id = await _approved_po(auth_client, "SKU-LANDED", 10)
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/receive",
            json={
                "warehouse_id": wh_id,
                "location_id": loc_id,
                "lines": [{"sku": "SKU-LANDED", "received_qty": 10, "batch_no": "B-900"}],
            },
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "received"
        assert Decimal(str(body["lines"][0]["received_qty"])) == Decimal("10")
        assert body["lines"][0]["received_at"], "the receipt needs a when, not just a how much"
        # The point of the whole change: the goods are in the warehouse now.
        assert await _inventory_qty(auth_client, wh_id, "SKU-LANDED") == Decimal("10")

    @pytest.mark.asyncio
    async def test_partial_delivery_is_a_partial_receipt(self, auth_client):
        """3 of 100 used to be recorded exactly like 100 of 100."""
        _po, po_id = await _approved_po(auth_client, "SKU-SHORT", 100)
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/receive",
            json={
                "warehouse_id": wh_id, "location_id": loc_id,
                "lines": [{"sku": "SKU-SHORT", "received_qty": 3}],
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "partial"
        # The 3 units that are physically in the building are pickable stock.
        assert await _inventory_qty(auth_client, wh_id, "SKU-SHORT") == Decimal("3")

        # The balance is still open, and a second receipt measures against it.
        rest = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/receive",
            json={
                "warehouse_id": wh_id, "location_id": loc_id,
                "lines": [{"sku": "SKU-SHORT", "received_qty": 97}],
            },
        )
        assert rest.json()["status"] == "received"
        assert Decimal(str(rest.json()["lines"][0]["received_qty"])) == Decimal("100")

    @pytest.mark.asyncio
    async def test_batch_and_expiry_travel_with_the_delivery(self, auth_client):
        _po, po_id = await _approved_po(auth_client, "SKU-FEFO-PO", 5)
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/receive",
            json={
                "warehouse_id": wh_id, "location_id": loc_id,
                "lines": [{
                    "sku": "SKU-FEFO-PO", "received_qty": 5,
                    "batch_no": "B-EXP", "expiry_date": "2027-06-30",
                }],
            },
        )

        resp = await auth_client.get(f"/api/v1/warehouses/inventory?warehouse_id={wh_id}")
        row = next(r for r in resp.json() if r["sku"] == "SKU-FEFO-PO")
        assert row["batch_no"] == "B-EXP"
        assert row["expiry_date"] == "2027-06-30"

    @pytest.mark.asyncio
    async def test_no_body_says_what_a_receipt_needs(self, auth_client):
        """The body-less call was the only shape this endpoint accepted."""
        _po, po_id = await _approved_po(auth_client, "SKU-NOBODY", 1)
        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/receive", json={}
        )

        assert resp.status_code == 422, resp.text
        assert "warehouse_id" in resp.text

    @pytest.mark.asyncio
    async def test_no_lines_means_the_whole_outstanding_order(self, auth_client):
        _po, po_id = await _approved_po(auth_client, "SKU-BALANCE", 12)
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/receive",
            json={"warehouse_id": wh_id, "location_id": loc_id},
        )

        assert resp.status_code == 200, resp.text
        assert Decimal(str(resp.json()["lines"][0]["received_qty"])) == Decimal("12")
        assert await _inventory_qty(auth_client, wh_id, "SKU-BALANCE") == Decimal("12")

    @pytest.mark.asyncio
    async def test_draft_order_cannot_be_received(self, auth_client):
        po = await _create_po(auth_client, lines=[{"sku": "SKU-DRAFT", "quantity": 1, "unit_price": 1}])
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po['id']}/receive",
            json={"warehouse_id": wh_id, "location_id": loc_id},
        )

        assert resp.status_code == 422, resp.text
        assert "draft" in resp.text
        assert await _inventory_qty(auth_client, wh_id, "SKU-DRAFT") == Decimal("0")

    @pytest.mark.asyncio
    async def test_empty_order_cannot_be_received(self, auth_client):
        """A PO with no lines used to be receivable, because nothing was booked anyway."""
        resp = await auth_client.post("/api/v1/warehouses/purchase-orders", json={
            "po_number": f"PO-{uuid.uuid4().hex[:8]}",
        })
        po_id = resp.json()["id"]
        await auth_client.post(f"/api/v1/warehouses/purchase-orders/{po_id}/approve")

        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)
        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/receive",
            json={"warehouse_id": wh_id, "location_id": loc_id},
        )

        assert resp.status_code == 422, resp.text
        assert "no lines" in resp.text

    @pytest.mark.asyncio
    async def test_location_of_another_warehouse_is_refused(self, auth_client):
        """adjust_inventory() only checks that both ids exist."""
        _po, po_id = await _approved_po(auth_client, "SKU-MISHELVED", 5)
        dest_wh = await _warehouse(auth_client, "Destination")
        other_wh = await _warehouse(auth_client, "Somebody else")
        other_loc = await _location(auth_client, other_wh)

        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/receive",
            json={
                "warehouse_id": dest_wh, "location_id": other_loc,
                "lines": [{"sku": "SKU-MISHELVED", "received_qty": 5}],
            },
        )

        assert resp.status_code == 422, resp.text
        assert "belongs to warehouse" in resp.text
        assert await _inventory_qty(auth_client, dest_wh, "SKU-MISHELVED") == Decimal("0")
        assert await _inventory_qty(auth_client, other_wh, "SKU-MISHELVED") == Decimal("0")

    @pytest.mark.asyncio
    async def test_sku_not_on_the_order_is_refused(self, auth_client):
        _po, po_id = await _approved_po(auth_client, "SKU-ONORDER", 5)
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/receive",
            json={
                "warehouse_id": wh_id, "location_id": loc_id,
                "lines": [{"sku": "SKU-SCANNED-BUT-NO", "received_qty": 5}],
            },
        )

        assert resp.status_code == 422, resp.text
        assert "not on PO" in resp.text
        # A mistyped scan must not conjure stock for a SKU nobody ordered.
        assert await _inventory_qty(auth_client, wh_id, "SKU-SCANNED-BUT-NO") == Decimal("0")

    @pytest.mark.asyncio
    async def test_ambiguous_sku_asks_for_the_line_id(self, auth_client):
        po = await _create_po(auth_client, lines=[
            {"sku": "SKU-TWIN", "quantity": 5, "unit_price": 1, "description": "lot A"},
            {"sku": "SKU-TWIN", "quantity": 7, "unit_price": 2, "description": "lot B"},
        ])
        await auth_client.post(f"/api/v1/warehouses/purchase-orders/{po['id']}/approve")
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po['id']}/receive",
            json={
                "warehouse_id": wh_id, "location_id": loc_id,
                "lines": [{"sku": "SKU-TWIN", "received_qty": 5}],
            },
        )

        assert resp.status_code == 422, resp.text
        assert "line_id" in resp.text

    @pytest.mark.asyncio
    async def test_someone_elses_line_is_refused(self, auth_client):
        """A line_id from another PO would book this delivery against that order."""
        other = await _create_po(auth_client, lines=[{"sku": "SKU-OTHER", "quantity": 5, "unit_price": 1}])
        await auth_client.post(f"/api/v1/warehouses/purchase-orders/{other['id']}/approve")
        _po, po_id = await _approved_po(auth_client, "SKU-THIS", 5)
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/receive",
            json={
                "warehouse_id": wh_id, "location_id": loc_id,
                "lines": [{"line_id": other["lines"][0]["id"], "received_qty": 5}],
            },
        )

        assert resp.status_code == 422, resp.text
        assert "not part of PO" in resp.text

    @pytest.mark.asyncio
    async def test_zero_delivery_is_not_a_receipt(self, auth_client):
        _po, po_id = await _approved_po(auth_client, "SKU-NOTHING", 5)
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/receive",
            json={
                "warehouse_id": wh_id, "location_id": loc_id,
                "lines": [{"sku": "SKU-NOTHING", "received_qty": 0}],
            },
        )

        assert resp.status_code == 422, resp.text
        # ...and the order stays receivable rather than being closed out.
        # src/main.py wraps AppExceptions as {"success": false, "error": {...}}.
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
        assert resp.json()["error"]["message"].startswith("Nothing was received")

    @pytest.mark.asyncio
    async def test_po_number_is_accepted_instead_of_a_uuid(self, auth_client):
        """_to_uuid() returned None for a document number, and the lookup reported the PO missing."""
        po = await _create_po(auth_client, lines=[{"sku": "SKU-BYNUMBER", "quantity": 4, "unit_price": 1}])
        await auth_client.post(f"/api/v1/warehouses/purchase-orders/{po['id']}/approve")
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po['po_number']}/receive",
            json={"warehouse_id": wh_id, "location_id": loc_id},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["po_number"] == po["po_number"]

    @pytest.mark.asyncio
    async def test_unknown_po_number_says_so(self, auth_client):
        resp = await auth_client.get("/api/v1/warehouses/purchase-orders/PO-NOPE")
        assert resp.status_code == 404, resp.text
        assert "PO-NOPE" in resp.text


# ══════════════════════════════════════════════════════════════════════════════
# One transaction per receipt
# ══════════════════════════════════════════════════════════════════════════════


class TestReceiptAtomicity:
    @pytest.mark.asyncio
    async def test_a_failure_mid_receipt_books_nothing(self, auth_client, monkeypatch):
        """Line 1 is booked, line 2 fails.

        Booking each line in its own transaction would leave line 1's stock in
        the warehouse while the receipt reported failure and the order stayed
        "approved" — inventory no purchase order accounts for, and a replay of
        the same receipt would book it a second time.
        """
        from src.wms import service as wms_service

        po = await _create_po(auth_client, lines=[
            {"sku": "SKU-OK", "quantity": 5, "unit_price": 1},
            {"sku": "SKU-BOOM", "quantity": 5, "unit_price": 1},
        ])
        await auth_client.post(f"/api/v1/warehouses/purchase-orders/{po['id']}/approve")
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        real_adjust = wms_service.adjust_inventory

        async def _explode_on_second_line(db, data, **kwargs):
            if data["sku"] == "SKU-BOOM":
                raise RuntimeError("warehouse system unavailable")
            return await real_adjust(db, data, **kwargs)

        monkeypatch.setattr(wms_service, "adjust_inventory", _explode_on_second_line)

        with pytest.raises(RuntimeError):
            await wms_service.receive_goods(db=auth_client._shared_session, po_id=po["id"], data={
                "warehouse_id": wh_id,
                "location_id": loc_id,
                "lines": [
                    {"sku": "SKU-OK", "received_qty": 5},
                    {"sku": "SKU-BOOM", "received_qty": 5},
                ],
            })

        session = auth_client._shared_session
        await session.rollback()

        # Neither line recorded anything, and neither SKU gained stock.
        landed = await session.execute(
            select(PurchaseOrderLine).where(
                PurchaseOrderLine.purchase_order_id == uuid.UUID(po["id"])
            )
        )
        assert all(Decimal(str(line.received_qty)) == 0 for line in landed.scalars().all())
        assert await _inventory_qty(auth_client, wh_id, "SKU-OK") == Decimal("0")

    @pytest.mark.asyncio
    async def test_inventory_contention_aborts_the_whole_receipt(self, auth_client, monkeypatch):
        """The optimistic-lock retry rolls the session back — and with it the lines already booked.

        adjust_inventory() retries a version race by rolling back.  Inside a
        multi-line receipt that rollback also throws away the earlier lines'
        bookkeeping, so carrying on would commit a receipt whose quantities no
        longer match the stock.  The receipt has to stop and say so.
        """
        from src.core.exceptions import ConflictException
        from src.wms import service as wms_service

        po = await _create_po(auth_client, lines=[
            {"sku": "SKU-RACE", "quantity": 5, "unit_price": 1},
            {"sku": "SKU-LATER", "quantity": 5, "unit_price": 1},
        ])
        await auth_client.post(f"/api/v1/warehouses/purchase-orders/{po['id']}/approve")
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        real_adjust = wms_service.adjust_inventory

        calls: list[str] = []

        async def _race_on_first_line(db, data, **kwargs):
            calls.append(data["sku"])
            if data["sku"] == "SKU-RACE":
                # Exactly what the version-conflict branch does: roll the
                # session back and retry, returning as if it had landed.
                await db.rollback()
                return {"sku": data["sku"]}
            return await real_adjust(db, data, **kwargs)

        monkeypatch.setattr(wms_service, "adjust_inventory", _race_on_first_line)

        session = auth_client._shared_session
        with pytest.raises(ConflictException) as exc_info:
            await wms_service.receive_goods(
                session, po["id"],
                {
                    "warehouse_id": wh_id,
                    "location_id": loc_id,
                    "lines": [
                        {"sku": "SKU-RACE", "received_qty": 5},
                        {"sku": "SKU-LATER", "received_qty": 5},
                    ],
                },
            )

        assert exc_info.value.status_code == 409
        assert "not applied" in exc_info.value.message
        # The receipt stopped at the line that raced: the lines behind it were
        # never booked against bookkeeping that had already been thrown away.
        assert calls == ["SKU-RACE"]
        await session.rollback()

    def test_adjust_inventory_keeps_its_own_commit_by_default(self):
        """The new keyword must not silently change the single-adjustment path."""
        import inspect

        from src.wms.service import adjust_inventory

        param = inspect.signature(adjust_inventory).parameters["commit"]
        assert param.default is True
        assert param.kind is inspect.Parameter.KEYWORD_ONLY

    @pytest.mark.asyncio
    async def test_receipt_of_dated_line_uses_the_ordered_sku(self, auth_client):
        """A line created from a SKU code receives into that SKU's inventory row."""
        po = await _create_po(auth_client, lines=[
            {"sku": "SKU-CODE-LINE", "quantity": 3, "unit_price": 1},
        ])
        await auth_client.post(f"/api/v1/warehouses/purchase-orders/{po['id']}/approve")
        assert po["lines"][0]["sku_id"], "the code should have resolved to a SKU"

        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)
        resp = await auth_client.post(
            f"/api/v1/warehouses/purchase-orders/{po['id']}/receive",
            json={"warehouse_id": wh_id, "location_id": loc_id},
        )
        assert resp.status_code == 200, resp.text
        assert await _inventory_qty(auth_client, wh_id, "SKU-CODE-LINE") == Decimal("3")

    def test_receivable_statuses_and_dates_are_typed_not_stringly(self):
        """The lifecycle the endpoint enforces, and the types the schema declares."""
        from src.wms.schemas import PurchaseOrderCreate, PurchaseOrderResponse
        from src.wms.service import PO_RECEIVABLE_STATUSES

        assert PO_RECEIVABLE_STATUSES == ("approved", "partial")
        # `date`, because model_to_dict() hands back a date and pydantic will
        # not squeeze one into a str field.
        assert PurchaseOrderResponse.model_fields["expected_date"].annotation == date | None
        assert PurchaseOrderCreate.model_fields["expected_date"].annotation == date | None
