"""Tests for security module — JWT creation, verification, password hashing."""
import pytest

from src.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    """Password hash and verify."""

    def test_hash_returns_different_value(self):
        h = hash_password("mypassword")
        assert h != "mypassword"
        assert h.startswith("$2b$")

    def test_verify_correct_password(self):
        h = hash_password("secret")
        assert verify_password("secret", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("secret")
        assert verify_password("wrong", h) is False

    def test_same_password_different_hash(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt salts are unique
        assert verify_password("same", h1)
        assert verify_password("same", h2)


class TestTokenCreation:
    """JWT token generation."""

    def test_create_access_token(self):
        data = {"sub": "user1", "uid": "abc-123"}
        token = create_access_token(data)
        assert isinstance(token, str)
        assert len(token) > 50

    def test_create_refresh_token(self):
        data = {"sub": "user1", "uid": "abc-123"}
        token = create_refresh_token(data)
        assert isinstance(token, str)
        assert len(token) > 50

    def test_tokens_are_different(self):
        data = {"sub": "test"}
        a = create_access_token(data)
        r = create_refresh_token(data)
        assert a != r

    def test_token_structure(self):
        """Valid JWT has 3 base64url segments separated by dots."""
        token = create_access_token({"sub": "x"})
        parts = token.split(".")
        assert len(parts) == 3


class TestTokenDecode:
    """JWT token validation."""

    def test_decode_valid_access_token(self):
        token = create_access_token({"sub": "decode-test"})
        payload = decode_token(token)
        assert "sub" in payload
        assert payload["sub"] == "decode-test"

    def test_decode_valid_refresh_token(self):
        token = create_refresh_token({"sub": "decode-refresh"})
        payload = decode_token(token)
        assert "sub" in payload
        assert payload["sub"] == "decode-refresh"

    def test_decode_tampered_token_returns_empty(self):
        token = create_access_token({"sub": "tamper"})
        parts = token.split(".")
        tampered = parts[0] + ".tampered." + parts[2]
        payload = decode_token(tampered)
        assert payload == {}  # decode_token returns {} on JWTError

    def test_decode_garbage_returns_empty(self):
        payload = decode_token("not-a-valid-jwt")
        assert payload == {}
