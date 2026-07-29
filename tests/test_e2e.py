"""E2E tests: verify PDA offline store persists across restarts + sync flush."""


import pytest
from src.core.offline import _open_local_store, LocalStore


# --- in-memory SQLite (no DB needed) -----------------------------------------

@pytest.mark.asyncio
async def test_store_add_then_drain():
    store = LocalStore(_open_local_store())
    store.add("Order", "oid-1", "create", {"sku": "A001"})
    items = store.drain(limit=5)
    assert len(items) == 1


# --- persistence: data survives a fresh connection ----------------------------

@pytest.mark.asyncio
async def test_persistence_across_restart(tmp_path):
    """Write via raw SQLite, re-open via LocalStore with the same file.
    Both connection and LocalStore share the same TempDB--no issue.
    """
    import sqlite3
    from src.core.offline import LocalStore
    db = str(tmp_path / "persist.db")

    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE pending (
            id INTEGER PRIMARY KEY, entity_type TEXT, entity_id TEXT,
            event_type TEXT NOT NULL, payload BLOB, status TEXT DEFAULT 'pending'
        )""")
    conn.execute(
        "INSERT INTO pending (entity_type, entity_id, event_type, payload, status) "
        "VALUES (?, ?, ?, ?, ?)", ["Order", "oid-42", "create", '{"sku":"X9"}', "pending"])
    conn.commit()
    conn.close()

    new = LocalStore(sqlite3.connect(db))
    items = new.drain(limit=10)
    assert len(items) == 1 and items[0]["entity_id"] == "oid-42"


# --- SyncQueue: plain-list behavior is unchanged --------------------------------

@pytest.mark.asyncio
async def test_sync_queue_append_plain():
    from src.core.offline import SyncQueue
    q = SyncQueue.new()
    q.append("hello")
    assert q[0] == "hello" and len(q) == 1


# --- queued-flag filtering ----------------------------------------------------

@pytest.mark.asyncio
async def test_sync_queue_filter_queued():
    from src.core.offline import SyncQueue, LocalStore
    store = LocalStore(_open_local_store())
    q1 = SyncQueue(store)
    q2 = SyncQueue(store)
    q1.append({"_queued": True, "entity_type": "Order", "entity_id": "1", "event_type": "create"})
    q2.append({"plain": "data"})
    assert len(q1.queued) == 1
