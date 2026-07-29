"""Tests for src.core.rate_limiter — RateLimiter and rate_limit decorator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRateLimiterInit:
    def test_init_default_url(self, monkeypatch):
        from src.core.rate_limiter import RateLimiter

        monkeypatch.setattr("src.core.rate_limiter.settings", MagicMock(redis_url="redis://default"))
        rl = RateLimiter()
        assert rl.redis_url == "redis://default"
        assert rl.client is None
        assert rl._connected is False

    def test_init_custom_url(self):
        from src.core.rate_limiter import RateLimiter

        rl = RateLimiter(redis_url="redis://custom:6379")
        assert rl.redis_url == "redis://custom:6379"


class TestRateLimiterConnect:
    async def test_connect_success(self):
        from src.core.rate_limiter import RateLimiter

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        rl = RateLimiter(redis_url="redis://test:6379")
        with patch("src.core.rate_limiter.aioredis.from_url", return_value=mock_redis):
            result = await rl.connect()

        assert result is True
        assert rl._connected is True
        assert rl.client is mock_redis
        mock_redis.ping.assert_awaited_once()

    async def test_connect_creates_client_only_once(self):
        from src.core.rate_limiter import RateLimiter

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        rl = RateLimiter(redis_url="redis://test:6379")
        rl.client = mock_redis
        rl._connected = False

        result = await rl.connect()
        assert result is True
        assert rl._connected is True

    async def test_connect_failure(self):
        from src.core.rate_limiter import RateLimiter

        rl = RateLimiter(redis_url="redis://bad:6379")
        with patch("src.core.rate_limiter.aioredis.from_url", side_effect=ConnectionError("no redis")):
            result = await rl.connect()

        assert result is False
        assert rl._connected is False

    async def test_connect_ping_failure(self):
        from src.core.rate_limiter import RateLimiter

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("ping failed"))

        rl = RateLimiter(redis_url="redis://test:6379")
        with patch("src.core.rate_limiter.aioredis.from_url", return_value=mock_redis):
            result = await rl.connect()

        assert result is False
        assert rl._connected is False


class TestRateLimiterDisconnect:
    async def test_disconnect_when_connected(self):
        from src.core.rate_limiter import RateLimiter

        mock_redis = AsyncMock()
        mock_redis.close = AsyncMock()

        rl = RateLimiter(redis_url="redis://test:6379")
        rl.client = mock_redis
        rl._connected = True

        await rl.disconnect()
        mock_redis.close.assert_awaited_once()
        assert rl._connected is False

    async def test_disconnect_when_not_connected(self):
        from src.core.rate_limiter import RateLimiter

        rl = RateLimiter(redis_url="redis://test:6379")
        await rl.disconnect()


class TestCheckRateLimit:
    async def test_not_connected_returns_true(self):
        from src.core.rate_limiter import RateLimiter

        rl = RateLimiter(redis_url="redis://test:6379")
        rl._connected = False

        result = await rl.check_rate_limit("test-key", requests=100, window=60)
        assert result is True

    @staticmethod
    def _make_mock_redis(time_val, pipeline_exec_result):
        mock_redis = MagicMock()
        mock_redis.time = AsyncMock(return_value=time_val)
        mock_pipeline = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value=pipeline_exec_result)
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        return mock_redis

    async def test_allowed(self):
        from src.core.rate_limiter import RateLimiter

        mock_redis = self._make_mock_redis([1735000000, 0], [1, 1])

        rl = RateLimiter(redis_url="redis://test:6379")
        rl.client = mock_redis
        rl._connected = True

        result = await rl.check_rate_limit("user-1", requests=100, window=60)
        assert result is True

    async def test_exceeded(self):
        from src.core.rate_limiter import RateLimiter

        mock_redis = self._make_mock_redis([1735000000, 0], [1, 200])

        rl = RateLimiter(redis_url="redis://test:6379")
        rl.client = mock_redis
        rl._connected = True

        result = await rl.check_rate_limit("user-1", requests=100, window=60)
        assert result is False

    async def test_unexpected_response_allows(self):
        from src.core.rate_limiter import RateLimiter

        mock_redis = self._make_mock_redis([1735000000, 0], ["error", None])

        rl = RateLimiter(redis_url="redis://test:6379")
        rl.client = mock_redis
        rl._connected = True

        result = await rl.check_rate_limit("user-1")
        assert result is True

    async def test_redis_error_returns_true(self):
        from src.core.rate_limiter import RateLimiter

        mock_redis = AsyncMock()
        mock_redis.time = AsyncMock(side_effect=Exception("redis down"))

        rl = RateLimiter(redis_url="redis://test:6379")
        rl.client = mock_redis
        rl._connected = True

        result = await rl.check_rate_limit("user-1")
        assert result is True


class TestGetRateLimitHeaders:
    async def test_not_connected_returns_empty(self):
        from src.core.rate_limiter import RateLimiter

        rl = RateLimiter(redis_url="redis://test:6379")
        rl._connected = False

        result = await rl.get_rate_limit_headers("test-key")
        assert result == {}

    async def test_connected_returns_headers(self):
        from src.core.rate_limiter import RateLimiter

        mock_redis = AsyncMock()
        mock_redis.time = AsyncMock(return_value=[1735000000, 0])
        mock_redis.zcount = AsyncMock(return_value=5)

        rl = RateLimiter(redis_url="redis://test:6379")
        rl.client = mock_redis
        rl._connected = True

        result = await rl.get_rate_limit_headers("user-1")
        assert result["X-Rate-Limit"] == "100"
        assert result["X-Rate-Remaining"] == "95"
        assert result["X-Rate-Window"] == "60"

    async def test_connected_non_int_response(self):
        from src.core.rate_limiter import RateLimiter

        mock_redis = AsyncMock()
        mock_redis.time = AsyncMock(return_value=[1735000000, 0])
        mock_redis.zcount = AsyncMock(return_value=5.5)

        rl = RateLimiter(redis_url="redis://test:6379")
        rl.client = mock_redis
        rl._connected = True

        result = await rl.get_rate_limit_headers("user-1")
        assert result == {}

    async def test_redis_error_returns_empty(self):
        from src.core.rate_limiter import RateLimiter

        mock_redis = AsyncMock()
        mock_redis.time = AsyncMock(side_effect=Exception("redis down"))

        rl = RateLimiter(redis_url="redis://test:6379")
        rl.client = mock_redis
        rl._connected = True

        result = await rl.get_rate_limit_headers("user-1")
        assert result == {}


class TestRateLimitDecorator:
    @staticmethod
    def make_request(client_host=None):
        req = MagicMock()
        req.client = MagicMock() if client_host else None
        if client_host:
            req.client.host = client_host
        return req

    async def test_custom_key_func(self):
        from src.core.rate_limiter import rate_limit

        called_key_func = False

        def my_key_func(request):
            nonlocal called_key_func
            called_key_func = True
            return "custom-key"

        @rate_limit(requests=10, window=5, key_func=my_key_func)
        async def my_endpoint(request):
            return {"ok": True}

        req = self.make_request("1.2.3.4")
        with patch("src.core.rate_limiter.rate_limiter.check_rate_limit", AsyncMock(return_value=True)):
            result = await my_endpoint(req)

        assert result == {"ok": True}
        assert called_key_func

    async def test_default_ip_key(self):
        from src.core.rate_limiter import rate_limit

        @rate_limit(requests=10, window=5)
        async def my_endpoint(request):
            return {"ok": True}

        req = self.make_request("1.2.3.4")
        with patch("src.core.rate_limiter.rate_limiter.check_rate_limit", AsyncMock(return_value=True)) as mock_check:
            result = await my_endpoint(req)

        assert result == {"ok": True}
        mock_check.assert_awaited_once()
        key_arg = mock_check.await_args[0][0]
        assert key_arg == "ip:1.2.3.4"

    async def test_default_ip_key_no_client(self):
        from src.core.rate_limiter import rate_limit

        @rate_limit(requests=10, window=5)
        async def my_endpoint(request):
            return {"ok": True}

        req = self.make_request(None)
        with patch("src.core.rate_limiter.rate_limiter.check_rate_limit", AsyncMock(return_value=True)) as mock_check:
            result = await my_endpoint(req)

        assert result == {"ok": True}
        mock_check.assert_awaited_once()
        key_arg = mock_check.await_args[0][0]
        assert key_arg == "ip:unknown"

    async def test_rate_limit_exceeded_raises_429(self):
        from fastapi import HTTPException
        from src.core.rate_limiter import rate_limit

        @rate_limit(requests=5, window=10)
        async def my_endpoint(request):
            return {"ok": True}

        req = self.make_request("1.2.3.4")
        with patch("src.core.rate_limiter.rate_limiter.check_rate_limit", AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as exc:
                await my_endpoint(req)

            assert exc.value.status_code == 429
            assert "Rate limit exceeded" in exc.value.detail

    async def test_json_response_gets_headers(self):
        from starlette.responses import JSONResponse

        from src.core.rate_limiter import rate_limit

        @rate_limit(requests=50, window=30)
        async def my_endpoint(request):
            return JSONResponse(content={"ok": True}, status_code=200)

        req = self.make_request("1.2.3.4")
        with (
            patch("src.core.rate_limiter.rate_limiter.check_rate_limit", AsyncMock(return_value=True)),
            patch("src.core.rate_limiter.rate_limiter.get_rate_limit_headers", AsyncMock(return_value={"X-Test": "1"})),
        ):
            result = await my_endpoint(req)

        assert isinstance(result, JSONResponse)
        assert result.headers.get("X-Test") == "1"

    async def test_non_json_response_no_header_modification(self):
        from src.core.rate_limiter import rate_limit

        @rate_limit(requests=50, window=30)
        async def my_endpoint(request):
            return {"ok": True}

        req = self.make_request("1.2.3.4")
        with (
            patch("src.core.rate_limiter.rate_limiter.check_rate_limit", AsyncMock(return_value=True)),
            patch("src.core.rate_limiter.rate_limiter.get_rate_limit_headers", AsyncMock(return_value={"X-Test": "1"})),
        ):
            result = await my_endpoint(req)

        assert result == {"ok": True}
