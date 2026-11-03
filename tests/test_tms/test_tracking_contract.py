"""Contract tests for the TMS transport-status and tracking-scan request shapes.

Two defects lived here at once:

* ``PUT /transport-orders/{id}/status`` read ``status`` from the query only, so
  the body shape every other status endpoint in this API uses answered 422
  "Field required: status".
* ``POST /transport-orders/{id}/tracking-events`` took a bare ``dict``.  A body
  that said ``location``/``description`` was accepted, the service read
  ``location_name``/``remark``, and the scan was stored with both columns NULL;
  an event type the enum did not know reached the enum constructor and raised,
  which the client saw as a 500 for a typo.

Both ends are pinned here — the HTTP contract, and the service boundary that
internal callers (outbox replay, PDA mutation sync) reach without a schema in
front of them.
"""

import uuid

import pytest

from src.core.exceptions import NotFoundException, ValidationException
from src.tms import service as tms_service

BAD_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
async def auth_headers(async_client):
    uname = f"tmsctrk_{uuid.uuid4().hex[:8]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def transport_order(async_client, auth_headers):
    resp = await async_client.post("/api/v1/transport-orders", json={
        "carrier_code": "sf_express",
        "pickup_warehouse_id": str(uuid.uuid4()),
        "delivery_name": "Contract Test",
        "delivery_address": {"city": "Beijing"},
    }, headers=auth_headers)
    assert resp.status_code in (200, 201), resp.text[:200]
    return resp.json()


# ── Status update: the body is the documented shape ─────────────────────────

