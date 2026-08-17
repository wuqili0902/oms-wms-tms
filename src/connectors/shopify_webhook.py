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
        if not isinstance(line, dict):
            continue
        items.append({
            "sku": str(line.get("sku", "")),
            "product_name": str(line.get("title", "")),
            "quantity": line.get("quantity", 1),
            "unit_price": str(line.get("price", "0")),
            "gtin": str(line.get("barcode", "")),
        })

    note = payload.get("note") or ""
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    return ERPMessage(
        msg_type=MessageType.ORDERS,
        sender_id="shopify",
        receiver_id="oms",
        created_at=datetime.now(UTC),
        payload={
            "source": "shopify",
            "shopify_order_id": str(payload.get("id", "")),
            "order_number": int(payload.get("order_number", 0) or 0),
            "customer_email": str(payload.get("email", "") or ""),
            "customer_name": "",
            "shipping_address": payload.get("shipping_address") or {},
            "items": items,
            "total_amount": str(payload.get("total_price", "0")),
            "currency": payload.get("currency", "USD"),
            "notes": (
                f"Shopify #{payload.get('order_number', '')}: {note}" if note
                else f"Shopify #{payload.get('order_number', '')}"
            ),
            "tags": tags,
            "fulfillment_status": payload.get("fulfillment_status", ""),
            "created_at": str(payload.get("created_at", "")),
        },
    )


def parse_fulfillment(payload: dict) -> ERPMessage:
    """Convert a Shopify ``orders/fulfilled`` event into a fulfillment message."""
    first = (payload.get("fulfillments") or [{}])[0] if isinstance(payload.get("fulfillments"), list) else {}
    return ERPMessage(
        msg_type=MessageType.DESADV,
        sender_id="shopify",
        receiver_id="oms",
        created_at=datetime.now(UTC),
        payload={
            "source": "shopify",
            "shopify_order_id": str(payload.get("id", "")),
            "fulfillment_status": "fulfilled",
            "tracking_company": str(first.get("tracking_company") or ""),
            "tracking_number": str(first.get("tracking_number") or ""),
            "fulfilled_at": str(first.get("created_at") or ""),
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

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("Shopify webhook JSON parse error (%s): %s", topic, exc)
        return None

    if not isinstance(payload, dict):
        logger.error("Shopify webhook payload is not a JSON object for topic: %s", topic)
        return None

    try:
        if topic == "orders/create":
            return parse_order_create(payload)
        elif topic == "orders/fulfilled":
            return parse_fulfillment(payload)
        else:
            logger.info("Unhandled Shopify webhook topic: %s", topic)
            return None
    except Exception as exc:
        logger.error("Shopify webhook handler error for topic '%s': %s", topic, exc)
        return None
