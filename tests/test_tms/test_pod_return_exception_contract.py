"""The three bodies a delivery person touches, read as the shape they are sent in.

``POST /transport-orders/{id}/pod``, ``POST /return-orders`` and
``POST /exceptions`` all declared ``data: dict``, and each of them is filed from
a screen — ``TransportOrderDetail.vue``, ``ReturnOrderList.vue``,
``ExceptionList.vue`` — whose fields are not the keys the handlers reached for:

* the signature form types a recipient (``receiver_name``), the record stored
  ``signed_by = "unknown"``, and a second submission of a POD that already
  exists was answered 201 and written nowhere;
* the return form's reason is free text and its shipment is the number printed
  in the list, and the service read ``ReturnReason(data["reason"])`` and
  ``uuid.UUID(data["transport_order_id"])`` — so 创建退货 answered 500 for every
  return anyone filed, and the shipment it named was dropped;
* the exception form sends ``exception_type``, the handler read ``data["type"]``,
  and a ``KeyError`` inside a handler is reported as a server failure: 报告异常
  answered 500 every time it was pressed.

All three bodies are typed now (``src/tms/schemas.py``), the field names a
client uses are aliases of the field that stores them, a value outside a
vocabulary is a 422 that names the vocabulary, and a shipment named by its
``TPL-…`` number resolves to that shipment.
"""

import uuid as uuid_mod

import pytest

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def auth_headers(async_client):
    uname = f"podctr_{uuid_mod.uuid4().hex[:8]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(autouse=True)
async def _authenticated(async_client, auth_headers):
    async_client.headers.update(auth_headers)
    yield


@pytest.fixture
async def order(async_client) -> dict:
    """A transport order to sign for, return, and report exceptions against."""
    r = await async_client.post("/api/v1/transport-orders", json={
        "carrier_code": "sf_express", "delivery_name": f"收货人 {uuid_mod.uuid4().hex[:6]}",
    })
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def warehouse(async_client) -> dict:
    r = await async_client.post("/api/v1/warehouses", json={
        "code": f"WH-RTN-{uuid_mod.uuid4().hex[:8]}", "name": "Return WH", "type": "center",
    })
    assert r.status_code == 201, r.text
    return r.json()


async def _pod(async_client, order_id: str, body: dict):
    return await async_client.post(f"/api/v1/transport-orders/{order_id}/pod", json=body)


async def _return(async_client, body: dict):
    return await async_client.post("/api/v1/return-orders", json=body)


async def _exception(async_client, body: dict):
    return await async_client.post("/api/v1/exceptions", json=body)


# ── Proof of delivery ────────────────────────────────────────────────────────


