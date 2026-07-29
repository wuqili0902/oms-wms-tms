from unittest.mock import patch

import pytest

from src.tms.push_service import PushMessage, PushService


@pytest.fixture
def service():
    s = PushService()
    return s


class TestPushService:
    async def test_send_to_device_success(self, service):
        result = await service.send_to_device("tok-a", PushMessage(title="T", body="B"))
        assert result is True
        assert service.stats == {"sent": 1, "failed": 0}

    async def test_send_to_device_failure(self, service):
        with patch("src.tms.push_service.logger.info", side_effect=Exception("FCM down")):
            result = await service.send_to_device("tok-a", PushMessage(title="T", body="B"))
        assert result is False
        assert service.stats == {"sent": 0, "failed": 1}

    async def test_send_to_topic_success(self, service):
        result = await service.send_to_topic("global", PushMessage(title="T", body="B"))
        assert result is True
        assert service.stats["sent"] == 1

    async def test_send_to_topic_failure(self, service):
        with patch("src.tms.push_service.logger.info", side_effect=Exception("Topic error")):
            result = await service.send_to_topic("global", PushMessage(title="T", body="B"))
        assert result is False
        assert service.stats["failed"] == 1

    async def test_notify_status_update(self, service):
        assert await service.notify_status_update("tok-1", "ORD-1", "dispatched") is True
        assert service.stats["sent"] == 1

    async def test_notify_status_update_exception(self, service):
        assert await service.notify_status_update("tok-1", "ORD-2", "exception") is True

    async def test_notify_delivery(self, service):
        assert await service.notify_delivery("tok-2", "SF-123") is True

    async def test_notify_exception(self, service):
        assert await service.notify_exception("tok-3", "ORD-3", "delay") is True

    async def test_send_order_status_update_legacy(self, service):
        assert await service.send_order_status_update("tok-4", "ORD-4", "delivered") is True

    async def test_empty_service_stats(self, service):
        assert service.stats == {"sent": 0, "failed": 0}
