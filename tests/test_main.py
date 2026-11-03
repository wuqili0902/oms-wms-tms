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


@pytest.fixture(autouse=True)
def _undo_module_reload_side_effects():
    """``importlib.reload(src.main)`` is a global mutation, not a local one.

    * it rebinds ``src.main.app`` to a brand-new FastAPI instance.  conftest
      captured the app created at collection time and every ``async_client``
      request goes through *that* one, so a later test that installs a
      dependency override on ``src.main.app`` overrides an app nobody is
      calling — the endpoint answers 401 and the override is invisible;
    * it re-runs ``logging.basicConfig``, silently switching the root logger to
      whatever format the test was exercising;
    * it re-imports ``sentry_sdk``.

    All three are put back here so the rest of the suite sees the module it
    collected.
    """
    import logging
    import sys

    import src as src_pkg

    saved_module = sys.modules["src.main"]
    saved_pkg_attr = getattr(src_pkg, "main", None)
    saved_app = saved_module.app
    saved_sentry = getattr(saved_module, "sentry_sdk", None)
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level

    yield

    # Re-importing "src.main" rebinds the attribute on the parent package too,
    # and `from src.main import app` resolves through that attribute — so
    # restoring sys.modules alone is not enough to hand the collected module back.
    sys.modules["src.main"] = saved_module
    if saved_pkg_attr is not None:
        src_pkg.main = saved_pkg_attr
    saved_module.app = saved_app
    saved_module.sentry_sdk = saved_sentry
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


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

    async def test_http_status_names_the_code_when_the_detail_has_none(self, _request):
        """A route that raises a plain ``HTTPException(404, "...")`` used to answer
        ``HTTP_ERROR``, and a client that branches on ``error.code`` — which is what
        the envelope is documented to carry — could not tell a missing device from a
        rejected body."""
        from fastapi import HTTPException

        for status_code, code in [(404, "NOT_FOUND"), (409, "CONFLICT"), (422, "VALIDATION_ERROR")]:
            resp = await handle_http_exception(_request, HTTPException(status_code=status_code, detail="gone"))
            assert resp.status_code == status_code
            assert f'"code":"{code}"' in resp.body.decode(), (status_code, resp.body.decode())

    async def test_a_re_raised_app_exception_keeps_its_code_and_its_sentence(self, _request):
        """``raise HTTPException(404, detail=str(e))`` is how most routers re-raise.
        The detail is then ``AppException.__str__``, so the handler read the code out
        of it and dropped the framing — the toast used to read
        "Error NOT_FOUND: Device 3f9... not found"."""
        from fastapi import HTTPException

        exc = NotFoundException(message="Device 3f9 not found")
        resp = await handle_http_exception(_request, HTTPException(status_code=404, detail=str(exc)))
        body = resp.body.decode()
        assert resp.status_code == 404
        assert '"code":"NOT_FOUND"' in body, body
        assert "Error NOT_FOUND" not in body, body
        assert "Device 3f9 not found" in body, body

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
    """Cover main.py's module-level Sentry init (DSN set + production).

    A fake sentry_sdk is injected into sys.modules first: the package is
    optional at runtime, so patching ``src.main.sentry_sdk.init`` directly would
    error out on any environment that doesn't have it installed.
    """
    fake_sentry = MagicMock()
    with patch.dict(sys.modules, {"sentry_sdk": fake_sentry}), \
         patch("src.main.settings.sentry_dsn", "https://key@sentry.io/proj"), \
         patch("src.main.settings.environment", "production"):
        importlib.reload(importlib.import_module("src.main"))

    fake_sentry.init.assert_called_once()
    assert fake_sentry.init.call_args.kwargs["dsn"] == "https://key@sentry.io/proj"


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
