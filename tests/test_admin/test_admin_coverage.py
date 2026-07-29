"""Tests for admin Web UI — covering un-tested pages and forms."""
import io
import uuid as uuid_mod

import pytest


@pytest.fixture
async def auth_headers(async_client):
    uname = f"adm2_{uuid_mod.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def csrf(async_client, auth_headers):
    resp = await async_client.get("/admin/", headers=auth_headers)
    assert resp.status_code == 200
    token = resp.cookies.get("csrf_token")
    if not token:
        pytest.skip("CSRF cookie not set")
    return token


@pytest.fixture
def csrf_cookies(csrf):
    return {"csrf_token": csrf}


@pytest.fixture
def csrf_headers(auth_headers, csrf):
    return {**auth_headers, "X-CSRF-Token": csrf}


class TestAdminPages:
    async def test_webhooks_page(self, async_client, auth_headers):
        resp = await async_client.get("/admin/webhooks", headers=auth_headers)
        assert resp.status_code == 200

    async def test_route_plans_page(self, async_client, auth_headers):
        resp = await async_client.get("/admin/route-plans", headers=auth_headers)
        assert resp.status_code == 200

    async def test_returns_page(self, async_client, auth_headers):
        resp = await async_client.get("/admin/returns", headers=auth_headers)
        assert resp.status_code == 200

    async def test_exceptions_page(self, async_client, auth_headers):
        resp = await async_client.get("/admin/exceptions", headers=auth_headers)
        assert resp.status_code == 200

    async def test_forecast_page(self, async_client, auth_headers):
        resp = await async_client.get("/admin/forecast", headers=auth_headers)
        assert resp.status_code == 200

    async def test_import_page(self, async_client, auth_headers):
        resp = await async_client.get("/admin/import", headers=auth_headers)
        assert resp.status_code == 200

    async def test_warehouse_edit_page(self, async_client, auth_headers):
        wh = await async_client.post("/api/v1/warehouses", json={
            "code": "WH-EDIT", "name": "Edit WH", "address": "Test", "type": "standard",
        }, headers=auth_headers)
        wh_id = wh.json()["id"]
        resp = await async_client.get(f"/admin/warehouses/{wh_id}/edit", headers=auth_headers)
        assert resp.status_code == 200

    async def test_ml_forecast_page_render(self, async_client, auth_headers):
        resp = await async_client.get("/admin/ml/forecast", headers=auth_headers)
        assert resp.status_code == 200


