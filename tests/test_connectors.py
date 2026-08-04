"""Tests for e-commerce connector parsing + router endpoints."""
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.amazon_sp_api import build_tracking_update, parse_amazon_order
from src.connectors.shopify_webhook import (
    handle_shopify_webhook,
    parse_fulfillment,
    parse_order_create,
    verify_webhook,
)


def test_verify_shopify_webhook():
    body = b'{"order": 123}'
    secret = "test-secret"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook(body, sig, secret)
    assert not verify_webhook(body, "invalid", secret)


def test_parse_shopify_order_create():
    payload = {
        "id": 12345,
        "order_number": 1001,
        "email": "test@example.com",
        "total_price": "99.99",
        "currency": "USD",
        "line_items": [{"sku": "ABC123", "title": "Widget", "quantity": 2, "price": "49.99"}],
        "shipping_address": {"city": "Shanghai", "country": "CN"},
    }
    msg = parse_order_create(payload)
    assert msg.msg_type.value == "ORDERS"
    assert msg.payload["source"] == "shopify"
    assert len(msg.payload["items"]) == 1
    assert msg.payload["items"][0]["sku"] == "ABC123"


@pytest.mark.asyncio
async def test_handle_shopify_webhook_order_create():
    body = json.dumps({"id": 1, "order_number": 101, "line_items": []}).encode()
    secret = "test-secret"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    msg = await handle_shopify_webhook("orders/create", body, sig, secret)
    assert msg is not None
    assert msg.msg_type.value == "ORDERS"
    assert msg.payload["shopify_order_id"] == "1"


@pytest.mark.asyncio
async def test_handle_shopify_webhook_fulfillment():
    body = json.dumps({"id": 2, "fulfillments": [{"tracking_company": "SF"}]}).encode()
    secret = "test-secret"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    msg = await handle_shopify_webhook("orders/fulfilled", body, sig, secret)
    assert msg is not None
    assert msg.msg_type.value == "DESADV"
    assert msg.payload["tracking_company"] == "SF"


@pytest.mark.asyncio
async def test_handle_shopify_webhook_unknown_topic():
    body = json.dumps({"id": 3}).encode()
    secret = "test-secret"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    msg = await handle_shopify_webhook("unknown/topic", body, sig, secret)
    assert msg is None


def test_parse_shopify_fulfillment():
    payload = {
        "id": 12345,
        "fulfillment_status": "fulfilled",
        "fulfillments": [
            {"tracking_company": "SF", "tracking_number": "SF123456", "created_at": "2026-01-01T00:00:00Z"},
        ],
    }
    msg = parse_fulfillment(payload)
    assert msg.msg_type.value == "DESADV"
    assert msg.payload["tracking_number"] == "SF123456"


@pytest.mark.asyncio
async def test_handle_shopify_webhook_invalid_sig():
    body = json.dumps({"id": 1}).encode()
    msg = await handle_shopify_webhook("orders/create", body, "bad-sig", "secret")
    assert msg is None


def test_parse_amazon_order():
    data = {
        "AmazonOrderId": "AMZ-001",
        "OrderStatus": "Unshipped",
        "BuyerEmail": "buyer@amazon.com",
        "BuyerName": "John",
        "OrderTotal": {"Amount": "150.00", "CurrencyCode": "USD"},
        "ShippingAddress": {"City": "Seattle", "CountryCode": "US"},
        "OrderItems": [{"SellerSKU": "SKU-1", "Title": "Product 1", "QuantityOrdered": 1}],
    }
    msg = parse_amazon_order(data)
    assert msg.payload["source"] == "amazon"
    assert msg.payload["amazon_order_id"] == "AMZ-001"
    assert len(msg.payload["items"]) == 1


def test_build_tracking_update():
    result = build_tracking_update("AMZ-001", "SF", "SF123456", "Shipped")
    assert result["amazon_order_id"] == "AMZ-001"
    assert result["tracking_number"] == "SF123456"


@pytest.mark.asyncio
async def test_amazon_import_endpoint(async_client):
    data = {
        "AmazonOrderId": "AMZ-TEST",
        "OrderStatus": "Unshipped",
        "BuyerEmail": "buyer@test.com",
        "OrderTotal": {"Amount": "50.00", "CurrencyCode": "USD"},
        "ShippingAddress": {"City": "TestCity"},
        "OrderItems": [{"SellerSKU": "T-SKU", "Title": "Test Item", "QuantityOrdered": 1}],
    }
    resp = await async_client.post("/api/v1/connectors/amazon/orders", json=data)
    assert resp.status_code in (201, 422)


@pytest.mark.asyncio
async def test_amazon_tracking_endpoint(async_client):
    data = {"amazon_order_id": "AMZ-001", "carrier_code": "SF", "tracking_number": "SF123456"}
    resp = await async_client.post("/api/v1/connectors/amazon/tracking", json=data)
    assert resp.status_code == 200
    assert resp.json()["status"] == "received"


# ── Shopify webhook ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shopify_webhook_skipped(async_client):
    """Valid webhook with no matching handler → skipped."""
    body = json.dumps({"id": 1}).encode()
    sig = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    with patch("src.connectors.router.verify_webhook", return_value=True), \
         patch("src.connectors.shopify_webhook.handle_shopify_webhook", return_value=None):
        resp = await async_client.post(
            "/api/v1/connectors/shopify/webhook",
            content=body,
            headers={"X-Shopify-Topic": "orders/create", "X-Shopify-Hmac-Sha256": sig},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"


@pytest.mark.asyncio
async def test_shopify_webhook_imported(async_client):
    """Valid webhook with matching handler → order imported."""
    body = json.dumps({"id": 1}).encode()
    sig = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    fake_msg = type("FakeMsg", (), {"msg_type": type("MT", (), {"value": "ORDERS"})()})()
    with patch("src.connectors.router.verify_webhook", return_value=True), \
         patch("src.connectors.shopify_webhook.handle_shopify_webhook", return_value=fake_msg), \
         patch("src.connectors.service.import_erp_order", new_callable=AsyncMock) as mock_import:
        mock_import.return_value = {"id": "order-abc"}
        resp = await async_client.post(
            "/api/v1/connectors/shopify/webhook",
            content=body,
            headers={"X-Shopify-Topic": "orders/fulfilled", "X-Shopify-Hmac-Sha256": sig},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "imported"
    assert resp.json()["order_id"] == "order-abc"


@pytest.mark.asyncio
async def test_shopify_webhook_invalid_signature(async_client):
    """Signature mismatch → 401."""
    with patch("src.connectors.router.verify_webhook", return_value=False):
        resp = await async_client.post(
            "/api/v1/connectors/shopify/webhook",
            content=b"{}",
            headers={"X-Shopify-Topic": "orders/create", "X-Shopify-Hmac-Sha256": "bad"},
        )
    assert resp.status_code == 401
