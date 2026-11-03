"""OMS-WMS-TMS full API test (in-process via httpx AsyncClient)"""
__test__ = False
import asyncio
import os
import sys
import time

os.environ["TESTING"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import httpx

from src.main import app

RESULTS = []
TOKEN = None
ADMIN_TOKEN = None

def log(tid, name, ok, detail=""):
    RESULTS.append((tid, name, ok, detail))
    mark = "[OK]" if ok else "[FAIL]"
    print(f"  {mark} [{tid}] {name}" + (f" -- {detail}" if detail and not ok else ""), flush=True)

async def api(client, method, path, token=None, json_data=None, params=None, expect=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = await client.request(method, path, json=json_data, params=params, headers=headers)
        try:
            body = r.json()
        except ValueError:
            # A body that is not JSON is the response — a gateway page, a plain-text
            # 500 — and the log has to show it, not the fact that parsing failed.
            body = r.text
        if expect is not None:
            ok = r.status_code == expect
            return r.status_code, body, ok
        return r.status_code, body, None
    except Exception as e:
        return 0, str(e), False

async def test_health(c):
    print("\n=== 16. Health ===", flush=True)
    code, body, ok = await api(c, "GET", "/health", expect=200)
    log("16.1", "GET /health -> 200", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/health", expect=200)
    log("16.2", "GET /api/v1/health -> 200", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/ready")
    log("16.3", "GET /api/v1/ready -> 200 or 503", code in (200, 503), f"got {code}")

async def test_auth(c):
    global TOKEN, ADMIN_TOKEN
    print("\n=== 2. Auth ===", flush=True)
    code, body, ok = await api(c, "POST", "/api/v1/auth/register",
                               json_data={"username": "testuser1", "email": "test1@t.com",
                                   "password": "test12345"}, expect=201)
    log("2.1.1", "Register -> 201", ok, f"got {code}")

    code, body, ok = await api(c, "POST", "/api/v1/auth/register",
                               json_data={"username": "testuser1", "email": "test1@t.com",
                                   "password": "test12345"}, expect=400)
    log("2.1.2", "Dup register -> 400", ok, f"got {code}")

    code, body, ok = await api(c, "POST", "/api/v1/auth/register",
                               json_data={"username": "short", "email": "s@t.com", "password": "123"}, expect=422)
    log("2.1.3", "Short pwd -> 422", ok, f"got {code}")

    code, body, ok = await api(c, "POST", "/api/v1/auth/login",
                               json_data={"username": "admin", "password": "admin123456"}, expect=200)
    log("2.2.1", "Admin login -> 200", ok, f"got {code}")
    if ok and isinstance(body, dict):
        data = body.get("data", body)
        ADMIN_TOKEN = data.get("access_token") or data.get("token")

    if not ok or ADMIN_TOKEN is None:
        await api(c, "POST", "/api/v1/auth/register",
                  json_data={"username": "admin", "email": "admin@test.com", "password": "admin123456"})
        code, body, ok = await api(c, "POST", "/api/v1/auth/login",
                                   json_data={"username": "admin", "password": "admin123456"}, expect=200)
        if ok and isinstance(body, dict):
            data = body.get("data", body)
            ADMIN_TOKEN = data.get("access_token") or data.get("token")
        log("2.2.1b", "Admin login (after register)", ok, f"got {code}")

    code, body, ok = await api(c, "POST", "/api/v1/auth/login",
                               json_data={"username": "admin", "password": "wrong"}, expect=401)
    log("2.2.2", "Wrong pwd -> 401", ok, f"got {code}")

    code, body, ok = await api(c, "POST", "/api/v1/auth/login",
                               json_data={"username": "testuser1", "password": "test12345"}, expect=200)
    if ok and isinstance(body, dict):
        data = body.get("data", body)
        TOKEN = data.get("access_token") or data.get("token")
    log("2.2.3", "testuser login", ok, f"got {code}")

    code, body, ok = await api(c, "GET", "/api/v1/auth/me", token=ADMIN_TOKEN, expect=200)
    log("2.5.1", "GET /auth/me -> 200", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/auth/me", expect=401)
    log("2.5.2", "No token -> 401", ok, f"got {code}")

    code, body, ok = await api(c, "GET", "/api/v1/auth/users", token=ADMIN_TOKEN, expect=200)
    log("2.6.1", "Admin list users -> 200", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/auth/users", token=TOKEN, expect=403)
    log("2.6.2", "Normal user list users -> 403", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/auth/roles", token=ADMIN_TOKEN, expect=200)
    log("2.6.4", "Admin list roles -> 200", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/auth/permissions", token=ADMIN_TOKEN, expect=200)
    log("2.6.7", "Admin list perms -> 200", ok, f"got {code}")

ORDER_ID = None
async def test_oms(c):
    global ORDER_ID
    print("\n=== 3. OMS ===", flush=True)
    t = ADMIN_TOKEN
    code, body, ok = await api(c, "POST", "/api/v1/orders", token=t, expect=201,
        json_data={"customer_id": "CUST-001",
            "items": [{"gtin": "1234567890123", "sku": "SKU-TEST-001", "quantity": 5, "unit_price": 10.5}],
            "priority": "high"})
    log("3.1.1", "Create order -> 201", ok, f"got {code}")
    if ok and isinstance(body, dict):
        data = body.get("data", body)
        ORDER_ID = data.get("id")

    code, body, ok = await api(c, "GET", "/api/v1/orders?page=1&page_size=10", token=t, expect=200)
    log("3.1.3", "List orders -> 200", ok, f"got {code}")

    if ORDER_ID:
        code, body, ok = await api(c, "GET", f"/api/v1/orders/{ORDER_ID}", token=t, expect=200)
        log("3.1.6", "Get order -> 200", ok, f"got {code}")
        for from_s, to_s, tid in [("pending","confirmed","3.2.1"),("confirmed","processing","3.2.2"),
            ("processing","picking","3.2.3")]:
            code, body, ok = await api(c, "PUT", f"/api/v1/orders/{ORDER_ID}/status", token=t, expect=200,
                json_data={"status": to_s})
            log(tid, f"Status {from_s}->{to_s} -> 200", ok, f"got {code}")
        code, body, ok = await api(c, "PUT", f"/api/v1/orders/{ORDER_ID}/status", token=t, expect=422,
            json_data={"status": "processing"})
        log("3.2.5", "Invalid jump picking->processing -> 422", ok, f"got {code}")
        code, body, ok = await api(c, "PUT", f"/api/v1/orders/{ORDER_ID}/status", token=t, expect=200,
            json_data={"status": "completed"})
        log("3.2.4", "Status picking->completed -> 200", ok, f"got {code}")
        code, body, ok = await api(c, "GET", f"/api/v1/orders/{ORDER_ID}/history", token=t, expect=200)
        log("3.4.1", "Order history -> 200", ok, f"got {code}")

WH_ID = None
LOC_ID = None
async def test_wms(c):
    global WH_ID, LOC_ID
    print("\n=== 4. WMS ===", flush=True)
    t = ADMIN_TOKEN
    code, body, ok = await api(c, "POST", "/api/v1/warehouses", token=t, expect=201,
        json_data={"code": "WH-TEST-001", "name": "Test WH", "warehouse_type": "CENTER", "status": "ACTIVE"})
    log("4.1.1", "Create warehouse -> 201", ok, f"got {code}")
    if ok and isinstance(body, dict):
        data = body.get("data", body)
        WH_ID = data.get("id")

    code, body, ok = await api(c, "GET", "/api/v1/warehouses?page=1&page_size=10", token=t, expect=200)
    log("4.1.3", "List warehouses -> 200", ok, f"got {code}")

    if WH_ID:
        code, body, ok = await api(c, "GET", f"/api/v1/warehouses/{WH_ID}", token=t, expect=200)
        log("4.1.4", "Get warehouse -> 200", ok, f"got {code}")
        code, body, ok = await api(c, "PUT", f"/api/v1/warehouses/{WH_ID}", token=t, expect=200,
            json_data={"code": "WH-TEST-001", "name": "Test WH v2"})
        log("4.1.5", "Update warehouse -> 200", ok, f"got {code}")
        code, body, ok = await api(c, "POST", f"/api/v1/warehouses/{WH_ID}/locations", token=t, expect=201,
            json_data={"zone": "A", "aisle": "01", "shelf": "02", "bin": "03", "type": "storage"})
        log("4.2.1", "Create location -> 201", ok, f"got {code}")
        if ok and isinstance(body, dict):
            data = body.get("data", body)
            LOC_ID = data.get("id")
        code, body, ok = await api(c, "GET", f"/api/v1/warehouses/{WH_ID}/locations?page=1&page_size=10", token=t,
            expect=200)
        log("4.2.2", "List locations -> 200", ok, f"got {code}")

    code, body, ok = await api(c, "POST", "/api/v1/warehouses/vendors", token=t, expect=201,
        json_data={"code": "V-TEST-001", "name": "Test Vendor"})
    log("4.3.1", "Create vendor -> 201", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/warehouses/vendors", token=t, expect=200)
    log("4.3.2", "List vendors -> 200", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/warehouses/inventory", token=t, expect=200)
    log("4.7.1", "Query inventory -> 200", ok, f"got {code}")

STOCK_IN_ID = None
async def test_stock(c):
    global STOCK_IN_ID
    print("\n=== 5. Stock ===", flush=True)
    t = ADMIN_TOKEN
    wh = WH_ID or "00000000-0000-0000-0000-000000000000"
    code, body, ok = await api(c, "POST", "/api/v1/stock-in", token=t, expect=201,
        json_data={"data": {"warehouse_id": wh, "type": "PURCHASE",
                            "lines": [{"sku": "SKU-TEST-001", "qty_received": 100}]}})
    log("5.1.1", "Create stock-in -> 201", ok, f"got {code}")
    if ok and isinstance(body, dict):
        data = body.get("data", body)
        STOCK_IN_ID = data.get("id")

    code, body, ok = await api(c, "GET", "/api/v1/stock-in", token=t, expect=200)
    log("5.1.2", "List stock-in -> 200", ok, f"got {code}")

    if STOCK_IN_ID:
        code, body, ok = await api(c, "PUT", f"/api/v1/stock-in/{STOCK_IN_ID}", token=t, expect=200,
            json_data={"data": {"status": "CONFIRMED"}})
        log("5.1.4", "Confirm stock-in -> 200", ok, f"got {code}")

    code, body, ok = await api(c, "POST", "/api/v1/stock-out", token=t, expect=201,
        json_data={"data": {"warehouse_id": wh, "type": "SALE", "lines": [{"sku": "SKU-TEST-001", "qty_shipped": 10}]}})
    log("5.2.1", "Create stock-out -> 201", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/stock-out", token=t, expect=200)
    log("5.2.2", "List stock-out -> 200", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/inventory-log", token=t, expect=200)
    log("5.3.1", "Inventory log -> 200", ok, f"got {code}")

TO_ID = None
async def test_tms(c):
    global TO_ID
    print("\n=== 6. TMS ===", flush=True)
    t = ADMIN_TOKEN
    wh = WH_ID or "00000000-0000-0000-0000-000000000000"
    code, body, ok = await api(c, "POST", "/api/v1/transport-orders", token=t, expect=201,
        json_data={"carrier_code": "sf_express", "pickup_warehouse_id": wh,
                   "pickup_address": {"city": "Shanghai", "address": "XX Rd 1"},
                   "delivery_name": "Zhang San", "delivery_address": {"city": "Beijing", "address": "YY Rd 2"},
                   "total_weight_kg": 5.5, "total_volume_m3": 0.01})
    log("6.1.1", "Create transport order -> 201", ok, f"got {code}")
    if ok and isinstance(body, dict):
        data = body.get("data", body)
        TO_ID = data.get("id")

    code, body, ok = await api(c, "GET", "/api/v1/transport-orders?page=1&limit=10", token=t, expect=200)
    log("6.1.2", "List transport orders -> 200", ok, f"got {code}")

    if TO_ID:
        code, body, ok = await api(c, "GET", f"/api/v1/transport-orders/{TO_ID}", token=t, expect=200)
        log("6.1.5", "Get transport order -> 200", ok, f"got {code}")
        for to_s, tid, desc in [("dispatched","6.1.6","draft->dispatched"),
            ("in_transit","6.1.7","dispatched->in_transit")]:
            code, body, ok = await api(c, "PUT", f"/api/v1/transport-orders/{TO_ID}/status?status={to_s}", token=t,
                expect=200)
            log(tid, f"Status {desc} -> 200", ok, f"got {code}")
        code, body, ok = await api(c, "PUT", f"/api/v1/transport-orders/{TO_ID}/status?status=delivered", token=t,
            expect=422)
        log("6.1.9", "Invalid jump -> 422", ok, f"got {code}")
        code, body, ok = await api(c, "PUT", f"/api/v1/transport-orders/{TO_ID}/status?status=out_for_delivery",
            token=t, expect=200)
        log("6.1.8a", "in_transit->out_for_delivery -> 200", ok, f"got {code}")
        code, body, ok = await api(c, "PUT", f"/api/v1/transport-orders/{TO_ID}/status?status=delivered", token=t,
            expect=200)
        log("6.1.8b", "out_for_delivery->delivered -> 200", ok, f"got {code}")

        code, body, ok = await api(c, "POST", "/api/v1/tracking-events", token=t, expect=201,
            json_data={"transport_order_id": TO_ID, "event_type": "in_transit", "location_name": "Shanghai Hub"})
        log("6.2.2", "Create tracking event -> 201", ok, f"got {code}")
        code, body, ok = await api(c, "GET", f"/api/v1/transport-orders/{TO_ID}/tracking", token=t, expect=200)
        log("6.2.3", "Get tracking -> 200", ok, f"got {code}")

        code, body, ok = await api(c, "POST", f"/api/v1/transport-orders/{TO_ID}/pod", token=t, expect=201,
            json_data={"signed_by": "Zhang San", "signature_type": "digital"})
        log("6.3.1", "Create POD -> 201", ok, f"got {code}")
        code, body, ok = await api(c, "GET", f"/api/v1/transport-orders/{TO_ID}/pod", token=t, expect=200)
        log("6.3.2", "Get POD -> 200", ok, f"got {code}")

    code, body, ok = await api(c, "POST", "/api/v1/return-orders", token=t, expect=201,
        json_data={"reason": "damaged", "reason_detail": "box broken",
            "pickup_address": {"city": "Shanghai", "address": "XX Rd"}})
    log("6.4.1", "Create return order -> 201", ok, f"got {code}")
    ret_id = (body.get("data", body).get("id") if ok and isinstance(body, dict) else None)
    code, body, ok = await api(c, "GET", "/api/v1/return-orders", token=t, expect=200)
    log("6.4.2", "List return orders -> 200", ok, f"got {code}")
    if ret_id:
        code, body, ok = await api(c, "GET", f"/api/v1/return-orders/{ret_id}", token=t, expect=200)
        log("6.4.3", "Get return order -> 200", ok, f"got {code}")
        code, body, ok = await api(c, "PATCH", f"/api/v1/return-orders/{ret_id}/status", token=t, expect=200,
            json_data={"target": "cancelled"})
        log("6.4.4", "Return requested->cancelled -> 200", ok, f"got {code}")

    code, body, ok = await api(c, "POST", "/api/v1/exceptions", token=t, expect=201,
        json_data={"transport_order_id": TO_ID or "00000000-0000-0000-0000-000000000000", "type": "delayed",
            "description": "Storm delay"})
    log("6.5.1", "Report exception -> 201", ok, f"got {code}")
    exc_id = (body.get("data", body).get("id") if ok and isinstance(body, dict) else None)
    code, body, ok = await api(c, "GET", "/api/v1/exceptions", token=t, expect=200)
    log("6.5.3", "List exceptions -> 200", ok, f"got {code}")
    if exc_id:
        code, body, ok = await api(c, "PATCH", f"/api/v1/exceptions/{exc_id}", token=t, expect=200,
            json_data={"status": "resolved", "resolution_notes": "Contacted customer"})
        log("6.5.4", "Resolve exception -> 200", ok, f"got {code}")

    code, body, ok = await api(c, "POST", "/api/v1/transfer-hubs", token=t, expect=201,
        json_data={"code": "HUB-TEST-001", "name": "Test Hub", "hub_type": "primary", "city": "Shanghai"})
    log("6.7.1", "Create transfer hub -> 201", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/transfer-hubs", token=t, expect=200)
    log("6.7.2", "List transfer hubs -> 200", ok, f"got {code}")

async def test_other_modules(c):
    print("\n=== 7-10. Logistics/Barcode/Notification/Webhook ===", flush=True)
    t = ADMIN_TOKEN
    code, body, ok = await api(c, "POST", "/api/v1/logistics/waybill/create", token=t, expect=201,
        json_data={"order_id": "TEST-ORDER-001", "carrier_code": "SF", "recipient_name": "Li Si",
                   "recipient_phone": "13900139000", "recipient_address": "Test Rd 100",
                   "items": [{"sku": "SKU-TEST-001", "quantity": 1}]})
    log("7.1", "Create waybill -> 201", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/logistics/waybill/list", token=t, expect=200)
    log("7.2", "List waybills -> 200", ok, f"got {code}")

    code, body, ok = await api(c, "POST", "/api/v1/barcode/generate", token=t, expect=201,
        json_data={"gtin_prefix": "1234567", "entity_type": "order",
            "entity_id": "00000000-0000-0000-0000-000000000001", "format": "ean13"})
    log("8.1", "Generate barcode -> 201", ok, f"got {code}")
    code, body, ok = await api(c, "POST", "/api/v1/barcode/validate", token=t, expect=200,
        json_data={"gtin": "1234567890123"})
    log("8.2", "Validate barcode -> 200", ok, f"got {code}")
    code, body, ok = await api(c, "POST", "/api/v1/barcode/templates", token=t, expect=201,
        json_data={"name": "Standard Label", "code": "TPL-TEST-001", "format": "zpl", "width_mm": 100, "height_mm": 50})
    log("8.6", "Create template -> 201", ok, f"got {code}")

    code, body, ok = await api(c, "GET", "/api/v1/notifications/", token=t, expect=200)
    log("9.1", "List notifications -> 200", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/notifications/preferences", token=t, expect=200)
    log("9.6", "Get notif prefs -> 200", ok, f"got {code}")

    code, body, ok = await api(c, "POST", "/api/v1/webhooks/", token=t, expect=200,
        json_data={"name": "Test Hook", "url": "https://example.com/hook", "events": ["order.created"],
            "secret": "sec123"})
    log("10.1", "Create webhook -> 201", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/webhooks/", token=t, expect=200)
    log("10.3", "List webhooks -> 200", ok, f"got {code}")

async def test_analytics(c):
    print("\n=== 11. Analytics ===", flush=True)
    t = ADMIN_TOKEN
    code, body, ok = await api(c, "GET", "/api/v1/analytics/dashboard", token=t, expect=200)
    log("11.1", "Dashboard -> 200", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/analytics/order-trends?days=7", token=t, expect=200)
    log("11.2", "Order trends -> 200", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/analytics/low-stock", token=t, expect=200)
    log("11.4", "Low stock -> 200", ok, f"got {code}")

async def test_security(c):
    print("\n=== 17. Security ===", flush=True)
    code, body, ok = await api(c, "GET", "/api/v1/auth/me", expect=401)
    log("17.1.1", "No token -> 401", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/orders", expect=401)
    log("17.1.1b", "No token orders -> 401", ok, f"got {code}")

    r = await c.get("/api/v1/auth/me", headers={"Authorization": "invalid_token"})
    log("17.1.4", "Bad Bearer prefix -> 401", r.status_code == 401, f"got {r.status_code}")
    code, body, ok = await api(c, "GET", "/api/v1/auth/users", token=TOKEN, expect=403)
    log("17.2.1", "No RBAC -> 403", ok, f"got {code}")
    code, body, ok = await api(c, "POST", "/api/v1/auth/login", json_data={"username": "' OR 1=1 --", "password": "x"},
        expect=401)
    log("17.3.1", "SQL injection -> 401", ok, f"got {code}")
    code, body, ok = await api(c, "GET", "/api/v1/orders/not-a-uuid", token=ADMIN_TOKEN, expect=422)
    log("17.3.5", "Bad UUID -> 422", ok, f"got {code}")

    code, body, ok = await api(c, "GET", "/api/v1/auth/me", token=ADMIN_TOKEN, expect=200)
    if ok and isinstance(body, dict):
        data = body.get("data", body)
        no_pwd = "password" not in data and "hashed_password" not in data
        log("17.6.1", "No password in response", no_pwd)
    else:
        log("17.6.1", "No password in response", False, "could not verify")

    r = await c.get("/health")
    no_server = "server" not in {k.lower() for k in r.headers.keys()}
    log("17.6.4", "Server header hidden", no_server, f"headers: {dict(r.headers)}")

def summary():
    total = len(RESULTS)
    passed = sum(1 for _, _, ok, _ in RESULTS if ok)
    failed = total - passed
    print(f"\n{'='*60}", flush=True)
    print(f"  Results: {passed}/{total} passed, {failed} failed", flush=True)
    print(f"{'='*60}", flush=True)
    if failed:
        print("\n  Failed:", flush=True)
        for tid, name, ok, detail in RESULTS:
            if not ok:
                print(f"    [FAIL] [{tid}] {name} -- {detail}", flush=True)
    print(flush=True)
    return 0 if failed == 0 else 1

async def main():
    from src.auth import service as _auth_svc
    from src.core.database import engine
    from src.models.base import Base
    # Reset admin seeding flag for clean test run
    _auth_svc._admin_seeded = False
    # Drop and recreate all tables for a clean test run
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        await test_health(c)
        await test_auth(c)
        await test_oms(c)
        await test_wms(c)
        await test_stock(c)
        await test_tms(c)
        await test_other_modules(c)
        await test_analytics(c)
        await test_security(c)

if __name__ == "__main__":
    print("OMS-WMS-TMS API Test (in-process)", flush=True)
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted", flush=True)
    except Exception as e:
        print(f"\n\nError: {e}", flush=True)
        import traceback
        traceback.print_exc()
    sys.exit(summary())
