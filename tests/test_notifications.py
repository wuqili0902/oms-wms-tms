import json
import pytest
from fastapi import WebSocketDisconnect
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from unittest.mock import patch

from src.core.database import get_db
from src.main import app
from src.notification.models import Notification, NotificationType, NotificationChannel, NotificationPreference
from src.notification.service import send_notification, notify_order_status_change
from tests.conftest import _SharedSession


@pytest.mark.asyncio
async def test_send_notification(sqlite_engine, db_session):
    uid = "notif-test-uid-001"
    result = await send_notification(
        user_id=uid,
        ntype=NotificationType.SYSTEM_ALERT,
        channel=NotificationChannel.WEBSOCKET,
        title="Test Title",
        body="Test Body",
        db=db_session,
    )
    assert result is True
    rows = (await db_session.execute(
        select(Notification).where(Notification.user_id == uid)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "Test Title"
    assert rows[0].user_id == uid


@pytest.mark.asyncio
async def test_notification_with_preference_disabled(sqlite_engine, db_session):
    uid = "notif-test-uid-002"
    pref = NotificationPreference(
        user_id=uid,
        notification_type=NotificationType.SYSTEM_ALERT,
        channel=NotificationChannel.WEBSOCKET,
        enabled=False,
    )
    db_session.add(pref)
    await db_session.commit()

    result = await send_notification(
        user_id=uid,
        ntype=NotificationType.SYSTEM_ALERT,
        channel=NotificationChannel.WEBSOCKET,
        title="Skipped",
        body="Should not appear",
        db=db_session,
    )
    assert result is False
    rows = (await db_session.execute(
        select(Notification).where(Notification.user_id == uid)
    )).scalars().all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_notify_order_status_change(sqlite_engine, db_session):
    uid = "notif-test-uid-003"
    await notify_order_status_change(
        order_id=42, user_id=uid, status="shipped", order_no="ORD-001", db=db_session
    )
    rows = (await db_session.execute(
        select(Notification).where(Notification.user_id == uid)
    )).scalars().all()
    assert len(rows) == 1
    assert "ORD-001" in rows[0].title
    assert rows[0].type == NotificationType.ORDER_STATUS_CHANGE


@pytest.mark.asyncio
async def test_notification_api_list(sqlite_engine):
    uid = "notif-api-test-001"
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token

    notif = Notification(
        user_id=uid,
        type=NotificationType.SYSTEM_ALERT,
        channel=NotificationChannel.WEBSOCKET,
        title="API Test",
        body="Body",
    )
    shared.session.add(notif)
    await shared.session.commit()

    token = create_access_token({"sub": "testuser", "uid": uid})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/notifications/",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["data"]["total"] >= 1

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_notification_api_mark_read(sqlite_engine):
    uid = "notif-api-test-002"
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token

    notif = Notification(
        user_id=uid,
        type=NotificationType.SYSTEM_ALERT,
        channel=NotificationChannel.WEBSOCKET,
        title="Read Me",
        body="Body",
    )
    shared.session.add(notif)
    await shared.session.commit()
    notif_id = notif.id

    token = create_access_token({"sub": "testuser", "uid": uid})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/notifications/{notif_id}/read",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_notification_api_unread_only(sqlite_engine):
    uid = "notif-unread-test"
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token

    n1 = Notification(user_id=uid, type=NotificationType.SYSTEM_ALERT,
                       channel=NotificationChannel.WEBSOCKET, title="Unread", body="B", is_read=False)
    n2 = Notification(user_id=uid, type=NotificationType.ORDER_STATUS_CHANGE,
                       channel=NotificationChannel.WEBSOCKET, title="Read", body="B", is_read=True)
    shared.session.add_all([n1, n2])
    await shared.session.commit()

    token = create_access_token({"sub": "testuser", "uid": uid})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/notifications/?unread_only=true",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Unread"

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_notification_api_mark_all_read(sqlite_engine):
    uid = "notif-markall-test"
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token

    shared.session.add_all([
        Notification(user_id=uid, type=NotificationType.SYSTEM_ALERT,
                     channel=NotificationChannel.WEBSOCKET, title="A", body="B"),
        Notification(user_id=uid, type=NotificationType.ORDER_STATUS_CHANGE,
                     channel=NotificationChannel.WEBSOCKET, title="B", body="B"),
    ])
    await shared.session.commit()

    token = create_access_token({"sub": "testuser", "uid": uid})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/notifications/read-all",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_notification_api_preferences(sqlite_engine):
    uid = "notif-pref-test"
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token

    from src.notification.models import NotificationPreference
    pref = NotificationPreference(user_id=uid, notification_type=NotificationType.SYSTEM_ALERT,
                                   channel=NotificationChannel.WEBSOCKET, enabled=False)
    shared.session.add(pref)
    await shared.session.commit()

    token = create_access_token({"sub": "testuser", "uid": uid})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/notifications/preferences",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["enabled"] is False

        resp2 = await client.put(
            "/api/v1/notifications/preferences",
            json=[{"notification_type": "system_alert", "channel": "websocket", "enabled": True}],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 200, resp2.text

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_ws_manager():
    from src.notification.ws import ConnectionManager
    mgr = ConnectionManager()
    assert mgr.active_connections == 0
    await mgr.send_to_user(1, {"msg": "hello"})
    assert mgr.active_connections == 0


@pytest.mark.asyncio
async def test_ws_manager_connect_disconnect():
    from unittest.mock import AsyncMock
    from src.notification.ws import ConnectionManager
    mgr = ConnectionManager()
    ws = AsyncMock()

    await mgr.connect(10, ws)
    assert mgr.active_connections == 1

    await mgr.connect(10, ws)
    assert mgr.active_connections == 2  # same user/ws appended again

    ws2 = AsyncMock()
    await mgr.connect(20, ws2)
    assert mgr.active_connections == 3

    mgr.disconnect(10, ws)
    assert mgr.active_connections == 2

    mgr.disconnect(20, ws2)
    assert mgr.active_connections == 1  # one copy of user1's ws remains


@pytest.mark.asyncio
async def test_ws_manager_send_json():
    from unittest.mock import AsyncMock
    from src.notification.ws import ConnectionManager
    mgr = ConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()

    await mgr.connect(1, ws1)
    await mgr.connect(2, ws2)

    await mgr.send_to_user(1, {"event": "test"})
    ws1.send_text.assert_called_once()
    ws2.send_text.assert_not_called()

    await mgr.broadcast({"broadcast": True})
    ws1.send_text.assert_called_with(json.dumps({"broadcast": True}, ensure_ascii=False))
    ws2.send_text.assert_called_with(json.dumps({"broadcast": True}, ensure_ascii=False))


@pytest.mark.asyncio
async def test_ws_manager_send_disconnect():
    from unittest.mock import AsyncMock
    from src.notification.ws import ConnectionManager
    mgr = ConnectionManager()
    ws = AsyncMock()
    ws.send_text = AsyncMock(side_effect=WebSocketDisconnect(code=1000))

    await mgr.connect(1, ws)
    assert mgr.active_connections == 1

    await mgr.send_to_user(1, {"event": "test"})
    assert mgr.active_connections == 0  # stale ws disconnected


@pytest.mark.asyncio
async def test_ws_manager_send_generic_error():
    from unittest.mock import AsyncMock
    from src.notification.ws import ConnectionManager
    mgr = ConnectionManager()
    ws = AsyncMock()
    ws.send_text = AsyncMock(side_effect=RuntimeError("network error"))

    await mgr.connect(1, ws)
    assert mgr.active_connections == 1

    await mgr.send_to_user(1, {"event": "test"})
    assert mgr.active_connections == 0  # stale ws disconnected


@pytest.mark.asyncio
async def test_ws_manager_broadcast():
    from unittest.mock import AsyncMock
    from src.notification.ws import ConnectionManager
    mgr = ConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    ws3 = AsyncMock()
    ws3.send_text = AsyncMock(side_effect=WebSocketDisconnect(code=1000))

    await mgr.connect(1, ws1)
    await mgr.connect(2, ws2)
    await mgr.connect(2, ws3)

    await mgr.broadcast({"msg": "hello"})
    assert mgr.active_connections == 2  # ws3 was disconnected


@pytest.mark.asyncio
async def test_email_service_disabled():
    from src.notification.email import EmailMessage, email_service
    result = await email_service.send(EmailMessage(to=["test@test.com"], subject="S", body_text="B"))
    assert result is False


@pytest.mark.asyncio
async def test_email_service_enabled(monkeypatch):
    monkeypatch.setattr("src.notification.email.settings.smtp_host", "smtp.test.com")
    monkeypatch.setattr("src.notification.email.settings.smtp_port", 587)
    monkeypatch.setattr("src.notification.email.settings.smtp_user", "user")
    monkeypatch.setattr("src.notification.email.settings.smtp_password", "pass")
    monkeypatch.setattr("src.notification.email.settings.smtp_use_tls", True)
    monkeypatch.setattr("src.notification.email.settings.smtp_from", "noreply@test.com")

    from src.notification.email import EmailMessage, email_service

    new_service = email_service.__class__()
    assert new_service._enabled is True

    sent_data = {}

    async def _fake_connect(smtp_self):
        pass

    async def _fake_starttls(smtp_self):
        pass

    async def _fake_login(smtp_self, user, pw):
        sent_data["login"] = (user, pw)

    async def _fake_sendmail(smtp_self, from_addr, to_addrs, msg_str):
        sent_data["from"] = from_addr
        sent_data["to"] = to_addrs
        sent_data["msg"] = msg_str

    async def _fake_quit(smtp_self):
        sent_data["quit"] = True

    monkeypatch.setattr("aiosmtplib.SMTP.connect", _fake_connect)
    monkeypatch.setattr("aiosmtplib.SMTP.starttls", _fake_starttls)
    monkeypatch.setattr("aiosmtplib.SMTP.login", _fake_login)
    monkeypatch.setattr("aiosmtplib.SMTP.sendmail", _fake_sendmail)
    monkeypatch.setattr("aiosmtplib.SMTP.quit", _fake_quit)

    result = await new_service.send(EmailMessage(to=["ops@test.com"], subject="Hi", body_text="Hello"))
    assert result is True
    assert "Hi" in sent_data.get("msg", "")


@pytest.mark.asyncio
async def test_email_service_send_template(monkeypatch):
    monkeypatch.setattr("src.notification.email.settings.smtp_host", "smtp.test.com")
    monkeypatch.setattr("src.notification.email.settings.smtp_user", "user")
    monkeypatch.setattr("src.notification.email.settings.smtp_password", "pass")

    from src.notification.email import email_service

    new_service = email_service.__class__()
    sent = []

    async def _fake_send(svc_self, msg):
        sent.append(msg)
        return True

    monkeypatch.setattr(new_service.__class__, "send", _fake_send)

    result = await new_service.send_template(["a@b.com"], "Greeting", "Hello {name}", name="World")
    assert result is True
    assert len(sent) == 1
    assert sent[0].body_text == "Hello World"


@pytest.mark.asyncio
async def test_email_service_send_failure(monkeypatch):
    monkeypatch.setattr("src.notification.email.settings.smtp_host", "smtp.test.com")
    monkeypatch.setattr("src.notification.email.settings.smtp_user", "user")
    monkeypatch.setattr("src.notification.email.settings.smtp_password", "pass")

    from src.notification.email import EmailMessage, email_service

    new_service = email_service.__class__()

    async def _fake_connect(smtp_self):
        raise RuntimeError("Connection refused")

    monkeypatch.setattr("aiosmtplib.SMTP.connect", _fake_connect)

    result = await new_service.send(EmailMessage(to=["fail@test.com"], subject="F", body_text="F"))
    assert result is False


@pytest.mark.asyncio
async def test_email_service_html_body(monkeypatch):
    monkeypatch.setattr("src.notification.email.settings.smtp_host", "smtp.test.com")
    monkeypatch.setattr("src.notification.email.settings.smtp_user", "user")
    monkeypatch.setattr("src.notification.email.settings.smtp_password", "pass")

    from src.notification.email import EmailMessage, email_service

    new_service = email_service.__class__()
    sent_body = []

    async def _fake_sendmail(smtp_self, from_addr, to_addrs, msg_str):
        sent_body.append(msg_str)

    async def _noop(*args, **kwargs):
        pass

    monkeypatch.setattr("aiosmtplib.SMTP.connect", _noop)
    monkeypatch.setattr("aiosmtplib.SMTP.starttls", _noop)
    monkeypatch.setattr("aiosmtplib.SMTP.login", _noop)
    monkeypatch.setattr("aiosmtplib.SMTP.sendmail", _fake_sendmail)
    monkeypatch.setattr("aiosmtplib.SMTP.quit", _noop)

    result = await new_service.send(EmailMessage(to=["a@b.com"], subject="HTML", body_html="<h1>Hi</h1>"))
    assert result is True
    assert any("<h1>Hi</h1>" in body for body in sent_body)


@pytest.mark.asyncio
async def test_send_notification_with_email(sqlite_engine, db_session):
    from src.notification.email import EmailMessage
    from src.notification.models import Notification, NotificationChannel, NotificationType
    from src.notification.service import send_notification

    sent = []

    async def _fake_send(msg: EmailMessage) -> bool:
        sent.append(msg)
        return True

    uid = "notif-email-test"
    with patch("src.notification.service.email_service.send", _fake_send):
        result = await send_notification(
            user_id=uid,
            ntype=NotificationType.LOW_STOCK_ALERT,
            channel=NotificationChannel.EMAIL,
            title="Low Stock",
            body="Qty: 5",
            user_email="ops@test.com",
            db=db_session,
        )
    assert result is True
    assert len(sent) == 1
    assert sent[0].to == ["ops@test.com"]
    assert sent[0].subject == "Low Stock"

    rows = (await db_session.execute(
        select(Notification).where(Notification.user_id == uid)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].channel == NotificationChannel.EMAIL


@pytest.mark.asyncio
async def test_send_notification_exception(sqlite_engine, db_session):
    from src.notification.service import send_notification

    def _broken_add(*args, **kwargs):
        raise RuntimeError("db fail")

    db_session.add = _broken_add

    result = await send_notification(
        user_id="notif-exc-test",
        ntype=NotificationType.SYSTEM_ALERT,
        channel=NotificationChannel.WEBSOCKET,
        title="Fail",
        body="Will fail",
        db=db_session,
    )
    assert result is False


@pytest.mark.asyncio
async def test_send_notification_auto_session(sqlite_engine, db_session):
    from unittest.mock import AsyncMock
    from src.notification.service import send_notification

    uid = "notif-auto-sess"

    with patch("src.notification.service.get_db_session") as mock_get:
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = db_session
        mock_get.return_value = mock_cm
        result = await send_notification(
            user_id=uid,
            ntype=NotificationType.SYSTEM_ALERT,
            channel=NotificationChannel.WEBSOCKET,
            title="Auto",
            body="Session test",
        )
    assert result is True


@pytest.mark.asyncio
async def test_notify_low_stock(sqlite_engine, db_session):
    from src.notification.models import Notification, NotificationChannel, NotificationType
    from src.notification.service import notify_low_stock
    import uuid
    from src.auth.models import User

    u1 = User(id=uuid.uuid4(), username="ops1", email="ops1@test.com", hashed_password="x", is_active=True)
    u2 = User(id=uuid.uuid4(), username="ops2", email="ops2@test.com", hashed_password="x", is_active=True)
    db_session.add_all([u1, u2])
    await db_session.commit()

    from src.notification.email import EmailMessage
    sent = []

    async def _fake_send(msg: EmailMessage) -> bool:
        sent.append(msg)
        return True

    with patch("src.notification.service.email_service.send", _fake_send):
        await notify_low_stock(warehouse_id="WH01", sku="SKU-001", current_qty=5, db=db_session)

    assert len(sent) >= 2
    emails_to = {", ".join(m.to) if isinstance(m.to, list) else m.to for m in sent}
    matched = any("ops1@test.com" in e for e in emails_to)
    assert matched, f"ops1@test.com not in {emails_to}"
    assert all("库存预警" in m.subject for m in sent)

    rows = (await db_session.execute(
        select(Notification).where(Notification.type == NotificationType.LOW_STOCK_ALERT)
    )).scalars().all()
    assert len(rows) >= 2
