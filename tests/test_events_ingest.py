"""Tests for src/api/v1/events.py — the outbox ingest endpoint."""
import time
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.v1.events import compute_internal_signature
from src.config import settings
from src.main import app


def _signed_headers(event_id: str, timestamp: str | None = None) -> dict[str, str]:
    ts = timestamp or str(int(time.time()))
    return {
        "X-Internal-Timestamp": ts,
        "X-Internal-Signature": compute_internal_signature(settings.secret_key, ts, event_id),
    }


def _payload(event_id: str) -> dict:
    return {
        "event_id": event_id,
        "aggregate_type": "Order",
        "aggregate_id": str(uuid.uuid4()),
        "event_type": "order.created",
        "payload": {"amount": 50},
    }


@pytest.mark.asyncio
async def test_ingest_accepts_signed_event():
    event_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/events/ingest", json=_payload(event_id), headers=_signed_headers(event_id),
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "received"
    assert data["event_id"] == event_id


@pytest.mark.asyncio
async def test_ingest_rejects_missing_headers():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/events/ingest", json=_payload(str(uuid.uuid4())))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ingest_rejects_bad_signature():
    event_id = str(uuid.uuid4())
    headers = _signed_headers(event_id)
    headers["X-Internal-Signature"] = "0" * 64
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/events/ingest", json=_payload(event_id), headers=headers)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ingest_rejects_stale_timestamp():
    event_id = str(uuid.uuid4())
    stale = str(int(time.time()) - 3600)  # 1 h outside the ±300 s window
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/events/ingest",
            json=_payload(event_id),
            headers=_signed_headers(event_id, timestamp=stale),
        )
    assert resp.status_code == 401


def test_signature_helper_is_stable():
    a = compute_internal_signature("secret", "1700000000", "evt-1")
    b = compute_internal_signature("secret", "1700000000", "evt-1")
    c = compute_internal_signature("secret", "1700000000", "evt-2")
    assert a == b
    assert a != c
    assert len(a) == 64
