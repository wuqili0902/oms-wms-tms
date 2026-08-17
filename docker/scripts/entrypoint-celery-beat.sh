#!/bin/sh
set -e

echo "Starting Celery beat..."
exec celery -A src.celeryconf beat --loglevel=info
