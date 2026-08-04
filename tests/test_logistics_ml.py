"""Tests for logistics carrier module and push service."""
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
    async def test_query_tracking(self):
        result = await query_tracking(CarrierCode.SF, "SF240101000001")
        assert "status" in result
        assert result["carrier"] == "sf"

    @pytest.mark.asyncio
    async def test_estimate_shipping(self):
        result = await estimate_shipping(CarrierCode.ZTO, weight_kg=2.5)
        assert result["estimated_cost_yuan"] > 10
        assert result["estimated_days"] >= 1


class TestPushService:
    """Push notification service."""

    @pytest.mark.asyncio
    async def test_send_to_device(self):
        ps = PushService()
        msg = PushMessage(title="Test", body="Hello")
        result = await ps.send_to_device("fake-token", msg)
        assert result is True
        assert ps.stats["sent"] == 1

    @pytest.mark.asyncio
    async def test_send_to_topic(self):
        ps = PushService()
        msg = PushMessage(title="Broadcast", body="All users")
        result = await ps.send_to_topic("all_users", msg)
        assert result is True

    @pytest.mark.asyncio
    async def test_order_status_notification(self):
        ps = PushService()
        result = await ps.send_order_status_update("token-1", "ORD-001", "completed")
        assert result is True

    @pytest.mark.asyncio
    async def test_stats_accumulate(self):
        ps = PushService()
        await ps.send_to_device("t1", PushMessage(title="1", body="a"))
        await ps.send_to_device("t2", PushMessage(title="2", body="b"))
        assert ps.stats["sent"] == 2
        assert ps.stats["failed"] == 0

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
