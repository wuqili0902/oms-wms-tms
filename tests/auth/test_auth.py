"""Tests for auth endpoints using synchronous TestClient.

The auth router stores users in memory and doesn't need a database,
so we can test it with the FastAPI TestClient directly.
"""

import pytest
from fastapi.testclient import TestClient
from src.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_register(client):
    resp = client.post("/api/v1/auth/register", json={
        "username": "testuser",
        "email": "user@test.com",
        "password": "test123456",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "testuser"
    assert data["is_active"] is True


def test_login(client):
    client.post("/api/v1/auth/register", json={
        "username": "loginuser",
        "email": "login@test.com",
        "password": "pass123456",
    })
    resp = client.post("/api/v1/auth/login", json={
        "username": "loginuser",
        "password": "pass123456",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


def test_login_invalid_password(client):
    client.post("/api/v1/auth/register", json={
        "username": "failuser",
        "email": "fail@test.com",
        "password": "correct123",
    })
    resp = client.post("/api/v1/auth/login", json={
        "username": "failuser",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


def test_get_me(client):
    client.post("/api/v1/auth/register", json={
        "username": "meuser",
        "email": "me@test.com",
        "password": "mepass123",
    })
    login_resp = client.post("/api/v1/auth/login", json={
        "username": "meuser",
        "password": "mepass123",
    })
    token = login_resp.json()["access_token"]
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "meuser"


def test_me_without_token(client):
    resp = client.get("/api/v1/auth/me")
    # HTTPBearer returns 401 when no credentials provided
    assert resp.status_code == 401