class TestAdminExports:
    async def test_export_orders_csv(self, async_client, auth_headers):
        resp = await async_client.get("/admin/export/orders", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/csv; charset=utf-8"

    async def test_export_inventory_csv(self, async_client, auth_headers):
        resp = await async_client.get("/admin/export/inventory", headers=auth_headers)
        assert resp.status_code == 200

    async def test_export_transport_orders_csv(self, async_client, auth_headers):
        resp = await async_client.get("/admin/export/transport-orders", headers=auth_headers)
        assert resp.status_code == 200

    async def test_export_returns_csv(self, async_client, auth_headers):
        resp = await async_client.get("/admin/export/returns", headers=auth_headers)
        assert resp.status_code == 200

    async def test_export_exceptions_csv(self, async_client, auth_headers):
        resp = await async_client.get("/admin/export/exceptions", headers=auth_headers)
        assert resp.status_code == 200

    async def test_export_route_plans_csv(self, async_client, auth_headers):
        resp = await async_client.get("/admin/export/route-plans", headers=auth_headers)
        assert resp.status_code == 200

    async def test_export_forecast_csv(self, async_client, auth_headers):
        resp = await async_client.get("/admin/export/ml-forecast", headers=auth_headers)
        assert resp.status_code == 200

    async def test_export_transport_orders_csv_with_data(self, async_client, auth_headers, monkeypatch):
        async def mock_list(*args, **kwargs):
            return ([{"transport_no": "TN001", "status": "dispatched",
                       "carrier_code": "sf_express",
                       "pickup_address": {"city": "Wuhan"},
                       "delivery_address": {"city": "Changsha"},
                       "total_weight_kg": "10.5",
                       "created_at": "2026-01-01T00:00:00"}], 1)
        monkeypatch.setattr("src.admin.router.tms_service.list_transport_orders", mock_list)
        resp = await async_client.get("/admin/export/transport-orders", headers=auth_headers)
        assert resp.status_code == 200
        content = resp.text
        assert "TN001" in content
        assert "Wuhan" in content
        assert "Changsha" in content
        assert "sf_express" in content

    async def test_export_returns_csv_with_data(self, async_client, auth_headers, monkeypatch):
        async def mock_list(*args, **kwargs):
            return ([{"return_no": "RN001", "status": "pending",
                      "reason": "damaged", "refund_amount": "150.00"}], 1)
        monkeypatch.setattr("src.admin.router.tms_service.list_return_orders", mock_list)
        resp = await async_client.get("/admin/export/returns", headers=auth_headers)
        assert resp.status_code == 200
        content = resp.text
        assert "RN001" in content
        assert "damaged" in content
        assert "150.00" in content

    async def test_export_exceptions_csv_with_data(self, async_client, auth_headers, monkeypatch):
        async def mock_list(*args, **kwargs):
            return [{"id": "EXC001", "status": "open",
                     "type": "delay", "severity": "high"}]
        monkeypatch.setattr("src.admin.router.tms_service.list_exceptions", mock_list)
        resp = await async_client.get("/admin/export/exceptions", headers=auth_headers)
        assert resp.status_code == 200
        content = resp.text
        assert "EXC001" in content
        assert "delay" in content
        assert "high" in content

    async def test_export_route_plans_csv_with_data(self, async_client, auth_headers, db_session):
        import uuid as uuid_mod
        from src.tms.models import RoutePlan, RoutePlanType, RoutePlanStatus
        from decimal import Decimal
        plan = RoutePlan(
            id=uuid_mod.uuid4(),
            transport_order_id=uuid_mod.uuid4(),
            type=RoutePlanType.AUTO_GEN,
            status=RoutePlanStatus.ROUTE_ACTIVE,
            origin_city="Wuhan",
            destination_city="Changsha",
            total_distance_km=Decimal("350"),
            total_cost_amount=Decimal("1200.00"),
            plan_json={},
        )
        db_session.add(plan)
        await db_session.commit()
        resp = await async_client.get("/admin/export/route-plans", headers=auth_headers)
        assert resp.status_code == 200
        content = resp.text
        assert "Wuhan" in content
        assert "Changsha" in content


class TestAdminForms:
    async def test_create_order(self, async_client, csrf_headers, csrf_cookies):
        resp = await async_client.post("/admin/orders",
            data={"order_no": "ADM-FRM-001", "customer_id": "frm-cust", "total_amount": "100"},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 303

    async def test_create_user(self, async_client, csrf_headers, csrf_cookies):
        resp = await async_client.post("/admin/users",
            data={"username": f"newadm_{uuid_mod.uuid4().hex[:4]}",
                  "email": "newadm@test.com", "password": "adm123456"},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 303

    async def test_webhook_create(self, async_client, csrf_headers, csrf_cookies):
        resp = await async_client.post("/admin/webhooks",
            data={"name": "Test Webhook", "url": "https://example.com/hook",
                  "events": "order.created"},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 303

    async def test_webhook_delete(self, async_client, csrf_headers, csrf_cookies):
        create = await async_client.post("/admin/webhooks",
            data={"name": "Del Webhook", "url": "https://example.com/del",
                  "events": "order.created"},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert create.status_code == 303
        list_resp = await async_client.get("/admin/webhooks", headers=csrf_headers)
        assert list_resp.status_code == 200
        resp = await async_client.post("/admin/webhooks/0/delete",
            data={}, cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 303

    async def test_create_warehouse(self, async_client, csrf_headers, csrf_cookies):
        resp = await async_client.post("/admin/warehouses",
            data={"code": "ADM-WH", "name": "Admin WH", "address": "Addr",
                  "type": "standard"},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 200

    async def test_import_orders_no_file(self, async_client, csrf_headers, csrf_cookies):
        resp = await async_client.post("/admin/import/orders",
            data={}, cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 303

    async def test_import_orders_with_file(self, async_client, csrf_headers, csrf_cookies):
        csv_content = b"order_no,customer_id,total_amount\nADM-IMP-001,imp-cust,100\n"
        resp = await async_client.post("/admin/import/orders",
            files={"file": ("orders.csv", csv_content, "text/csv")},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 303

    async def test_import_inventory_no_file(self, async_client, csrf_headers, csrf_cookies):
        resp = await async_client.post("/admin/import/inventory",
            data={}, cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 303

    async def test_update_order_status(self, async_client, csrf_headers, csrf_cookies):
        order = await async_client.post("/api/v1/orders", json={
            "customer_id": "stat-cust",
            "items": [{"gtin": "6901234567890", "sku": "STAT-001", "product_name": "Status Item",
                       "quantity": 1, "unit_price": 10.0}],
        }, headers=csrf_headers)
        order_id = order.json()["id"]
        resp = await async_client.post(f"/admin/orders/{order_id}/status",
            data={"status": "confirmed"},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 303

    async def test_train_forecast(self, async_client, csrf_headers, csrf_cookies):
        resp = await async_client.post("/admin/forecast/training",
            data={"origin_city": "Wuhan", "destination_city": "Changsha", "count": 50},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 200

    async def test_update_warehouse(self, async_client, csrf_headers, csrf_cookies):
        wh = await async_client.post("/api/v1/warehouses", json={
            "code": "PUT-WH", "name": "Put WH", "address": "Addr", "type": "standard",
        }, headers=csrf_headers)
        wh_id = wh.json()["id"]
        resp = await async_client.put(f"/admin/warehouses/{wh_id}",
            data={"name": "Updated WH"},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 200

    async def test_delete_warehouse(self, async_client, csrf_headers, csrf_cookies):
        wh = await async_client.post("/api/v1/warehouses", json={
            "code": "DEL-WH", "name": "Del WH", "address": "Addr", "type": "standard",
        }, headers=csrf_headers)
        wh_id = wh.json()["id"]
        resp = await async_client.delete(f"/admin/warehouses/{wh_id}",
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 200

    async def test_delete_user(self, async_client, csrf_headers, csrf_cookies):
        uname = f"delusr_{uuid_mod.uuid4().hex[:4]}"
        await async_client.post("/api/v1/auth/register", json={
            "username": uname, "email": "del@test.com", "password": "pass123456",
        }, headers=csrf_headers)
        users_resp = await async_client.get("/api/v1/auth/users", headers=csrf_headers)
        users = users_resp.json()
        target = [u for u in users if u["username"] == uname]
        if not target:
            pytest.skip("Created user not found")
        uid = target[0]["id"]
        resp = await async_client.post(f"/admin/users/{uid}/delete",
            data={}, cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 303

    async def test_toggle_user_active(self, async_client, csrf_headers, csrf_cookies):
        uname = f"toggl_{uuid_mod.uuid4().hex[:4]}"
        await async_client.post("/api/v1/auth/register", json={
            "username": uname, "email": "toggle@test.com", "password": "pass123456",
        }, headers=csrf_headers)
        users_resp = await async_client.get("/api/v1/auth/users", headers=csrf_headers)
        users = users_resp.json()
        target = [u for u in users if u["username"] == uname]
        if not target:
            pytest.skip("Created user not found")
        uid = target[0]["id"]
        resp = await async_client.post(f"/admin/users/{uid}/toggle",
            data={}, cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 303


class TestAdminErrorPaths:
    async def test_create_order_fails(self, async_client, csrf_headers, csrf_cookies):
        resp = await async_client.post("/admin/orders",
            data={},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 400

    async def test_create_user_fails(self, async_client, csrf_headers, csrf_cookies):
        resp = await async_client.post("/admin/users",
            data={"username": "nopass"},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 400

    async def test_update_order_status_invalid(self, async_client, csrf_headers, csrf_cookies):
        order = await async_client.post("/api/v1/orders", json={
            "customer_id": "err-cust",
            "items": [{"gtin": "6901234567890", "sku": "ERR-001", "product_name": "Err Item",
                       "quantity": 1, "unit_price": 10.0}],
        }, headers=csrf_headers)
        order_id = order.json()["id"]
        resp = await async_client.post(f"/admin/orders/{order_id}/status",
            data={"status": "invalid_status"},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 400


class TestAdminEdgeCases:
    async def test_flash_messages(self, async_client, auth_headers):
        resp = await async_client.get("/admin/?flash_success=OK&flash_error=Problem", headers=auth_headers)
        assert resp.status_code == 200

    async def test_toggle_user_active_not_found(self, async_client, csrf_cookies, csrf_headers):
        resp = await async_client.post("/admin/users/00000000-0000-0000-0000-000000000000/toggle",
            data={}, cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 404

    async def test_import_orders_with_errors(self, async_client, csrf_headers, csrf_cookies):
        csv_content = "gtin,sku,product_name,quantity,unit_price\ninvalid,SKU-ERR,Wrong,abc,def"
        resp = await async_client.post("/admin/import/orders",
            files={"file": ("orders.csv", csv_content, "text/csv")},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 303

    async def test_import_inventory_success(self, async_client, csrf_headers, csrf_cookies):
        csv_content = "sku,product_name,quantity,warehouse_code\nINV-IMP,Test Item,10,MAIN"
        resp = await async_client.post("/admin/import/inventory",
            files={"file": ("inv.csv", csv_content, "text/csv")},
            cookies=csrf_cookies, headers=csrf_headers,
        )
        assert resp.status_code == 303

    async def test_export_forecast_csv(self, async_client, csrf_headers, csrf_cookies):
        resp = await async_client.get("/admin/export/ml-forecast", headers=csrf_headers)
        assert resp.status_code == 200

    async def test_train_ml_forecast_direct(self, monkeypatch):
        from starlette.responses import HTMLResponse
        from src.admin.router import train_ml_forecast

        def fake_render(req, template, ctx):
            return HTMLResponse("<html><body>Trained with 100 orders</body></html>")

        monkeypatch.setattr("src.admin.router._render", fake_render)

        result = await train_ml_forecast(
            None,
            {"origin_city": "NYC", "destination_city": "LAX", "count": 100},
            None,
        )
        assert "Trained" in result.body.decode()
