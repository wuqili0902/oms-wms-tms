"""Celery tasks for order processing lifecycle.

These tasks handle asynchronous order state transitions, notifications,
and batch operations that should not block the HTTP request cycle.
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.celery_app import app
from src.config import settings
from src.oms.models import Order, OrderStatus, OrderStatusLog
from src.tasks.base import BaseTask

logger = logging.getLogger(__name__)


def _get_async_session() -> AsyncSession:
    """Create a new async session for task execution."""
    engine = create_async_engine(settings.database_url, echo=False)
    return AsyncSession(engine)


@app.task(base=BaseTask, bind=True, max_retries=3)
async def process_stale_orders(self):
    """Process orders stuck in intermediate states for too long.

    Orders in 'processing' or 'picking' for over 24 hours are flagged.
    This runs as a periodic task (e.g., every hour).
    """
    session = _get_async_session()
    try:
        cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        result = await session.execute(
            select(Order).where(
                Order.status.in_([OrderStatus.PROCESSING, OrderStatus.PICKING]),
                Order.updated_at < cutoff,
            )
        )
        stale = result.scalars().all()

        count = 0
        for order in stale:
            log = OrderStatusLog(
                order_id=order.id,
                from_status=order.status.value,
                to_status="flagged_stale",
                remark=f"Auto-flagged: stuck in '{order.status.value}' since {order.updated_at.isoformat()}",
            )
            session.add(log)
            count += 1

        if count:
            await session.commit()
            logger.info("Flagged %d stale orders", count)
        return {"stale_orders_flagged": count}
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@app.task(base=BaseTask, bind=True, max_retries=2)
async def auto_complete_picked_orders(self):
    """Auto-complete orders that have been in 'picking' for 48+ hours.

    This handles edge cases where the picking wave completed but the
    order status was never updated to 'completed'.
    """
    session = _get_async_session()
    try:
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(hours=48)
        result = await session.execute(
            select(Order).where(
                Order.status == OrderStatus.PICKING,
                Order.updated_at < cutoff,
            )
        )
        orders = result.scalars().all()

        completed = 0
        for order in orders:
            order.status = OrderStatus.COMPLETED
            order.updated_at = datetime.now(UTC)
            log = OrderStatusLog(
                order_id=order.id,
                from_status="picking",
                to_status="completed",
                remark="Auto-completed: order in picking state for 48+ hours",
            )
            session.add(log)
            completed += 1

        if completed:
            await session.commit()
            logger.info("Auto-completed %d picked orders", completed)
        return {"orders_completed": completed}
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@app.task(base=BaseTask, bind=True)
async def cancel_abandoned_drafts(self):
    """Cancel draft orders older than 7 days."""
    session = _get_async_session()
    try:
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=7)
        result = await session.execute(
            select(Order).where(
                Order.status == OrderStatus.PENDING,
                Order.created_at < cutoff,
            )
        )
        orders = result.scalars().all()

        cancelled = 0
        for order in orders:
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.now(UTC)
            log = OrderStatusLog(
                order_id=order.id,
                from_status="pending",
                to_status="cancelled",
                remark="Auto-cancelled: draft order older than 7 days",
            )
            session.add(log)
            cancelled += 1

        if cancelled:
            await session.commit()
            logger.info("Cancelled %d abandoned draft orders", cancelled)
        return {"orders_cancelled": cancelled}
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
