"""Tests for WMS router endpoints (untested success paths).

Covers: transfers, stock count, stock-in, picking wave lifecycle,
packing, shipment creation, and shipment shipping.
"""
import uuid

import pytest


@pytest.fixture
async def auth_client(async_client):
    """Provide async_client with a valid auth token."""
    uname = f"wmstest_{uuid.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname,
        "email": f"{uname}@test.com",
        "password": "test123456",
    })
    r = await async_client.post(
        "/api/v1/auth/login",
        json={"username": uname, "password": "test123456"},
    )
    token = r.json()["access_token"]
    async_client.headers["Authorization"] = f"Bearer {token}"
    return async_client


async def _create_wh(client):
    """Helper: create a warehouse and return its ID."""
    resp = await client.post("/api/v1/warehouses", json={
        "code": f"WH-{uuid.uuid4().hex[:6]}",
        "name": "Test WH",
        "address": "123 Main St",
    })
    assert resp.status_code == 201
    return resp.json()["id"]


async def _create_order(client):
    """Helper: create an order through the API and return its ID.

    ``shipments.order_id`` is a NOT NULL foreign key into ``orders``, and the
    shipping tests used to invent those uuids: SQLite let the insert through,
    so the suite was creating shipments for orders that never existed, and
    PostgreSQL answers the same insert with an FK violation — a 500 on the
    发货 screen.  ``create_shipment`` now refuses an order it cannot find, so
    the tests bring a real one.
    """
    resp = await client.post("/api/v1/orders", json={
        "customer_id": f"C-{uuid.uuid4().hex[:8]}",
        "items": [{
            "gtin": "4006381333931",
            "sku": f"SKU-{uuid.uuid4().hex[:6]}",
            "quantity": 1,
            "unit_price": "10.00",
        }],
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_location(client, wh_id):
    """Helper: create a location and return its ID."""
    resp = await client.post(
        f"/api/v1/warehouses/{wh_id}/locations",
        json={
            "zone": "A", "aisle": "1",
            "shelf": "1", "bin": "1",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ══════════════════════════════════════════════════════════════════════════════
# Transfers
# ══════════════════════════════════════════════════════════════════════════════

class TestTransfers:
    """POST /transfers, GET /transfers."""

    @pytest.mark.asyncio
    async def test_create_transfer_order(self, auth_client):
        wh_id = await _create_wh(auth_client)
        src_id = await _create_wh(auth_client)
        resp = await auth_client.post("/api/v1/warehouses/transfers", json={
            "source_warehouse_id": src_id,
            "destination_warehouse_id": wh_id,
            "items": [{"sku": "SKU-T1", "quantity": 10}],
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["code"].startswith("TO-")
        assert body["status"] == "DRAFT"
        assert body["source_warehouse_id"] == src_id

    @pytest.mark.asyncio
    async def test_create_transfer_missing_target(self, auth_client):
        wh_id = await _create_wh(auth_client)
        resp = await auth_client.post("/api/v1/warehouses/transfers", json={
            "source_warehouse_id": wh_id,
            "items": [{"sku": "SKU-X", "quantity": 1}],
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_transfers(self, auth_client):
        wh_id = await _create_wh(auth_client)
        src_id = await _create_wh(auth_client)
        await auth_client.post("/api/v1/warehouses/transfers", json={
            "source_warehouse_id": src_id,
            "destination_warehouse_id": wh_id,
            "items": [{"sku": "SKU-LT1", "quantity": 5}],
        })
        resp = await auth_client.get("/api/v1/warehouses/transfers")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_list_transfers_by_warehouse(self, auth_client):
        wh_id = await _create_wh(auth_client)
        src_id = await _create_wh(auth_client)
        await auth_client.post("/api/v1/warehouses/transfers", json={
            "source_warehouse_id": src_id,
            "destination_warehouse_id": wh_id,
            "items": [{"sku": "SKU-LT2", "quantity": 3}],
        })
        resp = await auth_client.get(
            f"/api/v1/warehouses/transfers?warehouse_id={wh_id}"
        )
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# Stock Count / Inventory Adjustment
# ══════════════════════════════════════════════════════════════════════════════

class TestStockCount:
    """POST /inventory/count/submit and /inventory/adjust-stock-count."""

    @pytest.mark.asyncio
    async def test_submit_stock_count_success(self, auth_client):
        wh_id = await _create_wh(auth_client)
        loc_id = await _create_location(auth_client, wh_id)
        resp = await auth_client.post(
            "/api/v1/warehouses/inventory/count/submit",
            json={
                "warehouse_id": wh_id,
                "location_id": loc_id,
                "count_results": [
                    {"sku": "SKU-SC1", "actual_qty": 50},
                ],
            },
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_submit_stock_count_missing_warehouse(self, auth_client):
        resp = await auth_client.post(
            "/api/v1/warehouses/inventory/count/submit",
            json={"location_id": str(uuid.uuid4()), "count_results": []},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_stock_count_missing_location(self, auth_client):
        wh_id = await _create_wh(auth_client)
        resp = await auth_client.post(
            "/api/v1/warehouses/inventory/count/submit",
            json={
                "warehouse_id": wh_id,
                "count_results": [{"sku": "X", "counted_qty": 1}],
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_adjust_stock_count_mobile(self, auth_client):
        wh_id = await _create_wh(auth_client)
        loc_id = await _create_location(auth_client, wh_id)
        resp = await auth_client.post(
            "/api/v1/warehouses/inventory/adjust-stock-count",
            json={
                "warehouse_id": wh_id,
                "location_id": loc_id,
                "count_results": [{"sku": "SKU-ASC1", "actual_qty": 25}],
            },
        )
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# Stock In (via router)
# ══════════════════════════════════════════════════════════════════════════════

class TestStockInRouter:
    """POST /inventory/items."""

    @pytest.mark.asyncio
    async def test_stock_in_success(self, auth_client):
        wh_id = await _create_wh(auth_client)
        resp = await auth_client.post(
            f"/api/v1/warehouses/inventory/items?warehouse_id={wh_id}",
            json={"sku": "SKU-SI-R1", "quantity": 42, "batch_no": "B100"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["sku"] == "SKU-SI-R1"
        assert body["quantity"] == 42

    @pytest.mark.asyncio
    async def test_stock_in_warehouse_not_found(self, auth_client):
        fake_id = str(uuid.uuid4())
        resp = await auth_client.post(
            f"/api/v1/warehouses/inventory/items?warehouse_id={fake_id}",
            json={"sku": "SKU-X", "quantity": 1},
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Picking Wave Lifecycle
# ══════════════════════════════════════════════════════════════════════════════

class TestPickingWaveLifecycle:
    """POST /picking-waves, start, complete."""

    @pytest.mark.asyncio
    async def test_start_picking_wave(self, auth_client):
        wh_id = await _create_wh(auth_client)
        create_resp = await auth_client.post(
            "/api/v1/warehouses/picking-waves",
            json={
                "warehouse_id": wh_id,
                "order_ids": [str(uuid.uuid4())],
            },
        )
        assert create_resp.status_code == 201
        wave_id = create_resp.json()["id"]

        start_resp = await auth_client.post(
            f"/api/v1/warehouses/picking-waves/{wave_id}/start",
        )
        assert start_resp.status_code == 200
        assert start_resp.json()["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_complete_picking_wave(self, auth_client):
        wh_id = await _create_wh(auth_client)
        create_resp = await auth_client.post(
            "/api/v1/warehouses/picking-waves",
            json={
                "warehouse_id": wh_id,
                "order_ids": [str(uuid.uuid4())],
            },
        )
        wave_id = create_resp.json()["id"]

        await auth_client.post(
            f"/api/v1/warehouses/picking-waves/{wave_id}/start",
        )
        complete_resp = await auth_client.post(
            f"/api/v1/warehouses/picking-waves/{wave_id}/complete",
        )
        assert complete_resp.status_code == 200
        assert complete_resp.json()["status"] == "completed"

    @pytest.mark.asyncio
    async def test_start_nonexistent_wave(self, auth_client):
        fake_id = str(uuid.uuid4())
        resp = await auth_client.post(
            f"/api/v1/warehouses/picking-waves/{fake_id}/start",
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_complete_nonexistent_wave(self, auth_client):
        fake_id = str(uuid.uuid4())
        resp = await auth_client.post(
            f"/api/v1/warehouses/picking-waves/{fake_id}/complete",
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_complete_pending_wave_fails(self, auth_client):
        wh_id = await _create_wh(auth_client)
        create_resp = await auth_client.post(
            "/api/v1/warehouses/picking-waves",
            json={
                "warehouse_id": wh_id,
                "order_ids": [str(uuid.uuid4())],
            },
        )
        wave_id = create_resp.json()["id"]
        resp = await auth_client.post(
            f"/api/v1/warehouses/picking-waves/{wave_id}/complete",
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Packing
# ══════════════════════════════════════════════════════════════════════════════

class TestPacking:
    """POST /packing."""

    @pytest.mark.asyncio
    async def test_create_packing_success(self, auth_client):
        wh_id = await _create_wh(auth_client)
        create_resp = await auth_client.post(
            "/api/v1/warehouses/picking-waves",
            json={
                "warehouse_id": wh_id,
                "order_ids": [str(uuid.uuid4())],
            },
        )
        wave_id = create_resp.json()["id"]
        await auth_client.post(
            f"/api/v1/warehouses/picking-waves/{wave_id}/start",
        )
        await auth_client.post(
            f"/api/v1/warehouses/picking-waves/{wave_id}/complete",
        )

        resp = await auth_client.post("/api/v1/warehouses/packing", json={
            "picking_wave_id": wave_id,
            "packed_by": "operator-1",
            "box_count": 3,
            "notes": "Packed safely",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["box_count"] == 3
        assert body["packed_by"] == "operator-1"

    @pytest.mark.asyncio
    async def test_create_packing_wave_not_found(self, auth_client):
        fake_id = str(uuid.uuid4())
        resp = await auth_client.post("/api/v1/warehouses/packing", json={
            "picking_wave_id": fake_id,
        })
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_packing_wave_not_completed(self, auth_client):
        wh_id = await _create_wh(auth_client)
        create_resp = await auth_client.post(
            "/api/v1/warehouses/picking-waves",
            json={
                "warehouse_id": wh_id,
                "order_ids": [str(uuid.uuid4())],
            },
        )
        wave_id = create_resp.json()["id"]
        resp = await auth_client.post("/api/v1/warehouses/packing", json={
            "picking_wave_id": wave_id,
        })
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Shipping
# ══════════════════════════════════════════════════════════════════════════════

class TestShipping:
    """POST /shipments, POST /shipments/{id}/ship.

    The create endpoint answers ``{count, shipments}`` — the same shape for one
    order and for the list 新建发货单 posts — and every shipment carries the
    ``shipment_no`` the shipping list's first column asks for.
    """

    @pytest.mark.asyncio
    async def test_create_shipment(self, auth_client):
        wh_id = await _create_wh(auth_client)
        order_id = await _create_order(auth_client)
        resp = await auth_client.post("/api/v1/warehouses/shipments", json={
            "order_id": order_id,
            "warehouse_id": wh_id,
            "tracking_number": "SF1234567890",
            "carrier": "sf_express",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["count"] == 1
        shipment = body["shipments"][0]
        assert shipment["tracking_number"] == "SF1234567890"
        assert shipment["carrier"] == "sf_express"
        assert shipment["shipment_no"].startswith("SHIP-")

    @pytest.mark.asyncio
    async def test_create_shipment_warehouse_not_found(self, auth_client):
        resp = await auth_client.post("/api/v1/warehouses/shipments", json={
            "order_id": await _create_order(auth_client),
            "warehouse_id": str(uuid.uuid4()),
        })
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_ship_package(self, auth_client):
        wh_id = await _create_wh(auth_client)
        order_id = await _create_order(auth_client)
        create_resp = await auth_client.post(
            "/api/v1/warehouses/shipments",
            json={
                "order_id": order_id,
                "warehouse_id": wh_id,
            },
        )
        shipment_id = create_resp.json()["shipments"][0]["id"]

        resp = await auth_client.post(
            f"/api/v1/warehouses/shipments/{shipment_id}/ship",
            json={
                "tracking_number": "YT9876543210",
                "carrier": "yunda",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "shipped"
        assert body["tracking_number"] == "YT9876543210"

    @pytest.mark.asyncio
    async def test_ship_package_not_found(self, auth_client):
        fake_id = str(uuid.uuid4())
        resp = await auth_client.post(
            f"/api/v1/warehouses/shipments/{fake_id}/ship",
            json={},
        )
        assert resp.status_code == 404
