"""Inventory FEFO/FIFO — Batch-level inventory tracking.

Design
------
Every inbound receipt creates a *lot/batch* row with its own expiry date.
When an outbound order is fulfilled, the system allocates stock from batches
using FIFO (First In First Out) or FEFO (First Expired First Out):

    FIFO  → allocate earliest `received_at` first          (for non-expiry goods)
    FEFO  → allocate earliest `expiry_date` first         (perishables, pharma)

Reservation model: orders don't immediately deduct stock; they create a
reservation that holds the allocated batch + qty. When the order ships,
the reservation is consumed and inventory is permanently deducted.

Key concepts:
    InventoryBatch   — physical lot with expiry info
    InventoryReservation  — pending allocation (order → batch)
    AllocationStrategy  — FIFO / FEFO / LIFO configurable per SKU/warehouse
"""
import uuid as _uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import UUID, Column, DateTime, ForeignKey, Numeric, String, select, update
from sqlalchemy import Date as SA_Date
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base


class InsufficientStockError(Exception):
    """Raised when inventory is insufficient for allocation."""

    def __init__(self, sku: str, warehouse_id: str, needed):
        super().__init__(f"SKU {sku} at warehouse {warehouse_id}: need {needed}, insufficient stock")


class AllocationStrategy(StrEnum):
    """Batch picking strategy."""

    FIFO = "fifo"       # First In First Out (earliest received_at)
    FEFO = "fefo"       # First Expired First Out (earliest expiry_date)
    LIFO = "lifo"       # Last In First Out (latest received_at)


class ReservationStatus(StrEnum):
    PENDING = "pending"          # Created but not shipped
    SHIPPED = "shipped"         # Allocated → physically gone
    CANCELLED = "cancelled"     # Reverted back to available


# ── Batch model ────────────────────────────────────────────────────────


