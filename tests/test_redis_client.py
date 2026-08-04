"""Tests for src.cache.redis_client — RedisClient, get_redis, redis_health_check."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError, TimeoutError


class TestRedisClient:
    def test_constructor(self):
        from src.cache.redis_client import RedisClient

        rc = RedisClient("redis://localhost:6379/0")
        assert rc.url == "redis://localhost:6379/0"
        assert rc._initialized is False

    def test_client_before_initialize_raises(self):
        from src.cache.redis_client import RedisClient

        rc = RedisClient("redis://localhost:6379/0")
        rc._pool = MagicMock()
        rc._pool.is_closed.return_value = False
        rc._initialized = False

        with pytest.raises(RuntimeError, match="not initialized"):
            _ = rc.client

    def test_client_when_pool_closed_raises(self):
        from src.cache.redis_client import RedisClient

        rc = RedisClient("redis://localhost:6379/0")
        rc._pool = MagicMock()
        rc._pool.is_closed.return_value = True
        rc._initialized = True

        with pytest.raises(RuntimeError, match="not initialized"):
            _ = rc.client

    def test_client_ok(self):
        from src.cache.redis_client import RedisClient

        rc = RedisClient("redis://localhost:6379/0")
        rc._pool = MagicMock()
        rc._pool.is_closed.return_value = False
        rc._initialized = True

        assert rc.client is rc._pool

    async def test_initialize_calls_ping(self):
        from src.cache.redis_client import RedisClient

        rc = RedisClient("redis://localhost:6379/0")
        with patch("src.cache.redis_client.aioredis") as mock_redis:
            mock_pool = AsyncMock()
            mock_redis.from_url.return_value = mock_pool

            await rc.initialize()

            assert rc._initialized is True
            mock_pool.ping.assert_awaited_once()

    async def test_initialize_skips_if_already_initialized(self):
        from src.cache.redis_client import RedisClient

        rc = RedisClient("redis://localhost:6379/0")
        rc._initialized = True

        with patch("src.cache.redis_client.aioredis") as mock_redis:
            await rc.initialize()
            mock_redis.from_url.assert_not_called()

    async def test_initialize_raises_on_connection_error(self):
        from src.cache.redis_client import RedisClient

        rc = RedisClient("redis://localhost:6379/0")
        with patch("src.cache.redis_client.aioredis") as mock_redis:
            mock_pool = AsyncMock()
            mock_pool.ping.side_effect = ConnectionError("refused")
            mock_redis.from_url.return_value = mock_pool

            with pytest.raises(ConnectionError):
                await rc.initialize()
            assert rc._initialized is False

    async def test_close(self):
        from src.cache.redis_client import RedisClient

        rc = RedisClient("redis://localhost:6379/0")
        pool = MagicMock()
        pool.is_closed.return_value = False
        pool.aclose = AsyncMock()
        rc._pool = pool
        rc._initialized = True

        await rc.close()

        assert rc._initialized is False
        pool.aclose.assert_awaited_once()

    async def test_close_skips_if_no_pool(self):
        from src.cache.redis_client import RedisClient

        rc = RedisClient("redis://localhost:6379/0")
        rc._pool = None

        await rc.close()


class TestGetRedis:
    async def test_yields_client(self):
        from src.cache.redis_client import get_redis, redis_client

        redis_client._pool = MagicMock()
        redis_client._pool.is_closed.return_value = False
        redis_client._initialized = True

        async with get_redis() as client:
            assert client is redis_client.client

    async def test_initializes_if_not_ready(self):
        from src.cache.redis_client import get_redis, redis_client

        pool = MagicMock()
        pool.is_closed.return_value = False
        redis_client._pool = pool
        redis_client._initialized = False

        async def _init():
            redis_client._initialized = True

        with patch.object(redis_client, "initialize", side_effect=_init):
            async with get_redis() as client:
                assert client is redis_client.client

    async def test_raises_on_connection_error(self):
        from src.cache.redis_client import get_redis, redis_client

        redis_client._pool = MagicMock()
        redis_client._initialized = False
        with patch.object(
            redis_client, "initialize",
            side_effect=ConnectionError("refused"),
        ):
            with pytest.raises(ConnectionError, match="refused"):
                async with get_redis():
                    pass

    async def test_raises_on_timeout(self):
        from src.cache.redis_client import get_redis, redis_client

        redis_client._pool = MagicMock()
        redis_client._initialized = False
        with patch.object(
            redis_client, "initialize",
            side_effect=TimeoutError("timed out"),
        ):
            with pytest.raises(TimeoutError, match="timed out"):
                async with get_redis():
                    pass


class TestRedisHealthCheck:
    async def test_returns_true(self):
        from src.cache.redis_client import redis_client, redis_health_check

        pool = MagicMock()
        pool.ping = AsyncMock()
        pool.is_closed.return_value = False
        redis_client._pool = pool
        redis_client._initialized = True

        result = await redis_health_check()
        assert result is True
        pool.ping.assert_awaited_once()

    async def test_returns_false(self):
        from src.cache.redis_client import redis_client, redis_health_check

        pool = MagicMock()
        pool.ping = AsyncMock(side_effect=ConnectionError("down"))
        pool.is_closed.return_value = False
        redis_client._pool = pool
        redis_client._initialized = True

        result = await redis_health_check()
        assert result is False
