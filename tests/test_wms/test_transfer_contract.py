"""A transfer order has to say where the stock leaves from.

``POST /api/v1/warehouses/transfers`` read its body as a dict, and read the
source out of one key: ``data["source_location"]``.  Everything else about the
source was lost.  The key ``docs/functional-test-plan.md`` documents
(``source_warehouse_id``) was never read as a source — only as the last fallback
for the *destination* — so the documented request created an order with
``source_warehouse_id = NULL`` and a destination equal to the warehouse the
caller named as its origin: an order shipping a warehouse's stock to itself.
The key the mobile screen does send carries a warehouse *code*, ``_to_uuid``
answers None for a code, and the order was filed with a NULL source all the same.

The lines were read as ``item_data["sku"]`` and ``item_data["quantity"]``, so the
documented line (``{"sku_id": "...", "quantity": 50}``) raised KeyError inside
the handler and answered 500, and the line's source was written into
``TransferOrderLine.location_from_id`` — a location column — as a warehouse id.

The body is typed now (``src/wms/schemas.py:TransferOrderCreate``).  Both ends
are required, resolved by id *or* code, and refused by the field that named them.
"""

import uuid as uuid_mod

import pytest
from sqlalchemy import select

from src.wms.models import SKU


@pytest.fixture
async def auth_headers(async_client):
    uname = f"trctr_{uuid_mod.uuid4().hex[:8]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(autouse=True)
async def _authenticated(async_client, auth_headers):
    async_client.headers.update(auth_headers)
    yield


@pytest.fixture
def db(async_client):
    """The session the app runs on, so seeded rows are visible to the route."""
    return async_client._shared_session


async def _warehouse(async_client, tag: str) -> dict:
    r = await async_client.post("/api/v1/warehouses", json={
        "code": f"WH-{tag}-{uuid_mod.uuid4().hex[:8]}", "name": f"WH {tag}", "type": "center",
    })
    assert r.status_code == 201, r.text
    return r.json()


async def _orders(async_client, wh_id: str) -> list[dict]:
    r = await async_client.get(f"/api/v1/warehouses/transfers?warehouse_id={wh_id}")
    assert r.status_code == 200, r.text
    return r.json()


def _order(orders: list[dict], order_id: str) -> dict:
    return next(o for o in orders if o["id"] == order_id)


async def _create(async_client, body: dict):
    return await async_client.post("/api/v1/warehouses/transfers", json=body)


# ── Both ends of the transfer ────────────────────────────────────────────────


class TestTransferEnds:
    async def test_the_source_warehouse_is_recorded(self, async_client):
        """The documented body names both ends, and both must land in the order."""
        src, dst = await _warehouse(async_client, "src"), await _warehouse(async_client, "dst")
        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            "type": "SKU", "lines": [{"sku": "SKU-AAA", "quantity": 50}],
        })
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["source_warehouse_id"] == src["id"], "the transfer recorded no origin"
        assert body["target_warehouse_id"] == dst["id"]
        assert body["status"] == "DRAFT"

    async def test_the_source_the_mobile_screen_sends_is_accepted(self, async_client):
        """``mobile/src/screens/TransferOrderScreen.js`` sends ``source_location``;
        the service has always treated its value as a warehouse."""
        src, dst = await _warehouse(async_client, "mob"), await _warehouse(async_client, "mob2")
        created = await _create(async_client, {
            "source_location": src["id"], "destination_warehouse_id": dst["id"],
            "items": [{"sku": "SKU-MOBILE", "quantity": 3}],
        })
        assert created.status_code == 201, created.text
        assert created.json()["source_warehouse_id"] == src["id"]

    async def test_a_warehouse_code_names_a_warehouse(self, async_client):
        """A handheld scans codes.  ``_to_uuid`` answers None for one, and every
        caller that used it as a lookup filed the record with a NULL."""
        src, dst = await _warehouse(async_client, "code1"), await _warehouse(async_client, "code2")
        created = await _create(async_client, {
            "source_warehouse_id": src["code"], "target_warehouse_id": dst["code"],
            "items": [{"sku": "SKU-CODED", "quantity": 2}],
        })
        assert created.status_code == 201, created.text
        assert created.json()["source_warehouse_id"] == src["id"], "a warehouse code resolved to no warehouse"
        assert created.json()["target_warehouse_id"] == dst["id"]

    async def test_a_name_that_is_no_warehouse_is_answered_by_the_field(self, async_client):
        dst = await _warehouse(async_client, "known")
        created = await _create(async_client, {
            "source_warehouse_id": "WH-NOT-THERE", "target_warehouse_id": dst["id"],
            "items": [{"sku": "SKU-404", "quantity": 1}],
        })
        assert created.status_code == 404, created.text
        assert "source_warehouse_id" in created.text, "the refusal did not name the field that was wrong"

    async def test_a_warehouse_cannot_transfer_to_itself(self, async_client):
        wh = await _warehouse(async_client, "self")
        created = await _create(async_client, {
            "source_warehouse_id": wh["id"], "target_warehouse_id": wh["id"],
            "items": [{"sku": "SKU-SELF", "quantity": 4}],
        })
        assert created.status_code == 422, created.text
        assert "same warehouse" in created.json()["error"]["message"], created.text

    async def test_the_source_is_required(self, async_client):
        dst = await _warehouse(async_client, "only-dst")
        created = await _create(async_client, {
            "target_warehouse_id": dst["id"], "items": [{"sku": "SKU-NOSRC", "quantity": 1}],
        })
        assert created.status_code == 422, created.text
        body = created.json()
        assert body["success"] is False and body["error"]["code"] == "VALIDATION_ERROR", created.text
        assert any("source_warehouse_id" in e["field"] for e in body["errors"]), created.text

    async def test_a_source_alone_does_not_become_the_destination(self, async_client):
        """The old code fell back from the destination to ``source_warehouse_id``,
        which made an order whose destination is its own source."""
        src = await _warehouse(async_client, "src-only")
        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "items": [{"sku": "SKU-FALLBACK", "quantity": 1}],
        })
        assert created.status_code == 422, created.text
        assert any("target_warehouse_id" in e["field"] for e in created.json()["errors"]), created.text


