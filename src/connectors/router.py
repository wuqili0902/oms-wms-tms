"""E-commerce connector API endpoints.

Receives Shopify webhooks and Amazon SP-API order data,
translates them into internal OMS orders via the connector service.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.connectors.amazon_mws import parse_amazon_order
from src.connectors.shopify_webhook import verify_webhook
from src.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.post("/shopify/webhook", status_code=status.HTTP_200_OK)
async def shopify_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Receive and process Shopify order webhooks.

    Supports ``orders/create`` and ``orders/fulfilled`` topics.
    Verified via HMAC-SHA256 signature in ``X-Shopify-Hmac-Sha256`` header.
    """
    topic = request.headers.get("X-Shopify-Topic", "")
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    secret = settings.secret_key  # Reuse app secret_key for Shopify HMAC

    body = await request.body()

    if not verify_webhook(body, hmac_header, secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    from src.connectors.shopify_webhook import handle_shopify_webhook

    msg = await handle_shopify_webhook(topic, body, hmac_header, secret)
    if msg is None:
        return {"status": "skipped", "topic": topic}

    import src.connectors.service as svc

    order = await svc.import_erp_order(db, msg)
    logger.info("Shopify webhook %s → OMS order %s", topic, order["id"])
    return {"status": "imported", "order_id": order["id"]}


@router.post("/amazon/orders", status_code=status.HTTP_201_CREATED)
async def import_amazon_order(data: dict, db: AsyncSession = Depends(get_db)):
    """Import an Amazon order via SP-API data."""
    msg = parse_amazon_order(data)
    import src.connectors.service as svc

    order = await svc.import_erp_order(db, msg)
    return {"status": "imported", "order_id": order["id"], "amazon_order_id": data.get("AmazonOrderId", "")}


@router.post("/amazon/tracking", status_code=status.HTTP_200_OK)
async def update_amazon_tracking(data: dict):
    """Receive tracking updates to send back to Amazon SP-API."""
    from src.connectors.amazon_mws import build_tracking_update

    payload = build_tracking_update(
        amazon_order_id=data.get("amazon_order_id", ""),
        carrier_code=data.get("carrier_code", ""),
        tracking_number=data.get("tracking_number", ""),
        status=data.get("status", "Shipped"),
    )
    logger.info("Amazon tracking update ready: %s", payload)
    return {"status": "received", "amazon_order_id": payload["amazon_order_id"]}
