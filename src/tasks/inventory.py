"""Inventory-related background tasks."""
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.celery_app import celery
from src.core.database import async_session_factory
from src.oms.models import Order as _Order
from src.oms.models import OrderStatus as _order_status  # noqa: N813
from src.tasks.base import BaseTask
from src.tms.models import SyncLog, SyncLogStatus, SyncLogType
from src.wms.models import Inventory as WMS_Inventory
from src.wms.models import InventoryChangeType, InventoryLog

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


@celery.task(bind=True, base=BaseTask, name="tasks.inventory.sync")
async def sync_inventory(self) -> dict:
    """Periodically scan inventory and create diff records."""
    from datetime import UTC, datetime

    async with async_session_factory() as session:
        count = 0
        while True:
            result = await session.execute(
                select(WMS_Inventory).offset(count).limit(BATCH_SIZE)
            )
            items = result.scalars().all()
            if not items:
                break
            for item in items:
                try:
                    session.add(SyncLog(
                        id=uuid.uuid4(), device_id=item.warehouse_id,
                        sync_type=SyncLogType.UPLOAD, status=SyncLogStatus.COMPLETED,
                        records_count=1, started_at=datetime.now(UTC), completed_at=datetime.now(UTC),
                    ))
                except Exception:
                    logger.exception("Failed to create SyncLog for inventory item %s", item.sku_id)
            count += len(items)
            await session.flush()

        await session.commit()

    return {"inventory_count": count, "message": "Inventory sync complete"}


@celery.task(bind=True, base=BaseTask, name="tasks.inventory.snapshot")
async def snapshot_inventory(self) -> dict:
    """Create a daily inventory snapshot."""
    from datetime import UTC, datetime

    async with async_session_factory() as session:
        count = 0
        while True:
            result = await session.execute(
                select(WMS_Inventory).offset(count).limit(BATCH_SIZE)
            )
            items = result.scalars().all()
            if not items:
                break
            count += len(items)
        return {"snapshot_count": count, "timestamp": datetime.now(UTC).isoformat()}


@celery.task(bind=True, base=BaseTask, name="tasks.inventory.check_low_stock")
async def check_low_stock_alerts(self) -> dict:
    """Check inventory levels and flag items below minimum threshold."""

    from src.notification.service import notify_low_stock

    async with async_session_factory() as session:
        result = await session.execute(
            select(WMS_Inventory).where(WMS_Inventory.quantity <= WMS_Inventory.min_qty).limit(BATCH_SIZE)
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


# How long an unattributed lock (reserved stock with no order_id) must have sat
# untouched before this task is willing to let go of it.  A young one is a bug
# somewhere else that is still in progress; releasing it would hand out stock
# that something else is about to pick.
UNATTRIBUTED_LOCK_MAX_AGE_DAYS = 7


def _clear_reservation(db: AsyncSession, inv: WMS_Inventory, *, reason: str) -> Decimal:
    """Clear one reservation, and write the audit row that says so.

    ``quantity`` is on-hand stock and ``locked_qty`` is the slice of it that an
    order has claimed — every reader in this codebase computes availability as
    ``quantity - locked_qty`` (src/wms/service.py:380,
    src/wms/services/picking_service.py:87).  Clearing the reservation therefore
    must not touch ``quantity``.  The old code did ``quantity += locked_qty``,
    which turned a cancelled order's 10 reserved units into 10 *extra* units on
    the shelf: availability went from ``q - 10`` to ``q + 10``, inventing stock
    that no receiving ever put there.

    The on-hand quantity genuinely does not change here, so the audit row records
    that faithfully (change 0, before == after) and puts the freed amount in the
    remark — a log reader tracing this event reads the remark, not a phantom
    quantity delta.
    """
    locked = Decimal(str(inv.locked_qty or 0))
    on_hand = Decimal(str(inv.quantity or 0))
    inv.locked_qty = Decimal("0")
    db.add(InventoryLog(
        id=uuid.uuid4(),
        inventory_id=inv.id,
        change_type=InventoryChangeType.ADJUSTMENT,
        quantity_change=Decimal("0"),
        quantity_before=on_hand,
        quantity_after=on_hand,
        reference_type="inventory_release",
        reference_id=inv.order_id,
        remark=(
            f"reservation cleared: {locked} reserved units released ({reason}); "
            f"available {on_hand - locked} -> {on_hand}"
        ),
    ))
    return locked


async def _cancelled_order_ids(db: AsyncSession) -> list:
    """Ids of the cancelled orders whose reservations this run can free."""
    result = await db.execute(select(_Order).where(_Order.status == _order_status.CANCELLED))
    return [o.id for o in result.scalars().all()]


async def release_locked_inventory(db: AsyncSession) -> dict:
    """Release reservations held by cancelled orders, plus stale unattributed ones.

    Split out of the Celery task on purpose: the task builds its own session from
    ``async_session_factory``, which points at whatever ``DATABASE_URL`` says and
    cannot be rolled back by a test.  This function takes the session, so the
    release rules below are testable instead of asserted by a docstring.

    The caller owns the transaction — this flushes, it does not commit.

    Returns counts split by origin, because a run that unlocked more than it
    should is only visible afterwards if the numbers say *why* each lock went.
    """
    cancelled = await _cancelled_order_ids(db)

    released = 0
    units_released = Decimal("0")
    if cancelled:
        inv_result = await db.execute(
            select(WMS_Inventory).where(
                WMS_Inventory.locked_qty > 0,
                WMS_Inventory.order_id.in_(cancelled),
            ).with_for_update(skip_locked=True)
        )
        for inv in inv_result.scalars().all():
            units_released += _clear_reservation(db, inv, reason=f"cancelled order {inv.order_id}")
            released += 1

    # Unattributed locks: stock marked reserved with nothing to say who reserved
    # it.  The old code released *all* of them on every run, so any unexplained
    # lock — including one created seconds ago by a half-finished allocation — was
    # silently unlocked by the next scheduled task.  Only a lock that has been
    # idle past the age limit counts as leftover, and it is logged at warning
    # level because a row nobody can account for is itself the finding.
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=UNATTRIBUTED_LOCK_MAX_AGE_DAYS)
    stale_result = await db.execute(
        select(WMS_Inventory).where(
            WMS_Inventory.locked_qty > 0,
            WMS_Inventory.order_id.is_(None),
            WMS_Inventory.updated_at.is_not(None),
            WMS_Inventory.updated_at < cutoff,
        ).with_for_update(skip_locked=True)
    )
    unattributed_released = 0
    for inv in stale_result.scalars().all():
        logger.warning(
            "Releasing unattributed stock lock: warehouse=%s sku=%s batch=%s locked=%s "
            "(idle since %s, over %d days old) — nothing in this system reserves stock "
            "with no order_id, so this row is worth investigating",
            inv.warehouse_id, inv.sku_id, inv.batch_no, inv.locked_qty, inv.updated_at,
            UNATTRIBUTED_LOCK_MAX_AGE_DAYS,
        )
        units_released += _clear_reservation(
            db, inv, reason=f"unattributed and idle for over {UNATTRIBUTED_LOCK_MAX_AGE_DAYS} days"
        )
        unattributed_released += 1

    # The rest are deliberately left alone, and said out loud: a lock we refuse
    # to release is stock someone should be told is short, not a row to hide.
    held = await db.scalar(
        select(func.count()).select_from(WMS_Inventory).where(
            WMS_Inventory.locked_qty > 0,
            WMS_Inventory.order_id.is_(None),
            or_(WMS_Inventory.updated_at.is_(None), WMS_Inventory.updated_at >= cutoff),
        )
    )
    held = int(held or 0)
    if held:
        logger.warning(
            "%d locked inventory row(s) have no order_id and are newer than %d days "
            "(or undated); left reserved — see tasks.inventory.release_locked",
            held, UNATTRIBUTED_LOCK_MAX_AGE_DAYS,
        )

    await db.flush()
    return {
        "released_count": released,
        "units_released": str(units_released),
        "unattributed_released_count": unattributed_released,
        "unattributed_locks_held": held,
    }


