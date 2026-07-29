import enum
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text

from src.models.base import Base


class WebhookEvent(enum.StrEnum):
    ORDER_CREATED = "order.created"
    ORDER_STATUS_CHANGED = "order.status_changed"
    ORDER_CANCELLED = "order.cancelled"
    INVENTORY_LOW_STOCK = "inventory.low_stock"
    TRANSPORT_STATUS_CHANGED = "transport.status_changed"
    DELIVERY_CONFIRMED = "delivery.confirmed"


class WebhookStatus(enum.StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


class DeliveryStatus(enum.StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class WebhookTarget(Base):
    __tablename__ = "webhook_targets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)
    secret = Column(String(255), nullable=True)
    events = Column(Text, nullable=False)
    status = Column(Enum(WebhookStatus), default=WebhookStatus.ACTIVE, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False)


class WebhookDeliveryLog(Base):
    __tablename__ = "webhook_delivery_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_id = Column(Integer, nullable=False, index=True)
    event = Column(String(50), nullable=False)
    payload = Column(Text, nullable=False)
    status = Column(Enum(DeliveryStatus), default=DeliveryStatus.PENDING, nullable=False)
    status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
