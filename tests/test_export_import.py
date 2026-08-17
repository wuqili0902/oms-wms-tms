import csv
import io
import uuid

import pytest

from src.core.export import export_inventory, export_orders, stream_csv
from src.core.import_utils import import_inventory_from_csv, import_orders_from_csv
from src.oms.models import Customer, Order, OrderStatus
from src.wms.models import SKU, Inventory, Warehouse


@pytest.mark.asyncio
async def test_stream_csv(sqlite_engine, db_session):
    rows = [{"col_a": "1", "col_b": "hello"}, {"col_a": "2", "col_b": "world"}]
    chunks = []
    async for chunk in stream_csv(rows, ["col_a", "col_b"]):
        chunks.append(chunk)
    content = b"".join(chunks).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    parsed = list(reader)
    assert len(parsed) == 2
    assert parsed[0]["col_a"] == "1"
    assert parsed[1]["col_b"] == "world"


@pytest.mark.asyncio
async def test_stream_csv_empty(sqlite_engine, db_session):
    chunks = []
    async for chunk in stream_csv([], ["a", "b"]):
        chunks.append(chunk)
    content = b"".join(chunks).decode("utf-8-sig")
    assert "a,b" in content


@pytest.mark.asyncio
async def test_export_orders(sqlite_engine, db_session):
    c = Customer(id=uuid.uuid4(), code="EXP01", name="Export")
    db_session.add(c)
    await db_session.flush()
    oid = uuid.uuid4()
    order_no = oid.hex[:12]
    o = Order(
        id=oid, order_no=order_no, status=OrderStatus.CONFIRMED,
        customer_id=c.id, items={}, total_amount=250,
    )
    db_session.add(o)
    await db_session.commit()

    rows = await export_orders(db_session)
    our = [r for r in rows if r["order_no"] == order_no]
    assert len(our) == 1
    assert our[0]["status"] == "confirmed"
    assert our[0]["total_amount"] == "250"


@pytest.mark.asyncio
async def test_export_inventory(sqlite_engine, db_session):
    sku = SKU(id=uuid.uuid4(), sku="EXSKU01", name="Export SKU")
    wh = Warehouse(id=uuid.uuid4(), code="EXWH01", name="Export WH")
    db_session.add_all([sku, wh])
    await db_session.flush()
    inv = Inventory(id=uuid.uuid4(), sku_id=sku.id, warehouse_id=wh.id, quantity=10, locked_qty=2, min_qty=1)
    db_session.add(inv)
    await db_session.commit()

    rows = await export_inventory(db_session)
    our = [r for r in rows if r["sku_id"] == str(sku.id)]
    assert len(our) == 1
    assert our[0]["quantity"] == 10
    assert our[0]["locked_qty"] == 2


class TestImportCsvHandler:
    """Covers core/_import/__init__.py import_csv_handler and ImportResult."""

    @pytest.mark.asyncio
    async def test_import_csv_handler_success(self):
        from src.core._import import ImportResult, import_csv_handler

        async def mock_handler(csv_text, db):
            return ImportResult(success=3), None

        result = await import_csv_handler(b"a,b\n1,2\n3,4\n5,6", None, mock_handler)
        assert result["success"] == 3
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_import_csv_handler_with_error(self):
        from src.core._import import ImportResult, import_csv_handler

        async def mock_handler(csv_text, db):
            return ImportResult(success=0, errors=[{"row": 1, "error": "bad"}] ), None

        result = await import_csv_handler("a,b\n1,2", None, mock_handler)
        assert result["success"] == 0
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_import_csv_handler_unicode_error(self):
        from src.core._import import import_csv_handler
        result = await import_csv_handler(b"\xff\xfe\x00\x01", None, lambda x, db: (None, None))
        assert result["success"] == 0
        assert "UTF-8" in result["errors"][0]["error"]

    @pytest.mark.asyncio
    async def test_import_result_to_dict(self):
        from src.core._import import ImportResult
        r = ImportResult(success=2, errors=[{"row": 1, "error": "x"}])
        d = r.to_dict()
        assert d["success"] == 2
        assert d["errors"] == [{"row": 1, "error": "x"}]

    @pytest.mark.asyncio
    async def test_import_result_defaults(self):
        from src.core._import import ImportResult
        r = ImportResult()
        assert r.success == 0
        assert r.errors == []

    @pytest.mark.asyncio
    async def test_import_csv_handler_handler_error(self):
        from src.core._import import ImportResult, import_csv_handler

        async def mock_handler(csv_text, db):
            return ImportResult(success=0), RuntimeError("handler failed")

        result = await import_csv_handler("a,b\n1,2", None, mock_handler)
        assert result["success"] == 0


