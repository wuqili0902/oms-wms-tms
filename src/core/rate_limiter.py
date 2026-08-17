"""Rate limiter using Redis sliding window log algorithm.

This module provides a rate limiting decorator that can be applied to API endpoints
to limit the number of requests per user or IP address within a specified time window.
"""

import functools
import time
import uuid
from collections.abc import Callable

import redis.asyncio as aioredis
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

from src.config import settings


class RateLimiter:
    """Rate limiter using Redis sliding window log algorithm.

    Each request is added to a sorted set with the current timestamp as score.
    Old entries outside the window are trimmed, and ZCARD gives the count.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self.redis_url = redis_url or settings.redis_url
        self.client: aioredis.Redis | None = None
        self._connected = False

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
            print(f"Failed to connect to Redis for rate limiting: {e}")
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
        When Redis is unavailable, returns False (fail-closed).
        """
        requests = requests or settings.rate_limit_requests
        window = window or settings.rate_limit_window

        if settings.testing:
            return True  # bypass in test mode

        if not self._connected:
            return False  # fail-closed

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

        except Exception:
            return False  # fail-closed

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
        @functools.wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            # Extract rate limit key
            if key_func:
                key = key_func(request)
            else:
                # Use IP address as the default key
                client_ip = request.client.host if request.client else "unknown"
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

            # Call the original function
            result = await func(request, *args, **kwargs)

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
