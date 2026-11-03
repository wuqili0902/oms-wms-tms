"""PDA API endpoints — offline queue management."""
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_current_user
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


class MutationCreatedResponse(BaseModel):
    id: int
    status: str


class MutationItem(BaseModel):
    id: int
    device_id: str
    entity_type: str
    entity_id: str
    operation: str
    created_at: str
    synced_at: str | None
    retry_count: int


class SyncResultResponse(BaseModel):
    # Must match the dict returned by ``process_pending_mutations`` —
    # a mismatch here made FastAPI response validation raise 500.
    accepted: int
    failed: int


@router.post("/mutations", response_model=MutationCreatedResponse)
async def create_mutation(
    body: MutationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    mutation = await enqueue_mutation(
        db, body.device_id, body.entity_type, body.entity_id, body.operation, body.payload,
    )
    return {"id": mutation.id, "status": "queued"}


@router.get("/mutations", response_model=list[MutationItem])
async def list_mutations(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(PendingMutation).order_by(PendingMutation.created_at.desc()).offset(skip).limit(limit)
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


@router.post("/sync", response_model=SyncResultResponse)
async def sync_mutations(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    result = await process_pending_mutations(db)
    return result


# WebSocket endpoint for real-time offline-queue updates.
# client_id is the device id used in the connect payload; we key by it to route
# messages back to the right PDA session.
@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, client_id: str = "", token: str = "") -> None:
    if not client_id:
        await websocket.accept()
        await websocket.close(code=4001, reason="client_id required")
        return

    if not token:
        await websocket.accept()
        await websocket.close(code=4001, reason="token required")
        return

    try:
        from src.core.security import TokenExpired, decode_token
    except ImportError:
        # Fail *closed*: if token verification can't be loaded, refuse the
        # connection instead of granting unauthenticated access.
        await websocket.close(code=1008, reason="Token verification unavailable")
        return

    try:
        decode_token(token)
    except TokenExpired:
        await websocket.accept()
        await websocket.close(code=4001, reason="Token expired")
        return
    except Exception:
        await websocket.accept()
        await websocket.close(code=4001, reason="Invalid token")
        return

    # connect() performs the accept and registers the connection (the old
    # code accepted here too and never awaited connect, so the registration
    # coroutine was dropped and the socket closed immediately after).
    await _manager.connect(client_id, websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        _manager.disconnect(client_id, websocket)