class TestHandleOrdersImport:
    """Covers core/_import/import_orders.py handle_orders_import."""

    @pytest.mark.asyncio
    async def test_orders_import_success(self, db_session):
        from src.core._import.import_orders import handle_orders_import
        csv_text = "customer_id,items,priority\nIMPORT-CUST-01,\"[]\",medium\n"
        result, error = await handle_orders_import(csv_text, db_session)
        assert error is None
        assert result.success == 1
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_orders_import_missing_customer_id(self, db_session):
        from src.core._import.import_orders import handle_orders_import
        csv_text = "customer_id,items\n,\n"
        result, error = await handle_orders_import(csv_text, db_session)
        assert error is None
        assert result.success == 0
        assert len(result.errors) == 1
        assert "customer_id" in result.errors[0]["error"].lower()

    @pytest.mark.asyncio
    async def test_orders_import_invalid_json(self, db_session):
        from src.core._import.import_orders import handle_orders_import
        csv_text = "customer_id,items\nc1,\"{bad\"\n"
        result, error = await handle_orders_import(csv_text, db_session)
        assert error is None
        assert result.success == 0
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_orders_import_whitespace_customer(self, db_session):
        from src.core._import.import_orders import handle_orders_import
        csv_text = "customer_id\n   \n"
        result, error = await handle_orders_import(csv_text, db_session)
        assert error is None
        assert result.success == 0


class TestHandleInventoryImport:
    """Covers core/_import/import_inventory.py handle_inventory_import."""

    @pytest.mark.asyncio
    async def test_inventory_import_success(self, db_session):
        from src.core._import.import_inventory import handle_inventory_import
        sku = SKU(id=uuid.uuid4(), sku="IMPORT-SKU-01", name="Import SKU")
        wh = Warehouse(id=uuid.uuid4(), code="IMPORT-WH-01", name="Import WH")
        db_session.add_all([sku, wh])
        await db_session.commit()

        csv_text = f"sku_id,warehouse_id,quantity,min_qty\n{sku.id},{wh.id},10,2\n"
        result, error = await handle_inventory_import(csv_text, db_session)
        assert error is None
        assert result.success == 1

    @pytest.mark.asyncio
    async def test_inventory_import_missing_fields(self, db_session):
        from src.core._import.import_inventory import handle_inventory_import
        csv_text = "sku_id,warehouse_id\ns1,\n"
        result, error = await handle_inventory_import(csv_text, db_session)
        assert error is None
        assert result.success == 0
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_inventory_import_invalid_quantity(self, db_session):
        from src.core._import.import_inventory import handle_inventory_import
        sku = SKU(id=uuid.uuid4(), sku="IMPORT-SKU-Q", name="Q SKU")
        wh = Warehouse(id=uuid.uuid4(), code="IMPORT-WH-Q", name="Q WH")
        db_session.add_all([sku, wh])
        await db_session.commit()

        csv_text = f"sku_id,warehouse_id,quantity\n{sku.id},{wh.id},abc\n"
        result, error = await handle_inventory_import(csv_text, db_session)
        assert error is None
        assert result.success == 0
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_inventory_import_empty_row_skipped(self, db_session):
        from src.core._import.import_inventory import handle_inventory_import
        csv_text = "sku_id,warehouse_id\n\n"
        result, error = await handle_inventory_import(csv_text, db_session)
        assert error is None
        assert result.success == 0


