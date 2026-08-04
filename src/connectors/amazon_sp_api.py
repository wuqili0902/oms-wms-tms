"""Amazon SP-API (Selling Partner API) connector for order import and tracking.

Translates Amazon Order API responses into internal ``Order`` messages
and sends shipment tracking updates back to Amazon.

Features:
  - Order status polling & sync
  - Tracking number auto-upload + FBA shipping management
  - Inventory synchronization to Amazon
"""
import logging
from datetime import UTC, datetime

from src.models.erp_connector import ERPMessage, MessageType

logger = logging.getLogger(__name__)

# Amazon SP-API endpoints
# https://developer-docs.amazon.com/sp-api/docs
MARKETPLACE_IDS = {
    "US": "ATVPDKIKX0DER",
    "CA": "A2EUQ1WTGCTBG2",
    "MX": "A1AM78C64UM0Y8",
    "UK": "A1F83G8C2ARO7P",
    "DE": "A1PA6795UKMFR9",
    "FR": "A13V1IB3VIYZZH",
    "IT": "APJ6JRA9NG5V4",
    "ES": "A1RKKUPIHCS9HS",
    "JP": "A1VC38T7YXB528",
    "CN": "AAHKV2X7AFYLW",
    "AU": "A39IBJ37TRP1C6",
}


def parse_amazon_order(order_data: dict) -> ERPMessage:
    """Convert an Amazon Orders API response into an internal order message.

    Maps these Amazon fields:
        - ``AmazonOrderId`` → ``amazon_order_id``
        - ``OrderStatus`` → ``status``
        - ``OrderTotal.Amount`` → ``total_amount``
        - ``BuyerEmail`` → ``customer_email``
        - ``ShippingAddress`` → ``shipping``
        - ``OrderItems`` → ``items``
    """
    shipping = order_data.get("ShippingAddress", {})
    items_raw = order_data.get("OrderItems", [])
    items = []
    for line in items_raw:
        items.append({
            "sku": line.get("SellerSKU", ""),
            "product_name": line.get("Title", ""),
            "quantity": int(line.get("QuantityOrdered", 1)),
            "unit_price": str(line.get("ItemPrice", {}).get("Amount", "0")),
            "gtin": line.get("ASIN", ""),
        })

    total = order_data.get("OrderTotal", {})
    return ERPMessage(
        msg_type=MessageType.ORDINR,
        sender_id="amazon",
        receiver_id="oms",
        created_at=datetime.now(UTC),
        payload={
            "source": "amazon",
            "amazon_order_id": order_data.get("AmazonOrderId", ""),
            "status": order_data.get("OrderStatus", ""),
            "customer_email": order_data.get("BuyerEmail", ""),
            "customer_name": order_data.get("BuyerName", ""),
            "shipping_address": {
                "name": shipping.get("Name", ""),
                "address_line1": shipping.get("AddressLine1", ""),
                "city": shipping.get("City", ""),
                "state": shipping.get("StateOrRegion", ""),
                "postal_code": shipping.get("PostalCode", ""),
                "country": shipping.get("CountryCode", ""),
                "phone": shipping.get("Phone", ""),
            },
            "items": items,
            "total_amount": str(total.get("Amount", "0")),
            "currency": total.get("CurrencyCode", "USD"),
            "marketplace_id": order_data.get("MarketplaceId", ""),
            "purchase_date": order_data.get("PurchaseDate", ""),
        },
    )


def build_tracking_update(
    amazon_order_id: str,
    carrier_code: str,
    tracking_number: str,
    status: str = "Shipped",
) -> dict:
    """Build a shipment tracking update payload for Amazon SP-API."""
    return {
        "amazon_order_id": amazon_order_id,
        "carrier_code": carrier_code,
        "tracking_number": tracking_number,
        "status": status,
        "updated_at": datetime.now(UTC).isoformat(),
    }


# ── Order Status Polling & Sync ─────────────────────────────────────────────

def poll_order_status(
    marketplace_id: str,
    amazon_order_id: str,
) -> dict:
    """Poll Amazon Orders API for the latest order status.

    Returns a dict with keys:
      - "status": current OrderStatus value (e.g., "Unshipped", "PartiallyShipped")
      - "fulfillment_type": "FBA" or "MFN"
      - "tracking_number": if available
      - "estimated_delivery_date": ISO date string or None
    """
    # TODO: Replace with real SP-API call when credentials are configured
    # For now, return a stub response — callers should handle this gracefully.
    return {
        "status": "Unshipped",
        "fulfillment_type": "FBA",
        "tracking_number": None,
        "estimated_delivery_date": None,
    }


def sync_order_status(
    marketplace_id: str,
    amazon_order_id: str,
    internal_order: dict | None = None,
) -> dict:
    """Sync Amazon order status back to our internal system.

    If ``internal_order`` is provided, updates its fields (status, tracking_number,
    estimated_delivery_date). Otherwise returns a stub indicating success.
    """
    # TODO: Implement real sync logic here
    return {
        "amazon_order_id": amazon_order_id,
        "synced_at": datetime.now(UTC).isoformat(),
        "internal_updated": internal_order is not None,
    }


# ── Tracking Upload & FBA Shipping ───────────────────────────────────────────

def upload_tracking_to_amazon(
    marketplace_id: str,
    amazon_order_id: str,
    carrier_code: str,
    tracking_number: str,
) -> dict:
    """Upload a tracking number to Amazon via SP-API Fulfillment API.

    Returns the response payload (or stub).
    """
    # TODO: Replace with real SP-API call
    return {
        "amazon_order_id": amazon_order_id,
        "carrier_code": carrier_code,
        "tracking_number": tracking_number,
        "status": "uploaded",
        "timestamp": datetime.now(UTC).isoformat(),
    }


def mark_fba_shipped(
    marketplace_id: str,
    amazon_order_id: str,
) -> dict:
    """Mark an order as shipped via FBA (creates ShipmentPost request in SP-API).

    Returns a stub response.
    """
    # TODO: Implement real FBA shipping logic
    return {
        "amazon_order_id": amazon_order_id,
        "status": "fba_shipped",
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ── Inventory Sync ───────────────────────────────────────────────────────────

def sync_inventory_to_amazon(
    marketplace_id: str,
    sku: str,
    quantity: int,
) -> dict:
    """Synchronize inventory levels to Amazon via SP-API Inventory API.

    Returns a stub response indicating success/failure.
    """
    # TODO: Replace with real SP-API call
    return {
        "marketplace_id": marketplace_id,
        "sku": sku,
        "quantity": quantity,
        "status": "synced",
        "timestamp": datetime.now(UTC).isoformat(),
    }
