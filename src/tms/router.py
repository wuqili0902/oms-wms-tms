"""TMS API router — device management.

Endpoints for device registration, heartbeat, sync logs, and sessions.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.exceptions import NotFoundException, ValidationException
from src.tms.schemas import (
    DeviceRegister,
    DeviceResponse,
    DeviceUpdate,
    HeartbeatResponse,
    SessionResponse,
    SyncLogCreate,
    SyncLogResponse,
)
from src.tms import service as tms_service

router = APIRouter(prefix="/devices", tags=["tms"])


def _device_to_response(d: dict) -> dict:
    return {k: d.get(k) for k in [
        "id", "code", "name", "device_type", "platform",
        "os_version", "app_version", "status", "warehouse_id",
        "last_sync_at", "last_heartbeat_at", "config", "push_token",
        "created_at", "updated_at",
    ]}


# ── Device CRUD ──────────────────────────────────────────────────────────────

@router.post("", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    data: DeviceRegister,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return _device_to_response(await tms_service.register_device(db, data.model_dump()))
    except ValidationException as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("", response_model=list[DeviceResponse])
async def list_devices(
    warehouse_id: str = Query(None),
    status: str = Query(None, pattern=r"^(online|offline|disabled)$"),
    device_type: str = Query(None, pattern=r"^(pda|phone|scanner|printer)$"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    devices = await tms_service.list_devices(
        db, warehouse_id=warehouse_id, status=status, device_type=device_type
    )
    return [_device_to_response(d) for d in devices]


@router.get("/{dev_id}", response_model=DeviceResponse)
async def get_device(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return _device_to_response(await tms_service.get_device(db, dev_id))
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{dev_id}", response_model=DeviceResponse)
async def update_device(
    dev_id: str,
    data: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return _device_to_response(
            await tms_service.update_device(db, dev_id, data.model_dump(exclude_none=True))
        )
    except (NotFoundException, ValidationException) as e:
        code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=code, detail=str(e))


# ── Heartbeat ────────────────────────────────────────────────────────────────

@router.post("/{dev_id}/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        return await tms_service.record_heartbeat(db, dev_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Sync Logs ────────────────────────────────────────────────────────────────

@router.post("/{dev_id}/sync", response_model=SyncLogResponse, status_code=status.HTTP_201_CREATED)
async def record_sync(
    dev_id: str,
    data: SyncLogCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        log = await tms_service.record_sync(db, dev_id, data.model_dump())
        return SyncLogResponse(**log)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{dev_id}/sync", response_model=list[SyncLogResponse])
async def list_sync_logs(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        logs = await tms_service.list_sync_logs(db, dev_id)
        return [SyncLogResponse(**l) for l in logs]
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Sessions ─────────────────────────────────────────────────────────────────

@router.post("/{dev_id}/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        sess = await tms_service.create_session(db, dev_id)
        return SessionResponse(**sess)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{dev_id}/sessions/{session_id}")
async def end_session(
    dev_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        sess = await tms_service.end_session(db, dev_id, session_id)
        return {"message": "Session ended", "session": SessionResponse(**sess)}
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{dev_id}/sessions", response_model=list[SessionResponse])
async def list_sessions(
    dev_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        sessions = await tms_service.list_sessions(db, dev_id)
        return [SessionResponse(**s) for s in sessions]
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
