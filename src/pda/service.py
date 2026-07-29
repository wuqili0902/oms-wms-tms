"""PDA business logic — offline mutation queue and sync orchestration."""
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.outbox import append_event
from src.pda.models import PendingMutation, SyncOperation

logger = logging.getLogger(__name__)


async def enqueue_mutation(
    db: AsyncSession,
    device_id: str,
    entity_type: str,
    entity_id: str,
    operation: SyncOperation,
    payload: dict,
) -> PendingMutation:
    mutation = PendingMutation(
        device_id=device_id,
        entity_type=entity_type,
        entity_id=entity_id,
        operation=operation.value,
        payload=json.dumps(payload),
    )
    db.add(mutation)
    await db.commit()
    await db.refresh(mutation)

    # Broadcast the event to all connected PDAs in real-time.
    from src.pda.ws import _manager  # type: ignore[import-not-found,unused-import]

    broadcast_payload = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "operation": operation.value,
        "mutation_id": str(mutation.id),
    }

    try:
        await _manager.broadcast(broadcast_payload)
    except Exception as e:
        logger.warning("PDA WS broadcast failed for mutation %s: %s", mutation.id, e)

    return mutation


async def process_pending_mutations(db: AsyncSession, batch_size: int = 50) -> dict:
    result = await db.execute(
        select(PendingMutation)
        .where(PendingMutation.synced_at.is_(None))
        .order_by(PendingMutation.created_at.asc())
        .limit(batch_size)
    )
    mutations = result.scalars().all()
    accepted = 0
    failed = 0
    for m in mutations:
        try:
            await append_event(
                db,
                aggregate_type=m.entity_type,
                aggregate_id=m.id,
                event_type=f"{m.entity_type}.{m.operation}",
                payload={
                    "entity_id": m.entity_id,
                    "operation": m.operation,
                    "data": json.loads(m.payload),
                },
            )
            m.synced_at = datetime.now(UTC)
            accepted += 1
        except Exception:
            m.retry_count = (m.retry_count or 0) + 1
            failed += 1
    await db.commit()
    return {"accepted": accepted, "failed": failed}
