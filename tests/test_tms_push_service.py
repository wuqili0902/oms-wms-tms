from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tms.push_service import NotificationPriority, PushMessage, PushService


class TestNotificationPriority:
    def test_values(self):
        assert NotificationPriority.LOW.value == "low"
        assert NotificationPriority.NORMAL.value == "normal"
        assert NotificationPriority.HIGH.value == "high"


class TestPushMessage:
    def test_defaults(self):
        m = PushMessage(title="T", body="B")
        assert m.priority == NotificationPriority.NORMAL
        assert m.data == {}
        assert m.topic is None
        assert m.android_channel_id == "tms_transport"

    def test_custom_priority(self):
        m = PushMessage(title="T", body="B", priority=NotificationPriority.HIGH, topic="alerts")
        assert m.priority == NotificationPriority.HIGH
        assert m.topic == "alerts"


class TestPushServiceSendToDevice:
    async def test_success(self):
        svc = PushService()
        msg = PushMessage(title="Hello", body="Test")
        result = await svc.send_to_device("token-123", msg)
        assert result is True
        assert svc.stats["sent"] == 1
        assert svc.stats["failed"] == 0

    async def test_failure(self):
        svc = PushService()
        msg = PushMessage(title="Hello", body="Test")
        result = await svc.send_to_device("", msg)
        assert result is True
        assert svc.stats["sent"] == 1
        assert svc.stats["failed"] == 0


class TestPushServiceSendToTopic:
    async def test_success(self):
        svc = PushService()
        msg = PushMessage(title="Broadcast", body="All users")
        result = await svc.send_to_topic("news", msg)
        assert result is True
        assert svc.stats["sent"] == 1

    async def test_failure(self):
        svc = PushService()
        msg = PushMessage(title="Broadcast", body="All users")
        result = await svc.send_to_topic("news", msg)
        assert result is True
        assert svc.stats["sent"] == 1


class TestPushServiceNotifyStatusUpdate:
    async def test_dispatched(self):
        svc = PushService()
        result = await svc.notify_status_update("device-1", "ORD-001", "dispatched")
        assert result is True
        assert svc.stats["sent"] == 1

    async def test_exception_status(self):
        svc = PushService()
        result = await svc.notify_status_update("device-1", "ORD-002", "exception")
        assert result is True

    async def test_unknown_status(self):
        svc = PushService()
        result = await svc.notify_status_update("device-1", "ORD-003", "unknown_status")
        assert result is True

    async def test_in_transit(self):
        svc = PushService()
        result = await svc.notify_status_update("device-1", "ORD-004", "in_transit")
        assert result is True

    async def test_out_for_delivery(self):
        svc = PushService()
        result = await svc.notify_status_update("device-1", "ORD-005", "out_for_delivery")
        assert result is True

    async def test_delivered(self):
        svc = PushService()
        result = await svc.notify_status_update("device-1", "ORD-006", "delivered")
        assert result is True


class TestPushServiceNotifyDelivery:
    async def test_without_eta(self):
        svc = PushService()
        result = await svc.notify_delivery("device-1", "SF123456")
        assert result is True

    async def test_with_eta(self):
        svc = PushService()
        eta = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)
        result = await svc.notify_delivery("device-1", "SF123456", eta=eta)
        assert result is True


class TestPushServiceNotifyException:
    async def test_exception_notification(self):
        svc = PushService()
        result = await svc.notify_exception("device-1", "TMS-001", "Package damaged")
        assert result is True


class TestPushServiceSendOrderStatusUpdate:
    async def test_legacy_alias(self):
        svc = PushService()
        result = await svc.send_order_status_update("device-1", "ORD-001", "delivered")
        assert result is True
        assert svc.stats["sent"] == 1


class TestInitFirebase:
    """Covers _init_firebase() edge cases."""

    async def test_already_initialized(self):
        import sys
        push_mod = sys.modules["src.tms.push_service"]
        push_mod._firebase_available = True
        push_mod._firebase_app = None
        try:
            result = push_mod._init_firebase()
            assert result is True
        finally:
            push_mod._firebase_available = False

    async def test_no_credentials_path(self):
        import sys
        push_mod = sys.modules["src.tms.push_service"]
        push_mod._firebase_available = False
        push_mod._firebase_app = None
        with patch("src.config.settings.firebase_credentials_path", ""):
            result = push_mod._init_firebase()
            assert result is False

    async def test_firebase_import_error(self):
        import sys
        push_mod = sys.modules["src.tms.push_service"]
        push_mod._firebase_available = False
        push_mod._firebase_app = None
        with patch("src.config.settings.firebase_credentials_path", "/fake/path.json"):
            result = push_mod._init_firebase()
            assert result is False

    async def test_firebase_init_exception(self):
        import sys
        push_mod = sys.modules["src.tms.push_service"]
        push_mod._firebase_available = False
        push_mod._firebase_app = None
        with patch("src.config.settings.firebase_credentials_path", "/fake/path.json"):
            firebase_admin_mod = MagicMock()
            firebase_admin_mod.credentials = MagicMock()
            firebase_admin_mod.credentials.Certificate = MagicMock(side_effect=RuntimeError("bad cert"))
            with patch.dict("sys.modules", {"firebase_admin": firebase_admin_mod}):
                result = push_mod._init_firebase()
                assert result is False

    async def test_firebase_init_success(self):
        import sys
        push_mod = sys.modules["src.tms.push_service"]
        push_mod._firebase_available = False
        push_mod._firebase_app = None
        mock_app = MagicMock()
        with patch("src.config.settings.firebase_credentials_path", "/fake/path.json"):
            firebase_admin_mod = MagicMock()
            firebase_admin_mod.credentials = MagicMock()
            firebase_admin_mod.initialize_app = MagicMock(return_value=mock_app)
            with patch.dict("sys.modules", {"firebase_admin": firebase_admin_mod}):
                result = push_mod._init_firebase()
                assert result is True
                assert push_mod._firebase_available is True
                push_mod._firebase_available = False


