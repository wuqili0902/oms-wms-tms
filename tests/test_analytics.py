import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from src.analytics.service import (
    get_dashboard_stats,
    get_low_stock_items,
    get_order_trends,
    get_recent_orders,
    get_status_distribution,
)
from src.core.database import get_db
from src.main import app
from src.oms.models import Customer, Order, OrderStatus
from src.wms.models import SKU, Inventory, Warehouse
from tests.conftest import _SharedSession


@pytest.mark.asyncio
async def test_dashboard_stats_empty(sqlite_engine, db_session):
    stats = await get_dashboard_stats(db_session)
    assert "order_count" in stats
    assert "user_count" in stats
    assert isinstance(stats["order_count"], int)
    assert isinstance(stats["user_count"], int)


@pytest.mark.asyncio
async def test_dashboard_stats_with_data(sqlite_engine, db_session):
    c = Customer(id=uuid.uuid4(), code="C001", name="Test")
    db_session.add(c)
    await db_session.flush()

    for i in range(5):
        o = Order(
            id=uuid.uuid4(), order_no=f"ORD-{i}", status=OrderStatus.PENDING,
            customer_id=c.id, items={}, total_amount=0,
        )
        db_session.add(o)
    await db_session.flush()

    stats = await get_dashboard_stats(db_session)
    assert stats["order_count"] == 5


@pytest.mark.asyncio
async def test_order_trends(sqlite_engine, db_session):
    c = Customer(id=uuid.uuid4(), code="C002", name="Test")
    db_session.add(c)
    await db_session.flush()

    now = datetime.now(UTC)
    for i in range(3):
        o = Order(
            id=uuid.uuid4(), order_no=uuid.uuid4().hex[:12], status=OrderStatus.PENDING,
            customer_id=c.id, items={}, total_amount=0,
            created_at=now - timedelta(days=i),
        )
        db_session.add(o)
    await db_session.commit()

    trends = await get_order_trends(db_session, days=30)
    assert len(trends) >= 1


@pytest.mark.asyncio
async def test_status_distribution(sqlite_engine, db_session):
    c = Customer(id=uuid.uuid4(), code="C003", name="Test")
    db_session.add(c)
    await db_session.flush()

    for status in [OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.COMPLETED]:
        o = Order(
            id=uuid.uuid4(), order_no=uuid.uuid4().hex[:12], status=status,
            customer_id=c.id, items={}, total_amount=0,
        )
        db_session.add(o)
    await db_session.commit()

    dist = await get_status_distribution(db_session)
    statuses = {d["status"]: d["count"] for d in dist}
    assert statuses.get("pending", 0) >= 1
    assert statuses.get("confirmed", 0) >= 1
    assert statuses.get("completed", 0) >= 1


@pytest.mark.asyncio
async def test_low_stock_items(sqlite_engine, db_session):
    sku = SKU(id=uuid.uuid4(), sku="LSKU01", name="Low Stock SKU")
    wh = Warehouse(id=uuid.uuid4(), code="WH01", name="Warehouse 1")
    db_session.add_all([sku, wh])
    await db_session.flush()

    inv = Inventory(id=uuid.uuid4(), sku_id=sku.id, warehouse_id=wh.id, quantity=2, min_qty=5)
    db_session.add(inv)
    await db_session.commit()

    items = await get_low_stock_items(db_session)
    assert len(items) >= 1
    assert items[0]["quantity"] <= items[0]["min_qty"]


@pytest.mark.asyncio
async def test_recent_orders(sqlite_engine, db_session):
    c = Customer(id=uuid.uuid4(), code="C004", name="Test")
    db_session.add(c)
    await db_session.flush()

    for i in range(3):
        o = Order(
            id=uuid.uuid4(), order_no=uuid.uuid4().hex[:12], status=OrderStatus.PENDING,
            customer_id=c.id, items={}, total_amount=100 * (i + 1),
            created_at=datetime.now(UTC) + timedelta(seconds=i),
        )
        db_session.add(o)
    await db_session.commit()

    recent = await get_recent_orders(db_session, limit=5)
    rec = [r for r in recent if r.get("customer_id") == str(c.id)]
    assert len(rec) == 3


@pytest.mark.asyncio
async def test_dashboard_api_endpoint(sqlite_engine):
    uid = "analytics-api-test"
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    c = Customer(id=uuid.uuid4(), code="CAPI", name="Test")
    shared.session.add(c)
    await shared.session.flush()
    o = Order(
        id=uuid.uuid4(), order_no=uuid.uuid4().hex[:12], status=OrderStatus.PENDING,
        customer_id=c.id, items={}, total_amount=100,
    )
    shared.session.add(o)
    await shared.session.commit()

    from src.core.security import create_access_token
    token = create_access_token({"sub": "testuser", "uid": uid})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/analytics/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["stats"]["order_count"] >= 1
    assert "order_trends" in data["data"]
    assert "status_distribution" in data["data"]

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_order_trends_api(sqlite_engine):
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token
    token = create_access_token({"sub": "testuser", "uid": "trends-test"})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/analytics/order-trends?days=7",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["data"]["days"] == 7

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_status_distribution_api(sqlite_engine):
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    from src.core.security import create_access_token
    token = create_access_token({"sub": "testuser", "uid": "status-test"})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/analytics/status-distribution",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text

    app.dependency_overrides.clear()
    await shared.teardown()


@pytest.mark.asyncio
async def test_low_stock_api(sqlite_engine):
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _override():
        yield shared.session

    app.dependency_overrides[get_db] = _override

    sku = SKU(id=uuid.uuid4(), sku="LAPI01", name="Low")
    wh = Warehouse(id=uuid.uuid4(), code="WH-L", name="Low WH")
    shared.session.add_all([sku, wh])
    await shared.session.flush()
    inv = Inventory(id=uuid.uuid4(), sku_id=sku.id, warehouse_id=wh.id, quantity=1, min_qty=10)
    shared.session.add(inv)
    await shared.session.commit()

    from src.core.security import create_access_token
    token = create_access_token({"sub": "testuser", "uid": "lowstock-test"})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/analytics/low-stock",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["data"]["count"] >= 1

    app.dependency_overrides.clear()
    await shared.teardown()
