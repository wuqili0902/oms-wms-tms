import logging
import time

import httpx

from src.api.v1.events import compute_internal_signature
from src.celery_app import app
from src.config import settings
from src.core.outbox import dispatch_pending_events, mark_dispatched, mark_failed
from src.tasks.base import BaseTask

logger = logging.getLogger(__name__)


def _internal_auth_headers(event_id: str) -> dict[str, str]:
    """HMAC headers proving this POST comes from our own dispatcher."""
    timestamp = str(int(time.time()))
    signature = compute_internal_signature(settings.secret_key, timestamp, event_id)
    return {
        "X-Internal-Timestamp": timestamp,
        "X-Internal-Signature": signature,
    }


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
            # dispatch_pending_events returns plain dicts (serialised copies),
            # not ORM objects — attribute access here used to blow up with
            # AttributeError on every single event.
            event_id = event["id"]
            try:
                payload = {
                    "event_id": str(event_id),
                    "aggregate_type": event["aggregate_type"],
                    "aggregate_id": str(event["aggregate_id"]),
                    "event_type": event["event_type"],
                    "payload": event["payload"],
                }
                headers = _internal_auth_headers(str(event_id))
                resp = await client.post(
                    settings.outbox_dispatch_url, json=payload, headers=headers,
                )
                resp.raise_for_status()
                dispatched_ids.append(event_id)
            except Exception as exc:
                await mark_failed(event_id, str(exc))
                failed_count += 1
                logger.error("Failed to dispatch outbox event %s: %s", event_id, exc)

    if dispatched_ids:
        count = await mark_dispatched(dispatched_ids)
        logger.info("Dispatched %d outbox events", count)

    return {"dispatched": len(dispatched_ids), "failed": failed_count}
