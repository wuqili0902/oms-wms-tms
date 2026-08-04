import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.database import get_db
from src.main import app
from src.webhooks.models import WebhookEvent, WebhookStatus, WebhookTarget
from src.webhooks.service import _do_dispatch, dispatch_event
from tests.conftest import _SharedSession


async def _clear_webhooks(session):
    from sqlalchemy import delete
    await session.execute(delete(WebhookTarget))
    from src.webhooks.models import WebhookDeliveryLog
    await session.execute(delete(WebhookDeliveryLog))
    await session.commit()


@pytest.mark.asyncio
async def test_dispatch_event_no_targets(sqlite_engine, db_session):
    await _clear_webhooks(db_session)
    await dispatch_event(WebhookEvent.ORDER_CREATED, {"test": True}, db=db_session)


@pytest.mark.asyncio
async def test_dispatch_event_with_target_mocked(sqlite_engine, db_session):
    await _clear_webhooks(db_session)
    target = WebhookTarget(
        name="Test Target",
        url="http://localhost:9999/hook",
        secret="test-secret",
        events=json.dumps([WebhookEvent.ORDER_CREATED.value]),
        status=WebhookStatus.ACTIVE,
    )
    db_session.add(target)
    await db_session.commit()

    mock_client = AsyncMock()
    mock_response = AsyncMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.text = "OK"
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("src.webhooks.service.httpx.AsyncClient") as mock_httpx:
        mock_httpx.return_value.__aenter__.return_value = mock_client
        await _do_dispatch(db_session, WebhookEvent.ORDER_CREATED, {"test": True})

    assert mock_client.post.called
    call_kwargs = mock_client.post.call_args
    assert call_kwargs[0][0] == "http://localhost:9999/hook"
    assert "X-Webhook-Signature" in call_kwargs[1]["headers"]


@pytest.mark.asyncio
async def test_dispatch_event_event_not_matching(sqlite_engine, db_session):
    await _clear_webhooks(db_session)
    target = WebhookTarget(
        name="No Match",
        url="http://localhost:9999/nomatch",
        events=json.dumps([WebhookEvent.ORDER_STATUS_CHANGED.value]),
        status=WebhookStatus.ACTIVE,
    )
    db_session.add(target)
    await db_session.commit()

    with patch("src.webhooks.service.httpx.AsyncClient") as mock_httpx:
        await _do_dispatch(db_session, WebhookEvent.ORDER_CREATED, {"test": True})

    mock_httpx.return_value.__aenter__.return_value.post.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_event_delivery_failure(sqlite_engine, db_session):
    await _clear_webhooks(db_session)
    target = WebhookTarget(
        name="Fail Target",
        url="http://localhost:9999/fail",
        secret=None,
        events=json.dumps([WebhookEvent.ORDER_CREATED.value]),
        status=WebhookStatus.ACTIVE,
    )
    db_session.add(target)
    await db_session.commit()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("src.webhooks.service.httpx.AsyncClient") as mock_httpx:
        mock_httpx.return_value.__aenter__.return_value = mock_client
        await _do_dispatch(db_session, WebhookEvent.ORDER_CREATED, {"test": True})

    from sqlalchemy import select

    from src.webhooks.models import DeliveryStatus, WebhookDeliveryLog
    logs = (await db_session.execute(
        select(WebhookDeliveryLog).where(WebhookDeliveryLog.target_id == target.id)
    )).scalars().all()
    assert len(logs) >= 1
    assert any(log.status == DeliveryStatus.FAILED for log in logs)


