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
        assert data["total"] == 3
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
