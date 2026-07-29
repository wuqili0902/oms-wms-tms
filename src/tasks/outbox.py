import logging

import httpx

from src.celery_app import app
from src.config import settings
from src.core.outbox import dispatch_pending_events, mark_dispatched, mark_failed
from src.tasks.base import BaseTask

logger = logging.getLogger(__name__)


@app.task(base=BaseTask, bind=True, max_retries=3, countdown=30)
async def dispatch_outbox_events(self):
    """Poll pending outbox events and dispatch them via HTTP POST.

    This task is called every minute by Celery Beat.  For each pending
    event we POST to ``outbox_dispatch_url``; if successful the event is
    marked ``dispatched``, otherwise ``failed`` (with auto-retry in 60 s).
    """
    events = await dispatch_pending_events(batch_size=100)
    if not events:
        return {"dispatched": 0, "failed": 0}

    dispatched_ids = []
    failed_count = 0

    async with httpx.AsyncClient(timeout=10) as client:
        for event in events:
            try:
                payload = {
                    "event_id": str(event.id),
                    "aggregate_type": event.aggregate_type,
                    "aggregate_id": str(event.aggregate_id),
                    "event_type": event.event_type,
                    "payload": event.payload,
                }
                resp = await client.post(settings.outbox_dispatch_url, json=payload)
                resp.raise_for_status()
                dispatched_ids.append(event.id)
            except Exception as exc:
                await mark_failed(event.id, str(exc))
                failed_count += 1
                logger.error("Failed to dispatch outbox event %s: %s", event.id, exc)

    if dispatched_ids:
        count = await mark_dispatched(dispatched_ids)
        logger.info("Dispatched %d outbox events", count)

    return {"dispatched": len(dispatched_ids), "failed": failed_count}
