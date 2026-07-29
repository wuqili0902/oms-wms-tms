"""Tests for token store — in-memory fallback and Redis→memory degradation."""
from unittest.mock import AsyncMock, patch

import pytest

from src.auth.token_store import REFRESH_TOKEN_TTL, TokenStore


class TestTokenStoreInMemory:
    @pytest.fixture
    def store(self):
        s = TokenStore()
        s._redis_ok = False
        return s

    async def test_store_and_lookup(self, store):
        await store.store("refresh-token-1", "alice")
        result = await store.lookup("refresh-token-1")
        assert result == "alice"

    async def test_lookup_missing(self, store):
        result = await store.lookup("nonexistent")
        assert result is None

    async def test_pop_returns_username_and_removes(self, store):
        await store.store("rt-2", "bob")
        username = await store.pop("rt-2")
        assert username == "bob"
        assert await store.lookup("rt-2") is None

    async def test_pop_missing(self, store):
        result = await store.pop("ghost")
        assert result is None

    async def test_revoke_removes_token(self, store):
        await store.store("rt-3", "carol")
        await store.revoke("rt-3")
        assert await store.lookup("rt-3") is None

    async def test_revoke_nonexistent(self, store):
        await store.revoke("nothing")
        assert await store.lookup("nothing") is None

    async def test_multiple_tokens_same_user(self, store):
        await store.store("rt-a", "dave")
        await store.store("rt-b", "dave")
        assert await store.lookup("rt-a") == "dave"
        assert await store.lookup("rt-b") == "dave"

    async def test_store_overwrites_existing(self, store):
        await store.store("rt-dup", "eve")
        await store.store("rt-dup", "frank")
        assert await store.lookup("rt-dup") == "frank"


class TestTokenStoreRedisHelpers:
    """Integration-style tests that exercise the actual Redis helper methods
    by patching the lower-level ``get_redis`` context manager."""

    async def test_redis_set(self):
        mock_redis = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_redis
        with patch("src.cache.redis_client.get_redis", return_value=mock_cm):
            store = TokenStore()
            await store._redis_set("rt-token", "alice")
        expected_key = TokenStore._key("rt-token")
        mock_redis.set.assert_awaited_once_with(expected_key, "alice", ex=REFRESH_TOKEN_TTL)

    async def test_redis_get_found(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "bob"
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_redis
        with patch("src.cache.redis_client.get_redis", return_value=mock_cm):
            store = TokenStore()
            result = await store._redis_get("rt-token")
        assert result == "bob"

    async def test_redis_get_not_found(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_redis
        with patch("src.cache.redis_client.get_redis", return_value=mock_cm):
            store = TokenStore()
            result = await store._redis_get("rt-token")
        assert result is None

    async def test_redis_del(self):
        mock_redis = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_redis
        with patch("src.cache.redis_client.get_redis", return_value=mock_cm):
            store = TokenStore()
            await store._redis_del("rt-token")
        expected_key = TokenStore._key("rt-token")
        mock_redis.delete.assert_awaited_once_with(expected_key)

    def test_key(self):
        key = TokenStore._key("test-token")
        assert key.startswith("rt:")
        assert len(key) == 3 + 16


class TestTokenStoreLookupRevokeDegradation:
    """Cover the ``except Exception:`` blocks in ``lookup`` / ``revoke``."""

    async def test_lookup_redis_exception_falls_back(self):
        store = TokenStore()
        store._memory["rt-lookup"] = "memory-user"
        with patch.object(TokenStore, "_redis_get", side_effect=Exception("down")):
            result = await store.lookup("rt-lookup")
        assert result == "memory-user"
        assert store._redis_ok is False

    async def test_revoke_redis_exception_still_removes_from_memory(self):
        store = TokenStore()
        store._memory["rt-revoke"] = "carol"
        with patch.object(TokenStore, "_redis_del", side_effect=Exception("down")):
            await store.revoke("rt-revoke")
        assert store._redis_ok is False
        assert "rt-revoke" not in store._memory


class TestTokenStoreRedisDegradation:
    async def test_fallback_on_redis_failure(self):
        with patch("src.auth.token_store.TokenStore._redis_set",
                   side_effect=Exception("Redis down")), \
             patch("src.auth.token_store.TokenStore._redis_get",
                   side_effect=Exception("Redis down")), \
             patch("src.auth.token_store.TokenStore._redis_del",
                   side_effect=Exception("Redis down")):
            store = TokenStore()
            await store.store("rt-fail", "grace")
            assert store._redis_ok is False
            result = await store.lookup("rt-fail")
            assert result == "grace"
            await store.revoke("rt-fail")
            assert await store.lookup("rt-fail") is None


class TestTokenStoreRedisSuccess:
    """When Redis works, store/lookup/revoke use Redis and skip memory."""

    async def test_store_calls_redis_set(self):
        store = TokenStore()
        with patch.object(TokenStore, "_redis_set", new_callable=AsyncMock) as mock_set:
            await store.store("rt-ok", "alice")
        mock_set.assert_called_once_with("rt-ok", "alice")
        assert "rt-ok" not in store._memory

    async def test_lookup_returns_redis_value(self):
        store = TokenStore()
        with patch.object(TokenStore, "_redis_get", new_callable=AsyncMock, return_value="bob"):
            result = await store.lookup("rt-ok")
        assert result == "bob"
        assert "rt-ok" not in store._memory

    async def test_lookup_redis_miss_falls_back(self):
        store = TokenStore()
        store._memory["rt-mem"] = "memory-user"
        with patch.object(TokenStore, "_redis_get", new_callable=AsyncMock, return_value=None):
            result = await store.lookup("rt-mem")
        assert result == "memory-user"

    async def test_lookup_redis_hit_takes_priority(self):
        store = TokenStore()
        store._memory["rt-both"] = "memory-user"
        with patch.object(TokenStore, "_redis_get", new_callable=AsyncMock, return_value="redis-user"):
            result = await store.lookup("rt-both")
        assert result == "redis-user"

    async def test_revoke_calls_redis_del(self):
        store = TokenStore()
        store._memory["rt-del"] = "carol"
        with patch.object(TokenStore, "_redis_del", new_callable=AsyncMock) as mock_del:
            await store.revoke("rt-del")
        mock_del.assert_called_once_with("rt-del")
        assert "rt-del" not in store._memory
