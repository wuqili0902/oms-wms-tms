"""Tests for pagination responses and ApiResponse envelope across modules."""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio

P = "/api/v1"


@pytest.fixture
async def auth(async_client):
    """Register + login, return headers dict."""
    session = async_client._shared_session
    # Seed RBAC
    from sqlalchemy import select as sa_select

    from src.auth.models import Permission, Role
    from src.models import Base
    existing = await session.execute(
        sa_select(Role.id).join(Role.permissions).where(Permission.code == "admin.rbac.manage")
    )
    row = existing.first()
    if row:
        role_id = row[0]
    else:
        perm = Permission(name="RBAC", code="admin.rbac.manage", resource="admin", action="rbac.manage")
        session.add(perm)
        role = Role(name="Admin", code="ADMIN")
        session.add(role)
        await session.flush()
        rp = Base.metadata.tables["role_permissions"]
        await session.execute(rp.insert().values(role_id=role.id, permission_id=perm.id))
        await session.flush()
        role_id = role.id

    uname = f"pg_{uuid.uuid4().hex[:6]}"
    await async_client.post(f"{P}/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })

    from src.auth.models import User
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
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════════
# 1. Auth router pagination
# ══════════════════════════════════════════════════════════════════════════


class TestAuthPagination:
    """Verify auth list endpoints return correct structure."""

    async def test_list_users_returns_list(self, async_client, auth):
        r = await async_client.get(f"{P}/auth/users", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_list_roles_returns_list(self, async_client, auth):
        r = await async_client.get(f"{P}/auth/roles", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    async def test_list_permissions_returns_list(self, async_client, auth):
        r = await async_client.get(f"{P}/auth/permissions", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert any(p["code"] == "admin.rbac.manage" for p in data)


# ══════════════════════════════════════════════════════════════════════════
# 2. WMS pagination
# ══════════════════════════════════════════════════════════════════════════


class TestWmsPagination:
    """Verify WMS list endpoints return correct paginated structure."""

    async def test_list_warehouses_paginated(self, async_client, auth):
        r = await async_client.get(f"{P}/warehouses", headers=auth)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "total" in body


# ══════════════════════════════════════════════════════════════════════════
# 3. TMS pagination
# ══════════════════════════════════════════════════════════════════════════


class TestTmsPagination:
    """Verify TMS list endpoints return correct paginated structure."""

    async def test_list_devices_paginated(self, async_client, auth):
        r = await async_client.get(f"{P}/devices", headers=auth)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "total" in body
        assert isinstance(body["items"], list)


# ══════════════════════════════════════════════════════════════════════════
# 4. Barcode list endpoints
# ══════════════════════════════════════════════════════════════════════════


class TestBarcodePagination:
    """Verify barcode list endpoints return correct structure."""

    async def test_list_templates_returns_list(self, async_client, auth):
        r = await async_client.get(f"{P}/barcode/templates", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    async def test_validate_returns_valid_field(self, async_client, auth):
        r = await async_client.post(f"{P}/barcode/validate", headers=auth,
                                    json={"gtin": "8901234567890"})
        assert r.status_code == 200
        body = r.json()
        assert "valid" in body or "is_valid" in body


# ══════════════════════════════════════════════════════════════════════════
# 5. OMS order history returns list
# ══════════════════════════════════════════════════════════════════════════


class TestOmsPagination:
    """Verify OMS endpoints return correct structure."""

    async def test_list_orders_paginated(self, async_client, auth):
        r = await async_client.get(f"{P}/orders", headers=auth)
        assert r.status_code == 200
        body = r.json()
        assert "total" in body
        assert "items" in body or "page" in body
