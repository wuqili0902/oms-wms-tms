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

# CSRF token validity window (seconds)
CSRF_TOKEN_MAX_AGE = 3600  # 1 hour


def generate_csrf_token() -> str:
    """Generate a CSRF token with an embedded timestamp for expiration."""
    seed = secrets.token_hex(16)
    ts = str(int(time.time()))
    msg = f"csrf:{seed}:{ts}"
    sig = hmac.new(
        settings.secret_key.encode(), msg.encode(), hashlib.sha256
    ).hexdigest()
    return f"{seed}:{ts}:{sig}"


def _verify_token(token: str, cookie_token: str) -> bool:
    """Verify that *token* matches *cookie_token* and is not expired."""
    try:
        parts = token.split(":", 2)
        if len(parts) != 3:
            return False
        seed, ts_str, sig = parts
        ts = int(ts_str)
        # Reject expired tokens
        if abs(time.time() - ts) > CSRF_TOKEN_MAX_AGE:
            return False
        msg = f"csrf:{seed}:{ts_str}"
        expected = hmac.new(
            settings.secret_key.encode(), msg.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig, expected) and token == cookie_token
    except (ValueError, AttributeError):
        return False


def _client_ip_for_signature(request: Request) -> str:
    """The address an extend signature is bound to.

    The address is in the HMAC precisely so a captured (path, timestamp, signature)
    triple cannot be used from another machine.  Reading it out of X-Real-Ip or
    X-Forwarded-For cancels that: whoever replayed the triple types the original
    client's address into a header and the check passes.  The TCP peer decides.

    A forwarding header is consulted only when the peer itself is a proxy the
    deployment declared it trusts (``settings.trusted_proxy_ips``) — which is the
    one case where the peer genuinely is not the client.
    """
    peer = request.client.host if request.client else "unknown"

    raw = getattr(settings, "trusted_proxy_ips", "")
    trusted = {entry.strip() for entry in raw.split(",")} if isinstance(raw, str) else set()
    trusted.discard("")

    if peer in trusted:
        forwarded = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip") or ""
        first_hop = forwarded.split(",")[0].strip()
        if first_hop:
            return first_hop

    return peer


def _verify_extend_signature(request: Request) -> bool:
    """Verify X-Extend-Signature header for extension API routes.

    Signature = HMAC-SHA256(secret, "path:timestamp:client_ip").
    Client must send X-Extend-Timestamp header with a Unix timestamp
    within the last 5 minutes to prevent replay attacks.
    """
    path = request.url.path

    # Only check /api/v1/extend/* paths; reject all other API methods
    if not path.startswith("/api/v1/extend"):
        return False  # Non-extend routes must have their own auth (e.g. JWT)

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

    client_ip = _client_ip_for_signature(request)
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
                secure=not settings.debug,
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
                # Only try form fallback for form content types
                ct = request.headers.get("content-type", "")
                if "application/x-www-form-urlencoded" in ct or "multipart/form-data" in ct:
                    form = await request.form()
                    form_token = str(form.get("csrf_token", ""))
                    if not form_token or not _verify_token(form_token, cookie_token):
                        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
                else:
                    return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
            return await call_next(request)

        # Extension API routes — require HMAC signature
        if method in ("POST", "PUT", "DELETE", "PATCH") and path.startswith("/api/v1/extend"):
            if not _verify_extend_signature(request):
                return JSONResponse(
                    status_code=403, content={"detail": "Extension API authentication failed"}
                )

        return await call_next(request)
