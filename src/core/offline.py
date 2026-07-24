"""PDA offline mode: SQLite local storage + SyncQueue for eventual consistency.

Design
------
When a warehouse worker's PDA device has no network connectivity,
local read/write operations continue against an embedded SQLite DB.
When the connection is restored, a *sync queue* (outbox-style) pushes
pending mutations back to the remote PostgreSQL server.

Sync rules
----------
1. All pending mutations are sent as JSON payloads via HTTP POST /api/v1/sync/push
2. The remote server validates and applies each mutation atomically
3. Upon success, local records are marked `synced_at = NOW()`
4. Conflicts (optimistic lock) trigger a merge strategy
5. Retries use exponential back-off up to 5 attempts

Conflict strategies
-------------------
- Last-Write-Wins (LWW): latest timestamp wins — suitable for most warehouse ops
- Merge: combine fields from local and remote copies
- Manual: create an alert row in admin dashboard for operator resolution
"""

import json
from datetime import datetime, UTC
from enum import Enum
from typing import Any
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    create_engine as _create_engine,
)
from sqlalchemy.orm import sessionmaker


# ── Enums ───────────────────────────────────────────────────────────────


class SyncDirection(str, Enum):
    """Which way data is flowing."""

    UP = "up"           # PDA → server (push mutations)
    DOWN = "down"       # Server → PDA (pull changes)


class MutationType(str, Enum):
    """Types of local mutation that need sync."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


# ── SyncQueue model (local SQLite only) ───────────────────────────────


class SyncQueue(Base):
    """A pending mutation waiting to be pushed to the remote server.

    Schema:
        id              UUID PK
        entity_type     str   e.g. 'InventoryItem', 'PurchaseOrder'
        entity_id       str   primary key of the affected row on remote
        operation       str   CREATE | UPDATE | DELETE
        payload         JSONB serialized mutation data
        direction       str   up | down
        priority        int   0 (normal) … 9 (critical — always first)
        retry_count     int   how many times we've tried to push
        max_retries     int   default 5
        pushed_at       datetime | None
        synced_at       datetime | None
        error_message   str | None
    """

    __tablename__ = "sync_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String(64), nullable=False)
    entity_id = Column(String(128), nullable=False)
    operation = Column(String(16), nullable=False)
    payload = Column(Text, nullable=False)  # JSON string in SQLite
    direction = Column(String(8), default="up")
    priority = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=5)
    pushed_at = Column(DateTime(timezone=True))
    synced_at = Column(DateTime(timezone=True))
    error_message = Column(Text)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class SyncRecord(Base):
    """Remote-server changes that need to be pulled down to PDA.

    Schema mirrors SyncQueue but represents server → client sync.
    """

    __tablename__ = "sync_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String(64), nullable=False)
    entity_id = Column(String(128), nullable=False)
    payload = Column(Text, nullable=False)
    operation = Column(String(16))  # CREATE/UPDATE/DELETE on server side
    pulled_at = Column(DateTime(timezone=True))

# ── SyncQueue service (local SQLite operations) ───────────────────────


class SyncQueueService:
    """Manage local sync queue operations."""

    def __init__(self, db_path: str):
        self.engine = _create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self.engine)
        self.SessionFactory = sessionmaker(bind=self.engine)

    def enqueue(
        self,
        entity_type: str,
        entity_id: str,
        operation: MutationType,
        payload: dict[str, Any],
        priority: int = 0,
    ) -> SyncQueue:
        """Add a mutation to the local queue."""
        with self.SessionFactory() as session:
            record = SyncQueue(
                entity_type=entity_type,
                entity_id=entity_id,
                operation=operation.value,
                payload=json.dumps(payload),
                priority=priority,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
        return record

    def enqueue_bulk(self, items: list[dict[str, Any]]) -> int:
        """Bulk insert multiple records (for batch sync)."""
        with self.SessionFactory() as session:
            for item in items:
                record = SyncQueue(
                    entity_type=item["entity_type"],
                    entity_id=item["entity_id"],
                    operation=item["operation"].value,
                    payload=json.dumps(item.get("payload", {})),
                )
                session.add(record)
            session.commit()
        return len(items)

    def get_pending(self, limit: int = 50) -> list[SyncQueue]:
        """Get unsynced records ordered by priority then creation time."""
        with self.SessionFactory() as session:
            stmt = (
                select(SyncQueue)
                .where(SyncQueue.synced_at.is_(None))
                .order_by(
                    SyncQueue.priority.desc(),
                    SyncQueue.created_at.asc(),
                )
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())

    def mark_synced(self, ids: list[uuid.UUID]) -> int:
        """Mark records as synced."""
        with self.SessionFactory() as session:
            from sqlalchemy import update
            stmt = (
                update(SyncQueue)
                .where(SyncQueue.id.in_(ids))
                .values(synced_at=datetime.now(UTC))
            )
            result = session.execute(stmt)
            session.commit()
        return result.rowcount

    def mark_failed(self, record_id: uuid.UUID, error_message: str) -> None:
        """Update retry count and set error message."""
        with self.SessionFactory() as session:
            from sqlalchemy import update
            stmt = (
                update(SyncQueue)
                .where(SyncQueue.id == record_id)
                .values(
                    retry_count=SyncQueue.retry_count + 1,
                    error_message=error_message[:500],
                    pushed_at=datetime.now(UTC),
                )
            )
            session.execute(stmt)
            session.commit()

    def pull_records(self, entity_types: list[str] | None = None) -> list[SyncRecord]:
        """Fetch records that need to be pulled down (server → PDA)."""
        with self.SessionFactory() as session:
            stmt = select(SyncRecord).where(
                SyncRecord.pulled_at.is_(None)
            )
            if entity_types:
                stmt = stmt.where(SyncRecord.entity_type.in_(entity_types))
            return list(session.execute(stmt.order_by(SyncRecord.created_at)).scalars().all())

    def pull_marked(self, ids: list[uuid.UUID]) -> None:
        """Mark pulled records as acknowledged."""
        with self.SessionFactory() as session:
            from sqlalchemy import update
            stmt = (
                update(SyncRecord)
                .where(SyncRecord.id.in_(ids))
                .values(pulled_at=datetime.now(UTC))
            )
            session.execute(stmt)
            session.commit()

# ── Helper functions ───────────────────────────────────────────────────


def get_local_db_path(config: Settings | None = None) -> str:
    """Get the local SQLite DB path from config or default."""
    if config and hasattr(config, 'pda_local_db_path'):
        return config.pda_local_db_path
    return "wms_pda.db"
