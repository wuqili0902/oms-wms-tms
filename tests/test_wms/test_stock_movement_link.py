"""A stock-out must move stock when it ships, and say so batch by batch.

``POST /api/v1/stock-out`` created a document and its lines;
``PUT /api/v1/stock-out/{id} {status: SHIPPED}`` set the status column.  Between
those two calls, nothing in this file's subject moved: not one
``Inventory.quantity``, not one ``InventoryLog``, not one ``StockInventoryLog``.
A shipment of 1 000 units of a SKU with 3 on the shelf was accepted, and a
shipment that left perfectly was recorded in the same place, and with the same
detail, as one that never existed — a row in ``stock_out``.

The audit trail of a shipment is therefore not a shipment: the ledger
``GET /api/v1/inventory-log`` serves listed adjustments and nothing a warehouse
actually shipped, while the quantities on the shelf were moved by other paths
(picking, adjustments) that write their own rows.

Consumption happens on CONFIRMED → SHIPPED, in the route's transaction, FEFO,
with the same ``available = quantity - locked_qty`` reading every other path in
this codebase uses.
"""

import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.wms.models import SKU, Inventory, InventoryChangeType, InventoryLog

BATCH_EXPIRY_EARLY = datetime.now(UTC).replace(tzinfo=None).date() + timedelta(days=30)
BATCH_EXPIRY_LATE = datetime.now(UTC).replace(tzinfo=None).date() + timedelta(days=400)


@pytest.fixture
async def auth_headers(async_client):
    uname = f"stklink_{uuid_mod.uuid4().hex[:8]}"
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
    """The session the app is running on — seeding must be visible to the route."""
    return async_client._shared_session


