"""PDA offline mode: SQLite local storage + SyncQueue for eventual consistency."""


# --- Local store (in-memory, auto-committing) ----------------------------------

def _open_local_store() -> "LocalStore":
    """Create a fresh in-memory SQLite DB seeded with schema."""
    from sqlite3 import connect
    conn = connect(":memory:")
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("""
        CREATE TABLE pending (
            id INTEGER PRIMARY KEY, entity_type TEXT, entity_id TEXT,
            event_type TEXT NOT NULL, payload BLOB, status TEXT DEFAULT 'pending'
        )""")
    return conn


class LocalStore:
    """Holds pending mutations for later sync to the remote server."""

    def __init__(self, conn=None):
        self._conn = conn or _open_local_store()._conn

    def add(self, entity_type: str, entity_id: str, event_type: str,
            payload: dict | None = None):
        conn = self._conn
        conn.execute(
            "INSERT INTO pending (entity_type, entity_id, event_type, payload, status)"
            " VALUES (?, ?, ?, ?, ?)",
            [entity_type, entity_id, event_type, json.dumps(payload) if payload else None, "pending"])
        conn.commit()

    def drain(self, limit: int = 100) -> list[dict]:
        """Flush pending events to remote (return the payloads)."""
        rows = self._conn.execute(
            f"SELECT entity_type,entity_id,event_type,payload,status "
            f"FROM pending LIMIT ?", [limit])
        items: list[dict] = []
        for r in rows:
            d = {"entity_type": r[0], "entity_id": r[1], "event_type": r[2],
                  "payload": json.loads(r[3]) if r[3] else {}, "status": r[4]}
            items.append(d)
        return items

    def clear(self):
        self._conn.execute("DELETE FROM pending")
        self._conn.commit()

# --- SyncQueueService: manages SQLite-based sync queue -------------------------


class _Record:
    """Thin wrapper around a row from the local SQLite DB."""

    def __init__(self, id, entity_type, entity_id, operation, payload):
        self.id = id
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.operation = operation
        self.payload = payload


class SyncQueueService:
    """Manages a SQLite-based sync queue for PDA offline mutations."""

    def __init__(self, db_path="wms_pda.db"):
        import sqlite3 as sqlite
        conn = sqlite.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_queue (
                id INTEGER PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                payload TEXT,
                status TEXT DEFAULT 'pending',
                failed_at TIMESTAMP,
                error_message TEXT
            )""")
        conn.execute("INSERT OR IGNORE INTO sync_queue (entity_type, entity_id, operation, payload) VALUES ('Order', 'ORD-INIT', 'create', '{}')")
        conn.commit()
        self.conn = conn

    def get_pending(self, limit=100):
        """Return pending records up to *limit* as ``_Record`` instances."""
        rows = self.conn.execute(
            "SELECT id, entity_type, entity_id, operation, payload FROM sync_queue WHERE status='pending' ORDER BY id LIMIT ?", [limit]
        )
        return [_Record(*r) for r in rows]

    def mark_synced(self, ids):
        """Mark records as synced; returns number actually updated."""
        placeholders = ",".join("?" * len(ids))
        sql = f"UPDATE sync_queue SET status='synced' WHERE id IN ({placeholders})"
        cur = self.conn.execute(sql, ids)
        self.conn.commit()
        return cur.rowcount

    def mark_failed(self, record_id, error):
        """Mark a single record as failed with an error message."""
        self.conn.execute(
            "UPDATE sync_queue SET status='failed', error_message=?, failed_at=CURRENT_TIMESTAMP WHERE id=?",
            [str(error), record_id],
        )
        self.conn.commit()


# --- JSON helper (so the module is importable without pydantic/typing imports) --

import json  # noqa: E402


__all__ = ["LocalStore", "SyncQueue", "SyncQueueService"]
