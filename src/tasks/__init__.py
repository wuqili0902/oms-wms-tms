"""Tasks package — Celery async task definitions.

Organized by domain:
- orders: Order lifecycle automation (auto-complete, stale detection)
- inventory: Stock level alerts and inventory release
- maintenance: Cleanup, health checks, daily aggregation
- base: Base task class with retry/logging helpers

The example.py module contains educational stubs and should not be
imported in production.
"""
from src.tasks.base import BaseTask  # noqa: F401
from src.tasks.maintenance import (  # noqa: F401
    cleanup_expired_tokens,
    cleanup_old_sync_logs,
    daily_aggregation,
    health_check,
)
from src.tasks.orders import (  # noqa: F401
    auto_complete_picked_orders,
    cancel_abandoned_drafts,
    process_stale_orders,
)
from src.tasks.inventory import (  # noqa: F401
    check_low_stock_alerts,
    release_locked_inventory_for_cancelled_orders,
)

__all__ = [
    "BaseTask",
    # Orders
    "process_stale_orders",
    "auto_complete_picked_orders",
    "cancel_abandoned_drafts",
    # Inventory
    "check_low_stock_alerts",
    "release_locked_inventory_for_cancelled_orders",
    # Maintenance
    "cleanup_expired_tokens",
    "cleanup_old_sync_logs",
    "daily_aggregation",
    "health_check",
]
