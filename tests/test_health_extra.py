from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestHealth:
    async def test_health_ok(self, client):
        with patch("src.api.v1.health.check_db_health", return_value=True):
            resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["checks"]["database"] == "healthy"

    async def test_health_degraded(self, client):
        with patch("src.api.v1.health.check_db_health", return_value=False):
            resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["database"] == "unhealthy"

    async def test_health_has_service_info(self, client):
        with patch("src.api.v1.health.check_db_health", return_value=True):
            resp = await client.get("/health")
        data = resp.json()
        assert "service" in data
        assert "version" in data


class TestReadiness:
    async def test_ready(self, client):
        with (
            patch("src.api.v1.health.check_db_health", return_value=True),
            patch("src.cache.redis_client.redis_health_check", return_value=True),
        ):
            resp = await client.get("/api/v1/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["checks"]["database"] == "healthy"
        assert data["checks"]["redis"] == "healthy"

    async def test_degraded_when_db_down(self, client):
        with (
            patch("src.api.v1.health.check_db_health", return_value=False),
            patch("src.cache.redis_client.redis_health_check", return_value=True),
        ):
            resp = await client.get("/api/v1/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["database"] == "unhealthy"
        assert data["checks"]["redis"] == "healthy"

    async def test_degraded_when_redis_down(self, client):
        with (
            patch("src.api.v1.health.check_db_health", return_value=True),
            patch("src.cache.redis_client.redis_health_check", return_value=False),
        ):
            resp = await client.get("/api/v1/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["database"] == "healthy"
        assert data["checks"]["redis"] == "unavailable"

    async def test_degraded_when_redis_exception(self, client):
        with (
            patch("src.api.v1.health.check_db_health", return_value=True),
            patch("src.cache.redis_client.redis_health_check", side_effect=Exception("timeout")),
        ):
            resp = await client.get("/api/v1/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["redis"] == "unavailable"

    async def test_degraded_when_both_down(self, client):
        with (
            patch("src.api.v1.health.check_db_health", return_value=False),
            patch("src.cache.redis_client.redis_health_check", return_value=False),
        ):
            resp = await client.get("/api/v1/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
