"""Direct service-level tests for OMS business logic.

Tests all untested paths in src/oms/service.py using the db_session fixture.
"""
import uuid

import pytest

from src.core.exceptions import NotFoundException, ValidationException
from src.oms import merge as oms_merge
from src.oms import service as oms_service
from src.oms.models import Order, OrderStatus


class TestValidateTransition:
    """State machine validation — every valid/invalid transition."""

    def test_valid_transitions(self):
        oms_service.validate_transition("draft", "confirmed")  # should not raise
        oms_service.validate_transition("draft", "cancelled")
        oms_service.validate_transition("confirmed", "processing")
        oms_service.validate_transition("confirmed", "cancelled")
        oms_service.validate_transition("processing", "picking")
        oms_service.validate_transition("processing", "cancelled")
        oms_service.validate_transition("picking", "completed")
        oms_service.validate_transition("picking", "cancelled")

    def test_invalid_from_draft(self):
        with pytest.raises(ValidationException, match="Cannot transition from 'draft'"):
            oms_service.validate_transition("draft", "completed")

    def test_invalid_from_terminal_completed(self):
        with pytest.raises(ValidationException):
            oms_service.validate_transition("completed", "processing")

    def test_invalid_from_terminal_cancelled(self):
        with pytest.raises(ValidationException):
            oms_service.validate_transition("cancelled", "confirmed")

    def test_invalid_from_terminal_failed(self):
        with pytest.raises(ValidationException):
            oms_service.validate_transition("failed", "processing")

    def test_unknown_current_state(self):
        with pytest.raises(ValidationException):
            oms_service.validate_transition("nonexistent", "confirmed")


class TestGetOrCreateCustomer:
    """Test _get_or_create_customer helper."""

    @pytest.mark.asyncio
    async def test_creates_new_customer(self, db_session):
        c = await oms_service._get_or_create_customer(db_session, "CUST-NEW")
        assert c.code == "CUST-NEW"
        assert c.name == "CUST-NEW"

    @pytest.mark.asyncio
    async def test_returns_existing_customer(self, db_session):
        c1 = await oms_service._get_or_create_customer(db_session, "CUST-DUP")
        c2 = await oms_service._get_or_create_customer(db_session, "CUST-DUP")
        assert c1.id == c2.id


class TestGetOrCreateSKU:
    """Test _get_or_create_sku helper."""

    @pytest.mark.asyncio
    async def test_creates_new_sku(self, db_session):
        sku = await oms_service._get_or_create_sku(db_session, "SKU-999")
        assert sku.sku == "SKU-999"

    @pytest.mark.asyncio
    async def test_returns_existing_sku(self, db_session):
        s1 = await oms_service._get_or_create_sku(db_session, "SKU-EXIST")
        s2 = await oms_service._get_or_create_sku(db_session, "SKU-EXIST")
        assert s1.id == s2.id


class TestCreateOrder:
    """Order creation with various item configurations."""

    @pytest.mark.asyncio
    async def test_create_order_single_item(self, db_session):
        data = {
            "customer_id": "CUST-A",
            "items": [{"gtin": "123", "sku": "SKU-A", "product_name": "Item A", "quantity": 2, "unit_price": "10.00"}],
            "priority": "medium",
        }
        order = await oms_service.create_order(db_session, data)
        assert order["status"] == "draft"
        assert order["order_no"].startswith("ORD-")
        assert len(order["items"]) == 1
        assert order["items"][0]["quantity"] == 2

    @pytest.mark.asyncio
    async def test_create_order_multiple_items(self, db_session):
        data = {
            "customer_id": "CUST-B",
            "items": [
                {"gtin": "A1", "sku": "SKU-1", "product_name": "Item 1", "quantity": 1, "unit_price": "5.00"},
                {"gtin": "A2", "sku": "SKU-2", "product_name": "Item 2", "quantity": 3, "unit_price": "15.00"},
            ],
        }
        order = await oms_service.create_order(db_session, data)
        assert len(order["items"]) == 2
        assert order["total_amount"] == "50.00"

    @pytest.mark.asyncio
    async def test_create_order_no_items(self, db_session):
        data = {"customer_id": "CUST-C", "items": []}
        order = await oms_service.create_order(db_session, data)
        assert order["total_amount"] == "0"
        assert order["items"] == []

    @pytest.mark.asyncio
    async def test_create_order_reuses_customer(self, db_session):
        data1 = {"customer_id": "CUST-D", "items": []}
        await oms_service.create_order(db_session, data1)
        data2 = {"customer_id": "CUST-D", "items": [{"gtin": "B1", "product_name": "X", "quantity": 1, "unit_price": "1.00"}]}
        order2 = await oms_service.create_order(db_session, data2)
        assert order2["customer_id"] == "CUST-D"


