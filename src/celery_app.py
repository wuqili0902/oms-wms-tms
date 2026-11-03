from celery import Celery
from celery.schedules import crontab

from src.config import settings

# Create Celery application instance
# Celery uses Redis as both broker and result backend (see src/config.redis_url).
broker_url = settings.redis_url
result_backend_url = settings.redis_url
app = Celery(__name__, broker=broker_url, result_backend=result_backend_url)

# Alias for task files that import `from src.celery_app import celery`.  It has to
# exist before the task modules are imported below: they run
# ``from src.celery_app import celery`` at module scope, and a half-initialized
# module without this name is exactly the ImportError the old try/except swallowed —
# which is how a task ended up in the beat schedule without ever being registered.
celery = app

# Configure task serialization to JSON (default is pickle which requires same Python version)
app.conf.task_serializer = "json"
app.conf.task_accept_content = ["json"]  # Reject pickle for security

# Set task time limits
app.conf.task_time_limit = 3600  # 1 hour hard limit
app.conf.task_soft_time_limit = 3000  # 50 minutes soft limit (triggers timeout signal)

# Configure worker settings
app.conf.worker_prefetch_count = 1  # Fetch one task at a time to avoid wasting work on shutdown
app.conf.task_acks_late = True  # Ack after execution (not before) — prevents task loss on worker crash
app.conf.worker_max_tasks_per_child = 1000  # Recycle workers periodically to prevent memory leaks
app.conf.broker_connection_retry = True
app.conf.broker_connection_retry_on_startup = True

# Importing the package registers every task with Celery (see src/tasks/__init__.py).
# No try/except here: an ImportError in a task module used to disappear, leaving a
# beat entry that fires "Received unregistered task" every night.
import src.tasks  # noqa: E402,F401  (registers tasks; must run after `celery = app`)

# ── Periodic tasks (Beat) ─────────────────────────────────────────────────────
# Defined here rather than in src/celeryconf.py: the schedule must be attached to
# the app no matter which module is imported first, and src/celeryconf.py (the
# module ``celery -A src.celeryconf worker|beat`` loads) imports this module — a
# schedule living there would be unreachable from here without a circular import.
#
# Task names are taken from how each module declared them: src/tasks/inventory.py
# gives explicit names (``tasks.inventory.*`` / ``tasks.order.*``), the rest keep
# Celery's default ``src.tasks.<module>.<function>``.  tests/test_celery_schedule_contract.py
# fails if an entry names something the worker never registered.
beat_schedule = {
    # ── Order processing ─────────────────────────────────────────────────
    "process-stale-orders-every-30m": {
        "task": "src.tasks.orders.process_stale_orders",
        "schedule": crontab(minute="*/30"),
        "options": {"queue": "default"},
    },
    "auto-complete-picked-every-6h": {
        "task": "src.tasks.orders.auto_complete_picked_orders",
        "schedule": crontab(minute=0, hour="*/6"),
        "options": {"queue": "default"},
    },
    "cancel-abandoned-drafts-daily": {
        "task": "src.tasks.orders.cancel_abandoned_drafts",
        "schedule": crontab(minute=0, hour=3),
        "options": {"queue": "default"},
    },
    # ── Inventory ────────────────────────────────────────────────────────
    "check-low-stock-every-6h": {
        "task": "tasks.inventory.check_low_stock",
        "schedule": crontab(minute=30, hour="*/6"),
        "options": {"queue": "default"},
    },
    "release-locked-inventory-daily": {
        "task": "tasks.inventory.release_locked",
        "schedule": crontab(minute=0, hour=2),
        "options": {"queue": "default"},
    },
    # ── Outbox ───────────────────────────────────────────────────────────
    "dispatch-outbox-every-1m": {
        "task": "src.tasks.outbox.dispatch_outbox_events",
        "schedule": crontab(minute="*/1"),
        "options": {"queue": "default"},
    },
    # ── ABC‑XYZ inventory analysis ───────────────────────────────────────
    "abc-xyz-analysis-daily": {
        "task": "src.tasks.maintenance.compute_abc_xyz_analysis",
        "schedule": crontab(minute=0, hour=2),
        "options": {"queue": "default"},
    },
    # ── Maintenance ──────────────────────────────────────────────────────
    "health-check-every-5m": {
        "task": "src.tasks.maintenance.health_check",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "default"},
    },
    "cleanup-sync-logs-daily": {
        "task": "src.tasks.maintenance.cleanup_old_sync_logs",
        "schedule": crontab(minute=0, hour=4),
        "options": {"queue": "default"},
    },
    "cleanup-expired-tokens-hourly": {
        "task": "src.tasks.maintenance.cleanup_expired_tokens",
        "schedule": crontab(minute=0),
        "options": {"queue": "default"},
    },
    "daily-aggregation-midnight": {
        "task": "src.tasks.maintenance.daily_aggregation",
        "schedule": crontab(minute=0, hour=1),
        "options": {"queue": "default"},
    },
}

app.conf.beat_schedule = beat_schedule


def start_celery_worker():
    """Start the Celery worker.

    Uses the prefork pool (one worker process = one main thread = one event
    loop).  All tasks are ``async def`` bridged through ``BaseTask.__call__``
    (see src/tasks/base.py); the shared async SQLAlchemy engine binds its
    pooled connections to that per-process loop, so the threads pool would
    risk cross-loop connection use and must not be used here.
    """
    app.worker_main(
        [
            "worker",
            "--loglevel=INFO",
            "--concurrency=8",
            "--pool=prefork",
            "--queues=default,critical",
        ]
    )


def start_celery_beat():
    """Start the Celery Beat scheduler."""
    app.beat_main(
        [
            "beat",
            "--loglevel=INFO",
        ]
    )


# Alias for task files that import `from src.celery_app import celery`
celery = app

if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        start_celery_worker()
    elif len(sys.argv) > 1 and sys.argv[1] == "beat":
        start_celery_beat()
