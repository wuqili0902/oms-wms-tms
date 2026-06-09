"""Unified API response format wrapper.

This module provides classes and functions to ensure consistent JSON response structure
across all API endpoints. This helps with client-side parsing and error handling.
"""

from typing import Any

from fastapi.responses import JSONResponse


class ApiResponse:
    """Wrapper for successful API responses with a consistent format.

    All successful responses follow this structure:
    {
        "success": true,
        "data": <response_data>,
        "message": "<optional_message>",
        "meta": <pagination_or_metadata>
    }

    Attributes:
        success (bool): Always True for ApiResponse instances
        data (Any): The actual response payload
        message (Optional[str]): Optional human-readable message
        meta (Optional[Dict]): Optional metadata (pagination, etc.)
    """

    def __init__(
        self,
        data: Any = None,
        message: str | None = None,
        meta: dict | None = None,
    ) -> None:
        self.success = True
        self.data = data
        self.message = message
        self.meta = meta

    def to_dict(self) -> dict:
        """Convert the response to a dictionary for JSON serialization."""
        result = {
            "success": self.success,
            "data": self.data,
        }
        if self.message is not None:
            result["message"] = self.message
        if self.meta is not None:
            result["meta"] = self.meta
        return result

    def to_response(self) -> JSONResponse:
        """Convert the response to a FastAPI JSONResponse."""
        return JSONResponse(content=self.to_dict())


def success_response(
    data: Any = None,
    message: str | None = None,
    meta: dict | None = None,
) -> ApiResponse:
    """Create a successful API response.

    Args:
        data (Any): The actual response payload
        message (Optional[str]): Optional human-readable message
        meta (Optional[Dict]): Optional metadata (pagination, etc.)

    Returns:
        ApiResponse: A wrapped successful response object
    """
    return ApiResponse(data=data, message=message, meta=meta)


def error_response(
    status_code: int = 400,
    code: str = "ERROR",
    message: str = "An error occurred",
    errors: list[dict] | None = None,
) -> JSONResponse:
    """Create an error API response with a consistent format.

    All error responses follow this structure:
    {
        "success": false,
        "error": {
            "code": "<error_code>",
            "message": "<error_message>"
        },
        "errors": <optional_validation_errors>
    }

    Args:
        status_code (int): HTTP status code for the response
        code (str): Error code identifier
        message (str): Human-readable error message
        errors (Optional[List[Dict]]): Optional list of validation errors or details

    Returns:
        JSONResponse: A FastAPI JSONResponse with the error structure
    """
    result = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if errors is not None:
        result["errors"] = errors

    return JSONResponse(
        content=result,
        status_code=status_code,
    )


def paginated_response(
    data: list[Any],
    total_count: int,
    page: int = 1,
    per_page: int = 20,
) -> ApiResponse:
    """Create a paginated API response.

    Args:
        data (List[Any]): The current page of results
        total_count (int): Total number of items across all pages
        page (int): Current page number
        per_page (int): Number of items per page

    Returns:
        ApiResponse: A wrapped paginated response with pagination metadata
    """
    meta = {
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "total_pages": (total_count + per_page - 1) // per_page,
            "has_next": page * per_page < total_count,
            "has_prev": page > 1,
        }
    }

    return ApiResponse(data=data, meta=meta)


def list_response(
    data: list[Any],
    message: str | None = None,
) -> ApiResponse:
    """Create a response for listing resources.

    Args:
        data (List[Any]): The list of items to return
        message (Optional[str]): Optional success message

    Returns:
        ApiResponse: A wrapped successful response containing the list
    """
    return ApiResponse(data=data, message=message)


def detail_response(
    data: Any,
    message: str | None = None,
) -> ApiResponse:
    """Create a response for a single resource detail.

    Args:
        data (Any): The detailed resource object to return
        message (Optional[str]): Optional success message

    Returns:
        ApiResponse: A wrapped successful response containing the detail
    """
    return ApiResponse(data=data, message=message)


def delete_response(
    message: str = "Resource deleted successfully",
) -> ApiResponse:
    """Create a response for deletion operations.

    Args:
        message (str): Success message to include in the response

    Returns:
        ApiResponse: A wrapped successful response with a confirmation message
    """
    return ApiResponse(data=None, message=message)


def create_response(
    data: Any,
    message: str | None = None,
) -> ApiResponse:
    """Create a response for creation operations.

    Args:
        data (Any): The newly created resource object to return
        message (Optional[str]): Optional success message

    Returns:
        ApiResponse: A wrapped successful response containing the new resource
    """
    return ApiResponse(data=data, message=message)


def update_response(
    data: Any,
    message: str | None = None,
) -> ApiResponse:
    """Create a response for update operations.

    Args:
        data (Any): The updated resource object to return
        message (Optional[str]): Optional success message

    Returns:
        ApiResponse: A wrapped successful response containing the updated resource
    """
    return ApiResponse(data=data, message=message)


def validate_error_response(
    errors: list[dict],
    status_code: int = 422,
) -> JSONResponse:
    """Create a validation error response.

    Args:
        errors (List[Dict]): List of validation errors with 'field', 'message' keys
        status_code (int): HTTP status code for the response

    Returns:
        JSONResponse: A FastAPI JSONResponse with validation error structure
    """
    return error_response(
        status_code=status_code,
        code="VALIDATION_ERROR",
        message="Validation failed",
        errors=errors,
    )


