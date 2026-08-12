"""WMS (Warehouse Management System) domain models.

This module contains all SQLAlchemy 2.0 ORM models for the Warehouse Management System,
including warehouses, locations, inventory management, stock movements, and picking waves.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class WarehouseType(Enum):
    """Enumeration of warehouse types."""

    CENTER = "center"
    REGIONAL = "regional"
    FRONT = "front"


class WarehouseStatus(Enum):
    """Enumeration of warehouse operational statuses."""

    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    CLOSED = "closed"


class LocationType(Enum):
    """Enumeration of location types within a warehouse."""

    STORAGE = "storage"
    PICKING = "picking"
    RECEIVING = "receiving"
    SHIPPING = "shipping"
    QUARANTINE = "quarantine"


class LocationStatus(Enum):
    """Enumeration of location statuses."""

    ACTIVE = "active"
    RESERVED = "reserved"
    MAINTENANCE = "maintenance"
    CLOSED = "closed"


class InventoryChangeType(Enum):
    """Enumeration of inventory change types for audit logging."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"
    ADJUSTMENT = "adjustment"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    PICKING = "picking"
    RETURNED = "returned"


class StockMovementType(Enum):
    """Enumeration of stock movement types."""

    TRANSFER = "transfer"
    REPLENISHMENT = "replenishment"
    RETURN = "return"


class PickingWaveType(Enum):
    """Enumeration of picking wave types."""

    ORDER_BASED = "order_based"
    TIME_BASED = "time_based"
    LOCATION_BASED = "location_based"
    MIXED = "mixed"


class PickingWavePriority(Enum):
    """Enumeration of picking wave priority levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


# ── Transfer Order ───────────────────────────────────────────────────────────

__ALL_TRANSFER_STATUSES: tuple[str] = (
    "DRAFT", "CONFIRMED", "IN_TRANSIT", "DELIVERED", "CANCELLED",
)


class TransferStatus(StrEnum):
    """Transfer order lifecycle states."""

    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TransferItemType(StrEnum):
    """Types of items that can appear in a transfer order line."""

    SKU = "SKU"
    LOCATION = "LOCATION"
    WAREHOUSE = "WAREHOUSE"


# ── Warehouse (re-defined below, after all dependencies) ────────────────────


class Warehouse(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Warehouse model representing a storage facility.

    Stores warehouse configuration including type, operational status, and contact information.
    """

    __tablename__ = "warehouses"

    code: str = Column(String(50), unique=True, index=True)
    name: str = Column(String(200), nullable=False)
    warehouse_type: WarehouseType = Column(SAEnum(WarehouseType))
    status: WarehouseStatus = Column(SAEnum(WarehouseStatus), default=WarehouseStatus.ACTIVE)
    address: dict = Column(JSON)
    contact: str | None = Column(String(100))
    phone: str | None = Column(String(30))
    config: dict | None = Column(JSON, nullable=True)

    locations: list = relationship("Location", back_populates="warehouse")
    inventory: list = relationship("Inventory", back_populates="warehouse")
    stock_movements: list = relationship(
        "StockMovement", foreign_keys="StockMovement.source_warehouse_id", back_populates="source_warehouse"
    )
    picking_waves: list = relationship("PickingWave", back_populates="warehouse")

    __table_args__ = (
        Index("ix_warehouses_status", "status"),
    )

    def __repr__(self):
        return f"<Warehouse {self.code}: {self.name}>"


