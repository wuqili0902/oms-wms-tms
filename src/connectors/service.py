"""Connector service — translates ERPMessages into internal OMS orders."""
import logging
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ValidationException
from src.models.erp_connector import ERPMessage
from src.oms import service as oms_service

logger = logging.getLogger(__name__)


def _line_quantity(value: object, *, line: int) -> int:
    try:
        quantity = int(str(value).strip())
    except (ValueError, TypeError):
        raise ValidationException(
            message=f"items[{line}].quantity must be a whole number, got {value!r}",
            detail={"quantity": str(value)},
        ) from None
    if quantity < 1:
        raise ValidationException(
            message=(f"items[{line}].quantity {quantity} is not an order quantity — "
                     "an ordered line has at least one unit"),
            detail={"quantity": str(value)},
        )
    return quantity


def _line_price(value: object, *, line: int) -> str:
    text = str(value).strip() or "0"
    try:
        Decimal(text)
    except InvalidOperation:
        raise ValidationException(
            message=f"items[{line}].unit_price must be a money amount, got {value!r}",
            detail={"unit_price": text},
        ) from None
    return text


async def import_erp_order(db: AsyncSession, msg: ERPMessage) -> dict:
    """Convert an ERPMessage into an OMS order.

    Handles ``ORDERS`` and ``ORDINR`` message types by mapping
    the external order payload to the internal ``create_order`` schema.

    The checks here are the only checks an imported order gets.  ``create_order``
    is called directly — it never sees ``OrderCreate``, the schema the HTTP path
    enforces (items required, one unit minimum, a money amount), so an imported
    order used to bypass every one of them.  The 201 at the end of that path was
    an order nobody downstream can act on: no lines to pick, a line with no
    product on it, a quantity the picker is expected to read as a number.  The
    Amazon import, the Shopify webhook and the admin CSV path all land here.
    """
    payload = msg.payload

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValidationException(
            message=f"items must be a list of order lines, got {type(raw_items).__name__}",
            detail={"items": str(raw_items)},
        )
    if not raw_items:
        raise ValidationException(
            message=(f"{payload.get('source', 'the source system')} sent an order with no lines — "
                     "an order with nothing on it cannot be picked, shipped, or invoiced"),
            detail={"items": []},
        )

    items = []
    for index, line in enumerate(raw_items):
        if not isinstance(line, dict):
            raise ValidationException(
                message=f"items[{index}] must be an order line, got {type(line).__name__}",
                detail={"items": index},
            )
        sku = str(line.get("sku") or "").strip()
        gtin = str(line.get("gtin") or "").strip()
        if not sku and not gtin:
            raise ValidationException(
                message=(f"items[{index}] names no product — an order line needs a sku "
                         "or a gtin for the warehouse to pick"),
                detail={"items": index},
            )
        items.append({
            "sku": sku,
            "product_name": str(line.get("product_name") or ""),
            "quantity": _line_quantity(line.get("quantity", 1), line=index),
            "unit_price": _line_price(line.get("unit_price", "0"), line=index),
            "gtin": gtin,
        })

    # An order with no one to ship to is not a shippable order; the old default
    # of "unknown" filed it under a customer named "unknown", where it joins
    # every other import that forgot the buyer and no one can tell them apart.
    customer_id = str(payload.get("customer_email") or payload.get("source") or "").strip()
    if not customer_id:
        raise ValidationException(
            message=("the incoming order names no customer — no buyer email and no source system, "
                     "so there is no one to bill and no address to ship to"),
            detail={"customer_email": None, "source": None},
        )

    order_data = {
        "customer_id": customer_id,
        "items": items,
        "priority": "medium",
        "notes": payload.get("notes", f"Imported from {payload.get('source', 'external')}"),
    }

    order = await oms_service.create_order(db, order_data)
    return order
