"""Rate limiter using Redis sliding window log algorithm.

This module provides a rate limiting decorator that can be applied to API endpoints
to limit the number of requests per user or IP address within a specified time window.
"""

import functools
import logging
import time
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

from src.config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Rate limiter using Redis sliding window log algorithm.

    Each request is added to a sorted set with the current timestamp as score.
    Old entries outside the window are trimmed, and ZCARD gives the count.
    """

    # Redis can blip.  While it is unreachable the limiter still has to answer
    # (a limiter that silently disables itself is not a limiter), so counts fall
    # back to an in-process window — weaker than the shared one (per worker, not
    # per cluster) but real — and a periodic probe reconnects instead of leaving
    # the process pinned to the fallback forever.
    RECONNECT_INTERVAL_SECONDS = 30.0
    RECONNECT_PROBE_TIMEOUT = 1.0
    MAX_LOCAL_KEYS = 10_000

    def __init__(self, redis_url: str | None = None) -> None:
        self.redis_url = redis_url or settings.redis_url
        self.client: aioredis.Redis | None = None
        self._connected = False
        self._local_windows: dict[str, deque[float]] = {}
        self._next_reconnect_at = 0.0

    async def connect(self) -> bool:
        """Connect to Redis instance."""
        try:
            if not self.client:
                self.client = aioredis.from_url(self.redis_url, decode_responses=True)
                await self.client.ping()
                self._connected = True
                return True
            else:
                await self.client.ping()
                self._connected = True
                return True
        except Exception as e:
            logger.error("Failed to connect to Redis for rate limiting: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from Redis instance."""
        if self.client and self._connected:
            await self.client.close()
            self._connected = False

    async def check_rate_limit(
        self,
        key: str,
        requests: int | None = None,
        window: int | None = None,
    ) -> bool:
        """Check if a request is within the rate limit.

        Returns True if allowed, False if rate limit exceeded.

        Redis is the shared source of truth; when it cannot be reached the
        decision falls through to the in-process window (see ``_check_local``)
        rather than to "allow everything" or "block everything".
        """
        requests = requests or settings.rate_limit_requests
        window = window or settings.rate_limit_window

        if settings.testing:
            return True  # bypass in test mode

        if not self._connected:
            await self._try_reconnect()
            if not self._connected:
                return self._check_local(key, requests, window)

        try:
            bucket_key = f"rate_limit:{key}"
            now = time.time()
            window_start = now - window
            member = f"{now}:{uuid.uuid4().hex[:8]}"

            pipe = self.client.pipeline()
            pipe.zadd(bucket_key, {member: now})
            pipe.zremrangebyscore(bucket_key, "-inf", window_start)
            pipe.zcard(bucket_key)
            pipe.expire(bucket_key, window)
            results = await pipe.execute()

            count = results[2] if isinstance(results[2], int) else 0
            return count <= requests

        except Exception as exc:  # noqa: BLE001 — a Redis blip must not decide the outcome
            logger.warning("Rate limiter Redis call failed, using in-process window: %s", exc)
            self._connected = False
            return self._check_local(key, requests, window)

    async def _try_reconnect(self) -> None:
        """Probe Redis again at most once per interval, without blocking the request.

        Without this a single Redis blip leaves ``_connected`` False forever, so
        the limiter stays on its per-process window long after Redis came back —
        silently, with no shared counts and no warning.
        """
        import asyncio

        now = time.monotonic()
        if now < self._next_reconnect_at:
            return
        self._next_reconnect_at = now + self.RECONNECT_INTERVAL_SECONDS
        try:
            await asyncio.wait_for(self.connect(), timeout=self.RECONNECT_PROBE_TIMEOUT)
        except TimeoutError:
            logger.warning("Rate limiter reconnect probe timed out after %ss", self.RECONNECT_PROBE_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 — connect() already logged it
            logger.debug("Rate limiter still unable to reach Redis: %s", exc)
        else:
            if self._connected:
                # Back to shared counts; the per-process windows are stale now.
                self._local_windows.clear()
                logger.info("Rate limiter reconnected to Redis; shared counts restored")

    def _check_local(self, key: str, requests: int, window: int) -> bool:
        """Per-process sliding window used while Redis is unreachable."""
        now = time.time()
        bucket = self._local_windows.get(key)
        if bucket is None:
            if len(self._local_windows) >= self.MAX_LOCAL_KEYS:
                # Drop the least recently used buckets so a key-spoofing client
                # cannot make this dict grow without bound.
                for stale in list(self._local_windows.keys())[: self.MAX_LOCAL_KEYS // 2]:
                    self._local_windows.pop(stale, None)
            bucket = deque()
            self._local_windows[key] = bucket

        cutoff = now - window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= requests:
            return False

        bucket.append(now)
        return True

    async def get_rate_limit_headers(self, key: str) -> dict[str, str]:
        """Get rate limiting headers for the response."""
        if not self._connected:
            return {}

        requests = settings.rate_limit_requests
        window = settings.rate_limit_window

        try:
            bucket_key = f"rate_limit:{key}"
            now = time.time()
            window_start = now - window

            count = await self.client.zcount(bucket_key, window_start, now)

            if isinstance(count, int):
                return {
                    "X-Rate-Limit": str(requests),
                    "X-Rate-Remaining": str(max(0, requests - count)),
                    "X-Rate-Window": str(window),
                    "X-Rate-Reset": str(int(now + window)),
                }
            return {}
        except Exception:
            return {}


# Global rate limiter instance
rate_limiter = RateLimiter()


def _looks_like_request(candidate: object) -> bool:
    """Duck-typed check for the ASGI request among an endpoint's arguments.

    FastAPI calls the endpoint with keyword arguments drawn from the **handler's**
    own signature (functools.wraps makes the wrapper transparent to it), so the
    limiter cannot assume which argument is the request by position or name.  It
    used to: the wrapper declared ``wrapper(request: Request)``, so a handler whose
    only parameter is a body model named ``request`` had that body model bound to
    it and ``request.client`` raised AttributeError — the endpoint answered 500 and
    was never limited at all.
    """
    return hasattr(candidate, "headers") and hasattr(candidate, "client") and hasattr(candidate, "url")


def _trusted_proxy_ips() -> set[str]:
    """Addresses whose forwarding headers this deployment believes (TRUSTED_PROXY_IPS)."""
    raw = getattr(settings, "trusted_proxy_ips", "")
    if not isinstance(raw, str):  # a mocked settings object in a test
        return set()
    return {entry.strip() for entry in raw.split(",") if entry.strip()}


def _find_request(args: tuple, kwargs: dict) -> Any:
    """Return the request object FastAPI passed, or None when there isn't one."""
    for candidate in (*args, *kwargs.values()):
        if isinstance(candidate, Request) or _looks_like_request(candidate):
            return candidate
    return None


def rate_limit(
    requests: int | None = None,
    window: int | None = None,
    key_func: Callable | None = None,
) -> Callable:
    """Decorator to apply rate limiting to API endpoints.

    Args:
        requests (int): Maximum number of requests allowed in the time window.
            Defaults to ``settings.rate_limit_requests``.
        window (int): Time window in seconds. Defaults to ``settings.rate_limit_window``.
        key_func (Optional[Callable]): Function to extract rate limit key from request
            If None, uses IP address as the key

    Returns:
        Callable: Decorator function that applies rate limiting
    """

    def decorator(func: Callable) -> Callable:
        # Fallback bucket for a handler FastAPI cannot give us a Request for.  It
        # is per-endpoint rather than per-client, so it still refuses a replay
        # flood — it just shares one budget across that endpoint's clients.
        module = getattr(func, "__module__", "")
        qualname = getattr(func, "__qualname__", getattr(func, "__name__", "unknown"))
        endpoint_key = f"endpoint:{module}.{qualname}"
        warned_without_request = False

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            nonlocal warned_without_request
            request = _find_request(args, kwargs)

            # Extract rate limit key
            if request is None:
                if not warned_without_request:
                    warned_without_request = True
                    logger.warning(
                        "rate_limit on %s received no Request argument; falling back to the "
                        "per-endpoint bucket %r.  Add `request: Request` to the handler to limit "
                        "per client.",
                        getattr(func, "__qualname__", func),
                        endpoint_key,
                    )
                key = endpoint_key
            elif key_func:
                key = key_func(request)
            else:
                # Use IP address as the default key, respecting X-Forwarded-For
                if request.client:
                    client_ip = request.client.host
                else:
                    client_ip = "unknown"
                # X-Forwarded-For names the real client only when this socket
                # really belongs to a proxy the deployment declared it trusts.
                # Otherwise the header is the client's own text: a flooded client
                # would mint a fresh bucket per attempt by rotating it, which
                # makes every per-IP limit decorative.
                if client_ip in _trusted_proxy_ips():
                    forwarded_for = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
                    first_hop = (forwarded_for or "").split(",")[0].strip()
                    if first_hop:
                        client_ip = first_hop
                key = f"ip:{client_ip}"

            # Check rate limit
            allowed = await rate_limiter.check_rate_limit(
                key,
                requests or settings.rate_limit_requests,
                window or settings.rate_limit_window,
            )

            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={
                        "X-Rate-Limit": str(requests or settings.rate_limit_requests),
                        "X-Rate-Window": str(window or settings.rate_limit_window),
                    },
                )

            # Call the original function with exactly what FastAPI handed us
            result = await func(*args, **kwargs)

            # Add rate limit headers to response if it's a JSONResponse
            if isinstance(result, JSONResponse):
                rate_headers = await rate_limiter.get_rate_limit_headers(key)
                for k, v in rate_headers.items():
                    result.headers[k] = v

            return result

        return wrapper

    return decorator


# Pre-configured rate limiters for common use cases (all follow settings)
api_rate_limit = rate_limit()  # uses settings.rate_limit_requests/window
user_rate_limit = rate_limit()  # follows global settings per user
write_rate_limit = rate_limit()  # follows global settings per IP
