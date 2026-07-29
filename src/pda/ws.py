"""PDA WebSocket channel for real-time offline-queue updates."""

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class PdaConnectionManager:
    """Manages per-device WebSocket connections for PDA offline sync."""

    def __init__(self):
        self._active: dict[str, list[WebSocket]] = {}

    async def connect(self, device_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._active.setdefault(device_id, []).append(ws)
        logger.debug("PDA WS connected: device_id=%s", device_id)

    def disconnect(self, device_id: str, ws: WebSocket) -> None:
        conns = self._active.get(device_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self._active.pop(device_id, None)
        logger.debug("PDA WS disconnected: device_id=%s", device_id)

    async def send_to_device(self, device_id: str, payload: dict[str, Any]) -> bool:
        """Push an event to a single device; returns True if at least one connection received."""
        conns = self._active.get(device_id, [])
        if not conns:
            return False
        message = json.dumps(payload, ensure_ascii=False)
        stale = []
        for ws in conns:
            try:
                await ws.send_text(message)
            except WebSocketDisconnect:
                stale.append(ws)
            except Exception as e:
                logger.warning("PDA WS send error device=%s: %s", device_id, e)
                stale.append(ws)
        for ws in stale:
            self.disconnect(device_id, ws)
        # Note: conns - stale is a set view (set difference), not tuple subtraction.
        return len([w for w in conns if w not in stale]) > 0


    async def broadcast(self, payload: dict[str, Any]) -> int:
        """Send an event to all connected PDAs; returns the count of successful deliveries."""
        delivered = 0
        for device_id in list(self._active.keys()):
            if await self.send_to_device(device_id, payload):
                delivered += 1
        return delivered

    @property
    def active_count(self) -> int:
        """Number of currently connected devices."""
        return sum(len(conns) for conns in self._active.values())


# Singleton instance shared across the app.
_manager = PdaConnectionManager()
