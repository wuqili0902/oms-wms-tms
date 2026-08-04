from datetime import timedelta

import pytest

from src.config import settings
from src.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
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


class TestConstants:
    def test_algorithm(self):
        assert ALGORITHM == "HS256"

    def test_access_token_expire_minutes(self):
        assert ACCESS_TOKEN_EXPIRE_MINUTES == 60

    def test_refresh_token_expire_days(self):
        assert REFRESH_TOKEN_EXPIRE_DAYS == 7


class TestVerifyPassword:
    def test_correct_password(self):
        pwd = "secret123"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed) is True

    def test_incorrect_password(self):
        hashed = hash_password("real_password")
        assert verify_password("wrong_password", hashed) is False

    def test_invalid_hash_returns_false(self):
        assert verify_password("any", "not-a-valid-hash") is False


class TestHashPassword:
    def test_returns_different_salt_each_time(self):
        pwd = "mypassword"
        h1 = hash_password(pwd)
        h2 = hash_password(pwd)
        assert h1 != h2
        assert verify_password(pwd, h1) is True
        assert verify_password(pwd, h2) is True


class TestAsyncHashPassword:
    async def test_async_hash(self):
        pwd = "async_test"
        hashed = await async_hash_password(pwd)
        assert verify_password(pwd, hashed) is True

    async def test_async_verify_correct(self):
        pwd = "async_verify"
        hashed = hash_password(pwd)
        result = await async_verify_password(pwd, hashed)
        assert result is True

    async def test_async_verify_incorrect(self):
        hashed = hash_password("real")
        result = await async_verify_password("wrong", hashed)
        assert result is False


class TestCreateAccessToken:
    def test_creates_token(self):
        token = create_access_token({"sub": "user-1"})
        assert isinstance(token, str)
        assert len(token.split(".")) == 3

    def test_custom_expiry(self):
        token = create_access_token({"sub": "user-2"}, expires_delta=timedelta(hours=1))
        payload = decode_token(token)
        assert payload["sub"] == "user-2"

    def test_default_expiry(self):
        token = create_access_token({"sub": "user-3"})
        payload = decode_token(token)
        assert payload["sub"] == "user-3"


class TestCreateRefreshToken:
    def test_creates_refresh_token(self):
        token = create_refresh_token({"sub": "user-1"})
        assert isinstance(token, str)
        assert len(token.split(".")) == 3

    def test_refresh_token_has_sub(self):
        token = create_refresh_token({"sub": "user-2"})
        payload = decode_token(token)
        assert payload["sub"] == "user-2"

    def test_access_and_refresh_are_different(self):
        access = create_access_token({"sub": "user-1"})
        refresh = create_refresh_token({"sub": "user-1"})
        assert access != refresh


class TestDecodeToken:
    def test_valid_token(self):
        token = create_access_token({"sub": "user-1", "role": "admin"})
        payload = decode_token(token)
        assert payload["sub"] == "user-1"
        assert payload["role"] == "admin"

    def test_expired_token(self):
        from datetime import UTC, datetime

        from jose import jwt
        expired = jwt.encode(
            {"sub": "user-1", "exp": datetime.now(UTC) - timedelta(hours=1)},
            settings.secret_key, algorithm=ALGORITHM,
        )
        with pytest.raises(TokenExpired):
            decode_token(expired)

    def test_invalid_signature(self):
        from datetime import UTC, datetime

        from jose import jwt
        bad = jwt.encode(
            {"sub": "user-1", "exp": datetime.now(UTC) + timedelta(hours=1)},
            "wrong-secret", algorithm=ALGORITHM,
        )
        with pytest.raises(TokenInvalid):
            decode_token(bad)

    def test_malformed_token(self):
        with pytest.raises(TokenInvalid):
            decode_token("not-a-jwt-token")


class TestTokenExceptions:
    def test_token_expired_is_exception(self):
        assert issubclass(TokenExpired, Exception)

    def test_token_invalid_is_exception(self):
        assert issubclass(TokenInvalid, Exception)
