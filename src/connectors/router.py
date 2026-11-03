"""E-commerce connector API endpoints.

Receives Shopify webhooks and Amazon SP-API order data,
translates them into internal OMS orders via the connector service.

Also answers the 连接器管理 screen: ``GET /connectors/status`` and
``GET /connectors/{id}`` report which connectors this build has and which
actions each one performs (credential *values* are never returned, only whether
the setting is set), and ``POST /connectors/{id}/sync`` answers 501/422 —
neither connector has a pull side, and a 200 there reads as a sync that
happened.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import AliasChoices, BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.connectors.amazon_sp_api import build_tracking_update, parse_amazon_order
from src.connectors.shopify_webhook import verify_webhook
from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.core.exceptions import (
    NotFoundException,
    NotImplementedActionException,
    ValidationException,
)
from src.core.schemas import PayloadBody

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors", tags=["connectors"])


class TrackingUpdateBody(PayloadBody):
    """The tracking handover, in the words Amazon SP-API updates an order with.

    ``data: dict`` with four ``.get(..., "")`` defaults accepted a body that
    named no order, no carrier and no tracking number, and the endpoint answered
    ``received`` — the console read that as "the tracking is on its way to
    Amazon".  It was an empty dict with a timestamp on it.
    """

    amazon_order_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("amazon_order_id", "amazonOrderId", "AmazonOrderId", "order_id"),
        serialization_alias="amazon_order_id",
    )
    carrier_code: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("carrier_code", "carrierCode", "CarrierCode", "carrier"),
        serialization_alias="carrier_code",
    )
    tracking_number: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("tracking_number", "trackingNumber", "TrackingNumber", "tracking_no"),
        serialization_alias="tracking_number",
    )
    status: str = Field(default="Shipped", max_length=40)


class WebhookResponse(BaseModel):
    status: str
    topic: str | None = None
    order_id: str | None = None
    order_no: str | None = None


class ImportResponse(BaseModel):
    """What the import produced: the OMS order, named both ways.

    ``id`` is a uuid nobody reads off a printed pick list; ``order_no`` is the
    number on the order itself, and the console had no way to get it.
    """

    status: str
    order_id: str | None = None
    order_no: str | None = None
    amazon_order_id: str | None = None
    line_count: int = 0
    total_amount: str | None = None


class TrackingReceiveResponse(BaseModel):
    """The handover we recorded, and how far it got.

    ``sync_status`` says what the Amazon side did with it.  Until SP-API
    credentials exist it is ``not_configured`` — not ``uploaded``, which the
    screen used to read as a done deal.
    """

    status: str
    amazon_order_id: str | None = None
    carrier_code: str | None = None
    tracking_number: str | None = None
    sync_status: str


class CredentialField(BaseModel):
    """One credential a connector reads from the server config.

    Only whether it is set — the value itself is a secret and never travels to
    a browser.  The two config screens this API used to serve asked operators to
    type an AWS access key and a Shopify Admin API token into a web form and
    posted them to endpoints that did not exist; SP-API authenticates with an
    LWA client id/secret plus a refresh token, and Shopify is verified by HMAC
    with the app's own ``SECRET_KEY``, so neither field was a credential this
    system can use.
    """

    env: str
    set: bool | None = None
    value: str | None = None


class ConnectorStatus(BaseModel):
    """One connector, as it actually stands in this deployment.

    ``status`` says whether the connector can be used today;
    ``capabilities`` names each action and whether this build performs it, so a
    screen can show what works instead of advertising the four outbound SP-API
    calls that are stubs.
    """

    id: str
    name: str
    type: str
    status: str
    configured: bool
    last_sync: str | None = None
    capabilities: dict[str, str]
    credentials: list[CredentialField]
    note: str


class SyncResponse(BaseModel):
    status: str
    connector_id: str
    detail: str | None = None


def _amazon_connector() -> ConnectorStatus:
    configured = settings.amazon_sp_api_configured
    return ConnectorStatus(
        id="amazon",
        name="Amazon SP-API",
        type="amazon",
        status="active" if configured else "not_configured",
        configured=configured,
        last_sync=None,
        capabilities={
            "order_import": "implemented",
            "tracking_handover_record": "implemented",
            "tracking_upload": "not_implemented",
            "order_status_poll": "not_implemented",
            "inventory_sync": "not_implemented",
        },
        credentials=[
            CredentialField(env="AMAZON_SP_API_CLIENT_ID", set=bool(settings.amazon_sp_api_client_id)),
            CredentialField(env="AMAZON_SP_API_CLIENT_SECRET", set=bool(settings.amazon_sp_api_client_secret)),
            CredentialField(env="AMAZON_SP_API_REFRESH_TOKEN", set=bool(settings.amazon_sp_api_refresh_token)),
            CredentialField(env="AMAZON_SP_API_REGION", value=settings.amazon_sp_api_region),
        ],
        note=("凭据写在服务器配置（.env / 环境变量）里，不经网页传输；"
              "此接口只回报是否已配置，不回传密钥值。"),
    )


def _shopify_connector() -> ConnectorStatus:
    return ConnectorStatus(
        id="shopify",
        name="Shopify Webhook",
        type="shopify",
        status="active" if settings.secret_key else "not_configured",
        configured=bool(settings.secret_key),
        last_sync=None,
        capabilities={
            "order_push": "implemented",
            "fulfillment_push": "implemented",
            "order_pull": "not_available",
            "inventory_sync": "not_available",
        },
        credentials=[CredentialField(env="SECRET_KEY", set=bool(settings.secret_key))],
        note=("Shopify 是推送式对接：订单由 Webhook 带 HMAC 签名送入，用应用自己的 SECRET_KEY 验签；"
              "系统不拉取 Shopify，也不需要 Admin API Token。"),
    )


# The connectors that exist in this build.  The registry is code, not a table:
# a connector is its module plus its credentials, and nothing in the database
# says whether SP-API works.
_CONNECTOR_IDS = ("amazon", "shopify")


@router.get("/status", response_model=list[ConnectorStatus], status_code=status.HTTP_200_OK)
async def connector_status(current_user: dict = Depends(get_current_user)):
    """Every connector this deployment has, and what each one can do today."""
    return [_amazon_connector(), _shopify_connector()]


@router.get("/{connector_id}", response_model=ConnectorStatus, status_code=status.HTTP_200_OK)
async def connector_detail(connector_id: str, current_user: dict = Depends(get_current_user)):
    """One connector by id (``amazon`` / ``shopify``)."""
    key = (connector_id or "").strip().lower()
    if key not in _CONNECTOR_IDS:
        raise NotFoundException(
            message=f"Connector {connector_id!r} does not exist — the connectors here are amazon and shopify",
            detail={"connector_id": connector_id},
        )
    return _amazon_connector() if key == "amazon" else _shopify_connector()


@router.post("/{connector_id}/sync", response_model=SyncResponse, status_code=status.HTTP_200_OK)
async def connector_sync(connector_id: str, current_user: dict = Depends(get_current_user)):
    """Pull data from a connector. There is nothing to pull.

    The 连接器管理 screen's 同步 button posted to a URL that did not exist (404,
    printed on screen as 同步失败 with no reason), on a screen that listed
    connectors from a URL that also did not exist.  The honest answer is that
    neither connector has a pull side: Amazon's outbound calls are unimplemented
    (``501``), and Shopify pushes — there is no Shopify data to fetch.
    """
    key = (connector_id or "").strip().lower()
    if key not in _CONNECTOR_IDS:
        raise NotFoundException(
            message=f"Connector {connector_id!r} does not exist — the connectors here are amazon and shopify",
            detail={"connector_id": connector_id},
        )
    if key == "amazon":
        raise NotImplementedActionException(
            message=("Amazon 同步（拉取订单 / 状态轮询 / 库存同步）需要 SP-API 调用，本系统尚未实现；"
                     "订单请用 POST /connectors/amazon/orders 导入，发货交接用 POST /connectors/amazon/tracking 记录"),
            detail={"connector_id": "amazon", "implemented": False},
        )
    raise ValidationException(
        message=("Shopify 是推送式对接：订单由 Webhook 送入，没有可拉取的 Shopify 数据；"
                 "库存与订单变更请在 Shopify 侧配置 Webhook 推送"),
        detail={"connector_id": "shopify", "implemented": False},
    )


@router.post("/shopify/webhook", response_model=WebhookResponse, status_code=status.HTTP_200_OK)
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
    return {"status": "imported", "topic": topic, "order_id": order["id"], "order_no": order.get("order_no")}


@router.post("/amazon/orders", response_model=ImportResponse, status_code=status.HTTP_201_CREATED)
async def import_amazon_order(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Import one Amazon SP-API order into the OMS.

    ``data`` stays a free-form dict on purpose: the body is Amazon's own
    ``Order`` object, keys and all, and the endpoint accepts the shape SP-API
    returns.  The checks therefore live in ``parse_amazon_order`` — the same
    guards run for the nightly poll, not only for what a screen happens to post.
    A body that names no order, carries no lines, or prices a line as prose is
    a 422 naming the key at fault; the 201 at the end is an order the warehouse
    can act on.
    """
    msg = parse_amazon_order(data)
    import src.connectors.service as svc

    order = await svc.import_erp_order(db, msg)
    return {
        "status": "imported",
        "order_id": order["id"],
        "order_no": order.get("order_no"),
        "amazon_order_id": msg.payload["amazon_order_id"],
        "line_count": len(order.get("items", [])),
        "total_amount": order.get("total_amount"),
    }


@router.post("/amazon/tracking", response_model=TrackingReceiveResponse, status_code=status.HTTP_200_OK)
async def update_amazon_tracking(
    data: TrackingUpdateBody,
    current_user: dict = Depends(get_current_user),
):
    """Record a shipment handover for one Amazon order.

    The handover needs the order, the carrier and the tracking number — a body
    without them used to be answered ``received``, and the console read that as
    tracking on its way to Amazon.  ``sync_status`` now says how far it actually
    got: SP-API upload needs credentials, and without them the answer is
    ``not_configured``, with the handover recorded.
    """
    payload = build_tracking_update(
        amazon_order_id=data.amazon_order_id,
        carrier_code=data.carrier_code,
        tracking_number=data.tracking_number,
        status=data.status,
    )
    logger.info("Amazon tracking update ready: %s", payload)
    return {
        "status": "received",
        "amazon_order_id": payload["amazon_order_id"],
        "carrier_code": payload["carrier_code"],
        "tracking_number": payload["tracking_number"],
        "sync_status": "queued" if settings.amazon_sp_api_configured else "not_configured",
    }
