"""Tests for src.core.ws_fanout — cross-process WebSocket fan-out (Redis pub/sub)."""
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from src.config import settings
from src.core.ws_fanout import (
    NOTIFY_CHANNEL,
    PDA_CHANNEL,
    WsFanoutSubscriber,
    publish_notify,
    publish_pda,
)


def _fake_redis_getter(monkeypatch, captured):
    from src.cache import redis_client as rc

    class _FakeRedis:
        async def publish(self, channel, message):
            captured.append((channel, json.loads(message)))

    @asynccontextmanager
    async def _get():
        yield _FakeRedis()

    monkeypatch.setattr(rc, "get_redis", _get)


def _broken_redis_getter(monkeypatch):
    from src.cache import redis_client as rc

    @asynccontextmanager
    async def _get():
        raise ConnectionError("redis down")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(rc, "get_redis", _get)


class TestPublishers:
    async def test_publish_disabled_in_testing_mode(self, monkeypatch):
        # conftest sets settings.testing=True → publishers short-circuit so
        # in-process tests deliver directly via the local WS managers.
        assert settings.testing is True
        captured = []
        _fake_redis_getter(monkeypatch, captured)
        assert await publish_notify("u", {}) is False
        assert await publish_pda(None, {}) is False
        assert captured == []

    async def test_publish_notify_envelope(self, monkeypatch):
        monkeypatch.setattr(settings, "testing", False)
        captured = []
        _fake_redis_getter(monkeypatch, captured)
        assert await publish_notify("user-1", {"title": "hi"}) is True
        assert captured == [(NOTIFY_CHANNEL, {"user_id": "user-1", "payload": {"title": "hi"}})]

    async def test_publish_pda_broadcast_envelope(self, monkeypatch):
        monkeypatch.setattr(settings, "testing", False)
        captured = []
        _fake_redis_getter(monkeypatch, captured)
        assert await publish_pda(None, {"mutation_id": "m1"}) is True
        assert captured == [(PDA_CHANNEL, {"device_id": None, "payload": {"mutation_id": "m1"}})]

    async def test_publish_returns_false_when_redis_down(self, monkeypatch):
        monkeypatch.setattr(settings, "testing", False)
        _broken_redis_getter(monkeypatch)
        assert await publish_notify("u", {}) is False
        assert await publish_pda("d", {}) is False


class TestSubscriberDelivery:
    async def test_notify_to_specific_user(self, monkeypatch):
        from src.notification.ws import ws_manager

        send_mock = AsyncMock()
        monkeypatch.setattr(ws_manager, "send_to_user", send_mock)
        monkeypatch.setattr(ws_manager, "broadcast", AsyncMock())

        sub = WsFanoutSubscriber()
        await sub._handle_message({
            "channel": NOTIFY_CHANNEL.encode(),
            "data": json.dumps({"user_id": "u9", "payload": {"t": 1}}),
        })
        send_mock.assert_awaited_once_with("u9", {"t": 1})

    async def test_notify_broadcast_when_user_none(self, monkeypatch):
        from src.notification.ws import ws_manager

        send_mock = AsyncMock()
        broadcast_mock = AsyncMock()
        monkeypatch.setattr(ws_manager, "send_to_user", send_mock)
        monkeypatch.setattr(ws_manager, "broadcast", broadcast_mock)

        sub = WsFanoutSubscriber()
        await sub._handle_message({
            "channel": NOTIFY_CHANNEL,
            "data": json.dumps({"user_id": None, "payload": {"t": 2}}),
        })
        broadcast_mock.assert_awaited_once_with({"t": 2})
        send_mock.assert_not_awaited()

    async def test_pda_to_specific_device(self, monkeypatch):
        from src.pda.ws import _manager

        send_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(_manager, "send_to_device", send_mock)

        sub = WsFanoutSubscriber()
        await sub._handle_message({
            "channel": PDA_CHANNEL.encode(),
            "data": json.dumps({"device_id": "d1", "payload": {"o": "sync"}}),
        })
        send_mock.assert_awaited_once_with("d1", {"o": "sync"})

    async def test_pda_broadcast_when_device_none(self, monkeypatch):
        from src.pda.ws import _manager

        broadcast_mock = AsyncMock(return_value=0)
        monkeypatch.setattr(_manager, "broadcast", broadcast_mock)

        sub = WsFanoutSubscriber()
        await sub._handle_message({
            "channel": PDA_CHANNEL,
            "data": json.dumps({"device_id": None, "payload": {"o": "all"}}),
        })
        broadcast_mock.assert_awaited_once_with({"o": "all"})

    async def test_malformed_envelope_ignored(self, monkeypatch):
        from src.notification.ws import ws_manager

        send_mock = AsyncMock()
        monkeypatch.setattr(ws_manager, "send_to_user", send_mock)

        sub = WsFanoutSubscriber()
        await sub._handle_message({"channel": NOTIFY_CHANNEL.encode(), "data": b"not-json"})
        send_mock.assert_not_awaited()

    async def test_unknown_channel_ignored(self, monkeypatch):
        from src.notification.ws import ws_manager
        from src.pda.ws import _manager

        n_mock = AsyncMock()
        p_mock = AsyncMock()
        monkeypatch.setattr(ws_manager, "send_to_user", n_mock)
        monkeypatch.setattr(ws_manager, "broadcast", n_mock)
        monkeypatch.setattr(_manager, "send_to_device", p_mock)
        monkeypatch.setattr(_manager, "broadcast", p_mock)

        sub = WsFanoutSubscriber()
        await sub._handle_message({
            "channel": b"some:other",
            "data": json.dumps({"user_id": "u", "payload": {}}),
        })
        n_mock.assert_not_awaited()
        p_mock.assert_not_awaited()


class TestSubscriberLifecycle:
    async def test_start_disabled_without_redis_url(self, monkeypatch):
        monkeypatch.setattr(settings, "redis_url", "")
        sub = WsFanoutSubscriber()
        await sub.start()
        assert sub._task is None
        assert sub._client is None
        await sub.stop()  # must be safe on a never-started subscriber
