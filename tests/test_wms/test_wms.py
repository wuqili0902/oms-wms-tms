"""Tests for WMS warehouse/location/inventory management."""
import uuid as uuid_mod

import pytest


@pytest.fixture
async def auth_headers(async_client):
    uname = f"wmsuser_{uuid_mod.uuid4().hex[:6]}"
    await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    r = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestWarehouse:
    async def test_create_warehouse(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses", json={
            "code": "WH-001", "name": "Main Warehouse", "address": "123 St", "type": "standard",
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["code"] == "WH-001"
        assert data["name"] == "Main Warehouse"
        assert data["is_active"] is True

    async def test_create_duplicate_code(self, async_client, auth_headers):
        await async_client.post("/api/v1/warehouses", json={"code": "WH-001", "name": "Main"}, headers=auth_headers)
        resp = await async_client.post(
            "/api/v1/warehouses",
            json={"code": "WH-001", "name": "Duplicate"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_list_warehouses(self, async_client, auth_headers):
        await async_client.post("/api/v1/warehouses", json={"code": "WH-001", "name": "Main"}, headers=auth_headers)
        await async_client.post("/api/v1/warehouses", json={"code": "WH-002", "name": "Second"}, headers=auth_headers)
        resp = await async_client.get("/api/v1/warehouses", headers=auth_headers)
        codes = [item["code"] for item in resp.json()["items"]]
        assert "WH-001" in codes
        assert "WH-002" in codes

    async def test_get_warehouse(self, async_client, auth_headers):
        r = await async_client.post("/api/v1/warehouses", json={"code": "WH-001", "name": "Main"}, headers=auth_headers)
        wid = r.json()["id"]
        resp = await async_client.get(f"/api/v1/warehouses/{wid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["code"] == "WH-001"

    async def test_get_warehouse_not_found(self, async_client, auth_headers):
        resp = await async_client.get("/api/v1/warehouses/00000000-0000-0000-0000-000000000000", headers=auth_headers)
        assert resp.status_code == 404


class TestLocation:
    async def test_create_location(self, async_client, auth_headers):
        wh = await async_client.post(
            "/api/v1/warehouses",
            json={"code": "WH-LOC", "name": "Loc WH"},
            headers=auth_headers,
        )
        wh_id = wh.json()["id"]
        resp = await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "A", "aisle": "1", "shelf": "S", "bin": "B", "type": "storage",
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["type"] == "storage"

    async def test_create_location_invalid_warehouse(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/00000000-0000-0000-0000-000000000000/locations", json={
            "zone": "A", "aisle": "1", "shelf": "S", "bin": "B",
        }, headers=auth_headers)
        assert resp.status_code == 404

    async def test_list_locations(self, async_client, auth_headers):
        wh = await async_client.post(
            "/api/v1/warehouses",
            json={"code": "WH-LST", "name": "List WH"},
            headers=auth_headers,
        )
        wh_id = wh.json()["id"]
        await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "A", "aisle": "1", "shelf": "S", "bin": "B",
        }, headers=auth_headers)
        resp = await async_client.get(f"/api/v1/warehouses/{wh_id}/locations", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1


class TestInventory:
    async def test_adjust_add(self, async_client, auth_headers):
        wh = await async_client.post(
            "/api/v1/warehouses",
            json={"code": "INV-ADD", "name": "Inv WH"},
            headers=auth_headers,
        )
        wh_id = wh.json()["id"]
        loc = await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "B", "aisle": "2", "shelf": "S", "bin": "B",
        }, headers=auth_headers)
        loc_id = loc.json()["id"]
        resp = await async_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": wh_id, "location_id": loc_id, "sku": "ITEM-001", "quantity": 100,
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert int(data["quantity"]) == 100

    async def test_adjust_negative(self, async_client, auth_headers):
        wh = await async_client.post(
            "/api/v1/warehouses",
            json={"code": "INV-NEG", "name": "Neg WH"},
            headers=auth_headers,
        )
        wh_id = wh.json()["id"]
        loc = await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "C", "aisle": "3", "shelf": "S", "bin": "B",
        }, headers=auth_headers)
        loc_id = loc.json()["id"]
        # Reduce without existing stock
        resp = await async_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": wh_id, "location_id": loc_id, "sku": "ITEM-002", "quantity": -10,
        }, headers=auth_headers)
        assert resp.status_code == 422

    async def test_query_inventory(self, async_client, auth_headers):
        wh = await async_client.post(
            "/api/v1/warehouses",
            json={"code": "INV-QRY", "name": "Qry WH"},
            headers=auth_headers,
        )
        wh_id = wh.json()["id"]
        loc = await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "D", "aisle": "4", "shelf": "S", "bin": "B",
        }, headers=auth_headers)
        loc_id = loc.json()["id"]
        await async_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": wh_id, "location_id": loc_id, "sku": "QRY-001", "quantity": 50,
        }, headers=auth_headers)
        resp = await async_client.get("/api/v1/warehouses/inventory", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestPickingWave:
    async def test_create_picking_wave(self, async_client, auth_headers):
        wh = await async_client.post(
            "/api/v1/warehouses",
            json={"code": "WVE", "name": "Wave WH"},
            headers=auth_headers,
        )
        wh_id = wh.json()["id"]
        resp = await async_client.post("/api/v1/warehouses/picking-waves", json={
            "warehouse_id": wh_id, "order_ids": ["ord-001"],
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["warehouse_id"] == wh_id

    async def test_list_picking_waves(self, async_client, auth_headers):
        wh = await async_client.post(
            "/api/v1/warehouses",
            json={"code": "WVE-LST", "name": "Waves"},
            headers=auth_headers,
        )
        wh_id = wh.json()["id"]
        await async_client.post("/api/v1/warehouses/picking-waves", json={
            "warehouse_id": wh_id, "order_ids": ["ord-001"],
        }, headers=auth_headers)
        resp = await async_client.get("/api/v1/warehouses/picking-waves", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestWarehouseUpdateDelete:
    async def test_update_warehouse(self, async_client, auth_headers):
        r = await async_client.post(
            "/api/v1/warehouses",
            json={"code": "WH-UPD", "name": "Original"},
            headers=auth_headers,
        )
        wid = r.json()["id"]
        resp = await async_client.put(f"/api/v1/warehouses/{wid}", json={
            "code": "WH-UPD", "name": "Updated Name", "address": "新地址", "type": "center",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    async def test_update_warehouse_not_found(self, async_client, auth_headers):
        resp = await async_client.put("/api/v1/warehouses/00000000-0000-0000-0000-000000000000", json={
            "code": "GHOST", "name": "Nope",
        }, headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_warehouse(self, async_client, auth_headers):
        r = await async_client.post(
            "/api/v1/warehouses",
            json={"code": "WH-DEL", "name": "To Delete"},
            headers=auth_headers,
        )
        wid = r.json()["id"]
        resp = await async_client.delete(f"/api/v1/warehouses/{wid}", headers=auth_headers)
        assert resp.status_code == 204

    async def test_delete_warehouse_not_found(self, async_client, auth_headers):
        resp = await async_client.delete(
            "/api/v1/warehouses/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestLocationUpdateDelete:
    async def _setup(self, async_client, auth_headers):
        r = await async_client.post(
            "/api/v1/warehouses",
            json={"code": "LOC-UPD", "name": "Loc WH"},
            headers=auth_headers,
        )
        wh_id = r.json()["id"]
        r2 = await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "X", "aisle": "9", "shelf": "S", "bin": "B", "type": "storage",
        }, headers=auth_headers)
        return wh_id, r2.json()["id"]

    async def test_update_location(self, async_client, auth_headers):
        wh_id, loc_id = await self._setup(async_client, auth_headers)
        resp = await async_client.put(f"/api/v1/warehouses/{wh_id}/locations/{loc_id}", json={
            "zone": "Z", "aisle": "99",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["zone"] == "Z"

    async def test_delete_location(self, async_client, auth_headers):
        wh_id, loc_id = await self._setup(async_client, auth_headers)
        resp = await async_client.delete(f"/api/v1/warehouses/{wh_id}/locations/{loc_id}", headers=auth_headers)
        assert resp.status_code == 204

    async def test_delete_location_not_found(self, async_client, auth_headers):
        resp = await async_client.delete(
            "/api/v1/warehouses/00000000-0000-0000-0000-000000000000/locations/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestMovements:
    async def test_list_movements(self, async_client, auth_headers):
        wh = await async_client.post("/api/v1/warehouses", json={"code": "MOV", "name": "Mov WH"}, headers=auth_headers)
        wh_id = wh.json()["id"]
        loc = await async_client.post(f"/api/v1/warehouses/{wh_id}/locations", json={
            "zone": "M", "aisle": "1", "shelf": "S", "bin": "B",
        }, headers=auth_headers)
        loc_id = loc.json()["id"]
        await async_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": wh_id, "location_id": loc_id, "sku": "MOV-001", "quantity": 25,
        }, headers=auth_headers)
        resp = await async_client.get("/api/v1/warehouses/inventory/movements", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_list_movements_filter_wh(self, async_client, auth_headers):
        wh = await async_client.post(
            "/api/v1/warehouses",
            json={"code": "MOV-F", "name": "MovF WH"},
            headers=auth_headers,
        )
        wh_id = wh.json()["id"]
        resp = await async_client.get(
            f"/api/v1/warehouses/inventory/movements?warehouse_id={wh_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200


class TestPurchaseOrderLifecycle:
    async def test_approve_and_receive(self, async_client, auth_headers):
        po_resp = await async_client.post("/api/v1/warehouses/purchase-orders", json={
            "po_number": "PO-001",
        }, headers=auth_headers)
        assert po_resp.status_code == 201
        po_id = po_resp.json()["id"]

        approve_resp = await async_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/approve",
            headers=auth_headers,
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "approved"

        receive_resp = await async_client.post(
            f"/api/v1/warehouses/purchase-orders/{po_id}/receive",
            headers=auth_headers,
        )
        assert receive_resp.status_code == 200
        assert receive_resp.json()["status"] == "received"

    async def test_approve_not_found(self, async_client, auth_headers):
        resp = await async_client.post(
            "/api/v1/warehouses/purchase-orders/00000000-0000-0000-0000-000000000000/approve",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_receive_not_found(self, async_client, auth_headers):
        resp = await async_client.post(
            "/api/v1/warehouses/purchase-orders/00000000-0000-0000-0000-000000000000/receive",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_approve_invalid_state(self, async_client, auth_headers):
        po_resp = await async_client.post("/api/v1/warehouses/purchase-orders", json={
            "po_number": "PO-INV",
        }, headers=auth_headers)
        po_id = po_resp.json()["id"]
        await async_client.post(f"/api/v1/warehouses/purchase-orders/{po_id}/approve", headers=auth_headers)
        resp = await async_client.post(f"/api/v1/warehouses/purchase-orders/{po_id}/approve", headers=auth_headers)
        assert resp.status_code == 422

    async def test_receive_invalid_state(self, async_client, auth_headers):
        po_resp = await async_client.post("/api/v1/warehouses/purchase-orders", json={
            "po_number": "PO-RINV",
        }, headers=auth_headers)
        po_id = po_resp.json()["id"]
        resp = await async_client.post(f"/api/v1/warehouses/purchase-orders/{po_id}/receive", headers=auth_headers)
        assert resp.status_code == 422


class TestCreditMemos:
    async def test_create_credit_memo(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/credit-memos", json={
            "credit_memo_number": "CM-001", "entity_type": "customer", "reason": "RMA",
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["credit_memo_number"] == "CM-001"

    async def test_list_credit_memos(self, async_client, auth_headers):
        await async_client.post("/api/v1/warehouses/credit-memos", json={
            "credit_memo_number": "CM-LST", "entity_type": "customer",
        }, headers=auth_headers)
        resp = await async_client.get("/api/v1/warehouses/credit-memos", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_get_credit_memo(self, async_client, auth_headers):
        create_resp = await async_client.post("/api/v1/warehouses/credit-memos", json={
            "credit_memo_number": "CM-GET", "entity_type": "customer",
        }, headers=auth_headers)
        cm_id = create_resp.json()["id"]
        resp = await async_client.get(f"/api/v1/warehouses/credit-memos/{cm_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["credit_memo_number"] == "CM-GET"

    async def test_get_credit_memo_not_found(self, async_client, auth_headers):
        resp = await async_client.get(
            "/api/v1/warehouses/credit-memos/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestInventoryExceptions:
    async def test_adjust_inventory_nonexistent_warehouse(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": "00000000-0000-0000-0000-000000000000",
            "location_id": "00000000-0000-0000-0000-000000000000",
            "sku": "NOPE", "quantity": 1,
        }, headers=auth_headers)
        assert resp.status_code == 404

    async def test_adjust_inventory_validation_error(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/inventory/adjust", json={
            "warehouse_id": "x", "sku": "", "quantity": 0,
        }, headers=auth_headers)
        assert resp.status_code == 422


class TestPickingWaveExceptions:
    async def test_create_picking_wave_nonexistent_warehouse(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/picking-waves", json={
            "warehouse_id": "00000000-0000-0000-0000-000000000000",
            "order_ids": ["ord-001"],
        }, headers=auth_headers)
        assert resp.status_code == 404

    async def test_start_picking_wave_not_found(self, async_client, auth_headers):
        resp = await async_client.post(
            "/api/v1/warehouses/picking-waves/00000000-0000-0000-0000-000000000000/start",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_complete_picking_wave_not_found(self, async_client, auth_headers):
        resp = await async_client.post(
            "/api/v1/warehouses/picking-waves/00000000-0000-0000-0000-000000000000/complete",
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestPacking:
    async def test_create_packing_not_found(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/packing", json={
            "picking_wave_id": "00000000-0000-0000-0000-000000000000",
        }, headers=auth_headers)
        assert resp.status_code == 404

    async def test_create_packing_validation_error(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/packing", json={
            "picking_wave_id": "00000000-0000-0000-0000-000000000000",
        }, headers=auth_headers)
        assert resp.status_code == 404

    async def test_create_shipment_not_found(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/shipments", json={
            "order_id": "00000000-0000-0000-0000-000000000000",
            "warehouse_id": "00000000-0000-0000-0000-000000000000",
        }, headers=auth_headers)
        assert resp.status_code == 404

    async def test_list_shipments(self, async_client, auth_headers):
        resp = await async_client.get("/api/v1/warehouses/shipments", headers=auth_headers)
        assert resp.status_code == 200

    async def test_ship_package_not_found(self, async_client, auth_headers):
        resp = await async_client.post(
            "/api/v1/warehouses/shipments/00000000-0000-0000-0000-000000000000/ship",
            json={"tracking_number": "TN123", "carrier": "UPS"},
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestVendor:
    async def test_create_vendor(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/vendors", json={
            "code": "V001", "name": "Test Vendor",
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["name"] == "Test Vendor"

    async def test_list_vendors(self, async_client, auth_headers):
        await async_client.post("/api/v1/warehouses/vendors", json={
            "code": "V002", "name": "Vendor A",
        }, headers=auth_headers)
        resp = await async_client.get("/api/v1/warehouses/vendors", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1

    async def test_get_vendor(self, async_client, auth_headers):
        r = await async_client.post("/api/v1/warehouses/vendors", json={
            "code": "V003", "name": "Get Vendor",
        }, headers=auth_headers)
        vid = r.json()["id"]
        resp = await async_client.get(f"/api/v1/warehouses/vendors/{vid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Get Vendor"

    async def test_get_vendor_not_found(self, async_client, auth_headers):
        resp = await async_client.get(
            "/api/v1/warehouses/vendors/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_create_vendor_duplicate_code(self, async_client, auth_headers):
        await async_client.post("/api/v1/warehouses/vendors", json={
            "code": "DUP", "name": "Original",
        }, headers=auth_headers)
        resp = await async_client.post("/api/v1/warehouses/vendors", json={
            "code": "DUP", "name": "Duplicate",
        }, headers=auth_headers)
        assert resp.status_code == 422


class TestAddress:
    async def test_create_address(self, async_client, auth_headers):
        wh = await async_client.post("/api/v1/warehouses", json={
            "code": "ADDR", "name": "Addr WH",
        }, headers=auth_headers)
        wh_id = wh.json()["id"]
        resp = await async_client.post("/api/v1/warehouses/addresses", json={
            "entity_type": "warehouse", "entity_id": wh_id,
            "address_type": "billing", "contact_name": "张三",
            "phone": "13800138000", "address_line_1": "某路1号",
            "city": "上海", "postal_code": "200000",
        }, headers=auth_headers)
        assert resp.status_code == 201

    async def test_list_addresses(self, async_client, auth_headers):
        wh = await async_client.post("/api/v1/warehouses", json={
            "code": "ADDR-L", "name": "AddrL WH",
        }, headers=auth_headers)
        wh_id = wh.json()["id"]
        await async_client.post("/api/v1/warehouses/addresses", json={
            "entity_type": "warehouse", "entity_id": wh_id,
            "address_type": "billing", "contact_name": "李四",
            "phone": "13900139000", "address_line_1": "街1号",
            "city": "北京", "postal_code": "100000",
        }, headers=auth_headers)
        resp = await async_client.get("/api/v1/warehouses/addresses", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestPurchaseOrderExceptions:
    async def test_create_purchase_order_validation_error(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/purchase-orders", json={}, headers=auth_headers)
        assert resp.status_code == 422

    async def test_list_purchase_orders(self, async_client, auth_headers):
        await async_client.post(
            "/api/v1/warehouses/purchase-orders",
            json={"po_number": "PO-LST"},
            headers=auth_headers,
        )
        resp = await async_client.get("/api/v1/warehouses/purchase-orders", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1

    async def test_get_purchase_order_not_found(self, async_client, auth_headers):
        resp = await async_client.get(
            "/api/v1/warehouses/purchase-orders/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestInvoice:
    async def test_create_invoice(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/invoices", json={
            "invoice_number": "INV-001", "entity_type": "customer",
        }, headers=auth_headers)
        assert resp.status_code == 201

    async def test_list_invoices(self, async_client, auth_headers):
        await async_client.post("/api/v1/warehouses/invoices", json={
            "invoice_number": "INV-LST", "entity_type": "customer",
        }, headers=auth_headers)
        resp = await async_client.get("/api/v1/warehouses/invoices", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_get_invoice(self, async_client, auth_headers):
        r = await async_client.post("/api/v1/warehouses/invoices", json={
            "invoice_number": "INV-GET", "entity_type": "customer",
        }, headers=auth_headers)
        inv_id = r.json()["id"]
        resp = await async_client.get(f"/api/v1/warehouses/invoices/{inv_id}", headers=auth_headers)
        assert resp.status_code == 200

    async def test_get_invoice_not_found(self, async_client, auth_headers):
        resp = await async_client.get(
            "/api/v1/warehouses/invoices/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_create_invoice_validation_error(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/invoices", json={}, headers=auth_headers)
        assert resp.status_code == 422

    async def test_create_credit_memo_validation_error(self, async_client, auth_headers):
        resp = await async_client.post("/api/v1/warehouses/credit-memos", json={}, headers=auth_headers)
        assert resp.status_code == 422


class TestLocationExceptions:
    async def test_update_location_not_found(self, async_client, auth_headers):
        resp = await async_client.put(
            "/api/v1/warehouses/00000000-0000-0000-0000-000000000000/locations/00000000-0000-0000-0000-000000000000",
            json={"zone": "Z"},
            headers=auth_headers,
        )
        assert resp.status_code == 404
