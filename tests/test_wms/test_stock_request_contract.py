"""Request-body contract for the Stock In / Out / Adjust Stock endpoints.

``src/routes/stock.py`` declared every write endpoint as ``req: dict`` and then
read it with ``req.get("data", {})``.  Four things followed from that:

* A flat body — the shape ``frontend/src/services/inventory.ts`` posts — reached
  ``data["warehouse_id"]`` on an empty dict: a KeyError, and a 500 for a request
  that is missing a field.
* ``update_stock_in`` / ``update_stock_out`` passed the client's dict straight to
  ``update(...).values(data)``.  ``{"data": {"is_deleted": true}}``,
  ``{"data": {"total_qty": -1}}`` and ``{"data": {"warehouse_id": <other>}}`` were
  all legal updates, written without touching the loaded ORM object, so the
  response the client got back was the pre-update row.
* ``_extract_qty`` accepted four key spellings and rejected nothing else: a line
  typed ``{"sku": "A", "qtyy": 3}`` answered 422 "Each line must have 'qty'…"
  (naming keys the client never sent) and ``{"qty": "abc"`` reached
  ``Decimal("abc")`` — 500.
* ``adjust_stock`` read ``data.get("operator_id")`` with no validation, and fell
  back to ``str(UUID(current_user["sub"]))``.  ``sub`` is a username, so the
  fallback always raised and was swallowed: the operator column of an adjustment
  audit row was NULL on every request, and a caller who did send an id got one
  inserted into a UUID foreign key unchecked.

Every case below is asserted against the HTTP response, because that is the
surface the client is writing against.
"""

import uuid as uuid_mod

import pytest

BAD_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
async def auth_headers(async_client):
    uname = f"stkctrt_{uuid_mod.uuid4().hex[:8]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(autouse=True)
async def _authenticated(async_client, auth_headers):
    """The stock API is authenticated end to end; opt out per-test when needed."""
    async_client.headers.update(auth_headers)
    yield


