import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._active: dict[int, list[WebSocket]] = {}

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        self._active.setdefault(user_id, []).append(ws)
        logger.debug("WebSocket connected: user_id=%d", user_id)

    def disconnect(self, user_id: int, ws: WebSocket):
        conns = self._active.get(user_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self._active.pop(user_id, None)
        logger.debug("WebSocket disconnected: user_id=%d", user_id)

    async def send_to_user(self, user_id: int, payload: dict[str, Any]):
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
                logger.warning("WebSocket send error user=%d: %s", user_id, e)
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
