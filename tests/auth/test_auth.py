"""Tests for auth endpoints — async HTTP integration tests with SQLite in-memory."""
import uuid

import pytest


class TestRegister:
    async def test_register(self, async_client):
        resp = await async_client.post("/api/v1/auth/register", json={
            "username": "testuser",
            "email": "user@test.com",
            "password": "test123456",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "testuser"
        assert data["is_active"] is True

    async def test_register_duplicate_username(self, async_client):
        await async_client.post("/api/v1/auth/register", json={
            "username": "dupuser", "email": "dup1@test.com", "password": "test123456",
        })
        resp = await async_client.post("/api/v1/auth/register", json={
            "username": "dupuser", "email": "dup2@test.com", "password": "test123456",
        })
        assert resp.status_code == 400


class TestLogin:
    async def test_login(self, async_client):
        await async_client.post("/api/v1/auth/register", json={
            "username": "loginuser", "email": "login@test.com", "password": "pass123456",
        })
        resp = await async_client.post("/api/v1/auth/login", json={
            "username": "loginuser", "password": "pass123456",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_login_invalid_password(self, async_client):
        await async_client.post("/api/v1/auth/register", json={
            "username": "failuser", "email": "fail@test.com", "password": "correct123",
        })
        resp = await async_client.post("/api/v1/auth/login", json={
            "username": "failuser", "password": "wrongpassword",
        })
        assert resp.status_code == 401


class TestMe:
    async def test_get_me(self, async_client):
        await async_client.post("/api/v1/auth/register", json={
            "username": "meuser", "email": "me@test.com", "password": "mepass123",
        })
        login_resp = await async_client.post("/api/v1/auth/login", json={
            "username": "meuser", "password": "mepass123",
        })
        token = login_resp.json()["access_token"]
        resp = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "meuser"

    async def test_me_without_token(self, async_client):
        resp = await async_client.get("/api/v1/auth/me")
        assert resp.status_code == 401


class TestRefresh:
    async def test_refresh_token(self, async_client):
        await async_client.post("/api/v1/auth/register", json={
            "username": "refreshuser", "email": "rf@test.com", "password": "test123456",
        })
        login_resp = await async_client.post("/api/v1/auth/login", json={
            "username": "refreshuser", "password": "test123456",
        })
        refresh_token = login_resp.json()["refresh_token"]
        resp = await async_client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_refresh_invalid(self, async_client):
        resp = await async_client.post("/api/v1/auth/refresh", json={
            "refresh_token": "invalid-token",
        })
        assert resp.status_code == 401


class TestLogout:
    async def test_logout(self, async_client):
        await async_client.post("/api/v1/auth/register", json={
            "username": "logoutuser", "email": "lo@test.com", "password": "test123456",
        })
        login_resp = await async_client.post("/api/v1/auth/login", json={
            "username": "logoutuser", "password": "test123456",
        })
        refresh_token = login_resp.json()["refresh_token"]
        resp = await async_client.post("/api/v1/auth/logout", json={
            "refresh_token": refresh_token,
        })
        assert resp.status_code == 200

        # After logout, refresh should fail
        resp = await async_client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert resp.status_code == 401


class TestRoles:
    async def test_create_role(self, async_client):
        await async_client.post("/api/v1/auth/register", json={
            "username": "roleadmin", "email": "role@test.com", "password": "test123456",
        })
        login_resp = await async_client.post("/api/v1/auth/login", json={
            "username": "roleadmin", "password": "test123456",
        })
        headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}
        resp = await async_client.post("/api/v1/auth/roles", json={
            "name": "Test Role", "code": "TEST-ROLE",
        }, headers=headers)
        assert resp.status_code == 201
        assert resp.json()["name"] == "Test Role"

    async def test_list_roles(self, async_client):
        await async_client.post("/api/v1/auth/register", json={
            "username": "rolelist", "email": "rlist@test.com", "password": "test123456",
        })
        login_resp = await async_client.post("/api/v1/auth/login", json={
            "username": "rolelist", "password": "test123456",
        })
        headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}
        resp = await async_client.get("/api/v1/auth/roles", headers=headers)
        assert resp.status_code == 200


class TestRoleErrorPaths:
    async def _login(self, async_client):
        suf = uuid.uuid4().hex[:6]
        await async_client.post("/api/v1/auth/register", json={
            "username": f"err-{suf}", "email": f"err-{suf}@t.com", "password": "p123456",
        })
        r = await async_client.post("/api/v1/auth/login", json={
            "username": f"err-{suf}", "password": "p123456",
        })
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    async def test_create_role_duplicate_code(self, async_client):
        h = await self._login(async_client)
        await async_client.post("/api/v1/auth/roles", json={
            "name": "First", "code": "ERR-DUP",
        }, headers=h)
        resp = await async_client.post("/api/v1/auth/roles", json={
            "name": "Second", "code": "ERR-DUP",
        }, headers=h)
        assert resp.status_code == 422

    async def test_update_role_not_found(self, async_client):
        h = await self._login(async_client)
        resp = await async_client.put(f"/api/v1/auth/roles/{uuid.uuid4()}", json={
            "name": "Nope",
        }, headers=h)
        assert resp.status_code == 404

    async def test_delete_role_not_found(self, async_client):
        h = await self._login(async_client)
        resp = await async_client.delete(f"/api/v1/auth/roles/{uuid.uuid4()}", headers=h)
        assert resp.status_code == 404

    async def test_create_permission_duplicate_code(self, async_client):
        h = await self._login(async_client)
        await async_client.post("/api/v1/auth/permissions", json={
            "name": "P1", "code": "P-ERR-DUP", "resource": "t", "action": "r",
        }, headers=h)
        resp = await async_client.post("/api/v1/auth/permissions", json={
            "name": "P2", "code": "P-ERR-DUP", "resource": "t", "action": "w",
        }, headers=h)
        assert resp.status_code == 422

    async def test_assign_role_user_not_found(self, async_client):
        h = await self._login(async_client)
        resp = await async_client.post(f"/api/v1/auth/users/{uuid.uuid4()}/roles", json={
            "role_id": str(uuid.uuid4()),
        }, headers=h)
        assert resp.status_code == 404

    async def test_remove_role_not_assigned(self, async_client):
        h = await self._login(async_client)
        resp = await async_client.delete(
            f"/api/v1/auth/users/{uuid.uuid4()}/roles/{uuid.uuid4()}", headers=h)
        assert resp.status_code == 404

    async def test_assign_permission_role_not_found(self, async_client):
        h = await self._login(async_client)
        resp = await async_client.post(f"/api/v1/auth/roles/{uuid.uuid4()}/permissions", json={
            "permission_id": str(uuid.uuid4()),
        }, headers=h)
        assert resp.status_code == 404

    async def test_remove_permission_not_assigned(self, async_client):
        h = await self._login(async_client)
        resp = await async_client.delete(
            f"/api/v1/auth/roles/{uuid.uuid4()}/permissions/{uuid.uuid4()}", headers=h)
        assert resp.status_code == 404