# ── The lines ────────────────────────────────────────────────────────────────


class TestTransferLines:
    @pytest.mark.parametrize("key", ["lines", "items"])
    async def test_the_line_array_key_the_callers_use_is_accepted(self, async_client, key):
        src, dst = await _warehouse(async_client, "arr1"), await _warehouse(async_client, "arr2")
        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            key: [{"sku": "SKU-ARR", "quantity": 1}],
        })
        assert created.status_code == 201, created.text

    async def test_a_line_named_by_sku_id_is_accepted(self, async_client, db):
        """``docs/functional-test-plan.md`` documents lines named by ``sku_id``;
        the route read ``item_data["sku"]``, and that documented request answered
        500 — a server failure, reported as one, for a body that named a product."""
        src, dst = await _warehouse(async_client, "sku1"), await _warehouse(async_client, "sku2")
        row = SKU(id=uuid_mod.uuid4(), sku=f"SKU-{uuid_mod.uuid4().hex[:8]}", name="Doc SKU", gtin="")
        db.add(row)
        await db.flush()

        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            "type": "SKU", "lines": [{"sku_id": str(row.id), "quantity": 50}],
        })
        assert created.status_code == 201, created.text

        lines = _order(await _orders(async_client, src["id"]), created.json()["id"])["lines"]
        assert len(lines) == 1
        assert lines[0]["sku_id"] == str(row.id), "the documented line did not land on the product it named"
        assert lines[0]["quantity"] == "50.0000"

    async def test_a_line_records_the_warehouse_it_leaves_from(self, async_client):
        """``location_from_id`` is a location column; it used to receive the
        source warehouse id, and the line said it left from a bin that does not
        exist."""
        src, dst = await _warehouse(async_client, "from1"), await _warehouse(async_client, "from2")
        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            "items": [{"sku": "SKU-FROM", "quantity": 7}],
        })
        assert created.status_code == 201, created.text
        lines = _order(await _orders(async_client, src["id"]), created.json()["id"])["lines"]
        assert lines[0]["warehouse_id"] == src["id"]
        assert lines[0]["location_from_id"] is None, "a transfer line recorded a warehouse as a location"

    async def test_a_line_with_no_product_is_refused(self, async_client):
        src, dst = await _warehouse(async_client, "nop1"), await _warehouse(async_client, "nop2")
        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            "items": [{"quantity": 5}],
        })
        assert created.status_code == 422, created.text
        assert "names no product" in created.json()["error"]["message"], created.text

    async def test_a_line_naming_the_product_twice_is_refused(self, async_client, db):
        src, dst = await _warehouse(async_client, "both1"), await _warehouse(async_client, "both2")
        row = SKU(id=uuid_mod.uuid4(), sku=f"SKU-{uuid_mod.uuid4().hex[:8]}", name="Both SKU", gtin="")
        db.add(row)
        await db.flush()

        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            "items": [{"sku": "SOMETHING-ELSE", "sku_id": str(row.id), "quantity": 5}],
        })
        assert created.status_code == 422, created.text
        assert "twice" in created.json()["error"]["message"], created.text

    async def test_an_unknown_sku_id_is_refused(self, async_client):
        src, dst = await _warehouse(async_client, "unk1"), await _warehouse(async_client, "unk2")
        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            "lines": [{"sku_id": str(uuid_mod.uuid4()), "quantity": 5}],
        })
        assert created.status_code == 422, created.text
        assert "sku_id" in created.json()["error"]["message"], created.text

    async def test_a_non_numeric_quantity_is_a_validation_error_not_a_500(self, async_client):
        """``Decimal("5x")`` inside the handler: the server reported its own
        breakdown for a request whose quantity was typed in the wrong place."""
        src, dst = await _warehouse(async_client, "qty1"), await _warehouse(async_client, "qty2")
        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            "items": [{"sku": "SKU-QTY", "quantity": "5x"}],
        })
        assert created.status_code == 422, created.text
        body = created.json()
        assert body["error"]["code"] == "VALIDATION_ERROR", created.text
        assert any("quantity" in e["field"] for e in body["errors"]), created.text

    @pytest.mark.parametrize("qty", [0, -3])
    async def test_a_line_that_moves_nothing_is_refused(self, async_client, qty):
        src, dst = await _warehouse(async_client, "zero1"), await _warehouse(async_client, "zero2")
        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            "items": [{"sku": "SKU-ZERO", "quantity": qty}],
        })
        assert created.status_code == 422, created.text

    async def test_an_empty_line_list_is_refused(self, async_client):
        src, dst = await _warehouse(async_client, "none1"), await _warehouse(async_client, "none2")
        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"], "lines": [],
        })
        assert created.status_code == 422, created.text
        assert any("lines" in e["field"] for e in created.json()["errors"]), created.text

    async def test_a_code_the_catalog_does_not_carry_still_gets_a_row(self, async_client, db):
        """The mobile flow scans codes the catalog has never seen; the precedent
        of creating the catalog row on transfer stands, and is recorded here."""
        src, dst = await _warehouse(async_client, "new1"), await _warehouse(async_client, "new2")
        code = f"SKU-FRESH-{uuid_mod.uuid4().hex[:6]}"
        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            "items": [{"sku": code, "quantity": 9}],
        })
        assert created.status_code == 201, created.text
        found = await db.scalar(select(SKU.id).where(SKU.sku == code))
        assert found is not None, "the scanned code never reached the SKU catalog"


