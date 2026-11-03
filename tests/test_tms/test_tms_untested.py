"""Tests for TMS functions with zero or near-zero coverage."""
import uuid
from decimal import Decimal

import pytest

from src.core.exceptions import NotFoundException
from src.tms import service as tms_service
from src.tms.models import CarrierCode, FreightRule, FreightTier


class TestUpdateCarrierRate:
    """update_carrier_rate — upserts freight tiers."""

    @pytest.mark.asyncio
    async def test_insert_new_tiers(self, db_session):
        count = await tms_service.update_carrier_rate(db_session, "sf_express", [
            {"rule_type": "weight_tiered", "min_value": "0", "max_value": "5", "price_per_unit": "10"},
            {"rule_type": "weight_tiered", "min_value": "5", "max_value": "20", "price_per_unit": "20"},
        ])
        assert count == 2
        from sqlalchemy import select
        result = await db_session.execute(select(FreightTier).where(FreightTier.carrier_code == CarrierCode.SF_EXPRESS))
        tiers = result.scalars().all()
        assert len(tiers) == 2

    @pytest.mark.asyncio
    async def test_upsert_existing_tier(self, db_session):
        tier = FreightTier(
            id=uuid.uuid4(), carrier_code=CarrierCode.SF_EXPRESS,
            rule_type=FreightRule.WEIGHT_TIERED,
            min_value=Decimal("0"), max_value=Decimal("5"),
            price_per_unit=Decimal("10"), surcharge_express=Decimal("0"),
        )
        db_session.add(tier)
        await db_session.flush()

        count = await tms_service.update_carrier_rate(db_session, "sf_express", [
            {
                "rule_type": "weight_tiered", "min_value": "0",
                "max_value": "10", "price_per_unit": "15",
                "surcharge_express": "3",
            },
        ])
        assert count == 1
        await db_session.refresh(tier)
        assert tier.price_per_unit == Decimal("15")
        assert tier.max_value == Decimal("10")
        assert tier.surcharge_express == Decimal("3")

    @pytest.mark.asyncio
    async def test_accepts_dict_with_tiers_key(self, db_session):
        count = await tms_service.update_carrier_rate(db_session, "zto", {
            "tiers": [
                {"rule_type": "flat_rate", "min_value": "0", "price_per_unit": "50"},
            ]
        })
        assert count == 1

    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self, db_session):
        count = await tms_service.update_carrier_rate(db_session, "sf_express", [])
        assert count == 0


class TestUpdatePod:
    """update_pod — updates existing POD record."""

    @pytest.mark.asyncio
    async def test_update_signed_by(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Test",
            "delivery_address": {"province": "Guangdong", "city": "Shenzhen"},
        })
        pod = await tms_service.create_pod(db_session, order["id"], {
            "signed_by": "Old Name",
        })
        assert pod["signed_by"] == "Old Name"

        updated = await tms_service.update_pod(db_session, order["id"], {
            "signed_by": "New Name",
            "notes": "Updated POD",
        })
        assert updated["signed_by"] == "New Name"
        assert updated["notes"] == "Updated POD"

    @pytest.mark.asyncio
    async def test_update_pod_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.update_pod(db_session, str(uuid.uuid4()), {"signed_by": "X"})

    @pytest.mark.asyncio
    async def test_update_pod_invalid_uuid(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.update_pod(db_session, "not-a-uuid", {"signed_by": "X"})


class TestRecordForecastObservation:
    """record_forecast_observation — records ML data point."""

    @pytest.mark.asyncio
    async def test_records_observation(self, db_session):
        result = await tms_service.record_forecast_observation(db_session, {
            "origin_city": "Wuhan",
            "destination_city": "Changsha",
            "count": 42,
        })
        assert result["status"] == "ok"
        assert result["key"] == "Wuhan-Changsha"

    @pytest.mark.asyncio
    async def test_records_with_missing_cities(self, db_session):
        """Used to record this as key ``"-"``: a lane no order will ever look up.

        An observation is a lane-day, so the lane is part of what is being said.
        """
        from src.core.exceptions import ValidationException

        with pytest.raises(ValidationException) as exc:
            await tms_service.record_forecast_observation(db_session, {"count": 10})
        assert "origin_city" in str(exc.value)

        with pytest.raises(ValidationException):
            await tms_service.record_forecast_observation(db_session, {"count": "八百"})


class TestGetForecast:
    """get_forecast — retrieves ML forecast points."""

    @pytest.mark.asyncio
    async def test_get_forecast(self, db_session):
        await tms_service.record_forecast_observation(db_session, {
            "origin_city": "Wuhan",
            "destination_city": "Changsha",
            "count": 10,
        })
        points = await tms_service.get_forecast(db_session, {
            "origin_city": "Wuhan",
            "destination_city": "Changsha",
            "days": 3,
        })
        assert isinstance(points, list)

    @pytest.mark.asyncio
    async def test_get_forecast_default_days(self, db_session):
        points = await tms_service.get_forecast(db_session, {
            "origin_city": "A",
            "destination_city": "B",
        })
        assert isinstance(points, list)


class TestGetPod:
    """get_pod — retrieves existing POD."""

    @pytest.mark.asyncio
    async def test_get_pod_exists(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Test",
            "delivery_address": {"province": "Guangdong", "city": "Shenzhen"},
        })
        await tms_service.create_pod(db_session, order["id"], {"signed_by": "Alice"})
        pod = await tms_service.get_pod(db_session, order["id"])
        assert pod is not None
        assert pod["signed_by"] == "Alice"

    @pytest.mark.asyncio
    async def test_get_pod_not_found(self, db_session):
        pod = await tms_service.get_pod(db_session, str(uuid.uuid4()))
        assert pod is None


