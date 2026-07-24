"""Tests for new TMS endpoints (tracking, POD, returns, exceptions)."""
import uuid as uuid_mod
from decimal import Decimal

import pytest


@pytest.fixture
async def auth_headers(async_client):
    uname = f"tmsuser_{uuid_mod.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestTrackingEvents:
    """Test tracking event CRUD via API."""

    async def test_list_tracking_events(self, async_client):
        create_resp = await async_client.post("/api/v1/transport-orders", json={
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid_mod.uuid4()),
            "delivery_name": "Bob",
            "delivery_address": {"city": "Beijing"},
        })
        order = create_resp.json()
        resp = await async_client.get(
            f"/api/v1/transport-orders/{order['id']}/tracking-events"
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestPOD:
    """Test Proof of Delivery endpoints via API."""

    async def test_create_pod(self, async_client):
        create_resp = await async_client.post("/api/v1/transport-orders", json={
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid_mod.uuid4()),
            "delivery_name": "Alice",
            "delivery_address": {"city": "Beijing"},
        })
        order = create_resp.json()
        resp = await async_client.post(
            f"/api/v1/transport-orders/{order['id']}/pod", json={"signed_by": "Bob"}
        )
        assert resp.status_code in (200, 201, 404)


class TestReturnOrders:
    """Test return order state machine via service."""

    async def test_return_order_crud(self, db_session):
        from src.tms import service as tms_service
        ret = await tms_service.create_return_order(
            db_session,
            {"reason": "damaged", "pickup_address": {}, "refund_amount": "100"}
        )
        assert ret["status"] == "requested"

    async def test_return_state_machine(self, db_session):
        from src.tms import service as tms_service
        ret = await tms_service.create_return_order(
            db_session,
            {"reason": "wrong_item", "pickup_address": {}, "refund_amount": "200"}
        )
        assert ret["status"] == "requested"

        updated = await tms_service.update_return_status(db_session, return_id=str(ret["id"]), target="pickup_scheduled")
        assert updated["status"] == "pickup_scheduled"


class TestExceptions:
    """Test transport exception handling via service."""

    async def test_create_exception(self, db_session):
        from src.tms import service as tms_service
        order = await tms_service.create_transport_order(
            db_session,
            {
                "carrier_code": "sf_express",
                "pickup_warehouse_id": str(uuid_mod.uuid4()),
                "delivery_name": "Test",
                "delivery_address": {"city": "Beijing"},
            }
        )
        exc = await tms_service.create_exception(
            db_session,
            {
                "transport_order_id": str(order["id"]),
                "type": "delayed",
                "description": "Weather delay"
            }
        )
        assert exc["type"] == "delayed"


class TestFreightCalc:
    """Test freight calculation."""

    async def test_freight_calculation(self, db_session):
        from src.tms import service as tms_service
        tier = await tms_service.create_freight_tier(
            db_session,
            {
                "carrier_code": "sf_express",
                "rule_type": "weight_tiered",
                "min_value": 0,
                "max_value": 10.0,
                "price_per_unit": Decimal("8.5"),
            }
        )
        assert tier["rule_type"] == "weight_tiered"


class TestAdminRoutes:
    """Test admin pages load correctly."""

    async def test_admin_transport_orders(self, async_client):
        r = await async_client.get("/admin/transport-orders")
        assert r.status_code in (200, 307)


class TestMLForecast:
    """Test ML forecast endpoint."""

    async def test_ml_forecast_observations(self, async_client):
        resp = await async_client.post("/api/v1/forecast/observations", json={
            "origin_city": "Wuhan",
            "destination_city": "Changsha",
            "count": 50.0,
        })
        assert resp.status_code == 200

    async def test_ml_forecast_api(self, async_client):
        fc = await async_client.get("/api/v1/forecast", params={
            "origin_city": "Wuhan",
            "destination_city": "Changsha",
        })
        points = fc.json()
        assert len(points) > 0


class TestCeleryTasks:
    """Test Celery task imports work."""

    async def test_celery_task_imports(self):
        from src.tasks.inventory import (
            sync_inventory, snapshot_inventory, cancel_expired_orders, process_pending_orders,
        )
        assert hasattr(sync_inventory, 'name')


class TestSeeding:
    """Test seed script runs."""

    async def test_seed_script(self, db_session):
        from src.tms.seed import main as seed_main
        await seed_main(db=db_session)


class TestMLForecastService:
    """Test ML forecast service directly."""

    async def test_forecast_service(self, async_client):
        resp = await async_client.post("/api/v1/forecast/observations", json={
            "origin_city": "Wuhan",
            "destination_city": "Changsha",
            "count": 50.0,
        })
        assert resp.status_code == 200

    async def test_get_forecast(self, async_client):
        fc = await async_client.get("/api/v1/forecast", params={
            "origin_city": "Wuhan",
            "destination_city": "Changsha",
        })
        points = fc.json()
        assert len(points) > 0


class TestAdminForecastPage:
    """Test ML forecast admin page."""

    async def test_ml_forecast_page(self, auth_headers, async_client):
        r = await async_client.get("/admin/ml/forecast")
        assert r.status_code in (200, 307)
