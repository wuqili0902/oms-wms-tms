"""Direct service-level tests for auth business logic.

Tests untested paths in src/auth/service.py and src/auth/token_store.py.
"""
import uuid

import pytest

from src.auth import service as auth_service
from src.auth.token_store import TokenStore, token_store
from src.core.exceptions import NotFoundException, ValidationException
from src.core.security import create_refresh_token


class TestRegisterUser:
    """User registration."""

    @pytest.mark.asyncio
    async def test_register_new_user(self, db_session):
        user = await auth_service.register_user(db_session, {
            "username": "newuser", "email": "new@test.com", "password": "secure123",
        })
        assert user["username"] == "newuser"
        assert "hashed_password" in user
        assert user["hashed_password"] != "secure123"

    @pytest.mark.asyncio
    async def test_register_duplicate_username(self, db_session):
        await auth_service.register_user(db_session, {"username": "dup", "email": "a@t.com", "password": "x"})
        with pytest.raises(ValidationException, match="already exists"):
            await auth_service.register_user(db_session, {"username": "dup", "email": "b@t.com", "password": "x"})

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, db_session):
        await auth_service.register_user(db_session, {"username": "u1", "email": "same@t.com", "password": "x"})
        with pytest.raises(ValidationException, match="already exists"):
            await auth_service.register_user(db_session, {"username": "u2", "email": "same@t.com", "password": "x"})


class TestAuthenticateUser:
    """Login authentication."""

    @pytest.mark.asyncio
    async def test_authenticate_valid(self, db_session):
        await auth_service.register_user(db_session, {"username": "authme", "email": "auth@t.com", "password": "pass123"})
        user = await auth_service.authenticate_user(db_session, "authme", "pass123")
        assert user is not None
        assert user["username"] == "authme"

    @pytest.mark.asyncio
    async def test_authenticate_wrong_password(self, db_session):
        await auth_service.register_user(db_session, {"username": "wp", "email": "wp@t.com", "password": "correct"})
        user = await auth_service.authenticate_user(db_session, "wp", "wrong")
        assert user is None

    @pytest.mark.asyncio
    async def test_authenticate_nonexistent(self, db_session):
        user = await auth_service.authenticate_user(db_session, "nobody", "pass")
        assert user is None

    @pytest.mark.asyncio
    async def test_authenticate_inactive_user(self, db_session):
        created = await auth_service.register_user(db_session, {"username": "inact", "email": "ia@t.com", "password": "x"})
        # Deactivate the user directly
        from src.auth.models import User
        from sqlalchemy import select
        result = await db_session.execute(select(User).where(User.id == uuid.UUID(created["id"])))
        u = result.scalar_one()
        u.is_active = False
        await db_session.commit()
        user = await auth_service.authenticate_user(db_session, "inact", "x")
        assert user is None


class TestUserQueries:
    """User retrieval and listing."""

    @pytest.mark.asyncio
    async def test_get_user_by_id(self, db_session):
        created = await auth_service.register_user(db_session, {"username": "byid", "email": "id@t.com", "password": "x"})
        user = await auth_service.get_user_by_id(db_session, created["id"])
        assert user["username"] == "byid"

    @pytest.mark.asyncio
    async def test_get_user_by_id_not_found(self, db_session):
        with pytest.raises(NotFoundException):
            await auth_service.get_user_by_id(db_session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_get_user_by_username(self, db_session):
        await auth_service.register_user(db_session, {"username": "byname", "email": "bn@t.com", "password": "x"})
        user = await auth_service.get_user_by_username(db_session, "byname")
        assert user is not None
        assert user["username"] == "byname"

    @pytest.mark.asyncio
    async def test_get_user_by_username_not_found(self, db_session):
        user = await auth_service.get_user_by_username(db_session, "nobody")
        assert user is None

    @pytest.mark.asyncio
    async def test_list_users(self, db_session):
        await auth_service.register_user(db_session, {"username": "lu1", "email": "lu1@t.com", "password": "x"})
        await auth_service.register_user(db_session, {"username": "lu2", "email": "lu2@t.com", "password": "x"})
        users = await auth_service.list_users(db_session)
        assert len(users) >= 2


class TestTokenManagement:
    """JWT token creation, refresh, revoke."""

    @pytest.mark.asyncio
    async def test_create_tokens(self, db_session):
        created = await auth_service.register_user(db_session, {"username": "tok", "email": "tok@t.com", "password": "x"})
        tokens = await auth_service.create_tokens(created)
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert len(tokens["access_token"]) > 0
        assert len(tokens["refresh_token"]) > 0

    @pytest.mark.asyncio
    async def test_refresh_tokens(self, db_session):
        created = await auth_service.register_user(db_session, {"username": "rot", "email": "rot@t.com", "password": "x"})
        tokens = await auth_service.create_tokens(created)
        new_tokens = await auth_service.refresh_tokens(tokens["refresh_token"])
        assert new_tokens is not None
        assert "access_token" in new_tokens
        assert "refresh_token" in new_tokens
        # Refresh token should be rotated (old one consumed)
        assert len(new_tokens["refresh_token"]) > 0

    @pytest.mark.asyncio
    async def test_refresh_with_invalid_token(self, db_session):
        result = await auth_service.refresh_tokens("invalid-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_refresh_already_revoked(self, db_session):
        created = await auth_service.register_user(db_session, {"username": "rev", "email": "rev@t.com", "password": "x"})
        tokens = await auth_service.create_tokens(created)
        await auth_service.revoke_refresh_token(tokens["refresh_token"])
        result = await auth_service.refresh_tokens(tokens["refresh_token"])
        assert result is None


class TestRoles:
    """Role CRUD."""

    @pytest.mark.asyncio
    async def test_create_role(self, db_session):
        role = await auth_service.create_role(db_session, {"name": "Operator", "code": "op"})
        assert role["code"] == "op"

    @pytest.mark.asyncio
    async def test_create_duplicate_role_code(self, db_session):
        await auth_service.create_role(db_session, {"name": "First", "code": "dup-role"})
        with pytest.raises(ValidationException, match="already exists"):
            await auth_service.create_role(db_session, {"name": "Second", "code": "dup-role"})

    @pytest.mark.asyncio
    async def test_list_roles(self, db_session):
        await auth_service.create_role(db_session, {"name": "Admin", "code": "admin"})
        await auth_service.create_role(db_session, {"name": "User", "code": "user"})
        roles = await auth_service.list_roles(db_session)
        assert len(roles) >= 2


class TestPermissions:
    """Permission listing."""

    @pytest.mark.asyncio
    async def test_list_permissions(self, db_session):
        perms = await auth_service.list_permissions(db_session)
        assert isinstance(perms, list)
