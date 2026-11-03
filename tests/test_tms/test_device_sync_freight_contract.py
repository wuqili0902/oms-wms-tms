"""The bodies behind the device, sync and rate-card screens.

Each of these endpoints declared ``data: dict`` and read keys their own console
never sends.  A ``KeyError`` inside a handler is reported as a server failure, so
the ordinary case — pressing 提交 on a form that was fully filled in — answered 500:

* ``DeviceList.vue`` posts ``{device_code, name, device_type}``, the service read
  ``data["code"]``, and the screen's 注册设备 answered 500 for every device anyone
  registered.  Its edit form sent the code and the type, and both were dropped, so
  saving a rename saved nothing;
* a handheld reporting ``{sync_type: "upload_data", data_count: 12}`` reached
  ``SyncLogType(...)`` inside the handler: the sync that failed on the floor
  failed on the way in as well, as a 500 that named nothing, and the row count it
  reported was never stored;
* ``FreightTierList.vue`` posts ``{carrier_code, weight_from, weight_to,
  price_per_kg}``, the service read ``data["rule_type"]`` and
  ``data["price_per_unit"]`` — 提交 answered 500 and no carrier has ever gained a
  bracket from that screen — and 运费试算 sent ``total_weight_kg`` to a calculation
  that read ``data.get("weight", 1)``, so every quote it showed priced the
  shipment as 1 kg.

The bodies are typed now (``src/tms/schemas.py``): the keys the screens use are
accepted as spellings of the fields that store them, a value outside a vocabulary
is a 422 that names the vocabulary, a bracket whose ceiling is below its floor is
refused, and the measurements the operator typed reach the price.
"""

import uuid as uuid_mod

import pytest

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def auth_headers(async_client):
    uname = f"dvcctr_{uuid_mod.uuid4().hex[:8]}"
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
async def warehouse(async_client) -> dict:
    r = await async_client.post("/api/v1/warehouses", json={
        "code": f"WH-DVC-{uuid_mod.uuid4().hex[:8]}", "name": "Terminal WH", "type": "center",
    })
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def device(async_client) -> dict:
    """A handheld registered the way the console registers one."""
    r = await async_client.post("/api/v1/devices", json={
        "device_code": f"PDA-{uuid_mod.uuid4().hex[:8]}", "name": "拣射手持", "device_type": "pda",
    })
    assert r.status_code == 201, r.text
    return r.json()


async def _register(async_client, body: dict):
    return await async_client.post("/api/v1/devices", json=body)


async def _sync(async_client, dev_id: str, body: dict):
    return await async_client.post(f"/api/v1/devices/{dev_id}/sync", json=body)


async def _tier(async_client, body: dict):
    return await async_client.post("/api/v1/freight-tiers", json=body)


async def _quote(async_client, body: dict):
    return await async_client.post("/api/v1/freight/calculate", json=body)


def _fields(resp) -> list[str]:
    """The keys a validation refusal named."""
    return [e["field"] for e in resp.json().get("errors", [])]


# ── Registering a device ─────────────────────────────────────────────────────


