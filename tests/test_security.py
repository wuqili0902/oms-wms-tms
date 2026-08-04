"""Tests for src.core.security — password hashing, JWT creation and decoding."""

from datetime import UTC, datetime, timedelta

import pytest

from src.core.security import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    TokenExpired,
    TokenInvalid,
    async_hash_password,
    async_verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self):
        pw = "super-secret-123"
        hashed = hash_password(pw)
        assert hashed != pw
        assert verify_password(pw, hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct-pw")
        assert verify_password("wrong-pw", hashed) is False

    def test_verify_invalid_hash_format(self):
        assert verify_password("pw", "not-a-valid-hash") is False

    def test_verify_empty_strings(self):
        hashed = hash_password("")
        assert verify_password("", hashed) is True

    def test_hash_produces_different_salts(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2


class TestAsyncPasswordHashing:
    @pytest.mark.asyncio
    async def test_async_hash_and_verify(self):
        pw = "async-pw-456"
        hashed = await async_hash_password(pw)
        assert hashed != pw
        assert await async_verify_password(pw, hashed) is True

    @pytest.mark.asyncio
    async def test_async_verify_wrong(self):
        hashed = await async_hash_password("real")
        assert await async_verify_password("fake", hashed) is False

    @pytest.mark.asyncio
    async def test_async_verify_bad_hash(self):
        assert await async_verify_password("pw", "badhash") is False


class TestJWT:
    def test_create_and_decode_access_token(self):
        data = {"sub": "user123", "role": "admin"}
        token = create_access_token(data)
        assert isinstance(token, str)
        assert token.count(".") == 2
        payload = decode_token(token)
        assert payload["sub"] == "user123"
        assert payload["role"] == "admin"
        assert "exp" in payload

    def test_create_refresh_token(self):
        data = {"sub": "user456"}
        token = create_refresh_token(data)
        payload = decode_token(token)
        assert payload["sub"] == "user456"
        assert "exp" in payload

    def test_access_token_custom_expiry(self):
        data = {"sub": "short-lived"}
        token = create_access_token(data, expires_delta=timedelta(seconds=1))
        payload = decode_token(token)
        assert payload["sub"] == "short-lived"

    def test_decode_expired_token(self):
        data = {"sub": "expired-user", "exp": datetime.now(UTC) - timedelta(hours=1)}
        from jose import jwt

        from src.config import settings
        token = jwt.encode(data, settings.secret_key, algorithm="HS256")
        with pytest.raises(TokenExpired):
            decode_token(token)

    def test_decode_invalid_signature(self):
        data = {"sub": "bad-sig", "exp": datetime.now(UTC) + timedelta(hours=1)}
        from jose import jwt
        token = jwt.encode(data, "wrong-secret", algorithm="HS256")
        with pytest.raises(TokenInvalid):
            decode_token(token)

    def test_decode_malformed_token(self):
        with pytest.raises(TokenInvalid):
            decode_token("not-a-jwt")

    def test_refresh_token_longer_expiry(self):
        data = {"sub": "user"}
        token = create_refresh_token(data)
        payload = decode_token(token)
        access = create_access_token(data)
        access_payload = decode_token(access)
        refresh_exp = payload["exp"]
        access_exp = access_payload["exp"]
        expected = datetime.now(UTC).timestamp() + REFRESH_TOKEN_EXPIRE_DAYS * 86400
        assert abs(refresh_exp - expected) < 5
        assert refresh_exp > access_exp

    def test_token_contains_original_data(self):
        data = {"sub": "u1", "scope": "read write"}
        token = create_access_token(data)
        payload = decode_token(token)
        assert payload["scope"] == "read write"

    def test_create_access_token_without_exp(self):
        data = {"sub": "no-exp-set"}
        token = create_access_token(data)
        payload = decode_token(token)
        assert "exp" in payload
