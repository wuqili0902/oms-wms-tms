"""Tests for WMS warehouse/location/inventory management."""
import uuid as uuid_mod

import pytest


@pytest.fixture
async def auth_headers(async_client):
    uname = f"wmsuser_{uuid_mod.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestWarehouse:
    async def test_create_warehouse(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses", json={
            "code": "WH-001", "name": "Main Warehouse", "address": "123 St", "type": "standard",
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["code"] == "WH-001"
        assert data["name"] == "Main Warehouse"
        assert data["is_active"] is True

    async def test_create_duplicate_code(self, async_client, auth_headers):
        await async_client.post("/api/v1/warehouses", json={"code": "WH-001", "name": "Main"}, headers=auth_headers)
        resp = await async_client.post("/api/v1/warehouses", json={"code": "WH-001", "name": "Duplicate"}, headers=auth_headers)
        assert resp.status_code == 422

    async def test_list_warehouses(self, async_client, auth_headers):
        await async_client.post("/api/v1/warehouses", json={"code": "WH-001", "name": "Main"}, headers=auth_headers)
        await async_client.post("/api/v1/warehouses", json={"code": "WH-002", "name": "Second"}, headers=auth_headers)
        resp = await async_client.get("/api/v1/warehouses", headers=auth_headers)
        assert len(resp.json()) == 2

    async def test_get_warehouse(self, async_client, auth_headers):
        r = await async_client.post("/api/v1/warehouses", json={"code": "WH-001", "name": "Main"}, headers=auth_headers)
        wid = r.json()["id"]
        resp = await async_client.get(f"/api/v1/warehouses/{wid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["code"] == "WH-001"

    async def test_get_warehouse_not_found(self, async_client, auth_headers):
        resp = await async_client.get("/api/v1/warehouses/00000000-0000-0000-0000-000000000000", headers=auth_headers)
        assert resp.status_code == 404


class TestLocation:
    async def test_create_location(self, async_client, auth_headers):
        wh = await async_client.post("/api/v1/warehouses", json={"code": "WH-LOC", "name": "Loc WH"}, headers=auth_headers)
        wh_id = wh.json()["id"]
        resp = await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "A", "aisle": "1", "shelf": "S", "bin": "B", "type": "storage",
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["type"] == "storage"

    async def test_create_location_invalid_warehouse(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/00000000-0000-0000-0000-000000000000/locations", json={
            "zone": "A", "aisle": "1", "shelf": "S", "bin": "B",
        }, headers=auth_headers)
        assert resp.status_code == 404

    async def test_list_locations(self, async_client, auth_headers):
        wh = await async_client.post("/api/v1/warehouses", json={"code": "WH-LST", "name": "List WH"}, headers=auth_headers)
        wh_id = wh.json()["id"]
        await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "A", "aisle": "1", "shelf": "S", "bin": "B",
        }, headers=auth_headers)
        resp = await async_client.get(f"/api/v1/warehouses/{wh_id}/locations", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestInventory:
    async def test_adjust_add(self, async_client, auth_headers):
        wh = await async_client.post("/api/v1/warehouses", json={"code": "INV-ADD", "name": "Inv WH"}, headers=auth_headers)
        wh_id = wh.json()["id"]
        loc = await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "B", "aisle": "2", "shelf": "S", "bin": "B",
        }, headers=auth_headers)
        loc_id = loc.json()["id"]
        resp = await async_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": wh_id, "location_id": loc_id, "sku": "ITEM-001", "quantity": 100,
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert int(data["quantity"]) == 100

    async def test_adjust_negative(self, async_client, auth_headers):
        wh = await async_client.post("/api/v1/warehouses", json={"code": "INV-NEG", "name": "Neg WH"}, headers=auth_headers)
        wh_id = wh.json()["id"]
        loc = await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "C", "aisle": "3", "shelf": "S", "bin": "B",
        }, headers=auth_headers)
        loc_id = loc.json()["id"]
        # Reduce without existing stock
        resp = await async_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": wh_id, "location_id": loc_id, "sku": "ITEM-002", "quantity": -10,
        }, headers=auth_headers)
        assert resp.status_code == 422

    async def test_query_inventory(self, async_client, auth_headers):
        wh = await async_client.post("/api/v1/warehouses", json={"code": "INV-QRY", "name": "Qry WH"}, headers=auth_headers)
        wh_id = wh.json()["id"]
        loc = await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "D", "aisle": "4", "shelf": "S", "bin": "B",
        }, headers=auth_headers)
        loc_id = loc.json()["id"]
        await async_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": wh_id, "location_id": loc_id, "sku": "QRY-001", "quantity": 50,
        }, headers=auth_headers)
        resp = await async_client.get("/api/v1/warehouses/inventory", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestPickingWave:
    async def test_create_picking_wave(self, async_client, auth_headers):
        wh = await async_client.post("/api/v1/warehouses", json={"code": "WVE", "name": "Wave WH"}, headers=auth_headers)
        wh_id = wh.json()["id"]
        resp = await async_client.post("/api/v1/warehouses/picking-waves", json={
            "warehouse_id": wh_id, "order_ids": ["ord-001"],
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["warehouse_id"] == wh_id

    async def test_list_picking_waves(self, async_client, auth_headers):
        wh = await async_client.post("/api/v1/warehouses", json={"code": "WVE-LST", "name": "Waves"}, headers=auth_headers)
        wh_id = wh.json()["id"]
        await async_client.post("/api/v1/warehouses/picking-waves", json={
            "warehouse_id": wh_id, "order_ids": ["ord-001"],
        }, headers=auth_headers)
        resp = await async_client.get("/api/v1/warehouses/picking-waves", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
