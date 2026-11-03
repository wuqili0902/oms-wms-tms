"""Logistics carrier integration module.

Provides carrier abstraction, tracking query, and waybill management
for Chinese domestic carriers (ZTO, SF Express, YTO, STO, etc.).

Configure carrier API endpoints via environment variable:
  CARRIER_API_ENDPOINTS='{"sf":"https://api.sf-express.com/track","zto":"https://api.zto.com/track"}'

Three answers to a tracking query, in this order of preference:
  * the carrier endpoint configured for that carrier → its data;
  * ``LOGISTICS_MOCK_ENABLED=true`` → the demo generator, every event labelled
    ``source: "mock"``;
  * neither → ``501 NOT_IMPLEMENTED``.

A failed carrier call used to fall through to the same demo data, so a timeout
looked like "运输中 — 到达中转站" and the dispatcher reported that to the customer.
It now raises; ``src/logistics/router.py`` renders it as 502.
"""
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum

import httpx

from src.config import settings
from src.core.exceptions import NotImplementedActionException

logger = logging.getLogger(__name__)


class CarrierCode(StrEnum):
    SF = "sf"
    ZTO = "zto"
    YTO = "yto"
    STO = "sto"
    YUNDA = "yunda"
    EMS = "ems"
    JD = "jd"


CARRIER_NAMES: dict[CarrierCode, str] = {
    CarrierCode.SF: "顺丰速运",
    CarrierCode.ZTO: "中通快递",
    CarrierCode.YTO: "圆通速递",
    CarrierCode.STO: "申通快递",
    CarrierCode.YUNDA: "韵达快递",
    CarrierCode.EMS: "EMS邮政",
    CarrierCode.JD: "京东物流",
}

CARRIER_TRACKING_URLS: dict[CarrierCode, str] = {
    CarrierCode.SF: "https://www.sf-express.com/we/ow/chn/sc/waybill/waybill-detail/",
    CarrierCode.ZTO: "https://track.zto.com/?nu={tracking}",
    CarrierCode.YTO: "https://www.yto.net.cn/tracking/{tracking}",
    CarrierCode.STO: "https://www.sto.cn/track?waybillNo={tracking}",
    CarrierCode.YUNDA: "https://www.yundaex.com/track/{tracking}",
    CarrierCode.EMS: "https://www.ems.com.cn/track?trackNum={tracking}",
    CarrierCode.JD: "https://www.jdl.com/tracking?waybill={tracking}",
}


def _get_carrier_endpoints() -> dict[str, str]:
    """Read carrier API endpoints from Settings (configurable via env var)."""
    try:
        return settings.carrier_api_endpoints_dict
    except Exception:
        # Malformed CARRIER_API_ENDPOINTS is a config error, not a licence to
        # invent tracking: the query below then answers 501.
        logger.warning("CARRIER_API_ENDPOINTS is not valid JSON; carrier tracking is unconfigured")
        return {}


class TrackingStatus(StrEnum):
    """Standardized tracking statuses."""

    PENDING = "pending"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETURNED = "returned"


def generate_tracking_number(carrier: CarrierCode, order_id: str = "") -> str:
    """Generate a deterministic tracking number for a carrier.

    In production, the carrier's API would provide the actual number.
    This generates a structured placeholder for testing/demo.
    """
    prefix_map = {
        CarrierCode.SF: "SF",
        CarrierCode.ZTO: "ZT",
        CarrierCode.YTO: "YT",
        CarrierCode.STO: "ST",
        CarrierCode.YUNDA: "YD",
        CarrierCode.EMS: "EM",
        CarrierCode.JD: "JD",
    }
    prefix = prefix_map.get(carrier, "XX")
    today = datetime.now(UTC).strftime("%y%m%d")
    # Use order_id hash for deterministic suffix
    if order_id:
        suffix = hashlib.md5(order_id.encode()).hexdigest()[:8].upper()
    else:
        suffix = uuid.uuid4().hex[:8].upper()
    return f"{prefix}{today}{suffix}"


def get_tracking_url(carrier: CarrierCode, tracking_number: str) -> str:
    """Get the public tracking URL for a carrier and tracking number."""
    template = CARRIER_TRACKING_URLS.get(carrier, "")
    if not template:
        return ""
    # Some URLs use query params, some use path segments
    if "{tracking}" in template:
        return template.replace("{tracking}", tracking_number)
    return f"{template}{tracking_number}"


def validate_carrier(carrier: str) -> CarrierCode | None:
    """Validate and normalize a carrier code string. Returns None if invalid."""
    try:
        return CarrierCode(carrier.lower())
    except ValueError:
        return None


# ── Carrier API ─────────────────────────────────────────────────────────
# Attempts real HTTP calls when carrier API endpoints are configured;
# falls back to mock data for demo/testing when endpoints are empty.


