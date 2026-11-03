import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError, TimeoutError

import src.cache.redis_client as rc_module
from src.cache.decorators import cached, distributed_lock, rate_limit
from src.cache.redis_client import RedisClient, get_redis, redis_health_check


class MockRedisClient:
    """A mock that simulates redis.asyncio.Redis methods."""

    def __init__(self):
        self._store = {}
        self.get = AsyncMock(side_effect=self._get)
        self.delete = AsyncMock(side_effect=self._delete)
        self.set = AsyncMock(side_effect=self._set)
        self.zremrange = AsyncMock()
        self.zcard = AsyncMock(return_value=0)
        self.zadd = AsyncMock()
        self.ping = AsyncMock()
        self.aclose = AsyncMock()
        self.is_closed = MagicMock(return_value=False)

    def _set(self, name, value, *args, **kwargs):
        self._store[name] = value
        return True

    def _get(self, name):
        return self._store.get(name)

    def _delete(self, *names):
        for n in names:
            self._store.pop(n, None)
        return len(names)


@pytest.fixture
def mock_redis():
    """Create a mock Redis that patches get_redis async context manager."""
    client = MockRedisClient()

    # get_redis is an async generator that yields a redis client.
    # We patch it so that async with get_redis() as r: yields our mock.
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("src.cache.decorators.get_redis", return_value=cm):
        yield client


@pytest.mark.asyncio
async def test_cached_decorator(mock_redis):
    """Test the cached decorator."""

    @cached(ttl=10, prefix="test")
    async def expensive_operation(x, y):
        return x + y

    # First call: cache miss -> function executes
    result1 = await expensive_operation(2, 3)
    assert result1 == 5
    assert mock_redis.set.called

    # Second call with same args: cache hit -> return cached
    mock_redis.get.reset_mock()
    mock_redis.get.return_value = json.dumps(5).encode("utf-8")
    result2 = await expensive_operation(2, 3)
    assert result2 == 5
    mock_redis.get.assert_called_once()


@pytest.mark.asyncio
async def test_rate_limit_decorator(mock_redis):
    """Test the rate_limit decorator."""
    mock_redis.zcard.return_value = 0  # No calls yet

    @rate_limit(max_calls=2, window=10)
    async def limited_function():
        return "success"

    result1 = await limited_function()
    assert result1 == "success"

    result2 = await limited_function()
    assert result2 == "success"


@pytest.mark.asyncio
async def test_distributed_lock_decorator(mock_redis):
    """Test the distributed_lock decorator."""
    mock_redis.set.return_value = True  # Lock acquired

    @distributed_lock(key="test_lock", timeout=5)
    async def locked_function():
        return "locked_result"

    result = await locked_function()
    assert result == "locked_result"
    mock_redis.set.assert_called_once()
    mock_redis.delete.assert_called_once()


# ── RedisClient unit tests ─────────────────────────────────────────────────


class TestRedisClient:
    async def test_initialize_success(self):
        client = RedisClient("redis://localhost:6379/0")
        mock_pool = AsyncMock(spec=["ping", "aclose", "is_closed"])
        mock_pool.ping = AsyncMock()
        with patch.object(rc_module.aioredis, "from_url", return_value=mock_pool):
            await client.initialize()
        assert client._initialized is True
        assert client._pool is mock_pool
        mock_pool.ping.assert_awaited_once()

    async def test_initialize_already_done(self):
        # "already done" only counts when the pool was built on *this* loop;
        # a foreign-loop pool must be rebuilt, not served.
        client = RedisClient("redis://localhost:6379/0")
        client._initialized = True
        client._loop = asyncio.get_running_loop()
        with patch.object(rc_module.aioredis, "from_url") as mock_from_url:
            await client.initialize()
        mock_from_url.assert_not_called()

    async def test_initialize_rebuilds_foreign_loop_pool(self):
        other_loop = asyncio.new_event_loop()
        try:
            client = RedisClient("redis://localhost:6379/0")
            stale_pool = MagicMock(spec=["ping", "aclose", "is_closed"])
            stale_pool.aclose = AsyncMock()
            client._initialized = True
            client._pool = stale_pool
            client._loop = other_loop  # pool belongs to a different loop
            fresh_pool = MagicMock(spec=["ping", "aclose", "is_closed"])
            fresh_pool.ping = AsyncMock()
            with patch.object(rc_module.aioredis, "from_url", return_value=fresh_pool):
                await client.initialize()
            stale_pool.aclose.assert_awaited_once()  # poisoned pool dropped
            assert client._pool is fresh_pool
            assert client._loop is asyncio.get_running_loop()
        finally:
            other_loop.close()

    async def test_initialize_connection_error(self):
        client = RedisClient("redis://localhost:6379/0")
        with patch.object(rc_module.aioredis, "from_url",
                          side_effect=ConnectionError("no conn")):
            with pytest.raises(ConnectionError):
                await client.initialize()
        assert client._initialized is False

    async def test_initialize_timeout_error(self):
        client = RedisClient("redis://localhost:6379/0")
        with patch.object(rc_module.aioredis, "from_url",
                          side_effect=TimeoutError("timed out")):
            with pytest.raises(TimeoutError):
                await client.initialize()
        assert client._initialized is False

    async def test_close(self):
        client = RedisClient("redis://localhost:6379/0")
        mock_pool = MagicMock(spec=["is_closed", "aclose"])
        mock_pool.is_closed.return_value = False
        mock_pool.aclose = AsyncMock()
        client._pool = mock_pool
        client._initialized = True
        await client.close()
        mock_pool.aclose.assert_awaited_once()
        assert client._initialized is False

    async def test_close_not_initialized(self):
        client = RedisClient("redis://localhost:6379/0")
        await client.close()

    async def test_close_twice_closes_once(self):
        # close() drops the pool reference, so a second close() is a no-op
        # rather than aclosing a dead pool again.
        client = RedisClient("redis://localhost:6379/0")
        mock_pool = MagicMock(spec=["aclose"])
        mock_pool.aclose = AsyncMock()
        client._pool = mock_pool
        client._initialized = True
        client._loop = asyncio.get_running_loop()
        await client.close()
        await client.close()
        mock_pool.aclose.assert_awaited_once()
        assert client._initialized is False
        assert client._pool is None
        assert client._loop is None

    async def test_client_property(self):
        client = RedisClient("redis://localhost:6379/0")
        client._initialized = True
        mock_pool = MagicMock(spec=["is_closed"])
        mock_pool.is_closed.return_value = False
        client._pool = mock_pool
        assert client.client is mock_pool

    async def test_client_property_not_initialized(self):
        client = RedisClient("redis://localhost:6379/0")
        with pytest.raises(RuntimeError):
            _ = client.client

    async def test_client_property_after_close_raises(self):
        client = RedisClient("redis://localhost:6379/0")
        mock_pool = MagicMock(spec=["ping", "aclose"])
        mock_pool.ping = AsyncMock()
        mock_pool.aclose = AsyncMock()
        with patch.object(rc_module.aioredis, "from_url", return_value=mock_pool):
            await client.initialize()
        await client.close()
        with pytest.raises(RuntimeError):
            _ = client.client


