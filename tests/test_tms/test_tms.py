"""Tests for TMS — device management, heartbeat, sync, sessions."""
import uuid as uuid_mod

import pytest

from src.tms import service as tms_service


@pytest.fixture
async def auth_headers(async_client):
    uname = f"tmsuser_{uuid_mod.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestDeviceRegister:
    async def test_register_device(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/devices", json={
            "code": "PDA-001", "name": "Scanner 1", "device_type": "pda",
            "platform": "android", "os_version": "14.0", "app_version": "1.0.0",
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["code"] == "PDA-001"
        assert data["device_type"] == "pda"
        assert data["status"] == "offline"
        assert data["platform"] == "android"

    async def test_register_duplicate_code(self, async_client, auth_headers):
        await async_client.post("/api/v1/devices", json={
            "code": "PDA-001", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)
        resp = await async_client.post("/api/v1/devices", json={
            "code": "PDA-001", "device_type": "phone", "platform": "ios",
        }, headers=auth_headers)
        assert resp.status_code == 422
        assert "already exists" in resp.text

    async def test_register_with_warehouse(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/devices", json={
            "code": "WH-PDA", "device_type": "pda", "platform": "android",
            "warehouse_id": str(uuid_mod.uuid4()),
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["warehouse_id"] is not None


class TestDeviceList:
    async def test_list_devices(self, async_client, auth_headers):
        await async_client.post("/api/v1/devices", json={
            "code": "DEV-01", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)
        await async_client.post("/api/v1/devices", json={
            "code": "DEV-02", "device_type": "phone", "platform": "ios",
        }, headers=auth_headers)
        resp = await async_client.get("/api/v1/devices", headers=auth_headers)
        assert len(resp.json()) == 2

    async def test_filter_by_type(self, async_client, auth_headers):
        await async_client.post("/api/v1/devices", json={
            "code": "FLT-01", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)
        await async_client.post("/api/v1/devices", json={
            "code": "FLT-02", "device_type": "printer", "platform": "android",
        }, headers=auth_headers)
        resp = await async_client.get("/api/v1/devices?device_type=pda", headers=auth_headers)
        assert len(resp.json()) == 1
        assert resp.json()[0]["code"] == "FLT-01"

    async def test_filter_by_status(self, async_client, auth_headers):
        await async_client.post("/api/v1/devices", json={
            "code": "STS-01", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)
        resp = await async_client.get("/api/v1/devices?status=offline", headers=auth_headers)
        assert len(resp.json()) >= 1


class TestDeviceGetUpdate:
    async def test_get_device(self, async_client, auth_headers):
        create = await async_client.post("/api/v1/devices", json={
            "code": "GET-01", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)
        dev_id = create.json()["id"]
        resp = await async_client.get(f"/api/v1/devices/{dev_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["code"] == "GET-01"

    async def test_get_device_not_found(self, async_client, auth_headers):
        resp = await async_client.get("/api/v1/devices/00000000-0000-0000-0000-000000000000", headers=auth_headers)
        assert resp.status_code == 404

    async def test_update_device(self, async_client, auth_headers):
        create = await async_client.post("/api/v1/devices", json={
            "code": "UPD-01", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)
        dev_id = create.json()["id"]
        resp = await async_client.patch(f"/api/v1/devices/{dev_id}", json={
            "name": "Updated Name",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"


class TestHeartbeat:
    async def test_heartbeat(self, async_client, auth_headers):
        create = await async_client.post("/api/v1/devices", json={
            "code": "HRT-01", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)
        dev_id = create.json()["id"]
        resp = await async_client.post(f"/api/v1/devices/{dev_id}/heartbeat", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "online"
        assert "heartbeat" in resp.text.lower()

    async def test_heartbeat_not_found(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/devices/00000000-0000-0000-0000-000000000000/heartbeat", headers=auth_headers)
        assert resp.status_code == 404


class TestSyncLog:
    async def test_record_sync(self, async_client, auth_headers):
        create = await async_client.post("/api/v1/devices", json={
            "code": "SYNC-01", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)
        dev_id = create.json()["id"]
        resp = await async_client.post(f"/api/v1/devices/{dev_id}/sync", json={
            "sync_type": "download", "status": "completed", "data_count": 100,
        }, headers=auth_headers)
        assert resp.status_code == 201

    async def test_list_sync_logs(self, async_client, auth_headers):
        create = await async_client.post("/api/v1/devices", json={
            "code": "SYNC-LST", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)
        dev_id = create.json()["id"]
        await async_client.post(f"/api/v1/devices/{dev_id}/sync", json={
            "sync_type": "download", "status": "completed",
        }, headers=auth_headers)
        resp = await async_client.get(f"/api/v1/devices/{dev_id}/sync", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestSession:
    async def test_create_session(self, async_client, auth_headers):
        create = await async_client.post("/api/v1/devices", json={
            "code": "SESS-01", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)
        dev_id = create.json()["id"]
        resp = await async_client.post(f"/api/v1/devices/{dev_id}/sessions", headers=auth_headers)
        assert resp.status_code == 201

    async def test_end_session(self, async_client, auth_headers):
        create = await async_client.post("/api/v1/devices", json={
            "code": "SESS-END", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)
        dev_id = create.json()["id"]
        sess_resp = await async_client.post(f"/api/v1/devices/{dev_id}/sessions", headers=auth_headers)
        sess_id = sess_resp.json()["id"]
        resp = await async_client.delete(f"/api/v1/devices/{dev_id}/sessions/{sess_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert "ended" in resp.text.lower()

    async def test_list_sessions(self, async_client, auth_headers):
        create = await async_client.post("/api/v1/devices", json={
            "code": "SESS-LST", "device_type": "pda", "platform": "android",
        }, headers=auth_headers)
        dev_id = create.json()["id"]
        await async_client.post(f"/api/v1/devices/{dev_id}/sessions", headers=auth_headers)
        resp = await async_client.get(f"/api/v1/devices/{dev_id}/sessions", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
