"""Tests for src.core.idempotency — the replay guard for mutations.

The phone replays every queued mutation with the same ``X-Idempotency-Key``.
Without a server-side guard that key is decoration: a scan whose response was
lost is sent again and the stock movement happens twice.  These tests drive the
middleware directly so each state (first delivery, in-progress, done, failed,
oversized, degraded) is reached on purpose instead of by hoping a real network
flakes in a test.
"""

import base64
import json
from datetime import timedelta

import pytest

from src.core import idempotency
from src.core.idempotency import (
    IDEMPOTENCY_HEADER,
    MAX_REPLAYABLE_BODY_BYTES,
    REPLAYED_HEADER,
    IdempotencyMiddleware,
    IdempotencyStore,
)
from src.core.security import create_access_token

# The guard key is part of the contract (it is what makes a replay recognisable
# across workers), so the tests name it rather than reconstruct it.
_guard_key = idempotency._guard_key


class FakeStore(IdempotencyStore):
    """In-memory stand-in with the same claim/complete/release contract."""

    def __init__(self):
        self.records: dict[str, dict] = {}
        self.claims: list[str] = []
        self.completions: list[tuple[str, int]] = []
        self.releases: list[str] = []

    async def claim(self, guard_key):
        self.claims.append(guard_key)
        record = self.records.get(guard_key)
        if record is not None:
            return dict(record)
        self.records[guard_key] = {"state": "in_progress"}
        return None

    async def complete(self, guard_key, status, headers, body):
        self.completions.append((guard_key, status))
        self.records[guard_key] = {
            "state": "done",
            "status": status,
            "headers": [[name, value] for name, value in headers],
            "body_b64": base64.b64encode(body).decode("ascii"),
        }

    async def release(self, guard_key):
        self.releases.append(guard_key)
        self.records.pop(guard_key, None)


class BrokenStore(IdempotencyStore):
    """What Redis being down looks like from the middleware's point of view."""

    def __init__(self):
        self.attempts = 0

    async def claim(self, guard_key):
        self.attempts += 1
        raise ConnectionError("redis is down")

    async def complete(self, guard_key, status, headers, body):
        raise ConnectionError("redis is down")

    async def release(self, guard_key):
        raise ConnectionError("redis is down")


class Recorder:
    """Counts how often the wrapped endpoint actually ran."""

    def __init__(self):
        self.calls = 0


