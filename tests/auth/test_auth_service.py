"""Unit tests for auth service functions (with db_session)."""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import Permission, Role, RolePermission, User, UserRole
from src.auth.service import (
    assign_permission_to_role,
    assign_role_to_user,
    create_permission,
    create_role,
    delete_role,
    get_user_by_id,
    get_user_by_username,
    list_permissions,
    list_roles,
    list_users,
    refresh_tokens,
    register_user,
    remove_permission_from_role,
    remove_role_from_user,
    update_role,
)
from src.core.exceptions import NotFoundException, ValidationException


class TestUserService:
    async def test_register_user(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        result = await register_user(db_session, {
            "username": f"svcuser-{suffix}",
            "email": f"svc-{suffix}@t.com",
            "password": "test123456",
        })
        assert result["username"] == f"svcuser-{suffix}"
        assert result["is_active"] is True

    async def test_register_duplicate_username(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        await register_user(db_session, {
            "username": f"dup-{suffix}",
            "email": f"dup-{suffix}@t.com",
            "password": "test123456",
        })
        with pytest.raises(ValidationException):
            await register_user(db_session, {
                "username": f"dup-{suffix}",
                "email": f"dup2-{suffix}@t.com",
                "password": "test123456",
            })

    async def test_get_user_by_id(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        created = await register_user(db_session, {
            "username": f"getbyid-{suffix}",
            "email": f"getbyid-{suffix}@t.com",
            "password": "test123456",
        })
        result = await get_user_by_id(db_session, created["id"])
        assert result["id"] == created["id"]

    async def test_get_user_by_id_not_found(self, db_session: AsyncSession):
        with pytest.raises(NotFoundException):
            await get_user_by_id(db_session, str(uuid.uuid4()))

    async def test_get_user_by_username(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        await register_user(db_session, {
            "username": f"byuname-{suffix}",
            "email": f"byuname-{suffix}@t.com",
            "password": "test123456",
        })
        result = await get_user_by_username(db_session, f"byuname-{suffix}")
        assert result is not None
        assert result["username"] == f"byuname-{suffix}"

    async def test_get_user_by_username_not_found(self, db_session: AsyncSession):
        result = await get_user_by_username(db_session, "nobody")
        assert result is None

    async def test_authenticate_inactive_user(self, db_session: AsyncSession, monkeypatch):
        suffix = uuid.uuid4().hex[:6]
        from src.auth.service import register_user, authenticate_user
        await register_user(db_session, {
            "username": f"inact-{suffix}",
            "email": f"inact-{suffix}@t.com",
            "password": "test123456",
        })
        from sqlalchemy import select
        from src.auth.models import User
        result = await db_session.execute(select(User).where(User.username == f"inact-{suffix}"))
        user = result.scalar_one()
        user.is_active = False
        await db_session.commit()
        auth_result = await authenticate_user(db_session, f"inact-{suffix}", "test123456")
        assert auth_result is None

    async def test_list_users(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        await register_user(db_session, {
            "username": f"listuser-{suffix}",
            "email": f"list-{suffix}@t.com",
            "password": "test123456",
        })
        users = await list_users(db_session)
        assert any(u["username"] == f"listuser-{suffix}" for u in users)


class TestRoleService:
    async def test_create_role(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        role = await create_role(db_session, {
            "name": f"TestRole-{suffix}",
            "code": f"TEST_{suffix}",
        })
        assert role["code"] == f"TEST_{suffix}"

    async def test_create_role_duplicate_code(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        await create_role(db_session, {
            "name": "First", "code": f"DUP_{suffix}",
        })
        with pytest.raises(ValidationException):
            await create_role(db_session, {
                "name": "Second", "code": f"DUP_{suffix}",
            })

    async def test_list_roles(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        await create_role(db_session, {
            "name": f"R1-{suffix}", "code": f"R1_{suffix}",
        })
        roles = await list_roles(db_session)
        assert any(r["code"] == f"R1_{suffix}" for r in roles)

    async def test_update_role_name(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        role = await create_role(db_session, {
            "name": f"OldName-{suffix}",
            "code": f"UP_{suffix}",
        })
        updated = await update_role(db_session, role["id"], {
            "name": f"NewName-{suffix}",
        })
        assert updated["name"] == f"NewName-{suffix}"

    async def test_update_role_not_found(self, db_session: AsyncSession):
        with pytest.raises(NotFoundException):
            await update_role(db_session, str(uuid.uuid4()), {"name": "Nope"})

    async def test_update_role_description(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        role = await create_role(db_session, {
            "name": f"DescRole-{suffix}",
            "code": f"DESC_{suffix}",
        })
        updated = await update_role(db_session, role["id"], {
            "description": "test description",
        })
        assert updated["description"] == "test description"

    async def test_delete_role_system(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        role = await create_role(db_session, {
            "name": f"SysRole-{suffix}",
            "code": f"SYS_{suffix}",
        })
        from src.auth.models import Role
        from sqlalchemy import select
        result = await db_session.execute(select(Role).where(Role.id == uuid.UUID(role["id"])))
        db_role = result.scalar_one()
        db_role.is_system = True
        await db_session.commit()
        from src.core.exceptions import ValidationException
        with pytest.raises(ValidationException, match="Cannot delete system role"):
            await delete_role(db_session, role["id"])

    async def test_delete_role(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        role = await create_role(db_session, {
            "name": f"DelRole-{suffix}",
            "code": f"DEL_{suffix}",
        })
        await delete_role(db_session, role["id"])
        roles = await list_roles(db_session)
        assert all(r["id"] != role["id"] for r in roles)

    async def test_delete_role_not_found(self, db_session: AsyncSession):
        with pytest.raises(NotFoundException):
            await delete_role(db_session, str(uuid.uuid4()))


class TestPermissionService:
    async def test_create_permission(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        perm = await create_permission(db_session, {
            "name": f"Perm-{suffix}",
            "code": f"perm_{suffix}",
            "resource": "test",
            "action": "read",
        })
        assert perm["code"] == f"perm_{suffix}"

    async def test_create_permission_duplicate_code(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        await create_permission(db_session, {
            "name": "P1", "code": f"pdup_{suffix}",
            "resource": "test", "action": "read",
        })
        with pytest.raises(ValidationException):
            await create_permission(db_session, {
                "name": "P2", "code": f"pdup_{suffix}",
                "resource": "test", "action": "write",
            })

    async def test_list_permissions(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        await create_permission(db_session, {
            "name": f"PL-{suffix}", "code": f"pl_{suffix}",
            "resource": "test", "action": "read",
        })
        perms = await list_permissions(db_session)
        assert any(p["code"] == f"pl_{suffix}" for p in perms)


class TestRoleAssignment:
    async def _setup_user_and_role(self, db_session, suffix):
        user = User(id=uuid.uuid4(), username=f"assign-{suffix}",
                    email=f"assign-{suffix}@t.com", hashed_password="h")
        role = Role(id=uuid.uuid4(), name=f"R-{suffix}", code=f"R_{suffix}")
        db_session.add_all([user, role])
        await db_session.commit()
        return str(user.id), str(role.id)

    async def test_assign_role_to_user(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        uid, rid = await self._setup_user_and_role(db_session, suffix)
        result = await assign_role_to_user(db_session, uid, rid)
        assert result["user_id"] == uid
        assert result["role_id"] == rid

    async def test_assign_role_duplicate(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        uid, rid = await self._setup_user_and_role(db_session, suffix)
        await assign_role_to_user(db_session, uid, rid)
        with pytest.raises(ValidationException):
            await assign_role_to_user(db_session, uid, rid)

    async def test_assign_role_user_not_found(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        uid, rid = await self._setup_user_and_role(db_session, suffix)
        with pytest.raises(NotFoundException):
            await assign_role_to_user(db_session, str(uuid.uuid4()), rid)

    async def test_assign_role_role_not_found(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        uid, _ = await self._setup_user_and_role(db_session, suffix)
        with pytest.raises(NotFoundException):
            await assign_role_to_user(db_session, uid, str(uuid.uuid4()))

    async def test_remove_role_from_user(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        uid, rid = await self._setup_user_and_role(db_session, suffix)
        await assign_role_to_user(db_session, uid, rid)
        await remove_role_from_user(db_session, uid, rid)
        with pytest.raises(NotFoundException):
            await remove_role_from_user(db_session, uid, rid)

    async def test_remove_role_not_assigned(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        uid, rid = await self._setup_user_and_role(db_session, suffix)
        with pytest.raises(NotFoundException):
            await remove_role_from_user(db_session, uid, rid)


class TestPermissionAssignment:
    async def _setup_role_and_perm(self, db_session, suffix):
        role = Role(id=uuid.uuid4(), name=f"PR-{suffix}", code=f"PR_{suffix}")
        perm = Permission(id=uuid.uuid4(), name=f"PP-{suffix}", code=f"pp_{suffix}",
                          resource="test", action="read")
        db_session.add_all([role, perm])
        await db_session.commit()
        return str(role.id), str(perm.id)

    async def test_assign_permission_to_role(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        rid, pid = await self._setup_role_and_perm(db_session, suffix)
        result = await assign_permission_to_role(db_session, rid, pid)
        assert result["role_id"] == rid
        assert result["permission_id"] == pid

    async def test_assign_permission_duplicate(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        rid, pid = await self._setup_role_and_perm(db_session, suffix)
        await assign_permission_to_role(db_session, rid, pid)
        with pytest.raises(ValidationException):
            await assign_permission_to_role(db_session, rid, pid)

    async def test_assign_permission_role_not_found(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        _, pid = await self._setup_role_and_perm(db_session, suffix)
        with pytest.raises(NotFoundException):
            await assign_permission_to_role(db_session, str(uuid.uuid4()), pid)

    async def test_assign_permission_perm_not_found(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        rid, _ = await self._setup_role_and_perm(db_session, suffix)
        with pytest.raises(NotFoundException):
            await assign_permission_to_role(db_session, rid, str(uuid.uuid4()))

    async def test_remove_permission_from_role(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        rid, pid = await self._setup_role_and_perm(db_session, suffix)
        await assign_permission_to_role(db_session, rid, pid)
        await remove_permission_from_role(db_session, rid, pid)
        with pytest.raises(NotFoundException):
            await remove_permission_from_role(db_session, rid, pid)

    async def test_remove_permission_not_assigned(self, db_session: AsyncSession):
        suffix = uuid.uuid4().hex[:6]
        rid, pid = await self._setup_role_and_perm(db_session, suffix)
        with pytest.raises(NotFoundException):
            await remove_permission_from_role(db_session, rid, pid)


class TestRefreshTokensCoverage:
    """Covers refresh_tokens with expired/invalid token (lines 105-106)."""

    async def test_refresh_tokens_expired(self, monkeypatch):
        from src.auth.token_store import token_store
        from src.core.security import TokenExpired
        await token_store.store("fake-expired-token", "testuser")
        import src.auth.service as svc
        orig = svc.decode_token
        def mock_decode(t):
            raise TokenExpired()
        svc.decode_token = mock_decode
        try:
            result = await svc.refresh_tokens("fake-expired-token")
            assert result is None
        finally:
            svc.decode_token = orig

    async def test_refresh_tokens_invalid(self, monkeypatch):
        from src.auth.token_store import token_store
        from src.core.security import TokenInvalid
        await token_store.store("fake-invalid-token", "testuser")
        import src.auth.service as svc
        orig = svc.decode_token
        def mock_decode(t):
            raise TokenInvalid()
        svc.decode_token = mock_decode
        try:
            result = await svc.refresh_tokens("fake-invalid-token")
            assert result is None
        finally:
            svc.decode_token = orig


class TestEnsureAdminCoverage:
    """Covers _ensure_admin no-user path (line 295)."""

    async def test_ensure_admin_no_users(self, db_session: AsyncSession):
        import src.auth.service as svc
        svc._admin_seeded = False
        await svc._ensure_admin(db_session)
        assert svc._admin_seeded is True
