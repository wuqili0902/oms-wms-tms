import logging
from typing import Any, Dict, Optional

from celery import Task as CeleryTask
from sqlalchemy.exc import SQLAlchemyError


class BaseTask(CeleryTask):
    """Base task class with retry, logging, and error handling."""

    # Default retry settings
    max_retries = 3
    countdown = 60  # Seconds to wait before retrying

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__name__)

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
        if isinstance(exc, CeleryTask.Retry):
            self.logger.warning(
                "Task %s will retry in %d seconds",
                self.request.id,
                exc.countdown or 60,
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

    def __init__(self, name, level=None, *args, **kwargs):
        super().__init__(name=name, level=level, *args, **kwargs)
        self.task_id = None

    def set_task_context(self, task_id: str):
        """Set the task context for logging."""
        self.task_id = task_id

    def _format(self, record):
        """Add task ID to log messages if available."""
        msg = super()._format(record)
        if self.task_id:
            return f"[{self.task_id}] {msg}"
        return msg


def get_task_logger(name: str) -> TaskLogger:
    """Get a logger with task context for Celery tasks."""
    logger = logging.getLogger(f"{__name__}.{name}")
    if not isinstance(logger, TaskLogger):
        logger = TaskLogger(name=name, level=logging.DEBUG)
    return logger
