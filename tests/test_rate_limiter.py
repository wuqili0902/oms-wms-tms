"""Tests for rate limiter — token bucket and graceful degradation.

Tests the RateLimiter class with mocked Redis (Sorted Set ZADD/ZRANGE API).
"""
import pytest

from src.core.rate_limiter import RateLimiter, rate_limit


class _Pipeline:
    """Mimics aioredis pipeline for rate_limiter's zadd/zrange/execute flow."""

    def __init__(self, count):
        self._count = count

    def zadd(self, key, member, score):
        return self

    def zrange(self, key, start, end):
        return self

    async def execute(self):
        return [self._count, self._count]


class _MockRedis:
    """Mock aioredis client matching the rate_limiter's actual API."""

    def __init__(self, count=50):
        self._count = count

    async def time(self):
        return 1000  # int — rate_limiter does int(current_time)

    def pipeline(self):
        return _Pipeline(self._count)

    async def zrange(self, key, start, end):
        return self._count

    async def ping(self):
        return True

    async def aclose(self):
        pass

    async def close(self):
        pass


class TestGracefulDegradation:
    """When Redis is unavailable, all requests pass through."""

    @pytest.mark.asyncio
    async def test_disconnected_allows(self):
        rl = RateLimiter()
        assert await rl.check_rate_limit("k") is True
        assert await rl.check_rate_limit("k", requests=10) is True

    @pytest.mark.asyncio
    async def test_disconnected_headers_empty(self):
        rl = RateLimiter()
        assert await rl.get_rate_limit_headers("k") == {}

    @pytest.mark.asyncio
    async def test_disconnect(self):
        rl = RateLimiter()
        rl._connected = True
        rl.client = _MockRedis()
        await rl.disconnect()
        assert rl._connected is False

    @pytest.mark.asyncio
    async def test_disconnect_noop(self):
        rl = RateLimiter()
        await rl.disconnect()  # should not raise


class TestTokenBucket:
    """Token bucket checking with mocked Redis."""

    @pytest.mark.asyncio
    async def test_under_limit_allowed(self):
        rl = RateLimiter()
        rl._connected = True
        rl.client = _MockRedis(count=50)
        assert await rl.check_rate_limit("k", requests=100) is True

    @pytest.mark.asyncio
    async def test_over_limit_denied(self):
        rl = RateLimiter()
        rl._connected = True
        rl.client = _MockRedis(count=150)
        assert await rl.check_rate_limit("k", requests=100) is False

    @pytest.mark.asyncio
    async def test_redis_error_graceful(self):
        rl = RateLimiter()
        rl._connected = True
        rl.client = _MockRedis(count=50)
        rl.client.time = lambda: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore
        assert await rl.check_rate_limit("k") is True


class TestHeaders:
    """Rate limit header generation."""

    @pytest.mark.asyncio
    async def test_connected_headers(self):
        rl = RateLimiter()
        rl._connected = True
        rl.client = _MockRedis(count=30)
        headers = await rl.get_rate_limit_headers("k")
        assert headers["X-Rate-Limit"] == "100"

    @pytest.mark.asyncio
    async def test_disconnected_headers(self):
        rl = RateLimiter()
        assert await rl.get_rate_limit_headers("k") == {}

    @pytest.mark.asyncio
    async def test_error_headers(self):
        rl = RateLimiter()
        rl._connected = True
        rl.client = _MockRedis(count=30)
        rl.client.time = lambda: (_ for _ in ()).throw(RuntimeError("t/o"))  # type: ignore
        assert await rl.get_rate_limit_headers("k") == {}


class TestDecorator:
    """The standalone @rate_limit decorator factory."""

    def test_creates_callable(self):
        d = rate_limit(requests=10, window=60)
        assert callable(d)

    def test_preserves_name(self):
        @rate_limit(requests=20)
        async def f(): pass
        assert f.__name__ == "f"
