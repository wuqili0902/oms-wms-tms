"""Tests for middleware edge cases."""
from unittest.mock import AsyncMock

import pytest


def make_scope(headers=None, **overrides):
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "headers": headers or [],
        "scheme": "http",
        "query_string": b"",
        "client": ("127.0.0.1", 50000),
        "server": ("localhost", 80),
    }
    scope.update(overrides)
    return scope


class MockApp:
    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})


class TestTraceContext:
    @pytest.fixture
    def middleware(self):
        from src.core.middleware import TraceContext
        return TraceContext(MockApp())

    async def test_adds_trace_id_from_traceparent(self, middleware):
        send = AsyncMock()
        scope = make_scope([(b"traceparent", b"00-abcdef1234567890abcdef1234567890-1234567890abcdef-01")])
        receive = AsyncMock()
        await middleware(scope, receive, send)
        assert scope["trace_id"] == "abcdef1234567890abcdef1234567890"

    async def test_short_traceparent_uses_default(self, middleware):
        send = AsyncMock()
        scope = make_scope([(b"traceparent", b"00-short")])
        receive = AsyncMock()
        await middleware(scope, receive, send)
        assert scope["trace_id"] == "0" * 32

    async def test_x_span_id_header(self, middleware):
        send = AsyncMock()
        scope = make_scope([(b"x-span-id", b"abcd" * 4)])
        receive = AsyncMock()
        await middleware(scope, receive, send)
        assert scope["span_id"] == "abcdabcdabcdabcd"

    async def test_long_span_id_truncated(self, middleware):
        send = AsyncMock()
        scope = make_scope([(b"x-span-id", b"x" * 20)])
        receive = AsyncMock()
        await middleware(scope, receive, send)
        assert scope["span_id"] == "x" * 16

    async def test_fallback_when_no_headers(self, middleware):
        send = AsyncMock()
        scope = make_scope()
        receive = AsyncMock()
        await middleware(scope, receive, send)
        assert scope["trace_id"] == "0" * 32
        assert scope["span_id"] == "0" * 16

    async def test_sets_response_header(self, middleware):
        results = {}
        async def record_send(message):
            if message["type"] == "http.response.start":
                results["headers"] = dict(message.get("headers", []))
        send = record_send
        scope = make_scope()
        receive = AsyncMock()
        await middleware(scope, receive, send)
        assert results["headers"].get(b"x-trace-id") == b"0" * 32

    async def test_app_called(self, middleware):
        called = False
        async def fake_app(scope, receive, send):
            nonlocal called
            called = True
        middleware.app = fake_app
        send = AsyncMock()
        scope = make_scope()
        receive = AsyncMock()
        await middleware(scope, receive, send)
        assert called


class TestRequestIDMiddlewareCall:
    @pytest.fixture
    def middleware(self):
        from src.core.middleware import RequestIDMiddleware
        return RequestIDMiddleware(MockApp())

    async def test_generates_request_id_when_missing(self, middleware):
        results = {}
        async def record_send(message):
            if message["type"] == "http.response.start":
                results["headers"] = dict(message.get("headers", []))
        send = record_send
        scope = make_scope()
        receive = AsyncMock()
        await middleware(scope, receive, send)
        assert "request_id" in scope
        rid = results["headers"].get(b"x-request-id")
        assert rid is not None
        assert len(rid) > 0

    async def test_uses_existing_request_id(self, middleware):
        results = {}
        async def record_send(message):
            if message["type"] == "http.response.start":
                results["headers"] = dict(message.get("headers", []))
        send = record_send
        scope = make_scope([(b"x-request-id", b"custom-id")])
        receive = AsyncMock()
        await middleware(scope, receive, send)
        assert scope["request_id"] == "custom-id"
        assert results["headers"].get(b"x-request-id") == b"custom-id"


class TestRequestLoggingMiddleware:
    @pytest.fixture
    def middleware(self):
        from src.core.middleware import RequestLoggingMiddleware
        return RequestLoggingMiddleware(MockApp())

    async def test_logs_request(self, middleware):
        send = AsyncMock()
        scope = make_scope(method="POST", path="/test")
        scope["request_id"] = "req-1"
        receive = AsyncMock()
        await middleware(scope, receive, send)
        send.assert_called()


