"""Inventory-related background tasks."""
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from src.celery_app import celery
from src.core.database import async_session_factory
from src.tms.models import SyncLog, SyncLogStatus, SyncLogType
from src.wms.models import Inventory as WMS_Inventory


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
                log = SyncLog(
                    id=self.request.id, device_id=item.warehouse_id,
                    sync_type=SyncLogType.UPLOAD, status=SyncLogStatus.COMPLETED,
                    records_count=count, started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
                )
            except Exception:
                log = SyncLog(id=self.request.id, device_id=None, sync_type=SyncLogType.DOWNLOAD,
                              status=SyncLogStatus.FAILED, error_message=str(self))
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


@celery.task(bind=True, name="tasks.order.cancel_expired")
async def cancel_expired_orders(self) -> int:
    """Cancel orders that have been pending too long."""
    from src.oms.models import Order as _Order, OrderStatus as _OS

    async with async_session_factory() as session:
        result = await session.execute(select(_Order).where(_Order.status == _OS.PENDING))
        old_orders = [o for o in result.scalars().all() if (datetime.now(UTC) - o.created_at).days > 7]

        count = 0
        for order in old_orders:
            try:
                order.status = _OS.CANCELLED
                count += 1
            except Exception:
                pass

        await session.commit()
    return {"cancelled_count": count}


@celery.task(bind=True, name="tasks.order.process_pending")
async def process_pending_orders(self) -> dict:
    """Auto-confirm pending orders after a grace period."""
    from datetime import UTC, datetime

    async with async_session_factory() as session:
        result = await session.execute(select(_Order).where(
            _Order.status == _OS.PENDING))
        ready = [o for o in result.scalars().all() if (datetime.now(UTC) - o.created_at).days >= 1]

        count = 0
        for order in ready:
            try:
                order.status = _OS.CONFIRMED
                count += 1
            except Exception:
                pass

        await session.commit()
    return {"processed_count": count}
