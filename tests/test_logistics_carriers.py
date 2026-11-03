"""Tests for src.logistics.carriers."""

import pytest

# --- carrier code validation -------------------------------------------------

def test_validate_carrier_valid():
    from src.logistics.carriers import CarrierCode, validate_carrier
    assert validate_carrier("sf") is CarrierCode.SF
    assert validate_carrier("SF") is CarrierCode.SF
    assert validate_carrier("zto") is CarrierCode.ZTO
    assert validate_carrier("yto") is CarrierCode.YTO


def test_validate_carrier_invalid():
    from src.logistics.carriers import validate_carrier
    # Unknown code -> None (not a new enum member)
    assert validate_carrier("unknown") is None
    assert validate_carrier("") is None
    assert validate_carrier("12345") is None


# --- tracking number generation ----------------------------------------------

def test_generate_tracking_number_sf():
    from src.logistics.carriers import CarrierCode, generate_tracking_number
    n = generate_tracking_number(CarrierCode.SF, "order-abc")
    assert len(n) == 16 and n.startswith("SF")


def test_generate_tracking_number_zto():
    from src.logistics.carriers import CarrierCode, generate_tracking_number
    n = generate_tracking_number(CarrierCode.ZTO, "xyz")
    assert len(n) == 16 and n.startswith("ZT")


# --- tracking URL -------------------------------------------------------------

def test_get_tracking_url_sf():
    from src.logistics.carriers import CarrierCode, get_tracking_url
    url = get_tracking_url(CarrierCode.SF, "nu123")
    # SF uses path-segment form: /waybill-detail/nu123 (no query param)
    assert "/waybill-detail/nu123" in url


def test_get_tracking_url_zto():
    from src.logistics.carriers import CarrierCode, get_tracking_url
    url = get_tracking_url(CarrierCode.ZTO, "AB12")
    # ZTO uses query-param form: /track/?nu=...
    assert "/?nu=" in url


# --- mock tracking status (hash-based) ---------------------------------------
# NOTE: hash is deterministic per-char, so test values must match the actual
# bucket ranges of _mock_tracking. Keep these in sync with whatever mapping
# src.logistics.carriers._mock_tracking uses.

def test_mock_tracking_returns_status():
    from src.logistics.carriers import CarrierCode, TrackingStatus, _mock_tracking
    n = "Z" * 10  # hash -> a stable bucket; just assert it's a valid status
    d = _mock_tracking(CarrierCode.ZTO, n)
    assert d["status"] in (s.value for s in TrackingStatus)


@pytest.mark.parametrize("tracking,expected_status", [
    ("d", "picked_up"),     # ord('d')=100 → 100%100=0   → < 20
    ("x", "in_transit"),    # ord('x')=120 → 120%100=20  → < 50
    ("2", "out_for_delivery"),  # ord('2')=50  → 50%100=50  → < 80
    ("P", "delivered"),     # ord('P')=80  → 80%100=80   → < 95
    ("_", "pending"),       # ord('_')=95  → 95%100=95   → else
])
def test_mock_tracking_all_buckets(tracking, expected_status):
    from src.logistics.carriers import CarrierCode, _mock_tracking
    d = _mock_tracking(CarrierCode.ZTO, tracking)
    assert d["status"] == expected_status
    assert d["carrier"] == "zto"
    assert d["carrier_name"] == "中通快递"
    assert d["tracking_number"] == tracking
    assert "tracking_url" in d
    assert "events" in d
    assert len(d["events"]) >= 1


def test_generate_tracking_number_without_order_id():
    from src.logistics.carriers import CarrierCode, generate_tracking_number
    n = generate_tracking_number(CarrierCode.JD)
    assert len(n) == 16 and n.startswith("JD")


def test_get_tracking_url_empty_template():
    from src.logistics.carriers import get_tracking_url
    url = get_tracking_url("unknown", "123")
    assert url == ""


@pytest.mark.asyncio
async def test_estimate_shipping_mock(monkeypatch):
    """The built-in rate table is demo data, reachable only with the flag on."""
    from src.config import settings
    from src.logistics.carriers import CarrierCode, estimate_shipping

    monkeypatch.setattr(settings, "logistics_mock_enabled", True)
    d = await estimate_shipping(CarrierCode.ZTO, origin="上海", destination="北京", weight_kg=5.0)
    # base=8.0 + (5-1)*5 = 8+20 = 28
    assert d["estimated_cost_yuan"] == 28.0
    assert d["estimated_days"] == 3
    assert d["weight_kg"] == 5.0
    assert d["carrier"] == "zto"
    assert d["carrier_name"] == "中通快递"
    assert d["source"] == "mock"
    assert "演示费率" in d["source_note"]


@pytest.mark.asyncio
async def test_estimate_shipping_without_endpoint_says_unconfigured(monkeypatch):
    """A quote is a number someone charges money on: no endpoint, no quote."""
    from src.config import settings
    from src.core.exceptions import NotImplementedActionException
    from src.logistics.carriers import CarrierCode, estimate_shipping

    monkeypatch.setattr(settings, "logistics_mock_enabled", False)
    with pytest.raises(NotImplementedActionException, match="运费询价未配置") as exc:
        await estimate_shipping(CarrierCode.ZTO, weight_kg=1.0)
    assert exc.value.detail["configured"] is False


