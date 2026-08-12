"""WMS business logic — warehouses, locations, inventory, stock movements, picking.

All CRUD functions are async and require an ``AsyncSession``.
Maps ORM model fields to schema/Pydantic response field names.
"""
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundException, ValidationException
from src.core.pagination import paginate
from src.models.base import model_to_dict
from src.wms.models import (
    SKU,
    Address,
    CreditMemo,
    CreditMemoLine,
    Inventory,
    InventoryChangeType,
    InventoryLog,
    Invoice,
    InvoiceLine,
    Location,
    LocationStatus,
    LocationType,
    PickingWave,
    PickingWavePriority,
    PickingWaveType,
    PurchaseOrder,
    PurchaseOrderLine,
    StockInventoryLog,
    StockMovement,
    StockMovementType,
    TransferItemType,
    TransferOrder,
    TransferOrderLine,
    Vendor,
    Warehouse,
    WarehouseStatus,
    WarehouseType,
)


def _now() -> datetime:
    return datetime.now(UTC)


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


async def list_warehouses(db: AsyncSession, page: int | None = None, page_size: int | None = None) -> list[dict] | dict:
    """List all warehouses."""
    stmt = select(Warehouse).order_by(Warehouse.created_at.desc())
    if page is not None and page_size is not None:
        result = await paginate(stmt, db, page=page, page_size=page_size)
        items = []
        for wh in result.items:
            d = model_to_dict(wh)
            d["type"] = d.pop("warehouse_type", "standard")
            d["is_active"] = d.get("status") == "active"
            items.append(d)
        return {
            "items": items,
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "total_pages": result.total_pages,
        }
    result = await db.execute(stmt)
    warehouses = []
    for wh in result.scalars().all():
        d = model_to_dict(wh)
        d["type"] = d.pop("warehouse_type", "standard")
        d["is_active"] = d.get("status") == "active"
        warehouses.append(d)
    return warehouses


async def update_warehouse(db: AsyncSession, wh_id: str, data: dict) -> Warehouse | None:
    """Update an existing warehouse."""
    result = await db.execute(select(Warehouse).where(Warehouse.id == _to_uuid(wh_id)))
    wh = result.scalar_one_or_none()
    if not wh:
        raise NotFoundException(message=f"Warehouse {wh_id} not found")

    for key, value in data.items():
        setattr(wh, key, value)

    await db.commit()
    await db.refresh(wh)
    return wh


async def delete_warehouse(db: AsyncSession, wh_id: str) -> dict:
    """Soft-delete a warehouse (sets deleted_at)."""
    result = await db.execute(select(Warehouse).where(Warehouse.id == _to_uuid(wh_id)))
    wh = result.scalar_one_or_none()
    if not wh:
        raise NotFoundException(message=f"Warehouse {wh_id} not found")

    await db.delete(wh)
    await db.commit()
    d = model_to_dict(wh)
    d["type"] = d.pop("warehouse_type", "standard")
    d["is_active"] = False
    return d


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


async def list_locations(
    db: AsyncSession, wh_id: str | None = None, page: int | None = None, page_size: int | None = None
) -> list[dict] | dict:
    """List locations with optional warehouse filter."""
    stmt = select(Location)
    if wh_id:
        stmt = stmt.where(Location.warehouse_id == _to_uuid(wh_id))
    stmt = stmt.order_by(Location.created_at.desc())
    if page is not None and page_size is not None:
        result = await paginate(stmt, db, page=page, page_size=page_size)
        return {
            "items": [_loc_to_dict(loc) for loc in result.items],
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "total_pages": result.total_pages,
        }
    result = await db.execute(stmt)
    return [_loc_to_dict(loc) for loc in result.scalars().all()]


async def get_location(db: AsyncSession, loc_id: str) -> dict:
    """Get a location by ID."""
    result = await db.execute(select(Location).where(Location.id == _to_uuid(loc_id)))
    loc = result.scalar_one_or_none()
    if not loc:
        raise NotFoundException(message=f"Location {loc_id} not found")
    return _loc_to_dict(loc)


async def update_location(db: AsyncSession, wh_id: str, loc_id: str, data: dict) -> dict:
    """Update a location within a warehouse."""
    result = await db.execute(select(Location).where(
        Location.id == _to_uuid(loc_id),
        Location.warehouse_id == _to_uuid(wh_id),
    ))
    loc = result.scalar_one_or_none()
    if not loc:
        raise NotFoundException(message=f"Location {loc_id} not found in warehouse {wh_id}")

    zone = data.get("zone")
    if zone is not None:
        loc.zone = zone
    aisle = data.get("aisle")
    if aisle is not None:
        loc.aisle = aisle
    shelf = data.get("shelf")
    if shelf is not None:
        loc.shelf = shelf
    level = data.get("bin") or data.get("level")
    if level is not None:
        loc.level = level
    loc_type = data.get("type")
    if loc_type is not None:
        loc.location_type = LocationType(loc_type)

    await db.commit()
    await db.refresh(loc)
    return _loc_to_dict(loc)


