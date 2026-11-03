import json
import logging
import re
from contextlib import asynccontextmanager

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # type: ignore[name-defined]

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware.base import BaseHTTPMiddleware

from src.admin.router import router as admin_router
from src.analytics.router import router as analytics_router
from src.api.v1.events import router as events_router
from src.api.v1.health import health_check
from src.api.v1.health import router as health_router
from src.api.v1.mobile import router as mobile_router
from src.auth import auth_router as auth_router
from src.barcode.router import router as barcode_router
from src.config import settings
from src.connectors.router import router as connectors_router
from src.core._import.routes import router as import_routes
from src.core.csrf import CsrfMiddleware
from src.core.database import engine
from src.core.exceptions import (
    AppException,
    AuthException,
    NotFoundException,
    PermissionDeniedException,
    RateLimitException,
    ValidationException,
)
from src.core.idempotency import IdempotencyMiddleware
from src.core.middleware import AuditLogMiddleware, RequestIDMiddleware, RequestLoggingMiddleware, TraceContext
from src.core.rate_limiter import rate_limiter
from src.core.response import error_response
from src.core.tracing import setup_tracing
from src.logistics.router import router as logistics_router
from src.notification.router import router as notification_router
from src.oms.router import router as oms_router
from src.pda.router import router as pda_router
from src.stock.router import router as stock_router
from src.tms.router import router as tms_router
from src.webhooks.router import router as webhooks_router
from src.wms.router import router as wms_router

# Configure logging
log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

if settings.log_format == "json":
    class JSONFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            obj = {
                "ts": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info and record.exc_info[0]:
                obj["exception"] = self.formatException(record.exc_info)
            extra = {k: v for k, v in record.__dict__.items() if k not in logging.LogRecord.__dict__}
            if extra:
                obj["extra"] = extra
            return json.dumps(obj, default=str)
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=log_level, handlers=[handler])
else:
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

logger = logging.getLogger(__name__)

# ── Sentry (error capture & alerting) ────────────────────────────────────────
if settings.sentry_dsn and settings.environment == "production":
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.1,       # sample 10% of traces for cost control
        environment=settings.environment,
        release=f"{settings.app_name}@{settings.app_version}",
    )

# ── OpenTelemetry tracing (distributed trace propagation) ───────────────────
setup_tracing()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager.

    Handles startup and shutdown events for the application.
    """
    # Startup - connect to Redis for rate limiting
    if settings.redis_url:
        await rate_limiter.connect()

    # Cross-process WS delivery: every worker subscribes to the fan-out
    # channels so a write handled by ANY worker reaches clients connected to
    # THIS worker.  No-op when Redis is absent (see ws_fanout).
    from src.core.ws_fanout import ws_fanout

    # PDA WebSocket channel is imported to ensure module-level singleton init.
    from src.pda import ws as _pda_ws  # noqa: F401

    await ws_fanout.start()

    yield

    await ws_fanout.stop()

    # Shutdown - disconnect from Redis
    if settings.redis_url:
        await rate_limiter.disconnect()

    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
    lifespan=lifespan,
    servers=[{"url": "/", "description": "Default"}],
)


# ── Security headers middleware ────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if not settings.debug:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ── Idempotency guard for replayed mutations ─────────────────────────────────
# Added before CORS so it sits *inside* it: a replayed or 503 response built by
# the guard itself still has to carry CORS headers, or a browser client cannot
# read the answer that tells it the mutation was already accepted.
app.add_middleware(IdempotencyMiddleware)


# ── Server header suppression middleware ────────────────────────────────────
class RemoveServerHeaderMiddleware(BaseHTTPMiddleware):
    """Remove Server header from responses to avoid version leakage."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if "server" in response.headers:
            del response.headers["server"]
        return response