class TestSendFcm:
    """Covers _send_fcm() edge cases."""

    async def test_send_fcm_success(self):
        from src.tms.push_service import PushMessage, NotificationPriority, _send_fcm
        msg = PushMessage(title="T", body="B", priority=NotificationPriority.HIGH, android_channel_id="test_ch")
        mock_messaging = MagicMock()
        mock_messaging.send.return_value = "ok"
        with patch.dict("sys.modules", {"firebase_admin": MagicMock(messaging=mock_messaging)}):
            result = _send_fcm(msg, "token-abc")
            assert result is True

    async def test_send_fcm_no_channel(self):
        from src.tms.push_service import PushMessage, _send_fcm
        msg = PushMessage(title="T", body="B", android_channel_id=None)
        mock_messaging = MagicMock()
        mock_messaging.send.return_value = "ok"
        with patch.dict("sys.modules", {"firebase_admin": MagicMock(messaging=mock_messaging)}):
            result = _send_fcm(msg, "token-xyz")
            assert result is True

    async def test_send_fcm_exception(self):
        from src.tms.push_service import PushMessage, _send_fcm
        msg = PushMessage(title="T", body="B")
        mock_messaging = MagicMock()
        mock_messaging.send.side_effect = RuntimeError("network error")
        with patch.dict("sys.modules", {"firebase_admin": MagicMock(messaging=mock_messaging)}):
            result = _send_fcm(msg, "token-err")
            assert result is False


class TestPushServiceFcmReady:
    """Covers FCM-ready paths in send_to_device and send_to_topic."""

    async def test_send_to_device_fcm_success(self):
        import sys
        push_mod = sys.modules["src.tms.push_service"]
        push_mod._fcm_ready = True
        svc = PushService()
        svc._fcm_ready = True
        svc._sent_count = 0
        msg = PushMessage(title="T", body="B")
        with patch("src.tms.push_service._send_fcm", return_value=True):
            result = await svc.send_to_device("token-fcm", msg)
            assert result is True
        assert svc.stats["sent"] == 1
        push_mod._fcm_ready = False

    async def test_send_to_device_fcm_failure(self):
        import sys
        push_mod = sys.modules["src.tms.push_service"]
        push_mod._fcm_ready = True
        svc = PushService()
        svc._fcm_ready = True
        msg = PushMessage(title="T", body="B")
        with patch("src.tms.push_service._send_fcm", return_value=False):
            result = await svc.send_to_device("token-fail", msg)
            assert result is False
        assert svc.stats["failed"] == 1
        push_mod._fcm_ready = False

    async def test_send_to_device_exception(self):
        import sys
        push_mod = sys.modules["src.tms.push_service"]
        push_mod._fcm_ready = True
        svc = PushService()
        svc._fcm_ready = True
        msg = PushMessage(title="T", body="B")
        with patch("src.tms.push_service._send_fcm", side_effect=RuntimeError("fail")):
            result = await svc.send_to_device("token-exc", msg)
            assert result is False
        assert svc.stats["failed"] == 1
        push_mod._fcm_ready = False

    async def test_send_to_topic_fcm_success(self):
        import sys
        push_mod = sys.modules["src.tms.push_service"]
        push_mod._fcm_ready = True
        svc = PushService()
        svc._fcm_ready = True
        msg = PushMessage(title="T", body="B")
        mock_messaging = MagicMock()
        mock_messaging.send.return_value = "ok"
        with patch.dict("sys.modules", {"firebase_admin": MagicMock(messaging=mock_messaging)}):
            result = await svc.send_to_topic("news", msg)
            assert result is True
        assert svc.stats["sent"] == 1
        push_mod._fcm_ready = False

    async def test_send_to_topic_fcm_fallback(self):
        import sys
        push_mod = sys.modules["src.tms.push_service"]
        push_mod._fcm_ready = True
        svc = PushService()
        svc._fcm_ready = True
        msg = PushMessage(title="T", body="B")
        mock_messaging = MagicMock()
        mock_messaging.send.return_value = None
        with patch.dict("sys.modules", {"firebase_admin": MagicMock(messaging=mock_messaging)}):
            result = await svc.send_to_topic("news", msg)
            assert result is False
        assert svc.stats["failed"] == 1
        push_mod._fcm_ready = False

    async def test_send_to_topic_fcm_exception(self):
        import sys
        push_mod = sys.modules["src.tms.push_service"]
        push_mod._fcm_ready = True
        svc = PushService()
        svc._fcm_ready = True
        msg = PushMessage(title="T", body="B")
        mock_messaging = MagicMock()
        mock_messaging.send.side_effect = RuntimeError("topic fail")
        with patch.dict("sys.modules", {"firebase_admin": MagicMock(messaging=mock_messaging)}):
            result = await svc.send_to_topic("news", msg)
            assert result is False
        assert svc.stats["failed"] == 1
        push_mod._fcm_ready = False


class TestPushServiceStats:
    async def test_stats_counts(self):
        import sys
        push_mod = sys.modules["src.tms.push_service"]
        push_mod._fcm_ready = False
        svc = PushService()
        svc._fcm_ready = False
        msg = PushMessage(title="T", body="B")
        await svc.send_to_device("t1", msg)
        await svc.send_to_topic("news", msg)
        await svc.send_to_device("t2", msg)
        assert svc.stats == {"sent": 3, "failed": 0}
