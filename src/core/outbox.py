"""Outbox pattern implementation for cross-service data consistency.

The Outbox pattern ensures that every business transaction that produces
side effects (e.g. order → payment) is recorded atomically in a local
database table, and a separate worker eventually dispatches these events
(e.g. via HTTP POST) — guaranteeing reliable delivery without distributed
transactions.

Typical flow:
    1. OrderService creates an ORDER row AND appends an OUTBOX event row
       inside the same database transaction.
    2. A background Celery task (or cron) polls `outbox_events` for rows
       whose `status = 'pending'`, dispatches them, then marks them
       `dispatched`.

References:
    - Microservices Pattern – Outbox: https://microservices.io/patterns/data/Outbox.html
"""
import logging
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Index, String, Text, and_, func, or_
from sqlalchemy import Uuid as UUID  # noqa: N814 — column type, not a constant; dialect-neutral
from sqlalchemy import select as _select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

logger = logging.getLogger(__name__)


# Memory cache fallback (used when Redis is unavailable)
try:
    from src.cache.redis_client import get_memory_cache  # noqa: F401
except ImportError:
    pass


def _get_session():
    """Lazy-import session factory to avoid circular imports."""
    from src.core.database import get_session
    return get_session


def _get_base():
    """Lazy-import Base to avoid circular imports."""
    from src.models.base import Base
    return Base


class OutboxEventStatus(StrEnum):
    """Outbox event lifecycle states."""

    PENDING = "pending"       # committed but not yet dispatched to MQ
    DISPATCHED = "dispatched"  # successfully dispatched
    FAILED = "failed"         # dispatch failed; scheduled for retry
    DEAD_LETTERED = "dead_lettered"  # max retries exceeded; no longer retried


# Cap on delivery attempts per outbox event before it is dead-lettered.
MAX_OUTBOX_RETRIES = 5

# An event sitting in DISPATCHED for longer than this was picked up by a
# dispatcher that crashed (or was killed) before POSTing it — reaper reclaim.
DISPATCH_LEASE_MINUTES = 15


