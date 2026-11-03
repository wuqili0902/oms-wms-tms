"""Tests for the cancelled-order stock release (src/tasks/inventory.py).

The file that used to cover this was skipped outright — "Requires PostgreSQL
(async_session_factory)" — which is precisely why the release rules stayed wrong:
they only ever ran on a schedule, against real stock, with nobody checking what
they did to it.  The database work now lives in ``release_locked_inventory(db)``,
so these tests use the same SQLite session the rest of the WMS suite uses.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from src.models.shared_models import Customer
from src.oms.models import Order, OrderStatus
from src.tasks.inventory import UNATTRIBUTED_LOCK_MAX_AGE_DAYS, release_locked_inventory
from src.wms.models import SKU, Inventory, InventoryChangeType, InventoryLog, Warehouse


def _now() -> datetime:
    """Naive UTC, the way TimestampMixin stores it."""
    return datetime.now(UTC).replace(tzinfo=None)


async def _warehouse_and_sku(db, tag: str):
    wh = Warehouse(id=uuid.uuid4(), code=f"REL-WH-{tag}", name="Release Warehouse")
    sku = SKU(id=uuid.uuid4(), sku=f"REL-SKU-{tag}", name="Release SKU")
    db.add_all([wh, sku])
    await db.flush()
    return wh, sku


async def _order(db, status: OrderStatus, tag: str) -> Order:
    customer = Customer(id=uuid.uuid4(), code=f"REL-CUST-{tag}", name="Release Customer")
    order = Order(
        id=uuid.uuid4(),
        order_no=f"REL-{tag}-{uuid.uuid4().hex[:8]}",
        status=status,
        customer_id=customer.id,
        items={},
        total_amount=Decimal("0"),
    )
    db.add_all([customer, order])
    await db.flush()
    return order


async def _locked_stock(
    db,
    wh: Warehouse,
    sku: SKU,
    *,
    quantity: str,
    locked: str,
    order_id=None,
    idle_days: float | None = 0.0,
    undated: bool = False,
) -> Inventory:
    """One reserved inventory row.

    ``idle_days`` sets how long the row has been untouched, which is the only
    evidence the unattributed sweep is allowed to act on.  ``idle_days=None``
    leaves the row dated "now" (the TimestampMixin default).
    """
    inv = Inventory(
        id=uuid.uuid4(),
        warehouse_id=wh.id,
        sku_id=sku.id,
        order_id=order_id,
        gtin="0000000000000",
        batch_no=f"REL-{uuid.uuid4().hex[:6]}",
        quantity=Decimal(quantity),
        locked_qty=Decimal(locked),
        min_qty=Decimal("0"),
        max_qty=Decimal("0"),
    )
    if idle_days is not None:
        inv.updated_at = _now() - timedelta(days=idle_days)
    db.add(inv)
    await db.flush()
    if undated:
        # Explicitly assigned, so the mixin's onupdate does not quietly re-date it.
        inv.updated_at = None
        await db.flush()
    return inv


async def _logs_for(db, inventory_id) -> list[InventoryLog]:
    result = await db.execute(
        select(InventoryLog).where(InventoryLog.inventory_id == inventory_id)
    )
    return list(result.scalars().all())


class TestCancelledOrderReservation:
    async def test_reservation_is_cleared_without_inventing_stock(self, db_session):
        """The defect this whole release existed to avoid.

        quantity is on-hand stock and locked_qty is the slice of it an order
        claimed, so cancelling must clear the claim and leave the shelf alone.
        Adding the locked amount back onto quantity made availability jump from
        70 to 100 out of thin air.
        """
        wh, sku = await _warehouse_and_sku(db_session, "CANCEL")
        order = await _order(db_session, OrderStatus.CANCELLED, "CANCEL")
        inv = await _locked_stock(
            db_session, wh, sku, quantity="100", locked="30", order_id=order.id
        )

        summary = await release_locked_inventory(db_session)

        await db_session.refresh(inv)
        assert inv.locked_qty == Decimal("0"), "the cancelled order's claim should be gone"
        assert inv.quantity == Decimal("100"), (
            "on-hand stock must not change: a released reservation is not a delivery"
        )
        assert summary["released_count"] == 1
        assert Decimal(summary["units_released"]) == Decimal("30")

    async def test_reservation_for_a_live_order_is_left_reserved(self, db_session):
        wh, sku = await _warehouse_and_sku(db_session, "LIVE")
        order = await _order(db_session, OrderStatus.CONFIRMED, "LIVE")
        inv = await _locked_stock(
            db_session, wh, sku, quantity="100", locked="30", order_id=order.id
        )

        summary = await release_locked_inventory(db_session)

        await db_session.refresh(inv)
        assert inv.locked_qty == Decimal("30"), "a live order's stock is not this task's to free"
        assert inv.quantity == Decimal("100")
        assert summary["released_count"] == 0

    async def test_release_leaves_an_audit_row_naming_the_order(self, db_session):
        wh, sku = await _warehouse_and_sku(db_session, "AUDIT")
        order = await _order(db_session, OrderStatus.CANCELLED, "AUDIT")
        inv = await _locked_stock(
            db_session, wh, sku, quantity="50", locked="12", order_id=order.id
        )

        await release_locked_inventory(db_session)

        logs = await _logs_for(db_session, inv.id)
        assert len(logs) == 1, "a release that leaves no trace is untraceable"
        log = logs[0]
        assert log.change_type == InventoryChangeType.ADJUSTMENT
        assert log.reference_type == "inventory_release"
        assert log.reference_id == order.id
        # Honest bookkeeping: the on-hand quantity did not move, and the log says
        # so rather than faking a delta.
        assert log.quantity_change == Decimal("0")
        assert log.quantity_before == Decimal("50")
        assert log.quantity_after == Decimal("50")
        assert "12" in log.remark and "available 38 -> 50" in log.remark

    async def test_second_run_frees_nothing(self, db_session):
        wh, sku = await _warehouse_and_sku(db_session, "TWICE")
        order = await _order(db_session, OrderStatus.CANCELLED, "TWICE")
        await _locked_stock(db_session, wh, sku, quantity="20", locked="5", order_id=order.id)

        first = await release_locked_inventory(db_session)
        second = await release_locked_inventory(db_session)

        assert first["released_count"] == 1
        assert second["released_count"] == 0
        assert second["unattributed_released_count"] == 0


class TestUnattributedLocks:
    async def test_stale_unattributed_lock_is_released_and_logged(self, db_session, caplog):
        wh, sku = await _warehouse_and_sku(db_session, "STALE")
        inv = await _locked_stock(
            db_session, wh, sku, quantity="40", locked="8",
            idle_days=UNATTRIBUTED_LOCK_MAX_AGE_DAYS + 1,
        )

        with caplog.at_level("WARNING"):
            summary = await release_locked_inventory(db_session)

        await db_session.refresh(inv)
        assert inv.locked_qty == Decimal("0")
        assert inv.quantity == Decimal("40")
        assert summary["unattributed_released_count"] == 1
        assert summary["released_count"] == 0, "cancelled-order count must stay separate"
        # A lock nobody can account for is itself the finding; silently dropping
        # it is how the row disappears from the audit trail.
        assert any("unattributed" in rec.message.lower() for rec in caplog.records)

        logs = await _logs_for(db_session, inv.id)
        assert len(logs) == 1
        assert logs[0].reference_type == "inventory_release"
        assert logs[0].reference_id is None

    async def test_fresh_unattributed_lock_is_held_not_released(self, db_session):
        """The blanket sweep this replaces ran on every schedule tick.

        A lock created moments ago is either a live allocation or a bug being
        fixed; unlocking it on a timer hands the same stock to the next order.
        """
        wh, sku = await _warehouse_and_sku(db_session, "FRESH")
        inv = await _locked_stock(db_session, wh, sku, quantity="40", locked="8", idle_days=0)

        summary = await release_locked_inventory(db_session)

        await db_session.refresh(inv)
        assert inv.locked_qty == Decimal("8"), "a young unexplained lock is evidence, not leftover"
        assert summary["unattributed_released_count"] == 0
        assert summary["unattributed_locks_held"] == 1

    async def test_undated_unattributed_lock_is_held_and_reported(self, db_session, caplog):
        """No date means no evidence, and no evidence means no release."""
        wh, sku = await _warehouse_and_sku(db_session, "UNDATED")
        inv = await _locked_stock(
            db_session, wh, sku, quantity="40", locked="8", idle_days=None, undated=True
        )

        with caplog.at_level("WARNING"):
            summary = await release_locked_inventory(db_session)

        await db_session.refresh(inv)
        assert inv.updated_at is None
        assert inv.locked_qty == Decimal("8")
        assert summary["unattributed_released_count"] == 0
        assert summary["unattributed_locks_held"] == 1
        assert any("no order_id" in rec.message for rec in caplog.records)

    async def test_locks_are_examined_even_with_no_cancelled_orders(self, db_session):
        """The old code returned before it ever looked at unattributed locks.

        ``if not order_ids: return {"released_count": 0}`` meant a stale leftover
        was only ever noticed on a run that happened to have a cancelled order —
        so the report below has to stand on its own.
        """
        wh, sku = await _warehouse_and_sku(db_session, "NOORDER")
        await _locked_stock(
            db_session, wh, sku, quantity="10", locked="4",
            idle_days=UNATTRIBUTED_LOCK_MAX_AGE_DAYS + 3,
        )

        summary = await release_locked_inventory(db_session)

        assert summary["released_count"] == 0
        assert summary["unattributed_released_count"] == 1

    async def test_each_lock_is_counted_for_why_it_went(self, db_session):
        """One run, three kinds of lock, three different answers."""
        wh, sku = await _warehouse_and_sku(db_session, "MIXED")
        cancelled = await _order(db_session, OrderStatus.CANCELLED, "MIXED")
        await _locked_stock(db_session, wh, sku, quantity="100", locked="10", order_id=cancelled.id)
        await _locked_stock(
            db_session, wh, sku, quantity="100", locked="20",
            idle_days=UNATTRIBUTED_LOCK_MAX_AGE_DAYS + 1,
        )
        await _locked_stock(db_session, wh, sku, quantity="100", locked="30", idle_days=0)

        summary = await release_locked_inventory(db_session)

        assert summary["released_count"] == 1
        assert summary["unattributed_released_count"] == 1
        assert summary["unattributed_locks_held"] == 1
        assert Decimal(summary["units_released"]) == Decimal("30")


class TestTaskWiring:
    async def test_celery_task_keeps_the_name_the_beat_schedule_calls(self):
        """celery_app's beat schedule and this decorator agree on the name only by
        spelling; a rename silently stops the scheduled release."""
        from src.tasks.inventory import release_locked_inventory_for_cancelled_orders

        assert release_locked_inventory_for_cancelled_orders.name == "tasks.inventory.release_locked"