class TestGetRedis:
    async def test_get_redis_returns_client(self):
        mock_pool = MagicMock()
        with patch.object(rc_module.redis_client, "_initialized", True), \
             patch.object(rc_module.redis_client, "_pool", mock_pool), \
             patch.object(rc_module.redis_client, "_loop", asyncio.get_running_loop()):
            async with get_redis() as r:
                assert r is mock_pool

    async def test_get_redis_calls_initialize(self):
        mock_pool = MagicMock(spec=["is_closed"])
        mock_pool.is_closed.return_value = False
        real_client = rc_module.redis_client
        async def _init_side_effect():
            real_client._initialized = True
            real_client._pool = mock_pool
        with patch.object(real_client, "_initialized", False), \
             patch.object(real_client, "_pool", None), \
             patch.object(real_client, "initialize",
                          side_effect=_init_side_effect):
            async with get_redis() as r:
                assert r is mock_pool

    async def test_get_redis_reinitializes_foreign_loop_pool(self):
        # A pool built on a foreign loop must be swapped out — get_redis
        # detects the mismatch even though _initialized is already True.
        other_loop = asyncio.new_event_loop()
        try:
            mock_pool = MagicMock()
            real_client = rc_module.redis_client
            async def _init_side_effect():
                real_client._initialized = True
                real_client._pool = mock_pool
                real_client._loop = asyncio.get_running_loop()
            stale_pool = MagicMock()
            with patch.object(real_client, "_initialized", True), \
                 patch.object(real_client, "_pool", stale_pool), \
                 patch.object(real_client, "_loop", other_loop), \
                 patch.object(real_client, "initialize",
                              side_effect=_init_side_effect):
                async with get_redis() as r:
                    assert r is mock_pool
        finally:
            other_loop.close()

    async def test_get_redis_raises_on_connection_error(self):
        real_client = rc_module.redis_client
        with patch.object(real_client, "_initialized", False), \
             patch.object(real_client, "_pool", None), \
             patch.object(real_client, "initialize",
                          side_effect=ConnectionError("down")):
            with pytest.raises(ConnectionError):
                async with get_redis():
                    pass

    async def test_get_redis_raises_on_timeout_error(self):
        real_client = rc_module.redis_client
        with patch.object(real_client, "_initialized", False), \
             patch.object(real_client, "_pool", None), \
             patch.object(real_client, "initialize",
                          side_effect=TimeoutError("timeout")):
            with pytest.raises(TimeoutError):
                async with get_redis():
                    pass


class TestRedisHealthCheck:
    async def test_health_check_success(self):
        mock_pool = MagicMock()
        mock_pool.ping = AsyncMock()
        real_client = rc_module.redis_client
        with patch.object(real_client, "_initialized", True), \
             patch.object(real_client, "_pool", mock_pool), \
             patch.object(real_client, "initialize", new=AsyncMock()):
            result = await redis_health_check()
        assert result is True
        mock_pool.ping.assert_awaited_once()

    async def test_health_check_failure_connection_error(self):
        real_client = rc_module.redis_client
        with patch.object(real_client, "_initialized", False), \
             patch.object(real_client, "_pool", None), \
             patch.object(real_client, "initialize",
                          side_effect=ConnectionError("down")):
            result = await redis_health_check()
        assert result is False

    async def test_health_check_failure_ping_timeout(self):
        mock_pool = MagicMock()
        mock_pool.ping = AsyncMock(side_effect=TimeoutError("timeout"))
        real_client = rc_module.redis_client
        with patch.object(real_client, "_initialized", True), \
             patch.object(real_client, "_pool", mock_pool), \
             patch.object(real_client, "initialize", new=AsyncMock()):
            result = await redis_health_check()
        assert result is False
