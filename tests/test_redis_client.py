"""Tests for src.cache.redis_client — RedisClient, get_redis, redis_health_check."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError, TimeoutError


@pytest.fixture(autouse=True)
def _restore_shared_client():
    """These tests poke the process-wide ``redis_client`` singleton.

    Without a restore, a fake pool installed by one test is handed to the next
    test (and to unrelated suites that expect a real client) — which is how
    ``test_returns_true`` ended up asserting on a pool nobody had used.
    """
    from src.cache.redis_client import redis_client

    saved = (redis_client._pool, redis_client._initialized, redis_client._loop)
    yield
    redis_client._pool, redis_client._initialized, redis_client._loop = saved


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

    async def test_client_after_close_raises(self):
        """A closed pool must never be handed out again.

        close() drops the pool reference, so ``client`` reports "not
        initialized" instead of returning a dead pool — the guard no longer
        needs to interrogate the pool's own closed flag.
        """
        from src.cache.redis_client import RedisClient

        rc = RedisClient("redis://localhost:6379/0")
        pool = MagicMock()
        pool.aclose = AsyncMock()
        rc._pool = pool
        rc._initialized = True

        await rc.close()

        assert rc._pool is None
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
        # "Already initialized" is only meaningful for *this* loop — a pool from
        # another loop is rebuilt, not skipped (see the sibling test below).
        rc._initialized = True
        rc._loop = asyncio.get_running_loop()
        rc._pool = MagicMock()

        with patch("src.cache.redis_client.aioredis") as mock_redis:
            await rc.initialize()
            mock_redis.from_url.assert_not_called()

    async def test_initialize_rebuilds_pool_from_other_loop(self):
        from src.cache.redis_client import RedisClient

        rc = RedisClient("redis://localhost:6379/0")
        stale_pool = MagicMock()
        stale_pool.aclose = AsyncMock()
        rc._pool = stale_pool
        rc._initialized = True
        other_loop = asyncio.new_event_loop()
        try:
            rc._loop = other_loop
            with patch("src.cache.redis_client.aioredis") as mock_redis:
                fresh_pool = MagicMock()
                fresh_pool.ping = AsyncMock()
                mock_redis.from_url.return_value = fresh_pool

                await rc.initialize()

            stale_pool.aclose.assert_awaited_once()
            assert rc._pool is fresh_pool
            assert rc._loop is asyncio.get_running_loop()
        finally:
            other_loop.close()

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
        redis_client._initialized = True
        redis_client._loop = asyncio.get_running_loop()

        async with get_redis() as client:
            assert client is redis_client._pool

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
        redis_client._pool = pool
        redis_client._initialized = True
        # Belongs to *this* loop, so health_check() uses it instead of building
        # a real pool against whatever Redis the machine happens to have.
        redis_client._loop = asyncio.get_running_loop()

        result = await redis_health_check()
        assert result is True
        pool.ping.assert_awaited_once()

    async def test_returns_false(self):
        from src.cache.redis_client import redis_client, redis_health_check

        pool = MagicMock()
        pool.ping = AsyncMock(side_effect=ConnectionError("down"))
        redis_client._pool = pool
        redis_client._initialized = True
        redis_client._loop = asyncio.get_running_loop()

        result = await redis_health_check()
        assert result is False
