"""Inventory-related background tasks."""
import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from src.celery_app import celery
from src.core.database import async_session_factory
from src.oms.models import Order as _Order
from src.oms.models import OrderStatus as _order_status  # noqa: N813
from src.tms.models import SyncLog, SyncLogStatus, SyncLogType
from src.wms.models import Inventory as WMS_Inventory

logger = logging.getLogger(__name__)


@celery.task(bind=True, name="tasks.inventory.sync")
async def sync_inventory(self) -> dict:
    """Periodically scan inventory and create diff records."""
    from datetime import UTC, datetime

    async with async_session_factory() as session:
        result = await session.execute(select(WMS_Inventory))
        items = result.scalars().all()
        count = len(items)
        for item in items:
            try:
                session.add(SyncLog(
                    id=self.request.id, device_id=item.warehouse_id,
                    sync_type=SyncLogType.UPLOAD, status=SyncLogStatus.COMPLETED,
                    records_count=count, started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
                ))
            except Exception:
                logger.exception("Failed to create SyncLog for inventory item %s", item.sku_id)
        await session.commit()

    return {"inventory_count": count, "message": "Inventory sync complete"}


@celery.task(bind=True, name="tasks.inventory.snapshot")
async def snapshot_inventory(self) -> dict:
    """Create a daily inventory snapshot."""
    from datetime import UTC, datetime

    async with async_session_factory() as session:
        result = await session.execute(select(WMS_Inventory))
        items = result.scalars().all()
        return {"snapshot_count": len(items), "timestamp": datetime.now(UTC).isoformat()}


@celery.task(bind=True, name="tasks.inventory.check_low_stock")
async def check_low_stock_alerts(self) -> dict:
    """Check inventory levels and flag items below minimum threshold."""

    from src.notification.service import notify_low_stock

    async with async_session_factory() as session:
        result = await session.execute(
            select(WMS_Inventory).where(WMS_Inventory.quantity <= WMS_Inventory.min_qty)
        )
        low_stock = result.scalars().all()
        for item in low_stock:
            logger.warning(
                "Low stock alert: sku=%s warehouse=%s qty=%s min_qty=%s",
                item.sku_id, item.warehouse_id, item.quantity, item.min_qty,
            )
            await notify_low_stock(
                warehouse_id=str(item.warehouse_id),
                sku=str(item.sku_id),
                current_qty=item.quantity,
                db=session,
            )

    return {"low_stock_count": len(low_stock)}


@celery.task(bind=True, name="tasks.inventory.release_locked")
async def release_locked_inventory_for_cancelled_orders(self) -> dict:
    """Release locked inventory for cancelled orders."""

    async with async_session_factory() as session:
        result = await session.execute(
            select(_Order).where(_Order.status == _order_status.CANCELLED)
        )
        cancelled = result.scalars().all()
        order_ids = [o.id for o in cancelled]
        if not order_ids:
            return {"released_count": 0}

        inv_result = await session.execute(
            select(WMS_Inventory).where(
                WMS_Inventory.locked_qty > 0,
            )
        )
        total_released = 0
        for inv in inv_result.scalars().all():
            if inv.locked_qty > 0:
                inv.quantity += inv.locked_qty
                inv.locked_qty = Decimal("0")
                total_released += 1

        await session.commit()

    return {"released_count": total_released}


@celery.task(bind=True, name="tasks.order.cancel_expired")
async def cancel_expired_orders(self) -> dict:
    """Cancel orders that have been pending too long."""

    async with async_session_factory() as session:
        result = await session.execute(select(_Order).where(_Order.status == _order_status.PENDING))
        now = datetime.now(UTC).replace(tzinfo=None)
        old_orders = [o for o in result.scalars().all() if (now - o.created_at.replace(tzinfo=None)).days > 7]

        count = 0
        for order in old_orders:
            try:
                order.status = _order_status.CANCELLED
                count += 1
            except Exception:
                logger.exception("Failed to cancel order %s", order.id)

        await session.commit()
    return {"cancelled_count": count}


@celery.task(bind=True, name="tasks.order.process_pending")
async def process_pending_orders(self) -> dict:
    """Auto-confirm pending orders after a grace period."""
    from datetime import UTC, datetime

    async with async_session_factory() as session:
        result = await session.execute(select(_Order).where(
            _Order.status == _order_status.PENDING))
        now2 = datetime.now(UTC).replace(tzinfo=None)
        ready = [o for o in result.scalars().all() if (now2 - o.created_at.replace(tzinfo=None)).days >= 1]

        count = 0
        for order in ready:
            try:
                order.status = _order_status.CONFIRMED
                count += 1
            except Exception:
                logger.exception("Failed to auto-confirm order %s", order.id)

        await session.commit()
    return {"processed_count": count}
