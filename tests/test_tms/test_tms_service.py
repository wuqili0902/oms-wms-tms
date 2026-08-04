"""Direct service-level tests for TMS business logic.

Tests all untested paths in src/tms/service.py using the db_session fixture.
"""
import uuid

import pytest

from src.core.exceptions import NotFoundException, ValidationException
from src.tms import service as tms_service


class TestDeviceCRUD:
    """Device registration, retrieval, listing, update."""

    @pytest.mark.asyncio
    async def test_register_device(self, db_session):
        dev = await tms_service.register_device(db_session, {
            "code": "DEV-001", "name": "Scanner 1", "device_type": "pda", "platform": "android",
        })
        assert dev["code"] == "DEV-001"
        assert dev["status"] == "offline"

    @pytest.mark.asyncio
    async def test_register_device_duplicate_code(self, db_session):
        await tms_service.register_device(db_session, {"code": "DEV-DUP", "name": "First"})
        with pytest.raises(ValidationException, match="already exists"):
            await tms_service.register_device(db_session, {"code": "DEV-DUP", "name": "Second"})

    @pytest.mark.asyncio
    async def test_get_device(self, db_session):
        created = await tms_service.register_device(db_session, {"code": "DEV-GET", "name": "Get"})
        fetched = await tms_service.get_device(db_session, created["id"])
        assert fetched["code"] == "DEV-GET"

    @pytest.mark.asyncio
    async def test_get_nonexistent_device(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.get_device(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_list_devices(self, db_session):
        await tms_service.register_device(db_session, {"code": "DEV-L1", "name": "List 1"})
        await tms_service.register_device(db_session, {"code": "DEV-L2", "name": "List 2"})
        devices = await tms_service.list_devices(db_session)
        assert len(devices) >= 2

    @pytest.mark.asyncio
    async def test_list_devices_filter_by_status(self, db_session):
        await tms_service.register_device(db_session, {"code": "DEV-FS", "name": "Filter"})
        devices = await tms_service.list_devices(db_session, status="offline")
        assert all(d["status"] == "offline" for d in devices)

    @pytest.mark.asyncio
    async def test_update_device(self, db_session):
        created = await tms_service.register_device(db_session, {"code": "DEV-UP", "name": "Old"})
        updated = await tms_service.update_device(db_session, created["id"], {"name": "New Name"})
        assert updated["name"] == "New Name"

    @pytest.mark.asyncio
    async def test_update_device_status(self, db_session):
        created = await tms_service.register_device(db_session, {"code": "DEV-US", "name": "Status"})
        updated = await tms_service.update_device(db_session, created["id"], {"status": "disabled"})
        assert updated["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_update_nonexistent_device(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.update_device(db_session, str(uuid.uuid4()), {"name": "X"})


class TestHeartbeat:
    """Device heartbeat recording."""

    @pytest.mark.asyncio
    async def test_record_heartbeat(self, db_session):
        created = await tms_service.register_device(db_session, {"code": "DEV-HB", "name": "Heartbeat"})
        result = await tms_service.record_heartbeat(db_session, created["id"])
        assert result["status"] == "online"
        assert "last_heartbeat_at" in result

    @pytest.mark.asyncio
    async def test_heartbeat_nonexistent_device(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.record_heartbeat(db_session, str(uuid.uuid4()))


class TestSyncLogs:
    """Sync log recording and listing."""

    @pytest.mark.asyncio
    async def test_record_sync(self, db_session):
        created = await tms_service.register_device(db_session, {"code": "DEV-SY", "name": "Sync"})
        log = await tms_service.record_sync(
            db_session,
            created["id"],
            {"sync_type": "upload", "status": "completed", "records_count": 10},
        )
        assert log["sync_type"] == "upload"

    @pytest.mark.asyncio
    async def test_record_sync_nonexistent_device(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.record_sync(db_session, str(uuid.uuid4()), {"sync_type": "download", "status": "pending"})

    @pytest.mark.asyncio
    async def test_list_sync_logs(self, db_session):
        created = await tms_service.register_device(db_session, {"code": "DEV-LS", "name": "Log Sync"})
        await tms_service.record_sync(db_session, created["id"], {"sync_type": "download", "status": "completed"})
        logs = await tms_service.list_sync_logs(db_session, created["id"])
        assert len(logs) >= 1

    @pytest.mark.asyncio
    async def test_list_sync_logs_nonexistent_device(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.list_sync_logs(db_session, str(uuid.uuid4()))


class TestSessions:
    """Device session management."""

    @pytest.mark.asyncio
    async def test_create_session(self, db_session):
        created = await tms_service.register_device(db_session, {"code": "DEV-SS", "name": "Session"})
        sess = await tms_service.create_session(db_session, created["id"], ip_address="192.168.1.1")
        assert sess["ip_address"] == "192.168.1.1"
        assert sess["login_at"] is not None

    @pytest.mark.asyncio
    async def test_create_session_nonexistent_device(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.create_session(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_end_session(self, db_session):
        created = await tms_service.register_device(db_session, {"code": "DEV-ES", "name": "End Sess"})
        sess = await tms_service.create_session(db_session, created["id"])
        ended = await tms_service.end_session(db_session, created["id"], sess["id"])
        assert ended["logout_at"] is not None

    @pytest.mark.asyncio
    async def test_end_session_nonexistent(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.end_session(db_session, str(uuid.uuid4()), str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_list_sessions(self, db_session):
        created = await tms_service.register_device(db_session, {"code": "DEV-LSS", "name": "List Sess"})
        await tms_service.create_session(db_session, created["id"])
        sessions = await tms_service.list_sessions(db_session, created["id"])
        assert len(sessions) >= 1


class TestTransportOrder:
    """Transport order CRUD and status transitions."""

    _counter = 0

    @pytest.fixture(autouse=True)
    async def _setup(self, db_session):
        from src.wms.service import create_warehouse
        TestTransportOrder._counter += 1
        self.wh = await create_warehouse(db_session, {
            "code": f"WH-TMS-{TestTransportOrder._counter}", "name": "TMS Test WH",
            "type": "center", "address": "Test",
        })

    @pytest.mark.asyncio
    async def test_create(self, db_session):
        order = await tms_service.create_transport_order(db_session, {
            "pickup_warehouse_id": self.wh["id"],
            "delivery_name": "Test Recipient",
        })
        assert order["delivery_name"] == "Test Recipient"
        assert order["status"] == "draft"

    @pytest.mark.asyncio
    async def test_get(self, db_session):
        created = await tms_service.create_transport_order(db_session, {
            "pickup_warehouse_id": self.wh["id"],
            "delivery_name": "Get Test",
        })
        fetched = await tms_service.get_transport_order(db_session, created["id"])
        assert fetched["id"] == created["id"]

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.get_transport_order(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_list(self, db_session):
        orders, total = await tms_service.list_transport_orders(db_session)
        assert isinstance(orders, list)
        assert isinstance(total, int)

    @pytest.mark.asyncio
    async def test_change_status_draft_to_dispatched(self, db_session):
        created = await tms_service.create_transport_order(db_session, {
            "pickup_warehouse_id": self.wh["id"],
            "delivery_name": "Status Test",
        })
        updated = await tms_service.change_transport_status(db_session, created["id"], "dispatched")
        assert updated["status"] == "dispatched"

    @pytest.mark.asyncio
    async def test_change_status_invalid_transition(self, db_session):
        created = await tms_service.create_transport_order(db_session, {
            "pickup_warehouse_id": self.wh["id"],
            "delivery_name": "Invalid Trans",
        })
        with pytest.raises(ValidationException, match="Cannot transition"):
            await tms_service.change_transport_status(db_session, created["id"], "delivered")

    @pytest.mark.asyncio
    async def test_change_status_nonexistent(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.change_transport_status(db_session, str(uuid.uuid4()), "dispatched")


class TestTrackingEvent:
    """Tracking event creation."""

    _counter = 0

    @pytest.fixture(autouse=True)
    async def _setup(self, db_session):
        from src.wms.service import create_warehouse
        TestTrackingEvent._counter += 1
        wh = await create_warehouse(
            db_session,
            {"code": f"WH-TRK-{TestTrackingEvent._counter}", "name": "Tracking WH", "type": "center"},
        )
        self.order = await tms_service.create_transport_order(db_session, {
            "pickup_warehouse_id": wh["id"], "delivery_name": "Tracking Test",
        })

    @pytest.mark.asyncio
    async def test_create_event(self, db_session):
        event = await tms_service.create_tracking_event(db_session, {
            "transport_order_id": self.order["id"],
            "event_type": "pickup_completed",
            "remark": "Picked up successfully",
        })
        assert event["event_type"] == "pickup_completed"
        assert event["remark"] == "Picked up successfully"

    @pytest.mark.asyncio
    async def test_create_event_nonexistent_order(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.create_tracking_event(db_session, {
                "transport_order_id": str(uuid.uuid4()),
                "event_type": "pickup_completed",
            })


class TestExceptionService:
    """Exception CRUD and resolution."""

    _counter = 0

    @pytest.fixture(autouse=True)
    async def _setup(self, db_session):
        from src.wms.service import create_warehouse
        TestExceptionService._counter += 1
        wh = await create_warehouse(
            db_session,
            {"code": f"WH-EXC-{TestExceptionService._counter}", "name": "Exception WH", "type": "center"},
        )
        self.order = await tms_service.create_transport_order(db_session, {
            "pickup_warehouse_id": wh["id"], "delivery_name": "Exception Test",
        })

    @pytest.mark.asyncio
    async def test_create(self, db_session):
        exc = await tms_service.create_exception(db_session, {
            "type": "delayed",
            "transport_order_id": self.order["id"],
            "description": "Traffic delay",
        })
        assert exc["type"] == "delayed"
        assert exc["status"] == "open"

    @pytest.mark.asyncio
    async def test_create_standalone(self, db_session):
        exc = await tms_service.create_exception(db_session, {
            "type": "delayed",
            "description": "Package damaged in transit",
        })
        assert exc["type"] == "delayed"

    @pytest.mark.asyncio
    async def test_list(self, db_session):
        exceptions = await tms_service.list_exceptions(db_session)
        assert isinstance(exceptions, list)

    @pytest.mark.asyncio
    async def test_resolve(self, db_session):
        exc = await tms_service.create_exception(db_session, {
            "type": "delayed",
            "transport_order_id": self.order["id"],
        })
        resolved = await tms_service.resolve_exception(db_session, exc["id"], "Resolved after driver contact")
        assert resolved["status"] == "resolved"
        assert resolved["resolution_notes"] == "Resolved after driver contact"

    @pytest.mark.asyncio
    async def test_resolve_nonexistent(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.resolve_exception(db_session, str(uuid.uuid4()))


class TestReturnOrder:
    """Return order CRUD and status transitions."""

    @pytest.mark.asyncio
    async def test_create(self, db_session):
        ret = await tms_service.create_return_order(db_session, {
            "reason": "customer_retrieval",
            "reason_detail": "Wrong item",
        })
        assert ret["reason"] == "customer_retrieval"
        assert ret["status"] == "requested"

    @pytest.mark.asyncio
    async def test_list(self, db_session):
        returns, total = await tms_service.list_return_orders(db_session)
        assert isinstance(returns, list)
        assert isinstance(total, int)

    @pytest.mark.asyncio
    async def test_get(self, db_session):
        created = await tms_service.create_return_order(db_session, {"reason": "customer_retrieval"})
        fetched = await tms_service.get_return_order(db_session, created["id"])
        assert fetched["id"] == created["id"]

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.get_return_order(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_cancel(self, db_session):
        created = await tms_service.create_return_order(db_session, {"reason": "customer_retrieval"})
        cancelled = await tms_service.cancel_return_order(db_session, created["id"])
        assert cancelled["status"] == "closed"

    @pytest.mark.asyncio
    async def test_cancel_invalid_status(self, db_session):
        ret = await tms_service.create_return_order(db_session, {"reason": "customer_retrieval"})
        await tms_service.update_return_status(db_session, ret["id"], "pickup_scheduled")
        await tms_service.update_return_status(db_session, ret["id"], "in_transit_return")
        with pytest.raises(ValidationException):
            await tms_service.cancel_return_order(db_session, ret["id"])


class TestFreightTier:
    """Freight tier and calculation."""

    @pytest.mark.asyncio
    async def test_create_tier(self, db_session):
        tier = await tms_service.create_freight_tier(db_session, {
            "carrier_code": "sf_express",
            "rule_type": "weight_tiered",
            "min_value": 0,
            "max_value": 100,
            "price_per_unit": 10.0,
        })
        assert tier["carrier_code"] == "sf_express"

    @pytest.mark.asyncio
    async def test_calculate_freight(self, db_session):
        await tms_service.create_freight_tier(db_session, {
            "carrier_code": "sf_express",
            "rule_type": "weight_tiered",
            "min_value": 0,
            "max_value": 100,
            "price_per_unit": 5.0,
        })
        result = await tms_service.calculate_freight(db_session, {
            "carrier_code": "sf_express",
            "weight": 10,
        })
        assert result["total_freight_yuan"] is not None
        assert float(result["total_freight_yuan"]) > 0
