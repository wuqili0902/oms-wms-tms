"""Cross-process WebSocket fan-out via Redis pub/sub.

With multiple API workers (uvicorn ``--workers N``, gunicorn, or multiple
containers behind the load balancer) — plus Celery dispatch arriving over
HTTP — the process that handles the write is frequently *not* the process a
given WebSocket client happens to be connected to.  In-process managers
therefore silently drop deliveries.

Design:
    1. Senders publish a delivery envelope to a Redis channel instead of
       touching the local manager.
    2. Every API process runs a subscriber (started in the app lifespan)
       that receives the envelope and delivers it to *its own* connected
       sockets.
    3. If Redis is unavailable, ``publish_*`` returns False and the caller
       falls back to direct local delivery — behaviour degrades to the old
       in-process semantics, never to a dropped message or an exception.

Channels:
    ws:notify  {"user_id": str | None, "payload": {...}}   (None = broadcast)
    ws:pda     {"device_id": str | None, "payload": {...}} (None = broadcast)
"""

import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from src.config import settings

logger = logging.getLogger(__name__)

NOTIFY_CHANNEL = "ws:notify"
PDA_CHANNEL = "ws:pda"

_RECONNECT_BACKOFF_SECONDS = 2.0


async def _publish(channel: str, envelope: dict[str, Any]) -> bool:
    """Publish an envelope; True on success, False when Redis is unavailable.

    In testing mode a live Redis may exist on the machine, but no fan-out
    subscriber runs inside the test process — publishing there would strand
    deliveries.  Tests therefore always take the direct local-delivery path;
    the pub/sub itself is covered by tests/test_ws_fanout.py unit tests.
    """
    if settings.testing:
        return False
    try:
        from src.cache.redis_client import get_redis

        async with get_redis() as r:
            await r.publish(channel, json.dumps(envelope, ensure_ascii=False))
        return True
    except Exception as exc:
        logger.warning("WS fan-out publish failed on %s: %s", channel, exc)
        return False


async def publish_notify(user_id: str | None, payload: dict[str, Any]) -> bool:
    """Request delivery of a notification payload to one user (or all)."""
    return await _publish(NOTIFY_CHANNEL, {"user_id": user_id, "payload": payload})


async def publish_pda(device_id: str | None, payload: dict[str, Any]) -> bool:
    """Request delivery of a PDA payload to one device (or all)."""
    return await _publish(PDA_CHANNEL, {"device_id": device_id, "payload": payload})


async def _deliver_notify(envelope: dict[str, Any]) -> None:
    from src.notification.ws import ws_manager

    payload = envelope.get("payload") or {}
    user_id = envelope.get("user_id")
    if user_id:
        await ws_manager.send_to_user(user_id, payload)
    else:
        await ws_manager.broadcast(payload)


async def _deliver_pda(envelope: dict[str, Any]) -> None:
    from src.pda.ws import _manager

    payload = envelope.get("payload") or {}
    device_id = envelope.get("device_id")
    if device_id:
        await _manager.send_to_device(device_id, payload)
    else:
        await _manager.broadcast(payload)


class WsFanoutSubscriber:
    """Background subscriber that feeds this process's WS managers from Redis."""

    def __init__(self):
        self._client: aioredis.Redis | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not settings.redis_url:
            logger.info("WS fan-out disabled (no REDIS_URL configured)")
            return
        # Dedicated client: pub/sub pins its connection for the subscription's
        # lifetime and must not occupy a slot of the shared request pool.
        self._client = aioredis.from_url(
            settings.redis_url,
            socket_timeout=5.0,
            socket_connect_timeout=2.0,
        )
        self._task = asyncio.create_task(self._run(), name="ws-fanout-subscriber")

    async def _run(self) -> None:
        while True:
            try:
                pubsub = self._client.pubsub()
                await pubsub.subscribe(NOTIFY_CHANNEL, PDA_CHANNEL)
                logger.info("WS fan-out subscriber listening on %s / %s", NOTIFY_CHANNEL, PDA_CHANNEL)
                while True:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if message is None:
                        continue
                    await self._handle_message(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "WS fan-out subscriber error (%s); retrying in %.1fs",
                    exc, _RECONNECT_BACKOFF_SECONDS,
                )
                await asyncio.sleep(_RECONNECT_BACKOFF_SECONDS)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Decode one pubsub message and deliver it to the local managers."""
        raw = message.get("data")
        if raw is None:
            return
        try:
            envelope = json.loads(raw)
        except (TypeError, ValueError) as exc:
            logger.warning("WS fan-out: malformed envelope ignored: %s", exc)
            return

        channel = message.get("channel")
        if isinstance(channel, bytes):
            channel = channel.decode("utf-8")

        if channel == NOTIFY_CHANNEL:
            await _deliver_notify(envelope)
        elif channel == PDA_CHANNEL:
            await _deliver_pda(envelope)
        else:
            logger.debug("WS fan-out: unknown channel %s ignored", channel)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None


ws_fanout = WsFanoutSubscriber()
