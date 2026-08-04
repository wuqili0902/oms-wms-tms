from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    """Test health check endpoint returns OK."""
    with patch("src.api.v1.health.check_db_health") as mock_check:
        mock_check.return_value = True
        response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "oms-wms-tms"


@pytest.mark.asyncio
async def test_readiness_check(async_client: AsyncClient):
    """Test readiness check endpoint returns ready."""
    with patch("src.api.v1.health.check_db_health") as mock_db:
        mock_db.return_value = True
        with patch("src.cache.redis_client.redis_health_check") as mock_redis:
            mock_redis.return_value = True
            response = await async_client.get("/api/v1/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"


@pytest.mark.asyncio
async def test_openapi_docs(async_client: AsyncClient):
    """Test that OpenAPI docs are accessible."""
    response = await async_client.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()