async def delete_location(db: AsyncSession, wh_id: str, loc_id: str) -> None:
    """Delete a location within a warehouse."""
    result = await db.execute(select(Location).where(
        Location.id == _to_uuid(loc_id),
        Location.warehouse_id == _to_uuid(wh_id),
    ))
    loc = result.scalar_one_or_none()
    if not loc:
        raise NotFoundException(message=f"Location {loc_id} not found in warehouse {wh_id}")
    await db.delete(loc)
    await db.commit()


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
        "batch_no": inv.batch_no or "",
        "expiry_date": inv.expiry_date.isoformat() if inv.expiry_date else None,
        "manufacturing_date": inv.manufacturing_date.isoformat() if inv.manufacturing_date else None,
        "received_at": inv.received_at.isoformat() if inv.received_at else None,
        "quantity": qty,
        "reserved_qty": locked,
        "available_qty": qty - locked,
        "created_at": inv.created_at.isoformat() if inv.created_at else "",
        "updated_at": inv.updated_at.isoformat() if inv.updated_at else "",
    }


# ── Batch picking strategies ──────────────────────────────────────────────────


async def _pick_batches(
    db: AsyncSession,
    wh_id: uuid.UUID,
    loc_id: uuid.UUID | None,
    sku_id: uuid.UUID,
    need: Decimal,
    strategy: str = "fefo",
) -> list[dict]:
    """Select inventory batches to fulfil a pick request.

    ``strategy`` controls the order:
      - ``"fefo"`` (default) — First Expiry First Out
      - ``"fifo"`` — First In First Out (by ``received_at``)
      - ``"batch"`` — strict batch_no ordering

    Returns a list of batches with available quantity, sorted by the
    chosen strategy.  Each dict contains ``{"inv": Inventory, "available": Decimal}``.
    """
    stmt = select(Inventory).where(
        Inventory.warehouse_id == wh_id,
        Inventory.sku_id == sku_id,
        Inventory.quantity > 0,
    )
    if loc_id:
        stmt = stmt.where(Inventory.location_id == loc_id)

    if strategy == "fefo":
        stmt = stmt.order_by(Inventory.expiry_date.asc().nulls_last(), Inventory.received_at.asc())
    elif strategy == "fifo":
        stmt = stmt.order_by(Inventory.received_at.asc().nulls_last(), Inventory.batch_no.asc())
    else:
        stmt = stmt.order_by(Inventory.batch_no.asc())

    result = await db.execute(stmt)
    batches = []
    for inv in result.scalars().all():
        available = Decimal(str(inv.quantity)) - Decimal(str(inv.locked_qty))
        if available > 0:
            batches.append({"inv": inv, "available": available})
    return batches


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
    inventory_rows = result.scalars().all()
    sku_ids = {inv.sku_id for inv in inventory_rows if inv.sku_id}
    sku_map: dict[uuid.UUID, SKU] = {}
    if sku_ids:
        skus_result = await db.execute(select(SKU).where(SKU.id.in_(list(sku_ids))))
        sku_map = {s.id: s for s in skus_result.scalars().all()}
    items = []
    for inv in inventory_rows:
        sku_obj = sku_map.get(inv.sku_id)
        items.append(_inv_to_dict(inv, sku_obj.sku if sku_obj else ""))
    return items


async def adjust_inventory(db: AsyncSession, data: dict) -> dict:
    """Adjust inventory quantity (positive=in, negative=out).

    Supports batch-level tracking: when adding stock (qty > 0) the caller
    may provide ``batch_no``, ``expiry_date``, and ``manufacturing_date``.
    When removing stock (qty < 0) the system picks the best batch
    automatically (FEFO first, then FIFO).
    """
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

    now = _now()
    batch_no = data.get("batch_no", "DEFAULT")
    expiry_date = data.get("expiry_date")
    manufacturing_date = data.get("manufacturing_date")

    if qty > 0:
        inv_result = await db.execute(
            select(Inventory).where(
                Inventory.warehouse_id == wh_id,
                Inventory.location_id == loc_id,
                Inventory.sku_id == sku_obj.id,
                Inventory.batch_no == batch_no,
            )
        )
        inv = inv_result.scalar_one_or_none()
        if inv:
            new_qty = Decimal(str(inv.quantity)) + qty
            inv.quantity = new_qty
            inv.updated_at = now
            if expiry_date and not inv.expiry_date:
                inv.expiry_date = expiry_date
            if manufacturing_date and not inv.manufacturing_date:
                inv.manufacturing_date = manufacturing_date
        else:
            inv = Inventory(
                id=uuid.uuid4(),
                warehouse_id=wh_id,
                location_id=loc_id,
                sku_id=sku_obj.id,
                gtin="",
                batch_no=batch_no,
                expiry_date=expiry_date,
                manufacturing_date=manufacturing_date,
                received_at=now,
                quantity=qty,
                locked_qty=Decimal(0),
                min_qty=Decimal(0),
                max_qty=Decimal(0),
            )
            db.add(inv)
    else:
        need = abs(qty)
        batches = await _pick_batches(
            db, wh_id, loc_id, sku_obj.id, need,
            strategy=data.get("picking_strategy", "fefo"),
        )
        if not batches or sum(b["available"] for b in batches) < need:
            raise ValidationException(message="Insufficient stock")
        inv = batches[0]["inv"]
        inv.quantity = Decimal(str(inv.quantity)) + qty  # qty is negative
        inv.updated_at = now

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


