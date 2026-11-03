"""The RBAC writes: an id the caller sent is checked, not trusted.

The role/permission screens post a body the handler read as a bare ``dict`` —
``data["role_id"]``, ``data["permission_id"]`` — so a request that arrived
without that key was a ``KeyError`` inside the handler: 500, a sentence about
the server, and nothing naming the field the caller had to fill in.  The ids
that did arrive went into ``uuid.UUID(role_id)`` in the middle of the query
work, so an id copied from an old bookmark — the panel links roles and users by
id, so a stale one is the ordinary input — raised ``ValueError`` in the service
and reached the operator the same way.  ``POST /auth/users/{id}/toggle`` built
the uuid in the route itself, and the admin panel's own
``/admin/users/{id}/toggle`` and ``/admin/users/{id}/delete`` did the same.

Now: the key is a typed field, so a request without it is refused before the
handler runs; an id that is not an id is a 422 naming the field that carried it;
an id that is one, for a role or user that is not there, is a 404 that says so;
and an HTML panel route is answered with the same answer as a row that is not in
the list — 404, not the server-error page.
"""

import uuid as uuid_mod

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture
async def rbac_admin(async_client) -> dict:
    """A user holding ``admin.rbac.manage`` and ``admin.user.manage``."""
    uname = f"rbacctr_{uuid_mod.uuid4().hex[:8]}"
    reg = await async_client.post("/api/v1/auth/register", json={
        "username": uname, "email": f"{uname}@test.com", "password": "test123456",
    })
    assert reg.status_code == 201, reg.text
    user_id = reg.json()["id"]

    from sqlalchemy import select

    from src.auth.models import Permission, Role, RolePermission, UserRole

    session = async_client._shared_session
    role = Role(id=uuid_mod.uuid4(), name=f"RBAC-{uname}", code=f"rbac_{uname}")
    session.add(role)
    for code, action in (("admin.rbac.manage", "rbac_manage"), ("admin.user.manage", "user_manage")):
        existing = await session.execute(select(Permission).where(Permission.code == code))
        perm = existing.scalar_one_or_none()
        if perm is None:
            perm = Permission(id=uuid_mod.uuid4(), name=code, code=code, resource="admin", action=action)
            session.add(perm)
            await session.flush()
        session.add(RolePermission(role_id=role.id, permission_id=perm.id))
    session.add(UserRole(user_id=uuid_mod.UUID(user_id), role_id=role.id))
    await session.flush()

    login = await async_client.post("/api/v1/auth/login", json={"username": uname, "password": "test123456"})
    token = login.json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "user_id": user_id, "role_id": str(role.id)}


@pytest.fixture(autouse=True)
async def _authenticated(async_client, rbac_admin):
    async_client.headers.update(rbac_admin["headers"])
    yield


