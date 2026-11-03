"""The 发货管理 screen and the packing/shipment endpoints, read against each other.

``frontend/src/views/warehouses/ShipmentList.vue`` is a warehouse clerk's 发货
workspace: a 新建发货单 dialog that names a warehouse and a textarea of order
ids, a 打包记录 form whose single input is labelled 波次ID, and a 发货 button on
every shipment row.  Read against ``src/wms``, none of the three worked:

* the packing form posts ``{"wave_id": …}``; ``create_packing`` read
  ``data["picking_wave_id"]`` — a KeyError, a 500, and a 打包记录成功 alert
  nobody ever saw;
* the dialog posts ``{"warehouse_id": …, "order_ids": […]}``; ``create_shipment``
  read ``data["order_id"]`` — the same KeyError on every 提交, so the screen
  that hands goods to a carrier had never created a shipment;
* the 发货 button posts **no body at all**, and the route asked for a required
  ``dict`` body — FastAPI answered 422 ``body: Field required`` before the
  handler ran, and the screen only ``console.warn``s, so the row never moved to
  已发货 and nothing appeared on the screen.

Two more were visible in the list itself: its first column asks for
``shipment_no``, a field the API never had, so every row rendered 发货单号
blank; and its order ids were never checked against the orders table, so a
shipment could be filed for an order that does not exist (SQLite accepts it,
PostgreSQL answers with an FK violation the operator sees as a 500).

The assertions below are the shapes the screen sends, in the keys it sends
them, and the answers a clerk should get.
"""
import uuid
from decimal import Decimal

import pytest

from src.core.exceptions import NotFoundException, ValidationException
from src.wms import service as wms_service

WAVE_URL = "/api/v1/warehouses/picking-waves"


@pytest.fixture
async def auth_headers(async_client):
    uname = f"shipctr_{uuid.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(autouse=True)
async def _authenticated(async_client, auth_headers):
    async_client.headers.update(auth_headers)
    return auth_headers


