"""Tests for TokenStore — in-memory fallback paths.

Tests all public API methods using the in-memory store (Redis disabled).
"""
import pytest

from src.auth.token_store import TokenStore


@pytest.fixture
def store():
    """Fresh TokenStore with Redis disabled (forces in-memory path)."""
    ts = TokenStore()
    ts._redis_ok = False  # force in-memory mode
    return ts


class TestStore:
    """TokenStore.store() — persist refresh token."""

    @pytest.mark.asyncio
    async def test_store_new_token(self, store):
        await store.store("token-1", "user-a")
        assert await store.lookup("token-1") == "user-a"

    @pytest.mark.asyncio
    async def test_store_overwrite(self, store):
        await store.store("token-1", "user-a")
        await store.store("token-1", "user-b")
        assert await store.lookup("token-1") == "user-b"

    @pytest.mark.asyncio
    async def test_store_multiple_users(self, store):
        await store.store("t1", "alice")
        await store.store("t2", "bob")
        assert await store.lookup("t1") == "alice"
        assert await store.lookup("t2") == "bob"


class TestLookup:
    """TokenStore.lookup() — retrieve username by token."""

    @pytest.mark.asyncio
    async def test_lookup_existing(self, store):
        await store.store("tok", "charlie")
        assert await store.lookup("tok") == "charlie"

    @pytest.mark.asyncio
    async def test_lookup_missing(self, store):
        assert await store.lookup("nonexistent") is None

    @pytest.mark.asyncio
    async def test_lookup_empty_store(self, store):
        assert await store.lookup("anything") is None


class TestRevoke:
    """TokenStore.revoke() — remove a token."""

    @pytest.mark.asyncio
    async def test_revoke_existing(self, store):
        await store.store("tok", "dave")
        await store.revoke("tok")
        assert await store.lookup("tok") is None

    @pytest.mark.asyncio
    async def test_revoke_missing_no_error(self, store):
        await store.revoke("nonexistent")  # should not raise

    @pytest.mark.asyncio
    async def test_revoke_only_target(self, store):
        await store.store("t1", "a")
        await store.store("t2", "b")
        await store.revoke("t1")
        assert await store.lookup("t1") is None
        assert await store.lookup("t2") == "b"


class TestPop:
    """TokenStore.pop() — atomic lookup + revoke (token rotation)."""

    @pytest.mark.asyncio
    async def test_pop_returns_username(self, store):
        await store.store("rotating", "eve")
        username = await store.pop("rotating")
        assert username == "eve"

    @pytest.mark.asyncio
    async def test_pop_revokes_token(self, store):
        await store.store("rotating", "eve")
        await store.pop("rotating")
        assert await store.lookup("rotating") is None

    @pytest.mark.asyncio
    async def test_pop_missing_returns_none(self, store):
        assert await store.pop("nonexistent") is None

    @pytest.mark.asyncio
    async def test_pop_idempotent(self, store):
        await store.store("once", "frank")
        await store.pop("once")
        assert await store.pop("once") is None


class TestKeyDerivation:
    """TokenStore._key() — deterministic key from JWT."""

    def test_same_input_same_key(self, store):
        k1 = store._key("my-refresh-token")
        k2 = store._key("my-refresh-token")
        assert k1 == k2

    def test_different_input_different_key(self, store):
        k1 = store._key("token-a")
        k2 = store._key("token-b")
        assert k1 != k2

    def test_key_prefix(self, store):
        k = store._key("any-token")
        assert k.startswith("rt:")

    def test_key_length(self, store):
        k = store._key("some-token")
        assert len(k) == 19  # "rt:" prefix (3) + 16 hex chars
