"""WMS business logic — warehouses, locations, inventory, stock movements, picking.

All CRUD functions are async and require an ``AsyncSession``.
Maps ORM model fields to schema/Pydantic response field names.
"""
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictException, NotFoundException, ValidationException
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
    TransferStatus,
    Vendor,
    Warehouse,
    WarehouseStatus,
    WarehouseType,
)
from src.wms.schemas import TransferOrderCreate


def _now() -> datetime:
    return datetime.now(UTC)


def _to_uuid(val: str | uuid.UUID | None) -> uuid.UUID | None:
    if val is None or isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(val)
    except (ValueError, TypeError):
        return None


def _as_int(value: object, *, field: str) -> int:
    """Read a count out of a request value without raising inside the handler.

    A box count that arrives as ``"three"`` used to reach the Integer column
    untouched, where the insert died and the global handler answered 500: the
    screen said 系统异常, and the number the operator typed was the answer.
    """
    try:
        return int(str(value))
    except (ValueError, TypeError):
        raise ValidationException(
            message=f"{field} must be a whole number, got {value!r}",
            detail={field: str(value)},
        ) from None


def _as_date(value: object, field: str) -> date | None:
    """Read a date out of whatever the caller handed over.

    The HTTP schemas validate dates now, so this is for the callers that never
    go through them — tasks, scripts, and any service call that passes a dict.
    Parsing with ``fromisoformat`` inline turned a mistyped date into a bare
    ValueError, which the global error handler reports as a 500: the caller is
    told the server broke, when what they actually wrote was "tomorrow".
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        # datetime subclasses date, and the column wants the day.
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationException(
            message=f"{field} must be an ISO date (YYYY-MM-DD), got {value!r}",
            detail={field: str(value)},
        ) from exc


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

    _updatable = {"name", "address", "capacity", "contact_person", "contact_phone", "notes", "status"}
    for key, value in data.items():
        if key in _updatable:
            setattr(wh, key, value)

    await db.commit()
    await db.refresh(wh)
    return wh


async def delete_warehouse(db: AsyncSession, wh_id: str) -> dict:
    """Soft-delete a warehouse (sets is_deleted and deleted_at)."""
    from datetime import UTC, datetime
    result = await db.execute(select(Warehouse).where(Warehouse.id == _to_uuid(wh_id)))
    wh = result.scalar_one_or_none()
    if not wh:
        raise NotFoundException(message=f"Warehouse {wh_id} not found")

    wh.is_deleted = True
    wh.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()
    await db.refresh(wh)
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
    ).with_for_update()
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


async def adjust_inventory(db: AsyncSession, data: dict, *, commit: bool = True) -> dict:
    """Adjust inventory quantity (positive=in, negative=out).

    Supports batch-level tracking: when adding stock (qty > 0) the caller
    may provide ``batch_no``, ``expiry_date``, and ``manufacturing_date``.
    When removing stock (qty < 0) the system picks the best batch
    automatically (FEFO first, then FIFO).

    Uses optimistic locking via the ``version`` column to prevent lost updates
    under concurrent access. Retries up to 3 times before raising ConflictException.

    ``commit=False`` leaves the write pending in the caller's transaction.  A
    multi-line receipt needs it: booking each line as its own transaction would
    let a failure on line 3 leave lines 1-2 landed while the receipt itself
    reported failure — inventory that no order accounts for.  With one commit at
    the end, either the whole receipt is in the books or none of it is.
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
    expiry_date = _as_date(data.get("expiry_date"), "expiry_date")
    manufacturing_date = _as_date(data.get("manufacturing_date"), "manufacturing_date")
    max_retries = 3
    committed = False

    for attempt in range(max_retries):
        now = _now()  # refresh timestamp per attempt
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
                current_version = inv.version or 0
                new_qty = Decimal(str(inv.quantity)) + qty
                # Optimistic lock: only update if version hasn't changed
                values = dict(
                    quantity=new_qty,
                    updated_at=now,
                    version=current_version + 1,
                )
                if expiry_date and not inv.expiry_date:
                    values["expiry_date"] = expiry_date
                if manufacturing_date and not inv.manufacturing_date:
                    values["manufacturing_date"] = manufacturing_date
                update_result = await db.execute(
                    Inventory.__table__.update()
                    .where(
                        Inventory.id == inv.id,
                        Inventory.version == current_version,
                    )
                    .values(**values)
                )
                if update_result.rowcount == 0:
                    # Version changed — another transaction modified this row, retry
                    await db.rollback()
                    continue
                await db.refresh(inv)
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
            current_version = inv.version or 0
            if inv.quantity + qty < Decimal("0"):
                await db.rollback()
                continue
            new_qty = Decimal(str(inv.quantity)) + qty  # qty is negative
            # Optimistic lock: only update if version hasn't changed
            update_result = await db.execute(
                Inventory.__table__.update()
                .where(
                    Inventory.id == inv.id,
                    Inventory.version == current_version,
                )
                .values(
                    quantity=new_qty,
                    updated_at=now,
                    version=current_version + 1,
                )
            )
            if update_result.rowcount == 0:
                # Version changed — re-pick batches on next iteration
                await db.rollback()
                continue
            await db.refresh(inv)

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

        if commit:
            try:
                await db.commit()
            except Exception:
                if attempt < max_retries - 1:
                    await db.rollback()
                    continue
                raise
        else:
            # flush(), not commit(): the write goes to the database but stays in
            # the caller's transaction.  It also makes the row SELECT-able —
            # the refresh() below reads a brand-new Inventory back, and a
            # never-flushed one is not in the session's persistent set.
            await db.flush()
        committed = True
        break

    # Every attempt can end in `continue`: the version check lost the race, or
    # the commit collided.  Falling through would return the *pre-adjustment*
    # quantity as if the adjustment had landed — a lost update the caller reads
    # as a success.
    if not committed:
        raise ConflictException(
            message=(
                f"Inventory for {sku_str} changed on every attempt; "
                "the adjustment was not applied"
            ),
            detail={"sku": sku_str, "attempts": max_retries},
        )

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
        if wh_id is None:
            # The field carried a warehouse *code* (_to_uuid returns None for
            # those).  Treat it as a code instead of answering "Missing
            # warehouse_id" to a request that did supply one.
            data = {**data, "source_warehouse_code": str(data["warehouse_id"])}

    if wh_id is None and data.get("source_warehouse_code"):
        wh_result = await db.execute(select(Warehouse).where(Warehouse.code == data["source_warehouse_code"]))
        wh_obj = wh_result.scalar_one_or_none()
        if not wh_obj:
            raise NotFoundException(message=f"Warehouse {data['source_warehouse_code']} not found")
        wh_id = wh_obj.id

    if wh_id is None:
        raise ValidationException(message="Missing warehouse_id or source_warehouse_code in count request")

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

    # Batch-fetch all SKUs upfront (avoids N+1)
    sku_strs = {item.get("sku", item.get("sku_code")) for item in results if item.get("sku") or item.get("sku_code")}
    sku_result = await db.execute(select(SKU).where(SKU.sku.in_(list(sku_strs))))
    sku_map = {s.sku: s for s in sku_result.scalars().all()}

    # Batch-fetch all existing inventory for this location (avoids N+1)
    sku_ids = [s.id for s in sku_map.values()]
    inv_result = await db.execute(
        select(Inventory).where(
            Inventory.warehouse_id == wh_id,
            Inventory.location_id == loc_id,
            Inventory.sku_id.in_(sku_ids),
        ).with_for_update()
    )
    inv_by_sku: dict[uuid.UUID, Inventory] = {inv.sku_id: inv for inv in inv_result.scalars().all()}

    for item in results:
        sku_str = item.get("sku", item.get("sku_code"))
        # `or` here would turn a counted zero into a missing quantity: counting
        # a SKU as 0 (盘亏 to nothing) is a valid result and has to reach the
        # comparison below as 0.
        actual_qty_raw = item.get("actual_qty")
        if actual_qty_raw is None:
            actual_qty_raw = item.get("actual_qty_count")
        if actual_qty_raw is None:
            raise ValidationException(
                message=f"Missing quantity field in count result for SKU {sku_str}"
            )
        actual_qty = Decimal(str(actual_qty_raw))

        sku_obj = sku_map.get(sku_str)
        if not sku_obj:
            sku_obj = SKU(id=uuid.uuid4(), sku=sku_str, name=sku_str)
            db.add(sku_obj)
            await db.flush()
            sku_map[sku_str] = sku_obj

        inv = inv_by_sku.get(sku_obj.id)

        system_qty = Decimal(str(inv.quantity)) if inv else Decimal(0)
        diff = actual_qty - system_qty

        if abs(diff) < Decimal("0.001"):
            continue

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
            # Signed the way ``StockInventoryLog`` documents the column
            # ("+ve = in, -ve = out").  ``abs(diff)`` wrote a positive number for
            # a 盘亏, so the ledger the API serves read as though every counted
            # loss had added stock; a ledger that mixes signs does not sum to the
            # shelf it is the audit trail of.
            quantity_change=diff,
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


