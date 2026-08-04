"""Tests for auth models."""
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth.models import Permission, Role, User


class TestUserModel:
    async def test_create_user_with_valid_data(self, db_session: AsyncSession):
        user = User(id=uuid4(), username=f"newuser-{uuid4().hex[:8]}", email="new@example.com", hashed_password="pw")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.id is not None
        assert user.username.startswith("newuser-")

    async def test_user_has_required_fields(self, db_session: AsyncSession):
        user = User(id=uuid4(), username=f"requser-{uuid4().hex[:8]}", email="req@example.com", hashed_password="pw")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.is_active is True
        assert user.created_at is not None
        assert user.updated_at is not None

    async def test_user_username_is_unique(self, db_session: AsyncSession):
        prefix = uuid4().hex[:8]
        u1 = User(id=uuid4(), username=f"unique-{prefix}", email=f"u1-{prefix}@example.com", hashed_password="pw")
        db_session.add(u1)
        await db_session.commit()
        u2 = User(id=uuid4(), username=f"unique-{prefix}", email=f"u2-{prefix}@example.com", hashed_password="pw")
        db_session.add(u2)
        with pytest.raises(Exception):
            await db_session.commit()
        await db_session.rollback()

    async def test_user_email_is_unique(self, db_session: AsyncSession):
        prefix = uuid4().hex[:8]
        u1 = User(id=uuid4(), username=f"email1-{prefix}", email=f"dup-{prefix}@example.com", hashed_password="pw")
        db_session.add(u1)
        await db_session.commit()
        u2 = User(id=uuid4(), username=f"email2-{prefix}", email=f"dup-{prefix}@example.com", hashed_password="pw")
        db_session.add(u2)
        with pytest.raises(Exception):
            await db_session.commit()
        await db_session.rollback()

    async def test_user_default_is_active(self, db_session: AsyncSession):
        user = User(
            id=uuid4(),
            username=f"activeuser-{uuid4().hex[:8]}",
            email="active@example.com",
            hashed_password="pw",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.is_active is True

    async def test_user_timestamps_are_set(self, db_session: AsyncSession):
        user = User(id=uuid4(), username=f"tsuser-{uuid4().hex[:8]}", email="ts@example.com", hashed_password="pw")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.created_at is not None
        assert user.updated_at is not None


class TestRoleModel:
    async def test_create_role(self, db_session: AsyncSession):
        role = Role(
            id=uuid4(),
            name="Warehouse Manager",
            code=f"wh_manager-{uuid4().hex[:8]}",
            description="Manages warehouse ops",
        )
        db_session.add(role)
        await db_session.commit()
        await db_session.refresh(role)
        assert role.code.startswith("wh_manager-")
        assert role.is_system is False

    async def test_role_code_unique(self, db_session: AsyncSession):
        prefix = uuid4().hex[:8]
        r1 = Role(id=uuid4(), name="Role1", code=f"dupcode-{prefix}")
        db_session.add(r1)
        await db_session.commit()
        r2 = Role(id=uuid4(), name="Role2", code=f"dupcode-{prefix}")
        db_session.add(r2)
        with pytest.raises(Exception):
            await db_session.commit()
        await db_session.rollback()

    async def test_role_user_relationship(self, db_session: AsyncSession):
        prefix = uuid4().hex[:8]
        user = User(id=uuid4(), username=f"reluser-{prefix}", email=f"rel-{prefix}@example.com", hashed_password="pw")
        role = Role(id=uuid4(), name="Admin", code=f"relrole-{prefix}", description="Administrator")
        db_session.add_all([user, role])
        await db_session.commit()
        result = await db_session.execute(
            select(User).where(User.id == user.id).options(selectinload(User.roles))
        )
        user = result.unique().scalar_one()
        user.roles.append(role)
        await db_session.commit()
        result = await db_session.execute(
            select(User).where(User.id == user.id).options(selectinload(User.roles))
        )
        loaded = result.unique().scalar_one()
        assert len(loaded.roles) == 1
        assert loaded.roles[0].code == f"relrole-{prefix}"


class TestPermissionModel:
    async def test_create_permission(self, db_session: AsyncSession):
        perm = Permission(
            id=uuid4(), name="Create Order", code=f"order:create-{uuid4().hex[:8]}", resource="order", action="create"
        )
        db_session.add(perm)
        await db_session.commit()
        await db_session.refresh(perm)
        assert perm.code.startswith("order:create-")
        assert perm.resource == "order"
        assert perm.action == "create"

    async def test_permission_code_unique(self, db_session: AsyncSession):
        prefix = uuid4().hex[:8]
        p1 = Permission(id=uuid4(), name="Perm1", code=f"unique:code-{prefix}", resource="test", action="read")
        db_session.add(p1)
        await db_session.commit()
        p2 = Permission(id=uuid4(), name="Perm2", code=f"unique:code-{prefix}", resource="test", action="write")
        db_session.add(p2)
        with pytest.raises(Exception):
            await db_session.commit()
        await db_session.rollback()

    async def test_permission_role_relationship(self, db_session: AsyncSession):
        prefix = uuid4().hex[:8]
        role = Role(id=uuid4(), name="Admin", code=f"permrole-{prefix}", description="Administrator")
        db_session.add(role)
        await db_session.commit()
        result = await db_session.execute(
            select(Role).where(Role.id == role.id).options(selectinload(Role.permissions))
        )
        role = result.unique().scalar_one()
        perm = Permission(
            id=uuid4(), name="Delete Order", code=f"order:delete-{prefix}", resource="order", action="delete"
        )
        role.permissions.append(perm)
        db_session.add(perm)
        await db_session.commit()
        result = await db_session.execute(
            select(Role).where(Role.id == role.id).options(selectinload(Role.permissions))
        )
        loaded = result.unique().scalar_one()
        assert len(loaded.permissions) == 1
        assert loaded.permissions[0].code == f"order:delete-{prefix}"
