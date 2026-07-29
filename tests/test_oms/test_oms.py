"""Tests for OMS order lifecycle (async DB-backed)."""
import uuid as uuid_mod

import pytest


@pytest.fixture
async def auth_headers(async_client):
    uname = f"omsuser_{uuid_mod.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestCreateOrder:
    async def test_create_order_success(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-001",
            "items": [{"gtin": "6901234567890", "sku": "SKU-001", "product_name": "Product A",
                       "quantity": 2, "unit_price": "10.50", "subtotal": "21.00"}],
            "priority": "high",
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["order_no"].startswith("ORD-")
        assert data["customer_id"] == "cust-001"
        assert data["priority"] == "high"

    async def test_create_order_without_auth(self, async_client):
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-001",
            "items": [{"gtin": "6901234567890", "sku": "SKU-001", "product_name": "A",
                       "quantity": 1, "unit_price": "10.00", "subtotal": "10.00"}],
        })
        assert resp.status_code == 401

    async def test_create_order_empty_items(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-001", "items": [],
        }, headers=auth_headers)
        assert resp.status_code == 422


class TestOrderStateMachine:
    async def test_full_lifecycle(self, async_client, auth_headers):
        # Create
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-001",
            "items": [{"gtin": "6901234567890", "sku": "SKU-001", "product_name": "A",
                       "quantity": 1, "unit_price": "10.00", "subtotal": "10.00"}],
        }, headers=auth_headers)
        oid = resp.json()["id"]

        # draft → confirmed
        resp = await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": "confirmed"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

        # confirmed → processing
        resp = await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": "processing"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

        # processing → picking
        resp = await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": "picking"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "picking"

        # picking → completed
        resp = await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": "completed"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    async def test_invalid_transition(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-001",
            "items": [{"gtin": "6901234567890", "sku": "SKU-001", "product_name": "A",
                       "quantity": 1, "unit_price": "10.00", "subtotal": "10.00"}],
        }, headers=auth_headers)
        oid = resp.json()["id"]

        # draft → processing (invalid: skip confirmed)
        resp = await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": "processing"}, headers=auth_headers)
        assert resp.status_code == 422

    async def test_cancel_from_draft(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-001",
            "items": [{"gtin": "6901234567890", "sku": "SKU-001", "product_name": "A",
                       "quantity": 1, "unit_price": "10.00", "subtotal": "10.00"}],
        }, headers=auth_headers)
        oid = resp.json()["id"]

        resp = await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": "cancelled"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        # terminal state — cannot transition
        resp = await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": "confirmed"}, headers=auth_headers)
        assert resp.status_code == 422


class TestListOrders:
    async def test_list_returns_paginated_results(self, async_client, auth_headers):
        for i in range(3):
            await async_client.post("/api/v1/orders", json={
                "customer_id": "cust-001",
                "items": [{"gtin": "6901234567890", "sku": f"SKU-{i}", "product_name": "A",
                           "quantity": 1, "unit_price": "10.00", "subtotal": "10.00"}],
            }, headers=auth_headers)

        resp = await async_client.get("/api/v1/orders?page=1&page_size=2", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] >= 3
        assert data["page"] == 1

    async def test_filter_by_status(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-001",
            "items": [{"gtin": "6901234567890", "sku": "SKU-001", "product_name": "A",
                       "quantity": 1, "unit_price": "10.00", "subtotal": "10.00"}],
        }, headers=auth_headers)
        oid = resp.json()["id"]
        await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": "cancelled"}, headers=auth_headers)

        resp = await async_client.get("/api/v1/orders?status=cancelled", headers=auth_headers)
        assert len(resp.json()["items"]) == 1


