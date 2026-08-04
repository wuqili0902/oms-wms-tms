"""Tests for src.core.csrf — CSRF token generation, verification, and middleware."""

from unittest.mock import AsyncMock, MagicMock


class TestGenerateCsrfToken:
    def test_returns_formatted_token(self):
        from src.core.csrf import generate_csrf_token

        token = generate_csrf_token()
        assert ":" in token
        seed, sig = token.split(":", 1)
        assert len(seed) == 32
        assert len(sig) == 64

    def test_produces_different_tokens(self):
        from src.core.csrf import generate_csrf_token

        tokens = {generate_csrf_token() for _ in range(100)}
        assert len(tokens) == 100


class TestVerifyToken:
    def test_valid_token(self):
        from src.core.csrf import _verify_token, generate_csrf_token

        token = generate_csrf_token()
        assert _verify_token(token, token) is True

    def test_wrong_cookie(self):
        from src.core.csrf import _verify_token, generate_csrf_token

        token = generate_csrf_token()
        other = generate_csrf_token()
        assert _verify_token(token, other) is False

    def test_tampered_signature(self):
        from src.core.csrf import _verify_token

        assert _verify_token("abc123:bad_sig", "abc123:bad_sig") is False

    def test_missing_colon(self):
        from src.core.csrf import _verify_token

        assert _verify_token("noseparator", "noseparator") is False

    def test_empty_token(self):
        from src.core.csrf import _verify_token

        assert _verify_token("", "") is False


class TestCsrfMiddleware:
    @staticmethod
    def make_request(method="GET", path="/admin/", cookies=None, headers=None, form_data=None):
        req = MagicMock()
        req.method = method
        req.url.path = path
        req.cookies = cookies or {}
        req.headers = headers or {}
        req.form = AsyncMock(return_value=form_data or {})
        return req

    def _make_middleware(self):
        from src.core.csrf import CsrfMiddleware

        return CsrfMiddleware(app=MagicMock())

    async def test_get_admin_generates_token_and_sets_cookie(self):
        mw = self._make_middleware()
        req = self.make_request(method="GET", path="/admin/dashboard")
        req.scope = {}
        call_next = AsyncMock(return_value=MagicMock())

        resp = await mw.dispatch(req, call_next)

        assert "csrf_token" in req.scope
        assert ":" in req.scope["csrf_token"]
        resp.set_cookie.assert_called_once()
        assert resp.set_cookie.call_args[0][0] == "csrf_token"
        assert resp.set_cookie.call_args[0][1] == req.scope["csrf_token"]

    async def test_get_non_admin_skips(self):
        mw = self._make_middleware()
        req = self.make_request(method="GET", path="/api/v1/orders")
        req.scope = {}
        call_next = AsyncMock(return_value=MagicMock())

        _ = await mw.dispatch(req, call_next)

        assert "csrf_token" not in req.scope
        call_next.assert_awaited_once_with(req)

    async def test_method_not_in_safe_or_unsafe_skips(self):
        mw = self._make_middleware()
        req = self.make_request(method="OPTIONS", path="/admin/")
        req.scope = {}
        call_next = AsyncMock(return_value=MagicMock())

        _ = await mw.dispatch(req, call_next)

        call_next.assert_awaited_once_with(req)

    async def test_post_admin_missing_cookie_returns_403(self):
        mw = self._make_middleware()
        req = self.make_request(method="POST", path="/admin/orders")
        call_next = AsyncMock()

        resp = await mw.dispatch(req, call_next)

        assert resp.status_code == 403
        call_next.assert_not_awaited()

    async def test_post_admin_with_valid_header(self):
        from src.core.csrf import generate_csrf_token

        mw = self._make_middleware()
        token = generate_csrf_token()
        req = self.make_request(
            method="POST",
            path="/admin/orders",
            cookies={"csrf_token": token},
            headers={"X-CSRF-Token": token},
        )
        call_next = AsyncMock(return_value=MagicMock())

        _ = await mw.dispatch(req, call_next)

        call_next.assert_awaited_once_with(req)

    async def test_post_admin_with_invalid_header(self):
        mw = self._make_middleware()
        req = self.make_request(
            method="POST",
            path="/admin/orders",
            cookies={"csrf_token": "valid_cookie_token"},
            headers={"X-CSRF-Token": "bad_token"},
        )
        call_next = AsyncMock()

        resp = await mw.dispatch(req, call_next)

        assert resp.status_code == 403
        call_next.assert_not_awaited()

    async def test_post_admin_with_valid_form(self):
        from src.core.csrf import generate_csrf_token

        mw = self._make_middleware()
        token = generate_csrf_token()
        req = self.make_request(
            method="POST",
            path="/admin/orders",
            cookies={"csrf_token": token},
            form_data={"csrf_token": token},
        )
        call_next = AsyncMock(return_value=MagicMock())

        _ = await mw.dispatch(req, call_next)

        call_next.assert_awaited_once_with(req)

    async def test_post_admin_with_invalid_form(self):
        from src.core.csrf import generate_csrf_token

        mw = self._make_middleware()
        token = generate_csrf_token()
        req = self.make_request(
            method="POST",
            path="/admin/orders",
            cookies={"csrf_token": token},
            form_data={"csrf_token": "wrong_token"},
        )
        call_next = AsyncMock()

        resp = await mw.dispatch(req, call_next)

        assert resp.status_code == 403
        call_next.assert_not_awaited()

    async def test_put_admin_requires_csrf(self):
        from src.core.csrf import generate_csrf_token

        mw = self._make_middleware()
        token = generate_csrf_token()
        req = self.make_request(
            method="PUT",
            path="/admin/orders/1",
            cookies={"csrf_token": token},
            headers={"X-CSRF-Token": token},
        )
        call_next = AsyncMock(return_value=MagicMock())

        _ = await mw.dispatch(req, call_next)

        call_next.assert_awaited_once_with(req)

    async def test_delete_admin_requires_csrf(self):
        mw = self._make_middleware()
        req = self.make_request(method="DELETE", path="/admin/orders/1", cookies={})
        call_next = AsyncMock()

        resp = await mw.dispatch(req, call_next)

        assert resp.status_code == 403

    async def test_patch_admin_requires_csrf(self):
        mw = self._make_middleware()
        req = self.make_request(method="PATCH", path="/admin/orders/1", cookies={})
        call_next = AsyncMock()

        resp = await mw.dispatch(req, call_next)

        assert resp.status_code == 403

    async def test_head_admin_generates_token(self):
        mw = self._make_middleware()
        req = self.make_request(method="HEAD", path="/admin/")
        req.scope = {}
        call_next = AsyncMock(return_value=MagicMock())

        _ = await mw.dispatch(req, call_next)

        assert "csrf_token" in req.scope
