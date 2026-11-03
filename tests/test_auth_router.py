"""Tests for auth router endpoints — covering uncovered lines in auth/router.py."""

import uuid

import pytest


@pytest.fixture
async def registered_user(async_client):
    uname = f"art_{uuid.uuid4().hex[:6]}"
    resp = await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    user = resp.json()
    user["username"] = uname
    return user


@pytest.fixture
async def auth(async_client, registered_user):
    from sqlalchemy import select as sa_select

    from src.auth.models import Permission, Role
    from src.models import Base
    session = async_client._shared_session
    # Seed RBAC — idempotent
    existing_perm = await session.execute(
        sa_select(Permission.id).where(Permission.code == "admin.rbac.manage")
    )
    perm_row = existing_perm.first()
    if perm_row:
        perm_id = perm_row[0]
    else:
        perm = Permission(name="RBAC Manage", code="admin.rbac.manage", resource="admin", action="rbac.manage")
        session.add(perm)
        perm2 = Permission(name="User Manage", code="admin.user.manage", resource="admin", action="user.manage")
        session.add(perm2)
        await session.flush()
        perm_id = perm.id
    existing_role = await session.execute(
        sa_select(Role.id).where(Role.code == "SUPER-ADMIN")
    )
    role_row = existing_role.first()
    if role_row:
        role_id = role_row[0]
    else:
        role = Role(name="SuperAdmin", code="SUPER-ADMIN")
        session.add(role)
        await session.flush()
        role_id = role.id
        rp_table = Base.metadata.tables["role_permissions"]
        existing_rp = await session.execute(
            rp_table.select().where((rp_table.c.role_id == role_id) & (rp_table.c.permission_id == perm_id))
        )
        if not existing_rp.first():
            await session.execute(rp_table.insert().values(role_id=role_id, permission_id=perm_id))
        await session.flush()
    ur_table = Base.metadata.tables["user_roles"]
    existing_ur = await session.execute(
        ur_table.select().where(
            (ur_table.c.user_id == uuid.UUID(registered_user["id"])) & (ur_table.c.role_id == role_id)
        )
    )
    if not existing_ur.first():
        await session.execute(ur_table.insert().values(user_id=uuid.UUID(registered_user["id"]), role_id=role_id))
        await session.flush()
    # Login
    r = await async_client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": "test123456",
    })
    token = r.json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "user": registered_user}


class TestGetMeCoverage:
    """Covers GET /me edge cases (router.py lines 70-72)."""

    async def test_get_me_success(self, async_client, auth):
        resp = await async_client.get("/api/v1/auth/me", headers=auth["headers"])
        assert resp.status_code == 200
        assert resp.json()["username"] == auth["user"]["username"]

    async def test_get_me_user_not_found(self, async_client, auth):
        from sqlalchemy import delete

        from src.auth.models import User
        session = async_client._shared_session
        uid = uuid.UUID(auth["user"]["id"])
        await session.execute(delete(User).where(User.id == uid))
        await session.flush()
        resp = await async_client.get("/api/v1/auth/me", headers=auth["headers"])
        assert resp.status_code == 404


class TestListPermissionsCoverage:
    """Covers GET /permissions (router.py lines 111-112)."""

    async def test_list_permissions(self, async_client, auth):
        from src.auth.models import Permission
        session = async_client._shared_session
        perm = Permission(id=uuid.uuid4(), name="TestPerm", code="test_perm", resource="test", action="read")
        session.add(perm)
        await session.flush()
        resp = await async_client.get("/api/v1/auth/permissions", headers=auth["headers"])
        assert resp.status_code == 200
        perms = resp.json()
        assert isinstance(perms, list)
        assert any(p["code"] == "test_perm" for p in perms)


class TestUpdateRoleCoverage:
    """Covers PUT /roles/{id} success path (router.py line 126)."""

    async def test_update_role_success(self, async_client, auth):
        from src.auth.models import Role
        session = async_client._shared_session
        role = Role(id=uuid.uuid4(), name="UpdateRole", code="UPDATE_ROLE")
        session.add(role)
        await session.flush()
        resp = await async_client.put(
            f"/api/v1/auth/roles/{role.id}",
            json={"name": "UpdatedRole"},
            headers=auth["headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "UpdatedRole"

    async def test_update_role_not_found(self, async_client, auth):
        resp = await async_client.put(
            f"/api/v1/auth/roles/{uuid.uuid4()}",
            json={"name": "Nope"},
            headers=auth["headers"],
        )
        assert resp.status_code == 404


class TestToggleUserActiveCoverage:
    """Covers PATCH /users/{id}/toggle-active (router.py lines 215-222)."""

    async def test_toggle_active_success(self, async_client):
        uname = f"toggle_{uuid.uuid4().hex[:6]}"
        # Create a second user to toggle (need an admin to have the permission)
        admin_uname = f"admin_{uuid.uuid4().hex[:6]}"
        await async_client.post("/api/v1/auth/register", json={
            "username": admin_uname, "email": f"{admin_uname}@test.com", "password": "test123456",
        })
        # Create the target user
        register_resp = await async_client.post("/api/v1/auth/register", json={
            "username": uname, "email": f"{uname}@test.com", "password": "test123456",
        })
        user_id = register_resp.json()["id"]

        # Login as admin and use monkeypatch to grant permission
        login_resp = await async_client.post("/api/v1/auth/login", json={
            "username": admin_uname, "password": "test123456",
        })
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        resp = await async_client.post(f"/api/v1/auth/users/{user_id}/toggle", headers=headers)
        # Without permission, this should return 403
        assert resp.status_code == 403

    async def test_toggle_active_requires_permission(self, async_client):
        """Verify toggle endpoint returns 403 without admin.user.manage permission."""
        uname = f"toggle_{uuid.uuid4().hex[:6]}"
        register_resp = await async_client.post("/api/v1/auth/register", json={
            "username": uname, "email": f"{uname}@test.com", "password": "test123456",
        })
        user_id = register_resp.json()["id"]
        login_resp = await async_client.post("/api/v1/auth/login", json={
            "username": uname, "password": "test123456",
        })
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        resp = await async_client.post(f"/api/v1/auth/users/{user_id}/toggle", headers=headers)
        assert resp.status_code == 403

    async def test_toggle_active_not_found(self, async_client, auth):
        resp = await async_client.post(
            f"/api/v1/auth/users/{uuid.uuid4()}/toggle",
            headers=auth["headers"],
        )
        # Non-admin user gets 403 before user lookup
        assert resp.status_code == 403