@pytest.fixture
async def warehouse(async_client, auth_headers):
    r = await async_client.post("/api/v1/warehouses", json={
        "code": f"WH-CTRT-{uuid_mod.uuid4().hex[:8]}",
        "name": "Contract Stock Warehouse",
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _body(wh_id, **over):
    data = {
        "warehouse_id": wh_id,
        "type": "PURCHASE",
        "ref_no": "PO-CTRT-1",
        "lines": [{"sku": "SKU-CTRT-A", "qty": 4, "batch_no": "B1"}],
    }
    data.update(over)
    return data


def _out_body(wh_id, **over):
    data = {
        "warehouse_id": wh_id,
        "type": "SALE",
        "ref_no": "SO-CTRT-1",
        "lines": [{"sku": "SKU-CTRT-A", "qty": 2}],
    }
    data.update(over)
    return data


# ── The envelope is a convention, not a crash switch ─────────────────────────


class TestRequestShape:
    async def test_enveloped_body_still_works(self, async_client, warehouse):
        """``{"data": {...}}`` is what existing clients send; it must keep working."""
        resp = await async_client.post("/api/v1/stock-in", json={"data": _body(warehouse["id"])})
        assert resp.status_code == 201, resp.text
        assert resp.json()["total_qty"] == "4.0000"

    async def test_flat_body_is_accepted(self, async_client, warehouse):
        """A flat body used to reach ``data["warehouse_id"]`` on ``{}`` — a 500.

        ``frontend/src/services/inventory.ts`` posts exactly this shape, so the
        stock-in form in the shipped UI was hitting an internal error, not a
        validation error.
        """
        resp = await async_client.post("/api/v1/stock-in", json=_body(warehouse["id"]))
        assert resp.status_code == 201, resp.text
        assert resp.json()["warehouse_id"] == warehouse["id"]

    async def test_items_is_accepted_as_a_spelling_of_lines(self, async_client, warehouse):
        """The frontend service names the line array ``items``; the route read ``lines``."""
        payload = {"warehouse_id": warehouse["id"], "type": "PURCHASE",
                   "items": [{"sku": "SKU-CTRT-A", "quantity": 3}]}
        resp = await async_client.post("/api/v1/stock-in", json=payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["total_qty"] == "3.0000"

    async def test_a_non_object_data_is_refused(self, async_client):
        resp = await async_client.post("/api/v1/stock-in", json={"data": "PURCHASE"})
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR", resp.text

    async def test_a_missing_field_names_the_field(self, async_client, warehouse):
        """The old behaviour was KeyError → 500 for the most common typo there is."""
        body = _body(warehouse["id"])
        body.pop("warehouse_id")
        resp = await async_client.post("/api/v1/stock-in", json={"data": body})
        assert resp.status_code == 422, resp.text
        assert "warehouse_id" in resp.text, resp.text

    async def test_an_undeclared_key_is_refused_by_name(self, async_client, warehouse):
        """``po_id`` is in the frontend payload and in no column of stock_in."""
        body = _body(warehouse["id"], po_id=str(uuid_mod.uuid4()))
        resp = await async_client.post("/api/v1/stock-in", json=body)
        assert resp.status_code == 422, resp.text
        assert "po_id" in resp.text, resp.text

    async def test_a_malformed_uuid_is_a_validation_error(self, async_client):
        resp = await async_client.post("/api/v1/stock-in", json={"data": _body("not-a-uuid")})
        assert resp.status_code == 422, resp.text
        assert "warehouse_id" in resp.text, resp.text

    async def test_the_422_uses_the_documented_error_envelope(self, async_client, warehouse):
        """Pydantic's default body-validation answer is ``{"detail": [...]}``; this
        API documents ``{"success": false, "error": {"code", "message"}}``."""
        resp = await async_client.post("/api/v1/stock-in", json={"data": _body("not-a-uuid")})
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["success"] is False, resp.text
        assert body["error"]["code"] == "VALIDATION_ERROR", resp.text
        assert "warehouse_id" in body["error"]["message"], resp.text
        assert any("warehouse_id" in e["field"] for e in body["errors"]), resp.text


# ── Lines ────────────────────────────────────────────────────────────────────


class TestLines:
    @pytest.mark.parametrize("key", ["qty", "quantity", "qty_received", "qty_shipped"])
    async def test_the_documented_qty_spellings_work(self, async_client, warehouse, key):
        lines = [{"sku": "SKU-CTRT-A", key: 7}]
        resp = await async_client.post("/api/v1/stock-in", json={"data": _body(warehouse["id"], lines=lines)})
        assert resp.status_code == 201, resp.text
        assert resp.json()["total_qty"] == "7.0000"

    async def test_a_receipt_with_no_lines_is_refused(self, async_client, warehouse):
        """An empty line array used to produce a receipt with total_qty 0."""
        resp = await async_client.post("/api/v1/stock-in", json={"data": _body(warehouse["id"], lines=[])})
        assert resp.status_code == 422, resp.text
        assert "lines" in resp.text, resp.text

    async def test_a_line_without_a_quantity_says_which_keys_it_tried(self, async_client, warehouse):
        resp = await async_client.post(
            "/api/v1/stock-in", json={"data": _body(warehouse["id"], lines=[{"sku": "A"}])},
        )
        assert resp.status_code == 422, resp.text
        assert "qty" in resp.text, resp.text

    async def test_a_typoed_key_is_refused_by_name(self, async_client, warehouse):
        """``{"qtyy": 3}`` answered "Each line must have 'qty', 'quantity', ...":
        a list of keys the client never sent, for a body that had a quantity in it."""
        resp = await async_client.post(
            "/api/v1/stock-in",
            json={"data": _body(warehouse["id"], lines=[{"sku": "A", "qtyy": 3}])},
        )
        assert resp.status_code == 422, resp.text
        assert "qtyy" in resp.text, resp.text

    async def test_a_non_numeric_quantity_is_not_a_500(self, async_client, warehouse):
        """``Decimal(str("abc"))`` is an InvalidOperation: the route has no handler for it."""
        resp = await async_client.post(
            "/api/v1/stock-in",
            json={"data": _body(warehouse["id"], lines=[{"sku": "A", "qty": "abc"}])},
        )
        assert resp.status_code == 422, resp.text

    async def test_a_negative_receipt_line_is_refused(self, async_client, warehouse):
        resp = await async_client.post(
            "/api/v1/stock-in",
            json={"data": _body(warehouse["id"], lines=[{"sku": "A", "qty": -2}])},
        )
        assert resp.status_code == 422, resp.text

    async def test_zero_is_a_legitimate_received_quantity(self, async_client, warehouse):
        """A line short-shipped by the carrier is recorded as 0, not refused."""
        resp = await async_client.post(
            "/api/v1/stock-in",
            json={"data": _body(warehouse["id"], lines=[{"sku": "A", "qty": 0}])},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["total_qty"] == "0.0000"

    async def test_an_unparseable_expiry_date_is_refused(self, async_client, warehouse):
        """The expiry_date column is a DateTime; the route passed the raw string."""
        resp = await async_client.post(
            "/api/v1/stock-in",
            json={"data": _body(warehouse["id"], lines=[{"sku": "A", "qty": 1, "expiry_date": "next Tuesday"}])},
        )
        assert resp.status_code == 422, resp.text
        assert "expiry_date" in resp.text, resp.text

    async def test_an_iso_expiry_date_is_accepted(self, async_client, warehouse):
        resp = await async_client.post(
            "/api/v1/stock-in",
            json={"data": _body(warehouse["id"], lines=[{"sku": "A", "qty": 1, "expiry_date": "2027-01-31"}])},
        )
        assert resp.status_code == 201, resp.text
        detail = await async_client.get(f"/api/v1/stock-in/{resp.json()['id']}")
        assert detail.json()["lines"][0]["expiry_date"].startswith("2027-01-31"), detail.text

    async def test_a_warehouse_that_does_not_exist_is_still_a_404(self, async_client):
        resp = await async_client.post("/api/v1/stock-in", json={"data": _body(BAD_UUID)})
        assert resp.status_code == 404, resp.text

    async def test_a_vendor_that_does_not_exist_is_still_a_404(self, async_client, warehouse):
        resp = await async_client.post(
            "/api/v1/stock-in", json={"data": _body(warehouse["id"], supplier_id=BAD_UUID)},
        )
        assert resp.status_code == 404, resp.text

    async def test_the_inbound_type_vocabulary_is_named(self, async_client, warehouse):
        """The UI offers 手动入库 (MANUAL); the model defines PURCHASE / RETURN /
        TRANSFER_IN / ADJUSTMENT.  The made-up value used to be stored verbatim."""
        resp = await async_client.post(
            "/api/v1/stock-in", json={"data": _body(warehouse["id"], type="MANUAL")},
        )
        assert resp.status_code == 422, resp.text
        assert "TRANSFER_IN" in resp.text, resp.text

    async def test_the_outbound_type_vocabulary_is_named(self, async_client, warehouse):
        resp = await async_client.post(
            "/api/v1/stock-out", json={"data": _out_body(warehouse["id"], type="PURCHASE")},
        )
        assert resp.status_code == 422, resp.text
        assert "TRANSFER_OUT" in resp.text, resp.text


# ── Updates: no mass assignment ──────────────────────────────────────────────


class TestUpdateIsAnAllowlist:
    @pytest.fixture
    async def stock_in(self, async_client, warehouse):
        resp = await async_client.post("/api/v1/stock-in", json={"data": _body(warehouse["id"])})
        assert resp.status_code == 201, resp.text
        return resp.json()

    async def test_a_declared_field_updates(self, async_client, stock_in):
        resp = await async_client.put(
            f"/api/v1/stock-in/{stock_in['id']}",
            json={"data": {"status": "CONFIRMED", "ref_no": "PO-CTRT-2"}},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "CONFIRMED"
        assert resp.json()["ref_no"] == "PO-CTRT-2"

    async def test_the_response_reflects_what_was_written(self, async_client, stock_in):
        """``.values(data)`` wrote the row without the loaded object, so the JSON
        the client received was the row as it was before the update."""
        resp = await async_client.put(
            f"/api/v1/stock-in/{stock_in['id']}", json={"data": {"status": "CONFIRMED"}},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "CONFIRMED", resp.text

    async def test_total_qty_is_not_a_client_supplied_field(self, async_client, stock_in):
        """total_qty is computed from the lines at creation; writing it from the
        request body invents stock."""
        resp = await async_client.put(
            f"/api/v1/stock-in/{stock_in['id']}", json={"data": {"total_qty": 9999}},
        )
        assert resp.status_code == 422, resp.text
        assert "total_qty" in resp.text, resp.text
        detail = await async_client.get(f"/api/v1/stock-in/{stock_in['id']}")
        assert detail.json()["total_qty"] == "4.0000", detail.text

    async def test_is_deleted_is_not_a_client_supplied_field(self, async_client, stock_in):
        resp = await async_client.put(
            f"/api/v1/stock-in/{stock_in['id']}", json={"data": {"is_deleted": True}},
        )
        assert resp.status_code == 422, resp.text
        detail = await async_client.get(f"/api/v1/stock-in/{stock_in['id']}")
        assert detail.status_code == 200, "the rejected body deleted the receipt"

    async def test_the_document_is_not_movable_to_another_warehouse(self, async_client, warehouse, stock_in):
        other = await async_client.post("/api/v1/warehouses", json={
            "code": f"WH-CTRT2-{uuid_mod.uuid4().hex[:8]}", "name": "Other", "type": "center",
        })
        resp = await async_client.put(
            f"/api/v1/stock-in/{stock_in['id']}",
            json={"data": {"warehouse_id": other.json()["id"]}},
        )
        assert resp.status_code == 422, resp.text
        detail = await async_client.get(f"/api/v1/stock-in/{stock_in['id']}")
        assert detail.json()["warehouse_id"] == warehouse["id"], detail.text

    async def test_a_status_the_document_never_has_is_refused(self, async_client, stock_in):
        """SHIPPED belongs to a stock-out; here it used to reach the transition
        check and answer 400 about a jump the client never made."""
        resp = await async_client.put(
            f"/api/v1/stock-in/{stock_in['id']}", json={"data": {"status": "SHIPPED"}},
        )
        assert resp.status_code == 422, resp.text

    async def test_an_illegal_jump_keeps_its_400(self, async_client, stock_in):
        """DRAFT -> RECEIVED skips confirmation: a real rule, a 400, not a 422."""
        resp = await async_client.put(
            f"/api/v1/stock-in/{stock_in['id']}", json={"data": {"status": "RECEIVED"}},
        )
        assert resp.status_code == 400, resp.text

    async def test_the_same_allowlist_applies_to_stock_out(self, async_client, warehouse):
        created = await async_client.post("/api/v1/stock-out", json={"data": _out_body(warehouse["id"])})
        assert created.status_code == 201, created.text
        oid = created.json()["id"]
        resp = await async_client.put(
            f"/api/v1/stock-out/{oid}", json={"data": {"total_qty": 1}},
        )
        assert resp.status_code == 422, resp.text
        detail = await async_client.get(f"/api/v1/stock-out/{oid}")
        assert detail.json()["total_qty"] == "2.0000", detail.text


# ── Adjust Stock ─────────────────────────────────────────────────────────────


class TestAdjustStockAudit:
    @pytest.fixture
    async def user_id(self, async_client, auth_headers):
        r = await async_client.get("/api/v1/auth/me", headers=auth_headers)
        assert r.status_code == 200, r.text
        return r.json()["id"]

    async def _logs(self, async_client, warehouse):
        r = await async_client.get(f"/api/v1/inventory-log?warehouse_id={warehouse['id']}")
        assert r.status_code == 200, r.text
        return r.json()

    async def test_the_operator_is_recorded_from_the_credential(self, async_client, warehouse, auth_headers, user_id):
        """"sub" is a username, so str(UUID(sub)) raised every single time and the
        handler swallowed it: the operator column was NULL on every adjustment."""
        resp = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": str(uuid_mod.uuid4()), "warehouse_id": warehouse["id"], "quantity": 5,
        }})
        assert resp.status_code == 200, resp.text
        logs = await self._logs(async_client, warehouse)
        assert logs, "the adjustment wrote no audit row"
        assert logs[0]["operator_id"] == user_id, resp.text

    async def test_a_requested_operator_is_recorded(self, async_client, warehouse, auth_headers, user_id):
        resp = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": str(uuid_mod.uuid4()), "warehouse_id": warehouse["id"],
            "quantity": 3, "operator_id": user_id,
        }})
        assert resp.status_code == 200, resp.text
        logs = await self._logs(async_client, warehouse)
        assert logs[0]["operator_id"] == user_id, resp.text

    async def test_an_operator_id_that_is_not_an_id_is_refused(self, async_client, warehouse, auth_headers):
        """The column is a foreign key to users.id; the route inserted whatever arrived."""
        resp = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": str(uuid_mod.uuid4()), "warehouse_id": warehouse["id"],
            "quantity": 3, "operator_id": "admin",
        }})
        assert resp.status_code == 422, resp.text
        assert "operator_id" in resp.text, resp.text

    async def test_an_operator_that_is_not_a_user_is_refused(self, async_client, warehouse, auth_headers):
        resp = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": str(uuid_mod.uuid4()), "warehouse_id": warehouse["id"],
            "quantity": 3, "operator_id": BAD_UUID,
        }})
        assert resp.status_code == 422, resp.text
        assert "operator_id" in resp.text, resp.text

    async def test_the_key_the_ui_sent_is_named_not_dropped(self, async_client, warehouse, auth_headers):
        """``{"operator": "test"}`` is what tests/test_stock.py used to send: the
        route read ``operator_id``, ignored the key, and filed the audit row with no
        operator.  A dropped audit field has to be visible to the caller."""
        resp = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": str(uuid_mod.uuid4()), "warehouse_id": warehouse["id"],
            "quantity": 3, "operator": "test",
        }})
        assert resp.status_code == 422, resp.text
        assert "operator" in resp.text, resp.text

    async def test_the_reason_vocabulary_is_named(self, async_client, warehouse, auth_headers):
        resp = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": str(uuid_mod.uuid4()), "warehouse_id": warehouse["id"],
            "quantity": 3, "reason": "MYSTERY",
        }})
        assert resp.status_code == 422, resp.text
        assert "COUNT_ERROR" in resp.text, resp.text

    async def test_a_reason_longer_than_the_column_is_refused(self, async_client, warehouse, auth_headers):
        """reason is String(32); a longer one used to fail at COMMIT."""
        resp = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": str(uuid_mod.uuid4()), "warehouse_id": warehouse["id"],
            "quantity": 3, "reason": "R" * 40,
        }})
        assert resp.status_code == 422, resp.text

    async def test_a_remark_longer_than_the_column_is_refused(self, async_client, warehouse, auth_headers):
        resp = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": str(uuid_mod.uuid4()), "warehouse_id": warehouse["id"],
            "quantity": 3, "remark": "R" * 600,
        }})
        assert resp.status_code == 422, resp.text

    async def test_the_stock_movement_rules_are_untouched(self, async_client, warehouse, auth_headers):
        """Zero is refused, and an OUT that exceeds the available stock is refused."""
        bad = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": str(uuid_mod.uuid4()), "warehouse_id": warehouse["id"], "quantity": 0,
        }})
        assert bad.status_code == 400, bad.text
        seed = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": str(uuid_mod.uuid4()), "warehouse_id": warehouse["id"], "quantity": 4,
        }})
        assert seed.status_code == 200, seed.text
        over = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": seed.json()["sku_id"], "warehouse_id": warehouse["id"], "quantity": -999,
        }})
        assert over.status_code == 400, over.text
