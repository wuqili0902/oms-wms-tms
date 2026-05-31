"""Rate limiter using Redis token bucket algorithm.

This module provides a rate limiting decorator that can be applied to API endpoints
to limit the number of requests per user or IP address within a specified time window.
"""

import functools
from typing import Any, Callable, Optional

import aioredis
from fastapi import Request, HTTPException
from starlette.responses import JSONResponse

from src.config import settings


class RateLimiter:
    """Rate limiter using Redis token bucket algorithm.

    This class implements a token bucket rate limiting strategy where tokens are added
    to the bucket at a fixed rate up to a maximum capacity. Each request consumes
    one or more tokens from the bucket. If there aren't enough tokens, the request is denied.

    Attributes:
        redis_url (str): URL of the Redis instance to use for rate limiting
        client (Optional[aioredis.Redis]): Redis client connection
    """

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self.redis_url = redis_url or settings.redis_url
        self.client: Optional[aioredis.Redis] = None
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
        requests: int = 100,
        window: int = 60,
    ) -> bool:
        """Check if a request is within the rate limit.

        Args:
            key (str): Unique identifier for the client (user ID or IP address)
            requests (int): Maximum number of requests allowed in the time window
            window (int): Time window in seconds

        Returns:
            bool: True if request is allowed, False if rate limit exceeded
        """
        if not self._connected:
            # Graceful degradation - allow all requests if Redis is unavailable
            return True

        try:
            bucket_key = f"rate_limit:{key}"
            current_time = await self.client.time()
            
            # Use ZRANGE to get tokens in the current window
            start_window = int(current_time) - window
            end_window = int(current_time)
            
            # Add token for this request and check count
            pipe = self.client.pipeline()
            pipe.zadd(bucket_key, "1", f"{start_window}:{end_window}")
            pipe.zrange(bucket_key, start_window, end_window)
            results = await pipe.execute()
            
            if isinstance(results[0], int):
                # If we got a count, check against limit
                return results[0] <= requests
            else:
                # Redis returned an error or unexpected response - allow request
                return True
                
        except Exception as e:
            print(f"Error checking rate limit: {e}")
            # Graceful degradation on errors
            return True

    async def get_rate_limit_headers(self, key: str) -> dict[str, str]:
        """Get rate limiting headers for the response.

        Args:
            key (str): Unique identifier for the client

        Returns:
            dict: Rate limit headers to add to the response
        """
        if not self._connected:
            return {}

        try:
            bucket_key = f"rate_limit:{key}"
            current_time = await self.client.time()
            
            # Get tokens in the window
            start_window = int(current_time) - 60
            end_window = int(current_time)
            
            count = await self.client.zrange(bucket_key, start_window, end_window)
            
            if isinstance(count, int):
                return {
                    "X-Rate-Limit": "100",
                    "X-Rate-Remaining": str(max(0, 100 - count)),
                    "X-Rate-Window": "60",
                    "X-Rate-Reset": str(end_window),
                }
            else:
                return {}
        except Exception as e:
            print(f"Error getting rate limit headers: {e}")
            return {}


# Global rate limiter instance
rate_limiter = RateLimiter()


def rate_limit(
    requests: int = 100,
    window: int = 60,
    key_func: Optional[Callable] = None,
) -> Callable:
    """Decorator to apply rate limiting to API endpoints.

    Args:
        requests (int): Maximum number of requests allowed in the time window
        window (int): Time window in seconds
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
            allowed = await rate_limiter.check_rate_limit(key, requests, window)
            
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={
                        "X-Rate-Limit": str(requests),
                        "X-Rate-Window": str(window),
                    },
                )

            # Call the original function
            result = await func(request, *args, **kwargs)
            
            # Add rate limit headers to response if it's a JSONResponse
            if isinstance(result, JSONResponse):
                headers = dict(result.headers)
                rate_headers = await rate_limiter.get_rate_limit_headers(key)
                headers.update(rate_headers)
                result = JSONResponse(
                    content=result.body,
                    status_code=result.status_code,
                    headers=headers,
                )

            return result

        return wrapper

    return decorator


# Pre-configured rate limiters for common use cases
api_rate_limit = rate_limit(requests=1000, window=60)  # 1000 requests per minute
user_rate_limit = rate_limit(requests=300, window=60)  # 300 requests per minute per user
write_rate_limit = rate_limit(requests=100, window=60)  # 100 write operations per minute
