"""Tests for Celery task definitions.

Note: Methods that call ``super()`` (before_start, on_success, on_failure,
after_return) require a Celery runtime — they are tested indirectly via
integration coverage.

``execute_with_retry`` is a simple wrapper around ``retry_on_db_error``
and is tested through that path.
"""
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError


class TestBaseTask:
    """BaseTask retry helpers via unbound-method call on a mock."""

    def _task(self):
        """Return a real BaseTask instance with logger patched."""
        from src.tasks.base import BaseTask
        import threading
        t = BaseTask()
        t.logger = MagicMock()
        t.retry = MagicMock(side_effect=Exception("retry"))
        t.countdown = 60
        t.request_stack = threading.local()
        t.request_stack.top = MagicMock()
        t.request_stack.top.id = "task-1"
        t.request_stack.top.args = ()
        t.request_stack.top.kwargs = {}
        return t

    def test_defaults(self):
        from src.tasks.base import BaseTask
        assert BaseTask.max_retries == 3
        assert BaseTask.countdown == 60

    def test_retry_on_db_error_raises(self):
        from src.tasks.base import BaseTask
        t = self._task()
        with pytest.raises(Exception):
            BaseTask.retry_on_db_error(t, SQLAlchemyError("db"))
        t.logger.warning.assert_called_once()

    def test_retry_on_db_error_ignores_non_db(self):
        from src.tasks.base import BaseTask
        t = self._task()
        BaseTask.retry_on_db_error(t, ValueError("no"))
        t.retry.assert_not_called()

    def _task_with_request(self):
        """Return a BaseTask with logger patched and fake request."""
        from src.tasks.base import BaseTask
        import threading
        t = BaseTask()
        t.logger = MagicMock()
        t.request_stack = threading.local()
        t.request_stack.top = MagicMock()
        t.request_stack.top.id = "task-1"
        t.request_stack.top.args = ()
        t.request_stack.top.kwargs = {}
        return t

    def test_before_start_no_task_id(self):
        from src.tasks.base import BaseTask
        from celery.app.task import Task
        t = self._task_with_request()
        with patch.object(Task, "before_start", return_value=None):
            BaseTask.before_start(t, task_id=None, args=(), kwargs={})
            t.logger.info.assert_called_once()

    def test_on_success(self):
        from src.tasks.base import BaseTask
        from celery.app.task import Task
        t = self._task_with_request()
        with patch.object(Task, "on_success", return_value=None):
            BaseTask.on_success(t, retval="ok", task_id="t1", args=(), kwargs={})
            t.logger.info.assert_called_once()

    def test_on_failure_celery_retry(self):
        from src.tasks.base import BaseTask
        from celery.app.task import Task
        from celery.exceptions import Retry as CeleryRetry
        t = self._task_with_request()
        with patch.object(Task, "on_failure", return_value=None):
            exc = CeleryRetry(exc=Exception("transient"), when=60)
            BaseTask.on_failure(t, exc=exc, task_id="t1", args=(), kwargs={}, einfo=None)
            t.logger.warning.assert_called_once()

    def test_on_failure_other(self):
        from src.tasks.base import BaseTask
        from celery.app.task import Task
        t = self._task_with_request()
        with patch.object(Task, "on_failure", return_value=None):
            BaseTask.on_failure(t, exc=ValueError("bad"), task_id="t1", args=(), kwargs={}, einfo=None)
            t.logger.error.assert_called_once()

    def test_after_return(self):
        from src.tasks.base import BaseTask
        from celery.app.task import Task
        t = self._task_with_request()
        with patch.object(Task, "after_return", return_value=None):
            BaseTask.after_return(t, status="SUCCESS", retval="ok", task_id="t1", args=(), kwargs={}, einfo=None)
            t.logger.info.assert_called_once()

    def test_execute_with_retry_success(self):
        from src.tasks.base import BaseTask
        t = self._task()
        fn = MagicMock(return_value=42)
        result = BaseTask.execute_with_retry(t, fn, 1, 2, key="v")
        assert result == 42
        fn.assert_called_once_with(1, 2, key="v")

    def test_execute_with_retry_db_error(self):
        from src.tasks.base import BaseTask
        from sqlalchemy.exc import SQLAlchemyError
        t = self._task()
        t.retry.side_effect = Exception("retry-called")
        fn = MagicMock(side_effect=SQLAlchemyError("db down"))
        with pytest.raises(Exception):
            BaseTask.execute_with_retry(t, fn)
        t.logger.warning.assert_called_once()


class TestTaskLogger:
    def test_create(self):
        from src.tasks.base import TaskLogger
        assert TaskLogger(name="x").name == "x"

    def test_set_context(self):
        from src.tasks.base import TaskLogger
        l = TaskLogger(name="x")
        l.set_task_context("tid")
        assert l.task_id == "tid"

    def test_get_task_logger(self):
        from src.tasks.base import get_task_logger, TaskLogger
        assert isinstance(get_task_logger("my"), TaskLogger)


# --- tasks/sync.py tests ---


