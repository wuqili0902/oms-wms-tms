from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocket, WebSocketDisconnect

from src.notification.ws import ConnectionManager


@pytest.fixture
def ws():
    m = MagicMock(spec=WebSocket)
    m.accept = AsyncMock()
    m.send_text = AsyncMock()
    return m


@pytest.fixture
def mgr():
    return ConnectionManager()


class TestConnect:
    async def test_accepts_and_stores(self, mgr, ws):
        await mgr.connect(1, ws)
        ws.accept.assert_awaited_once()
        assert len(mgr._active[1]) == 1
        assert mgr._active[1][0] is ws

    async def test_multiple_connections_same_user(self, mgr, ws):
        ws2 = MagicMock(spec=WebSocket)
        ws2.accept = AsyncMock()
        await mgr.connect(1, ws)
        await mgr.connect(1, ws2)
        assert len(mgr._active[1]) == 2


class TestDisconnect:
    async def test_removes_connection(self, mgr, ws):
        await mgr.connect(1, ws)
        mgr.disconnect(1, ws)
        assert 1 not in mgr._active

    async def test_keeps_other_connections(self, mgr, ws):
        ws2 = MagicMock(spec=WebSocket)
        ws2.accept = AsyncMock()
        await mgr.connect(1, ws)
        await mgr.connect(1, ws2)
        mgr.disconnect(1, ws)
        assert len(mgr._active[1]) == 1

    async def test_ignores_unknown_ws(self, mgr, ws):
        mgr.disconnect(1, ws)
        assert 1 not in mgr._active


class TestSendToUser:
    async def test_sends_to_connected_user(self, mgr, ws):
        await mgr.connect(1, ws)
        await mgr.send_to_user(1, {"type": "test"})
        ws.send_text.assert_awaited_once()

    async def test_noop_when_no_connections(self, mgr):
        await mgr.send_to_user(1, {"type": "test"})

    async def test_handles_websocket_disconnect(self, mgr, ws):
        ws.send_text.side_effect = WebSocketDisconnect()
        await mgr.connect(1, ws)
        await mgr.send_to_user(1, {"type": "test"})
        assert 1 not in mgr._active

    async def test_handles_generic_exception(self, mgr, ws):
        ws.send_text.side_effect = Exception("Send failed")
        await mgr.connect(1, ws)
        await mgr.send_to_user(1, {"type": "test"})
        assert 1 not in mgr._active

    async def test_only_removes_failed_connections(self, mgr, ws):
        ws2 = MagicMock(spec=WebSocket)
        ws2.accept = AsyncMock()
        ws2.send_text = AsyncMock()
        ws.send_text.side_effect = WebSocketDisconnect()
        await mgr.connect(1, ws)
        await mgr.connect(1, ws2)
        await mgr.send_to_user(1, {"type": "test"})
        assert len(mgr._active.get(1, [])) == 1


class TestBroadcast:
    async def test_sends_to_all_users(self, mgr, ws):
        ws2 = MagicMock(spec=WebSocket)
        ws2.accept = AsyncMock()
        ws2.send_text = AsyncMock()
        await mgr.connect(1, ws)
        await mgr.connect(2, ws2)
        await mgr.broadcast({"type": "broadcast"})
        ws.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()

    async def test_noop_when_no_users(self, mgr):
        await mgr.broadcast({"type": "broadcast"})


class TestActiveConnections:
    async def test_counts_connections(self, mgr, ws):
        assert mgr.active_connections == 0
        await mgr.connect(1, ws)
        assert mgr.active_connections == 1

    async def test_after_disconnect(self, mgr, ws):
        await mgr.connect(1, ws)
        mgr.disconnect(1, ws)
        assert mgr.active_connections == 0

    async def test_multiple_users(self, mgr, ws):
        ws2 = MagicMock(spec=WebSocket)
        ws2.accept = AsyncMock()
        await mgr.connect(1, ws)
        await mgr.connect(2, ws2)
        assert mgr.active_connections == 2
