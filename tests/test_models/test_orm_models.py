"""ORM model unit tests — verify table creation, structure, and CRUD with SQLite in-memory.

All 5 modules (auth, oms, wms, barcode, tms) are tested against a SQLite engine
so the CI pipeline can validate ORM definitions without a PostgreSQL server.
"""
import uuid

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session as SASession

# ---------------------------------------------------------------------------
# SQLite compatibility shim for PostgreSQL-only types
# ---------------------------------------------------------------------------
# Register JSONB→JSON compiler for SQLite BEFORE importing models that use
# JSONB (LabelTemplate.content), so SQLiteDialect knows how to render it.
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

setattr(SQLiteTypeCompiler, "visit_JSONB", lambda self, type_, **kw: "JSON")

# Now safe to import models — Base.metadata is populated with all tables.
from src.models import Base  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    """In-memory SQLite engine with all ORM metadata applied."""
    e = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(e)
    yield e
    Base.metadata.drop_all(e)


@pytest.fixture()
def session(engine):
    """Fresh transactional session per test."""
    s = SASession(engine)
    try:
        yield s
    finally:
        s.rollback()
        s.close()


# =========================================================================
# Metadata / Schema
# =========================================================================


class TestMetadata:
    """Verify that every module's ORM models are discoverable and create
    the expected tables."""

    def test_all_tables_created(self, engine):
        """All 5 modules contribute to Base.metadata -> all tables exist."""
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        expected = {
            # auth
            "users",
            "roles",
            "permissions",
            "user_roles",
            "role_permissions",
            # oms
            "customers",
            "orders",
            "order_items",
            "order_status_logs",
            # wms
            "warehouses",
            "locations",
            "skus",
            "inventory",
            "inventory_logs",
            "reference_entities",
            "stock_movements",
            "picking_waves",
            # barcode
            "barcode_records",
            "label_templates",
            # tms
            "terminal_devices",
            "device_sessions",
            "sync_logs",
            "packing_records",
            "shipments",
        }
        missing = expected - tables
        extra = tables - expected
        assert not missing, f"Missing tables: {missing}"
        assert not extra, f"Unexpected tables: {extra}"
        assert len(tables) >= 24, f"Expected >=24 tables, got {len(tables)}"

    def test_primary_keys(self, engine):
        """Every entity table has a PK column named 'id'. Junction tables
        (user_roles, role_permissions) may use composite PKs."""
        inspector = inspect(engine)
        junction_tables = {"user_roles", "role_permissions"}
        for table in inspector.get_table_names():
            pk = inspector.get_pk_constraint(table)
            pk_cols = pk.get("constrained_columns", [])
            if table in junction_tables:
                assert len(pk_cols) >= 2, (
                    f"Junction table {table!r} should have a composite PK, got {pk_cols}"
                )
            else:
                assert "id" in pk_cols, (
                    f"Table {table!r} has no 'id' primary key (PK: {pk_cols})"
                )

    def test_foreign_keys_created(self, engine):
        """Referential integrity constraints are present."""
        inspector = inspect(engine)
        fks = {
            (fk["constrained_columns"][0], fk["referred_table"])
            for table in inspector.get_table_names()
            for fk in inspector.get_foreign_keys(table)
            if fk["constrained_columns"]
        }
        expected_fks = {
            ("warehouse_id", "warehouses"),
            ("location_id", "locations"),
            ("sku_id", "skus"),
            ("customer_id", "customers"),
            ("device_id", "terminal_devices"),
            ("order_id", "orders"),
        }
        assert expected_fks.issubset(fks), (
            f"Missing FK constraints. Expected {expected_fks}, got {fks}"
        )


# =========================================================================
# Auth models
# =========================================================================


class TestAuthModels:
    def test_create_user(self, session):
        from src.auth.models import User, Role

        role = Role(id=uuid.uuid4(), name="Admin", code="admin")
        session.add(role)
        session.flush()

        user = User(
            id=uuid.uuid4(),
            username="test_user",
            email="test@example.com",
            hashed_password="hashed_pw",
        )
        user.roles.append(role)
        session.add(user)
        session.commit()

        fetched = session.get(User, user.id)
        assert fetched is not None
        assert fetched.username == "test_user"
        assert len(fetched.roles) == 1
        assert fetched.roles[0].code == "admin"

    def test_unique_constraints(self, session):
        from src.auth.models import User

        u1 = User(id=uuid.uuid4(), username="dup", email="a@a.com", hashed_password="p1")
        u2 = User(id=uuid.uuid4(), username="dup", email="b@b.com", hashed_password="p2")
        session.add(u1)
        session.add(u2)
        with pytest.raises(Exception):
            session.commit()


