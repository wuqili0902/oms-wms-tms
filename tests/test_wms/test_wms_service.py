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


class TestVendorCRUD:
    @pytest.mark.asyncio
    async def test_create_vendor(self, db_session):
        v = await wms_service.create_vendor(db_session, {"code": "V-001", "name": "Test Vendor"})
        assert v["code"] == "V-001"
        assert v["name"] == "Test Vendor"

    @pytest.mark.asyncio
    async def test_create_duplicate_vendor(self, db_session):
        code = f"V-DUP-{uuid.uuid4().hex[:4]}"
        await wms_service.create_vendor(db_session, {"code": code, "name": "First"})
        with pytest.raises(ValidationException):
            await wms_service.create_vendor(db_session, {"code": code, "name": "Second"})

    @pytest.mark.asyncio
    async def test_get_vendor(self, db_session):
        v = await wms_service.create_vendor(db_session, {"code": "V-003", "name": "Get Me"})
        got = await wms_service.get_vendor(db_session, v["id"])
        assert got["code"] == "V-003"

    @pytest.mark.asyncio
    async def test_get_vendor_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.get_vendor(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_list_vendors(self, db_session):
        await wms_service.create_vendor(db_session, {"code": "V-L1", "name": "A"})
        await wms_service.create_vendor(db_session, {"code": "V-L2", "name": "B"})
        lst = await wms_service.list_vendors(db_session)
        assert len(lst) >= 2


class TestAddressCRUD:
    @pytest.mark.asyncio
    async def test_create_address(self, db_session):
        a = await wms_service.create_address(db_session, {
            "entity_type": "customer", "entity_id": str(uuid.uuid4()),
            "address_type": "shipping", "city": "Shanghai",
        })
        assert a["city"] == "Shanghai"
        assert a["entity_type"] == "customer"

    @pytest.mark.asyncio
    async def test_list_addresses_filter(self, db_session):
        eid = str(uuid.uuid4())
        await wms_service.create_address(db_session, {"entity_type": "vendor", "entity_id": eid, "address_type": "billing"})
        await wms_service.create_address(db_session, {"entity_type": "customer", "entity_id": eid, "address_type": "shipping"})
        filtered = await wms_service.list_addresses(db_session, entity_type="vendor")
        assert len(filtered) == 1


class TestUpdateLocation:
    @pytest.mark.asyncio
    async def test_update_location_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.update_location(db_session, str(uuid.uuid4()), str(uuid.uuid4()), {"zone": "X"})

    @pytest.mark.asyncio
    async def test_update_location_fields(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-UL", "name": "Upd Loc"})
        loc = await wms_service.create_location(db_session, wh["id"], {"zone": "A", "aisle": "1", "bin": "B1"})
        updated = await wms_service.update_location(db_session, wh["id"], loc["id"], {
            "shelf": "S5", "level": "L3", "type": "picking",
        })
        assert updated["shelf"] == "S5"
        assert updated["bin"] == "L3"
        assert updated["type"] == "picking"


class TestQueryInventory:
    @pytest.mark.asyncio
    async def test_query_all(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-QA", "name": "QAll"})
        loc = await wms_service.create_location(db_session, wh["id"], {"zone": "Z"})
        await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "Q-ALL", "quantity": "10",
        })
        result = await wms_service.query_inventory(db_session)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_query_wh_filter(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-QW", "name": "QWh"})
        loc = await wms_service.create_location(db_session, wh["id"], {"zone": "Z"})
        await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "Q-WH", "quantity": "5",
        })
        result = await wms_service.query_inventory(db_session, wh_id=wh["id"])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_query_sku_filter(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-QS", "name": "QSku"})
        loc = await wms_service.create_location(db_session, wh["id"], {"zone": "Z"})
        await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "Q-SKU1", "quantity": "7",
        })
        await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "Q-SKU2", "quantity": "3",
        })
        result = await wms_service.query_inventory(db_session, sku="Q-SKU1")
        assert len(result) == 1
        assert result[0]["sku"] == "Q-SKU1"


class TestAdjustInventoryBranches:
    @pytest.mark.asyncio
    async def test_adjust_with_expiry_date_on_existing(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-EXP", "name": "Exp"})
        loc = await wms_service.create_location(db_session, wh["id"], {"zone": "Z"})
        from datetime import datetime, timedelta, date

        await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "SKU-EXP", "quantity": "10",
        })
        future = (datetime.now() + timedelta(days=365)).date()
        await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "SKU-EXP", "quantity": "5",
            "expiry_date": future,
        })
        result = await wms_service.query_inventory(db_session, sku="SKU-EXP")
        assert float(result[0]["quantity"]) == 15