# ── Stock Count / Inventory Adjustment (mobile app "盘点") ─────────────────────


async def adjust_stock_count(db: AsyncSession, data: dict) -> dict:
    """Process stock count results for a location.

    Mobile flow: operator scans each SKU and enters the actual qty.
    System compares with inventory → creates IN/OUT adjustments as needed.
    """
    # Accept both UUID-style `warehouse_id` and code-based `source_warehouse_code`
    wh_id: uuid.UUID | None = None
    if data.get("warehouse_id"):
        wh_id = _to_uuid(data["warehouse_id"])
    elif data.get("source_warehouse_code"):
        wh_result = await db.execute(select(Warehouse).where(Warehouse.code == data["source_warehouse_code"]))
        wh_obj = wh_result.scalar_one_or_none()
        if not wh_obj:
            raise NotFoundException(message=f"Warehouse {data['source_warehouse_code']} not found")
        wh_id = wh_obj.id

    loc_id_str = data.get("location_id") or data.get("target_location_id", "")
    if not loc_id_str:
        raise ValidationException(message="Missing location_id in count request")
    loc_id = _to_uuid(loc_id_str)

    # Validate warehouse exists (already done above with source_warehouse_code check)
    loc_result = await db.execute(select(Location).where(Location.id == loc_id))
    if not loc_result.scalar_one_or_none():
        raise NotFoundException(message=f"Location {loc_id} not found")

    results: list[dict] = data.get("count_results", [])
    if not results:
        raise ValidationException(message="No count results to process")

    now = _now()
    for item in results:
        # Mobile sends `sku_code` and `actual_qty_count`; service expects `sku` and `actual_qty`
        sku_str = item.get("sku", item.get("sku_code"))
        actual_qty_raw = item.get("actual_qty") or item.get("actual_qty_count")
        if actual_qty_raw is None:
            sku_val = item.get("sku", "unknown")
            raise ValidationException(
                message=f"Missing quantity field in count result for SKU {sku_val}"
            )
        actual_qty = Decimal(str(actual_qty_raw))

        # Lookup or create SKU
        sku_obj = await _get_or_create_sku(db, sku_str)

        # Current inventory at this location/SKU
        inv_result = await db.execute(
            select(Inventory).where(
                Inventory.warehouse_id == wh_id,
                Inventory.location_id == loc_id,
                Inventory.sku_id == sku_obj.id,
            )
        )
        inv = inv_result.scalar_one_or_none()

        system_qty = Decimal(str(inv.quantity)) if inv else Decimal(0)
        diff = actual_qty - system_qty  # positive = excess (IN), negative = shortage (OUT)

        if abs(diff) < Decimal("0.001"):
            continue  # no change needed

        if not inv:
            # Create new inventory record
            inv = Inventory(
                id=uuid.uuid4(),
                warehouse_id=wh_id,
                location_id=loc_id,
                sku_id=sku_obj.id,
                gtin="",
                batch_no="COUNT",
                quantity=actual_qty,
                locked_qty=Decimal(0),
                min_qty=Decimal(0),
                max_qty=Decimal(0),
                received_at=now,
            )
            db.add(inv)
        elif diff > 0:
            # Stock increase (盘盈)
            inv.quantity = actual_qty
        else:
            # Stock decrease (盘亏)
            if abs(diff) > Decimal(str(inv.quantity)):
                raise ValidationException(
                    message=f"SKU {sku_str}: actual qty ({actual_qty}) exceeds available inventory ({inv.quantity})"
                )
            inv.quantity = actual_qty

        inv.updated_at = now

        # Create adjustment log entry
        adj_type = "ADJUSTMENT_IN" if diff > 0 else "ADJUSTMENT_OUT"
        log_entry = StockInventoryLog(
            id=uuid.uuid4(),
            warehouse_id=wh_id,
            sku=sku_str,
            type=adj_type,
            reference_type="stock_count",
            quantity_change=abs(diff),
            reason="stock_count",
        )
        db.add(log_entry)

    await db.commit()
    return {"success": True, "message": f"Stock count processed: {len(results)} SKUs"}


async def list_movements(db: AsyncSession, wh_id: str | None = None) -> list[dict]:
    """List stock movements."""
    stmt = select(StockMovement)
    if wh_id:
        stmt = stmt.where(StockMovement.source_warehouse_id == _to_uuid(wh_id))
    stmt = stmt.order_by(StockMovement.created_at.desc())
    result = await db.execute(stmt)
    movements = result.scalars().all()
    sku_ids = {m.sku_id for m in movements if m.sku_id}
    sku_map: dict[uuid.UUID, SKU] = {}
    if sku_ids:
        skus_result = await db.execute(select(SKU).where(SKU.id.in_(list(sku_ids))))
        sku_map = {s.id: s for s in skus_result.scalars().all()}
    items = []
    for m in movements:
        sku_obj = sku_map.get(m.sku_id)
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