@pytest.fixture
async def spare_role(async_client) -> dict:
    """A role nothing is assigned to, created the way the panel creates one."""
    code = f"spare_{uuid_mod.uuid4().hex[:8]}"
    resp = await async_client.post("/api/v1/auth/roles", json={
        "name": f"角色 {code}", "code": code, "description": "分配测试",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def spare_permission(async_client) -> dict:
    code = f"perm_{uuid_mod.uuid4().hex[:8]}"
    resp = await async_client.post("/api/v1/auth/permissions", json={
        "name": f"权限 {code}", "code": code, "resource": "wms", "action": "pick",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def admin_csrf(async_client, rbac_admin) -> dict:
    """The panel's CSRF pair: the cookie the middleware reads, and the header it checks.

    The cookie is set ``secure`` outside debug, so the http test client keeps it out
    of its jar and the POST has to carry it explicitly.
    """
    resp = await async_client.get("/admin/")
    assert resp.status_code == 200, resp.text
    token = resp.cookies.get("csrf_token")
    if not token:
        pytest.skip("CSRF cookie not set")
    # The cookie travels per request: the response set it ``secure``, so the http
    # test client keeps it out of its jar, and a POST would fail CSRF for a
    # reason that has nothing to do with the route under test.
    return {"headers": {"X-CSRF-Token": token}, "cookies": {"csrf_token": token}}


def _fields(resp) -> str:
    """Everything the server named in its refusal: field, message, sent value."""
    body = resp.json()
    err = body.get("error") or {}
    parts = [str(err.get("message") or ""), str(body.get("detail") or "")]
    for entry in (body.get("errors") or err.get("errors") or []):
        parts.append(str(entry.get("field")))
        parts.append(str(entry.get("message")))
        parts.append(str(entry.get("value")))
    return " ".join(parts)


BAD_UUID = "00000000-0000-0000-0000-000000000000"
NOT_AN_ID = "role-12"


# ── POST /auth/users/{user_id}/roles ────────────────────────────────────────


class TestAssignRoleBody:
    async def test_assigning_a_role_works(self, async_client, rbac_admin, spare_role):
        resp = await async_client.post(
            f"/api/v1/auth/users/{rbac_admin['user_id']}/roles",
            json={"role_id": spare_role["id"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["role_id"] == spare_role["id"]

    async def test_a_body_without_the_role_key_names_the_key(self, async_client, rbac_admin):
        """``data["role_id"]`` on a body that has no such key was a KeyError in the handler."""
        resp = await async_client.post(f"/api/v1/auth/users/{rbac_admin['user_id']}/roles", json={})
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
        assert "role_id" in _fields(resp)

    async def test_an_id_that_is_not_an_id_names_the_field_and_the_value(self, async_client, rbac_admin):
        resp = await async_client.post(
            f"/api/v1/auth/users/{rbac_admin['user_id']}/roles", json={"role_id": NOT_AN_ID},
        )
        assert resp.status_code == 422, resp.text
        fields = _fields(resp)
        assert "role_id" in fields
        assert NOT_AN_ID in fields

    async def test_a_role_that_is_not_there_is_not_found(self, async_client, rbac_admin):
        resp = await async_client.post(
            f"/api/v1/auth/users/{rbac_admin['user_id']}/roles", json={"role_id": BAD_UUID},
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    async def test_a_user_id_that_is_not_an_id_is_refused_in_the_path(self, async_client):
        resp = await async_client.post("/api/v1/auth/users/not-a-uuid/roles", json={"role_id": BAD_UUID})
        assert resp.status_code == 422, resp.text
        assert "user_id" in _fields(resp)

    async def test_assigning_the_same_role_twice_says_so(self, async_client, rbac_admin, spare_role):
        body = {"role_id": spare_role["id"]}
        first = await async_client.post(f"/api/v1/auth/users/{rbac_admin['user_id']}/roles", json=body)
        assert first.status_code == 200, first.text
        second = await async_client.post(f"/api/v1/auth/users/{rbac_admin['user_id']}/roles", json=body)
        assert second.status_code == 422, second.text
        assert "already" in _fields(second).lower()

    async def test_the_data_envelope_is_accepted(self, async_client, rbac_admin, spare_role):
        resp = await async_client.post(
            f"/api/v1/auth/users/{rbac_admin['user_id']}/roles",
            json={"data": {"role_id": spare_role["id"]}},
        )
        assert resp.status_code == 200, resp.text

    async def test_a_key_the_assignment_does_not_have_is_refused_by_name(self, async_client, rbac_admin, spare_role):
        resp = await async_client.post(
            f"/api/v1/auth/users/{rbac_admin['user_id']}/roles",
            json={"role_id": spare_role["id"], "expires_at": "2026-01-01"},
        )
        assert resp.status_code == 422, resp.text
        assert "expires_at" in _fields(resp)

    async def test_removing_a_role_with_an_id_that_is_not_one_is_refused(self, async_client, rbac_admin):
        resp = await async_client.delete(f"/api/v1/auth/users/{rbac_admin['user_id']}/roles/{NOT_AN_ID}")
        assert resp.status_code == 422, resp.text
        assert "role_id" in _fields(resp)


# ── POST /auth/roles/{role_id}/permissions ──────────────────────────────────


class TestAssignPermissionBody:
    async def test_granting_a_permission_works(self, async_client, spare_role, spare_permission):
        resp = await async_client.post(
            f"/api/v1/auth/roles/{spare_role['id']}/permissions",
            json={"permission_id": spare_permission["id"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["permission_id"] == spare_permission["id"]

    async def test_a_body_without_the_permission_key_names_the_key(self, async_client, spare_role):
        resp = await async_client.post(f"/api/v1/auth/roles/{spare_role['id']}/permissions", json={})
        assert resp.status_code == 422, resp.text
        assert "permission_id" in _fields(resp)

    async def test_an_id_that_is_not_an_id_names_the_field_and_the_value(self, async_client, spare_role):
        resp = await async_client.post(
            f"/api/v1/auth/roles/{spare_role['id']}/permissions", json={"permission_id": NOT_AN_ID},
        )
        assert resp.status_code == 422, resp.text
        fields = _fields(resp)
        assert "permission_id" in fields and NOT_AN_ID in fields

    async def test_a_permission_that_is_not_there_is_not_found(self, async_client, spare_role):
        resp = await async_client.post(
            f"/api/v1/auth/roles/{spare_role['id']}/permissions", json={"permission_id": BAD_UUID},
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    async def test_granting_twice_says_so(self, async_client, spare_role, spare_permission):
        body = {"permission_id": spare_permission["id"]}
        assert (await async_client.post(f"/api/v1/auth/roles/{spare_role['id']}/permissions",
                                        json=body)).status_code == 200
        second = await async_client.post(f"/api/v1/auth/roles/{spare_role['id']}/permissions", json=body)
        assert second.status_code == 422, second.text
        assert "already" in _fields(second).lower()

    async def test_revoking_with_an_id_that_is_not_one_is_refused(self, async_client, spare_role):
        resp = await async_client.delete(f"/api/v1/auth/roles/{spare_role['id']}/permissions/{NOT_AN_ID}")
        assert resp.status_code == 422, resp.text
        assert "permission_id" in _fields(resp)


# ── POST /auth/users/{user_id}/toggle ───────────────────────────────────────


class TestToggleUserBody:
    async def test_toggling_flips_the_flag(self, async_client, rbac_admin):
        before = await async_client.get("/api/v1/auth/me")
        assert before.json()["is_active"] is True
        resp = await async_client.post(f"/api/v1/auth/users/{rbac_admin['user_id']}/toggle")
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_active"] is False

    async def test_an_id_that_is_not_an_id_is_not_a_server_failure(self, async_client):
        """The route built ``uuid.UUID(user_id)`` itself, so a typed-wrong id was a 500."""
        resp = await async_client.post("/api/v1/auth/users/the-users-id/toggle")
        assert resp.status_code == 422, resp.text
        fields = _fields(resp)
        assert "user_id" in fields and "the-users-id" in fields

    async def test_a_user_that_is_not_there_is_not_found(self, async_client):
        resp = await async_client.post(f"/api/v1/auth/users/{BAD_UUID}/toggle")
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND"


# ── The HTML admin panel's user routes ──────────────────────────────────────


class TestAdminPanelUserRoutes:
    """``/admin/users/{id}/…`` are HTML form posts; the panel builds those links
    out of the ids the list shows, and the routes built ``uuid.UUID(user_id)``
    themselves — a half-copied id was the server-error page."""

    async def test_toggle_with_an_id_that_is_not_one_is_no_such_user(self, async_client, admin_csrf):
        resp = await async_client.post(
            "/admin/users/27/toggle",
            headers=admin_csrf["headers"], cookies=admin_csrf["cookies"],
            follow_redirects=False,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    async def test_delete_with_an_id_that_is_not_one_is_no_such_user(self, async_client, admin_csrf):
        resp = await async_client.post(
            "/admin/users/27/delete",
            headers=admin_csrf["headers"], cookies=admin_csrf["cookies"],
            follow_redirects=False,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    async def test_a_real_user_toggles_and_stays_toggled(self, async_client, rbac_admin, admin_csrf):
        first = await async_client.post(
            f"/admin/users/{rbac_admin['user_id']}/toggle",
            headers=admin_csrf["headers"], cookies=admin_csrf["cookies"],
            follow_redirects=False,
        )
        assert first.status_code in (200, 303), first.text
        from sqlalchemy import select

        from src.auth.models import User

        result = await async_client._shared_session.execute(
            select(User.is_active).where(User.id == uuid_mod.UUID(rbac_admin["user_id"]))
        )
        assert result.scalar_one() is False
