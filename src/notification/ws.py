import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._active: dict[str, list[WebSocket]] = {}

    async def connect(self, user_id: str, ws: WebSocket):
        await ws.accept()
        # Evict stale connections if user already has max 3 (prevents duplicate sends)
        conns = self._active.get(user_id, [])
        while len(conns) >= 3:
            old_ws = conns.pop(0)
            try:
                await old_ws.close()
            except Exception:
                pass
        # Prevent duplicate WebSocket for same user (idempotent connect)
        if ws in conns:
            return
        self._active.setdefault(user_id, []).append(ws)

    def disconnect(self, user_id: str, ws: WebSocket):
        conns = self._active.get(user_id, [])
        # Remove ALL matching stale connections for this ws object
        while ws in conns:
            conns.remove(ws)
        if not conns:
            self._active.pop(user_id, None)
        logger.debug("WebSocket disconnected: user_id=%s", user_id)

    async def send_to_user(self, user_id: str, payload: dict[str, Any]):
        conns = self._active.get(user_id, [])
        if not conns:
            return
        message = json.dumps(payload, ensure_ascii=False)
        stale = []
        for ws in conns:
            try:
                await ws.send_text(message)
            except WebSocketDisconnect:
                stale.append(ws)
            except Exception as e:
                logger.warning("WebSocket send error user=%s: %s", user_id, e)
                stale.append(ws)
        for ws in stale:
            self.disconnect(user_id, ws)

    async def broadcast(self, payload: dict[str, Any]):
        for user_id in list(self._active.keys()):
            await self.send_to_user(user_id, payload)

    @property
    def active_connections(self) -> int:
        return sum(len(conns) for conns in self._active.values())


ws_manager = ConnectionManager()
