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


class TestPickingExecution:
    """Picking wave execution: start → complete."""

    @pytest.mark.asyncio
    async def test_start_picking(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SP", "name": "StartPick"})
        wave = await wms_service.create_picking_wave(db_session, {"warehouse_id": wh["id"], "order_ids": ["o1"]})
        result = await wms_service.start_picking(db_session, wave["id"])
        assert result["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_start_already_in_progress(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SP2", "name": "StartPick2"})
        wave = await wms_service.create_picking_wave(db_session, {"warehouse_id": wh["id"], "order_ids": ["o1"]})
        await wms_service.start_picking(db_session, wave["id"])
        with pytest.raises(ValidationException):
            await wms_service.start_picking(db_session, wave["id"])

    @pytest.mark.asyncio
    async def test_complete_picking(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-CP", "name": "CompPick"})
        wave = await wms_service.create_picking_wave(db_session, {"warehouse_id": wh["id"], "order_ids": ["o1"]})
        await wms_service.start_picking(db_session, wave["id"])
        result = await wms_service.complete_picking(db_session, wave["id"])
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_complete_without_start(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-CP2", "name": "CompPick2"})
        wave = await wms_service.create_picking_wave(db_session, {"warehouse_id": wh["id"], "order_ids": ["o1"]})
        with pytest.raises(ValidationException):
            await wms_service.complete_picking(db_session, wave["id"])


class TestPacking:
    """Packing after completed picking."""

    @pytest.mark.asyncio
    async def test_create_packing(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-PK", "name": "Pack"})
        wave = await wms_service.create_picking_wave(db_session, {"warehouse_id": wh["id"], "order_ids": ["o1"]})
        await wms_service.start_picking(db_session, wave["id"])
        await wms_service.complete_picking(db_session, wave["id"])
        record = await wms_service.create_packing(db_session, {"picking_wave_id": wave["id"], "box_count": 3})
        assert record["box_count"] == 3

    @pytest.mark.asyncio
    async def test_pack_before_complete(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-PK2", "name": "Pack2"})
        wave = await wms_service.create_picking_wave(db_session, {"warehouse_id": wh["id"], "order_ids": ["o1"]})
        with pytest.raises(ValidationException, match="Only completed"):
            await wms_service.create_packing(db_session, {"picking_wave_id": wave["id"]})


class TestShipping:
    """Shipment creation and tracking."""

    @pytest.mark.asyncio
    async def test_create_shipment(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SH", "name": "Ship"})
        shipment = await wms_service.create_shipment(db_session, {
            "order_id": str(uuid.uuid4()), "warehouse_id": wh["id"],
        })
        assert "tracking_number" in shipment

    @pytest.mark.asyncio
    async def test_mark_shipped(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SH2", "name": "Ship2"})
        shipment = await wms_service.create_shipment(db_session, {
            "order_id": str(uuid.uuid4()), "warehouse_id": wh["id"],
        })
        result = await wms_service.mark_shipped(db_session, shipment["id"], "TRK-123", "FedEx")
        assert result["status"] == "shipped"
        assert result["tracking_number"] == "TRK-123"

    @pytest.mark.asyncio
    async def test_list_shipments(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SH3", "name": "Ship3"})
        await wms_service.create_shipment(db_session, {"order_id": str(uuid.uuid4()), "warehouse_id": wh["id"]})
        await wms_service.create_shipment(db_session, {"order_id": str(uuid.uuid4()), "warehouse_id": wh["id"]})
        shipments = await wms_service.list_shipments(db_session)
        assert len(shipments) >= 2

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, db_session):
        """End-to-end: create wave → start → complete → pack → ship."""
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-E2E", "name": "E2E"})
        order_id = str(uuid.uuid4())

        # Create wave
        wave = await wms_service.create_picking_wave(db_session, {
            "warehouse_id": wh["id"], "order_ids": [order_id],
        })
        assert wave["status"] == "pending"

        # Start picking
        w = await wms_service.start_picking(db_session, wave["id"])
        assert w["status"] == "in_progress"

        # Complete picking
        w = await wms_service.complete_picking(db_session, wave["id"])
        assert w["status"] == "completed"

        # Pack
        pack = await wms_service.create_packing(db_session, {"picking_wave_id": wave["id"], "box_count": 2})
        assert pack["box_count"] == 2

        # Ship
        shipment = await wms_service.create_shipment(db_session, {
            "order_id": order_id, "warehouse_id": wh["id"],
            "packing_record_id": pack["id"], "tracking_number": "ZTO-999",
        })
        shipped = await wms_service.mark_shipped(db_session, shipment["id"], carrier="ZTO")
        assert shipped["status"] == "shipped"
