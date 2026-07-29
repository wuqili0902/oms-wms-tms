#!/bin/bash
# Database backup script for oms-wms-tms (PostgreSQL)
# Usage: PG_PASSWORD=secret ./backup-db.sh [output-dir]

set -euo pipefail

OUTPUT_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${OUTPUT_DIR}/oms_wms_tms_${TIMESTAMP}.sql.gz"
KEEP_DAYS=30

PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-postgres}"
PG_DATABASE="${PG_DATABASE:-oms_wms_tms}"
PG_PASSWORD="${PG_PASSWORD:-}"

mkdir -p "${OUTPUT_DIR}"

export PGPASSWORD="${PG_PASSWORD}"

echo "Backing up ${PG_DATABASE} → ${BACKUP_FILE}..."
pg_dump -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DATABASE}" \
    --format=custom \
    --compress=9 \
    --verbose \
    --file="${BACKUP_FILE}" 2>&1 | tail -5

echo "Removing backups older than ${KEEP_DAYS} days..."
find "${OUTPUT_DIR}" -name "oms_wms_tms_*.sql.gz" -mtime +${KEEP_DAYS} -delete

echo "Backup complete: ${BACKUP_FILE}"
