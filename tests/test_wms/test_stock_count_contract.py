"""A stock count is a measurement, and the API has to be able to read one.

``POST /api/v1/warehouses/inventory/count/submit`` (and the ``/adjust-stock-count``
route the handheld calls) took ``data: dict`` and passed it to
``wms_service.adjust_stock_count``, which picked the fields out with ``.get``:
the warehouse under ``warehouse_id`` *or* ``source_warehouse_code``, the location
under ``location_id`` *or* ``target_location_id``, the lines under
``count_results``, each line's product under ``sku`` *or* ``sku_code``, its count
under ``actual_qty`` *or* ``actual_qty_count``.  A quantity arriving under a key
the service does not know (``counted_qty``) reached ``Decimal(str(None))`` —
inside the handler, so the caller was told the server broke.  ``count_results: []``
ran the loop over nothing and answered success.

The body is typed now (``src/wms/schemas.py:StockCountSubmit``).  Every spelling
above is an alias of the same field, an unparsable count is a 422 that names the
line, and the ledger row a count writes is signed the way the column is
documented, so the ledger sums to the shelf.
"""

import uuid as uuid_mod
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.wms.models import SKU, Inventory


@pytest.fixture
async def auth_headers(async_client):
    uname = f"cnt_{uuid_mod.uuid4().hex[:8]}"
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
    """The session the app runs on, so the shelf the route reads is this one."""
    return async_client._shared_session


@pytest.fixture
async def warehouse(async_client):
    r = await async_client.post("/api/v1/warehouses", json={
        "code": f"WH-CNT-{uuid_mod.uuid4().hex[:8]}", "name": "Count WH", "type": "center",
    })
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def location(async_client, warehouse):
    r = await async_client.post(f"/api/v1/warehouses/{warehouse['id']}/locations", json={
        "zone": "A", "aisle": "1", "shelf": "1", "bin": "1",
    })
    assert r.status_code == 201, r.text
    return r.json()


async def _stock(db, warehouse, location, code, qty) -> Inventory:
    """Put a SKU with ``qty`` on the shelf (flushed, not committed).

    Flushing is the point: the route commits this session, and committed test
    data survives the savepoint the suite wraps each test in.  The codes are
    unique per test, so what does leak from a count that succeeds is its own
    shelf row and nothing another test depends on.
    """
    sku = await db.scalar(select(SKU).where(SKU.sku == code))
    if sku is None:
        sku = SKU(id=uuid_mod.uuid4(), sku=code, name=code, gtin="")
        db.add(sku)
        await db.flush()
    row = Inventory(
        id=uuid_mod.uuid4(), warehouse_id=uuid_mod.UUID(warehouse["id"]),
        location_id=uuid_mod.UUID(location["id"]), sku_id=sku.id,
        gtin="", batch_no="COUNT-BASE", quantity=Decimal(str(qty)), locked_qty=Decimal("0"),
        received_at=datetime.now(UTC).replace(tzinfo=None), version=0,
    )
    db.add(row)
    await db.flush()
    return row


async def _count(async_client, body):
    return await async_client.post("/api/v1/warehouses/inventory/count/submit", json=body)


async def _ledger(async_client, warehouse):
    r = await async_client.get(f"/api/v1/inventory-log?warehouse_id={warehouse['id']}")
    assert r.status_code == 200, r.text
    return [row for row in r.json() if row["reference_type"] == "stock_count"]


# ── The shapes callers send ──────────────────────────────────────────────────


