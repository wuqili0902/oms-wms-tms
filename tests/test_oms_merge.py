from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

UUID_1 = "00000000-0000-0000-0000-000000000001"
UUID_2 = "00000000-0000-0000-0000-000000000002"
UUID_10 = "00000000-0000-0000-0000-000000000010"
UUID_20 = "00000000-0000-0000-0000-000000000020"
UUID_100 = "00000000-0000-0000-0000-000000000100"
UUID_999 = "00000000-0000-0000-0000-000000000999"
UUID_3000 = "00000000-0000-0000-0000-000000003000"


def _mock_order(**kwargs) -> MagicMock:
    o = MagicMock()
    o.id = UUID(UUID_1)
    o.order_no = kwargs.get("order_no", "ORD-001")
    o.status = kwargs.get("status", "pending")
    o.customer_id = UUID(UUID_10)
    o.warehouse_id = UUID(UUID_20)
    o.priority = kwargs.get("priority", "normal")
    o.total_amount = kwargs.get("total_amount", None)
    o.items_list = kwargs.get("items_list", [])
    return o


def _mock_order_item(**kwargs) -> MagicMock:
    i = MagicMock()
    i.sku_id = UUID(kwargs.get("sku_id", UUID_100))
    i.gtin = kwargs.get("gtin", "GTIN-001")
    i.name = kwargs.get("name", "Test Product")
    i.quantity = kwargs.get("quantity", 2)
    i.unit_price = kwargs.get("unit_price", Decimal("0"))
    return i


def _mock_merge_group(**kwargs) -> MagicMock:
    g = MagicMock()
    g.id = UUID(UUID_3000)
    g.code = kwargs.get("code", "MG-0001")
    g.status = kwargs.get("status", "active")
    g.total_items = kwargs.get("total_items", 5)
    g.total_amount = kwargs.get("total_amount", None)
    g.notes = kwargs.get("notes", "")
    g.created_at = kwargs.get("created_at", None)
    return g


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)


class TestSplitOrder:
    async def test_success(self, mock_db):
        from src.oms.merge import split_order

        item = _mock_order_item(unit_price=Decimal("10"))
        order = _mock_order(items_list=[item], total_amount=Decimal("0"))
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = order
        mock_db.execute.return_value = mock_result

        with patch("src.oms.merge._order_to_dict", new_callable=AsyncMock) as mock_otd:
            mock_otd.return_value = {"id": "child-id", "order_no": "ORD-001-SP1"}
            result = await split_order(mock_db, UUID_1, [
                {"items": [{"sku": UUID_100, "quantity": 1}], "note": "Test split"},
            ])

        assert len(result) == 1
        mock_db.add.assert_called()
        mock_db.flush.assert_awaited()
        mock_db.commit.assert_awaited()

    async def test_order_not_found(self, mock_db):
        from src.core.exceptions import NotFoundException
        from src.oms.merge import split_order

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(NotFoundException, match="not found"):
            await split_order(mock_db, UUID_999, [])

    async def test_empty_splits(self, mock_db):
        from src.oms.merge import split_order

        order = _mock_order()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = order
        mock_db.execute.return_value = mock_result

        with patch("src.oms.merge._order_to_dict", new_callable=AsyncMock):
            result = await split_order(mock_db, UUID_1, [])

        assert result == []

    async def test_sku_not_found_in_parent(self, mock_db):
        from src.oms.merge import split_order

        item = _mock_order_item(sku_id=UUID_100)
        order = _mock_order(items_list=[item])
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = order
        mock_db.execute.return_value = mock_result

        with patch("src.oms.merge._order_to_dict", new_callable=AsyncMock) as mock_otd:
            mock_otd.return_value = {"id": "child-id"}
            result = await split_order(mock_db, UUID_1, [
                {"items": [{"sku": UUID_999, "quantity": 1}]},
            ])

        assert len(result) == 1


class TestMergeOrders:
    async def test_merges_two_orders(self, mock_db):
        from src.oms.merge import merge_orders

        o1 = _mock_order(order_no="ORD-001", total_amount=Decimal("100"))
        o2 = _mock_order(order_no="ORD-002", total_amount=Decimal("200"))
        mock_order_result = MagicMock()
        mock_order_result.scalar_one_or_none.side_effect = [o1, o2]
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_db.execute.side_effect = [mock_order_result, mock_order_result, mock_count_result]

        result = await merge_orders(mock_db, [UUID_1, UUID_2])

        assert result["status"] == "active"
        assert len(result["order_ids"]) == 2

    async def test_less_than_two_orders_raises(self, mock_db):
        from src.core.exceptions import ValidationException
        from src.oms.merge import merge_orders

        with pytest.raises(ValidationException, match="at least 2 orders"):
            await merge_orders(mock_db, [UUID_1])

    async def test_order_not_found_raises(self, mock_db):
        from src.core.exceptions import NotFoundException
        from src.oms.merge import merge_orders

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(NotFoundException, match="not found"):
            await merge_orders(mock_db, [UUID_1, UUID_2])

    async def test_terminal_state_order_raises(self, mock_db):
        from src.core.exceptions import ValidationException
        from src.oms.merge import merge_orders
        from src.oms.models import OrderStatus

        o1 = _mock_order(status=OrderStatus.COMPLETED)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = o1
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValidationException, match="terminal state"):
            await merge_orders(mock_db, [UUID_1, UUID_2])


class TestGetMergeGroup:
    async def test_found(self, mock_db):
        from src.oms.merge import get_merge_group

        group = _mock_merge_group(code="MG-TEST")
        mock_group_result = MagicMock()
        mock_group_result.scalar_one_or_none.return_value = group
        mock_link_result = MagicMock()
        link = MagicMock()
        link.child_order_id = UUID("00000000-0000-0000-0000-000000000005")
        link.is_deleted = False
        mock_link_result.scalars.return_value.all.return_value = [link]

        mock_db.execute.side_effect = [mock_group_result, mock_link_result]

        result = await get_merge_group(mock_db, UUID_3000)

        assert result["code"] == "MG-TEST"
        assert len(result["child_order_ids"]) == 1

    async def test_not_found(self, mock_db):
        from src.oms.merge import get_merge_group

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await get_merge_group(mock_db, UUID_3000)
        assert result is None
