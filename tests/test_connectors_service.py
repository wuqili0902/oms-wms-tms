"""Tests for connectors/service.py."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.erp_connector import ERPMessage, MessageType


@pytest.mark.asyncio
async def test_import_erp_order_creates_order(db_session: AsyncSession):
    from src.connectors.service import import_erp_order

    msg = ERPMessage(
        msg_type=MessageType.ORDERS,
        sender_id="SAP",
        receiver_id="WMS",
        payload={
            "customer_email": "test@example.com",
            "items": [
                {"sku": "SKU-001", "product_name": "Widget", "quantity": 5, "unit_price": "10.00", "gtin": "123456789"},
            ],
            "notes": "ERP import",
            "source": "SAP",
        },
    )

    order = await import_erp_order(db_session, msg)
    assert order["order_no"].startswith("ORD-")
    assert order["status"] == "draft"
    assert len(order["items"]) == 1
    assert order["items"][0]["sku"] == "SKU-001"
    assert order["notes"] == "ERP import"


@pytest.mark.asyncio
async def test_import_erp_order_multiple_items(db_session: AsyncSession):
    from src.connectors.service import import_erp_order

    msg = ERPMessage(
        msg_type=MessageType.ORDERS,
        sender_id="Oracle",
        receiver_id="WMS",
        payload={
            "customer_email": "bulk@example.com",
            "items": [
                {"sku": "SKU-A", "quantity": 2, "unit_price": "5.00"},
                {"sku": "SKU-B", "quantity": 3, "unit_price": "15.00"},
                {"sku": "SKU-C", "quantity": 1, "unit_price": "50.00"},
            ],
        },
    )

    order = await import_erp_order(db_session, msg)
    assert len(order["items"]) == 3


@pytest.mark.asyncio
async def test_import_erp_order_missing_customer_uses_source(db_session: AsyncSession):
    from src.connectors.service import import_erp_order

    msg = ERPMessage(
        msg_type=MessageType.ORDERS,
        sender_id="EDI",
        receiver_id="WMS",
        payload={
            "items": [{"sku": "SKU-X", "quantity": 1, "unit_price": "0"}],
            "source": "EDI-SYSTEM",
        },
    )

    order = await import_erp_order(db_session, msg)
    assert order["customer_id"] == "EDI-SYSTEM"


@pytest.mark.asyncio
async def test_import_erp_order_empty_items_is_refused(db_session: AsyncSession):
    """An order with nothing on it used to import green.

    It was asserted as behaviour: ``len(order["items"]) == 0`` and a total of
    "0".  An order with no lines cannot be picked, shipped, invoiced, or
    cancelled — every screen downstream shows it as work that does not exist.
    """
    from src.connectors.service import import_erp_order
    from src.core.exceptions import ValidationException

    msg = ERPMessage(
        msg_type=MessageType.ORDERS,
        sender_id="SAP",
        receiver_id="WMS",
        payload={
            "customer_email": "empty@example.com",
            "items": [],
        },
    )

    with pytest.raises(ValidationException, match="no lines"):
        await import_erp_order(db_session, msg)