class TestAuditLogMiddleware:
    @pytest.fixture
    def middleware(self):
        from src.core.middleware import AuditLogMiddleware
        return AuditLogMiddleware(MockApp())

    async def test_get_user_id_valid_token(self, middleware):
        from src.core.security import create_access_token
        from starlette.requests import Request
        from unittest.mock import MagicMock

        token = create_access_token({"sub": "user123"})
        request = MagicMock(spec=Request)
        request.headers = {"authorization": f"Bearer {token}"}
        result = await middleware._get_user_id(request)
        assert result == "user123"

    async def test_get_user_id_no_header(self, middleware):
        from starlette.requests import Request
        from unittest.mock import MagicMock

        request = MagicMock(spec=Request)
        request.headers = {}
        result = await middleware._get_user_id(request)
        assert result == "anonymous"

    async def test_get_user_id_invalid_token(self, middleware):
        from starlette.requests import Request
        from unittest.mock import MagicMock

        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer invalid_token_here"}
        result = await middleware._get_user_id(request)
        assert result == "anonymous"

    async def test_extract_request_body_dict(self, middleware):
        from starlette.requests import Request
        from unittest.mock import AsyncMock

        body = b'{"key1": "value1", "key2": "value2"}'
        receive = AsyncMock(return_value={"type": "http.request", "body": body, "more_body": False})
        scope = {
            "type": "http", "method": "POST", "path": "/test",
            "headers": [(b"content-type", b"application/json")],
        }
        request = Request(scope, receive=receive)
        result = await middleware._extract_request_body(request, receive)
        assert result is not None
        assert isinstance(result, dict)
        assert result["key1"] == "value1"

    async def test_extract_request_body_list(self, middleware):
        from starlette.requests import Request
        from unittest.mock import AsyncMock

        body = b'[{"id": 1}, {"id": 2}]'
        receive = AsyncMock(return_value={"type": "http.request", "body": body, "more_body": False})
        scope = {
            "type": "http", "method": "POST", "path": "/test",
            "headers": [(b"content-type", b"application/json")],
        }
        request = Request(scope, receive=receive)
        result = await middleware._extract_request_body(request, receive)
        assert isinstance(result, list)
        assert len(result) == 2

    async def test_extract_request_body_scalar(self, middleware):
        from starlette.requests import Request
        from unittest.mock import AsyncMock

        body = b'"just a string"'
        receive = AsyncMock(return_value={"type": "http.request", "body": body, "more_body": False})
        scope = {
            "type": "http", "method": "POST", "path": "/test",
            "headers": [(b"content-type", b"application/json")],
        }
        request = Request(scope, receive=receive)
        result = await middleware._extract_request_body(request, receive)
        assert isinstance(result, str)

    async def test_extract_request_body_invalid_json(self, middleware):
        from starlette.requests import Request
        from unittest.mock import AsyncMock

        body = b"not valid json"
        receive = AsyncMock(return_value={"type": "http.request", "body": body, "more_body": False})
        scope = {
            "type": "http", "method": "POST", "path": "/test",
            "headers": [(b"content-type", b"application/json")],
        }
        request = Request(scope, receive=receive)
        result = await middleware._extract_request_body(request, receive)
        assert result == "unable to parse request body"

    async def test_logs_write_operations(self, middleware):
        from src.core.middleware import AuditLogMiddleware
        mw = AuditLogMiddleware(MockApp())
        results = {}
        async def record_send(message):
            if message["type"] == "http.response.start":
                results["called"] = True
        scope = make_scope(method="POST", path="/api/orders")
        receive = AsyncMock()
        await mw(scope, receive, record_send)
        assert results["called"] is True

    async def test_skips_read_operations(self, middleware):
        from src.core.middleware import AuditLogMiddleware
        called = False
        async def check_send(message):
            nonlocal called
            called = True
        scope = make_scope(method="GET", path="/api/orders")
        receive = AsyncMock()
        await AuditLogMiddleware(MockApp())(scope, receive, check_send)
        assert called is True
