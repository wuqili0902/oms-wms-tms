"""End-to-end test for new WMS mobile endpoints."""
import httpx, json, uuid as _uuid

BASE = "http://localhost:8000"
AUTH_TOKEN = None

def req(method, path, **kwargs):
    url = f"{BASE}/api/v1{path}"
    headers = {"Content-Type": "application/json"}
    if kwargs.get("token"):
        global AUTH_TOKEN
        AUTH_TOKEN = kwargs["token"]
    # Always use the latest token from the global
    if AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {AUTH_TOKEN}"

    resp = httpx.request(method, url, json=kwargs.get("json"), headers=headers)
    print(f"{method} {path} -> {resp.status_code}")
    try:
        data = resp.json() if resp.content else None
        if resp.status_code >= 400 and isinstance(data, dict):
            print(f"  Error: {json.dumps(data, ensure_ascii=False)}")
        return data
    except Exception as e:
        print(f"  Response body: {resp.text[:500]}")
        return None

# Login to get token
r = req("POST", "/auth/login", json={"username": "e2etest", "password": "test123456"})
token = r.get("access_token") if isinstance(r, dict) else None
if not token:
    print(f"Login failed: {r}")
    exit(1)

print(f"\nToken obtained: {token[:30]}...")

# Use existing warehouse (WH-TEST01)
wh_id = "7b1277d7-cf88-436d-b454-f27aaca902ce"
code = "WH-E2E-001"

# Create location in the warehouse
loc_data = {"label": f"A-TEST-{_uuid.uuid4().hex[:8]}", "zone": "A", "aisle": "A1", "shelf": 1, "bin": 1}
loc = req("POST", f"/warehouses/{wh_id}/inventory/items", json=loc_data)
if loc is None or not isinstance(loc, dict):
    print(f"Location creation failed: {loc}")
    exit(1)
loc_id = loc.get("id")
print(f"Location: {loc_id}")

# Test 1: Stock count submit (POST /inventory/count/submit)
print("\n=== TEST 1: POST /inventory/count/submit ===")
r = req("POST", f"/warehouses/{wh_id}/inventory/count/submit", json={
    "source_warehouse_code": code,
    "target_location_id": loc_id,
    "count_results": [
        {"sku_code": "SKU-TEST-001", "actual_qty_count": 50},
        {"sku_code": "SKU-TEST-002", "actual_qty_count": 30}
    ]
})

# Test 2: GET transfers list
print("\n=== TEST 2: GET /warehouse/transfers ===")
r = req("GET", f"/warehouses/{wh_id}/warehouse/transfers?status=pending")

# Test 3: POST transfer order
print("\n=== TEST 3: POST /warehouse/transfers ===")
r = req("POST", f"/warehouses/{wh_id}/warehouse/transfers", json={
    "source_warehouse_code": code,
    "destination_warehouse_id": wh_id,
    "line_items": [
        {"sku_code": "SKU-TEST-001", "quantity": 10},
        {"sku_code": "SKU-TEST-002", "quantity": 5}
    ]
})

print("\n=== DONE ===")
