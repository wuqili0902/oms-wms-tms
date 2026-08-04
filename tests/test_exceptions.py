"""Tests for src.core.exceptions — AppException and subclasses."""

from fastapi import status


class TestAppException:
    def test_defaults(self):
        from src.core.exceptions import AppException

        exc = AppException()
        assert exc.code == "APP_ERROR"
        assert exc.status_code == 500
        assert exc.message == "An application error occurred"
        assert exc.detail is None

    def test_custom_values(self):
        from src.core.exceptions import AppException

        exc = AppException(code="CUSTOM", status_code=418, message="teapot", detail={"x": 1})
        assert exc.code == "CUSTOM"
        assert exc.status_code == 418
        assert exc.message == "teapot"
        assert exc.detail == {"x": 1}

    def test_str_representation(self):
        from src.core.exceptions import AppException

        exc = AppException(code="TEST_ERR", message="test error")
        assert str(exc) == "Error TEST_ERR: test error"

    def test_is_exception(self):
        from src.core.exceptions import AppException

        exc = AppException()
        assert isinstance(exc, Exception)


class TestNotFound:
    def test_defaults(self):
        from src.core.exceptions import NotFoundException

        exc = NotFoundException()
        assert exc.code == "NOT_FOUND"
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.message == "Resource not found"

    def test_custom_message(self):
        from src.core.exceptions import NotFoundException

        exc = NotFoundException(message="Order not found", detail={"id": 42})
        assert exc.message == "Order not found"
        assert exc.detail == {"id": 42}


class TestValidation:
    def test_defaults(self):
        from src.core.exceptions import ValidationException

        exc = ValidationException()
        assert exc.code == "VALIDATION_ERROR"
        assert exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_custom_message(self):
        from src.core.exceptions import ValidationException

        exc = ValidationException(message="Invalid email")
        assert exc.message == "Invalid email"


class TestAuth:
    def test_defaults(self):
        from src.core.exceptions import AuthException

        exc = AuthException()
        assert exc.code == "AUTH_FAILED"
        assert exc.status_code == status.HTTP_401_UNAUTHORIZED

    def test_custom_message(self):
        from src.core.exceptions import AuthException

        exc = AuthException(message="Token expired")
        assert exc.message == "Token expired"


class TestPermission:
    def test_defaults(self):
        from src.core.exceptions import PermissionDeniedException

        exc = PermissionDeniedException()
        assert exc.code == "PERMISSION_DENIED"
        assert exc.status_code == status.HTTP_403_FORBIDDEN

    def test_custom_message(self):
        from src.core.exceptions import PermissionDeniedException

        exc = PermissionDeniedException(message="Admin only")
        assert exc.message == "Admin only"


class TestRateLimit:
    def test_defaults(self):
        from src.core.exceptions import RateLimitException

        exc = RateLimitException()
        assert exc.code == "RATE_LIMIT_EXCEEDED"
        assert exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_custom_message(self):
        from src.core.exceptions import RateLimitException

        exc = RateLimitException(message="Slow down")
        assert exc.message == "Slow down"
