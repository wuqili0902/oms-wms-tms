"""Logistics (electronic waybill) API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.logistics.kdniao import print_callback_url
from src.logistics.kdniao import query_tracking as kdniao_query_tracking
from src.logistics.schemas import CreateWaybillRequest
from src.logistics.service import (
    create_waybill,
    get_waybill,
    list_waybills,
    mark_printed,
    void_waybill,
)

router = APIRouter(prefix="/logistics", tags=["Logistics"])


@router.post("/waybill/create")
async def create_waybill_endpoint(
    request: Request,
    body: CreateWaybillRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await create_waybill(db, body)
    except Exception as e:
        logger = request.app.state.logger
        logger.error("[logistics] create_waybill failed for order %s: %s", body.order_id, e)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail="下单失败：" + str(e),
        ) from e

    return result


@router.get("/waybill/list")
async def list_waybill_endpoint(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    carrier: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await list_waybills(db, page=page, page_size=page_size, status=status, carrier=carrier, q=q)
    except Exception as e:
        logger = request.app.state.logger
        logger.error("[logistics] list_waybill failed: %s", e)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="查询面单列表失败",
        ) from e

    return result


@router.get("/waybill/{tracking}")
async def get_waybill_endpoint(
    tracking: str,
    db: AsyncSession = Depends(get_db),
):
    return await get_waybill(db, tracking)


@router.post("/waybill/{tracking}/void")
async def void_waybill_endpoint(
    tracking: str,
    db: AsyncSession = Depends(get_db),
):
    return await void_waybill(db, tracking)


@router.get("/waybill/{tracking}/track")
async def track_waybill_endpoint(
    request: Request,
    tracking: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await kdniao_query_tracking(tracking)
    except Exception as e:
        logger = request.app.state.logger
        logger.error("[logistics] track failed for %s: %s", tracking, e)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail="查单失败：" + str(e),
        ) from e

    return result


@router.post("/waybill/{tracking}/print")
async def print_waybill_endpoint(
    tracking: str,
    db: AsyncSession = Depends(get_db),
):
    url = print_callback_url(tracking)
    try:
        await mark_printed(db, tracking)
    except Exception:
        pass

    return {"print_callback_url": url}
