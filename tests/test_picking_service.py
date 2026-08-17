"""Tests for wms/services/picking_service.py."""
import uuid
from decimal import Decimal

import pytest

from src.wms.models import (
    Inventory,
    Location,
    LocationStatus,
    LocationType,
    PickingWave,
    SKU,
    Warehouse,
)
from src.wms.services.picking_service import (
    assign_pick_task,
    auto_replenish,
    complete_pick,
    pick_from_stock,
)


@pytest.mark.asyncio
async def test_pick_from_stock_happy_path(db_session):
    wh = Warehouse(id=uuid.uuid4(), code="PW-HW1", name="Pick WH")
    sku = SKU(id=uuid.uuid4(), sku="PICK-SKU-01", name="Pick SKU")
    db_session.add_all([wh, sku])
    await db_session.flush()

    inv1 = Inventory(
        id=uuid.uuid4(), warehouse_id=wh.id, sku_id=sku.id,
        batch_no="B001", quantity=Decimal("10"), locked_qty=Decimal("0"),
        min_qty=Decimal("0"), max_qty=Decimal("0"),
    )
    inv2 = Inventory(
        id=uuid.uuid4(), warehouse_id=wh.id, sku_id=sku.id,
        batch_no="B002", quantity=Decimal("5"), locked_qty=Decimal("0"),
        min_qty=Decimal("0"), max_qty=Decimal("0"),
    )
    db_session.add_all([inv1, inv2])
    await db_session.commit()

    result = await pick_from_stock(db_session, str(wh.id), "PICK-SKU-01", 12)
    assert result["remaining_quantity"] == 0
    assert len(result["picked_batches"]) == 2
    assert result["picked_batches"][0]["batch_no"] == "B001"
    assert result["picked_batches"][0]["qty"] == 10
    assert result["picked_batches"][1]["batch_no"] == "B002"
    assert result["picked_batches"][1]["qty"] == 2


@pytest.mark.asyncio
async def test_pick_from_stock_partial_fulfill(db_session):
    wh = Warehouse(id=uuid.uuid4(), code="PW-HW2", name="Pick WH")
    sku = SKU(id=uuid.uuid4(), sku="PICK-SKU-02", name="Pick SKU 2")
    db_session.add_all([wh, sku])
    await db_session.flush()

    inv = Inventory(
        id=uuid.uuid4(), warehouse_id=wh.id, sku_id=sku.id,
        batch_no="B003", quantity=Decimal("3"), locked_qty=Decimal("0"),
        min_qty=Decimal("0"), max_qty=Decimal("0"),
    )
    db_session.add(inv)
    await db_session.commit()

    result = await pick_from_stock(db_session, str(wh.id), "PICK-SKU-02", 5)
    assert result["remaining_quantity"] == 2
    assert len(result["picked_batches"]) == 1
    assert result["picked_batches"][0]["qty"] == 3


@pytest.mark.asyncio
async def test_pick_from_stock_no_inventory(db_session):
    wh = Warehouse(id=uuid.uuid4(), code="PW-HW3", name="Pick WH")
    db_session.add(wh)
    await db_session.commit()

    with pytest.raises(Exception, match="No inventory found"):
        await pick_from_stock(db_session, str(wh.id), "NONEXIST", 1)


@pytest.mark.asyncio
async def test_pick_from_stock_skips_locked(db_session):
    wh = Warehouse(id=uuid.uuid4(), code="PW-HW4", name="Pick WH")
    sku = SKU(id=uuid.uuid4(), sku="PICK-SKU-03", name="Locked SKU")
    db_session.add_all([wh, sku])
    await db_session.flush()

    inv = Inventory(
        id=uuid.uuid4(), warehouse_id=wh.id, sku_id=sku.id,
        batch_no="B004", quantity=Decimal("5"), locked_qty=Decimal("5"),
        min_qty=Decimal("0"), max_qty=Decimal("0"),
    )
    db_session.add(inv)
    await db_session.commit()

    result = await pick_from_stock(db_session, str(wh.id), "PICK-SKU-03", 1)
    assert result["remaining_quantity"] == 1
    assert len(result["picked_batches"]) == 0


@pytest.mark.asyncio
async def test_assign_pick_task(db_session):
    wh = Warehouse(id=uuid.uuid4(), code="PW-HW5", name="Pick WH")
    loc = Location(
        id=uuid.uuid4(), warehouse_id=wh.id, code="LOC-01",
        zone="A", aisle="1", shelf="1", level="1", position="1",
        location_type=LocationType.STORAGE, status=LocationStatus.ACTIVE,
    )
    db_session.add_all([wh, loc])
    await db_session.commit()

    result = await assign_pick_task(db_session, str(wh.id), [str(loc.id)])
    assert result["code"].startswith("PW-")
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_assign_pick_task_invalid_location(db_session):
    wh = Warehouse(id=uuid.uuid4(), code="PW-HW6", name="Pick WH")
    db_session.add(wh)
    await db_session.commit()

    fake_loc = str(uuid.uuid4())
    with pytest.raises(Exception, match="invalid"):
        await assign_pick_task(db_session, str(wh.id), [fake_loc])


@pytest.mark.asyncio
async def test_complete_pick(db_session):
    wh = Warehouse(id=uuid.uuid4(), code="PW-HW7", name="Pick WH")
    wave = PickingWave(
        id=uuid.uuid4(), warehouse_id=wh.id, code="PW-TEST",
        status="in_progress",
    )
    db_session.add_all([wh, wave])
    await db_session.commit()

    result = await complete_pick(db_session, str(wave.id), actual_quantity=5)
    assert result["status"] == "completed"
    assert result["completed_items"] == 5


@pytest.mark.asyncio
async def test_complete_pick_not_found(db_session):
    with pytest.raises(Exception, match="not found"):
        await complete_pick(db_session, str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_auto_replenish(db_session):
    wh = Warehouse(id=uuid.uuid4(), code="PW-HW8", name="Replenish WH")
    sku = SKU(id=uuid.uuid4(), sku="REPL-SKU", name="Replenish SKU")
    db_session.add_all([wh, sku])
    await db_session.flush()

    inv = Inventory(
        id=uuid.uuid4(), warehouse_id=wh.id, sku_id=sku.id,
        batch_no="B005", quantity=Decimal("2"), locked_qty=Decimal("0"),
        min_qty=Decimal("5"), max_qty=Decimal("100"),
    )
    db_session.add(inv)
    await db_session.commit()

    result = await auto_replenish(db_session, str(wh.id), threshold_pct=0.2)
    assert result["replenishments_created"] >= 1
    assert len(result["movements"]) >= 1


@pytest.mark.asyncio
async def test_auto_replenish_no_items_below_threshold(db_session):
    wh = Warehouse(id=uuid.uuid4(), code="PW-HW9", name="No Replenish WH")
    sku = SKU(id=uuid.uuid4(), sku="OK-SKU", name="OK SKU")
    db_session.add_all([wh, sku])
    await db_session.flush()

    inv = Inventory(
        id=uuid.uuid4(), warehouse_id=wh.id, sku_id=sku.id,
        batch_no="B006", quantity=Decimal("50"), locked_qty=Decimal("0"),
        min_qty=Decimal("5"), max_qty=Decimal("100"),
    )
    db_session.add(inv)
    await db_session.commit()

    result = await auto_replenish(db_session, str(wh.id))
    assert result["replenishments_created"] == 0
