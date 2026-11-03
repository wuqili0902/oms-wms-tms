"""Extended tests for oms/service.py — uncovered paths."""
import uuid
from decimal import Decimal

import pytest

from src.core.exceptions import NotFoundException, ValidationException
from src.oms import service as oms_service
from src.oms.models import OrderStatus


class TestOrderToDict:
    def test_with_all_params(self):
        order = type("Order", (), {
            "id": uuid.uuid4(),
            "order_no": "ORD-001",
            "status": OrderStatus.PENDING,
            "customer_id": uuid.uuid4(),
            "total_amount": Decimal("100"),
            "priority": oms_service.OrderPriority.MEDIUM,
            "notes": "test",
            "created_at": None,
            "updated_at": None,
        })()
        customer = type("Customer", (), {"code": "CUST-1"})()
        result = oms_service._order_to_dict(order, customer=customer)
        assert result["order_no"] == "ORD-001"
        assert result["customer_id"] == "CUST-1"

    def test_with_items_map(self):
        order = type("Order", (), {
            "id": uuid.uuid4(),
            "order_no": "ORD-002",
            "status": OrderStatus.PENDING,
            "customer_id": uuid.uuid4(),
            "total_amount": Decimal("50"),
            "priority": oms_service.OrderPriority.HIGH,
            "notes": "",
            "created_at": None,
            "updated_at": None,
        })()
        sku = type("SKU", (), {"id": uuid.uuid4(), "sku": "SKU-1"})()
        oi = type("OrderItem", (), {
            "sku_id": sku.id,
            "gtin": "123",
            "name": "Product",
            "quantity": 2,
            "unit_price": Decimal("25"),
        })()
        items_map = {order.id: [oi]}
        sku_map = {sku.id: sku}
        result = oms_service._order_to_dict(order, items_map=items_map, sku_map=sku_map)
        assert len(result["items"]) == 1
        assert result["items"][0]["sku"] == "SKU-1"


class TestToUuid:
    def test_invalid_string(self):
        assert oms_service._to_uuid("not-a-uuid") is None

    def test_none(self):
        assert oms_service._to_uuid(None) is None

    def test_uuid_object(self):
        uid = uuid.uuid4()
        assert oms_service._to_uuid(uid) == uid


class TestGetOrderHistory:
    @pytest.mark.asyncio
    async def test_returns_history(self, db_session):
        order = await oms_service.create_order(db_session, {
            "customer_id": "CUST-HIST",
            "items": [{"sku": "SKU-H", "quantity": 1, "unit_price": "10"}],
        })
        history = await oms_service.get_order_history(db_session, order["id"])
        assert isinstance(history, list)
        assert len(history) >= 1

    @pytest.mark.asyncio
    async def test_nonexistent_order_raises(self, db_session):
        with pytest.raises(NotFoundException):
            await oms_service.get_order_history(db_session, str(uuid.uuid4()))


class TestListOrdersEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_list(self, db_session):
        items, total = await oms_service.list_orders(db_session)
        assert isinstance(items, list)
        assert isinstance(total, int)

    @pytest.mark.asyncio
    async def test_filter_by_nonexistent_status(self, db_session):
        items, total = await oms_service.list_orders(db_session, status="nonexistent")
        assert isinstance(items, list)


class TestCreateOrderWithOperator:
    @pytest.mark.asyncio
    async def test_with_operator_id(self, db_session):
        result = await oms_service.create_order(db_session, {
            "customer_id": "CUST-OP",
            "items": [],
        }, operator_id="nonexistent_user")
        assert result["order_no"].startswith("ORD-")


class TestUpdateOrderStatusEdgeCases:
    @pytest.mark.asyncio
    async def test_update_to_same_status(self, db_session):
        order = await oms_service.create_order(db_session, {
            "customer_id": "CUST-SAME",
            "items": [],
        })
        with pytest.raises(ValidationException):
            await oms_service.update_order_status(db_session, order["id"], "draft")
