"""Celery task base class with an asyncio bridge.

Celery does not natively support ``async def`` tasks: calling one returns an
un-awaited coroutine object and the task "succeeds" without doing any work.
``BaseTask.__call__`` below bridges this gap (the pattern from the Celery
docs' "Calling a Coroutine from a Celery Task").

Event-loop design:
    A *persistent per-thread* event loop is used instead of ``asyncio.run()``
    because the shared async SQLAlchemy engine binds its pooled connections
    to the loop on which they were first opened.  Creating a fresh loop per
    task would leak/break those connections.  With the default prefork pool
    each worker process has one main thread, hence one loop, hence a
    consistent engine pool.

Test compatibility:
    When called from inside an already-running event loop (pytest-asyncio
    tests that ``await task_object(...)``), the coroutine is returned
    untouched so the caller can await it, preserving the previous behavior.
"""
import asyncio
import inspect
import logging
import threading

from celery import Task as CeleryTask
from celery.exceptions import Retry as CeleryRetry
from sqlalchemy.exc import SQLAlchemyError

_task_loop_local = threading.local()


def _worker_event_loop() -> asyncio.AbstractEventLoop:
    """Return the persistent event loop for the current worker thread."""
    loop = getattr(_task_loop_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _task_loop_local.loop = loop
    return loop


class BaseTask(CeleryTask):
    """Base task class with coroutine bridge, retry, logging, and error handling."""

    abstract = True

    # Default retry settings
    max_retries = 3
    countdown = 60  # Seconds to wait before retrying

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__name__)

    def __call__(self, *args, **kwargs):
        """Execute the task, awaiting coroutines on a persistent event loop.

        * Celery worker path (no running loop): the coroutine is executed to
          completion here, so the periodic task's body actually runs.
        * Async test path (loop already running): the coroutine is returned
          unchanged so ``await task(...)`` keeps working.
        """
        result = self.run(*args, **kwargs)
        if inspect.iscoroutine(result):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return _worker_event_loop().run_until_complete(result)
            return result
        return result

    def before_start(self, task_id=None, *args, **kwargs):
        """Called when the task is about to start."""
        super().before_start(task_id=task_id, *args, **kwargs)
        self.logger.info(
            "Task %s starting with args: %s",
            task_id or self.request.id,
            args,
        )

    def on_success(self, result=None, *args, **kwargs):
        """Called when the task succeeds."""
        super().on_success(result=result, *args, **kwargs)
        self.logger.info(
            "Task %s succeeded with result: %s",
            self.request.id,
            result,
        )

    def on_failure(self, exc=None, *args, **kwargs):
        """Called when the task fails."""
        super().on_failure(exc=exc, *args, **kwargs)
        if isinstance(exc, CeleryRetry):
            self.logger.warning(
                "Task %s will retry in %d seconds",
                self.request.id,
                getattr(exc, 'countdown', None) or getattr(exc, 'when', None) or 60,
            )
        else:
            self.logger.error(
                "Task %s failed with error: %s",
                self.request.id,
                str(exc),
                exc_info=True,
            )

    def after_return(self, *args, **kwargs):
        """Called when the task returns."""
        super().after_return(*args, **kwargs)
        self.logger.info(
            "Task %s returned with args: %s",
            self.request.id,
            args,
        )

    def retry_on_db_error(self, exc=None):
        """Retry the task if a database error occurred."""
        if isinstance(exc, SQLAlchemyError):
            self.logger.warning(
                "Database error in task %s: %s. Retrying...",
                self.request.id,
                str(exc),
            )
            raise self.retry(countdown=self.countdown)

    def execute_with_retry(self, func, *args, **kwargs):
        """Execute a function with retry logic for database errors."""
        try:
            return func(*args, **kwargs)
        except SQLAlchemyError as exc:
            self.retry_on_db_error(exc)


class TaskLogger(logging.Logger):
    """Custom logger for tasks that adds task context to log messages."""

    def __init__(self, name, level=logging.NOTSET, *args, **kwargs):
        super().__init__(name=name, level=level, *args, **kwargs)
        self.task_id = None

    def set_task_context(self, task_id: str):
        """Set the task context for logging."""
        self.task_id = task_id

    # Note: Log message formatting is handled by Formatter, not Logger.
    # Task context injection should be done via a custom logging Filter/Formatter.


def get_task_logger(name: str) -> TaskLogger:
    """Get a logger with task context for Celery tasks."""
    logger = logging.getLogger(f"{__name__}.{name}")
    if not isinstance(logger, TaskLogger):
        logger = TaskLogger(name=name, level=logging.DEBUG)
    return logger
