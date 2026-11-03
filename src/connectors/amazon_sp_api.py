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
from decimal import Decimal, InvalidOperation

from src.core.exceptions import ValidationException
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


def _as_quantity(value: object, *, line: int) -> int:
    """How many of a line Amazon says was ordered, read out of Amazon's own spelling.

    ``int(line.get("QuantityOrdered", 1))`` accepted a negative number, and died
    on the string SP-API uses for bundled listings ("2 items") — a 500 on the
    import endpoint for a payload that was merely unusual.
    """
    try:
        quantity = int(str(value).strip())
    except (ValueError, TypeError):
        raise ValidationException(
            message=f"OrderItems[{line}].QuantityOrdered must be a whole number, got {value!r}",
            detail={"QuantityOrdered": str(value)},
        ) from None
    if quantity < 1:
        raise ValidationException(
            message=(f"OrderItems[{line}].QuantityOrdered {quantity} is not an order quantity — "
                     "Amazon orders at least one unit"),
            detail={"QuantityOrdered": str(value)},
        )
    return quantity


def _as_amount(value: object, *, field: str) -> str:
    """A money amount in Amazon's spelling, as the Decimal the OMS order needs.

    ``OrderTotal``/``ItemPrice`` arrive as an object, as a bare string, or as
    null (SP-API omits them for unshipped and cancelled orders).  ``.get`` on
    the null answered AttributeError and a 500; the string reached
    ``Decimal(str(...))`` in ``create_order`` and died there.
    """
    if value is None:
        return "0"
    if isinstance(value, dict):
        raw = value.get("Amount", "0")
    else:
        raw = value
    text = str(raw).strip() or "0"
    try:
        Decimal(text)
    except InvalidOperation:
        raise ValidationException(
            message=f"{field} must be a money amount, got {raw!r}",
            detail={field: text},
        ) from None
    return text


def _as_object(value: object) -> dict:
    """Amazon omits an address, a price, a total — as null, not as a missing key."""
    return value if isinstance(value, dict) else {}