class TestSyncTasks:
    """Tests for ``src.tasks.sync`` – the PDA offline queue push task."""

    @pytest.mark.asyncio
    async def test_process_pda_sync_queue_empty(self):
        import src.tasks.sync as sync_module
        from src.tasks.sync import process_pda_sync_queue
        mock_svc = AsyncMock()
        mock_svc.get_pending.return_value = []
        with patch.object(sync_module, "SyncQueueService", return_value=mock_svc):
            r = await process_pda_sync_queue.run()
        assert r == {"pushed": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_process_pda_sync_queue_success(self):
        import src.tasks.sync as sync_module
        from src.tasks.sync import process_pda_sync_queue

        mock_record1 = MagicMock(id=1, entity_type="Order", entity_id="ORD-001", operation="create", payload='{"amount": 99.0}')
        mock_record2 = MagicMock(id=2, entity_type="InventoryAdjustment", entity_id="INV-010", operation="update", payload='{}')

        mock_svc = AsyncMock()
        mock_svc.get_pending.return_value = [mock_record1, mock_record2]
        mock_svc.mark_synced.return_value = 2
        mock_svc.mark_failed = MagicMock()

        async def _post(*a, **kw):
            return MagicMock(status_code=200)

        with patch.object(sync_module, "SyncQueueService", return_value=mock_svc), \
                patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__.return_value.post = AsyncMock(side_effect=_post)
            r = await process_pda_sync_queue.run()

        assert r["pushed"] == 2
        mock_svc.mark_synced.assert_called_once_with([1, 2])

    @pytest.mark.asyncio
    async def test_process_pda_sync_queue_partial_fail(self):
        import src.tasks.sync as sync_module
        from src.tasks.sync import process_pda_sync_queue

        mock_record = MagicMock(id=99, entity_type="Order", entity_id="ORD-099", operation="create", payload='{"amount": 10.0}')

        mock_svc = AsyncMock()
        mock_svc.get_pending.return_value = [mock_record]
        mock_svc.mark_synced = MagicMock(return_value=0)
        mock_svc.mark_failed = MagicMock()

        async def _post(*a, **kw):
            raise Exception("connection refused")

        with patch.object(sync_module, "SyncQueueService", return_value=mock_svc), \
                patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__.return_value.post = AsyncMock(side_effect=_post)
            r = await process_pda_sync_queue.run()

        assert r["failed"] == 1


# --- tasks/outbox.py tests ---


class TestOutboxTasks:
    """Tests for ``src.tasks.outbox`` – the outbox dispatcher task."""

    @pytest.mark.asyncio
    async def test_dispatch_outbox_events_empty(self):
        from src.tasks.outbox import dispatch_outbox_events
        with patch("src.tasks.outbox.dispatch_pending_events", return_value=AsyncMock()) as mock_get:
            mock_get.return_value = []
            r = await dispatch_outbox_events.run()
        assert r == {"dispatched": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_dispatch_outbox_success(self):
        from src.tasks.outbox import dispatch_outbox_events
        from uuid import uuid4

        ev1 = MagicMock(id=uuid4(), aggregate_type="Order", aggregate_id=uuid4(), event_type="order.created", payload='{"amount": 50}')
        ev2 = MagicMock(id=uuid4(), aggregate_type="Payment", aggregate_id=uuid4(), event_type="payment.processed", payload='{}')

        async def _get_pending(*a, **kw):
            return [ev1, ev2]

        with patch("src.tasks.outbox.dispatch_pending_events", side_effect=_get_pending), \
                patch("src.tasks.outbox.mark_dispatched", AsyncMock(return_value=2)), \
                patch("src.tasks.outbox.mark_failed", AsyncMock()), \
                patch("httpx.AsyncClient") as MockClient:
            async def _post(*a, **kw):
                return MagicMock(status_code=200)
            MockClient.return_value.__aenter__.return_value.post = AsyncMock(side_effect=_post)
            r = await dispatch_outbox_events.run()

        assert r["dispatched"] == 2

    @pytest.mark.asyncio
    async def test_dispatch_outbox_failure(self):
        from src.tasks.outbox import dispatch_outbox_events
        from uuid import uuid4

        ev1 = MagicMock(id=uuid4(), aggregate_type="Order", aggregate_id=uuid4(), event_type="order.created", payload='{"amount": 50}')

        async def _get_pending(*a, **kw):
            return [ev1]

        with patch("src.tasks.outbox.dispatch_pending_events", side_effect=_get_pending), \
                patch("src.tasks.outbox.mark_dispatched", AsyncMock(return_value=0)), \
                patch("src.tasks.outbox.mark_failed", AsyncMock()), \
                patch("httpx.AsyncClient") as MockClient:
            async def _post(*a, **kw):
                raise Exception("timeout")
            MockClient.return_value.__aenter__.return_value.post = AsyncMock(side_effect=_post)
            r = await dispatch_outbox_events.run()

        assert r["failed"] == 1


class TestOrdersTasks:
    @pytest.mark.asyncio
    async def test_process_stale_orders_empty(self, db_session):
        from src.tasks.orders import process_stale_orders
        with patch("src.tasks.orders._get_async_session", return_value=db_session):
            r = await process_stale_orders.run()
        assert r["stale_orders_flagged"] == 0

    @pytest.mark.asyncio
    async def test_cancel_abandoned_drafts_empty(self, db_session):
        from src.tasks.orders import cancel_abandoned_drafts
        with patch("src.tasks.orders._get_async_session", return_value=db_session):
            r = await cancel_abandoned_drafts.run()
        assert r["orders_cancelled"] == 0