class OutboxEvent(_get_base()):
    """Represents a domain event waiting for delivery.

    Schema:
        id              UUID PK          Unique event ID (UUIDv7 recommended)
        aggregate_type  str              e.g. 'Order', 'InventoryAdjustment'
        aggregate_id    UUID             The entity that generated the event
        event_type      str              e.g. 'order.created', 'payment.processed'
        payload         JSONB            Event-specific data (serialised dict)
        status          str              PENDING / DISPATCHED / FAILED
        retry_count     int              Number of dispatch attempts
        error_message   Text             Last error encountered during dispatch
        scheduled_at    datetime         When this event should be retried (NULL = ASAP)
        dispatched_at   datetime | None  Time when finally published to MQ
        created_at      datetime
        updated_at      datetime | None

    Usage:
        from src.core.outbox import outbox_service
        await outbox_service.append(
            aggregate_type="Order",
            aggregate_id=order_id,
            event_type="order.created",
            payload={"amount": 120.50},
        )
    """

    __tablename__ = "outbox_events"

    # ── columns ───────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=OutboxEventStatus.PENDING.value
    )
    retry_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── indexes (fast lookup + dispatch query) ────────────────────────────
    __table_args__ = (
        Index("ix_outbox_events_status_created", "status", "created_at"),
        Index("ix_outbox_events_aggregate_type_id", "aggregate_type", "aggregate_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "aggregate_type": self.aggregate_type,
            "aggregate_id": str(self.aggregate_id),
            "event_type": self.event_type,
            "payload": self.payload,
            "status": self.status,
            "retry_count": self.retry_count,
            "error_message": self.error_message,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "dispatched_at": self.dispatched_at.isoformat() if self.dispatched_at else None,
        }


# ── Service layer (append + dispatch) ────────────────────────────────────────


async def append_event(
    db: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    """Append an outbox event **within the caller's transaction**.

    Call this in the same DB transaction as the business logic (e.g. inside
    ``create_order``) so that the event is committed atomically with the
    entity change.  Do **not** commit here — the caller owns the transaction.
    """
    event = OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
    )
    db.add(event)
    await db.flush()
    return event


async def dispatch_pending_events(batch_size: int = 100) -> list[dict[str, Any]]:
    """Fetch pending events up to ``batch_size`` for Celery worker processing.

    Uses ``FOR UPDATE SKIP LOCKED`` to prevent multiple workers from picking
    up the same events (double-dispatch).

    Returns serialised dicts (not ORM objects) so callers never hold
    detached references.  After dispatching, call ``mark_dispatched()``
    or ``mark_failed()``.
    """
    async with _get_session() as session:
        lease_cutoff = datetime.now(UTC) - timedelta(minutes=DISPATCH_LEASE_MINUTES)
        # Reaper step 1: DISPATCHED rows older than the lease whose retries
        # are exhausted are dead-letters, not in-flight work.
        await session.execute(
            OutboxEvent.__table__.update()  # type: ignore[union-attr]
            .where(
                OutboxEvent.status == OutboxEventStatus.DISPATCHED.value,
                OutboxEvent.dispatched_at.isnot(None),
                OutboxEvent.dispatched_at <= lease_cutoff,
                OutboxEvent.retry_count >= MAX_OUTBOX_RETRIES,
            )
            .values(status=OutboxEventStatus.DEAD_LETTERED.value)
        )
        stmt = (
            _select(OutboxEvent)
            .where(
                or_(
                    OutboxEvent.status == OutboxEventStatus.PENDING.value,
                    and_(
                        OutboxEvent.status == OutboxEventStatus.FAILED.value,
                        (OutboxEvent.scheduled_at.is_(None)) | (OutboxEvent.scheduled_at <= func.now()),
                    ),
                    # Reaper step 2: re-pick DISPATCHED rows stranded by a
                    # dispatcher that crashed between fetch and POST (the
                    # status was already flipped, so a plain poll would
                    # strand them forever).
                    and_(
                        OutboxEvent.status == OutboxEventStatus.DISPATCHED.value,
                        OutboxEvent.dispatched_at.isnot(None),
                        OutboxEvent.dispatched_at <= lease_cutoff,
                        OutboxEvent.retry_count < MAX_OUTBOX_RETRIES,
                    ),
                )
            )
            .order_by(OutboxEvent.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        events = list(result.scalars().all())
        # Mark as DISPATCHED within the same session so the lock is held
        # until the status update is committed.
        now = datetime.now(UTC)
        for ev in events:
            if ev.status == OutboxEventStatus.DISPATCHED.value:
                # Reclaimed from a stale lease: consume one delivery attempt
                # so a repeatedly crashing dispatcher dead-letters instead
                # of cycling the same events every beat forever.
                ev.retry_count = (ev.retry_count or 0) + 1
            ev.status = OutboxEventStatus.DISPATCHED.value
            ev.dispatched_at = now
        await session.commit()
    # Return serialised copies so callers never hold ORM references
    return [
        {
            "id": str(ev.id),
            "aggregate_type": ev.aggregate_type,
            "aggregate_id": str(ev.aggregate_id),
            "event_type": ev.event_type,
            "payload": ev.payload,
            "status": ev.status,
            "retry_count": ev.retry_count,
        }
        for ev in events
    ]


def _coerce_uuid(value):
    """Accept str/UUID ids; pass through anything that isn't a UUID.

    The Celery dispatcher hands back string ids (JSON-serialised), while the
    column is a UUID type — coerce when possible so PostgreSQL binds cleanly,
    and leave odd test fixtures (``"id-1"``) untouched rather than raising.
    """
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return value


async def mark_dispatched(event_ids: list[uuid.UUID]) -> int:
    """Mark a batch of events as dispatched (successfully published to MQ)."""
    async with _get_session() as session:
        result = await session.execute(
            OutboxEvent.__table__.update()  # type: ignore[union-attr]
            .where(OutboxEvent.id.in_([_coerce_uuid(i) for i in event_ids]))
            .values(
                status=OutboxEventStatus.DISPATCHED.value,
                dispatched_at=datetime.now(UTC),
            )
        )
        rowcount = result.rowcount
        await session.commit()
    return rowcount  # type: ignore[return-value]


async def mark_failed(event_id: uuid.UUID, error_message: str) -> None:
    """Mark an event as failed and schedule a retry after exponential backoff.

    Uses a single atomic UPDATE to avoid TOCTOU race on retry_count.
    Only marks FAILED if the event is still in DISPATCHED state.
    Max retries capped at 5; events exceeding limit become dead letters.
    """
    event_id = _coerce_uuid(event_id)
    async with _get_session() as session:
        # Atomic: increment retry_count only while below the cap, in a single UPDATE.
        result = await session.execute(
            OutboxEvent.__table__.update()  # type: ignore[union-attr]
            .where(
                OutboxEvent.id == event_id,
                OutboxEvent.status == OutboxEventStatus.DISPATCHED.value,
                OutboxEvent.retry_count < MAX_OUTBOX_RETRIES,
            )
            .values(
                status=OutboxEventStatus.FAILED.value,
                error_message=error_message[:500],
                retry_count=OutboxEvent.retry_count + 1,
                scheduled_at=datetime.now(UTC) + timedelta(seconds=60),
            )
        )
        if result.rowcount == 0:
            # Either not in DISPATCHED state, or already at max retries.
            # Read the current retry count regardless of status (by now the event is
            # FAILED, so filtering on DISPATCHED would miss it and never dead-letter).
            check = await session.execute(
                _select(OutboxEvent.retry_count).where(
                    OutboxEvent.id == event_id,
                )
            )
            current_retry = check.scalar_one_or_none()
            if current_retry is not None and current_retry >= MAX_OUTBOX_RETRIES:
                # Cap reached → dead-letter so the dispatcher stops re-selecting it.
                await session.execute(
                    OutboxEvent.__table__.update()  # type: ignore[union-attr]
                    .where(OutboxEvent.id == event_id)
                    .values(
                        status=OutboxEventStatus.DEAD_LETTERED.value,
                        error_message=f"Max retries exceeded ({current_retry} attempts): {error_message[:400]}",
                    )
                )
        await session.commit()
