"""Tests for TMS router — covering exception handlers and uncovered endpoints."""
import uuid as uuid_mod

import pytest


@pytest.fixture
async def auth_headers(async_client):
    uname = f"tmscov_{uuid_mod.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def transport_order(async_client):
    resp = await async_client.post("/api/v1/transport-orders", json={
        "carrier_code": "sf_express",
        "pickup_warehouse_id": str(uuid_mod.uuid4()),
        "delivery_name": "Coverage Test",
        "delivery_address": {"city": "Beijing"},
    })
    return resp.json()


@pytest.fixture
async def transport_order_with_pickup(async_client):
    resp = await async_client.post("/api/v1/transport-orders", json={
        "carrier_code": "sf_express",
        "pickup_warehouse_id": str(uuid_mod.uuid4()),
        "delivery_name": "Route Plan Test",
        "pickup_address": {"city": "Wuhan"},
        "delivery_address": {"city": "Changsha"},
    })
    return resp.json()


BAD_UUID = "00000000-0000-0000-0000-000000000000"


# ── Device Exception Handlers ─────────────────────────────────────────────

class TestDeviceExceptions:
    async def test_update_device_not_found(self, async_client, auth_headers):
        resp = await async_client.patch(
            f"/api/v1/devices/{BAD_UUID}", json={"name": "Nope"}, headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_create_session_not_found(self, async_client, auth_headers):
        resp = await async_client.post(f"/api/v1/devices/{BAD_UUID}/sessions", headers=auth_headers)
        assert resp.status_code == 404

    async def test_end_session_not_found(self, async_client, auth_headers):
        resp = await async_client.delete(
            f"/api/v1/devices/{BAD_UUID}/sessions/{BAD_UUID}", headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_list_sessions_not_found(self, async_client, auth_headers):
        resp = await async_client.get(f"/api/v1/devices/{BAD_UUID}/sessions", headers=auth_headers)
        assert resp.status_code == 404

    async def test_record_sync_not_found(self, async_client, auth_headers):
        resp = await async_client.post(
            f"/api/v1/devices/{BAD_UUID}/sync", json={"sync_type": "download"}, headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_list_sync_logs_not_found(self, async_client, auth_headers):
        resp = await async_client.get(f"/api/v1/devices/{BAD_UUID}/sync", headers=auth_headers)
        assert resp.status_code == 404


# ── Transport Order Exception Handlers ─────────────────────────────────────

class TestTransportOrderExceptions:
    async def test_get_transport_order_not_found(self, async_client):
        resp = await async_client.get(f"/api/v1/transport-orders/{BAD_UUID}")
        assert resp.status_code == 404

    async def test_update_status_success(self, async_client, transport_order):
        order_id = transport_order["id"]
        resp = await async_client.put(f"/api/v1/transport-orders/{order_id}/status?status=dispatched")
        assert resp.status_code == 200
        assert resp.json()["status"] == "dispatched"

    async def test_update_status_not_found(self, async_client):
        resp = await async_client.put(f"/api/v1/transport-orders/{BAD_UUID}/status?status=dispatched")
        assert resp.status_code == 404

    async def test_update_status_invalid_transition(self, async_client, transport_order):
        order_id = transport_order["id"]
        resp = await async_client.put(f"/api/v1/transport-orders/{order_id}/status?status=delivered")
        assert resp.status_code == 422


# ── Tracking Event Handlers ────────────────────────────────────────────────

class TestTrackingEventsAPI:
    async def test_record_tracking_event_validation(self, async_client, transport_order):
        order_id = transport_order["id"]
        resp = await async_client.post("/api/v1/tracking-events", json={
            "transport_order_id": order_id, "event_type": "invalid_type",
        })
        assert resp.status_code == 422

    async def test_standalone_record_tracking_event(self, async_client, transport_order):
        order_id = transport_order["id"]
        resp = await async_client.post("/api/v1/tracking-events", json={
            "transport_order_id": order_id, "event_type": "in_transit",
        })
        assert resp.status_code == 201

    async def test_get_tracking_events_success(self, async_client, transport_order):
        order_id = transport_order["id"]
        resp = await async_client.get(f"/api/v1/transport-orders/{order_id}/tracking")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_tracking_event_success(self, async_client, transport_order):
        order_id = transport_order["id"]
        resp = await async_client.post(
            f"/api/v1/transport-orders/{order_id}/tracking-events",
            json={"event_type": "in_transit", "location_code": "WH-SZ-01"},
        )
        assert resp.status_code == 200

    async def test_create_tracking_event_not_found(self, async_client):
        resp = await async_client.post(
            f"/api/v1/transport-orders/{BAD_UUID}/tracking-events",
            json={"event_type": "in_transit"},
        )
        assert resp.status_code == 404


# ── POD Exception Handlers ─────────────────────────────────────────────────

class TestPODExceptions:
    async def test_create_pod_success(self, async_client, transport_order):
        order_id = transport_order["id"]
        resp = await async_client.post(
            f"/api/v1/transport-orders/{order_id}/pod", json={"signed_by": "Alice"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["signed_by"] == "Alice"


# ── Return Order Handlers ──────────────────────────────────────────────────

class TestReturnOrderExceptions:
    async def test_get_return_order_not_found(self, async_client):
        resp = await async_client.get(f"/api/v1/return-orders/{BAD_UUID}")
        assert resp.status_code == 404

    async def test_update_return_status_success(self, async_client):
        create = await async_client.post("/api/v1/return-orders", json={
            "reason": "damaged", "pickup_address": {"city": "Shenzhen"}, "refund_amount": "100",
        })
        ret_id = create.json()["id"]
        resp = await async_client.patch(f"/api/v1/return-orders/{ret_id}/status", json={"target": "pickup_scheduled"})
        assert resp.status_code == 200

    async def test_update_return_status_not_found(self, async_client):
        resp = await async_client.patch(f"/api/v1/return-orders/{BAD_UUID}/status", json={"target": "pickup_scheduled"})
        assert resp.status_code == 404

    async def test_list_return_orders(self, async_client):
        await async_client.post("/api/v1/return-orders", json={
            "reason": "damaged", "pickup_address": {"city": "Shenzhen"}, "refund_amount": "50",
        })
        resp = await async_client.get("/api/v1/return-orders")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ── Exception Handlers ─────────────────────────────────────────────────────

class TestTransportExceptions:
    async def test_create_exception_success(self, async_client):
        resp = await async_client.post("/api/v1/exceptions", json={
            "type": "delayed", "severity": "normal", "description": "Weather delay",
        })
        assert resp.status_code == 201

    async def test_resolve_exception_not_found(self, async_client):
        resp = await async_client.patch(f"/api/v1/exceptions/{BAD_UUID}/resolve")
        assert resp.status_code == 404

    async def test_resolve_exception_success(self, async_client):
        create = await async_client.post("/api/v1/exceptions", json={
            "type": "delayed", "severity": "normal", "description": "Weather delay",
        })
        exc_id = create.json()["id"]
        resp = await async_client.patch(f"/api/v1/exceptions/{exc_id}/resolve")
        assert resp.status_code == 200

    async def test_create_order_exception(self, async_client, transport_order):
        order_id = transport_order["id"]
        resp = await async_client.post(
            f"/api/v1/transport-orders/{order_id}/exceptions",
            json={"type": "delayed", "description": "Weather delay"},
        )
        assert resp.status_code == 201

    async def test_create_order_exception_not_found(self, async_client):
        resp = await async_client.post(
            f"/api/v1/transport-orders/{BAD_UUID}/exceptions",
            json={"type": "delayed", "description": "x"},
        )
        assert resp.status_code == 404

    async def test_list_exceptions_success(self, async_client):
        resp = await async_client.get("/api/v1/exceptions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_resolve_exc_not_found(self, async_client):
        resp = await async_client.patch(
            f"/api/v1/exceptions/{BAD_UUID}", json={"resolution_notes": "Done"},
        )
        assert resp.status_code == 404

    async def test_resolve_exc_success(self, async_client):
        create = await async_client.post("/api/v1/exceptions", json={
            "type": "delayed", "severity": "normal", "description": "Weather delay",
        })
        exc_id = create.json()["id"]
        resp = await async_client.patch(
            f"/api/v1/exceptions/{exc_id}", json={"resolution_notes": "Redelivered"},
        )
        assert resp.status_code == 200


# ── Freight Endpoints ──────────────────────────────────────────────────────

class TestFreight:
    async def test_freight_estimate(self, async_client):
        resp = await async_client.post(
            "/api/v1/freight-estimate?carrier_code=sf_express&service_type=standard&distance_km=150&weight_kg=25",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "estimated_cost" in data

    async def test_freight_tiers_success(self, async_client):
        resp = await async_client.post("/api/v1/freight-tiers", json={
            "carrier_code": "zto",
            "rule_type": "weight_tiered",
            "min_value": 0,
            "max_value": 10.0,
            "price_per_unit": 6.0,
        })
        assert resp.status_code == 201
        assert resp.json()["rule_type"] == "weight_tiered"


# ── Route Planning Endpoints ───────────────────────────────────────────────

class TestTransferHubs:
    async def test_create_hub_success(self, async_client):
        resp = await async_client.post("/api/v1/transfer-hubs", json={
            "code": "HUB_COV", "name": "Coverage Hub", "type": "primary", "city": "Wuhan",
        })
        assert resp.status_code == 201

    async def test_create_hub_duplicate(self, async_client):
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "HUB_DUP", "name": "Original", "type": "primary", "city": "Beijing",
        })
        resp = await async_client.post("/api/v1/transfer-hubs", json={
            "code": "HUB_DUP", "name": "Duplicate", "type": "primary", "city": "Shanghai",
        })
        assert resp.status_code == 422

    async def test_get_hub_not_found(self, async_client):
        resp = await async_client.get(f"/api/v1/transfer-hubs/{BAD_UUID}")
        assert resp.status_code == 404

    async def test_get_hub_success(self, async_client):
        create = await async_client.post("/api/v1/transfer-hubs", json={
            "code": "HUB_GET", "name": "Get Hub", "type": "primary", "city": "Nanjing",
        })
        hub_id = create.json()["id"]
        resp = await async_client.get(f"/api/v1/transfer-hubs/{hub_id}")
        assert resp.status_code == 200
        assert resp.json()["code"] == "HUB_GET"

    async def test_list_hubs(self, async_client):
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "HUB_LST", "name": "List Hub", "type": "primary", "city": "Chengdu",
        })
        resp = await async_client.get("/api/v1/transfer-hubs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_update_hub_not_found(self, async_client):
        resp = await async_client.patch(f"/api/v1/transfer-hubs/{BAD_UUID}", json={"name": "Nope"})
        assert resp.status_code == 404

    async def test_update_hub_success(self, async_client):
        create = await async_client.post("/api/v1/transfer-hubs", json={
            "code": "HUB_UPD2", "name": "Original", "type": "primary", "city": "Xi'an",
        })
        hub_id = create.json()["id"]
        resp = await async_client.patch(f"/api/v1/transfer-hubs/{hub_id}", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"


class TestCarrierRoutes:
    async def test_add_carrier_route_success(self, async_client):
        resp = await async_client.post("/api/v1/carrier-routes", json={
            "carrier_code": "sf_express", "origin_city": "Wuhan",
            "dest_city": "Changsha", "distance_km": 300, "transit_hours": 4,
            "base_price_per_kg": 8.0,
        })
        assert resp.status_code == 201

    async def test_list_carrier_routes(self, async_client):
        resp = await async_client.get("/api/v1/carrier-routes")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestHubConnections:
    async def test_add_hub_connection_success(self, async_client):
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "HC_A", "name": "Hub A", "type": "primary", "city": "Wuhan",
        })
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "HC_B", "name": "Hub B", "type": "secondary", "city": "Changsha",
        })
        resp = await async_client.post("/api/v1/hub-connections", json={
            "from_hub_code": "HC_A", "to_hub_code": "HC_B",
            "distance_km": 300, "transit_hours": 4,
        })
        assert resp.status_code == 201

    async def test_add_hub_connection_duplicate(self, async_client):
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "DUP_H1", "name": "Dup H1", "type": "primary", "city": "Beijing",
        })
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "DUP_H2", "name": "Dup H2", "type": "secondary", "city": "Shanghai",
        })
        await async_client.post("/api/v1/hub-connections", json={
            "from_hub_code": "DUP_H1", "to_hub_code": "DUP_H2",
            "distance_km": 500, "transit_hours": 6,
        })
        resp = await async_client.post("/api/v1/hub-connections", json={
            "from_hub_code": "DUP_H1", "to_hub_code": "DUP_H2",
            "distance_km": 500, "transit_hours": 6,
        })
        assert resp.status_code == 422

    async def test_list_hub_connections(self, async_client):
        resp = await async_client.get("/api/v1/hub-connections")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestRoutePlans:
    async def test_generate_route_plan_success(self, async_client, transport_order_with_pickup):
        order_id = transport_order_with_pickup["id"]
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "RT_A", "name": "Route A", "type": "primary", "city": "Wuhan",
        })
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "RT_B", "name": "Route B", "type": "secondary", "city": "Changsha",
        })
        await async_client.post("/api/v1/hub-connections", json={
            "from_hub_code": "RT_A", "to_hub_code": "RT_B",
            "distance_km": 500, "transit_hours": 6,
        })
        resp = await async_client.post(f"/api/v1/transport-orders/{order_id}/route-plans?type=auto_gen")
        assert resp.status_code == 201

    async def test_generate_route_plan_not_found(self, async_client):
        resp = await async_client.post(f"/api/v1/transport-orders/{BAD_UUID}/route-plans?type=auto_gen")
        assert resp.status_code == 404

    async def test_get_route_plan_not_found(self, async_client):
        resp = await async_client.get(f"/api/v1/route-plans/{BAD_UUID}")
        assert resp.status_code == 404

    async def test_get_route_plan_success(self, async_client, transport_order_with_pickup):
        order_id = transport_order_with_pickup["id"]
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "RPG_A", "name": "Plan Gen A", "type": "primary", "city": "Wuhan",
        })
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "RPG_B", "name": "Plan Gen B", "type": "secondary", "city": "Changsha",
        })
        await async_client.post("/api/v1/hub-connections", json={
            "from_hub_code": "RPG_A", "to_hub_code": "RPG_B",
            "distance_km": 300, "transit_hours": 4,
        })
        plan = await async_client.post(
            f"/api/v1/transport-orders/{order_id}/route-plans?type=auto_gen",
        )
        plan_id = plan.json()["id"]
        resp = await async_client.get(f"/api/v1/route-plans/{plan_id}")
        assert resp.status_code == 200