app.add_middleware(RemoveServerHeaderMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization", "Content-Type", "X-Request-ID",
        "X-CSRF-Token", "X-Extend-Signature", "X-Extend-Timestamp",
        # A preflight that does not allow this header means the browser never
        # sends it, so every replay from a web client arrives unlabelled and the
        # idempotency guard cannot recognise it.
        "X-Idempotency-Key",
    ],
    # Without this the guard's answer is invisible to a browser: the response
    # arrives, but reading x-idempotency-replayed throws.
    expose_headers=["X-Idempotency-Replayed"],
)

# CSRF protection for admin HTML forms
app.add_middleware(CsrfMiddleware)

# TrustedHost — restrict allowed hosts in production (skip in testing)
if not settings.debug and not settings.testing:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.cors_origins_list)

# TraceContext — must be first so downstream middlewares see trace_id
app.add_middleware(TraceContext)

# Request ID middleware - must be added before other middleware that needs request_id
app.add_middleware(RequestIDMiddleware)

# Request logging middleware
app.add_middleware(RequestLoggingMiddleware)

# Audit log middleware for write operations
app.add_middleware(AuditLogMiddleware)

# Routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(events_router)  # outbox ingest — router carries its own /api/v1/events prefix
app.include_router(auth_router, prefix="/api/v1")
app.include_router(oms_router, prefix="/api/v1")
app.include_router(wms_router, prefix="/api/v1")
app.include_router(barcode_router, prefix="/api/v1")
app.include_router(logistics_router, prefix="/api/v1")
app.include_router(tms_router, prefix="/api/v1")
app.include_router(mobile_router, prefix="/api/v1")
app.include_router(connectors_router, prefix="/api/v1")
app.include_router(notification_router)
app.include_router(analytics_router)
app.include_router(admin_router)  # no /api/v1 prefix — these are HTML pages, not REST
app.include_router(import_routes, prefix="/api/v1")
app.include_router(stock_router, prefix="/api/v1")
app.include_router(pda_router)
app.include_router(webhooks_router)

# Root-level health endpoint (used by Docker/K8s liveness probes)
@app.get("/health", include_in_schema=False)
async def root_health(response: Response):
    return await health_check(response)

# Prometheus metrics — internal only, not exposed publicly
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


# Global exception handlers
@app.exception_handler(AppException)
async def handle_app_exception(request: Request, exc: AppException):
    """Handle custom application exceptions."""
    logger.error(
        "Application error %s: %s",
        exc.code,
        exc.message,
        extra={"request_id": request.headers.get("x-request-id")},
    )

    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


@app.exception_handler(NotFoundException)
async def handle_not_found(request: Request, exc: NotFoundException):
    """Handle 404 Not Found exceptions."""
    logger.warning("Not found: %s", request.url.path)

    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


@app.exception_handler(ValidationException)
async def handle_validation_error(request: Request, exc: ValidationException):
    """Handle 422 Unvalid Request exceptions."""
    logger.warning("Validation error: %s", request.url.path)

    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


@app.exception_handler(AuthException)
async def handle_auth_error(request: Request, exc: AuthException):
    """Handle 401 Unauthorized exceptions."""
    logger.warning("Authentication error: %s", request.url.path)

    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


@app.exception_handler(PermissionDeniedException)
async def handle_permission_denied(request: Request, exc: PermissionDeniedException):
    """Handle 403 Forbidden exceptions."""
    logger.warning("Permission denied: %s", request.url.path)

    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


@app.exception_handler(RateLimitException)
async def handle_rate_limit_exceeded(request: Request, exc: RateLimitException):
    """Handle 429 Too Many Requests exceptions."""
    logger.warning("Rate limit exceeded: %s", request.url.path)

    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


