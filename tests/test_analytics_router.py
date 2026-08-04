from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.main import app

API = "/api/v1/analytics"


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def client(mock_db):
    async def _get_db():
        return mock_db
    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    c = AsyncClient(transport=transport, base_url="http://test")
    yield c
    app.dependency_overrides.clear()


class TestDashboard:
    async def test_returns_dashboard(self, client):
        with (
            patch("src.analytics.router.get_dashboard_stats", new_callable=AsyncMock, return_value={"order_count": 10}),
            patch("src.analytics.router.get_order_trends", new_callable=AsyncMock, return_value=[]),
            patch("src.analytics.router.get_status_distribution", new_callable=AsyncMock, return_value=[]),
            patch("src.analytics.router.get_low_stock_items", new_callable=AsyncMock, return_value=[]),
            patch("src.analytics.router.get_recent_orders", new_callable=AsyncMock, return_value=[]),
        ):
            resp = await client.get(f"{API}/dashboard")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["stats"]["order_count"] == 10
        assert "generated_at" in data


class TestOrderTrends:
    async def test_returns_trends(self, client):
        with patch("src.analytics.router.get_order_trends", new_callable=AsyncMock) as mock_trends:
            mock_trends.return_value = [{"date": "2026-01-01", "count": 5}]
            resp = await client.get(f"{API}/order-trends?days=7")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["days"] == 7
        assert len(data["trends"]) == 1

    async def test_default_days(self, client):
        with patch("src.analytics.router.get_order_trends", new_callable=AsyncMock, return_value=[]):
            resp = await client.get(f"{API}/order-trends")
        assert resp.status_code == 200


class TestStatusDistribution:
    async def test_returns_distribution(self, client):
        with patch("src.analytics.router.get_status_distribution", new_callable=AsyncMock) as mock_dist:
            mock_dist.return_value = [{"status": "confirmed", "count": 5}]
            resp = await client.get(f"{API}/status-distribution")
        assert resp.status_code == 200
        assert resp.json()["data"][0]["status"] == "confirmed"


class TestLowStock:
    async def test_returns_low_stock(self, client):
        with patch("src.analytics.router.get_low_stock_items", new_callable=AsyncMock) as mock_ls:
            mock_ls.return_value = [{"sku": "ABC", "quantity": 2}]
            resp = await client.get(f"{API}/low-stock")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["count"] == 1
        assert data["items"][0]["sku"] == "ABC"

    async def test_empty_low_stock(self, client):
        with patch("src.analytics.router.get_low_stock_items", new_callable=AsyncMock, return_value=[]):
            resp = await client.get(f"{API}/low-stock")
        assert resp.status_code == 200
        assert resp.json()["data"]["count"] == 0