@pytest.mark.asyncio
async def test_estimate_shipping_mock_1kg(monkeypatch):
    from src.config import settings
    from src.logistics.carriers import CarrierCode, estimate_shipping

    monkeypatch.setattr(settings, "logistics_mock_enabled", True)
    d = await estimate_shipping(CarrierCode.SF, weight_kg=1.0)
    assert d["estimated_cost_yuan"] == 18.0  # base rate, no weight surcharge
    assert d["estimated_days"] == 2


@pytest.mark.asyncio
async def test_estimate_shipping_default_carrier(monkeypatch):
    from src.config import settings
    from src.logistics.carriers import estimate_shipping

    monkeypatch.setattr(settings, "logistics_mock_enabled", True)

    class _FakeCarrier:
        value = "unknown"
    d = await estimate_shipping(_FakeCarrier(), weight_kg=3.0)
    # default base=10.0 + (3-1)*5 = 20
    assert d["estimated_cost_yuan"] == 20.0
    assert d["estimated_days"] == 4
    assert d["source"] == "mock"


@pytest.mark.asyncio
async def test_query_tracking_real_api():
    from unittest.mock import MagicMock, patch

    from src.logistics.carriers import CarrierCode, query_tracking

    endpoints = {"zto": "https://mock-api.zto.com/track"}
    with patch("src.logistics.carriers._get_carrier_endpoints", return_value=endpoints):
        with patch("src.logistics.carriers.httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {
                "status": "delivered",
                "detail": "已签收",
                "estimated_delivery": "2026-07-30",
                "events": [{"time": "2026-07-28T10:00:00", "location": "上海", "description": "已签收"}],
            }
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_resp
            d = await query_tracking(CarrierCode.ZTO, "ZT260729TEST")
            assert d["status"] == "delivered"
            assert d["status_detail"] == "已签收"
            assert d["carrier"] == "zto"
            assert d["source"] == "carrier_api"


@pytest.mark.asyncio
async def test_query_tracking_endpoint_failure_raises_instead_of_answering_demo_data():
    """A timeout used to fall through to 运输中 — 到达中转站, which dispatch relayed to the customer."""
    from unittest.mock import MagicMock, patch

    from src.logistics.carriers import CarrierCode, query_tracking

    endpoints = {"zto": "https://mock-api.zto.com/track"}
    with patch("src.logistics.carriers._get_carrier_endpoints", return_value=endpoints):
        with patch("src.logistics.carriers.httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = Exception("HTTP error")
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_resp
            with pytest.raises(RuntimeError, match="轨迹接口调用失败"):
                await query_tracking(CarrierCode.ZTO, "ZT260729TEST")


@pytest.mark.asyncio
async def test_estimate_shipping_real_api():
    from unittest.mock import MagicMock, patch

    from src.logistics.carriers import CarrierCode, estimate_shipping

    endpoints = {"zto": "https://mock-api.zto.com/estimate"}
    with patch("src.logistics.carriers._get_carrier_endpoints", return_value=endpoints):
        with patch("src.logistics.carriers.httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"cost": 15.0, "days": 2}
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_resp
            d = await estimate_shipping(
                CarrierCode.ZTO, origin="上海", destination="北京", weight_kg=2.0
            )
            assert d["estimated_cost_yuan"] == 15.0
            assert d["estimated_days"] == 2
            assert d["weight_kg"] == 2.0
            assert d["source"] == "carrier_api"


@pytest.mark.asyncio
async def test_estimate_shipping_endpoint_failure_raises_instead_of_answering_a_demo_rate():
    from unittest.mock import MagicMock, patch

    from src.logistics.carriers import CarrierCode, estimate_shipping

    endpoints = {"zto": "https://mock-api.zto.com/estimate"}
    with patch("src.logistics.carriers._get_carrier_endpoints", return_value=endpoints):
        with patch("src.logistics.carriers.httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = Exception("HTTP error")
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_resp
            with pytest.raises(RuntimeError, match="运费询价失败"):
                await estimate_shipping(CarrierCode.ZTO, weight_kg=1.0)


def test_get_carrier_endpoints_with_settings():
    from unittest.mock import patch

    from src.logistics.carriers import _get_carrier_endpoints

    class FakeSettings:
        carrier_api_endpoints_dict = {"sf": "https://api.sf.com/track"}

    # carriers.py binds ``settings`` at import, so the patch has to land on that binding.
    with patch("src.logistics.carriers.settings", FakeSettings()):
        endpoints = _get_carrier_endpoints()
        assert endpoints == {"sf": "https://api.sf.com/track"}


def test_get_carrier_endpoints_error():
    from unittest.mock import MagicMock, patch

    from src.logistics.carriers import _get_carrier_endpoints

    fake = MagicMock()
    del fake.carrier_api_endpoints_dict
    # Malformed CARRIER_API_ENDPOINTS is a config error, not a licence to invent tracking:
    # the read degrades to "unconfigured", and the query below answers 501.
    with patch("src.logistics.carriers.settings", fake):
        endpoints = _get_carrier_endpoints()
        assert endpoints == {}
