"""Connector service — translates ERPMessages into internal OMS orders."""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.erp_connector import ERPMessage
from src.oms import service as oms_service

logger = logging.getLogger(__name__)


async def import_erp_order(db: AsyncSession, msg: ERPMessage) -> dict:
    """Convert an ERPMessage into an OMS order.

    Handles ``ORDERS`` and ``ORDINR`` message types by mapping
    the external order payload to the internal ``create_order`` schema.
    """
    payload = msg.payload

    items = []
    for line in payload.get("items", []):
        items.append({
            "sku": line.get("sku", ""),
            "product_name": line.get("product_name", ""),
            "quantity": line.get("quantity", 1),
            "unit_price": line.get("unit_price", "0"),
            "gtin": line.get("gtin", ""),
        })

    customer_data = {
        "customer_id": payload.get("customer_email", payload.get("source", "unknown")),
    }

    order_data = {
        **customer_data,
        "items": items,
        "priority": "medium",
        "notes": payload.get("notes", f"Imported from {payload.get('source', 'external')}"),
    }

    order = await oms_service.create_order(db, order_data)
    return order