class TestGetOrder:
    """Order retrieval and error handling."""

    @pytest.mark.asyncio
    async def test_get_existing_order(self, db_session):
        data = {"customer_id": "CUST-G", "items": []}
        created = await oms_service.create_order(db_session, data)
        fetched = await oms_service.get_order(db_session, created["id"])
        assert fetched["id"] == created["id"]

    @pytest.mark.asyncio
    async def test_get_nonexistent_order(self, db_session):
        with pytest.raises(NotFoundException):
            await oms_service.get_order(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_get_soft_deleted_order_returns_404(self, db_session):
        data = {"customer_id": "CUST-SD", "items": []}
        created = await oms_service.create_order(db_session, data)
        # Soft-delete
        result = await db_session.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(Order).where(Order.id == uuid.UUID(created["id"]))
        )
        order = result.scalar_one()
        order.is_deleted = True
        await db_session.commit()
        with pytest.raises(NotFoundException):
            await oms_service.get_order(db_session, created["id"])


class TestListOrders:
    """Order listing with pagination and filters."""

    @pytest.mark.asyncio
    async def test_list_with_pagination(self, db_session):
        for i in range(5):
            await oms_service.create_order(db_session, {"customer_id": f"CUST-P{i}", "items": []})
        items, total = await oms_service.list_orders(db_session, page=1, page_size=2)
        assert 1 <= len(items) <= 2
        assert total >= 5

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, db_session):
        await oms_service.create_order(db_session, {"customer_id": "CUST-F1", "items": []})
        items, total = await oms_service.list_orders(db_session, status="draft")
        assert total >= 1
        assert all(i["status"] == "draft" for i in items)

    @pytest.mark.asyncio
    async def test_list_filter_by_customer(self, db_session):
        from src.oms.models import Customer
        from sqlalchemy import select
        await oms_service.create_order(db_session, {"customer_id": "CUST-FILTER", "items": []})
        result = await db_session.execute(select(Customer).where(Customer.code == "CUST-FILTER"))
        customer = result.scalar_one()
        items, total = await oms_service.list_orders(db_session, customer_id=str(customer.id))
        assert total >= 1
        assert items[0]["customer_id"] == "CUST-FILTER"


