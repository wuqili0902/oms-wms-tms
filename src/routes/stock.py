"""Stock In / Out / Inventory Log / Adjust Stock API endpoints."""
import uuid as _uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.exceptions import NotFoundException
from src.models.base import model_to_dict
from src.models.wms import (
    StockIn,
    StockInLine,
    StockInventoryLog,
    StockOut,
    StockOutLine,
)

router = APIRouter(tags=["Stock In/Out"])


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


# ── Stock In CRUD ───────────────────────────────────────────────────


@router.post("/stock-in")
async def create_stock_in(req: dict, session: Annotated[AsyncSession, Depends(get_db)]):
    """Create a Stock In record with line items."""
    data = req.get("data", {})
    lines = data.pop("lines", [])

    # Validate warehouse exists
    from src.wms.models import Warehouse  # noqa: F811
    wh = await session.execute(
        select(Warehouse).where(Warehouse.id == _uuid.UUID(data["warehouse_id"]))
    )
    warehouse = wh.scalar_one_or_none()
    if not warehouse:
        raise NotFoundException(f"warehouse {data['warehouse_id']}")

    if data.get("supplier_id"):
        from src.wms.models import Vendor  # noqa: F811
        v = await session.execute(
            select(Vendor).where(Vendor.id == _uuid.UUID(data["supplier_id"]))
        )
        if not v.scalar_one_or_none():
            raise NotFoundException(f"vendor {data['supplier_id']}")

    obj = StockIn(
        warehouse_id=warehouse.id,
        type=data.get("type", "PURCHASE"),
        ref_no=data.get("ref_no"),
        reference_type=data.get("reference_type"),
        supplier_id=_uuid.UUID(data["supplier_id"]) if data.get("supplier_id") else None,
        total_qty=(sum((Decimal(str(ln.get("qty"))) for ln in lines), Decimal(0))).quantize(Decimal("0.0001")),
    )
    session.add(obj)

    for line_data in lines:
        qty = Decimal(str(line_data["qty"]))
        obj.lines.append(StockInLine(
            stock_in_id=obj.id,
            sku=line_data.get("sku"),
            qty_received=qty,
            batch_no=line_data.get("batch_no"),
            lot_no=line_data.get("lot_no"),
            expiry_date=line_data.get("expiry_date"),
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
async def update_stock_in(id: str, req: dict, session: Annotated[AsyncSession, Depends(get_db)]):
    obj = await _get_stock_in(session, id)
    data = req.get("data", {})

    if "status" in data and data["status"] != obj.status:
        # Validate status transition
        valid_transitions = {
            "DRAFT": ["CONFIRMED"],
            "CONFIRMED": ["RECEIVED"],
            "RECEIVED": [],
        }
        allowed = valid_transitions.get(obj.status, [])
        if data["status"] not in allowed:
            raise HTTPException(400, f"Invalid status transition {obj.status} -> {data['status']}")

    await session.execute(update(StockIn).where(StockIn.id == obj.id).values(data))
    await session.commit()
    return model_to_dict(obj)


# ── Stock Out CRUD ───────────────────────────────────────────────────


@router.post("/stock-out")
async def create_stock_out(req: dict, session: Annotated[AsyncSession, Depends(get_db)]):
    """Create a Stock Out record with line items."""
    data = req.get("data", {})
    lines = data.pop("lines", [])

    # Validate warehouse exists
    from src.wms.models import Warehouse  # noqa: F811
    wh = await session.execute(
        select(Warehouse).where(Warehouse.id == _uuid.UUID(data["warehouse_id"]))
    )
    warehouse = wh.scalar_one_or_none()
    if not warehouse:
        raise NotFoundException(f"warehouse {data['warehouse_id']}")

    obj = StockOut(
        warehouse_id=warehouse.id,
        type=data.get("type", "SALE"),
        ref_no=data.get("ref_no"),
        reference_type=data.get("reference_type"),
        total_qty=(sum((Decimal(str(ln.get("qty"))) for ln in lines), Decimal(0))).quantize(Decimal("0.0001")),
    )
    session.add(obj)

    for line_data in lines:
        qty = Decimal(str(line_data["qty"]))
        obj.lines.append(StockOutLine(
            stock_out_id=obj.id,
            sku=line_data.get("sku"),
            qty_shipped=qty,
            batch_no=line_data.get("batch_no"),
            lot_no=line_data.get("lot_no"),
            expiry_date=line_data.get("expiry_date"),
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
async def update_stock_out(id: str, req: dict, session: Annotated[AsyncSession, Depends(get_db)]):
    obj = await _get_stock_out(session, id)
    data = req.get("data", {})

    if "status" in data and data["status"] != obj.status:
        valid_transitions = {
            "DRAFT": ["CONFIRMED"],
            "CONFIRMED": ["SHIPPED"],
            "SHIPPED": [],
        }
        allowed = valid_transitions.get(obj.status, [])
        if data["status"] not in allowed:
            raise HTTPException(400, f"Invalid status transition {obj.status} -> {data['status']}")

    await session.execute(update(StockOut).where(StockOut.id == obj.id).values(data))
    await session.commit()
    return model_to_dict(obj)


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
async def adjust_stock(req: dict, session: Annotated[AsyncSession, Depends(get_db)]):
    """Adjust stock up or down with audit trail.

    Business rules:
        - Positive qty → IN adjustment (creates inventory log)
        - Negative qty → OUT adjustment (creates inventory log)
        - Zero qty is rejected
    """
    data = req.get("data", {})
    sku_id = _uuid.UUID(data["sku_id"])
    warehouse_id = _uuid.UUID(data["warehouse_id"])

    # Validate quantity
    qty = Decimal(str(data["quantity"]))
    if qty == 0:
        raise HTTPException(400, "Quantity must be non-zero")

    # Determine direction
    is_inbound = qty > 0
    adj_type = "ADJUSTMENT_IN" if is_inbound else "ADJUSTMENT_OUT"
    abs_qty = abs(qty)

    # Log the adjustment in inventory logs
    log_entry = StockInventoryLog(
        warehouse_id=warehouse_id,
        sku=str(sku_id),
        type=adj_type,
        reference_type="adjust_stock",
        quantity_change=abs_qty,
        operator_id=data.get("operator_id"),
        reason=data.get("reason"),
        remark=data.get("remark"),
    )
    session.add(log_entry)

    # Update warehouse inventory (simplified - just logs for now)
    await session.commit()

    return {
        "success": True,
        "message": f"Stock adjusted: {'IN' if is_inbound else 'OUT'}",
        "quantity": str(abs_qty),
        "type": adj_type,
    }
