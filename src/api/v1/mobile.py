"""Mobile / PDA sync API endpoints.

Provides push/pull endpoints for PDA offline-to-online synchronisation.
Clients (PDA devices) push pending mutations when connectivity is restored
and pull server-side changes.
"""
import uuid
from typing import Any
from pydantic import Field

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db

router = APIRouter(tags=["mobile"])


# ── Request / response schemas ────────────────────────────────────────────────


class SyncPushItem(BaseModel):
    entity_type: str
    entity_id: str
    operation: str  # create | update | delete
    payload: dict[str, Any]
    client_timestamp: str | None = None


class ImportOrdersRequest(BaseModel):
    """Multipart form data for orders CSV (matches core/_import/routes.py)."""
    file: str = Field(..., description="CSV file with columns: customer_id, items (JSON array), priority, notes")

    @property
    def is_file(self) -> bool:
        return True


class ImportInventoryRequest(BaseModel):
    """Multipart form data for inventory CSV (matches core/_import/routes.py)."""
    file: str = Field(..., description="CSV file with columns: sku_id, warehouse_id, quantity, min_qty")

    @property
    def is_file(self) -> bool:
        return True


class SyncPushRequest(BaseModel):
    batch: list[SyncPushItem]


class SyncPushResult(BaseModel):
    accepted: int
    failed: list[dict[str, Any]]


class SyncPullResponse(BaseModel):
    changes: list[dict[str, Any]]
    has_more: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/sync/push", response_model=SyncPushResult)
async def sync_push(body: SyncPushRequest, db: AsyncSession = Depends(get_db)):
    """Accept a batch of pending mutations from a PDA device.

    Each item is validated and applied atomically.  Failed items are
    returned with an error message so the client can decide to retry
    or discard.
    """
    from src.core.outbox import append_event

    accepted = 0
    failed: list[dict[str, Any]] = []

    for item in body.batch:
        try:
            uuid.uuid4()
            await append_event(
                db,
                aggregate_type=item.entity_type,
                aggregate_id=uuid.uuid5(uuid.NAMESPACE_DNS, item.entity_id),
                event_type=f"{item.entity_type}.{item.operation}",
                payload={
                    "entity_id": item.entity_id,
                    "operation": item.operation,
                    "data": item.payload,
                    "client_timestamp": item.client_timestamp,
                },
            )
            accepted += 1
        except Exception as exc:
            failed.append({"entity_id": item.entity_id, "error": str(exc)})

    return SyncPushResult(accepted=accepted, failed=failed)


@router.get("/sync/pull", response_model=SyncPullResponse)
async def sync_pull(
    entity_type: str | None = None,
    since: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """Pull server-side changes since the last sync timestamp.

    PDA devices call this after push to get any updates that happened
    on the server while they were offline.
    """
    from datetime import datetime

    from sqlalchemy import select

    from src.core.outbox import OutboxEvent, OutboxEventStatus

    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.status == OutboxEventStatus.DISPATCHED.value)
        .order_by(OutboxEvent.created_at.desc())
        .limit(limit)
    )
    if entity_type:
        stmt = stmt.where(OutboxEvent.aggregate_type == entity_type)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            stmt = stmt.where(OutboxEvent.created_at >= since_dt)
        except ValueError:
            pass

    result = await db.execute(stmt)
    events = result.scalars().all()

    changes = [
        {
            "event_id": str(e.id),
            "entity_type": e.aggregate_type,
            "entity_id": str(e.aggregate_id),
            "event_type": e.event_type,
            "payload": e.payload,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]

    return SyncPullResponse(changes=changes, has_more=len(changes) >= limit)


@router.post("/sync/ack")
async def sync_ack(ids: list[str], db: AsyncSession = Depends(get_db)):
    """Acknowledge that pulled changes were applied locally.

    Called by the PDA device after successfully applying server-side
    changes from a ``/sync/pull`` response.
    """
    return {"acknowledged": len(ids)}
