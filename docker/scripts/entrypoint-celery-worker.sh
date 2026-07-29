#!/bin/sh
set -e

echo "Starting Celery worker..."
exec celery -A src.celery_app worker --loglevel=info --concurrency=4
