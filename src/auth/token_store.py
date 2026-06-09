"""Token storage backend with Redis + in-memory fallback.

Provides a module-level ``token_store`` singleton that the auth service
uses to persist refresh-token → username mappings.

Redis is preferred (TTL = 7 days).  If Redis is unreachable the store
silently degrades to an in-memory dict so that auth never breaks.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Matches REFRESH_TOKEN_EXPIRE_DAYS in src/core/security.py
REFRESH_TOKEN_TTL: int = 7 * 24 * 3600  # 7 days in seconds


class TokenStore:
    """Token storage backend.

    Thread‑/coroutine‑safe because ``get_redis()`` uses a connection pool,
    and the in-memory fallback dict is only accessed from a single event loop.
    """

    def __init__(self) -> None:
        self._memory: dict[str, str] = {}
        self._redis_ok: bool = True  # optimistic; flipped on first failure

    # ── Public API ──────────────────────────────────────────────────────────

    async def store(self, refresh_token: str, username: str) -> None:
        """Persist *refresh_token* → *username* (TTL = 7 days)."""
        if self._redis_ok:
            try:
                await self._redis_set(refresh_token, username)
                return
            except Exception:
                self._redis_ok = False
                logger.warning("Redis set() failed — falling back to memory")
        self._memory[refresh_token] = username

    async def lookup(self, refresh_token: str) -> str | None:
        """Return the username associated with *refresh_token*, or ``None``."""
        if self._redis_ok:
            try:
                val: str | None = await self._redis_get(refresh_token)
                if val is not None:
                    return val
            except Exception:
                self._redis_ok = False
                logger.warning("Redis get() failed — falling back to memory")
        return self._memory.get(refresh_token)

    async def revoke(self, refresh_token: str) -> None:
        """Remove *refresh_token* from the store."""
        if self._redis_ok:
            try:
                await self._redis_del(refresh_token)
            except Exception:
                self._redis_ok = False
                logger.warning("Redis del() failed — falling back to memory")
        self._memory.pop(refresh_token, None)

    async def pop(self, refresh_token: str) -> str | None:
        """Look up *refresh_token* and atomically revoke it (token rotation)."""
        username = await self.lookup(refresh_token)
        await self.revoke(refresh_token)
        return username

    # ── Internal: Redis helpers ─────────────────────────────────────────────

    @staticmethod
    def _key(token: str) -> str:
        """Short deterministic key derived from the JWT."""
        return f"rt:{hashlib.sha256(token.encode()).hexdigest()[:16]}"

    @staticmethod
    async def _redis_set(token: str, username: str) -> None:
        from src.cache.redis_client import get_redis

        async with get_redis() as r:
            await r.set(TokenStore._key(token), username, ex=REFRESH_TOKEN_TTL)

    @staticmethod
    async def _redis_get(token: str) -> str | None:
        from src.cache.redis_client import get_redis

        async with get_redis() as r:
            val: Any = await r.get(TokenStore._key(token))
            return str(val) if val is not None else None

    @staticmethod
    async def _redis_del(token: str) -> None:
        from src.cache.redis_client import get_redis

        async with get_redis() as r:
            await r.delete(TokenStore._key(token))


# Singleton — import from other modules via:
#   from src.auth.token_store import token_store
token_store = TokenStore()
