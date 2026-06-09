import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase, AsyncAttrs):
    __allow_unmapped__ = True


def model_to_dict(model: Any) -> dict:
    """Convert a SQLAlchemy model instance to a plain dict.

    Handles UUID, datetime, Decimal, Enum serialisation automatically.
    """
    result = {}
    for col in model.__table__.columns:
        val = getattr(model, col.name)
        if val is None:
            result[col.name] = None
        elif isinstance(val, uuid.UUID):
            result[col.name] = str(val)
        elif isinstance(val, datetime):
            result[col.name] = val.isoformat()
        elif isinstance(val, Decimal):
            result[col.name] = str(val)
        elif isinstance(val, Enum):
            result[col.name] = val.value
        else:
            result[col.name] = val
    return result


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class SoftDeleteMixin:
    """Mixin that adds soft-delete capability."""

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UUIDMixin:
    """Mixin that adds UUID primary key."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
