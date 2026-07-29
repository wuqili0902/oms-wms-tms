from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.connectors.router import router
from src.core.database import get_db

API = "/api/v1"


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router, prefix=API)
    return app


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def client(app, mock_db):
    async def _get_db():
        return mock_db
    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    c = AsyncClient(transport=transport, base_url="http://test")
    yield c
    app.dependency_overrides.clear()


class TestShopifyWebhook:
    async def test_invalid_signature_returns_401(self, client):
        with patch("src.connectors.router.verify_webhook", return_value=False):
            resp = await client.post(
                f"{API}/connectors/shopify/webhook",
                content=b"{}",
                headers={"X-Shopify-Topic": "orders/create", "X-Shopify-Hmac-Sha256": "bad"},
            )
        assert resp.status_code == 401

    async def test_skipped_topic(self, client):
        with (
            patch("src.connectors.router.verify_webhook", return_value=True),
            patch("src.connectors.shopify_webhook.handle_shopify_webhook", return_value=None),
        ):
            resp = await client.post(
                f"{API}/connectors/shopify/webhook",
                content=b"{}",
                headers={"X-Shopify-Topic": "orders/create", "X-Shopify-Hmac-Sha256": "sig"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    async def test_imports_order(self, client):
        fake_msg = MagicMock()
        fake_msg.msg_type.value = "ORDERS"
        with (
            patch("src.connectors.router.verify_webhook", return_value=True),
            patch("src.connectors.shopify_webhook.handle_shopify_webhook", return_value=fake_msg),
            patch("src.connectors.service.import_erp_order", new_callable=AsyncMock) as mock_import,
        ):
            mock_import.return_value = {"id": "ord-abc"}
            resp = await client.post(
                f"{API}/connectors/shopify/webhook",
                content=b"{}",
                headers={"X-Shopify-Topic": "orders/create", "X-Shopify-Hmac-Sha256": "sig"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "imported"
        assert resp.json()["order_id"] == "ord-abc"


class TestImportAmazonOrder:
    async def test_imports_order(self, client):
        with patch("src.connectors.service.import_erp_order", new_callable=AsyncMock) as mock_import:
            mock_import.return_value = {"id": "amz-ord-1"}
            resp = await client.post(f"{API}/connectors/amazon/orders", json={
                "AmazonOrderId": "AMZ-001", "OrderStatus": "Unshipped",
                "BuyerEmail": "b@t.com", "OrderTotal": {"Amount": "50", "CurrencyCode": "USD"},
                "ShippingAddress": {"City": "Seattle"},
                "OrderItems": [{"SellerSKU": "SKU-1", "Title": "P1", "QuantityOrdered": 1}],
            })
        assert resp.status_code == 201
        assert resp.json()["status"] == "imported"
        assert resp.json()["amazon_order_id"] == "AMZ-001"


class TestAmazonTracking:
    async def test_receives_tracking(self, client):
        resp = await client.post(f"{API}/connectors/amazon/tracking", json={
            "amazon_order_id": "AMZ-001", "carrier_code": "SF",
            "tracking_number": "SF123456",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"
