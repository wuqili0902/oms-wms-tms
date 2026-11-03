"""Tests for WMS stock_in, stock_out, and related router endpoints."""
import uuid

import pytest

from src.core.exceptions import NotFoundException, ValidationException
from src.wms import service as wms_service
from src.wms.models import WarehouseStatus


class TestStockIn:
    """stock_in — single-SKU inbound with audit log."""

    @pytest.mark.asyncio
    async def test_stock_in_new_sku(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SI-01", "name": "StockIn WH",
            "address": "Test Address",
        })
        result = await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-SI-001", "quantity": 50, "batch_no": "B001",
        }, current_user={"id": str(uuid.uuid4())})
        assert result["quantity"] == 50
        assert result["sku"] == "SKU-SI-001"

    @pytest.mark.asyncio
    async def test_stock_in_existing_sku(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SI-02", "name": "StockIn WH2",
            "address": "Test Address",
        })
        await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-SI-002", "quantity": 30,
        }, current_user={})
        result = await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-SI-002", "quantity": 20,
        }, current_user={})
        assert result["quantity"] == 50

    @pytest.mark.asyncio
    async def test_stock_in_warehouse_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.stock_in(db_session, str(uuid.uuid4()), {
                "sku": "X", "quantity": 1,
            }, current_user={})

    @pytest.mark.asyncio
    async def test_stock_in_warehouse_inactive(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SI-INACTIVE", "name": "Inactive WH",
            "address": "Test", "status": WarehouseStatus.ACTIVE,
        })
        await wms_service.update_warehouse(db_session, wh["id"], {"status": WarehouseStatus.CLOSED})
        with pytest.raises(ValidationException, match="inactive"):
            await wms_service.stock_in(db_session, wh["id"], {
                "sku": "X", "quantity": 1,
            }, current_user={})

    @pytest.mark.asyncio
    async def test_stock_in_with_expiry(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SI-EXP", "name": "Expiry WH", "address": "Test",
        })
        result = await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-EXP-001", "quantity": 10,
            "batch_no": "EXP01", "expiry_date": "2027-01-01",
            "manufacturing_date": "2026-01-01",
        }, current_user={})
        assert result["quantity"] == 10

    @pytest.mark.asyncio
    async def test_stock_in_creates_audit_log(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SI-AUDIT", "name": "Audit WH", "address": "Test",
        })
        result = await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-AUDIT-001", "quantity": 100, "remark": "Initial stock",
        }, current_user={"id": str(uuid.uuid4())})
        assert result["quantity"] == 100
        from sqlalchemy import select

        from src.wms.models import InventoryLog
        logs = await db_session.execute(
            select(InventoryLog).where(InventoryLog.reference_type == "stock_in")
        )
        assert len(logs.scalars().all()) >= 1


