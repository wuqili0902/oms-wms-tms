"""Tests for src.cache.decorators — cached, rate_limit, distributed_lock."""

from unittest.mock import AsyncMock, patch

import pytest


class TestGenerateCacheKey:
    def test_different_args_different_keys(self):
        from src.cache.decorators import _generate_cache_key

        k1 = _generate_cache_key("pfx", "foo", (1,), {})
        k2 = _generate_cache_key("pfx", "foo", (2,), {})
        assert k1 != k2

    def test_different_prefixes_different_keys(self):
        from src.cache.decorators import _generate_cache_key

        k1 = _generate_cache_key("a", "foo", (1,), {})
        k2 = _generate_cache_key("b", "foo", (1,), {})
        assert k1 != k2

    def test_format(self):
        from src.cache.decorators import _generate_cache_key

        key = _generate_cache_key("pfx", "bar", ("x",), {"y": 1})
        assert key.startswith("pfx:bar:")

    def test_skip_args_makes_same_key(self):
        from src.cache.decorators import _generate_cache_key

        k1 = _generate_cache_key("pfx", "f", (99, 1, 2), {})
        k2 = _generate_cache_key("pfx", "f", (42, 1, 2), {})
        assert k1 != k2


class TestCachedDecorator:
    async def test_cache_miss(self):
        from src.cache.decorators import cached

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        @cached(ttl=60, prefix="test")
        async def my_func(x: int) -> int:
            return x * 2

        with patch("src.cache.decorators.get_redis") as mock_get_redis:
            mock_get_redis.return_value.__aenter__.return_value = mock_redis

            result = await my_func(5)
            assert result == 10
            mock_redis.get.assert_awaited_once()
            mock_redis.set.assert_awaited_once()

    async def test_cache_hit(self):
        import json

        from src.cache.decorators import cached

        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps(42).encode("utf-8")

        @cached(ttl=60, prefix="test")
        async def my_func(x: int) -> int:
            return x * 2

        with patch("src.cache.decorators.get_redis") as mock_get_redis:
            mock_get_redis.return_value.__aenter__.return_value = mock_redis

            result = await my_func(5)
            assert result == 42
            mock_redis.get.assert_awaited_once()
            mock_redis.set.assert_not_called()

    async def test_redis_unavailable_fallback(self):
        from src.cache.decorators import cached

        mock_redis = AsyncMock()
        mock_redis.get.side_effect = ConnectionError("down")

        call_count = 0

        @cached(ttl=60, prefix="test")
        async def my_func(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        with patch("src.cache.decorators.get_redis") as mock_get_redis:
            mock_get_redis.return_value.__aenter__.return_value = mock_redis

            result = await my_func(5)
            assert result == 10
            assert call_count == 1

    async def test_skip_args_parameter(self):
        from src.cache.decorators import cached

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        @cached(ttl=60, prefix="test", skip_args=1)
        async def my_func(_db, x: int) -> int:
            return x * 2

        with patch("src.cache.decorators.get_redis") as mock_get_redis:
            mock_get_redis.return_value.__aenter__.return_value = mock_redis

            result = await my_func("session", 5)
            assert result == 10


class TestRateLimitDecorator:
    async def test_under_limit(self):
        from src.cache.decorators import rate_limit

        mock_redis = AsyncMock()
        mock_redis.zcard.return_value = 5

        call_count = 0

        @rate_limit(max_calls=10, window=60)
        async def api_call():
            nonlocal call_count
            call_count += 1
            return "ok"

        with patch("src.cache.decorators.get_redis") as mock_get_redis:
            mock_get_redis.return_value.__aenter__.return_value = mock_redis

            result = await api_call()
            assert result == "ok"
            assert call_count == 1
            mock_redis.zadd.assert_awaited_once()

    async def test_exceeds_limit(self):
        from src.cache.decorators import RateLimitExceeded, rate_limit

        mock_redis = AsyncMock()
        mock_redis.zcard.return_value = 10

        @rate_limit(max_calls=10, window=60)
        async def api_call():
            return "ok"

        with patch("src.cache.decorators.get_redis") as mock_get_redis:
            mock_get_redis.return_value.__aenter__.return_value = mock_redis

            with pytest.raises(RateLimitExceeded):
                await api_call()

    async def test_redis_unavailable(self):
        from src.cache.decorators import rate_limit

        mock_redis = AsyncMock()
        mock_redis.zadd.side_effect = ConnectionError("down")

        call_count = 0

        @rate_limit(max_calls=10, window=60)
        async def api_call():
            nonlocal call_count
            call_count += 1
            return "ok"

        with patch("src.cache.decorators.get_redis") as mock_get_redis:
            mock_get_redis.return_value.__aenter__.return_value = mock_redis

            result = await api_call()
            assert result == "ok"
            assert call_count == 1


class TestDistributedLock:
    async def test_acquires_lock_and_releases(self):
        from src.cache.decorators import distributed_lock

        mock_redis = AsyncMock()
        mock_redis.set.return_value = True

        @distributed_lock(key="my_resource", timeout=10)
        async def critical():
            return "done"

        with patch("src.cache.decorators.get_redis") as mock_get_redis:
            mock_get_redis.return_value.__aenter__.return_value = mock_redis

            result = await critical()
            assert result == "done"
            mock_redis.set.assert_called_once()
            mock_redis.delete.assert_awaited_once()

    async def test_lock_not_acquired(self):
        from src.cache.decorators import distributed_lock

        mock_redis = AsyncMock()
        mock_redis.set.return_value = None  # nx=True returns None when key exists

        @distributed_lock(key="busy_resource", timeout=10)
        async def critical():
            return "done"

        with patch("src.cache.decorators.get_redis") as mock_get_redis:
            mock_get_redis.return_value.__aenter__.return_value = mock_redis

            result = await critical()
            assert result is None

    async def test_release_on_finally(self):
        from src.cache.decorators import distributed_lock

        mock_redis = AsyncMock()
        mock_redis.set.return_value = True

        @distributed_lock(key="r", timeout=10)
        async def critical():
            raise ValueError("boom")

        with patch("src.cache.decorators.get_redis") as mock_get_redis:
            mock_get_redis.return_value.__aenter__.return_value = mock_redis

            with pytest.raises(ValueError):
                await critical()
            mock_redis.delete.assert_awaited_once()

    async def test_redis_unavailable_fallback(self):
        from src.cache.decorators import distributed_lock

        mock_redis = AsyncMock()
        mock_redis.set.side_effect = ConnectionError("down")

        call_count = 0

        @distributed_lock(key="r", timeout=10)
        async def critical():
            nonlocal call_count
            call_count += 1
            return "fallback"

        with patch("src.cache.decorators.get_redis") as mock_get_redis:
            mock_get_redis.return_value.__aenter__.return_value = mock_redis

            result = await critical()
            assert result == "fallback"
            assert call_count == 1
