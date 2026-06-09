"""TMS (Terminal Management System) domain models.

This module contains all SQLAlchemy 2.0 ORM models for the Terminal Management System,
including mobile devices, device sessions, and synchronization logging.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class TerminalDeviceType(Enum):
    """Enumeration of terminal device types."""

    PDA = "pda"
    PHONE = "phone"
    SCANNER = "scanner"
    PRINTER = "printer"


class PlatformType(Enum):
    """Enumeration of mobile platforms."""

    ANDROID = "android"
    IOS = "ios"
    DESKTOP = "desktop"


class DeviceStatus(Enum):
    """Enumeration of device operational statuses."""

    ONLINE = "online"
    OFFLINE = "offline"
    DISABLED = "disabled"


class SyncLogType(Enum):
    """Enumeration of synchronization operation types."""

    UPLOAD = "upload"
    DOWNLOAD = "download"


class SyncLogStatus(Enum):
    """Enumeration of synchronization log statuses."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class TerminalDevice(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Terminal device model for mobile hardware tracking.

    Manages the lifecycle and configuration of handheld devices used in warehouse operations.
    """

    __tablename__ = "terminal_devices"

    code: str = Column(String(50), unique=True, index=True)
    name: str | None = Column(String(200))
    device_type: TerminalDeviceType = Column(SAEnum(TerminalDeviceType))
    platform: PlatformType = Column(SAEnum(PlatformType))
    os_version: str | None = Column(String(50))
    app_version: str | None = Column(String(20))
    status: DeviceStatus = Column(SAEnum(DeviceStatus), default=DeviceStatus.OFFLINE)
    warehouse_id: UUID | None = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=True
    )
    last_sync_at: datetime | None = Column(DateTime(timezone=True), nullable=True, index=True)
    last_heartbeat_at: datetime | None = Column(DateTime(timezone=True), nullable=True, index=True)
    config: dict | None = Column(JSON, nullable=True)
    push_token: str | None = Column(String(500), nullable=True)

    warehouse: Optional["Warehouse"] = relationship("Warehouse")
    device_sessions: list = relationship("DeviceSession", back_populates="device")
    sync_logs: list = relationship("SyncLog", back_populates="device")

    __table_args__ = (
        Index("ix_terminal_devices_status", "status"),
    )

    def __repr__(self):
        return f"<TerminalDevice {self.code}: type={self.device_type.value}, platform={self.platform.value}>"


class DeviceSession(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Active device session tracking for mobile terminals.

    Manages authentication sessions and tracks active usage of terminal devices.
    """

    __tablename__ = "device_sessions"

    device_id: UUID = Column(UUID(as_uuid=True), ForeignKey("terminal_devices.id"))
    token: str = Column(String(500), unique=True, index=True)
    login_at: datetime = Column(DateTime(timezone=True))
    logout_at: datetime | None = Column(DateTime(timezone=True), nullable=True)
    ip_address: str | None = Column(String(45))

    device: TerminalDevice = relationship("TerminalDevice", back_populates="device_sessions")

    __table_args__ = (
        Index("ix_device_sessions_device_id_active", "device_id", "logout_at"),
    )

    def __repr__(self):
        return f"<DeviceSession device={self.device_id} token={self.token[:8]}...>"


class SyncLog(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Synchronization log for tracking data sync operations.

    Records all synchronization activities between mobile devices and the central server.
    """

    __tablename__ = "sync_logs"

    device_id: UUID = Column(UUID(as_uuid=True), ForeignKey("terminal_devices.id"))
    sync_type: SyncLogType = Column(SAEnum(SyncLogType))
    status: SyncLogStatus = Column(SAEnum(SyncLogStatus), default=SyncLogStatus.PENDING)
    records_count: int = Column(Integer, default=0)
    error_message: str | None = Column(Text, nullable=True)
    started_at: datetime = Column(DateTime(timezone=True))
    completed_at: datetime | None = Column(DateTime(timezone=True), nullable=True)

    device: TerminalDevice = relationship("TerminalDevice", back_populates="sync_logs")

    __table_args__ = (
        Index(
            "ix_sync_logs_device_id_status",
            "device_id",
            "status",
        ),
        Index(
            "ix_sync_logs_started_at_completed_at",
            "started_at",
            "completed_at",
        ),
    )

    def __repr__(self):
        return f"<SyncLog device={self.device_id} type={self.sync_type.value}: status={self.status.value}>"