def endpoint(
    calls: Recorder,
    status: int = 201,
    body: bytes = b'{"id":"warehouse-1"}',
    headers: list[tuple[bytes, bytes]] | None = None,
    raise_exc: bool = False,
    statuses: list[int] | None = None,
):
    """A stand-in endpoint.  ``statuses`` answers the nth call in order, so a
    test can make the first attempt fail and the replay succeed."""

    async def app(scope, receive, send):
        code = status
        if statuses is not None:
            code = statuses[min(calls.calls, len(statuses) - 1)]
        calls.calls += 1
        if raise_exc:
            raise RuntimeError("endpoint exploded")
        await send({
            "type": "http.response.start",
            "status": code,
            "headers": headers if headers is not None else [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": body})

    return app


def scope(
    method: str = "POST",
    path: str = "/api/v1/warehouses",
    query: str = "",
    sub: str | None = "user-a",
    key: str | None = "scan-1",
    token: str | None = None,
) -> dict:
    headers: list[tuple[bytes, bytes]] = [(b"content-type", b"application/json")]
    if sub is not None:
        headers.append((b"authorization", f"Bearer {create_access_token({'sub': sub})}".encode()))
    if token is not None:
        # Anything the signing key did not produce: not a caller to scope a guard to.
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if key is not None:
        headers.append((IDEMPOTENCY_HEADER.encode(), key.encode()))
    return {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": headers,
        "client": ("127.0.0.1", 51234),
        "scheme": "http",
        "server": ("testserver", 80),
    }


async def drive(middleware: IdempotencyMiddleware, request_scope: dict) -> dict:
    """Run one request through the middleware and return what the client saw."""
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    await middleware(request_scope, receive, send)

    start = next((m for m in sent if m.get("type") == "http.response.start"), None)
    body = b"".join(m.get("body") or b"" for m in sent if m.get("type") == "http.response.body")
    return {
        "status": start.get("status") if start else None,
        "headers": {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in (start or {}).get("headers", [])},
        "body": body,
    }


# ── Requests the guard is not for ────────────────────────────────────────────

class TestUnguardedRequests:
    async def test_a_request_without_the_key_is_untouched(self):
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls), store=store)
        result = await drive(mw, scope(key=None))
        assert result["status"] == 201
        assert calls.calls == 1
        assert store.claims == []

    async def test_a_read_is_never_guarded(self):
        """Replaying a GET is harmless; guarding it would only hide the answer."""
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls), store=store)
        await drive(mw, scope(method="GET"))
        await drive(mw, scope(method="GET"))
        assert calls.calls == 2
        assert store.claims == []

    async def test_an_unverified_caller_cannot_reserve_a_key(self):
        """Without a verified sub there is no one to scope the key to — guarding
        an anonymous request lets any caller block another one's mutation."""
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls), store=store)
        result = await drive(mw, scope(sub=None))
        assert result["status"] == 201
        assert store.claims == []

    async def test_a_forged_token_gets_no_protection(self):
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls), store=store)
        result = await drive(mw, scope(sub=None, token="not-a-signed-jwt"))
        assert result["status"] == 201
        assert store.claims == []

    async def test_a_lapsed_token_still_reaches_the_endpoint(self):
        """A queued mutation replayed after the access token expired is the
        ordinary case, not the exotic one.  TokenExpired is its own Exception
        rather than a JWTError, so reading it wrong answers 500 to a request
        whose only problem is "log in again"."""
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls), store=store)
        lapsed = create_access_token({"sub": "user-a"}, expires_delta=timedelta(minutes=-1))

        result = await drive(mw, scope(sub=None, token=lapsed))

        assert result["status"] == 201
        assert calls.calls == 1
        assert store.claims == []

    async def test_an_absurd_key_length_is_refused_rather_than_stored(self, caplog):
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls), store=store)
        result = await drive(mw, scope(key="k" * 5000))
        assert result["status"] == 201
        assert store.claims == []
        assert "exceeds" in caplog.text


# ── The replay itself ────────────────────────────────────────────────────────

class TestReplay:
    async def test_the_second_delivery_is_answered_without_running_the_endpoint(self):
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls), store=store)

        first = await drive(mw, scope())
        second = await drive(mw, scope())

        assert first["status"] == 201
        assert calls.calls == 1, "the mutation was applied twice — the whole point of the guard"
        assert second["status"] == 201
        assert second["body"] == first["body"]
        assert second["headers"][REPLAYED_HEADER] == "true"
        assert first["headers"].get(REPLAYED_HEADER) is None

    async def test_the_first_response_headers_survive_but_the_transport_ones_do_not(self):
        store = FakeStore()
        calls = Recorder()
        app = endpoint(
            calls,
            headers=[
                (b"content-type", b"application/json"),
                (b"x-total-count", b"3"),
                (b"transfer-encoding", b"chunked"),
            ],
        )
        mw = IdempotencyMiddleware(app, store=store)
        await drive(mw, scope())
        replayed = await drive(mw, scope())

        assert replayed["headers"]["x-total-count"] == "3"
        assert replayed["headers"]["content-type"] == "application/json"
        assert "transfer-encoding" not in replayed["headers"], "a chunked marker on a stored body is a lie"
        assert replayed["headers"]["content-length"] == str(len(replayed["body"]))

    async def test_in_progress_answers_retryably_and_keeps_the_key(self):
        """503, not 409: the client files 4xx mutations as permanently rejected,
        which would throw away a scan that is still being written."""
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls), store=store)
        key = _guard_key("user-a", "POST", "/api/v1/warehouses", "scan-1")
        store.records[key] = {"state": "in_progress"}

        result = await drive(mw, scope())

        assert result["status"] == 503
        assert result["headers"]["retry-after"] == "2"
        assert calls.calls == 0
        assert json.loads(result["body"])["error"]["code"] == "IDEMPOTENCY_IN_PROGRESS"
        assert store.releases == [], "releasing here would let a concurrent copy through"

    async def test_the_guard_is_scoped_to_the_caller(self):
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls), store=store)

        await drive(mw, scope(sub="user-a"))
        await drive(mw, scope(sub="user-b"))

        assert calls.calls == 2, "one user must not answer another user's key"
        assert len(store.completions) == 2

    async def test_the_guard_follows_the_request_it_guarded(self):
        """The same key on another endpoint is a different mutation."""
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls), store=store)

        await drive(mw, scope(path="/api/v1/warehouses"))
        await drive(mw, scope(path="/api/v1/orders"))
        await drive(mw, scope(path="/api/v1/warehouses", query="mode=quick"))

        assert calls.calls == 3
        assert len(store.completions) == 3


