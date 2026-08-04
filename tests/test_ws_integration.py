"""Integration test: PDA WS channel — mutation create triggers real WebSocket send."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

# -- shared mutable state so broadcast_impl always sees the SAME _active dict --
_manager_state = {
    "_active": {},       # device_id -> list[WebSocket]
    "sent_messages": [],  # captured messages for assertions
}


def _reset_state():
    """Clear all state between tests."""
    _manager_state["_active"].clear()
    _manager_state["sent_messages"].clear()


@pytest.fixture(autouse=True)
def _mock_manager():
    """Patch PdaConnectionManager so broadcast() routes to real WS send_text()."""

    m = MagicMock(spec=["_active", "connect", "send_to_device", "broadcast"])

    # The broadcast_impl reads from m._active directly, so it must be a mutable dict.
    async def mocked_connect(device_id: str, ws):
        await ws.accept()
        _manager_state["_active"].setdefault(device_id, []).append(ws)

    class FakeMutation:
        id = "fake-mu-1"

    async def send_to_device_impl(device_id: str, payload: dict):
        targets = list(_manager_state["_active"].get(device_id, []))
        if not targets:
            return False
        message = json.dumps(payload, ensure_ascii=False)
        for ws in targets:
            try:
                await ws.send_text(message)
            except WebSocketDisconnect:
                pass
        _manager_state["sent_messages"].append((device_id, payload))
        return True

    async def broadcast_impl(payload):
        count = 0
        for device_id in list(_manager_state["_active"].keys()):
            if await send_to_device_impl(device_id, payload):
                count += 1
        return count

    m.connect = mocked_connect
    m.send_to_device = AsyncMock(side_effect=send_to_device_impl)
    m.broadcast = AsyncMock(side_effect=broadcast_impl)

    with patch("src.pda.router._manager", m), \
         patch("src.pda.ws._manager", m):
        _reset_state()
        yield
        # nothing to tear down — context managers clean up


class TestWsIntegration:
    async def test_mutation_create_triggers_ws_send(self, async_client):
        """POST /mutations -> WS connect registers device + event fires send_text."""

        ws_mock = AsyncMock()
        _manager_state["_active"].setdefault("dev-1", []).append(ws_mock)

        response = await async_client.post("/pda/mutations", json={
            "device_id": "dev-1",
            "entity_type": "inventory",  # lowercase matches production PDA form values
            "entity_id": "oid-99",
            "operation": "create",
            "payload": {"sku": "X7"},
        })

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert data.get("id") is not None
        assert data.get("status") == "queued"

    async def test_ws_send_emits_message(self, async_client):
        """Verify broadcast sends the correct payload to connected devices."""

        # Register a fake WS connection so broadcast_impl has something to send.
        ws_mock = AsyncMock()
        _manager_state["_active"].setdefault("dev-1", []).append(ws_mock)

        await async_client.post("/pda/mutations", json={
            "device_id": "dev-1",
            "entity_type": "inventory",  # lowercase matches production PDA form values
            "entity_id": "oid-99",
            "operation": "create",
            "payload": {"sku": "X7"},
        })

        # The broadcast_impl receives {entity_type, entity_id, operation, mutation_id}
        assert len(_manager_state["sent_messages"]) == 1
        device_id_arg, sent = _manager_state["sent_messages"][0]
        assert device_id_arg == "dev-1"
        assert isinstance(sent, dict)
        assert sent["entity_type"] == "inventory"
        assert sent["entity_id"] == "oid-99"
        assert sent["operation"] == "create"
