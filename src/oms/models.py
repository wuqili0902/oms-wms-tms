"""OMS (Order Management System) domain models.

This module contains all SQLAlchemy 2.0 ORM models for the Order Management System,
including orders, order items, customer information, and status tracking.
"""

import uuid
from decimal import Decimal
from datetime import UTC, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Numeric,
    Integer,
    Text,
    Enum as SAEnum,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.models.base import Base, TimestampMixin, SoftDeleteMixin, UUIDMixin


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
    URGANIC = "urgent"


class Customer(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Customer information model.

    Stores customer details including contact information and address data.
    """
    __tablename__ = "customers"

    code: str = Column(String(50), unique=True, index=True)
    name: str = Column(String(200), nullable=False)
    contact: str = Column(String(100))
    phone: str = Column(String(30))
    address: dict = Column(JSON)

    orders: list = relationship("Order", back_populates=True, lazy="dynamic")

    def __repr__(self):
        return f"<Customer {self.code}: {self.name}>"


class Order(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Order model representing a customer's request for items.

    This model tracks the order lifecycle from creation to completion or cancellation.
    """
    __tablename__ = "orders"

    order_no: str = Column(String(50), unique=True, index=True)
    status: OrderStatus = Column(SAEnum(OrderStatus), default=OrderStatus.PENDING)
    customer_id: UUID = Column(UUID(as_uuid=True), ForeignKey("customers.id"))
    warehouse_id: Optional[UUID] = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=True)
    items: dict = Column(JSON)
    total_amount: Decimal = Column(Numeric(18, 2))
    priority: OrderPriority = Column(SAEnum(OrderPriority), default=OrderPriority.MEDIUM)
    version: int = Column(Integer, default=0)
    notes: str = Column(Text)

    customer: Customer = relationship("Customer", back_populates=True)
    warehouse: Optional["Warehouse"] = relationship("Warehouse", back_populates=True, lazy="dynamic")
    items_list: list = relationship("OrderItem", back_populates=True, lazy="dynamic")
    status_logs: list = relationship("OrderStatusLog", back_populates=True, lazy="dynamic")

    __table_args__ = Index(
        "ix_orders_order_no", "order_no",
        unique=True,
    ), Index(
        "ix_orders_status_customer_id", "status", "customer_id",
    ),

    def __repr__(self):
        return f"<Order {self.order_no}: {self.status.value}>"


class OrderItem(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Individual item within an order.

    Tracks the details of each item requested in an order, including quantity,
    price, and picking status.
    """
    __tablename__ = "order_items"

    order_id: UUID = Column(UUID(as_uuid=True), ForeignKey("orders.id"))
    sku_id: Optional[UUID] = Column(UUID(as_uuid=True), nullable=True)
    gtin: str = Column(String(13))
    name: str = Column(String(200))
    quantity: int = Column(Integer, default=0)
    picked_qty: int = Column(Integer, default=0)
    unit_price: Decimal = Column(Numeric(18, 4))
    batch_no: Optional[str] = Column(String(50), nullable=True)
    status: str = Column(String(20), default="pending")

    order: Order = relationship("Order", back_populates=True)
    sku: Optional["SKU"] = relationship("SKU", back_populates=True, lazy="dynamic")

    __table_args__ = Index(
        "ix_order_items_gtin", "gtin",
    ), Index(
        "ix_order_items_order_id_status", "order_id", "status",
    ),

    def __repr__(self):
        return f"<OrderItem {self.name}: qty={self.quantity}>"


class OrderStatusLog(Base, UUIDMixin, TimestampMixin):
    """Logs of order status changes.

    Tracks the history of status transitions for each order, including who made the change and any remarks.
    """
    __tablename__ = "order_status_logs"

    order_id: UUID = Column(UUID(as_uuid=True), ForeignKey("orders.id"))
    from_status: str = Column(String(20))
    to_status: str = Column(String(20))
    operator_id: Optional[UUID] = Column(UUID(as_uuid=True), nullable=True)
    remark: Optional[str] = Column(Text, nullable=True)

    order: Order = relationship("Order", back_populates=True)
    operator: Optional["User"] = relationship("User", back_populates=True, lazy="dynamic")

    __table_args__ = (
        Index("ix_order_status_logs_order_id_created_at", "order_id", "created_at"),
    )

    def __repr__(self):
        return f"<OrderStatusLog {self.from_status} -> {self.to_status}>"