# ── When the first attempt did not decide anything ───────────────────────────

class TestReleases:
    async def test_a_server_error_releases_the_key_so_the_mutation_can_be_tried_again(self):
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(
            endpoint(calls, statuses=[503, 201], body=b'{"detail":"down"}'), store=store
        )

        first = await drive(mw, scope())
        second = await drive(mw, scope())

        assert first["status"] == 503
        # Only the successful attempt was recorded as a verdict.  Recording the
        # 503 would answer the replay with the server's own failure.
        assert [status for _, status in store.completions] == [201], "a 5xx is not a verdict on the payload"
        assert calls.calls == 2, "the operator's scan was stranded by a server hiccup"
        assert second["status"] == 201

    async def test_an_expired_token_does_not_strand_the_mutation(self):
        """The phone refreshes the token and replays the *same* key; a guard that
        kept the 401 would drop the scan for a credential that has since been
        fixed."""
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(
            endpoint(calls, statuses=[401, 201], body=b'{"detail":"expired"}'), store=store
        )

        await drive(mw, scope())
        second = await drive(mw, scope())

        assert calls.calls == 2
        assert second["status"] == 201
        assert [status for _, status in store.completions] == [201]

    async def test_rate_limiting_releases_the_key(self):
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls, status=429, body=b'{"detail":"slow down"}'), store=store)
        await drive(mw, scope())
        await drive(mw, scope())
        assert calls.calls == 2
        assert store.completions == []
        assert store.releases == store.claims

    async def test_a_rejected_payload_stays_rejected(self):
        """422 *is* a verdict: replaying a bad payload must not re-run it, and
        must not look like a new answer either."""
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls, status=422, body=b'{"detail":"code required"}'), store=store)

        first = await drive(mw, scope())
        second = await drive(mw, scope())

        assert first["status"] == 422
        assert calls.calls == 1
        assert second["status"] == 422
        assert second["body"] == first["body"]

    async def test_an_exception_in_the_endpoint_releases_the_key_and_propagates(self):
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls, raise_exc=True), store=store)

        with pytest.raises(RuntimeError, match="endpoint exploded"):
            await drive(mw, scope())

        assert store.completions == []
        assert store.releases == store.claims


# ── Limits that must fail honestly ───────────────────────────────────────────

class TestDegradation:
    async def test_an_oversized_response_is_not_pretended_to_be_guarded(self, caplog):
        """A replay answered with something other than the first response is how
        an operator ends up believing a scan landed twice — so the key is
        released and the gap is logged instead."""
        store = FakeStore()
        calls = Recorder()
        big = b"x" * (MAX_REPLAYABLE_BODY_BYTES + 1)
        mw = IdempotencyMiddleware(endpoint(calls, body=big), store=store)

        first = await drive(mw, scope())
        second = await drive(mw, scope())

        assert first["status"] == 201
        assert len(second["body"]) == len(big)
        assert second["headers"].get(REPLAYED_HEADER) is None
        assert calls.calls == 2
        assert store.completions == []
        assert "cannot be replayed" in caplog.text

    async def test_a_response_right_at_the_limit_is_still_guarded(self):
        store = FakeStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls, body=b"x" * MAX_REPLAYABLE_BODY_BYTES), store=store)
        await drive(mw, scope())
        replayed = await drive(mw, scope())
        assert calls.calls == 1
        assert replayed["headers"][REPLAYED_HEADER] == "true"

    async def test_no_redis_means_no_guard_rather_than_a_fake_one(self, caplog):
        store = BrokenStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls), store=store)

        first = await drive(mw, scope())
        second = await drive(mw, scope())

        assert first["status"] == 201 and second["status"] == 201
        assert calls.calls == 2, "the request must still be served when the store is down"
        assert "without deduplication" in caplog.text

    async def test_a_failure_to_record_does_not_break_the_response(self, caplog):
        class HalfBrokenStore(FakeStore):
            async def complete(self, guard_key, status, headers, body):
                raise ConnectionError("redis went away mid-response")

        store = HalfBrokenStore()
        calls = Recorder()
        mw = IdempotencyMiddleware(endpoint(calls), store=store)
        result = await drive(mw, scope())
        assert result["status"] == 201
        assert result["body"] == b'{"id":"warehouse-1"}'
        assert "could not record" in caplog.text


