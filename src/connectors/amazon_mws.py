"""Amazon SP-API (Selling Partner API) connector for order import and tracking.

Translates Amazon Order API responses into internal ``Order`` messages
and sends shipment tracking updates back to Amazon.
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
