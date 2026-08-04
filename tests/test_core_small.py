from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    AppException,
    AuthException,
    NotFoundException,
    PermissionDeniedException,
    RateLimitException,
    ValidationException,
)
from src.core.models import AddressMaster, resolve_address
from src.core.pagination import PaginatedResponse, paginate
from src.models.base import model_to_dict


class TestExceptions:
    def test_app_exception_defaults(self):
        e = AppException()
        assert e.code == "APP_ERROR"
        assert e.status_code == 500
        assert e.message == "An application error occurred"
        assert e.detail is None

    def test_app_exception_custom(self):
        e = AppException(code="CUSTOM", status_code=418, message="Teapot", detail="I'm a teapot")
        assert str(e) == "Error CUSTOM: Teapot"
        assert e.detail == "I'm a teapot"

    def test_not_found_exception(self):
        e = NotFoundException()
        assert e.code == "NOT_FOUND"
        assert e.status_code == 404

    def test_not_found_exception_custom_message(self):
        e = NotFoundException(message="Order not found", detail={"id": "123"})
        assert str(e) == "Error NOT_FOUND: Order not found"

    def test_validation_exception(self):
        e = ValidationException()
        assert e.code == "VALIDATION_ERROR"
        assert e.status_code == 422

    def test_validation_exception_custom(self):
        e = ValidationException(message="Bad input")
        assert str(e) == "Error VALIDATION_ERROR: Bad input"

    def test_auth_exception(self):
        e = AuthException()
        assert e.code == "AUTH_FAILED"
        assert e.status_code == 401

    def test_auth_exception_custom(self):
        e = AuthException(message="Token expired", detail="Refresh token")
        assert e.detail == "Refresh token"

    def test_permission_denied_exception(self):
        e = PermissionDeniedException()
        assert e.code == "PERMISSION_DENIED"
        assert e.status_code == 403

    def test_rate_limit_exception(self):
        e = RateLimitException()
        assert e.code == "RATE_LIMIT_EXCEEDED"
        assert e.status_code == 429


class TestPaginate:
    async def test_paginate_basic(self):
        mock_db = AsyncMock(spec=AsyncSession)

        class FakeResult:
            def scalar(self):
                return 50
            def scalars(self):
                class S:
                    def all(self):
                        return ["a", "b"]
                return S()

        async def fake_execute(stmt):
            if hasattr(stmt, "_func"):
                return FakeResult()
            return FakeResult()

        mock_db.execute = fake_execute

        # Build a real-ish select statement using sqlalchemy
        from sqlalchemy import Column, Integer, MetaData, Table
        from sqlalchemy import select as sa_select
        meta = MetaData()
        t = Table("test", meta, Column("id", Integer))
        stmt = sa_select(t)

        result = await paginate(stmt, mock_db, page=2, page_size=10)
        assert isinstance(result, PaginatedResponse)
        assert result.total == 50
        assert result.page == 2
        assert result.page_size == 10
        assert result.total_pages == 5

    async def test_paginate_empty(self):
        mock_db = AsyncMock(spec=AsyncSession)

        class FakeResult:
            def scalar(self):
                return 0
            def scalars(self):
                class S:
                    def all(self):
                        return []
                return S()

        async def fake_execute(stmt):
            if hasattr(stmt, "_func"):
                return FakeResult()
            return FakeResult()

        mock_db.execute = fake_execute

        from sqlalchemy import Column, Integer, MetaData, Table
        from sqlalchemy import select as sa_select
        meta = MetaData()
        t = Table("test", meta, Column("id", Integer))
        result = await paginate(sa_select(t), mock_db)
        assert result.total == 0
        assert result.total_pages == 0
        assert result.items == []

    def test_paginated_response_model(self):
        r = PaginatedResponse(items=[1, 2], total=2, page=1, page_size=10, total_pages=1)
        assert r.model_dump() == {"items": [1, 2], "total": 2, "page": 1, "page_size": 10, "total_pages": 1}


class FakeCol:
    """Simple column stub for SQLAlchemy __table__.columns iteration."""
    def __init__(self, name):
        self.name = name


class ModelStub:
    """A minimal ORM-like object with a __dict__ and __table__.columns."""

    @staticmethod
    def make(**attrs):
        obj = type("Model", (), {})()
        obj.__dict__.update(attrs)
        cols = [FakeCol(k) for k in attrs]
        table_stub = type("Table", (), {"columns": cols})()
        object.__setattr__(obj, "__table__", table_stub)
        return obj


class TestModelToDict:

    def test_none_value(self):
        m = ModelStub.make(field=None)
        assert model_to_dict(m)["field"] is None

    def test_string_value(self):
        m = ModelStub.make(name="hello")
        assert model_to_dict(m)["name"] == "hello"

    def test_datetime_value(self):
        dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        m = ModelStub.make(ts=dt)
        assert model_to_dict(m)["ts"] == "2026-01-01T12:00:00+00:00"

    def test_decimal_value(self):
        m = ModelStub.make(price=Decimal("10.50"))
        assert model_to_dict(m)["price"] == "10.50"

    def test_enum_value(self):
        class Status(Enum):
            ACTIVE = "active"
        m = ModelStub.make(status=Status.ACTIVE)
        assert model_to_dict(m)["status"] == "active"

    def test_uuid_value(self):
        import uuid
        m = ModelStub.make(id=uuid.uuid4())
        result = model_to_dict(m)
        assert isinstance(result["id"], str)


class TestSharedModelsRepr:
    def test_customer_repr(self):
        from src.models.shared_models import Customer
        c = Customer(code="C001", name="Test Corp")
        assert repr(c) == "<Customer C001: Test Corp>"

    def test_order_item_repr(self):
        from src.models.shared_models import OrderItem
        item = OrderItem(gtin="1234567890123", quantity=5)
        r = repr(item)
        assert "1234567890123" in r
        assert "qty=5" in r


class TestSharedModelsBackRefs:
    def test_register_back_references_catches_from_configure(self):
        import src.models.shared_models as sm
        with patch.object(sm, '_configure_order_item_sku', side_effect=ImportError("test")):
            sm._register_back_references()

    def test_register_back_references_returns_on_no_orders_attr(self):
        import src.models.shared_models as sm
        mock = type("MockCustomer", (), {})()
        with patch.object(sm, 'Customer', mock):
            sm._register_back_references()

    def test_configure_order_item_sku_import_error(self):
        import src.models.shared_models as sm
        with patch.dict('sys.modules', {'src.wms.models': None}):
            sm._configure_order_item_sku()


class TestAddressMaster:
    def test_repr(self):
        a = AddressMaster(label="Home", city="Beijing")
        assert "Home" in repr(a)
        assert "Beijing" in repr(a)

    async def test_resolve_address_all(self):
        mock_db = AsyncMock(spec=AsyncSession)
        a = MagicMock()
        a.id = "addr-1"
        a.label = "Home"
        a.address_type = "shipping"
        a.contact_name = "Alice"
        a.phone = "123"
        a.email = "a@b.com"
        a.address_line_1 = "1 Main St"
        a.address_line_2 = ""
        a.city = "Beijing"
        a.state = "BJ"
        a.postal_code = "100000"
        a.country = "中国"
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [a]
        mock_db.execute.return_value = mock_result
        result = await resolve_address(
            mock_db,
            "order",
            entity_id="550e8400-e29b-41d4-a716-446655440000",
            address_type="shipping",
        )
        assert len(result) == 1
        assert result[0]["label"] == "Home"

    async def test_resolve_address_empty(self):
        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result
        result = await resolve_address(mock_db, "order")
        assert result == []
