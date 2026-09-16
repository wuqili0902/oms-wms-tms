"""Logistics (electronic waybill) API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.exceptions import NotFoundException
from src.logistics.kdniao import print_callback_url
from src.logistics.kdniao import query_tracking as kdniao_query_tracking
from src.logistics.schemas import (
    CreateWaybillRequest,
    PrintWaybillResponse,
    TrackingInfoResponse,
    WaybillListResponse,
    WaybillResponse,
)
from src.logistics.service import (
    create_waybill,
    get_waybill,
    list_waybills,
    mark_printed,
    void_waybill,
)

router = APIRouter(prefix="/logistics", tags=["Logistics"])
logger = logging.getLogger(__name__)


@router.post("/waybill/create", response_model=WaybillResponse, status_code=http_status.HTTP_201_CREATED)
async def create_waybill_endpoint(
    request: Request,
    body: CreateWaybillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = await create_waybill(db, body)
    except Exception as e:
        logger.error("[logistics] create_waybill failed for order %s: %s", body.order_id, e)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail="下单失败：" + str(e),
        ) from e

    return result


@router.get("/waybill/list", response_model=WaybillListResponse)
async def list_waybill_endpoint(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    carrier: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = await list_waybills(db, page=page, page_size=page_size, status=status, carrier=carrier, q=q)
    except Exception as e:
        logger.error("[logistics] list_waybill failed: %s", e)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="查询面单列表失败",
        ) from e

    return result


@router.get("/waybill/{tracking}", response_model=WaybillResponse)
async def get_waybill_endpoint(
    tracking: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await get_waybill(db, tracking)


@router.post("/waybill/{tracking}/void", response_model=WaybillResponse)
async def void_waybill_endpoint(
    tracking: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await void_waybill(db, tracking)


@router.get("/waybill/{tracking}/track", response_model=TrackingInfoResponse)
async def track_waybill_endpoint(
    request: Request,
    tracking: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = await kdniao_query_tracking(tracking)
    except Exception as e:
        logger.error("[logistics] track failed for %s: %s", tracking, e)
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail="查单失败：" + str(e),
        ) from e

    return result


@router.post("/waybill/{tracking}/print", response_model=PrintWaybillResponse)
async def print_waybill_endpoint(
    request: Request,
    tracking: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    url = print_callback_url(tracking)
    try:
        result = await mark_printed(db, tracking)
        logger.info("[logistics] marked %s printed (count=%s)", tracking, result.get("print_count"))
    except NotFoundException as e:
        # 运单尚未在本库落库(承运商侧已有记录):尽力而为,仍返回回调地址供打印机取图打印
        logger.warning("[logistics] waybill %s not found locally for print marking: %s", tracking, e)
    except Exception as e:
        # 标记打印失败不影响标签打印本身:记录后继续返回回调地址(尽力而为),避免打印机拿不到取图地址
        logger.error("[logistics] mark_printed failed for %s: %s", tracking, e)

    return {"print_callback_url": url}
