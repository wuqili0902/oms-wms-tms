from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin

# Import all model modules so Base.metadata is populated for Alembic
import src.auth.models  # noqa: F401
import src.oms.models  # noqa: F401
import src.wms.models  # noqa: F401
import src.barcode.models  # noqa: F401
import src.tms.models  # noqa: F401

__all__ = [
    "Base",
    "TimestampMixin",
    "SoftDeleteMixin",
    "UUIDMixin",
]