# ── Transfer Order (库存调拨) ───────────────────────────────────────────────


async def create_transfer_order(db: AsyncSession, data: dict) -> dict:
    """Create a transfer order with line items."""
    # Accept both `source_location` and `source_warehouse_code` / `source_warehouse_id`
    src_wh = _to_uuid(data["source_location"]) if data.get("source_location") else None

    target_wh_id_raw = (data.get("destination_warehouse_id")
                        or data.get("target_warehouse_id")
                        or data.get("source_warehouse_id"))
    # Mobile sends destination by code; try resolving from Warehouse.code
    if not target_wh_id_raw:
        raise ValidationException(message="destination_warehouse_id or target_warehouse_id required")

    if isinstance(target_wh_id_raw, str) and len(target_wh_id_raw) == 36:
        target_wh_id = _to_uuid(target_wh_id_raw)
    else:
        wh_result = await db.execute(select(Warehouse).where(Warehouse.code == target_wh_id_raw))
        wh_obj = wh_result.scalar_one_or_none()
        if not wh_obj:
            raise NotFoundException(message=f"Warehouse {target_wh_id_raw} not found")
        target_wh_id = wh_obj.id

    data.get("source_warehouse_code", "") or (src_wh.hex[:12].upper() if src_wh else "")

    # Generate transfer order code
    code = f"TO-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    transfer = TransferOrder(
        id=uuid.uuid4(),
        code=code,
        source_warehouse_id=target_wh_id if not src_wh else None,  # fallback to target if no source location
        target_warehouse_id=target_wh_id,
        type=TransferItemType.SKU,
        status="DRAFT",
    )
    db.add(transfer)

    for item_data in data.get("items", []):
        sku_str = item_data["sku"]
        qty = Decimal(str(item_data["quantity"]))
        sku_obj = await _get_or_create_sku(db, sku_str)

        line = TransferOrderLine(
            id=uuid.uuid4(),
            transfer_order_id=transfer.id,
            sku_id=sku_obj.id,
            location_from_id=src_wh,
            quantity=qty,
        )
        db.add(line)

    await db.commit()
    return model_to_dict(transfer)


async def list_transfers(db: AsyncSession, wh_id: str | None = None) -> list[dict]:
    """List transfer orders with optional warehouse filter."""
    stmt = select(TransferOrder).order_by(TransferOrder.created_at.desc())
    if wh_id:
        wh_uuid = _to_uuid(wh_id)
        stmt = stmt.where(
            or_(
                TransferOrder.source_warehouse_id == wh_uuid,
                TransferOrder.target_warehouse_id == wh_uuid,
            )
        )
    result = await db.execute(stmt)
    orders = result.scalars().all()

    # Load lines eagerly
    order_ids = [o.id for o in orders]
    lines_map: dict[uuid.UUID, list[dict]] = {}
    if order_ids:
        line_result = await db.execute(
            select(TransferOrderLine).where(
                TransferOrderLine.transfer_order_id.in_(order_ids)
            )
        )
        for ln in line_result.scalars().all():
            lines_map.setdefault(ln.transfer_order_id, []).append(model_to_dict(ln))

    items = []
    for o in orders:
        d = model_to_dict(o)
        d["lines"] = lines_map.get(o.id, [])
        items.append(d)
    return items


# ── Picking Wave Execution ──────────────────────────────────────────────────

async def start_picking(db: AsyncSession, wave_id: str, assignee: str = "") -> dict:
    """Start executing a picking wave — marks it in_progress."""
    result = await db.execute(select(PickingWave).where(PickingWave.id == _to_uuid(wave_id)))
    wave = result.scalar_one_or_none()
    if not wave:
        raise NotFoundException(message=f"Picking wave {wave_id} not found")
    if wave.status != "pending":
        raise ValidationException(message=f"Wave is already {wave.status}")

    wave.status = "in_progress"
    try:
        wave.assignee_id = _to_uuid(assignee) if assignee else None
    except (ValueError, TypeError):
        wave.assignee_id = None
    wave.updated_at = _now()
    await db.commit()
    await db.refresh(wave)
    d = model_to_dict(wave)
    d["wave_no"] = d.pop("code", "")
    return d


async def complete_picking(db: AsyncSession, wave_id: str) -> dict:
    """Mark a picking wave as completed."""
    result = await db.execute(select(PickingWave).where(PickingWave.id == _to_uuid(wave_id)))
    wave = result.scalar_one_or_none()
    if not wave:
        raise NotFoundException(message=f"Picking wave {wave_id} not found")
    if wave.status != "in_progress":
        raise ValidationException(message=f"Cannot complete wave in '{wave.status}' status")

    wave.status = "completed"
    wave.completed_items = wave.total_items
    wave.updated_at = _now()
    await db.commit()
    await db.refresh(wave)
    d = model_to_dict(wave)
    d["wave_no"] = d.pop("code", "")
    return d


# ── Packing ─────────────────────────────────────────────────────────────────

