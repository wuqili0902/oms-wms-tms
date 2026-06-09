"""WMS business logic — warehouses, locations, inventory, stock movements, picking.

All CRUD functions are async and require an ``AsyncSession``.
Maps ORM model fields to schema/Pydantic response field names.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException, ValidationException
from src.models.base import model_to_dict
from src.wms.models import (
    Inventory,
    Location,
    LocationStatus,
    LocationType,
    PickingWave,
    PickingWavePriority,
    PickingWaveType,
    SKU,
    StockMovement,
    StockMovementType,
    Warehouse,
    WarehouseStatus,
    WarehouseType,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_uuid(val: str | uuid.UUID | None) -> uuid.UUID | None:
    if val is None or isinstance(val, uuid.UUID):
        return val
    return uuid.UUID(val)


# ── Warehouse CRUD ──────────────────────────────────────────────────────────

async def create_warehouse(db: AsyncSession, data: dict) -> dict:
    """Create a new warehouse."""
    existing = await db.execute(select(Warehouse).where(Warehouse.code == data["code"]))
    if existing.scalar_one_or_none():
        raise ValidationException(message=f"Warehouse code '{data['code']}' already exists")

    wh = Warehouse(
        id=uuid.uuid4(),
        code=data["code"],
        name=data["name"],
        address=data.get("address", ""),
        warehouse_type=WarehouseType(data.get("type", "standard"))
        if data.get("type") in [t.value for t in WarehouseType]
        else WarehouseType.CENTER,
        status=WarehouseStatus.ACTIVE,
    )
    db.add(wh)
    await db.commit()
    await db.refresh(wh)
    d = model_to_dict(wh)
    d["type"] = d.pop("warehouse_type", "standard")
    d["is_active"] = d.get("status") == "active"
    return d


async def get_warehouse(db: AsyncSession, wh_id: str) -> dict:
    """Get a warehouse by ID."""
    result = await db.execute(select(Warehouse).where(Warehouse.id == _to_uuid(wh_id)))
    wh = result.scalar_one_or_none()
    if not wh:
        raise NotFoundException(message=f"Warehouse {wh_id} not found")
    d = model_to_dict(wh)
    d["type"] = d.pop("warehouse_type", "standard")
    d["is_active"] = d.get("status") == "active"
    return d


async def list_warehouses(db: AsyncSession) -> list[dict]:
    """List all warehouses."""
    result = await db.execute(select(Warehouse).order_by(Warehouse.created_at.desc()))
    warehouses = []
    for wh in result.scalars().all():
        d = model_to_dict(wh)
        d["type"] = d.pop("warehouse_type", "standard")
        d["is_active"] = d.get("status") == "active"
        warehouses.append(d)
    return warehouses


# ── Location CRUD ───────────────────────────────────────────────────────────

async def create_location(db: AsyncSession, wh_id: str, data: dict) -> dict:
    """Create a location within a warehouse."""
    wh_result = await db.execute(select(Warehouse).where(Warehouse.id == _to_uuid(wh_id)))
    if not wh_result.scalar_one_or_none():
        raise NotFoundException(message=f"Warehouse {wh_id} not found")

    zone = data.get("zone", "")
    aisle = data.get("aisle", "")
    shelf = data.get("shelf", "")
    bin_val = data.get("bin", "")
    loc_code = f"{str(wh_id)[:4]}-{zone}-{aisle}-{bin_val}"

    loc = Location(
        id=uuid.uuid4(),
        warehouse_id=_to_uuid(wh_id),
        code=loc_code,
        zone=zone,
        aisle=aisle,
        shelf=shelf,
        level=bin_val,
        position=bin_val,
        location_type=LocationType(data.get("type", "storage")),
        status=LocationStatus.ACTIVE,
    )
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    d = model_to_dict(loc)
    d["location_code"] = d.pop("code", "")
    d["type"] = d.pop("location_type", "storage")
    d["bin"] = d.pop("level", "")
    d["is_occupied"] = False
    return d


def _loc_to_dict(loc: Location) -> dict:
    d = model_to_dict(loc)
    d["location_code"] = d.pop("code", "")
    d["type"] = d.pop("location_type", "storage")
    d["bin"] = d.pop("level", "")
    d["is_occupied"] = False
    return d


async def list_locations(db: AsyncSession, wh_id: str | None = None) -> list[dict]:
    """List locations with optional warehouse filter."""
    stmt = select(Location)
    if wh_id:
        stmt = stmt.where(Location.warehouse_id == _to_uuid(wh_id))
    stmt = stmt.order_by(Location.created_at.desc())
    result = await db.execute(stmt)
    return [_loc_to_dict(loc) for loc in result.scalars().all()]


async def get_location(db: AsyncSession, loc_id: str) -> dict:
    """Get a location by ID."""
    result = await db.execute(select(Location).where(Location.id == _to_uuid(loc_id)))
    loc = result.scalar_one_or_none()
    if not loc:
        raise NotFoundException(message=f"Location {loc_id} not found")
    return _loc_to_dict(loc)


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _get_or_create_sku(db: AsyncSession, sku_str: str) -> SKU:
    """Look up a SKU by code string, creating one if not found."""
    result = await db.execute(select(SKU).where(SKU.sku == sku_str))
    sku = result.scalar_one_or_none()
    if not sku:
        sku = SKU(id=uuid.uuid4(), sku=sku_str, name=sku_str)
        db.add(sku)
        await db.flush()
    return sku


def _inv_to_dict(inv: Inventory, sku_str: str) -> dict:
    """Convert an Inventory ORM row to schema dict (flat field names)."""
    qty = float(inv.quantity) if inv.quantity else 0.0
    locked = float(inv.locked_qty) if inv.locked_qty else 0.0
    return {
        "id": str(inv.id),
        "warehouse_id": str(inv.warehouse_id),
        "location_id": str(inv.location_id) if inv.location_id else "",
        "sku": sku_str,
        "quantity": qty,
        "reserved_qty": locked,
        "available_qty": qty - locked,
        "created_at": inv.created_at.isoformat() if inv.created_at else "",
        "updated_at": inv.updated_at.isoformat() if inv.updated_at else "",
    }


# ── Inventory ───────────────────────────────────────────────────────────────

async def query_inventory(
    db: AsyncSession,
    wh_id: str | None = None,
    location_id: str | None = None,
    sku: str | None = None,
) -> list[dict]:
    """Query inventory with optional filters."""
    stmt = select(Inventory)
    if wh_id:
        stmt = stmt.where(Inventory.warehouse_id == _to_uuid(wh_id))
    if location_id:
        stmt = stmt.where(Inventory.location_id == _to_uuid(location_id))
    if sku:
        sku_obj = await _get_or_create_sku(db, sku)
        stmt = stmt.where(Inventory.sku_id == sku_obj.id)
    result = await db.execute(stmt)
    items = []
    for inv in result.scalars().all():
        sku_obj = await db.get(SKU, inv.sku_id)
        items.append(_inv_to_dict(inv, sku_obj.sku if sku_obj else ""))
    return items


async def adjust_inventory(db: AsyncSession, data: dict) -> dict:
    """Adjust inventory quantity (positive=in, negative=out)."""
    wh_id = _to_uuid(data["warehouse_id"])
    loc_id = _to_uuid(data["location_id"])
    sku_str = data["sku"]
    qty = Decimal(str(data["quantity"]))

    wh_result = await db.execute(select(Warehouse).where(Warehouse.id == wh_id))
    if not wh_result.scalar_one_or_none():
        raise NotFoundException(message=f"Warehouse {wh_id} not found")
    loc_result = await db.execute(select(Location).where(Location.id == loc_id))
    if not loc_result.scalar_one_or_none():
        raise NotFoundException(message=f"Location {loc_id} not found")

    sku_obj = await _get_or_create_sku(db, sku_str)

    inv_result = await db.execute(
        select(Inventory).where(
            Inventory.warehouse_id == wh_id,
            Inventory.location_id == loc_id,
            Inventory.sku_id == sku_obj.id,
        )
    )
    inv = inv_result.scalar_one_or_none()

    now = _now()
    if inv:
        new_qty = Decimal(str(inv.quantity)) + qty
        if new_qty < 0:
            raise ValidationException(message="Insufficient stock")
        inv.quantity = new_qty
        inv.updated_at = now
    else:
        if qty < 0:
            raise ValidationException(message="Insufficient stock — no existing inventory")
        inv = Inventory(
            id=uuid.uuid4(),
            warehouse_id=wh_id,
            location_id=loc_id,
            sku_id=sku_obj.id,
            gtin="",
            batch_no="DEFAULT",
            quantity=qty,
            locked_qty=Decimal(0),
            min_qty=Decimal(0),
            max_qty=Decimal(0),
        )
        db.add(inv)

    movement = StockMovement(
        id=uuid.uuid4(),
        source_warehouse_id=wh_id,
        target_warehouse_id=None,
        source_location_id=loc_id if qty < 0 else None,
        target_location_id=loc_id if qty > 0 else None,
        sku_id=sku_obj.id,
        gtin="",
        quantity=abs(qty),
        movement_type=StockMovementType.TRANSFER,
    )
    db.add(movement)

    await db.commit()
    await db.refresh(inv)
    return _inv_to_dict(inv, sku_str)


async def list_movements(db: AsyncSession, wh_id: str | None = None) -> list[dict]:
    """List stock movements."""
    stmt = select(StockMovement)
    if wh_id:
        stmt = stmt.where(StockMovement.source_warehouse_id == _to_uuid(wh_id))
    stmt = stmt.order_by(StockMovement.created_at.desc())
    result = await db.execute(stmt)
    items = []
    for m in result.scalars().all():
        sku_obj = await db.get(SKU, m.sku_id)
        d = {
            "id": str(m.id),
            "warehouse_id": str(m.source_warehouse_id),
            "from_location_id": str(m.source_location_id) if m.source_location_id else None,
            "to_location_id": str(m.target_location_id) if m.target_location_id else None,
            "sku": sku_obj.sku if sku_obj else "",
            "quantity": float(m.quantity) if m.quantity else 0.0,
            "type": m.movement_type.value if m.movement_type else "transfer",
            "reference_no": getattr(m, "reference_no", m.id.hex[:12].upper()),
            "created_at": m.created_at.isoformat() if m.created_at else "",
        }
        items.append(d)
    return items


# ── Picking Waves ──────────────────────────────────────────────────────────

async def create_picking_wave(db: AsyncSession, data: dict) -> dict:
    """Create a picking wave."""
    wh_id = _to_uuid(data["warehouse_id"])
    wh_result = await db.execute(select(Warehouse).where(Warehouse.id == wh_id))
    if not wh_result.scalar_one_or_none():
        raise NotFoundException(message=f"Warehouse {wh_id} not found")

    order_ids = data.get("order_ids", [])
    if not order_ids:
        raise ValidationException(message="At least one order required")

    wave = PickingWave(
        id=uuid.uuid4(),
        warehouse_id=wh_id,
        code=f"WAVE-{uuid.uuid4().hex[:8].upper()}",
        wave_type=PickingWaveType.MIXED,
        priority=PickingWavePriority.MEDIUM,
    )
    db.add(wave)
    await db.commit()
    await db.refresh(wave)
    d = model_to_dict(wave)
    d["wave_no"] = d.pop("code", "")
    d["order_ids"] = order_ids
    d.pop("wave_type", None)
    d.pop("priority", None)
    d.pop("completed_items", None)
    d.pop("assignee_id", None)
    d["updated_at"] = d.get("updated_at", d.get("created_at", ""))
    return d


async def list_picking_waves(db: AsyncSession, wh_id: str | None = None) -> list[dict]:
    """List picking waves."""
    stmt = select(PickingWave)
    if wh_id:
        stmt = stmt.where(PickingWave.warehouse_id == _to_uuid(wh_id))
    stmt = stmt.order_by(PickingWave.created_at.desc())
    result = await db.execute(stmt)
    items = []
    for w in result.scalars().all():
        d = model_to_dict(w)
        d["wave_no"] = d.pop("code", "")
        d["order_ids"] = []
        d.pop("wave_type", None)
        d.pop("priority", None)
        d.pop("completed_items", None)
        d.pop("assignee_id", None)
        d["updated_at"] = d.get("updated_at", d.get("created_at", ""))
        items.append(d)
    return items