async def _resolve_warehouse(db: AsyncSession, raw: object, *, field: str) -> Warehouse:
    """Find a warehouse by id *or* by code, naming the field that named it.

    Callers send both forms: the API's own ids, and the warehouse code the mobile
    screen types into its 源仓库 field.  ``_to_uuid`` answers None for a code, and
    every caller that used it as a lookup treated None as "the caller named no
    warehouse" and filed the record with a NULL — so the code a handheld sent was
    the code that silently disappeared.  Resolving here, a value that is neither
    an id nor a known code is refused by the field it arrived in.
    """
    value = str(raw).strip()
    as_id = _to_uuid(value)
    wh: Warehouse | None = None
    if as_id is not None:
        wh = await db.scalar(select(Warehouse).where(Warehouse.id == as_id))
    if wh is None:
        wh = await db.scalar(select(Warehouse).where(Warehouse.code == value))
    if wh is None:
        raise NotFoundException(
            message=f"{field} {value!r} is neither a warehouse id nor a known warehouse code",
        )
    return wh


async def create_transfer_order(db: AsyncSession, payload: TransferOrderCreate) -> dict:
    """Create a transfer order with line items.

    Both ends of a transfer are required, and both are warehouses.  This function
    used to read the source from ``data["source_location"]`` only, which had three
    consequences at once: the source that ``docs/functional-test-plan.md``
    documents (``source_warehouse_id``) was dropped and the order was filed with
    ``source_warehouse_id = NULL`` — a transfer with no origin, and no line
    recording where the goods came from; that same key, read as the last fallback
    for the *destination*, made an order whose destination is the warehouse its
    caller named as the source (an order that ships a warehouse's stock to
    itself); and a warehouse *code* — what the mobile screen sends — reached
    ``_to_uuid``, answered None, and produced the same silent NULL.

    Lines were read as ``item_data["sku"]`` and ``item_data["quantity"]``, so the
    documented body (lines named by ``sku_id``) raised KeyError inside the
    handler: 500 for a request that named a real product, and the same for a
    quantity written as ``"5x"``.

    ``location_from_id`` used to receive the source *warehouse* id.  It is a
    location column; the warehouse a line leaves from is
    ``TransferOrderLine.warehouse_id``, which is what is written now.
    """
    source = await _resolve_warehouse(db, payload.source_warehouse_id, field="source_warehouse_id")
    target = await _resolve_warehouse(db, payload.target_warehouse_id, field="target_warehouse_id")
    if source.id == target.id:
        raise ValidationException(
            message=f"source and target are the same warehouse ({source.code}) — a transfer "
                    "from a warehouse to itself moves nothing, and every later step of a "
                    "transfer (approve, ship, receive) would run on it",
        )

    # Generate transfer order code
    code = f"TO-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    transfer = TransferOrder(
        id=uuid.uuid4(),
        code=code,
        source_warehouse_id=source.id,
        target_warehouse_id=target.id,
        type=TransferItemType(payload.type),
        status=TransferStatus.DRAFT,
        ref_no=payload.ref_no,
        remarks=payload.remarks,
    )
    db.add(transfer)

    # Batch-fetch existing SKUs (avoids N+1)
    sku_strs = {line.sku for line in payload.lines if line.sku}
    sku_result = await db.execute(select(SKU).where(SKU.sku.in_(list(sku_strs))))
    sku_map = {s.sku: s for s in sku_result.scalars().all()}

    for index, line in enumerate(payload.lines):
        if line.sku and line.sku_id is not None:
            raise ValidationException(
                message=f"line {index} names a product twice — sku {line.sku} and "
                        f"sku_id {line.sku_id}. The two spellings of the documented body "
                        "are both accepted, on one line each, not on the same line",
            )
        if not line.sku and line.sku_id is None:
            raise ValidationException(
                message=f"line {index} names no product — a transfer line needs sku (a "
                        "product code) or sku_id (a SKU row id)",
            )

        if line.sku_id is not None:
            sku_obj = await db.get(SKU, line.sku_id)
            if sku_obj is None:
                raise ValidationException(
                    message=f"line {index}: sku_id {line.sku_id} is not a product in the "
                            "SKU catalog — register the SKU before transferring it",
                )
        else:
            # The mobile flow scans codes the catalog may not carry yet; the
            # precedent of creating the catalog row stands.
            sku_obj = sku_map.get(line.sku)
            if sku_obj is None:
                sku_obj = SKU(id=uuid.uuid4(), sku=line.sku, name=line.sku)
                db.add(sku_obj)
                await db.flush()
                sku_map[line.sku] = sku_obj

        db.add(TransferOrderLine(
            id=uuid.uuid4(),
            transfer_order_id=transfer.id,
            item_type=TransferItemType(payload.type),
            sku_id=sku_obj.id,
            warehouse_id=source.id,
            quantity=line.qty,
        ))

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
    """Record packing for a completed picking wave.

    Two keys name the wave: ``picking_wave_id`` is the key this service read,
    and ``wave_id`` is the key the 打包记录 screen in ``ShipmentList.vue``
    posts.  The screen had been posting the second one since it was written, so
    every 记录打包 click was ``data["picking_wave_id"]``, a KeyError and a 500 —
    a record the operator never saw created and never saw refused.  Both spellings
    are read here, and a body that names no wave is refused by the field that
    should have named it.
    """
    from src.wms.models import PackingRecord

    wave_id = data.get("picking_wave_id") or data.get("wave_id")
    if not wave_id:
        raise ValidationException(
            message="picking_wave_id is required — a packing record says which wave was packed",
            detail={"picking_wave_id": None},
        )
    wave_uuid = _to_uuid(wave_id)
    if wave_uuid is None:
        raise ValidationException(
            message=f"picking_wave_id {wave_id!r} is not a wave id — the wave is named by its uuid",
            detail={"picking_wave_id": str(wave_id)},
        )
    result = await db.execute(select(PickingWave).where(PickingWave.id == wave_uuid))
    wave = result.scalar_one_or_none()
    if not wave:
        raise NotFoundException(message=f"Picking wave {wave_id} not found")
    if wave.status != "completed":
        raise ValidationException(message=f"Only completed waves can be packed — wave {wave.code} is {wave.status}")

    box_count = _as_int(data.get("box_count", 1), field="box_count")
    if box_count < 1:
        raise ValidationException(
            message=f"box_count {box_count} is not a packing count — a wave packs at least one box",
            detail={"box_count": box_count},
        )

    record = PackingRecord(
        id=uuid.uuid4(),
        picking_wave_id=wave_uuid,
        packed_by=str(data.get("packed_by") or ""),
        box_count=box_count,
        notes=str(data.get("notes") or ""),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return model_to_dict(record)


# ── Shipping ────────────────────────────────────────────────────────────────

def _shipment_no() -> str:
    """A number for a shipment, generated the way ``create_order`` numbers orders."""
    return f"SHIP-{_now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"


async def create_shipment(db: AsyncSession, data: dict) -> dict:
    """Create one shipment per order the caller listed.

    The 新建发货单 dialog in ``ShipmentList.vue`` collects a warehouse and a
    textarea of order ids and posts ``{"warehouse_id": …, "order_ids": […]}``;
    this function read ``data["order_id"]``, so 提交 on that screen was a
    KeyError, a 500 and a 发货单创建失败 toast — the shipment was never created
    and the operator was never told the form's own list was the problem.  Both
    keys are read: ``order_ids`` for the screen, ``order_id`` for the callers
    that name one order.

    The ids are then checked against the orders table.  ``Shipment.order_id``
    is a NOT NULL FK into ``orders``, and inserting a uuid that is not an order
    is an FK violation the server answered with a 500 — under SQLite the FK is
    not enforced, so the suite had been filing shipments for orders that never
    existed, which is a handover sheet with nothing behind it.

    The result is one shape for one order and for many: ``{"count",
    "shipments"}``.  Returning the first shipment bare is what made a batch
    of order ids look like a single shipment in the response.
    """
    from src.oms.models import Order
    from src.wms.models import PackingRecord, Shipment, ShipmentStatus

    if not data.get("warehouse_id"):
        raise ValidationException(
            message="warehouse_id is required — a shipment leaves from a warehouse",
            detail={"warehouse_id": None},
        )
    wh = await _resolve_warehouse(db, data["warehouse_id"], field="warehouse_id")

    raw_ids = data.get("order_ids")
    if raw_ids in (None, [], {}):
        raw_ids = [data["order_id"]] if data.get("order_id") else []
    if isinstance(raw_ids, (str, uuid.UUID)):
        raw_ids = [raw_ids]  # noqa: RUF057 — a single id is the one-element list of it
    if not isinstance(raw_ids, (list, tuple)):
        raise ValidationException(
            message=f"order_ids must be a list of order ids, got {type(raw_ids).__name__}",
            detail={"order_ids": str(raw_ids)},
        )
    if not raw_ids:
        raise ValidationException(
            message="order_ids is required — a shipment carries orders out of the warehouse",
            detail={"order_ids": []},
        )

    order_ids: list[uuid.UUID] = []
    for raw in raw_ids:
        oid = _to_uuid(raw)
        if oid is None:
            raise ValidationException(
                message=f"order_ids contains {raw!r}, which is not an order id",
                detail={"order_ids": str(raw)},
            )
        if oid not in order_ids:
            order_ids.append(oid)

    found = set(
        (await db.execute(select(Order.id).where(Order.id.in_(order_ids)))).scalars().all()
    )
    missing = [str(oid) for oid in order_ids if oid not in found]
    if missing:
        raise NotFoundException(
            message=f"Order {', '.join(missing)} not found — a shipment cannot carry an order that does not exist",
            detail={"order_ids": missing},
        )

    pack_id: uuid.UUID | None = None
    if data.get("packing_record_id"):
        pack_id = _to_uuid(data["packing_record_id"])
        if pack_id is None:  # noqa: RUF019 — keep the raw value in the message
            raise ValidationException(
                message=f"packing_record_id {data['packing_record_id']!r} is not an id",
                detail={"packing_record_id": str(data["packing_record_id"])},
            )
        if await db.scalar(select(PackingRecord).where(PackingRecord.id == pack_id)) is None:
            raise NotFoundException(
                message=f"Packing record {data['packing_record_id']} not found — pack the wave before shipping it",
            )

    created: list[Shipment] = []
    for oid in order_ids:
        shipment = Shipment(
            id=uuid.uuid4(),
            shipment_no=_shipment_no(),
            order_id=oid,
            warehouse_id=wh.id,
            packing_record_id=pack_id,
            tracking_number=str(data.get("tracking_number") or ""),
            carrier=str(data.get("carrier") or ""),
            status=ShipmentStatus.PACKED if pack_id else ShipmentStatus.PICKED,
            notes=str(data.get("notes") or ""),
        )
        db.add(shipment)
        created.append(shipment)
    await db.commit()

    shipments = []
    for shipment in created:
        await db.refresh(shipment)
        shipments.append(model_to_dict(shipment))
    return {"count": len(shipments), "shipments": shipments}


async def mark_shipped(db: AsyncSession, shipment_id: str, tracking_number: str = "", carrier: str = "") -> dict:
    """Mark a shipment as shipped with tracking info.

    The 发货 button on the list posts no body at all, so the handover the
    carrier signs for is recorded by the 标记发货 screen that has the tracking
    number, and this keeps whatever the shipment already carried.  Statuses
    that do not leave the warehouse again — shipped, delivered, cancelled —
    are refused: a second click on 发货 used to stamp a fresh ``shipped_at``
    on a shipment that had already gone out, and a cancelled shipment used to
    ship as happily as any other.
    """
    from src.wms.models import Shipment, ShipmentStatus

    result = await db.execute(select(Shipment).where(Shipment.id == _to_uuid(shipment_id)))
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise NotFoundException(message=f"Shipment {shipment_id} not found")

    if shipment.status in (ShipmentStatus.SHIPPED, ShipmentStatus.DELIVERED):
        raise ValidationException(
            message=(
                f"Shipment {shipment.shipment_no or shipment_id} is already {shipment.status} — "
                "shipping it again would record a second handover"
            ),
        )
    if shipment.status == ShipmentStatus.CANCELLED:
        raise ValidationException(
            message=(
                f"Shipment {shipment.shipment_no or shipment_id} is cancelled — "
                "a cancelled shipment does not leave the warehouse"
            ),
        )

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


#: A receipt is legal only for an order the vendor has actually been given
#: ("approved") or that has partly landed ("partial").  "draft" has not been
#: ordered yet; "received" is already closed out.
PO_RECEIVABLE_STATUSES: tuple[str, ...] = ("approved", "partial")

#: ``status="pending"`` is what clients have always sent for "waiting to be
#: received".  It is not a status this table stores, so filtering on it used to
#: match nothing and the receiving screen reported an empty day.
_LEGACY_STATUS_ALIASES: dict[str, tuple[str, ...]] = {"pending": PO_RECEIVABLE_STATUSES}


async def _load_po(db: AsyncSession, po_id: str) -> PurchaseOrder:
    """Load a PO by id, or by ``po_number`` when the caller holds a document number.

    ``_to_uuid`` returns None for a non-UUID string, which compared the id
    column against NULL: a scanned PO number came back as "PurchaseOrder
    PO-2026-001 not found", a lookup failure dressed up as a missing order.
    """
    po_uuid = _to_uuid(po_id)
    if po_uuid is not None:
        result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_uuid))
    else:
        result = await db.execute(
            select(PurchaseOrder).where(PurchaseOrder.po_number == str(po_id))
        )
    po = result.scalar_one_or_none()
    if not po:
        raise NotFoundException(message=f"PurchaseOrder {po_id} not found")
    return po


