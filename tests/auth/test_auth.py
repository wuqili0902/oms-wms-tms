"""Tests for auth endpoints — async HTTP integration tests with SQLite in-memory."""
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
