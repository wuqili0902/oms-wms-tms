# Import all model modules so Base.metadata is populated for Alembic
import src.auth.models  # noqa: F401
import src.barcode.models  # noqa: F401
import src.core.models  # noqa: F401
import src.notification.models  # noqa: F401
import src.oms.models  # noqa: F401
import src.pda.models  # noqa: F401
import src.tms.models  # noqa: F401
import src.webhooks.models  # noqa: F401
import src.wms.models  # noqa: F401
from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from src.models.shared_models import Customer, OrderItem

__all__ = [
    "Base",
    "TimestampMixin",
    "SoftDeleteMixin",
    "UUIDMixin",
    "Customer",
    "OrderItem",
]