class TestOrderHistory:
    async def test_get_history(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-001",
            "items": [{"gtin": "6901234567890", "sku": "SKU-001", "product_name": "A",
                       "quantity": 1, "unit_price": "10.00", "subtotal": "10.00"}],
        }, headers=auth_headers)
        oid = resp.json()["id"]

        await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": "cancelled"}, headers=auth_headers)

        resp = await async_client.get(f"/api/v1/orders/{oid}/history", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 2  # creation + status change

    async def test_get_history_not_found(self, async_client, auth_headers):
        import uuid as _uuid
        fake_id = str(_uuid.uuid4())
        resp = await async_client.get(f"/api/v1/orders/{fake_id}/history", headers=auth_headers)
        assert resp.status_code == 404


class TestOrderErrorPaths:
    async def test_get_order_success(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-get",
            "items": [{"gtin": "6901234567890", "sku": "SKU-GET", "product_name": "A",
                       "quantity": 1, "unit_price": "10.00", "subtotal": "10.00"}],
        }, headers=auth_headers)
        oid = resp.json()["id"]

        resp = await async_client.get(f"/api/v1/orders/{oid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == oid

    async def test_get_order_not_found(self, async_client, auth_headers):
        import uuid as _uuid
        fake_id = str(_uuid.uuid4())
        resp = await async_client.get(f"/api/v1/orders/{fake_id}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_order_not_found(self, async_client, auth_headers):
        import uuid as _uuid
        fake_id = str(_uuid.uuid4())
        resp = await async_client.delete(f"/api/v1/orders/{fake_id}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_split_order_not_found(self, async_client, auth_headers):
        import uuid as _uuid
        fake_id = str(_uuid.uuid4())
        resp = await async_client.post(f"/api/v1/orders/{fake_id}/split", json={
            "splits": [{"items": [], "note": "split1"}],
        }, headers=auth_headers)
        assert resp.status_code == 404

    async def test_merge_orders_not_found(self, async_client, auth_headers):
        import uuid as _uuid
        resp = await async_client.post("/api/v1/orders/merge", json={
            "order_ids": [str(_uuid.uuid4()), str(_uuid.uuid4())],
        }, headers=auth_headers)
        assert resp.status_code == 404

    async def test_merge_orders_terminal_state(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-term",
            "items": [{"gtin": "6901234567890", "sku": "SKU-TERM", "product_name": "A",
                       "quantity": 1, "unit_price": "10.00", "subtotal": "10.00"}],
        }, headers=auth_headers)
        oid = resp.json()["id"]

        resp = await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": "cancelled"}, headers=auth_headers)
        assert resp.status_code == 200

        oid2_resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-term2",
            "items": [{"gtin": "6901234567890", "sku": "SKU-TERM2", "product_name": "B",
                       "quantity": 1, "unit_price": "10.00", "subtotal": "10.00"}],
        }, headers=auth_headers)
        oid2 = oid2_resp.json()["id"]

        resp = await async_client.post("/api/v1/orders/merge", json={
            "order_ids": [oid, oid2],
        }, headers=auth_headers)
        assert resp.status_code == 422

    async def test_get_merge_group_success(self, async_client, auth_headers):
        resp1 = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-grp",
            "items": [{"gtin": "6901234567890", "sku": "SKU-GRP1", "product_name": "A",
                       "quantity": 1, "unit_price": "10.00", "subtotal": "10.00"}],
        }, headers=auth_headers)
        oid1 = resp1.json()["id"]
        resp2 = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-grp",
            "items": [{"gtin": "6901234567890", "sku": "SKU-GRP2", "product_name": "B",
                       "quantity": 2, "unit_price": "5.00", "subtotal": "10.00"}],
        }, headers=auth_headers)
        oid2 = resp2.json()["id"]

        resp = await async_client.post("/api/v1/orders/merge", json={
            "order_ids": [oid1, oid2],
        }, headers=auth_headers)
        group_id = resp.json()["id"]

        resp = await async_client.get(f"/api/v1/orders/merge/{group_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["child_order_ids"]) == 2

    async def test_get_merge_group_not_found(self, async_client, auth_headers):
        import uuid as _uuid
        fake_id = str(_uuid.uuid4())
        resp = await async_client.get(f"/api/v1/orders/merge/{fake_id}", headers=auth_headers)
        assert resp.status_code == 404

class TestSplitMerge:
    async def test_split_order_with_existing_sku(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-split-ex",
            "items": [{"gtin": "6901234567890", "sku": "SKU-EXIST", "product_name": "Exists",
                       "quantity": 10, "unit_price": "10.00", "subtotal": "100.00"}],
        }, headers=auth_headers)
        oid = resp.json()["id"]

        resp = await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": "confirmed"}, headers=auth_headers)
        assert resp.status_code == 200

        resp = await async_client.post(f"/api/v1/orders/{oid}/split", json={
            "splits": [{"items": [
                {"sku": "SKU-EXIST", "quantity": 3,
                 "product_name": "Exists", "gtin": "6901234567890"},
            ], "note": "split with existing sku"}],
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["children"]) == 1

    async def test_split_order_with_unknown_sku(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-split",
            "items": [{"gtin": "6901234567890", "sku": "SKU-REAL", "product_name": "Real",
                       "quantity": 10, "unit_price": "10.00", "subtotal": "100.00"}],
        }, headers=auth_headers)
        oid = resp.json()["id"]

        resp = await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": "confirmed"}, headers=auth_headers)
        assert resp.status_code == 200

        resp = await async_client.post(f"/api/v1/orders/{oid}/split", json={
            "splits": [{"items": [{"sku": "SKU-NOT-IN-ORDER", "quantity": 2,
                                   "product_name": "Ghost", "gtin": "000"}],
                        "note": "split with unknown sku"}],
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["children"]) == 1

    async def test_merge_orders_success(self, async_client, auth_headers):
        resp1 = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-merge",
            "items": [{"gtin": "6901234567890", "sku": "SKU-M1", "product_name": "M1",
                       "quantity": 2, "unit_price": "10.00", "subtotal": "20.00"}],
        }, headers=auth_headers)
        oid1 = resp1.json()["id"]

        resp2 = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-merge",
            "items": [{"gtin": "6901234567890", "sku": "SKU-M2", "product_name": "M2",
                       "quantity": 3, "unit_price": "15.00", "subtotal": "45.00"}],
        }, headers=auth_headers)
        oid2 = resp2.json()["id"]

        resp = await async_client.post("/api/v1/orders/merge", json={
            "order_ids": [oid1, oid2],
        }, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["code"].startswith("MG-")
        assert len(data["order_ids"]) == 2

    async def test_delete_order_invalid_state(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/orders", json={
            "customer_id": "cust-del",
            "items": [{"gtin": "6901234567890", "sku": "SKU-DEL", "product_name": "A",
                       "quantity": 1, "unit_price": "10.00", "subtotal": "10.00"}],
        }, headers=auth_headers)
        oid = resp.json()["id"]
        # Complete the order → terminal state, cannot be deleted
        for s in ("confirmed", "processing", "picking", "completed"):
            await async_client.put(f"/api/v1/orders/{oid}/status", json={"status": s}, headers=auth_headers)

        resp = await async_client.delete(f"/api/v1/orders/{oid}", headers=auth_headers)
        assert resp.status_code == 422


class TestModelRepr:
    """Covers __repr__ methods in oms/models.py (lines 98, 122, 140, 158)."""

    async def test_order_repr(self):
        from src.oms.models import Order, OrderStatus
        o = Order(order_no="ORD-REPR", status=OrderStatus.PENDING)
        assert "ORD-REPR" in repr(o)
        assert "pending" in repr(o)

    async def test_order_status_log_repr(self):
        from src.oms.models import OrderStatusLog
        log = OrderStatusLog(from_status="draft", to_status="confirmed")
        assert "draft" in repr(log)
        assert "confirmed" in repr(log)

    async def test_merge_group_repr(self):
        from src.oms.models import MergeGroup
        mg = MergeGroup(code="MG-REPR", status="active")
        assert "MG-REPR" in repr(mg)
        assert "active" in repr(mg)

    async def test_split_child_order_repr(self):
        import uuid
        from src.oms.models import SplitChildOrder
        sco = SplitChildOrder(
            parent_order_id=uuid.uuid4(),
            child_order_id=uuid.uuid4(),
        )
        assert "SplitChildOrder" in repr(sco)