# Routes across the API catch the service's own error and re-raise it as
# ``HTTPException(status_code=404, detail=str(e))``.  This handler then answered
# ``code: "HTTP_ERROR"`` for all of them — a client branching on the documented
# envelope could not tell a missing device from a rejected body — and the message
# carried ``AppException.__str__``'s framing, so the toast read
# "Error NOT_FOUND: Device 3f9… not found".  Both are repaired here rather than at
# the ~65 call sites, because the re-raise is a normal FastAPI idiom and this
# handler is the one place that decides how it reaches the wire.
_STATUS_CODE_BY_STATUS = {
    400: "VALIDATION_ERROR",
    401: "AUTH_FAILED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    417: "VALIDATION_ERROR",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
}
# ``AppException.__str__`` — the string the routers pass into ``detail``.
_APP_ERROR_DETAIL = re.compile(r"^Error ([A-Z][A-Z0-9_]+): ([\s\S]*)$")


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException):
    """Handle FastAPI HTTP exceptions in the documented error envelope.

    A re-raised ``AppException`` carries its own code in the detail this handler
    reads, so ``NOT_FOUND`` survives the trip to the client; a plain
    ``HTTPException`` gets its code from its status, and only a status the API
    has no code for is left as ``HTTP_ERROR``.
    """
    logger.warning(
        "HTTP error %d: %s",
        exc.status_code,
        exc.detail,
        extra={"request_id": request.headers.get("x-request-id")},
    )

    code = _STATUS_CODE_BY_STATUS.get(exc.status_code, "HTTP_ERROR")
    message = str(exc.detail)
    carried = _APP_ERROR_DETAIL.match(message)
    if carried:
        code, message = carried.group(1), carried.group(2)

    return error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation(request: Request, exc: RequestValidationError):
    """Render Pydantic request-validation failures in the documented error envelope.

    Every other error this API answers is ``{"success": false, "error": {"code",
    "message"}}`` — ``error_response`` is the single shape all the handlers above
    use.  A body that failed Pydantic validation bypassed all of them and got
    FastAPI's own ``{"detail": [{"loc": [...], "msg": ...}, ...]}``: a client
    written against the documented contract found neither ``error`` nor
    ``success``, and had to parse a second format for the most common failure in
    the API.  The stock endpoints made that the normal path — their bodies were
    bare ``dict``s, so a missing field was a 500 and a typed body was the fix,
    which meant the typed bodies had to speak the documented language.

    Field names keep the path the client sent (``data.lines.1.qty``), each entry
    echoes the value that field carried, and the message names the first problem
    plus how many there were, because Pydantic reports them all and a client that
    fixes only the first will be back.
    """
    errors = []
    for item in exc.errors():
        loc = [str(part) for part in item.get("loc", ())]
        field = ".".join(part for part in loc if part not in ("body",)) or "body"
        message = str(item.get("msg", "invalid value"))
        ctx = item.get("ctx") or {}
        if ctx.get("expected"):
            message = f"{message} (expected {ctx['expected']})"
        entry = {"field": field, "message": message}
        # The value the caller sent for that field, when it is a scalar.  Pydantic
        # knows it, and a refusal that names the field and lists the accepted
        # values is half the answer without the value that was refused — the
        # console shows the message, and "类型 must be one of …" is answered by
        # the operator looking at what they typed.
        sent = item.get("input")
        if sent is None or isinstance(sent, (str, int, float, bool)):
            entry["value"] = sent
        errors.append(entry)

    first = errors[0] if errors else {"field": "body", "message": "invalid request"}
    sentence = f"{first['field']}: {first['message']}"
    if first.get("value") not in (None, ...):
        sentence = f"{sentence} — sent {first['value']!r}"
    message = f"Request validation failed: {sentence}"
    if len(errors) > 1:
        message = f"{message} ({len(errors)} field problems in total)"

    logger.warning(
        "Request validation failed: %s — %s",
        request.url.path,
        "; ".join(f"{e['field']}: {e['message']}" for e in errors[:5]),
        extra={"request_id": request.headers.get("x-request-id")},
    )

    return error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message=message,
        errors=errors,
    )


@app.exception_handler(Exception)
async def handle_generic_exception(request: Request, exc: Exception):
    """Handle all other exceptions."""
    logger.error(
        "Unhandled exception: %s",
        str(exc),
        exc_info=True,
        extra={"request_id": request.headers.get("x-request-id")},
    )

    return error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred",
    )
