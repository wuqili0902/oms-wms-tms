"""PDA local SQLite models for offline operation."""
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Column, DateTime, Integer, String, Text

from src.models.base import Base


class SyncOperation(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class PendingMutation(Base):
    __tablename__ = "pda_pending_mutations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(50), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(100), nullable=False)
    operation = Column(String(20), nullable=False)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    synced_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, default=0)
