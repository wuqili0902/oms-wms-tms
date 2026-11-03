import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

# Generic SQLAlchemy 2 Uuid instead of dialects.postgresql.UUID: on PostgreSQL
# it still renders the native UUID type, but on SQLite it renders CHAR(32)
# (TEXT affinity).  The PG-specific UUID type emitted a bare "UUID" column on
# SQLite, which SQLite's affinity rules treat as NUMERIC — silently coercing
# all-digit hex ids (e.g. 00000000-0000-...-001) to integers and then blowing
# up on every read with "'int' object has no attribute 'replace'".
from sqlalchemy import Boolean, DateTime, func
from sqlalchemy import Uuid as UUID  # noqa: N814 — column type, not a constant
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase, AsyncAttrs):
    __allow_unmapped__ = True


def model_to_dict(model: Any) -> dict:
    """Convert a SQLAlchemy model instance to a plain dict.

    Handles UUID, datetime, Decimal, Enum serialisation automatically.
    """

    def serialize(val):
        if val is None:
            return None
        if isinstance(val, uuid.UUID):
            return str(val)
        if isinstance(val, datetime):
            return val.isoformat()
        if isinstance(val, Decimal):
            return str(val)
        if isinstance(val, Enum):
            return val.value
        return val

    result = {}
    mapper = getattr(type(model), "__mapper__", None)
    if mapper is not None:
        for prop in mapper.column_attrs:
            col = prop.columns[0]
            result[col.name] = serialize(getattr(model, prop.key))
    else:
        for col in model.__table__.columns:
            attr = getattr(col, "key", None) or col.name
            result[col.name] = serialize(getattr(model, attr))
    return result


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
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
