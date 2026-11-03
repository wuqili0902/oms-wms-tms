"""Contract tests for POST /api/v1/freight-estimate and estimate_freight().

What was here before was a hard-coded table wearing a service function's name:

    def estimate_freight_sync(...):        # "used by tests that call directly"
        base_rate = {"sf_express": 8.5, "yunda": 6.0, "zto": 7.0, "ems": 9.0}.get(carrier_code or "", 7.0)
        ...
    async def estimate_freight(*args, ...):  # "async alias … used by tests"
        result = estimate_freight_sync(...)
        result["transit_days"] = 2

and ``src/tms/router.py`` called the second one.  So the public quote endpoint
priced every shipment from that table: it never read a FreightTier row, priced an
unrecognised carrier code at a generic 7.0, applied no surcharge, quoted a 2-day
transit for every carrier and service level, and gave the caller no way to tell a
placeholder from a rate-card price.  The request layer also passed
``int(weight_kg)``, so a 5.5 kg shipment was quoted 5 kg.

The estimate now goes through the same tier helpers ``calculate_freight`` uses, and
the response says which pricing produced it.
"""

import uuid
from decimal import Decimal

import pytest

from src.core.exceptions import ValidationException
from src.tms import service as tms_service


@pytest.fixture
async def auth_headers(async_client):
    uname = f"frqest_{uuid.uuid4().hex[:8]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _tier(db, *, carrier="zto", rule_type="weight_tiered", min_value="0",
                max_value=None, price="2.00", surcharge_express="0") -> dict:
    return await tms_service.create_freight_tier(db, {
        "carrier_code": carrier,
        "rule_type": rule_type,
        "min_value": min_value,
        "max_value": max_value,
        "price_per_unit": price,
        "surcharge_express": surcharge_express,
    })


class TestRateCardPricing:
    async def test_configured_tier_prices_the_estimate(self, db_session):
        await _tier(db_session, carrier="zto", rule_type="flat_rate", price="123.45")

        result = await tms_service.estimate_freight(
            db_session, carrier_code="zto", service_type="standard",
            distance_km=100, weight_kg=10,
        )

        assert Decimal(result["estimated_cost"]) == Decimal("123.45"), (
            "a flat-rate tier is a fixed price; multiplying it by weight is what the "
            "placeholder table was doing to every carrier"
        )
        assert result["pricing_source"] == "rate_card"
        assert result["rule_type"] == "flat_rate"

    async def test_distance_tiered_tier_prices_on_kilometres(self, db_session):
        await _tier(db_session, carrier="zto", rule_type="distance_tiered", price="0.80")

        result = await tms_service.estimate_freight(
            db_session, carrier_code="zto", service_type="standard",
            distance_km=350, weight_kg=10,
        )

        assert Decimal(result["estimated_cost"]) == Decimal("280.00")

    async def test_weight_bracket_selects_the_right_tier(self, db_session):
        await _tier(db_session, carrier="sf_express", min_value="0", max_value="10", price="8.50")
        await _tier(db_session, carrier="sf_express", min_value="10", max_value=None, price="7.20")

        light = await tms_service.estimate_freight(
            db_session, carrier_code="sf_express", distance_km=100, weight_kg=5,
        )
        heavy = await tms_service.estimate_freight(
            db_session, carrier_code="sf_express", distance_km=100, weight_kg=25,
        )

        assert Decimal(light["estimated_cost"]) == Decimal("42.50")
        assert Decimal(heavy["estimated_cost"]) == Decimal("180.00")

    async def test_express_uses_the_configured_surcharge(self, db_session):
        await _tier(db_session, carrier="ems", price="2.00", surcharge_express="5.00")

        standard = await tms_service.estimate_freight(
            db_session, carrier_code="ems", service_type="standard", distance_km=100, weight_kg=5,
        )
        express = await tms_service.estimate_freight(
            db_session, carrier_code="ems", service_type="express", distance_km=100, weight_kg=5,
        )

        assert Decimal(standard["estimated_cost"]) == Decimal("10.00")
        assert Decimal(express["estimated_cost"]) == Decimal("15.00"), (
            "the surcharge the rate card carries replaces a made-up 1.3 multiplier"
        )

    async def test_a_rate_card_that_does_not_cover_the_shipment_says_so(self, db_session):
        """No matching bracket is a quote failure, not an excuse to guess."""
        await _tier(db_session, carrier="yunda", min_value="0", max_value="10", price="6.00")

        with pytest.raises(ValidationException, match="yunda"):
            await tms_service.estimate_freight(
                db_session, carrier_code="yunda", distance_km=100, weight_kg=50,
            )


