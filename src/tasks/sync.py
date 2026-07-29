"""Background sync task for PDA offline queue.

Pushes pending local mutations back to the remote PostgreSQL server
when the PDA device reconnects.  Designed to run periodically or on
network-available events.
"""
import json
import logging

import httpx

from src.celery_app import app
from src.config import settings
from src.tasks.base import BaseTask

logger = logging.getLogger(__name__)

# Remote sync endpoint
SYNC_URL = f"http://{settings.host}:{settings.port}/api/v1/sync/push"


@app.task(base=BaseTask, bind=True, max_retries=3, countdown=30)
async def process_pda_sync_queue(self, local_db_path: str = "wms_pda.db"):
    """Poll the local PDA sync queue and push pending mutations upstream.

    This task reads from the local SQLite ``sync_queue`` table, sends
    each pending mutation to the remote HTTP endpoint
    ``POST /api/v1/sync/push``, and marks them as synced on success.
    """
    from src.core.offline import SyncQueueService

    svc = SyncQueueService(local_db_path)
    pending = svc.get_pending(limit=50)

    if not pending:
        return {"pushed": 0, "failed": 0}

    pushed_ids = []
    failed_count = 0

    async with httpx.AsyncClient(timeout=15) as client:
        for record in pending:
            try:
                payload = {
                    "entity_type": record.entity_type,
                    "entity_id": record.entity_id,
                    "operation": record.operation,
                    "payload": json.loads(record.payload),
                }
                resp = await client.post(SYNC_URL, json={"batch": [payload]})
                resp.raise_for_status()
                pushed_ids.append(record.id)
            except Exception as exc:
                svc.mark_failed(record.id, str(exc))
                failed_count += 1
                logger.error("Failed to push sync item %s: %s", record.id, exc)

    if pushed_ids:
        count = svc.mark_synced(pushed_ids)
        logger.info("Pushed %d sync queue items upstream", count)

    return {"pushed": len(pushed_ids), "failed": failed_count}