class Location(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Location model representing a specific storage position within a warehouse.

    Provides granular location tracking for inventory management and picking operations.
    """

    __tablename__ = "locations"

    warehouse_id: UUID = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    code: str = Column(String(50), unique=True, index=True)
    zone: str | None = Column(String(20))
    aisle: str | None = Column(String(10))
    shelf: str | None = Column(String(10))
    level: str | None = Column(String(10))
    position: str | None = Column(String(50))
    location_type: LocationType = Column(SAEnum(LocationType), default=LocationType.STORAGE)
    status: LocationStatus = Column(SAEnum(LocationStatus), default=LocationStatus.ACTIVE)

    warehouse: Warehouse = relationship("Warehouse", back_populates="locations")
    inventory_items: list = relationship("Inventory", back_populates="location")

    __table_args__ = (
        Index("ix_locations_warehouse_id_zone", "warehouse_id", "zone"),
    )

    def __repr__(self):
        return f"<Location {self.code}: {self.zone}/{self.aisle}/{self.shelf}>"


class SKU(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """SKU (Stock Keeping Unit) model for product identification.

    Centralizes product information across all warehouse operations.
    """

    __tablename__ = "skus"

    sku: str = Column(String(50), unique=True, index=True)
    gtin: str | None = Column(String(13))
    name: str | None = Column(String(200))
    description: str | None = Column(Text)
    category: str | None = Column(String(100))
    manufacturer: str | None = Column(String(200))
    weight_kg: Decimal | None = Column(Numeric(12, 4), nullable=True)
    volume_m3: Decimal | None = Column(Numeric(12, 6), nullable=True)
    hs_code: str | None = Column(String(12), nullable=True)
    unit_of_measure: str | None = Column(String(10), nullable=True)

    inventory_items: list = relationship("Inventory", back_populates="sku")
    order_items: list = relationship("OrderItem", overlaps="sku")

    __table_args__ = (
        Index("ix_skus_gtin", "gtin"),
    )

    def __repr__(self):
        return f"<SKU {self.sku}>"


class Inventory(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Inventory model tracking stock levels at specific warehouse locations.

    Maintains real-time inventory counts with batch-level tracking and quantity limits.
    """

    __tablename__ = "inventory"

    warehouse_id: UUID = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"), index=True)
    location_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True)
    sku_id: UUID = Column(UUID(as_uuid=True), ForeignKey("skus.id"), index=True)
    gtin: str = Column(String(13), index=True)
    batch_no: str = Column(String(50), index=True)
    quantity: Decimal = Column(Numeric(20, 4), default=Decimal("0"))
    locked_qty: Decimal = Column(Numeric(20, 4), default=Decimal("0"))
    min_qty: Decimal = Column(Numeric(18, 4), default=Decimal("0"))
    max_qty: Decimal = Column(Numeric(18, 4), default=Decimal("0"))
    version: int = Column(Integer, default=0)
    expiry_date: date | None = Column(Date, nullable=True)
    manufacturing_date: date | None = Column(Date, nullable=True)
    received_at: datetime | None = Column(DateTime(timezone=True), nullable=True)

    warehouse: Warehouse = relationship("Warehouse", back_populates="inventory")
    location: Location | None = relationship("Location", back_populates="inventory_items")
    sku: SKU = relationship("SKU", back_populates="inventory_items")
    inventory_logs: list = relationship("InventoryLog", back_populates="inventory")

    __table_args__ = (
        Index("ix_inventory_warehouse_id_sku_id", "warehouse_id", "sku_id"),
    )

    def __repr__(self):
        return f"<Inventory sku={self.sku_id} batch={self.batch_no}: qty={self.quantity}>"