class TestPlaceholderTable:
    async def test_carrier_without_tiers_is_priced_from_the_table_and_says_so(self, db_session, caplog):
        with caplog.at_level("INFO"):
            result = await tms_service.estimate_freight(
                db_session, carrier_code="yunda", service_type="standard",
                distance_km=100, weight_kg=10,
            )

        # 6.0 per 100 km × 100 km + 10 kg × 0.50 = 11.00
        assert Decimal(result["estimated_cost"]) == Decimal("11.00")
        assert result["pricing_source"] == "placeholder_table"
        assert any("placeholder table" in rec.message for rec in caplog.records), (
            "a placeholder price has to be visible in the log as well as the response"
        )

    async def test_carrier_missing_from_the_table_still_gets_a_quote(self, db_session):
        """jd_logistics is a real carrier code that the table never covered."""
        result = await tms_service.estimate_freight(
            db_session, carrier_code="jd_logistics", service_type="standard",
            distance_km=100, weight_kg=10,
        )

        # default 7.0 + 10 × 0.50
        assert Decimal(result["estimated_cost"]) == Decimal("12.00")
        assert result["pricing_source"] == "placeholder_table"

    async def test_service_level_still_changes_the_placeholder_price(self, db_session):
        standard = await tms_service.estimate_freight(
            db_session, carrier_code="yunda", service_type="standard", distance_km=100, weight_kg=10,
        )
        overnight = await tms_service.estimate_freight(
            db_session, carrier_code="yunda", service_type="overnight", distance_km=100, weight_kg=10,
        )

        assert Decimal(overnight["estimated_cost"]) > Decimal(standard["estimated_cost"])


class TestUnknownInputs:
    @pytest.mark.parametrize("carrier", ["sf", "not_a_carrier", ""])
    async def test_unknown_carrier_code_is_rejected(self, db_session, carrier):
        """'sf' is a valid waybill carrier and not a valid TMS one.

        The table used to answer it with a generic 7.0, which is how a carrier
        name typo became a plausible-looking price.
        """
        with pytest.raises(ValidationException, match="carrier_code"):
            await tms_service.estimate_freight(
                db_session, carrier_code=carrier, distance_km=100, weight_kg=10,
            )

    async def test_unknown_service_type_is_rejected(self, db_session):
        with pytest.raises(ValidationException, match="service_type"):
            await tms_service.estimate_freight(
                db_session, carrier_code="zto", service_type="same_day",
                distance_km=100, weight_kg=10,
            )

    async def test_endpoint_reports_an_unknown_carrier_as_422(self, async_client, auth_headers):
        resp = await async_client.post(
            "/api/v1/freight-estimate?carrier_code=not_a_carrier&distance_km=100&weight_kg=10",
            headers=auth_headers,
        )
        assert resp.status_code == 422, resp.text[:200]
        assert "not_a_carrier" in resp.text


class TestEstimateEndpoint:
    async def test_fractional_weight_is_not_truncated(self, async_client, auth_headers):
        await async_client.post("/api/v1/freight-tiers", json={
            "carrier_code": "zto", "rule_type": "weight_tiered",
            "min_value": 0, "max_value": None, "price_per_unit": 2.00,
        }, headers=auth_headers)

        resp = await async_client.post(
            "/api/v1/freight-estimate?carrier_code=zto&service_type=standard"
            "&distance_km=100&weight_kg=5.5",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text[:200]
        data = resp.json()
        assert Decimal(str(data["estimated_cost"])) == Decimal("11.00"), (
            "5.5 kg must not be quoted as 5 kg — int(weight_kg) gave away 0.5 kg per shipment"
        )
        assert data["pricing_source"] == "rate_card"

    async def test_transit_days_is_not_invented(self, async_client, auth_headers):
        resp = await async_client.post(
            "/api/v1/freight-estimate?carrier_code=zto&service_type=express"
            "&distance_km=1200&weight_kg=5.5",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text[:200]
        assert resp.json()["transit_days"] is None, (
            "the endpoint used to answer 2 days for every carrier and service level; "
            "a transit promise needs a lane, which this request does not name"
        )


class TestNoMorePlaceholderAliases:
    """The aliases were the defect, not a convenience.

    A name that callers use and that is documented "used by tests" is how the
    placeholder table ended up behind the public quote endpoint, and
    ``get_pod_via_alias`` opened its own database session outside the caller's
    transaction.  Asserting their absence keeps the next convenience alias from
    being added to the same file.
    """

    @pytest.mark.parametrize("name", [
        "estimate_freight_sync",
        "record_tracking_event",
        "get_tracking_events",
        "change_transport_status_alias",
        "create_exception_optional_order",
        "get_pod_via_alias",
        "create_pod_via_alias",
        "_make_pod_alias",
        "_create_exception_alias",
    ])
    def test_alias_is_gone(self, name):
        assert not hasattr(tms_service, name), (
            f"src/tms/service.py defines {name} again: point callers at the real function "
            "instead of adding a second name for it"
        )
