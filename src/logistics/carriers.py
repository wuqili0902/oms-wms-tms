"""Logistics carrier integration module.

Provides carrier abstraction, tracking query stubs, and waybill management
for Chinese domestic carriers (ZTO, SF Express, YTO, STO, etc.).

Configure carrier API endpoints via environment variable:
  CARRIER_API_ENDPOINTS='{"sf":"https://api.sf-express.com/track","zto":"https://api.zto.com/track"}'

Leave empty (default) to use mock data for demo/testing.
"""
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum

import httpx

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
        from src.config import settings
        return settings.carrier_api_endpoints_dict
    except Exception:
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

    When a carrier API endpoint is configured via CARRIER_API_ENDPOINTS env var,
    makes an HTTP GET request. Otherwise returns mock data.
    """
    endpoints = _get_carrier_endpoints()
    api_url = endpoints.get(carrier.value, "")

    if api_url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(api_url, params={"tracking": tracking_number})
                resp.raise_for_status()
                data = resp.json()
                return {
                    "carrier": carrier.value,
                    "carrier_name": CARRIER_NAMES.get(carrier, ""),
                    "tracking_number": tracking_number,
                    "status": data.get("status", "unknown"),
                    "status_detail": data.get("detail", ""),
                    "estimated_delivery": data.get("estimated_delivery", ""),
                    "tracking_url": get_tracking_url(carrier, tracking_number),
                    "events": data.get("events", []),
                }
        except Exception:
            logger.warning("Carrier API %s unavailable, falling back to mock", api_url)

    return _mock_tracking(carrier, tracking_number)


async def estimate_shipping(
    carrier: CarrierCode,
    origin: str = "",
    destination: str = "",
    weight_kg: float = 1.0,
) -> dict:
    """Estimate shipping cost and delivery time.

    When a carrier API endpoint is configured via CARRIER_API_ENDPOINTS env var,
    makes an HTTP POST. Otherwise returns mock estimates.
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
                return {
                    "carrier": carrier.value,
                    "carrier_name": CARRIER_NAMES.get(carrier, ""),
                    "estimated_cost_yuan": data.get("cost", 0),
                    "estimated_days": data.get("days", 3),
                    "weight_kg": weight_kg,
                }
        except Exception:
            logger.warning("Carrier API %s unavailable, falling back to mock", api_url)

    return _mock_estimate(carrier, weight_kg)


# ── Mock fallbacks ────────────────────────────────────────────────────────────


def _mock_tracking(carrier: CarrierCode, tracking_number: str) -> dict:
    """Generate plausible mock tracking data."""
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

    return {
        "carrier": carrier.value,
        "carrier_name": CARRIER_NAMES.get(carrier, ""),
        "tracking_number": tracking_number,
        "status": status.value,
        "status_detail": detail,
        "estimated_delivery": now[:10],
        "tracking_url": get_tracking_url(carrier, tracking_number),
        "events": [{"time": now, "location": "上海转运中心", "description": detail}],
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
    }