class TestImportRoutes:
    """Covers core/_import/routes.py import endpoints."""

    async def test_import_orders_no_file(self, async_client):
        resp = await async_client.post("/api/v1/import/orders", json={})
        assert resp.status_code == 422

    async def test_import_inventory_no_file(self, async_client):
        resp = await async_client.post("/api/v1/import/inventory", json={})
        assert resp.status_code == 422

    async def test_import_orders_with_file(self, async_client, monkeypatch):
        async def mock_handler(content, db, handler):
            return {"success": 3, "errors": []}
        monkeypatch.setattr("src.core._import.routes.import_csv_handler", mock_handler)
        resp = await async_client.post(
            "/api/v1/import/orders",
            files={"file": ("orders.csv", b"customer_id,items\nC001,[]\nC002,[]\nC003,[]")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] == 3

    async def test_import_inventory_with_file(self, async_client, monkeypatch):
        async def mock_handler(content, db, handler):
            return {"success": 2, "errors": []}
        monkeypatch.setattr("src.core._import.routes.import_csv_handler", mock_handler)
        resp = await async_client.post(
            "/api/v1/import/inventory",
            files={"file": ("inventory.csv", b"sku_id,warehouse_id,quantity\nS1,W1,10\nS2,W2,20")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] == 2


@pytest.mark.asyncio
async def test_import_orders_from_csv(sqlite_engine, db_session):
    csv_content = "customer_id,items,priority,notes\nC001,[],medium,test-import\n"
    result = await import_orders_from_csv(csv_content, db_session)
    assert result["success"] == 1
    assert len(result["errors"]) == 0


@pytest.mark.asyncio
async def test_import_orders_csv_missing_customer(sqlite_engine, db_session):
    csv_content = "customer_id,items,priority,notes\n,,\n"
    result = await import_orders_from_csv(csv_content, db_session)
    assert result["success"] == 0
    assert len(result["errors"]) == 1
    assert "customer_id is required" in result["errors"][0]["error"]


@pytest.mark.asyncio
async def test_import_orders_csv_invalid_json(sqlite_engine, db_session):
    csv_content = "customer_id,items,priority,notes\nC001,{invalid,medium,test\n"
    result = await import_orders_from_csv(csv_content, db_session)
    assert result["success"] == 0
    assert len(result["errors"]) >= 1


@pytest.mark.asyncio
async def test_import_inventory_from_csv_create(sqlite_engine, db_session):
    sku = SKU(id=uuid.uuid4(), sku="IMSKU01", name="Import SKU")
    wh = Warehouse(id=uuid.uuid4(), code="IMWH01", name="Import WH")
    db_session.add_all([sku, wh])
    await db_session.commit()

    csv_content = f"sku_id,warehouse_id,quantity,min_qty\n{sku.id},{wh.id},50,5\n"
    result = await import_inventory_from_csv(csv_content, db_session)
    assert result["success"] == 1
    assert len(result["errors"]) == 0


@pytest.mark.asyncio
async def test_import_inventory_from_csv_update(sqlite_engine, db_session):
    sku = SKU(id=uuid.uuid4(), sku="IMSKU02", name="Update SKU")
    wh = Warehouse(id=uuid.uuid4(), code="IMWH02", name="Update WH")
    db_session.add_all([sku, wh])
    await db_session.flush()
    inv = Inventory(id=uuid.uuid4(), sku_id=sku.id, warehouse_id=wh.id, quantity=10, min_qty=2)
    db_session.add(inv)
    await db_session.commit()

    csv_content = f"sku_id,warehouse_id,quantity,min_qty\n{sku.id},{wh.id},99,9\n"
    result = await import_inventory_from_csv(csv_content, db_session)
    assert result["success"] == 1

    from sqlalchemy import select
    updated = (await db_session.execute(
        select(Inventory).where(Inventory.sku_id == sku.id, Inventory.warehouse_id == wh.id)
    )).scalar_one()
    assert updated.quantity == 99
    assert updated.min_qty == 9


@pytest.mark.asyncio
async def test_import_inventory_csv_invalid_uuid(sqlite_engine, db_session):
    csv_content = "sku_id,warehouse_id,quantity,min_qty\nnot-a-uuid,also-not-uuid,10,1\n"
    result = await import_inventory_from_csv(csv_content, db_session)
    assert result["success"] == 0
    assert len(result["errors"]) == 1