async def create_packing(db: AsyncSession, data: dict) -> dict:
    """Record packing for a completed picking wave."""
    from src.wms.models import PackingRecord

    wave_id = data["picking_wave_id"]
    result = await db.execute(select(PickingWave).where(PickingWave.id == _to_uuid(wave_id)))
    wave = result.scalar_one_or_none()
    if not wave:
        raise NotFoundException(message=f"Picking wave {wave_id} not found")
    if wave.status != "completed":
        raise ValidationException(message="Only completed waves can be packed")

    record = PackingRecord(
        id=uuid.uuid4(),
        picking_wave_id=_to_uuid(wave_id),
        packed_by=data.get("packed_by", ""),
        box_count=data.get("box_count", 1),
        notes=data.get("notes", ""),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return model_to_dict(record)


# ── Shipping ────────────────────────────────────────────────────────────────

async def create_shipment(db: AsyncSession, data: dict) -> dict:
    """Create a shipment for an order."""
    from src.wms.models import Shipment, ShipmentStatus

    order_id = data["order_id"]
    wh_id = data["warehouse_id"]

    wh_result = await db.execute(select(Warehouse).where(Warehouse.id == _to_uuid(wh_id)))
    if not wh_result.scalar_one_or_none():
        raise NotFoundException(message=f"Warehouse {wh_id} not found")

    shipment = Shipment(
        id=uuid.uuid4(),
        order_id=_to_uuid(order_id),
        warehouse_id=_to_uuid(wh_id),
        packing_record_id=_to_uuid(data.get("packing_record_id")),
        tracking_number=data.get("tracking_number", ""),
        carrier=data.get("carrier", ""),
        status=ShipmentStatus.PACKED if data.get("packing_record_id") else ShipmentStatus.PICKED,
    )
    db.add(shipment)
    await db.commit()
    await db.refresh(shipment)
    return model_to_dict(shipment)


async def mark_shipped(db: AsyncSession, shipment_id: str, tracking_number: str = "", carrier: str = "") -> dict:
    """Mark a shipment as shipped with tracking info."""
    from src.wms.models import Shipment, ShipmentStatus

    result = await db.execute(select(Shipment).where(Shipment.id == _to_uuid(shipment_id)))
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise NotFoundException(message=f"Shipment {shipment_id} not found")

    shipment.status = ShipmentStatus.SHIPPED
    shipment.tracking_number = tracking_number or shipment.tracking_number
    shipment.carrier = carrier or shipment.carrier
    shipment.shipped_at = _now().isoformat()
    shipment.updated_at = _now()
    await db.commit()
    await db.refresh(shipment)
    return model_to_dict(shipment)


async def list_shipments(db: AsyncSession, warehouse_id: str | None = None) -> list[dict]:
    """List shipments with optional warehouse filter."""
    from src.wms.models import Shipment

    stmt = select(Shipment)
    if warehouse_id:
        stmt = stmt.where(Shipment.warehouse_id == _to_uuid(warehouse_id))
    stmt = stmt.order_by(Shipment.created_at.desc())
    result = await db.execute(stmt)
    return [model_to_dict(s) for s in result.scalars().all()]


# ── Vendor CRUD ────────────────────────────────────────────────────────


async def create_vendor(db: AsyncSession, data: dict) -> dict:
    result = await db.execute(select(Vendor).where(Vendor.code == data["code"]))
    if result.scalar_one_or_none():
        raise ValidationException(message=f"Vendor code {data['code']} already exists")
    v = Vendor(id=uuid.uuid4(), **{k: data[k] for k in ("code", "name", "email", "phone") if k in data})
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return model_to_dict(v)


async def get_vendor(db: AsyncSession, vendor_id: str) -> dict:
    result = await db.execute(select(Vendor).where(Vendor.id == _to_uuid(vendor_id)))
    v = result.scalar_one_or_none()
    if not v:
        raise NotFoundException(message=f"Vendor {vendor_id} not found")
    return model_to_dict(v)


async def list_vendors(db: AsyncSession, page: int | None = None, page_size: int | None = None) -> list[dict] | dict:
    stmt = select(Vendor).order_by(Vendor.created_at.desc())
    if page is not None and page_size is not None:
        result = await paginate(stmt, db, page=page, page_size=page_size)
        return {
            "items": [model_to_dict(v) for v in result.items],
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "total_pages": result.total_pages,
        }
    result = await db.execute(stmt)
    return [model_to_dict(v) for v in result.scalars().all()]


# ── Address CRUD ───────────────────────────────────────────────────────


async def create_address(db: AsyncSession, data: dict) -> dict:
    kwargs = {}
    for k in ("entity_type", "address_type", "contact_name", "phone",
              "email", "address_line_1", "address_line_2", "city", "state",
              "postal_code", "country"):
        if data.get(k):
            kwargs[k] = data[k]
    if data.get("entity_id"):
        kwargs["entity_id"] = _to_uuid(data["entity_id"])
    a = Address(id=uuid.uuid4(), **kwargs)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return model_to_dict(a)


async def list_addresses(db: AsyncSession, entity_type: str | None = None, entity_id: str | None = None) -> list[dict]:
    stmt = select(Address)
    if entity_type:
        stmt = stmt.where(Address.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(Address.entity_id == _to_uuid(entity_id))
    stmt = stmt.order_by(Address.created_at.desc())
    result = await db.execute(stmt)
    return [model_to_dict(a) for a in result.scalars().all()]


# ── PurchaseOrder CRUD ─────────────────────────────────────────────────


async def create_purchase_order(db: AsyncSession, data: dict) -> dict:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        po_number=data["po_number"],
        vendor_id=_to_uuid(data.get("vendor_id")) if data.get("vendor_id") else None,
        expected_date=datetime.fromisoformat(data["expected_date"]).date() if data.get("expected_date") else None,
        notes=data.get("notes", ""),
    )
    db.add(po)
    await db.flush()

    total = Decimal("0")
    for line_data in data.get("lines", []):
        line = PurchaseOrderLine(
            id=uuid.uuid4(),
            purchase_order_id=po.id,
            sku_id=_to_uuid(line_data.get("sku_id")) if line_data.get("sku_id") else None,
            description=line_data.get("description", ""),
            quantity=Decimal(str(line_data.get("quantity", 1))),
            unit_price=Decimal(str(line_data.get("unit_price", 0))),
        )
        db.add(line)
        total += line.quantity * line.unit_price

    po.total_amount = total
    await db.commit()
    await db.refresh(po)
    return model_to_dict(po)


async def get_purchase_order(db: AsyncSession, po_id: str) -> dict:
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == _to_uuid(po_id)))
    po = result.scalar_one_or_none()
    if not po:
        raise NotFoundException(message=f"PurchaseOrder {po_id} not found")
    return model_to_dict(po)


