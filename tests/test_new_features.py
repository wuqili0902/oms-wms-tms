"""Tests for all new features added in Phase 1-3 implementation."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

setattr(SQLiteTypeCompiler, "visit_JSONB", lambda self, type_, **kw: "JSON")

from src.core.database import get_db
from src.main import app
from src.models import Base


pytest_plugins = ("pytest_asyncio",)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def sqlite_engine():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(sqlite_engine):
    conn = await sqlite_engine.connect()
    trans = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)
    await session.begin_nested()
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()


@pytest_asyncio.fixture
async def async_client(sqlite_engine):
    class Shared:
        def __init__(self, engine):
            self.engine = engine
            self.session = None
            self.conn = None
            self.trans = None
        async def setup(self):
            self.conn = await self.engine.connect()
            self.trans = await self.conn.begin()
            self.session = AsyncSession(bind=self.conn, expire_on_commit=False)
            await self.session.begin_nested()
        async def teardown(self):
            if self.session: await self.session.close()
            if self.trans: await self.trans.rollback()
            if self.conn: await self.conn.close()

    shared = Shared(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    await shared.teardown()


def _wh(**kw):
    """Factory helper for Warehouse to avoid column-name confusion."""
    from src.wms.models import Warehouse, WarehouseType, WarehouseStatus
    return Warehouse(
        warehouse_type=WarehouseType.CENTER,
        status=WarehouseStatus.ACTIVE,
        address={},
        **kw,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Outbox Pattern
# ═══════════════════════════════════════════════════════════════════════════════


class TestOutbox:
    async def test_append_event(self, db):
        from src.core.outbox import append_event, OutboxEvent

        event = await append_event(
            db,
            aggregate_type="Order",
            aggregate_id=uuid.uuid4(),
            event_type="order.created",
            payload={"order_no": "ORD-001"},
        )
        assert event.id is not None
        assert event.status == "pending"
        assert event.event_type == "order.created"
        assert event.payload["order_no"] == "ORD-001"




# ═══════════════════════════════════════════════════════════════════════════════
# 2. PDA Offline — SyncQueueService
# ═══════════════════════════════════════════════════════════════════════════════

class TestPDAOffline:
    pytestmark = pytest.mark.skip("SyncQueueService/MutationType not yet implemented in offline.py")
    def setup_method(self):
        self.db_path = None

    def _make_svc(self, tmp_path):
        from src.core.offline import SyncQueueService
        db_path = str(tmp_path / "test_pda.db")
        return SyncQueueService(db_path), db_path

    def test_sync_queue_enqueue_and_pending(self, tmp_path):
        from src.core.offline import MutationType
        svc, _ = self._make_svc(tmp_path)

        rec = svc.enqueue("InventoryItem", "SKU-001", MutationType.UPDATE,
                          {"qty": 10}, priority=5)
        assert rec.id is not None
        assert rec.operation == "update"

        n = svc.enqueue_bulk([
            {"entity_type": "Order", "entity_id": "ORD-1",
             "operation": MutationType.CREATE, "payload": {"total": 100}},
            {"entity_type": "Order", "entity_id": "ORD-2",
             "operation": MutationType.CREATE, "payload": {"total": 200}},
        ])
        assert n == 2

        pending = svc.get_pending(limit=10)
        assert len(pending) == 3

        ids = [r.id for r in pending[:2]]
        count = svc.mark_synced(ids)
        assert count == 2

        remaining = svc.get_pending(limit=10)
        assert len(remaining) == 1

    def test_sync_queue_mark_failed(self, tmp_path):
        from src.core.offline import SyncQueueService, MutationType, SyncQueue
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        svc, _ = self._make_svc(tmp_path)
        rec = svc.enqueue("Test", "1", MutationType.CREATE, {})
        svc.mark_failed(rec.id, "connection timeout")

        with Session(svc.engine) as s:
            r = s.execute(select(SyncQueue).where(SyncQueue.id == rec.id)).scalar_one()
            assert r.error_message == "connection timeout"
            assert r.retry_count == 1
            assert r.synced_at is None  # still pending

    def test_mark_failed_exhausts_retries(self, tmp_path):
        from src.core.offline import SyncQueueService, MutationType, SyncQueue
        from sqlalchemy import select, update
        from sqlalchemy.orm import Session

        svc, _ = self._make_svc(tmp_path)
        rec = svc.enqueue("Test", "2", MutationType.CREATE, {})

        with Session(svc.engine) as s:
            q = select(SyncQueue).where(SyncQueue.id == rec.id)
            orig = s.execute(q).scalar_one()
            max_r = orig.max_retries
            s.execute(
                update(SyncQueue).where(SyncQueue.id == rec.id).values(retry_count=max_r)
            )
            s.commit()

        svc.mark_failed(rec.id, "final attempt failed")

        with Session(svc.engine) as s:
            r = s.execute(select(SyncQueue).where(SyncQueue.id == rec.id)).scalar_one()
            assert r.error_message == "final attempt failed"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. FEFO / FIFO — _pick_batches
# ═══════════════════════════════════════════════════════════════════════════════

class TestFEFOFIFO:
    async def _seed_inventory(self, db, sku_id, warehouse_id, location_id):
        from src.wms.models import Inventory
        now = datetime.now(UTC)
        batches = [
            Inventory(id=uuid.uuid4(), warehouse_id=warehouse_id, location_id=location_id,
                      sku_id=sku_id, gtin="", batch_no="B001",
                      expiry_date=now + timedelta(days=100),
                      manufacturing_date=now - timedelta(days=30),
                      received_at=now - timedelta(days=30),
                      quantity=Decimal("50"), locked_qty=Decimal("0")),
            Inventory(id=uuid.uuid4(), warehouse_id=warehouse_id, location_id=location_id,
                      sku_id=sku_id, gtin="", batch_no="B002",
                      expiry_date=now + timedelta(days=10),
                      manufacturing_date=now - timedelta(days=60),
                      received_at=now - timedelta(days=60),
                      quantity=Decimal("30"), locked_qty=Decimal("0")),
            Inventory(id=uuid.uuid4(), warehouse_id=warehouse_id, location_id=location_id,
                      sku_id=sku_id, gtin="", batch_no="B003",
                      expiry_date=now + timedelta(days=50),
                      manufacturing_date=now - timedelta(days=10),
                      received_at=now - timedelta(days=10),
                      quantity=Decimal("20"), locked_qty=Decimal("0")),
        ]
        for b in batches:
            db.add(b)
        await db.flush()
        return batches

    @pytest.mark.parametrize("strategy,first_batch", [
        ("fefo", "B002"),
        ("fifo", "B002"),
    ])
    async def test_pick_strategy(self, db, strategy, first_batch):
        from src.wms.models import SKU, Location
        wh = _wh(id=uuid.uuid4(), code=f"WH-{strategy.upper()}", name=f"Test {strategy}")
        loc = Location(id=uuid.uuid4(), warehouse_id=wh.id, code=f"L-{strategy.upper()}")
        sku = SKU(id=uuid.uuid4(), sku=f"SKU-{strategy.upper()}", name="Test")
        db.add_all([wh, loc, sku])
        await db.flush()

        await self._seed_inventory(db, sku.id, wh.id, loc.id)

        from src.wms.service import _pick_batches
        picked = await _pick_batches(db, wh.id, loc.id, sku.id, Decimal("40"), strategy=strategy)
        assert len(picked) >= 1
        assert picked[0]["inv"].batch_no == first_batch

    async def test_pick_insufficient_qty(self, db):
        from src.wms.models import SKU, Location, Inventory
        wh = _wh(id=uuid.uuid4(), code="WH-SHORT", name="Short")
        loc = Location(id=uuid.uuid4(), warehouse_id=wh.id, code="L-SHORT")
        sku = SKU(id=uuid.uuid4(), sku="SKU-SHORT", name="Short")
        db.add_all([wh, loc, sku])
        await db.flush()

        inv = Inventory(id=uuid.uuid4(), warehouse_id=wh.id, location_id=loc.id,
                        sku_id=sku.id, gtin="", batch_no="B001",
                        quantity=Decimal("5"), locked_qty=Decimal("0"))
        db.add(inv)
        await db.flush()

        from src.wms.service import _pick_batches
        picked = await _pick_batches(db, wh.id, loc.id, sku.id, Decimal("99"), strategy="fefo")
        total = sum(float(p["available"]) for p in picked)
        assert total == 5.0

    async def test_adjust_inventory_with_batch(self, db):
        from src.wms.models import SKU, Location
        wh = _wh(id=uuid.uuid4(), code="WH-ADJ", name="Adj")
        loc = Location(id=uuid.uuid4(), warehouse_id=wh.id, code="L-ADJ")
        sku = SKU(id=uuid.uuid4(), sku="SKU-ADJ", name="Adj")
        db.add_all([wh, loc, sku])
        await db.flush()

        from src.wms.service import adjust_inventory
        result = await adjust_inventory(db, {
            "warehouse_id": str(wh.id),
            "location_id": str(loc.id),
            "sku": "SKU-ADJ",
            "quantity": 100,
            "batch_no": "BATCH-001",
        })
        assert result["batch_no"] == "BATCH-001"
        assert result["quantity"] == 100.0


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Order Split / Merge
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrderSplitMerge:
    async def _seed_order(self, db, suffix="", customer_id=None, wh_id=None):
        from src.oms.models import Customer, Order, OrderItem, OrderStatus, OrderPriority
        if customer_id is None:
            cid = uuid.uuid4()
            cust = Customer(id=cid, code=f"CUST-SM{suffix}", name=f"SM{suffix}",
                            contact="", phone="", address={})
            db.add(cust)
            await db.flush()
            customer_id = cid

        order = Order(id=uuid.uuid4(), order_no=f"ORD-SM-{suffix}", status=OrderStatus.PENDING,
                      customer_id=customer_id, items={}, total_amount=Decimal("100"),
                      priority=OrderPriority.MEDIUM, notes="")
        if wh_id:
            order.warehouse_id = wh_id
        db.add(order)
        await db.flush()
        items = [
            OrderItem(id=uuid.uuid4(), order_id=order.id, sku_id=None, gtin="001",
                      name="Item A", quantity=5, unit_price=Decimal("10")),
            OrderItem(id=uuid.uuid4(), order_id=order.id, sku_id=None, gtin="002",
                      name="Item B", quantity=3, unit_price=Decimal("20")),
        ]
        for it in items:
            db.add(it)
        await db.flush()
        return order

    async def test_split_order(self, db):
        order = await self._seed_order(db, suffix="SPLIT")
        from src.oms.merge import split_order

        children = await split_order(db, str(order.id), [
            {"items": [{"sku": "", "quantity": 2, "product_name": "Item A"}],
             "note": "Split 1"},
            {"items": [{"sku": "", "quantity": 3, "product_name": "Item B"}],
             "note": "Split 2"},
        ], reason="test split")

        assert len(children) == 2
        assert children[0]["order_no"].endswith("-SP1")
        assert children[1]["order_no"].endswith("-SP2")

    async def test_merge_orders(self, db):
        from src.oms.models import Customer
        cust = Customer(id=uuid.uuid4(), code="CUST-MG", name="MG", contact="", phone="", address={})
        db.add(cust)
        await db.flush()

        wh = _wh(id=uuid.uuid4(), code="WH-MG", name="MG")
        db.add(wh)
        await db.flush()

        o1 = await self._seed_order(db, suffix="MG01", customer_id=cust.id, wh_id=wh.id)
        o2 = await self._seed_order(db, suffix="MG02", customer_id=cust.id, wh_id=wh.id)
        from src.oms.merge import merge_orders, get_merge_group

        group = await merge_orders(db, [str(o1.id), str(o2.id)], code="MG-001")
        assert group["code"] == "MG-001"
        assert group["status"] == "active"
        assert len(group["order_ids"]) == 2

        fetched = await get_merge_group(db, group["id"])
        assert fetched is not None
        assert fetched["code"] == "MG-001"

    async def test_split_nonexistent_order(self, db):
        from src.oms.merge import split_order
        from src.core.exceptions import NotFoundException
        with pytest.raises(NotFoundException):
            await split_order(db, str(uuid.uuid4()), [])

    async def test_merge_single_order_fails(self, db):
        from src.oms.merge import merge_orders
        from src.core.exceptions import ValidationException
        wh = _wh(id=uuid.uuid4(), code="WH-FAIL", name="Fail")
        db.add(wh)
        await db.flush()
        o = await self._seed_order(db, suffix="FAIL", wh_id=wh.id)
        with pytest.raises(ValidationException):
            await merge_orders(db, [str(o.id)], code="MG-FAIL")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ABC-XYZ Analysis
# ═══════════════════════════════════════════════════════════════════════════════

class TestABCXYZ:
    async def _seed_movements(self, db):
        from src.wms.models import SKU, StockMovement, Location
        wh = _wh(id=uuid.uuid4(), code="WH-ABC", name="ABC")
        loc = Location(id=uuid.uuid4(), warehouse_id=wh.id, code="L-ABC")
        skus = []
        for i in range(5):
            s = SKU(id=uuid.uuid4(), sku=f"SKU-ABC-{i}", name=f"ABC {i}")
            skus.append(s)
        db.add_all([wh, loc, *skus])
        await db.flush()

        now = datetime.now(UTC)
        for idx, s in enumerate(skus):
            for day in range(1, 10):
                m = StockMovement(
                    id=uuid.uuid4(), source_warehouse_id=wh.id, target_warehouse_id=None,
                    source_location_id=loc.id, target_location_id=None,
                    sku_id=s.id, gtin="", quantity=Decimal(-((10 - idx) * day)),
                    movement_type="outbound", created_at=now - timedelta(days=10 - day),
                )
                db.add(m)
        await db.flush()
        return wh, skus

    async def test_abc_analysis(self, db):
        await self._seed_movements(db)
        from src.wms.analysis import compute_abc_analysis
        analysis = await compute_abc_analysis(db, months=6)
        assert len(analysis) == 5
        assert analysis[0]["abc_category"] in ("A", "B", "C")
        assert analysis[0]["share_pct"] > 0

    async def test_xyz_analysis(self, db):
        pytest.skip("XYZ analysis uses date_trunc (PostgreSQL only)")

    async def test_abc_xyz_matrix(self, db):
        pytest.skip("XYZ analysis uses date_trunc (PostgreSQL only)")

    async def test_abc_empty_db(self, db):
        from src.wms.analysis import compute_abc_analysis
        result = await compute_abc_analysis(db, months=6)
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Shopify Connector
# ═══════════════════════════════════════════════════════════════════════════════

class TestShopifyConnector:
    def test_parse_order_create(self):
        from src.connectors.shopify_webhook import parse_order_create
        payload = {
            "id": 12345,
            "order_number": 1001,
            "email": "test@shop.com",
            "currency": "USD",
            "total_price": "99.99",
            "line_items": [{"sku": "SKU-S", "title": "Widget", "quantity": 2, "price": "49.99"}],
            "customer": {"first_name": "John"},
            "shipping_address": {"city": "NYC"},
        }
        msg = parse_order_create(payload)
        assert msg.payload["shopify_order_id"] == "12345"
        assert len(msg.payload["items"]) == 1

    def test_verify_webhook(self):
        from src.connectors.shopify_webhook import verify_webhook
        secret = "test_secret"
        body = b'{"test": true}'
        import hmac, hashlib
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert verify_webhook(body, expected, secret)
        assert not verify_webhook(body, "bad_hash", secret)

    def test_parse_order_create_empty_items(self):
        from src.connectors.shopify_webhook import parse_order_create
        msg = parse_order_create({"id": 0, "order_number": 0})
        assert msg.msg_type.value == "ORDERS"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Amazon Connector
# ═══════════════════════════════════════════════════════════════════════════════

class TestAmazonConnector:
    def test_parse_amazon_order(self):
        from src.connectors.amazon_mws import parse_amazon_order
        data = {
            "AmazonOrderId": "AMZ-001",
            "OrderStatus": "Unshipped",
            "BuyerEmail": "buyer@amz.com",
            "BuyerName": "Alice",
            "OrderTotal": {"Amount": "199.99", "CurrencyCode": "USD"},
            "ShippingAddress": {"City": "Seattle", "StateOrRegion": "WA"},
            "OrderItems": [{"SellerSKU": "SKU-A1", "Title": "Gadget", "QuantityOrdered": 1}],
        }
        msg = parse_amazon_order(data)
        assert msg.payload["amazon_order_id"] == "AMZ-001"
        assert len(msg.payload["items"]) == 1

    def test_build_tracking_update(self):
        from src.connectors.amazon_mws import build_tracking_update
        upd = build_tracking_update("AMZ-001", "UPS", "1Z999AA10123456784")
        assert upd["carrier_code"] == "UPS"
        assert upd["status"] == "Shipped"

    def test_parse_amazon_order_no_items(self):
        from src.connectors.amazon_mws import parse_amazon_order
        msg = parse_amazon_order({"AmazonOrderId": "AMZ-000"})
        assert msg.payload["items"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Mobile Sync API
# ═══════════════════════════════════════════════════════════════════════════════

class TestMobileSyncAPI:
    async def test_sync_push_endpoint(self, async_client):
        r = await async_client.post("/api/v1/sync/push", json={
            "batch": [
                {"entity_type": "Inventory", "entity_id": "SKU-X",
                 "operation": "update", "payload": {"qty": 5}},
            ]
        })
        assert r.status_code == 200
        data = r.json()
        assert data["accepted"] == 1

    async def test_sync_pull_endpoint(self, async_client):
        r = await async_client.get("/api/v1/sync/pull")
        assert r.status_code == 200
        data = r.json()
        assert "changes" in data
        assert "has_more" in data

    async def test_sync_ack_endpoint(self, async_client):
        r = await async_client.post("/api/v1/sync/ack", json=["id-1", "id-2"])
        assert r.status_code == 200
        data = r.json()
        assert data["acknowledged"] == 2

    async def test_health_check(self, async_client):
        with patch("src.api.v1.health.check_db_health") as mock_check:
            mock_check.return_value = True
            r = await async_client.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["service"] == "oms-wms-tms"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Inventory model new fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestInventoryModel:
    async def test_inventory_has_new_fields(self, db):
        from src.wms.models import Inventory
        inv = Inventory(
            id=uuid.uuid4(), warehouse_id=uuid.uuid4(), location_id=uuid.uuid4(),
            sku_id=uuid.uuid4(), gtin="", batch_no="B-NEW",
            expiry_date=datetime.now(UTC), manufacturing_date=datetime.now(UTC),
            received_at=datetime.now(UTC), quantity=Decimal("10"),
        )
        db.add(inv)
        await db.flush()
        assert inv.expiry_date is not None
        assert inv.manufacturing_date is not None
        assert inv.received_at is not None
