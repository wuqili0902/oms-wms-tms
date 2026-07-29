#!/bin/sh
set -e

# Run database migrations before starting the application
echo "Running database migrations..."
alembic upgrade head
echo "Migrations complete."

# Execute the main command (uvicorn)
exec "$@"
