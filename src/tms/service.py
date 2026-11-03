"""TMS business logic — device registration, heartbeat, sync logs, sessions,
hub-and-spoke routing, carrier routes, transport segments, and route plans.

All CRUD functions are async and require an ``AsyncSession``.
"""
import heapq
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache.decorators import cached, distributed_lock
from src.core.exceptions import NotFoundException, ValidationException
from src.models.base import model_to_dict
from src.tms.models import (
    CarrierCode,
    CarrierRoute,
    CarrierServiceType,
    DeviceSession,
    DeviceStatus,
    FreightRule,
    FreightTier,
    HubConnection,
    HubStatus,
    PlatformType,
    ReturnOrder,
    ReturnShipmentStatus,
    ReturnStatus,
    RoutePlan,
    RoutePlanStatus,
    RoutePlanType,
    SessionStatus,
    SyncLog,
    SyncLogStatus,
    SyncLogType,
    TerminalDevice,
    TerminalDeviceType,
    TrackingEvent,
    TrackingEventType,
    TransferHub,
    TransferHubType,
    TransportOrder,
    TransportSegment,
    TransportSegmentStatus,
    TransportStatus,
    TransportType,
)

logger = logging.getLogger(__name__)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(UTC)


def _to_uuid(val: str | uuid.UUID | None) -> uuid.UUID | None:
    """Convert a string or UUID value to ``uuid.UUID``, or return None."""
    if val is None or isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(val)
    except (ValueError, TypeError):
        return None


_ALLOWED_EVENT_TYPES = [event.value for event in TrackingEventType]


def _as_event_type(value: object) -> TrackingEventType:
    """Name the event types this API accepts instead of raising.

    ``TrackingEventType(value)`` on a typo raises ValueError, which the global
    error handler reports as a 500: the caller is told the server broke when
    what they wrote was "PICKED_UP", and nothing tells them the API calls that
    event "pickup_completed".  The HTTP schemas catch this now; the guard stays
    here because tasks, seed scripts and tests call the service directly.
    """
    if value is None:
        raise ValidationException(
            message=f"event_type is required (one of: {', '.join(_ALLOWED_EVENT_TYPES)})",
            detail={"allowed": _ALLOWED_EVENT_TYPES},
        )
    try:
        return TrackingEventType(value)
    except ValueError:
        raise ValidationException(
            message=f"event_type must be one of: {', '.join(_ALLOWED_EVENT_TYPES)}, got {value!r}",
            detail={"event_type": str(value), "allowed": _ALLOWED_EVENT_TYPES},
        ) from None


def _as_choice[E: StrEnum](value: object, enum: type[E], *, field: str) -> E:
    """Read a vocabulary member out of a request value, naming the members it accepts.

    ``ReturnReason(data["reason"])`` on a typo — and the console's return form is
    a free-text textarea, so a typo is the normal case — raised ``ValueError``
    inside the handler: the caller was told the server broke, and nothing told
    them the reason codes the domain knows.  The HTTP schemas refuse these
    before the handler runs; this guard is here because tasks, seed scripts and
    tests call the service directly.
    """
    allowed = ", ".join(member.value for member in enum)
    if value is None:
        raise ValidationException(message=f"{field} is required (one of: {allowed})")
    try:
        return enum(value)
    except ValueError:
        raise ValidationException(
            message=f"{field} must be one of: {allowed}, got {value!r}",
            detail={field: str(value), "allowed": [member.value for member in enum]},
        ) from None


def _as_decimal(value: object, *, field: str) -> Decimal:
    """Read a quantity out of a request value without raising inside the handler.

    ``Decimal(str(data.get("refund_amount", "0")))`` on ``"五十九元"`` raised
    ``decimal.InvalidOperation`` — a 500 for a number typed into the wrong box.
    A value that is not a number is refused by the field it arrived in.
    """
    try:
        return Decimal(str(value))
    except Exception:
        raise ValidationException(
            message=f"{field} must be a number, got {value!r}",
            detail={field: str(value)},
        ) from None


def _as_int(value: object, *, field: str) -> int:
    """Read a count out of a request value without raising inside the handler."""
    try:
        return int(str(value))
    except (ValueError, TypeError):
        raise ValidationException(
            message=f"{field} must be a whole number, got {value!r}",
            detail={field: str(value)},
        ) from None


def _safe_uuid(val: str | uuid.UUID | None) -> uuid.UUID | None:
    """Convert to ``uuid.UUID`` without raising on malformed input."""
    if val is None or isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError, TypeError):
        return None


async def _resolve_transport_order(db: AsyncSession, raw: object, *, field: str = "transport_order_id") -> uuid.UUID:
    """Find a transport order by id *or* transport number, naming the field that named it.

    The two screens that link a record to a shipment — ``ReturnOrderList.vue``
    files a return against the number shown in the list, ``ExceptionList.vue``
    reports an exception against the number the operator typed — both send
    ``TPL-…`` numbers, and the services read that column as a uuid:
    ``uuid.UUID("TPL-20260718-0001")`` raised ValueError inside the handler, so
    a request naming a real shipment in the form the API printed for it was
    reported as a server failure.  Ids and numbers are both accepted; a value
    that is neither is refused by the field that carried it.
    """
    value = str(raw).strip()
    as_id = _safe_uuid(value)
    if as_id is not None:
        found = await db.scalar(select(TransportOrder.id).where(TransportOrder.id == as_id))
        if found is not None:
            return found
    by_no = await db.scalar(select(TransportOrder.id).where(TransportOrder.transport_no == value))
    if by_no is None:
        raise NotFoundException(
            message=f"{field} {value!r} is neither a transport order id nor a known transport number",
        )
    return by_no


async def _resolve_warehouse_id(db: AsyncSession, raw: object, *, field: str = "destination_warehouse_id") -> uuid.UUID:
    """Find a warehouse by id *or* code, naming the field that named it.

    A return is filed to a warehouse; the value a handheld sends is the code
    printed on its bay door, and a value the lookup cannot read used to reach
    the UUID column as a string.  Same rule as the transfer endpoints: id first,
    code second, refusal naming the field.
    """
    from src.wms.models import Warehouse

    value = str(raw).strip()
    as_id = _safe_uuid(value)
    if as_id is not None:
        found = await db.scalar(select(Warehouse.id).where(Warehouse.id == as_id))
        if found is not None:
            return found
    by_code = await db.scalar(select(Warehouse.id).where(Warehouse.code == value))
    if by_code is None:
        raise NotFoundException(
            message=f"{field} {value!r} is neither a warehouse id nor a known warehouse code",
        )
    return by_code


# ── Device CRUD ──────────────────────────────────────────────────────────────

