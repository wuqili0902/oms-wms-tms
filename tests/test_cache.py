from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cache.decorators import cached, rate_limit, distributed_lock


class MockRedisClient:
    """A mock that simulates redis.asyncio.Redis methods."""

    def __init__(self):
        self._store = {}
        self.setex = AsyncMock(side_effect=self._setex)
        self.get = AsyncMock(side_effect=self._get)
        self.delete = AsyncMock(side_effect=self._delete)
        self.zremrange = AsyncMock()
        self.zcard = AsyncMock(return_value=0)
        self.zadd = AsyncMock()
        self.set = AsyncMock(return_value=True)
        self.ping = AsyncMock()
        self.aclose = AsyncMock()
        self.is_closed = MagicMock(return_value=False)

    def _setex(self, name, time, value, *args, **kwargs):
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
    assert mock_redis.setex.called

    # Second call with same args: cache hit -> return cached
    mock_redis.get.reset_mock()
    mock_redis.get.return_value = b"5"  # Simulate cached result
    result2 = await expensive_operation(2, 3)
    assert result2 == "5"  # returns decoded string
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
    mock_redis.setex.return_value = True  # Lock acquired

    @distributed_lock(key="test_lock", timeout=5)
    async def locked_function():
        return "locked_result"

    result = await locked_function()
    assert result == "locked_result"
    mock_redis.setex.assert_called_once()
    mock_redis.delete.assert_called_once()