async def query_tracking(carrier: CarrierCode, tracking_number: str) -> dict:
    """Query tracking information for a waybill.

    The carrier endpoint configured via ``CARRIER_API_ENDPOINTS`` answers when it
    is configured; a failing endpoint is an error, not a licence to answer demo
    data.  With no endpoint, the demo generator runs only when
    ``LOGISTICS_MOCK_ENABLED`` is on, and the answer says so.
    """
    endpoints = _get_carrier_endpoints()
    api_url = endpoints.get(carrier.value, "")

    if api_url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(api_url, params={"tracking": tracking_number})
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            # Returning plausible tracking here is how a network timeout became
            # "运输中 — 到达中转站" on a screen.
            logger.error("Carrier API %s failed for %s: %s", api_url, tracking_number, e)
            raise RuntimeError(f"{carrier.value} 轨迹接口调用失败（{api_url}）：{e}") from e
        return {
            "carrier": carrier.value,
            "carrier_name": CARRIER_NAMES.get(carrier, ""),
            "tracking_number": tracking_number,
            "status": data.get("status", "unknown"),
            "status_detail": data.get("detail", ""),
            "estimated_delivery": data.get("estimated_delivery", ""),
            "tracking_url": get_tracking_url(carrier, tracking_number),
            "source": "carrier_api",
            "events": data.get("events", []),
        }

    if settings.logistics_mock_enabled:
        return _mock_tracking(carrier, tracking_number)
    raise NotImplementedActionException(
        message=(
            f"承运商 {carrier.value} 轨迹查询未配置：在 CARRIER_API_ENDPOINTS 里加上"
            f'{{"{carrier.value}": "https://…"}}。未配置时不返回任何轨迹状态'
            "（旧版本按运单号哈希编造 已揽收/运输中/派送中/已签收）；"
            "演示环境可设 LOGISTICS_MOCK_ENABLED=true，结果会标 source=mock。"
        ),
        detail={"carrier": carrier.value, "tracking_number": tracking_number, "configured": False},
    )


async def estimate_shipping(
    carrier: CarrierCode,
    origin: str = "",
    destination: str = "",
    weight_kg: float = 1.0,
) -> dict:
    """Estimate shipping cost and delivery time.

    A quote is a number someone charges money on, so it follows the same rule as
    tracking: the carrier endpoint answers when configured, a failing endpoint is
    an error, and the built-in rate table is only reachable when
    ``LOGISTICS_MOCK_ENABLED`` is on — labelled ``source: "mock"``.
    """
    endpoints = _get_carrier_endpoints()
    api_url = endpoints.get(carrier.value, "")

    if api_url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    api_url,
                    json={"origin": origin, "destination": destination, "weight_kg": weight_kg},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error("Carrier API %s quote failed: %s", api_url, e)
            raise RuntimeError(f"{carrier.value} 运费询价失败（{api_url}）：{e}") from e
        return {
            "carrier": carrier.value,
            "carrier_name": CARRIER_NAMES.get(carrier, ""),
            "estimated_cost_yuan": data.get("cost", 0),
            "estimated_days": data.get("days", 3),
            "weight_kg": weight_kg,
            "source": "carrier_api",
        }

    if settings.logistics_mock_enabled:
        return _mock_estimate(carrier, weight_kg)
    raise NotImplementedActionException(
        message=(
            f"承运商 {carrier.value} 运费询价未配置：在 CARRIER_API_ENDPOINTS 里加上"
            f'{{"{carrier.value}": "https://…"}}；未配置时本地费率表只是演示数据'
        ),
        detail={"carrier": carrier.value, "configured": False},
    )


# ── Mock fallbacks ────────────────────────────────────────────────────────────


def _mock_tracking(carrier: CarrierCode, tracking_number: str) -> dict:
    """Demo tracking, reachable only with ``LOGISTICS_MOCK_ENABLED=true``.

    The status comes out of ``sum(ord(c)) % 100`` of the waybill number — no
    shipment is consulted — so every string here carries the 演示数据 label.
    """
    now = datetime.now(UTC).isoformat()
    hash_val = sum(ord(c) for c in tracking_number) % 100

    if hash_val < 20:
        status = TrackingStatus.PICKED_UP
        detail = "已揽收"
    elif hash_val < 50:
        status = TrackingStatus.IN_TRANSIT
        detail = "运输中 — 到达中转站"
    elif hash_val < 80:
        status = TrackingStatus.OUT_FOR_DELIVERY
        detail = "派送中"
    elif hash_val < 95:
        status = TrackingStatus.DELIVERED
        detail = "已签收"
    else:
        status = TrackingStatus.PENDING
        detail = "等待揽收"

    label = f"【演示数据】{detail}"
    return {
        "carrier": carrier.value,
        "carrier_name": CARRIER_NAMES.get(carrier, ""),
        "tracking_number": tracking_number,
        "status": status.value,
        "status_detail": label,
        "estimated_delivery": now[:10],
        "tracking_url": get_tracking_url(carrier, tracking_number),
        "source": "mock",
        "source_note": "演示数据：状态由运单号哈希得出，与真实快递无关（LOGISTICS_MOCK_ENABLED=true）",
        "events": [{"time": now, "location": "演示数据", "description": label}],
    }


def _mock_estimate(carrier: CarrierCode, weight_kg: float) -> dict:
    """Generate plausible mock shipping estimate."""
    base_rates = {
        CarrierCode.SF: (18.0, 2),
        CarrierCode.ZTO: (8.0, 3),
        CarrierCode.YTO: (8.0, 3),
        CarrierCode.STO: (8.0, 4),
        CarrierCode.YUNDA: (8.0, 3),
        CarrierCode.EMS: (15.0, 3),
        CarrierCode.JD: (12.0, 2),
    }
    base_cost, days = base_rates.get(carrier, (10.0, 4))
    cost = base_cost + max(0, weight_kg - 1) * 5.0

    return {
        "carrier": carrier.value,
        "carrier_name": CARRIER_NAMES.get(carrier, ""),
        "estimated_cost_yuan": round(cost, 2),
        "estimated_days": days,
        "weight_kg": weight_kg,
        "source": "mock",
        "source_note": "演示费率：内置基准价，不是承运商报价（LOGISTICS_MOCK_ENABLED=true）",
    }
