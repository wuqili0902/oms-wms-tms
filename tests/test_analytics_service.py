from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics import service as analytics_service


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)


def make_scalar_result(value):
    m = MagicMock()
    m.scalar.return_value = value
    return m


def make_rows_result(rows):
    m = MagicMock()
    m.all.return_value = rows
    return m


class TestGetDashboardStats:
    async def test_returns_counts(self, mock_db):
        mock_db.execute = AsyncMock(side_effect=[
            make_scalar_result(10),  # orders
            make_scalar_result(5),   # users
            make_scalar_result(20),  # inventory
            make_scalar_result(3),   # warehouses
        ])
        result = await analytics_service.get_dashboard_stats(mock_db)
        assert result == {"order_count": 10, "user_count": 5, "inventory_count": 20, "warehouse_count": 3}

    async def test_returns_zero_when_null(self, mock_db):
        mock_db.execute = AsyncMock(return_value=make_scalar_result(None))
        result = await analytics_service.get_dashboard_stats(mock_db)
        assert result == {"order_count": 0, "user_count": 0, "inventory_count": 0, "warehouse_count": 0}


class MockRow:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class TestGetOrderTrends:
    async def test_returns_trends(self, mock_db):
        mock_db.execute.return_value = make_rows_result([
            MockRow(date="2026-01-01", count=5),
            MockRow(date="2026-01-02", count=3),
        ])
        result = await analytics_service.get_order_trends(mock_db, days=7)
        assert result == [{"date": "2026-01-01", "count": 5}, {"date": "2026-01-02", "count": 3}]

    async def test_empty_when_no_orders(self, mock_db):
        mock_db.execute.return_value = make_rows_result([])
        result = await analytics_service.get_order_trends(mock_db, days=30)
        assert result == []


class TestGetStatusDistribution:
    async def test_returns_distribution(self, mock_db):
        class StatusObj:
            def __init__(self, v):
                self.value = v
        mock_db.execute.return_value = make_rows_result([
            MockRow(status=StatusObj("shipped"), count=10),
            MockRow(status=StatusObj("pending"), count=5),
        ])
        result = await analytics_service.get_status_distribution(mock_db)
        assert result == [{"status": "shipped", "count": 10}, {"status": "pending", "count": 5}]

    async def test_handles_non_value_status(self, mock_db):
        mock_db.execute.return_value = make_rows_result([
            MockRow(status="cancelled", count=2),
        ])
        result = await analytics_service.get_status_distribution(mock_db)
        assert result == [{"status": "cancelled", "count": 2}]

    async def test_empty(self, mock_db):
        mock_db.execute.return_value = make_rows_result([])
        result = await analytics_service.get_status_distribution(mock_db)
        assert result == []


class TestGetLowStockItems:
    async def test_returns_items(self, mock_db):
        item = MagicMock()
        item.sku_id = "SKU-1"
        item.warehouse_id = "WH-1"
        item.quantity = 5
        item.min_qty = 10
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [item]
        mock_db.execute.return_value = mock_result
        result = await analytics_service.get_low_stock_items(mock_db)
        assert result == [{"sku": "SKU-1", "warehouse": "WH-1", "quantity": 5, "min_qty": 10}]

    async def test_empty(self, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        result = await analytics_service.get_low_stock_items(mock_db)
        assert result == []


class TestGetRecentOrders:
    async def test_returns_orders(self, mock_db):
        o = MagicMock()
        o.id = "ord-1"
        o.order_no = "ORD-001"
        o.status = "shipped"
        o.total_amount = 100.50
        o.customer_id = "cust-1"
        o.created_at = None
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [o]
        mock_db.execute.return_value = mock_result
        result = await analytics_service.get_recent_orders(mock_db, limit=5)
        assert len(result) == 1
        assert result[0]["id"] == "ord-1"
        assert result[0]["order_no"] == "ORD-001"
        assert result[0]["created_at"] == ""

    async def test_handles_none_amount(self, mock_db):
        o = MagicMock()
        o.id = "ord-2"
        o.order_no = "ORD-002"
        o.status = "draft"
        o.total_amount = None
        o.customer_id = "cust-2"
        o.created_at = None
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [o]
        mock_db.execute.return_value = mock_result
        result = await analytics_service.get_recent_orders(mock_db)
        assert result[0]["total_amount"] == "0"

    async def test_empty(self, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        result = await analytics_service.get_recent_orders(mock_db)
        assert result == []
