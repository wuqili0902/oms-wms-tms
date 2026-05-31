import time

from src.celery_app import app


@app.task(bind=True)
def example_task(self, message: str = "Hello, World!"):
    """Example task that demonstrates basic Celery usage.

    Args:
        message (str): Message to log and return.

    Returns:
        str: Echoed message with timestamp.
    """
    try:
        # Simulate some work
        time.sleep(1)
        result = f"{message} - Processed at {time.strftime('%Y-%m-%S')}"
        return result
    except Exception as exc:
        self.logger.error("Example task failed: %s", str(exc))
        raise


@app.task(bind=True)
def scheduled_task(self):
    """Template for Celery Beat scheduled tasks.

    This task should be configured in celeryconf.py to run periodically.
    Replace the placeholder code with your actual scheduled logic.
    """
    try:
        self.logger.info("Scheduled task running at %s", time.strftime("%Y-%m-%S"))
        # Add your scheduled logic here
        return "Scheduled task completed"
    except Exception as exc:
        self.logger.error("Scheduled task failed: %s", str(exc))
        raise


@app.task(bind=True)
def cleanup_task(self):
    """Example cleanup task that should be run periodically.

    This is a placeholder for actual cleanup logic (e.g., deleting expired records,
    cleaning up temporary files, etc.).
    """
    try:
        self.logger.info("Running cleanup at %s", time.strftime("%Y-%m-%S"))
        # Add your cleanup logic here
        return "Cleanup completed"
    except Exception as exc:
        self.logger.error("Cleanup task failed: %s", str(exc))
        raise


@app.task(bind=True)
def health_check_task(self):
    """Example health check task that should be run periodically.

    This is a placeholder for actual health check logic (e.g., checking database
    connectivity, Redis availability, etc.).
    """
    try:
        self.logger.info("Running health check at %s", time.strftime("%Y-%m-%S"))
        # Add your health check logic here
        return "Health check passed"
    except Exception as exc:
        self.logger.error("Health check failed: %s", str(exc))
        raise
