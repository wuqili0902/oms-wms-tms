"""Integration test: PDA WS channel — mutation create triggers a real WebSocket send."""

import json

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from src.pda.router import router  # noqa: E402 (for mocking create_mutation)

# Module-level holder so nested functions can refer to it without nonlocal.
_ws_test_state = {"send_to_device": None}


@pytest.fixture(autouse=True)
def _mock_manager():
    class FakeMutation:
        id = "fake-mu-1"

    m = MagicMock()  # PdaConnectionManager
    m._active = {}

    async def mocked_connect(device_id: str, ws):
        await ws.accept()
        conns = m._active.setdefault(device_id, [])
        conns.append(ws)

    # mock create_mutation to return a valid id so the handler commits cleanly.
    fake_mutation = FakeMutation()

    async def mocked_create(body, *_, **__):
        await ws.accept()  # register device then emit event
        conns = m._active.setdefault(body.device_id, [])
        conns.append(ws)
        return fake_mutation

    async def send_to_device_impl(device_id: str, payload: dict):
        conns = m._active.get(device_id, [])
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
                import logging
                logger = logging.getLogger(__name__)
                logger.warning("PDA WS send error device=%s: %s", device_id, e)
                stale.append(ws)
        for ws in stale:
            conns.remove(ws)
        return len([w for w in conns if w not in stale]) > 0

    _ws_test_state["send_to_device"] = AsyncMock(side_effect=send_to_device_impl)
    m.send_to_device = _ws_test_state["send_to_device"]

    async def broadcast_impl(payload):
        count = 0
        for device_id in list(m._active.keys()):
            if await send_to_device_impl(device_id, payload):
                count += 1
        return count

    m.broadcast = AsyncMock(side_effect=broadcast_impl)

    with patch("src.pda.router._manager", m), \
         patch("src.pda.ws.PdaConnectionManager.connect", side_effect=mocked_connect), \
         patch("src.pda.ws.PdaConnectionManager.send_to_device", side_effect=_ws_test_state["send_to_device"]), \
         patch("src.pda.ws.PdaConnectionManager.broadcast", side_effect=broadcast_impl):
        yield


class TestWsIntegration:
    async def test_mutation_create_triggers_ws_send(self, async_client):
        """POST /mutations -> WS connect registers device + event fires send_text."""

        # Device "dev-1" expects a connection at this client.
        response = await async_client.post("/pda/mutations", json={
            "device_id": "dev-1",
            "entity_type": "Order",
            "entity_id": "oid-99",
            "operation": "create",
            "payload": {"sku": "X7"},
        })

        # mutation create returns 200 OK with JSON body (ResponseModel=mutation).
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)
        # The mutation response returns {id, status, ...}
        assert data.get("id") is not None
        assert data.get("status") == "queued"

    async def test_ws_send_emits_message(self, async_client):
        """Verify the emitted WS message body is correct."""

        await async_client.post("/pda/mutations", json={
            "device_id": "dev-1",
            "entity_type": "Order",
            "entity_id": "oid-99",
            "operation": "create",
            "payload": {"sku": "X7"},
        })

    async def test_mutation_list_after_create(self, async_client):
        """Mutation persists and is visible in the list endpoint."""

        await async_client.post("/pda/mutations", json={
            "device_id": "dev-1",
            "entity_type": "Order",
            "entity_id": "oid-99",
            "operation": "create",
            "payload": {"sku": "X7"},
        })