class TestListTransportOrdersFilter:
    """list_transport_orders — filter by status and carrier_code."""

    @pytest.mark.asyncio
    async def test_filter_by_status(self, db_session):
        await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "A",
            "delivery_address": {"province": "Guangdong", "city": "Shenzhen"},
        })
        items, total = await tms_service.list_transport_orders(db_session, status="draft")
        assert total >= 1

    @pytest.mark.asyncio
    async def test_filter_by_carrier_code(self, db_session):
        await tms_service.create_transport_order(db_session, {
            "carrier_code": "zto",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "B",
            "delivery_address": {"province": "Guangdong", "city": "Shenzhen"},
        })
        items, total = await tms_service.list_transport_orders(db_session, carrier_code="zto")
        assert total >= 1

    @pytest.mark.asyncio
    async def test_filter_combined(self, db_session):
        items, total = await tms_service.list_transport_orders(
            db_session, status="dispatched", carrier_code="sf_express"
        )
        assert total == 0


class TestListCarrierRoutesFilter:
    """list_carrier_routes — filter by carrier_code."""

    @pytest.mark.asyncio
    async def test_filter_by_carrier_code(self, db_session):
        await tms_service.add_carrier_route(db_session, {
            "carrier_code": "sf_express",
            "origin_city": "Wuhan",
            "dest_city": "Changsha",
            "distance_km": 350,
            "transit_hours": 4,
            "base_price_per_kg": "1.5",
        })
        result = await tms_service.list_carrier_routes(db_session, carrier_code="sf_express")
        assert len(result) >= 1


class TestListHubConnectionsFilter:
    """list_hub_connections — filter by hub_code."""

    @pytest.mark.asyncio
    async def test_filter_by_hub_code(self, db_session):
        """Types are the model's vocabulary.

        These bodies asked for ``"distribution"`` and ``"sorting"``: the service
        read ``data.get("type")``, never the key sent, so both hubs were silently
        created as ``primary``.  A type the hub network does not have is now
        refused by the name of the vocabulary it is outside of.
        """
        hub = await tms_service.create_hub(db_session, {
            "code": "HUB-TEST-CONN", "name": "Test Hub",
            "hub_type": "primary", "city": "Wuhan",
        })
        hub2 = await tms_service.create_hub(db_session, {
            "code": "HUB-TEST-CONN2", "name": "Test Hub 2",
            "hub_type": "secondary", "city": "Changsha",
        })
        await tms_service.add_hub_connection(db_session, {
            "from_hub_code": hub["code"], "to_hub_code": hub2["code"],
            "distance_km": 100, "transit_hours": 2,
        })
        result = await tms_service.list_hub_connections(db_session, hub_code="HUB-TEST-CONN")
        assert len(result) >= 1
        # The spelling the caller used is the type the hub got.
        assert hub["hub_type"] == "primary"
        assert hub2["hub_type"] == "secondary"


class TestTrainForecast:
    """train_forecast — batch-trains the ML forecast model from historical transport orders."""

    @pytest.mark.asyncio
    async def test_returns_status_ok(self, db_session):
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_result = MagicMock()
        mock_result.all.return_value = []
        db_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.tms.ml.forecast.forecaster") as mock_fc:
            mock_fc.add_observation = MagicMock()
            result = await tms_service.train_forecast(db_session, months=6)
        assert result["status"] == "ok"
        assert result["trained"] == 0

    @pytest.mark.asyncio
    async def test_with_orders(self, db_session):
        """Orders on one lane and one day are one observation, counted.

        The rows are the three columns the query selects — the day bucket is
        Python's, because ``date_trunc`` is a PostgreSQL function and the
        training run used to raise everywhere else.
        """
        from datetime import UTC, datetime
        from unittest.mock import AsyncMock, MagicMock, patch

        day = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
        rows = [(
            {"city": "Shanghai"}, {"city": "Beijing"}, day,
        )] * 5

        mock_result = MagicMock()
        mock_result.all.return_value = rows
        db_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.tms.ml.forecast.forecaster") as mock_fc:
            mock_fc.add_observation = MagicMock()
            result = await tms_service.train_forecast(db_session, months=12)
        assert result["status"] == "ok"
        assert result["trained"] == 1
        assert result["skipped"] == 0
        mock_fc.add_observation.assert_called_once_with("Shanghai-Beijing", 5.0)

    @pytest.mark.asyncio
    async def test_null_addresses(self, db_session):
        """An order whose address names no city trains nothing — and says so.

        It used to be trained on as the lane ``"-"``, a city pair no lookup can
        ask for, and counted in ``trained`` as if it had taught the model
        something.
        """
        from datetime import UTC, datetime
        from unittest.mock import AsyncMock, MagicMock, patch

        rows = [(None, None, datetime(2026, 5, 6, tzinfo=UTC))] * 2

        mock_result = MagicMock()
        mock_result.all.return_value = rows
        db_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.tms.ml.forecast.forecaster") as mock_fc:
            mock_fc.add_observation = MagicMock()
            result = await tms_service.train_forecast(db_session, months=3)
        assert result["trained"] == 0
        assert result["skipped"] == 2
        mock_fc.add_observation.assert_not_called()