async def _po_lines(db: AsyncSession, po: PurchaseOrder) -> list[dict]:
    """This PO's lines with their SKU codes attached.

    The response had no lines at all.  A receiving screen given a PO without
    lines has nothing to enter quantities against, so it showed an empty order
    and still let the operator confirm a receipt for goods they could not list.
    """
    rows = (
        await db.execute(
            select(PurchaseOrderLine, SKU.sku)
            .outerjoin(SKU, SKU.id == PurchaseOrderLine.sku_id)
            .where(PurchaseOrderLine.purchase_order_id == po.id)
            # purchase_order_lines has no timestamps, so there is no ordering
            # that means anything beyond "stable" — which is what the PDA needs
            # to keep a scanned order matched to the same row between screens.
            .order_by(PurchaseOrderLine.id)
        )
    ).all()
    return [{**model_to_dict(line), "sku": sku_code} for line, sku_code in rows]


async def _po_payload(db: AsyncSession, po: PurchaseOrder) -> dict:
    payload = model_to_dict(po)
    payload["lines"] = await _po_lines(db, po)
    return payload


async def create_purchase_order(db: AsyncSession, data: dict) -> dict:
    expected_date = _as_date(data.get("expected_date"), "expected_date")

    po = PurchaseOrder(
        id=uuid.uuid4(),
        po_number=data["po_number"],
        vendor_id=_to_uuid(data.get("vendor_id")) if data.get("vendor_id") else None,
        expected_date=expected_date,
        notes=data.get("notes", ""),
    )
    db.add(po)
    await db.flush()

    total = Decimal("0")
    for line_data in data.get("lines", []):
        sku_id = _to_uuid(line_data.get("sku_id")) if line_data.get("sku_id") else None
        if sku_id is None and line_data.get("sku"):
            # A PDA knows the code it scanned, not the SKU's primary key.
            sku_obj = await _get_or_create_sku(db, str(line_data["sku"]))
            sku_id = sku_obj.id
        if sku_id is None and not line_data.get("description"):
            raise ValidationException(
                message=(
                    "A purchase order line needs sku_id, sku, or a description; "
                    "an unidentifiable line cannot be received or invoiced"
                )
            )

        line = PurchaseOrderLine(
            id=uuid.uuid4(),
            purchase_order_id=po.id,
            sku_id=sku_id,
            description=line_data.get("description", ""),
            quantity=Decimal(str(line_data.get("quantity", 1))),
            unit_price=Decimal(str(line_data.get("unit_price", 0))),
        )
        db.add(line)
        total += line.quantity * line.unit_price

    po.total_amount = total
    await db.commit()
    await db.refresh(po)
    return await _po_payload(db, po)


