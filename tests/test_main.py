import builtins
import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from src.core.exceptions import (
    AppException,
    AuthException,
    NotFoundException,
    PermissionDeniedException,
    RateLimitException,
    ValidationException,
)
from src.main import (
    handle_app_exception,
    handle_auth_error,
    handle_generic_exception,
    handle_http_exception,
    handle_not_found,
    handle_permission_denied,
    handle_rate_limit_exceeded,
    handle_validation_error,
    lifespan,
)

# ── Exception handler tests (direct function calls) ──────────────────────
# We test handlers as callables (not through HTTP) because Starlette's
# BaseHTTPMiddleware re-raises exceptions even after ExceptionMiddleware
# handles them, causing ServerErrorMiddleware to produce generic 500s.


class TestExceptionHandlers:
    @pytest.fixture
    def _request(self):
        return Request(scope={
            "type": "http",
            "method": "GET",
            "path": "/test",
            "query_string": b"",
            "headers": [],
            "server": ("test", 80),
        })

    async def test_app_exception(self, _request):
        exc = AppException(code="ERR", message="app error", status_code=500)
        resp = await handle_app_exception(_request, exc)
        assert resp.status_code == 500
        assert '"code":"ERR"' in resp.body.decode()

    async def test_not_found(self, _request):
        exc = NotFoundException(message="missing")
        resp = await handle_not_found(_request, exc)
        assert resp.status_code == 404
        assert '"code":"NOT_FOUND"' in resp.body.decode()

    async def test_validation_error(self, _request):
        exc = ValidationException(message="bad input")
        resp = await handle_validation_error(_request, exc)
        assert resp.status_code == 422
        assert '"code":"VALIDATION_ERROR"' in resp.body.decode()

    async def test_auth_error(self, _request):
        exc = AuthException(message="unauthorized")
        resp = await handle_auth_error(_request, exc)
        assert resp.status_code == 401
        assert '"code":"AUTH_FAILED"' in resp.body.decode()

    async def test_permission_denied(self, _request):
        exc = PermissionDeniedException(message="no access")
        resp = await handle_permission_denied(_request, exc)
        assert resp.status_code == 403
        assert '"code":"PERMISSION_DENIED"' in resp.body.decode()

    async def test_rate_limit(self, _request):
        exc = RateLimitException(message="too fast")
        resp = await handle_rate_limit_exceeded(_request, exc)
        assert resp.status_code == 429
        assert '"code":"RATE_LIMIT_EXCEEDED"' in resp.body.decode()

    async def test_http_exception(self, _request):
        from fastapi import HTTPException

        exc = HTTPException(status_code=402, detail="pay up")
        resp = await handle_http_exception(_request, exc)
        assert resp.status_code == 402
        assert '"code":"HTTP_ERROR"' in resp.body.decode()

    async def test_generic_exception(self, _request):
        exc = RuntimeError("unexpected")
        resp = await handle_generic_exception(_request, exc)
        assert resp.status_code == 500
        assert '"code":"INTERNAL_ERROR"' in resp.body.decode()


# ── Module-level code paths ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sentry_import_fallback():
    """Cover main.py lines 7-8 — sentry_sdk set to None on ImportError."""
    old_main = sys.modules.pop("src.main", None)
    original_import = builtins.__import__
    def fake_import(name, *args, **kw):
        if name == "sentry_sdk":
            raise ImportError("sentry_sdk not available")
        return original_import(name, *args, **kw)
    try:
        with patch("builtins.__import__", side_effect=fake_import):
            mod = importlib.import_module("src.main")
            assert mod.sentry_sdk is None
    finally:
        if old_main:
            sys.modules["src.main"] = old_main


@patch("src.main.settings.log_format", "text")
@pytest.mark.asyncio
async def test_default_logging_format():
    """Cover main.py line 67 — else branch for non-JSON log format."""
    mod = importlib.reload(importlib.import_module("src.main"))
    assert mod is not None


@pytest.mark.asyncio
async def test_sentry_init():
    """Cover main.py lines 75-81 — sentry_sdk.init with DSN in production."""
    with patch("src.main.settings.sentry_dsn", "https://key@sentry.io/proj"), \
         patch("src.main.settings.environment", "production"), \
         patch("src.main.sentry_sdk.init") as mock_init:
        _ = importlib.reload(importlib.import_module("src.main"))
    mock_init.assert_called_once()


# ── Root health endpoint ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_root_health(async_client):
    with patch("src.api.v1.health.check_db_health", return_value=True):
        resp = await async_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Lifespan ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lifespan_startup_shutdown():
    mock_engine = AsyncMock()
    with patch("src.main.rate_limiter.connect", new_callable=AsyncMock) as mock_connect, \
         patch("src.main.rate_limiter.disconnect", new_callable=AsyncMock) as mock_disconnect, \
         patch("src.main.engine", mock_engine):
        async with lifespan(MagicMock()):
            pass
    mock_connect.assert_awaited_once()
    mock_disconnect.assert_awaited_once()
    mock_engine.dispose.assert_awaited_once()
