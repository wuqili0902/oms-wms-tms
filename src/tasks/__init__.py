"""Tasks package — Celery async task definitions.

Organized by domain:
- orders: Order lifecycle automation (auto-complete, stale detection, draft cleanup)
- inventory: Low-stock alerts, locked-inventory release, snapshots, pending/cancelled sweeps
- maintenance: Cleanup, health checks, daily aggregation, ABC-XYZ analysis
- outbox: Outbound event dispatch
- sync: PDA offline queue drain
- base: Base task class with retry/logging helpers

Importing this package is what registers every task with Celery: a task module
that is never imported is never registered, and a beat entry naming it fires
"Received unregistered task" instead of running.  A deployment starts the worker
and beat with ``celery -A src.celeryconf worker|beat`` (see src/celeryconf.py for
the schedule); ``src/celeryconf.py`` imports this package through
``src.celery_app``.

Task names come in two families, and the schedule has to spell them the way the
decorator registered them:

- ``src/tasks/inventory.py`` declares explicit names (``tasks.inventory.*``,
  ``tasks.order.*``);
- every other module keeps Celery's default ``src.tasks.<module>.<function>``.
"""
from src.tasks.base import BaseTask  # noqa: F401
from src.tasks.inventory import (
    cancel_expired_orders,  # noqa: F401
    check_low_stock_alerts,  # noqa: F401
    process_pending_orders,  # noqa: F401
    release_locked_inventory_for_cancelled_orders,  # noqa: F401
    snapshot_inventory,  # noqa: F401
    sync_inventory,  # noqa: F401
)
from src.tasks.maintenance import (  # noqa: F401
    cleanup_expired_tokens,
    cleanup_old_sync_logs,
    compute_abc_xyz_analysis,
    daily_aggregation,
    health_check,
)
from src.tasks.orders import (  # noqa: F401
    auto_complete_picked_orders,
    cancel_abandoned_drafts,
    process_stale_orders,
)
from src.tasks.outbox import dispatch_outbox_events  # noqa: F401
from src.tasks.sync import process_pda_sync_queue  # noqa: F401

__all__ = [
    "BaseTask",
    # Orders (src.tasks.orders.*)
    "process_stale_orders",
    "auto_complete_picked_orders",
    "cancel_abandoned_drafts",
    # Inventory (declared with explicit names: tasks.inventory.* / tasks.order.*)
    "sync_inventory",
    "snapshot_inventory",
    "check_low_stock_alerts",
    "release_locked_inventory_for_cancelled_orders",
    "cancel_expired_orders",
    "process_pending_orders",
    # Outbox
    "dispatch_outbox_events",
    # PDA Sync
    "process_pda_sync_queue",
    # Maintenance
    "cleanup_expired_tokens",
    "cleanup_old_sync_logs",
    "daily_aggregation",
    "compute_abc_xyz_analysis",
    "health_check",
]