class InventoryLog(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Audit log for all inventory changes.

    Provides complete traceability of every quantity change to the inventory records.
    """

    __tablename__ = "inventory_logs"

    inventory_id: UUID = Column(UUID(as_uuid=True), ForeignKey("inventory.id"), index=True)
    change_type: InventoryChangeType = Column(SAEnum(InventoryChangeType))
    quantity_change: Decimal = Column(Numeric(20, 4))
    quantity_before: Decimal = Column(Numeric(20, 4))
    quantity_after: Decimal = Column(Numeric(20, 4))
    reference_type: str | None = Column(String(50), nullable=True)
    reference_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)
    operator_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    remark: str | None = Column(Text, nullable=True)

    inventory: Inventory = relationship("Inventory", back_populates="inventory_logs")
    operator: Optional["User"] = relationship("User")  # noqa: F821

    __table_args__ = (
        Index(
            "ix_inventory_logs_inventory_id_created_at",
            "inventory_id",
            "created_at",
        ),
        Index(
            "ix_inventory_logs_reference_type_reference_id",
            "reference_type",
            "reference_id",
        ),
    )

    def __repr__(self):
        return f"<InventoryLog {self.change_type.value}: qty_change={self.quantity_change}>"


class ReferenceEntity(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Generic reference entity for linking inventory logs to external systems.

    Provides polymorphic relationships between inventory logs and various system entities.
    """

    __tablename__ = "reference_entities"

    reference_type: str = Column(String(50), index=True)
    reference_id: UUID = Column(UUID(as_uuid=True), index=True)
    entity_data: dict = Column(JSON, nullable=True)

    __table_args__ = (
        Index(
            "ix_reference_entities_type_id",
            "reference_type",
            "reference_id",
            unique=True,
        ),
    )

    def __repr__(self):
        return f"<ReferenceEntity type={self.reference_type} id={self.reference_id}>"


class StockMovement(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Stock movement tracking for inter-warehouse transfers and replenishment.

    Records all movements of stock between warehouses or locations with full audit trail.
    """

    __tablename__ = "stock_movements"

    source_warehouse_id: UUID = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    target_warehouse_id: UUID | None = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=True
    )
    source_location_id: UUID | None = Column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True
    )
    target_location_id: UUID | None = Column(
        UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True
    )
    sku_id: UUID = Column(UUID(as_uuid=True), ForeignKey("skus.id"))
    gtin: str = Column(String(13))
    quantity: Decimal = Column(Numeric(20, 4))
    movement_type: StockMovementType = Column(SAEnum(StockMovementType))
    status: str = Column(String(20), default="pending")

    source_warehouse: Warehouse = relationship("Warehouse", foreign_keys=[source_warehouse_id])
    target_warehouse: Warehouse | None = relationship("Warehouse", foreign_keys=[target_warehouse_id])
    sku: SKU = relationship("SKU")

    __table_args__ = (
        Index(
            "ix_stock_movements_gtin",
            "gtin",
        ),
        Index(
            "ix_stock_movements_status_created_at",
            "status",
            "created_at",
        ),
    )

    def __repr__(self):
        return f"<StockMovement {self.movement_type.value}: qty={self.quantity}>"


class PickingWave(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Picking wave for batch order processing.

    Groups orders into waves to optimize picking efficiency and resource allocation.
    """

    __tablename__ = "picking_waves"

    warehouse_id: UUID = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    code: str = Column(String(50), unique=True, index=True)
    status: str = Column(String(20), default="pending")
    wave_type: PickingWaveType = Column(SAEnum(PickingWaveType))
    priority: PickingWavePriority = Column(
        SAEnum(PickingWavePriority), default=PickingWavePriority.MEDIUM
    )
    total_items: int = Column(Integer, default=0)
    completed_items: int = Column(Integer, default=0)
    assignee_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)

    warehouse: Warehouse = relationship("Warehouse")

    __table_args__ = (
        Index("ix_picking_waves_status_created_at", "status", "created_at"),
    )

    def __repr__(self):
        return f"<PickingWave {self.code}: status={self.status}, items={self.total_items}>"


class ShipmentStatus(StrEnum):
    """Shipment lifecycle states."""

    PENDING = "pending"
    PICKED = "picked"
    PACKED = "packed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class PackingRecord(Base, UUIDMixin, TimestampMixin):
    """Record of which items were packed for a picking wave."""

    __tablename__ = "packing_records"

    picking_wave_id: UUID = Column(UUID(as_uuid=True), ForeignKey("picking_waves.id"), nullable=False)
    packed_by: str = Column(String(100), default="")
    box_count: int = Column(Integer, default=1)
    notes: str = Column(Text, default="")

    picking_wave: PickingWave = relationship("PickingWave")

    def __repr__(self):
        return f"<PackingRecord wave={self.picking_wave_id} boxes={self.box_count}>"


class Shipment(Base, UUIDMixin, TimestampMixin):
    """Outbound shipment tracking."""

    __tablename__ = "shipments"

    order_id: UUID = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    warehouse_id: UUID = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    packing_record_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("packing_records.id"), nullable=True)
    tracking_number: str = Column(String(100), default="")
    carrier: str = Column(String(50), default="")
    status: ShipmentStatus = Column(SAEnum(ShipmentStatus), default=ShipmentStatus.PENDING)
    shipped_at: str | None = Column(String(30), nullable=True)
    delivered_at: str | None = Column(String(30), nullable=True)
    notes: str = Column(Text, default="")

    warehouse: Warehouse = relationship("Warehouse")
    packing_record: PackingRecord | None = relationship("PackingRecord")

    def __repr__(self):
        return f"<Shipment tracking={self.tracking_number} status={self.status}>"


