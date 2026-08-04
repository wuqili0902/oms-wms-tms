from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.main import app

API = "/api/v1"


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_user():
    return {"uid": "user123", "sub": "admin"}


@pytest.fixture
def override_deps(mock_db, mock_user):
    async def _get_db():
        return mock_db

    async def _get_current_user():
        return mock_user

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_current_user
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(override_deps):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def make_order(**kw):
    return {
        "id": kw.get("id", "ord-1"),
        "order_no": kw.get("order_no", "ORD-001"),
        "status": kw.get("status", "confirmed"),
        "customer_id": kw.get("customer_id", "c1"),
        "items": kw.get("items", []),
        "total_amount": kw.get("total_amount", "100.00"),
        "priority": kw.get("priority", "normal"),
        "notes": kw.get("notes", ""),
        "created_at": kw.get("created_at", "2026-01-01T00:00:00"),
        "updated_at": kw.get("updated_at", "2026-01-01T00:00:00"),
    }


def make_history(**kw):
    return {
        "id": kw.get("id", "h1"),
        "order_id": kw.get("order_id", "ord-1"),
        "from_status": kw.get("from_status", "draft"),
        "to_status": kw.get("to_status", "confirmed"),
        "operator": kw.get("operator", "admin"),
        "remark": kw.get("remark", ""),
        "created_at": kw.get("created_at", "2026-01-01T00:00:00"),
    }


ORDER_ITEM = {"gtin": "12345678901234", "sku": "ABC", "quantity": 1, "unit_price": "10.00"}


