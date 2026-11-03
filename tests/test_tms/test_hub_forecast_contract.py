"""The hub screens and the demand model's two input bodies.

``TmsInfrastructure.vue`` posts ``{code, name, type, city}`` for a 中转站, and
the endpoint behind it read a bare ``dict``: the type arrived as ``type`` while
the column is ``hub_type`` (so a hub was created as 主站 no matter what the
operator picked), the capacity, contact name and phone the record carries were
not in the body at all, and the edit dialog's 编码 was dropped on save — the
hub kept its code while the screen said 已更新.  A value the model's vocabulary
did not know (``type: "hub"``, ``status: "active"``, a capacity typed as 一千)
reached ``TransferHubType(...)`` / ``Decimal(...)`` inside the handler, and the
operator's answer was a 500 that named nothing.

The list endpoint made the same screen lie twice more: it serialized the
record's column names, so it answered ``hub_type`` where every other hub
endpoint answered ``type`` — the 类型 column was reading a key the list never
sent.

The demand model had the plainest version of the bug: the observation route did
``float(data["count"])``, so the count a script omitted, or wrote as 八百, was
answered as a server failure, and an observation on an empty lane trained a city
pair no order will ever look up.  Training did ``int(data.get("months", 6))``,
so ``months: "six"`` was a 500 and ``months: 600`` asked the forecaster to
extrapolate over a window it does not build.

Bodies are typed (``src/tms/schemas.py``) and the services keep the same guards
for direct callers; a refused value names the field that carried it, and a value
outside a vocabulary names the vocabulary.
"""

import uuid as uuid_mod
from decimal import Decimal

import pytest

from src.tms import service as tms_service

BAD_UUID = "00000000-0000-0000-0000-000000000000"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def auth_headers(async_client):
    uname = f"hubctr_{uuid_mod.uuid4().hex[:8]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(autouse=True)
async def _authenticated(async_client, auth_headers):
    async_client.headers.update(auth_headers)
    yield


def _hub_code() -> str:
    return f"HUB-{uuid_mod.uuid4().hex[:8]}"


@pytest.fixture
async def hub(async_client) -> dict:
    """A hub created exactly the way the 中转站 dialog creates one."""
    r = await async_client.post("/api/v1/transfer-hubs", json={
        "code": _hub_code(), "name": "武汉中转站", "type": "primary", "city": "武汉",
    })
    assert r.status_code == 201, r.text
    return r.json()


async def _create(async_client, body: dict):
    return await async_client.post("/api/v1/transfer-hubs", json=body)


async def _patch(async_client, hub_id: str, body: dict):
    return await async_client.patch(f"/api/v1/transfer-hubs/{hub_id}", json=body)


def _fields(resp) -> str:
    """Everything the server named in its refusal: field, message, sent value."""
    body = resp.json()
    err = body.get("error") or {}
    parts = [str(err.get("message") or ""), str(body.get("detail") or "")]
    for entry in (body.get("errors") or err.get("errors") or []):
        parts.append(str(entry.get("field")))
        parts.append(str(entry.get("message")))
        parts.append(str(entry.get("value")))
    return " ".join(parts)


def _kg(value: object) -> Decimal:
    """A capacity as the column holds it — ``Numeric(20, 4)`` answers ``"800.0000"``."""
    return Decimal(str(value))


# ── POST /transfer-hubs ─────────────────────────────────────────────────────


