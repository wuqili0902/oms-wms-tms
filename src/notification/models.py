import enum
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String, Text

from src.models.base import Base


class NotificationChannel(enum.StrEnum):
    EMAIL = "email"
    WEBSOCKET = "websocket"
    PUSH = "push"


class NotificationType(enum.StrEnum):
    ORDER_STATUS_CHANGE = "order_status_change"
    ORDER_CREATED = "order_created"
    LOW_STOCK_ALERT = "low_stock_alert"
    TRANSPORT_STATUS_CHANGE = "transport_status_change"
    DELIVERY_CONFIRMED = "delivery_confirmed"
    EXCEPTION_OCCURRED = "exception_occurred"
    SYSTEM_ALERT = "system_alert"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False, index=True)
    type = Column(Enum(NotificationType), nullable=False)
    channel = Column(Enum(NotificationChannel), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    data = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False, index=True)
    notification_type = Column(Enum(NotificationType), nullable=False)
    channel = Column(Enum(NotificationChannel), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
