"""PDA API endpoints — offline queue management."""
from fastapi import APIRouter, Depends, WebSocket
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.pda.models import PendingMutation, SyncOperation
from src.pda.service import enqueue_mutation, process_pending_mutations
from src.pda.ws import _manager  # type: ignore[name-defined]

router = APIRouter(prefix="/pda", tags=["pda"])


class MutationCreate(BaseModel):
    device_id: str
    entity_type: str
    entity_id: str
    operation: SyncOperation
    payload: dict


@router.post("/mutations")
async def create_mutation(body: MutationCreate, db: AsyncSession = Depends(get_db)):
    mutation = await enqueue_mutation(
        db, body.device_id, body.entity_type, body.entity_id, body.operation, body.payload,
    )
    return {"id": mutation.id, "status": "queued"}


@router.get("/mutations")
async def list_mutations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PendingMutation).order_by(PendingMutation.created_at.desc()).limit(100)
    )
    rows = result.scalars().all()
    return [
        {
            "id": m.id,
            "device_id": m.device_id,
            "entity_type": m.entity_type,
            "entity_id": m.entity_id,
            "operation": m.operation,
            "created_at": m.created_at.isoformat() if m.created_at else "",
            "synced_at": m.synced_at.isoformat() if m.synced_at else None,
            "retry_count": m.retry_count,
        }
        for m in rows
    ]


@router.post("/sync")
async def sync_mutations(db: AsyncSession = Depends(get_db)):
    result = await process_pending_mutations(db)
    return result


# WebSocket endpoint for real-time offline-queue updates.
# client_id is the device id used in the connect payload; we key by it to route
# messages back to the right PDA session.
@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, client_id: str = "") -> None:
    if not client_id:
        await websocket.accept()
    else:
        await websocket.accept()
        # Register this connection so future events reach it.
        _manager.connect(client_id, websocket)