class TestHubCreateBody:
    async def test_console_shape_creates_the_hub_the_operator_picked(self, async_client):
        resp = await _create(async_client, {
            "code": _hub_code(), "name": "郑州中转站", "type": "secondary", "city": "郑州",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # ``type`` was the console's key for the hub's type, ``hub_type`` the
        # column's: both spellings mean the hub the operator selected.
        assert body["type"] == "secondary"
        assert body["city"] == "郑州"
        assert body["status"] == "open"

    async def test_hub_type_spelling_is_accepted_too(self, async_client):
        resp = await _create(async_client, {
            "code": _hub_code(), "name": "广州货运站", "hub_type": "cargo_station", "city": "广州",
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["type"] == "cargo_station"

    async def test_capacity_and_contacts_reach_the_record(self, async_client, hub):
        """The dialog's 容量/联系人/联系电话 are the record's columns — they arrive."""
        code = _hub_code()
        resp = await _create(async_client, {
            "code": code, "name": "成都中转站", "type": "primary", "city": "成都",
            "capacity_weight_kg": "1200.50", "contact_name": "张强", "contact_phone": "13800000000",
        })
        assert resp.status_code == 201, resp.text
        assert _kg(resp.json()["capacity_weight_kg"]) == Decimal("1200.50")
        assert resp.json()["contact_name"] == "张强"
        assert resp.json()["contact_phone"] == "13800000000"
        record = await tms_service.get_hub(async_client._shared_session, hub["id"])
        assert _kg(record["capacity_weight_kg"]) == Decimal("0"), "a hub defaults to no capacity, not to a guess"

    async def test_type_outside_the_hub_vocabulary_names_the_vocabulary(self, async_client):
        resp = await _create(async_client, {
            "code": _hub_code(), "name": "中心", "type": "hub", "city": "武汉",
        })
        assert resp.status_code == 422
        fields = _fields(resp)
        assert "primary" in fields and "secondary" in fields and "cargo_station" in fields
        assert "hub" in fields

    async def test_city_is_required_because_the_planner_routes_by_city(self, async_client):
        resp = await _create(async_client, {"code": _hub_code(), "name": "无名中转站"})
        assert resp.status_code == 422
        assert "city" in _fields(resp)

    async def test_negative_capacity_is_refused(self, async_client):
        resp = await _create(async_client, {
            "code": _hub_code(), "name": "负容量", "type": "primary", "city": "武汉",
            "capacity_weight_kg": -5,
        })
        assert resp.status_code == 422
        assert "capacity_weight_kg" in _fields(resp)

    async def test_capacity_typed_as_text_names_the_capacity(self, async_client):
        resp = await _create(async_client, {
            "code": _hub_code(), "name": "一千", "type": "primary", "city": "武汉",
            "capacity_weight_kg": "一千",
        })
        assert resp.status_code == 422
        assert "capacity_weight_kg" in _fields(resp)

    async def test_duplicate_code_names_the_code(self, async_client, hub):
        resp = await _create(async_client, {
            "code": hub["code"], "name": "撞码", "type": "primary", "city": "武汉",
        })
        assert resp.status_code == 422
        assert hub["code"] in _fields(resp)

    async def test_the_data_envelope_is_accepted(self, async_client):
        resp = await _create(async_client, {"data": {
            "code": _hub_code(), "name": "信封站", "type": "primary", "city": "西安",
        }})
        assert resp.status_code == 201, resp.text

    async def test_a_key_the_hub_record_does_not_have_is_refused_by_name(self, async_client):
        resp = await _create(async_client, {
            "code": _hub_code(), "name": "多余字段", "type": "primary", "city": "武汉",
            "manager": "张强",
        })
        assert resp.status_code == 422
        assert "manager" in _fields(resp)


# ── PATCH /transfer-hubs/{id} ───────────────────────────────────────────────


class TestHubUpdateBody:
    async def test_the_edit_dialog_saves_every_field_it_shows(self, async_client, hub):
        """编码/名称/类型/城市: the dialog offers four, and saved two."""
        new_code = _hub_code()
        resp = await _patch(async_client, hub["id"], {
            "code": new_code, "name": "郑州中转站(新)", "type": "cargo_station", "city": "郑州",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == new_code
        assert body["name"] == "郑州中转站(新)"
        assert body["type"] == "cargo_station"
        assert body["city"] == "郑州"

    async def test_capacity_contacts_and_status_are_saved(self, async_client, hub):
        resp = await _patch(async_client, hub["id"], {
            "capacity_weight_kg": "800", "contact_name": "李雷",
            "contact_phone": "13900000000", "status": "maintenance",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert _kg(body["capacity_weight_kg"]) == Decimal("800")
        assert body["contact_name"] == "李雷"
        assert body["status"] == "maintenance"

    async def test_a_status_outside_the_hub_vocabulary_names_the_vocabulary(self, async_client, hub):
        """The console's 状态 tag compared ``'active'`` — the hub model has no such status."""
        resp = await _patch(async_client, hub["id"], {"status": "active"})
        assert resp.status_code == 422
        fields = _fields(resp)
        assert "open" in fields and "maintenance" in fields and "closed" in fields

    async def test_renaming_onto_another_hubs_code_is_refused_by_that_code(self, async_client, hub):
        other = _hub_code()
        await _create(async_client, {"code": other, "name": "占码站", "type": "primary", "city": "武汉"})
        resp = await _patch(async_client, hub["id"], {"code": other})
        assert resp.status_code == 422
        assert other in _fields(resp)
        # Refused means refused: the hub is still reachable under its own code.
        keep = await async_client.get(f"/api/v1/transfer-hubs/{hub['id']}")
        assert keep.json()["code"] == hub["code"]

    async def test_a_blank_code_is_refused(self, async_client, hub):
        resp = await _patch(async_client, hub["id"], {"code": "   "})
        assert resp.status_code == 422
        assert "code" in _fields(resp)

    async def test_negative_capacity_is_refused(self, async_client, hub):
        resp = await _patch(async_client, hub["id"], {"capacity_weight_kg": "-1"})
        assert resp.status_code == 422
        assert "capacity_weight_kg" in _fields(resp)

    async def test_the_data_envelope_is_accepted(self, async_client, hub):
        resp = await _patch(async_client, hub["id"], {"data": {"name": "信封改名"}})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "信封改名"

    async def test_an_unknown_hub_is_not_found(self, async_client):
        resp = await _patch(async_client, BAD_UUID, {"name": "不存在"})
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"


class TestHubShapeIsOneShape:
    async def test_the_list_and_the_detail_name_the_type_the_same_way(self, async_client, hub):
        """The list used to answer ``hub_type`` while every other hub endpoint
        answered ``type`` — the 类型 column read a key the list never sent."""
        listed = await async_client.get("/api/v1/transfer-hubs")
        rows = {row["id"]: row for row in listed.json()["items"]}
        assert hub["id"] in rows
        row = rows[hub["id"]]
        assert row["type"] == hub["type"]
        assert "hub_type" not in row
        detail = await async_client.get(f"/api/v1/transfer-hubs/{hub['id']}")
        assert set(detail.json()) <= set(row)
        assert row["status"] == hub["status"]


# ── POST /forecast/observations ─────────────────────────────────────────────


class TestForecastObservationBody:
    async def test_a_lane_day_is_recorded_on_the_lane_it_names(self, async_client):
        resp = await async_client.post("/api/v1/forecast/observations", json={
            "origin_city": "上海", "destination_city": "北京", "count": 12,
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["key"] == "上海-北京"

    async def test_a_missing_count_names_the_count(self, async_client):
        resp = await async_client.post("/api/v1/forecast/observations", json={
            "origin_city": "上海", "destination_city": "北京",
        })
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
        assert "count" in _fields(resp)

    async def test_a_count_written_as_text_names_the_count(self, async_client):
        resp = await async_client.post("/api/v1/forecast/observations", json={
            "origin_city": "上海", "destination_city": "北京", "count": "八百",
        })
        assert resp.status_code == 422
        assert "count" in _fields(resp)

    async def test_a_day_with_negative_orders_is_not_an_observation(self, async_client):
        resp = await async_client.post("/api/v1/forecast/observations", json={
            "origin_city": "上海", "destination_city": "北京", "count": -3,
        })
        assert resp.status_code == 422
        assert "count" in _fields(resp)

    async def test_an_observation_needs_both_cities(self, async_client):
        resp = await async_client.post("/api/v1/forecast/observations", json={
            "origin_city": "", "destination_city": "北京", "count": 5,
        })
        assert resp.status_code == 422
        assert "origin_city" in _fields(resp)

    async def test_the_data_envelope_is_accepted(self, async_client):
        resp = await async_client.post("/api/v1/forecast/observations", json={"data": {
            "origin_city": "广州", "destination_city": "深圳", "count": 7,
        }})
        assert resp.status_code == 200, resp.text

    async def test_direct_callers_get_the_same_refusal(self, async_client):
        """A task calling the service gets the guard too — it is not HTTP-only."""
        from src.core.exceptions import ValidationException

        for payload in (
            {"origin_city": "", "destination_city": "北京", "count": 1},
            {"origin_city": "上海", "destination_city": "北京"},
            {"origin_city": "上海", "destination_city": "北京", "count": "八百"},
            {"origin_city": "上海", "destination_city": "北京", "count": -1},
        ):
            with pytest.raises(ValidationException):
                await tms_service.record_forecast_observation(async_client._shared_session, payload)


# ── POST /forecast/training ─────────────────────────────────────────────────


async def _order(async_client, origin: str, destination: str) -> dict:
    resp = await async_client.post("/api/v1/transport-orders", json={
        "carrier_code": "sf_express",
        "pickup_warehouse_id": str(uuid_mod.uuid4()),
        "delivery_name": "预测训练",
        "pickup_address": {"city": origin},
        "delivery_address": {"city": destination},
    })
    return resp.json()


class TestForecastTrainingBody:
    async def test_months_outside_the_models_window_is_refused_by_name(self, async_client):
        resp = await async_client.post("/api/v1/forecast/training", json={"months": 600})
        assert resp.status_code == 422
        assert "months" in _fields(resp)

    async def test_months_written_as_text_is_refused_by_name(self, async_client):
        resp = await async_client.post("/api/v1/forecast/training", json={"months": "six"})
        assert resp.status_code == 422
        assert "months" in _fields(resp)

    async def test_training_reports_what_it_trained(self, async_client):
        await _order(async_client, "苏州", "杭州")
        resp = await async_client.post("/api/v1/forecast/training", json={"months": 6})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["trained"] >= 1
        assert body["skipped"] == 0

    async def test_orders_without_cities_are_counted_as_skipped(self, async_client):
        """A lane key of ``"-"`` is a city pair no order will ever ask the model about."""
        await _order(async_client, "南京", "合肥")
        await _order(async_client, "", "")
        resp = await async_client.post("/api/v1/forecast/training", json={"months": 6})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["trained"] >= 1
        assert body["skipped"] >= 1

    async def test_direct_callers_get_the_same_guard(self, async_client):
        from src.core.exceptions import ValidationException

        for months in ("six", 0, 600):
            with pytest.raises(ValidationException):
                await tms_service.train_forecast(async_client._shared_session, months=months)