# ── The body itself ──────────────────────────────────────────────────────────


class TestTransferBody:
    async def test_the_envelope_shape_is_accepted(self, async_client):
        src, dst = await _warehouse(async_client, "env1"), await _warehouse(async_client, "env2")
        created = await _create(async_client, {"data": {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            "lines": [{"sku": "SKU-ENV", "quantity": 2}],
        }})
        assert created.status_code == 201, created.text

    async def test_the_type_is_the_transfer_item_vocabulary(self, async_client):
        src, dst = await _warehouse(async_client, "typ1"), await _warehouse(async_client, "typ2")
        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            "type": "PALLET", "items": [{"sku": "SKU-TYPE", "quantity": 1}],
        })
        assert created.status_code == 422, created.text
        assert "SKU" in created.text and "WAREHOUSE" in created.text, "the refusal did not name the allowed types"

    async def test_a_key_the_endpoint_does_not_read_is_refused_by_name(self, async_client):
        """A key nobody reads used to be dropped silently, so a caller who sent
        ``priority`` believed they had set a priority."""
        src, dst = await _warehouse(async_client, "ext1"), await _warehouse(async_client, "ext2")
        created = await _create(async_client, {
            "source_warehouse_id": src["id"], "target_warehouse_id": dst["id"],
            "priority": "HIGH", "items": [{"sku": "SKU-KEY", "quantity": 1}],
        })
        assert created.status_code == 422, created.text
        assert any("priority" in e["field"] for e in created.json()["errors"]), created.text

    async def test_a_refused_transfer_creates_no_order(self, async_client):
        """The refusals above happen before any row is written; a rejected
        request must not leave a DRAFT order nobody asked for."""
        wh = await _warehouse(async_client, "clean")
        created = await _create(async_client, {
            "source_warehouse_id": wh["id"], "target_warehouse_id": wh["id"],
            "items": [{"sku": "SKU-CLEAN", "quantity": 1}],
        })
        assert created.status_code == 422, created.text
        orders = [o for o in await _orders(async_client, wh["id"]) if o["source_warehouse_id"] == wh["id"]]
        assert orders == [], f"a refused transfer filed an order: {orders}"
