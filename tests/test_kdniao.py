"""Tests for src.logistics.kdniao — Kdniao electronic waybill SDK."""

import base64
import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest

from src.config import settings
from src.core.exceptions import NotImplementedActionException
from src.logistics.kdniao import (
    CARRIER_NAMES,
    CARRIER_TRACKING_URLS,
    CarrierCode,
    _sign_query,
    _sign_waybill,
    create_waybill,
    credentials_configured,
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

    async def test_local_number_says_the_carrier_never_issued_it(self):
        """A label prints the same either way, so the number has to say where it came from."""
        result = await create_waybill(
            order_id="order-004",
            recipient_name="赵六",
            recipient_phone="13600136000",
            recipient_address="成都市武侯区",
            items=[{"sku": "SKU004", "qty": 1}],
        )
        assert result["source"] == "local_placeholder"
        assert "快递侧并不存在这张面单" in result["source_note"]


class TestQueryTracking:
    """Demo tracking is opt-in (LOGISTICS_MOCK_ENABLED) and every row is labelled."""

    @pytest.fixture(autouse=True)
    def _demo_mode(self, monkeypatch):
        monkeypatch.setattr(settings, "logistics_mock_enabled", True)

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

    async def test_every_row_is_labelled_demo_data(self):
        """The state comes out of a hash of the waybill number — the screen must say so."""
        result = await query_tracking("ZT240101ABCD1234")
        assert result["source"] == "mock"
        assert result["status_detail"].startswith("【演示数据】")
        assert "演示数据" in result["source_note"]
        for event in result["events"]:
            assert "演示数据" in event["description"]


class TestQueryTrackingUnconfigured:
    """Without 快递鸟 credentials the endpoint has no answer, and used to invent one."""

    async def test_raises_501_naming_the_credentials(self, monkeypatch):
        monkeypatch.setattr(settings, "logistics_mock_enabled", False)
        with pytest.raises(NotImplementedActionException, match="KDNIAO_EBUSINESS_ID") as exc:
            await query_tracking("ZT240101ABCD1234")
        assert exc.value.detail["configured"] is False
        assert exc.value.detail["tracking_number"] == "ZT240101ABCD1234"

    async def test_mock_flag_is_what_unlocks_demo_data(self, monkeypatch):
        monkeypatch.setattr(settings, "logistics_mock_enabled", True)
        assert (await query_tracking("ZT240101ABCD1234"))["source"] == "mock"


class TestPrintCallbackUrl:
    def test_returns_url(self):
        url = print_callback_url("ZT240101ABCD1234")
        assert isinstance(url, str)
        assert len(url) > 0

    def test_url_contains_tracking(self):
        tn = "ZT240101ABCD1234"
        url = print_callback_url(tn)
        assert tn in url


# ── Real API mode (httpx transport patched — never hits the network) ─────────


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


def _install_fake_httpx(monkeypatch, payload, status_code=200, recorder=None):
    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, data=None, **kwargs):
            if recorder is not None:
                recorder["url"] = url
                recorder["data"] = data
            return _FakeResponse(payload, status_code)

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)


def _configure_credentials(monkeypatch):
    monkeypatch.setattr(settings, "kdniao_ebusiness_id", "EBUSINESS-TEST")
    monkeypatch.setattr(settings, "kdniao_api_key", "SECRET-KEY")


class TestRealModePlumbing:
    def test_sign_waybill_matches_spec(self):
        # Base64(raw MD5(Data + ApiKey))
        expected = base64.b64encode(
            hashlib.md5(b"DATASECRET-KEY").digest()
        ).decode("ascii")
        assert _sign_waybill("DATA", "SECRET-KEY") == expected

    def test_sign_query_matches_spec(self):
        expected = hashlib.md5(b"DATASECRET-KEY").hexdigest().upper()
        assert _sign_query("DATA", "SECRET-KEY") == expected

    def test_credentials_not_configured_by_default(self, monkeypatch):
        monkeypatch.setattr(settings, "kdniao_ebusiness_id", "")
        monkeypatch.setattr(settings, "kdniao_api_key", "")
        assert credentials_configured() is False


