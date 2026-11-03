"""Stock In / Out / Inventory Log / Adjust Stock API endpoints.

Every write endpoint here used to declare ``req: dict`` and read it as
``req.get("data", {})``.  That shape is the reason four separate defects lived
in this file at once — a missing field was a KeyError (500), an update accepted
whichever columns the client named, a mistyped quantity key was reported as a
missing key, and an adjustment never recorded who made it.  The bodies are typed
now (``src/wms/schemas.py``); the rules each endpoint enforces are documented
where the endpoint is.
"""
import uuid as _uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.exceptions import NotFoundException, ValidationException
from src.models.base import model_to_dict
from src.models.wms import (
    StockIn,
    StockInLine,
    StockInventoryLog,
    StockOut,
    StockOutLine,
)
from src.wms.models import SKU, Inventory
from src.wms.schemas import (
    AdjustStockRequest,
    StockInCreate,
    StockInUpdate,
    StockOutCreate,
    StockOutUpdate,
)
from src.wms.services.picking_service import consume_stock_for_shipment

router = APIRouter(tags=["Stock In/Out"], dependencies=[Depends(get_current_user)])

# The status a document may move to from where it stands.  Skipping a step
# (DRAFT -> RECEIVED) is a business rule and answers 400; a status the document
# type never has (SHIPPED on a receipt) is a validation error and answers 422 —
# the schema rejects it before this table is consulted.
_STOCK_IN_TRANSITIONS = {
    "DRAFT": ["CONFIRMED"],
    "CONFIRMED": ["RECEIVED"],
    "RECEIVED": [],
    "CANCELLED": [],
}
_STOCK_OUT_TRANSITIONS = {
    "DRAFT": ["CONFIRMED"],
    "CONFIRMED": ["SHIPPED"],
    "SHIPPED": [],
    "CANCELLED": [],
}


# ── Helpers ─────────────────────────────────────────────────────────


async def _get_stock_in(db: AsyncSession, id: str) -> StockIn:
    obj = await db.get(StockIn, _uuid.UUID(id))
    if not obj or getattr(obj, "is_deleted", False):
        raise NotFoundException(f"stock-in {id}")
    return obj


async def _get_stock_out(db: AsyncSession, id: str) -> StockOut:
    obj = await db.get(StockOut, _uuid.UUID(id))
    if not obj or getattr(obj, "is_deleted", False):
        raise NotFoundException(f"stock-out {id}")
    return obj


async def _operator_from_credential(session: AsyncSession, current_user: object) -> _uuid.UUID | None:
    """The user id of the caller, resolved from the credential.

    ``get_current_user`` hands back the JWT payload, whose ``sub`` is a
    **username** (``src/core/dependencies.py`` reads it as one when it looks up
    permissions).  ``adjust_stock`` used to do ``str(UUID(sub))`` on it, which
    raised on every request, and the ``except (ValueError, TypeError)`` below it
    swallowed the failure — so the operator column of an adjustment was NULL
    always, and the audit trail of a stock difference never named a person.
    """
    if not isinstance(current_user, dict):
        return None
    username = current_user.get("sub")
    if not username:
        return None
    return await session.scalar(select(User.id).where(User.username == username))


# ── Stock In CRUD ───────────────────────────────────────────────────


