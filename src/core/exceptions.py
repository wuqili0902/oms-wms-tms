"""Custom exception classes for the API gateway.

This module provides a hierarchy of custom exceptions that can be raised throughout
the application to provide consistent error responses across all endpoints.
"""

from typing import Any

from fastapi import status

# Starlette renamed this constant across releases — ``HTTP_422_UNPROCESSABLE_ENTITY``
# (0.46, installed here) vs ``..._CONTENT`` (other 0.4x builds) — and FastAPI
# re-exports whichever module object it holds, so only one of the two names is
# guaranteed to exist.  Reading the absent one raised AttributeError, which turned
# every validation failure into a 500 whose message was the AttributeError itself
# ("Registration failed: module 'starlette.status' has no attribute …").
HTTP_422_UNPROCESSABLE = (
    getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", None)
    or getattr(status, "HTTP_422_UNPROCESSABLE_ENTITY", None)
    or 422
)


class AppException(Exception):
    """Base exception class for all application-specific errors.

    This class provides a foundation for custom exceptions that can be caught
    and handled by the global exception handler to return consistent error responses.

    Attributes:
        code (str): A unique error code for this exception type
        status_code (int): HTTP status code to return
        message (str): Human-readable error message
        detail (Optional[Any]): Additional context or details about the error
    """

    def __init__(
        self,
        code: str = "APP_ERROR",
        status_code: int = 500,
        message: str = "An application error occurred",
        detail: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return f"Error {self.code}: {self.message}"


class NotFoundException(AppException):
    """Raised when a requested resource is not found.

    HTTP Status Code: 404 Not Found
    Error Code: NOT_FOUND
    """

    def __init__(
        self,
        message: str = "Resource not found",
        detail: Any | None = None,
    ) -> None:
        super().__init__(
            code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
            message=message,
            detail=detail,
        )


class ValidationException(AppException):
    """Raised when request validation fails.

    HTTP Status Code: 422 Unvalid Request
    Error Code: VALIDATION_ERROR
    """

    def __init__(
        self,
        message: str = "Validation failed",
        detail: Any | None = None,
    ) -> None:
        super().__init__(
            code="VALIDATION_ERROR",
            status_code=HTTP_422_UNPROCESSABLE,
            message=message,
            detail=detail,
        )


class AuthException(AppException):
    """Raised when authentication fails.

    HTTP Status Code: 401 Unauthorized
    Error Code: AUTH_FAILED
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        detail: Any | None = None,
    ) -> None:
        super().__init__(
            code="AUTH_FAILED",
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=message,
            detail=detail,
        )


class PermissionDeniedException(AppException):
    """Raised when a user lacks permission to perform an action.

    HTTP Status Code: 403 Forbidden
    Error Code: PERMISSION_DENIED
    """

    def __init__(
        self,
        message: str = "Permission denied",
        detail: Any | None = None,
    ) -> None:
        super().__init__(
            code="PERMISSION_DENIED",
            status_code=status.HTTP_403_FORBIDDEN,
            message=message,
            detail=detail,
        )


class ConflictException(AppException):
    """Raised when the resource changed underneath the request.

    Used by the optimistic-locking paths: the write was rejected because another
    transaction had already modified the row, so the caller has to re-read and
    retry rather than assume the update happened.

    HTTP Status Code: 409 Conflict
    Error Code: CONFLICT
    """

    def __init__(
        self,
        message: str = "Resource was modified concurrently",
        detail: Any | None = None,
    ) -> None:
        super().__init__(
            code="CONFLICT",
            status_code=status.HTTP_409_CONFLICT,
            message=message,
            detail=detail,
        )


class NotImplementedActionException(AppException):
    """Raised when the API is asked for an action this build does not perform.

    HTTP Status Code: 501 Not Implemented
    Error Code: NOT_IMPLEMENTED

    The connector endpoints answer 200 for the actions they do, and this for the
    ones they don't.  A "同步" button that answers 200 for a sync that never
    happened is worse than a 501: the operator reads success, and the system they
    are reconciling against has never been told.
    """

    def __init__(
        self,
        message: str = "This action is not implemented",
        detail: Any | None = None,
    ) -> None:
        super().__init__(
            code="NOT_IMPLEMENTED",
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            message=message,
            detail=detail,
        )


class RateLimitException(AppException):
    """Raised when rate limiting is exceeded.

    HTTP Status Code: 429 Too Many Requests
    Error Code: RATE_LIMIT_EXCEEDED
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        detail: Any | None = None,
    ) -> None:
        super().__init__(
            code="RATE_LIMIT_EXCEEDED",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            message=message,
            detail=detail,
        )
