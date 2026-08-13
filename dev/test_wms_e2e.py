"""End-to-end test for new WMS mobile endpoints."""
import httpx, json, sys

BASE = "http://localhost:8000/api/v1/warehouses"
AUTH = {"Authorization": f"Bearer {sys.argv[1]}"} if len(sys.argv) > 1 else {}

def req(method: str, path: str, **kwargs):
    url = BASE + path
    headers = {"Content-Type": "application/json", **AUTH}
    resp = httpx.request(method, url, json=kwargs.get("json"), headers=headers)
    print(f"{method.upper()} {path} -> {resp.status_code}")
    if resp.status_code >= 400:
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
    return resp

# ── Create test warehouse ───────────────────────────────────────────────
print("\n=== Creating test data ===")
wh_resp = req("POST", "", code="WH-TEST01", name="Test Warehouse")
wh_id = wh_resp.json()["id"]
print(f"Warehouse: {wh_id}")

# Create a location in the warehouse
loc_resp = req("POST", f"/{wh_id}/locations", label="A-01", zone="A")
loc_id = loc_resp.json()["id"]
print(f"Location: {loc_id}")

# ── Test 1: POST /inventory/count/submit (stock count) ────────────────
print("\n=== TEST 1: Submit stock count ===")
count_data = {
    "source_warehouse_code": "WH-TEST01",
    "target_location_id": loc_id,
    "count_results": [
        {"sku_code": "SKU-001", "actual_qty_count": 50},
        {"sku_code": "SKU-002", "actual_qty_count": 30},
    ],
}
try:
    resp = req("POST", "/inventory/count/submit", json=count_data)
    print(f"Response: {resp.text}")
except Exception as e:
    print(f"FAIL: {e}")

# ── Test 2: GET /warehouse/transfers (list transfers) ─────────────────
print("\n=== TEST 2: List transfer orders ===")
try:
    resp = req("GET", "/warehouse/transfers?warehouse_id=1")
    print(f"Transfers: {resp.text}")
except Exception as e:
    print(f"FAIL: {e}")

# ── Test 3: POST /warehouse/transfers (create transfer order) ────────
print("\n=== TEST 3: Create transfer order ===")
transfer_data = {
    "source_warehouse_code": "WH-TEST01",
    "destination_warehouse_id": wh_id,
    "line_items": [
        {"sku_code": "SKU-001", "quantity": 25},
        {"sku_code": "SKU-002", "quantity": 15},
    ],
}
try:
    resp = req("POST", "/warehouse/transfers", json=transfer_data)
    print(f"Transfer order created: {resp.text}")
except Exception as e:
    print(f"FAIL: {e}")

print("\n=== DONE ===")
