import hashlib
import hmac
import json
import logging
import time
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select

from src.core.outbox import append_event
from src.webhooks.models import (
    DeliveryStatus,
    WebhookDeliveryLog,
    WebhookEvent,
    WebhookStatus,
    WebhookTarget,
)

logger = logging.getLogger(__name__)


async def _do_dispatch(db, event: WebhookEvent, payload: dict):
    result = await db.execute(
        select(WebhookTarget).where(
            WebhookTarget.status == WebhookStatus.ACTIVE,
        )
    )
    targets = result.scalars().all()

    matching: list[WebhookTarget] = []
    for t in targets:
        try:
            target_events = json.loads(t.events) if isinstance(t.events, str) else (t.events or [])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid JSON in webhook target %d events, skipping", t.id)
            continue
        if event.value in target_events:
            matching.append(t)

    if not matching:
        logger.debug("No webhook targets for event %s", event.value)
        return []

    outbox_payload = {
        "event_type": event.value,
        "payload": payload,
        "target_ids": [str(t.id) for t in matching],
    }

    # Deliver webhooks immediately (synchronous for backward compatibility).
    # Collect per-delivery results first, then write logs — so each log reflects the
    # actual outcome instead of being marked SUCCESS unconditionally.
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)

    delivery_results: list[dict] = []
    async with httpx.AsyncClient(timeout=15) as client:
        for target in matching:
            result = await _deliver(db, client, target, event, payload_json)
            delivery_results.append(result)

    # Write delivery logs reflecting the actual delivery outcome (committed in caller's transaction)
    delivery_logs: list[WebhookDeliveryLog] = []
    for target, result in zip(matching, delivery_results):
        status = DeliveryStatus.SUCCESS if result["success"] else DeliveryStatus.FAILED
        log = WebhookDeliveryLog(
            target_id=target.id,
            event=event.value,
            payload=payload_json,
            status=status,
            status_code=result["status_code"],
            response_body=result["response_body"],
            duration_ms=result["duration_ms"],
        )
        db.add(log)
        delivery_logs.append(log)

    await db.flush()

    # Append outbox event for async Celery dispatch (committed in caller's transaction)
    try:
        await append_event(
            db,
            aggregate_type="Webhook",
            aggregate_id=uuid4(),
            event_type="webhook.dispatch",
            payload=outbox_payload,
        )
    except Exception as e:
        logger.warning("Failed to create outbox event for webhook dispatch: %s", e)

    return delivery_logs


async def dispatch_event(event: WebhookEvent, payload: dict, db=None):
    """Dispatch webhook event — writes delivery logs + outbox event within caller's transaction."""
    if db is None:
        from src.core.database import get_session
        async with get_session() as session:
            await _do_dispatch(session, event, payload)
            await session.commit()
    else:
        await _do_dispatch(db, event, payload)


async def _deliver(db, client, target: WebhookTarget, event: WebhookEvent, payload: str) -> dict:
    """Deliver a single webhook. Returns the outcome captured in the delivery log."""
    headers = {"Content-Type": "application/json", "X-Webhook-Event": event.value}
    if target.secret:
        timestamp = str(int(time.time()))
        msg = f"{timestamp}:{payload}"
        signature = hmac.new(target.secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = signature
        headers["X-Webhook-Timestamp"] = timestamp

    start = time.monotonic()
    try:
        resp = await client.post(target.url, content=payload, headers=headers)
        elapsed = int((time.monotonic() - start) * 1000)
        logger.info("Webhook %s -> %s delivered in %dms (status=%d)", event.value, target.url, elapsed, resp.status_code)  # noqa: E501
        return {
            "success": resp.is_success,
            "status_code": resp.status_code,
            "response_body": resp.text[:1000],
            "duration_ms": elapsed,
        }
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.warning("Webhook %s -> %s failed after %dms: %s", event.value, target.url, elapsed, e)
        return {
            "success": False,
            "status_code": None,
            "response_body": str(e)[:1000],
            "duration_ms": elapsed,
        }


async def _deliver_async(
    target_id: int | UUID,
    url: str,
    secret: str | None,
    event_value: str,
    payload_str: str,
):
    """Deliver a single webhook via Celery task (async)."""
    headers = {"Content-Type": "application/json", "X-Webhook-Event": event_value}
    if secret:
        timestamp = str(int(time.time()))
        msg = f"{timestamp}:{payload_str}"
        signature = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = signature
        headers["X-Webhook-Timestamp"] = timestamp

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, content=payload_str, headers=headers)
            elapsed = int((time.monotonic() - start) * 1000)
            return {
                "success": resp.is_success,
                "status_code": resp.status_code,
                "response_body": resp.text[:1000],
                "duration_ms": elapsed,
            }
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.warning("Webhook %s -> %s failed: %s", event_value, url, e)
        return {
            "success": False,
            "status_code": None,
            "response_body": str(e)[:1000],
            "duration_ms": elapsed,
        }
