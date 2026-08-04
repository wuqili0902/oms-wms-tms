"""Tests for src.core.export — export_orders, export_inventory (mocked DB)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest


def _make_mock_row(**attrs):
    row = MagicMock()
    for k, v in attrs.items():
        setattr(row, k, v)
    return row


@pytest.fixture
def mock_order():
    return _make_mock_row(
        order_no="ORD-001",
        status="pending",
        customer_id=UUID("00000000-0000-0000-0000-000000000001"),
        total_amount=100.50,
        created_at=None,
        updated_at=None,
    )


@pytest.fixture
def mock_inventory():
    return _make_mock_row(
        sku_id=UUID("00000000-0000-0000-0000-000000000101"),
        warehouse_id=1,
        quantity=50,
        locked_qty=5,
        min_qty=10,
        updated_at=None,
    )


def _mock_db_execute(db, rows):
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result)


class TestExportOrders:
    async def test_export_orders_empty(self):
        from src.core.export import export_orders

        db = AsyncMock()
        _mock_db_execute(db, [])

        result = await export_orders(db)
        assert result == []

    async def test_export_orders_with_data(self, mock_order):
        from src.core.export import export_orders

        db = AsyncMock()
        _mock_db_execute(db, [mock_order])

        result = await export_orders(db)
        assert len(result) == 1
        assert result[0]["order_no"] == "ORD-001"
        assert result[0]["total_amount"] == "100.5"

    async def test_export_orders_status_mapping(self):
        from src.core.export import export_orders
        from src.oms.models import OrderStatus
        from src.oms.service import STATUS_REVERSE

        confirmed = _make_mock_row(
            order_no="ORD-002",
            status=OrderStatus.CONFIRMED,
            customer_id=UUID("00000000-0000-0000-0000-000000000002"),
            total_amount=None,
            created_at=None,
            updated_at=None,
        )
        db = AsyncMock()
        _mock_db_execute(db, [confirmed])

        result = await export_orders(db)
        assert result[0]["status"] == "confirmed"
        assert result[0]["status"] == STATUS_REVERSE[OrderStatus.CONFIRMED]

    async def test_export_orders_null_amount(self):
        from src.core.export import export_orders

        order = _make_mock_row(
            order_no="ORD-003",
            status="draft",
            customer_id=UUID("00000000-0000-0000-0000-000000000003"),
            total_amount=None,
            created_at=None,
            updated_at=None,
        )
        db = AsyncMock()
        _mock_db_execute(db, [order])

        result = await export_orders(db)
        assert result[0]["total_amount"] == "0"

    async def test_export_orders_multiple(self):
        from src.core.export import export_orders

        o1 = _make_mock_row(
            order_no="A",
            status="a",
            customer_id=UUID(int=1),
            total_amount=None,
            created_at=None,
            updated_at=None,
        )
        o2 = _make_mock_row(
            order_no="B",
            status="b",
            customer_id=UUID(int=2),
            total_amount=None,
            created_at=None,
            updated_at=None,
        )
        db = AsyncMock()
        _mock_db_execute(db, [o1, o2])

        result = await export_orders(db)
        assert len(result) == 2

class TestExportInventory:
    async def test_export_inventory_empty(self):
        from src.core.export import export_inventory

        db = AsyncMock()
        _mock_db_execute(db, [])

        result = await export_inventory(db)
        assert result == []

    async def test_export_inventory_with_data(self, mock_inventory):
        from src.core.export import export_inventory

        db = AsyncMock()
        _mock_db_execute(db, [mock_inventory])

        result = await export_inventory(db)
        assert len(result) == 1
        assert result[0]["sku_id"] == "00000000-0000-0000-0000-000000000101"
        assert result[0]["quantity"] == 50
        assert result[0]["locked_qty"] == 5

    async def test_export_inventory_multiple(self):
        from src.core.export import export_inventory

        i1 = _make_mock_row(sku_id=UUID(int=1), warehouse_id=1, quantity=10, locked_qty=0, min_qty=0, updated_at=None)
        i2 = _make_mock_row(sku_id=UUID(int=2), warehouse_id=2, quantity=20, locked_qty=1, min_qty=2, updated_at=None)
        db = AsyncMock()
        _mock_db_execute(db, [i1, i2])

        result = await export_inventory(db)
        assert len(result) == 2
