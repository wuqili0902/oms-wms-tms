from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.notification.models import NotificationChannel, NotificationType
from src.notification import service as notification_service


class TestCheckEnabled:
    def make_pref(self, ntype, channel, enabled):
        p = MagicMock()
        p.notification_type = ntype
        p.channel = channel
        p.enabled = enabled
        return p

    def test_enabled_matching_pref(self):
        prefs = [self.make_pref(NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.WEBSOCKET, True)]
        assert notification_service._check_enabled(prefs, NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.WEBSOCKET) is True

    def test_disabled_pref(self):
        prefs = [self.make_pref(NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.WEBSOCKET, False)]
        assert notification_service._check_enabled(prefs, NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.WEBSOCKET) is False

    def test_no_matching_pref_returns_true(self):
        prefs = [self.make_pref(NotificationType.LOW_STOCK_ALERT, NotificationChannel.EMAIL, False)]
        assert notification_service._check_enabled(prefs, NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.WEBSOCKET) is True

    def test_empty_prefs_returns_true(self):
        assert notification_service._check_enabled([], NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.WEBSOCKET) is True

    def test_multiple_prefs_matches_correct(self):
        prefs = [
            self.make_pref(NotificationType.LOW_STOCK_ALERT, NotificationChannel.EMAIL, False),
            self.make_pref(NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.WEBSOCKET, True),
        ]
        assert notification_service._check_enabled(prefs, NotificationType.LOW_STOCK_ALERT, NotificationChannel.EMAIL) is False
        assert notification_service._check_enabled(prefs, NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.WEBSOCKET) is True


class TestSendNotification:
    @patch("src.notification.service._do_send", new_callable=AsyncMock)
    async def test_with_db_passed(self, mock_do_send):
        mock_do_send.return_value = True
        db = AsyncMock(spec=AsyncSession)
        result = await notification_service.send_notification(
            "u1", NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.PUSH,
            "Title", "Body", data={"k": "v"}, user_email="a@b.com", db=db,
        )
        mock_do_send.assert_awaited_once_with(db, "u1", NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.PUSH, "Title", "Body", {"k": "v"}, "a@b.com")
        assert result is True

    @patch("src.notification.service.get_db_session")
    @patch("src.notification.service._do_send", new_callable=AsyncMock)
    async def test_without_db_creates_session(self, mock_do_send, mock_get_db_session):
        mock_do_send.return_value = True
        mock_session = AsyncMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_get_db_session.return_value = mock_cm
        result = await notification_service.send_notification(
            "u1", NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.PUSH,
            "Title", "Body", data=None, user_email=None, db=None,
        )
        mock_do_send.assert_awaited_once()
        assert result is True