def parse_amazon_order(order_data: dict) -> ERPMessage:
    """Convert an Amazon Orders API response into an internal order message.

    Maps these Amazon fields:
        - ``AmazonOrderId`` → ``amazon_order_id``
        - ``OrderStatus`` → ``status``
        - ``OrderTotal.Amount`` → ``total_amount``
        - ``BuyerEmail`` → ``customer_email``
        - ``ShippingAddress`` → ``shipping``
        - ``OrderItems`` → ``items``

    The guards here are the difference between an import that answers and one
    that crashes.  ``AmazonOrderId`` was never checked, so a payload naming no
    order produced an OMS order with an empty ``amazon_order_id`` — the number
    the tracking upload, the reconciliation and the Amazon Seller Central
    support ticket are all answered with.  ``OrderItems`` was never checked
    either: an order with no lines imported as a 201, and an order with no
    lines cannot be picked, shipped, invoiced, or cancelled.
    """
    amazon_order_id = str(order_data.get("AmazonOrderId") or "").strip()
    if not amazon_order_id:
        raise ValidationException(
            message="AmazonOrderId is required — an imported order has to say which Amazon order it is",
            detail={"AmazonOrderId": None},
        )
    shipping = _as_object(order_data.get("ShippingAddress"))
    items_raw = order_data.get("OrderItems") or []
    if not isinstance(items_raw, list):
        raise ValidationException(
            message=f"OrderItems must be a list of order lines, got {type(items_raw).__name__}",
            detail={"OrderItems": str(items_raw)},
        )
    if not items_raw:
        raise ValidationException(
            message="OrderItems is required — an order with no lines cannot be picked, shipped, or invoiced",
            detail={"OrderItems": []},
        )
    items = []
    for index, line in enumerate(items_raw):
        line = _as_object(line)
        # ``SellerSKU`` names the seller's own listing; an FBA line has no seller
        # SKU at all and names the ASIN instead.  Reading only SellerSKU left
        # every FBA line with an empty sku, which the warehouse cannot pick.
        sku = str(line.get("SellerSKU") or line.get("SKU") or line.get("ASIN") or "").strip()
        # ASIN is not a GTIN — it is Amazon's own alphanumeric id.  It was being
        # written into ``gtin``, where the scan-gun flows (/barcode/validate, the
        # PDA 扫码) read it as an EAN and reject it.
        gtin = str(line.get("gtin") or line.get("EAN") or line.get("barcode") or "").strip()
        if not sku and not gtin:
            raise ValidationException(
                message=(f"OrderItems[{index}] names no product — no SellerSKU, SKU, ASIN, or barcode. "
                         "An order line the warehouse cannot identify cannot be picked"),
                detail={"OrderItems": index},
            )
        items.append({
            "sku": sku,
            "product_name": str(line.get("Title") or ""),
            "quantity": _as_quantity(line.get("QuantityOrdered", 1), line=index),
            "unit_price": _as_amount(line.get("ItemPrice"), field=f"OrderItems[{index}].ItemPrice"),
            "gtin": gtin,
        })

    total = _as_object(order_data.get("OrderTotal"))
    return ERPMessage(
        msg_type=MessageType.ORDINR,
        sender_id="amazon",
        receiver_id="oms",
        created_at=datetime.now(UTC),
        payload={
            "source": "amazon",
            "amazon_order_id": amazon_order_id,
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
            "total_amount": _as_amount(total.get("Amount"), field="OrderTotal.Amount"),
            "currency": str(total.get("CurrencyCode") or "USD"),
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

def _not_implemented(action: str, *, needs: str, **identifiers: object) -> dict:
    """The answer an unimplemented SP-API action gives: it did not happen.

    Each of these used to return a canned success — ``"status": "Unshipped"`` for
    a poll that polled nothing, ``"uploaded"`` for an upload that never left the
    process, ``"synced"`` for inventory Amazon never heard about.  A caller
    cannot tell "the tracking number is on Amazon" from "the tracking number is
    not on Amazon" out of that, and the operator acting on it schedules a
    reconciliation against a shipment Amazon has never seen.  An unimplemented
    action now says so, in a key the caller can branch on.
    """
    return {
        "implemented": False,
        "status": "not_implemented",
        "action": action,
        "reason": f"{action} needs a real SP-API call ({needs}) and SP-API credentials",
        **identifiers,
    }


# ── Order Status Polling & Sync ─────────────────────────────────────────────

def poll_order_status(
    marketplace_id: str,
    amazon_order_id: str,
) -> dict:
    """Poll Amazon Orders API for the latest order status. **Not implemented.**

    Needs ``GET /orders/v0/orders/{orderId}`` with an SP-API access token;
    ``settings.amazon_sp_api_*`` carries the credentials.  Until then the answer
    is ``status: "not_implemented"`` — not a status invented for the order.
    """
    return _not_implemented(
        "poll_order_status", needs="GET /orders/v0/orders/{orderId}",
        marketplace_id=marketplace_id, amazon_order_id=amazon_order_id,
    )


def sync_order_status(
    marketplace_id: str,
    amazon_order_id: str,
    internal_order: dict | None = None,
) -> dict:
    """Sync Amazon order status back to the internal order. **Not implemented.**

    Needs ``poll_order_status`` above plus the OMS status write it feeds.
    """
    return _not_implemented(
        "sync_order_status", needs="poll_order_status + oms.service.update_order_status",
        marketplace_id=marketplace_id, amazon_order_id=amazon_order_id,
        internal_updated=False,
    )


# ── Tracking Upload & FBA Shipping ───────────────────────────────────────────

def upload_tracking_to_amazon(
    marketplace_id: str,
    amazon_order_id: str,
    carrier_code: str,
    tracking_number: str,
) -> dict:
    """Upload a tracking number to Amazon. **Not implemented.**

    Needs ``PUT /orders/v0/orders/{orderId}/tracking``.  The 发货交接 the
    console records (``POST /connectors/amazon/tracking``) is stored locally and
    reports ``sync_status: "not_configured"`` for exactly this reason — the
    handover is not on Amazon.
    """
    return _not_implemented(
        "upload_tracking_to_amazon", needs="PUT /orders/v0/orders/{orderId}/tracking",
        marketplace_id=marketplace_id, amazon_order_id=amazon_order_id,
        carrier_code=carrier_code, tracking_number=tracking_number,
    )


def mark_fba_shipped(
    marketplace_id: str,
    amazon_order_id: str,
) -> dict:
    """Mark an order as shipped via FBA. **Not implemented.**

    Needs ``POST /fbaInbound`` (ShipmentPost) with the FBA shipment id.
    """
    return _not_implemented(
        "mark_fba_shipped", needs="POST /fbaInbound ShipmentPost",
        marketplace_id=marketplace_id, amazon_order_id=amazon_order_id,
    )


# ── Inventory Sync ───────────────────────────────────────────────────────────

def sync_inventory_to_amazon(
    marketplace_id: str,
    sku: str,
    quantity: int,
) -> dict:
    """Push inventory levels to Amazon. **Not implemented.**

    Needs ``POST /fp/inventory/v1/inventory``; nothing in the warehouse calls
    it, so Amazon has never been told about a stock change here.
    """
    return _not_implemented(
        "sync_inventory_to_amazon", needs="POST /fp/inventory/v1/inventory",
        marketplace_id=marketplace_id, sku=sku, quantity=quantity,
    )
