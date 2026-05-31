from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from src.api.v1.health import router as health_router
from src.auth import auth_router as auth_router
from src.config import settings
from src.core.database import engine
from src.core.exceptions import (
    AppException,
    NotFoundException,
    ValidationException,
    AuthException,
    PermissionDeniedException,
    RateLimitException,
)
from src.core.middleware import RequestIDMiddleware, RequestLoggingMiddleware, AuditLogMiddleware
from src.core.rate_limiter import rate_limiter
from src.core.response import error_response


# Configure logging
log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(levelname)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager.

    Handles startup and shutdown events for the application.
    """
    # Startup - connect to Redis for rate limiting
    if settings.redis_url:
        await rate_limiter.connect()
    
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

# Request ID middleware - must be added before other middleware that needs request_id
app.add_middleware(RequestIDMiddleware)

# Request logging middleware
app.add_middleware(RequestLoggingMiddleware)

# Audit log middleware for write operations
app.add_middleware(AuditLogMiddleware)

# Routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")

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
        detail=exc.detail,
    )


@app.exception_handler(NotFoundException)
async def handle_not_found(request: Request, exc: NotFoundException):
    """Handle 404 Not Found exceptions."""
    logger.warning("Not found: %s", request.path)
    
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        detail=exc.detail,
    )


@app.exception_handler(ValidationException)
async def handle_validation_error(request: Request, exc: ValidationException):
    """Handle 422 Unvalid Request exceptions."""
    logger.warning("Validation error: %s", request.path)
    
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        detail=exc.detail,
    )


@app.exception_handler(AuthException)
async def handle_auth_error(request: Request, exc: AuthException):
    """Handle 401 Unauthorized exceptions."""
    logger.warning("Authentication error: %s", request.path)
    
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        detail=exc.detail,
    )


@app.exception_handler(PermissionDeniedException)
async def handle_permission_denied(request: Request, exc: PermissionDeniedException):
    """Handle 403 Forbidden exceptions."""
    logger.warning("Permission denied: %s", request.path)
    
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        detail=exc.detail,
    )


@app.exception_handler(RateLimitException)
async def handle_rate_limit_exceeded(request: Request, exc: RateLimitException):
    """Handle 429 Too Many Requests exceptions."""
    logger.warning("Rate limit exceeded: %s", request.path)
    
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        detail=exc.detail,
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

