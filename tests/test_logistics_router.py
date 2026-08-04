"""Tests for src.logistics.router — logistics API endpoints."""

from unittest.mock import AsyncMock

import pytest

from src.core.database import get_session


@pytest.fixture(autouse=True)
def _override_get_session():
    from src.main import app
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.pop(get_session, None)


class TestCreateWaybill:
    async def test_create_waybill_success(self, async_client):
        resp = await async_client.post(
            "/api/v1/logistics/waybill/create",
            json={
                "order_id": "order-001",
                "recipient_name": "张三",
                "recipient_phone": "13800138000",
                "recipient_address": "广东省深圳市南山区科技园",
                "carrier_code": "zto",
                "items": [{"sku": "SKU001", "qty": 2}],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["tracking_number"].startswith("ZT")
        assert data["carrier_code"] == "zto"
        assert data["status"] == "created"

    async def test_create_waybill_default_carrier(self, async_client):
        resp = await async_client.post(
            "/api/v1/logistics/waybill/create",
            json={
                "order_id": "order-002",
                "recipient_name": "李四",
                "recipient_phone": "13900139000",
                "recipient_address": "北京市朝阳区",
                "items": [{"sku": "SKU002", "qty": 1}],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["carrier_code"] == "zto"

    async def test_create_waybill_with_sf(self, async_client):
        resp = await async_client.post(
            "/api/v1/logistics/waybill/create",
            json={
                "order_id": "order-003",
                "recipient_name": "王五",
                "recipient_phone": "13700137000",
                "recipient_address": "上海市浦东新区",
                "carrier_code": "sf",
                "items": [{"sku": "SKU003", "qty": 3}],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["tracking_number"].startswith("SF")


class TestTrackWaybill:
    async def test_track_known_waybill(self, async_client):
        resp = await async_client.get("/api/v1/logistics/waybill/ZT240101ABCD1234/track")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "status" in data
        assert "tracking_number" in data
        assert data["carrier"] == "ZT"
        assert len(data["events"]) >= 1

    async def test_track_returns_events(self, async_client):
        resp = await async_client.get("/api/v1/logistics/waybill/SF240101WXYZ5678/track")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["events"], list)


class TestPrintWaybill:
    async def test_print_returns_callback_url(self, async_client):
        resp = await async_client.post("/api/v1/logistics/waybill/ZT240101ABCD1234/print")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "print_callback_url" in data
        assert len(data["print_callback_url"]) > 0

    async def test_print_url_contains_tracking(self, async_client):
        tn = "ZT240101ABCD1234"
        resp = await async_client.post(f"/api/v1/logistics/waybill/{tn}/print")
        assert resp.status_code == 200
        assert tn in resp.json()["print_callback_url"]