async def list_purchase_orders(
    db: AsyncSession,
    page: int | None = None,
    page_size: int | None = None,
) -> list[dict] | dict:
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())
    if page is not None and page_size is not None:
        result = await paginate(stmt, db, page=page, page_size=page_size)
        return {
            "items": [model_to_dict(po) for po in result.items],
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "total_pages": result.total_pages,
        }
    result = await db.execute(stmt)
    return [model_to_dict(po) for po in result.scalars().all()]


async def approve_purchase_order(db: AsyncSession, po_id: str) -> dict:
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == _to_uuid(po_id)))
    po = result.scalar_one_or_none()
    if not po:
        raise NotFoundException(message=f"PurchaseOrder {po_id} not found")
    if po.status != "draft":
        raise ValidationException(message=f"Cannot approve PO in '{po.status}' state")
    po.status = "approved"
    await db.commit()
    await db.refresh(po)
    return model_to_dict(po)


async def receive_goods(db: AsyncSession, po_id: str) -> dict:
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == _to_uuid(po_id)))
    po = result.scalar_one_or_none()
    if not po:
        raise NotFoundException(message=f"PurchaseOrder {po_id} not found")
    if po.status not in ("approved", "partial"):
        raise ValidationException(message=f"Cannot receive goods for PO in '{po.status}' state")
    po.status = "received"
    await db.commit()
    await db.refresh(po)
    return model_to_dict(po)


# ── Invoice CRUD ───────────────────────────────────────────────────────


async def create_invoice(db: AsyncSession, data: dict) -> dict:
    inv = Invoice(
        id=uuid.uuid4(),
        invoice_number=data["invoice_number"],
        entity_type=data["entity_type"],
        entity_id=_to_uuid(data.get("entity_id")) if data.get("entity_id") else None,
        issue_date=datetime.fromisoformat(data["issue_date"]).date() if data.get("issue_date") else None,
        due_date=datetime.fromisoformat(data["due_date"]).date() if data.get("due_date") else None,
        notes=data.get("notes", ""),
    )
    db.add(inv)
    await db.flush()

    total = Decimal("0")
    for line_data in data.get("lines", []):
        line = InvoiceLine(
            id=uuid.uuid4(),
            invoice_id=inv.id,
            description=line_data.get("description", ""),
            quantity=Decimal(str(line_data.get("quantity", 1))),
            unit_price=Decimal(str(line_data.get("unit_price", 0))),
        )
        db.add(line)
        total += line.quantity * line.unit_price

    inv.total_amount = total
    await db.commit()
    await db.refresh(inv)
    return model_to_dict(inv)


async def get_invoice(db: AsyncSession, invoice_id: str) -> dict:
    result = await db.execute(select(Invoice).where(Invoice.id == _to_uuid(invoice_id)))
    inv = result.scalar_one_or_none()
    if not inv:
        raise NotFoundException(message=f"Invoice {invoice_id} not found")
    return model_to_dict(inv)


async def list_invoices(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(Invoice).order_by(Invoice.created_at.desc()))
    return [model_to_dict(inv) for inv in result.scalars().all()]


# ── CreditMemo CRUD ─────────────────────────────────────────────────────


