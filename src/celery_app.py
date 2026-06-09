from celery import Celery

from src.config import settings

# Create Celery application instance with Redis broker
app = Celery(
    __name__,
    broker=settings.redis_url,
    result_backend=settings.redis_url,
)

# Configure task serialization to JSON (default is pickle which requires same Python version)
app.conf.task_serializer = "json"

# Set task time limits
app.conf.task_time_limit = 3600  # 1 hour hard limit
app.conf.task_soft_time_limit = 3000  # 50 minutes soft limit (triggers timeout signal)

# Configure worker settings
app.conf.worker_pool_size = 4  # Number of preforked processes
app.conf.worker_concurrency = 8  # Threads per process
app.conf.worker_prefetch_count = 1  # Fetch one task at a time to avoid wasting work on shutdown

# Enable periodic tasks (Beat)
app.conf.beat_schedule = None  # Will be configured in celeryconf.py

# Configure logging for Celery
app.conf.task_log_format = """[%(asctime)s] %(levelname)s: %(message)s"""

# Import tasks to register them with Celery
from src.tasks.orders import (  # noqa: F401
    auto_complete_picked_orders,
    cancel_abandoned_drafts,
    process_stale_orders,
)
from src.tasks.inventory import (  # noqa: F401
    check_low_stock_alerts,
    release_locked_inventory_for_cancelled_orders,
)
from src.tasks.maintenance import (  # noqa: F401
    cleanup_expired_tokens,
    cleanup_old_sync_logs,
    daily_aggregation,
    health_check,
)


def start_celery_worker():
    """Start the Celery worker."""
    app.worker_main(
        [
            "worker",
            "--loglevel=INFO",
            "--concurrency=8",
            "--pool=pthreads",
            "--queues=default,critical",
            "--logfile=celery.log",
            "--pidfile=celery.pid",
        ]
    )


def start_celery_beat():
    """Start the Celery Beat scheduler."""
    app.beat_main(
        [
            "beat",
            "--loglevel=INFO",
            "--logfile=celery-beat.log",
            "--pidfile=celery-beat.pid",
        ]
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        start_celery_worker()
    elif len(sys.argv) > 1 and sys.argv[1] == "beat":
        start_celery_beat()
