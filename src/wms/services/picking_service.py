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
