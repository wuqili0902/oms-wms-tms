"""Middleware components for the API gateway.

This module provides various middleware classes that can be added to the FastAPI application
to enhance security, observability, and user experience.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

# Configure structured logging for middleware
logger = logging.getLogger("middleware")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add and forward request IDs across the application.

    This middleware adds a unique X-Request-ID header to each incoming request
    if not present, and forwards it to downstream services or logs.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

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

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        start_time = datetime.now()
        request = Request(scope, receive)
        request_id = scope.get("request_id", "unknown")
        client_ip = request.client.host if request.client else "unknown"

        async def wrapped_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                log_data = {
                    "level": "info"
                    if status_code < 400
                    else "warning"
                    if status_code < 500
                    else "error",
                    "method": request.method,
                    "path": scope.get("path", "/"),
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "request_id": request_id,
                    "client_ip": client_ip,
                }
                logger.info(
                    "%s %s -> %d (%.2fms)",
                    request.method,
                    scope.get("path", "/"),
                    status_code,
                    duration_ms,
                )
            await send(message)

        await self.app(scope, receive, wrapped_send)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Middleware to log all write operations (POST/PUT/DELETE/PATCH).

    Logs include: user_id, action, resource, detail, request_id, client_ip
    This is useful for auditing and tracking changes made through the API.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        request_id = scope.get("request_id", "unknown")
        client_ip = request.client.host if request.client else "unknown"

        # Only log write operations
        if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
            user_id = await self._get_user_id(request)
            resource = scope.get("path", "/")

            logger.info(
                "Audit: %s %s by user %s from IP %s",
                request.method,
                resource,
                user_id,
                client_ip,
            )

        await self.app(scope, receive, send)

    async def _get_user_id(self, request: Request) -> str:
        """Extract user ID from the request. This is a placeholder implementation."""
        # TODO: Implement actual authentication extraction logic
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            # In real implementation, decode JWT or validate session
            return f"token:{len(token)}chars"  # Placeholder
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