class TestCountShapes:
    async def test_the_documented_shape_is_accepted(self, async_client, db, warehouse, location):
        """``docs/functional-test-plan.md`` 4.7.5."""
        code = f"SKU-CNT-{uuid_mod.uuid4().hex[:6]}"
        await _stock(db, warehouse, location, code, "100")
        resp = await _count(async_client, {
            "warehouse_id": warehouse["id"], "location_id": location["id"],
            "count_results": [{"sku": code, "actual_qty": 95}],
        })
        assert resp.status_code == 200, resp.text

    async def test_the_shape_the_handheld_sends_is_accepted(self, async_client, db, warehouse, location):
        """Codes and the PDA's own key names: ``source_warehouse_code``,
        ``target_location_id``, ``results``, ``sku_code``, ``actual_qty_count``."""
        code = f"SKU-PDA-{uuid_mod.uuid4().hex[:6]}"
        await _stock(db, warehouse, location, code, "40")
        resp = await _count(async_client, {
            "source_warehouse_code": warehouse["code"], "target_location_id": location["id"],
            "results": [{"sku_code": code, "actual_qty_count": 41}],
        })
        assert resp.status_code == 200, resp.text

    async def test_the_envelope_shape_is_accepted(self, async_client, db, warehouse, location):
        code = f"SKU-ENV-{uuid_mod.uuid4().hex[:6]}"
        await _stock(db, warehouse, location, code, "10")
        resp = await _count(async_client, {"data": {
            "warehouse_id": warehouse["id"], "location_id": location["id"],
            "count_results": [{"sku": code, "actual_qty": 10}],
        }})
        assert resp.status_code == 200, resp.text

    async def test_the_other_stock_count_route_takes_the_same_body(self, async_client, db, warehouse, location):
        """``/adjust-stock-count`` is the route ``mobile/src/api/client.js`` calls;
        it used to be the same ``dict`` body reached by a different docstring."""
        code = f"SKU-MOB-{uuid_mod.uuid4().hex[:6]}"
        await _stock(db, warehouse, location, code, "12")
        resp = await async_client.post("/api/v1/warehouses/inventory/adjust-stock-count", json={
            "warehouse_id": warehouse["id"], "location_id": location["id"],
            "count_results": [{"sku": code, "actual_qty": 13}],
        })
        assert resp.status_code == 200, resp.text


# ── What the body refuses ────────────────────────────────────────────────────


class TestCountRefusals:
    async def test_a_count_that_is_not_a_number_is_a_422_not_a_500(self, async_client, db, warehouse, location):
        code = f"SKU-BAD-{uuid_mod.uuid4().hex[:6]}"
        await _stock(db, warehouse, location, code, "5")
        resp = await _count(async_client, {
            "warehouse_id": warehouse["id"], "location_id": location["id"],
            "count_results": [{"sku": code, "actual_qty": "九十五"}],
        })
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["success"] is False and body["error"]["code"] == "VALIDATION_ERROR", resp.text
        assert any("actual_qty" in e["field"] for e in body["errors"]), resp.text

    async def test_a_count_under_zero_is_refused(self, async_client, db, warehouse, location):
        code = f"SKU-NEG-{uuid_mod.uuid4().hex[:6]}"
        await _stock(db, warehouse, location, code, "5")
        resp = await _count(async_client, {
            "warehouse_id": warehouse["id"], "location_id": location["id"],
            "count_results": [{"sku": code, "actual_qty": -3}],
        })
        assert resp.status_code == 422, resp.text

    async def test_a_key_nothing_read_is_refused_by_name(self, async_client, db, warehouse, location):
        """``counted_qty`` was dropped silently, so an operator who sent the
        count under that key was told the count succeeded and read nothing."""
        code = f"SKU-KEY-{uuid_mod.uuid4().hex[:6]}"
        await _stock(db, warehouse, location, code, "5")
        resp = await _count(async_client, {
            "warehouse_id": warehouse["id"], "location_id": location["id"],
            "count_results": [{"sku": code, "counted_qty": 5}],
        })
        assert resp.status_code == 422, resp.text
        assert any("counted_qty" in e["field"] for e in resp.json()["errors"]), resp.text

    async def test_a_count_with_no_lines_is_refused(self, async_client, warehouse, location):
        resp = await _count(async_client, {
            "warehouse_id": warehouse["id"], "location_id": location["id"], "count_results": [],
        })
        assert resp.status_code == 422, resp.text
        assert any("count_results" in e["field"] for e in resp.json()["errors"]), resp.text

    @pytest.mark.parametrize("key", ["warehouse_id", "source_warehouse_code"])
    async def test_the_warehouse_is_required(self, async_client, warehouse, location, key):
        resp = await _count(async_client, {
            "location_id": location["id"], key: "NOT-A-WAREHOUSE",
            "count_results": [{"sku": "SKU-X", "actual_qty": 1}],
        })
        assert resp.status_code == 404, resp.text

    async def test_the_location_is_required(self, async_client, warehouse):
        resp = await _count(async_client, {
            "warehouse_id": warehouse["id"],
            "count_results": [{"sku": "SKU-X", "actual_qty": 1}],
        })
        assert resp.status_code == 422, resp.text
        assert any("location_id" in e["field"] for e in resp.json()["errors"]), resp.text


