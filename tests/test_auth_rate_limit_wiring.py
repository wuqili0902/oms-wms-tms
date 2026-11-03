"""Rate limiting must be wired to the function FastAPI actually registers.

``@rate_limit`` written **above** ``@router.post`` decorates the *return value* of
``router.post(...)``.  ``router.post`` has already put the undecorated handler into
the router by then, so the limiter survives only as a local name and never runs.
``/auth/refresh`` in src/auth/router.py is written that way, and its declared
10-requests-per-60s budget has therefore never been enforced: a stolen refresh
token can be replayed without limit (M3 in 补充开发修复计划.md).

These tests patch the limiter's own decision so they test the **wiring**, not the
Redis window (``settings.testing`` bypasses the limiter for the API tests, so the
real limiter would answer "allowed" here regardless of how the route is decorated).
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

LOGIN = "/api/v1/auth/login"
REGISTER = "/api/v1/auth/register"
REFRESH = "/api/v1/auth/refresh"

# Bodies that pass Pydantic validation.  FastAPI validates the body *before* it
# calls the endpoint callable, so an invalid body would 422 without ever reaching
# the limiter and the test would pass vacuously.
BODIES = {
    LOGIN: {"username": "no-such-user", "password": "wrong-password"},
    REGISTER: {"username": "rl_wiring_probe", "email": "rl-wiring@example.com", "password": "test123456"},
    REFRESH: {"refresh_token": "not-a-signed-jwt"},
}


def _deny_everything() -> AsyncMock:
    return AsyncMock(return_value=False)


@pytest.mark.parametrize("path", [LOGIN, REGISTER, REFRESH])
async def test_auth_endpoint_refuses_when_the_limiter_says_no(async_client, path):
    """Each mutating auth route has to run through the limiter before its handler does."""
    limiter = _deny_everything()
    with patch("src.core.rate_limiter.rate_limiter.check_rate_limit", limiter):
        response = await async_client.post(path, json=BODIES[path])

    assert limiter.await_count == 1, f"{path} never consulted the rate limiter"
    assert response.status_code == 429, f"{path} answered {response.status_code}, not 429"


async def test_refresh_is_stopped_at_its_declared_budget(async_client):
    """10 allowed, then blocked — the budget src/auth/router.py claims for /auth/refresh."""
    calls: list[tuple[str, int, int]] = []

    async def fake_check(key: str, requests: int, window: int) -> bool:
        calls.append((key, requests, window))
        return len(calls) <= requests

    with patch("src.core.rate_limiter.rate_limiter.check_rate_limit", side_effect=fake_check):
        codes = [
            (await async_client.post(REFRESH, json=BODIES[REFRESH])).status_code for _ in range(12)
        ]

    assert (requests_used := calls[0][1]) == 10, f"/auth/refresh declared requests={requests_used}"
    assert codes[:10] == [401] * 10, f"first 10 attempts should reach the handler (401), got {codes[:10]}"
    assert codes[10:] == [429, 429], f"attempts 11-12 should be limited, got {codes[10:]}"


async def test_refresh_limit_is_keyed_per_client_ip(async_client):
    """A shared bucket would let one client exhaust everyone's refresh budget."""
    seen: list[str] = []

    async def fake_check(key: str, requests: int, window: int) -> bool:
        seen.append(key)
        return True

    with patch("src.core.rate_limiter.rate_limiter.check_rate_limit", side_effect=fake_check):
        await async_client.post(REFRESH, json=BODIES[REFRESH])

    assert seen and seen[0].startswith("ip:"), f"limit key was {seen!r}, expected per-IP"


class _Body(BaseModel):
    token: str


async def test_handler_with_no_request_parameter_is_still_limited():
    """A handler that never takes Request must be limited, not crash.

    The limiter's wrapper used to declare ``wrapper(request: Request)``.  FastAPI
    reads the decorated handler's own signature (functools.wraps sets
    ``__wrapped__``), so for a handler whose only parameter is a body model, the
    *body model* was handed to that ``request`` parameter and ``request.client``
    raised AttributeError — the endpoint answered 500 and was never limited.
    """
    app = FastAPI()

    @app.post("/probe")
    @patch_free_limit(requests=1)
    async def probe(request: _Body):  # the body model is named `request` on purpose
        return {"ok": True}

    limiter_calls: list[str] = []

    async def fake_check(key: str, requests: int, window: int) -> bool:
        limiter_calls.append(key)
        return len(limiter_calls) <= requests

    with patch("src.core.rate_limiter.rate_limiter.check_rate_limit", side_effect=fake_check):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://probe") as client:
            codes = [(await client.post("/probe", json={"token": "x"})).status_code for _ in range(3)]

    assert codes[0] == 200, f"first call answered {codes[0]} instead of 200 (wrapper collided with the body model?)"
    assert codes[1:] == [429, 429], f"calls 2-3 answered {codes[1:]}, expected 429"
    assert len(limiter_calls) == 3, "the limiter was not consulted on every call"
    assert limiter_calls[0].startswith("endpoint:"), (
        f"without a Request the key should be per-endpoint, got {limiter_calls[0]!r}"
    )


def patch_free_limit(requests: int):
    """Local alias so the decorator order under test stays readable."""
    from src.core.rate_limiter import rate_limit

    return rate_limit(requests=requests, window=60)