class TestStatusUpdateBody:
    async def test_body_form_is_accepted(self, async_client, auth_headers, transport_order):
        resp = await async_client.put(
            f"/api/v1/transport-orders/{transport_order['id']}/status",
            json={"status": "dispatched"}, headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text[:200]
        assert resp.json()["status"] == "dispatched"

    async def test_query_form_still_works(self, async_client, auth_headers, transport_order):
        """The query form was the only one that ever worked, and existing
        clients (and tests/test_tms/test_tms_coverage.py) still send it."""
        resp = await async_client.put(
            f"/api/v1/transport-orders/{transport_order['id']}/status?status=dispatched",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text[:200]
        assert resp.json()["status"] == "dispatched"

    async def test_neither_form_says_what_is_missing(self, async_client, auth_headers, transport_order):
        resp = await async_client.put(
            f"/api/v1/transport-orders/{transport_order['id']}/status",
            headers=auth_headers,
        )
        assert resp.status_code == 422, resp.text[:200]
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR", resp.text[:200]
        assert "status" in body["error"]["message"], resp.text[:200]

    async def test_an_invalid_status_is_not_relabelled(self, async_client, auth_headers, transport_order):
        """created -> delivered is not a legal jump; the service's own
        ValidationException must keep its code on the wire."""
        resp = await async_client.put(
            f"/api/v1/transport-orders/{transport_order['id']}/status",
            json={"status": "delivered"}, headers=auth_headers,
        )
        assert resp.status_code == 422, resp.text[:200]
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR", resp.text[:200]

    async def test_a_missing_order_stays_a_404_with_its_code(self, async_client, auth_headers):
        resp = await async_client.put(
            f"/api/v1/transport-orders/{BAD_UUID}/status",
            json={"status": "dispatched"}, headers=auth_headers,
        )
        assert resp.status_code == 404, resp.text[:200]
        assert resp.json()["error"]["code"] == "NOT_FOUND", resp.text[:200]


# ── Tracking scans ──────────────────────────────────────────────────────────

class TestTrackingScanContract:
    async def test_a_scan_keeps_what_the_operator_typed(self, async_client, auth_headers, transport_order):
        resp = await async_client.post(
            f"/api/v1/transport-orders/{transport_order['id']}/tracking-events",
            json={"event_type": "pickup_completed", "location_name": "上海分拨中心",
                  "remark": "已揽收"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text[:200]
        body = resp.json()
        assert body["event_type"] == "pickup_completed"
        assert body["location_name"] == "上海分拨中心"
        assert body["remark"] == "已揽收"

    async def test_an_unknown_event_type_is_a_422_not_a_500(self, async_client, auth_headers, transport_order):
        resp = await async_client.post(
            f"/api/v1/transport-orders/{transport_order['id']}/tracking-events",
            json={"event_type": "PICKED_UP"}, headers=auth_headers,
        )
        assert resp.status_code == 422, resp.text[:200]
        # A 422 that does not say what was acceptable leaves the client guessing.
        assert "in_transit" in resp.text, resp.text[:200]

    async def test_wrong_field_names_are_refused_not_dropped(self, async_client, auth_headers, transport_order):
        """The old route answered 200 to this body and filed the scan with
        location_name and remark NULL."""
        resp = await async_client.post(
            f"/api/v1/transport-orders/{transport_order['id']}/tracking-events",
            json={"event_type": "in_transit", "location": "上海分拨中心", "description": "在途"},
            headers=auth_headers,
        )
        assert resp.status_code == 422, resp.text[:200]
        assert "location" in resp.text, resp.text[:200]

    async def test_the_scan_is_readable_back(self, async_client, auth_headers, transport_order):
        order_id = transport_order["id"]
        post = await async_client.post(
            f"/api/v1/transport-orders/{order_id}/tracking-events",
            json={"event_type": "arrived_hub", "location_name": "武汉中转场"},
            headers=auth_headers,
        )
        assert post.status_code == 200, post.text[:200]
        listing = await async_client.get(
            f"/api/v1/transport-orders/{order_id}/tracking-events", headers=auth_headers,
        )
        assert listing.status_code == 200, listing.text[:200]
        items = listing.json()["items"]
        match = [i for i in items if i["id"] == post.json()["id"]]
        assert match, "the scan the API accepted is not in the history it serves"
        assert match[0]["location_name"] == "武汉中转场"

    async def test_the_standalone_route_refuses_undeclared_keys(self, async_client, auth_headers, transport_order):
        resp = await async_client.post("/api/v1/tracking-events", json={
            "transport_order_id": transport_order["id"],
            "event_type": "in_transit",
            "description": "在途",
        }, headers=auth_headers)
        assert resp.status_code == 422, resp.text[:200]
        assert "description" in resp.text, resp.text[:200]


# ── Service boundary (no schema in front of it) ─────────────────────────────

class TestTrackingScanService:
    @pytest.fixture
    async def order(self, db_session):
        from src.wms.service import create_warehouse
        wh = await create_warehouse(db_session, {
            "code": f"WH-CTRK-{uuid.uuid4().hex[:8]}", "name": "Contract WH", "type": "center",
        })
        return await tms_service.create_transport_order(db_session, {
            "pickup_warehouse_id": wh["id"], "delivery_name": "Contract Scan",
        })

    async def test_unknown_event_type_is_a_validation_error(self, db_session, order):
        """Internal callers reach the service without a Pydantic model in
        front of it; a typo must not surface as a bare ValueError."""
        with pytest.raises(ValidationException) as exc:
            await tms_service.create_tracking_event(db_session, {
                "transport_order_id": order["id"], "event_type": "PICKED_UP",
            })
        assert "event_type" in exc.value.message
        assert "pickup_completed" in exc.value.message

    async def test_missing_event_type_says_so(self, db_session, order):
        with pytest.raises(ValidationException, match="event_type is required"):
            await tms_service.create_tracking_event(db_session, {
                "transport_order_id": order["id"],
            })

    async def test_an_unparseable_operator_id_is_refused(self, db_session, order):
        """``data.get("operator_id") and uuid.UUID(...) or None`` used to turn a
        mistyped id into "no operator at all", so the scan looked anonymous
        instead of wrong."""
        with pytest.raises(ValidationException, match="operator_id"):
            await tms_service.create_tracking_event(db_session, {
                "transport_order_id": order["id"],
                "event_type": "delivered",
                "operator_id": "not-a-uuid",
            })

    async def test_a_missing_order_is_still_a_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await tms_service.create_tracking_event(db_session, {
                "transport_order_id": str(uuid.uuid4()),
                "event_type": "delivered",
            })
