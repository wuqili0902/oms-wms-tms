"""OMS (Order Management System) domain models.

This module contains all SQLAlchemy 2.0 ORM models for the Order Management System,
including orders, order items, customer information, and status tracking.
"""

from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import (
    JSON,
    Column,
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

# Shared models imported from the common module to avoid circular imports.
from src.models.shared_models import Customer  # noqa: F401,E501
from src.models.shared_models import OrderItem as _OrderItemBase

# Alias so string references like relationship("OrderItem") resolve correctly, and also expose for backwards compat.
OrderItem = _OrderItemBase

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class OrderStatus(Enum):
    """Enumeration of possible order statuses."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    PICKING = "picking"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OrderPriority(Enum):
    """Enumeration of order priority levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


# ── Shared model definitions ────────────────────────────────────────────
# Customer and OrderItem are imported above from shared_models to avoid
# circular imports between OMS, WMS, and TMS subsystems.

class Order(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Order model representing a customer's request for items.

    This model tracks the order lifecycle from creation to completion or cancellation.
    """

    __tablename__ = "orders"

    order_no: str = Column(String(50), unique=True, index=True)
    status: OrderStatus = Column(SAEnum(OrderStatus), default=OrderStatus.PENDING)
    customer_id: UUID = Column(UUID(as_uuid=True), ForeignKey("customers.id"))
    warehouse_id: UUID | None = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=True
    )
    items: dict = Column(JSON)
    total_amount: Decimal = Column(Numeric(18, 2))
    priority: OrderPriority = Column(SAEnum(OrderPriority), default=OrderPriority.MEDIUM)
    version: int = Column(Integer, default=0)
    notes: str = Column(Text)

    customer: Customer = relationship("Customer", back_populates="orders")
    warehouse: Optional["Warehouse"] = relationship("Warehouse")
    items_list: list = relationship(
        "OrderItem", back_populates="order", uselist=True, overlaps="order",
        collection_class=list,
    )
    status_logs: list = relationship(
        "OrderStatusLog", back_populates="order", uselist=True, overlaps="order",
        collection_class=list,
    )

    __table_args__ = (
        Index("ix_orders_status_customer_id", "status", "customer_id"),
    )

    def __repr__(self):
        return f"<Order {self.order_no}: {self.status.value}>"



class OrderStatusLog(Base, UUIDMixin, TimestampMixin):
    """Logs of order status changes.

    Tracks the history of status transitions for each order, including who made the change and any remarks.
    """

    __tablename__ = "order_status_logs"

    order_id: UUID = Column(UUID(as_uuid=True), ForeignKey("orders.id"))
    from_status: str = Column(String(20))
    to_status: str = Column(String(20))
    operator_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    remark: str | None = Column(Text, nullable=True)

    order: Order = relationship("Order", back_populates="status_logs")
    operator: Optional["User"] = relationship("User")

    __table_args__ = (Index("ix_order_status_logs_order_id_created_at", "order_id", "created_at"),)

    def __repr__(self):
        return f"<OrderStatusLog {self.from_status} -> {self.to_status}>"


class MergeGroup(Base, UUIDMixin, TimestampMixin):
    """Group of orders merged for combined fulfilment."""

    __tablename__ = "merge_groups"

    code: str = Column(String(50), unique=True, index=True)
    warehouse_id: UUID | None = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=True
    )
    status: str = Column(String(20), default="active")
    total_items: int = Column(Integer, default=0)
    total_amount: Decimal = Column(Numeric(18, 2), default=Decimal("0"))
    notes: str = Column(Text)

    def __repr__(self):
        return f"<MergeGroup {self.code}: {self.status}>"


class SplitChildOrder(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Link table for split/merge relationships between orders."""

    __tablename__ = "split_child_orders"

    parent_order_id: UUID | None = Column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True
    )
    child_order_id: UUID = Column(UUID(as_uuid=True), ForeignKey("orders.id"))
    merge_group_id: UUID | None = Column(
        UUID(as_uuid=True), ForeignKey("merge_groups.id"), nullable=True
    )
    split_reason: str = Column(Text)

    def __repr__(self):
        return f"<SplitChildOrder {self.parent_order_id} -> {self.child_order_id}>"
