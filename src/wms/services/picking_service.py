"""Warehouse Picking Service — FEFO (First-Expired-First-Out) logic.

Core picking operations:
* ``pick_from_stock`` – locate inventory and decrement quantities in the correct order
* ``assign_pick_task`` – create a PickTask for warehouse staff
* ``complete_pick`` – update status and log the pick event
* ``auto_replenish`` – trigger replenishment when stock drops below min_qty

All operations are transactional within an AsyncSession.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.exceptions import NotFoundException, ValidationException
from src.models.base import model_to_dict
from src.wms.models import (
    SKU,
    Inventory,
    InventoryChangeType,
    InventoryLog,
    Location,
    LocationStatus,
    PickingWave,
    PickingWavePriority,
    PickingWaveType,
    StockMovement,
    StockMovementType,
)

# ── FEFO Picking ───────────────────────────────────────────────────────────────

async def pick_from_stock(
    db: AsyncSession,
    warehouse_id: str,
    sku: str,
    quantity: int,
    location_id: str | None = None,
) -> dict:
    """Pick items from stock using FEFO (first-expired-first-out).

    Loads *all* inventory rows for the SKU at the warehouse and orders them by
    ``expiry_date ASC NULLS LAST`` so that batches expiring soonest are picked first.
    Then decrements each batch's quantity until the requested amount is fulfilled.

    Returns a dict with:
      - ``picked_batchs`` – list of {batch_no, sku_name, qty} dicts in pick order
      - ``remaining_quantity`` – how much was *not* fulfilled (0 if complete)
    """
    warehouse_uuid = _to_uuid(warehouse_id)

    # Load all inventory for this SKU + warehouse
    result = await db.execute(
        select(Inventory)
        .where(
            Inventory.warehouse_id == warehouse_uuid,
            Inventory.sku.has(SKU.sku == sku),  # type: ignore[arg-type]
            Inventory.is_deleted.is_(False),
        )
        .options(selectinload(Inventory.sku))
        .with_for_update()
        .order_by(
            Inventory.expiry_date.asc().nulls_last(),  # FEFO: oldest expiry first
            Inventory.batch_no,                        # stable tie-breaker
        )
    )
    batches = result.scalars().all()

    if not batches:
        raise NotFoundException(message=f"No inventory found for SKU {sku} at warehouse {warehouse_id}")

    # Calculate available (quantity - locked_qty) and pick in FEFO order
    picked_batches: list[dict[str, Any]] = []
    remaining = quantity

    for inv in batches:
        if remaining <= 0:
            break

        available = max(Decimal("0"), inv.quantity - (inv.locked_qty or Decimal("0")))
        pick_qty = min(remaining, available)
        pick_int = int(pick_qty)

        if pick_int <= 0:
            continue

        # Update inventory quantity
        new_quantity = inv.quantity - pick_int
        inv.quantity = new_quantity
        inv.version += 1

        # Log the outbound change
        log = InventoryLog(
            id=uuid.uuid4(),
            inventory_id=inv.id,
            change_type=InventoryChangeType.OUTBOUND,
            quantity_change=-pick_int,
            quantity_before=inv.quantity + pick_int,
            quantity_after=new_quantity,
            reference_type="picking",
            reference_id=None,  # set after commit if we have a task id
        )
        db.add(log)

        sku_name = inv.sku.name or ""
        picked_batches.append({
            "batch_no": str(inv.batch_no),
            "sku_name": sku_name,
            "expiry_date": inv.expiry_date.isoformat() if inv.expiry_date else None,
            "qty": pick_int,
        })

        remaining -= pick_int

    await db.commit()

    return {
        "picked_batches": picked_batches,
        "remaining_quantity": remaining,  # >0 means we couldn't fulfill fully
    }


async def consume_stock_for_shipment(
    db: AsyncSession,
    *,
    warehouse_id: str,
    lines: list[dict],
    stock_out_id: str,
    operator_id: uuid.UUID | None = None,
) -> list[dict]:
    """Deduct a stock-out shipment from the shelf, batch by batch, and log each batch.

    A ``StockOut`` document used to be pure paper: ``POST /stock-out`` created
    the document and its lines, ``PUT …/status {status: SHIPPED}`` flipped the
    status, and between them not one ``Inventory.quantity`` moved and not one
    ``InventoryLog`` row was written.  The shelf and the shipment ledger
    therefore describe two different warehouses, and the audit trail of a
    shipment was the document, which is not a record of stock.

    FEFO ordering is the same one :func:`pick_from_stock` uses — soonest-expiry
    batch first — so a shipment leaves the stock that has to leave first, and
    each batch it touches gets its own ``InventoryLog`` row naming this shipment
    (``reference_type="stock_out"``, ``reference_id=<stock out id>``) with the
    before/after quantities.  One ``StockInventoryLog`` row per shipment line
    records the movement in the ledger ``GET /api/v1/inventory-log`` serves.

    Quantities are Decimals: :func:`pick_from_stock` narrows the pick to
    ``int(pick_qty)``, which is fine for whole-unit picking tasks and would
    silently drop the fraction of a 2.5 kg line.

    This function never commits.  The route that ships a document owns the
    transaction, so the inventory movement, its audit rows, and the document's
    SHIPPED status are one fact: a shipment that cannot be honoured on the shelf
    leaves no half-deducted stock and no status change behind.
    """
    from src.models.wms import StockInventoryLog

    warehouse_uuid = _to_uuid(warehouse_id)
    stock_out_uuid = _to_uuid(stock_out_id)
    movements: list[dict] = []

    for index, line in enumerate(lines):
        sku_code = str(line.get("sku") or "").strip()
        if not sku_code:
            raise ValidationException(
                message=f"line {index} has no sku — a shipment line with no product "
                        "cannot be deducted from any batch",
            )
        requested = Decimal(str(line.get("qty") or 0))
        if requested <= 0:
            raise ValidationException(
                message=f"line {index} ({sku_code}) requests {requested}; a shipment line "
                        "must request a positive quantity",
            )

        sku_result = await db.execute(select(SKU).where(SKU.sku == sku_code))
        sku_obj = sku_result.scalar_one_or_none()
        if sku_obj is None:
            raise ValidationException(
                message=f"SKU {sku_code} is not in the SKU catalog, so shipment "
                        f"{stock_out_id} has no stock to deduct from — register the SKU "
                        "and receive the goods before shipping them",
            )

        batch_result = await db.execute(
            select(Inventory)
            .where(
                Inventory.warehouse_id == warehouse_uuid,
                Inventory.sku_id == sku_obj.id,
                Inventory.is_deleted.is_(False),
                Inventory.quantity > 0,
            )
            .with_for_update(skip_locked=True)
            .order_by(
                Inventory.expiry_date.asc().nulls_last(),
                Inventory.received_at.asc().nulls_last(),
                Inventory.batch_no,
            )
        )
        batches = list(batch_result.scalars().all())
        on_hand = sum(
            (Decimal(str(b.quantity)) - Decimal(str(b.locked_qty or 0)) for b in batches),
            Decimal("0"),
        )
        if on_hand < requested:
            raise ValidationException(
                message=f"cannot ship {requested} of {sku_code}: warehouse has {on_hand} "
                        f"available (stock_out {stock_out_id})",
            )

        remaining = requested
        for inv in batches:
            if remaining <= 0:
                break
            available = Decimal(str(inv.quantity)) - Decimal(str(inv.locked_qty or 0))
            take = min(remaining, available)
            if take <= 0:
                continue
            before = Decimal(str(inv.quantity))
            inv.quantity = before - take
            inv.version = (inv.version or 0) + 1
            db.add(InventoryLog(
                id=uuid.uuid4(),
                inventory_id=inv.id,
                change_type=InventoryChangeType.OUTBOUND,
                quantity_change=-take,
                quantity_before=before,
                quantity_after=inv.quantity,
                reference_type="stock_out",
                reference_id=stock_out_uuid,
                remark=f"stock_out {stock_out_id}: {take} of {sku_code} left batch {inv.batch_no}",
            ))
            movements.append({
                "sku": sku_code,
                "batch_no": inv.batch_no,
                "qty": str(take),
                "inventory_id": str(inv.id),
            })
            remaining -= take

        db.add(StockInventoryLog(
            id=uuid.uuid4(),
            warehouse_id=warehouse_uuid,
            sku=sku_code,
            type="OUTBOUND",
            reference_type="stock_out",
            reference_id=stock_out_uuid,
            # Signed the way the column is documented ("+ve = in, -ve = out"), so
            # the ledger the API serves sums to the stock that is on the shelf.
            quantity_change=-requested,
            operator_id=operator_id,
            remark=f"shipped {requested} of {sku_code}",
        ))

    await db.flush()
    return movements


# ── Pick Task Management ───────────────────────────────────────────────────────

async def assign_pick_task(
    db: AsyncSession,
    warehouse_id: str,
    stop_ids: list[str],
) -> dict:
    """Create a PickingWave that groups all orders passing through the given stops.

    Used by dispatch planners to assign a wave of order-picking work to a single
    picker or team.  Returns the created wave + its pick task summary.
    """
    warehouse_uuid = _to_uuid(warehouse_id)

    # Verify stops exist and are active
    loc_uuids = [uuid.UUID(sid) for sid in stop_ids]
    result = await db.execute(select(Location).where(Location.id.in_(loc_uuids)))
    locs = {str(loc.id): loc for loc in result.scalars().all()}
    for sid, luuid in zip(stop_ids, loc_uuids):
        loc = locs.get(sid)
        if not loc or loc.status != LocationStatus.ACTIVE:
            raise ValidationException(message=f"Location {sid} is invalid")

    wave_code = f"PW-{datetime.now(UTC):%Y%m%d%H%M%S}"
    wave = PickingWave(
        id=uuid.uuid4(),
        warehouse_id=warehouse_uuid,
        code=wave_code,
        status="pending",
        wave_type=PickingWaveType.ORDER_BASED,
        priority=PickingWavePriority.HIGH,
    )
    db.add(wave)
    await db.flush()

    # (In a real system we'd link orders to the wave here via order→stop mapping)
    return model_to_dict(wave)


async def complete_pick(
    db: AsyncSession,
    pick_task_id: str,
    actual_quantity: int | None = None,
    notes: str = "",
) -> dict:
    """Mark a PickTask as completed and log any discrepancies.

    After completion the picked items are transferred to the picking location
    so they can be packed and shipped.
    """
    # Load wave (or task if we had PickTask model) — for now just validate
    result = await db.execute(select(PickingWave).where(PickingWave.id == uuid.UUID(pick_task_id)))
    wave = result.scalar_one_or_none()
    if not wave:
        raise NotFoundException(message=f"Picking wave {pick_task_id} not found")

    wave.status = "completed"
    wave.completed_items = actual_quantity or (wave.total_items or 0)
    await db.commit()
    return model_to_dict(wave)


# ── Auto Replenishment ────────────────────────────────────────────────────────

async def auto_replenish(
    db: AsyncSession,
    warehouse_id: str,
    threshold_pct: float = 0.2,
) -> dict:
    """Scan inventory for items below ``min_qty`` and create replenishment movements.

    *threshold_pct* controls how aggressively to replenish (default 20 % of max qty).

    Returns a dict with "replenishments_created" count and list of new StockMovements.
    """
    warehouse_uuid = _to_uuid(warehouse_id)

    result = await db.execute(
        select(Inventory)
        .where(
            Inventory.warehouse_id == warehouse_uuid,
            Inventory.is_deleted.is_(False),
        )
        .options(selectinload(Inventory.sku))  # type: ignore[arg-type]
    )
    items = result.scalars().all()

    replenishments: list[dict[str, Any]] = []

    for inv in items:
        if not inv.max_qty or inv.quantity >= (inv.min_qty or Decimal("0")):
            continue

        # Calculate how much to bring it up to 80% of max
        target_qty = inv.max_qty * Decimal(str(1 - threshold_pct))
        needed = int(target_qty - inv.quantity)
        if needed <= 0:
            continue

        movement = StockMovement(
            id=uuid.uuid4(),
            source_warehouse_id=warehouse_uuid,
            sku_id=inv.sku_id,
            gtin=inv.gtin or "",
            quantity=Decimal(str(needed)),
            movement_type=StockMovementType.REPLENISHMENT,
            status="pending",
        )
        db.add(movement)
        replenishments.append(model_to_dict(movement))

    await db.commit()
    return {"replenishments_created": len(replenishments), "movements": replenishments}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_uuid(v: str) -> uuid.UUID:
    """Coerce a string (or UUID-like) to ``uuid.UUID``."""
    if isinstance(v, uuid.UUID):
        return v
    return uuid.UUID(str(v))