class TestDoSend:
    @pytest.fixture
    def mock_db(self):
        return AsyncMock(spec=AsyncSession)

    async def test_disabled_preference_returns_false(self, mock_db):
        pref = MagicMock()
        pref.notification_type = NotificationType.ORDER_STATUS_CHANGE
        pref.channel = NotificationChannel.WEBSOCKET
        pref.enabled = False
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [pref]
        mock_db.execute.return_value = mock_result
        result = await notification_service._do_send(
            mock_db, "u1", NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.WEBSOCKET,
            "Title", "Body", None, None,
        )
        assert result is False
        mock_db.add.assert_not_called()

    async def test_websocket_channel(self, mock_db):
        pref = MagicMock()
        pref.notification_type = NotificationType.ORDER_STATUS_CHANGE
        pref.channel = NotificationChannel.WEBSOCKET
        pref.enabled = True
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [pref]
        mock_db.execute.return_value = mock_result
        with patch("src.notification.service.ws_manager.send_to_user", new_callable=AsyncMock) as mock_ws:
            result = await notification_service._do_send(
                mock_db, "u1", NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.WEBSOCKET,
                "Title", "Body", {"k": "v"}, None,
            )
        assert result is True
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        mock_ws.assert_awaited_once()

    async def test_email_channel_with_no_email_skips(self, mock_db):
        pref = MagicMock()
        pref.notification_type = NotificationType.LOW_STOCK_ALERT
        pref.channel = NotificationChannel.EMAIL
        pref.enabled = True
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [pref]
        mock_db.execute.return_value = mock_result
        with patch("src.notification.service.email_service.send", new_callable=AsyncMock) as mock_email:
            result = await notification_service._do_send(
                mock_db, "u1", NotificationType.LOW_STOCK_ALERT, NotificationChannel.EMAIL,
                "Stock Alert", "Low", None, None,
            )
        assert result is True
        mock_email.assert_not_called()

    async def test_email_channel_with_email_sends(self, mock_db):
        pref = MagicMock()
        pref.notification_type = NotificationType.LOW_STOCK_ALERT
        pref.channel = NotificationChannel.EMAIL
        pref.enabled = True
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [pref]
        mock_db.execute.return_value = mock_result
        with patch("src.notification.service.email_service.send", new_callable=AsyncMock) as mock_email:
            result = await notification_service._do_send(
                mock_db, "u1", NotificationType.LOW_STOCK_ALERT, NotificationChannel.EMAIL,
                "Stock Alert", "Low", None, "user@example.com",
            )
        assert result is True
        mock_email.assert_awaited_once()

    async def test_handles_exception_gracefully(self, mock_db):
        mock_db.execute.side_effect = Exception("DB error")
        result = await notification_service._do_send(
            mock_db, "u1", NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.WEBSOCKET,
            "Title", "Body", None, None,
        )
        assert result is False

    async def test_database_channel_no_extra(self, mock_db):
        pref = MagicMock()
        pref.notification_type = NotificationType.ORDER_STATUS_CHANGE
        pref.channel = NotificationChannel.PUSH
        pref.enabled = True
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [pref]
        mock_db.execute.return_value = mock_result
        result = await notification_service._do_send(
            mock_db, "u1", NotificationType.ORDER_STATUS_CHANGE, NotificationChannel.PUSH,
            "Title", "Body", None, None,
        )
        assert result is True
        mock_db.add.assert_called_once()


class TestNotifyOrderStatusChange:
    @patch("src.notification.service.send_notification", new_callable=AsyncMock)
    async def test_calls_send_notification(self, mock_send):
        await notification_service.notify_order_status_change(1, "u1", "shipped", "ORD-001", MagicMock())
        mock_send.assert_awaited_once()
        args, kwargs = mock_send.call_args
        assert kwargs["ntype"] == NotificationType.ORDER_STATUS_CHANGE
        assert kwargs["channel"] == NotificationChannel.WEBSOCKET
        assert "已发货" in kwargs["body"]


class TestNotifyLowStock:
    @patch("src.notification.service.send_notification", new_callable=AsyncMock)
    async def test_sends_to_all_active_users(self, mock_send):
        db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.all.return_value = [("user-1", "a@b.com"), ("user-2", "c@d.com")]
        db.execute.return_value = mock_result

        await notification_service.notify_low_stock("wh1", "SKU-001", 5, db)

        assert mock_send.call_count == 2
        call1 = mock_send.call_args_list[0]
        assert call1.kwargs["user_id"] == "user-1"
        assert call1.kwargs["user_email"] == "a@b.com"
        assert call1.kwargs["ntype"] == NotificationType.LOW_STOCK_ALERT
        assert call1.kwargs["channel"] == NotificationChannel.EMAIL
        assert call1.kwargs["title"] == "库存预警"
        assert "SKU-001" in call1.kwargs["body"]
        assert call1.kwargs["data"]["current_qty"] == 5

        call2 = mock_send.call_args_list[1]
        assert call2.kwargs["user_id"] == "user-2"
        assert call2.kwargs["user_email"] == "c@d.com"

    @patch("src.notification.service.send_notification", new_callable=AsyncMock)
    async def test_no_active_users_skips(self, mock_send):
        db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute.return_value = mock_result

        await notification_service.notify_low_stock("wh1", "SKU-001", 5, db)

        mock_send.assert_not_called()
