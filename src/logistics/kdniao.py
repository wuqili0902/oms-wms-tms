"""Kdniao (快递鸟) electronic waybill integration.

Provides:
    - create_waybill(order_id, recipient, items, carrier_code): 下单并返回面单号 + 打印 URL
    - query_tracking(tracking_number): 查单（调用快递鸟 API）
    - print_callback_url(tracking_number): 获取打印回调地址

Two modes for 面单下单, three for 轨迹查询:
    - KDNIAO_EBUSINESS_ID + KDNIAO_API_KEY configured → real 快递鸟 API calls
      (电子面单下单 EbossEwayBill v1 / 路由查询 /api/dist) with MD5 signing.
    - Tracking without credentials → ``501 NOT_IMPLEMENTED``.  There is no carrier
      data to read in that case, and the demo generator below picks a delivery
      state from a hash of the waybill number: 未配置时它答的"已签收"不是快递的
      状态，是一个哈希桶，而 SOP 让调度员拿这个接口"实时拉取快递轨迹"回客户。
    - LOGISTICS_MOCK_ENABLED=true (dev/test only) → the demo generator, with every
      event labelled ``source: "mock"`` so a screen cannot display it as a real
      shipment.

Environment variables:
    KDNIAO_EBUSINESS_ID = "your_ebusiness_id"   # 快递鸟用户ID
    KDNIAO_API_KEY = "your_api_key"             # 快递鸟API key
    LOGISTICS_MOCK_ENABLED = "false"            # 演示轨迹数据（显式开启才有）
"""

import base64
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from src.config import settings
from src.core.exceptions import NotImplementedActionException

logger = logging.getLogger(__name__)

# 快递鸟 endpoints (official API docs: api.kdniao.com)
KDNIAO_WAYBILL_URL = "http://api.kdniao.com/EbossEwayBillRSS/1.0/send/v1.html"
KDNIAO_QUERY_URL = "http://api.kdniao.com/api/dist"
KDNIAO_TIMEOUT_SECONDS = 10.0


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

