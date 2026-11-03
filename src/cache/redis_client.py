"""Async Redis client with connection pooling, health checks, and an in-memory fallback cache."""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import ConnectionError, TimeoutError

from src.config import settings

logger = logging.getLogger(__name__)

# Redis connection pool configuration
REDIS_POOL_SIZE = 10
REDIS_SOCKET_TIMEOUT = 5.0


class RedisClient:
    """Async Redis client with connection pooling and health checks."""

    def __init__(self, url: str):
        self.url = url
        self._pool: aioredis.Redis = None
        self._initialized = False
        # The event loop the current pool's connections belong to.  A redis
        # connection created on one loop is unusable from another (pytest
        # per-test loops, Celery bridge loops) — using one raises
        # "Event loop is closed" deep inside the transport.
        self._loop: asyncio.AbstractEventLoop | None = None

    async def initialize(self):
        """Initialize the Redis connection pool for the current event loop."""
        current_loop = asyncio.get_running_loop()
        if self._initialized and self._loop is current_loop:
            return
        if self._initialized and self._loop is not current_loop:
            # Pool belongs to a different (possibly closed) loop: drop it and
            # rebuild here instead of serving poisoned connections.
            old_pool = self._pool
            self._pool = None
            self._initialized = False
            self._loop = None
            if old_pool is not None:
                try:
                    await old_pool.aclose()
                except Exception:
                    pass  # best-effort; may raise on a closed loop

        try:
            self._pool = aioredis.from_url(
                self.url,
                max_connections=REDIS_POOL_SIZE,
                socket_timeout=REDIS_SOCKET_TIMEOUT,
                socket_connect_timeout=1.0,
                retry=Retry(NoBackoff(), 0),
            )
            await self._pool.ping()
            self._loop = current_loop
            self._initialized = True
            logger.info("Redis connection pool initialized successfully")
        except (ConnectionError, TimeoutError) as exc:
            logger.error("Failed to initialize Redis connection pool: %s", str(exc))
            raise

    async def close(self):
        """Close the Redis connection pool."""
        if self._pool:
            await self._pool.aclose()
            self._pool = None  # don't hand a dead pool back to close()/client again
            self._initialized = False
            self._loop = None
            logger.info("Redis connection pool closed")

    @property
    def client(self) -> aioredis.Redis:
        """Get the Redis client instance."""
        if not self._initialized:
            raise RuntimeError("Redis client is not initialized. Call initialize() first.")
        return self._pool


# Global Redis client instance
redis_client = RedisClient(settings.redis_url)


@asynccontextmanager
async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """Context manager for getting a Redis connection.

    Usage:
        async with get_redis() as redis:
            await redis.set("key", "value")
    """
    try:
        # A pool built on another event loop is unusable here; initialize()
        # returns immediately when the loop matches, so this is cheap.
        if not redis_client._initialized or redis_client._loop is not asyncio.get_running_loop():
            await redis_client.initialize()
        yield redis_client.client
    except (ConnectionError, TimeoutError) as exc:
        logger.error("Redis connection error: %s", str(exc))
        raise
    finally:
        # Don't close the pool in a context manager - it's managed globally
        pass


async def redis_health_check() -> bool:
    """Check Redis connectivity and return health status.

    Returns:
        bool: True if Redis is healthy, False otherwise.
    """
    try:
        await redis_client.initialize()
        await redis_client.client.ping()
        logger.info("Redis health check passed")
        return True
    except (ConnectionError, TimeoutError) as exc:
        logger.error("Redis health check failed: %s", str(exc))
        return False


# ── In-memory fallback cache (used when Redis is unavailable) ────────────────

class MemoryCache:
    """Simple in-memory cache using OrderedDict for LRU eviction."""

    def __init__(self, maxsize: int = 1000):
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self.maxsize = maxsize

    def get(self, key: str) -> Any | None:
        if key not in self._cache:
            return None
        value, _ = self._cache[key]
        # Move to end (most recently used)
        self._cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any, expire: float | None = None) -> None:
        if key in self._cache:
            self._cache.pop(key)
        else:
            if len(self._cache) >= self.maxsize:
                # Evict oldest entry
                self._cache.popitem(last=False)
        self._cache[key] = (value, expire or 0.0)

    def delete(self, key: str) -> bool:
        return self._cache.pop(key, None) is not None

    def exists(self, key: str) -> bool:
        return key in self._cache

    def incr(self, key: str, delta: int = 1) -> int:
        if key not in self._cache:
            self.set(key, 0)
        value, _ = self._cache[key]
        self._cache[key] = (value + delta, self._cache[key][1])
        return value + delta

    def decr(self, key: str, delta: int = 1) -> int:
        if key not in self._cache:
            self.set(key, 0)
        value, _ = self._cache[key]
        self._cache[key] = (value - delta, self._cache[key][1])
        return max(0, value - delta)

    def expire(self, key: str, seconds: float) -> bool:
        if key not in self._cache:
            return False
        _, current_expire = self._cache[key]
        new_expire = min(current_expire + seconds, 86400 * 30)  # max 30 days
        self._cache[key] = (self._cache[key][0], new_expire)
        return True

    def ttl(self, key: str) -> float | None:
        if key not in self._cache:
            return -1
        _, expire = self._cache[key]
        return max(0.0, expire)

    def flushall(self) -> None:
        self._cache.clear()


# Singleton instance for use throughout the app
_memory_cache = MemoryCache(maxsize=1000)


def get_memory_cache() -> MemoryCache:
    """Return the global memory cache singleton."""
    return _memory_cache
