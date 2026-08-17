"""Celery tasks for system maintenance and health monitoring.

Handles periodic cleanup, health checks, and data pruning operations
that keep the system running smoothly.
"""
import json
import logging
from datetime import UTC, datetime, timedelta

import redis
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError

from src.celery_app import app
from src.core.database import get_session
from src.tasks.base import BaseTask
from src.tms.models import SyncLog

logger = logging.getLogger(__name__)


@app.task(base=BaseTask, bind=True)
async def cleanup_old_sync_logs(self):
    """Delete sync logs older than 30 days.

    TMS sync logs can accumulate rapidly. This task prunes old records
    to prevent unbounded table growth.
    """
    async with get_session() as session:
        try:
            cutoff = datetime.now(UTC) - timedelta(days=30)
            result = await session.execute(
                delete(SyncLog).where(SyncLog.started_at < cutoff)
            )
            deleted = result.rowcount
            if deleted:
                logger.info("Cleaned up %d sync logs older than 30 days", deleted)
            return {"deleted_sync_logs": deleted}
        except SQLAlchemyError:
            await session.rollback()
            raise


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
    from src.config import settings

    results = {"database": False, "redis": False, "timestamp": datetime.now(UTC).isoformat()}

    # Check database
    async with get_session() as session:
        try:
            await session.execute(text("SELECT 1"))
            results["database"] = True
        except Exception as e:
            logger.error("Health check: database unreachable — %s", str(e))

    # Check Redis
    try:
        import redis.asyncio as aioredis

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

    Writes daily KPI summary to logs/storage for reporting.
    """
    async with get_session() as session:
        try:
            from sqlalchemy import func

            from src.oms.models import Order, OrderStatus
            from src.wms.models import Inventory

            today = datetime.now(UTC).date()
            start = datetime(today.year, today.month, today.day, tzinfo=UTC)

            # Total orders
            total_result = await session.execute(select(func.count()).select_from(Order))
            total = total_result.scalar() or 0

            # Orders today
            today_result = await session.execute(
                select(func.count()).select_from(Order).where(Order.created_at >= start)
            )
            today_count = today_result.scalar() or 0

            # Orders by status
            status_counts = {}
            for status in OrderStatus:
                count_result = await session.execute(
                    select(func.count()).select_from(Order).where(Order.status == status)
                )
                status_counts[status.value] = count_result.scalar() or 0

            # Total inventory items
            inv_result = await session.execute(select(func.count()).select_from(Inventory))
            inv_count = inv_result.scalar() or 0

            stats = {
                "date": today.isoformat(),
                "total_orders": total,
                "orders_today": today_count,
                "orders_by_status": status_counts,
                "total_inventory_items": inv_count,
            }

            # Persist to JSON log for external ingestion
            import os

            log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
            os.makedirs(log_dir, exist_ok=True)
            daily_file = os.path.join(log_dir, f"daily_stats_{today.isoformat()}.json")
            with open(daily_file, "w") as f:
                json.dump(stats, f, indent=2)

            logger.info("Daily aggregation written: %s — %d orders, %d inventory items",
                          today.isoformat(), total, inv_count)
            return stats
        except SQLAlchemyError:
            await session.rollback()
            raise


@app.task(base=BaseTask, bind=True, max_retries=2)
async def compute_abc_xyz_analysis(self):
    """Daily ABC-XYZ inventory analysis.

    Reads stock movement data, computes the ABC‑XYZ matrix, and writes
    the result to Redis so the admin dashboard can display it instantly.
    """
    async with get_session() as session:
        try:
            from src.wms.analysis import compute_abc_xyz_matrix

            matrix = await compute_abc_xyz_matrix(session, months=6)

            try:
                from src.cache.redis_client import get_redis

                async with get_redis() as r:
                    if r:
                        await r.setex(
                            "inventory:abc_xyz_matrix",
                            86400,  # 24 h TTL
                            json.dumps(matrix, default=str),
                        )
                        logger.info("ABC‑XYZ matrix cached in Redis")
            except (redis.RedisError, ConnectionError, TimeoutError):
                logger.warning("Redis unavailable — ABC‑XYZ matrix not cached")

            total = sum(len(v) for v in matrix.values())
            logger.info("ABC‑XYZ analysis completed: %d SKUs classified", total)
            return {cell: len(items) for cell, items in matrix.items()}
        except SQLAlchemyError:
            await session.rollback()
            raise
