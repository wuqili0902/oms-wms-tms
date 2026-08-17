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
from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from src.core.security import TokenInvalid, decode_token

# Configure structured logging for middleware
logger = logging.getLogger("middleware")


class TraceContext:
    """Inject OpenTelemetry context and trace ID into request/response headers.

    Reads existing W3C traceparent/tracestate headers (if present) and stores them in the scope,
    so downstream services or loggers can reconstruct the distributed trace.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        traceparent = request.headers.get("traceparent", "")
        span_id = request.headers.get("x-span-id") or ""

        trace_parts = traceparent.split("-")
        trace_id = trace_parts[1] if len(trace_parts) >= 2 else traceparent[-32:]

        scope["trace_id"] = trace_id[-32:] if len(trace_id) >= 32 else "0" * 32
        scope["span_id"] = span_id[:16] if len(span_id) >= 16 else "0" * 16

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

    def __init__(self, app: ASGIApp | None = None) -> None:
        super().__init__(app)  # type: ignore[arg-type]
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

    def __init__(self, app: ASGIApp | None = None) -> None:
        super().__init__(app)  # type: ignore[arg-type]
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


class _BodyBuffer:
    """Wrap a *receive* callable so that body data can be read multiple times.

    The first call to ``read_all()`` consumes all chunks from the underlying
    receive into an internal buffer.  Subsequent ``__call__`` invocations
    replay the buffered data in 8KB chunks so that downstream handlers
    (FastAPI's body parser) can parse the same request body.

    Call ``read_all()`` first (for audit logging), then pass the same
    ``_BodyBuffer`` instance as the ``receive`` to FastAPI.
    """

    def __init__(self, receive: Receive) -> None:
        self._receive = receive
        self._chunks: list[bytes] = []
        self._byte_offset = 0
        self._done = False

    async def read_all(self) -> bytes:
        """Consume all body chunks and return them as a single blob."""
        if not self._chunks and not self._done:
            while True:
                message = await self._receive()
                body = message.get("body", b"")
                if not body:
                    break
                self._chunks.append(body)
            self._done = True
        return b"".join(self._chunks)

    async def __call__(self) -> dict:
        """Replay buffered data in 8KB chunks, or signal disconnect."""
        if not self._done:
            await self.read_all()

        total_len = sum(len(c) for c in self._chunks)
        if not self._chunks:
            return {"type": "http.disconnect"}

        if self._byte_offset < total_len:
            flat = b"".join(self._chunks)
            chunk_size = min(8192, total_len - self._byte_offset)
            data = flat[self._byte_offset : self._byte_offset + chunk_size]
            self._byte_offset += chunk_size
            return {"type": "http.request", "body": data}

        return {"type": "http.disconnect"}


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Middleware to log all write operations (POST/PUT/DELETE/PATCH).

    Logs include: user_id, action, resource, detail, request_id, client_ip
    This is useful for auditing and tracking changes made through the API.
    """

    def __init__(self, app: ASGIApp | None = None) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        request_id = scope.get("request_id", "unknown")
        client_ip = request.client.host if request.client else "unknown"

        # Single buffer: read_all() for audit, then replay to FastAPI
        wrapped = _BodyBuffer(receive)

        if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
            user_id = await self._get_user_id(request)
            resource = scope.get("path", "/")
            body_summary = await self._extract_request_body(wrapped)
            logger.info(
                "Audit: %s %s by user %s from IP %s [req:%s] body=%s",
                request.method, resource, user_id, client_ip, request_id, body_summary,
            )

        # Pass the same wrapped buffer — read_all() already populated it
        await self.app(scope, wrapped, send)

    async def _get_user_id(self, request: Request) -> str:
        """Extract user identity from JWT in Authorization header."""
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = decode_token(token)
                if "sub" in payload:
                    return payload["sub"]
            except (JWTError, TokenInvalid, json.JSONDecodeError, KeyError):
                pass
        return "anonymous"

    async def _extract_request_body(self, buffer: _BodyBuffer) -> Any | None:
        """Extract and serialize the request body for audit logging.

        Calls ``read_all()`` on the buffer to populate it, then returns
        a truncated summary.  The buffer can still replay to FastAPI afterward.
        """
        try:
            raw_body = await buffer.read_all()

            body_str = raw_body.decode("utf-8", errors="replace")
            try:
                body = json.loads(body_str)
            except (json.JSONDecodeError, ValueError):
                return "unable to parse request body"

            if isinstance(body, dict):
                return {
                    k: str(v)[:100] for k, v in list(body.items())[:20]
                }  # First 20 keys, values truncated to 100 chars
            elif isinstance(body, list):
                return [str(item)[:100] for item in body[:20]]  # First 20 items
            else:
                return str(body)[:500]  # Truncate large bodies

        except (json.JSONDecodeError, RuntimeError) as e:
            logger.warning("Audit log extract failed: %s", e)
            return "unable to parse request body"


__all__ = ["TraceContext", "RequestIDMiddleware", "RequestLoggingMiddleware",
            "AuditLogMiddleware"]
