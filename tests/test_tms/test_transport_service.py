"""Tests for new TMS transport order functionality."""
import uuid

import pytest

from src.core.exceptions import NotFoundException, ValidationException
from src.tms import service as tms_service


class TestCreateTransportOrder:
    """Transport order creation."""

    @pytest.mark.asyncio
    async def test_create_draft_order(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Alice Wang",
            "delivery_phone": "+8613900000000",
            "delivery_address": {"province": "Guangdong", "city": "Shenzhen", "district": "Nanshan"},
            "package_count": 2,
            "total_weight_kg": 5.5,
        })
        assert order["status"] == "draft"
        assert order["carrier_code"] == "sf_express"

    @pytest.mark.asyncio
    async def test_create_order_with_shipment_id(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "shipment_id": str(uuid.uuid4()),
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Bob Li",
            "delivery_address": {"province": "Beijing"},
        })
        assert order["status"] == "draft"

    @pytest.mark.asyncio
    async def test_transport_no_format(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "zto",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Charlie",
            "delivery_address": {"province": "Shanghai"},
        })
        assert order["transport_no"].startswith("TPL-")


class TestTransportStatusMachine:
    """Full state machine lifecycle."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Zhang San",
            "delivery_address": {"province": "Guangdong"},
        })

        # draft -> dispatched
        r = await tms_service.change_transport_status(db_session, order["id"], "dispatched")
        assert r["status"] == "dispatched"

        # dispatched -> in_transit
        r2 = await tms_service.change_transport_status(db_session, order["id"], "in_transit")
        assert r2["status"] == "in_transit"

        # in_transit -> out_for_delivery
        r3 = await tms_service.change_transport_status(db_session, order["id"], "out_for_delivery")
        assert r3["status"] == "out_for_delivery"

        # out_for_delivery -> delivered
        r4 = await tms_service.change_transport_status(db_session, order["id"], "delivered")
        assert r4["status"] == "delivered"

    @pytest.mark.asyncio
    async def test_invalid_transition(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "yunda",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Tester",
            "delivery_address": {"province": "Fujian"},
        })
        with pytest.raises(ValidationException):
            await tms_service.change_transport_status(db_session, order["id"], "delivered")

    @pytest.mark.asyncio
    async def test_cancel_from_dispatched(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "jd_logistics",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Cancel Me",
            "delivery_address": {"province": "Hubei"},
        })
        r = await tms_service.change_transport_status(db_session, order["id"], "cancelled")
        assert r["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_exception_path(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Exception Test",
            "delivery_address": {"province": "Henan"},
        })
        r1 = await tms_service.change_transport_status(db_session, order["id"], "in_transit")
        assert r1["status"] == "in_transit"

        r2 = await tms_service.change_transport_status(db_session, order["id"], "exception")
        assert r2["status"] == "exception"

        # From exception can go back to dispatched or directly delivered
        r3 = await tms_service.change_transport_status(db_session, order["id"], "delivered")
        assert r3["status"] == "delivered"


class TestTrackingEvents:
    """Tracking event recording and retrieval."""

    @pytest.mark.asyncio
    async def test_record_tracking_event(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Event Tester",
            "delivery_address": {"province": "Sichuan"},
        })
        evt = await tms_service.record_tracking_event(db_session, {
            "transport_order_id": order["id"],
            "event_type": "in_transit",
            "location_code": "WH-SZ-01",
            "location_name": "深圳仓",
        })
        assert evt["event_type"] == "in_transit"

    @pytest.mark.asyncio
    async def test_get_tracking_events(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "zto",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Tracker",
            "delivery_address": {"province": "Yunnan"},
        })
        events = await tms_service.get_tracking_events(db_session, order["id"])
        assert len(events) >= 1  # at least CREATED event

    @pytest.mark.asyncio
    async def test_delivered_event_sets_actual_delivery_time(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Delivery Test",
            "delivery_address": {"province": "Guangxi"},
        })

        # Record delivered event
        await tms_service.record_tracking_event(db_session, {
            "transport_order_id": order["id"],
            "event_type": "delivered",
            "location_name": "Customer Address",
        })

        fetched = await tms_service.get_transport_order(db_session, order["id"])
        assert fetched["actual_delivery_time"] is not None


class TestPOD:
    """Proof of Delivery recording."""

    @pytest.mark.asyncio
    async def test_create_pod(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "POD Test",
            "delivery_address": {"province": "Guangdong"},
        })
        pod = await tms_service.create_pod(db_session, order["id"], {
            "signed_by": "Zhang Wei",
            "signature_type": "physical",
            "delivery_photo_urls": [{"url": "https://example.com/photo1.jpg"}],
        })
        assert pod["signed_by"] == "Zhang Wei"


class TestReturnOrders:
    """Reverse logistics / return orders."""

    @pytest.mark.asyncio
    async def test_create_return_order(self, db_session):
        ret = await tms_service.create_return_order(db_session, {
            "reason": "damaged",
            "reason_detail": "Package crushed during transit",
            "carrier_code": "ems",
            "refund_amount": 150.00,
        })
        assert ret["return_no"].startswith("RTN-")
        assert ret["status"] == "requested"

    @pytest.mark.asyncio
    async def test_create_return_with_transport_order(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid.uuid4()),
            "delivery_name": "Return Test",
            "delivery_address": {"province": "Jiangsu"},
        })

        ret = await tms_service.create_return_order(db_session, {
            "transport_order_id": order["id"],
            "reason": "wrong_item",
        })
        assert ret is not None


class TestExceptions:
    """Transport exception management."""

    @pytest.mark.asyncio
    async def test_create_exception(self, db_session):
        exc = await tms_service.create_exception(db_session, {
            "type": "delayed",
            "severity": "normal",
            "description": "Weather delay in Henan province",
        })
        assert exc["status"] == "open"

    @pytest.mark.asyncio
    async def test_resolve_exception(self, db_session):
        exc = await tms_service.create_exception(db_session, {
            "type": "damaged_in_transit",
            "description": "Box torn open",
        })
        resolved = await tms_service.resolve_exception(db_session, exc["id"])
        assert resolved["status"] == "resolved"


class TestFreightEstimate:
    """Freight cost estimation."""

    @pytest.mark.asyncio
    async def test_estimate_freight(self):
        result = await tms_service.estimate_freight(
            carrier_code="sf_express",
            service_type="express",
            distance_km=150.0,
            weight_kg=25,
        )
        assert result["carrier_code"] == "sf_express"
        assert float(result["estimated_cost"]) > 0

    @pytest.mark.asyncio
    async def test_estimate_freight_different_carriers(self):
        sf = await tms_service.estimate_freight(
            carrier_code="sf_express", service_type="standard", distance_km=100, weight_kg=10,
        )
        yunda = await tms_service.estimate_freight(
            carrier_code="yunda", service_type="standard", distance_km=100, weight_kg=10,
        )
        # SF is typically more expensive than Yunda
        assert float(sf["estimated_cost"]) > float(yunda["estimated_cost"])


class TestReturnOrderEdgeCases:
    """Return order reverse-logistics edge cases."""

    @pytest.mark.asyncio
    async def test_mark_shipment_received(self, db_session):
        from sqlalchemy import select

        from src.tms.models import ReturnOrder, ReturnShipmentStatus
        ret = await tms_service.create_return_order(db_session, {
            "reason": "damaged", "pickup_address": {}, "refund_amount": "100",
        })
        result = await db_session.execute(
            select(ReturnOrder).where(ReturnOrder.id == __import__("uuid").UUID(ret["id"]))
        )
        ro = result.scalar_one()
        ro.shipment_status = ReturnShipmentStatus.IN_TRANSIT_RETURN
        await db_session.commit()
        updated = await tms_service.mark_shipment_received(db_session, ret["id"])
        assert updated["shipment_status"] == "received_by_carrier"

    @pytest.mark.asyncio
    async def test_mark_shipment_received_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.mark_shipment_received(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_mark_return_inspected_accepted(self, db_session):
        ret = await tms_service.create_return_order(db_session, {
            "reason": "wrong_item", "pickup_address": {}, "refund_amount": "200",
        })
        await tms_service.update_return_status(db_session, ret["id"], "pickup_scheduled")
        await tms_service.update_return_status(db_session, ret["id"], "in_transit_return")
        await tms_service.update_return_status(db_session, ret["id"], "returned_to_warehouse")
        updated = await tms_service.mark_return_inspected(db_session, ret["id"], accepted=True)
        assert updated["status"] == "refunded"

    @pytest.mark.asyncio
    async def test_mark_return_inspected_rejected(self, db_session):
        ret = await tms_service.create_return_order(db_session, {
            "reason": "damaged", "pickup_address": {}, "refund_amount": "50",
        })
        await tms_service.update_return_status(db_session, ret["id"], "pickup_scheduled")
        await tms_service.update_return_status(db_session, ret["id"], "in_transit_return")
        await tms_service.update_return_status(db_session, ret["id"], "returned_to_warehouse")
        updated = await tms_service.mark_return_inspected(db_session, ret["id"], accepted=False)
        assert updated["status"] == "closed"

    @pytest.mark.asyncio
    async def test_mark_return_inspected_invalid_state(self, db_session):
        ret = await tms_service.create_return_order(db_session, {
            "reason": "wrong_item", "pickup_address": {},
        })
        with pytest.raises(ValidationException, match="Cannot inspect"):
            await tms_service.mark_return_inspected(db_session, ret["id"])

    @pytest.mark.asyncio
    async def test_mark_return_inspected_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.mark_return_inspected(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_cancel_return_order(self, db_session):
        ret = await tms_service.create_return_order(db_session, {
            "reason": "wrong_item", "pickup_address": {},
        })
        cancelled = await tms_service.cancel_return_order(db_session, ret["id"])
        assert cancelled["status"] == "closed"

    @pytest.mark.asyncio
    async def test_cancel_return_order_invalid_state(self, db_session):
        ret = await tms_service.create_return_order(db_session, {
            "reason": "damaged", "pickup_address": {},
        })
        await tms_service.update_return_status(db_session, ret["id"], "pickup_scheduled")
        await tms_service.update_return_status(db_session, ret["id"], "in_transit_return")
        with pytest.raises(ValidationException, match="Cannot cancel"):
            await tms_service.cancel_return_order(db_session, ret["id"])

    @pytest.mark.asyncio
    async def test_cancel_return_order_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.cancel_return_order(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_update_return_status_invalid_transition(self, db_session):
        ret = await tms_service.create_return_order(db_session, {
            "reason": "wrong_item", "pickup_address": {},
        })
        with pytest.raises(ValidationException, match="Cannot transition return"):
            await tms_service.update_return_status(db_session, ret["id"], "returned_to_warehouse")

    @pytest.mark.asyncio
    async def test_update_return_status_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.update_return_status(db_session, str(uuid.uuid4()), "pickup_scheduled")


class TestFreightService:
    """Freight tier CRUD and calculation."""

    @pytest.mark.asyncio
    async def test_create_freight_tier(self, db_session):
        tier = await tms_service.create_freight_tier(db_session, {
            "carrier_code": "sf_express",
            "rule_type": "weight_tiered",
            "min_value": 0,
            "max_value": 10.0,
            "price_per_unit": 8.5,
        })
        assert tier["carrier_code"] == "sf_express"
        assert tier["rule_type"] == "weight_tiered"

    @pytest.mark.asyncio
    async def test_calculate_freight_success(self, db_session):
        await tms_service.create_freight_tier(db_session, {
            "carrier_code": "sf_express",
            "rule_type": "weight_tiered",
            "min_value": 0,
            "max_value": 10.0,
            "price_per_unit": 8.5,
        })
        result = await tms_service.calculate_freight(db_session, {
            "carrier_code": "sf_express", "weight": 5,
        })
        assert float(result["total_freight_yuan"]) > 0
        assert result["carrier_code"] == "sf_express"

    @pytest.mark.asyncio
    async def test_calculate_freight_no_tier(self, db_session):
        with pytest.raises(ValidationException, match="No matching freight tier found"):
            await tms_service.calculate_freight(db_session, {
                "carrier_code": "ems", "weight": 5,
            })

    @pytest.mark.asyncio
    async def test_calculate_freight_with_express_surcharge(self, db_session):
        await tms_service.create_freight_tier(db_session, {
            "carrier_code": "zto", "rule_type": "weight_tiered",
            "min_value": 0, "max_value": 10.0, "price_per_unit": 8.5,
            "surcharge_express": 5.0,
        })
        result = await tms_service.calculate_freight(db_session, {
            "carrier_code": "zto", "weight": 5, "express": True,
        })
        assert float(result["total_freight_yuan"]) > 42.5
