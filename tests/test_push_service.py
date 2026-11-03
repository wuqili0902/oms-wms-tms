import pytest

from src.tms.push_service import PushMessage, PushService


@pytest.fixture
def service():
    s = PushService()
    return s


@pytest.fixture(autouse=True)
def _reset_firebase_globals():
    """Reset shared Firebase module state so tests are order-independent.

    Without this, a test in another file that leaves `_firebase_available`/
    `_fcm_ready` dirty makes later `PushService()` instances think FCM is ready.
    """
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
    async def test_send_to_device_success(self, service):
        result = await service.send_to_device("tok-a", PushMessage(title="T", body="B"))
        assert result is False
        assert service.stats == {"sent": 0, "failed": 1}

    async def test_send_to_device_failure(self, service):
        # Firebase not configured in tests → push is skipped and counted as a failure.
        result = await service.send_to_device("tok-a", PushMessage(title="T", body="B"))
        assert result is False
        assert service.stats == {"sent": 0, "failed": 1}

    async def test_send_to_topic_success(self, service):
        result = await service.send_to_topic("global", PushMessage(title="T", body="B"))
        assert result is False
        assert service.stats["sent"] == 0

    async def test_send_to_topic_failure(self, service):
        result = await service.send_to_topic("global", PushMessage(title="T", body="B"))
        assert result is False
        assert service.stats["failed"] == 1

    async def test_notify_status_update(self, service):
        assert await service.notify_status_update("tok-1", "ORD-1", "dispatched") is False
        assert service.stats["sent"] == 0

    async def test_notify_status_update_exception(self, service):
        assert await service.notify_status_update("tok-1", "ORD-2", "exception") is False

    async def test_notify_delivery(self, service):
        assert await service.notify_delivery("tok-2", "SF-123") is False

    async def test_notify_exception(self, service):
        assert await service.notify_exception("tok-3", "ORD-3", "delay") is False

    async def test_send_order_status_update_legacy(self, service):
        assert await service.send_order_status_update("tok-4", "ORD-4", "delivered") is False

    async def test_empty_service_stats(self, service):
        assert service.stats == {"sent": 0, "failed": 0}
