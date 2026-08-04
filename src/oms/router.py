"""OMS API router."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.exceptions import NotFoundException
from src.core.exceptions import ValidationException as AppValidationException
from src.oms import merge as merge_service
from src.oms import service as oms_service
from src.oms.schemas import (
    MergeGroupResponse,
    OrderCreate,
    OrderHistoryResponse,
    OrderListResponse,
    OrderResponse,
    OrderStatusUpdate,
)

router = APIRouter(prefix="/orders", tags=["orders"])


def _order_to_response(order: dict) -> dict:
    return {
        "id": order["id"],
        "order_no": order["order_no"],
        "status": order["status"],
        "customer_id": order["customer_id"],
        "items": order["items"],
        "total_amount": order["total_amount"],
        "priority": order["priority"],
        "notes": order["notes"],
        "created_at": order["created_at"],
        "updated_at": order["updated_at"],
    }


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(data: OrderCreate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    order = await oms_service.create_order(db, data.model_dump())
    return _order_to_response(order)


@router.get("", response_model=OrderListResponse)
async def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None, pattern=r"^(draft|confirmed|processing|picking|completed|cancelled|failed)$"),
    customer_id: str = Query(None),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    items, total = await oms_service.list_orders(
        db, page=page, page_size=page_size, status=status, customer_id=customer_id
    )
    return {
        "items": [_order_to_response(o) for o in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    try:
        order = await oms_service.get_order(db, order_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _order_to_response(order)


@router.put("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: str,
    data: OrderStatusUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    operator = current_user.get("sub", "unknown")
    try:
        order = await oms_service.update_order_status(db, order_id, data.status, operator=operator)
    except (NotFoundException, AppValidationException) as e:
        status_code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=status_code, detail=str(e))
    return _order_to_response(order)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(order_id: str, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    try:
        await oms_service.delete_order(db, order_id)
    except (NotFoundException, AppValidationException) as e:
        status_code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=status_code, detail=str(e))


@router.get("/{order_id}/history", response_model=list[OrderHistoryResponse])
async def get_order_history(order_id: str, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    try:
        return await oms_service.get_order_history(db, order_id)
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Split / Merge ────────────────────────────────────────────────────────────


class SplitRequest(BaseModel):
    splits: list[dict]
    reason: str = ""


class MergeRequest(BaseModel):
    order_ids: list[str]
    code: str | None = None
    warehouse_id: str | None = None
    note: str = ""


@router.post("/{order_id}/split", status_code=status.HTTP_201_CREATED)
async def split_order(
    order_id: str,
    data: SplitRequest,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        children = await merge_service.split_order(
            db, order_id, data.splits, reason=data.reason,
        )
    except (NotFoundException, AppValidationException) as e:
        status_code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=status_code, detail=str(e))
    return {"parent_order_id": order_id, "children": children}


@router.post("/merge", status_code=status.HTTP_201_CREATED)
async def merge_orders(
    data: MergeRequest,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        group = await merge_service.merge_orders(
            db, data.order_ids, code=data.code,
            warehouse_id=data.warehouse_id, note=data.note,
        )
    except (NotFoundException, AppValidationException) as e:
        status_code = 404 if isinstance(e, NotFoundException) else 422
        raise HTTPException(status_code=status_code, detail=str(e))
    return group


@router.get("/merge/{group_id}", response_model=MergeGroupResponse)
async def get_merge_group(
    group_id: str,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    group = await merge_service.get_merge_group(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Merge group not found")
    return group
