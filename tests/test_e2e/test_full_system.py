"""Comprehensive end‑to‑end system test.

Each module's test is one async function so that all steps share the
same DB session (``async_client`` fixture).  The outer transaction
is rolled back at teardown.

Usage:
    pytest tests/test_e2e/test_full_system.py -v --tb=short

NOTE: All REST routes are mounted under ``/api/v1`` in ``src/main.py``.
      The HTTPBearer dependency returns 401 (not 403) when a token is
      missing, and all protected endpoints require ``Bearer <token>``.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

P = "/api/v1"


@pytest.fixture
async def tokens(async_client) -> dict:
    """Register + login once, return access/refresh tokens."""
    # Ignore duplicate-registration error from concurrent tests
    await async_client.post(
        f"{P}/auth/register",
        json=dict(username="e2e_admin", email="admin@example.com", password="secret123"),
    )
    resp = await async_client.post(
        f"{P}/auth/login",
        json=dict(username="e2e_admin", password="secret123"),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def auth_header(tokens) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ══════════════════════════════════════════════════════════════════════════
# 1. AUTH — user life‑cycle & RBAC
# ══════════════════════════════════════════════════════════════════════════


class TestAuth:
    """Registration, login, token refresh, RBAC in one session."""

    async def test_auth_flow(self, async_client, auth_header, tokens):
        # ── Register duplicate → 400 ─────────────────────────────────────
        r = await async_client.post(
            f"{P}/auth/register",
            json=dict(username="e2e_admin", email="x@x.com", password="secret123"),
        )
        assert r.status_code == 400

        # ── Login bad password → 401 ─────────────────────────────────────
        r = await async_client.post(
            f"{P}/auth/login", json=dict(username="e2e_admin", password="wrong"),
        )
        assert r.status_code == 401

        # ── Get /me ──────────────────────────────────────────────────────
        r = await async_client.get(f"{P}/auth/me", headers=auth_header)
        assert r.status_code == 200
        assert r.json()["username"] == "e2e_admin"

        # ── List users ───────────────────────────────────────────────────
        r = await async_client.get(f"{P}/auth/users", headers=auth_header)
        assert r.status_code == 200
        assert any(u["username"] == "e2e_admin" for u in r.json())

        # ── Create role ──────────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/auth/roles",
            headers=auth_header,
            json=dict(name="Warehouse Manager", code="wh_manager", description="Ops mgr"),
        )
        assert r.status_code == 201
        assert r.json()["code"] == "wh_manager"

        # ── Duplicate role → 422 ─────────────────────────────────────────
        r = await async_client.post(
            f"{P}/auth/roles",
            headers=auth_header,
            json=dict(name="Another", code="wh_manager"),
        )
        assert r.status_code == 422

        # ── List roles ───────────────────────────────────────────────────
        r = await async_client.get(f"{P}/auth/roles", headers=auth_header)
        assert r.status_code == 200
        assert any(role["code"] == "wh_manager" for role in r.json())

        # ── List permissions ─────────────────────────────────────────────
        r = await async_client.get(f"{P}/auth/permissions", headers=auth_header)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

        # ── Refresh token ────────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/auth/refresh",
            json=dict(refresh_token=tokens["refresh_token"]),
        )
        assert r.status_code == 200
        new = r.json()
        assert "access_token" in new
        assert "refresh_token" in new

        # ── Refresh with bad token → 401 ─────────────────────────────────
        r = await async_client.post(
            f"{P}/auth/refresh", json=dict(refresh_token="garbage"),
        )
        assert r.status_code == 401

        # ── Logout ───────────────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/auth/logout",
            json=dict(refresh_token=new["refresh_token"]),
        )
        assert r.status_code == 200
        assert r.json()["message"] == "Logged out successfully"

        # ── Refresh after logout → 401 ───────────────────────────────────
        r = await async_client.post(
            f"{P}/auth/refresh", json=dict(refresh_token=new["refresh_token"]),
        )
        assert r.status_code == 401

    async def test_unauthenticated(self, async_client):
        """All protected endpoints reject requests without a token."""
        endpoints = [
            ("GET", f"{P}/auth/me"),
            ("GET", f"{P}/auth/users"),
            ("POST", f"{P}/auth/roles"),
            ("GET", f"{P}/auth/roles"),
            ("GET", f"{P}/auth/permissions"),
            ("GET", f"{P}/warehouses"),
            ("POST", f"{P}/warehouses"),
            ("GET", f"{P}/warehouses/inventory"),
            ("POST", f"{P}/warehouses/inventory/adjust"),
            ("GET", f"{P}/warehouses/picking-waves"),
            ("GET", f"{P}/devices"),
            ("POST", f"{P}/devices"),
            ("GET", f"{P}/barcode/templates"),
            ("POST", f"{P}/barcode/generate"),
            ("POST", f"{P}/barcode/validate"),
            ("POST", f"{P}/barcode/scan"),
            ("GET", f"{P}/orders"),
            ("POST", f"{P}/orders"),
        ]
        for method, path in endpoints:
            r = await async_client.request(method, path)
            assert r.status_code == 401, f"{method} {path} → {r.status_code}"


# ══════════════════════════════════════════════════════════════════════════
# 2. WMS — warehouse, location, inventory, picking
# ══════════════════════════════════════════════════════════════════════════


class TestWms:
    """Full WMS workflow: warehouse → location → inventory → picking."""

    async def test_wms_flow(self, async_client, auth_header):
        # ── Create warehouse ─────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/warehouses",
            headers=auth_header,
            json=dict(code="WH-E2E-01", name="E2E WH", address="123 Test Dr", type="center"),
        )
        assert r.status_code == 201, r.text
        wh = r.json()
        assert wh["code"] == "WH-E2E-01"
        assert wh["type"] == "center"
        wh_id = wh["id"]

        # ── List warehouses ──────────────────────────────────────────────
        r = await async_client.get(f"{P}/warehouses", headers=auth_header)
        assert r.status_code == 200
        assert any(w["id"] == wh_id for w in r.json())

        # ── Get warehouse ────────────────────────────────────────────────
        r = await async_client.get(f"{P}/warehouses/{wh_id}", headers=auth_header)
        assert r.status_code == 200
        assert r.json()["id"] == wh_id

        # ── Get warehouse 404 ────────────────────────────────────────────
        r = await async_client.get(
            f"{P}/warehouses/00000000-0000-0000-0000-000000000000",
            headers=auth_header,
        )
        assert r.status_code == 404

        # ── Create location ──────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/warehouses/{wh_id}/locations",
            headers=auth_header,
            json=dict(zone="A", aisle="01", shelf="02", bin="03", type="storage"),
        )
        assert r.status_code == 201, r.text
        loc = r.json()
        assert loc["warehouse_id"] == wh_id
        assert loc["zone"] == "A"
        loc_id = loc["id"]

        # ── List locations ───────────────────────────────────────────────
        r = await async_client.get(
            f"{P}/warehouses/{wh_id}/locations", headers=auth_header,
        )
        assert r.status_code == 200
        assert any(l["id"] == loc_id for l in r.json())

        # ── Adjust inventory (in) ────────────────────────────────────────
        r = await async_client.post(
            f"{P}/warehouses/inventory/adjust",
            headers=auth_header,
            json=dict(warehouse_id=wh_id, location_id=loc_id, sku="SKU-E2E-001", quantity=100, reason="stock in"),
        )
        assert r.status_code == 200, r.text
        inv = r.json()
        assert inv["sku"] == "SKU-E2E-001"
        assert inv["quantity"] == 100

        # ── Adjust inventory (out) ───────────────────────────────────────
        r = await async_client.post(
            f"{P}/warehouses/inventory/adjust",
            headers=auth_header,
            json=dict(warehouse_id=wh_id, location_id=loc_id, sku="SKU-E2E-001", quantity=-30, reason="pick"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["quantity"] == 70

        # ── Query inventory ──────────────────────────────────────────────
        r = await async_client.get(
            f"{P}/warehouses/inventory",
            headers=auth_header,
            params=dict(sku="SKU-E2E-001"),
        )
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        # available_qty = quantity - reserved_qty
        assert items[0]["available_qty"] == 70

        # ── List movements ───────────────────────────────────────────────
        r = await async_client.get(
            f"{P}/warehouses/inventory/movements",
            headers=auth_header,
            params=dict(warehouse_id=wh_id),
        )
        assert r.status_code == 200
        assert len(r.json()) >= 2  # 2 adjust calls

        # ── Create picking wave (needs a real order — test schema only) ──
        r = await async_client.post(
            f"{P}/warehouses/picking-waves",
            headers=auth_header,
            json=dict(warehouse_id=wh_id, order_ids=["order-001"]),
        )
        assert r.status_code in (201, 404), r.text

        # ── List picking waves ───────────────────────────────────────────
        r = await async_client.get(
            f"{P}/warehouses/picking-waves",
            headers=auth_header,
            params=dict(warehouse_id=wh_id),
        )
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# 3. TMS — device life‑cycle
# ══════════════════════════════════════════════════════════════════════════


class TestTms:
    """Device registration, heartbeat, sessions, sync logs."""

    async def test_tms_flow(self, async_client, auth_header):
        # ── Register device ──────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/devices",
            headers=auth_header,
            json=dict(
                code="PDA-E2E-001",
                name="Scanner Gun 1",
                device_type="pda",
                platform="android",
                os_version="14.0",
                app_version="2.1.0",
                warehouse_id=None,
                config=dict(scan_modes=["barcode", "qrcode"]),
            ),
        )
        assert r.status_code == 201, r.text
        dev = r.json()
        assert dev["code"] == "PDA-E2E-001"
        dev_id = dev["id"]

        # ── Get device ───────────────────────────────────────────────────
        r = await async_client.get(f"{P}/devices/{dev_id}", headers=auth_header)
        assert r.status_code == 200
        assert r.json()["id"] == dev_id

        # ── Get device 404 ───────────────────────────────────────────────
        r = await async_client.get(
            f"{P}/devices/00000000-0000-0000-0000-000000000000",
            headers=auth_header,
        )
        assert r.status_code == 404

        # ── List devices ─────────────────────────────────────────────────
        r = await async_client.get(f"{P}/devices", headers=auth_header)
        assert r.status_code == 200
        assert any(d["code"] == "PDA-E2E-001" for d in r.json())

        # ── List devices filtered ────────────────────────────────────────
        r = await async_client.get(
            f"{P}/devices", headers=auth_header, params=dict(device_type="pda"),
        )
        assert r.status_code == 200

        # ── Update device ────────────────────────────────────────────────
        r = await async_client.patch(
            f"{P}/devices/{dev_id}",
            headers=auth_header,
            json=dict(name="Scanner 1 (Updated)", app_version="2.2.0"),
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Scanner 1 (Updated)"

        # ── Heartbeat ────────────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/devices/{dev_id}/heartbeat", headers=auth_header,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "online"

        # ── Create session ───────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/devices/{dev_id}/sessions", headers=auth_header,
        )
        assert r.status_code == 201, r.text
        sess = r.json()
        assert sess["device_id"] == dev_id
        assert sess["logout_at"] is None
        sess_id = sess["id"]

        # ── List sessions ────────────────────────────────────────────────
        r = await async_client.get(
            f"{P}/devices/{dev_id}/sessions", headers=auth_header,
        )
        assert r.status_code == 200
        assert any(s["id"] == sess_id for s in r.json())

        # ── End session ──────────────────────────────────────────────────
        r = await async_client.delete(
            f"{P}/devices/{dev_id}/sessions/{sess_id}", headers=auth_header,
        )
        assert r.status_code == 200
        assert r.json()["session"]["logout_at"] is not None

        # ── Record sync ──────────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/devices/{dev_id}/sync",
            headers=auth_header,
            json=dict(sync_type="download", status="completed", records_count=42),
        )
        assert r.status_code == 201, r.text
        assert r.json()["device_id"] == dev_id

        # ── List sync logs ───────────────────────────────────────────────
        r = await async_client.get(
            f"{P}/devices/{dev_id}/sync", headers=auth_header,
        )
        assert r.status_code == 200
        assert any(l["records_count"] == 42 for l in r.json())


# ══════════════════════════════════════════════════════════════════════════
# 4. BARCODE — generation, scanning, templates
# ══════════════════════════════════════════════════════════════════════════


class TestBarcode:
    """Barcode / label-template workflows."""

    async def test_barcode_flow(self, async_client, auth_header):
        # ── Create template ──────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/barcode/templates",
            headers=auth_header,
            json=dict(
                name="Standard Pallet Label",
                code="PALLET-ZPL",
                format="zpl",
                width_mm=100,
                height_mm=75,
                content=dict(fields=["sku", "qty", "location"]),
                is_default=True,
            ),
        )
        assert r.status_code == 201, r.text
        tpl = r.json()
        assert tpl["code"] == "PALLET-ZPL"
        tpl_id = tpl["id"]

        # ── List templates ───────────────────────────────────────────────
        r = await async_client.get(f"{P}/barcode/templates", headers=auth_header)
        assert r.status_code == 200
        assert any(t["id"] == tpl_id for t in r.json())

        # ── Generate barcode ─────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/barcode/generate",
            headers=auth_header,
            json=dict(gtin_prefix="8901234567", entity_type="inventory", entity_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890", format="code128"),
        )
        assert r.status_code == 201, r.text
        bc = r.json()
        assert bc["entity_type"] == "inventory"
        assert bc["format"] == "code128"
        bc_id = bc["id"]

        # ── Validate barcode ─────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/barcode/validate",
            headers=auth_header,
            json=dict(gtin="8901234567890"),
        )
        assert r.status_code == 200
        assert "valid" in r.json() or "is_valid" in r.json()

        # ── Scan barcode ─────────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/barcode/scan",
            headers=auth_header,
            json=dict(raw_data="8901234567890", scanner_id=None, location_id=None),
        )
        assert r.status_code == 201, r.text
        assert r.json()["gtin"] == "8901234567890"

        # ── Get by GTIN ──────────────────────────────────────────────────
        r = await async_client.get(f"{P}/barcode/8901234567890", headers=auth_header)
        assert r.status_code == 200
        records = r.json()
        assert isinstance(records, list)
        assert len(records) >= 1


# ══════════════════════════════════════════════════════════════════════════
# 5. OMS — order life‑cycle
# ══════════════════════════════════════════════════════════════════════════


class TestOms:
    """Order creation, retrieval, status updates, history, deletion."""

    async def test_oms_flow(self, async_client, auth_header):
        # ── Create order ─────────────────────────────────────────────────
        r = await async_client.post(
            f"{P}/orders",
            headers=auth_header,
            json=dict(
                customer_id="CUST-E2E-001",
                priority="high",
                notes="Rush order — E2E test",
                items=[
                    dict(gtin="8901234567890", sku="SKU-E2E-001", product_name="Widget Pro", quantity=10, unit_price="29.99"),
                    dict(gtin="8901234567891", sku="SKU-E2E-002", product_name="Widget Lite", quantity=5, unit_price="14.99"),
                ],
            ),
        )
        assert r.status_code == 201, r.text
        order = r.json()
        assert order["customer_id"] == "CUST-E2E-001"
        assert order["priority"] == "high"
        assert order["status"] in ("draft", "confirmed")
        assert len(order["items"]) == 2
        order_id = order["id"]

        # ── Get order ────────────────────────────────────────────────────
        r = await async_client.get(f"{P}/orders/{order_id}", headers=auth_header)
        assert r.status_code == 200
        assert r.json()["id"] == order_id
        assert len(r.json()["items"]) == 2

        # ── Get order 404 ────────────────────────────────────────────────
        r = await async_client.get(
            f"{P}/orders/00000000-0000-0000-0000-000000000000",
            headers=auth_header,
        )
        assert r.status_code == 404

        # ── List orders ──────────────────────────────────────────────────
        r = await async_client.get(f"{P}/orders", headers=auth_header)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        assert body["page"] == 1

        # ── Update status: draft → confirmed → processing ────────────────
        for status in ("confirmed", "processing"):
            r = await async_client.put(
                f"{P}/orders/{order_id}/status",
                headers=auth_header,
                json=dict(status=status),
            )
            assert r.status_code == 200, f"{r.text} (status={status})"
            assert r.json()["status"] == status

        # ── Get order history ────────────────────────────────────────────
        r = await async_client.get(
            f"{P}/orders/{order_id}/history", headers=auth_header,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) >= 2  # draft→confirmed, confirmed→processing

        # ── Delete order ─────────────────────────────────────────────────
        r = await async_client.delete(f"{P}/orders/{order_id}", headers=auth_header)
        assert r.status_code == 204, r.text

        # ── Get deleted order → 404 ──────────────────────────────────────
        r = await async_client.get(f"{P}/orders/{order_id}", headers=auth_header)
        assert r.status_code == 404