class TestSegments:
    async def test_create_segment_success(self, async_client, transport_order):
        order_id = transport_order["id"]
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "SEG_A", "name": "Seg A", "type": "primary", "city": "Wuhan",
        })
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "SEG_B", "name": "Seg B", "type": "secondary", "city": "Changsha",
        })
        resp = await async_client.post("/api/v1/segments", json={
            "transport_order_id": order_id, "segment_no": 0,
            "origin_hub_code": "SEG_A", "dest_hub_code": "SEG_B",
            "carrier_code": "sf_express", "weight_kg": 10,
        })
        assert resp.status_code == 201

    async def test_get_segment_not_found(self, async_client):
        resp = await async_client.get(f"/api/v1/segments/{BAD_UUID}")
        assert resp.status_code == 404

    async def test_get_segment_success(self, async_client, transport_order):
        order_id = transport_order["id"]
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "SEG_G1", "name": "Get Seg A", "type": "primary", "city": "Wuhan",
        })
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "SEG_G2", "name": "Get Seg B", "type": "secondary", "city": "Changsha",
        })
        create = await async_client.post("/api/v1/segments", json={
            "transport_order_id": order_id, "segment_no": 0,
            "origin_hub_code": "SEG_G1", "dest_hub_code": "SEG_G2",
            "carrier_code": "sf_express", "weight_kg": 10,
        })
        seg_id = create.json()["id"]
        resp = await async_client.get(f"/api/v1/segments/{seg_id}")
        assert resp.status_code == 200

    async def test_list_segments(self, async_client, transport_order):
        order_id = transport_order["id"]
        resp = await async_client.get(f"/api/v1/segments?transport_order_id={order_id}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_update_segment_status_not_found(self, async_client):
        resp = await async_client.patch(f"/api/v1/segments/{BAD_UUID}/status?status=dispatched")
        assert resp.status_code == 404

    async def test_update_segment_status_success(self, async_client, transport_order):
        order_id = transport_order["id"]
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "SST_C", "name": "Status C", "type": "primary", "city": "Wuhan",
        })
        await async_client.post("/api/v1/transfer-hubs", json={
            "code": "SST_D", "name": "Status D", "type": "secondary", "city": "Changsha",
        })
        create = await async_client.post("/api/v1/segments", json={
            "transport_order_id": order_id, "segment_no": 0,
            "origin_hub_code": "SST_C", "dest_hub_code": "SST_D",
            "carrier_code": "sf_express", "weight_kg": 10,
        })
        seg_id = create.json()["id"]
        resp = await async_client.patch(f"/api/v1/segments/{seg_id}/status?status=dispatched")
        assert resp.status_code == 200
        assert resp.json()["status"] == "dispatched"


class TestForecastTrainingCoverage:
    """Covers POST /forecast/training in tms/router.py (lines 630-631)."""

    async def test_train_forecast_success(self, async_client, auth_headers, monkeypatch):
        async def mock_train(db, months=6):
            return {"status": "ok", "trained": 5}
        monkeypatch.setattr("src.tms.service.train_forecast", mock_train)
        resp = await async_client.post(
            "/api/v1/forecast/training",
            json={"months": 12},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["trained"] == 5

    async def test_train_forecast_default_months(self, async_client, auth_headers, monkeypatch):
        async def mock_train(db, months=6):
            return {"status": "ok", "trained": 0}
        monkeypatch.setattr("src.tms.service.train_forecast", mock_train)
        resp = await async_client.post(
            "/api/v1/forecast/training",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["trained"] == 0
