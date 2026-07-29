"""Shopify Webhook → OMS order bridge.

Receives Shopify order webhooks (``orders/create``, ``orders/fulfilled``)
and translates them into internal ``Order`` + outbox events.
"""
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

from src.models.erp_connector import ERPMessage, MessageType

logger = logging.getLogger(__name__)


def verify_webhook(body: bytes, hmac_header: str, secret: str) -> bool:
    """Verify Shopify HMAC-SHA256 webhook signature."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, hmac_header)


def parse_order_create(payload: dict) -> ERPMessage:
    """Convert a Shopify ``orders/create`` payload into an internal order message.

    Fields mapped:
        - Shopify ``id`` → ``order_id``
        - ``note`` → internal ``notes``
        - ``line_items`` → ``items``
        - ``customer.email`` → ``customer_email``
        - ``shipping_address`` → ``shipping``
        - ``total_price`` → ``total_amount``
    """
    items = []
    for line in payload.get("line_items", []):
        items.append({
            "sku": line.get("sku", ""),
            "product_name": line.get("title", ""),
            "quantity": line.get("quantity", 1),
            "unit_price": str(line.get("price", "0")),
            "gtin": line.get("barcode", ""),
        })

    note = payload.get("note") or ""
    tags = payload.get("tags") or ""

    return ERPMessage(
        msg_type=MessageType.ORDERS,
        sender_id="shopify",
        receiver_id="oms",
        created_at=datetime.now(UTC),
        payload={
            "source": "shopify",
            "shopify_order_id": str(payload.get("id", "")),
            "order_number": payload.get("order_number", 0),
            "customer_email": payload.get("email", ""),
            "customer_name": payload.get("customer", {}).get("first_name", ""),
            "shipping_address": payload.get("shipping_address", {}),
            "items": items,
            "total_amount": str(payload.get("total_price", "0")),
            "currency": payload.get("currency", "USD"),
            "notes": f"Shopify #{payload.get('order_number', '')}: {note}",
            "tags": tags,
            "fulfillment_status": payload.get("fulfillment_status", ""),
            "created_at": payload.get("created_at", ""),
        },
    )


def parse_fulfillment(payload: dict) -> ERPMessage:
    """Convert a Shopify ``orders/fulfilled`` event into a fulfillment message."""
    return ERPMessage(
        msg_type=MessageType.DESADV,
        sender_id="shopify",
        receiver_id="oms",
        created_at=datetime.now(UTC),
        payload={
            "source": "shopify",
            "shopify_order_id": str(payload.get("id", "")),
            "fulfillment_status": payload.get("fulfillment_status", "fulfilled"),
            "tracking_company": payload.get("fulfillments", [{}])[0].get("tracking_company", ""),
            "tracking_number": payload.get("fulfillments", [{}])[0].get("tracking_number", ""),
            "fulfilled_at": payload.get("fulfillments", [{}])[0].get("created_at", ""),
        },
    )


async def handle_shopify_webhook(
    topic: str,
    body: bytes,
    hmac_header: str,
    secret: str,
) -> ERPMessage | None:
    """Verify and parse a Shopify webhook. Returns ``None`` if signature is invalid."""
    if not verify_webhook(body, hmac_header, secret):
        logger.warning("Shopify webhook HMAC verification failed")
        return None

    payload = json.loads(body)

    if topic == "orders/create":
        return parse_order_create(payload)
    elif topic == "orders/fulfilled":
        return parse_fulfillment(payload)
    else:
        logger.info("Unhandled Shopify webhook topic: %s", topic)
        return None
