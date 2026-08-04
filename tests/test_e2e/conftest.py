"""E2E-specific fixtures — mock external services so tests don't depend on live infra."""

from unittest.mock import AsyncMock, patch

import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
def mock_redis():
    """Replace Redis with a no-op AsyncMock for all E2E tests."""
    with patch("redis.asyncio.Redis") as MockRedis:  # noqa: N806
        client = AsyncMock()
        MockRedis.return_value = client
        yield


@pytest_asyncio.fixture(autouse=True)
def mock_rate_limiter():
    """Skip Redis-backed rate limiter in E2E suite."""
    from src.core.rate_limiter import RateLimiter

    class _NoOp:
        async def is_allowed(self, key: str, limit: int, window: int) -> bool:
            return True

        def cleanup_expired(self):
            pass

    app = __import__("src.main", fromlist=["app"]).app
    app.dependency_overrides[RateLimiter] = lambda: _NoOp()


@pytest_asyncio.fixture(autouse=True)
def mock_celery():
    """Skip Celery task dispatch in E2E tests."""
    with patch("src.celery_app.app.send_task"):
        yield