async def get_purchase_order(db: AsyncSession, po_id: str) -> dict:
    po = await _load_po(db, po_id)
    return await _po_payload(db, po)


async def list_purchase_orders(
    db: AsyncSession,
    page: int | None = None,
    page_size: int | None = None,
    status: str | None = None,
) -> list[dict] | dict:
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())
    if status:
        statuses = _LEGACY_STATUS_ALIASES.get(status, (status,))
        stmt = stmt.where(PurchaseOrder.status.in_(statuses))

    if page is not None and page_size is not None:
        result = await paginate(stmt, db, page=page, page_size=page_size)
        return {
            "items": [await _po_payload(db, po) for po in result.items],
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "total_pages": result.total_pages,
        }
    result = await db.execute(stmt)
    return [await _po_payload(db, po) for po in result.scalars().all()]


async def approve_purchase_order(db: AsyncSession, po_id: str) -> dict:
    po = await _load_po(db, po_id)
    if po.status != "draft":
        raise ValidationException(message=f"Cannot approve PO in '{po.status}' state")
    po.status = "approved"
    await db.commit()
    await db.refresh(po)
    return await _po_payload(db, po)


async def receive_goods(db: AsyncSession, po_id: str, data: dict | None = None) -> dict:
    """Book what physically arrived against a purchase order.

    This used to be ``po.status = "received"; commit()``.  Nothing was added to
    inventory and no quantity was recorded anywhere: a PO for 100 units against
    a delivery of 3 looked identical to a complete delivery, and the 3 units
    that were in the building were invisible to every later pick.

    ``data`` carries the destination (``warehouse_id``/``location_id``) and the
    per-line landed quantities.  With no ``lines`` given, the outstanding
    balance of every line is received — the old "receive the whole order"
    meaning, now with the quantities attached.
    """
    data = data or {}
    po = await _load_po(db, po_id)
    if po.status not in PO_RECEIVABLE_STATUSES:
        raise ValidationException(
            message=(
                f"Cannot receive goods for PO in '{po.status}' state "
                f"(expected {' or '.join(PO_RECEIVABLE_STATUSES)})"
            )
        )

    lines = await _po_lines(db, po)
    if not lines:
        # An order with nothing on it cannot be received.  Saying so is the
        # point: create_purchase_order() used to drop the request's lines, so
        # every PO created through the API was empty and every receipt of it
        # was a status flip over an empty order.
        raise ValidationException(message=f"PO {po.po_number} has no lines to receive")

    wh_id = _to_uuid(data.get("warehouse_id"))
    loc_id = _to_uuid(data.get("location_id"))
    if wh_id is None:
        raise ValidationException(
            message=(
                "Receiving needs a warehouse_id: the goods have to land somewhere. "
                f"Got {data.get('warehouse_id')!r}"
            )
        )
    if loc_id is None:
        raise ValidationException(
            message=(
                "Receiving needs a location_id: stock is keyed by location, so a "
                f"receipt without one cannot be booked. Got {data.get('location_id')!r}"
            )
        )

    # Checked before anything is written, so a mistyped destination cannot leave
    # part of the order booked.
    location = (
        await db.execute(select(Location).where(Location.id == loc_id))
    ).scalar_one_or_none()
    if not location:
        raise NotFoundException(message=f"Location {loc_id} not found")
    if location.warehouse_id != wh_id:
        # adjust_inventory() only checks that both ids exist, which would have
        # booked the delivery into another warehouse's shelf.
        raise ValidationException(
            message=(
                f"Location {location.code} belongs to warehouse {location.warehouse_id}, "
                f"not {wh_id}"
            ),
            detail={"location_id": str(loc_id), "location_warehouse_id": str(location.warehouse_id)},
        )
    warehouse = (
        await db.execute(select(Warehouse).where(Warehouse.id == wh_id))
    ).scalar_one_or_none()
    if not warehouse:
        raise NotFoundException(message=f"Warehouse {wh_id} not found")

    by_id = {str(line["id"]): line for line in lines}
    by_sku: dict[str, list[dict]] = {}
    for line in lines:
        if line["sku"]:
            by_sku.setdefault(str(line["sku"]).lower(), []).append(line)

    requested = data.get("lines")
    plan: list[tuple[dict, Decimal, dict]] = []

    if requested is None:
        for line in lines:
            outstanding = Decimal(str(line["quantity"])) - Decimal(str(line["received_qty"] or 0))
            if outstanding > 0:
                plan.append((line, outstanding, {}))
    else:
        for item in requested:
            qty = Decimal(str(item.get("received_qty", 0)))
            if qty < 0:
                raise ValidationException(
                    message=(
                        f"received_qty cannot be negative (got {qty}) "
                        f"for line {item.get('line_id') or item.get('sku')}"
                    )
                )
            if qty == 0:
                continue

            line: dict | None = None
            if item.get("line_id"):
                line = by_id.get(str(item["line_id"]))
                if line is None:
                    # Accepting a foreign line would book this delivery against
                    # somebody else's order.
                    raise ValidationException(
                        message=f"Line {item['line_id']} is not part of PO {po.po_number}"
                    )
            elif item.get("sku"):
                matches = by_sku.get(str(item["sku"]).lower(), [])
                if not matches:
                    raise ValidationException(
                        message=f"SKU {item['sku']} is not on PO {po.po_number}"
                    )
                if len(matches) > 1:
                    raise ValidationException(
                        message=(
                            f"PO {po.po_number} has {len(matches)} lines for SKU {item['sku']}; "
                            "send line_id so the receipt books the right one"
                        ),
                        detail={"sku": item["sku"], "line_ids": [m["id"] for m in matches]},
                    )
                line = matches[0]
            else:
                raise ValidationException(message="A received line needs line_id or sku")

            if not line["sku"]:
                raise ValidationException(
                    message=(
                        f"Line {line['id']} has no SKU, so there is no inventory row to "
                        "receive it into; give the line a sku_id or sku before receiving it"
                    )
                )
            plan.append((line, qty, item))

    if not plan:
        raise ValidationException(
            message=(
                "Nothing was received (every line was zero): the PO stays as it is. "
                "A delivery of nothing is not a receipt."
            )
        )

    # adjust_inventory() rolls the session back and retries when another
    # transaction moved the inventory row underneath it.  In a multi-line
    # receipt that rollback also throws away the lines already booked, so the
    # receipt cannot quietly carry on with half its bookkeeping gone: if the
    # transaction changes mid-receipt, the whole receipt is reported as a
    # conflict and nothing is committed.  The caller re-reads and retries.
    po_number = str(po.po_number)  # read now: a rollback expires the ORM object
    tx_before = db.get_transaction()

    now = _now()
    for line, qty, item in plan:
        # The line and the stock land in one transaction (commit=False on the
        # adjustment, committed once below): booking the delivery while the
        # ordered line still says "0 received" leaves inventory no order
        # accounts for, and a replay of the same receipt would book it twice.
        await db.execute(
            PurchaseOrderLine.__table__.update()
            .where(PurchaseOrderLine.id == _to_uuid(line["id"]))
            .values(
                received_qty=Decimal(str(line["received_qty"] or 0)) + qty,
                received_at=now,
            )
        )
        await adjust_inventory(
            db,
            {
                "warehouse_id": str(wh_id),
                "location_id": str(loc_id),
                "sku": line["sku"],
                "quantity": qty,
                # The batch the delivery note names; without it the received
                # units merge into "DEFAULT" and the dated batch never expires.
                # The receipt's own audit trail is the line's received_qty /
                # received_at: StockMovement's type enum has no RECEIPT member,
                # so its movement row reads as a movement into the location.
                "batch_no": item.get("batch_no") or "DEFAULT",
                "expiry_date": item.get("expiry_date"),
                "manufacturing_date": item.get("manufacturing_date"),
            },
            commit=False,
        )

        if db.get_transaction() is not tx_before:
            raise ConflictException(
                message=(
                    f"Stock changed while receiving {po_number}; this receipt was "
                    "not applied. Re-read the order and receive it again."
                ),
                detail={"po_number": po_number, "sku": line["sku"]},
            )

    landed = await _po_lines(db, po)
    complete = all(
        Decimal(str(line["received_qty"] or 0)) >= Decimal(str(line["quantity"]))
        for line in landed
    )
    po.status = "received" if complete else "partial"

    await db.commit()
    await db.refresh(po)
    return await _po_payload(db, po)


