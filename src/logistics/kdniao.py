"""Kdniao (快递鸟) electronic waybill integration.

Provides:
    - create_waybill(order_id, recipient, items, carrier_code): 下单并返回面单号 + 打印 URL
    - query_tracking(tracking_number): 查单（调用快递鸟 API）
    - print_callback_url(tracking_number): 获取打印回调地址

Environment variables (optional):
    KDNIAO_API_KEY = "your_api_key"
    KDNIAO_SECRET_KEY = "your_secret_key"
"""

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class CarrierCode:
    """Supported carriers (string constants)."""
    SF = "sf"
    ZTO = "zto"
    YTO = "yto"
    STO = "sto"
    YUNDA = "yunda"
    EMS = "ems"
    JD = "jd"


VALID_CARRIERS = {getattr(CarrierCode, a) for a in vars(CarrierCode) if not a.startswith("_")}

CARRIER_NAMES: dict[str, str] = {
    CarrierCode.SF: "顺丰速运",
    CarrierCode.ZTO: "中通快递",
    CarrierCode.YTO: "圆通速递",
    CarrierCode.STO: "申通快递",
    CarrierCode.YUNDA: "韵达快递",
    CarrierCode.EMS: "EMS 邮政",
    CarrierCode.JD: "京东物流",
}

CARRIER_TRACKING_URLS: dict[str, str] = {
    CarrierCode.SF: "https://www.sf-express.com/we/ow/chn/sc/waybill/waybill-detail/",
    CarrierCode.ZTO: "https://track.zto.com/?nu={tracking}",
    CarrierCode.YTO: "https://www.yto.net.cn/tracking/{tracking}",
    CarrierCode.STO: "https://www.sto.cn/track?waybillNo={tracking}",
    CarrierCode.YUNDA: "https://www.yundaex.com/track/{tracking}",
    CarrierCode.EMS: "https://www.ems.com.cn/track?trackNum={tracking}",
    CarrierCode.JD: "https://www.jdl.com/tracking?waybill={tracking}",
}


def generate_tracking_number(carrier: str, order_id: str = "") -> str:
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
        suffix = "".join(hashlib.sha1(str(datetime.now()).encode()).hexdigest()[i:i+4].upper() for i in range(0, 32, 4))
    return f"{prefix}{today}{suffix}"


def get_tracking_url(carrier: str, tracking_number: str) -> str:
    """Get the public tracking URL for a carrier and tracking number."""
    template = CARRIER_TRACKING_URLS.get(carrier, "")
    if not template:
        return ""
    # Some URLs use query params, some use path segments
    if "{tracking}" in template:
        return template.replace("{tracking}", tracking_number)
    return f"{template}{tracking_number}"


def validate_carrier(carrier: str) -> str | None:
    """Validate and normalize a carrier code string. Returns None if invalid."""
    c = carrier.lower()
    return c if c in VALID_CARRIERS else None


# ── API stubs (mock data for demo/testing) ───────────────────────────────────

async def create_waybill(
    order_id: str,
    recipient_name: str,
    recipient_phone: str,
    recipient_address: str,
    items: list[dict[str, Any]],  # {"sku": "...", "qty": int}
    carrier_code: str = CarrierCode.ZTO,
) -> dict[str, Any]:
    """Create a waybill via Kdniao (or mock).

    Returns:
        {
            "tracking_number": str,
            "carrier": str,
            "print_callback_url": str,  # 快递鸟提供的打印回调地址
            "status": "success",
        }
    """
    tracking = generate_tracking_number(carrier_code, order_id)
    url = get_tracking_url(carrier_code, tracking)

    return {
        "tracking_number": tracking,
        "carrier": carrier_code,
        "carrier_name": CARRIER_NAMES.get(carrier_code, ""),
        "print_callback_url": f"{url}?callback=1",  # mock: append ?callback=1
        "status": "success",
    }


async def query_tracking(tracking_number: str) -> dict[str, Any]:
    """Query tracking information (mock)."""
    now = datetime.now(UTC).isoformat()
    hash_val = sum(ord(c) for c in tracking_number) % 100

    if hash_val < 20:
        status = "picked_up"
        detail = "已揽收"
    elif hash_val < 50:
        status = "in_transit"
        detail = "运输中 — 到达中转站"
    elif hash_val < 80:
        status = "out_for_delivery"
        detail = "派送中"
    elif hash_val < 95:
        status = "delivered"
        detail = "已签收"
    else:
        status = "pending"
        detail = "等待揽收"

    return {
        "carrier": tracking_number[:2],
        "tracking_number": tracking_number,
        "status": status,
        "status_detail": detail,
        "estimated_delivery": now[:10],
        "events": [{"time": now, "location": "上海转运中心", "description": detail}],
    }


def print_callback_url(tracking_number: str) -> str:
    """Return the print callback URL for a tracking number."""
    prefix = tracking_number[:2].lower() if len(tracking_number) >= 2 else "xx"
    prefix_map = {
        "sf": "sf", "zt": "zto", "yt": "yto", "st": "sto",
        "yd": "yunda", "em": "ems", "jd": "jd",
    }
    carrier = prefix_map.get(prefix, "zto")
    return get_tracking_url(carrier, tracking_number)
