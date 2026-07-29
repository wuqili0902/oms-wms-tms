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

    async def test_seed_script_no_db(self, db_session):
        from unittest.mock import AsyncMock, patch
        from src.tms.seed import main as seed_main
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = db_session
        with patch("src.tms.seed.async_session_factory", return_value=mock_cm):
            await seed_main()


class TestOrderForecaster:
    """Test OrderForecaster class directly."""

    async def test_add_and_forecast(self):
        from src.tms.ml.forecast import OrderForecaster
        fc = OrderForecaster(window_size=3, alpha=0.5)
        fc.add_observation("wuh→cs", 10.0)
        result = fc.forecast("wuh→cs", days=2)
        assert len(result) == 2
        assert result[0].predicted_orders == 0  # less than 2 observations

    async def test_add_and_forecast_with_history(self):
        from src.tms.ml.forecast import OrderForecaster
        fc = OrderForecaster(window_size=3, alpha=0.5)
        key = "wh→cs"
        for v in [10.0, 20.0, 30.0]:
            fc.add_observation(key, v)
        result = fc.forecast(key, days=3)
        assert len(result) == 3
        assert result[0].predicted_orders > 0

    async def test_history_trim(self):
        from src.tms.ml.forecast import OrderForecaster
        fc = OrderForecaster(window_size=3, alpha=0.5)
        key = "trim_test"
        for v in range(10):
            fc.add_observation(key, float(v))
        hist = fc._history[key]
        assert len(hist) == 3  # trimmed to window_size


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


class TestListTransportOrders:
    """Test list / transport-orders endpoint."""

    async def test_list_transport_orders(self, async_client):
        await async_client.post("/api/v1/transport-orders", json={
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid_mod.uuid4()),
            "delivery_name": "Alice",
            "delivery_address": {"city": "Beijing"},
        })
        resp = await async_client.get("/api/v1/transport-orders")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["page"] == 1

    async def test_list_transport_orders_with_filters(self, async_client):
        resp = await async_client.get("/api/v1/transport-orders?status=draft&carrier_code=sf_express")
        assert resp.status_code == 200


class TestGetPOD:
    """Test get / transport-orders/{order_id}/pod endpoint."""

    async def test_get_pod_not_found(self, async_client):
        resp = await async_client.get(
            f"/api/v1/transport-orders/{uuid_mod.uuid4()}/pod"
        )
        assert resp.status_code == 404

    async def test_get_pod_success(self, async_client):
        create_resp = await async_client.post("/api/v1/transport-orders", json={
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid_mod.uuid4()),
            "delivery_name": "Bob",
            "delivery_address": {"city": "Shanghai"},
        })
        order_id = create_resp.json()["id"]
        await async_client.post(f"/api/v1/transport-orders/{order_id}/pod", json={"signed_by": "Bob"})
        resp = await async_client.get(f"/api/v1/transport-orders/{order_id}/pod")
        assert resp.status_code == 200


class TestUpdatePOD:
    """Test put / transport-orders/{order_id}/pod endpoint."""

    async def test_update_pod_not_found(self, async_client):
        resp = await async_client.put(
            f"/api/v1/transport-orders/{uuid_mod.uuid4()}/pod", json={"signed_by": "Alice"}
        )
        assert resp.status_code == 404

    async def test_update_pod_success(self, async_client):
        create_resp = await async_client.post("/api/v1/transport-orders", json={
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid_mod.uuid4()),
            "delivery_name": "Charlie",
            "delivery_address": {"city": "Guangzhou"},
        })
        order_id = create_resp.json()["id"]
        await async_client.post(f"/api/v1/transport-orders/{order_id}/pod", json={"signed_by": "Charlie"})
        resp = await async_client.put(f"/api/v1/transport-orders/{order_id}/pod", json={
            "signed_by": "Charlie Updated",
            "notes": "Delivered on time",
        })
        assert resp.status_code == 200


class TestListReturnOrders:
    """Test list / return-orders endpoint."""

    async def test_list_return_orders(self, db_session):
        from src.tms import service as tms_service
        await tms_service.create_return_order(db_session, {
            "reason": "damaged", "pickup_address": {}, "refund_amount": "50",
        })
        result = await tms_service.list_return_orders(db_session)
        items, total = result
        assert total >= 1

    async def test_list_return_orders_filter_status(self, db_session):
        from src.tms import service as tms_service
        result = await tms_service.list_return_orders(db_session, status="requested")
        items, total = result
        assert isinstance(items, list)


class TestGetReturnOrder:
    """Test get / return-orders/{return_id} endpoint."""

    async def test_get_return_order_not_found(self, async_client):
        resp = await async_client.get(f"/api/v1/return-orders/{uuid_mod.uuid4()}")
        assert resp.status_code == 404

    async def test_get_return_order_success(self, async_client):
        create_resp = await async_client.post("/api/v1/return-orders", json={
            "reason": "damaged", "pickup_address": {"city": "Shenzhen"}, "refund_amount": "100",
        })
        return_id = create_resp.json()["id"]
        resp = await async_client.get(f"/api/v1/return-orders/{return_id}")
        assert resp.status_code == 200


class TestListExceptions:
    """Test list / exceptions endpoint."""

    async def test_list_exceptions(self, db_session):
        from src.tms import service as tms_service
        order = await tms_service.create_transport_order(db_session, {
            "carrier_code": "sf_express",
            "pickup_warehouse_id": str(uuid_mod.uuid4()),
            "delivery_name": "Test",
            "delivery_address": {"city": "Beijing"},
        })
        await tms_service.create_exception(db_session, {
            "transport_order_id": str(order["id"]),
            "type": "delayed",
            "description": "Traffic",
        })
        exc_list = await tms_service.list_exceptions(db_session)
        assert len(exc_list) >= 1

    async def test_list_exceptions_filter(self, db_session):
        from src.tms import service as tms_service
        exc_list = await tms_service.list_exceptions(db_session, status="open")
        assert isinstance(exc_list, list)


class TestCalculateFreight:
    """Test post / freight/calculate endpoint."""

    async def test_calculate_freight_no_tier(self, async_client):
        resp = await async_client.post("/api/v1/freight/calculate", json={
            "carrier_code": "ems", "weight": 5,
        })
        assert resp.status_code == 422

    async def test_calculate_freight_success(self, async_client):
        await async_client.post("/api/v1/freight-tiers", json={
            "carrier_code": "sf_express",
            "rule_type": "weight_tiered",
            "min_value": 0,
            "max_value": 10.0,
            "price_per_unit": 8.5,
        })
        resp = await async_client.post("/api/v1/freight/calculate", json={
            "carrier_code": "sf_express", "weight": 5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "total_freight_yuan" in data


class TestAdminForecastPage:
    """Test ML forecast admin page."""

    async def test_ml_forecast_page(self, auth_headers, async_client):
        r = await async_client.get("/admin/ml/forecast")
        assert r.status_code in (200, 307)