# ── Invoice CRUD ───────────────────────────────────────────────────────


async def _lines_by_parent(
    db: AsyncSession,
    line_model,
    parent_field: str,
    parent_ids: list,
) -> dict[str, list[dict]]:
    """Child rows for several parents, in one query, keyed by parent id.

    Read through the ORM relationship instead and the async session lazy-loads
    from another greenlet and raises; read per parent and a list endpoint turns
    into one query per invoice.
    """
    ids = [i for i in parent_ids if i is not None]
    if not ids:
        return {}
    result = await db.execute(select(line_model).where(getattr(line_model, parent_field).in_(ids)))
    grouped: dict[str, list[dict]] = {}
    for line in result.scalars().all():
        payload = model_to_dict(line)
        grouped.setdefault(str(payload[parent_field]), []).append(payload)
    return grouped


async def _invoice_payload(db: AsyncSession, inv: Invoice) -> dict:
    payload = model_to_dict(inv)
    lines = await _lines_by_parent(db, InvoiceLine, "invoice_id", [inv.id])
    payload["lines"] = lines.get(str(inv.id), [])
    return payload


async def create_invoice(db: AsyncSession, data: dict) -> dict:
    inv = Invoice(
        id=uuid.uuid4(),
        invoice_number=data["invoice_number"],
        entity_type=data["entity_type"],
        entity_id=_to_uuid(data.get("entity_id")) if data.get("entity_id") else None,
        issue_date=_as_date(data.get("issue_date"), "issue_date"),
        due_date=_as_date(data.get("due_date"), "due_date"),
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

    # The total is a fact about the lines, not a number somebody types: an
    # invoice whose amount disagrees with what is on it is a document two
    # departments will spend a week reconciling.
    inv.total_amount = total
    await db.commit()
    await db.refresh(inv)
    return await _invoice_payload(db, inv)


async def get_invoice(db: AsyncSession, invoice_id: str) -> dict:
    result = await db.execute(select(Invoice).where(Invoice.id == _to_uuid(invoice_id)))
    inv = result.scalar_one_or_none()
    if not inv:
        raise NotFoundException(message=f"Invoice {invoice_id} not found")
    return await _invoice_payload(db, inv)


async def list_invoices(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(Invoice).order_by(Invoice.created_at.desc()))
    invoices = list(result.scalars().all())
    lines = await _lines_by_parent(db, InvoiceLine, "invoice_id", [inv.id for inv in invoices])
    out = []
    for inv in invoices:
        payload = model_to_dict(inv)
        payload["lines"] = lines.get(str(inv.id), [])
        out.append(payload)
    return out


# ── CreditMemo CRUD ─────────────────────────────────────────────────────


async def _credit_memo_payload(db: AsyncSession, cm: CreditMemo) -> dict:
    payload = model_to_dict(cm)
    lines = await _lines_by_parent(db, CreditMemoLine, "credit_memo_id", [cm.id])
    payload["lines"] = lines.get(str(cm.id), [])
    return payload


async def create_credit_memo(db: AsyncSession, data: dict) -> dict:
    raw_invoice_id = data.get("invoice_id")
    invoice_id = _to_uuid(raw_invoice_id) if raw_invoice_id else None
    # _to_uuid() answers None for anything it cannot parse.  Without this check
    # a memo written against a mistyped invoice id becomes a memo against
    # nothing, and the refund can no longer be traced back to the document it
    # was issued for.
    if raw_invoice_id and invoice_id is None:
        raise ValidationException(
            message=f"invoice_id is not a valid invoice reference: {raw_invoice_id!r}",
            detail={"invoice_id": str(raw_invoice_id)},
        )
    if invoice_id is not None:
        found = await db.execute(select(Invoice.id).where(Invoice.id == invoice_id))
        if found.scalar_one_or_none() is None:
            raise NotFoundException(
                message=f"Invoice {raw_invoice_id} not found: this credit memo would correct nothing",
                detail={"invoice_id": str(raw_invoice_id)},
            )

    cm = CreditMemo(
        id=uuid.uuid4(),
        credit_memo_number=data["credit_memo_number"],
        invoice_id=invoice_id,
        entity_type=data["entity_type"],
        entity_id=_to_uuid(data.get("entity_id")) if data.get("entity_id") else None,
        issue_date=_as_date(data.get("issue_date"), "issue_date"),
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
    return await _credit_memo_payload(db, cm)


async def get_credit_memo(db: AsyncSession, cm_id: str) -> dict:
    result = await db.execute(select(CreditMemo).where(CreditMemo.id == _to_uuid(cm_id)))
    cm = result.scalar_one_or_none()
    if not cm:
        raise NotFoundException(message=f"CreditMemo {cm_id} not found")
    return await _credit_memo_payload(db, cm)


async def list_credit_memos(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(CreditMemo).order_by(CreditMemo.created_at.desc()))
    memos = list(result.scalars().all())
    lines = await _lines_by_parent(db, CreditMemoLine, "credit_memo_id", [cm.id for cm in memos])
    out = []
    for cm in memos:
        payload = model_to_dict(cm)
        payload["lines"] = lines.get(str(cm.id), [])
        out.append(payload)
    return out


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
    if wh.status != WarehouseStatus.ACTIVE:
        raise ValidationException(message=f"Warehouse {wh.code} is inactive (status={wh.status})")

    # 2. 解析入库项数据
    sku_str = data["sku"]
    qty = Decimal(str(data["quantity"]))
    batch_no = data.get("batch_no", "DEFAULT")
    expiry_date = _as_date(data.get("expiry_date"), "expiry_date")
    manufacturing_date = _as_date(data.get("manufacturing_date"), "manufacturing_date")

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
            quantity_before=float(inv.quantity) - float(qty) if inv else 0.0,
            quantity_after=float(inv.quantity),
            reference_type="stock_in",
            reference_id=inv.id,
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
            quantity_before=float(inv.quantity) - float(qty) if inv else 0.0,
            quantity_after=float(inv.quantity),
            reference_type="stock_out",
            reference_id=inv.id,
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
    if wh.status != WarehouseStatus.ACTIVE:
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
    # FOR UPDATE：并发出库必须串行扣同一批库存行，否则两个请求都通过
    # "库存充足"检查、双双扣减 → 超卖（PostgreSQL 行锁；SQLite 自动忽略）。
    inv_result = await db.execute(
        select(Inventory).where(
            Inventory.warehouse_id == wh_id,
            Inventory.sku_id == sku.id,
            Inventory.quantity > 0,
        ).with_for_update()
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

    # Record initial quantities before deduction
    initial_qty = float(batches[0]["inv"].quantity) if batches else 0

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
        quantity_before=initial_qty,
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

