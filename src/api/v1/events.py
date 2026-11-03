"""Internal event-ingest endpoint — the receiving end of the outbox pipeline.

``src.tasks.outbox.dispatch_outbox_events`` POSTs each pending outbox event to
``settings.outbox_dispatch_url``, which defaults to
``POST /api/v1/events/ingest`` on this very app.  Before this module existed
the URL pointed at a route that was never implemented, so every dispatched
event failed with 404 and the outbox chain could never complete.

Security: requests must carry an HMAC-SHA256 signature computed from the
shared ``settings.secret_key`` over ``"{timestamp}.{event_id}"``, with the
timestamp inside a ±300 s window — enough to keep the endpoint unreachable
from anything that doesn't know the signing key.
"""
import hashlib
import hmac
import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/events", tags=["events"])

#: Max allowed skew (seconds) between the signer's clock and ours.
SIGNATURE_WINDOW_SECONDS = 300


class EventIngestPayload(BaseModel):
    event_id: str = Field(min_length=1, max_length=64)
    aggregate_type: str = Field(min_length=1, max_length=64)
    aggregate_id: str = Field(min_length=1, max_length=64)
    event_type: str = Field(min_length=1, max_length=128)
    payload: dict = Field(default_factory=dict)


def compute_internal_signature(secret: str, timestamp: str, event_id: str) -> str:
    """Signature scheme shared with the outbox dispatcher task."""
    return hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{event_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


async def verify_internal_signature(request: Request) -> None:
    """FastAPI dependency enforcing the internal HMAC on ingest requests."""
    timestamp = request.headers.get("X-Internal-Timestamp", "")
    signature = request.headers.get("X-Internal-Signature", "")
    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing internal signature headers")

    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid internal timestamp") from exc

    now = int(time.time())
    if abs(now - ts) > SIGNATURE_WINDOW_SECONDS:
        raise HTTPException(status_code=401, detail="Internal signature timestamp out of window")

    # The event id is needed to recompute the HMAC; read it from the raw body
    # (the validated EventIngestPayload is parsed separately by the endpoint).
    try:
        body = await request.json()
        event_id = str(body.get("event_id", "")) if isinstance(body, dict) else ""
    except Exception:
        event_id = ""
    if not event_id:
        raise HTTPException(status_code=401, detail="Cannot verify signature: event_id missing")

    expected = compute_internal_signature(settings.secret_key, timestamp, event_id)
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid internal signature")


@router.post("/ingest", dependencies=[Depends(verify_internal_signature)])
async def ingest_event(body: EventIngestPayload) -> dict:
    """Accept one dispatched outbox event.

    The dispatcher marks the event DISPATCHED only when this returns 2xx, so
    this handler must fail loudly for anything it cannot accept.
    """
    logger.info(
        "Outbox event ingested: id=%s type=%s aggregate=%s/%s",
        body.event_id, body.event_type, body.aggregate_type, body.aggregate_id,
    )
    # Downstream projection/logging hook; kept deliberately light so the
    # endpoint stays idempotent and cannot 500 on consumer-side issues.
    return {
        "status": "received",
        "event_id": body.event_id,
        "received_at": datetime.now(UTC).isoformat(),
    }