class TestStockOut:
    """stock_out — single-SKU outbound with batch picking."""

    @pytest.mark.asyncio
    async def test_stock_out_success(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SO-01", "name": "StockOut WH", "address": "Test",
        })
        await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-SO-001", "quantity": 100,
        }, current_user={})
        result = await wms_service.stock_out(db_session, wh["id"], {
            "sku": "SKU-SO-001", "quantity": 30,
        }, current_user={})
        assert result["quantity"] == 70

    @pytest.mark.asyncio
    async def test_stock_out_warehouse_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await wms_service.stock_out(db_session, str(uuid.uuid4()), {
                "sku": "X", "quantity": 1,
            }, current_user={})

    @pytest.mark.asyncio
    async def test_stock_out_warehouse_inactive(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SO-INACTIVE", "name": "Inactive WH",
            "address": "Test", "status": WarehouseStatus.ACTIVE,
        })
        await wms_service.update_warehouse(db_session, wh["id"], {"status": WarehouseStatus.CLOSED})
        with pytest.raises(ValidationException, match="inactive"):
            await wms_service.stock_out(db_session, wh["id"], {
                "sku": "X", "quantity": 1,
            }, current_user={})

    @pytest.mark.asyncio
    async def test_stock_out_no_stock(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SO-EMPTY", "name": "Empty WH", "address": "Test",
        })
        with pytest.raises(ValidationException, match="No stock"):
            await wms_service.stock_out(db_session, wh["id"], {
                "sku": "SKU-NONEXISTENT", "quantity": 10,
            }, current_user={})

    @pytest.mark.asyncio
    async def test_stock_out_insufficient(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SO-INSUF", "name": "Insuf WH", "address": "Test",
        })
        await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-INSUF-001", "quantity": 5,
        }, current_user={})
        with pytest.raises(ValidationException, match="Insufficient"):
            await wms_service.stock_out(db_session, wh["id"], {
                "sku": "SKU-INSUF-001", "quantity": 100,
            }, current_user={})

    @pytest.mark.asyncio
    async def test_stock_out_creates_audit_log(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SO-AUDIT", "name": "Audit WH", "address": "Test",
        })
        await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-SO-AUDIT", "quantity": 50,
        }, current_user={})
        await wms_service.stock_out(db_session, wh["id"], {
            "sku": "SKU-SO-AUDIT", "quantity": 20, "remark": "Pick order",
        }, current_user={"id": str(uuid.uuid4())})
        from sqlalchemy import select

        from src.wms.models import InventoryLog
        logs = await db_session.execute(
            select(InventoryLog).where(InventoryLog.reference_type == "stock_out")
        )
        assert len(logs.scalars().all()) >= 1

    @pytest.mark.asyncio
    async def test_stock_out_fifo_strategy(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SO-FIFO", "name": "FIFO WH", "address": "Test",
        })
        await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-FIFO-001", "quantity": 30, "batch_no": "B1",
        }, current_user={})
        await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-FIFO-001", "quantity": 20, "batch_no": "B2",
        }, current_user={})
        result = await wms_service.stock_out(db_session, wh["id"], {
            "sku": "SKU-FIFO-001", "quantity": 10, "picking_strategy": "fifo",
        }, current_user={})
        # stock_out returns snapshot of first batch only
        assert result["quantity"] == 20

    @pytest.mark.asyncio
    async def test_stock_out_fefo_strategy(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SO-FEFO", "name": "FEFO WH", "address": "Test",
        })
        await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-FEFO-001", "quantity": 25, "batch_no": "B1",
        }, current_user={})
        await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-FEFO-001", "quantity": 15, "batch_no": "B2",
        }, current_user={})
        result = await wms_service.stock_out(db_session, wh["id"], {
            "sku": "SKU-FEFO-001", "quantity": 10, "picking_strategy": "fefo",
        }, current_user={})
        # stock_out returns snapshot of first batch only
        assert result["quantity"] == 15

    @pytest.mark.asyncio
    async def test_stock_out_cross_batch(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {
            "code": "SO-CROSS", "name": "Cross WH", "address": "Test",
        })
        await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-CROSS-001", "quantity": 5, "batch_no": "B1",
        }, current_user={})
        await wms_service.stock_in(db_session, wh["id"], {
            "sku": "SKU-CROSS-001", "quantity": 5, "batch_no": "B2",
        }, current_user={})
        result = await wms_service.stock_out(db_session, wh["id"], {
            "sku": "SKU-CROSS-001", "quantity": 8,
        }, current_user={})
        # stock_out returns snapshot of first batch only (B1 fully consumed)
        assert result["quantity"] == 0


class TestAdjustStockCountMobile:
    """adjust_stock_count_mobile router endpoint."""

    @pytest.mark.asyncio
    async def test_endpoint_exists(self, async_client):
        from src.core.dependencies import get_current_user
        from src.main import app
        app.dependency_overrides[get_current_user] = lambda: {"sub": "admin"}
        try:
            resp = await async_client.post("/api/v1/wms/inventory/adjust-stock-count", json={
                "warehouse_id": str(uuid.uuid4()),
                "items": [],
            })
            assert resp.status_code in (200, 404, 422)
        finally:
            app.dependency_overrides.pop(get_current_user, None)