# Internal carrier codes expected by the 快递鸟 electronic-waybill API.
# NOTE: 面单下单 carrier codes depend on which carriers are activated in your
# 快递鸟 account console — verify against 电子面单 → 快递公司列表 and adjust if
# your account provisions different codes.
KDNIAO_CARRIER_CODES: dict[str, str] = {
    CarrierCode.SF: "2001",
    CarrierCode.ZTO: "3011",
    CarrierCode.YTO: "3013",
    CarrierCode.STO: "3009",
    CarrierCode.YUNDA: "3016",
    CarrierCode.EMS: "2",
    CarrierCode.JD: "2002",
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


# ── Credential / signing helpers ────────────────────────────────────────────


def credentials_configured() -> bool:
    """True when both 快递鸟 credentials are set → real API mode."""
    return bool(settings.kdniao_ebusiness_id and settings.kdniao_api_key)


def _sign_waybill(payload: str, api_key: str) -> str:
    """快递鸟下单签名: Base64(raw MD5(Data + ApiKey))."""
    digest = hashlib.md5((payload + api_key).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def _sign_query(payload: str, api_key: str) -> str:
    """快递轨迹查询签名: MD5(RequestData + ApiKey) 全大写 hex."""
    return hashlib.md5((payload + api_key).encode("utf-8")).hexdigest().upper()


# ── Waybill creation ─────────────────────────────────────────────────────────

async def create_waybill(
    order_id: str,
    recipient_name: str,
    recipient_phone: str,
    recipient_address: str,
    items: list[dict[str, Any]],  # {"sku": "...", "qty": int}
    carrier_code: str = CarrierCode.ZTO,
) -> dict[str, Any]:
    """Create a waybill — real 快递鸟下单 when credentials are configured,
    deterministic mock otherwise (dev/test).

    Returns:
        {
            "tracking_number": str,
            "carrier": str,
            "print_callback_url": str,  # 打印/查询地址
            "status": "success",
        }
        Real mode additionally returns ``waybill_code`` and ``print_settings``.
    """
    if credentials_configured():
        return await _create_waybill_real(
            order_id, recipient_name, recipient_phone, recipient_address, items, carrier_code
        )
    tracking = generate_tracking_number(carrier_code, order_id)
    url = get_tracking_url(carrier_code, tracking)

    return {
        "tracking_number": tracking,
        "carrier": carrier_code,
        "carrier_name": CARRIER_NAMES.get(carrier_code, ""),
        "print_callback_url": f"{url}?callback=1",  # mock: append ?callback=1
        "status": "success",
        # Not a carrier-issued number: nothing was ordered from 快递鸟.  Anything
        # printing this label is printing a local placeholder.
        "source": "local_placeholder",
        "source_note": "未配置快递鸟凭据：面单号由本地生成，快递侧并不存在这张面单",
    }


async def _create_waybill_real(
    order_id: str,
    recipient_name: str,
    recipient_phone: str,
    recipient_address: str,
    items: list[dict[str, Any]],
    carrier_code: str,
) -> dict[str, Any]:
    """Call 快递鸟 电子面单下单 API (EbossEwayBill v1, RequestType=101)."""
    kdniao_carrier = KDNIAO_CARRIER_CODES.get(carrier_code)
    if not kdniao_carrier:
        raise ValueError(f"快递鸟不支持的物流商: {carrier_code}")

    request_data = {
        "OrderCode": str(order_id),
        "CarrierCode": kdniao_carrier,
        "CompanionCode": None,
        "OrderOriginName": "OMS-WMS-TMS",
        "OrderOriginCode": None,
        "OrderOriginRemark": None,
        "RecipientName": recipient_name,
        "RecipientPhone": recipient_phone,
        "RecipientAddress": recipient_address,
        "InsuredAmount": 0,
        "ItemTitle": ", ".join(str(i.get("sku", "")) for i in items) or "一般货物",
        "IsConfirm2": 0,
        "IsANNeed": 0,
    }
    data_json = json.dumps(request_data, ensure_ascii=False, separators=(",", ":"))
    form = {
        "EBusinessID": settings.kdniao_ebusiness_id,
        "RequestType": "101",
        "SignType": "MD5",
        "DataSign": _sign_waybill(data_json, settings.kdniao_api_key),
        "Data": data_json,
    }

    async with httpx.AsyncClient(timeout=KDNIAO_TIMEOUT_SECONDS) as client:
        resp = await client.post(KDNIAO_WAYBILL_URL, data=form)
    if resp.status_code != 200:
        raise RuntimeError(f"快递鸟下单 HTTP {resp.status_code}: {resp.text[:200]}")

    body = resp.json()
    result = body.get("Result") or {}
    if isinstance(result, list):
        result = result[0] if result else {}
    tracking = result.get("WaybillCode") or body.get("WaybillCode")
    if not body.get("Success") or not tracking:
        reason = body.get("Reason") or result.get("Message") or "no WaybillCode returned"
        raise RuntimeError(f"快递鸟下单失败: {reason}")

    tracking = str(tracking)
    logger.info("[kdniao] waybill created for order %s: %s", order_id, tracking)
    return {
        "tracking_number": tracking,
        "carrier": carrier_code,
        "carrier_name": CARRIER_NAMES.get(carrier_code, ""),
        "print_callback_url": get_tracking_url(carrier_code, tracking),
        "status": "success",
        "waybill_code": tracking,
        "source": "kdniao",
        "print_settings": result.get("PrintSettings") or [],
    }


# Heuristic mapping of 快递鸟 trace text → our normalized shipment status.
_TRACE_STATUS_RULES: list[tuple[str, str]] = [
    ("签收", "delivered"),
    ("代收", "delivered"),
    ("派送", "out_for_delivery"),
    ("投递", "out_for_delivery"),
    ("揽收", "picked_up"),
    ("收件", "picked_up"),
    ("取件", "picked_up"),
    ("到达", "in_transit"),
    ("中转", "in_transit"),
    ("运输", "in_transit"),
    ("发出", "in_transit"),
]


def _map_trace_status(description: str) -> str:
    for keyword, status in _TRACE_STATUS_RULES:
        if keyword in description:
            return status
    return "pending"


def _mock_tracking(tracking_number: str) -> dict[str, Any]:
    """Demo tracking, for dev/test only, and always labelled.

    The delivery state comes out of ``sum(ord(c)) % 100`` of the waybill number:
    two identical numbers read the same, and nothing about the shipment is
    consulted.  That is fine as a screen fixture and dangerous as an answer, so
    every string the caller receives says 演示数据 / ``source: "mock"``.
    """
    now = datetime.now(UTC).isoformat()
    hash_val = sum(ord(c) for c in tracking_number) % 100

    if hash_val < 20:
        status, detail = "picked_up", "已揽收"
    elif hash_val < 50:
        status, detail = "in_transit", "运输中 — 到达中转站"
    elif hash_val < 80:
        status, detail = "out_for_delivery", "派送中"
    elif hash_val < 95:
        status, detail = "delivered", "已签收"
    else:
        status, detail = "pending", "等待揽收"

    label = f"【演示数据】{detail}"
    return {
        "carrier": tracking_number[:2],
        "tracking_number": tracking_number,
        "status": status,
        "status_detail": label,
        "estimated_delivery": now[:10],
        "source": "mock",
        "source_note": "演示数据：状态由运单号哈希得出，与真实快递无关（LOGISTICS_MOCK_ENABLED=true）",
        "events": [{"time": now, "location": "演示数据", "description": label}],
    }


async def query_tracking(tracking_number: str) -> dict[str, Any]:
    """Query tracking information.

    Real 快递鸟 路由查询 when the credentials are configured; the labelled demo
    generator when ``LOGISTICS_MOCK_ENABLED`` is on; otherwise an explicit
    ``501`` — inventing "已签收" for a shipment nobody queried is the failure this
    closes, because the SOP tells dispatch to answer customers from this endpoint.
    """
    if credentials_configured():
        return await _query_tracking_real(tracking_number)
    if settings.logistics_mock_enabled:
        return _mock_tracking(tracking_number)
    raise NotImplementedActionException(
        message=(
            "快递鸟轨迹查询未配置：需要 KDNIAO_EBUSINESS_ID / KDNIAO_API_KEY。"
            "未配置时本接口不返回任何轨迹状态（旧版本按运单号哈希编造 已揽收/运输中/派送中/已签收）。"
            "演示环境可设 LOGISTICS_MOCK_ENABLED=true，返回的每条轨迹都会标 source=mock。"
        ),
        detail={"tracking_number": tracking_number, "configured": False},
    )


async def _query_tracking_real(tracking_number: str) -> dict[str, Any]:
    """Call 快递鸟 路由查询 API (/api/dist, RequestType=8001)."""
    request_data = json.dumps(
        {"LogisticCode": tracking_number}, ensure_ascii=False, separators=(",", ":")
    )
    form = {
        "RequestType": "8001",
        "EBusinessID": settings.kdniao_ebusiness_id,
        "Language": "zh-cn",
        "DataSign": _sign_query(request_data, settings.kdniao_api_key),
        "RequestData": request_data,
    }

    async with httpx.AsyncClient(timeout=KDNIAO_TIMEOUT_SECONDS) as client:
        resp = await client.post(KDNIAO_QUERY_URL, data=form)
    if resp.status_code != 200:
        raise RuntimeError(f"快递鸟轨迹查询 HTTP {resp.status_code}: {resp.text[:200]}")

    body = resp.json()
    if not body.get("Success"):
        raise RuntimeError(
            f"快递鸟轨迹查询失败: {body.get('Reason') or 'unknown error'}"
        )

    traces = body.get("Traces") or body.get("Routes") or []
    events = []
    for trace in traces:
        description = str(
            trace.get("AcceptStation") or trace.get("Action") or trace.get("Remark") or ""
        )
        events.append({
            "time": str(trace.get("AcceptTime") or trace.get("OcpTime") or ""),
            "location": str(trace.get("AcceptStation") or ""),
            "description": description,
        })

    if events:
        detail = events[-1]["description"] or "轨迹查询成功"
        status = _map_trace_status(detail)
    else:
        status, detail = "pending", "暂无轨迹信息"

    return {
        "carrier": body.get("Company") or tracking_number[:2],
        "tracking_number": body.get("LogisticCode") or tracking_number,
        "status": status,
        "status_detail": detail,
        "estimated_delivery": datetime.now(UTC).isoformat()[:10],
        "source": "kdniao",
        "events": events
        or [{"time": datetime.now(UTC).isoformat(), "location": "", "description": detail}],
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
