"""Celery Beat periodic task schedule.

Configure recurring tasks with their execution intervals.
All times are in UTC.
"""
from celery.schedules import crontab

from src.celery_app import app

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
        "task": "src.tasks.inventory.check_low_stock_alerts",
        "schedule": crontab(minute=30, hour="*/6"),
        "options": {"queue": "default"},
    },
    "release-locked-inventory-daily": {
        "task": "src.tasks.inventory.release_locked_inventory_for_cancelled_orders",
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

# Apply the beat schedule to the Celery app
app.conf.beat_schedule = beat_schedule
