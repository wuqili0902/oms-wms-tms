"""Direct service-level tests for WMS business logic.

Tests all untested paths in src/wms/service.py using the db_session fixture.
"""
import uuid

import pytest

from src.core.exceptions import NotFoundException, ValidationException
from src.wms import service as wms_service
from src.wms.models import WarehouseType


class TestWarehouseCRUD:
    """Warehouse create, read, list."""

    @pytest.mark.asyncio
    async def test_create_warehouse(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-001", "name": "Main Warehouse"})
        assert wh["code"] == "WH-001"
        assert wh["name"] == "Main Warehouse"
        assert wh["is_active"] is True

    @pytest.mark.asyncio
    async def test_create_warehouse_with_type(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-002", "name": "Regional", "type": "regional"})
        assert wh["type"] == "regional"

    @pytest.mark.asyncio
    async def test_create_duplicate_code(self, db_session):
        await wms_service.create_warehouse(db_session, {"code": "WH-DUP", "name": "First"})
        with pytest.raises(ValidationException, match="already exists"):
            await wms_service.create_warehouse(db_session, {"code": "WH-DUP", "name": "Second"})

    @pytest.mark.asyncio
    async def test_get_warehouse(self, db_session):
        created = await wms_service.create_warehouse(db_session, {"code": "WH-GET", "name": "Get Test"})
        fetched = await wms_service.get_warehouse(db_session, created["id"])
        assert fetched["code"] == "WH-GET"

    @pytest.mark.asyncio
    async def test_get_nonexistent_warehouse(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.get_warehouse(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_list_warehouses(self, db_session):
        await wms_service.create_warehouse(db_session, {"code": "WH-L1", "name": "List 1"})
        await wms_service.create_warehouse(db_session, {"code": "WH-L2", "name": "List 2"})
        warehouses = await wms_service.list_warehouses(db_session)
        assert len(warehouses) >= 2


class TestLocationCRUD:
    """Location create, list, get."""

    @pytest.mark.asyncio
    async def test_create_location(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-LOC", "name": "Loc WH"})
        loc = await wms_service.create_location(db_session, wh["id"], {"zone": "A", "aisle": "01", "bin": "01"})
        assert "location_code" in loc
        assert loc["zone"] == "A"

    @pytest.mark.asyncio
    async def test_create_location_invalid_warehouse(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.create_location(db_session, str(uuid.uuid4()), {"zone": "A"})

    @pytest.mark.asyncio
    async def test_list_locations(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-LL", "name": "List Loc"})
        await wms_service.create_location(db_session, wh["id"], {"zone": "B", "aisle": "02", "bin": "02"})
        locs = await wms_service.list_locations(db_session)
        assert len(locs) >= 1

    @pytest.mark.asyncio
    async def test_list_locations_filter_by_warehouse(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-LF", "name": "Filter"})
        await wms_service.create_location(db_session, wh["id"], {"zone": "C"})
        locs = await wms_service.list_locations(db_session, wh_id=wh["id"])
        assert len(locs) >= 1

    @pytest.mark.asyncio
    async def test_get_location(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-GL", "name": "Get Loc"})
        created = await wms_service.create_location(db_session, wh["id"], {"zone": "D"})
        fetched = await wms_service.get_location(db_session, created["id"])
        assert fetched["zone"] == "D"

    @pytest.mark.asyncio
    async def test_get_nonexistent_location(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.get_location(db_session, str(uuid.uuid4()))


class TestSKUHelper:
    """Test _get_or_create_sku helper."""

    @pytest.mark.asyncio
    async def test_creates_new_sku(self, db_session):
        sku = await wms_service._get_or_create_sku(db_session, "SKU-NEW")
        assert sku.sku == "SKU-NEW"

    @pytest.mark.asyncio
    async def test_returns_existing_sku(self, db_session):
        s1 = await wms_service._get_or_create_sku(db_session, "SKU-EXIST")
        s2 = await wms_service._get_or_create_sku(db_session, "SKU-EXIST")
        assert s1.id == s2.id


class TestInventoryAdjust:
    """Inventory adjustments — in, out, errors."""

    @pytest.mark.asyncio
    async def test_adjust_positive_adds_stock(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-INV", "name": "Inv"})
        loc = await wms_service.create_location(db_session, wh["id"], {"zone": "Z1"})
        result = await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "SKU-ADD", "quantity": "100",
        })
        assert float(result["quantity"]) == 100

    @pytest.mark.asyncio
    async def test_adjust_positive_adds_to_existing(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-ADD2", "name": "Add2"})
        loc = await wms_service.create_location(db_session, wh["id"], {"zone": "Z2"})
        await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "SKU-CUM", "quantity": "50",
        })
        result = await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "SKU-CUM", "quantity": "30",
        })
        assert float(result["quantity"]) == 80

    @pytest.mark.asyncio
    async def test_adjust_negative_reduces_stock(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SUB", "name": "Sub"})
        loc = await wms_service.create_location(db_session, wh["id"], {"zone": "Z3"})
        await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "SKU-SUB", "quantity": "100",
        })
        result = await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "SKU-SUB", "quantity": "-30",
        })
        assert float(result["quantity"]) == 70

    @pytest.mark.asyncio
    async def test_adjust_insufficient_raises(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-NEG", "name": "Neg"})
        loc = await wms_service.create_location(db_session, wh["id"], {"zone": "Z4"})
        with pytest.raises(ValidationException, match="Insufficient"):
            await wms_service.adjust_inventory(db_session, {
                "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "SKU-NOEXIST", "quantity": "-10",
            })

    @pytest.mark.asyncio
    async def test_adjust_invalid_warehouse(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.adjust_inventory(db_session, {
                "warehouse_id": str(uuid.uuid4()), "location_id": str(uuid.uuid4()), "sku": "SKU", "quantity": "10",
            })

    @pytest.mark.asyncio
    async def test_adjust_invalid_location(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-LERR", "name": "LocErr"})
        with pytest.raises(NotFoundException):
            await wms_service.adjust_inventory(db_session, {
                "warehouse_id": wh["id"], "location_id": str(uuid.uuid4()), "sku": "SKU", "quantity": "10",
            })


class TestPickingWave:
    """Picking wave creation and listing."""

    @pytest.mark.asyncio
    async def test_create_picking_wave(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-PW", "name": "Wave"})
        wave = await wms_service.create_picking_wave(db_session, {
            "warehouse_id": wh["id"], "order_ids": ["order-1"],
        })
        assert "wave_no" in wave

    @pytest.mark.asyncio
    async def test_create_picking_wave_invalid_warehouse(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.create_picking_wave(db_session, {
                "warehouse_id": str(uuid.uuid4()), "order_ids": ["order-1"],
            })

    @pytest.mark.asyncio
    async def test_create_picking_wave_no_orders(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-PWO", "name": "NoOrders"})
        with pytest.raises(ValidationException, match="At least one order"):
            await wms_service.create_picking_wave(db_session, {
                "warehouse_id": wh["id"], "order_ids": [],
            })

    @pytest.mark.asyncio
    async def test_list_picking_waves(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-PL", "name": "WaveList"})
        await wms_service.create_picking_wave(db_session, {"warehouse_id": wh["id"], "order_ids": ["o1"]})
        await wms_service.create_picking_wave(db_session, {"warehouse_id": wh["id"], "order_ids": ["o2"]})
        waves = await wms_service.list_picking_waves(db_session)
        assert len(waves) >= 2
