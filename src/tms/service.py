"""TMS business logic — device registration, heartbeat, sync logs, sessions.

All CRUD functions are async and require an ``AsyncSession``.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException, ValidationException
from src.models.base import model_to_dict
from src.tms.models import (
    DeviceSession,
    DeviceStatus,
    SyncLog,
    SyncLogStatus,
    SyncLogType,
    TerminalDevice,
    TerminalDeviceType,
    PlatformType,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_uuid(val: str | uuid.UUID | None) -> uuid.UUID | None:
    """Convert a string or UUID value to ``uuid.UUID``, or return None."""
    if val is None or isinstance(val, uuid.UUID):
        return val
    return uuid.UUID(val)


# ── Device CRUD ──────────────────────────────────────────────────────────────

async def register_device(db: AsyncSession, data: dict) -> dict:
    """Register a new terminal device."""
    # Check unique code
    existing = await db.execute(select(TerminalDevice).where(TerminalDevice.code == data["code"]))
    if existing.scalar_one_or_none():
        raise ValidationException(message=f"Device code '{data['code']}' already exists")

    device = TerminalDevice(
        id=uuid.uuid4(),
        code=data["code"],
        name=data.get("name", ""),
        device_type=TerminalDeviceType(data.get("device_type", "pda")),
        platform=PlatformType(data.get("platform", "android")),
        os_version=data.get("os_version", ""),
        app_version=data.get("app_version", ""),
        status=DeviceStatus.OFFLINE,
        warehouse_id=_to_uuid(data.get("warehouse_id")),
        config=data.get("config"),
        push_token=data.get("push_token"),
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return model_to_dict(device)


async def get_device(db: AsyncSession, dev_id: str) -> dict:
    """Get a device by ID."""
    result = await db.execute(select(TerminalDevice).where(TerminalDevice.id == uuid.UUID(dev_id)))
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundException(message=f"Device {dev_id} not found")
    return model_to_dict(dev)


async def list_devices(
    db: AsyncSession,
    warehouse_id: str | None = None,
    status: str | None = None,
    device_type: str | None = None,
) -> list[dict]:
    """List devices with optional filters."""
    stmt = select(TerminalDevice)
    if warehouse_id:
        stmt = stmt.where(TerminalDevice.warehouse_id == uuid.UUID(warehouse_id))
    if status:
        stmt = stmt.where(TerminalDevice.status == DeviceStatus(status))
    if device_type:
        stmt = stmt.where(TerminalDevice.device_type == TerminalDeviceType(device_type))
    stmt = stmt.order_by(TerminalDevice.created_at.desc())
    result = await db.execute(stmt)
    return [model_to_dict(d) for d in result.scalars().all()]


async def update_device(db: AsyncSession, dev_id: str, data: dict) -> dict:
    """Update device fields."""
    result = await db.execute(select(TerminalDevice).where(TerminalDevice.id == uuid.UUID(dev_id)))
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundException(message=f"Device {dev_id} not found")

    updatable = {"name", "os_version", "app_version", "warehouse_id", "config", "push_token", "status"}
    for key in updatable:
        if key in data and data[key] is not None:
            if key == "status":
                setattr(dev, key, DeviceStatus(data[key]))
            elif key == "warehouse_id":
                setattr(dev, key, uuid.UUID(data[key]) if data[key] else None)
            else:
                setattr(dev, key, data[key])
    dev.updated_at = _now()

    await db.commit()
    await db.refresh(dev)
    return model_to_dict(dev)


# ── Heartbeat ────────────────────────────────────────────────────────────────

async def record_heartbeat(db: AsyncSession, dev_id: str) -> dict:
    """Record device heartbeat — marks device online."""
    result = await db.execute(select(TerminalDevice).where(TerminalDevice.id == uuid.UUID(dev_id)))
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundException(message=f"Device {dev_id} not found")

    now = _now()
    dev.last_heartbeat_at = now
    dev.status = DeviceStatus.ONLINE
    dev.updated_at = now

    await db.commit()
    return {
        "id": dev_id,
        "status": "online",
        "last_heartbeat_at": now.isoformat(),
        "message": "Heartbeat received",
    }


# ── Sync Logs ────────────────────────────────────────────────────────────────

async def record_sync(db: AsyncSession, dev_id: str, data: dict) -> dict:
    """Record a sync operation for a device."""
    result = await db.execute(select(TerminalDevice).where(TerminalDevice.id == uuid.UUID(dev_id)))
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundException(message=f"Device {dev_id} not found")

    now = _now()
    log = SyncLog(
        id=uuid.uuid4(),
        device_id=uuid.UUID(dev_id),
        sync_type=SyncLogType(data.get("sync_type", "download")),
        status=SyncLogStatus(data.get("status", "pending")),
        records_count=data.get("records_count", 0),
        error_message=data.get("error_message"),
        started_at=now,
        completed_at=now if data.get("status") in ("completed", "failed") else None,
    )
    db.add(log)

    # Update device
    dev.last_sync_at = now
    dev.status = DeviceStatus.ONLINE
    dev.updated_at = now

    await db.commit()
    await db.refresh(log)
    return model_to_dict(log)


async def list_sync_logs(db: AsyncSession, dev_id: str) -> list[dict]:
    """List sync logs for a device."""
    # Verify device exists
    result = await db.execute(select(TerminalDevice).where(TerminalDevice.id == uuid.UUID(dev_id)))
    if not result.scalar_one_or_none():
        raise NotFoundException(message=f"Device {dev_id} not found")

    logs_result = await db.execute(
        select(SyncLog)
        .where(SyncLog.device_id == uuid.UUID(dev_id))
        .order_by(SyncLog.started_at.desc())
    )
    return [model_to_dict(l) for l in logs_result.scalars().all()]


# ── Sessions ─────────────────────────────────────────────────────────────────

async def create_session(db: AsyncSession, dev_id: str, ip_address: str | None = None) -> dict:
    """Create a new device session."""
    result = await db.execute(select(TerminalDevice).where(TerminalDevice.id == uuid.UUID(dev_id)))
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundException(message=f"Device {dev_id} not found")

    now = _now()
    sess = DeviceSession(
        id=uuid.uuid4(),
        device_id=uuid.UUID(dev_id),
        ip_address=ip_address,
        login_at=now,
    )
    db.add(sess)

    dev.status = DeviceStatus.ONLINE
    dev.updated_at = now

    await db.commit()
    await db.refresh(sess)
    return model_to_dict(sess)


async def end_session(db: AsyncSession, dev_id: str, sess_id: str) -> dict:
    """End a device session."""
    result = await db.execute(
        select(DeviceSession).where(
            DeviceSession.id == uuid.UUID(sess_id),
            DeviceSession.device_id == uuid.UUID(dev_id),
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise NotFoundException(message=f"Session {sess_id} not found for device {dev_id}")

    now = _now()
    sess.logout_at = now

    await db.commit()
    await db.refresh(sess)
    return model_to_dict(sess)


async def list_sessions(db: AsyncSession, dev_id: str) -> list[dict]:
    """List sessions for a device."""
    result = await db.execute(
        select(TerminalDevice).where(TerminalDevice.id == uuid.UUID(dev_id))
    )
    if not result.scalar_one_or_none():
        raise NotFoundException(message=f"Device {dev_id} not found")

    sessions_result = await db.execute(
        select(DeviceSession)
        .where(DeviceSession.device_id == uuid.UUID(dev_id))
        .order_by(DeviceSession.login_at.desc())
    )
    return [model_to_dict(s) for s in sessions_result.scalars().all()]