# =========================================================================
# OMS models
# =========================================================================


class TestOmsModels:
    def test_create_customer(self, session):
        from src.oms.models import Customer

        c = Customer(id=uuid.uuid4(), code="C001", name="Test Corp")
        session.add(c)
        session.commit()

        fetched = session.get(Customer, c.id)
        assert fetched is not None
        assert fetched.code == "C001"

    def test_create_order_with_items(self, session):
        from src.oms.models import Customer, Order, OrderItem, OrderStatus

        c = Customer(id=uuid.uuid4(), code="C002", name="Client")
        session.add(c)
        session.flush()

        order = Order(
            id=uuid.uuid4(),
            order_no="ORD-20260601-0001",
            customer_id=c.id,
            total_amount=100.50,
        )
        session.add(order)
        session.flush()

        item = OrderItem(
            id=uuid.uuid4(),
            order=order,        # use relationship, not FK
            gtin="5901234123457",
            name="Widget",
            quantity=2,
            unit_price=50.25,
        )
        session.add(item)
        session.commit()

        # Expire + reload to test relationship loading
        session.expire_all()
        fetched = session.get(Order, order.id)
        assert fetched is not None
        assert fetched.status == OrderStatus.PENDING
        assert len(fetched.items_list) == 1

    def test_order_status_log(self, session):
        from src.oms.models import Customer, Order, OrderStatus, OrderStatusLog

        c = Customer(id=uuid.uuid4(), code="C003", name="Client")
        session.add(c)
        session.flush()

        order = Order(
            id=uuid.uuid4(),
            order_no="ORD-20260601-0002",
            customer_id=c.id,
        )
        session.add(order)
        session.flush()

        log = OrderStatusLog(
            id=uuid.uuid4(),
            order=order,
            from_status=OrderStatus.PENDING.value,
            to_status=OrderStatus.CONFIRMED.value,
        )
        session.add(log)
        session.commit()

        assert log.id is not None
        assert session.get(OrderStatusLog, log.id) is not None


# =========================================================================
# WMS models
# =========================================================================


class TestWmsModels:
    def test_create_warehouse(self, session):
        from src.wms.models import Warehouse, WarehouseStatus

        wh = Warehouse(id=uuid.uuid4(), code="WH01", name="Main Warehouse")
        session.add(wh)
        session.commit()

        fetched = session.get(Warehouse, wh.id)
        assert fetched is not None
        assert fetched.status == WarehouseStatus.ACTIVE

    def test_create_location(self, session):
        from src.wms.models import Warehouse, Location

        wh = Warehouse(id=uuid.uuid4(), code="WH-LOC", name="Loc Warehouse")
        session.add(wh)
        session.flush()

        loc = Location(
            id=uuid.uuid4(),
            warehouse_id=wh.id,
            code="A-01-01",
            zone="A",
            aisle="01",
            shelf="01",
        )
        session.add(loc)
        session.commit()

        assert session.get(Location, loc.id) is not None

    def test_inventory_crud(self, session):
        from src.wms.models import Warehouse, SKU, Inventory

        wh = Warehouse(id=uuid.uuid4(), code="WH-INV", name="Inv Warehouse")
        sku = SKU(id=uuid.uuid4(), sku="SKU-001", name="Test SKU")
        session.add_all([wh, sku])
        session.flush()

        inv = Inventory(
            id=uuid.uuid4(),
            warehouse_id=wh.id,
            sku_id=sku.id,
            gtin="5901234123457",
            batch_no="B001",
            quantity=100,
        )
        session.add(inv)
        session.commit()

        fetched = session.get(Inventory, inv.id)
        assert fetched is not None
        assert fetched.quantity == 100

    def test_stock_movement(self, session):
        from src.wms.models import Warehouse, Location, SKU, StockMovement

        wh = Warehouse(id=uuid.uuid4(), code="WH-MV", name="Movement")
        loc = Location(id=uuid.uuid4(), warehouse_id=wh.id, code="MV-LOC")
        sku = SKU(id=uuid.uuid4(), sku="SKU-MV")
        session.add_all([wh, loc, sku])
        session.flush()

        mv = StockMovement(
            id=uuid.uuid4(),
            source_warehouse_id=wh.id,
            source_location_id=loc.id,
            sku_id=sku.id,
            gtin="5901234123457",
            quantity=10,
            movement_type="TRANSFER",
        )
        session.add(mv)
        session.commit()

        assert session.get(StockMovement, mv.id) is not None

    def test_picking_wave(self, session):
        from src.wms.models import Warehouse, PickingWave

        wh = Warehouse(id=uuid.uuid4(), code="WH-PW", name="Picking Wave")
        session.add(wh)
        session.flush()

        wave = PickingWave(
            id=uuid.uuid4(),
            warehouse_id=wh.id,
            code="PW-001",
        )
        session.add(wave)
        session.commit()

        fetched = session.get(PickingWave, wave.id)
        assert fetched is not None
        assert fetched.code == "PW-001"


