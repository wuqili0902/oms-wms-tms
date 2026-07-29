"""Tests for core models — AddressMaster CRUD and resolve_address query."""
import uuid

import pytest

from src.core.models import AddressMaster, resolve_address


pytestmark = pytest.mark.asyncio


class TestAddressMasterModel:
    async def test_repr(self, db_session):
        addr = AddressMaster(
            id=uuid.uuid4(),
            label="HQ",
            entity_type="warehouse",
            city="上海",
        )
        db_session.add(addr)
        r = repr(addr)
        assert "AddressMaster" in r
        assert "HQ" in r
        assert "上海" in r


class TestResolveAddress:

    async def _seed(self, db_session):
        ids = []
        for label, etype, eid, atype in [
            ("WH-1", "warehouse", None, "shipping"),
            ("WH-2", "warehouse", None, "billing"),
            ("CUST-HOME", "customer", uuid.uuid4(), "shipping"),
        ]:
            a = AddressMaster(
                id=uuid.uuid4(),
                label=label,
                entity_type=etype,
                entity_id=eid,
                address_type=atype,
                contact_name="张三",
                phone="13800138000",
                email="test@test.com",
                address_line_1="路123号",
                city="上海",
                state="上海市",
                postal_code="200000",
                country="中国",
            )
            db_session.add(a)
            ids.append(a.id)
        await db_session.commit()
        return ids

    async def test_resolve_by_entity_type(self, db_session):
        await self._seed(db_session)
        results = await resolve_address(db_session, entity_type="warehouse")
        assert len(results) >= 2

    async def test_resolve_by_entity_type_and_id(self, db_session):
        await self._seed(db_session)
        eid = uuid.uuid4()
        db_session.add(AddressMaster(
            id=uuid.uuid4(), label="TEST", entity_type="customer",
            entity_id=eid, address_type="shipping",
            contact_name="李四", phone="13900139000",
            address_line_1="街456号", city="北京",
            postal_code="100000",
        ))
        await db_session.commit()
        results = await resolve_address(db_session, entity_type="customer", entity_id=str(eid))
        assert len(results) >= 1
        assert results[0]["label"] == "TEST"

    async def test_resolve_with_address_type(self, db_session):
        await self._seed(db_session)
        results = await resolve_address(db_session, entity_type="warehouse", address_type="billing")
        assert len(results) >= 1
        assert results[0]["address_type"] == "billing"

    async def test_resolve_empty_result(self, db_session):
        results = await resolve_address(db_session, entity_type="nonexistent")
        assert results == []

    async def test_resolve_returns_dict_with_all_fields(self, db_session):
        await self._seed(db_session)
        results = await resolve_address(db_session, entity_type="warehouse")
        r = results[0]
        assert "id" in r
        assert "label" in r
        assert "city" in r
        assert "country" in r
        assert r["country"] == "中国"
