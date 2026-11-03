"""Server-side idempotency for replayed mutations.

Why this exists
---------------
The PDA client keeps a local FIFO queue of mutations and replays each one with
the same ``X-Idempotency-Key`` on every attempt.  A replay whose *response* was
lost is indistinguishable, on the phone, from one that never reached the
server: the operator's fetch timed out, but the row may already be committed.
The next attempt then sends the scan again — and the stock movement happens
twice.  The key made that detectable; nothing on the server read it, so every
replay inserted a second mutation and the FIFO barrier only ordered the
duplicates instead of removing them.

Design
------
    guard key  = "idempotency:<sha256(caller | METHOD | path?query | key)>"
    states     = IN_PROGRESS (short TTL)  ->  DONE (long TTL, response stored)

* first delivery of a key reserves the guard and runs the endpoint;
* the same key arriving while the first is still running answers 503 with
  ``Retry-After`` — a status the client treats as retryable, so the mutation
  stays queued instead of being filed as permanently rejected;
* the same key arriving after the first finished replays the first response
  verbatim, marked ``x-idempotency-replayed: true``;
* a first attempt that produced 401/403/408/429/5xx released the guard: those
  are not verdicts on the payload.  A token that expired mid-flight is the
  common case — the phone refreshes it and replays the *same* key, and a guard
  that kept the 401 would drop the operator's scan.
* the guard is scoped to the authenticated user (``sub``), not the token, so a
  refreshed token still recognises its own earlier request, and one user cannot
  poison another user's key by guessing it.

Only requests that carry the header *and* a valid bearer token are guarded —
that is exactly the replay surface (queued mutations are all authenticated).

When Redis is unreachable the guard is absent, not guessed: the request runs
unguarded and the gap is logged.  A guard that silently "worked" without a
store would be worse than an honest one, because the client's only remaining
protection is the order it keeps in its own queue.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any

from jose import JWTError
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.core.security import TokenExpired, TokenInvalid, decode_token

logger = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "x-idempotency-key"
REPLAYED_HEADER = "x-idempotency-replayed"

GUARDED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# A longer key is not a key anyone can replay meaningfully; guarding it would
# spend Redis on a value that is probably an attack or a bug.
MAX_KEY_LENGTH = 200

# A response that cannot be stored verbatim cannot be replayed either.  Not
# guarding it is the honest option: answering a replay with something other than
# the first response is how an operator ends up believing a scan landed twice.
MAX_REPLAYABLE_BODY_BYTES = 64 * 1024

# How long an unfinished request blocks its own replay.  Sized against the
# client's retry ladder (2s doubling to 5min, 8 attempts ≈ 8.5 minutes): a
# worker that died mid-request must not hold the key past the point where the
# phone gives up on the mutation.
IN_PROGRESS_TTL_SECONDS = 120

# How long a finished response stays replayable.  The client stops retrying a
# mutation long before this, so it only needs to outlive one flaky link.
DONE_TTL_SECONDS = 24 * 3600

RETRY_AFTER_SECONDS = 2

# Statuses that are not a verdict on the payload: the guard is released so a
# later attempt with a fresh token (or a healthy server) can still go through.
RELEASE_STATUSES = frozenset({401, 403, 408, 429})

_KEY_PREFIX = "idempotency"

_STATE_IN_PROGRESS = "in_progress"
_STATE_DONE = "done"

_IN_PROGRESS_JSON = json.dumps({"state": _STATE_IN_PROGRESS})


class IdempotencyStore:
    """Reserve / record / release one guard key."""

    async def claim(self, guard_key: str) -> dict[str, Any] | None:
        """Try to take the key.

        Returns ``None`` when the caller now owns it, otherwise the stored
        record (``{"state": ...}``).
        """
        raise NotImplementedError

    async def complete(
        self, guard_key: str, status: int, headers: list[tuple[str, str]], body: bytes
    ) -> None:
        raise NotImplementedError

    async def release(self, guard_key: str) -> None:
        raise NotImplementedError


class RedisIdempotencyStore(IdempotencyStore):
    """Guard stored in Redis, shared by every API worker.

    No connection is held: ``get_redis()`` is resolved per call, so a pool built
    on another event loop is re-created instead of being reused and failing deep
    inside the transport (the same hazard the WS fan-out publish already works
    around).
    """

    async def claim(self, guard_key: str) -> dict[str, Any] | None:
        from src.cache.redis_client import get_redis

        async with get_redis() as redis:
            # Two turns: the key can expire between the failed SETNX and the GET,
            # in which case this caller is first again rather than a duplicate.
            for _ in range(2):
                if await redis.set(guard_key, _IN_PROGRESS_JSON, nx=True, ex=IN_PROGRESS_TTL_SECONDS):
                    return None
                raw = await redis.get(guard_key)
                if raw is None:
                    continue
                record = _decode_record(raw)
                if record is None:
                    # Unreadable (wrong type, foreign writer): take the key over
                    # rather than answer 503 forever.
                    await redis.delete(guard_key)
                    continue
                return record
        logger.warning("idempotency: lost the claim race for %s twice; running unguarded", guard_key)
        return None

    async def complete(
        self, guard_key: str, status: int, headers: list[tuple[str, str]], body: bytes
    ) -> None:
        from src.cache.redis_client import get_redis

        record = {
            "state": _STATE_DONE,
            "status": status,
            "headers": [[name, value] for name, value in headers],
            "body_b64": base64.b64encode(body).decode("ascii"),
        }
        async with get_redis() as redis:
            await redis.set(guard_key, json.dumps(record), ex=DONE_TTL_SECONDS)

    async def release(self, guard_key: str) -> None:
        from src.cache.redis_client import get_redis

        async with get_redis() as redis:
            await redis.delete(guard_key)


def _decode_record(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return None
    try:
        record = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return record if isinstance(record, dict) else None


# Headers that describe the transport of the *original* response rather than its
# content.  Replayed under a body we stored separately, a stale content-length or
# chunked transfer-encoding is a lie the client would act on.
_UNREPLAYABLE_HEADERS = frozenset({
    "content-length", "transfer-encoding", "connection", "keep-alive",
    REPLAYED_HEADER, IDEMPOTENCY_HEADER,
})


def _storable_headers(headers: list[tuple[bytes, bytes]]) -> list[tuple[str, str]]:
    """Decode response headers, dropping the ones that cannot survive a replay."""
    kept: list[tuple[str, str]] = []
    for name, value in headers:
        decoded_name = name.decode("latin-1")
        if decoded_name.lower() in _UNREPLAYABLE_HEADERS:
            continue
        kept.append((decoded_name, value.decode("latin-1")))
    return kept


# ── Store indirection (tests and non-Redis deployments swap it here) ──────────

_default_store = RedisIdempotencyStore()


def get_store() -> IdempotencyStore:
    return _default_store


def set_store(store: IdempotencyStore | None) -> None:
    """Install a store implementation; ``None`` restores the Redis default."""
    global _default_store
    _default_store = RedisIdempotencyStore() if store is None else store


# ── Middleware ────────────────────────────────────────────────────────────────

class IdempotencyMiddleware:
    """Deduplicate mutations that arrive twice under the same key."""

    def __init__(self, app: ASGIApp, store: IdempotencyStore | None = None) -> None:
        self.app = app
        self._store = store

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        headers = Headers(scope=scope)
        raw_key = headers.get(IDEMPOTENCY_HEADER)
        if not raw_key or method not in GUARDED_METHODS:
            await self.app(scope, receive, send)
            return

        key = raw_key.strip()
        if not key:
            await self.app(scope, receive, send)
            return
        if len(key) > MAX_KEY_LENGTH:
            logger.warning(
                "idempotency: key of %d chars on %s %s exceeds %d; request not deduplicated",
                len(key), method, scope.get("path", ""), MAX_KEY_LENGTH,
            )
            await self.app(scope, receive, send)
            return

        caller = _caller_id(headers)
        if caller is None:
            # No verified identity to scope the key to.  Guarding an anonymous
            # request would let one caller block another's.
            await self.app(scope, receive, send)
            return

        target = _target(scope)
        guard_key = _guard_key(caller, method, target, key)
        store = self._store or get_store()

        try:
            record = await store.claim(guard_key)
        except Exception as exc:  # noqa: BLE001 — any store failure means "unguarded"
            logger.warning(
                "idempotency: store unavailable (%s); %s %s ran without deduplication",
                exc, method, target,
            )
            await self.app(scope, receive, send)
            return

        if record is None:
            await self._run_guarded(store, guard_key, target, scope, receive, send)
            return

        if record.get("state") == _STATE_DONE:
            await self._replay(record, send)
            return

        await _respond(
            send,
            status_code=503,
            payload={
                "success": False,
                "error": {
                    "code": "IDEMPOTENCY_IN_PROGRESS",
                    "message": (
                        "A request with this idempotency key is still being processed. "
                        "Retry later — the original request has not been discarded."
                    ),
                },
            },
            extra_headers=[(b"retry-after", str(RETRY_AFTER_SECONDS).encode())],
        )

    # ── first delivery ────────────────────────────────────────────────────────

    async def _run_guarded(
        self, store: IdempotencyStore, guard_key: str, target: str,
        scope: Scope, receive: Receive, send: Send,
    ) -> None:
        captured: dict[str, Any] = {"status": None, "headers": [], "chunks": [], "overflow": False}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                captured["status"] = message.get("status", 500)
                captured["headers"] = list(message.get("headers") or [])
            elif message["type"] == "http.response.body":
                body = message.get("body") or b""
                if body:
                    stored = sum(len(chunk) for chunk in captured["chunks"])
                    if stored + len(body) > MAX_REPLAYABLE_BODY_BYTES:
                        captured["overflow"] = True
                    else:
                        captured["chunks"].append(bytes(body))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # The endpoint raised; nothing was decided, so a later attempt of the
            # same key must still be able to run.
            await _release_quietly(store, guard_key)
            raise

        status = captured["status"] if captured["status"] is not None else 500
        if captured["overflow"]:
            logger.warning(
                "idempotency: response for %s is over %d bytes and cannot be replayed; "
                "key released instead of pretending to guard it",
                target, MAX_REPLAYABLE_BODY_BYTES,
            )
            await _release_quietly(store, guard_key)
            return
        if status >= 500 or status in RELEASE_STATUSES:
            await _release_quietly(store, guard_key)
            return

        try:
            await store.complete(
                guard_key, status, _storable_headers(captured["headers"]), b"".join(captured["chunks"])
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("idempotency: could not record the response for %s (%s)", target, exc)

    # ── replay ────────────────────────────────────────────────────────────────

    async def _replay(self, record: dict[str, Any], send: Send) -> None:
        try:
            body = base64.b64decode(record.get("body_b64", ""))
        except (ValueError, TypeError):
            body = b""
        status = int(record.get("status") or 200)
        stored = record.get("headers") or []
        headers: list[tuple[bytes, bytes]] = []
        for entry in stored:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            name, value = str(entry[0]), str(entry[1])
            if name.lower() in _UNREPLAYABLE_HEADERS:
                continue
            headers.append((name.encode("latin-1"), value.encode("latin-1")))
        headers.append((b"content-length", str(len(body)).encode()))
        headers.append((REPLAYED_HEADER.encode(), b"true"))
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": headers,
        })
        await send({"type": "http.response.body", "body": body})


# ── helpers ───────────────────────────────────────────────────────────────────

def _caller_id(headers: Headers) -> str | None:
    """Verified ``sub`` from the bearer token, or None."""
    auth = headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = decode_token(auth[7:])
    except (JWTError, TokenInvalid, TokenExpired, ValueError, KeyError):
        # TokenExpired is its own Exception (not a JWTError subclass), and a
        # queued mutation replayed after the access token lapsed is the normal
        # case, not the exotic one: an uncaught one here would turn "log in
        # again" into a 500 on the whole request.
        return None
    sub = payload.get("sub") if isinstance(payload, dict) else None
    return str(sub) if sub else None


def _target(scope: Scope) -> str:
    path = scope.get("path", "")
    query = scope.get("query_string") or b""
    if isinstance(query, bytes):
        query = query.decode("latin-1")
    return f"{path}?{query}" if query else path


def _guard_key(caller: str, method: str, target: str, key: str) -> str:
    material = "\n".join([caller, method, target, key])
    return f"{_KEY_PREFIX}:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


async def _respond(
    send: Send, status_code: int, payload: dict[str, Any], extra_headers: list[tuple[bytes, bytes]] | None = None
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    headers.extend(extra_headers or [])
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _release_quietly(store: IdempotencyStore, guard_key: str) -> None:
    try:
        await store.release(guard_key)
    except Exception as exc:  # noqa: BLE001 — the guard expires on its own TTL
        logger.warning("idempotency: could not release %s (%s); it expires in %ds",
                       guard_key, exc, IN_PROGRESS_TTL_SECONDS)


__all__ = [
    "IDEMPOTENCY_HEADER",
    "REPLAYED_HEADER",
    "IdempotencyMiddleware",
    "IdempotencyStore",
    "RedisIdempotencyStore",
    "get_store",
    "set_store",
]