# =========================================================================
# Barcode models
# =========================================================================


class TestBarcodeModels:
    def test_create_barcode_record(self, session):
        from src.barcode.models import BarcodeRecord

        record = BarcodeRecord(
            id=uuid.uuid4(),
            gtin="5901234123457",
            entity_type="inventory",
            entity_id=uuid.uuid4(),
            format="ean13",
        )
        session.add(record)
        session.commit()

        assert session.get(BarcodeRecord, record.id) is not None

    def test_create_label_template(self, session):
        from src.barcode.models import LabelTemplate

        tmpl = LabelTemplate(
            id=uuid.uuid4(),
            name="Standard Label",
            code="STD",
            format="zpl",
            width_mm=100.0,
            height_mm=75.0,
            content={"fields": ["gtin", "name"]},
        )
        session.add(tmpl)
        session.commit()

        fetched = session.get(LabelTemplate, tmpl.id)
        assert fetched is not None
        assert fetched.content["fields"] == ["gtin", "name"]


# =========================================================================
# TMS models
# =========================================================================


class TestTmsModels:
    def test_create_device(self, session):
        from src.tms.models import TerminalDevice, TerminalDeviceType, PlatformType

        dev = TerminalDevice(
            id=uuid.uuid4(),
            code="DEV-001",
            name="Scanner 1",
            device_type=TerminalDeviceType.PDA,
            platform=PlatformType.ANDROID,
        )
        session.add(dev)
        session.commit()

        fetched = session.get(TerminalDevice, dev.id)
        assert fetched is not None
        assert fetched.code == "DEV-001"

    def test_create_session(self, session):
        from src.tms.models import TerminalDevice, DeviceSession, TerminalDeviceType, PlatformType

        dev = TerminalDevice(
            id=uuid.uuid4(),
            code="DEV-SES",
            name="Session device",
            device_type=TerminalDeviceType.PDA,
            platform=PlatformType.ANDROID,
        )
        session.add(dev)
        session.flush()

        ses = DeviceSession(
            id=uuid.uuid4(),
            device_id=dev.id,
            token="tok_" + uuid.uuid4().hex,
        )
        session.add(ses)
        session.commit()

        assert session.get(DeviceSession, ses.id) is not None

    def test_create_sync_log(self, session):
        from datetime import datetime, timezone
        from src.tms.models import (
            TerminalDevice,
            SyncLog,
            SyncLogType,
            SyncLogStatus,
            TerminalDeviceType,
            PlatformType,
        )

        dev = TerminalDevice(
            id=uuid.uuid4(),
            code="DEV-SYNC",
            name="Sync device",
            device_type=TerminalDeviceType.PDA,
            platform=PlatformType.ANDROID,
        )
        session.add(dev)
        session.flush()

        log = SyncLog(
            id=uuid.uuid4(),
            device_id=dev.id,
            sync_type=SyncLogType.DOWNLOAD,
            status=SyncLogStatus.PENDING,
            started_at=datetime.now(timezone.utc),
        )
        session.add(log)
        session.commit()

        fetched = session.get(SyncLog, log.id)
        assert fetched is not None
        assert fetched.sync_type == SyncLogType.DOWNLOAD