async def create_credit_memo(db: AsyncSession, data: dict) -> dict:
    cm = CreditMemo(
        id=uuid.uuid4(),
        credit_memo_number=data["credit_memo_number"],
        invoice_id=_to_uuid(data.get("invoice_id")) if data.get("invoice_id") else None,
        entity_type=data["entity_type"],
        entity_id=_to_uuid(data.get("entity_id")) if data.get("entity_id") else None,
        issue_date=datetime.fromisoformat(data["issue_date"]).date() if data.get("issue_date") else None,
        reason=data.get("reason", ""),
        notes=data.get("notes", ""),
    )
    db.add(cm)
    await db.flush()

    total = Decimal("0")
    for line_data in data.get("lines", []):
        line = CreditMemoLine(
            id=uuid.uuid4(),
            credit_memo_id=cm.id,
            description=line_data.get("description", ""),
            quantity=Decimal(str(line_data.get("quantity", 1))),
            unit_price=Decimal(str(line_data.get("unit_price", 0))),
        )
        db.add(line)
        total += line.quantity * line.unit_price

    cm.total_amount = total
    await db.commit()
    await db.refresh(cm)
    return model_to_dict(cm)


async def get_credit_memo(db: AsyncSession, cm_id: str) -> dict:
    result = await db.execute(select(CreditMemo).where(CreditMemo.id == _to_uuid(cm_id)))
    cm = result.scalar_one_or_none()
    if not cm:
        raise NotFoundException(message=f"CreditMemo {cm_id} not found")
    return model_to_dict(cm)


async def list_credit_memos(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(CreditMemo).order_by(CreditMemo.created_at.desc()))
    return [model_to_dict(cm) for cm in result.scalars().all()]


# ── Stock In / Out (入库/出库) ───────────────────────────────────────────────

async def stock_in(
    db: AsyncSession,
    warehouse_id: str,
    data: dict,
    current_user: dict,
) -> dict:
    """录入商品到仓库（SKU、数量、批次号），返回操作后的实时库存快照。

    调用方传入单个 SKU 入库项：
      - sku: 商品编码
      - quantity: 入库数量
      - batch_no / expiry_date / manufacturing_date: 批次信息（可选）

    系统会：
      1. 校验仓库存在且状态为 active
      2. 自动创建/更新库存记录（按批次号匹配，无则新建）
      3. 写入 InventoryLog 审计日志
      4. 返回该 SKU 在该仓库的最新库存快照

    注意：本函数只处理单 SKU 入库。如需批量入库，调用方应多次调用或自行聚合后一次性提交。
    """
    wh_id = _to_uuid(warehouse_id)

    # 1. 校验仓库存在且状态为 active
    wh_result = await db.execute(select(Warehouse).where(Warehouse.id == wh_id))
    wh = wh_result.scalar_one_or_none()
    if not wh:
        raise NotFoundException(message=f"Warehouse {wh_id} not found")
    if wh.status != WarehouseStatus.ACTIVE.value:
        raise ValidationException(message=f"Warehouse {wh.code} is inactive (status={wh.status})")

    # 2. 解析入库项数据
    sku_str = data["sku"]
    qty = Decimal(str(data["quantity"]))
    batch_no = data.get("batch_no", "DEFAULT")
    expiry_date = data.get("expiry_date")
    manufacturing_date = data.get("manufacturing_date")

    # 3. 查找或创建 SKU
    sku_result = await db.execute(select(SKU).where(SKU.sku == sku_str))
    sku = sku_result.scalar_one_or_none()
    if not sku:
        sku = SKU(id=uuid.uuid4(), sku=sku_str, name=sku_str)
        db.add(sku)
        await db.flush()

    # 4. 查找现有库存记录（按仓库 +SKU+ 批次号）
    inv_result = await db.execute(
        select(Inventory).where(
            Inventory.warehouse_id == wh_id,
            Inventory.sku_id == sku.id,
            Inventory.batch_no == batch_no,
        )
    )
    inv = inv_result.scalar_one_or_none()

    now = _now()

    if qty > 0:
        # ── 入库（增加库存） ───────────────────────────────────────────────────
        if inv:
            new_qty = Decimal(str(inv.quantity)) + qty
            inv.quantity = new_qty
            inv.updated_at = now
            if expiry_date and not inv.expiry_date:
                inv.expiry_date = expiry_date
            if manufacturing_date and not inv.manufacturing_date:
                inv.manufacturing_date = manufacturing_date
        else:
            # 新建库存记录
            inv = Inventory(
                id=uuid.uuid4(),
                warehouse_id=wh_id,
                sku_id=sku.id,
                gtin="",
                batch_no=batch_no,
                expiry_date=expiry_date,
                manufacturing_date=manufacturing_date,
                received_at=now,
                quantity=qty,
                locked_qty=Decimal(0),
                min_qty=Decimal(0),
                max_qty=Decimal(0),
            )
            db.add(inv)

        # 写入审计日志（入库）
        log = InventoryLog(
            id=uuid.uuid4(),
            inventory_id=inv.id,
            change_type=InventoryChangeType.INBOUND,
            quantity_change=qty,
            quantity_before=float(inv.quantity) - qty if inv else 0.0,
            quantity_after=float(inv.quantity),
            reference_type="stock_in",
            reference_id=str(inv.id),
            operator_id=_to_uuid(current_user.get("id")) if current_user.get("id") else None,
            remark=data.get("remark"),
        )
        db.add(log)

    else:
        # ── 出库（减少库存） ───────────────────────────────────────────────────
        need = abs(qty)
        batches = await _pick_batches(
            db, wh_id, inv.location_id if inv else None, sku.id, need,
            strategy=data.get("picking_strategy", "fefo"),
        )
        if not batches or sum(b["available"] for b in batches) < need:
            raise ValidationException(message="Insufficient stock")

        # 扣减第一个批次（FEFO）
        inv = batches[0]["inv"]
        inv.quantity = Decimal(str(inv.quantity)) + qty  # qty is negative
        inv.updated_at = now

        # 写入审计日志（出库）
        log = InventoryLog(
            id=uuid.uuid4(),
            inventory_id=inv.id,
            change_type=InventoryChangeType.OUTBOUND,
            quantity_change=qty,
            quantity_before=float(inv.quantity) - qty if inv else 0.0,
            quantity_after=float(inv.quantity),
            reference_type="stock_in",
            reference_id=str(inv.id),
            operator_id=_to_uuid(current_user.get("id")) if current_user.get("id") else None,
            remark=data.get("remark"),
        )
        db.add(log)

    # 5. 提交事务并返回库存快照
    await db.commit()
    await db.refresh(inv)
    return _inv_to_dict(inv, sku_str)


