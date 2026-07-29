import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache.decorators import cached
from src.oms.models import Order
from src.wms.models import Inventory

logger = logging.getLogger(__name__)


@cached(ttl=300, prefix="analytics", skip_args=1)
async def get_dashboard_stats(db: AsyncSession) -> dict:
    order_total = await db.execute(select(func.count(Order.id)))
    order_count = order_total.scalar() or 0

    from src.auth.models import User
    user_result = await db.execute(select(func.count(User.id)))
    user_count = user_result.scalar() or 0

    inv_result = await db.execute(select(func.count(Inventory.id)))
    inventory_count = inv_result.scalar() or 0

    from src.wms.models import Warehouse
    wh_result = await db.execute(select(func.count(Warehouse.id)))
    warehouse_count = wh_result.scalar() or 0

    return {
        "order_count": order_count,
        "user_count": user_count,
        "inventory_count": inventory_count,
        "warehouse_count": warehouse_count,
    }


@cached(ttl=300, prefix="analytics", skip_args=1)
async def get_order_trends(db: AsyncSession, days: int = 30) -> list[dict]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    date_col = func.date(Order.created_at).label("date")
    result = await db.execute(
        select(
            date_col,
            func.count(Order.id).label("count"),
        )
        .where(Order.created_at >= cutoff)
        .group_by(date_col)
        .order_by("date")
    )
    rows = []
    for r in result.all():
        date_val = r.date
        rows.append({"date": str(date_val) if date_val else "", "count": r.count})
    return rows


@cached(ttl=300, prefix="analytics", skip_args=1)
async def get_status_distribution(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Order.status, func.count(Order.id).label("count"))
        .group_by(Order.status)
    )
    return [{"status": r.status.value if hasattr(r.status, "value") else str(r.status), "count": r.count} for r in result.all()]


@cached(ttl=600, prefix="analytics", skip_args=1)
async def get_low_stock_items(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Inventory).where(Inventory.quantity <= Inventory.min_qty)
        .limit(20)
    )
    return [
        {
            "sku": str(item.sku_id),
            "warehouse": str(item.warehouse_id),
            "quantity": item.quantity,
            "min_qty": item.min_qty,
        }
        for item in result.scalars().all()
    ]


@cached(ttl=300, prefix="analytics", skip_args=1)
async def get_recent_orders(db: AsyncSession, limit: int = 10) -> list[dict]:
    from src.oms.service import STATUS_REVERSE
    result = await db.execute(
        select(Order).order_by(Order.created_at.desc()).limit(limit)
    )
    items = []
    for o in result.scalars().all():
        items.append({
            "id": str(o.id),
            "order_no": o.order_no,
            "status": STATUS_REVERSE.get(o.status, "draft"),
            "total_amount": str(o.total_amount) if o.total_amount else "0",
            "customer_id": str(o.customer_id),
            "created_at": o.created_at.isoformat() if o.created_at else "",
        })
    return items