class TestProofOfDelivery:
    async def test_the_documented_shape_is_accepted(self, async_client, order):
        """``docs/functional-test-plan.md`` 6.3.1."""
        resp = await _pod(async_client, order["id"], {"signed_by": "张三", "signature_type": "digital"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["signed_by"] == "张三"
        assert resp.json()["signature_type"] == "digital"

    async def test_the_name_the_screen_types_is_the_recipient(self, async_client, order):
        """``TransportOrderDetail.vue`` posts ``{receiver_name, notes}``; the
        column is ``signed_by``, so every signature the console recorded was
        filed as ``signed_by = "unknown"``."""
        resp = await _pod(async_client, order["id"], {"receiver_name": "李四", "notes": "已当面签收"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["signed_by"] == "李四", "the recipient the form typed did not reach the record"
        assert body["notes"] == "已当面签收"

    async def test_photos_sent_as_urls_are_recorded_as_urls(self, async_client, order):
        """The column is documented ``[{url, timestamp}]``; the screen that
        posts photos sends bare URLs, and the list it displays is a list of
        bare URLs."""
        resp = await _pod(async_client, order["id"], {
            "signed_by": "王五",
            "photos": ["https://cdn.example.com/pod/1.jpg", "https://cdn.example.com/pod/2.jpg"],
        })
        assert resp.status_code == 201, resp.text
        rows = resp.json()["delivery_photo_urls"]
        assert [row["url"] for row in rows] == [
            "https://cdn.example.com/pod/1.jpg", "https://cdn.example.com/pod/2.jpg",
        ], "the photos the driver sent are not on the record"

    async def test_a_photo_that_names_no_url_is_refused(self, async_client, order):
        """A photo entry the record cannot point at is a photo nobody can see."""
        resp = await _pod(async_client, order["id"], {"signed_by": "赵六", "photos": [{"name": "front-door"}]})
        assert resp.status_code == 422, resp.text
        # The field named is the key the caller sent — ``photos`` is an accepted
        # spelling of ``delivery_photo_urls``, and its errors say ``photos``.
        assert any("photos" in e["field"] for e in resp.json()["errors"]), resp.text

    async def test_re_sending_the_pod_records_what_was_sent(self, async_client, order):
        """``pod_records.transport_order_id`` is unique.  A second submission
        used to find the existing record and read nothing: the caller was
        answered 201 for a signature they had just sent."""
        first = await _pod(async_client, order["id"], {"signed_by": "第一签收人"})
        assert first.status_code == 201, first.text
        assert first.json()["signed_by"] == "第一签收人"

        second = await _pod(async_client, order["id"], {
            "signed_by": "第二签收人", "photos": ["https://cdn.example.com/pod/late.jpg"],
        })
        assert second.status_code == 201, second.text
        assert second.json()["signed_by"] == "第二签收人", "the re-sent signature was not recorded"
        assert second.json()["delivery_photo_urls"][0]["url"] == "https://cdn.example.com/pod/late.jpg"
        assert second.json()["id"] == first.json()["id"], "the re-submission created a second POD for one order"

    async def test_the_pod_of_an_order_that_does_not_exist_is_a_404(self, async_client):
        resp = await _pod(async_client, str(uuid_mod.uuid4()), {"signed_by": "无人"})
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND", resp.text

    async def test_the_signature_vocabulary_is_named(self, async_client, order):
        resp = await _pod(async_client, order["id"], {"signed_by": "张三", "signature_type": "thumbprint"})
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["success"] is False and body["error"]["code"] == "VALIDATION_ERROR", resp.text
        assert "physical" in resp.text and "digital" in resp.text, "the refusal did not name the signature types"

    async def test_the_envelope_shape_is_accepted(self, async_client, order):
        resp = await _pod(async_client, order["id"], {"data": {"signed_by": "信封签收人"}})
        assert resp.status_code == 201, resp.text
        assert resp.json()["signed_by"] == "信封签收人"

    async def test_a_key_the_endpoint_does_not_read_is_refused_by_name(self, async_client, order):
        resp = await _pod(async_client, order["id"], {"signer": "张三", "signed_by_photo": "x"})
        assert resp.status_code == 422, resp.text
        fields = [e["field"] for e in resp.json()["errors"]]
        assert any("signer" in f for f in fields), resp.text

    async def test_an_update_changes_the_signature_type(self, async_client, order):
        """``PUT /transport-orders/{id}/pod`` (docs 6.3.3): the field the paper
        receipt to on-screen signature update changes is ``signature_type``,
        and the update path did not contain it."""
        created = await _pod(async_client, order["id"], {"signed_by": "纸面签收"})
        assert created.status_code == 201, created.text

        resp = await async_client.put(f"/api/v1/transport-orders/{order['id']}/pod", json={
            "signature_type": "digital", "notes": "已当面签收",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["signature_type"] == "digital", "the signature type the update sent was dropped"
        assert resp.json()["notes"] == "已当面签收"


# ── Return orders ────────────────────────────────────────────────────────────


class TestReturnOrderBody:
    async def test_the_shape_the_console_sends_files_the_return(self, async_client, order):
        """``ReturnOrderList.vue`` posts ``{order_no, reason}`` where ``order_no``
        is the ``TPL-…`` number printed in the list — the number the API itself
        prints.  The service read ``uuid.UUID(data["transport_order_id"])``, so
        every return filed from the console answered 500."""
        resp = await _return(async_client, {"order_no": order["transport_no"], "reason": "damaged"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["reason"] == "damaged"
        assert body["transport_order_id"] == order["id"], "the shipment the number named was not linked"
        assert body["status"] == "requested"

    async def test_the_reason_is_the_reason_vocabulary(self, async_client, order):
        """The console's reason field is a textarea, so "damaged package" is
        ordinary input; it reached ``ReturnReason(...)`` and raised inside the
        handler."""
        resp = await _return(async_client, {"order_no": order["transport_no"], "reason": "damaged package"})
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR", resp.text
        assert "wrong_item" in resp.text and "quality_issue" in resp.text, (
            "the refusal did not name the reason codes the domain knows"
        )

    async def test_the_reason_is_required(self, async_client):
        resp = await _return(async_client, {})
        assert resp.status_code == 422, resp.text
        assert any("reason" in e["field"] for e in resp.json()["errors"]), resp.text

    async def test_a_number_that_names_no_shipment_is_answered_by_the_field(self, async_client):
        resp = await _return(async_client, {"order_no": "TPL-19700101-0001", "reason": "damaged"})
        assert resp.status_code == 404, resp.text
        assert "transport_order_id" in resp.json()["error"]["message"], (
            "the refusal did not name the field that named the shipment"
        )

    async def test_a_destination_the_handheld_scans_is_resolved(self, async_client, order, warehouse):
        """A bay door carries a code, not a uuid; the value was written straight
        into the UUID column."""
        resp = await _return(async_client, {
            "order_no": order["transport_no"], "reason": "wrong_item",
            "destination_warehouse_id": warehouse["code"],
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["destination_warehouse_id"] == warehouse["id"], (
            "the warehouse the handheld scanned did not land on the return"
        )

    async def test_a_destination_that_names_no_warehouse_is_refused_by_the_field(self, async_client, order):
        resp = await _return(async_client, {
            "order_no": order["transport_no"], "reason": "damaged",
            "destination_warehouse_id": "WH-NOT-THERE",
        })
        assert resp.status_code == 404, resp.text
        assert "destination_warehouse_id" in resp.json()["error"]["message"], resp.text

    async def test_a_refund_that_is_not_a_number_is_a_422_not_a_500(self, async_client, order):
        resp = await _return(async_client, {
            "order_no": order["transport_no"], "reason": "damaged", "refund_amount": "五十九元",
        })
        assert resp.status_code == 422, resp.text
        assert any("refund_amount" in e["field"] for e in resp.json()["errors"]), resp.text

    async def test_a_negative_refund_is_refused(self, async_client, order):
        resp = await _return(async_client, {
            "order_no": order["transport_no"], "reason": "damaged", "refund_amount": -59,
        })
        assert resp.status_code == 422, resp.text

    async def test_the_carrier_is_the_carrier_vocabulary(self, async_client, order):
        resp = await _return(async_client, {
            "order_no": order["transport_no"], "reason": "damaged", "carrier_code": "顺丰",
        })
        assert resp.status_code == 422, resp.text
        assert "sf_express" in resp.text, "the refusal did not name the carrier codes"

    async def test_the_envelope_shape_is_accepted(self, async_client, order):
        resp = await _return(async_client, {"data": {
            "transport_order_id": order["id"], "reason": "quality_issue", "refund_amount": "12.50",
        }})
        assert resp.status_code == 201, resp.text
        assert resp.json()["refund_amount"] == "12.50"

    async def test_a_key_the_endpoint_does_not_read_is_refused_by_name(self, async_client, order):
        resp = await _return(async_client, {
            "order_no": order["transport_no"], "reason": "damaged", "priority": "HIGH",
        })
        assert resp.status_code == 422, resp.text
        assert any("priority" in e["field"] for e in resp.json()["errors"]), resp.text

    async def test_the_status_the_console_sends_is_the_status(self, async_client, order):
        """``PATCH /return-orders/{id}/status`` read ``data["target"]``; the
        console sends ``{"status": ...}``, the shape every other status endpoint
        in this API takes — and the move was refused as a transition to ``'None'``."""
        created = await _return(async_client, {"order_no": order["transport_no"], "reason": "damaged"})
        assert created.status_code == 201, created.text

        resp = await async_client.patch(
            f"/api/v1/return-orders/{created.json()['id']}/status", json={"status": "pickup_scheduled"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "pickup_scheduled"

    async def test_a_status_the_lifecycle_does_not_have_is_refused_by_name(self, async_client, order):
        created = await _return(async_client, {"order_no": order["transport_no"], "reason": "damaged"})
        assert created.status_code == 201, created.text
        resp = await async_client.patch(
            f"/api/v1/return-orders/{created.json()['id']}/status", json={"status": "refunded"},
        )
        assert resp.status_code == 422, resp.text
        assert "pickup_scheduled" in resp.json()["error"]["message"], (
            "the refusal did not name the moves this return has left"
        )


# ── Transport exceptions ─────────────────────────────────────────────────────


class TestExceptionBody:
    async def test_the_shape_the_console_sends_reports_the_exception(self, async_client, order):
        """``ExceptionList.vue`` posts ``{transport_order_no, exception_type,
        description}``; the handler read ``data["type"]`` — a KeyError inside a
        handler for the ordinary case of pressing 报告异常."""
        resp = await _exception(async_client, {
            "transport_order_no": order["transport_no"], "exception_type": "delayed",
            "description": "暴雨滞留",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["type"] == "delayed", "the exception type the form chose was not recorded"
        assert body["transport_order_id"] == order["id"], "the shipment the operator named was dropped"
        assert body["description"] == "暴雨滞留"
        assert body["status"] == "open"

    async def test_an_exception_that_belongs_to_no_shipment_is_allowed(self, async_client):
        resp = await _exception(async_client, {"exception_type": "weather", "description": "全省停发"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["transport_order_id"] is None

    async def test_the_type_is_the_exception_vocabulary(self, async_client):
        resp = await _exception(async_client, {"exception_type": "traffic_jam"})
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["error"]["code"] == "VALIDATION_ERROR", resp.text
        assert "damaged_in_transit" in resp.text and "customer_unavailable" in resp.text, (
            "the refusal did not name the exception types the domain knows"
        )

    async def test_the_type_is_required(self, async_client):
        resp = await _exception(async_client, {"description": "没有类型"})
        assert resp.status_code == 422, resp.text
        assert any("type" in e["field"] for e in resp.json()["errors"]), resp.text

    async def test_a_number_that_names_no_shipment_is_answered_by_the_field(self, async_client):
        resp = await _exception(async_client, {"transport_order_no": "TPL-19700101-0001", "type": "lost"})
        assert resp.status_code == 404, resp.text
        assert "transport_order_id" in resp.json()["error"]["message"], resp.text

    async def test_the_severity_vocabulary_is_named(self, async_client, order):
        resp = await _exception(async_client, {
            "transport_order_id": order["id"], "type": "delayed", "severity": "urgent",
        })
        assert resp.status_code == 422, resp.text
        assert "critical" in resp.text, "the refusal did not name the severity levels"

    async def test_the_shipment_scoped_route_takes_the_same_body(self, async_client, order):
        """``POST /transport-orders/{id}/exceptions`` — the order comes from the
        path, and the console's key is the same ``exception_type``."""
        resp = await async_client.post(
            f"/api/v1/transport-orders/{order['id']}/exceptions",
            json={"exception_type": "address_issue", "description": "地址不详"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["transport_order_id"] == order["id"]
        assert resp.json()["type"] == "address_issue"

    async def test_resolving_records_how_it_was_handled(self, async_client, order):
        created = await _exception(async_client, {
            "transport_order_id": order["id"], "type": "delayed", "description": "航班延误",
        })
        assert created.status_code == 201, created.text

        resp = await async_client.patch(f"/api/v1/exceptions/{created.json()['id']}", json={
            "resolution_notes": "改走铁路, 已送达",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "resolved"
        assert resp.json()["resolution_notes"] == "改走铁路, 已送达"

    async def test_a_key_the_endpoint_does_not_read_is_refused_by_name(self, async_client):
        resp = await _exception(async_client, {"exception_type": "lost", "priority": "HIGH"})
        assert resp.status_code == 422, resp.text
        assert any("priority" in e["field"] for e in resp.json()["errors"]), resp.text

    async def test_one_exception_carries_the_number_of_its_shipment(self, async_client, order):
        """``ExceptionList.vue`` 详情 reads 运单号.  There was no route that
        answered one exception, so the console queried the list with a parameter
        the route ignores — and the record it showed had no shipment in it."""
        created = await _exception(async_client, {
            "transport_order_id": order["id"], "type": "lost", "description": "包裹丢失",
        })
        assert created.status_code == 201, created.text

        resp = await async_client.get(f"/api/v1/exceptions/{created.json()['id']}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["transport_order_no"] == order["transport_no"], (
            "the exception record names no shipment a person can read"
        )

    async def test_an_exception_that_is_not_there_is_a_404(self, async_client):
        resp = await async_client.get(f"/api/v1/exceptions/{uuid_mod.uuid4()}")
        assert resp.status_code == 404, resp.text
