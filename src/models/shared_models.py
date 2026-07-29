"""Shared model classes used across OMS, WMS, and TMS modules.

These models are imported by multiple subsystems to avoid circular imports
and ensure consistent definitions for shared entities like Customer and OrderItem.
"""

from decimal import Decimal

from sqlalchemy import JSON, UUID, Column, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, relationship

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class Customer(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Customer information model.

    Stores customer details including contact information and address data.
    Shared across OMS (order management) and other subsystems.
    """

    __tablename__ = "customers"

    code: str = Column(String(50), unique=True, index=True)
    name: str = Column(String(200), nullable=False)
    contact: str = Column(String(100))
    phone: str = Column(String(30))
    address: dict | None = Column(JSON)

    orders: list = relationship("Order", back_populates="customer")

    def __repr__(self):  # type: ignore[no-untyped-decorator]
        return f"<Customer {self.code}: {self.name}>"


class OrderItem(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Individual item within an order.

    Tracks the details of each item requested in an order, including quantity,
    price, and picking status. Shared across OMS/WMS/TMS.
    """

    __tablename__ = "order_items"

    order_id: UUID = Column(UUID(as_uuid=True), ForeignKey("orders.id"))
    sku_id: UUID | None = Column(UUID(as_uuid=True), ForeignKey("skus.id"), nullable=True)
    gtin: str = Column(String(13))
    name: str = Column(String(200))
    quantity: int = Column(Integer, default=0)
    picked_qty: int = Column(Integer, default=0)
    unit_price: Decimal = Column(Numeric(18, 4))
    batch_no: str | None = Column(String(50), nullable=True)
    status: str = Column(String(20), default="pending")

    # One-way relationship — Order has the back-reference via items_list
    order: Mapped["Order"] | None = relationship("Order", foreign_keys=[order_id])  # type: ignore[name-defined]

    __table_args__ = (
        Index("ix_order_items_gtin", "gtin"),
        Index("ix_order_items_order_id_status", "order_id", "status"),
    )

    def __repr__(self):  # type: ignore[no-untyped-decorator]
        return f"<OrderItem {self.id}: {self.gtin} qty={self.quantity}>"


# ── Lazy relationship registration ────────────────────────────────────────
# SQLAlchemy needs the back_populates targets to exist at configure time.
# Because Customer and OrderItem are imported *after* their owning modules
# (OMS, WMS) define the parent classes that reference them via back_populates,
# we register those mappings here once all classes have been loaded.


def _register_back_references() -> None:
    """Register bidirectional relationships between shared models and module-specific ones."""
    try:
        from src.models.shared_models import Customer, OrderItem  # noqa: F811

        if not hasattr(Customer, "orders"):
            return  # already configured or Owner hasn't loaded yet

        _configure_order_item_sku()
    except ImportError:
        pass


def _configure_order_item_sku() -> None:
    """Register OrderItem.sku relationship pointing to WMS SKU model."""
    try:
        from src.wms.models import SKU  # type: ignore[import-untyped]

        if not hasattr(OrderItem, "sku"):
            OrderItem.sku = relationship("SKU", foreign_keys=[OrderItem.sku_id])  # type: ignore[attr-defined]
    except ImportError:
        pass


# Auto-register when this module is imported as __main__ or via __init__.py
_register_back_references()
