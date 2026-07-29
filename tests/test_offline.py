"""Tests for src.core.offline — LocalStore + SyncQueue."""


# --- LocalStore --------------------------------------------------------------

def test_local_store_add():
    from src.core.offline import _open_local_store, LocalStore
    store = LocalStore(_open_local_store())
    store.add("Order", "oid-1", "create", {"sku": "A001"})


def test_local_store_drain():
    from src.core.offline import _open_local_store, LocalStore
    store = LocalStore(_open_local_store())
    store.add("Order", "oid-1", "create", {"sku": "A001"})
    items = store.drain()
    assert len(items) >= 1
    assert items[0]["entity_type"] == "Order"


def test_local_store_clear():
    from src.core.offline import _open_local_store, LocalStore
    store = LocalStore(_open_local_store())
    store.add("Order", "oid-1", "create", {"sku": "A001"})
    store.clear()
    items = store.drain()
    assert items == []


# --- SyncQueue (drop-in list) ------------------------------------------------

def test_sync_queue_append_plain():
    from src.core.offline import SyncQueue
    q = SyncQueue.new()
    q.append("hello")
    assert q[0] == "hello" and len(q) == 1


def test_sync_queue_unchanged_plain_item():
    from src.core.offline import SyncQueue
    q = SyncQueue.new()
    q.append({"plain": "data"})  # no _queued flag -> not queued
    assert len(q) == 1


def test_sync_queue_append_queued():
    from src.core.offline import SyncQueue
    q = SyncQueue.new()
    q.append({"_queued": True, "entity_type": "Order", "entity_id": "o-1", "event_type": "create"})
    assert len(q) == 1
    assert len(q.queued) == 1
    assert q.queued[0]["entity_id"] == "o-1"


def test_sync_queue_queued_excludes_plain():
    from src.core.offline import SyncQueue
    q = SyncQueue.new()
    q.append({"plain": "data"})
    q.append({"_queued": True, "entity_type": "Order", "entity_id": "o-1", "event_type": "create"})
    assert len(q) == 2
    assert len(q.queued) == 1
