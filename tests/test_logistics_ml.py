"""Tests for logistics carrier module and push service."""
from unittest.mock import patch

import pytest

from src.logistics import (
    CarrierCode,
    estimate_shipping,
    generate_tracking_number,
    get_tracking_url,
    query_tracking,
    validate_carrier,
)
from src.tms.push_service import NotificationPriority, PushMessage, PushService


class TestCarriers:
    """Carrier code validation and tracking number generation."""

    def test_validate_valid_carrier(self):
        assert validate_carrier("sf") == CarrierCode.SF
        assert validate_carrier("ZTO") == CarrierCode.ZTO
        assert validate_carrier("ems") == CarrierCode.EMS

    def test_validate_invalid_carrier(self):
        assert validate_carrier("ups") is None
        assert validate_carrier("") is None

    def test_generate_tracking_number(self):
        tn = generate_tracking_number(CarrierCode.SF, "order-123")
        assert tn.startswith("SF")
        assert len(tn) > 10

    def test_generate_tracking_number_different(self):
        t1 = generate_tracking_number(CarrierCode.SF, "a")
        t2 = generate_tracking_number(CarrierCode.SF, "b")
        assert t1 != t2

    def test_get_tracking_url(self):
        url = get_tracking_url(CarrierCode.ZTO, "ZT123456789")
        assert "ZT123456789" in url
        assert "zto.com" in url

    @pytest.mark.asyncio
    async def test_query_tracking(self, monkeypatch):
        """Unconfigured the query answers 501; the demo generator answers only when opted in."""
        from src.config import settings

        monkeypatch.setattr(settings, "logistics_mock_enabled", True)
        result = await query_tracking(CarrierCode.SF, "SF240101000001")
        assert "status" in result
        assert result["carrier"] == "sf"
        assert result["source"] == "mock"
        assert result["status_detail"].startswith("【演示数据】")

    @pytest.mark.asyncio
    async def test_estimate_shipping(self, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings, "logistics_mock_enabled", True)
        result = await estimate_shipping(CarrierCode.ZTO, weight_kg=2.5)
        assert result["estimated_cost_yuan"] > 10
        assert result["estimated_days"] >= 1
        assert result["source"] == "mock"
        assert "演示费率" in result["source_note"]


@pytest.fixture(autouse=True)
def _reset_firebase_globals():
    """Reset shared Firebase module state so tests are order-independent."""
    import sys

    mod = sys.modules["src.tms.push_service"]
    mod._firebase_available = False
    mod._firebase_app = None
    mod.__dict__.pop("_fcm_ready", None)
    yield
    mod._firebase_available = False
    mod._firebase_app = None
    mod.__dict__.pop("_fcm_ready", None)


class TestPushService:
    """Push notification service.

    Firebase is deliberately *unconfigured* here: an unconfigured push must
    report failure, not quietly claim it delivered the message (the old
    behaviour counted a log line as a sent notification).
    """

    @pytest.mark.asyncio
    async def test_send_to_device(self):
        ps = PushService()
        msg = PushMessage(title="Test", body="Hello")
        result = await ps.send_to_device("fake-token", msg)
        assert result is False
        assert ps.stats["sent"] == 0
        assert ps.stats["failed"] == 1

    @pytest.mark.asyncio
    async def test_send_to_topic(self):
        ps = PushService()
        msg = PushMessage(title="Broadcast", body="All users")
        result = await ps.send_to_topic("all_users", msg)
        assert result is False
        assert ps.stats["failed"] == 1

    @pytest.mark.asyncio
    async def test_send_to_device_with_firebase_mocked(self):
        """With a working FCM client the same call does succeed."""
        ps = PushService()
        ps._fcm_ready = True  # pretend Firebase initialised
        msg = PushMessage(title="Test", body="Hello")
        with patch("src.tms.push_service._send_fcm", return_value=True) as mock_send:
            result = await ps.send_to_device("fake-token", msg)
        mock_send.assert_called_once_with(msg, "fake-token")
        assert result is True
        assert ps.stats["sent"] == 1

    @pytest.mark.asyncio
    async def test_order_status_notification(self):
        ps = PushService()
        result = await ps.send_order_status_update("token-1", "ORD-001", "completed")
        assert result is False

    @pytest.mark.asyncio
    async def test_stats_accumulate(self):
        ps = PushService()
        await ps.send_to_device("t1", PushMessage(title="1", body="a"))
        await ps.send_to_device("t2", PushMessage(title="2", body="b"))
        assert ps.stats["sent"] == 0
        assert ps.stats["failed"] == 2

    def test_notification_priority(self):
        assert NotificationPriority.HIGH.value == "high"
        assert NotificationPriority.LOW.value == "low"

    def test_push_message_fields(self):
        msg = PushMessage(
            title="Order Shipped",
            body="Your order #123 has shipped",
            priority=NotificationPriority.HIGH,
            data={"order_no": "123", "tracking": "SF123"},
        )
        assert msg.title == "Order Shipped"
        assert msg.priority == NotificationPriority.HIGH
        assert msg.data["tracking"] == "SF123"
