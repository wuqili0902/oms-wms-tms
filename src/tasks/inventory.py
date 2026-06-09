"""Celery tasks for WMS inventory operations.

Handles inventory synchronization, stock level alerts, and batch
inventory adjustments that should run asynchronously.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.celery_app import app
from src.config import settings
from src.tasks.base import BaseTask
from src.wms.models import Inventory, StockMovement, StockMovementType
from src.oms.models import Order, OrderStatus

logger = logging.getLogger(__name__)


def _get_async_session() -> AsyncSession:
    engine = create_async_engine(settings.database_url, echo=False)
    return AsyncSession(engine)


@app.task(base=BaseTask, bind=True, max_retries=2)
async def check_low_stock_alerts(self):
    """Check inventory levels and log alerts for low-stock items.

    Runs periodically (e.g., every 6 hours). In production, this would
    send notifications via email/SMS/push.
    """
    session = _get_async_session()
    try:
        result = await session.execute(select(Inventory))
        items = result.scalars().all()

        low_stock = []
        for inv in items:
            available = float(inv.quantity or 0) - float(inv.locked_qty or 0)
            if available <= 0:
                low_stock.append({
                    "warehouse_id": str(inv.warehouse_id),
                    "location_id": str(inv.location_id) if inv.location_id else "",
                    "sku_id": str(inv.sku_id),
                    "available": available,
                })

        if low_stock:
            logger.warning(
                "Low stock alert: %d items at or below zero available quantity",
                len(low_stock),
            )
        return {"low_stock_items": len(low_stock), "items": low_stock}
    finally:
        await session.close()


@app.task(base=BaseTask, bind=True)
async def release_locked_inventory_for_cancelled_orders(self):
    """Release locked inventory when orders are cancelled.

    When an order is cancelled, any reserved/locked inventory should be
    released back to available stock.
    """
    session = _get_async_session()
    try:
        result = await session.execute(
            select(Order).where(Order.status == OrderStatus.CANCELLED)
        )
        cancelled = result.scalars().all()

        released = 0
        for order in cancelled:
            # Find stock movements related to this order and release them
            movements = await session.execute(
                select(StockMovement).where(
                    StockMovement.reference_id == str(order.id),
                    StockMovement.reference_type == "order",
                )
            )
            for move in movements.scalars().all():
                if hasattr(move, 'quantity') and float(move.quantity) < 0:
                    # Negative quantity = reservation, reverse it
                    reverse = StockMovement(
                        warehouse_id=move.warehouse_id,
                        location_id=move.location_id,
                        sku_id=move.sku_id,
                        movement_type=StockMovementType.ADJUSTMENT,
                        quantity=abs(float(move.quantity)),
                        reference_type="order_cancel",
                        reference_id=str(order.id),
                        remark=f"Released from cancelled order {order.order_no}",
                    )
                    session.add(reverse)
                    released += 1

        if released:
            await session.commit()
            logger.info("Released %d inventory reservations from cancelled orders", released)
        return {"released_items": released}
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