class TestDeviceRegisterBody:
    async def test_the_documented_shape_is_accepted(self, async_client):
        """``docs/functional-test-plan.md`` 6.9.1: the body the plan documents is
        the body the endpoint takes, under the plan's own key names."""
        code = f"PDA-{uuid_mod.uuid4().hex[:8]}"
        resp = await _register(async_client, {
            "code": code, "name": "手持终端1", "device_type": "pda", "platform": "android",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["code"] == code
        assert body["platform"] == "android"
        assert body["device_type"] == "pda"

    async def test_the_code_the_screen_types_is_the_device_code(self, async_client):
        """``DeviceList.vue`` posts ``{device_code, name, device_type}``; the
        handler read ``data["code"]``, so the 500 came before the device — printed
        on the shell, typed into the form — was ever filed."""
        code = f"PDA-{uuid_mod.uuid4().hex[:8]}"
        resp = await _register(async_client, {"device_code": code, "name": "拣射手持", "device_type": "pda"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["code"] == code, "the code the form typed did not reach the record"
        assert body["name"] == "拣射手持"
        assert body["device_type"] == "pda"
        assert body["status"] == "offline", "a device that has never phoned home is not online"

    async def test_a_type_the_domain_does_not_record_is_refused_by_name(self, async_client):
        """The screen offered 终端 as a type; ``TerminalDeviceType`` has no such
        member, so the choice the form made was the choice that broke the form."""
        resp = await _register(async_client, {
            "device_code": f"PDA-{uuid_mod.uuid4().hex[:8]}", "device_type": "terminal",
        })
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR", resp.text
        assert "scanner" in resp.text and "printer" in resp.text, (
            "the refusal did not name the device types the domain records"
        )

    async def test_a_device_has_to_be_named_by_a_code(self, async_client):
        resp = await _register(async_client, {"name": "无编号手持"})
        assert resp.status_code == 422, resp.text
        assert any("code" in f for f in _fields(resp)), resp.text

    async def test_a_code_that_is_already_on_the_network_is_refused(self, async_client, device):
        """``terminal_devices.code`` is unique; two handhelds with one code cannot
        both report sync, and the collision belongs at the door, not at commit."""
        resp = await _register(async_client, {"device_code": device["code"], "name": "第二台"})
        assert resp.status_code == 422, resp.text
        assert device["code"] in resp.json()["error"]["message"], resp.text

    async def test_a_handheld_is_filed_to_the_warehouse_named_by_its_code(self, async_client, warehouse):
        """A handheld's setup screen knows the code printed on the bay door.
        ``_to_uuid`` answered None for a code, and the device was filed with no
        warehouse — silently."""
        resp = await _register(async_client, {
            "device_code": f"PDA-{uuid_mod.uuid4().hex[:8]}", "warehouse_id": warehouse["code"],
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["warehouse_id"] == warehouse["id"], "the warehouse the form named is not on the record"

    async def test_a_warehouse_that_does_not_exist_names_the_field(self, async_client):
        resp = await _register(async_client, {
            "device_code": f"PDA-{uuid_mod.uuid4().hex[:8]}", "warehouse_id": "WH-NOPE",
        })
        assert resp.status_code == 404, resp.text
        assert "warehouse_id" in resp.json()["error"]["message"], (
            "the refusal did not name the field that named the warehouse"
        )

    async def test_the_envelope_shape_is_accepted(self, async_client):
        resp = await _register(async_client, {"data": {"device_code": f"PDA-{uuid_mod.uuid4().hex[:8]}"}})
        assert resp.status_code == 201, resp.text

    async def test_a_key_the_endpoint_does_not_read_is_refused_by_name(self, async_client):
        resp = await _register(async_client, {
            "device_code": f"PDA-{uuid_mod.uuid4().hex[:8]}", "serial_number": "SN-00123",
        })
        assert resp.status_code == 422, resp.text
        assert any("serial_number" in f for f in _fields(resp)), (
            "a key this endpoint ignores has to be named, not dropped"
        )


# ── Editing a device ─────────────────────────────────────────────────────────


class TestDeviceUpdateBody:
    async def test_the_edit_form_saves_the_code_and_the_type(self, async_client, device):
        """The edit form sends ``device_code``, ``name`` and ``device_type``.  The
        body declared neither of the first and last, so an edit that renamed a
        scanner, or corrected a device registered as the wrong type, was refused
        as an unknown key — and the code it sent was dropped."""
        new_code = f"PDA-{uuid_mod.uuid4().hex[:8]}"
        resp = await async_client.patch(f"/api/v1/devices/{device['id']}", json={
            "device_code": new_code, "name": "扫码枪", "device_type": "scanner",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == new_code, "the code the edit typed was dropped"
        assert body["device_type"] == "scanner", "the type the edit corrected was dropped"
        assert body["name"] == "扫码枪"

    async def test_the_status_vocabulary_is_named(self, async_client, device):
        resp = await async_client.patch(f"/api/v1/devices/{device['id']}", json={"status": "inactive"})
        assert resp.status_code == 422, resp.text
        assert "disabled" in resp.text and "online" in resp.text, (
            "the refusal did not name the statuses a device reports"
        )

    async def test_a_device_can_be_taken_out_of_service(self, async_client, device):
        resp = await async_client.patch(f"/api/v1/devices/{device['id']}", json={"status": "disabled"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "disabled"

    async def test_a_rename_onto_another_device_is_refused(self, async_client, device):
        other = await _register(async_client, {"device_code": f"PDA-{uuid_mod.uuid4().hex[:8]}"})
        assert other.status_code == 201, other.text

        resp = await async_client.patch(
            f"/api/v1/devices/{other.json()['id']}", json={"device_code": device["code"]},
        )
        assert resp.status_code == 422, resp.text
        assert device["code"] in resp.json()["error"]["message"], (
            "a rename that steals another device's code has to be refused by name"
        )

    async def test_an_edit_of_a_device_that_is_not_there_is_a_404(self, async_client):
        resp = await async_client.patch(f"/api/v1/devices/{uuid_mod.uuid4()}", json={"name": "无"})
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND", resp.text


# ── The sync run a handheld reports ─────────────────────────────────────────


class TestSyncLogBody:
    async def test_the_count_the_handheld_reports_is_counted(self, async_client, device):
        """The device reports its row count as ``data_count``; the column is
        ``records_count``, and the number was dropped on the floor."""
        resp = await _sync(async_client, device["id"], {
            "sync_type": "upload", "status": "completed", "data_count": 42,
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["records_count"] == 42, "the count the device reported is not on the log"
        assert body["sync_type"] == "upload"
        assert body["completed_at"] is not None, "a completed run has to say when it finished"
        assert body["device_id"] == device["id"]

    async def test_a_sync_type_the_domain_does_not_have_is_refused_by_name(self, async_client, device):
        resp = await _sync(async_client, device["id"], {"sync_type": "upload_data"})
        assert resp.status_code == 422, resp.text
        assert "upload" in resp.text and "download" in resp.text, (
            "the refusal did not name the sync types the device domain has"
        )

    async def test_a_failed_run_keeps_its_reason(self, async_client, device):
        resp = await _sync(async_client, device["id"], {
            "sync_type": "download", "status": "failed",
            "data_count": 7, "error_message": "库存差异，中断同步",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "failed"
        assert body["error_message"] == "库存差异，中断同步"
        assert body["completed_at"] is not None, "a run that stopped is a run that finished, badly"

    async def test_a_pending_run_has_not_finished(self, async_client, device):
        resp = await _sync(async_client, device["id"], {"sync_type": "download", "status": "pending"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["completed_at"] is None, "a run that is pending has not completed"

    async def test_a_count_that_is_not_a_number_is_refused_by_the_key_sent(self, async_client, device):
        resp = await _sync(async_client, device["id"], {"data_count": "很多"})
        assert resp.status_code == 422, resp.text
        assert any("data_count" in f for f in _fields(resp)), (
            "Pydantic names the key the caller sent — that is the point"
        )

    async def test_the_device_that_synced_is_reachable_afterwards(self, async_client, device):
        resp = await _sync(async_client, device["id"], {"sync_type": "upload", "status": "completed"})
        assert resp.status_code == 201, resp.text

        after = await async_client.get(f"/api/v1/devices/{device['id']}")
        assert after.status_code == 200, after.text
        assert after.json()["status"] == "online", "a device that just synced is not reachable"
        assert after.json()["last_sync_at"] is not None

    async def test_a_sync_for_a_device_that_is_not_there_is_a_404(self, async_client):
        resp = await _sync(async_client, str(uuid_mod.uuid4()), {"sync_type": "upload"})
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND", resp.text


# ── The rate card ────────────────────────────────────────────────────────────


class TestFreightTierBody:
    async def test_the_form_the_screen_posts_adds_a_bracket(self, async_client):
        """``{carrier_code, weight_from, weight_to, price_per_kg}`` is what
        新建运费等级 sends; the handler read ``rule_type`` and ``price_per_unit``,
        so this request was a 500 and no carrier ever gained a tier here."""
        resp = await _tier(async_client, {
            "carrier_code": "zto", "weight_from": 0, "weight_to": 50, "price_per_kg": 5,
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert float(body["min_value"]) == 0.0
        assert float(body["max_value"]) == 50.0
        assert float(body["price_per_unit"]) == 5.0, "the price per kg the form typed is the tier's unit price"
        assert body["rule_type"] == "weight_tiered", "the bracket the form's fields measure is a weight bracket"

    async def test_a_bracket_whose_ceiling_is_below_its_floor_is_refused(self, async_client):
        """Such a bracket covers no shipment, and a carrier holding it answers
        "no matching freight tier" for the shipments that should have matched it."""
        resp = await _tier(async_client, {
            "carrier_code": "zto", "weight_from": 100, "weight_to": 10, "price_per_kg": 5,
        })
        assert resp.status_code == 422, resp.text
        assert "max_value" in resp.text and "min_value" in resp.text, resp.text

    async def test_the_rule_is_a_rule_the_pricer_knows(self, async_client):
        resp = await _tier(async_client, {
            "carrier_code": "zto", "rule_type": "volume_tiered", "price_per_kg": 5,
        })
        assert resp.status_code == 422, resp.text
        assert "volume_based" in resp.text and "distance_tiered" in resp.text, (
            "the refusal did not name the rules the pricer implements"
        )

    async def test_the_price_is_required(self, async_client):
        """A bracket without a price prices nothing; before the body was typed the
        request reached the model and failed at commit as a 500."""
        resp = await _tier(async_client, {"carrier_code": "zto", "weight_from": 0, "weight_to": 50})
        assert resp.status_code == 422, resp.text
        assert any("price" in f for f in _fields(resp)), resp.text

    async def test_a_carrier_the_domain_does_not_have_is_named(self, async_client):
        resp = await _tier(async_client, {"carrier_code": "顺丰", "price_per_kg": 5})
        assert resp.status_code == 422, resp.text
        assert "sf_express" in resp.text, "the refusal did not name the carrier codes the rate card uses"

    async def test_a_negative_price_is_refused(self, async_client):
        resp = await _tier(async_client, {"carrier_code": "zto", "price_per_kg": -5})
        assert resp.status_code == 422, resp.text

    async def test_the_envelope_shape_is_accepted(self, async_client):
        resp = await _tier(async_client, {"data": {
            "carrier_code": "ems", "min_value": 0, "max_value": None, "price_per_unit": 9,
        }})
        assert resp.status_code == 201, resp.text
        assert resp.json()["max_value"] is None, "an open-ended bracket stays open-ended"


# ── The quote the screen shows ───────────────────────────────────────────────


class TestFreightQuoteBody:
    async def test_the_weight_the_operator_typed_prices_the_shipment(self, async_client):
        """The 运费试算 form sends ``total_weight_kg``; the calculation read
        ``data.get("weight", 1)``, so the weight typed in the box never reached
        the price and every quote this screen made priced 1 kg."""
        created = await _tier(async_client, {
            "carrier_code": "yunda", "weight_from": 0, "max_value": None, "price_per_kg": 2.00,
        })
        assert created.status_code == 201, created.text

        resp = await _quote(async_client, {"carrier_code": "yunda", "total_weight_kg": 10})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert float(body["weight_kg"]) == 10.0, "the quote did not price the weight that was typed"
        assert float(body["total_freight_yuan"]) == 20.00, (
            "10 kg at 2.00 per kg is 20.00; the screen showed 2.00 for every shipment"
        )

    async def test_the_service_level_in_the_form_pays_the_surcharge(self, async_client):
        """The form has a 服务类型 select; the surcharge follows from it, and the
        request that says 加急 is the request that pays it."""
        created = await _tier(async_client, {
            "carrier_code": "ems", "weight_from": 0, "max_value": None,
            "price_per_kg": 2.00, "surcharge_express": 5.00,
        })
        assert created.status_code == 201, created.text

        standard = await _quote(async_client, {"carrier_code": "ems", "total_weight_kg": 5, "service_type": "standard"})
        express = await _quote(async_client, {"carrier_code": "ems", "total_weight_kg": 5, "service_type": "express"})
        assert standard.status_code == 200, standard.text
        assert express.status_code == 200, express.text
        assert float(standard.json()["total_freight_yuan"]) == 10.00
        assert float(express.json()["total_freight_yuan"]) == 15.00, (
            "the rate card's own surcharge, not a multiplier invented in code"
        )

    async def test_a_distance_bracket_is_priced_on_kilometres(self, async_client):
        created = await _tier(async_client, {
            "carrier_code": "jd_logistics", "rule_type": "distance_tiered",
            "min_value": 0, "max_value": None, "price_per_unit": 0.80,
        })
        assert created.status_code == 201, created.text

        resp = await _quote(async_client, {"carrier_code": "jd_logistics", "distance": 100})
        assert resp.status_code == 200, resp.text
        assert float(resp.json()["total_freight_yuan"]) == 80.00, (
            "a per-kilometre rule charged weight before; the distance the caller "
            "sent under one accepted spelling has to reach the price"
        )

    async def test_a_shipment_the_rate_card_does_not_cover_says_so(self, async_client):
        created = await _tier(async_client, {
            "carrier_code": "sf_express", "weight_from": 0, "weight_to": 10, "price_per_kg": 8.50,
        })
        assert created.status_code == 201, created.text

        resp = await _quote(async_client, {"carrier_code": "sf_express", "total_weight_kg": 50})
        assert resp.status_code == 422, resp.text
        assert "freight tier" in resp.json()["error"]["message"], resp.text

    async def test_a_weight_that_is_not_a_number_is_refused_by_the_key_sent(self, async_client):
        resp = await _quote(async_client, {"carrier_code": "zto", "total_weight_kg": "十公斤"})
        assert resp.status_code == 422, resp.text
        assert any("total_weight_kg" in f for f in _fields(resp)), resp.text

    async def test_the_envelope_shape_is_accepted(self, async_client):
        created = await _tier(async_client, {
            "carrier_code": "zto", "min_value": 0, "max_value": None, "price_per_unit": 3,
        })
        assert created.status_code == 201, created.text

        resp = await _quote(async_client, {"data": {"carrier_code": "zto", "weight": 2}})
        assert resp.status_code == 200, resp.text
        assert float(resp.json()["total_freight_yuan"]) == 6.0
