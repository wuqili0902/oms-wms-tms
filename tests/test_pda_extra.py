from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.main import app
from src.pda.models import PendingMutation, SyncOperation
from src.pda.service import enqueue_mutation, process_pending_mutations


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)


class TestEnqueueMutation:
    async def test_creates_and_returns_mutation(self, mock_db):
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await enqueue_mutation(
            mock_db, device_id="pda-001", entity_type="inventory",
            entity_id="e1", operation=SyncOperation.UPDATE, payload={"qty": 5},
        )

        assert isinstance(result, PendingMutation)
        assert result.device_id == "pda-001"
        assert result.entity_type == "inventory"
        assert result.operation == "update"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    async def test_payload_serialized_to_json(self, mock_db):
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await enqueue_mutation(
            mock_db, device_id="pda-002", entity_type="order",
            entity_id="e2", operation=SyncOperation.CREATE, payload={"order_no": "X"},
        )

        import json
        assert json.loads(result.payload) == {"order_no": "X"}


class TestProcessPendingMutations:
    async def test_no_mutations_returns_zero(self, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await process_pending_mutations(mock_db)

        assert result == {"accepted": 0, "failed": 0}

    async def test_processes_mutations_successfully(self, mock_db):
        mutation = PendingMutation(
            id=1, device_id="pda-001", entity_type="order",
            entity_id="e1", operation="create", payload='{"order_no": "X"}',
            retry_count=0, synced_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mutation]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch("src.pda.service.append_event", new_callable=AsyncMock):
            result = await process_pending_mutations(mock_db)

        assert result["accepted"] == 1
        assert result["failed"] == 0
        assert mutation.synced_at is not None
        mock_db.commit.assert_awaited_once()

    async def test_handles_failure_increments_retry(self, mock_db):
        mutation = PendingMutation(
            id=2, device_id="pda-001", entity_type="order",
            entity_id="e2", operation="create", payload='{"order_no": "Y"}',
            retry_count=0, synced_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mutation]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch("src.pda.service.append_event", new_callable=AsyncMock, side_effect=Exception("DB error")):
            result = await process_pending_mutations(mock_db)

        assert result["accepted"] == 0
        assert result["failed"] == 1
        assert mutation.retry_count == 1
        assert mutation.synced_at is None
        mock_db.commit.assert_awaited_once()

    async def test_respects_batch_size(self, mock_db):
        mutations = [
            PendingMutation(id=i, device_id="pda-001", entity_type="order",
                            entity_id=f"e{i}", operation="create", payload="{}",
                            retry_count=0, synced_at=None)
            for i in range(3)
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mutations
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch("src.core.outbox.append_event", new_callable=AsyncMock):
            await process_pending_mutations(mock_db, batch_size=2)

        call_args = mock_db.execute.call_args[0][0]
        qs = str(call_args)
        assert "limit" in qs.lower()


class TestRouter:
    @pytest.fixture
    def client(self, mock_db):
        async def _get_db():
            return mock_db
        app.dependency_overrides[get_db] = _get_db
        transport = ASGITransport(app=app)
        c = AsyncClient(transport=transport, base_url="http://test")
        yield c
        app.dependency_overrides.clear()

    async def test_create_mutation_endpoint(self, client, mock_db):
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        resp = await client.post("/pda/mutations", json={
            "device_id": "api-test", "entity_type": "inventory",
            "entity_id": "e1", "operation": "update", "payload": {"qty": 5},
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"

    async def test_sync_endpoint(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        resp = await client.post("/pda/sync")

        assert resp.status_code == 200
        data = resp.json()
        assert data == {"accepted": 0, "failed": 0}


class TestProcessPdaSyncQueue:
    """Test the `process_pda_sync_queue` Celery background task."""

    async def test_process_pda_sync_queue_empty(self, monkeypatch):
        """When there are no pending mutations, returns pushed=0."""
        mock_svc = MagicMock()
        mock_svc.get_pending.return_value = []
        monkeypatch.setattr("src.tasks.sync.SyncQueueService", lambda path: mock_svc)

        from src.tasks.sync import process_pda_sync_queue as _t  # noqa: F811
        result = await _t(local_db_path=":memory:")
        assert result == {"pushed": 0, "failed": 0}

    async def test_process_pda_sync_queue_pushes_items(self, monkeypatch):
        """Pending records get pushed upstream and marked synced."""
        mock_svc = MagicMock()
        r1 = type("_Record", (), {"id": 1, "entity_type": "Order",
                                  "entity_id": "ORD-001", "operation": "create",
                                  "payload": "{}"})()
        r2 = type("_Record", (), {"id": 2, "entity_type": "Inventory",
                                  "entity_id": "INV-001", "operation": "update",
                                  "payload": '{"qty": 5}'})()
        mock_svc.get_pending.return_value = [r1, r2]
        monkeypatch.setattr("src.tasks.sync.SyncQueueService", lambda path: mock_svc)

        class FakeResp:
            status_code = 200
            def raise_for_status(self): pass
        fake_client = MagicMock()
        fake_client.post.return_value = FakeResp()
        monkeypatch.setattr("src.tasks.sync.httpx.AsyncClient", lambda timeout=None: fake_client)

        from src.tasks.sync import process_pda_sync_queue as _t  # noqa: F811
        result = await _t(local_db_path=":memory:")
        assert result == {"pushed": 2, "failed": 0}
        mock_svc.mark_synced.assert_called_once_with([1, 2])

    async def test_process_pda_sync_queue_handles_failure(self, monkeypatch):
        """Failed pushes increment failed count and mark records as failed."""
        record = type("_Record", (), {"id": 3, "entity_type": "Order",
                                      "entity_id": "ORD-002", "operation": "create",
                                      "payload": "{}"})()

        fake_response = MagicMock()
        fake_response.status_code = 500
        def raise_for_status_side_effect():
            raise Exception("server error")
        fake_response.raise_for_status = MagicMock(side_effect=raise_for_status_side_effect)

        async def mock_post(*args, **kwargs):
            return fake_response

        class FakeClient:
            def __init__(self, timeout=None): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            post = mock_post

        monkeypatch.setattr("src.tasks.sync.httpx.AsyncClient", FakeClient)

        # Patch SyncQueueService to avoid real DB access
        class FakeSvc:
            def __init__(self, db_path=None):
                self.failed_records = []
            def get_pending(self, limit=50): return [record]
            def mark_failed(self, rid, reason): self.failed_records.append((rid, reason))
            def mark_synced(self, ids): pass

        monkeypatch.setattr("src.tasks.sync.SyncQueueService", FakeSvc)

        from src.tasks.sync import process_pda_sync_queue as _t  # noqa: F811
        result = await _t(local_db_path="wms_pda.db")
        assert result == {"pushed": 0, "failed": 1}

    async def test_process_pda_sync_queue_partial_success(self, monkeypatch):
        """Mix of successes and failures 鈥?only successful ones marked synced."""
        r1 = type("_Record", (), {"id": 4, "entity_type": "Order", "entity_id": "ORD-003",
                                  "operation": "create", "payload": "{}"})()
        r2 = type("_Record", (), {"id": 5, "entity_type": "Inventory", "entity_id": "INV-002",
                                  "operation": "update", "payload": '{"qty": 10}'})()

        call_count = [0]
        async def post_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                resp_obj = MagicMock()
                resp_obj.status_code = 200
                return resp_obj
            else:
                resp_obj = MagicMock()
                resp_obj.status_code = 500
                def raise_side_effect():
                    raise Exception("timeout")
                resp_obj.raise_for_status = MagicMock(side_effect=raise_side_effect)
                return resp_obj

        class FakeClient2:
            def __init__(self, timeout=None): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            post = post_side_effect

        # Patch SyncQueueService to avoid real DB access
        captured = {"failed_records": []}
        class FakeSvc2:
            def __init__(self, db_path=None):
                self.failed_records = captured["failed_records"]
            def get_pending(self, limit=50): return [r1, r2]
            def mark_failed(self, rid, reason): self.failed_records.append((rid, reason))
            def mark_synced(self, ids): return len(ids) if isinstance(ids, list) else 0

        monkeypatch.setattr("src.tasks.sync.httpx.AsyncClient", FakeClient2)
        monkeypatch.setattr("src.tasks.sync.SyncQueueService", FakeSvc2)

        from src.tasks.sync import process_pda_sync_queue as _t  # noqa: F811
        result = await _t(local_db_path=":memory:")
        assert result == {"pushed": 1, "failed": 1}
        # The first item (id=4) succeeded, second (id=5) failed
        assert captured["failed_records"] == [(5, 'timeout')]

    async def test_process_pda_sync_queue_multiple_failures(self, monkeypatch):
        """All items fail 鈥?no pushed count, only failures."""
        records = [
            type("_Record", (), {"id": i, "entity_type": "Order",
                                  "entity_id": f"ORD-{i}", "operation": "create",
                                  "payload": "{}"})()
            for i in range(10, 15)
        ]

        def make_error_response():
            resp_obj = MagicMock()
            resp_obj.status_code = 500
            def raise_side_effect():
                raise Exception("timeout")
            resp_obj.raise_for_status = MagicMock(side_effect=raise_side_effect)
            return resp_obj

        async def error_post(*args, **kwargs):
            return make_error_response()

        class FakeClient3:
            def __init__(self, timeout=None): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            post = error_post

        # Patch SyncQueueService to avoid real DB access
        captured = {"failed_records": []}
        class FakeSvc3:
            def __init__(self, db_path=None):
                self.failed_records = captured["failed_records"]
            def get_pending(self, limit=50): return records
            def mark_failed(self, rid, reason): self.failed_records.append((rid, reason))
            def mark_synced(self, ids): pass

        monkeypatch.setattr("src.tasks.sync.httpx.AsyncClient", FakeClient3)
        monkeypatch.setattr("src.tasks.sync.SyncQueueService", FakeSvc3)

        from src.tasks.sync import process_pda_sync_queue as _t  # noqa: F811
        result = await _t(local_db_path="wms_pda.db")
        assert result["pushed"] == 0
        assert result["failed"] == len(records)
        # All 5 items should be in failed_records
        assert captured["failed_records"] == [
            (10, "timeout"), (11, "timeout"), (12, "timeout"), (13, "timeout"), (14, "timeout")
        ]
