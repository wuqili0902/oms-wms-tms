from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request


def _mock_request(headers: dict | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/admin/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    return Request(scope)


class TestAuditLogGetUserId:
    async def test_valid_bearer_token(self):
        from src.core.middleware import AuditLogMiddleware
        from src.core.security import create_access_token

        mw = AuditLogMiddleware()
        token = create_access_token({"sub": "user-123"})
        req = _mock_request({"authorization": f"Bearer {token}"})
        uid = await mw._get_user_id(req)
        assert uid == "user-123"

    async def test_no_auth_header(self):
        from src.core.middleware import AuditLogMiddleware

        mw = AuditLogMiddleware()
        req = _mock_request({})
        uid = await mw._get_user_id(req)
        assert uid == "anonymous"

    async def test_not_bearer(self):
        from src.core.middleware import AuditLogMiddleware

        mw = AuditLogMiddleware()
        req = _mock_request({"authorization": "Basic dXNlcjpwYXNz"})
        uid = await mw._get_user_id(req)
        assert uid == "anonymous"

    async def test_invalid_token(self):
        from src.core.middleware import AuditLogMiddleware

        mw = AuditLogMiddleware()
        req = _mock_request({"authorization": "Bearer invalid-token"})
        uid = await mw._get_user_id(req)
        assert uid == "anonymous"

    async def test_token_without_sub(self):
        from src.core.middleware import AuditLogMiddleware
        from src.core.security import create_access_token

        mw = AuditLogMiddleware()
        token = create_access_token({"role": "admin"})
        req = _mock_request({"authorization": f"Bearer {token}"})
        uid = await mw._get_user_id(req)
        assert uid == "anonymous"


class TestAuditLogExtractRequestBody:
    @staticmethod
    def _make_request(body_bytes: bytes) -> Request:
        scope = {"type": "http", "method": "POST", "path": "/admin/", "headers": [(b"content-type", b"application/json")], "query_string": b""}
        req = Request(scope)
        object.__setattr__(req, "_body", body_bytes)
        return req

    async def test_dict_body(self):
        from src.core.middleware import AuditLogMiddleware
        mw = AuditLogMiddleware()
        body = await mw._extract_request_body(self._make_request(b'{"a":"b","c":"d"}'), AsyncMock())
        assert body == {"a": "b", "c": "d"}

    async def test_dict_body_truncated(self):
        from src.core.middleware import AuditLogMiddleware
        mw = AuditLogMiddleware()
        big = {f"k{i}": "x" * 200 for i in range(50)}
        import json
        body = await mw._extract_request_body(self._make_request(json.dumps(big).encode()), AsyncMock())
        assert len(body) <= 20

    async def test_list_body(self):
        from src.core.middleware import AuditLogMiddleware
        mw = AuditLogMiddleware()
        body = await mw._extract_request_body(self._make_request(b'["a","b","c"]'), AsyncMock())
        assert body == ["a", "b", "c"]

    async def test_list_body_truncated(self):
        from src.core.middleware import AuditLogMiddleware
        mw = AuditLogMiddleware()
        import json
        items = ["x"] * 50
        body = await mw._extract_request_body(self._make_request(json.dumps(items).encode()), AsyncMock())
        assert isinstance(body, list)

    async def test_plain_value_body(self):
        from src.core.middleware import AuditLogMiddleware
        mw = AuditLogMiddleware()
        body = await mw._extract_request_body(self._make_request(b'"just a string"'), AsyncMock())
        assert body == "just a string"

    async def test_invalid_json_returns_fallback(self):
        from src.core.middleware import AuditLogMiddleware
        mw = AuditLogMiddleware()
        body = await mw._extract_request_body(self._make_request(b"not-json"), AsyncMock())
        assert body == "unable to parse request body"


async def _minimal_asgi(scope, receive, send):
    import json
    body = json.dumps({"ok": True}).encode()
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({
        "type": "http.response.body",
        "body": body,
    })


class TestTraceContext:
    def test_injects_trace_id_from_traceparent(self):
        from src.core.middleware import TraceContext
        from starlette.testclient import TestClient

        mw = TraceContext(_minimal_asgi)
        client = TestClient(mw)
        resp = client.get("/", headers={
            "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        })
        assert resp.headers.get("x-trace-id") == "0af7651916cd43dd8448eb211c80319c"

    def test_default_trace_id_without_headers(self):
        from src.core.middleware import TraceContext
        from starlette.testclient import TestClient

        mw = TraceContext(_minimal_asgi)
        client = TestClient(mw)
        resp = client.get("/")
        assert resp.headers.get("x-trace-id") == "0" * 32

    def test_short_trace_id_padded_to_32_chars(self):
        from src.core.middleware import TraceContext
        from starlette.testclient import TestClient

        mw = TraceContext(_minimal_asgi)
        client = TestClient(mw)
        resp = client.get("/", headers={"traceparent": "00-short-trace-id-01"})
        tid = resp.headers.get("x-trace-id")
        assert len(tid) == 32

    def test_non_http_scope_skips_processing(self):
        from src.core.middleware import TraceContext
        from starlette.testclient import TestClient

        mw = TraceContext(_minimal_asgi)
        client = TestClient(mw)
        resp = client.get("/")
        assert resp.status_code == 200


class TestRequestIDMiddleware:
    def test_generates_request_id(self):
        from src.core.middleware import RequestIDMiddleware
        from starlette.testclient import TestClient

        mw = RequestIDMiddleware(_minimal_asgi)
        client = TestClient(mw)
        resp = client.get("/")
        rid = resp.headers.get("x-request-id")
        assert rid is not None

    def test_uses_existing_request_id(self):
        from src.core.middleware import RequestIDMiddleware
        from starlette.testclient import TestClient

        mw = RequestIDMiddleware(_minimal_asgi)
        client = TestClient(mw)
        resp = client.get("/", headers={"x-request-id": "my-custom-id"})
        assert resp.headers.get("x-request-id") == "my-custom-id"


class TestRequestLoggingMiddleware:
    def test_logs_request_info(self):
        from unittest.mock import patch
        from src.core.middleware import RequestLoggingMiddleware, logger
        from starlette.testclient import TestClient

        mw = RequestLoggingMiddleware(_minimal_asgi)
        client = TestClient(mw)
        with patch.object(logger, "info") as mock_info:
            resp = client.get("/test-path")
            assert resp.status_code == 200
            mock_info.assert_called_once()
            args = mock_info.call_args[0]
            assert args[1] == "GET"
            assert args[2] == "/test-path"

    def test_logs_status_code(self):
        from unittest.mock import patch
        from src.core.middleware import RequestLoggingMiddleware, logger
        from starlette.testclient import TestClient

        mw = RequestLoggingMiddleware(_minimal_asgi)
        client = TestClient(mw)
        with patch.object(logger, "info") as mock_info:
            resp = client.post("/create")
            assert resp.status_code == 200
            mock_info.assert_called_once()
            args = mock_info.call_args[0]
            assert args[1] == "POST"
            assert args[3] == 200


class TestAuditLogMiddlewareCall:
    def test_get_does_not_log_audit(self):
        from unittest.mock import patch
        from src.core.middleware import AuditLogMiddleware, logger
        from starlette.testclient import TestClient

        mw = AuditLogMiddleware(_minimal_asgi)
        client = TestClient(mw)
        with patch.object(logger, "info") as mock_info:
            resp = client.get("/resource")
            assert resp.status_code == 200
            for c in mock_info.call_args_list:
                assert "Audit" not in c[0][0]

    def test_post_logs_audit(self):
        from unittest.mock import patch
        from src.core.middleware import AuditLogMiddleware, logger
        from starlette.testclient import TestClient

        mw = AuditLogMiddleware(_minimal_asgi)
        client = TestClient(mw)
        with patch.object(logger, "info") as mock_info:
            resp = client.post("/resource")
            assert resp.status_code == 200
            audit = [c for c in mock_info.call_args_list if c[0][0].startswith("Audit")]
            assert len(audit) >= 1

    def test_put_logs_audit(self):
        from unittest.mock import patch
        from src.core.middleware import AuditLogMiddleware, logger
        from starlette.testclient import TestClient

        mw = AuditLogMiddleware(_minimal_asgi)
        client = TestClient(mw)
        with patch.object(logger, "info") as mock_info:
            resp = client.put("/resource/1")
            assert resp.status_code == 200
            audit = [c for c in mock_info.call_args_list if c[0][0].startswith("Audit")]
            assert len(audit) >= 1

    def test_delete_logs_audit(self):
        from unittest.mock import patch
        from src.core.middleware import AuditLogMiddleware, logger
        from starlette.testclient import TestClient

        mw = AuditLogMiddleware(_minimal_asgi)
        client = TestClient(mw)
        with patch.object(logger, "info") as mock_info:
            resp = client.delete("/resource/1")
            assert resp.status_code == 200
            audit = [c for c in mock_info.call_args_list if c[0][0].startswith("Audit")]
            assert len(audit) >= 1

    def test_patch_logs_audit(self):
        from unittest.mock import patch
        from src.core.middleware import AuditLogMiddleware, logger
        from starlette.testclient import TestClient

        mw = AuditLogMiddleware(_minimal_asgi)
        client = TestClient(mw)
        with patch.object(logger, "info") as mock_info:
            resp = client.patch("/resource/1")
            assert resp.status_code == 200
            audit = [c for c in mock_info.call_args_list if c[0][0].startswith("Audit")]
            assert len(audit) >= 1

    def test_post_logs_user_id_from_token(self):
        from unittest.mock import patch
        from src.core.middleware import AuditLogMiddleware, logger
        from src.core.security import create_access_token
        from starlette.testclient import TestClient

        mw = AuditLogMiddleware(_minimal_asgi)
        token = create_access_token({"sub": "user-123"})
        client = TestClient(mw)
        with patch.object(logger, "info") as mock_info:
            resp = client.post("/admin/", headers={"authorization": f"Bearer {token}"})
            assert resp.status_code == 200
            audit = [c for c in mock_info.call_args_list if c[0][0].startswith("Audit")]
            assert len(audit) >= 1
            assert "user-123" in str(audit)