async def stock_out(
    db: AsyncSession,
    warehouse_id: str,
    data: dict,
    current_user: dict,
) -> dict:
    """出库（减少库存），返回操作后的实时库存快照。

    调用方传入单个 SKU 出库项：
      - sku: 商品编码
      - quantity: 出库数量（正数）
      - picking_strategy: 拣货策略（默认"fefo"）
      - remark: 备注

    系统会按 FEFO/FIFO 自动选择批次扣减库存，并写入审计日志。
    """
    wh_id = _to_uuid(warehouse_id)

    # 1. 校验仓库存在且状态为 active
    wh_result = await db.execute(select(Warehouse).where(Warehouse.id == wh_id))
    wh = wh_result.scalar_one_or_none()
    if not wh:
        raise NotFoundException(message=f"Warehouse {wh_id} not found")
    if wh.status != WarehouseStatus.ACTIVE.value:
        raise ValidationException(message=f"Warehouse {wh.code} is inactive (status={wh.status})")

    # 2. 解析出库项数据
    sku_str = data["sku"]
    qty = Decimal(str(data["quantity"]))
    strategy = data.get("picking_strategy", "fefo")

    # 3. 查找或创建 SKU
    sku_result = await db.execute(select(SKU).where(SKU.sku == sku_str))
    sku = sku_result.scalar_one_or_none()
    if not sku:
        sku = SKU(id=uuid.uuid4(), sku=sku_str, name=sku_str)
        db.add(sku)
        await db.flush()

    # 4. 查找现有库存记录（按仓库 +SKU）
    inv_result = await db.execute(
        select(Inventory).where(
            Inventory.warehouse_id == wh_id,
            Inventory.sku_id == sku.id,
            Inventory.quantity > 0,
        )
    )
    inventory_rows = inv_result.scalars().all()

    if not inventory_rows:
        raise ValidationException(message="No stock available for this SKU in this warehouse")

    # 5. 按策略排序并扣减
    batches = []
    for inv in inventory_rows:
        available = Decimal(str(inv.quantity)) - Decimal(str(inv.locked_qty))
        if available > 0:
            batches.append({"inv": inv, "available": available})

    # 应用策略排序（FEFO / FIFO / BATCH）
    if strategy == "fefo":

        def sort_fefo(b):  # noqa: D103
            return (b["inv"].expiry_date or date.max, b["inv"].received_at or datetime.min)

        batches.sort(key=sort_fefo)
    elif strategy == "fifo":

        def sort_fifo(b):  # noqa: D103
            return (b["inv"].received_at or datetime.min, b["inv"].batch_no or "")

        batches.sort(key=sort_fifo)
    else:  # batch
        batches.sort(key=lambda b: b["inv"].batch_no or "", reverse=True)

    need = qty
    total_available = sum(b["available"] for b in batches)
    if total_available < need:
        raise ValidationException(message="Insufficient stock")

    # 扣减库存（从第一个批次开始）
    remaining = need
    for batch in batches:
        inv = batch["inv"]
        take = min(remaining, Decimal(str(inv.quantity)) - Decimal(str(inv.locked_qty)))
        if take > 0:
            inv.quantity = Decimal(str(inv.quantity)) - take
            inv.updated_at = _now()
            remaining -= take

    # 6. 写入审计日志（出库）
    log = InventoryLog(
        id=uuid.uuid4(),
        inventory_id=batches[0]["inv"].id,
        change_type=InventoryChangeType.OUTBOUND,
        quantity_change=-qty,
        quantity_before=float(batches[0]["inv"].quantity) + qty,
        quantity_after=float(batches[0]["inv"].quantity),
        reference_type="stock_out",
        operator_id=_to_uuid(current_user.get("id")) if current_user.get("id") else None,
        remark=data.get("remark"),
    )
    db.add(log)

    # 7. 提交事务并返回库存快照
    await db.commit()
    await db.refresh(batches[0]["inv"])
    return _inv_to_dict(batches[0]["inv"], sku_str)

