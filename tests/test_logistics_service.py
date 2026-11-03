"""Tests for src/logistics/service.py — waybill CRUD.

Covers: create_waybill, get_waybill, list_waybills, void_waybill, mark_printed.
"""
import uuid

import pytest

from src.core.exceptions import NotFoundException, ValidationException
from src.logistics import service as logistics_service
from src.logistics.schemas import CreateWaybillRequest


def _make_req(**overrides) -> CreateWaybillRequest:
    """Build a CreateWaybillRequest with defaults."""
    data = {
        "order_id": f"ORD-{uuid.uuid4().hex[:8]}",
        "recipient_name": "张三",
        "recipient_phone": "13800138000",
        "recipient_address": "广东省深圳市南山区科技园",
        "items": [{"sku": "SKU-001", "qty": 2}],
        "carrier_code": "zto",
    }
    data.update(overrides)
    return CreateWaybillRequest(**data)


class TestCreateWaybill:
    """create_waybill — inserts a waybill row."""

    @pytest.mark.asyncio
    async def test_create_success(self, db_session):
        req = _make_req()
        result = await logistics_service.create_waybill(db_session, req)
        assert result["tracking_number"]
        assert result["order_id"] == req.order_id
        assert result["carrier_code"] == "zto"
        assert result["status"] == "created"
        assert result["print_count"] == 0

    @pytest.mark.asyncio
    async def test_create_invalid_carrier(self, db_session):
        req = _make_req(carrier_code="INVALID_CARRIER_XYZ")
        with pytest.raises(ValidationException, match="无效"):
            await logistics_service.create_waybill(db_session, req)


class TestGetWaybill:
    """get_waybill — fetch by tracking number."""

    @pytest.mark.asyncio
    async def test_get_success(self, db_session):
        req = _make_req()
        created = await logistics_service.create_waybill(db_session, req)
        result = await logistics_service.get_waybill(
            db_session, created["tracking_number"]
        )
        assert result["tracking_number"] == created["tracking_number"]

    @pytest.mark.asyncio
    async def test_get_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await logistics_service.get_waybill(db_session, "NONEXISTENT-TRACKING")


class TestListWaybills:
    """list_waybills — paginated list with filters."""

    @pytest.mark.asyncio
    async def test_list_empty(self, db_session):
        result = await logistics_service.list_waybills(db_session)
        assert result["items"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_list_with_data(self, db_session):
        req = _make_req(order_id="ORD-LIST-001")
        await logistics_service.create_waybill(db_session, req)
        result = await logistics_service.list_waybills(db_session)
        assert result["total"] >= 1
        assert len(result["items"]) >= 1

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, db_session):
        req = _make_req(order_id="ORD-STATUS-001")
        await logistics_service.create_waybill(db_session, req)
        result = await logistics_service.list_waybills(db_session, status="created")
        assert result["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_filter_by_carrier(self, db_session):
        req = _make_req(order_id="ORD-CARRIER-001", carrier_code="sf")
        await logistics_service.create_waybill(db_session, req)
        result = await logistics_service.list_waybills(db_session, carrier="sf")
        assert result["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_filter_by_q(self, db_session):
        req = _make_req(
            order_id="ORD-SEARCH-001",
            recipient_name="李四",
        )
        created = await logistics_service.create_waybill(db_session, req)
        result = await logistics_service.list_waybills(
            db_session, q=created["tracking_number"][:6]
        )
        assert result["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_pagination(self, db_session):
        for i in range(3):
            req = _make_req(order_id=f"ORD-PAGE-{i}")
            await logistics_service.create_waybill(db_session, req)
        result = await logistics_service.list_waybills(db_session, page=1, page_size=2)
        assert len(result["items"]) <= 2
        assert result["total"] >= 3


class TestVoidWaybill:
    """void_waybill — soft-void a waybill."""

    @pytest.mark.asyncio
    async def test_void_success(self, db_session):
        req = _make_req(order_id="ORD-VOID-001")
        created = await logistics_service.create_waybill(db_session, req)
        result = await logistics_service.void_waybill(
            db_session, created["tracking_number"]
        )
        assert result["status"] == "voided"

    @pytest.mark.asyncio
    async def test_void_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await logistics_service.void_waybill(db_session, "NONEXISTENT")

    @pytest.mark.asyncio
    async def test_void_already_voided(self, db_session):
        req = _make_req(order_id="ORD-VOID-002")
        created = await logistics_service.create_waybill(db_session, req)
        await logistics_service.void_waybill(db_session, created["tracking_number"])
        with pytest.raises(ValidationException, match="已作废"):
            await logistics_service.void_waybill(
                db_session, created["tracking_number"]
            )


class TestMarkPrinted:
    """mark_printed — increment print_count."""

    @pytest.mark.asyncio
    async def test_mark_printed_success(self, db_session):
        req = _make_req(order_id="ORD-PRINT-001")
        created = await logistics_service.create_waybill(db_session, req)
        result = await logistics_service.mark_printed(
            db_session, created["tracking_number"]
        )
        assert result["print_count"] == 1
        assert result["last_printed_at"] is not None

    @pytest.mark.asyncio
    async def test_mark_printed_twice(self, db_session):
        req = _make_req(order_id="ORD-PRINT-002")
        created = await logistics_service.create_waybill(db_session, req)
        await logistics_service.mark_printed(db_session, created["tracking_number"])
        result = await logistics_service.mark_printed(
            db_session, created["tracking_number"]
        )
        assert result["print_count"] == 2

    @pytest.mark.asyncio
    async def test_mark_printed_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await logistics_service.mark_printed(db_session, "NONEXISTENT")
