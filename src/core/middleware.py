"""Middleware components for the API gateway.

This module provides various middleware classes that can be added to the FastAPI application
to enhance security, observability, and user experience.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from src.core.security import decode_token

# Configure structured logging for middleware
logger = logging.getLogger("middleware")


class TraceContext:
    """Inject OpenTelemetry context and trace ID into request/response headers.

    Reads existing W3C traceparent/tracestate headers (if present) and stores them in the scope,
    so downstream services or loggers can reconstruct the distributed trace.
    """

    # BaseHTTPMiddleware(BaseMiddleware) no longer takes an argument; set self.app directly.

    def __init__(self, app: ASGIApp | None = None) -> None:
        if app is not None and hasattr(self, "app") == False:
            self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        trace_id = request.headers.get("traceparent", "")
        span_id = request.headers.get("x-span-id") or ""

        # Store in scope for downstream access (e.g. middleware, handlers)
        scope["trace_id"] = trace_id[-32:] if len(trace_id) >= 32 else "0" * 32
        scope["span_id"] = span_id[:16] if len(span_id) <= 16 else "0" * 16

        # Enrich logging with trace info
        old_factory = logger.factory if hasattr(logger, "factory") else None
        enriched_logger = logger.bind(trace_id=scope.get("trace_id", "unknown"), span_id=span_id[:8] or "")

        async def wrapped_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                new_headers = [(b"x-trace-id", scope.get("trace_id", "").encode())] + headers
                message["headers"] = new_headers
            await send(message)

        await self.app(scope, receive, wrapped_send)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add and forward request IDs across the application.

    This middleware adds a unique X-Request-ID header to each incoming request
    if not present, and forwards it to downstream services or logs.
    """

    # BaseHTTPMiddleware(BaseMiddleware) no longer takes an argument; set self.app directly.

    def __init__(self, app: ASGIApp | None = None) -> None:
        if app is not None and hasattr(self, "app") == False:
            self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        # Generate or extract request ID
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())

        # Add to response headers for client visibility
        async def wrapped_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                # Add request_id to response headers
                new_headers = [(b"x-request-id", request_id.encode())] + headers
                message["headers"] = new_headers
            await send(message)

        # Store in scope for access by other middleware or handlers
        scope["request_id"] = request_id
        await self.app(scope, receive, wrapped_send)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all requests with structured JSON logging.

    Logs include: method, path, status_code, duration_ms, request_id, client_ip
    """

    # BaseHTTPMiddleware(BaseMiddleware) no longer takes an argument; set self.app directly.

    def __init__(self, app: ASGIApp | None = None) -> None:
        if app is not None and hasattr(self, "app") == False:
            self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        start_time = datetime.now()
        request = Request(scope, receive)
        request_id = scope.get("request_id", "unknown")

        async def wrapped_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                logger.info(
                    "%s %s -> %d (%.2fms) [%s]",
                    request.method, scope.get("path", "/"), status_code, duration_ms, request_id,
                )
            await send(message)

        await self.app(scope, receive, wrapped_send)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Middleware to log all write operations (POST/PUT/DELETE/PATCH).

    Logs include: user_id, action, resource, detail, request_id, client_ip
    This is useful for auditing and tracking changes made through the API.
    """

    # BaseHTTPMiddleware(BaseMiddleware) no longer takes an argument; set self.app directly.

    def __init__(self, app: ASGIApp | None = None) -> None:
        if app is not None and hasattr(self, "app") == False:
            self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        request_id = scope.get("request_id", "unknown")
        client_ip = request.client.host if request.client else "unknown"

        # Only log write operations
        if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
            user_id = await self._get_user_id(request)
            resource = scope.get("path", "/")

            logger.info(
                "Audit: %s %s by user %s from IP %s [req:%s]",
                request.method, resource, user_id, client_ip, request_id,
            )

        await self.app(scope, receive, send)

    async def _get_user_id(self, request: Request) -> str:
        """Extract user identity from JWT in Authorization header."""
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = decode_token(token)
            if payload and "sub" in payload:
                return payload["sub"]
        return "anonymous"

    async def _extract_request_body(self, request: Request, receive: Receive) -> Any | None:
        """Extract and serialize the request body for audit logging."""
        try:
            body = await request.json()
            # Limit log size to prevent excessive logging
            if isinstance(body, dict):
                return {
                    k: str(v)[:100] for k, v in list(body.items())[:20]
                }  # First 20 keys, values truncated to 100 chars
            elif isinstance(body, list):
                return [str(item)[:100] for item in body[:20]]  # First 20 items
            else:
                return str(body)[:500]  # Truncate large bodies
        except Exception:
            return "unable to parse request body"