# ── What a count does to the shelf, and what it says about it ────────────────


class TestCountResults:
    async def test_counting_zero_empties_the_shelf_and_says_so(self, async_client, db, warehouse, location):
        """Zero is a counted quantity, not a missing one: 盘亏到零 has to reach
        the comparison as 0, and its ledger row is an outbound row."""
        code = f"SKU-ZERO-{uuid_mod.uuid4().hex[:6]}"
        row = await _stock(db, warehouse, location, code, "8")
        resp = await _count(async_client, {
            "warehouse_id": warehouse["id"], "location_id": location["id"],
            "count_results": [{"sku": code, "actual_qty": 0}],
        })
        assert resp.status_code == 200, resp.text
        await db.refresh(row)
        assert row.quantity == Decimal("0"), "counting a SKU as zero left its stock where it was"

        logs = [r for r in await _ledger(async_client, warehouse) if r["sku"] == code]
        assert logs, "the count wrote no ledger row"
        assert logs[0]["type"] == "ADJUSTMENT_OUT"
        assert Decimal(logs[0]["quantity_change"]) == Decimal("-8"), (
            "a counted loss is signed as a loss: StockInventoryLog documents "
            "+ve = in, -ve = out"
        )

    async def test_a_surplus_lands_and_is_recorded_as_an_inbound_row(self, async_client, db, warehouse, location):
        code = f"SKU-FIND-{uuid_mod.uuid4().hex[:6]}"
        row = await _stock(db, warehouse, location, code, "5")
        resp = await _count(async_client, {
            "warehouse_id": warehouse["id"], "location_id": location["id"],
            "count_results": [{"sku": code, "actual_qty": 9}],
        })
        assert resp.status_code == 200, resp.text
        await db.refresh(row)
        assert row.quantity == Decimal("9")

        logs = [r for r in await _ledger(async_client, warehouse) if r["sku"] == code]
        assert logs[0]["type"] == "ADJUSTMENT_IN"
        assert Decimal(logs[0]["quantity_change"]) == Decimal("4")

    async def test_a_count_that_agrees_writes_nothing(self, async_client, db, warehouse, location):
        code = f"SKU-AGREE-{uuid_mod.uuid4().hex[:6]}"
        await _stock(db, warehouse, location, code, "7")
        resp = await _count(async_client, {
            "warehouse_id": warehouse["id"], "location_id": location["id"],
            "count_results": [{"sku": code, "actual_qty": 7}],
        })
        assert resp.status_code == 200, resp.text
        assert [r for r in await _ledger(async_client, warehouse) if r["sku"] == code] == [], (
            "a count that matched the shelf wrote an adjustment for it"
        )

    async def test_a_refused_count_leaves_the_shelf_as_it_was(self, async_client, db, warehouse, location):
        """The service's own guard (``盘亏`` cannot take out more than is there) is
        reached by a quantity the body cannot express: a count is a measured
        quantity, so it is never negative, and the refusal happens at validation
        — before the shelf, its rows and its log are touched."""
        code = f"SKU-OVER-{uuid_mod.uuid4().hex[:6]}"
        row = await _stock(db, warehouse, location, code, "6")
        resp = await _count(async_client, {
            "warehouse_id": warehouse["id"], "location_id": location["id"],
            "count_results": [{"sku": code, "actual_qty": -1}],
        })
        assert resp.status_code == 422, resp.text
        await db.refresh(row)
        assert row.quantity == Decimal("6"), "a refused count changed the shelf"
