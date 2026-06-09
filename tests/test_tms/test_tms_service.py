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
        log = await tms_service.record_sync(db_session, created["id"], {"sync_type": "upload", "status": "completed", "records_count": 10})
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
