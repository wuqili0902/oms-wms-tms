import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.main import app
from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.webhooks.models import WebhookTarget, WebhookStatus, WebhookEvent


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_user():
    return {"uid": "user123", "username": "admin"}


@pytest.fixture
def override_deps(mock_db, mock_user):
    async def _get_db():
        return mock_db

    async def _get_current_user():
        return mock_user

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_current_user
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(override_deps):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestListTargets:
    async def test_returns_empty_list(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.get("/api/v1/webhooks/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == []

    async def test_returns_targets_list(self, client, mock_db):
        t = WebhookTarget(
            id=1, name="Hook1", url="http://x.com", secret="s",
            events=json.dumps(["order.created"]),
            status=WebhookStatus.ACTIVE, created_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [t]
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.get("/api/v1/webhooks/")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["name"] == "Hook1"
        assert data["data"][0]["events"] == ["order.created"]


class TestCreateTarget:
    async def test_creates_webhook(self, client, mock_db):
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        resp = await client.post("/api/v1/webhooks/", json={
            "name": "My Hook", "url": "http://example.com/hook",
            "secret": "s3cret", "events": ["order.created"],
        })

        assert resp.status_code == 200
        data = resp.json()
        assert "Webhook target created" in data["message"]
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    async def test_rejects_invalid_event(self, client, mock_db):
        resp = await client.post("/api/v1/webhooks/", json={
            "name": "Bad", "url": "http://x.com",
            "events": ["not_a_real_event"],
        })

        assert resp.status_code == 422
        data = resp.json()
        assert "Invalid event" in data["error"]["message"]

    async def test_creates_without_secret(self, client, mock_db):
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        resp = await client.post("/api/v1/webhooks/", json={
            "name": "No Secret", "url": "http://x.com",
            "events": ["order.created"],
        })

        assert resp.status_code == 200

    async def test_creates_with_paused_status(self, client, mock_db):
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        resp = await client.post("/api/v1/webhooks/", json={
            "name": "Paused", "url": "http://x.com",
            "events": ["order.created"], "status": "paused",
        })

        assert resp.status_code == 200


class TestUpdateTarget:
    async def test_updates_webhook(self, client, mock_db):
        t = WebhookTarget(
            id=10, name="Old", url="http://old.com", secret=None,
            events=json.dumps(["order.created"]),
            status=WebhookStatus.ACTIVE,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = t
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        resp = await client.put("/api/v1/webhooks/10", json={
            "name": "New", "url": "http://new.com",
            "secret": "newsecret", "events": ["order.cancelled"],
            "status": "paused",
        })

        assert resp.status_code == 200
        assert t.name == "New"
        assert t.url == "http://new.com"
        assert t.secret == "newsecret"
        assert "order.cancelled" in t.events
        assert t.status == WebhookStatus.PAUSED
        mock_db.commit.assert_awaited_once()

    async def test_update_not_found(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.put("/api/v1/webhooks/999", json={"name": "Ghost"})

        assert resp.status_code == 404

    async def test_update_partial_fields(self, client, mock_db):
        t = WebhookTarget(
            id=11, name="Partial", url="http://partial.com", secret="old",
            events=json.dumps(["order.created"]),
            status=WebhookStatus.ACTIVE,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = t
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        resp = await client.put("/api/v1/webhooks/11", json={"url": "http://changed.com"})

        assert resp.status_code == 200
        assert t.url == "http://changed.com"
        assert t.name == "Partial"
        assert t.secret == "old"

    async def test_update_invalid_event(self, client, mock_db):
        t = WebhookTarget(
            id=12, name="BadEv", url="http://x.com", secret=None,
            events=json.dumps(["order.created"]),
            status=WebhookStatus.ACTIVE,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = t
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.put("/api/v1/webhooks/12", json={"events": ["bad_event"]})

        assert resp.status_code == 422

    async def test_update_name_only(self, client, mock_db):
        t = WebhookTarget(
            id=13, name="Original", url="http://x.com", secret=None,
            events=json.dumps(["order.created"]),
            status=WebhookStatus.ACTIVE,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = t
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        resp = await client.put("/api/v1/webhooks/13", json={"name": "Renamed"})

        assert resp.status_code == 200
        assert t.name == "Renamed"
        assert t.url == "http://x.com"


class TestDeleteTarget:
    async def test_deletes_webhook(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = WebhookTarget(
            id=20, name="Del", url="http://x.com", secret=None,
            events=json.dumps(["order.created"]),
            status=WebhookStatus.ACTIVE,
        )
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        resp = await client.delete("/api/v1/webhooks/20")

        assert resp.status_code == 200
        assert mock_db.execute.await_count == 2
        mock_db.commit.assert_awaited_once()

    async def test_delete_not_found(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.delete("/api/v1/webhooks/999")

        assert resp.status_code == 404
