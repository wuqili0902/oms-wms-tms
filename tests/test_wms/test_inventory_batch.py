"""Batch/expiry handling on the inventory adjustment path.

The PDA scans a batch and (for food/cosmetics) an expiry date.  Two things had
to be true for that to reach the database:

* ``InventoryAdjust`` had to *declare* the fields — ``adjust_inventory()`` reads
  ``data["batch_no"]``, but the schema dropped the key on ``model_dump()``, so
  every PDA intake landed on the "DEFAULT" batch;
* ``InventoryResponse`` had to report them back, or no client could confirm the
  batch it just booked, and FEFO picking (which orders by ``expiry_date``) had
  nothing to order by.

Also pinned here: the optimistic-locking loop must *fail* when it never landed,
and a stock count of zero must be read as a count, not as a missing quantity.
"""

import re
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictException


@pytest.fixture
async def auth_client(async_client):
    """async_client with a bearer token, mirroring test_wms_router."""
    uname = f"batch_{uuid.uuid4().hex[:6]}"
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


async def _warehouse(client) -> str:
    resp = await client.post("/api/v1/warehouses", json={
        "code": f"WB-{uuid.uuid4().hex[:6]}", "name": "Batch WH", "address": "",
    })
    assert resp.status_code == 201
    return resp.json()["id"]


async def _location(client, wh_id: str) -> str:
    resp = await client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
        "zone": "A", "aisle": "1", "shelf": "1", "bin": "1",
    })
    assert resp.status_code == 201
    return resp.json()["id"]


# ══════════════════════════════════════════════════════════════════════════════
# Schema: the fields have to survive model_dump()
# ══════════════════════════════════════════════════════════════════════════════


class TestInventoryAdjustSchema:
    def test_batch_and_dates_survive_model_dump(self):
        from src.wms.schemas import InventoryAdjust

        data = InventoryAdjust(
            warehouse_id=str(uuid.uuid4()),
            location_id=str(uuid.uuid4()),
            sku="SKU-BATCH",
            quantity=5,
            batch_no="B-100",
            expiry_date="2027-03-31",
            manufacturing_date="2026-01-05",
        ).model_dump()

        assert data["batch_no"] == "B-100"
        assert data["expiry_date"] == date(2027, 3, 31)
        assert data["manufacturing_date"] == date(2026, 1, 5)

    def test_defaults_do_not_change_existing_callers(self):
        from src.wms.schemas import InventoryAdjust

        data = InventoryAdjust(
            warehouse_id=str(uuid.uuid4()), location_id=str(uuid.uuid4()),
            sku="SKU-OLD", quantity=-3,
        ).model_dump()

        assert data["batch_no"] is None
        assert data["expiry_date"] is None
        # adjust_inventory falls back to "DEFAULT" only when the key is absent;
        # the FEFO default has to stay FEFO.
        assert data["picking_strategy"] == "fefo"

    def test_bad_expiry_date_is_a_validation_error(self):
        """Typed as ``date``, not ``str``, so garbage 422s instead of 500ing.

        With ``str`` the service ran ``date.fromisoformat(...)`` and raised
        ValueError mid-request — an unhandled 500 for a mistyped field.
        """
        from pydantic import ValidationError

        from src.wms.schemas import InventoryAdjust

        with pytest.raises(ValidationError):
            InventoryAdjust(
                warehouse_id=str(uuid.uuid4()), location_id=str(uuid.uuid4()),
                sku="SKU-BAD", quantity=1, expiry_date="31/03/2027",
            )

    def test_unknown_picking_strategy_is_rejected(self):
        from pydantic import ValidationError

        from src.wms.schemas import InventoryAdjust

        with pytest.raises(ValidationError):
            InventoryAdjust(
                warehouse_id=str(uuid.uuid4()), location_id=str(uuid.uuid4()),
                sku="SKU-STRAT", quantity=-1, picking_strategy="lifo",
            )


# ══════════════════════════════════════════════════════════════════════════════
# HTTP path: what the PDA actually sees
# ══════════════════════════════════════════════════════════════════════════════


