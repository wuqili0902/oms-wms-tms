"""Celery tasks for system maintenance and health monitoring.

Handles periodic cleanup, health checks, and data pruning operations
that keep the system running smoothly.
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.celery_app import app
from src.config import settings
from src.tasks.base import BaseTask
from src.tms.models import SyncLog
from src.auth.models import User

logger = logging.getLogger(__name__)


def _get_async_session() -> AsyncSession:
    engine = create_async_engine(settings.database_url, echo=False)
    return AsyncSession(engine)


def _get_sync_session() -> AsyncSession:
    """Create session using sync URL for maintenance operations."""
    from sqlalchemy import create_engine as sync_create_engine

    engine = sync_create_engine(settings.database_sync_url, echo=False)
    return AsyncSession(engine)


@app.task(base=BaseTask, bind=True)
async def cleanup_old_sync_logs(self):
    """Delete sync logs older than 30 days.

    TMS sync logs can accumulate rapidly. This task prunes old records
    to prevent unbounded table growth.
    """
    session = _get_async_session()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        result = await session.execute(
            delete(SyncLog).where(SyncLog.started_at < cutoff)
        )
        await session.commit()
        deleted = result.rowcount
        if deleted:
            logger.info("Cleaned up %d sync logs older than 30 days", deleted)
        return {"deleted_sync_logs": deleted}
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@app.task(base=BaseTask, bind=True)
async def cleanup_expired_tokens(self):
    """Remove expired refresh tokens from the token store.

    Note: The current TokenStore is in-memory. In production with Redis,
    expired keys are auto-evicted via TTL. This task serves as a safety net.
    """
    from src.auth.token_store import token_store

    before = len(token_store._store)
    token_store.cleanup_expired()
    after = len(token_store._store)
    removed = before - after
    if removed:
        logger.info("Cleaned up %d expired tokens (in-memory store)", removed)
    return {"expired_tokens_removed": removed}


@app.task(base=BaseTask, bind=True)
async def health_check(self):
    """Comprehensive health check — verifies DB and Redis connectivity.

    Runs every 5 minutes. Results should be monitored by an external
    system (Prometheus, Datadog, etc.).
    """
    results = {"database": False, "redis": False, "timestamp": datetime.now(timezone.utc).isoformat()}

    # Check database
    session = _get_async_session()
    try:
        await session.execute(text("SELECT 1"))
        results["database"] = True
    except Exception as e:
        logger.error("Health check: database unreachable — %s", str(e))
    finally:
        await session.close()

    # Check Redis
    try:
        import aioredis

        client = aioredis.from_url(settings.redis_url)
        await client.ping()
        await client.aclose()
        results["redis"] = True
    except Exception as e:
        logger.error("Health check: Redis unreachable — %s", str(e))

    all_ok = all(results[k] for k in ("database", "redis"))
    if not all_ok:
        logger.warning("Health check FAILED: %s", results)
    return results


@app.task(base=BaseTask, bind=True)
async def daily_aggregation(self):
    """Daily aggregation task — compute order/inventory stats.

    Placeholder for business intelligence / reporting aggregation.
    In production, this would compute daily KPIs and write to a
    reporting table or external analytics system.
    """
    session = _get_async_session()
    try:
        today = datetime.now(timezone.utc).date()
        start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

        from sqlalchemy import func

        from src.oms.models import Order, OrderStatus

        total_result = await session.execute(
            select(func.count()).select_from(Order)
        )
        total = total_result.scalar() or 0

        today_result = await session.execute(
            select(func.count()).select_from(Order).where(Order.created_at >= start)
        )
        today_count = today_result.scalar() or 0

        stats = {
            "date": today.isoformat(),
            "total_orders": total,
            "orders_today": today_count,
        }
        logger.info("Daily aggregation: %s", stats)
        return stats
    finally:
        await session.close()
