import hmac
import hashlib

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.config import settings
from src.core.csrf import CsrfMiddleware, _verify_token, generate_csrf_token


def _make_app():
    async def ok(request):
        return PlainTextResponse("ok")

    methods = ["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH"]
    routes = [
        Route("/admin/", endpoint=ok, methods=methods),
        Route("/admin/dashboard", endpoint=ok, methods=methods),
        Route("/api/public", endpoint=ok, methods=methods),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(CsrfMiddleware)
    return app


class TestGenerateCsrfToken:
    def test_returns_seed_sig_format(self):
        token = generate_csrf_token()
        parts = token.split(":")
        assert len(parts) == 2
        assert len(parts[0]) == 32
        assert len(parts[1]) == 64

    def test_generates_unique_tokens(self):
        tokens = {generate_csrf_token() for _ in range(100)}
        assert len(tokens) == 100


class TestVerifyToken:
    def test_valid_token(self):
        token = generate_csrf_token()
        assert _verify_token(token, token) is True

    def test_wrong_token_value(self):
        token = generate_csrf_token()
        assert _verify_token(token, "some-other-token") is False

    def test_wrong_seed_in_token(self):
        token = generate_csrf_token()
        seed, sig = token.split(":", 1)
        bad_token = f"differentseed{sig}"
        assert _verify_token(bad_token, bad_token) is False

    def test_malformed_token_no_colon(self):
        assert _verify_token("malformed-no-colon", "cookie-token") is False

    def test_empty_values(self):
        assert _verify_token("", "") is False

    def test_different_message_in_token(self):
        token = generate_csrf_token()
        wrong_sig = hmac.new(
            settings.secret_key.encode(), b"csrf:different_msg", hashlib.sha256
        ).hexdigest()
        bad_token = f"seed:{wrong_sig}"
        assert _verify_token(bad_token, bad_token) is False


class TestCsrfMiddleware:
    def test_get_admin_sets_cookie(self):
        client = TestClient(_make_app())
        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert "csrf_token" in resp.cookies
        assert resp.cookies["csrf_token"]

    def test_get_admin_dashboard_sets_cookie(self):
        client = TestClient(_make_app())
        resp = client.get("/admin/dashboard")
        assert resp.status_code == 200
        assert "csrf_token" in resp.cookies

    def test_post_admin_without_cookie_returns_403(self):
        client = TestClient(_make_app())
        resp = client.post("/admin/")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "CSRF validation failed"

    def test_post_admin_with_cookie_and_header_passes(self):
        client = TestClient(_make_app())
        first = client.get("/admin/")
        token = first.cookies["csrf_token"]
        resp = client.post(
            "/admin/",
            headers={"X-CSRF-Token": token, "Cookie": f"csrf_token={token}"},
        )
        assert resp.status_code == 200

    def test_post_admin_with_cookie_and_bad_header_returns_403(self):
        client = TestClient(_make_app())
        first = client.get("/admin/")
        token = first.cookies["csrf_token"]
        resp = client.post(
            "/admin/",
            headers={"X-CSRF-Token": "bad-token", "Cookie": f"csrf_token={token}"},
        )
        assert resp.status_code == 403

    def test_post_admin_with_cookie_and_form_passes(self):
        client = TestClient(_make_app())
        first = client.get("/admin/")
        token = first.cookies["csrf_token"]
        resp = client.post(
            "/admin/",
            data={"csrf_token": token},
            headers={"Cookie": f"csrf_token={token}"},
        )
        assert resp.status_code == 200

    def test_post_admin_with_cookie_and_bad_form_returns_403(self):
        client = TestClient(_make_app())
        first = client.get("/admin/")
        token = first.cookies["csrf_token"]
        resp = client.post(
            "/admin/",
            data={"csrf_token": "bad"},
            headers={"Cookie": f"csrf_token={token}"},
        )
        assert resp.status_code == 403

    def test_non_admin_path_passes_through(self):
        client = TestClient(_make_app())
        resp = client.post("/api/public", json={"data": "test"})
        assert resp.status_code == 200

    def test_get_non_admin_path_no_cookie(self):
        client = TestClient(_make_app())
        resp = client.get("/api/public")
        assert resp.status_code == 200
        assert "csrf_token" not in resp.cookies

    def test_put_admin_without_cookie_returns_403(self):
        client = TestClient(_make_app())
        resp = client.put("/admin/")
        assert resp.status_code == 403

    def test_delete_admin_without_cookie_returns_403(self):
        client = TestClient(_make_app())
        resp = client.delete("/admin/")
        assert resp.status_code == 403

    def test_patch_admin_without_cookie_returns_403(self):
        client = TestClient(_make_app())
        resp = client.patch("/admin/")
        assert resp.status_code == 403
