"""Tests for src.routes.stock — Stock In / Stock Out / Inventory Log / Adjust Stock."""
import uuid as uuid_mod

import pytest


@pytest.fixture
async def auth_headers(async_client):
    uname = f"stockuser_{uuid_mod.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def anonymous_client(async_client):
    """A second client on the same app and the same overridden session, no credentials.

    Same ``app`` object, so the ``get_db`` override the ``async_client`` fixture
    installed still applies — this is the same database transaction, just an
    unauthenticated caller.
    """
    from httpx import ASGITransport, AsyncClient

    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as anon:
        yield anon


@pytest.fixture(autouse=True)
async def _stock_api_is_authenticated(async_client, auth_headers):
    """Default every call in this module to a logged-in caller.

    src/routes/stock.py:24 declares the whole stock API as
    ``APIRouter(dependencies=[Depends(get_current_user)])``.  The mount in
    src/stock/router.py used to rebuild each route with
    ``add_api_route(path, endpoint, methods, status_code)``, which carried no
    ``dependencies`` — so this suite could call stock-in, stock-out and
    inventory-log with no Authorization header at all and still get a 2xx.  The
    tests were green against an API that was answering anonymous callers in
    production.  Headers are on by default from here; the one test that wants
    anonymity passes ``{"Authorization": None}`` to drop the default.
    """
    async_client.headers.update(auth_headers)
    yield


