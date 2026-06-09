"""Tests for the admin Web UI routes (HTML rendering)."""
import uuid as uuid_mod

import pytest
from fastapi import status


@pytest.fixture
async def auth_headers(async_client):
    uname = f"admin_{uuid_mod.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestAdminAuth:
    """Admin pages should require authentication."""

    async def test_dashboard_requires_auth(self, async_client):
        resp = await async_client.get("/admin/")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_orders_requires_auth(self, async_client):
        resp = await async_client.get("/admin/orders")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_users_requires_auth(self, async_client):
        resp = await async_client.get("/admin/users")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_inventory_requires_auth(self, async_client):
        resp = await async_client.get("/admin/inventory")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_templates_requires_auth(self, async_client):
        resp = await async_client.get("/admin/templates")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_order_detail_requires_auth(self, async_client):
        resp = await async_client.get("/admin/orders/nonexistent")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_devices_requires_auth(self, async_client):
        resp = await async_client.get("/admin/devices")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


class TestAdminDashboard:
    """Dashboard page tests."""

    async def test_dashboard_renders(self, async_client, auth_headers):
        resp = await async_client.get("/admin/", headers=auth_headers)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.headers["content-type"].startswith("text/html")
        assert "Dashboard" in resp.text

    async def test_dashboard_shows_stats(self, async_client, auth_headers):
        resp = await async_client.get("/admin/", headers=auth_headers)
        assert resp.status_code == 200
        assert "Total Orders" in resp.text
        assert "Users" in resp.text


class TestAdminOrders:
    """Order pages tests."""

    async def test_orders_page_renders(self, async_client, auth_headers):
        resp = await async_client.get("/admin/orders", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")

    async def test_orders_page_shows_orders(self, async_client, auth_headers):
        r = await async_client.post("/api/v1/orders", json={
            "customer_id": "admin-cust-1",
            "items": [{"gtin": "6901234567890", "sku": "ADM-001", "product_name": "Admin Item",
                       "quantity": 1, "unit_price": 10.0}],
        }, headers=auth_headers)
        order_no = r.json()["order_no"]

        resp = await async_client.get("/admin/orders", headers=auth_headers)
        assert resp.status_code == 200
        assert order_no in resp.text
        assert "admin-cust-1" in resp.text

    async def test_order_detail_renders(self, async_client, auth_headers):
        r = await async_client.post("/api/v1/orders", json={
            "customer_id": "detail-cust",
            "items": [{"gtin": "6901234567890", "sku": "DTL-001", "product_name": "Detail Item",
                       "quantity": 2, "unit_price": 25.0}],
        }, headers=auth_headers)
        order_id = r.json()["id"]
        order_no = r.json()["order_no"]

        resp = await async_client.get(f"/admin/orders/{order_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert order_no in resp.text
        assert "detail-cust" in resp.text
        assert "DTL-001" in resp.text

    async def test_order_detail_404(self, async_client, auth_headers):
        resp = await async_client.get("/admin/orders/00000000-0000-0000-0000-000000000000", headers=auth_headers)
        assert resp.status_code == 404


class TestAdminUsers:
    """User page tests."""

    async def test_users_page_renders(self, async_client, auth_headers):
        resp = await async_client.get("/admin/users", headers=auth_headers)
        assert resp.status_code == 200
        assert "Active" in resp.text


class TestAdminInventory:
    """Inventory page tests."""

    async def test_inventory_page_renders(self, async_client, auth_headers):
        resp = await async_client.get("/admin/inventory", headers=auth_headers)
        assert resp.status_code == 200

    async def test_inventory_shows_items(self, async_client, auth_headers):
        wh = await async_client.post("/api/v1/warehouses", json={
            "code": "ADM-INV", "name": "Admin Inv WH", "address": "Test", "type": "standard",
        }, headers=auth_headers)
        wh_id = wh.json()["id"]
        loc = await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "A", "aisle": "1", "shelf": "1", "bin": "B1", "type": "storage",
        }, headers=auth_headers)
        loc_id = loc.json()["id"]
        await async_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": wh_id, "location_id": loc_id, "sku": "ADM-INV-001",
            "quantity": 100, "reason": "admin test",
        }, headers=auth_headers)

        resp = await async_client.get("/admin/inventory", headers=auth_headers)
        assert resp.status_code == 200
        assert "ADM-INV-001" in resp.text


class TestAdminTemplates:
    """Barcode template page tests."""

    async def test_templates_page_renders(self, async_client, auth_headers):
        resp = await async_client.get("/admin/templates", headers=auth_headers)
        assert resp.status_code == 200

    async def test_templates_shows_created(self, async_client, auth_headers):
        await async_client.post("/api/v1/barcode/templates", json={
            "name": "Admin Label", "code": "ADM-LBL",
            "width_mm": 60, "height_mm": 40,
        }, headers=auth_headers)

        resp = await async_client.get("/admin/templates", headers=auth_headers)
        assert resp.status_code == 200
        assert "Admin Label" in resp.text


class TestAdminDevices:
    """TMS device page tests."""

    async def test_devices_page_renders(self, async_client, auth_headers):
        resp = await async_client.get("/admin/devices", headers=auth_headers)
        assert resp.status_code == 200

    async def test_devices_shows_registered(self, async_client, auth_headers):
        await async_client.post("/api/v1/devices", json={
            "code": "ADM-PDA", "name": "Admin PDA", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)

        resp = await async_client.get("/admin/devices", headers=auth_headers)
        assert resp.status_code == 200
        assert "ADM-PDA" in resp.text
