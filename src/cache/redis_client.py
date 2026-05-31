import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError, TimeoutError

from src.config import settings


logger = logging.getLogger(__name__)

# Redis connection pool configuration
REDIS_POOL_SIZE = 10
REDIS_SOCKET_TIMEOUT = 5.0
REDIS_CONNECTION_RETRY_DELAY = 2.0
REDIS_MAX_RETRIES = 3


class RedisClient:
    """Async Redis client with connection pooling and health checks."""

    def __init__(self, url: str):
        self.url = url
        self._pool: aioredis.Redis = None
        self._initialized = False

    async def initialize(self):
        """Initialize the Redis connection pool."""
        if self._initialized:
            return

        try:
            self._pool = aioredis.from_url(
                self.url,
                max_connections=REDIS_POOL_SIZE,
                socket_timeout=REDIS_SOCKET_TIMEOUT,
                retry_attempts=REDIS_MAX_RETRIES,
                retry_interval=REDIS_CONNECTION_RETRY_DELAY,
            )
            await self._pool.ping()
            self._initialized = True
            logger.info("Redis connection pool initialized successfully")
        except (ConnectionError, TimeoutError) as exc:
            logger.error("Failed to initialize Redis connection pool: %s", str(exc))
            raise

    async def close(self):
        """Close the Redis connection pool."""
        if self._pool and not self._pool.is_closed():
            await self._pool.aclose()
            self._initialized = False
            logger.info("Redis connection pool closed")

    @property
    def client(self) -> aioredis.Redis:
        """Get the Redis client instance."""
        if not self._initialized or self._pool.is_closed():
            raise RuntimeError(
                "Redis client is not initialized. Call initialize() first."
            )
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
        if not redis_client._initialized or redis_client._pool.is_closed():
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
