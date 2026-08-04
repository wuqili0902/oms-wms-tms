from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocket
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.main import app
from src.notification.models import Notification, NotificationChannel, NotificationPreference, NotificationType
from src.notification.router import notification_websocket


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_user():
    return {"uid": "user123", "username": "testuser"}


@pytest.fixture
def override_deps(mock_db, mock_user):
    async def _get_db():
        return mock_db

    async def _get_current_user():
        return mock_user

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_current_user
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(override_deps):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestListNotifications:
    async def test_returns_paginated_notifications(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            Notification(
                id=1, user_id="user123", type=NotificationType.SYSTEM_ALERT,
                channel=NotificationChannel.WEBSOCKET, title="T1", body="B1",
                data=None, is_read=False, created_at=None,
            ),
        ]
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        async def execute_side_effect(query):
            qs = str(query)
            if "count" in qs.lower():
                return mock_count_result
            return mock_result

        mock_db.execute = AsyncMock(side_effect=execute_side_effect)

        resp = await client.get("/api/v1/notifications/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["total"] == 1
        assert data["data"]["items"][0]["title"] == "T1"

    async def test_filters_unread_only(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        async def execute_side_effect(query):
            qs = str(query)
            if "count" in qs.lower():
                return mock_count_result
            return mock_result

        mock_db.execute = AsyncMock(side_effect=execute_side_effect)

        resp = await client.get("/api/v1/notifications/?unread_only=true")

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["total"] == 0

    async def test_list_uses_query_params(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        async def execute_side_effect(query):
            qs = str(query)
            if "count" in qs.lower():
                return mock_count_result
            return mock_result

        mock_db.execute = AsyncMock(side_effect=execute_side_effect)

        resp = await client.get("/api/v1/notifications/?page=2&page_size=10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["page"] == 2
        assert data["data"]["page_size"] == 10

    async def test_list_notifications_with_no_data(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        async def execute_side_effect(query):
            qs = str(query)
            if "count" in qs.lower():
                return mock_count_result
            return mock_result

        mock_db.execute = AsyncMock(side_effect=execute_side_effect)

        resp = await client.get("/api/v1/notifications/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["items"] == []


class TestMarkRead:
    async def test_marks_notification_as_read(self, client, mock_db):
        mock_db.commit = AsyncMock()

        resp = await client.post("/api/v1/notifications/1/read")

        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Marked as read"
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

    async def test_mark_read_updates_correct_notification(self, client, mock_db):
        mock_db.commit = AsyncMock()

        await client.post("/api/v1/notifications/42/read")

        call_args = mock_db.execute.call_args[0][0]
        qs = str(call_args)
        assert "notifications" in qs
        assert "is_read" in qs.lower()


class TestMarkAllRead:
    async def test_marks_all_as_read(self, client, mock_db):
        mock_db.commit = AsyncMock()

        resp = await client.post("/api/v1/notifications/read-all")

        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "All marked as read"
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

    async def test_mark_all_read_updates_unread(self, client, mock_db):
        mock_db.commit = AsyncMock()

        await client.post("/api/v1/notifications/read-all")

        call_args = mock_db.execute.call_args[0][0]
        qs = str(call_args)
        assert "is_read" in qs.lower()


class TestGetPreferences:
    async def test_returns_preferences(self, client, mock_db):
        pref = NotificationPreference(
            id=1, user_id="user123",
            notification_type=NotificationType.SYSTEM_ALERT,
            channel=NotificationChannel.WEBSOCKET,
            enabled=False,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [pref]
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.get("/api/v1/notifications/preferences")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["notification_type"] == "system_alert"
        assert data["data"][0]["enabled"] is False

    async def test_get_preferences_empty(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.get("/api/v1/notifications/preferences")

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == []


class TestUpdatePreferences:
    async def test_updates_preferences(self, client, mock_db):
        mock_db.commit = AsyncMock()
        prefs = [
            {"notification_type": "system_alert", "channel": "websocket", "enabled": True},
        ]

        resp = await client.put("/api/v1/notifications/preferences", json=prefs)

        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Preferences updated"
        mock_db.execute.assert_awaited_once()
        assert mock_db.add.called
        mock_db.commit.assert_awaited_once()

    async def test_update_preferences_adds_objects(self, client, mock_db):
        mock_db.commit = AsyncMock()
        prefs = [
            {"notification_type": "order_status_change", "channel": "email", "enabled": False},
            {"notification_type": "low_stock_alert", "channel": "email", "enabled": True},
        ]

        await client.put("/api/v1/notifications/preferences", json=prefs)

        added = [call.args[0] for call in mock_db.add.call_args_list]
        assert len(added) == 2
        assert isinstance(added[0], NotificationPreference)

    async def test_update_preferences_with_default_enabled(self, client, mock_db):
        mock_db.commit = AsyncMock()
        prefs = [
            {"notification_type": "system_alert", "channel": "websocket"},
        ]

        await client.put("/api/v1/notifications/preferences", json=prefs)

        added = [call.args[0] for call in mock_db.add.call_args_list]
        assert len(added) == 1
        assert added[0].enabled is True


class TestWebSocket:
    async def test_no_token_closes_4001(self):
        ws = AsyncMock(spec=WebSocket)
        ws.query_params = {}

        await notification_websocket(ws)

        ws.close.assert_awaited_once_with(code=4001)

    @patch("src.core.security.decode_token")
    async def test_invalid_token_closes_4001(self, mock_decode):
        mock_decode.side_effect = ValueError("bad")
        ws = AsyncMock(spec=WebSocket)
        ws.query_params = {"token": "bad"}

        await notification_websocket(ws)

        ws.close.assert_awaited_once_with(code=4001)

    @patch("src.core.security.decode_token")
    async def test_missing_uid_closes_4001(self, mock_decode):
        mock_decode.return_value = {}
        ws = AsyncMock(spec=WebSocket)
        ws.query_params = {"token": "x"}

        await notification_websocket(ws)

        ws.close.assert_awaited_once_with(code=4001)

    @patch("src.notification.router.ws_manager.connect")
    @patch("src.core.security.decode_token")
    async def test_connect_calls_manager(self, mock_decode, mock_connect):
        mock_decode.return_value = {"uid": "user123"}
        mock_connect.return_value = None
        ws = AsyncMock(spec=WebSocket)
        ws.query_params = {"token": "valid"}

        async def receive_text():
            raise Exception("done")

        ws.receive_text = receive_text

        await notification_websocket(ws)

        mock_connect.assert_awaited_once_with("user123", ws)

    @patch("src.notification.router.ws_manager.disconnect")
    @patch("src.notification.router.ws_manager.connect")
    @patch("src.core.security.decode_token")
    async def test_disconnect_cleans_up(self, mock_decode, mock_connect, mock_disconnect):
        from fastapi import WebSocketDisconnect
        mock_decode.return_value = {"uid": "user123"}
        ws = AsyncMock(spec=WebSocket)
        ws.query_params = {"token": "valid"}

        async def receive_text():
            raise WebSocketDisconnect()

        ws.receive_text = receive_text

        await notification_websocket(ws)

        mock_disconnect.assert_called_once_with("user123", ws)

    @patch("src.notification.router.ws_manager.disconnect")
    @patch("src.notification.router.ws_manager.connect")
    @patch("src.core.security.decode_token")
    async def test_unknown_exception_logs_and_disconnects(self, mock_decode, mock_connect, mock_disconnect):
        mock_decode.return_value = {"uid": "user123"}
        ws = AsyncMock(spec=WebSocket)
        ws.query_params = {"token": "valid"}

        async def receive_text():
            raise RuntimeError("unexpected")

        ws.receive_text = receive_text

        await notification_websocket(ws)

        mock_connect.assert_awaited_once()
        mock_disconnect.assert_called_once_with("user123", ws)

    @patch("src.notification.router.ws_manager.disconnect")
    @patch("src.notification.router.ws_manager.connect")
    @patch("src.core.security.decode_token")
    async def test_logs_received_message(self, mock_decode, mock_connect, mock_disconnect):
        from src.notification.router import logger
        mock_decode.return_value = {"uid": "user123"}
        ws = AsyncMock(spec=WebSocket)
        ws.query_params = {"token": "valid"}

        call_count = 0

        async def receive_text():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "ping"
            raise RuntimeError("done")

        ws.receive_text = receive_text

        with patch.object(logger, "debug") as mock_log:
            await notification_websocket(ws)
            assert mock_log.called

    @patch("src.core.security.decode_token")
    async def test_uid_none_closes_4001(self, mock_decode):
        mock_decode.return_value = {"uid": None}
        ws = AsyncMock(spec=WebSocket)
        ws.query_params = {"token": "x"}

        await notification_websocket(ws)

        ws.close.assert_awaited_once_with(code=4001)