@pytest.mark.asyncio
async def test_dispatch_event_paused_target_skipped(sqlite_engine, db_session):
    await _clear_webhooks(db_session)
    target = WebhookTarget(
        name="Paused Target",
        url="http://localhost:9999/paused",
        events=json.dumps([WebhookEvent.ORDER_CREATED.value]),
        status=WebhookStatus.PAUSED,
    )
    db_session.add(target)
    await db_session.commit()

    with patch("src.webhooks.service.httpx.AsyncClient") as mock_httpx:
        await _do_dispatch(db_session, WebhookEvent.ORDER_CREATED, {"test": True})

    mock_httpx.return_value.__aenter__.return_value.post.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_crud_api(sqlite_engine):
    uid = "wh-crud-test"
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token
    token = create_access_token({"sub": "testuser", "uid": uid})
    transport = ASGITransport(app=app)
    base_url = "http://test"

    async with AsyncClient(transport=transport, base_url=base_url) as client:
        resp = await client.get(
            "/api/v1/webhooks/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data["data"], list)

        payload = {
            "name": "Test Webhook",
            "url": "https://example.com/hook",
            "secret": "mysecret",
            "events": ["order.created", "order.status_changed"],
            "status": "active",
        }
        resp = await client.post(
            "/api/v1/webhooks/",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        created = resp.json()
        target_id = created["data"]["id"]

        resp = await client.put(
            f"/api/v1/webhooks/{target_id}",
            json={"name": "Updated Webhook", "events": ["order.created"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text

        resp = await client.delete(
            f"/api/v1/webhooks/{target_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_webhook_create_invalid_event(sqlite_engine):
    uid = "wh-invalid-event"
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token
    token = create_access_token({"sub": "testuser", "uid": uid})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/webhooks/",
            json={"name": "Bad", "url": "http://x.com", "events": ["invalid.event"]},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 422

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_webhook_delete_not_found(sqlite_engine):
    uid = "wh-delete-404"
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token
    token = create_access_token({"sub": "testuser", "uid": uid})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(
            "/api/v1/webhooks/999999",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 404

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_dispatch_event_no_db_session(sqlite_engine, db_session):
    """Test the code path where dispatch_event() creates its own session."""
    from src.webhooks.models import WebhookStatus, WebhookTarget
    from src.webhooks.service import dispatch_event

    target = WebhookTarget(
        name="Auto Session Target",
        url="http://localhost:9999/auto",
        secret="s3kret",
        events=json.dumps([WebhookEvent.ORDER_CREATED.value]),
        status=WebhookStatus.ACTIVE,
    )
    db_session.add(target)
    await db_session.commit()

    mock_client = AsyncMock()
    mock_response = AsyncMock()
    mock_response.is_success = True
    mock_response.status_code = 200
    mock_response.text = "OK"
    mock_client.post = AsyncMock(return_value=mock_response)

    with (
        patch("src.core.database.get_session") as mock_get_session,
        patch("httpx.AsyncClient") as mock_httpx,
    ):
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = db_session
        mock_get_session.return_value = mock_cm
        mock_httpx.return_value.__aenter__.return_value = mock_client
        await dispatch_event(WebhookEvent.ORDER_CREATED, {"test": True})

    assert mock_client.post.called


@pytest.mark.asyncio
async def test_webhook_update_not_found(sqlite_engine):
    uid = "wh-update-404"
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token
    token = create_access_token({"sub": "testuser", "uid": uid})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/v1/webhooks/999999",
            json={"name": "Ghost", "events": ["order.created"]},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 404

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_webhook_update_invalid_event(sqlite_engine):
    uid = "wh-update-bad-ev"
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token
    token = create_access_token({"sub": "testuser", "uid": uid})

    import json

    from src.webhooks.models import WebhookStatus, WebhookTarget
    target = WebhookTarget(name="Update Target", url="http://x.com",
                           events=json.dumps(["order.created"]), status=WebhookStatus.ACTIVE)
    shared.session.add(target)
    await shared.session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            f"/api/v1/webhooks/{target.id}",
            json={"events": ["not_a_real_event"]},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 422

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_webhook_update_partial_fields(sqlite_engine):
    uid = "wh-update-partial"
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token
    token = create_access_token({"sub": "testuser", "uid": uid})

    import json

    from src.webhooks.models import WebhookStatus, WebhookTarget
    target = WebhookTarget(name="Partial", url="http://x.com",
                           events=json.dumps(["order.created"]), status=WebhookStatus.ACTIVE)
    shared.session.add(target)
    await shared.session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            f"/api/v1/webhooks/{target.id}",
            json={"url": "http://y.com", "secret": "newsecret", "status": "paused"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text

    app.dependency_overrides.clear()
    await shared.teardown()
