from celery.schedules import crontab
from src.celery_app import app


# Configure Beat schedule for periodic tasks
beat_schedule = {
    # Example: Run cleanup_task every 10 minutes
    # "cleanup-every-10m": {
    #     "task": "src.tasks.example.cleanup_task",
    #     "schedule": crontab(minute=range(0, 60, 10)),
    # },

    # Example: Run health check every 5 minutes
    # "health-check-every-5m": {
    #     "task": "src.tasks.example.health_check_task",
    #     "schedule": crontab(minute=range(0, 60, 5)),
    # },

    # Example: Run data sync every hour
    # "data-sync-every-hour": {
    #     "task": "src.tasks.example.data_sync_task",
    #     "schedule": crontab(hour="*"),
    # },
}


# Apply the beat schedule to the Celery app
app.conf.beat_schedule = beat_schedule
