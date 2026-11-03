"""Tests for auth guards (require_permission), response models, and pagination."""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio

P = "/api/v1"


@pytest.fixture
async def admin_client(async_client):
    """Register + login admin with full RBAC, return (client, headers)."""
    session = async_client._shared_session
    # Idempotent RBAC seed — find or create
    from sqlalchemy import select as sa_select

    from src.auth.models import Permission, Role, User
    from src.models import Base

    # Find existing permission
    existing_perm = await session.execute(
        sa_select(Permission.id).where(Permission.code == "admin.rbac.manage")
    )
    perm_row = existing_perm.first()
    if perm_row:
        perm_id = perm_row[0]
    else:
        perm = Permission(name="RBAC Manage", code="admin.rbac.manage", resource="admin", action="rbac.manage")
        session.add(perm)
        await session.flush()
        perm_id = perm.id

    # Find existing user_manage permission
    existing_perm2 = await session.execute(
        sa_select(Permission.id).where(Permission.code == "admin.user.manage")
    )
    perm2_row = existing_perm2.first()
    if not perm2_row:
        perm2 = Permission(name="User Manage", code="admin.user.manage", resource="admin", action="user.manage")
        session.add(perm2)
        await session.flush()

    # Find existing role
    existing_role = await session.execute(
        sa_select(Role.id).where(Role.code == "FULL-ADMIN")
    )
    role_row = existing_role.first()
    if role_row:
        role_id = role_row[0]
    else:
        role = Role(name="FullAdmin", code="FULL-ADMIN")
        session.add(role)
        await session.flush()
        role_id = role.id
        # Link permissions to role (idempotent)
        rp = Base.metadata.tables["role_permissions"]
        existing_rp = await session.execute(
            rp.select().where((rp.c.role_id == role_id) & (rp.c.permission_id == perm_id))
        )
        if not existing_rp.first():
            await session.execute(rp.insert().values(role_id=role_id, permission_id=perm_id))
        if perm2_row:
            existing_rp2 = await session.execute(
                rp.select().where((rp.c.role_id == role_id) & (rp.c.permission_id == perm2_row[0]))
            )
            if not existing_rp2.first():
                await session.execute(rp.insert().values(role_id=role_id, permission_id=perm2_row[0]))
        await session.flush()

    # Register user
    uname = f"adm_{uuid.uuid4().hex[:6]}"
    await async_client.post(f"{P}/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })

    # Assign role to user via ORM
    result = await session.execute(sa_select(User.id).where(User.username == uname))
    user_row = result.first()
    if user_row:
        ur = Base.metadata.tables["user_roles"]
        existing_ur = await session.execute(
            ur.select().where((ur.c.user_id == user_row[0]) & (ur.c.role_id == role_id))
        )
        if not existing_ur.first():
            await session.execute(ur.insert().values(user_id=user_row[0], role_id=role_id))
            await session.flush()

    login = await async_client.post(f"{P}/auth/login", json={"username": uname, "password": "test123456"})
    token = login.json()["access_token"]
    return async_client, {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def unprivileged_client(async_client):
    """Register + login user without any RBAC permissions."""
    uname = f"nopriv_{uuid.uuid4().hex[:6]}"
    await async_client.post(f"{P}/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    login = await async_client.post(f"{P}/auth/login", json={"username": uname, "password": "test123456"})
    token = login.json()["access_token"]
    return async_client, {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════════
# 1. require_permission guard — 403 for unprivileged users
# ══════════════════════════════════════════════════════════════════════════


class TestRequirePermissionGuards:
    """Verify all guarded endpoints return 403 without required permission."""

    async def test_create_role_403(self, unprivileged_client):
        client, headers = unprivileged_client
        r = await client.post(f"{P}/auth/roles", headers=headers,
                              json={"name": "X", "code": "X"})
        assert r.status_code == 403
        body = r.json()
        msg = body.get("error", {}).get("message", "") or body.get("detail", "")
        assert "admin.rbac.manage" in msg

    async def test_update_role_403(self, unprivileged_client):
        client, headers = unprivileged_client
        r = await client.put(f"{P}/auth/roles/{uuid.uuid4()}", headers=headers,
                             json={"name": "X"})
        assert r.status_code == 403

    async def test_delete_role_403(self, unprivileged_client):
        client, headers = unprivileged_client
        r = await client.delete(f"{P}/auth/roles/{uuid.uuid4()}", headers=headers)
        assert r.status_code == 403

    async def test_create_permission_403(self, unprivileged_client):
        client, headers = unprivileged_client
        r = await client.post(f"{P}/auth/permissions", headers=headers,
                              json={"name": "X", "code": "x.y", "resource": "x", "action": "y"})
        assert r.status_code == 403

    async def test_assign_role_to_user_403(self, unprivileged_client):
        client, headers = unprivileged_client
        r = await client.post(f"{P}/auth/users/{uuid.uuid4()}/roles", headers=headers,
                              json={"role_id": str(uuid.uuid4())})
        assert r.status_code == 403

    async def test_remove_role_from_user_403(self, unprivileged_client):
        client, headers = unprivileged_client
        r = await client.delete(f"{P}/auth/users/{uuid.uuid4()}/roles/{uuid.uuid4()}", headers=headers)
        assert r.status_code == 403

    async def test_assign_permission_to_role_403(self, unprivileged_client):
        client, headers = unprivileged_client
        r = await client.post(f"{P}/auth/roles/{uuid.uuid4()}/permissions", headers=headers,
                              json={"permission_id": str(uuid.uuid4())})
        assert r.status_code == 403

    async def test_remove_permission_from_role_403(self, unprivileged_client):
        client, headers = unprivileged_client
        r = await client.delete(
            f"{P}/auth/roles/{uuid.uuid4()}/permissions/{uuid.uuid4()}", headers=headers)
        assert r.status_code == 403

    async def test_toggle_user_active_403(self, unprivileged_client):
        client, headers = unprivileged_client
        r = await client.post(f"{P}/auth/users/{uuid.uuid4()}/toggle", headers=headers)
        assert r.status_code == 403


# ══════════════════════════════════════════════════════════════════════════
# 2. require_permission guard — 200/201 for privileged users
# ══════════════════════════════════════════════════════════════════════════


class TestRequirePermissionSuccess:
    """Verify guarded endpoints succeed with required permission."""

    async def test_create_role_201(self, admin_client):
        client, headers = admin_client
        r = await client.post(f"{P}/auth/roles", headers=headers,
                              json={"name": "TestRole", "code": f"TR_{uuid.uuid4().hex[:6]}"})
        assert r.status_code == 201
        assert r.json()["name"] == "TestRole"

    async def test_create_permission_201(self, admin_client):
        client, headers = admin_client
        r = await client.post(f"{P}/auth/permissions", headers=headers, json={
            "name": "TestPerm", "code": f"tp_{uuid.uuid4().hex[:6]}",
            "resource": "test", "action": "read",
        })
        assert r.status_code == 201
        assert r.json()["name"] == "TestPerm"

    async def test_update_role_200(self, admin_client):
        client, headers = admin_client
        # Create role first
        r = await client.post(f"{P}/auth/roles", headers=headers,
                              json={"name": "ToUpdate", "code": f"TU_{uuid.uuid4().hex[:6]}"})
        role_id = r.json()["id"]
        # Update
        r = await client.put(f"{P}/auth/roles/{role_id}", headers=headers,
                             json={"name": "Updated"})
        assert r.status_code == 200
        assert r.json()["name"] == "Updated"

    async def test_delete_role_204(self, admin_client):
        client, headers = admin_client
        r = await client.post(f"{P}/auth/roles", headers=headers,
                              json={"name": "ToDelete", "code": f"TD_{uuid.uuid4().hex[:6]}"})
        role_id = r.json()["id"]
        r = await client.delete(f"{P}/auth/roles/{role_id}", headers=headers)
        assert r.status_code == 204

    async def test_assign_role_to_user_200(self, admin_client):
        client, headers = admin_client
        # Create role
        r = await client.post(f"{P}/auth/roles", headers=headers,
                              json={"name": "AssignRole", "code": f"AR_{uuid.uuid4().hex[:6]}"})
        role_id = r.json()["id"]
        # Create user
        uname = f"target_{uuid.uuid4().hex[:6]}"
        r = await client.post(f"{P}/auth/register", json={
            "username": uname, "email": f"{uname}@test.com", "password": "test123456",
        })
        user_id = r.json()["id"]
        # Assign
        r = await client.post(f"{P}/auth/users/{user_id}/roles", headers=headers,
                              json={"role_id": role_id})
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# 3. Unauthenticated access — 401 for all protected endpoints
# ══════════════════════════════════════════════════════════════════════════


class TestUnauthenticatedAccess:
    """Verify protected endpoints reject requests without token."""

    async def test_get_me_401(self, async_client):
        r = await async_client.get(f"{P}/auth/me")
        assert r.status_code == 401

    async def test_list_users_401(self, async_client):
        r = await async_client.get(f"{P}/auth/users")
        assert r.status_code == 401

    async def test_list_roles_401(self, async_client):
        r = await async_client.get(f"{P}/auth/roles")
        assert r.status_code == 401

    async def test_list_permissions_401(self, async_client):
        r = await async_client.get(f"{P}/auth/permissions")
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════
# 4. Response model validation
# ══════════════════════════════════════════════════════════════════════════


class TestResponseModels:
    """Verify response models match expected schemas."""

    async def test_user_response_model(self, admin_client):
        client, headers = admin_client
        r = await client.get(f"{P}/auth/me", headers=headers)
        assert r.status_code == 200
        data = r.json()
        # UserResponse fields
        assert "id" in data
        assert "username" in data
        assert "email" in data
        assert "is_active" in data

    async def test_role_response_model(self, admin_client):
        client, headers = admin_client
        r = await client.get(f"{P}/auth/roles", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            role = data[0]
            assert "id" in role
            assert "name" in role
            assert "code" in role

    async def test_permission_response_model(self, admin_client):
        client, headers = admin_client
        r = await client.get(f"{P}/auth/permissions", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            perm = data[0]
            assert "id" in perm
            assert "name" in perm
            assert "code" in perm

    async def test_token_response_model(self, async_client):
        uname = f"tok_{uuid.uuid4().hex[:6]}"
        await async_client.post(f"{P}/auth/register", json={
            "username": uname, "email": f"{uname}@test.com", "password": "test123456",
        })
        r = await async_client.post(f"{P}/auth/login", json={"username": uname, "password": "test123456"})
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_message_response_model(self, admin_client):
        client, headers = admin_client
        # Logout returns MessageResponse
        # First get a refresh token
        uname = f"msg_{uuid.uuid4().hex[:6]}"
        await client.post(f"{P}/auth/register", json={
            "username": uname, "email": f"{uname}@test.com", "password": "test123456",
        })
        login = await client.post(f"{P}/auth/login", json={"username": uname, "password": "test123456"})
        refresh_token = login.json()["refresh_token"]
        r = await client.post(f"{P}/auth/logout", json={"refresh_token": refresh_token})
        assert r.status_code == 200
        data = r.json()
        assert "message" in data