class Vendor(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Vendor / supplier master data."""

    __tablename__ = "vendors"

    code: str = Column(String(50), unique=True, index=True)
    name: str = Column(String(200), nullable=False)
    email: str = Column(String(255))
    phone: str = Column(String(50))
    is_active: bool = Column(Boolean, default=True)

    def __repr__(self):
        return f"<Vendor {self.code}: {self.name}>"


class Address(Base, UUIDMixin, TimestampMixin):
    """Address book for customers, vendors, and warehouses."""

    __tablename__ = "addresses"

    entity_type: str = Column(String(20), nullable=False, index=True)
    entity_id: UUID | None = Column(UUID(as_uuid=True), nullable=True, index=True)
    address_type: str = Column(String(20), nullable=False)
    contact_name: str = Column(String(100))
    phone: str = Column(String(30))
    email: str = Column(String(255))
    address_line_1: str = Column(String(255))
    address_line_2: str = Column(String(255))
    city: str = Column(String(100))
    state: str = Column(String(100))
    postal_code: str = Column(String(20))
    country: str = Column(String(100), default="中国")

    def __repr__(self):
        return f"<Address {self.entity_type}:{self.city}>"


class PurchaseOrder(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Purchase order to vendors."""

    __tablename__ = "purchase_orders"

    po_number: str = Column(String(50), unique=True, index=True)
    vendor_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=True)
    status: str = Column(String(20), default="draft")
    expected_date: date | None = Column(Date, nullable=True)
    notes: str = Column(Text)
    total_amount: Decimal = Column(Numeric(18, 2), default=Decimal("0"))

    lines: list = relationship("PurchaseOrderLine", back_populates="purchase_order", uselist=True)

    def __repr__(self):
        return f"<PurchaseOrder {self.po_number}: {self.status}>"


class PurchaseOrderLine(Base, UUIDMixin):
    """Line item within a purchase order."""

    __tablename__ = "purchase_order_lines"

    purchase_order_id: UUID = Column(UUID(as_uuid=True), ForeignKey("purchase_orders.id"))
    sku_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("skus.id"), nullable=True)
    description: str = Column(String(255))
    quantity: Decimal = Column(Numeric(18, 4), default=Decimal("1"))
    unit_price: Decimal = Column(Numeric(18, 4), default=Decimal("0"))

    purchase_order: PurchaseOrder = relationship("PurchaseOrder", back_populates="lines")

    def __repr__(self):
        return f"<POLine {self.description}: qty={self.quantity}>"


class Invoice(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Invoice record for customer billing or vendor payment."""

    __tablename__ = "invoices"

    invoice_number: str = Column(String(50), unique=True, index=True)
    entity_type: str = Column(String(20), nullable=False)
    entity_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)
    status: str = Column(String(20), default="draft")
    issue_date: date | None = Column(Date, nullable=True)
    due_date: date | None = Column(Date, nullable=True)
    total_amount: Decimal = Column(Numeric(18, 2), default=Decimal("0"))
    paid_amount: Decimal = Column(Numeric(18, 2), default=Decimal("0"))
    reference_number: str = Column(String(100))
    notes: str = Column(Text)

    lines: list = relationship("InvoiceLine", back_populates="invoice", uselist=True)

    def __repr__(self):
        return f"<Invoice {self.invoice_number}: {self.status}>"


class InvoiceLine(Base, UUIDMixin):
    """Line item within an invoice."""

    __tablename__ = "invoice_lines"

    invoice_id: UUID = Column(UUID(as_uuid=True), ForeignKey("invoices.id"))
    description: str = Column(String(255))
    quantity: Decimal = Column(Numeric(18, 4), default=Decimal("1"))
    unit_price: Decimal = Column(Numeric(18, 4), default=Decimal("0"))

    invoice: Invoice = relationship("Invoice", back_populates="lines")

    def __repr__(self):
        return f"<InvoiceLine {self.description}: qty={self.quantity}>"


class CreditMemo(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Credit memo for refunds against invoices."""

    __tablename__ = "credit_memos"

    credit_memo_number: str = Column(String(50), unique=True, index=True)
    invoice_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True)
    entity_type: str = Column(String(20), nullable=False)
    entity_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)
    status: str = Column(String(20), default="draft")
    issue_date: date | None = Column(Date, nullable=True)
    total_amount: Decimal = Column(Numeric(18, 2), default=Decimal("0"))
    reason: str = Column(Text)
    notes: str = Column(Text)

    lines: list = relationship("CreditMemoLine", back_populates="credit_memo", uselist=True)

    def __repr__(self):
        return f"<CreditMemo {self.credit_memo_number}: {self.status}>"


