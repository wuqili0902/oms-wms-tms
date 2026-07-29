import hashlib
import hmac
import json
import logging
import time

import httpx
from sqlalchemy import select

from src.webhooks.models import (
    DeliveryStatus,
    WebhookDeliveryLog,
    WebhookEvent,
    WebhookStatus,
    WebhookTarget,
)

logger = logging.getLogger(__name__)


async def dispatch_event(event: WebhookEvent, payload: dict, db=None):
    if db is None:
        from src.core.database import get_session
        async with get_session() as session:
            await _do_dispatch(session, event, payload)
            await session.commit()
    else:
        await _do_dispatch(db, event, payload)


async def _do_dispatch(db, event: WebhookEvent, payload: dict):
    result = await db.execute(
        select(WebhookTarget).where(
            WebhookTarget.status == WebhookStatus.ACTIVE,
        )
    )
    targets = result.scalars().all()

    matching = [t for t in targets if event.value in (json.loads(t.events) if t.events else [])]
    if not matching:
        logger.debug("No webhook targets for event %s", event.value)
        return

    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    async with httpx.AsyncClient(timeout=30) as client:
        for target in matching:
            await _deliver(db, client, target, event, payload_json)


async def _deliver(db, client, target: WebhookTarget, event: WebhookEvent, payload: str):
    headers = {"Content-Type": "application/json", "X-Webhook-Event": event.value}
    if target.secret:
        signature = hmac.new(target.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = signature

    log = WebhookDeliveryLog(target_id=target.id, event=event.value, payload=payload)
    db.add(log)
    await db.flush()

    start = time.monotonic()
    try:
        resp = await client.post(target.url, content=payload, headers=headers)
        elapsed = int((time.monotonic() - start) * 1000)
        log.status = DeliveryStatus.SUCCESS if resp.is_success else DeliveryStatus.FAILED
        log.status_code = resp.status_code
        log.response_body = resp.text[:1000]
        log.duration_ms = elapsed
        logger.info("Webhook %s -> %s (%d, %dms)", event.value, target.url, resp.status_code, elapsed)
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        log.status = DeliveryStatus.FAILED
        log.response_body = str(e)[:1000]
        log.duration_ms = elapsed
        logger.warning("Webhook %s -> %s failed: %s", event.value, target.url, e)

    await db.flush()
