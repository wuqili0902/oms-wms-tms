"""Logistics carrier integration module.

Provides carrier abstraction, tracking query stubs, and waybill management
for Chinese domestic carriers (ZTO, SF Express, YTO, STO, etc.).
"""
import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class CarrierCode(str, Enum):
    """Supported carrier codes."""

    SF = "sf"           # 顺丰
    ZTO = "zto"         # 中通
    YTO = "yto"         # 圆通
    STO = "sto"         # 申通
    YUNDA = "yunda"     # 韵达
    EMS = "ems"         # EMS
    JD = "jd"           # 京东


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


class TrackingStatus(str, Enum):
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
    today = datetime.now(timezone.utc).strftime("%y%m%d")
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


def validate_carrier(carrier: str) -> Optional[CarrierCode]:
    """Validate and normalize a carrier code string. Returns None if invalid."""
    try:
        return CarrierCode(carrier.lower())
    except ValueError:
        return None


# ── Carrier API Stubs ──────────────────────────────────────────────────────
# In production, these would call each carrier's REST/SOAP API.
# The stubs return plausible mock data for testing and demo purposes.


async def query_tracking(carrier: CarrierCode, tracking_number: str) -> dict:
    """Query tracking information for a waybill.

    Returns a standardized tracking response. In production, this
    would call the carrier's actual API and normalize the response.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Simulate different statuses based on tracking number hash
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
        "events": [
            {
                "time": now,
                "location": "上海转运中心",
                "description": detail,
            }
        ],
    }


async def estimate_shipping(
    carrier: CarrierCode,
    origin: str = "",
    destination: str = "",
    weight_kg: float = 1.0,
) -> dict:
    """Estimate shipping cost and delivery time.

    Returns mock estimates. In production, calls carrier rate API.
    """
    base_rates = {
        CarrierCode.SF: (18.0, 2),    # (base_cost, days)
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