class TestToUuid:
    """Covers _to_uuid edge cases (oms/service.py line 73)."""

    @pytest.mark.asyncio
    async def test_to_uuid_none(self):
        result = oms_service._to_uuid(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_to_uuid_uuid_obj(self):
        uid = uuid.uuid4()
        result = oms_service._to_uuid(uid)
        assert result is uid


class TestUpdateOrderStatus:
    """State machine status transitions."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, db_session):
        created = await oms_service.create_order(db_session, {"customer_id": "LC", "items": []})
        oid = created["id"]

        # draft → confirmed
        r1 = await oms_service.update_order_status(db_session, oid, "confirmed")
        assert r1["status"] == "confirmed"

        # confirmed → processing
        r2 = await oms_service.update_order_status(db_session, oid, "processing")
        assert r2["status"] == "processing"

        # processing → picking
        r3 = await oms_service.update_order_status(db_session, oid, "picking")
        assert r3["status"] == "picking"

        # picking → completed
        r4 = await oms_service.update_order_status(db_session, oid, "completed")
        assert r4["status"] == "completed"

    @pytest.mark.asyncio
    async def test_cancel_from_draft(self, db_session):
        created = await oms_service.create_order(db_session, {"customer_id": "CD", "items": []})
        r = await oms_service.update_order_status(db_session, created["id"], "cancelled")
        assert r["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_status_change_webhook_fails_gracefully(self, db_session, monkeypatch):
        async def mock_dispatch(*args, **kwargs):
            raise RuntimeError("Webhook down")
        monkeypatch.setattr("src.webhooks.service.dispatch_event", mock_dispatch)
        created = await oms_service.create_order(db_session, {"customer_id": "WH-FAIL", "items": []})
        created_id = created["id"]
        result = await oms_service.update_order_status(db_session, created_id, "confirmed")
        assert result["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_invalid_transition_raises_error(self, db_session):
        created = await oms_service.create_order(db_session, {"customer_id": "IV", "items": []})
        with pytest.raises(ValidationException, match="Cannot transition from 'draft'"):
            await oms_service.update_order_status(db_session, created["id"], "completed")

    @pytest.mark.asyncio
    async def test_terminal_state_cannot_transition(self, db_session):
        created = await oms_service.create_order(db_session, {"customer_id": "TM", "items": []})
        await oms_service.update_order_status(db_session, created["id"], "cancelled")
        with pytest.raises(ValidationException):
            await oms_service.update_order_status(db_session, created["id"], "confirmed")

    @pytest.mark.asyncio
    async def test_update_nonexistent_order(self, db_session):
        with pytest.raises(NotFoundException):
            await oms_service.update_order_status(db_session, str(uuid.uuid4()), "confirmed")

    @pytest.mark.asyncio
    async def test_history_logged(self, db_session):
        created = await oms_service.create_order(db_session, {"customer_id": "HL", "items": []})
        await oms_service.update_order_status(db_session, created["id"], "confirmed")
        history = await oms_service.get_order_history(db_session, created["id"])
        assert len(history) >= 2  # created log + transition log


class TestCancelOrder:
    """Cancel order via status transition."""

    @pytest.mark.asyncio
    async def test_cancel_draft_order(self, db_session):
        created = await oms_service.create_order(db_session, {"customer_id": "CA", "items": []})
        r = await oms_service.update_order_status(db_session, created["id"], "cancelled")
        assert r["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_processing_order(self, db_session):
        created = await oms_service.create_order(db_session, {"customer_id": "CP", "items": []})
        await oms_service.update_order_status(db_session, created["id"], "confirmed")
        await oms_service.update_order_status(db_session, created["id"], "processing")
        r = await oms_service.update_order_status(db_session, created["id"], "cancelled")
        assert r["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self, db_session):
        with pytest.raises(NotFoundException):
            await oms_service.update_order_status(db_session, str(uuid.uuid4()), "cancelled")


class TestDeleteOrder:
    """Soft delete order."""

    @pytest.mark.asyncio
    async def test_delete_draft_order(self, db_session):
        created = await oms_service.create_order(db_session, {"customer_id": "DEL", "items": []})
        await oms_service.delete_order(db_session, created["id"])
        with pytest.raises(NotFoundException):
            await oms_service.get_order(db_session, created["id"])

    @pytest.mark.asyncio
    async def test_cannot_delete_completed_order(self, db_session):
        created = await oms_service.create_order(db_session, {"customer_id": "DEL-C", "items": []})
        await oms_service.update_order_status(db_session, created["id"], "confirmed")
        await oms_service.update_order_status(db_session, created["id"], "processing")
        await oms_service.update_order_status(db_session, created["id"], "picking")
        await oms_service.update_order_status(db_session, created["id"], "completed")
        with pytest.raises(ValidationException):
            await oms_service.delete_order(db_session, created["id"])

    @pytest.mark.asyncio
    async def test_delete_nonexistent_order(self, db_session):
        with pytest.raises(NotFoundException):
            await oms_service.delete_order(db_session, str(uuid.uuid4()))


class TestSplitOrder:
    """Order splitting via merge.split_order."""

    @pytest.mark.asyncio
    async def test_split_into_multiple_children(self, db_session):
        created = await oms_service.create_order(db_session, {
            "customer_id": "SPLIT",
            "items": [{"gtin": "S1", "sku": "SKU-SP", "product_name": "Split", "quantity": 10, "unit_price": "5.00"}],
        })
        children = await oms_merge.split_order(db_session, created["id"], splits=[
            {"items": [{"sku": "SKU-SP", "quantity": 4}], "note": "Child A"},
            {"items": [{"sku": "SKU-SP", "quantity": 6}], "note": "Child B"},
        ])
        assert len(children) == 2
        assert children[0]["order_no"].endswith("-SP1")
        assert children[1]["order_no"].endswith("-SP2")

    @pytest.mark.asyncio
    async def test_split_nonexistent_order(self, db_session):
        with pytest.raises(NotFoundException):
            await oms_merge.split_order(db_session, str(uuid.uuid4()), splits=[])


class TestMergeOrders:
    """Order merging via merge.merge_orders."""

    @pytest.mark.asyncio
    async def test_merge_two_orders(self, db_session):
        o1 = await oms_service.create_order(db_session, {"customer_id": "MG-A", "items": []})
        o2 = await oms_service.create_order(db_session, {"customer_id": "MG-B", "items": []})
        group = await oms_merge.merge_orders(db_session, [o1["id"], o2["id"]], code="MG-TEST")
        assert group["code"] == "MG-TEST"
        assert group["status"] == "active"
        assert len(group["order_ids"]) == 2

    @pytest.mark.asyncio
    async def test_merge_less_than_two_orders(self, db_session):
        with pytest.raises(ValidationException, match="Need at least 2 orders to merge"):
            await oms_merge.merge_orders(db_session, [str(uuid.uuid4())])

    @pytest.mark.asyncio
    async def test_merge_with_terminal_order(self, db_session):
        o1 = await oms_service.create_order(db_session, {"customer_id": "MG-TM", "items": []})
        o2 = await oms_service.create_order(db_session, {"customer_id": "MG-TM2", "items": []})
        await oms_service.update_order_status(db_session, o1["id"], "cancelled")
        with pytest.raises(ValidationException, match="terminal state"):
            await oms_merge.merge_orders(db_session, [o1["id"], o2["id"]])

    @pytest.mark.asyncio
    async def test_merge_nonexistent_order(self, db_session):
        o1 = await oms_service.create_order(db_session, {"customer_id": "MG-NF", "items": []})
        with pytest.raises(NotFoundException):
            await oms_merge.merge_orders(db_session, [o1["id"], str(uuid.uuid4())])


class TestGetMergeGroup:
    """Merge group retrieval."""

    @pytest.mark.asyncio
    async def test_get_existing_merge_group(self, db_session):
        o1 = await oms_service.create_order(db_session, {"customer_id": "GG-A", "items": []})
        o2 = await oms_service.create_order(db_session, {"customer_id": "GG-B", "items": []})
        group = await oms_merge.merge_orders(db_session, [o1["id"], o2["id"]])
        fetched = await oms_merge.get_merge_group(db_session, group["id"])
        assert fetched["id"] == group["id"]
        assert len(fetched["child_order_ids"]) == 2

    @pytest.mark.asyncio
    async def test_get_nonexistent_merge_group(self, db_session):
        result = await oms_merge.get_merge_group(db_session, str(uuid.uuid4()))
        assert result is None
