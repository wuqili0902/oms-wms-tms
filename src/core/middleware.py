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

from src.core.security import TokenExpired, TokenInvalid, decode_token

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


# Audit logging only ever shows a bounded summary, so the middleware peeks at
# this many bytes of the request body and then lets the rest stream through.
AUDIT_PREVIEW_BYTES = 8192

# Hard cap on how many transport messages one peek will walk.  A client that
# dribbles 1-byte chunks must not turn the audit log into an unbounded loop.
_MAX_PEEK_MESSAGES = 4096


class _BodyBuffer:
    """Peek at the head of the request body for audit logging, then hand the
    body to the application *verbatim*.

    The earlier version of this class buffered the whole body for the log line
    and replayed it in 8 KB pieces:

    * a large upload was held in memory twice (chunk list + join) for a summary
      that prints at most 20 keys;
    * the replayed messages carried no ``more_body``, so Starlette stopped after
      the first piece — POST/PUT bodies above 8 KB reached the endpoint
      truncated, and an empty body came back as ``http.disconnect``.

    Now the peek is bounded, every message the peek consumed is replayed with
    its original flags, and anything past the preview is streamed straight from
    the transport.  A malformed or disconnect message ends the peek instead of
    spinning forever.
    """

    def __init__(self, receive: Receive, preview_limit: int = AUDIT_PREVIEW_BYTES) -> None:
        self._receive = receive
        self._preview_limit = preview_limit
        self._preview = b""
        self._queued: list[dict] = []
        self._queued_pos = 0
        self._peeked = False
        self.preview_truncated = False  # body continued past the preview

    async def read_preview(self) -> bytes:
        """Consume transport messages up to the preview limit or body end."""
        if self._peeked:
            return self._preview
        self._peeked = True

        for _ in range(_MAX_PEEK_MESSAGES):
            message = await self._receive()
            # Queue it first: whatever the transport sent must still reach the
            # application untouched, even if the peek stops here.
            self._queued.append(message)

            if not isinstance(message, dict) or message.get("type") == "http.disconnect":
                break  # malformed/disconnect: the endpoint decides, not us
            body = message.get("body") or b""
            if isinstance(body, (bytes, bytearray)):
                self._preview += bytes(body)
            if not message.get("more_body", False):
                break  # body complete — nothing left to stream
            if len(self._preview) >= self._preview_limit:
                self.preview_truncated = True
                break  # stop buffering here; the rest streams to the endpoint
        else:
            # Message cap hit while the transport still promised more_body.
            last = self._queued[-1] if self._queued else None
            if isinstance(last, dict) and last.get("more_body"):
                self.preview_truncated = True
        return self._preview

    async def read_all(self) -> bytes:
        """Compatibility alias — returns the audit preview, not the whole body."""
        return await self.read_preview()

    async def __call__(self) -> dict:
        """ASGI receive: replay the peeked messages, then pass the transport through."""
        if self._queued_pos < len(self._queued):
            message = self._queued[self._queued_pos]
            self._queued_pos += 1
            return message
        return await self._receive()


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
            except (JWTError, TokenInvalid, TokenExpired, json.JSONDecodeError, KeyError):
                # TokenExpired is not a JWTError subclass.  Leaving it out made an
                # expired token raise out of the audit middleware, so every write
                # request with a lapsed token answered 500 instead of reaching the
                # endpoint that would have said 401.
                pass
        return "anonymous"

    _SENSITIVE_KEYS = frozenset({
        "password", "passwd", "pwd", "token", "refresh_token", "access_token",
        "secret", "api_key", "apikey", "authorization", "credit_card",
        "card_number", "cvv", "ssn", "id_number",
    })

    def _redact(self, value: Any) -> Any:
        """Recursively redact sensitive fields from a parsed JSON structure.

        Any dict key whose lowercased name contains a sensitive substring is
        replaced with ``***REDACTED***``; nested dicts/lists are walked so
        secrets buried deeper than the top level are not serialized verbatim.
        Non-sensitive scalars are stringified and truncated to bound log size.
        """
        if isinstance(value, dict):
            return {
                k: ("***REDACTED***" if any(s in str(k).lower() for s in self._SENSITIVE_KEYS) else self._redact(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return str(value)[:100]

    async def _read_raw_body(self, buffer: _BodyBuffer) -> bytes:
        """Return request body bytes from a _BodyBuffer (preview) or a Starlette Request."""
        read_preview = getattr(buffer, "read_preview", None)
        if callable(read_preview):
            return await read_preview()
        read_all = getattr(buffer, "read_all", None)
        if callable(read_all):
            return await read_all()
        body_method = getattr(buffer, "body", None)
        if callable(body_method):
            return await body_method()
        return getattr(buffer, "_body", b"")

    async def _extract_request_body(self, buffer: _BodyBuffer, logger=None) -> Any | None:
        """Extract and serialize the request body for audit logging.

        Reads the body preview (via ``read_preview()`` on a _BodyBuffer or
        ``body()`` on a Request), then returns a truncated summary (first 20
        keys/items) with sensitive fields redacted. Redaction recurses into
        nested structures so secrets buried deeper than the top level are not
        serialized verbatim.
        The buffer still replays every message to FastAPI afterwards.
        """
        try:
            raw_body = await self._read_raw_body(buffer)

            if getattr(buffer, "preview_truncated", False):
                # The peek hit its byte cap mid-stream: summarising half a JSON
                # document would put misleading fragments in the audit log.
                return f"<request body over {AUDIT_PREVIEW_BYTES} bytes — not summarised>"

            body_str = raw_body.decode("utf-8", errors="replace")
            try:
                body = json.loads(body_str)
            except (json.JSONDecodeError, ValueError):
                return "unable to parse request body"

            if isinstance(body, dict):
                redacted = {}
                for k, v in list(body.items())[:20]:  # First 20 keys bound log size
                    if any(s in str(k).lower() for s in self._SENSITIVE_KEYS):
                        redacted[k] = "***REDACTED***"
                    else:
                        redacted[k] = self._redact(v)  # recurse to catch nested secrets
                return redacted

            elif isinstance(body, list):
                return [self._redact(item) for item in body[:20]]  # First 20 items
            else:
                return str(body)[:500]  # Truncate large scalar bodies

        except (json.JSONDecodeError, RuntimeError) as e:
            target = logger if logger is not None else logging.getLogger(__name__)
            target.warning("Audit log extract failed: %s", e)
            return "unable to parse request body"


__all__ = ["TraceContext", "RequestIDMiddleware", "RequestLoggingMiddleware",
            "AuditLogMiddleware"]