class TestAdjustEndpointBatch:
    @pytest.mark.asyncio
    async def test_scanned_batch_and_expiry_are_booked(self, auth_client):
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        resp = await auth_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": wh_id,
            "location_id": loc_id,
            "sku": "SKU-FEFO",
            "quantity": 40,
            "batch_no": "B-777",
            "expiry_date": "2027-03-31",
            "reason": "pda_stock_in",
        })

        assert resp.status_code == 200, resp.text
        body = resp.json()
        # An endpoint that accepts batch_no but answers without it is the same
        # silent drop in a different place: the operator cannot confirm what was
        # booked, and FEFO has no expiry to order by.
        assert body["batch_no"] == "B-777"
        assert body["expiry_date"] == "2027-03-31"

    @pytest.mark.asyncio
    async def test_second_adjustment_same_batch_merges(self, auth_client):
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        payload = {
            "warehouse_id": wh_id, "location_id": loc_id, "sku": "SKU-MERGE",
            "quantity": 7, "batch_no": "B-SAME",
        }
        first = await auth_client.post("/api/v1/warehouses/inventory/adjust", json=payload)
        second = await auth_client.post("/api/v1/warehouses/inventory/adjust", json=payload)

        assert first.json()["quantity"] == 7.0
        assert second.json()["quantity"] == 14.0
        assert second.json()["id"] == first.json()["id"]

    @pytest.mark.asyncio
    async def test_bad_expiry_date_answers_422_not_500(self, auth_client):
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        resp = await auth_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": wh_id, "location_id": loc_id, "sku": "SKU-BADDATE",
            "quantity": 1, "expiry_date": "tomorrow",
        })

        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_response_carries_batch_fields_for_existing_rows(self, auth_client):
        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)
        await auth_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": wh_id, "location_id": loc_id, "sku": "SKU-LIST",
            "quantity": 3, "batch_no": "B-LIST", "expiry_date": "2027-01-01",
        })

        resp = await auth_client.get(f"/api/v1/warehouses/inventory?warehouse_id={wh_id}")
        assert resp.status_code == 200
        row = next(r for r in resp.json() if r["sku"] == "SKU-LIST")
        assert row["batch_no"] == "B-LIST"
        assert row["expiry_date"] == "2027-01-01"


# ══════════════════════════════════════════════════════════════════════════════
# Stock count
# ══════════════════════════════════════════════════════════════════════════════


async def _seed(db: AsyncSession, *, wh_code: str, sku_code: str, qty: Decimal):
    from src.wms.models import SKU, Inventory, Location, Warehouse, WarehouseType

    wh = Warehouse(
        id=uuid.uuid4(), code=wh_code, name="Batch WH",
        address={}, warehouse_type=WarehouseType.CENTER,
    )
    loc = Location(id=uuid.uuid4(), warehouse_id=wh.id, code="L-BATCH")
    sku = SKU(id=uuid.uuid4(), sku=sku_code, name=sku_code)
    db.add_all([wh, loc, sku])
    await db.flush()

    inv = Inventory(
        id=uuid.uuid4(), warehouse_id=wh.id, location_id=loc.id, sku_id=sku.id,
        gtin="", batch_no="B001", quantity=qty, locked_qty=Decimal("0"),
        min_qty=Decimal("0"), max_qty=Decimal("0"),
    )
    db.add(inv)
    await db.flush()
    return wh, loc, sku, inv


class TestStockCount:
    @pytest.mark.asyncio
    async def test_counting_zero_is_a_count_not_a_missing_quantity(self, db_session):
        """`item.get("actual_qty") or item.get("actual_qty_count")` read 0 as absent."""
        from src.wms.service import adjust_stock_count

        wh, loc, _sku, inv = await _seed(
            db_session, wh_code="WH-ZERO", sku_code="SKU-ZERO", qty=Decimal("10")
        )

        await adjust_stock_count(db_session, {
            "warehouse_id": str(wh.id),
            "location_id": str(loc.id),
            "count_results": [{"sku_code": "SKU-ZERO", "actual_qty": 0}],
        })
        await db_session.refresh(inv)

        # 盘亏 to nothing is what the operator actually saw; rejecting it forced
        # them to record a fake 1 instead.
        assert inv.quantity == Decimal("0")

    @pytest.mark.asyncio
    async def test_warehouse_code_in_warehouse_id_is_looked_up_as_a_code(self, db_session):
        """The field held a code; `_to_uuid` returned None and the request was told it was missing an id."""
        from src.wms.service import adjust_stock_count

        _wh, loc, _sku, inv = await _seed(
            db_session, wh_code="WH-CODED", sku_code="SKU-CODED", qty=Decimal("4")
        )

        await adjust_stock_count(db_session, {
            "warehouse_id": "WH-CODED",
            "location_id": str(loc.id),
            "count_results": [{"sku": "SKU-CODED", "actual_qty": 6}],
        })
        await db_session.refresh(inv)

        assert inv.quantity == Decimal("6")

    @pytest.mark.asyncio
    async def test_unknown_warehouse_code_still_reports_not_found(self, db_session):
        from src.core.exceptions import NotFoundException
        from src.wms.service import adjust_stock_count

        _wh, loc, _sku, _inv = await _seed(
            db_session, wh_code="WH-OTHER", sku_code="SKU-OTHER", qty=Decimal("1")
        )

        with pytest.raises(NotFoundException, match="WH-MISSING"):
            await adjust_stock_count(db_session, {
                "warehouse_id": "WH-MISSING",
                "location_id": str(loc.id),
                "count_results": [{"sku": "SKU-OTHER", "actual_qty": 1}],
            })


