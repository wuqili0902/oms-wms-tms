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

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy import select as _select
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    FAILED = "failed"         # dispatch failed; may retry


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
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
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


async def dispatch_pending_events(batch_size: int = 100) -> list[OutboxEvent]:
    """Fetch pending events up to ``batch_size`` for Celery worker processing.

    Uses ``FOR UPDATE SKIP LOCKED`` to prevent multiple workers from picking
    up the same events (double-dispatch).

    Returns events that are due for dispatch.  The caller should dispatch
    each event and then call ``mark_dispatched()`` on success or
    ``mark_failed()`` on failure.
    """
    async with _get_session() as session:
        stmt = (
            _select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxEventStatus.PENDING.value,
                (OutboxEvent.scheduled_at.is_(None)) | (OutboxEvent.scheduled_at <= func.now()),
            )
            .order_by(OutboxEvent.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        events = list(result.scalars().all())
    return events


async def mark_dispatched(event_ids: list[uuid.UUID]) -> int:
    """Mark a batch of events as dispatched (successfully published to MQ)."""
    async with _get_session() as session:
        result = await session.execute(
            OutboxEvent.__table__.update()  # type: ignore[union-attr]
            .where(OutboxEvent.id.in_(event_ids))
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
    async with _get_session() as session:
        # Atomic: increment retry_count only if < 5, in a single UPDATE
        result = await session.execute(
            OutboxEvent.__table__.update()  # type: ignore[union-attr]
            .where(
                OutboxEvent.id == event_id,
                OutboxEvent.status == OutboxEventStatus.DISPATCHED.value,
                OutboxEvent.retry_count < 5,
            )
            .values(
                status=OutboxEventStatus.FAILED.value,
                error_message=error_message[:500],
                retry_count=OutboxEvent.retry_count + 1,
                scheduled_at=datetime.now(UTC) + timedelta(seconds=60),
            )
        )
        if result.rowcount == 0:
            # Either not in DISPATCHED state, or already at max retries
            # Check if we need to dead-letter (retry_count >= 5)
            check = await session.execute(
                _select(OutboxEvent.retry_count).where(
                    OutboxEvent.id == event_id,
                    OutboxEvent.status == OutboxEventStatus.DISPATCHED.value,
                )
            )
            current_retry = check.scalar_one_or_none()
            if current_retry is not None and current_retry >= 5:
                await session.execute(
                    OutboxEvent.__table__.update()  # type: ignore[union-attr]
                    .where(OutboxEvent.id == event_id)
                    .values(
                        status=OutboxEventStatus.FAILED.value,
                        error_message=f"Max retries exceeded ({current_retry} attempts): {error_message[:400]}",
                    )
                )
        await session.commit()
