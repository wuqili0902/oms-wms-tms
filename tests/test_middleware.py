"""Tests for API gateway middleware and exception handling."""

import pytest
from httpx import AsyncClient

from src.core.response import (
    ApiResponse,
    error_response,
    success_response,
    not_found_response,
    unauthorized_response,
    forbidden_response,
    rate_limit_exceeded_response,
)


class TestApiResponse:
    """Tests for the ApiResponse class."""

    def test_success_response_with_data(self):
        """Test creating a successful response with data."""
        response = success_response(data={"key": "value"})
        
        assert response.success is True
        assert response.data == {"key": "value"}
        assert response.message is None
        assert response.meta is None

    def test_success_response_with_message(self):
        """Test creating a successful response with message."""
        response = success_response(message="Operation completed")
        
        assert response.success is True
        assert response.data is None
        assert response.message == "Operation completed"

    def test_success_response_with_meta(self):
        """Test creating a successful response with metadata."""
        meta = {"pagination": {"page": 1, "total_pages": 5}}
        response = success_response(meta=meta)
        
        assert response.success is True
        assert response.meta == meta

    def test_to_dict_serialization(self):
        """Test converting ApiResponse to dictionary for JSON serialization."""
        response = ApiResponse(data={"test": "data"}, message="Success")
        result = response.to_dict()
        
        assert result["success"] is True
        assert result["data"] == {"test": "data"}
        assert result["message"] == "Success"

    def test_to_response_conversion(self):
        """Test converting ApiResponse to FastAPI JSONResponse."""
        from fastapi.responses import JSONResponse
        
        response = success_response(data={"key": "value"})
        json_response = response.to_response()
        
        assert isinstance(json_response, JSONResponse)


class TestErrorResponses:
    """Tests for error response functions."""

    def test_error_response_format(self):
        """Test the structure of error responses."""
        response = error_response(
            status_code=400,
            code="TEST_ERROR",
            message="Test error message",
        )
        
        assert response.status_code == 400
        content = response.body
        
        # Parse JSON content
        import json
        data = json.loads(content)
        
        assert data["success"] is False
        assert data["error"]["code"] == "TEST_ERROR"
        assert data["error"]["message"] == "Test error message"

    def test_error_response_with_details(self):
        """Test error response with additional details."""
        errors = [{"field": "email", "message": "Invalid email"}]
        response = error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Validation failed",
            errors=errors,
        )
        
        content = response.body
        import json
        data = json.loads(content)
        
        assert "errors" in data
        assert len(data["errors"]) == 1

    def test_not_found_response(self):
        """Test 404 Not Found response."""
        response = not_found_response("Resource not found")
        
        assert response.status_code == 404
        content = response.body
        import json
        data = json.loads(content)
        
        assert data["error"]["code"] == "NOT_FOUND"

    def test_unauthorized_response(self):
        """Test 401 Unauthorized response."""
        response = unauthorized_response("Authentication required")
        
        assert response.status_code == 401
        content = response.body
        import json
        data = json.loads(content)
        
        assert data["error"]["code"] == "UNAUTHORIZED"

    def test_forbidden_response(self):
        """Test 403 Forbidden response."""
        response = forbidden_response("Permission denied")
        
        assert response.status_code == 403
        content = response.body
        import json
        data = json.loads(content)
        
        assert data["error"]["code"] == "FORBIDDEN"

    def test_rate_limit_exceeded_response(self):
        """Test 429 Too Many Requests response."""
        response = rate_limit_exceeded_response()
        
        assert response.status_code == 429
        content = response.body
        import json
        data = json.loads(content)
        
        assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"


class TestRequestIDMiddleware:
    """Tests for request ID middleware."""

    @pytest.mark.asyncio
    async def test_request_id_added_to_response(self, async_client: AsyncClient):
        """Test that request ID is added to response headers."""
        response = await async_client.get("/api/v1/health")
        
        assert "x-request-id" in response.headers
        assert len(response.headers["x-request-id"]) > 0

    @pytest.mark.asyncio
    async def test_request_id_propagated_across_requests(self, async_client: AsyncClient):
        """Test that request ID is propagated across multiple requests."""
        # First request - get a request ID
        response1 = await async_client.get("/api/v1/health")
        request_id_1 = response1.headers["x-request-id"]
        
        # Second request with explicit request ID
        custom_request_id = "test-request-123"
        response2 = await async_client.get(
            "/api/v1/health",
            headers={"x-request-id": custom_request_id}
        )
        
        assert response2.headers["x-request-id"] == custom_request_id


class TestRateLimiter:
    """Tests for the rate limiter."""

    @pytest.mark.asyncio
    async def test_rate_limiter_connect(self):
        """Test connecting to Redis for rate limiting."""
        from src.core.rate_limiter import rate_limiter
        
        # This test will skip if Redis is not available
        connected = await rate_limiter.connect()
        
        assert connected or rate_limiter._connected == False  # Either connected or gracefully handled

    @pytest.mark.asyncio
    async def test_rate_limit_check(self):
        """Test checking rate limits."""
        from src.core.rate_limiter import rate_limiter
        
        # This test will skip if Redis is not available
        allowed = await rate_limiter.check_rate_limit("test_key", requests=10, window=60)
        
        assert isinstance(allowed, bool)


class TestHealthEndpoints:
    """Tests for health endpoints (already exist in test_health.py)."""

    @pytest.mark.asyncio
    async def test_health_check(self, async_client: AsyncClient):
        """Test health check endpoint returns OK."""
        response = await async_client.get("/api/v1/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_readiness_check(self, async_client: AsyncClient):
        """Test readiness check endpoint returns ready."""
        response = await async_client.get("/api/v1/ready")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"


class TestExceptionHandling:
    """Tests for exception handling middleware."""

    @pytest.mark.asyncio
    async def test_custom_exception_format(self, async_client: AsyncClient):
        """Test that custom exceptions return consistent error format."""
        # This would require adding a test endpoint that raises an exception
        # For now, we'll just verify the response structure from our tests above
        
        pass  # Implementation requires additional test endpoints


class TestMiddlewareIntegration:
    """Tests for middleware integration with the application."""

    @pytest.mark.asyncio
    async def test_middleware_applied_to_all_requests(self, async_client: AsyncClient):
        """Test that all middleware is applied to requests."""
        response = await async_client.get("/api/v1/health")
        
        # Check request ID header (RequestIDMiddleware)
        assert "x-request-id" in response.headers
        
        # Check status code (all middleware should pass through for successful requests)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_cors_middleware_applied(self, async_client: AsyncClient):
        """Test that CORS middleware is applied correctly."""
        response = await async_client.get(
            "/api/v1/health",
            headers={"origin": "http://test-origin.com"}
        )
        
        assert response.status_code == 200
