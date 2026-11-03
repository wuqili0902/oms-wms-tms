"""OMS-WMS-TMS 投产冒烟测试 (pytest 版)

使用方法:
    pytest tests/smoke_test.py -v --tb=short
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

P = "/api/v1"
PASS = 0
FAIL = 0


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def tokens(async_client: AsyncClient) -> dict:
    r = await async_client.post(f"{P}/auth/register", json=dict(
        username="smoke_admin", email="smoke@test.com", password="Test1234",
    ))
    if r.status_code not in (200, 201, 400):
        pytest.fail(f"注册失败: {r.status_code} {r.text[:200]}")
    r = await async_client.post(f"{P}/auth/login", json=dict(
        username="smoke_admin", password="Test1234",
    ))
    assert r.status_code in (200, 201), f"登录失败: {r.text[:200]}"
    data = r.json()
    return data if isinstance(data, dict) else (data.get("data", {}) or {})


@pytest.fixture
def auth_header(tokens: dict) -> dict:
    token = tokens.get("access_token") or tokens.get("token") or ""
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════════
# 1. AUTH
# ═══════════════════════════════════════════════════════════════════════
class TestAuth:
    async def test_register_login(self, async_client: AsyncClient, tokens: dict):
        assert tokens.get("access_token") or tokens.get("token"), str(tokens)

    async def test_get_me(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/auth/me", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_refresh_token(self, async_client: AsyncClient, tokens: dict):
        refresh = tokens.get("refresh_token")
        if not refresh:
            pytest.skip("无 refresh_token")
        r = await async_client.post(f"{P}/auth/refresh",
                                     json={"refresh_token": refresh})
        assert r.status_code in (200, 201), r.text[:200]


# ═══════════════════════════════════════════════════════════════════════
# 2. OMS
# ═══════════════════════════════════════════════════════════════════════
class TestOMS:
    async def test_list_orders(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/orders", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_create_order(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.post(f"{P}/orders", headers=auth_header, json={
            "customer_id": "00000000-0000-0000-0000-000000000001",
            "priority": "medium",
            "notes": "冒烟测试",
            "items": [{
                "gtin": "6901234567890",
                "sku": "SKU-SMOKE-001",
                "product_name": "冒烟测试商品",
                "quantity": 2,
                "unit_price": 999.99,
            }],
        })
        assert r.status_code in (200, 201), r.text[:300]
        pytest.STATE["order"] = r.json().get("id") or r.json().get("data", {}).get("id")

    async def test_get_order(self, async_client: AsyncClient, auth_header: dict):
        oid = pytest.STATE.get("order", getattr(self, "order_id", None))
        if not oid:
            pytest.skip("无订单 ID")
        r = await async_client.get(f"{P}/orders/{oid}", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_update_order_status(self, async_client: AsyncClient, auth_header: dict):
        oid = pytest.STATE.get("order")
        if not oid:
            pytest.skip("无订单 ID")
        r = await async_client.put(f"{P}/orders/{oid}/status", headers=auth_header,
                                    json={"status": "confirmed"})
        assert r.status_code in (200, 201), r.text[:200]

    async def test_order_history(self, async_client: AsyncClient, auth_header: dict):
        oid = pytest.STATE.get("order")
        if not oid:
            pytest.skip("无订单 ID")
        r = await async_client.get(f"{P}/orders/{oid}/history", headers=auth_header)
        assert r.status_code == 200, r.text[:200]


# ═══════════════════════════════════════════════════════════════════════
# 3. WMS
# ═══════════════════════════════════════════════════════════════════════
class TestWMS:
    async def test_list_warehouses(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/warehouses", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_create_warehouse(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.post(f"{P}/warehouses", headers=auth_header, json={
            "name": "冒烟仓库", "code": "WH-SMOKE", "type": "standard",
            "status": "active", "address": "上海市", "city": "上海",
            "province": "上海", "country": "中国",
            "contact_name": "张三", "contact_phone": "13800138000",
        })
        assert r.status_code in (200, 201), r.text[:300]
        pytest.STATE["wh_id"] = r.json().get("id")

    async def test_inventory(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/warehouses/inventory", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_purchase_orders(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/warehouses/purchase-orders", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_shipments(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/warehouses/shipments", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_invoices(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/warehouses/invoices", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_vendors(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/warehouses/vendors", headers=auth_header)
        assert r.status_code == 200, r.text[:200]


# ═══════════════════════════════════════════════════════════════════════
# 4. TMS
# ═══════════════════════════════════════════════════════════════════════
class TestTMS:
    async def test_list_transport(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/transport-orders", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_create_transport(self, async_client: AsyncClient, auth_header: dict):
        import sys
        if sys.version_info >= (3, 14):
            pytest.skip("Python 3.14+ SQLAlchemy UUID/SQLite 兼容问题")
        uid = "00000000-0000-0000-0000-000000000001"
        r = await async_client.post(f"{P}/transport-orders", headers=auth_header, json={
            "carrier_code": "sf_express",
            "service_type": "standard",
            "transport_type": "carrier_pickup",
            "pickup_warehouse_id": uid,
            "delivery_name": "冒烟收件人",
            "delivery_phone": "13900139000",
            "package_count": 1,
            "total_weight_kg": 5.5,
        })
        if r.status_code in (200, 201):
            body = r.json()
            tms_id = body.get("id") or body.get("data", {}).get("id")
            if tms_id:
                pytest.STATE["tms_id"] = tms_id

    async def test_get_transport(self, async_client: AsyncClient, auth_header: dict):
        tid = pytest.STATE.get("tms_id")
        if not tid:
            pytest.skip("无运输单 ID")
        r = await async_client.get(f"{P}/transport-orders/{tid}", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_update_transport_status(self, async_client: AsyncClient, auth_header: dict):
        tid = pytest.STATE.get("tms_id")
        if not tid:
            pytest.skip("无运输单 ID")
        r = await async_client.put(f"{P}/transport-orders/{tid}/status",
                                    headers=auth_header, json={"status": "in_transit"})
        assert r.status_code in (200, 201), r.text[:200]
        assert r.json().get("status") == "in_transit", r.text[:200]

    async def test_tracking_events(self, async_client: AsyncClient, auth_header: dict):
        tid = pytest.STATE.get("tms_id")
        if not tid:
            pytest.skip("无运输单 ID")
        r = await async_client.post(
            f"{P}/transport-orders/{tid}/tracking-events",
            headers=auth_header,
            json={"event_type": "pickup_completed", "location_name": "上海分拨中心",
                  "remark": "已揽收"},
        )
        assert r.status_code in (200, 201), r.text[:200]
        # A scan is only worth filing if what the operator typed survived.  The
        # route took a bare dict, so the body above (and the older
        # PICKED_UP/location/description one) was accepted and then dropped.
        body = r.json()
        assert body.get("event_type") == "pickup_completed", r.text[:200]
        assert body.get("location_name") == "上海分拨中心", r.text[:200]
        assert body.get("remark") == "已揽收", r.text[:200]

    async def test_return_orders(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/return-orders", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_exceptions(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/exceptions", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_freight_estimate(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.post(f"{P}/freight-estimate", headers=auth_header,
                                     params={"carrier_code": "sf_express",
                                             "distance_km": 1200,
                                             "weight_kg": 5.5})
        assert r.status_code in (200, 201), r.text[:200]


# ═══════════════════════════════════════════════════════════════════════
# 5. EXTRA
# ═══════════════════════════════════════════════════════════════════════
class TestExtra:
    async def test_barcode(self, async_client: AsyncClient, auth_header: dict):
        import sys
        if sys.version_info >= (3, 14):
            pytest.skip("Python 3.14+ SQLAlchemy UUID/SQLite 兼容问题")
        r = await async_client.post(f"{P}/barcode/generate", headers=auth_header,
                                     json={"gtin_prefix": "69012345678", "entity_type": "order",
                                           "entity_id": "00000000-0000-0000-0000-000000000001",
                                           "format": "code128"})
        assert r.status_code in (200, 201), r.text[:200]

    async def test_label_templates(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/barcode/templates", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_notifications(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/notifications/", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_webhooks(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/webhooks/", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_analytics_dashboard(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/analytics/dashboard", headers=auth_header)
        assert r.status_code == 200, r.text[:200]

    async def test_analytics_trends(self, async_client: AsyncClient, auth_header: dict):
        r = await async_client.get(f"{P}/analytics/order-trends",
                                    headers=auth_header, params={"days": 30})
        assert r.status_code == 200, r.text[:200]

    async def test_logistics_waybill(self, async_client: AsyncClient, auth_header: dict):
        import sys
        if sys.version_info >= (3, 14):
            pytest.skip("Python 3.14+ 中 get_db 依赖存在 AsyncGeneratorContextManager 兼容问题")
        r = await async_client.post(f"{P}/logistics/waybill/create", headers=auth_header,
                                     json={
                                         "order_id": pytest.STATE.get("order")
                                         or f"SMOKE-{__import__('time').time():.0f}",
                                         "carrier_code": "sf",
                                         "recipient_name": "冒烟收件人",
                                         "recipient_phone": "13900139000",
                                         "recipient_address": "北京市朝阳区",
                                         "items": [{"sku": "SKU-SMOKE-001", "qty": 2}],
                                     })
        assert r.status_code in (200, 201), r.text[:200]
        body = r.json()
        # order_id and items are required by CreateWaybillRequest; the older body
        # here named neither, so the request was refused before reaching the
        # carrier and the waybill half of the smoke test tested nothing.
        assert body.get("carrier_code") == "sf", r.text[:200]
        assert body.get("items"), r.text[:200]
        tracking = body.get("tracking_number") or body.get("data", {}).get("tracking_number")
        if tracking:
            pytest.STATE["tracking"] = tracking

    async def test_logistics_tracking(self, async_client: AsyncClient, auth_header: dict):
        tracking = pytest.STATE.get("tracking")
        if not tracking:
            pytest.skip("无运单号")
        r = await async_client.get(f"{P}/logistics/waybill/{tracking}", headers=auth_header)
        assert r.status_code == 200, r.text[:200]


# 初始化类级 state
pytest.STATE = {}
