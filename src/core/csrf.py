import hashlib
import hmac
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import settings


def generate_csrf_token() -> str:
    seed = secrets.token_hex(16)
    msg = f"csrf:{seed}"
    sig = hmac.new(
        settings.secret_key.encode(), msg.encode(), hashlib.sha256
    ).hexdigest()
    return f"{seed}:{sig}"


def _verify_token(token: str, cookie_token: str) -> bool:
    try:
        seed, sig = token.split(":", 1)
        msg = f"csrf:{seed}"
        expected = hmac.new(
            settings.secret_key.encode(), msg.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig, expected) and token == cookie_token
    except (ValueError, AttributeError):
        return False


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method in ("GET", "HEAD") and path.startswith("/admin/"):
            token = generate_csrf_token()
            request.scope["csrf_token"] = token
            response = await call_next(request)
            response.set_cookie(
                "csrf_token", token, path="/admin/", httponly=True, samesite="lax",
            )
            return response

        if request.method in ("POST", "PUT", "DELETE", "PATCH") and path.startswith("/admin/"):
            cookie_token = request.cookies.get("csrf_token", "")
            if not cookie_token:
                return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
            header_token = request.headers.get("X-CSRF-Token", "")
            if header_token:
                if not _verify_token(header_token, cookie_token):
                    return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
            else:
                form = await request.form()
                form_token = form.get("csrf_token", "")
                if not form_token or not _verify_token(form_token, cookie_token):
                    return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
            return await call_next(request)

        return await call_next(request)