@router.post("/stock-in", status_code=201)
async def create_stock_in(
    payload: StockInCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a Stock In record with line items.

    This is a document, not a movement: it records what the warehouse received
    and writes no ``Inventory`` row and no ``InventoryLog``.  The same is true of
    ``create_stock_out`` below.  A receipt that is never confirmed and put
    through the inventory path leaves the shelf unchanged, so the receipt ledger
    and the shelf quantities are not the same fact — see
    tests/test_wms/test_stock_movement_link.py for the audit gap asserted in
    those terms.
    """
    from src.wms.models import Vendor, Warehouse

    wh = await session.execute(
        select(Warehouse).where(Warehouse.id == payload.warehouse_id)
    )
    warehouse = wh.scalar_one_or_none()
    if not warehouse:
        raise NotFoundException(f"warehouse {payload.warehouse_id}")

    if payload.supplier_id:
        v = await session.execute(select(Vendor).where(Vendor.id == payload.supplier_id))
        if not v.scalar_one_or_none():
            raise NotFoundException(f"vendor {payload.supplier_id}")

    obj = StockIn(
        warehouse_id=warehouse.id,
        type=payload.type,
        ref_no=payload.ref_no,
        reference_type=payload.reference_type,
        supplier_id=payload.supplier_id,
        total_qty=sum((line.qty for line in payload.lines), Decimal("0")).quantize(Decimal("0.0001")),
    )
    session.add(obj)

    for line in payload.lines:
        obj.lines.append(StockInLine(
            stock_in_id=obj.id,
            sku=line.sku,
            qty_received=line.qty,
            batch_no=line.batch_no,
            lot_no=line.lot_no,
            expiry_date=line.expiry_date,
        ))

    await session.commit()
    return model_to_dict(obj)


@router.get("/stock-in/{id}")
async def get_stock_in(id: str, session: Annotated[AsyncSession, Depends(get_db)]):
    """Get a single Stock In with line items."""
    obj = await _get_stock_in(session, id)
    result = model_to_dict(obj)
    # Load lines eagerly
    from sqlalchemy import select as sel  # noqa: F811
    q = sel(StockInLine).where(StockInLine.stock_in_id == obj.id)
    res = await session.execute(q)
    result["lines"] = [model_to_dict(ln) for ln in res.scalars().all()]
    return result


@router.get("/stock-in")
async def list_stock_in(session: Annotated[AsyncSession, Depends(get_db)], warehouse_id: str | None = Query(None)):
    """List Stock In records with optional warehouse filter."""
    q = select(StockIn).where(StockIn.status != "CANCELLED")
    if warehouse_id:
        q = q.where(StockIn.warehouse_id == _uuid.UUID(warehouse_id))
    q = q.order_by(StockIn.created_at.desc())
    res = await session.execute(q)
    return [model_to_dict(r) for r in res.scalars().all()]


@router.put("/stock-in/{id}")
async def update_stock_in(
    id: str,
    payload: StockInUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
):
    """Confirm a stock-in.  Only the allowlisted fields reach the UPDATE.

    ``values(data)`` used to write every key the client sent, so
    ``{"data": {"is_deleted": true}}`` deleted the document,
    ``{"data": {"total_qty": 9999}}`` wrote a total its lines do not add up to,
    and ``{"data": {"warehouse_id": ...}}`` moved it to another warehouse.  The
    write also bypassed the loaded object, which meant the JSON handed back to
    the client was the row as it was *before* the update.
    """
    obj = await _get_stock_in(session, id)
    values = payload.model_dump(exclude_unset=True)

    if "status" in values and values["status"] != obj.status:
        allowed = _STOCK_IN_TRANSITIONS.get(obj.status, [])
        if values["status"] not in allowed:
            raise HTTPException(400, f"Invalid status transition {obj.status} -> {values['status']}")

    if values:
        await session.execute(update(StockIn).where(StockIn.id == obj.id).values(**values))
        await session.commit()
        await session.refresh(obj)
    return model_to_dict(obj)


# ── Stock Out CRUD ───────────────────────────────────────────────────


@router.post("/stock-out", status_code=201)
async def create_stock_out(
    payload: StockOutCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a Stock Out record with line items — a document, not a movement.

    The shelf is untouched here on purpose: a shipment is created as DRAFT, and
    the inventory is consumed when it ships.  See ``update_stock_out`` and
    ``src.wms.services.picking_service.consume_stock_for_shipment``, which is
    called on the CONFIRMED → SHIPPED transition and is what writes the
    per-batch audit rows.  Creation deducting would double-count every
    shipment that is confirmed and shipped.
    """
    from src.wms.models import Warehouse

    wh = await session.execute(
        select(Warehouse).where(Warehouse.id == payload.warehouse_id)
    )
    warehouse = wh.scalar_one_or_none()
    if not warehouse:
        raise NotFoundException(f"warehouse {payload.warehouse_id}")

    obj = StockOut(
        warehouse_id=warehouse.id,
        type=payload.type,
        ref_no=payload.ref_no,
        reference_type=payload.reference_type,
        total_qty=sum((line.qty for line in payload.lines), Decimal("0")).quantize(Decimal("0.0001")),
    )
    session.add(obj)

    for line in payload.lines:
        obj.lines.append(StockOutLine(
            stock_out_id=obj.id,
            sku=line.sku,
            qty_shipped=line.qty,
            batch_no=line.batch_no,
            lot_no=line.lot_no,
            expiry_date=line.expiry_date,
        ))

    await session.commit()
    return model_to_dict(obj)


@router.get("/stock-out/{id}")
async def get_stock_out(id: str, session: Annotated[AsyncSession, Depends(get_db)]):
    """Get a single Stock Out with line items."""
    obj = await _get_stock_out(session, id)
    result = model_to_dict(obj)
    # Load lines eagerly
    q = select(StockOutLine).where(StockOutLine.stock_out_id == obj.id)
    res = await session.execute(q)
    result["lines"] = [model_to_dict(ln) for ln in res.scalars().all()]
    return result


@router.get("/stock-out")
async def list_stock_out(session: Annotated[AsyncSession, Depends(get_db)], warehouse_id: str | None = Query(None)):
    """List Stock Out records with optional warehouse filter."""
    q = select(StockOut).where(StockOut.status != "CANCELLED")
    if warehouse_id:
        q = q.where(StockOut.warehouse_id == _uuid.UUID(warehouse_id))
    q = q.order_by(StockOut.created_at.desc())
    res = await session.execute(q)
    return [model_to_dict(r) for r in res.scalars().all()]


@router.put("/stock-out/{id}")
async def update_stock_out(
    id: str,
    payload: StockOutUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Confirm or ship a stock-out.  The allowlist is the same as ``update_stock_in``.

    CONFIRMED → SHIPPED is where the shelf moves: the shipment is deducted from
    the batches FEFO and each batch gets its own audit row.  It is all one
    transaction, so a shipment the stock cannot cover answers 422 and changes
    neither the inventory nor the status — the document stays CONFIRMED and the
    shelf stays as it was.

    SHIPPED is terminal (``_STOCK_OUT_TRANSITIONS``), so a shipment recorded
    wrong is not undone here: it is corrected by a compensating adjustment, which
    is what ``/adjust-stock`` is for.

    Re-sending SHIPPED on a document already shipped is a no-op that answers 200,
    not a second movement.  A PDA working offline replays its queued mutations on
    reconnect (``src/core/offline.py``), and a queue that replays a shipped
    shipment must not deduct the shelf a second time.
    """
    obj = await _get_stock_out(session, id)
    values = payload.model_dump(exclude_unset=True)

    shipping = "status" in values and values["status"] != obj.status and values["status"] == "SHIPPED"
    if "status" in values and values["status"] != obj.status:
        allowed = _STOCK_OUT_TRANSITIONS.get(obj.status, [])
        if values["status"] not in allowed:
            raise HTTPException(400, f"Invalid status transition {obj.status} -> {values['status']}")

    if values:
        if shipping:
            lines = await _stock_out_lines(session, obj.id)
            await consume_stock_for_shipment(
                session,
                warehouse_id=str(obj.warehouse_id),
                lines=lines,
                stock_out_id=str(obj.id),
                operator_id=await _operator_from_credential(session, current_user),
            )
        await session.execute(update(StockOut).where(StockOut.id == obj.id).values(**values))
        await session.commit()
        await session.refresh(obj)
    return model_to_dict(obj)


async def _stock_out_lines(session: AsyncSession, stock_out_id) -> list[dict]:
    """The shipment's lines, in the shape the consuming service reads."""
    result = await session.execute(select(StockOutLine).where(StockOutLine.stock_out_id == stock_out_id))
    return [{"sku": ln.sku, "qty": Decimal(str(ln.qty_shipped))} for ln in result.scalars().all()]


# ── Inventory Log CRUD ───────────────────────────────────────────────


@router.get("/inventory-log/{id}")
async def get_inventory_log(id: str, session: Annotated[AsyncSession, Depends(get_db)]):
    """Get a single Inventory Log record."""
    obj = await session.get(StockInventoryLog, _uuid.UUID(id))
    if not obj or getattr(obj, "is_deleted", False):
        raise NotFoundException(f"inventory-log {id}")
    return model_to_dict(obj)


@router.get("/inventory-log")
async def list_inventory_log(session: Annotated[AsyncSession, Depends(get_db)], warehouse_id: str | None = Query(None)):
    """List Inventory Log records with optional warehouse filter."""
    q = select(StockInventoryLog).order_by(StockInventoryLog.created_at.desc())
    if warehouse_id:
        q = q.where(StockInventoryLog.warehouse_id == _uuid.UUID(warehouse_id))
    res = await session.execute(q)
    return [model_to_dict(r) for r in res.scalars().all()]


# ── Adjust Stock (bulk inventory adjustment) ─────────────────────────


@router.post("/adjust-stock")
async def adjust_stock(
    payload: AdjustStockRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Adjust stock up or down with audit trail.

    Business rules:
        - Positive qty → IN adjustment (updates stock + creates inventory log)
        - Negative qty → OUT adjustment (updates stock + creates inventory log)
        - Zero qty is rejected; OUT is rejected when available stock is short

    The adjustment now actually moves ``wms.Inventory`` quantities (locked
    rows with FOR UPDATE so concurrent adjustments can't double-spend),
    matching the log it writes — previously this endpoint was log-only and
    stock silently drifted from its own audit trail.

    The audit trail names an operator.  The direction of the movement is the
    sign of ``quantity``, and the log row carries the same sign
    (``StockInventoryLog`` documents "+ve = in, -ve = out"), so a ledger read
    sums to the stock that is on the shelf.
    """
    sku_id = payload.sku_id
    warehouse_id = payload.warehouse_id
    qty = payload.quantity
    if qty == 0:
        raise HTTPException(400, "Quantity must be non-zero")

    # Determine direction
    is_inbound = qty > 0
    adj_type = "ADJUSTMENT_IN" if is_inbound else "ADJUSTMENT_OUT"
    abs_qty = abs(qty)

    # ── Real inventory movement ────────────────────────────────────────────
    sku_result = await session.execute(select(SKU).where(SKU.id == sku_id))
    sku_obj = sku_result.scalar_one_or_none()
    if not sku_obj:
        # Follow adjust_stock_count's precedent: auto-create unknown SKUs.
        sku_obj = SKU(id=sku_id, sku=str(sku_id), name=str(sku_id))
        session.add(sku_obj)
        await session.flush()

    inv_result = await session.execute(
        select(Inventory)
        .where(Inventory.warehouse_id == warehouse_id, Inventory.sku_id == sku_id)
        .order_by(Inventory.created_at.asc())
        .with_for_update()
    )
    inv_rows = list(inv_result.scalars().all())
    now = datetime.now(UTC).replace(tzinfo=None)

    if is_inbound:
        if inv_rows:
            target = inv_rows[0]
            target.quantity = Decimal(str(target.quantity)) + abs_qty
            target.updated_at = now
        else:
            session.add(Inventory(
                id=_uuid.uuid4(), warehouse_id=warehouse_id, sku_id=sku_id, quantity=abs_qty,
                # NOT NULL columns on the Inventory model — supply safe blanks.
                gtin=str(sku_obj.gtin or "")[:13], batch_no="",
            ))
    else:
        available = sum(
            Decimal(str(r.quantity)) - Decimal(str(r.locked_qty or 0)) for r in inv_rows
        )
        if available < abs_qty:
            raise HTTPException(
                400, f"Insufficient stock: available {available}, requested {abs_qty}",
            )
        remaining = abs_qty
        for row in inv_rows:
            if remaining <= 0:
                break
            take = min(remaining, Decimal(str(row.quantity)) - Decimal(str(row.locked_qty or 0)))
            if take > 0:
                row.quantity = Decimal(str(row.quantity)) - take
                row.updated_at = now
                remaining -= take

    # Log the adjustment in inventory logs
    operator_id = payload.operator_id
    if operator_id is not None and not await session.scalar(select(User.id).where(User.id == operator_id)):
        raise ValidationException(
            message=f"operator_id {operator_id} is not a user — the operator column of "
                    "an adjustment is a foreign key to users.id, so naming a person who "
                    "does not exist is not a way to record one",
        )
    if operator_id is None:
        operator_id = await _operator_from_credential(session, current_user)
    log_entry = StockInventoryLog(
        warehouse_id=warehouse_id,
        sku=str(sku_id),
        type=adj_type,
        reference_type="adjust_stock",
        quantity_change=qty,
        operator_id=operator_id,
        reason=payload.reason,
        remark=payload.remark,
    )
    session.add(log_entry)

    await session.commit()

    return {
        "success": True,
        "message": f"Stock adjusted: {'IN' if is_inbound else 'OUT'}",
        "sku_id": str(sku_id),
        "warehouse_id": str(warehouse_id),
        "quantity": str(abs_qty),
        "type": adj_type,
        "operator_id": str(operator_id) if operator_id else None,
    }