class CreditMemoLine(Base, UUIDMixin):
    """Line item within a credit memo."""

    __tablename__ = "credit_memo_lines"

    credit_memo_id: UUID = Column(UUID(as_uuid=True), ForeignKey("credit_memos.id"))
    description: str = Column(String(255))
    quantity: Decimal = Column(Numeric(18, 4), default=Decimal("1"))
    unit_price: Decimal = Column(Numeric(18, 4), default=Decimal("0"))

    credit_memo: CreditMemo = relationship("CreditMemo", back_populates="lines")

    def __repr__(self):
        return f"<CreditMemoLine {self.description}: qty={self.quantity}>"


# ── Transfer Order ───────────────────────────────────────────────────────────


class TransferOrder(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Transfer order header — tracks stock movement between warehouses."""

    __tablename__ = "transfer_orders"

    code: str = Column(String(50), unique=True, index=True)
    source_warehouse_id: UUID = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    target_warehouse_id: UUID = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"))
    type: TransferItemType = Column(SAEnum(TransferItemType))
    status: TransferStatus = Column(SAEnum(TransferStatus), default=TransferStatus.DRAFT)
    total_weight_kg: Decimal = Column(Numeric(18, 4), default=Decimal("0"))
    total_volume_m3: Decimal = Column(Numeric(18, 6), default=Decimal("0"))
    total_pieces: int = Column(Integer, default=0)
    ref_no: str | None = Column(String(100), nullable=True)
    ref_type: str | None = Column(String(50), nullable=True)
    remarks: str | None = Column(Text, nullable=True)

    source_warehouse: Warehouse = relationship("Warehouse", foreign_keys=[source_warehouse_id])
    target_warehouse: Warehouse = relationship("Warehouse", foreign_keys=[target_warehouse_id])
    lines: list = relationship("TransferOrderLine", back_populates="transfer_order")
    logs: list = relationship("TransferLog", back_populates="transfer_order")

    __table_args__ = (
        Index("ix_transfer_orders_status_created_at", "status", "created_at"),
    )

    def __repr__(self):
        return f"<TransferOrder {self.code}: status={self.status}>"


class TransferOrderLine(Base, UUIDMixin):
    """Line item within a transfer order."""

    __tablename__ = "transfer_order_lines"

    transfer_order_id: UUID = Column(UUID(as_uuid=True), ForeignKey("transfer_orders.id"))
    item_type: TransferItemType = Column(SAEnum(TransferItemType))
    sku_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("skus.id"), nullable=True)
    location_from_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)
    location_to_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)

    # Warehouse-level transfer fields (used when item_type == WAREHOUSE)
    warehouse_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)

    quantity: Decimal = Column(Numeric(20, 4), default=Decimal("0"))
    available_qty: Decimal = Column(Numeric(20, 4), default=Decimal("0"))
    picked_qty: Decimal = Column(Numeric(20, 4), default=Decimal("0"))
    shipped_qty: Decimal = Column(Numeric(20, 4), default=Decimal("0"))
    received_qty: Decimal = Column(Numeric(20, 4), default=Decimal("0"))

    transfer_order: TransferOrder = relationship("TransferOrder", back_populates="lines")
    sku: SKU | None = relationship("SKU", foreign_keys=[sku_id])

    def __repr__(self):
        return f"<TransferLine {self.transfer_order_id}: qty={self.quantity}>"


class TransferLog(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Audit log for transfer order status changes and stock movements."""

    __tablename__ = "transfer_logs"

    transfer_order_id: UUID = Column(UUID(as_uuid=True), ForeignKey("transfer_orders.id"), index=True)
    operator_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)
    remark: str | None = Column(Text, nullable=True)
    from_warehouse_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)
    to_warehouse_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)
    from_location_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)
    to_location_id: UUID | None = Column(UUID(as_uuid=True), nullable=True)
    quantity_change: Decimal = Column(Numeric(20, 4), default=Decimal("0"))

    transfer_order: TransferOrder = relationship("TransferOrder", back_populates="logs")

    def __repr__(self):
        return f"<TransferLog {self.transfer_order_id}: qty_chg={self.quantity_change}>"

# Re-export from legacy models for backwards compatibility
from src.models.wms import StockInventoryLog  # noqa: E402, F401