@pytest.fixture
async def warehouse(async_client, auth_headers):
    r = await async_client.post("/api/v1/warehouses", json={
        "code": f"WH-STOCK-{uuid_mod.uuid4().hex[:6]}",
        "name": "Stock Test Warehouse",
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def vendor(async_client, auth_headers):
    r = await async_client.post("/api/v1/warehouses/vendors", json={
        "code": f"VEND-{uuid_mod.uuid4().hex[:6]}",
        "name": "Stock Test Vendor",
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


STOCK_IN_BODY = {
    "type": "PURCHASE",
    "ref_no": "PO-1001",
    "reference_type": "purchase_order",
    "lines": [
        {"sku": "SKU-A", "qty": 10, "batch_no": "B1"},
        {"sku": "SKU-B", "qty": 5},
    ],
}

STOCK_OUT_BODY = {
    "type": "SALE",
    "ref_no": "SO-2001",
    "reference_type": "sales_order",
    "lines": [
        {"sku": "SKU-A", "qty": 3},
    ],
}


class TestCreateStockIn:
    async def test_create_stock_in(self, async_client, warehouse):
        resp = await async_client.post("/api/v1/stock-in", json={
            "data": {**STOCK_IN_BODY, "warehouse_id": warehouse["id"]},
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["warehouse_id"] == warehouse["id"]
        assert data["type"] == "PURCHASE"
        assert str(data["total_qty"]) == "15.0000"
        assert data["status"] == "DRAFT"

    async def test_create_stock_in_with_supplier(self, async_client, warehouse, vendor):
        resp = await async_client.post("/api/v1/stock-in", json={
            "data": {
                **STOCK_IN_BODY,
                "warehouse_id": warehouse["id"],
                "supplier_id": vendor["id"],
            },
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["supplier_id"] == vendor["id"]

    async def test_create_stock_in_warehouse_not_found(self, async_client):
        resp = await async_client.post("/api/v1/stock-in", json={
            "data": {
                **STOCK_IN_BODY,
                "warehouse_id": "00000000-0000-0000-0000-000000000000",
            },
        })
        assert resp.status_code == 404

    async def test_create_stock_in_supplier_not_found(self, async_client, warehouse):
        resp = await async_client.post("/api/v1/stock-in", json={
            "data": {
                **STOCK_IN_BODY,
                "warehouse_id": warehouse["id"],
                "supplier_id": "00000000-0000-0000-0000-000000000000",
            },
        })
        assert resp.status_code == 404


class TestGetStockIn:
    async def test_get_stock_in_with_lines(self, async_client, warehouse):
        created = await async_client.post("/api/v1/stock-in", json={
            "data": {**STOCK_IN_BODY, "warehouse_id": warehouse["id"]},
        })
        sid = created.json()["id"]
        resp = await async_client.get(f"/api/v1/stock-in/{sid}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == sid
        assert len(data["lines"]) == 2
        assert data["lines"][0]["sku"] == "SKU-A"

    async def test_get_stock_in_not_found(self, async_client):
        resp = await async_client.get("/api/v1/stock-in/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestListStockIn:
    async def test_list_stock_in(self, async_client, warehouse):
        await async_client.post("/api/v1/stock-in", json={
            "data": {**STOCK_IN_BODY, "warehouse_id": warehouse["id"]},
        })
        resp = await async_client.get("/api/v1/stock-in")
        assert resp.status_code == 200, resp.text
        assert any(item["ref_no"] == "PO-1001" for item in resp.json())

    async def test_list_stock_in_filter_by_warehouse(self, async_client, warehouse):
        await async_client.post("/api/v1/stock-in", json={
            "data": {**STOCK_IN_BODY, "warehouse_id": warehouse["id"]},
        })
        resp = await async_client.get(f"/api/v1/stock-in?warehouse_id={warehouse['id']}")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestUpdateStockIn:
    async def test_update_status_valid(self, async_client, warehouse):
        created = await async_client.post("/api/v1/stock-in", json={
            "data": {**STOCK_IN_BODY, "warehouse_id": warehouse["id"]},
        })
        sid = created.json()["id"]
        resp = await async_client.put(f"/api/v1/stock-in/{sid}", json={"data": {"status": "CONFIRMED"}})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "CONFIRMED"

    async def test_update_status_invalid_transition(self, async_client, warehouse):
        created = await async_client.post("/api/v1/stock-in", json={
            "data": {**STOCK_IN_BODY, "warehouse_id": warehouse["id"]},
        })
        sid = created.json()["id"]
        resp = await async_client.put(f"/api/v1/stock-in/{sid}", json={"data": {"status": "RECEIVED"}})
        assert resp.status_code == 400

    async def test_update_not_found(self, async_client):
        resp = await async_client.put(
            "/api/v1/stock-in/00000000-0000-0000-0000-000000000000",
            json={"data": {"status": "CONFIRMED"}},
        )
        assert resp.status_code == 404


class TestCreateStockOut:
    async def test_create_stock_out(self, async_client, warehouse):
        resp = await async_client.post("/api/v1/stock-out", json={
            "data": {**STOCK_OUT_BODY, "warehouse_id": warehouse["id"]},
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["type"] == "SALE"
        assert str(data["total_qty"]) == "3.0000"
        assert data["status"] == "DRAFT"

    async def test_create_stock_out_warehouse_not_found(self, async_client):
        resp = await async_client.post("/api/v1/stock-out", json={
            "data": {
                **STOCK_OUT_BODY,
                "warehouse_id": "00000000-0000-0000-0000-000000000000",
            },
        })
        assert resp.status_code == 404


class TestGetStockOut:
    async def test_get_stock_out_with_lines(self, async_client, warehouse):
        created = await async_client.post("/api/v1/stock-out", json={
            "data": {**STOCK_OUT_BODY, "warehouse_id": warehouse["id"]},
        })
        oid = created.json()["id"]
        resp = await async_client.get(f"/api/v1/stock-out/{oid}")
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["lines"]) == 1

    async def test_get_stock_out_not_found(self, async_client):
        resp = await async_client.get("/api/v1/stock-out/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestListStockOut:
    async def test_list_stock_out(self, async_client, warehouse):
        await async_client.post("/api/v1/stock-out", json={
            "data": {**STOCK_OUT_BODY, "warehouse_id": warehouse["id"]},
        })
        resp = await async_client.get("/api/v1/stock-out")
        assert resp.status_code == 200, resp.text
        assert any(item["ref_no"] == "SO-2001" for item in resp.json())


class TestUpdateStockOut:
    async def test_update_status_valid(self, async_client, warehouse):
        created = await async_client.post("/api/v1/stock-out", json={
            "data": {**STOCK_OUT_BODY, "warehouse_id": warehouse["id"]},
        })
        oid = created.json()["id"]
        resp = await async_client.put(f"/api/v1/stock-out/{oid}", json={"data": {"status": "CONFIRMED"}})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "CONFIRMED"

    async def test_update_status_invalid_transition(self, async_client, warehouse):
        created = await async_client.post("/api/v1/stock-out", json={
            "data": {**STOCK_OUT_BODY, "warehouse_id": warehouse["id"]},
        })
        oid = created.json()["id"]
        resp = await async_client.put(f"/api/v1/stock-out/{oid}", json={"data": {"status": "SHIPPED"}})
        assert resp.status_code == 400

    async def test_update_not_found(self, async_client):
        resp = await async_client.put(
            "/api/v1/stock-out/00000000-0000-0000-0000-000000000000",
            json={"data": {"status": "CONFIRMED"}},
        )
        assert resp.status_code == 404


class TestInventoryLog:
    async def _make_log(self, async_client, warehouse, auth_headers):
        await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": "00000000-0000-0000-0000-000000000001",
            "warehouse_id": warehouse["id"],
            "quantity": 5,
            "reason": "COUNT_ERROR",
        }})
        logs = (await async_client.get("/api/v1/inventory-log")).json()
        return logs[0]

    async def test_list_inventory_log(self, async_client, warehouse, auth_headers):
        await self._make_log(async_client, warehouse, auth_headers)
        resp = await async_client.get("/api/v1/inventory-log")
        assert resp.status_code == 200, resp.text
        assert len(resp.json()) == 1

    async def test_list_inventory_log_filter(self, async_client, warehouse, auth_headers):
        await self._make_log(async_client, warehouse, auth_headers)
        resp = await async_client.get(f"/api/v1/inventory-log?warehouse_id={warehouse['id']}")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_get_inventory_log(self, async_client, warehouse, auth_headers):
        log = await self._make_log(async_client, warehouse, auth_headers)
        resp = await async_client.get(f"/api/v1/inventory-log/{log['id']}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["type"] == "ADJUSTMENT_IN"

    async def test_get_inventory_log_not_found(self, async_client):
        resp = await async_client.get("/api/v1/inventory-log/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestAdjustStock:
    async def test_adjust_stock_in(self, async_client, warehouse, auth_headers):
        """``"operator": "test"`` used to be in this body.

        The route read ``operator_id``, ignored ``operator``, and its own
        fallback — ``str(UUID(current_user["sub"]))`` — raised on every request
        because ``sub`` is a username: the audit row's operator column was NULL
        always, and the test suite was asserting against a log that had no
        operator in it by construction.
        """
        resp = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": "00000000-0000-0000-0000-000000000001",
            "warehouse_id": warehouse["id"],
            "quantity": 10,
            "reason": "FOUND",
        }})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["type"] == "ADJUSTMENT_IN"
        assert data["quantity"] == "10"
        me = await async_client.get("/api/v1/auth/me", headers=auth_headers)
        assert data["operator_id"] == me.json()["id"], "the adjustment named no operator"

    async def test_adjust_stock_out(self, async_client, warehouse, auth_headers):
        # OUT now actually decrements stock, so seed some first.
        seed = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": "00000000-0000-0000-0000-000000000001",
            "warehouse_id": warehouse["id"],
            "quantity": 10,
        }})
        assert seed.status_code == 200, seed.text
        resp = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": "00000000-0000-0000-0000-000000000001",
            "warehouse_id": warehouse["id"],
            "quantity": -4,
            "reason": "LOST",
        }})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["type"] == "ADJUSTMENT_OUT"
        assert data["quantity"] == "4"

    async def test_adjust_stock_out_insufficient_rejected(self, async_client, warehouse, auth_headers):
        resp = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": "00000000-0000-0000-0000-000000000001",
            "warehouse_id": warehouse["id"],
            "quantity": -999,
        }})
        assert resp.status_code == 400

    async def test_adjust_stock_requires_auth(self, anonymous_client, warehouse):
        # A separate client with no credentials: this is the one stock call that
        # must arrive anonymous.
        resp = await anonymous_client.post("/api/v1/adjust-stock", json={"data": {
            "sku_id": "00000000-0000-0000-0000-000000000001",
            "warehouse_id": warehouse["id"],
            "quantity": 10,
        }})
        assert resp.status_code == 401, resp.text[:200]

    async def test_adjust_stock_zero_rejected(self, async_client, warehouse, auth_headers):
        resp = await async_client.post("/api/v1/adjust-stock", headers=auth_headers, json={"data": {
            "sku_id": "00000000-0000-0000-0000-000000000001",
            "warehouse_id": warehouse["id"],
            "quantity": 0,
        }})
        assert resp.status_code == 400
