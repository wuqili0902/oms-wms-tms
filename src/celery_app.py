from celery import Celery

from src.config import settings

# Create Celery application instance
# Celery uses Redis as both broker and result backend (see src/config.redis_url).
broker_url = settings.redis_url
result_backend_url = settings.redis_url
app = Celery(__name__, broker=broker_url, result_backend=result_backend_url)

# Configure task serialization to JSON (default is pickle which requires same Python version)
app.conf.task_serializer = "json"

# Set task time limits
app.conf.task_time_limit = 3600  # 1 hour hard limit
app.conf.task_soft_time_limit = 3000  # 50 minutes soft limit (triggers timeout signal)

# Configure worker settings
app.conf.worker_prefetch_count = 1  # Fetch one task at a time to avoid wasting work on shutdown

# Enable periodic tasks (Beat)
app.conf.beat_schedule = None  # Will be configured in celeryconf.py

# Import tasks to register them with Celery
try:
    from src.tasks.inventory import check_low_stock_alerts  # noqa: F401
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
except ImportError:
    pass  # Gracefully handle circular imports in test environments


def start_celery_worker():
    """Start the Celery worker."""
    app.worker_main(
        [
            "worker",
            "--loglevel=INFO",
            "--concurrency=8",
            "--pool=threads",
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
