"""Tests for src.logistics.kdniao — Kdniao electronic waybill SDK."""

import hashlib
from datetime import UTC, datetime

from src.logistics.kdniao import (
    CARRIER_NAMES,
    CARRIER_TRACKING_URLS,
    CarrierCode,
    create_waybill,
    generate_tracking_number,
    get_tracking_url,
    print_callback_url,
    query_tracking,
    validate_carrier,
)


class TestCarrierCode:
    def test_constants(self):
        assert CarrierCode.SF == "sf"
        assert CarrierCode.ZTO == "zto"
        assert CarrierCode.YTO == "yto"
        assert CarrierCode.STO == "sto"
        assert CarrierCode.YUNDA == "yunda"
        assert CarrierCode.EMS == "ems"
        assert CarrierCode.JD == "jd"

    def test_all_carriers_have_names(self):
        for attr in vars(CarrierCode):
            if not attr.startswith('_'):
                code = getattr(CarrierCode, attr)
                assert code in CARRIER_NAMES

    def test_all_carriers_have_tracking_urls(self):
        for attr in vars(CarrierCode):
            if not attr.startswith('_'):
                code = getattr(CarrierCode, attr)
                assert code in CARRIER_TRACKING_URLS


class TestGenerateTrackingNumber:
    def test_returns_string(self):
        tn = generate_tracking_number("zto", "order-001")
        assert isinstance(tn, str)
        assert len(tn) > 10

    def test_contains_carrier_prefix(self):
        tn = generate_tracking_number("sf", "order-001")
        assert tn.startswith("SF")

    def test_deterministic_with_order_id(self):
        tn1 = generate_tracking_number("zto", "order-001")
        tn2 = generate_tracking_number("zto", "order-001")
        assert tn1 == tn2

    def test_different_order_different_number(self):
        tn1 = generate_tracking_number("zto", "order-001")
        tn2 = generate_tracking_number("zto", "order-002")
        assert tn1 != tn2

    def test_prefixes(self):
        assert generate_tracking_number("sf", "x").startswith("SF")
        assert generate_tracking_number("zto", "x").startswith("ZT")
        assert generate_tracking_number("yto", "x").startswith("YT")
        assert generate_tracking_number("sto", "x").startswith("ST")
        assert generate_tracking_number("yunda", "x").startswith("YD")
        assert generate_tracking_number("ems", "x").startswith("EM")
        assert generate_tracking_number("jd", "x").startswith("JD")

    def test_unknown_carrier_fallback(self):
        tn = generate_tracking_number("unknown", "order-001")
        assert tn.startswith("XX")

    def test_contains_today_date(self):
        today = datetime.now(UTC).strftime("%y%m%d")
        tn = generate_tracking_number("zto", "order-001")
        assert today in tn

    def test_contains_order_hash(self):
        order_id = "order-001"
        suffix = hashlib.md5(order_id.encode()).hexdigest()[:8].upper()
        tn = generate_tracking_number("zto", order_id)
        assert tn.endswith(suffix)

    def test_generates_without_order_id(self):
        tn = generate_tracking_number("zto")
        assert isinstance(tn, str)
        assert len(tn) > 10


class TestGetTrackingUrl:
    def test_known_carrier(self):
        url = get_tracking_url("zto", "ZT123456")
        assert "{tracking}" not in url
        assert "ZT123456" in url

    def test_unknown_carrier(self):
        url = get_tracking_url("unknown", "XX123")
        assert url == ""

    def test_sf_uses_query_param(self):
        url = get_tracking_url("sf", "SF123456")
        assert "sf-express.com" in url
        assert "SF123456" in url


class TestValidateCarrier:
    def test_valid_carrier(self):
        code = validate_carrier("zto")
        assert code == CarrierCode.ZTO

    def test_valid_uppercase(self):
        code = validate_carrier("ZTO")
        assert code == CarrierCode.ZTO

    def test_valid_mixed_case(self):
        code = validate_carrier("YunDa")
        assert code == CarrierCode.YUNDA

    def test_invalid_carrier(self):
        code = validate_carrier("nonexistent")
        assert code is None

    def test_empty_string(self):
        code = validate_carrier("")
        assert code is None


class TestCreateWaybill:
    async def test_successful_creation(self):
        result = await create_waybill(
            order_id="order-001",
            recipient_name="张三",
            recipient_phone="13800138000",
            recipient_address="广东省深圳市南山区科技园",
            items=[{"sku": "SKU001", "qty": 2}],
            carrier_code=CarrierCode.ZTO,
        )
        assert result["status"] == "success"
        assert result["tracking_number"].startswith("ZT")
        assert result["carrier"] == "zto"
        assert result["carrier_name"] == "中通快递"
        assert "callback=1" in result["print_callback_url"]

    async def test_returns_tracking_number(self):
        result = await create_waybill(
            order_id="order-002",
            recipient_name="李四",
            recipient_phone="13900139000",
            recipient_address="北京市朝阳区",
            items=[{"sku": "SKU002", "qty": 1}],
            carrier_code=CarrierCode.SF,
        )
        assert result["tracking_number"].startswith("SF")

    async def test_default_carrier_is_zto(self):
        result = await create_waybill(
            order_id="order-003",
            recipient_name="王五",
            recipient_phone="13700137000",
            recipient_address="上海市浦东新区",
            items=[{"sku": "SKU003", "qty": 3}],
        )
        assert result["carrier"] == "zto"


class TestQueryTracking:
    async def test_returns_dict(self):
        result = await query_tracking("ZT240101ABCD1234")
        assert isinstance(result, dict)
        assert "status" in result
        assert "tracking_number" in result
        assert "events" in result

    async def test_deterministic_status(self):
        tn = "ZT240101ABCD1234"
        result1 = await query_tracking(tn)
        result2 = await query_tracking(tn)
        assert result1["status"] == result2["status"]

    async def test_events_contain_timeline(self):
        result = await query_tracking("ZT240101ABCD1234")
        assert len(result["events"]) >= 1
        assert "time" in result["events"][0]
        assert "description" in result["events"][0]

    async def test_carrier_derived_from_prefix(self):
        result = await query_tracking("SF240101ABCD1234")
        assert result["carrier"] == "SF"


class TestPrintCallbackUrl:
    def test_returns_url(self):
        url = print_callback_url("ZT240101ABCD1234")
        assert isinstance(url, str)
        assert len(url) > 0

    def test_url_contains_tracking(self):
        tn = "ZT240101ABCD1234"
        url = print_callback_url(tn)
        assert tn in url