@pytest.fixture
async def warehouse(async_client, auth_headers):
    r = await async_client.post("/api/v1/warehouses", json={
        "code": f"WH-LINK-{uuid_mod.uuid4().hex[:8]}", "name": "Link Warehouse", "type": "center",
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def sku(db):
    """A catalog SKU, flushed (not committed): the route's transaction must see it."""
    code = f"SKU-LINK-{uuid_mod.uuid4().hex[:8]}"
    row = SKU(id=uuid_mod.uuid4(), sku=code, name="Link SKU", gtin="")
    db.add(row)
    await db.flush()
    return row


def _new_batch(warehouse, sku, *, qty, batch_no, expiry=None, locked="0") -> Inventory:
    return Inventory(
        id=uuid_mod.uuid4(), warehouse_id=uuid_mod.UUID(warehouse["id"]), sku_id=sku.id,
        gtin="", batch_no=batch_no, quantity=Decimal(str(qty)), locked_qty=Decimal(str(locked)),
        expiry_date=expiry, received_at=datetime.now(UTC).replace(tzinfo=None), version=0,
    )


async def _stock_on(db, warehouse, sku, batches):
    """Put batches on the shelf without committing them.

    Seeding commits are a problem here: the route calls ``commit()`` on the same
    session, and committed test data survives the savepoint the suite wraps each
    test in — it would leak into every later test.  Flushing gives the route rows
    to read inside its own transaction and nothing that outlives it.
    """
    for spec in batches:
        db.add(_new_batch(warehouse, sku, **spec))
    await db.flush()


async def _create(db, *, wh_id, lines):
    """A shipment written straight to the tables, in DRAFT.

    Used where the test needs a document the API would refuse to create (a line
    with no product on it), and where the point is the state the document is in,
    not how it got there.
    """
    from src.models.wms import StockOut, StockOutLine

    doc = StockOut(
        id=uuid_mod.uuid4(), warehouse_id=uuid_mod.UUID(wh_id), type="SALE",
        total_qty=sum((Decimal(str(q)) for _s, q in lines), Decimal("0")),
        status="DRAFT",
    )
    doc.lines = [StockOutLine(stock_out_id=doc.id, sku=s, qty_shipped=Decimal(str(q))) for s, q in lines]
    db.add(doc)
    await db.flush()
    return doc


async def _set_status(async_client, doc_id, status):
    return await async_client.put(f"/api/v1/stock-out/{doc_id}", json={"data": {"status": status}})


async def _rows(db, warehouse, sku):
    from sqlalchemy import select

    result = await db.execute(
        select(Inventory).where(Inventory.warehouse_id == uuid_mod.UUID(warehouse["id"]),
                                Inventory.sku_id == sku.id)
    )
    return {inv.batch_no: inv for inv in result.scalars().all()}


async def _logs(db, doc_id):
    from sqlalchemy import select

    result = await db.execute(
        select(InventoryLog).where(
            InventoryLog.reference_type == "stock_out",
            InventoryLog.reference_id == uuid_mod.UUID(doc_id),
        ).order_by(InventoryLog.created_at)
    )
    return list(result.scalars().all())


# ── When the shelf moves ─────────────────────────────────────────────────────


class TestTheShelfMovesOnShip:
    async def test_creating_a_shipment_moves_nothing(self, async_client, db, warehouse, sku):
        """Creation is paperwork: the goods have not left, and an API that deducted
        at creation and again at ship would count every shipment twice."""
        await _stock_on(db, warehouse, sku, [{"qty": "10", "batch_no": "B-ONE"}])

        created = await async_client.post("/api/v1/stock-out", json={"data": {
            "warehouse_id": warehouse["id"], "type": "SALE",
            "lines": [{"sku": sku.sku, "qty": 6}],
        }})
        assert created.status_code == 201, created.text

        rows = await _rows(db, warehouse, sku)
        assert rows["B-ONE"].quantity == Decimal("10"), "the shelf moved when the document was created"
        assert await _logs(db, created.json()["id"]) == []

    async def test_confirming_moves_nothing(self, async_client, db, warehouse, sku):
        """Confirmation reserves work; it is not a movement.  Deducting at creation
        too would count the same shipment twice."""
        await _stock_on(db, warehouse, sku, [{"qty": "10", "batch_no": "B-ONE"}])
        doc = await _create(db, wh_id=warehouse["id"], lines=[(sku.sku, 6)])
        confirm = await _set_status(async_client, str(doc.id), "CONFIRMED")
        assert confirm.status_code == 200, confirm.text

        rows = await _rows(db, warehouse, sku)
        assert rows["B-ONE"].quantity == Decimal("10"), "the stock left when the document was confirmed"
        assert await _logs(db, str(doc.id)) == []

    async def test_shipping_deducts_in_fefo_order(self, async_client, db, warehouse, sku):
        """The batch that expires first leaves first, and the pick spans batches."""
        await _stock_on(db, warehouse, sku, [
            {"qty": "5", "batch_no": "B-LATE", "expiry": BATCH_EXPIRY_LATE},
            {"qty": "5", "batch_no": "B-EARLY", "expiry": BATCH_EXPIRY_EARLY},
        ])
        doc = await _create(db, wh_id=warehouse["id"], lines=[(sku.sku, 7)])
        await _set_status(async_client, str(doc.id), "CONFIRMED")

        ship = await _set_status(async_client, str(doc.id), "SHIPPED")
        assert ship.status_code == 200, ship.text

        rows = await _rows(db, warehouse, sku)
        assert rows["B-EARLY"].quantity == Decimal("0"), "the earliest-expiry batch must leave first"
        assert rows["B-LATE"].quantity == Decimal("3")

    async def test_a_fractional_line_is_not_rounded_down(self, async_client, db, warehouse, sku):
        """``pick_from_stock`` narrows its pick to ``int(pick_qty)``; a 2.5 kg line
        shipped through the same idea on the shelf leaves 0.5 behind."""
        await _stock_on(db, warehouse, sku, [{"qty": "10", "batch_no": "B-ONE"}])
        doc = await _create(db, wh_id=warehouse["id"], lines=[(sku.sku, "2.5")])
        await _set_status(async_client, str(doc.id), "CONFIRMED")
        ship = await _set_status(async_client, str(doc.id), "SHIPPED")
        assert ship.status_code == 200, ship.text

        rows = await _rows(db, warehouse, sku)
        assert rows["B-ONE"].quantity == Decimal("7.5")

    async def test_locked_stock_is_not_shippable(self, async_client, db, warehouse, sku):
        """``locked_qty`` is the slice of ``quantity`` other orders hold; every other
        reader in this codebase computes available = quantity - locked_qty."""
        await _stock_on(db, warehouse, sku, [{"qty": "10", "batch_no": "B-ONE", "locked": "9"}])
        doc = await _create(db, wh_id=warehouse["id"], lines=[(sku.sku, 5)])
        await _set_status(async_client, str(doc.id), "CONFIRMED")

        ship = await _set_status(async_client, str(doc.id), "SHIPPED")
        assert ship.status_code == 422, ship.text
        assert "has 1.0000 available" in ship.json()["error"]["message"], ship.text


# ── The audit rows ───────────────────────────────────────────────────────────


class TestPerBatchAuditTrail:
    async def test_every_batch_touched_writes_its_own_row(self, async_client, db, warehouse, sku):
        await _stock_on(db, warehouse, sku, [
            {"qty": "5", "batch_no": "B-LATE", "expiry": BATCH_EXPIRY_LATE},
            {"qty": "5", "batch_no": "B-EARLY", "expiry": BATCH_EXPIRY_EARLY},
        ])
        doc = await _create(db, wh_id=warehouse["id"], lines=[(sku.sku, 7)])
        await _set_status(async_client, str(doc.id), "CONFIRMED")
        await _set_status(async_client, str(doc.id), "SHIPPED")

        logs = await _logs(db, str(doc.id))
        assert len(logs) == 2, "a shipment that spans two batches wrote a single log row"
        by_batch = {log.remark.split("batch ")[-1]: log for log in logs}
        assert set(by_batch) == {"B-EARLY", "B-LATE"}, "the audit rows do not name the batches they deducted"
        assert by_batch["B-EARLY"].quantity_change == Decimal("-5")
        assert by_batch["B-EARLY"].quantity_before == Decimal("5")
        assert by_batch["B-EARLY"].quantity_after == Decimal("0")
        assert by_batch["B-LATE"].quantity_change == Decimal("-2")
        assert by_batch["B-LATE"].quantity_before == Decimal("5")
        assert by_batch["B-LATE"].quantity_after == Decimal("3")
        for row in logs:
            assert row.change_type == InventoryChangeType.OUTBOUND
            assert str(row.reference_id) == str(doc.id), "the audit row does not name the shipment it belongs to"

    async def test_the_shipment_appears_in_the_ledger_the_api_serves(self, async_client, warehouse, sku, db):
        """``GET /api/v1/inventory-log`` reads ``StockInventoryLog``; a shipment that
        writes nothing there is invisible in the screen that lists stock movements."""
        await _stock_on(db, warehouse, sku, [{"qty": "9", "batch_no": "B-ONE"}])
        doc = await _create(db, wh_id=warehouse["id"], lines=[(sku.sku, 4)])
        await _set_status(async_client, str(doc.id), "CONFIRMED")
        ship = await _set_status(async_client, str(doc.id), "SHIPPED")
        assert ship.status_code == 200, ship.text

        listing = await async_client.get(f"/api/v1/inventory-log?warehouse_id={warehouse['id']}")
        assert listing.status_code == 200, listing.text
        shipment_rows = [r for r in listing.json() if r["reference_type"] == "stock_out"]
        assert shipment_rows, "the ledger listed no shipment at all"
        assert shipment_rows[0]["type"] == "OUTBOUND"
        assert Decimal(shipment_rows[0]["quantity_change"]) == Decimal("-4"), (
            "an outbound row is signed as an outbound row: StockInventoryLog documents "
            "+ve = in, -ve = out, and a ledger that mixes signs does not sum to the shelf"
        )
        assert shipment_rows[0]["reference_id"] == str(doc.id)

    async def test_the_shipment_names_the_operator_who_shipped_it(self, async_client, warehouse, sku, db, auth_headers):
        await _stock_on(db, warehouse, sku, [{"qty": "9", "batch_no": "B-ONE"}])
        doc = await _create(db, wh_id=warehouse["id"], lines=[(sku.sku, 4)])
        await _set_status(async_client, str(doc.id), "CONFIRMED")
        await _set_status(async_client, str(doc.id), "SHIPPED")

        me = await async_client.get("/api/v1/auth/me", headers=auth_headers)
        listing = await async_client.get(f"/api/v1/inventory-log?warehouse_id={warehouse['id']}")
        shipment_rows = [r for r in listing.json() if r["reference_type"] == "stock_out"]
        assert shipment_rows[0]["operator_id"] == me.json()["id"]


# ── A shipment the shelf cannot cover ────────────────────────────────────────


class TestShipmentMustBeCovered:
    async def test_an_uncatchable_shipment_is_refused_and_leaves_nothing_behind(
        self, async_client, db, warehouse, sku,
    ):
        """The route owns the transaction, so the deduction, its audit rows and the
        status change are one fact — a failure is invisible, not half-applied."""
        await _stock_on(db, warehouse, sku, [{"qty": "3", "batch_no": "B-ONE"}])
        doc = await _create(db, wh_id=warehouse["id"], lines=[(sku.sku, 1000)])
        await _set_status(async_client, str(doc.id), "CONFIRMED")

        ship = await _set_status(async_client, str(doc.id), "SHIPPED")
        assert ship.status_code == 422, ship.text
        assert "SKU" in ship.json()["error"]["message"]

        rows = await _rows(db, warehouse, sku)
        assert rows["B-ONE"].quantity == Decimal("3"), "the refusal deducted stock"
        assert await _logs(db, str(doc.id)) == [], "the refusal wrote audit rows"
        detail = await async_client.get(f"/api/v1/stock-out/{doc.id}")
        assert detail.json()["status"] == "CONFIRMED", "the refusal shipped the document"

    async def test_an_unregistered_sku_code_cannot_be_shipped(self, async_client, db, warehouse, sku):
        """Lines store a product code, batches are keyed by the SKU row: with no
        catalog row there is nothing to deduct, and the old answer was silence."""
        doc = await _create(db, wh_id=warehouse["id"], lines=[("SKU-NOT-IN-CATALOG", 2)])
        await _set_status(async_client, str(doc.id), "CONFIRMED")

        ship = await _set_status(async_client, str(doc.id), "SHIPPED")
        assert ship.status_code == 422, ship.text
        assert "SKU-NOT-IN-CATALOG" in ship.text, ship.text

    async def test_a_line_with_no_product_is_refused(self, async_client, db, warehouse, sku):
        await _stock_on(db, warehouse, sku, [{"qty": "5", "batch_no": "B-ONE"}])
        doc = await _create(db, wh_id=warehouse["id"], lines=[(sku.sku, 1), ("", 2)])
        await _set_status(async_client, str(doc.id), "CONFIRMED")

        ship = await _set_status(async_client, str(doc.id), "SHIPPED")
        assert ship.status_code == 422, ship.text
        assert "no sku" in ship.json()["error"]["message"], ship.text

    async def test_replaying_a_shipped_document_moves_the_shelf_once(
        self, async_client, db, warehouse, sku,
    ):
        """A repeat of the request that shipped a document is the same request.

        SHIPPED is terminal in the transition table, and the PDA queue replays its
        mutations on reconnect (``src/core/offline.py``), so the second send is
        what the server sees after a dropped response — a replay must be accepted
        as the shipment it already is, not answered as an illegal transition, and
        above all it must not deduct the batch a second time.
        """
        await _stock_on(db, warehouse, sku, [{"qty": "6", "batch_no": "B-ONE"}])
        doc = await _create(db, wh_id=warehouse["id"], lines=[(sku.sku, 6)])
        await _set_status(async_client, str(doc.id), "CONFIRMED")
        first = await _set_status(async_client, str(doc.id), "SHIPPED")
        assert first.status_code == 200, first.text

        second = await _set_status(async_client, str(doc.id), "SHIPPED")
        assert second.status_code == 200, second.text
        assert second.json()["status"] == "SHIPPED"
        rows = await _rows(db, warehouse, sku)
        assert rows["B-ONE"].quantity == Decimal("0"), "the replay deducted the batch twice"
        assert len(await _logs(db, str(doc.id))) == 1, "the replay wrote a second audit row"
