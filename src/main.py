import json
import logging
from contextlib import asynccontextmanager

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # type: ignore[name-defined]

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from src.admin.router import router as admin_router
from src.analytics.router import router as analytics_router
from src.api.v1.health import health_check
from src.api.v1.health import router as health_router
from src.api.v1.mobile import router as mobile_router
from src.auth import auth_router as auth_router
from src.barcode.router import router as barcode_router
from src.config import settings
from src.connectors.router import router as connectors_router
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
from src.core.middleware import AuditLogMiddleware, RequestIDMiddleware, RequestLoggingMiddleware, TraceContext
from src.core.rate_limiter import rate_limiter
from src.core.response import error_response
from src.core.tracing import setup_tracing
from src.notification.router import router as notification_router
from src.oms.router import router as oms_router
from src.pda.router import router as pda_router
from src.tms.router import router as tms_router
from src.webhooks.router import router as webhooks_router
from src.wms.router import router as wms_router
from src.core._import.routes import router as import_routes

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

    # PDA WebSocket channel is imported to ensure module-level singleton init.
    from src.pda import ws as _pda_ws  # noqa: F401

    yield

    # Shutdown - disconnect from Redis
    if settings.redis_url:
        await rate_limiter.disconnect()

    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSRF protection for admin HTML forms
app.add_middleware(CsrfMiddleware)

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
app.include_router(auth_router, prefix="/api/v1")
app.include_router(oms_router, prefix="/api/v1")
app.include_router(wms_router, prefix="/api/v1")
app.include_router(barcode_router, prefix="/api/v1")
app.include_router(tms_router, prefix="/api/v1")
app.include_router(mobile_router, prefix="/api/v1")
app.include_router(connectors_router, prefix="/api/v1")
app.include_router(notification_router)
app.include_router(analytics_router)
app.include_router(admin_router)  # no /api/v1 prefix — these are HTML pages, not REST
app.include_router(import_routes, prefix="/api/v1")
app.include_router(pda_router)
app.include_router(webhooks_router)

# Root-level health endpoint (used by Docker/K8s liveness probes)
@app.get("/health", include_in_schema=False)
async def root_health():
    return await health_check()

# Prometheus metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


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


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException):
    """Handle FastAPI HTTP exceptions."""
    logger.warning(
        "HTTP error %d: %s",
        exc.status_code,
        exc.detail,
        extra={"request_id": request.headers.get("x-request-id")},
    )

    return error_response(
        status_code=exc.status_code,
        code="HTTP_ERROR",
        message=str(exc.detail),
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
