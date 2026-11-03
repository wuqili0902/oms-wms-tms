"""Extended tests for push_service — FCM path and edge cases."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tms.push_service import (
    NotificationPriority,
    PushMessage,
    PushService,
    _init_firebase,
    _send_fcm,
)


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


class TestInitFirebase:
    def test_returns_false_when_not_configured(self):
        with patch("src.tms.push_service._firebase_available", False), \
             patch("src.tms.push_service._firebase_app", None), \
             patch("src.config.settings") as mock_settings:
            mock_settings.firebase_credentials_path = ""
            result = _init_firebase()
            assert result is False

    def test_returns_false_on_import_error(self):
        with patch("src.tms.push_service._firebase_available", False), \
             patch("src.tms.push_service._firebase_app", None), \
             patch("src.config.settings") as mock_settings:
            mock_settings.firebase_credentials_path = "/nonexistent/path.json"
            result = _init_firebase()
            assert result is False

    def test_returns_true_when_already_initialized(self):
        with patch("src.tms.push_service._firebase_available", True):
            assert _init_firebase() is True

    def test_returns_true_when_app_exists(self):
        with patch("src.tms.push_service._firebase_available", False), \
             patch("src.tms.push_service._firebase_app", MagicMock()):
            assert _init_firebase() is True


class TestSendFcm:
    def test_send_import_error(self):
        msg = PushMessage(title="T", body="B")
        result = _send_fcm(msg, "token-abc")
        assert result is False  # firebase_admin not installed → exception


class TestPushMessage:
    def test_defaults(self):
        msg = PushMessage(title="T", body="B")
        assert msg.priority == NotificationPriority.NORMAL
        assert msg.data == {}
        assert msg.topic is None
        assert msg.android_channel_id == "tms_transport"

    def test_custom_fields(self):
        msg = PushMessage(
            title="T", body="B",
            priority=NotificationPriority.HIGH,
            data={"key": "val"},
            topic="global",
            android_channel_id="custom",
        )
        assert msg.priority == NotificationPriority.HIGH
        assert msg.data == {"key": "val"}
        assert msg.topic == "global"
        assert msg.android_channel_id == "custom"


class TestPushServiceWithFcm:
    async def test_send_to_device_fcm_success(self):
        with patch("src.tms.push_service._init_firebase", return_value=True), \
             patch("src.tms.push_service._send_fcm", return_value=True):
            svc = PushService()
            result = await svc.send_to_device("tok", PushMessage(title="T", body="B"))
            assert result is True
            assert svc.stats["sent"] == 1

    async def test_send_to_device_fcm_failure(self):
        with patch("src.tms.push_service._init_firebase", return_value=True), \
             patch("src.tms.push_service._send_fcm", return_value=False):
            svc = PushService()
            result = await svc.send_to_device("tok", PushMessage(title="T", body="B"))
            assert result is False
            assert svc.stats["failed"] == 1

    async def test_send_to_topic_noop(self):
        # Firebase not configured in tests → push skipped, counted as a failure.
        svc = PushService()
        result = await svc.send_to_topic("global", PushMessage(title="T", body="B"))
        assert result is False
        assert svc.stats == {"sent": 0, "failed": 1}


class TestNotifyStatusUpdateLabels:
    async def test_all_status_labels(self):
        svc = PushService()
        for status in ("dispatched", "in_transit", "out_for_delivery", "delivered", "exception", "unknown"):
            result = await svc.notify_status_update("tok", "ORD-1", status)
            # Firebase not configured → each push is skipped and reported as a failure.
            assert result is False

    async def test_exception_priority_is_high(self):
        svc = PushService()
        with patch.object(svc, "send_to_device", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await svc.notify_status_update("tok", "ORD-1", "exception")
            msg = mock_send.call_args[0][1]
            assert msg.priority == NotificationPriority.HIGH

    async def test_normal_status_priority(self):
        svc = PushService()
        with patch.object(svc, "send_to_device", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await svc.notify_status_update("tok", "ORD-1", "delivered")
            msg = mock_send.call_args[0][1]
            assert msg.priority == NotificationPriority.NORMAL


class TestNotifyDelivery:
    async def test_calls_send_with_high_priority(self):
        svc = PushService()
        with patch.object(svc, "send_to_device", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await svc.notify_delivery("tok", "SF-123")
            msg = mock_send.call_args[0][1]
            assert msg.priority == NotificationPriority.HIGH
            assert "SF-123" in msg.body


class TestNotifyException:
    async def test_calls_send_with_high_priority(self):
        svc = PushService()
        with patch.object(svc, "send_to_device", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            await svc.notify_exception("tok", "ORD-1", "delay")
            msg = mock_send.call_args[0][1]
            assert msg.priority == NotificationPriority.HIGH
            assert "delay" in msg.body


class TestSendOrderStatusUpdate:
    async def test_delegates_to_notify(self):
        svc = PushService()
        with patch.object(svc, "notify_status_update", new_callable=AsyncMock) as mock_notify:
            mock_notify.return_value = True
            await svc.send_order_status_update("tok", "ORD-1", "delivered")
            mock_notify.assert_awaited_once_with("tok", "ORD-1", "delivered")
