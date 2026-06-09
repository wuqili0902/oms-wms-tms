import hashlib
import time
from collections.abc import Callable
from functools import wraps

from redis.exceptions import ConnectionError

from src.cache.redis_client import get_redis


def cached(ttl: int = 300, prefix: str = "cache"):
    """Cache decorator that stores function results in Redis.

    Args:
        ttl (int): Time-to-live for cache entries in seconds.
        prefix (str): Prefix for cache keys to avoid collisions.

    Usage:
        @cached(ttl=300)
        async def expensive_operation(x, y):
            return x + y  # This result will be cached for 5 minutes
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key from function name and arguments
            key = _generate_cache_key(prefix, func.__name__, args, kwargs)

            try:
                async with get_redis() as redis:
                    cached_value = await redis.get(key)
                    if cached_value is not None:
                        return cached_value.decode("utf-8")

                    result = await func(*args, **kwargs)

                    # Store result in cache
                    await redis.setex(key, ttl, str(result).encode("utf-8"), ex="nx")
                    return result
            except (ConnectionError, Timeout):
                logger.error("Redis connection error in cached decorator")
                raise

        return wrapper

    return decorator


def rate_limit(max_calls: int = 10, window: int = 60):
    """Rate limit decorator using Redis sliding window.

    Args:
        max_calls (int): Maximum number of calls allowed in the time window.
        window (int): Time window in seconds for rate limiting.

    Usage:
        @rate_limit(max_calls=10, window=60)  # Max 10 calls per minute
        async def api_call():
            return requests.get("https://api.com").json()
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = f"rate_limit:{func.__name__}"

            try:
                async with get_redis() as redis:
                    # Get current timestamp and window start
                    now = time.time()
                    window_start = now - window

                    # Remove expired entries from the sorted set
                    await redis.zremrange(key, 0, window_start)

                    # Count calls in the current window
                    call_count = await redis.zcard(key)

                    if call_count >= max_calls:
                        raise RateLimitExceeded(
                            f"Rate limit exceeded for {func.__name__}: "
                            f"{max_calls} calls per {window}s window"
                        )

                    # Add current timestamp to the sorted set
                    await redis.zadd(key, now)

                    return await func(*args, **kwargs)
            except (ConnectionError, Timeout):
                logger.error("Redis connection error in rate_limit decorator")
                raise

        return wrapper

    return decorator


def distributed_lock(key: str, timeout: int = 10):
    """Distributed lock decorator using Redis SETNX.

    Args:
        key (str): Lock key to prevent concurrent access.
        timeout (int): Timeout in seconds for the lock.

    Usage:
        @distributed_lock(key="my_resource", timeout=10)
        async def critical_operation():
            # Only one instance of this function can run at a time
            return do_something()
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            lock_key = f"lock:{key}"

            try:
                async with get_redis() as redis:
                    # Try to acquire the lock (non-blocking)
                    acquired = await redis.setex(lock_key, timeout, "locked", ex="nx")

                    if not acquired:
                        return None  # Lock not acquired, function won't run

                    try:
                        result = await func(*args, **kwargs)
                        return result
                    finally:
                        # Release the lock
                        await redis.delete(lock_key)
            except (ConnectionError, Timeout):
                logger.error("Redis connection error in distributed_lock decorator")
                raise

        return wrapper

    return decorator


def _generate_cache_key(prefix: str, func_name: str, args: tuple, kwargs: dict) -> str:
    """Generate a cache key from function name and arguments.

    Args:
        prefix (str): Prefix for the cache key.
        func_name (str): Name of the function being cached.
        args (tuple): Positional arguments passed to the function.
        kwargs (dict): Keyword arguments passed to the function.

    Returns:
        str: Cache key string.
    """
    # Create a hash from the function name and arguments
    arg_str = f"{args}{kwargs}"
    arg_hash = hashlib.md5(arg_str.encode("utf-8")).hexdigest()[:12]

    return f"{prefix}:{func_name}:{arg_hash}"


class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded."""

    pass
