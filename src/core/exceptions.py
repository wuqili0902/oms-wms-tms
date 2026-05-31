"""Custom exception classes for the API gateway.

This module provides a hierarchy of custom exceptions that can be raised throughout
the application to provide consistent error responses across all endpoints.
"""

from http import HTTPStatus
from typing import Any, Optional

from fastapi import status


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
        detail: Optional[Any] = None,
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
        detail: Optional[Any] = None,
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
        detail: Optional[Any] = None,
    ) -> None:
        super().__init__(
            code="VALIDATION_ERROR",
            status_code=status.HTTP_422_UNVALID_REQUEST,
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
        detail: Optional[Any] = None,
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
        detail: Optional[Any] = None,
    ) -> None:
        super().__init__(
            code="PERMISSION_DENIED",
            status_code=status.HTTP_403_FORBIDDEN,
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
        detail: Optional[Any] = None,
    ) -> None:
        super().__init__(
            code="RATE_LIMIT_EXCEEDED",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            message=message,
            detail=detail,
        )