def not_found_response(message: str = "Resource not found") -> JSONResponse:
    """Create a 404 Not Found response.

    Args:
        message (str): Custom error message

    Returns:
        JSONResponse: A FastAPI JSONResponse with 404 status code
    """
    return error_response(
        status_code=404,
        code="NOT_FOUND",
        message=message,
    )


def unauthorized_response(message: str = "Authentication required") -> JSONResponse:
    """Create a 401 Unauthorized response.

    Args:
        message (str): Custom error message

    Returns:
        JSONResponse: A FastAPI JSONResponse with 401 status code
    """
    return error_response(
        status_code=401,
        code="UNAUTHORIZED",
        message=message,
    )


def forbidden_response(message: str = "Permission denied") -> JSONResponse:
    """Create a 403 Forbidden response.

    Args:
        message (str): Custom error message

    Returns:
        JSONResponse: A FastAPI JSONResponse with 403 status code
    """
    return error_response(
        status_code=403,
        code="FORBIDDEN",
        message=message,
    )


def rate_limit_exceeded_response() -> JSONResponse:
    """Create a 429 Too Many Requests response.

    Returns:
        JSONResponse: A FastAPI JSONResponse with 429 status code and rate limit headers
    """
    return error_response(
        status_code=429,
        code="RATE_LIMIT_EXCEEDED",
        message="Rate limit exceeded",
    )


def server_error_response(message: str = "Internal server error") -> JSONResponse:
    """Create a 500 Internal Server Error response.

    Args:
        message (str): Custom error message

    Returns:
        JSONResponse: A FastAPI JSONResponse with 500 status code
    """
    return error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message=message,
    )


def bad_request_response(message: str = "Bad request") -> JSONResponse:
    """Create a 400 Bad Request response.

    Args:
        message (str): Custom error message

    Returns:
        JSONResponse: A FastAPI JSONResponse with 400 status code
    """
    return error_response(
        status_code=400,
        code="BAD_REQUEST",
        message=message,
    )


def method_not_allowed_response(message: str = "Method not allowed") -> JSONResponse:
    """Create a 405 Method Not Allowed response.

    Args:
        message (str): Custom error message

    Returns:
        JSONResponse: A FastAPI JSONResponse with 405 status code
    """
    return error_response(
        status_code=405,
        code="METHOD_NOT_ALLOWED",
        message=message,
    )


def not_implemented_response(message: str = "Not implemented") -> JSONResponse:
    """Create a 501 Not Implemented response.

    Args:
        message (str): Custom error message

    Returns:
        JSONResponse: A FastAPI JSONResponse with 501 status code
    """
    return error_response(
        status_code=501,
        code="NOT_IMPLEMENTED",
        message=message,
    )


def conflict_response(message: str = "Resource already exists") -> JSONResponse:
    """Create a 409 Conflict response.

    Args:
        message (str): Custom error message

    Returns:
        JSONResponse: A FastAPI JSONResponse with 409 status code
    """
    return error_response(
        status_code=409,
        code="CONFLICT",
        message=message,
    )


def bad_gateway_response(message: str = "Bad gateway request") -> JSONResponse:
    """Create a 502 Bad Gateway response.

    Args:
        message (str): Custom error message

    Returns:
        JSONResponse: A FastAPI JSONResponse with 502 status code
    """
    return error_response(
        status_code=502,
        code="BAD_GATEWAY",
        message=message,
    )


def service_unavailable_response(message: str = "Service temporarily unavailable") -> JSONResponse:
    """Create a 503 Service Unavailable response.

    Args:
        message (str): Custom error message

    Returns:
        JSONResponse: A FastAPI JSONResponse with 503 status code
    """
    return error_response(
        status_code=503,
        code="SERVICE_UNAVAILABLE",
        message=message,
    )


def internal_error_response(message: str = "Internal server error") -> JSONResponse:
    """Create a 500 Internal Server Error response.

    Args:
        message (str): Custom error message

    Returns:
        JSONResponse: A FastAPI JSONResponse with 500 status code
    """
    return error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message=message,
    )


def unknown_error_response(message: str = "An unexpected error occurred") -> JSONResponse:
    """Create a generic error response for unhandled exceptions.

    Args:
        message (str): Custom error message

    Returns:
        JSONResponse: A FastAPI JSONResponse with 500 status code and unknown error code
    """
    return error_response(
        status_code=500,
        code="UNKNOWN_ERROR",
        message=message,
    )


def health_check_response() -> ApiResponse:
    """Create a standardized health check response.

    Returns:
        ApiResponse: A wrapped successful response with health status information
    """
    return success_response(
        data={
            "status": "ok",
            "service": "oms-wms-tms",
        },
        message="Service is healthy",
    )


def readiness_check_response() -> ApiResponse:
    """Create a standardized readiness check response.

    Returns:
        ApiResponse: A wrapped successful response with readiness status information
    """
    return success_response(
        data={
            "status": "ready",
            "service": "oms-wms-tms",
        },
        message="Service is ready to accept requests",
    )