# ══════════════════════════════════════════════════════════════════════════════
# Optimistic locking
# ══════════════════════════════════════════════════════════════════════════════


def _exec_result(obj=None, rowcount=1):
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    result.rowcount = rowcount
    return result


class TestOptimisticLocking:
    @pytest.mark.asyncio
    async def test_lost_update_raises_conflict_instead_of_reporting_success(self):
        """Every attempt lost the version race.

        Falling out of the retry loop returned the *pre-adjustment* row, so the
        caller got 200 and a quantity that had never been written — a lost
        update that looked like a success.
        """
        from src.wms.service import adjust_inventory

        inv = SimpleNamespace(
            id=uuid.uuid4(), quantity=Decimal("10"), locked_qty=Decimal("0"),
            version=3, expiry_date=None, manufacturing_date=None,
            received_at=None, created_at=None, updated_at=None,
            min_qty=Decimal("0"), max_qty=Decimal("0"),
            batch_no="B001", gtin="", warehouse_id=uuid.uuid4(),
            location_id=uuid.uuid4(), sku_id=uuid.uuid4(),
        )
        db = AsyncMock()
        lost_race = [_exec_result(obj=inv), _exec_result(rowcount=0)]
        db.execute.side_effect = [
            _exec_result(obj=SimpleNamespace(id=uuid.uuid4())),  # warehouse
            _exec_result(obj=SimpleNamespace(id=uuid.uuid4())),  # location
            _exec_result(obj=SimpleNamespace(id=uuid.uuid4(), sku="SKU-X", name="SKU-X")),  # sku
            *lost_race, *lost_race, *lost_race,
        ]

        with pytest.raises(ConflictException) as exc_info:
            await adjust_inventory(db, {
                "warehouse_id": str(uuid.uuid4()),
                "location_id": str(uuid.uuid4()),
                "sku": "SKU-X",
                "quantity": 5,
            })

        assert exc_info.value.status_code == 409
        assert exc_info.value.code == "CONFLICT"
        assert "not applied" in exc_info.value.message
        # Nothing was ever committed, so no half-written movement is left behind.
        db.commit.assert_not_awaited()
        assert db.rollback.await_count == 3

    @pytest.mark.asyncio
    async def test_conflict_maps_to_a_409_body(self, auth_client, monkeypatch):
        """The PDA has to be able to tell "rejected" from "booked"."""
        from src.wms import service as wms_service

        wh_id = await _warehouse(auth_client)
        loc_id = await _location(auth_client, wh_id)

        def _conflicting_adjust(*_args, **_kwargs):
            raise ConflictException(
                message="Inventory for SKU-X changed on every attempt; the adjustment was not applied"
            )

        monkeypatch.setattr(wms_service, "adjust_inventory", _conflicting_adjust)

        resp = await auth_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": wh_id, "location_id": loc_id, "sku": "SKU-X", "quantity": 5,
        })

        assert resp.status_code == 409
        # src/core/response.py wraps errors as {"success": false, "error": {...}}
        assert resp.json()["error"]["code"] == "CONFLICT"
        assert "not applied" in resp.json()["error"]["message"]

    def test_conflict_is_distinct_from_validation(self):
        from src.core.exceptions import AppException, ConflictException, ValidationException

        exc = ConflictException(message="boom")
        assert isinstance(exc, AppException)
        assert not isinstance(exc, ValidationException)
        assert re.match(r"^Error CONFLICT: boom$", str(exc))
