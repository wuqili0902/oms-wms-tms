from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.main import app
from src.core.database import get_db


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def client(mock_db):
    async def _get_db():
        return mock_db

    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    c = AsyncClient(transport=transport, base_url="http://test")
    yield c
    app.dependency_overrides.clear()


class TestSyncPush:
    async def test_accepts_batch(self, client, mock_db):
        mock_db.commit = AsyncMock()

        with patch("src.core.outbox.append_event", new_callable=AsyncMock):
            resp = await client.post("/api/v1/sync/push", json={
                "batch": [
                    {"entity_type": "order", "entity_id": "e1", "operation": "create", "payload": {"no": "X"}},
                ],
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] == 1
        assert data["failed"] == []

    async def test_returns_failed_items(self, client, mock_db):
        with patch("src.core.outbox.append_event", new_callable=AsyncMock, side_effect=Exception("fail")):
            resp = await client.post("/api/v1/sync/push", json={
                "batch": [
                    {"entity_type": "order", "entity_id": "e1", "operation": "create", "payload": {}},
                    {"entity_type": "inventory", "entity_id": "e2", "operation": "update", "payload": {}},
                ],
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] == 0
        assert len(data["failed"]) == 2

    async def test_mixed_success_and_failure(self, client, mock_db):
        call_count = 0

        async def append_side(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return
            raise Exception("db error")

        with patch("src.core.outbox.append_event", new_callable=AsyncMock, side_effect=append_side):
            resp = await client.post("/api/v1/sync/push", json={
                "batch": [
                    {"entity_type": "order", "entity_id": "e1", "operation": "create", "payload": {}},
                    {"entity_type": "order", "entity_id": "e2", "operation": "update", "payload": {}},
                ],
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] == 1
        assert len(data["failed"]) == 1

    async def test_empty_batch(self, client):
        with patch("src.core.outbox.append_event", new_callable=AsyncMock):
            resp = await client.post("/api/v1/sync/push", json={"batch": []})

        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] == 0
        assert data["failed"] == []


class TestSyncPull:
    async def _make_event(self, eid=1, etype="order", eid_str="agg-1"):
        ev = MagicMock()
        ev.id = eid
        ev.aggregate_type = etype
        ev.aggregate_id = eid_str
        ev.event_type = f"{etype}.created"
        ev.payload = "{}"
        ev.created_at = None
        return ev

    async def test_returns_changes(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [await self._make_event()]
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.get("/api/v1/sync/pull")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["changes"]) == 1
        assert data["has_more"] is False

    async def test_empty_pull(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.get("/api/v1/sync/pull")

        assert resp.status_code == 200
        data = resp.json()
        assert data["changes"] == []
        assert data["has_more"] is False

    async def test_filters_by_entity_type(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.get("/api/v1/sync/pull?entity_type=order")

        assert resp.status_code == 200

    async def test_filters_by_since(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.get("/api/v1/sync/pull?since=2024-01-01T00:00:00")

        assert resp.status_code == 200

    async def test_ignores_invalid_since(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.get("/api/v1/sync/pull?since=not-a-date")

        assert resp.status_code == 200

    async def test_has_more_when_limit_reached(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [await self._make_event()] * 100
        mock_db.execute = AsyncMock(return_value=mock_result)

        resp = await client.get("/api/v1/sync/pull?limit=100")

        assert resp.status_code == 200
        data = resp.json()
        assert data["has_more"] is True


class TestSyncAck:
    async def test_acknowledges_ids(self, client):
        resp = await client.post("/api/v1/sync/ack", json=["id1", "id2"])

        assert resp.status_code == 200
        data = resp.json()
        assert data["acknowledged"] == 2

    async def test_acknowledges_empty(self, client):
        resp = await client.post("/api/v1/sync/ack", json=[])

        assert resp.status_code == 200
        data = resp.json()
        assert data["acknowledged"] == 0


class TestMobileSchemas:
    """Covers schema property methods (mobile.py lines 37, 46 and api/v1/__init__.py lines 12, 21)."""

    async def test_import_orders_is_file(self):
        from src.api.v1.mobile import ImportOrdersRequest
        req = ImportOrdersRequest(file="test.csv")
        assert req.is_file is True

    async def test_import_inventory_is_file(self):
        from src.api.v1.mobile import ImportInventoryRequest
        req = ImportInventoryRequest(file="inventory.csv")
        assert req.is_file is True

    async def test_v1_init_import_orders_is_file(self):
        from src.api.v1 import ImportOrdersRequest
        req = ImportOrdersRequest(file="test.csv")
        assert req.is_file is True

    async def test_v1_init_import_inventory_is_file(self):
        from src.api.v1 import ImportInventoryRequest
        req = ImportInventoryRequest(file="inv.csv")
        assert req.is_file is True

    async def test_v1_init_import_orders_function(self):
        from src.api.v1 import import_orders
        result = import_orders()
        assert result is not None

    async def test_v1_init_inventory_function(self):
        from src.api.v1 import inventory
        result = inventory()
        assert result is not None