async def _warehouse(client) -> str:
    resp = await client.post("/api/v1/warehouses", json={
        "code": f"WH-{uuid.uuid4().hex[:6]}", "name": "Ship Contract WH",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _order(client) -> str:
    resp = await client.post("/api/v1/orders", json={
        "customer_id": f"C-{uuid.uuid4().hex[:6]}",
        "items": [{"gtin": "4006381333931", "sku": f"SKU-{uuid.uuid4().hex[:6]}",
                   "quantity": 1, "unit_price": "10.00"}],
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _completed_wave(client, wh_id: str) -> str:
    """A wave a packer is allowed to pack: created, started, completed."""
    resp = await client.post(WAVE_URL, json={"warehouse_id": wh_id, "order_ids": [await _order(client)]})
    assert resp.status_code == 201, resp.text
    wave_id = resp.json()["id"]
    assert (await client.post(f"{WAVE_URL}/{wave_id}/start")).status_code == 200
    assert (await client.post(f"{WAVE_URL}/{wave_id}/complete")).status_code == 200
    return wave_id


def _fields(resp) -> str:
    """Everything a refusal said: the sentence, the detail, each entry's field and value.

    The console shows the top-level sentence, so that is the sentence the test
    has to read — the field names and the sent values ride in ``errors``, and a
    message that names the key is what tells the clerk which box to fix.
    """
    body = resp.json()
    error = body.get("error", {})
    parts = [error.get("message", ""), str(body.get("detail", ""))]
    parts += [f"{e.get('field')} {e.get('message')} {e.get('value')}" for e in body.get("errors", [])]
    return " ".join(str(p) for p in parts)


class TestPackingBody:
    """POST /warehouses/packing — the 打包记录 form's body."""

    @pytest.mark.asyncio
    async def test_the_screens_own_key_creates_the_record(self, async_client):
        """``{"wave_id": …}`` is what ShipmentList.vue posts, and it is the shape that works."""
        wh_id = await _warehouse(async_client)
        wave_id = await _completed_wave(async_client, wh_id)
        resp = await async_client.post("/api/v1/warehouses/packing", json={"wave_id": wave_id})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["picking_wave_id"] == wave_id
        assert body["box_count"] == 1

    @pytest.mark.asyncio
    async def test_the_services_own_key_still_works(self, async_client):
        wh_id = await _warehouse(async_client)
        wave_id = await _completed_wave(async_client, wh_id)
        resp = await async_client.post("/api/v1/warehouses/packing", json={
            "picking_wave_id": wave_id, "box_count": 4, "packed_by": "仓管员-张", "notes": "两箱加一箱",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["box_count"] == 4
        assert body["packed_by"] == "仓管员-张"
        assert body["notes"] == "两箱加一箱"

    @pytest.mark.asyncio
    async def test_missing_wave_is_refused_by_the_key_that_should_name_it(self, async_client):
        resp = await async_client.post("/api/v1/warehouses/packing", json={})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
        assert "picking_wave_id" in _fields(resp)

    @pytest.mark.asyncio
    async def test_a_wave_id_that_is_not_an_id_names_the_value(self, async_client):
        resp = await async_client.post("/api/v1/warehouses/packing", json={"wave_id": "WAVE-0021"})
        assert resp.status_code == 422
        fields = _fields(resp)
        assert "picking_wave_id" in fields
        assert "WAVE-0021" in fields

    @pytest.mark.asyncio
    async def test_unknown_wave_is_404(self, async_client):
        resp = await async_client.post("/api/v1/warehouses/packing", json={"wave_id": str(uuid.uuid4())})
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_a_wave_still_being_picked_is_refused_by_name(self, async_client):
        wh_id = await _warehouse(async_client)
        resp = await async_client.post(WAVE_URL, json={
            "warehouse_id": wh_id, "order_ids": [await _order(async_client)],
        })
        wave = resp.json()
        resp = await async_client.post("/api/v1/warehouses/packing", json={"wave_id": wave["id"]})
        assert resp.status_code == 422
        assert "Only completed waves can be packed" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_box_count_that_is_not_a_number_is_refused(self, async_client):
        """A box count is an Integer column; ``"三箱"`` used to reach it and die in the insert."""
        wh_id = await _warehouse(async_client)
        wave_id = await _completed_wave(async_client, wh_id)
        resp = await async_client.post("/api/v1/warehouses/packing", json={"wave_id": wave_id, "box_count": "三箱"})
        assert resp.status_code == 422
        assert "box_count" in _fields(resp)

    @pytest.mark.asyncio
    async def test_a_wave_with_no_boxes_is_refused(self, async_client):
        wh_id = await _warehouse(async_client)
        wave_id = await _completed_wave(async_client, wh_id)
        resp = await async_client.post("/api/v1/warehouses/packing", json={"wave_id": wave_id, "box_count": 0})
        assert resp.status_code == 422
        assert "box_count" in _fields(resp)

    @pytest.mark.asyncio
    async def test_the_envelope_shape_is_accepted(self, async_client):
        wh_id = await _warehouse(async_client)
        wave_id = await _completed_wave(async_client, wh_id)
        resp = await async_client.post("/api/v1/warehouses/packing", json={
            "data": {"wave_id": wave_id, "box_count": 2},
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["box_count"] == 2

    @pytest.mark.asyncio
    async def test_an_unrecognised_key_is_refused_not_ignored(self, async_client):
        """``boxes`` is not the field's name; a body that spells it must not pack 1 box quietly."""
        wh_id = await _warehouse(async_client)
        wave_id = await _completed_wave(async_client, wh_id)
        resp = await async_client.post("/api/v1/warehouses/packing", json={"wave_id": wave_id, "boxes": 5})
        assert resp.status_code == 422
        assert "boxes" in _fields(resp)

    @pytest.mark.asyncio
    async def test_direct_callers_are_guarded_too(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-DIRECT-PACK", "name": "Direct"})
        with pytest.raises(ValidationException, match="picking_wave_id"):
            await wms_service.create_packing(db_session, {})
        with pytest.raises(ValidationException, match="not a wave id"):
            await wms_service.create_packing(db_session, {"wave_id": "wave-9"})
        wave = await wms_service.create_picking_wave(db_session, {
            "warehouse_id": wh["id"], "order_ids": [str(uuid.uuid4())],
        })
        await wms_service.start_picking(db_session, wave["id"])
        await wms_service.complete_picking(db_session, wave["id"])
        with pytest.raises(ValidationException, match="box_count"):
            await wms_service.create_packing(db_session, {"wave_id": wave["id"], "box_count": "三箱"})
        with pytest.raises(ValidationException, match="box_count"):
            await wms_service.create_packing(db_session, {"wave_id": wave["id"], "box_count": 0})


class TestShipmentBody:
    """POST /warehouses/shipments — the 新建发货单 dialog's body."""

    @pytest.mark.asyncio
    async def test_the_screens_own_body_creates_one_shipment_per_order(self, async_client):
        wh_id = await _warehouse(async_client)
        order_ids = [await _order(async_client), await _order(async_client)]
        resp = await async_client.post("/api/v1/warehouses/shipments", json={
            "warehouse_id": wh_id, "order_ids": order_ids,
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["count"] == 2
        assert {s["order_id"] for s in body["shipments"]} == set(order_ids)
        # The number the list's first column asks for, on every row.
        assert all(s["shipment_no"].startswith("SHIP-") for s in body["shipments"])
        assert len({s["shipment_no"] for s in body["shipments"]}) == 2

    @pytest.mark.asyncio
    async def test_single_order_body_is_still_accepted(self, async_client):
        wh_id = await _warehouse(async_client)
        order_id = await _order(async_client)
        resp = await async_client.post("/api/v1/warehouses/shipments", json={
            "order_id": order_id, "warehouse_id": wh_id, "tracking_number": "SF1234567890",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["count"] == 1
        assert body["shipments"][0]["tracking_number"] == "SF1234567890"

    @pytest.mark.asyncio
    async def test_no_orders_is_refused_by_the_key_that_names_them(self, async_client):
        """A shipment is goods leaving against orders; an empty list says nothing leaves."""
        wh_id = await _warehouse(async_client)
        resp = await async_client.post("/api/v1/warehouses/shipments", json={"warehouse_id": wh_id})
        assert resp.status_code == 422
        assert "order_ids" in _fields(resp)

    @pytest.mark.asyncio
    async def test_no_warehouse_is_refused_by_the_key_that_names_it(self, async_client):
        resp = await async_client.post("/api/v1/warehouses/shipments", json={"order_ids": [await _order(async_client)]})
        assert resp.status_code == 422
        assert "warehouse_id" in _fields(resp)

    @pytest.mark.asyncio
    async def test_an_order_id_that_is_not_an_id_names_the_value(self, async_client):
        wh_id = await _warehouse(async_client)
        resp = await async_client.post("/api/v1/warehouses/shipments", json={
            "warehouse_id": wh_id, "order_ids": ["ORD-2024-0001"],
        })
        assert resp.status_code == 422
        fields = _fields(resp)
        assert "order_ids" in fields
        assert "ORD-2024-0001" in fields

    @pytest.mark.asyncio
    async def test_an_order_that_does_not_exist_is_404(self, async_client):
        """The defect this closes: SQLite used to accept these, PostgreSQL crashed on them."""
        wh_id = await _warehouse(async_client)
        missing = str(uuid.uuid4())
        resp = await async_client.post("/api/v1/warehouses/shipments", json={
            "warehouse_id": wh_id, "order_ids": [missing],
        })
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"
        assert missing in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_a_warehouse_listed_twice_ships_once(self, async_client):
        wh_id = await _warehouse(async_client)
        order_id = await _order(async_client)
        resp = await async_client.post("/api/v1/warehouses/shipments", json={
            "warehouse_id": wh_id, "order_ids": [order_id, order_id],
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["count"] == 1

    @pytest.mark.asyncio
    async def test_a_warehouse_can_be_named_by_code(self, async_client):
        """The transfer endpoints accept a warehouse code; the shipment screen's neighbours do."""
        wh_id = await _warehouse(async_client)
        code = (await async_client.get(f"/api/v1/warehouses/{wh_id}")).json()["code"]
        resp = await async_client.post("/api/v1/warehouses/shipments", json={
            "warehouse_id": code, "order_ids": [await _order(async_client)],
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["shipments"][0]["warehouse_id"] == wh_id

    @pytest.mark.asyncio
    async def test_a_packing_record_that_does_not_exist_is_404(self, async_client):
        wh_id = await _warehouse(async_client)
        resp = await async_client.post("/api/v1/warehouses/shipments", json={
            "warehouse_id": wh_id,
            "order_ids": [await _order(async_client)],
            "packing_record_id": str(uuid.uuid4()),
        })
        assert resp.status_code == 404
        assert "Packing record" in resp.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_a_packed_wave_ships_as_packed(self, async_client):
        wh_id = await _warehouse(async_client)
        wave_id = await _completed_wave(async_client, wh_id)
        pack = await async_client.post("/api/v1/warehouses/packing", json={"wave_id": wave_id, "box_count": 2})
        assert pack.status_code == 201, pack.text
        resp = await async_client.post("/api/v1/warehouses/shipments", json={
            "warehouse_id": wh_id,
            "order_ids": [await _order(async_client)],
            "packing_record_id": pack.json()["id"],
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["shipments"][0]["status"] == "packed"

    @pytest.mark.asyncio
    async def test_the_envelope_shape_is_accepted(self, async_client):
        wh_id = await _warehouse(async_client)
        resp = await async_client.post("/api/v1/warehouses/shipments", json={
            "data": {"warehouse_id": wh_id, "order_ids": [await _order(async_client)]},
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["count"] == 1

    @pytest.mark.asyncio
    async def test_an_unrecognised_key_is_refused_not_ignored(self, async_client):
        """``carrier_code`` is not the field's name — the carrier would have vanished quietly."""
        wh_id = await _warehouse(async_client)
        resp = await async_client.post("/api/v1/warehouses/shipments", json={
            "warehouse_id": wh_id, "order_ids": [await _order(async_client)], "carrier_code": "sf_express",
        })
        assert resp.status_code == 422
        assert "carrier_code" in _fields(resp)

    @pytest.mark.asyncio
    async def test_the_shipment_number_the_list_shows(self, async_client):
        """发货管理's first column reads ``shipment_no``; every row must answer it."""
        wh_id = await _warehouse(async_client)
        created = await async_client.post("/api/v1/warehouses/shipments", json={
            "warehouse_id": wh_id, "order_ids": [await _order(async_client)],
        })
        shipment_no = created.json()["shipments"][0]["shipment_no"]
        listed = await async_client.get("/api/v1/warehouses/shipments")
        assert listed.status_code == 200
        rows = listed.json()
        assert any(row["shipment_no"] == shipment_no for row in rows), rows

    @pytest.mark.asyncio
    async def test_direct_callers_are_guarded_too(self, db_session):
        wh = await wms_service.create_warehouse(db_session, {"code": "WH-DIRECT-SHIP", "name": "Direct Ship"})
        with pytest.raises(ValidationException, match="warehouse_id"):
            await wms_service.create_shipment(db_session, {"order_id": str(uuid.uuid4())})
        with pytest.raises(ValidationException, match="order_ids"):
            await wms_service.create_shipment(db_session, {"warehouse_id": wh["id"]})
        with pytest.raises(ValidationException, match="not an order id"):
            await wms_service.create_shipment(db_session, {"warehouse_id": wh["id"], "order_ids": ["ORD-1"]})
        with pytest.raises(NotFoundException, match="not found"):
            await wms_service.create_shipment(db_session, {
                "warehouse_id": wh["id"], "order_ids": [str(uuid.uuid4())],
            })


class TestShipMark:
    """POST /warehouses/shipments/{id}/ship — the 发货 button."""

    async def _shipment(self, client, wh_id: str) -> dict:
        resp = await client.post("/api/v1/warehouses/shipments", json={
            "warehouse_id": wh_id, "order_ids": [await _order(client)],
        })
        assert resp.status_code == 201, resp.text
        return resp.json()["shipments"][0]

    @pytest.mark.asyncio
    async def test_the_buttons_own_request_no_body_marks_it_shipped(self, async_client):
        """ShipmentList.vue posts this route with no body at all.

        The route used to require a ``dict`` body, so FastAPI answered
        ``body: Field required`` before the handler ran — the row stayed at
        待发货 and the screen only logged to the console.
        """
        wh_id = await _warehouse(async_client)
        shipment = await self._shipment(async_client, wh_id)
        resp = await async_client.post(f"/api/v1/warehouses/shipments/{shipment['id']}/ship")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "shipped"
        assert body["shipment_no"] == shipment["shipment_no"]
        assert body["shipped_at"]

    @pytest.mark.asyncio
    async def test_the_tracking_number_the_carrier_needs_is_recorded(self, async_client):
        wh_id = await _warehouse(async_client)
        shipment = await self._shipment(async_client, wh_id)
        resp = await async_client.post(f"/api/v1/warehouses/shipments/{shipment['id']}/ship", json={
            "tracking_number": "YT9876543210", "carrier": "yunda",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["tracking_number"] == "YT9876543210"
        assert resp.json()["carrier"] == "yunda"

    @pytest.mark.asyncio
    async def test_nothing_sent_keeps_what_the_shipment_already_carried(self, async_client):
        """The 发货 button sends no tracking number; the one on the record stays."""
        wh_id = await _warehouse(async_client)
        resp = await async_client.post("/api/v1/warehouses/shipments", json={
            "warehouse_id": wh_id,
            "order_ids": [await _order(async_client)],
            "tracking_number": "SF-KEEP-1",
            "carrier": "sf_express",
        })
        shipment = resp.json()["shipments"][0]
        marked = await async_client.post(f"/api/v1/warehouses/shipments/{shipment['id']}/ship")
        assert marked.status_code == 200, marked.text
        assert marked.json()["tracking_number"] == "SF-KEEP-1"
        assert marked.json()["carrier"] == "sf_express"

    @pytest.mark.asyncio
    async def test_a_body_that_spells_the_field_wrong_is_refused(self, async_client):
        """``tracking`` is not the key; ignoring it is how a parcel leaves untraceable."""
        wh_id = await _warehouse(async_client)
        shipment = await self._shipment(async_client, wh_id)
        resp = await async_client.post(f"/api/v1/warehouses/shipments/{shipment['id']}/ship", json={"tracking": "YT1"})
        assert resp.status_code == 422
        assert "tracking" in _fields(resp)

    @pytest.mark.asyncio
    async def test_shipping_twice_is_refused(self, async_client):
        """A second 发货 click used to stamp a second handover onto the record."""
        wh_id = await _warehouse(async_client)
        shipment = await self._shipment(async_client, wh_id)
        ship_url = f"/api/v1/warehouses/shipments/{shipment['id']}/ship"
        first = await async_client.post(ship_url, json={"tracking_number": "A"})
        assert first.status_code == 200
        second = await async_client.post(ship_url, json={"tracking_number": "B"})
        assert second.status_code == 422
        assert "already shipped" in second.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_a_shipment_id_that_is_not_an_id_answers_like_an_absent_one(self, async_client):
        resp = await async_client.post("/api/v1/warehouses/shipments/not-a-uuid/ship", json={})
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_a_cancelled_shipment_does_not_leave_the_warehouse(self, db_session):
        from src.models.shared_models import Customer
        from src.oms.models import Order, OrderStatus
        from src.wms.models import Shipment, ShipmentStatus

        wh = await wms_service.create_warehouse(db_session, {"code": "WH-CANCEL-SHIP", "name": "Cancel"})
        customer = Customer(id=uuid.uuid4(), code=f"C-{uuid.uuid4().hex[:6]}", name="Cancel Customer")
        order = Order(
            id=uuid.uuid4(), order_no=f"ORD-{uuid.uuid4().hex[:10].upper()}",
            status=OrderStatus.PENDING, customer_id=customer.id,
            items={}, total_amount=Decimal("0.00"), notes="",
        )
        db_session.add_all([customer, order])
        await db_session.commit()

        shipment = (await wms_service.create_shipment(db_session, {
            "warehouse_id": wh["id"], "order_ids": [str(order.id)],
        }))["shipments"][0]
        row = await db_session.get(Shipment, uuid.UUID(shipment["id"]))
        row.status = ShipmentStatus.CANCELLED
        await db_session.commit()

        with pytest.raises(ValidationException, match="cancelled"):
            await wms_service.mark_shipped(db_session, shipment["id"], "TRK", "SF")
