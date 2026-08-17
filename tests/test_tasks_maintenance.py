"""Tests for tasks/maintenance.py — Celery maintenance tasks."""
import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.tms.models import SyncLog, SyncLogStatus, SyncLogType


@pytest.mark.asyncio
async def test_cleanup_old_sync_logs(db_session):
    from src.tasks.maintenance import cleanup_old_sync_logs

    old = SyncLog(
        id=uuid4(),
        device_id=uuid4(),
        sync_type=SyncLogType.UPLOAD,
        status=SyncLogStatus.COMPLETED,
        started_at=datetime.now(UTC) - timedelta(days=31),
        completed_at=datetime.now(UTC) - timedelta(days=31),
    )
    recent = SyncLog(
        id=uuid4(),
        device_id=uuid4(),
        sync_type=SyncLogType.DOWNLOAD,
        status=SyncLogStatus.COMPLETED,
        started_at=datetime.now(UTC) - timedelta(days=1),
        completed_at=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add_all([old, recent])
    await db_session.commit()

    with patch("src.tasks.maintenance.get_session") as mock_get_session:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=db_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_ctx

        result = await cleanup_old_sync_logs.run()
        assert "deleted_sync_logs" in result


@pytest.mark.asyncio
async def test_cleanup_expired_tokens():
    from src.tasks.maintenance import cleanup_expired_tokens

    result = await cleanup_expired_tokens.run()
    assert "expired_tokens_removed" in result
    assert isinstance(result["expired_tokens_removed"], int)


@pytest.mark.asyncio
async def test_health_check(db_session):
    from src.tasks.maintenance import health_check

    with patch("src.tasks.maintenance.get_session") as mock_get_session:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=db_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_ctx

        with patch("redis.asyncio.from_url") as mock_redis:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock()
            mock_client.aclose = AsyncMock()
            mock_redis.return_value = mock_client

            result = await health_check.run()
            assert result["database"] is True
            assert result["redis"] is True


@pytest.mark.asyncio
async def test_health_check_redis_failure(db_session):
    from src.tasks.maintenance import health_check

    with patch("src.tasks.maintenance.get_session") as mock_get_session:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=db_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_ctx

        with patch("redis.asyncio.from_url", side_effect=ConnectionError("Redis down")):
            result = await health_check.run()
            assert result["database"] is True
            assert result["redis"] is False


@pytest.mark.asyncio
async def test_daily_aggregation(db_session):
    from src.tasks.maintenance import daily_aggregation

    with patch("src.tasks.maintenance.get_session") as mock_get_session:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=db_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_ctx

        result = await daily_aggregation.run()
        assert "total_orders" in result
        assert "orders_today" in result
        assert "total_inventory_items" in result
        assert "date" in result


@pytest.mark.asyncio
async def test_compute_abc_xyz_analysis(db_session):
    from src.tasks.maintenance import compute_abc_xyz_analysis

    with patch("src.tasks.maintenance.get_session") as mock_get_session:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=db_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = mock_ctx

        with patch("src.wms.analysis.compute_abc_xyz_matrix", new_callable=AsyncMock) as mock_matrix:
            mock_matrix.return_value = {"AX": ["sku1"], "BY": ["sku2"]}

            with patch("src.cache.redis_client.get_redis") as mock_get_redis:
                mock_redis = AsyncMock()
                mock_redis.setex = AsyncMock()
                mock_get_redis.return_value.__aenter__ = AsyncMock(return_value=mock_redis)
                mock_get_redis.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await compute_abc_xyz_analysis.run()
                assert result["AX"] == 1
                assert result["BY"] == 1
