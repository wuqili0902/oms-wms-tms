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

    async def test_get_me_user_not_found(self, async_client, auth, db_session):
        from sqlalchemy import delete

        from src.auth.models import User
        uid = uuid.UUID(auth["user"]["id"])
        await db_session.execute(delete(User).where(User.id == uid))
        await db_session.commit()
        resp = await async_client.get("/api/v1/auth/me", headers=auth["headers"])
        assert resp.status_code == 404


class TestListPermissionsCoverage:
    """Covers GET /permissions (router.py lines 111-112)."""

    async def test_list_permissions(self, async_client, auth, db_session):
        from src.auth.models import Permission
        perm = Permission(id=uuid.uuid4(), name="TestPerm", code="test_perm", resource="test", action="read")
        db_session.add(perm)
        await db_session.commit()
        resp = await async_client.get("/api/v1/auth/permissions", headers=auth["headers"])
        assert resp.status_code == 200
        perms = resp.json()
        assert isinstance(perms, list)
        assert any(p["code"] == "test_perm" for p in perms)


class TestUpdateRoleCoverage:
    """Covers PUT /roles/{id} success path (router.py line 126)."""

    async def test_update_role_success(self, async_client, auth, db_session):
        from src.auth.models import Role
        role = Role(id=uuid.uuid4(), name="UpdateRole", code="UPDATE_ROLE")
        db_session.add(role)
        await db_session.commit()
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
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    async def test_toggle_active_not_found(self, async_client, auth):
        resp = await async_client.post(
            f"/api/v1/auth/users/{uuid.uuid4()}/toggle",
            headers=auth["headers"],
        )
        assert resp.status_code == 404
