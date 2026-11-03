"""Tracking and freight quotes used to answer even when nothing had been asked.

``src/logistics/kdniao.py`` and ``src/logistics/carriers.py`` both had the same
shape: with no credentials, no endpoints, or a *failed* carrier call, they fell
through to a generator that picked a delivery state out of ``sum(ord(c)) % 100``
of the waybill number — 已揽收 / 运输中 — 到达中转站 / 派送中 / 已签收, with an event
"到达上海转运中心" attached.  Nothing in the answer said which of these it was, and
the SOP has dispatch relaying this screen to customers: the invented 已签收 is a
customer being told a parcel arrived.  Freight quotes had the same shape — the
built-in rate table answered a price with no carrier in the loop, and a quote is a
number someone charges money on.

The contract these tests pin is one fact per answer, and no answer at all when
there is none:

* configured 快递鸟 credentials → ``source: "kdniao"``;
* configured carrier endpoint → ``source: "carrier_api"``, and a *failing* endpoint
  raises (``src/logistics/router.py`` renders 502) instead of answering demo data;
* ``LOGISTICS_MOCK_ENABLED=true`` → the demo generator, which is allowed only here
  and labels every row 演示数据 / ``source: "mock"``;
* none of the above → ``501 NOT_IMPLEMENTED`` naming the variable to set.

Waybill numbers carry the same distinction, because the label prints identically
either way: ``tracking_source`` is ``kdniao`` when 快递鸟 returned the number and
``local_placeholder`` when this server assembled one the carrier has never seen —
in which case there is nothing for the tracking endpoint to read.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import settings
from src.core.exceptions import NotImplementedActionException
from src.logistics import carriers, kdniao
from src.logistics.schemas import CreateWaybillRequest
from src.logistics.service import create_waybill as service_create_waybill


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _Client:
    """Stand-in for ``httpx.AsyncClient`` — used so no test can reach the network."""

    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        if self._error:
            raise self._error
        return _Resp(self._payload)

    async def post(self, url, data=None, json=None):
        if self._error:
            raise self._error
        return _Resp(self._payload)


@pytest.fixture(autouse=True)
def _no_demo_data_by_default(monkeypatch):
    """The demo generator is opt-in; a test that wants it says so explicitly."""
    monkeypatch.setattr(settings, "logistics_mock_enabled", False)
    monkeypatch.setattr(settings, "kdniao_ebusiness_id", "")
    monkeypatch.setattr(settings, "kdniao_api_key", "")


def _demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "logistics_mock_enabled", True)


def _kdniao_credentials(monkeypatch):
    monkeypatch.setattr(settings, "kdniao_ebusiness_id", "EBUSINESS-ID")
    monkeypatch.setattr(settings, "kdniao_api_key", "SECRET-KEY")


# ── 快递鸟 轨迹 ──────────────────────────────────────────────────────────────


class TestKdniaoTracking:
    async def test_unconfigured_answers_501(self):
        with pytest.raises(NotImplementedActionException, match="KDNIAO_EBUSINESS_ID") as exc:
            await kdniao.query_tracking("ZT240101ABCD1234")
        assert exc.value.detail["configured"] is False

    async def test_demo_data_is_labelled_every_row(self, monkeypatch):
        _demo_mode(monkeypatch)
        result = await kdniao.query_tracking("ZT240101ABCD1234")
        assert result["source"] == "mock"
        assert result["status_detail"].startswith("【演示数据】")
        assert all("演示数据" in e["description"] for e in result["events"])

    async def test_real_answer_says_kdniao(self, monkeypatch):
        _kdniao_credentials(monkeypatch)
        payload = {
            "Success": True,
            "Company": "zto",
            "LogisticCode": "ZT240101ABCD1234",
            "Traces": [{"AcceptTime": "2026-01-02 08:30:00", "AcceptStation": "到达上海转运中心"}],
        }
        with patch("src.logistics.kdniao.httpx.AsyncClient", lambda **kw: _Client(payload)):
            result = await kdniao.query_tracking("ZT240101ABCD1234")
        assert result["source"] == "kdniao"
        assert result["status"] == "in_transit"
        assert "演示数据" not in result["status_detail"]

    async def test_carrier_failure_propagates(self, monkeypatch):
        """快递鸟 5xx is an error: a screen reading it must not show an invented state."""
        _kdniao_credentials(monkeypatch)
        client = _Client(error=RuntimeError("connection reset"))
        with patch("src.logistics.kdniao.httpx.AsyncClient", lambda **kw: client):
            with pytest.raises(RuntimeError, match="connection reset"):
                await kdniao.query_tracking("ZT240101ABCD1234")


# ── 承运商接口 轨迹 / 运费 ───────────────────────────────────────────────────


class TestCarrierTracking:
    async def test_endpoint_answers_and_says_so(self):
        endpoints = {"zto": "https://mock-api.zto.com/track"}
        payload = {"status": "delivered", "detail": "已签收", "events": []}
        with patch("src.logistics.carriers._get_carrier_endpoints", return_value=endpoints):
            with patch("src.logistics.carriers.httpx.AsyncClient", lambda **kw: _Client(payload)):
                result = await carriers.query_tracking(carriers.CarrierCode.ZTO, "ZT260729TEST")
        assert result["source"] == "carrier_api"
        assert result["status_detail"] == "已签收"

    async def test_failing_endpoint_is_not_an_answer(self, monkeypatch):
        """The demo path is deliberately *not* a fallback here, flag on or off."""
        _demo_mode(monkeypatch)
        endpoints = {"zto": "https://mock-api.zto.com/track"}
        client = _Client(error=RuntimeError("HTTP 504 gateway timeout"))
        with patch("src.logistics.carriers._get_carrier_endpoints", return_value=endpoints):
            with patch("src.logistics.carriers.httpx.AsyncClient", lambda **kw: client):
                with pytest.raises(RuntimeError, match="轨迹接口调用失败"):
                    await carriers.query_tracking(carriers.CarrierCode.ZTO, "ZT260729TEST")

    async def test_no_endpoint_answers_501(self):
        with patch("src.logistics.carriers._get_carrier_endpoints", return_value={}):
            with pytest.raises(NotImplementedActionException, match="CARRIER_API_ENDPOINTS") as exc:
                await carriers.query_tracking(carriers.CarrierCode.ZTO, "ZT260729TEST")
        assert exc.value.detail["configured"] is False

    async def test_demo_mode_labels_the_state(self, monkeypatch):
        _demo_mode(monkeypatch)
        with patch("src.logistics.carriers._get_carrier_endpoints", return_value={}):
            result = await carriers.query_tracking(carriers.CarrierCode.ZTO, "ZT260729TEST")
        assert result["source"] == "mock"
        assert result["status_detail"].startswith("【演示数据】")
        assert "LOGISTICS_MOCK_ENABLED" in result["source_note"]


class TestCarrierQuote:
    async def test_endpoint_answers_and_says_so(self):
        endpoints = {"zto": "https://mock-api.zto.com/estimate"}
        payload = {"cost": 15.0, "days": 2}
        with patch("src.logistics.carriers._get_carrier_endpoints", return_value=endpoints):
            with patch("src.logistics.carriers.httpx.AsyncClient", lambda **kw: _Client(payload)):
                result = await carriers.estimate_shipping(
                    carriers.CarrierCode.ZTO, origin="上海", destination="北京", weight_kg=2.0
                )
        assert result["source"] == "carrier_api"
        assert result["estimated_cost_yuan"] == 15.0

    async def test_failing_endpoint_is_not_a_quote(self, monkeypatch):
        _demo_mode(monkeypatch)
        endpoints = {"zto": "https://mock-api.zto.com/estimate"}
        client = _Client(error=RuntimeError("HTTP 500"))
        with patch("src.logistics.carriers._get_carrier_endpoints", return_value=endpoints):
            with patch("src.logistics.carriers.httpx.AsyncClient", lambda **kw: client):
                with pytest.raises(RuntimeError, match="运费询价失败"):
                    await carriers.estimate_shipping(carriers.CarrierCode.ZTO, weight_kg=1.0)

    async def test_no_endpoint_answers_501(self):
        with patch("src.logistics.carriers._get_carrier_endpoints", return_value={}):
            with pytest.raises(NotImplementedActionException, match="运费询价未配置"):
                await carriers.estimate_shipping(carriers.CarrierCode.ZTO, weight_kg=1.0)

    async def test_demo_rate_is_labelled(self, monkeypatch):
        _demo_mode(monkeypatch)
        with patch("src.logistics.carriers._get_carrier_endpoints", return_value={}):
            result = await carriers.estimate_shipping(carriers.CarrierCode.ZTO, weight_kg=1.0)
        assert result["source"] == "mock"
        assert "演示费率" in result["source_note"]


# ── 面单号的出处 ─────────────────────────────────────────────────────────────


def _fake_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock()
    return db


def _request():
    return CreateWaybillRequest(
        order_id="order-prov-1",
        recipient_name="张三",
        recipient_phone="13800138000",
        recipient_address="广东省深圳市南山区科技园",
        items=[{"sku": "SKU001", "qty": 1}],
        carrier_code="zto",
    )


class TestWaybillNumberProvenance:
    async def test_local_number_says_the_carrier_never_saw_it(self):
        """The label looks the same either way, so the field has to carry the difference."""
        result = await service_create_waybill(_fake_db(), _request())
        assert result["tracking_source"] == "local_placeholder"
        assert "KDNIAO_EBUSINESS_ID" in result["tracking_source_note"]
        assert "轨迹查询与运单追踪均不可用" in result["tracking_source_note"]

    async def test_carrier_number_says_who_issued_it(self, monkeypatch):
        monkeypatch.setattr("src.logistics.service.credentials_configured", lambda: True)
        monkeypatch.setattr(
            "src.logistics.service.kdniao_create_waybill",
            AsyncMock(
                return_value={
                    "tracking_number": "ZT26010200001",
                    "carrier_name": "中通快递",
                    "print_callback_url": "https://waybill.kdniao.com/print/ZT26010200001",
                }
            ),
        )
        result = await service_create_waybill(_fake_db(), _request())
        assert result["tracking_number"] == "ZT26010200001"
        assert result["tracking_source"] == "kdniao"
        assert result["tracking_source_note"] == "面单号由快递鸟返回"
