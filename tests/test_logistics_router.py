"""Tests for src.logistics.router — logistics API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest

from src.config import settings
from src.core.database import get_db, get_session
from src.core.dependencies import get_current_user


@pytest.fixture(autouse=True)
def _override_deps():
    from src.main import app
    mock_session = AsyncMock()
    app.dependency_overrides[get_session] = lambda: mock_session
    app.dependency_overrides[get_db] = lambda: mock_session
    app.dependency_overrides[get_current_user] = lambda: {"id": "00000000-0000-0000-0000-000000000000",
        "username": "test"}
    yield
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


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
        assert resp.status_code == 201, resp.text
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
        assert resp.status_code == 201, resp.text
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
        assert resp.status_code == 201, resp.text
        assert resp.json()["tracking_number"].startswith("SF")


class TestCreateWaybillProvenance:
    """The label prints the same either way, so the response has to say whose number it is."""

    async def test_local_number_is_flagged_as_a_placeholder(self, async_client):
        resp = await async_client.post(
            "/api/v1/logistics/waybill/create",
            json={
                "order_id": "order-004",
                "recipient_name": "赵六",
                "recipient_phone": "13600136000",
                "recipient_address": "成都市武侯区",
                "carrier_code": "zto",
                "items": [{"sku": "SKU004", "qty": 1}],
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["tracking_source"] == "local_placeholder"
        assert "快递侧没有这张面单" in data["tracking_source_note"]


class TestTrackWaybill:
    """Tracking answers describe this deployment; they are no longer picked from a hash.

    The SOP has dispatch relaying this endpoint to customers, so the old fabricated
    已揽收/运输中/已签收 timeline told customers about deliveries that never happened.
    """

    async def test_unconfigured_deployment_says_it_cannot_answer(self, async_client, monkeypatch):
        monkeypatch.setattr(settings, "logistics_mock_enabled", False)
        resp = await async_client.get("/api/v1/logistics/waybill/ZT240101ABCD1234/track")
        assert resp.status_code == 501, resp.text
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_IMPLEMENTED"
        assert "KDNIAO_EBUSINESS_ID" in body["error"]["message"]
        # A 501 is an answer about *this deployment*, not a gateway failure: the
        # router re-raises it instead of flattening it into the 502 below.

    async def test_demo_tracking_is_labelled(self, async_client, monkeypatch):
        monkeypatch.setattr(settings, "logistics_mock_enabled", True)
        resp = await async_client.get("/api/v1/logistics/waybill/SF240101WXYZ5678/track")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["source"] == "mock"
        assert data["status_detail"].startswith("【演示数据】")
        assert "演示数据" in data["source_note"]
        assert isinstance(data["events"], list)
        assert len(data["events"]) >= 1

    async def test_carrier_failure_is_a_502(self, async_client):
        with patch(
            "src.logistics.router.kdniao_query_tracking",
            new_callable=AsyncMock,
            side_effect=RuntimeError("connection reset"),
        ):
            resp = await async_client.get("/api/v1/logistics/waybill/ZT240101ABCD1234/track")
        assert resp.status_code == 502, resp.text
        assert "查单失败" in resp.json()["error"]["message"]


class TestPrintWaybill:
    async def test_print_returns_callback_url(self, async_client):
        with patch("src.logistics.router.mark_printed", new_callable=AsyncMock, return_value={"print_count": 1}):
            resp = await async_client.post("/api/v1/logistics/waybill/ZT240101ABCD1234/print")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "print_callback_url" in data
        assert len(data["print_callback_url"]) > 0

    async def test_print_url_contains_tracking(self, async_client):
        tn = "ZT240101ABCD1234"
        with patch("src.logistics.router.mark_printed", new_callable=AsyncMock, return_value={"print_count": 1}):
            resp = await async_client.post(f"/api/v1/logistics/waybill/{tn}/print")
        assert resp.status_code == 200
        assert tn in resp.json()["print_callback_url"]
