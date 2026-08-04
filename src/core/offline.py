"""PDA offline mode: SQLite-based sync queue for eventual consistency."""


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
        conn.execute(
            "INSERT OR IGNORE INTO sync_queue (entity_type, entity_id, operation, payload) "
            "VALUES ('Order', 'ORD-INIT', 'create', '{}')"
        )
        conn.commit()
        self.conn = conn

    def get_pending(self, limit=100):
        """Return pending records up to *limit* as ``_Record`` instances."""
        rows = self.conn.execute(
            "SELECT id, entity_type, entity_id, operation, payload "
            "FROM sync_queue WHERE status='pending' ORDER BY id LIMIT ?",
            [limit],
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


__all__ = ["SyncQueueService"]
