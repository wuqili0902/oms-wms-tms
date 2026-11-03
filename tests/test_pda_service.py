import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete as sa_delete

from src.pda.models import PendingMutation, SyncOperation


@pytest.fixture
async def clean_pda(db_session):
    from src.core.outbox import OutboxEvent
    await db_session.execute(sa_delete(OutboxEvent))
    await db_session.execute(sa_delete(PendingMutation))
    await db_session.commit()


@pytest.mark.asyncio
async def test_enqueue_mutation(db_session, clean_pda):
    from src.pda.service import enqueue_mutation

    mutation = await enqueue_mutation(
        db_session,
        device_id="pda-001",
        entity_type="inventory",
        entity_id=str(uuid.uuid4()),
        operation=SyncOperation.UPDATE,
        payload={"qty": 5},
    )
    assert mutation.device_id == "pda-001"
    assert mutation.entity_type == "inventory"
    assert mutation.operation == "update"
    assert mutation.synced_at is None


@pytest.mark.asyncio
async def test_enqueue_mutation_and_sync(db_session, clean_pda):
    from src.pda.service import enqueue_mutation, process_pending_mutations

    eid = str(uuid.uuid4())
    await enqueue_mutation(
        db_session, device_id="pda-002",
        entity_type="order", entity_id=eid,
        operation=SyncOperation.CREATE, payload={"order_no": "X"},
    )

    with patch("src.pda.service.append_event", new_callable=AsyncMock) as mock_append:
        result = await process_pending_mutations(db_session)
    assert result["accepted"] >= 1
    assert result["failed"] == 0
    mock_append.assert_called()


@pytest.mark.asyncio
async def test_process_pending_mutations_empty(db_session, clean_pda):
    from src.pda.service import process_pending_mutations

    result = await process_pending_mutations(db_session)
    assert result == {"accepted": 0, "failed": 0}


@pytest.mark.asyncio
async def test_process_pending_mutations_failure(db_session, clean_pda):
    from src.pda.service import enqueue_mutation, process_pending_mutations

    eid = str(uuid.uuid4())
    await enqueue_mutation(
        db_session, device_id="pda-003",
        entity_type="order", entity_id=eid,
        operation=SyncOperation.CREATE, payload={"order_no": "Y"},
    )

    with patch("src.pda.service.append_event", new_callable=AsyncMock, side_effect=Exception("DB error")):
        result = await process_pending_mutations(db_session)
    assert result["accepted"] == 0
    assert result["failed"] >= 1


@pytest.mark.asyncio
async def test_pda_create_mutation_api(sqlite_engine):
    from httpx import ASGITransport, AsyncClient

    from src.core.database import get_db
    from src.core.dependencies import get_current_user
    from src.main import app
    from tests.conftest import _SharedSession

    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_current_user] = lambda: {"sub": "pda-test-user"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/pda/mutations", json={
            "device_id": "api-pda-001",
            "entity_type": "inventory",
            "entity_id": str(uuid.uuid4()),
            "operation": "update",
            "payload": {"qty": 5},
        })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "queued"
    assert "id" in data

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_pda_list_mutations_api(sqlite_engine):
    from httpx import ASGITransport, AsyncClient

    from src.core.database import get_db
    from src.core.dependencies import get_current_user
    from src.main import app
    from src.pda.models import SyncOperation
    from src.pda.service import enqueue_mutation
    from tests.conftest import _SharedSession

    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    await enqueue_mutation(
        shared.session, device_id="pda-list",
        entity_type="order", entity_id="list-001",
        operation=SyncOperation.CREATE, payload={},
    )

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_current_user] = lambda: {"sub": "pda-test-user"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/pda/mutations")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["device_id"] == "pda-list"
    assert data[0]["entity_type"] == "order"

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_pda_sync_mutations_api(sqlite_engine):
    from httpx import ASGITransport, AsyncClient

    from src.core.database import get_db
    from src.core.dependencies import get_current_user
    from src.main import app
    from src.pda.models import SyncOperation
    from src.pda.service import enqueue_mutation
    from tests.conftest import _SharedSession

    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    await enqueue_mutation(
        shared.session, device_id="api-pda-002",
        entity_type="order", entity_id=str(uuid.uuid4()),
        operation=SyncOperation.CREATE, payload={"order_no": "X"},
    )

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[get_current_user] = lambda: {"sub": "pda-test-user"}

    with patch("src.pda.service.append_event", new_callable=AsyncMock):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/pda/sync")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["accepted"] >= 1

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_pda_ws_endpoint_no_client_id():
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import WebSocket

    from src.pda.router import ws_endpoint

    ws = MagicMock(spec=WebSocket)
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.send_text = AsyncMock()
    await ws_endpoint(websocket=ws)
    ws.accept.assert_awaited_once()


@pytest.mark.asyncio
async def test_pda_ws_endpoint_with_client_id():
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import WebSocket, WebSocketDisconnect

    from src.pda.router import ws_endpoint
    ws = MagicMock(spec=WebSocket)
    ws.accept = AsyncMock()
    # The endpoint now keeps the socket open in a receive loop; simulate the
    # client disconnecting so the route returns.
    ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())
    ws.send_text = AsyncMock()
    with patch("src.pda.router._manager") as mock_mgr, \
         patch("src.core.security.decode_token", return_value={"sub": "pda-user"}):
        mock_mgr.connect = AsyncMock()
        await ws_endpoint(websocket=ws, client_id="ws-test-device", token="valid-token")
    mock_mgr.connect.assert_awaited_once_with("ws-test-device", ws)
    ws.receive_text.assert_awaited()
    mock_mgr.disconnect.assert_called_once_with("ws-test-device", ws)


@pytest.mark.asyncio
async def test_pda_ws_endpoint_no_token():
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import WebSocket

    from src.pda.router import ws_endpoint
    ws = MagicMock(spec=WebSocket)
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    with patch("src.pda.router._manager") as mock_mgr:
        await ws_endpoint(websocket=ws, client_id="ws-test-device")
    ws.accept.assert_awaited_once()
    ws.close.assert_awaited_once()
    mock_mgr.connect.assert_not_called()


@pytest.mark.asyncio
async def test_pda_ws_endpoint_answers_ping_with_pong():
    """The keepalive the phone's socket depends on, in both directions.

    ``mobile/src/api/socket.js`` sends the bare text ``ping`` on a timer and
    closes its own socket when no ``pong`` comes back inside the deadline —
    without that, a link a middlebox dropped without closing anything still
    reads OPEN, so the phone reports 已连接 while every request behind it
    fails.  A reply of JSON, or of anything other than the exact text the
    client compares, closes healthy sockets and looks like a flaky warehouse
    network.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import WebSocket, WebSocketDisconnect

    from src.pda.router import ws_endpoint

    ws = MagicMock(spec=WebSocket)
    ws.accept = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=["ping", "ping", WebSocketDisconnect()])
    ws.send_text = AsyncMock()
    with patch("src.pda.router._manager") as mock_mgr, \
         patch("src.core.security.decode_token", return_value={"sub": "pda-user"}):
        mock_mgr.connect = AsyncMock()
        await ws_endpoint(websocket=ws, client_id="ws-keepalive", token="valid-token")

    assert ws.send_text.await_count == 2, "the keepalive was answered once, then dropped"
    for call in ws.send_text.await_args_list:
        assert call.args == ("pong",), f"expected the text 'pong', got {call.args}"