@celery.task(bind=True, base=BaseTask, name="tasks.inventory.release_locked")
async def release_locked_inventory_for_cancelled_orders(self) -> dict:
    """Release locked inventory held by cancelled orders.

    Scoped, and only as broad as its evidence: a reservation is freed when its
    order is cancelled, or when it belongs to no order and has been idle past
    UNATTRIBUTED_LOCK_MAX_AGE_DAYS.  Unattributed locks younger than that are
    reported in ``unattributed_locks_held`` instead of being unlocked — the old
    behaviour was a blanket "order_id IS NULL" sweep on every run, which silently
    released whatever a concurrent allocation had just reserved.
    """

    async with async_session_factory() as session:
        summary = await release_locked_inventory(session)
        await session.commit()

    return summary


@celery.task(bind=True, base=BaseTask, name="tasks.order.cancel_expired")
async def cancel_expired_orders(self) -> dict:
    """Cancel orders that have been pending too long."""

    async with async_session_factory() as session:
        cutoff = datetime.now(UTC).replace(tzinfo=None)
        from datetime import timedelta
        cutoff -= timedelta(days=7)
        result = await session.execute(
            select(_Order).where(
                _Order.status == _order_status.PENDING,
                _Order.created_at < cutoff,
            )
        )
        old_orders = result.scalars().all()

        count = 0
        for order in old_orders:
            try:
                order.status = _order_status.CANCELLED
                count += 1
            except Exception:
                logger.exception("Failed to cancel order %s", order.id)

        await session.commit()
    return {"cancelled_count": count}


@celery.task(bind=True, base=BaseTask, name="tasks.order.process_pending")
async def process_pending_orders(self) -> dict:
    """Auto-confirm pending orders after a grace period."""
    from datetime import UTC, datetime, timedelta

    async with async_session_factory() as session:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        result = await session.execute(
            select(_Order).where(
                _Order.status == _order_status.PENDING,
                _Order.created_at < cutoff,
            )
        )
        ready = result.scalars().all()

        count = 0
        for order in ready:
            try:
                order.status = _order_status.CONFIRMED
                count += 1
            except Exception:
                logger.exception("Failed to auto-confirm order %s", order.id)

        await session.commit()
    return {"processed_count": count}