class TestCreateWaybillReal:
    async def test_success_uses_api_waybill_code(self, monkeypatch):
        _configure_credentials(monkeypatch)
        captured = {}
        payload = {
            "Success": True,
            "Result": {
                "Code": "101",
                "Message": "用户下单成功",
                "WaybillCode": "ZT-REAL-999",
                "PrintSettings": [{"PrintSettingsURL": "http://print"}],
            },
        }
        _install_fake_httpx(monkeypatch, payload, recorder=captured)

        result = await create_waybill(
            order_id="order-real-1",
            recipient_name="张三",
            recipient_phone="13800138000",
            recipient_address="广东省深圳市南山区",
            items=[{"sku": "SKU001", "qty": 2}],
            carrier_code=CarrierCode.ZTO,
        )
        assert result["status"] == "success"
        assert result["tracking_number"] == "ZT-REAL-999"
        assert result["waybill_code"] == "ZT-REAL-999"
        assert result["print_settings"]

        # The submitted form must be signed consistently with its own Data.
        form = captured["data"]
        assert form["RequestType"] == "101"
        assert form["EBusinessID"] == "EBUSINESS-TEST"
        assert form["DataSign"] == _sign_waybill(form["Data"], "SECRET-KEY")
        sent_data = json.loads(form["Data"])
        assert sent_data["OrderCode"] == "order-real-1"

    async def test_api_business_failure_raises(self, monkeypatch):
        _configure_credentials(monkeypatch)
        _install_fake_httpx(
            monkeypatch, {"Success": False, "Reason": "账户余额不足"}
        )
        with pytest.raises(RuntimeError, match="下单失败"):
            await create_waybill("o1", "N1", "P1", "A1", [], carrier_code=CarrierCode.ZTO)

    async def test_http_error_raises(self, monkeypatch):
        _configure_credentials(monkeypatch)
        _install_fake_httpx(monkeypatch, {"error": "boom"}, status_code=500)
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await create_waybill("o1", "N1", "P1", "A1", [], carrier_code=CarrierCode.ZTO)

    async def test_missing_credentials_falls_back_to_a_labelled_placeholder(self, monkeypatch):
        monkeypatch.setattr(settings, "kdniao_ebusiness_id", "")
        monkeypatch.setattr(settings, "kdniao_api_key", "")
        result = await create_waybill("o1", "N1", "P1", "A1", [], carrier_code=CarrierCode.ZTO)
        assert result["tracking_number"].startswith("ZT")
        assert "callback=1" in result["print_callback_url"]
        assert result["source"] == "local_placeholder"


class TestQueryTrackingReal:
    async def test_traces_parsed_and_mapped(self, monkeypatch):
        _configure_credentials(monkeypatch)
        captured = {}
        payload = {
            "Success": True,
            "Company": "zto",
            "LogisticCode": "ZT240101ABCD1234",
            "Traces": [
                {"AcceptTime": "2026-01-01 10:00:00", "AcceptStation": "深圳网点 已揽收"},
                {"AcceptTime": "2026-01-02 08:30:00", "AcceptStation": "到达上海转运中心"},
            ],
        }
        _install_fake_httpx(monkeypatch, payload, recorder=captured)

        result = await query_tracking("ZT240101ABCD1234")
        assert result["status"] == "in_transit"
        assert result["carrier"] == "zto"
        assert result["source"] == "kdniao"
        assert len(result["events"]) == 2
        assert result["events"][1]["description"] == "到达上海转运中心"

        form = captured["data"]
        assert form["RequestType"] == "8001"
        assert form["DataSign"] == _sign_query(form["RequestData"], "SECRET-KEY")

    async def test_delivered_status(self, monkeypatch):
        _configure_credentials(monkeypatch)
        _install_fake_httpx(monkeypatch, {
            "Success": True,
            "Traces": [{"AcceptTime": "2026-01-03 12:00:00", "AcceptStation": "派送成功 已签收"}],
        })
        result = await query_tracking("ZT240101ABCD1234")
        assert result["status"] == "delivered"

    async def test_success_false_raises(self, monkeypatch):
        _configure_credentials(monkeypatch)
        _install_fake_httpx(
            monkeypatch, {"Success": False, "Reason": "运单号不存在"}
        )
        with pytest.raises(RuntimeError, match="轨迹查询失败"):
            await query_tracking("ZT000")

    async def test_empty_traces_pending(self, monkeypatch):
        _configure_credentials(monkeypatch)
        _install_fake_httpx(monkeypatch, {"Success": True, "Traces": []})
        result = await query_tracking("ZT240101ABCD1234")
        assert result["status"] == "pending"
        assert result["events"][0]["description"] == "暂无轨迹信息"


class TestServiceWiring:
    """With credentials configured, service.create_waybill stores the carrier's
    waybill number instead of the local placeholder generator."""

    async def test_service_uses_real_waybill_code(self, db_session, monkeypatch):
        from src.logistics import service as logistics_service
        from src.logistics.schemas import CreateWaybillRequest

        _configure_credentials(monkeypatch)

        async def _fake_kdniao_create(**kwargs):
            return {
                "tracking_number": "REAL-WB-001",
                "carrier_name": "中通快递",
                "print_callback_url": "https://track.zto.com/?nu=REAL-WB-001",
                "status": "success",
            }

        monkeypatch.setattr(logistics_service, "kdniao_create_waybill", _fake_kdniao_create)

        req = CreateWaybillRequest(
            order_id="ORD-REAL-001",
            recipient_name="张三",
            recipient_phone="13800138000",
            recipient_address="广东省深圳市",
            items=[],
            carrier_code="zto",
        )
        result = await logistics_service.create_waybill(db_session, req)
        assert result["tracking_number"] == "REAL-WB-001"
        assert result["label_url"] == "https://track.zto.com/?nu=REAL-WB-001"
