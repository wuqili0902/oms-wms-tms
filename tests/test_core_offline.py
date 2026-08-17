"""Tests for core/offline.py — SyncQueueService."""
import os
import tempfile

import pytest

from src.core.offline import SyncQueueService


@pytest.fixture
def sync_service(tmp_path):
    """Create a SyncQueueService backed by a temp SQLite DB."""
    db_path = str(tmp_path / "test_sync.db")
    svc = SyncQueueService(db_path=db_path)
    yield svc
    svc.conn.close()


class TestSyncQueueService:
    def test_get_pending_empty(self, sync_service):
        # The init inserts a seed record, so there's 1 pending
        pending = sync_service.get_pending()
        assert len(pending) >= 1

    def test_mark_synced(self, sync_service):
        pending = sync_service.get_pending()
        ids = [r.id for r in pending]
        count = sync_service.mark_synced(ids)
        assert count == len(ids)
        assert len(sync_service.get_pending()) == 0

    def test_mark_failed(self, sync_service):
        pending = sync_service.get_pending()
        record_id = pending[0].id
        sync_service.mark_failed(record_id, "test error")
        remaining = sync_service.get_pending()
        assert all(r.id != record_id for r in remaining)

    def test_get_pending_limit(self, sync_service):
        for i in range(5):
            sync_service.conn.execute(
                "INSERT INTO sync_queue (entity_type, entity_id, operation, payload) "
                "VALUES (?, ?, ?, ?)",
                [f"Entity-{i}", f"ID-{i}", "create", "{}"],
            )
        sync_service.conn.commit()

        limited = sync_service.get_pending(limit=3)
        assert len(limited) == 3

    def test_record_attributes(self, sync_service):
        pending = sync_service.get_pending()
        record = pending[0]
        assert record.entity_type == "Order"
        assert record.entity_id == "ORD-INIT"
        assert record.operation == "create"

    def test_init_creates_table(self, tmp_path):
        db_path = str(tmp_path / "new_sync.db")
        svc = SyncQueueService(db_path=db_path)
        pending = svc.get_pending()
        assert len(pending) >= 1
        svc.conn.close()