class TestCreateOrder:
    async def test_creates_order(self, client):
        with patch("src.oms.router.oms_service.create_order", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = make_order(order_no="ORD-001")
            resp = await client.post(f"{API}/orders", json={
                "customer_id": "c1",
                "items": [ORDER_ITEM],
            })
        assert resp.status_code == 201
        assert resp.json()["order_no"] == "ORD-001"


class TestListOrders:
    async def test_lists_orders(self, client):
        with patch("src.oms.router.oms_service.list_orders", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = ([make_order(id="1"), make_order(id="2")], 2)
            resp = await client.get(f"{API}/orders")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    async def test_list_with_filters(self, client):
        with patch("src.oms.router.oms_service.list_orders", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = ([], 0)
            resp = await client.get(f"{API}/orders?status=confirmed&customer_id=c1&page=2&page_size=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["page_size"] == 10


class TestGetOrder:
    async def test_gets_order(self, client):
        with patch("src.oms.router.oms_service.get_order", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = make_order(id="ord-1")
            resp = await client.get(f"{API}/orders/ord-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "ord-1"

    async def test_get_not_found(self, client):
        from src.core.exceptions import NotFoundException
        with patch("src.oms.router.oms_service.get_order", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = NotFoundException("Order not found")
            resp = await client.get(f"{API}/orders/ord-999")
        assert resp.status_code == 404


class TestUpdateOrderStatus:
    async def test_updates_status(self, client):
        with patch("src.oms.router.oms_service.update_order_status", new_callable=AsyncMock) as mock_update:
            mock_update.return_value = make_order(status="processing")
            resp = await client.put(f"{API}/orders/ord-1/status", json={"status": "processing"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

    async def test_update_not_found(self, client):
        from src.core.exceptions import NotFoundException
        with patch("src.oms.router.oms_service.update_order_status", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = NotFoundException("Order not found")
            resp = await client.put(f"{API}/orders/ord-999/status", json={"status": "processing"})
        assert resp.status_code == 404

    async def test_update_validation_error(self, client):
        from src.core.exceptions import ValidationException
        with patch("src.oms.router.oms_service.update_order_status", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = ValidationException("Invalid transition")
            resp = await client.put(f"{API}/orders/ord-1/status", json={"status": "invalid"})
        assert resp.status_code == 422


class TestDeleteOrder:
    async def test_deletes_order(self, client):
        with patch("src.oms.router.oms_service.delete_order", new_callable=AsyncMock):
            resp = await client.delete(f"{API}/orders/ord-1")
        assert resp.status_code == 204

    async def test_delete_not_found(self, client):
        from src.core.exceptions import NotFoundException
        with patch("src.oms.router.oms_service.delete_order", new_callable=AsyncMock) as mock_delete:
            mock_delete.side_effect = NotFoundException("Not found")
            resp = await client.delete(f"{API}/orders/ord-999")
        assert resp.status_code == 404

    async def test_delete_validation_error(self, client):
        from src.core.exceptions import ValidationException
        with patch("src.oms.router.oms_service.delete_order", new_callable=AsyncMock) as mock_delete:
            mock_delete.side_effect = ValidationException("Cannot delete")
            resp = await client.delete(f"{API}/orders/ord-1")
        assert resp.status_code == 422


class TestGetOrderHistory:
    async def test_gets_history(self, client):
        with patch("src.oms.router.oms_service.get_order_history", new_callable=AsyncMock) as mock_history:
            mock_history.return_value = [make_history()]
            resp = await client.get(f"{API}/orders/ord-1/history")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_history_not_found(self, client):
        from src.core.exceptions import NotFoundException
        with patch("src.oms.router.oms_service.get_order_history", new_callable=AsyncMock) as mock_history:
            mock_history.side_effect = NotFoundException("Not found")
            resp = await client.get(f"{API}/orders/ord-999/history")
        assert resp.status_code == 404


class TestSplitOrder:
    async def test_splits_order(self, client):
        with patch("src.oms.router.merge_service.split_order", new_callable=AsyncMock) as mock_split:
            mock_split.return_value = [{"id": "child-1"}]
            resp = await client.post(f"{API}/orders/ord-1/split", json={
                "splits": [{"items": [{"sku": "ABC", "qty": 1}]}],
            })
        assert resp.status_code == 201
        assert resp.json()["parent_order_id"] == "ord-1"

    async def test_split_not_found(self, client):
        from src.core.exceptions import NotFoundException
        with patch("src.oms.router.merge_service.split_order", new_callable=AsyncMock) as mock_split:
            mock_split.side_effect = NotFoundException("Not found")
            resp = await client.post(f"{API}/orders/ord-999/split", json={"splits": []})
        assert resp.status_code == 404


class TestMergeOrders:
    async def test_merges_orders(self, client):
        with patch("src.oms.router.merge_service.merge_orders", new_callable=AsyncMock) as mock_merge:
            mock_merge.return_value = {"id": "merged-1", "order_ids": ["ord-1", "ord-2"]}
            resp = await client.post(f"{API}/orders/merge", json={
                "order_ids": ["ord-1", "ord-2"],
            })
        assert resp.status_code == 201
        assert resp.json()["id"] == "merged-1"

    async def test_merge_not_found(self, client):
        from src.core.exceptions import NotFoundException
        with patch("src.oms.router.merge_service.merge_orders", new_callable=AsyncMock) as mock_merge:
            mock_merge.side_effect = NotFoundException("Not found")
            resp = await client.post(f"{API}/orders/merge", json={"order_ids": ["ord-999"]})
        assert resp.status_code == 404


class TestGetMergeGroup:
    async def test_gets_merge_group(self, client):
        with patch("src.oms.router.merge_service.get_merge_group", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "id": "grp-1",
                "code": "MG-001",
                "status": "merged",
                "total_items": 2,
                "total_amount": "100.00",
                "notes": "",
                "child_order_ids": ["ord-1", "ord-2"],
                "created_at": "2026-01-01T00:00:00",
            }
            resp = await client.get(f"{API}/orders/merge/grp-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "grp-1"

    async def test_merge_group_not_found(self, client):
        with patch("src.oms.router.merge_service.get_merge_group", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            resp = await client.get(f"{API}/orders/merge/grp-999")
        assert resp.status_code == 404
