"""Tests for middleware edge cases."""
import asyncio
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


class BodyReadingApp:
    """ASGI app that reads the body the way Starlette does.

    Accumulates every ``http.request`` message until ``more_body`` is false, so
    a middleware that replays a body without ``more_body`` shows up as a
    truncated body here.
    """

    def __init__(self):
        self.body = b""
        self.messages = []

    async def __call__(self, scope, receive, send):
        while True:
            message = await receive()
            self.messages.append(message)
            if message.get("type") == "http.disconnect":
                break
            self.body += message.get("body", b"") or b""
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})


def make_chunked_receive(chunks, *, truncate_last_with_disconnect=False):
    """A receive callable emitting ``chunks`` with correct ``more_body`` flags."""
    state = {"i": 0}

    async def _receive():
        i = state["i"]
        state["i"] += 1
        if i < len(chunks):
            return {"type": "http.request", "body": chunks[i], "more_body": i < len(chunks) - 1}
        if truncate_last_with_disconnect:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": b"", "more_body": False}

    return _receive


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
        from unittest.mock import MagicMock

        from starlette.requests import Request

        from src.core.security import create_access_token

        token = create_access_token({"sub": "user123"})
        request = MagicMock(spec=Request)
        request.headers = {"authorization": f"Bearer {token}"}
        result = await middleware._get_user_id(request)
        assert result == "user123"

    async def test_get_user_id_no_header(self, middleware):
        from unittest.mock import MagicMock

        from starlette.requests import Request

        request = MagicMock(spec=Request)
        request.headers = {}
        result = await middleware._get_user_id(request)
        assert result == "anonymous"

    async def test_get_user_id_invalid_token(self, middleware):
        from unittest.mock import MagicMock

        from starlette.requests import Request

        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer invalid_token_here"}
        result = await middleware._get_user_id(request)
        assert result == "anonymous"

    async def test_extract_request_body_dict(self, middleware):
        from unittest.mock import AsyncMock

        from starlette.requests import Request

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
        from unittest.mock import AsyncMock

        from starlette.requests import Request

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
        from unittest.mock import AsyncMock

        from starlette.requests import Request

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
        from unittest.mock import AsyncMock

        from starlette.requests import Request

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

    async def test_body_larger_than_replay_chunk_reaches_endpoint_intact(self):
        # Regression: the buffer used to replay in 8 KB pieces without
        # more_body, so Starlette stopped after the first piece and endpoints
        # silently received a truncated body.
        from src.core.middleware import AuditLogMiddleware

        chunks = [b"a" * 8192, b"b" * 8192, b"c" * 5000]
        expected = b"".join(chunks)
        app = BodyReadingApp()
        scope = make_scope(method="POST", path="/api/orders")

        await AuditLogMiddleware(app)(scope, make_chunked_receive(chunks), _noop_send)

        assert app.body == expected, f"body truncated to {len(app.body)} of {len(expected)} bytes"

    async def test_empty_body_reaches_endpoint_as_request_message(self):
        # The old replay answered with http.disconnect for an empty body, which
        # Starlette reads as "the client went away".
        from src.core.middleware import AuditLogMiddleware

        app = BodyReadingApp()
        scope = make_scope(method="POST", path="/api/orders")

        await AuditLogMiddleware(app)(scope, make_chunked_receive([b""]), _noop_send)

        assert app.messages[0]["type"] == "http.request"
        assert app.body == b""

    async def test_oversized_body_is_previewed_not_buffered(self):
        # Audit needs only a bounded preview; the endpoint must still get every
        # byte streamed through the middleware.
        from src.core.middleware import AUDIT_PREVIEW_BYTES, AuditLogMiddleware

        chunks = [b"x" * 8192] * 13  # 106496 bytes
        expected = b"".join(chunks)
        app = BodyReadingApp()
        scope = make_scope(method="POST", path="/api/orders")

        await AuditLogMiddleware(app)(scope, make_chunked_receive(chunks), _noop_send)

        assert app.body == expected
        assert AUDIT_PREVIEW_BYTES == 8192  # documented budget for the peek

    async def test_oversized_body_summary_is_honest_about_the_cap(self, caplog):
        from src.core.middleware import AuditLogMiddleware

        chunks = [b'{"items": [' + b"1," * 6000, b"garbage-past-the-cap]"]  # 12 KB then more
        scope = make_scope(method="POST", path="/api/orders")

        with caplog.at_level("INFO", logger="middleware"):
            await AuditLogMiddleware(MockApp())(scope, make_chunked_receive(chunks), _noop_send)

        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "not summarised" in messages, messages
        assert "garbage" not in messages  # half-parsed JSON must not leak into the log

    async def test_misbehaving_transport_does_not_spin_forever(self, middleware):
        # A receive that never reports more_body=false used to loop forever,
        # growing the audit buffer until the process was killed.
        from src.core.middleware import AuditLogMiddleware

        results = {}
        async def record_send(message):
            if message["type"] == "http.response.start":
                results["called"] = True

        scope = make_scope(method="POST", path="/api/orders")
        await asyncio.wait_for(
            AuditLogMiddleware(MockApp())(scope, AsyncMock(), record_send),
            timeout=10,
        )
        assert results["called"] is True

    async def test_peek_stops_at_the_byte_budget_on_normal_streams(self):
        from src.core.middleware import AUDIT_PREVIEW_BYTES, _BodyBuffer

        buffer = _BodyBuffer(make_chunked_receive([b"z" * 8192] * 12))
        preview = await buffer.read_preview()

        assert len(preview) == AUDIT_PREVIEW_BYTES
        assert buffer.preview_truncated is True

    async def test_peek_stops_at_the_message_cap_on_pathological_streams(self):
        # 12 000 one-byte chunks: the message cap binds before the byte budget,
        # so a client that dribbles bytes cannot make the audit loop unbounded.
        from src.core.middleware import _BodyBuffer

        buffer = _BodyBuffer(make_chunked_receive([b"z"] * 12000))
        preview = await buffer.read_preview()

        assert len(preview) == 4096  # _MAX_PEEK_MESSAGES
        assert buffer.preview_truncated is True

        # The endpoint still receives the whole stream afterwards.
        app = BodyReadingApp()
        await app(make_scope(method="POST", path="/api/orders"), buffer, _noop_send)
        assert app.body == b"z" * 12000


async def _noop_send(message):
    pass
