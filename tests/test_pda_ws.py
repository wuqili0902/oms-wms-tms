from unittest.mock import AsyncMock, MagicMock

import pytest

from src.pda.ws import PdaConnectionManager


@pytest.fixture
def ws():
    m = MagicMock()
    m.accept = AsyncMock()
    m.send_text = AsyncMock()
    return m


@pytest.fixture
def mgr():
    return PdaConnectionManager()


class TestConnect:
    async def test_accepts_and_stores(self, mgr, ws):
        await mgr.connect("dev-1", ws)
        ws.accept.assert_awaited_once()
        assert len(mgr._active["dev-1"]) == 1
        assert mgr._active["dev-1"][0] is ws

    async def test_multiple_connections_same_device(self, mgr, ws):
        ws2 = MagicMock()
        ws2.accept = AsyncMock()
        await mgr.connect("dev-1", ws)
        await mgr.connect("dev-1", ws2)
        assert len(mgr._active["dev-1"]) == 2


class TestDisconnect:
    async def test_removes_connection(self, mgr, ws):
        await mgr.connect("dev-1", ws)
        mgr.disconnect("dev-1", ws)
        assert "dev-1" not in mgr._active

    async def test_keeps_other_connections(self, mgr, ws):
        ws2 = MagicMock()
        ws2.accept = AsyncMock()
        await mgr.connect("dev-1", ws)
        await mgr.connect("dev-1", ws2)
        mgr.disconnect("dev-1", ws)
        assert len(mgr._active["dev-1"]) == 1

    async def test_ignores_unknown_ws(self, mgr, ws):
        mgr.disconnect("dev-1", ws)
        assert "dev-1" not in mgr._active


class TestSendToDevice:
    async def test_sends_to_connected_device(self, mgr, ws):
        await mgr.connect("dev-1", ws)
        result = await mgr.send_to_device("dev-1", {"type": "test"})
        ws.send_text.assert_awaited_once()
        assert result is True

    async def test_noop_when_no_connections(self, mgr):
        result = await mgr.send_to_device("dev-1", {"type": "test"})
        assert result is False

    async def test_handles_websocket_disconnect(self, mgr, ws):
        from starlette.websockets import WebSocketDisconnect
        ws.send_text.side_effect = WebSocketDisconnect(code=1001)
        await mgr.connect("dev-1", ws)
        await mgr.send_to_device("dev-1", {"type": "test"})
        assert "dev-1" not in mgr._active

    async def test_handles_generic_exception(self, mgr, ws):
        ws.send_text.side_effect = Exception("Send failed")
        await mgr.connect("dev-1", ws)
        await mgr.send_to_device("dev-1", {"type": "test"})
        assert "dev-1" not in mgr._active

    async def test_only_removes_failed_connections(self, mgr, ws):
        ws2 = MagicMock()
        ws2.accept = AsyncMock()
        ws2.send_text = AsyncMock()
        ws.send_text.side_effect = Exception("closed")
        await mgr.connect("dev-1", ws)
        await mgr.connect("dev-1", ws2)
        await mgr.send_to_device("dev-1", {"type": "test"})
        assert len(mgr._active.get("dev-1", [])) == 1


class TestBroadcast:
    async def test_sends_to_all_devices(self, mgr, ws):
        ws2 = MagicMock()
        ws2.accept = AsyncMock()
        ws2.send_text = AsyncMock()
        await mgr.connect("dev-a", ws)
        await mgr.connect("dev-b", ws2)
        result = await mgr.broadcast({"type": "broadcast"})
        assert result == 2


    async def test_noop_when_no_devices(self, mgr):
        result = await mgr.broadcast({"type": "broadcast"})
        assert result == 0


class TestActiveCount:
    async def test_counts_connections(self, mgr, ws):
        assert mgr.active_count == 0
        await mgr.connect("dev-1", ws)
        assert mgr.active_count == 1

    async def test_after_disconnect(self, mgr, ws):
        await mgr.connect("dev-1", ws)
        mgr.disconnect("dev-1", ws)
        assert mgr.active_count == 0
