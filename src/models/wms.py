"""WMS Stock In / Out / Inventory Log models."""
import uuid as _uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import UUID, Column, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import relationship

from src.models.base import Base
from src.models.wms_enum import StockInType, StockOutType

# ── Stock In ────────────────────────────────────────────────────────


class StockIn(Base):
    """Warehouse inbound receipt.

    Schema:
        id              UUID PK
        warehouse_id    FK → warehouses.id
        type            str          INBOUND_* enum value
        reference_type  str | None   PO / SO / WO id (nullable)
        ref_no          str | None   external doc number
        supplier_id     FK → vendors.id | None
        total_qty       Decimal      sum of all line quantities
        status          str          DRAFT, CONFIRMED, RECEIVED, CANCELLED

    Lifecycle:
        1. Operator creates a StockIn (DRAFT) with SKU lines
        2. Confirm → stock reservation is made
        3. Receive → inventory batches are created / updated
    """

    __tablename__ = "stock_in"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    type = Column(String(32), nullable=False, default=StockInType.PURCHASE.value)

    reference_type = Column(String(64), nullable=True)  # e.g. 'purchase_order'
    ref_no = Column(String(100), nullable=True)         # external doc number

    supplier_id = Column(UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=True)

    total_qty = Column(Numeric(precision=18, scale=4), default=Decimal(0))
    status = Column(String(32), default="DRAFT")  # DRAFT CONFIRMED RECEIVED CANCELLED

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    lines = relationship(
        "StockInLine", back_populates="stock_in", cascade="all, delete-orphan"
    )


class StockInLine(Base):
    """Line item of a stock-in.

    Schema:
        id              UUID PK
        stock_in_id     FK → stock_in.id
        sku             str | None  product identifier (nullable for ad-hoc)
        qty_received    Decimal     quantity actually received
        batch_no        str | None
        lot_no          str | None
        expiry_date     date | None
        metadata_       JSONB       custom fields
    """

    __tablename__ = "stock_in_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    stock_in_id = Column(
        UUID(as_uuid=True), ForeignKey("stock_in.id", ondelete="CASCADE"), nullable=False
    )
    sku = Column(String(64), nullable=True)
    qty_received = Column(Numeric(precision=18, scale=4), default=Decimal(0))

    batch_no = Column(String(64), nullable=True)
    lot_no = Column(String(64), nullable=True)
    expiry_date = Column(DateTime(timezone=True), nullable=True)

    metadata_ = Column("metadata", String(length=1024), nullable=True)

    stock_in = relationship("StockIn", back_populates="lines")


# ── Stock Out ───────────────────────────────────────────────────────


class StockOut(Base):
    """Warehouse outbound shipment.

    Schema:
        id              UUID PK
        warehouse_id    FK → warehouses.id
        type            str          SALE / TRANSFER_OUT / ADJUSTMENT
        total_qty       Decimal      sum of all line quantities
        status          str          DRAFT, CONFIRMED, SHIPPED, CANCELLED

    Lifecycle:
        1. Operator creates StockOut (DRAFT) with SKU lines
        2. Confirm → stock reservation is made (InventoryReservation rows created)
        3. Ship → inventory batches are deducted
    """

    __tablename__ = "stock_out"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    type = Column(String(32), nullable=False, default=StockOutType.SALE.value)

    reference_type = Column(String(64), nullable=True)  # e.g. 'sales_order'
    ref_no = Column(String(100), nullable=True)         # external doc number

    total_qty = Column(Numeric(precision=18, scale=4), default=Decimal(0))
    status = Column(String(32), default="DRAFT")  # DRAFT CONFIRMED SHIPPED CANCELLED

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    lines = relationship(
        "StockOutLine", back_populates="stock_out", cascade="all, delete-orphan"
    )


class StockOutLine(Base):
    """Line item of a stock-out.

    Schema:
        id              UUID PK
        stock_out_id    FK → stock_out.id
        sku             str | None  product identifier (nullable for ad-hoc)
        qty_shipped     Decimal     quantity actually shipped
        batch_no        str | None
        lot_no          str | None
        expiry_date     date | None
        metadata_       JSONB       custom fields
    """

    __tablename__ = "stock_out_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    stock_out_id = Column(
        UUID(as_uuid=True), ForeignKey("stock_out.id", ondelete="CASCADE"), nullable=False
    )
    sku = Column(String(64), nullable=True)
    qty_shipped = Column(Numeric(precision=18, scale=4), default=Decimal(0))

    batch_no = Column(String(64), nullable=True)
    lot_no = Column(String(64), nullable=True)
    expiry_date = Column(DateTime(timezone=True), nullable=True)

    metadata_ = Column("metadata", String(length=1024), nullable=True)

    stock_out = relationship("StockOut", back_populates="lines")


# ── Inventory Log ───────────────────────────────────────────────────


class InventoryLogType(StrEnum):
    """Types of inventory movements."""

    INBOUND = "INBOUND"              # 入库 (StockIn confirmed/received)
    OUTBOUND = "OUTBOUND"            # 出库 (StockOut confirmed/shipped)
    ADJUSTMENT_IN = "ADJUSTMENT_IN"   # 盘盈 (stock increase)
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT" # 盘亏 (stock decrease)


class StockInventoryLog(Base):
    """Audit trail for stock in/out inventory changes.

    Schema:
        id                  UUID PK
        warehouse_id        FK → warehouses.id
        sku                 str          affected product
        type                str          INBOUND / OUTBOUND / ADJUSTMENT_IN / ADJUSTMENT_OUT
        reference_type      str | None   source entity (e.g. 'stock_in')
        reference_id        UUID | None  id of the source entity
        quantity_change     Decimal      +ve = in, -ve = out
        operator            FK → users.id | None
        reason              AdjustReason | None
        remark              str | None
    """

    __tablename__ = "stock_inventory_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    sku = Column(String(64), nullable=False)
    type = Column(String(32), nullable=False)  # INBOUND / OUTBOUND / ADJUSTMENT_IN / ADJUSTMENT_OUT

    reference_type = Column(String(64), nullable=True)  # e.g. 'stock_in'
    reference_id = Column(UUID(as_uuid=True), nullable=True)

    quantity_change = Column(Numeric(precision=18, scale=4), nullable=False)
    operator_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reason = Column(String(32), nullable=True)  # AdjustReason enum value
    remark = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