# ── Wiring ───────────────────────────────────────────────────────────────────

def test_the_guard_is_mounted_on_the_real_app():
    from src.main import app

    middleware_classes = [entry.cls for entry in app.user_middleware]
    assert IdempotencyMiddleware in middleware_classes, (
        "the client sends X-Idempotency-Key on every replay; with the guard not "
        "mounted, every replay is a second mutation"
    )

    cors = next(entry for entry in app.user_middleware if entry.cls.__name__ == "CORSMiddleware")
    assert "X-Idempotency-Key" in cors.kwargs["allow_headers"], (
        "a browser preflight that rejects the header means the web client's "
        "replays arrive unlabelled"
    )
    assert "X-Idempotency-Replayed" in cors.kwargs["expose_headers"]


async def test_the_guard_lands_in_redis_when_redis_is_there(async_client, _test_redis):
    """The suite's own Redis (test DB 15) drives the real store.

    Everything above proves the middleware's decisions against a stand-in; this
    proves the stand-in's contract is what RedisIdempotencyStore actually does,
    because two API workers deduplicate only through shared state.
    """
    if _test_redis is None:
        pytest.skip("no Redis reachable on this machine")

    username = "idempotency_redis_user"
    register = await async_client.post("/api/v1/auth/register", json={
        "username": username, "email": "idempotency_redis@test.com", "password": "test123456",
    })
    assert register.status_code in (200, 201), register.text[:200]
    login = await async_client.post("/api/v1/auth/login", json={"username": username, "password": "test123456"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "X-Idempotency-Key": "wh-redis-scan-1"}

    payload = {"name": "Redis WH", "code": "WH-REDIS-IDEM", "type": "center"}
    first = await async_client.post("/api/v1/warehouses", json=payload, headers=headers)
    assert first.status_code in (200, 201), first.text[:200]

    guard_keys = [k.decode() for k in _test_redis.keys("idempotency:*")]
    assert len(guard_keys) == 1, f"expected one guard record in Redis, got {guard_keys}"
    record = json.loads(_test_redis.get(guard_keys[0]))
    assert record["state"] == "done"
    assert record["status"] == first.status_code

    second = await async_client.post("/api/v1/warehouses", json=payload, headers=headers)
    assert second.headers.get("x-idempotency-replayed") == "true"
    assert second.json()["id"] == first.json()["id"]


async def test_a_replayed_warehouse_create_lands_once(async_client, monkeypatch):
    """End to end through the real middleware stack: same key, one warehouse."""
    store = FakeStore()
    monkeypatch.setattr(idempotency, "_default_store", store)

    username = "idempotency_wh_user"
    register = await async_client.post("/api/v1/auth/register", json={
        "username": username, "email": "idempotency_wh@test.com", "password": "test123456",
    })
    assert register.status_code in (200, 201), register.text[:200]
    login = await async_client.post("/api/v1/auth/login", json={"username": username, "password": "test123456"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "X-Idempotency-Key": "wh-scan-1"}

    payload = {"name": "Idempotency WH", "code": "WH-IDEMPOTENCY", "type": "center"}
    first = await async_client.post("/api/v1/warehouses", json=payload, headers=headers)
    assert first.status_code in (200, 201), first.text[:200]
    first_id = first.json()["id"]

    # Same operator, same key, same body — a lost response on the first attempt.
    second = await async_client.post("/api/v1/warehouses", json=payload, headers=headers)

    assert second.headers.get("x-idempotency-replayed") == "true"
    assert second.json()["id"] == first_id, "the replay created a second warehouse"

    listing = await async_client.get("/api/v1/warehouses", headers={"Authorization": f"Bearer {token}"})
    matches = [w for w in listing.json()["items"] if w["code"] == "WH-IDEMPOTENCY"]
    assert len(matches) == 1, f"the queue replay filed {len(matches)} warehouses"