class InventoryBatch(Base):
    """Physical inventory batch (lot).

    Schema:
        id              UUID PK
        warehouse_id    FK → warehouses.id
        sku             str          product identifier
        qty_on_hand     Decimal      current available quantity
        reserved_qty    Decimal      locked by reservations
        received_at     datetime     inbound receipt timestamp
        expiry_date     date | None  null for non-expiry products
        manufacturer    str | None   lot origin (traceability)
        supplier_name   str | None
        metadata_       JSONB       custom fields (lot_no, etc.)

    Business rules:
        - qty_on_hand >= reserved_qty always holds (enforced by service layer)
        - FEFO batches are sorted by expiry_date ASC NULLS FIRST for picklists
        - FIFO batches sorted by received_at ASC
    """

    __tablename__ = "inventory_batches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    sku = Column(String(64), nullable=False)
    qty_on_hand = Column(Numeric(precision=18, scale=4), nullable=False, default=Decimal(0))
    reserved_qty = Column(Numeric(precision=18, scale=4), nullable=False, default=Decimal(0))

    received_at = Column(DateTime(timezone=True), nullable=False)
    expiry_date = Column(SA_Date, nullable=True)
    manufacturer = Column(String(256), nullable=True)
    supplier_name = Column(String(256), nullable=True)
    metadata_ = Column("metadata", JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


# ── Reservation model ──────────────────────────────────────────────────


class InventoryReservation(Base):
    """Holds stock allocation from a batch to an order line.

    Schema:
        id              UUID PK
        warehouse_id    FK → warehouses.id
        sku             str
        batch_id        FK → inventory_batches.id
        quantity        Decimal      amount reserved from this batch
        status          ReservationStatus  PENDING / SHIPPED / CANCELLED
        order_line_id   FK → order_lines.id (nullable — orphaned if cancelled)
        created_at      datetime

    Lifecycle:
        1. AllocationService.allocate() creates a reservation row
        2. When order ships, InventoryService.consume_reservation() deducts qty_on_hand
        3. If order is cancelled, InventoryService.release_reservation() restores stock
    """

    __tablename__ = "inventory_reservations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    sku = Column(String(64), nullable=False)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("inventory_batches.id"))
    quantity = Column(Numeric(precision=18, scale=4), nullable=False)
    status = Column(String(32), default=ReservationStatus.PENDING.value)

    order_line_id = Column(
        UUID(as_uuid=True), ForeignKey("order_lines.id"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


# ── Allocation service ─────────────────────────────────────────────────


class AllocationService:
    """Reserve stock from batches using FIFO/FEFO strategy."""

    def __init__(self, session):  # SQLAlchemy async session
        self.session = session

    async def allocate(
        self,
        warehouse_id: _uuid.UUID,
        sku: str,
        quantity_needed: Decimal,
        strategy: AllocationStrategy = AllocationStrategy.FIFO,
    ) -> list[dict]:
        """Allocate stock from batches using the configured strategy.

        Returns a list of allocations {batch_id, allocated_qty}.
        Raises InsufficientStockError if total available < quantity_needed.
        """
        # 1) Fetch available batches ordered by strategy
        query = select(InventoryBatch).where(
            InventoryBatch.warehouse_id == warehouse_id,
            InventoryBatch.sku == sku,
            InventoryBatch.qty_on_hand > InventoryBatch.reserved_qty,
        )

        if strategy == AllocationStrategy.FIFO:
            query = query.order_by(InventoryBatch.received_at)
        elif strategy == AllocationStrategy.FEFO:
            # FEFO: earliest expiry_date first; NULLs first (non-expiry products picked before safe stock)
            query = query.order_by(
                InventoryBatch.expiry_date.nulls_first()
            )

        batches = list((await self.session.execute(query)).scalars().all())

        # 2) Greedily allocate from each batch until satisfied
        allocations = []
        remaining = quantity_needed

        for batch in batches:
            if remaining <= Decimal(0):
                break

            available = batch.qty_on_hand - batch.reserved_qty
            to_allocate = min(remaining, available)
            if to_allocate <= Decimal(0):
                continue

            # Create reservation and update batch
            reservation = InventoryReservation(
                warehouse_id=warehouse_id,
                sku=sku,
                batch_id=batch.id,
                quantity=to_allocate,
                status=ReservationStatus.PENDING.value,
            )
            self.session.add(reservation)

            await self.session.execute(
                update(InventoryBatch)
                .where(InventoryBatch.id == batch.id)
                .values(reserved_qty=batch.reserved_qty + to_allocate)
            )

            allocations.append({
                "batch_id": str(batch.id),
                "allocated_qty": str(to_allocate),
            })
            remaining -= to_allocate

        if remaining > Decimal(0):
            raise InsufficientStockError(
                sku=sku, warehouse_id=str(warehouse_id), needed=quantity_needed
            )

        await self.session.commit()
        return allocations


# ── Inventory consumption / release (for order ship/cancel) ───────────────


async def consume_reservation(session, reservation_id: _uuid.UUID) -> None:
    """Mark a reservation as shipped and permanently deduct inventory."""
    res = await session.get(InventoryReservation, reservation_id)
    if not res or res.status != ReservationStatus.PENDING.value:
        return

    # Deduct batch qty
    batch = await session.get(InventoryBatch, res.batch_id)
    await session.execute(
        update(InventoryBatch).where(InventoryBatch.id == batch.id).values(
            qty_on_hand=batch.qty_on_hand - res.quantity,
            reserved_qty=batch.reserved_qty - res.quantity,
        )
    )

    # Mark reservation shipped
    await session.execute(
        update(InventoryReservation).where(InventoryReservation.id == reservation_id).values(
            status=ReservationStatus.SHIPPED.value,
        )
    )
    await session.commit()


async def release_reservation(session, reservation_id: _uuid.UUID) -> None:
    """Cancel a reservation and restore batch inventory."""
    res = await session.get(InventoryReservation, reservation_id)
    if not res or res.status != ReservationStatus.PENDING.value:
        return

    # Restore batch qty
    batch = await session.get(InventoryBatch, res.batch_id)
    await session.execute(
        update(InventoryBatch).where(InventoryBatch.id == batch.id).values(
            qty_on_hand=batch.qty_on_hand - res.quantity,
            reserved_qty=batch.reserved_qty - res.quantity,
        )
    )

    # Mark reservation cancelled
    await session.execute(
        update(InventoryReservation).where(InventoryReservation.id == reservation_id).values(
            status=ReservationStatus.CANCELLED.value,
        )
    )
    await session.commit()


# ── Batch expiry scan (FEFO compliance) ─────────────────────────────────


async def find_expired_batches(session, warehouse_id: _uuid.UUID, days_early: int = 7) -> list[InventoryBatch]:
    """Find batches approaching expiry within `days_early` window.

    Used by warehouse operators to run FEFO compliance reports.
    """
    cutoff_date = date.today() + timedelta(days=days_early)
    result = await session.execute(
        select(InventoryBatch).where(
            InventoryBatch.warehouse_id == warehouse_id,
            InventoryBatch.expiry_date <= cutoff_date,
            InventoryBatch.qty_on_hand > 0,
        )
    )
    return list(result.scalars().all())