async def register_device(db: AsyncSession, data: dict) -> dict:
    """Register a new terminal device.

    The console (``frontend/src/views/devices/DeviceList.vue``) posts
    ``{device_code, name, device_type}`` and this function read
    ``data["code"]``: a ``KeyError`` inside the handler, reported as a server
    failure, for the ordinary case of registering the device the form described.
    The body (``DeviceRegister``) accepts ``device_code`` as the code now, and
    the device's warehouse is resolved by id *or* code — ``_to_uuid`` answers
    None for a code, and the device was filed with no warehouse, silently.
    """
    code = data.get("code")
    if not code:
        raise ValidationException(
            message="code is required — a device is identified by the code printed on it",
        )
    code = str(code).strip()
    existing = await db.scalar(select(TerminalDevice.id).where(TerminalDevice.code == code))
    if existing is not None:
        raise ValidationException(message=f"Device code {code!r} already exists")

    device = TerminalDevice(
        id=uuid.uuid4(),
        code=code,
        name=data.get("name", ""),
        device_type=_as_choice(data.get("device_type") or "pda", TerminalDeviceType, field="device_type"),
        platform=_as_choice(data.get("platform") or "android", PlatformType, field="platform"),
        os_version=data.get("os_version", ""),
        app_version=data.get("app_version", ""),
        status=DeviceStatus.OFFLINE,
        warehouse_id=(
            await _resolve_warehouse_id(db, data["warehouse_id"], field="warehouse_id")
            if data.get("warehouse_id") else None
        ),
        config=data.get("config"),
        push_token=data.get("push_token"),
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return model_to_dict(device)


async def get_device(db: AsyncSession, dev_id: str) -> dict:
    """Get a device by ID."""
    dev_uuid = _safe_uuid(dev_id)
    if dev_uuid is None:
        raise NotFoundException(message=f"Device {dev_id} not found")
    result = await db.execute(select(TerminalDevice).where(TerminalDevice.id == dev_uuid))
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
        wh_uuid = _safe_uuid(warehouse_id)
        if wh_uuid is None:
            return []
        stmt = stmt.where(TerminalDevice.warehouse_id == wh_uuid)
    if status:
        stmt = stmt.where(TerminalDevice.status == DeviceStatus(status))
    if device_type:
        stmt = stmt.where(TerminalDevice.device_type == TerminalDeviceType(device_type))
    stmt = stmt.order_by(TerminalDevice.created_at.desc())
    result = await db.execute(stmt)
    return [model_to_dict(d) for d in result.scalars().all()]


async def update_device(db: AsyncSession, dev_id: str, data: dict) -> dict:
    """Update device fields."""
    dev_uuid = _safe_uuid(dev_id)
    if dev_uuid is None:
        raise NotFoundException(message=f"Device {dev_id} not found")
    result = await db.execute(select(TerminalDevice).where(TerminalDevice.id == dev_uuid))
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundException(message=f"Device {dev_id} not found")

    # The fields an update carries.  ``code``, ``device_type`` and ``platform``
    # are among them: the console's edit form sends the code and the type, and
    # an edit that renamed a device, or corrected a scanner registered as a
    # phone, had its two meaningful fields dropped.
    updatable = {"code", "name", "device_type", "platform", "os_version", "app_version",
                 "warehouse_id", "config", "push_token", "status"}
    for key in updatable:
        if key not in data or data[key] is None:
            continue
        if key == "status":
            setattr(dev, key, _as_choice(data[key], DeviceStatus, field="status"))
        elif key == "device_type":
            setattr(dev, key, _as_choice(data[key], TerminalDeviceType, field="device_type"))
        elif key == "platform":
            setattr(dev, key, _as_choice(data[key], PlatformType, field="platform"))
        elif key == "warehouse_id":
            setattr(dev, key, await _resolve_warehouse_id(db, data[key], field="warehouse_id"))
        elif key == "code":
            # Codes are unique; a rename that lands on another device's code has
            # to be refused here, not at commit, where it is a 500.
            code = str(data[key]).strip()
            clash = await db.scalar(
                select(TerminalDevice.id).where(TerminalDevice.code == code, TerminalDevice.id != dev.id)
            )
            if clash is not None:
                raise ValidationException(message=f"Device code {code!r} already exists")
            dev.code = code
        else:
            setattr(dev, key, data[key])
    dev.updated_at = _now()

    await db.commit()
    await db.refresh(dev)
    return model_to_dict(dev)


# ── Heartbeat ────────────────────────────────────────────────────────────────

async def record_heartbeat(db: AsyncSession, dev_id: str) -> dict:
    """Record device heartbeat — marks device online."""
    dev_uuid = _safe_uuid(dev_id)
    if dev_uuid is None:
        raise NotFoundException(message=f"Device {dev_id} not found")
    result = await db.execute(select(TerminalDevice).where(TerminalDevice.id == dev_uuid))
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
    dev_uuid = _safe_uuid(dev_id)
    if dev_uuid is None:
        raise NotFoundException(message=f"Device {dev_id} not found")
    result = await db.execute(select(TerminalDevice).where(TerminalDevice.id == dev_uuid))
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundException(message=f"Device {dev_id} not found")

    now = _now()
    # The vocabularies are read as vocabularies: a device that reported
    # ``sync_type: "upload_data"`` reached SyncLogType(...) inside this handler,
    # so the sync that failed on the floor failed on the way in as well, as a
    # 500 that named nothing.
    sync_type = _as_choice(data.get("sync_type") or "download", SyncLogType, field="sync_type")
    status = _as_choice(data.get("status") or "pending", SyncLogStatus, field="status")
    log = SyncLog(
        id=uuid.uuid4(),
        device_id=dev_uuid,
        sync_type=sync_type,
        status=status,
        records_count=_as_int(data.get("records_count") if data.get("records_count") is not None else 0,
                              field="records_count"),
        error_message=data.get("error_message"),
        started_at=now,
        completed_at=now if status in (SyncLogStatus.COMPLETED, SyncLogStatus.FAILED) else None,
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
    dev_uuid = _safe_uuid(dev_id)
    if dev_uuid is None:
        raise NotFoundException(message=f"Device {dev_id} not found")
    # Verify device exists
    result = await db.execute(select(TerminalDevice).where(TerminalDevice.id == dev_uuid))
    if not result.scalar_one_or_none():
        raise NotFoundException(message=f"Device {dev_id} not found")

    logs_result = await db.execute(
        select(SyncLog)
        .where(SyncLog.device_id == dev_uuid)
        .order_by(SyncLog.started_at.desc())
    )
    return [model_to_dict(entry) for entry in logs_result.scalars().all()]


# ── Sessions ─────────────────────────────────────────────────────────────────

async def create_session(db: AsyncSession, dev_id: str, ip_address: str | None = None) -> dict:
    """Create a new device session."""
    dev_uuid = _safe_uuid(dev_id)
    if dev_uuid is None:
        raise NotFoundException(message=f"Device {dev_id} not found")
    result = await db.execute(select(TerminalDevice).where(TerminalDevice.id == dev_uuid))
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundException(message=f"Device {dev_id} not found")

    now = _now()
    sess = DeviceSession(
        id=uuid.uuid4(),
        device_id=dev_uuid,
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
    dev_uuid = _safe_uuid(dev_id)
    sess_uuid = _safe_uuid(sess_id)
    if dev_uuid is None or sess_uuid is None:
        raise NotFoundException(message=f"Session {sess_id} not found for device {dev_id}")
    result = await db.execute(
        select(DeviceSession).where(
            DeviceSession.id == sess_uuid,
            DeviceSession.device_id == dev_uuid,
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise NotFoundException(message=f"Session {sess_id} not found for device {dev_id}")

    now = _now()
    sess.logout_at = now
    sess.status = SessionStatus.ENDED

    await db.commit()
    await db.refresh(sess)
    return model_to_dict(sess)


async def list_sessions(db: AsyncSession, dev_id: str) -> list[dict]:
    """List sessions for a device."""
    dev_uuid = _safe_uuid(dev_id)
    if dev_uuid is None:
        raise NotFoundException(message=f"Device {dev_id} not found")
    result = await db.execute(
        select(TerminalDevice).where(TerminalDevice.id == dev_uuid)
    )
    if not result.scalar_one_or_none():
        raise NotFoundException(message=f"Device {dev_id} not found")

    sessions_result = await db.execute(
        select(DeviceSession)
        .where(DeviceSession.device_id == dev_uuid)
        .order_by(DeviceSession.login_at.desc())
    )
    return [model_to_dict(s) for s in sessions_result.scalars().all()]


# ═══════════════════════════════════════════════════════════════════════════════
# Transport Order CRUD (prerequisite for route planning)
# ═══════════════════════════════════════════════════════════════════════════════

async def create_transport_order(db: AsyncSession, data: dict) -> dict:
    """Create a new transport order (draft)."""
    from datetime import date

    _now()
    # carrier_code may be omitted if shipment_id or packing_record_id is provided (auto-resolved later)
    carrier_code_value = data.get("carrier_code")
    order = TransportOrder(
        id=uuid.uuid4(),
        transport_no=f"TPL-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}",
        status=TransportStatus.DRAFT,
        carrier_code=CarrierCode(carrier_code_value) if carrier_code_value else None,
        pickup_warehouse_id=uuid.UUID(data["pickup_warehouse_id"]) if data.get("pickup_warehouse_id") else None,
        pickup_address=data.get("pickup_address", {}),
        delivery_name=data["delivery_name"],
        delivery_phone=data.get("delivery_phone"),
        delivery_address=data.get("delivery_address", {}),
        shipment_id=uuid.UUID(data["shipment_id"]) if data.get("shipment_id") else None,
        packing_record_id=uuid.UUID(data["packing_record_id"]) if data.get("packing_record_id") else None,
        package_count=data.get("package_count", 1),
        total_weight_kg=Decimal(str(data.get("total_weight_kg", 0))),
        total_volume_m3=Decimal(str(data.get("total_volume_m3", 0))),
        service_type=CarrierServiceType(data.get("service_type", "standard")),
        transport_type=TransportType(data.get("transport_type", "carrier_pickup")),
        driver_name=data.get("driver_name"),
        driver_phone=data.get("driver_phone"),
        notes=data.get("notes"),
    )
    # Create order + initial CREATED event atomically so a partial failure
    # doesn't leave an order without its first tracking event.
    db.add(order)
    evt = TrackingEvent(
        id=uuid.uuid4(),
        transport_order_id=order.id,
        event_type=TrackingEventType.CREATED,
        location_name=(data.get("pickup_address") or {}).get("city") or "Warehouse",
    )
    db.add(evt)

    await db.commit()
    await db.refresh(order)
    return model_to_dict(order)


@cached(ttl=300, prefix="tms", skip_args=1)
async def get_transport_order(db: AsyncSession, order_id: str) -> dict:
    """Get a transport order by ID."""
    order_uuid = _safe_uuid(order_id)
    if order_uuid is None:
        raise NotFoundException(message=f"TransportOrder {order_id} not found")
    result = await db.execute(
        select(TransportOrder).where(TransportOrder.id == order_uuid)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundException(message=f"TransportOrder {order_id} not found")
    return model_to_dict(order)


async def list_transport_orders(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    carrier_code: str | None = None,
) -> tuple[list[dict], int]:
    """List transport orders with pagination and filters."""
    from sqlalchemy import func as sa_func

    # Build base query
    base = select(TransportOrder)
    if status:
        base = base.where(TransportOrder.status == TransportStatus(status))
    if carrier_code:
        base = base.where(TransportOrder.carrier_code == CarrierCode(carrier_code))

    # Count total (clone the WHERE clauses)
    count_q = select(sa_func.count()).select_from(TransportOrder)
    if status:
        count_q = count_q.where(TransportOrder.status == TransportStatus(status))
    if carrier_code:
        count_q = count_q.where(TransportOrder.carrier_code == CarrierCode(carrier_code))
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate
    stmt = base.order_by(TransportOrder.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    items = [model_to_dict(r) for r in result.scalars().all()]
    return items, total


_transport_status_transitions: dict[TransportStatus, list[TransportStatus]] = {
    # Allow direct transit when order has no pickup yet (e.g. carrier pickup flow)
    TransportStatus.DRAFT: [TransportStatus.DISPATCHED, TransportStatus.IN_TRANSIT, TransportStatus.CANCELLED],
    TransportStatus.DISPATCHED: (
        TransportStatus.PICKUP_COMPLETED,
        TransportStatus.IN_TRANSIT,
        TransportStatus.CANCELLED,
    ),
    TransportStatus.PICKUP_COMPLETED: [TransportStatus.IN_TRANSIT, TransportStatus.EXCEPTION],
    TransportStatus.IN_TRANSIT: [TransportStatus.OUT_FOR_DELIVERY, TransportStatus.EXCEPTION],
    TransportStatus.OUT_FOR_DELIVERY: [TransportStatus.DELIVERED, TransportStatus.EXCEPTION],
    TransportStatus.DELIVERED: [],
    TransportStatus.EXCEPTION: [TransportStatus.DISPATCHED, TransportStatus.DELIVERED, TransportStatus.CANCELLED],
    TransportStatus.CANCELLED: [],
}


async def change_transport_status(db: AsyncSession, order_id: str, new_status: str) -> dict:
    """Change transport order status with state machine validation."""
    order_uuid = _safe_uuid(order_id)
    if order_uuid is None:
        raise NotFoundException(message=f"TransportOrder {order_id} not found")
    result = await db.execute(
        select(TransportOrder).where(TransportOrder.id == order_uuid)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundException(message=f"TransportOrder {order_id} not found")

    target = TransportStatus(new_status)
    allowed = _transport_status_transitions.get(order.status, [])

    if target not in allowed:
        raise ValidationException(
            message=f"Cannot transition transport order from {order.status.value} to {target.value}"
        )

    order.status = target
    now = _now()
    order.updated_at = now

    # actual_pickup_time should be set on PICKUP_COMPLETED, not IN_TRANSIT.
    # An order may go DRAFT → IN_TRANSIT directly (carrier pickup flow) without a pickup event.
    if target == TransportStatus.PICKUP_COMPLETED and not order.actual_pickup_time:
        order.actual_pickup_time = now
    elif target == TransportStatus.DELIVERED:
        order.actual_delivery_time = now

    await db.commit()
    await db.refresh(order)
    return model_to_dict(order)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase A1 — TransferHub CRUD
# ═══════════════════════════════════════════════════════════════════════════════

async def create_hub(db: AsyncSession, data: dict) -> dict:
    """Create a new transfer hub.

    The hub's type is read as a vocabulary (``TransferHubType``) and its capacity as
    a number — both by the guards the rest of this module uses, so a task or seed
    script that calls this directly gets a 422 naming the field, the way the HTTP
    layer does.  The console's key is ``type``, the column is ``hub_type``; both
    spellings name the same thing.
    """
    code = str(data.get("code") or "").strip()
    if not code:
        raise ValidationException(message="code is required — a hub is picked by the code on its sign")
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationException(message="name is required")
    city = str(data.get("city") or "").strip()
    if not city:
        raise ValidationException(message="city is required — the route planner routes by city")

    existing = await db.execute(select(TransferHub).where(TransferHub.code == code))
    if existing.scalar_one_or_none():
        raise ValidationException(message=f"Hub code '{code}' already exists")

    capacity = _as_decimal(
        data.get("capacity_weight_kg") if data.get("capacity_weight_kg") not in (None, "") else "0",
        field="capacity_weight_kg",
    )
    if capacity < 0:
        raise ValidationException(
            message=f"capacity_weight_kg {capacity} is negative — a hub that lifts negative weight "
                    "matches every shipment and prices none of them",
        )

    hub = TransferHub(
        id=uuid.uuid4(),
        code=code,
        name=name,
        hub_type=_as_choice(
            data.get("hub_type") or data.get("type") or "primary", TransferHubType, field="hub_type",
        ),
        city=city,
        address=data.get("address"),
        capacity_weight_kg=capacity,
        contact_name=data.get("contact_name"),
        contact_phone=data.get("contact_phone"),
        status=HubStatus.OPEN,
    )
    db.add(hub)
    await db.commit()
    await db.refresh(hub)
    return model_to_dict(hub)


@cached(ttl=300, prefix="tms", skip_args=1)
async def get_hub(db: AsyncSession, hub_id: str) -> dict:
    """Get a transfer hub by ID."""
    hub_uuid = _safe_uuid(hub_id)
    if hub_uuid is None:
        raise NotFoundException(message=f"Hub {hub_id} not found")
    result = await db.execute(select(TransferHub).where(TransferHub.id == hub_uuid))
    hub = result.scalar_one_or_none()
    if not hub:
        raise NotFoundException(message=f"Hub {hub_id} not found")
    return model_to_dict(hub)


async def list_hubs(
    db: AsyncSession,
    city: str | None = None,
    hub_type: str | None = None,
) -> list[dict]:
    """List transfer hubs with optional city/type filters."""
    stmt = select(TransferHub)
    if city:
        stmt = stmt.where(TransferHub.city == city)
    if hub_type:
        stmt = stmt.where(TransferHub.hub_type == TransferHubType(hub_type))
    stmt = stmt.order_by(TransferHub.created_at.desc())
    result = await db.execute(stmt)
    return [model_to_dict(h) for h in result.scalars().all()]


async def update_hub(db: AsyncSession, hub_id: str, data: dict) -> dict:
    """Update transfer hub fields."""
    hub_uuid = _safe_uuid(hub_id)
    if hub_uuid is None:
        raise NotFoundException(message=f"Hub {hub_id} not found")
    result = await db.execute(select(TransferHub).where(TransferHub.id == hub_uuid))
    hub = result.scalar_one_or_none()
    if not hub:
        raise NotFoundException(message=f"Hub {hub_id} not found")

    # The console's edit dialog offers 编码, 名称, 类型 and 城市.  ``code`` was not in
    # this set and neither was the key the form sends for the type (``type``), so
    # two of the four fields the operator edited were dropped on every save — the
    # hub kept its old code, and kept the type the route planner routes by.
    updatable = {"code", "name", "hub_type", "type", "city", "address", "capacity_weight_kg",
                 "contact_name", "contact_phone", "status"}
    for key in updatable:
        if key not in data or data[key] is None:
            continue
        if key == "hub_type" or key == "type":
            hub.hub_type = _as_choice(data[key], TransferHubType, field="hub_type")
        elif key == "status":
            hub.status = _as_choice(data[key], HubStatus, field="status")
        elif key == "capacity_weight_kg":
            capacity = _as_decimal(data[key], field="capacity_weight_kg")
            if capacity < 0:
                raise ValidationException(
                    message=f"capacity_weight_kg {capacity} is negative — a hub that lifts negative "
                            "weight matches every shipment and prices none of them",
                )
            hub.capacity_weight_kg = capacity
        elif key == "code":
            # ``transfer_hubs.code`` is unique, and it is how the hub-network
            # screens and the hub-connection rows refer to a hub: a rename that
            # lands on another hub's code has to be refused here, not at commit.
            code = str(data[key]).strip()
            if not code:
                raise ValidationException(message="code cannot be blank — the hub is picked by its code")
            clash = await db.scalar(
                select(TransferHub.id).where(TransferHub.code == code, TransferHub.id != hub.id)
            )
            if clash is not None:
                raise ValidationException(message=f"Hub code {code!r} already exists")
            hub.code = code
        else:
            setattr(hub, key, data[key])
    hub.updated_at = _now()

    await db.commit()
    await db.refresh(hub)
    # A hub's city/type change rewires the pricing graph — invalidate plans.
    await _bump_route_cache_version()
    return model_to_dict(hub)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase A1 — CarrierRoute CRUD
# ═══════════════════════════════════════════════════════════════════════════════

async def add_carrier_route(db: AsyncSession, data: dict) -> dict:
    """Add a new carrier route entry."""
    route = CarrierRoute(
        id=uuid.uuid4(),
        carrier_code=CarrierCode(data["carrier_code"]),
        origin_city=data["origin_city"],
        dest_city=data["dest_city"],
        distance_km=Decimal(str(data["distance_km"])),
        transit_hours=Decimal(str(data["transit_hours"])),
        base_price_per_kg=Decimal(str(data["base_price_per_kg"])),
        express_surcharge=Decimal(str(data.get("express_surcharge", "0"))),
        min_charge_weight=Decimal(str(data.get("min_charge_weight", "1.0"))),
        is_active=True,
    )
    db.add(route)
    await db.commit()
    await db.refresh(route)
    await _bump_route_cache_version()
    return model_to_dict(route)


async def list_carrier_routes(
    db: AsyncSession,
    origin_city: str | None = None,
    dest_city: str | None = None,
    carrier_code: str | None = None,
) -> list[dict]:
    """List carrier routes with optional filters."""
    stmt = select(CarrierRoute)
    if origin_city:
        stmt = stmt.where(CarrierRoute.origin_city == origin_city)
    if dest_city:
        stmt = stmt.where(CarrierRoute.dest_city == dest_city)
    if carrier_code:
        stmt = stmt.where(CarrierRoute.carrier_code == CarrierCode(carrier_code))
    stmt = stmt.order_by(CarrierRoute.created_at.desc())
    result = await db.execute(stmt)
    return [model_to_dict(r) for r in result.scalars().all()]


async def update_carrier_rate(
    db: AsyncSession,
    carrier_code: str,
    rate_data: dict,
) -> int:
    """Update freight tiers for a carrier from ERP rate data.

    ``rate_data`` is a list of tier dicts, each with keys:
        rule_type, min_value, max_value, price_per_unit, surcharge_express

    Returns the number of tiers upserted.
    """
    code = CarrierCode(carrier_code)
    tiers = rate_data if isinstance(rate_data, list) else rate_data.get("tiers", [])
    count = 0
    for tier_data in tiers:
        rule_type = FreightRule(tier_data["rule_type"])
        # Upsert: delete existing tier for same carrier+rule+min, then insert
        existing = await db.execute(
            select(FreightTier).where(
                FreightTier.carrier_code == code,
                FreightTier.rule_type == rule_type,
                FreightTier.min_value == Decimal(str(tier_data["min_value"])),
            )
        )
        old = existing.scalar_one_or_none()
        if old:
            old.max_value = Decimal(str(tier_data["max_value"])) if tier_data.get("max_value") is not None else None
            old.price_per_unit = Decimal(str(tier_data["price_per_unit"]))
            old.surcharge_express = Decimal(str(tier_data.get("surcharge_express", "0")))
        else:
            db.add(FreightTier(
                id=uuid.uuid4(),
                carrier_code=code,
                rule_type=rule_type,
                min_value=Decimal(str(tier_data["min_value"])),
                max_value=Decimal(str(tier_data["max_value"])) if tier_data.get("max_value") is not None else None,
                price_per_unit=Decimal(str(tier_data["price_per_unit"])),
                surcharge_express=Decimal(str(tier_data.get("surcharge_express", "0"))),
            ))
        count += 1
    await db.commit()
    return count


# ═══════════════════════════════════════════════════════════════════════════════
# Phase A1 — HubConnection CRUD
# ═══════════════════════════════════════════════════════════════════════════════

async def add_hub_connection(db: AsyncSession, data: dict) -> dict:
    """Create a directed hub connection (graph edge)."""
    existing = await db.execute(
        select(HubConnection).where(
            HubConnection.from_hub_code == data["from_hub_code"],
            HubConnection.to_hub_code == data["to_hub_code"],
        )
    )
    if existing.scalar_one_or_none():
        raise ValidationException(
            message=f"Connection {data['from_hub_code']}→{data['to_hub_code']} already exists"
        )

    conn = HubConnection(
        id=uuid.uuid4(),
        from_hub_code=data["from_hub_code"],
        to_hub_code=data["to_hub_code"],
        distance_km=Decimal(str(data["distance_km"])),
        transit_hours=Decimal(str(data["transit_hours"])),
        is_active=True,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    await _bump_route_cache_version()
    return model_to_dict(conn)


async def list_hub_connections(
    db: AsyncSession,
    hub_code: str | None = None,
) -> list[dict]:
    """List hub connections, optionally filtered by hub code."""
    stmt = select(HubConnection)
    if hub_code:
        stmt = stmt.where(
            (HubConnection.from_hub_code == hub_code) | (HubConnection.to_hub_code == hub_code)
        )
    stmt = stmt.order_by(HubConnection.created_at.desc())
    result = await db.execute(stmt)
    return [model_to_dict(c) for c in result.scalars().all()]


# ═══════════════════════════════════════════════════════════════════════════════
# Phase A1 — TransportSegment CRUD
# ═══════════════════════════════════════════════════════════════════════════════

async def create_segment(db: AsyncSession, data: dict) -> dict:
    """Create a transport segment."""
    seg = TransportSegment(
        id=uuid.uuid4(),
        transport_order_id=uuid.UUID(data["transport_order_id"]),
        segment_no=data.get("segment_no", 0),
        origin_hub_code=data.get("origin_hub_code"),
        dest_hub_code=data.get("dest_hub_code"),
        carrier_code=CarrierCode(data["carrier_code"]) if data.get("carrier_code") else None,
        status=TransportSegmentStatus.DRAFT,
        weight_kg=Decimal(str(data.get("weight_kg", "0"))),
        cost_amount=Decimal(str(data.get("cost_amount", "0"))),
        estimated_departure_time=data.get("estimated_departure_time"),
        expected_arrival_time=data.get("expected_arrival_time"),
        notes=data.get("notes"),
    )
    db.add(seg)
    await db.commit()
    await db.refresh(seg)
    return model_to_dict(seg)


async def update_segment_status(
    db: AsyncSession, seg_id: str, status: str
) -> dict:
    """Update transport segment status with state machine validation."""
    seg_uuid = _safe_uuid(seg_id)
    if seg_uuid is None:
        raise NotFoundException(message=f"Segment {seg_id} not found")
    result = await db.execute(select(TransportSegment).where(TransportSegment.id == seg_uuid))
    seg = result.scalar_one_or_none()
    if not seg:
        raise NotFoundException(message=f"Segment {seg_id} not found")

    new_status = TransportSegmentStatus(status)
    # State machine transitions
    valid_transitions = {
        TransportSegmentStatus.DRAFT: [
            TransportSegmentStatus.DISPATCHED, TransportSegmentStatus.CANCELLED,
        ],
        TransportSegmentStatus.DISPATCHED: [
            TransportSegmentStatus.PICKUP, TransportSegmentStatus.CANCELLED,
        ],
        TransportSegmentStatus.PICKUP: [
            TransportSegmentStatus.IN_TRANSIT, TransportSegmentStatus.EXCEPTION,
        ],
        TransportSegmentStatus.IN_TRANSIT: [
            TransportSegmentStatus.TRANSIT_HUB_ARRIVED,
            TransportSegmentStatus.OUT_FOR_DELIVERY,
            TransportSegmentStatus.EXCEPTION,
        ],
        TransportSegmentStatus.TRANSIT_HUB_ARRIVED: [
            TransportSegmentStatus.SORTING_CENTER, TransportSegmentStatus.IN_TRANSIT,
            TransportSegmentStatus.EXCEPTION,
        ],
        TransportSegmentStatus.SORTING_CENTER: [
            TransportSegmentStatus.IN_TRANSIT, TransportSegmentStatus.EXCEPTION,
        ],
        TransportSegmentStatus.OUT_FOR_DELIVERY: [
            TransportSegmentStatus.COMPLETED, TransportSegmentStatus.EXCEPTION,
        ],
        TransportSegmentStatus.COMPLETED: [],
        TransportSegmentStatus.EXCEPTION: [TransportSegmentStatus.CANCELLED],
        TransportSegmentStatus.CANCELLED: [],
    }

    allowed = valid_transitions.get(seg.status, [])
    if new_status not in allowed:
        raise ValidationException(
            message=f"Cannot transition segment from {seg.status.value} to {new_status.value}"
        )

    seg.status = new_status
    now = _now()
    seg.updated_at = now

    # Record timestamps on transitions
    if new_status == TransportSegmentStatus.DISPATCHED:
        seg.actual_departure_time = now
    elif new_status == TransportSegmentStatus.COMPLETED:
        seg.actual_arrival_time = now

    await db.commit()
    await db.refresh(seg)
    return model_to_dict(seg)


async def get_segment(db: AsyncSession, seg_id: str) -> dict:
    """Get a transport segment by ID."""
    seg_uuid = _safe_uuid(seg_id)
    if seg_uuid is None:
        raise NotFoundException(message=f"Segment {seg_id} not found")
    result = await db.execute(select(TransportSegment).where(TransportSegment.id == seg_uuid))
    seg = result.scalar_one_or_none()
    if not seg:
        raise NotFoundException(message=f"Segment {seg_id} not found")
    return model_to_dict(seg)


async def list_segments(db: AsyncSession, transport_order_id: str) -> list[dict]:
    """List all segments for a transport order."""
    order_uuid = _safe_uuid(transport_order_id)
    if order_uuid is None:
        raise NotFoundException(message=f"TransportOrder {transport_order_id} not found")
    stmt = (
        select(TransportSegment)
        .where(TransportSegment.transport_order_id == order_uuid)
        .order_by(TransportSegment.segment_no)
    )
    result = await db.execute(stmt)
    return [model_to_dict(s) for s in result.scalars().all()]


# ═══════════════════════════════════════════════════════════════════════════════
# Phase A2 — Core Algorithm: find_best_route_plan (Dijkstra + cost optimization)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(order=True)
class _PriorityNode:
    priority: Decimal
    hub_code: str = field(compare=False)
    path: list[str] = field(compare=False)
    total_distance: Decimal = field(compare=False)
    total_hours: Decimal = field(compare=False)
    # Per-edge distance/hours recorded as the node was expanded, so segment
    # metrics come straight off the winner instead of being re-guessed from
    # the graph (the old lookup duplicated segments whenever two hubs had
    # parallel edges).
    edge_distances: tuple = field(default=(), compare=False)
    edge_hours: tuple = field(default=(), compare=False)


async def _find_best_route_plan_impl(
    transport_order_id: str, db: AsyncSession
) -> dict:
    """Internal implementation — no caching."""
    order_result = await db.execute(
        select(TransportOrder).where(TransportOrder.id == uuid.UUID(transport_order_id))
    )
    order = order_result.scalar_one_or_none()
    if not order:
        raise NotFoundException(message=f"TransportOrder {transport_order_id} not found")

    order_dict = model_to_dict(order)
    pickup_city = order_dict.get("pickup_address", {}).get("city", "")
    delivery_city = order_dict.get("delivery_address", {}).get("city", "")
    weight_kg = Decimal(str(order_dict.get("total_weight_kg", 1)))

    if not pickup_city or not delivery_city:
        raise ValidationException(message="Transport order missing pickup/delivery city")

    # Step 2 — Find origin & destination hubs by city
    origin_hubs = await list_hubs(db, city=pickup_city)
    dest_hubs = await list_hubs(db, city=delivery_city)

    if not origin_hubs:
        raise NotFoundException(message=f"No transfer hub found in origin city '{pickup_city}'")
    if not dest_hubs:
        raise NotFoundException(message=f"No transfer hub found in destination city '{delivery_city}'")

    # Step 3 — Build graph from HubConnections
    conns = await list_hub_connections(db)
    graph: dict[str, list[tuple[str, Decimal, Decimal]]] = {}
    for c in conns:
        graph.setdefault(c["from_hub_code"], []).append(
            (c["to_hub_code"], Decimal(str(c["distance_km"])), Decimal(str(c["transit_hours"])))
        )

    # Step 4 — Load carrier routes for pricing
    carrier_routes = await list_carrier_routes(db)

    # Lane pricing lookup: (origin_city, dest_city) → cheapest price_per_kg
    # across carriers.  A CarrierRoute prices the WHOLE lane between two
    # cities, so graph edges are priced per hub-city pair below.
    lane_price: dict[tuple[str, str], Decimal] = {}
    for cr in carrier_routes:
        key = (cr["origin_city"], cr["dest_city"])
        price = Decimal(str(cr["base_price_per_kg"]))
        if key not in lane_price or price < lane_price[key]:
            lane_price[key] = price

    # Hub code → city, so every edge pays its own city-pair lane price
    # (武汉→长沙→柳州 pays 武汉→长沙 plus 长沙→柳州, never the full lane twice).
    all_hubs = await list_hubs(db)
    hub_cities: dict[str, str] = {h["code"]: (h.get("city") or "") for h in all_hubs}

    # Step 5 — Run Dijkstra for each origin→dest hub pair
    best_result: dict | None = None
    best_cost: Decimal = Decimal("Infinity")

    for o_hub in origin_hubs:
        o_code = o_hub["code"]
        for d_hub in dest_hubs:
            d_code = d_hub["code"]
            result = _dijkstra(
                o_code, d_code, graph, lane_price, hub_cities, weight_kg,
            )
            if result and result["total_cost"] < best_cost:
                best_cost = result["total_cost"]
                best_result = result

    if best_result is None:
        raise NotFoundException(message=f"No route found from '{pickup_city}' to '{delivery_city}'")

    return {
        "origin_city": pickup_city,
        "destination_city": delivery_city,
        "total_distance_km": str(best_result["total_distance"]),
        "estimated_transit_hours": str(best_result["total_hours"]),
        "total_cost_amount": str(best_result["total_cost"]),
        "segments": [
            {
                "segment_no": i,
                "from_hub": path[i],
                "to_hub": path[i + 1],
                "distance_km": str(seg_dist),
                "transit_hours": str(seg_hours),
            }
            for i, (path, seg_dist, seg_hours) in enumerate(
                zip(best_result["path"], best_result["seg_distances"], best_result["seg_hours"])
            )
        ],
    }


_ROUTE_CACHE_TTL = 86400  # 24 hours
_ROUTE_CACHE_VERSION_KEY = "route:version"


async def _bump_route_cache_version() -> None:
    """Invalidate cached route plans after hub / connection / lane changes.

    Bumps a global version counter; cache keys embed the version, so old
    entries become unreachable and age out via their own TTL.  Called from
    add_carrier_route / add_hub_connection / update_hub — previously the
    docstring promised invalidation but nothing ever bumped anything, so
    route plans could serve stale pricing for up to 24 h after a rate change.
    """
    try:
        from src.cache.redis_client import get_redis

        async with get_redis() as r:
            if r:
                await r.incr(_ROUTE_CACHE_VERSION_KEY)
    except Exception:
        logger.warning("Route cache version bump failed")


async def find_best_route_plan(
    transport_order_id: str, db: AsyncSession
) -> dict:
    """Dijkstra + price optimisation with Redis result cache.

    When Redis is available, route plans are cached by
    ``route:v{version}:{pickup_city}:{delivery_city}:{weight_kg}`` for 24 h.
    ``version`` is bumped whenever carrier routes, hub connections or hubs
    change, which makes every previously cached plan unreachable immediately.
    The key deliberately does NOT include the transport order id — plans only
    depend on (cities, weight), so identical shipments reuse one entry.
    """
    order_uuid = _safe_uuid(transport_order_id)
    if order_uuid is None:
        raise NotFoundException(message=f"TransportOrder {transport_order_id} not found")
    pickup_city = ""
    delivery_city = ""
    weight_kg = "1"

    try:
        from src.cache.redis_client import get_redis

        async with get_redis() as r:
            if r:
                order_result = await db.execute(
                    select(TransportOrder).where(
                        TransportOrder.id == uuid.UUID(transport_order_id)
                    )
                )
                order = order_result.scalar_one_or_none()
                if order:
                    pickup_city = (order.pickup_address or {}).get("city", "")
                    delivery_city = (order.delivery_address or {}).get("city", "")
                    weight_kg = str(order.total_weight_kg or "1")
                    version = int(await r.get(_ROUTE_CACHE_VERSION_KEY) or 1)
                    cache_key = f"route:v{version}:{pickup_city}:{delivery_city}:{weight_kg}"
                    cached = await r.get(cache_key)
                    if cached:
                        return json.loads(cached)
    except Exception:
        logger.warning("Route plan cache read failed — recomputing")

    result = await _find_best_route_plan_impl(transport_order_id, db)

    try:
        from src.cache.redis_client import get_redis

        async with get_redis() as r:
            if r:
                version = int(await r.get(_ROUTE_CACHE_VERSION_KEY) or 1)
                cache_key = f"route:v{version}:{pickup_city}:{delivery_city}:{weight_kg}"
                # ``setex`` is deprecated in redis-py 5; ``set(..., ex=…)`` is the
                # same write with the current spelling.
                await r.set(cache_key, json.dumps(result), ex=_ROUTE_CACHE_TTL)
    except Exception:
        logger.warning("Route plan cache write failed")

    return result


def _dijkstra(
    origin: str,
    destination: str,
    graph: dict[str, list[tuple[str, Decimal, Decimal]]],
    lane_price: dict[tuple[str, str], Decimal],
    hub_cities: dict[str, str],
    weight_kg: Decimal,
) -> dict | None:
    """Internal Dijkstra over hub graph returning cheapest path + costs.

    Cost semantics (corrected): a carrier lane price is per-kg for the WHOLE
    city→city lane, so traversing an edge costs ``weight × lane_price`` only
    for edges whose hub cities form a priced lane.  The previous version added
    the full origin→destination lane price once PER SEGMENT, so a 3-segment
    route was charged 3× the lane and multi-hop routes were mis-ranked.
    Edges without a priced lane fall back to a generic 0.5/km estimate.
    """
    fallback_rate = Decimal("0.5")  # fallback ¥/km when no carrier lane covers the edge
    inf_val = Decimal("Infinity")
    best: dict[str, Decimal] = {}  # hub_code → best cost so far
    path_by_hub: dict[str, _PriorityNode] = {}  # hub_code → node that set the current best

    start_node = _PriorityNode(
        priority=Decimal("0"),
        hub_code=origin,
        path=[origin],
        total_distance=Decimal("0"),
        total_hours=Decimal("0"),
    )
    best[origin] = Decimal("0")
    heap: list[_PriorityNode] = [start_node]
    path_by_hub[origin] = start_node
    heapq.heapify(heap)

    while heap:
        node = heapq.heappop(heap)
        if node.hub_code == destination:
            break
        if node.priority > best.get(node.hub_code, inf_val):
            continue

        from_city = hub_cities.get(node.hub_code, "")
        for next_hub, dist, hours in graph.get(node.hub_code, []):
            to_city = hub_cities.get(next_hub, "")
            price = lane_price.get((from_city, to_city))
            if price is not None:
                seg_cost = weight_kg * price
            else:
                seg_cost = dist * fallback_rate

            new_cost = node.priority + seg_cost
            if new_cost < best.get(next_hub, inf_val):
                best[next_hub] = new_cost
                pushed = _PriorityNode(
                    priority=new_cost,
                    hub_code=next_hub,
                    path=node.path + [next_hub],
                    total_distance=node.total_distance + dist,
                    total_hours=node.total_hours + hours,
                    edge_distances=node.edge_distances + (dist,),
                    edge_hours=node.edge_hours + (hours,),
                )
                heapq.heappush(heap, pushed)
                path_by_hub[next_hub] = pushed

    # Check if destination was reached
    if destination not in best:
        return None

    winner = path_by_hub[destination]
    return {
        "path": winner.path,
        "total_distance": winner.total_distance,
        "total_hours": winner.total_hours,
        "total_cost": best[destination],
        "seg_distances": list(winner.edge_distances),
        "seg_hours": list(winner.edge_hours),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Phase A3 — generate_route_plan
# ═══════════════════════════════════════════════════════════════════════════════

@distributed_lock(key="generate_route_plan", timeout=30)
async def generate_route_plan(
    transport_order_id: str,
    db: AsyncSession,
    plan_type: str = "auto_gen",
) -> dict:
    """Generate a route plan for a transport order.

    When plan_type is "auto_gen", runs find_best_route_plan then
    persists the result as a RoutePlan record with TransportSegments.
    """
    order_uuid = _safe_uuid(transport_order_id)
    if order_uuid is None:
        raise NotFoundException(message=f"TransportOrder {transport_order_id} not found")
    # Step 1 — Run the core algorithm
    route = await find_best_route_plan(transport_order_id, db)

    # Step 2 — Create RoutePlan
    plan = RoutePlan(
        id=uuid.uuid4(),
        transport_order_id=order_uuid,
        type=RoutePlanType(plan_type),
        status=RoutePlanStatus.ROUTE_ACTIVE,
        origin_city=route["origin_city"],
        destination_city=route["destination_city"],
        total_distance_km=Decimal(route["total_distance_km"]),
        total_cost_amount=Decimal(route.get("total_cost_amount", "0")),
        estimated_transit_hours=Decimal(route["estimated_transit_hours"]),
        plan_json=route,
    )
    db.add(plan)
    await db.flush()  # get the plan ID without committing yet

    # Step 3 — Create TransportSegments for each segment in the route
    segments_created: list[dict] = []
    for seg in route.get("segments", []):
        seg_record = TransportSegment(
            id=uuid.uuid4(),
            transport_order_id=uuid.UUID(transport_order_id),
            segment_no=seg["segment_no"],
            origin_hub_code=seg["from_hub"],
            dest_hub_code=seg["to_hub"],
            status=TransportSegmentStatus.DRAFT,
            weight_kg=Decimal("0"),
            cost_amount=Decimal("0"),
            estimated_departure_time=None,
            expected_arrival_time=None,
        )
        db.add(seg_record)
        await db.flush()
        segments_created.append(model_to_dict(seg_record))

    await db.commit()
    await db.refresh(plan)

    result = model_to_dict(plan)
    result["segments"] = segments_created
    return result


@cached(ttl=300, prefix="tms", skip_args=1)
async def get_route_plan(db: AsyncSession, plan_id: str) -> dict:
    """Get a route plan by ID, including its segments."""
    plan_uuid = _safe_uuid(plan_id)
    if plan_uuid is None:
        raise NotFoundException(message=f"RoutePlan {plan_id} not found")
    result = await db.execute(select(RoutePlan).where(RoutePlan.id == plan_uuid))
    plan = result.scalar_one_or_none()
    if not plan:
        raise NotFoundException(message=f"RoutePlan {plan_id} not found")

    plan_dict = model_to_dict(plan)
    # Attach segments
    segs_result = await db.execute(
        select(TransportSegment)
        .where(TransportSegment.transport_order_id == plan.transport_order_id)
        .order_by(TransportSegment.segment_no)
    )
    plan_dict["segments"] = [model_to_dict(s) for s in segs_result.scalars().all()]
    return plan_dict


# ═══════════════════════════════════════════════════════════════════════════════
# Phase B — Tracking Events & POD (Proof of Delivery)
# ═══════════════════════════════════════════════════════════════════════════════

async def create_tracking_event(db: AsyncSession, data: dict) -> dict:
    """Record a tracking event for a transport order."""
    from src.tms.models import (
        TrackingEvent as _TrackingEvent,
    )
    from src.tms.models import (
        TransportOrder as TransportOrder,
    )

    result = await db.execute(
        select(TransportOrder).where(TransportOrder.id == _to_uuid(data["transport_order_id"])).with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundException(message=f"TransportOrder {data['transport_order_id']} not found")

    event_type = _as_event_type(data.get("event_type"))

    raw_operator_id = data.get("operator_id")
    operator_id = _to_uuid(raw_operator_id) if raw_operator_id else None
    # _to_uuid() answers None for anything it cannot parse; used directly that
    # filed the scan with no operator rather than saying the id was wrong.
    if raw_operator_id and operator_id is None:
        raise ValidationException(
            message=f"operator_id is not a valid id: {raw_operator_id!r}",
            detail={"operator_id": str(raw_operator_id)},
        )

    event = _TrackingEvent(
        id=uuid.uuid4(),
        transport_order_id=_to_uuid(data["transport_order_id"]),
        event_type=event_type,
        location_code=data.get("location_code"),
        location_name=data.get("location_name"),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        operator_id=operator_id,
        remark=data.get("remark"),
    )
    db.add(event)

    # Update parent order before commit — otherwise the change is lost
    if event_type == TrackingEventType.DELIVERED and not order.actual_delivery_time:
        order.actual_delivery_time = _now()

    await db.commit()
    await db.refresh(event)
    return model_to_dict(event)


async def list_tracking_events(db: AsyncSession, transport_order_id: str) -> list[dict]:
    """List all tracking events for a transport order."""
    order_uuid = _safe_uuid(transport_order_id)
    if order_uuid is None:
        raise NotFoundException(message=f"TransportOrder {transport_order_id} not found")
    stmt = (
        select(TrackingEvent)
        .where(TrackingEvent.transport_order_id == order_uuid)
        .order_by(TrackingEvent.created_at.asc())
    )
    result = await db.execute(stmt)
    return [model_to_dict(e) for e in result.scalars().all()]


def _photo_rows(value: object) -> list[dict] | None:
    """Delivery photos in the shape ``pod_records.delivery_photo_urls`` documents.

    The column is documented ``[{url, timestamp}]``, and the screen that lists
    the photos (``frontend/src/views/transport/TransportOrderDetail.vue``) reads
    a list of bare URLs — so the clients that post photos send URLs, and the
    record they get back is the shape the screen cannot display.  Bare strings
    and ``{url, timestamp}`` objects are both accepted and stored as the
    documented row; an entry that is neither is refused, because a photo the
    record cannot point at is a photo nobody can see.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValidationException(
            message="delivery_photo_urls must be a list of URLs or {url, timestamp} objects",
        )
    rows: list[dict] = []
    for item in value:
        if isinstance(item, str):
            rows.append({"url": item, "timestamp": None})
        elif isinstance(item, dict) and item.get("url"):
            rows.append({"url": str(item["url"]), "timestamp": item.get("timestamp")})
        else:
            raise ValidationException(
                message=f"delivery_photo_urls entry {item!r} names no URL — send a URL string "
                        "or {\"url\": ..., \"timestamp\": ...}",
            )
    return rows


async def create_pod(db: AsyncSession, data_or_transport_order_id: str | dict, data: dict | None = None) -> dict:
    """Create — and on a second submission, update — the POD of a transport order.

    Two call forms are supported: ``create_pod(db, data)`` and
    ``create_pod(db, order_id, data)``; the route names the order in its path.

    A POD is one per transport order (``pod_records.transport_order_id`` is
    unique), and the route used to treat a second submission as the first: the
    record existed, so nothing in the body was read, and the caller was answered
    201 for a signature they had just sent that was never recorded — a driver who
    re-submitted a POD after adding the delivery photos was told it was filed.
    The re-submission is applied now, field by field, so the fields a caller
    sends are the fields that change.

    The order named is also checked against ``transport_orders``.  Parsing the
    string was the whole check, so a POD written for a well-formed id that names
    no order reached the foreign key and failed at commit: a 500 for a request
    naming a shipment that does not exist, where a 404 naming it is the truth.
    """
    from src.tms.models import ProofOfDelivery

    if isinstance(data_or_transport_order_id, str):
        real_data: dict = {"transport_order_id": data_or_transport_order_id, **(data or {})}
    else:
        real_data = dict(data_or_transport_order_id)

    raw_order = real_data.get("transport_order_id")
    if not raw_order:
        raise ValidationException(
            message="transport_order_id is required — a POD records the delivery of a transport order",
        )
    order_uuid = _safe_uuid(raw_order)
    if order_uuid is None:
        raise NotFoundException(message=f"TransportOrder {raw_order} not found")
    if await db.scalar(select(TransportOrder).where(TransportOrder.id == order_uuid)) is None:
        raise NotFoundException(message=f"TransportOrder {raw_order} not found")

    pod = await db.scalar(select(ProofOfDelivery).where(ProofOfDelivery.transport_order_id == order_uuid))
    photos = _photo_rows(real_data.get("delivery_photo_urls"))

    if pod is None:
        pod = ProofOfDelivery(
            id=uuid.uuid4(),
            transport_order_id=order_uuid,
            signed_by=real_data.get("signed_by") or "unknown",
            signature_type=real_data.get("signature_type") or "physical",
            signature_image_url=real_data.get("signature_image_url"),
            delivery_photo_urls=photos or [],
            delivered_to_address=real_data.get("delivered_to_address"),
            notes=real_data.get("notes"),
        )
        db.add(pod)
    else:
        updates = {
            "signed_by": real_data.get("signed_by"),
            "signature_type": real_data.get("signature_type"),
            "signature_image_url": real_data.get("signature_image_url"),
            "delivery_photo_urls": photos,
            "delivered_to_address": real_data.get("delivered_to_address"),
            "notes": real_data.get("notes"),
        }
        for key, value in updates.items():
            if value is not None:
                setattr(pod, key, value)
        pod.updated_at = _now()

    await db.commit()
    await db.refresh(pod)
    return model_to_dict(pod)


async def get_pod(db: AsyncSession, transport_order_id: str) -> dict | None:
    """Get POD for a transport order."""
    from src.tms.models import ProofOfDelivery

    order_uuid = _safe_uuid(transport_order_id)
    if order_uuid is None:
        return None
    result = await db.execute(
        select(ProofOfDelivery).where(ProofOfDelivery.transport_order_id == order_uuid)
    )
    pod = result.scalar_one_or_none()
    return model_to_dict(pod) if pod else None


async def update_pod(db: AsyncSession, transport_order_id: str, data: dict) -> dict:
    """Update existing POD."""
    from src.tms.models import ProofOfDelivery

    order_uuid = _safe_uuid(transport_order_id)
    if order_uuid is None:
        raise NotFoundException(message="POD not found")
    result = await db.execute(
        select(ProofOfDelivery).where(ProofOfDelivery.transport_order_id == order_uuid)
    )
    pod = result.scalar_one_or_none()
    if not pod:
        raise NotFoundException(message="POD not found")

    # The fields a POD update carries.  ``signature_type`` is one of them: the
    # route accepted it, the set did not contain it, and an update that changed
    # a paper receipt to an on-screen signature left it as a paper receipt.
    updatable = {"signed_by", "signature_type", "signature_image_url", "delivery_photo_urls",
                 "delivered_to_address", "notes"}
    for key in updatable:
        if key in data and data[key] is not None:
            setattr(pod, key, _photo_rows(data[key]) if key == "delivery_photo_urls" else data[key])
    pod.updated_at = _now()

    await db.commit()
    await db.refresh(pod)
    return model_to_dict(pod)


# ═══════════════════════════════════════════════════════════════════════
# Return Order (Reverse Logistics)
# ═══════════════════════════════════════════════════════════════════════

async def create_return_order(db: AsyncSession, data: dict) -> dict:
    """File a return / reverse-logistics request.

    Every field of this body was read with a constructor that raises:
    ``ReturnReason(data["reason"])`` (KeyError on the console's body, ValueError
    on a reason code the domain does not know — and the console's reason field is
    a free-text textarea, so "damaged package" is the normal input),
    ``uuid.UUID(data["transport_order_id"])`` on the transport *number* the
    console sends, ``CarrierCode(...)``, and
    ``Decimal(str(data.get("refund_amount", "0")))``.  Any one of them raised
    inside the handler, so the console's 创建退货 button answered 500 and named
    nothing — a refund request typed by a person became a server failure.

    ``destination_warehouse_id`` was written straight from the body into a UUID
    column, so a warehouse code — what a handheld scans — arrived as a string.
    It is resolved by id *or* code now, refused by the field that named it.
    """
    from datetime import date

    from src.tms.models import ReturnOrder, ReturnReason

    count = (await db.execute(select(func.count()).select_from(ReturnOrder))).scalar() or 0
    ret = ReturnOrder(
        id=uuid.uuid4(), return_no=f"RTN-{date.today().strftime('%Y%m%d')}-{count+1:04d}",
        status="requested", reason=_as_choice(data.get("reason"), ReturnReason, field="reason"),
        reason_detail=data.get("reason_detail"),
        transport_order_id=(
            await _resolve_transport_order(db, data["transport_order_id"], field="transport_order_id")
            if data.get("transport_order_id") else None
        ),
        carrier_code=_carrier_code(data["carrier_code"]) if data.get("carrier_code") else None,
        return_tracking_number=data.get("return_tracking_number"),
        pickup_address=data.get("pickup_address") or {},
        destination_warehouse_id=(
            await _resolve_warehouse_id(db, data["destination_warehouse_id"])
            if data.get("destination_warehouse_id") else None
        ),
        refund_amount=_as_decimal(data.get("refund_amount", "0"), field="refund_amount"),
    )
    if ret.refund_amount < 0:
        raise ValidationException(
            message=f"refund_amount must be zero or more, got {ret.refund_amount} — a refund is "
                    "money leaving the seller, and the settlement step reads it as such",
        )
    db.add(ret)
    await db.commit()
    await db.refresh(ret)
    return model_to_dict(ret)


async def list_return_orders(db: AsyncSession, status=None, warehouse_id=None) -> tuple[list[dict], int]:
    from src.tms.models import ReturnOrder
    stmt = select(ReturnOrder)
    if status:
        stmt = stmt.where(ReturnOrder.status == status)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0
    stmt = stmt.order_by(ReturnOrder.created_at.desc())
    result = await db.execute(stmt)
    return [model_to_dict(r) for r in result.scalars().all()], total


async def get_return_order(db: AsyncSession, return_id: str) -> dict | None:
    from src.tms.models import ReturnOrder
    return_uuid = _safe_uuid(return_id)
    if return_uuid is None:
        raise NotFoundException(message=f"ReturnOrder {return_id} not found")
    result = await db.execute(select(ReturnOrder).where(ReturnOrder.id == return_uuid))
    ret = result.scalar_one_or_none()
    if not ret:
        raise NotFoundException(message=f"ReturnOrder {return_id} not found")
    return model_to_dict(ret)


async def update_return_status(db: AsyncSession, return_id: str, target: str) -> dict:
    from src.tms.models import ReturnOrder
    return_uuid = _safe_uuid(return_id)
    if return_uuid is None:
        raise NotFoundException(message=f"ReturnOrder {return_id} not found")
    result = await db.execute(select(ReturnOrder).where(ReturnOrder.id == return_uuid))
    ret = result.scalar_one_or_none()
    if not ret:
        raise NotFoundException(message=f"ReturnOrder {return_id} not found")
    allowed_transitions = {"requested": {"pickup_scheduled", "cancelled"},
        "pickup_scheduled": {"in_transit_return", "cancelled"},
        "in_transit_return": {"returned_to_warehouse", "cancelled"},
        "returned_to_warehouse": {"refunded", "closed"}}
    current = ret.status
    if target not in allowed_transitions.get(current, set()):
        # The allowed moves are named in the message, not only in a detail the
        # caller has to know to ask for: the screen drives this lifecycle by
        # button, and "you cannot do that" without the moves that exist is a
        # dead end.
        allowed = allowed_transitions.get(current, set())
        raise ValidationException(
            message=f"Cannot transition return from '{current}' to '{target}' — from '{current}' the "
                    f"moves are: {', '.join(sorted(allowed)) if allowed else 'none (this is a final state)'}",
            detail=f"Allowed: {sorted(allowed)}",
        )
    ret.status = target
    await db.commit()
    await db.refresh(ret)
    return model_to_dict(ret)


# ── Return Shipment Tracking (Item 91) ─────────────────────────────────────

async def mark_shipment_received(db: AsyncSession, return_id: str) -> dict:
    """Mark a return order as received by the carrier.

    Transition flow: PENDING → IN_TRANSIT_RETURN → RECEIVED_BY_CARRIER
    """
    return_uuid = _safe_uuid(return_id)
    if return_uuid is None:
        raise NotFoundException(message=f"ReturnOrder {return_id} not found")
    result = await db.execute(select(ReturnOrder).where(ReturnOrder.id == return_uuid))
    ret = result.scalar_one_or_none()
    if not ret:
        raise NotFoundException(message=f"ReturnOrder {return_id} not found")

    allowed_transitions = {
        ReturnShipmentStatus.PENDING: [ReturnShipmentStatus.IN_TRANSIT_RETURN],
        ReturnShipmentStatus.IN_TRANSIT_RETURN: [ReturnShipmentStatus.RECEIVED_BY_CARRIER],
    }

    current = ret.shipment_status
    if current not in allowed_transitions:
        raise ValidationException(message=f"Cannot transition shipment from '{current}'")

    if ReturnShipmentStatus.RECEIVED_BY_CARRIER not in allowed_transitions[current]:
        raise ValidationException(
            message=f"Cannot move to RECEIVED_BY_CARRIER, expected one of {allowed_transitions.get(current)}"
        )

    ret.shipment_status = ReturnShipmentStatus.RECEIVED_BY_CARRIER
    ret.status = ReturnStatus.IN_TRANSIT_RETURN

    await db.commit()
    await db.refresh(ret)
    return model_to_dict(ret)


async def mark_return_inspected(db: AsyncSession, return_id: str, accepted: bool = True) -> dict:
    """Inspect a returned item and decide disposition.

    If accepted → REFUNDED / CLOSED
    If rejected → RETURNED_TO_SUPPLIER
    """
    return_uuid = _safe_uuid(return_id)
    if return_uuid is None:
        raise NotFoundException(message=f"ReturnOrder {return_id} not found")
    result = await db.execute(select(ReturnOrder).where(ReturnOrder.id == return_uuid))
    ret = result.scalar_one_or_none()
    if not ret:
        raise NotFoundException(message=f"ReturnOrder {return_id} not found")

    allowed_statuses = [ReturnStatus.RETURNED_TO_WAREHOUSE, ReturnStatus.IN_TRANSIT_RETURN]
    if ret.status not in allowed_statuses:
        raise ValidationException(
            message=f"Cannot inspect return in status '{ret.status}'"
        )

    if accepted:
        # Item verified OK → refund and close
        ret.status = ReturnStatus.REFUNDED
        ret.shipment_status = ReturnShipmentStatus.RETURNED_TO_WAREHOUSE
    else:
        # Reject → send back to supplier (handled by admin workflow)
        ret.status = ReturnStatus.CANCELLED
        ret.shipment_status = ReturnShipmentStatus.RETURNED_TO_WAREHOUSE

    await db.commit()
    await db.refresh(ret)
    return model_to_dict(ret)


async def cancel_return_order(db: AsyncSession, return_id: str) -> dict:
    """Cancel a return order (only if still in PENDING or SHIPPED)."""
    return_uuid = _safe_uuid(return_id)
    if return_uuid is None:
        raise NotFoundException(message=f"ReturnOrder {return_id} not found")
    result = await db.execute(select(ReturnOrder).where(ReturnOrder.id == return_uuid))
    ret = result.scalar_one_or_none()
    if not ret:
        raise NotFoundException(message=f"ReturnOrder {return_id} not found")

    allowed_cancel_statuses = [ReturnStatus.REQUESTED, ReturnStatus.PICKUP_SCHEDULED]
    if ret.status not in allowed_cancel_statuses:
        raise ValidationException(
            message=f"Cannot cancel return in status '{ret.status}'"
        )

    ret.status = ReturnStatus.CLOSED
    ret.shipment_status = ReturnShipmentStatus.RETURNED_TO_WAREHOUSE

    await db.commit()
    await db.refresh(ret)
    return model_to_dict(ret)


# ═══════════════════════════════════════════════════════════════════════
# Transport Exception / Incident
# ═══════════════════════════════════════════════════════════════════════

async def create_exception(db: AsyncSession, data: dict) -> dict:
    """Report a transport exception.

    The type was read as ``ExceptionType(data["type"])``.  The console that
    reports exceptions (``frontend/src/views/transport/ExceptionList.vue``) sends
    ``exception_type``, so the key the handler reached for was never in the body:
    a ``KeyError`` inside the handler, reported as a server failure, for a person
    reporting a delayed shipment.  The type is read as the vocabulary the domain
    knows, and a value outside it names that vocabulary.

    The order named was *checked* as an id and *written* as whatever arrived, so
    a transport number — the form the API itself prints, and the form the
    console sends — answered 404 for a shipment that exists, and any value that
    passed the parse was written into a UUID column.  It is resolved by id *or*
    transport number and written as the order's id.
    """
    from src.tms.models import ExceptionType, TransportException

    # transport_order_id may be optional (exceptions not linked to an order)
    order_id = data.get("transport_order_id")
    order_uuid = await _resolve_transport_order(db, order_id) if order_id else None

    exc = TransportException(
        id=uuid.uuid4(),
        transport_order_id=order_uuid,
        type=_as_choice(data.get("type"), ExceptionType, field="type"),
        status="open", severity=data.get("severity", "normal"),
        description=data.get("description"), resolution_notes=data.get("resolution_notes"),
    )
    db.add(exc)
    await db.commit()
    await db.refresh(exc)
    return await _exception_payload(db, exc)


async def _exception_payload(db: AsyncSession, exc: object) -> dict:
    """An exception record with the shipment's number next to its id.

    An exception is acted on at a shipment, and the number a person reads on a
    box, in a list, and in a carrier's own site is ``transport_no`` — the API's
    own answer for a transport order prints it.  An exception list that carries
    only the shipment's uuid asks the operator to read a uuid, which is why the
    console (``ExceptionList.vue``) shows a 运单号 column that has never had a
    value in it.
    """
    payload = model_to_dict(exc)
    order_id = _safe_uuid(payload.get("transport_order_id"))
    payload["transport_order_no"] = (
        await db.scalar(select(TransportOrder.transport_no).where(TransportOrder.id == order_id))
        if order_id is not None else None
    )
    return payload


async def list_exceptions(db: AsyncSession, transport_order_id=None, status="open") -> list[dict]:
    from src.tms.models import TransportException
    stmt = select(TransportException).where(TransportException.status == status)
    if transport_order_id:
        order_uuid = _safe_uuid(transport_order_id)
        if order_uuid is None:
            return []
        stmt = stmt.where(TransportException.transport_order_id == order_uuid)
    result = await db.execute(stmt.order_by(TransportException.created_at.desc()))
    return [await _exception_payload(db, e) for e in result.scalars().all()]


async def get_exception(db: AsyncSession, exc_id: str) -> dict:
    """One exception by id, with the shipment's number beside its id.

    The console reads a single exception (``ExceptionList.vue`` 详情); there was
    no route for one, so it queried the list with an ``exception_id`` parameter
    the route ignores — and the list defaults to ``status="open"``, which is why
    a resolved exception's detail view has never shown what it was resolved with.
    """
    from src.tms.models import TransportException

    exc_uuid = _safe_uuid(exc_id)
    if exc_uuid is None:
        raise NotFoundException(message=f"TransportException {exc_id} not found")
    exc = await db.scalar(select(TransportException).where(TransportException.id == exc_uuid))
    if exc is None:
        raise NotFoundException(message=f"TransportException {exc_id} not found")
    return await _exception_payload(db, exc)


async def resolve_exception(db: AsyncSession, exc_id: str, resolution_notes=None) -> dict:
    from src.tms.models import TransportException
    exc_uuid = _safe_uuid(exc_id)
    if exc_uuid is None:
        raise NotFoundException(message=f"TransportException {exc_id} not found")
    result = await db.execute(select(TransportException).where(TransportException.id == exc_uuid))
    exc = result.scalar_one_or_none()
    if not exc:
        raise NotFoundException(message=f"TransportException {exc_id} not found")
    exc.status = "resolved"
    exc.resolution_notes = resolution_notes or exc.resolution_notes
    await db.commit()
    await db.refresh(exc)
    return await _exception_payload(db, exc)


# ═══════════════════════════════════════════════════════════════════════
# FreightTier (Shipping Cost Calculation)
# ═══════════════════════════════════════════════════════════════════════

def _carrier_code(value: object) -> CarrierCode:
    """Carrier codes are a closed set, and an unknown one is a request error.

    ``CarrierCode(value)`` on a typo raised a bare ValueError, which the generic
    handler turned into a 500 — and in ``estimate_freight`` the unknown code was
    never checked at all, so a misspelled carrier quietly received a generic
    price.  Both now get a 422 that names the code it did not recognise.
    """
    try:
        return CarrierCode(str(value))
    except ValueError:
        valid = ", ".join(sorted(code.value for code in CarrierCode))
        raise ValidationException(
            message=f"unknown carrier_code {value!r} (expected one of: {valid})"
        ) from None


async def _freight_tiers(db: AsyncSession, carrier: CarrierCode) -> list[FreightTier]:
    result = await db.execute(select(FreightTier).where(FreightTier.carrier_code == carrier))
    return list(result.scalars().all())


def _match_freight_tier(
    tiers: list[FreightTier],
    *,
    weight_kg: Decimal,
    volume_m3: Decimal,
    distance_km: Decimal,
) -> FreightTier | None:
    """The tier whose bracket covers this shipment.

    Shared with estimate_freight() on purpose: which rule measures what is one
    rule, and having it written twice is how a quote and an invoice stop agreeing.
    """
    for tier in tiers:
        if tier.rule_type == FreightRule.DISTANCE_TIERED:
            measure = distance_km
        elif tier.rule_type == FreightRule.VOLUME_BASED:
            measure = volume_m3
        else:  # WEIGHT_TIERED and FLAT_RATE bracket on weight
            measure = weight_kg
        if measure <= 0:
            continue  # request lacks the measurement this rule prices on
        if tier.min_value <= measure and (tier.max_value is None or measure <= tier.max_value):
            return tier
    return None


def _price_freight_tier(
    tier: FreightTier,
    *,
    weight_kg: Decimal,
    volume_m3: Decimal,
    distance_km: Decimal,
    express: bool = False,
) -> Decimal:
    """Money for one tier, honouring its ``rule_type``."""
    unit_price = Decimal(str(tier.price_per_unit))
    if tier.rule_type == FreightRule.FLAT_RATE:
        total = unit_price
    elif tier.rule_type == FreightRule.DISTANCE_TIERED:
        total = unit_price * distance_km
    elif tier.rule_type == FreightRule.VOLUME_BASED:
        total = unit_price * volume_m3
    else:  # WEIGHT_TIERED
        total = unit_price * weight_kg

    if express:
        total += Decimal(str(tier.surcharge_express or 0))
    return total.quantize(Decimal("0.01"))


async def create_freight_tier(db: AsyncSession, data: dict) -> dict:
    """Add a bracket to a carrier's rate card.

    ``FreightTierList.vue`` posts ``{carrier_code, weight_from, weight_to,
    price_per_kg}``; this function read ``data["rule_type"]`` and
    ``data["price_per_unit"]`` — two ``KeyError``s for a request whose bracket
    the form fully described, so the console's 提交 answered 500 and no carrier
    has ever gained a tier from that screen.  The bracket's keys are the
    console's spellings (accepted by ``FreightTierCreate``), the rule defaults to
    the one the form's fields measure, and a bracket whose ceiling is below its
    floor is refused: it covers no shipment, and a carrier holding it answers
    "no matching freight tier" for the shipments that should have matched it.
    """
    min_value = _as_decimal(data.get("min_value") if data.get("min_value") is not None else "0",
                            field="min_value")
    max_value = (_as_decimal(data["max_value"], field="max_value")
                 if data.get("max_value") not in (None, "") else None)
    if max_value is not None and max_value < min_value:
        raise ValidationException(
            message=f"max_value {max_value} is below min_value {min_value} — a bracket whose ceiling "
                    "is under its floor covers no shipment",
        )
    tier = FreightTier(
        id=uuid.uuid4(), carrier_code=_carrier_code(data.get("carrier_code")),
        rule_type=_as_choice(data.get("rule_type") or "weight_tiered", FreightRule, field="rule_type"),
        min_value=min_value,
        max_value=max_value,
        price_per_unit=_as_decimal(
            data.get("price_per_unit") if data.get("price_per_unit") is not None else "",
            field="price_per_unit",
        ),
        surcharge_express=_as_decimal(data.get("surcharge_express")
                                      if data.get("surcharge_express") is not None else "0",
                                      field="surcharge_express"),
    )
    if tier.min_value < 0 or tier.price_per_unit < 0 or tier.surcharge_express < 0:
        raise ValidationException(
            message="a rate-card bracket cannot carry negative bounds — a negative price per unit "
                    "pays the shipper, and the settlement step reads it as a charge",
        )
    db.add(tier)
    await db.commit()
    await db.refresh(tier)
    return model_to_dict(tier)


async def calculate_freight(db: AsyncSession, data: dict) -> dict:
    """Calculate freight honouring each tier's ``rule_type``.

    Previously every tier was billed as ``price_per_unit × weight`` regardless
    of its rule — FLAT_RATE tiers got multiplied by weight, DISTANCE_TIERED
    charged weight instead of kilometres, VOLUME_BASED charged weight instead
    of cubic metres, and the math ran through float.  Now:

        WEIGHT_TIERED   bracket matched on weight,   price × weight
        DISTANCE_TIERED bracket matched on km,       price × distance_km
        VOLUME_BASED    bracket matched on volume,   price × volume_m3
        FLAT_RATE       bracket matched on weight,   fixed price (no multiply)

    ``distance_km`` / ``volume_m3`` are new optional request fields; rules that
    need them skip tiers when the request omits the measurement.
    """
    # ``data.get("weight", 1)`` — the console sends ``total_weight_kg``, so the
    # weight the operator typed never reached the calculation and every quote
    # the console showed priced the shipment as 1 kg.  ``FreightCalculateRequest``
    # accepts the console's spelling; the guard here keeps a non-number a 422 for
    # callers that reach the service directly.
    carrier = _carrier_code(data.get("carrier_code"))
    # Each measurement is spelled a few ways by the clients that send it: the
    # rate-card screen says ``total_weight_kg``, the body's own field is
    # ``weight``, a distance is a ``distance`` on one form and a ``distance_km``
    # on the other.  All of them name the same measurement.
    def _sent(*keys: str, default: object) -> Decimal:
        for key in keys:
            if data.get(key) is not None:
                return _as_decimal(data[key], field=key)
        return Decimal(str(default))

    weight_kg = _sent("weight", "weight_kg", "total_weight_kg", default=1)
    volume_m3 = _sent("volume", "volume_m3", default=0)
    distance_km = _sent("distance_km", "distance", default=0)
    for name, qty in (("weight", weight_kg), ("volume", volume_m3), ("distance_km", distance_km)):
        if qty < 0:
            raise ValidationException(message=f"{name} cannot be negative, got {qty}")

    tier = _match_freight_tier(
        await _freight_tiers(db, carrier),
        weight_kg=weight_kg, volume_m3=volume_m3, distance_km=distance_km,
    )
    if tier is None:
        raise ValidationException(
            message="No matching freight tier found "
            "(check weight/volume/distance against the carrier's tiers)"
        )

    total_price = _price_freight_tier(
        tier,
        weight_kg=weight_kg, volume_m3=volume_m3, distance_km=distance_km,
        express=bool(data.get("express")),
    )

    return {"carrier_code": carrier.value, "weight_kg": str(weight_kg),
            "total_freight_yuan": str(total_price),
            "rule_type": tier.rule_type.value,
            "price_per_unit": str(tier.price_per_unit),
            "tier_min_value": str(tier.min_value),
            "tier_max_value": str(tier.max_value) if tier.max_value else None}


# ═══════════════════════════════════════════════════════════════════════
# ML Forecast (Demand Prediction)
# ═══════════════════════════════════════════════════════════════════════

async def record_forecast_observation(db: AsyncSession, data: dict) -> dict:
    """Record daily order count for the forecast model.

    ``float(data["count"])`` raised on the two ordinary failures of a hand-typed
    count — absent, and written as text — and the demand model's own input was
    reported as a server failure.  The lane is checked too: an observation on an
    empty lane key trains the model on a city pair no order will ever match.
    """
    from src.tms.ml.forecast import forecaster

    origin = str(data.get("origin_city") or "").strip()
    destination = str(data.get("destination_city") or "").strip()
    if not origin or not destination:
        raise ValidationException(
            message="origin_city and destination_city are required — an observation belongs to a lane",
            detail={"origin_city": origin, "destination_city": destination},
        )
    if data.get("count") is None:
        raise ValidationException(message="count is required — the observation is the order count")
    count = _as_int(data["count"], field="count")
    if count < 0:
        raise ValidationException(
            message=f"count {count} is negative — a day with negative orders is not an observation",
        )
    key = f"{origin}-{destination}"
    forecaster.add_observation(key, float(count))
    return {"status": "ok", "key": key}


async def get_forecast(db: AsyncSession, data: dict) -> list[dict]:
    """Get forecast for a given origin/destination pair."""
    from src.tms.ml.forecast import forecaster
    key = f"{data.get('origin_city', '')}-{data.get('destination_city', '')}"
    days = int(data.get("days", 7))
    points = forecaster.forecast(key, days)
    return [p.__dict__ for p in points]


async def train_forecast(db: AsyncSession, months: int = 6) -> dict:
    """Batch train the forecast model from historical transport orders.

    ``months`` is read through :func:`_as_int` and bounded to the window the
    forecaster has: a task calling this with ``"6"`` used to reach ``timedelta``
    and raise, and a window of 600 months asked the model to extrapolate over
    data far older than the series it was built on.  Orders whose address has no
    city are skipped, not trained on — same reason as
    :func:`record_forecast_observation`: a lane key of ``"-"`` is a city pair no
    order will ever look up.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from src.tms.models import TransportOrder

    window = _as_int(months, field="months")
    if not 1 <= window <= 36:
        raise ValidationException(
            message=f"months {window} is outside the training window (1-36)",
            detail={"months": str(window)},
        )
    cutoff = datetime.now(UTC) - timedelta(days=30 * window)
    stmt = select(
        TransportOrder.pickup_address,
        TransportOrder.delivery_address,
        TransportOrder.created_at,
    ).where(TransportOrder.created_at >= cutoff)
    rows = (await db.execute(stmt)).all()

    from src.tms.ml.forecast import forecaster

    # The day bucket happens here, not in SQL: the grouping this needs used
    # ``date_trunc``, which is a PostgreSQL function, so the training run raised
    # on every other dialect — answered 500, and never worked at all on the
    # SQLite file the test suite runs on.  Grouping in Python is dialect-neutral
    # and the window is bounded by ``months``, so the rows are bounded too.
    buckets: dict[tuple[str, str, str], int] = {}
    skipped = 0
    for pickup, delivery, created_at in rows:
        origin = ((pickup or {}).get("city") or "").strip()
        dest = ((delivery or {}).get("city") or "").strip()
        if not origin or not dest:
            skipped += 1
            continue
        day = (created_at.date() if created_at else datetime.now(UTC).date()).isoformat()
        lane_day = (origin, dest, day)
        buckets[lane_day] = buckets.get(lane_day, 0) + 1

    for (origin, dest, _day), orders in buckets.items():
        forecaster.add_observation(f"{origin}-{dest}", float(orders))
    return {"status": "ok", "trained": len(buckets), "skipped": skipped}


# ═══════════════════════════════════════════════════════════════════════
# Freight estimation
# ═══════════════════════════════════════════════════════════════════════
#
# An estimate is the one price produced without a transport order and without a
# route.  That is legitimate — a quote has to be answerable before either exists
# — but the number has to say where it came from, and it has to come from the
# same rules an invoice uses.
#
# What was here instead was a hard-coded four-carrier table named
# ``estimate_freight_sync`` ("sync wrapper … used by tests that call directly")
# with an async wrapper named ``estimate_freight`` ("async alias … used by
# tests").  The wrapper is what ``src/tms/router.py`` calls, so every
# /freight-estimate quote ignored the carrier's configured FreightTier rows
# entirely, priced any carrier code that missed the table at a generic 7.0,
# reported a 2-day transit for every carrier and every service level, and could
# not be told apart from a real rate-card price in the response.

# Placeholder rates for a carrier with no configured tiers.
# Units: base rate per 100 km, plus 0.50 per kg.
_FALLBACK_BASE_RATE_PER_100KM: dict[str, Decimal] = {
    "sf_express": Decimal("8.5"),
    "zto": Decimal("7.0"),
    "yunda": Decimal("6.0"),
    "ems": Decimal("9.0"),
}
_FALLBACK_DEFAULT_BASE_RATE = Decimal("7.0")
_FALLBACK_WEIGHT_RATE_PER_KG = Decimal("0.5")
_SERVICE_MULTIPLIER: dict[str, Decimal] = {
    CarrierServiceType.STANDARD.value: Decimal("1.0"),
    CarrierServiceType.EXPRESS.value: Decimal("1.3"),
    CarrierServiceType.OVERNIGHT.value: Decimal("2.0"),
    CarrierServiceType.FREIGHT.value: Decimal("1.5"),
}


def _service_type(value: object) -> CarrierServiceType:
    """A service level is one of four things, and pricing each differently."""
    try:
        return CarrierServiceType(str(value))
    except ValueError:
        valid = ", ".join(sorted(t.value for t in CarrierServiceType))
        raise ValidationException(
            message=f"unknown service_type {value!r} (expected one of: {valid})"
        ) from None


async def estimate_freight(
    db: AsyncSession,
    carrier_code: str,
    service_type: str = "standard",
    distance_km: float | Decimal = 0,
    weight_kg: float | Decimal = 0,
    volume_m3: float | Decimal = 0,
) -> dict:
    """Quote freight for a lane that has not been booked yet.

    Pricing goes to the carrier's configured FreightTier rows first, through the
    same bracket-and-rule helpers calculate_freight() uses for a real shipment —
    so a quote and the invoice it becomes cannot disagree.  The placeholder table
    only stands in when the carrier has no tiers at all, and the response names
    which of the two priced it (``pricing_source``): a placeholder presented as a
    carrier's price is how a quote turns into a loss.

    ``transit_days`` is None on purpose.  This endpoint is handed a distance, not
    a route; transit belongs to a lane (CarrierRoute.transit_hours) and a network
    path, and inferring days from kilometres is how a quote promises a delivery
    the network cannot make.  ``quote_transport_cost`` answers the routed question.
    """
    carrier = _carrier_code(carrier_code)
    service = _service_type(service_type)
    weight = Decimal(str(weight_kg or 0))
    distance = Decimal(str(distance_km or 0))
    volume = Decimal(str(volume_m3 or 0))

    tiers = await _freight_tiers(db, carrier)
    tier = _match_freight_tier(
        tiers, weight_kg=weight, volume_m3=volume, distance_km=distance,
    )
    if tier is not None:
        cost = _price_freight_tier(
            tier,
            weight_kg=weight, volume_m3=volume, distance_km=distance,
            express=service == CarrierServiceType.EXPRESS,
        )
        return {
            "carrier_code": carrier.value,
            "estimated_cost": str(cost),
            "transit_days": None,
            "pricing_source": "rate_card",
            "rule_type": tier.rule_type.value,
            "price_per_unit": str(tier.price_per_unit),
        }

    if tiers:
        # A rate card exists and does not cover this shipment.  Guessing a number
        # anyway would present the guess as the carrier's price.
        raise ValidationException(
            f"{carrier.value} has {len(tiers)} configured freight tier(s) and none covers "
            f"this shipment (weight {weight} kg, distance {distance} km, volume {volume} m3)"
        )

    base_rate = _FALLBACK_BASE_RATE_PER_100KM.get(carrier.value, _FALLBACK_DEFAULT_BASE_RATE)
    multiplier = _SERVICE_MULTIPLIER[service.value]
    cost = (
        base_rate * distance / Decimal("100")
        + weight * _FALLBACK_WEIGHT_RATE_PER_KG * multiplier
    ).quantize(Decimal("0.01"))
    logger.info(
        "Freight estimate for %s priced from the placeholder table: this carrier has no "
        "configured freight tiers, so the number is not a rate-card price",
        carrier.value,
    )
    return {
        "carrier_code": carrier.value,
        "estimated_cost": str(cost),
        "transit_days": None,
        "pricing_source": "placeholder_table",
    }