class TestQueryInventoryFilters:
    @pytest.mark.asyncio
    async def test_query_location_filter(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-QL", "name": "QLoc"})
        loc1 = await wms_service.create_location(db_session, wh["id"], {"zone": "Z1"})
        loc2 = await wms_service.create_location(db_session, wh["id"], {"zone": "Z2"})
        await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc1["id"], "sku": "QL-SKU", "quantity": "5",
        })
        await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc2["id"], "sku": "QL-SKU", "quantity": "3",
        })
        result = await wms_service.query_inventory(db_session, location_id=loc1["id"])
        assert len(result) == 1


class TestPickBatchesDefaultSort:
    @pytest.mark.asyncio
    async def test_custom_strategy_falls_to_default(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-PB", "name": "PickB"})
        loc = await wms_service.create_location(db_session, wh["id"], {"zone": "Z"})
        await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "PB-SKU", "quantity": "10",
        })
        result = await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"], "sku": "PB-SKU", "quantity": "-5",
            "picking_strategy": "custom",
        })
        assert float(result["quantity"]) >= 0


class TestPurchaseOrderCRUD:
    @pytest.mark.asyncio
    async def test_create_purchase_order(self, db_session):
        po = await wms_service.create_purchase_order(db_session, {"po_number": "PO-001"})
        assert po["po_number"] == "PO-001"
        assert po["status"] == "draft"

    @pytest.mark.asyncio
    async def test_create_po_with_lines(self, db_session):
        sku = await wms_service._get_or_create_sku(db_session, "SKU-PO")
        po = await wms_service.create_purchase_order(db_session, {
            "po_number": "PO-002",
            "lines": [{"sku_id": str(sku.id), "description": "Test item", "quantity": 10, "unit_price": "5.00"}],
        })
        assert float(po["total_amount"]) == 50.0

    @pytest.mark.asyncio
    async def test_get_purchase_order(self, db_session):
        po = await wms_service.create_purchase_order(db_session, {"po_number": "PO-003"})
        got = await wms_service.get_purchase_order(db_session, po["id"])
        assert got["po_number"] == "PO-003"

    @pytest.mark.asyncio
    async def test_get_po_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.get_purchase_order(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_list_purchase_orders(self, db_session):
        await wms_service.create_purchase_order(db_session, {"po_number": "PO-L1"})
        await wms_service.create_purchase_order(db_session, {"po_number": "PO-L2"})
        lst = await wms_service.list_purchase_orders(db_session)
        assert len(lst) >= 2


class TestInvoiceCRUD:
    @pytest.mark.asyncio
    async def test_create_invoice(self, db_session):
        inv = await wms_service.create_invoice(db_session, {
            "invoice_number": "INV-001", "entity_type": "purchase_order", "amount": "100.00",
        })
        assert inv["invoice_number"] == "INV-001"

    @pytest.mark.asyncio
    async def test_get_invoice(self, db_session):
        inv = await wms_service.create_invoice(db_session, {
            "invoice_number": "INV-002", "entity_type": "purchase_order", "amount": "200.00",
        })
        got = await wms_service.get_invoice(db_session, inv["id"])
        assert got["invoice_number"] == "INV-002"

    @pytest.mark.asyncio
    async def test_get_invoice_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.get_invoice(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_list_invoices(self, db_session):
        await wms_service.create_invoice(db_session, {"invoice_number": "INV-L1", "entity_type": "purchase_order", "amount": "10"})
        await wms_service.create_invoice(db_session, {"invoice_number": "INV-L2", "entity_type": "purchase_order", "amount": "20"})
        lst = await wms_service.list_invoices(db_session)
        assert len(lst) >= 2


class TestCreditMemoCRUD:
    """Credit memo creation, retrieval, listing."""

    @pytest.mark.asyncio
    async def test_create(self, db_session):
        cm = await wms_service.create_credit_memo(db_session, {
            "credit_memo_number": "CM-001", "entity_type": "invoice", "amount": "50",
        })
        assert cm["credit_memo_number"] == "CM-001"

    @pytest.mark.asyncio
    async def test_get(self, db_session):
        created = await wms_service.create_credit_memo(db_session, {
            "credit_memo_number": "CM-GET", "entity_type": "invoice", "amount": "30",
        })
        fetched = await wms_service.get_credit_memo(db_session, created["id"])
        assert fetched["credit_memo_number"] == "CM-GET"

    @pytest.mark.asyncio
    async def test_list(self, db_session):
        lst = await wms_service.list_credit_memos(db_session)
        assert isinstance(lst, list)


class TestWarehouseUpdateDelete:
    """Warehouse update and soft-delete."""

    @pytest.mark.asyncio
    async def test_update(self, db_session):
        created = await wms_service.create_warehouse(db_session, {"code": "WH-UPD", "name": "Before"})
        updated = await wms_service.update_warehouse(db_session, created["id"], {"name": "After"})
        assert updated.name == "After"

    @pytest.mark.asyncio
    async def test_delete(self, db_session):
        created = await wms_service.create_warehouse(db_session, {"code": "WH-DEL", "name": "Delete Me"})
        result = await wms_service.delete_warehouse(db_session, created["id"])
        assert result["is_active"] is False


class TestMovements:
    """Inventory movement listing."""

    @pytest.mark.asyncio
    async def test_list_empty(self, db_session):
        movements = await wms_service.list_movements(db_session)
        assert isinstance(movements, list)


class TestWmsEdgeCoverage:
    """Targeted tests for uncovered edge cases in wms/service.py."""

    @pytest.mark.asyncio
    async def test_adjust_inventory_manufacturing_date(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-MFG", "name": "Mfg WH"})
        loc = await wms_service.create_location(db_session, wh["id"], {"code": "LOC-MFG", "name": "Mfg"})
        await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"],
            "sku": "MFG-SKU", "quantity": 10,
        })
        from datetime import date
        inv2 = await wms_service.adjust_inventory(db_session, {
            "warehouse_id": wh["id"], "location_id": loc["id"],
            "sku": "MFG-SKU", "quantity": 5,
            "manufacturing_date": date(2026, 6, 15),
        })
        assert inv2["manufacturing_date"] == "2026-06-15"

    @pytest.mark.asyncio
    async def test_list_picking_waves_by_warehouse(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-PW", "name": "PW WH"})
        waves = await wms_service.list_picking_waves(db_session, wh_id=wh["id"])
        assert isinstance(waves, list)

    @pytest.mark.asyncio
    async def test_start_picking_wave_invalid_assignee(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-ASN", "name": "Asn WH"})
        wave = await wms_service.create_picking_wave(db_session, {
            "warehouse_id": wh["id"],
            "order_ids": [str(uuid.uuid4())],
        })
        started = await wms_service.start_picking(db_session, wave["id"], assignee="not-a-uuid")
        assert started["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_list_shipments_by_warehouse(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-SHP", "name": "Shp WH"})
        shipments = await wms_service.list_shipments(db_session, warehouse_id=wh["id"])
        assert isinstance(shipments, list)

    @pytest.mark.asyncio
    async def test_list_addresses_by_entity(self, db_session):
        addresses = await wms_service.list_addresses(db_session, entity_type="warehouse", entity_id=str(uuid.uuid4()))
        assert isinstance(addresses, list)

    @pytest.mark.asyncio
    async def test_create_invoice_with_lines(self, db_session):
        inv = await wms_service.create_invoice(db_session, {
            "invoice_number": "INV-LINE-001",
            "entity_type": "vendor",
            "lines": [{"description": "Line 1", "quantity": 2, "unit_price": "10.00"}],
        })
        assert inv["total_amount"] == "20.00"


class TestWmsModelRepr:
    """Covers __repr__ methods for all WMS models (wms/models.py)."""

    @pytest.mark.asyncio
    async def test_warehouse_repr(self):
        from src.wms.models import Warehouse
        w = Warehouse(code="WH-R", name="Repr WH")
        assert "WH-R" in repr(w)

    @pytest.mark.asyncio
    async def test_location_repr(self):
        from src.wms.models import Location
        loc = Location(code="LOC-R", zone="A", aisle="1", shelf="2")
        assert "LOC-R" in repr(loc)

    @pytest.mark.asyncio
    async def test_sku_repr(self):
        from src.wms.models import SKU
        s = SKU(sku="SKU-REPR")
        assert "SKU-REPR" in repr(s)

    @pytest.mark.asyncio
    async def test_inventory_repr(self):
        import uuid
        from src.wms.models import Inventory
        inv = Inventory(sku_id=uuid.uuid4(), batch_no="B001", quantity=10)
        assert "B001" in repr(inv)

    @pytest.mark.asyncio
    async def test_inventory_log_repr(self):
        import uuid
        from src.wms.models import InventoryLog, InventoryChangeType
        log = InventoryLog(inventory_id=uuid.uuid4(), change_type=InventoryChangeType.INBOUND, quantity_change=5)
        assert "inbound" in repr(log)

    @pytest.mark.asyncio
    async def test_reference_entity_repr(self):
        from src.wms.models import ReferenceEntity
        ref = ReferenceEntity(reference_type="order", reference_id="ORD-001")
        assert "order" in repr(ref)

    @pytest.mark.asyncio
    async def test_stock_movement_repr(self):
        import uuid
        from src.wms.models import StockMovement, StockMovementType
        sm = StockMovement(
            source_warehouse_id=uuid.uuid4(), target_warehouse_id=uuid.uuid4(),
            sku_id=uuid.uuid4(), gtin="",
            movement_type=StockMovementType.TRANSFER, quantity=20,
        )
        assert "transfer" in repr(sm)

    @pytest.mark.asyncio
    async def test_picking_wave_repr(self):
        from src.wms.models import PickingWave
        pw = PickingWave(code="WAVE-R", status="pending", total_items=3)
        assert "WAVE-R" in repr(pw)

    @pytest.mark.asyncio
    async def test_packing_record_repr(self):
        import uuid
        from src.wms.models import PackingRecord
        pr = PackingRecord(picking_wave_id=uuid.uuid4(), box_count=3)
        assert "PackingRecord" in repr(pr)

    @pytest.mark.asyncio
    async def test_shipment_repr(self):
        import uuid
        from src.wms.models import Shipment
        sh = Shipment(order_id=uuid.uuid4(), warehouse_id=uuid.uuid4(), tracking_number="SHP-R")
        assert "SHP-R" in repr(sh)

    @pytest.mark.asyncio
    async def test_vendor_repr(self):
        from src.wms.models import Vendor
        v = Vendor(code="VEN-R", name="Repr Vendor")
        assert "VEN-R" in repr(v)

    @pytest.mark.asyncio
    async def test_address_repr(self):
        from src.wms.models import Address
        a = Address(entity_type="warehouse", city="Beijing")
        assert "warehouse" in repr(a)

    @pytest.mark.asyncio
    async def test_purchase_order_repr(self):
        from src.wms.models import PurchaseOrder
        po = PurchaseOrder(po_number="PO-R")
        assert "PO-R" in repr(po)

    @pytest.mark.asyncio
    async def test_purchase_order_line_repr(self):
        import uuid
        from src.wms.models import PurchaseOrderLine
        pol = PurchaseOrderLine(purchase_order_id=uuid.uuid4(), description="POL R")
        assert "POL R" in repr(pol)

    @pytest.mark.asyncio
    async def test_invoice_repr(self):
        from src.wms.models import Invoice
        i = Invoice(invoice_number="INV-R")
        assert "INV-R" in repr(i)

    @pytest.mark.asyncio
    async def test_invoice_line_repr(self):
        import uuid
        from src.wms.models import InvoiceLine
        il = InvoiceLine(invoice_id=uuid.uuid4(), description="Line R")
        assert "Line R" in repr(il)

    @pytest.mark.asyncio
    async def test_credit_memo_repr(self):
        from src.wms.models import CreditMemo
        cm = CreditMemo(credit_memo_number="CM-R")
        assert "CM-R" in repr(cm)

    @pytest.mark.asyncio
    async def test_credit_memo_line_repr(self):
        import uuid
        from src.wms.models import CreditMemoLine
        cml = CreditMemoLine(credit_memo_id=uuid.uuid4(), description="CM Line R")
        assert "CM Line R" in repr(cml)

    @pytest.mark.asyncio
    async def test_create_credit_memo_with_lines(self, db_session):
        cm = await wms_service.create_credit_memo(db_session, {
            "credit_memo_number": "CM-LINE-001",
            "entity_type": "vendor",
            "lines": [{"description": "CM Line", "quantity": 3, "unit_price": "15.00"}],
        })
        assert cm["total_amount"] == "45.00"
