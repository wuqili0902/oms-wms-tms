#!/bin/sh
set -e

echo "Starting Celery worker..."
exec celery -A src.celeryconf worker --loglevel=info --concurrency=4
