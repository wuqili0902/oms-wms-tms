"""Supplementary unit tests for auth/service.py.

Covers: authenticate_user (success + wrong password), create_tokens,
revoke_refresh_token — the 3 functions lacking direct unit tests.
"""
import uuid

import pytest

from src.auth.service import (
    authenticate_user,
    create_tokens,
    register_user,
    revoke_refresh_token,
)


async def _register_user(db_session):
    """Helper: register a user and return its dict."""
    suffix = uuid.uuid4().hex[:6]
    return await register_user(db_session, {
        "username": f"authtest-{suffix}",
        "email": f"auth-{suffix}@test.com",
        "password": "test123456",
    })


class TestAuthenticateUser:
    """authenticate_user — verify credentials."""

    @pytest.mark.asyncio
    async def test_authenticate_success(self, db_session):
        user = await _register_user(db_session)
        result = await authenticate_user(
            db_session, user["username"], "test123456"
        )
        assert result is not None
        assert result["username"] == user["username"]

    @pytest.mark.asyncio
    async def test_authenticate_wrong_password(self, db_session):
        user = await _register_user(db_session)
        result = await authenticate_user(
            db_session, user["username"], "wrong_password"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_nonexistent_user(self, db_session):
        result = await authenticate_user(
            db_session, "nonexistent_user_xyz", "any_password"
        )
        assert result is None


class TestCreateTokens:
    """create_tokens — generate access + refresh token pair."""

    @pytest.mark.asyncio
    async def test_create_tokens_returns_pair(self, db_session):
        user = await _register_user(db_session)
        tokens = await create_tokens(user)
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert len(tokens["access_token"]) > 20
        assert len(tokens["refresh_token"]) > 20

    @pytest.mark.asyncio
    async def test_tokens_are_different(self, db_session):
        user = await _register_user(db_session)
        tokens = await create_tokens(user)
        assert tokens["access_token"] != tokens["refresh_token"]


class TestRevokeRefreshToken:
    """revoke_refresh_token — remove refresh token from store."""

    @pytest.mark.asyncio
    async def test_revoke_refresh_token(self, db_session):
        user = await _register_user(db_session)
        tokens = await create_tokens(user)
        # Should not raise
        await revoke_refresh_token(tokens["refresh_token"])

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_token(self, db_session):
        # Revoking a token that doesn't exist should not raise
        await revoke_refresh_token("nonexistent-token-value")
