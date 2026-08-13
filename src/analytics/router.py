import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.service import (
    get_dashboard_stats,
    get_low_stock_items,
    get_order_trends,
    get_recent_orders,
    get_status_distribution,
)
from src.core.database import get_db
from src.core.response import success_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db)):
    stats, trends, status_dist, low_stock, recent = await _load_dashboard_data(db)
    return success_response(data={
        "stats": stats,
        "order_trends": trends,
        "status_distribution": status_dist,
        "low_stock": low_stock,
        "recent_orders": recent,
        "generated_at": datetime.now(UTC).isoformat(),
    })


@router.get("/order-trends")
async def order_trends(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    data = await get_order_trends(db, days)
    return success_response(data={"days": days, "trends": data})


@router.get("/status-distribution")
async def status_distribution(db: AsyncSession = Depends(get_db)):
    data = await get_status_distribution(db)
    return success_response(data=data)


@router.get("/low-stock")
async def low_stock(db: AsyncSession = Depends(get_db)):
    items = await get_low_stock_items(db)
    return success_response(data={"items": items, "count": len(items)})


async def _load_dashboard_data(db: AsyncSession) -> tuple:
    stats = await get_dashboard_stats(db)
    trends = await get_order_trends(db)
    status_dist = await get_status_distribution(db)
    low_stock = await get_low_stock_items(db)
    recent = await get_recent_orders(db)
    return stats, trends, status_dist, low_stock, recent
