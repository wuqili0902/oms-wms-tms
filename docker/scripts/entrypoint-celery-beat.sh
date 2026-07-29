#!/bin/sh
set -e

echo "Starting Celery beat..."
exec celery -A src.celery_app beat --loglevel=info --scheduler celery.beat.PersistentScheduler
