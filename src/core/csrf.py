import hashlib
import hmac
import logging
import secrets
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import settings

logger = logging.getLogger(__name__)


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


def _verify_extend_signature(request: Request) -> bool:
    """Verify X-Extend-Signature header for extension API routes.

    Signature = HMAC-SHA256(secret, "path:timestamp:client_ip").
    Client must send X-Extend-Timestamp header with a Unix timestamp
    within the last 5 minutes to prevent replay attacks.
    """
    path = request.url.path

    # Only check /api/v1/extend/* paths
    if not path.startswith("/api/v1/extend"):
        return True  # No signature required for non-extend routes in this middleware

    actual_sig = request.headers.get("X-Extend-Signature", "")
    if not actual_sig:
        logger.warning("Missing X-Extend-Signature header on %s", path)
        return False

    timestamp_str = request.headers.get("X-Extend-Timestamp", "")
    if not timestamp_str:
        logger.warning("Missing X-Extend-Timestamp header on %s", path)
        return False

    try:
        ts = int(timestamp_str)
    except ValueError:
        logger.warning("Invalid X-Extend-Timestamp on %s: %s", path, timestamp_str)
        return False

    # Reject timestamps older than 5 minutes (replay protection)
    if abs(int(time.time()) - ts) > 300:
        logger.warning("X-Extend-Timestamp expired on %s (ts=%s)", path, timestamp_str)
        return False

    client_ip = request.client.host if request.client else "unknown"
    msg = f"{path}:{timestamp_str}:{client_ip}"
    expected_sig = hmac.new(
        settings.secret_key.encode(),
        msg.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(actual_sig, expected_sig):
        logger.warning("Invalid X-Extend-Signature for %s from %s", path, client_ip)
        return False

    return True


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # Admin routes — set cookie on GET/HEAD, validate on mutating methods
        if method in ("GET", "HEAD") and path.startswith("/admin/"):
            token = generate_csrf_token()
            request.scope["csrf_token"] = token
            response = await call_next(request)
            response.set_cookie(
                "csrf_token", token, path="/admin/", httponly=True, samesite="lax",
            )
            return response

        if method in ("POST", "PUT", "DELETE", "PATCH") and path.startswith("/admin/"):
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

        # Extension API routes — require HMAC signature
        if method in ("POST", "PUT", "DELETE", "PATCH") and path.startswith("/api/v1/extend"):
            if not _verify_extend_signature(request):
                return JSONResponse(
                    status_code=403, content={"detail": "Extension API authentication failed"}
                )

        return await call_next(request)
