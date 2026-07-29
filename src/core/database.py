"""Database engine, session factory, and ContextVar-based session access.

Each HTTP request gets its own ``AsyncSession`` managed by the ``get_db``
FastAPI dependency.  The session is also placed in a ``ContextVar`` so that
deeply nested helpers can access it without explicit injection.

For testing, ``app.dependency_overrides[get_db]`` replaces this dependency
— tests provide their own session with savepoint isolation.
"""
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=settings.db_pool_pre_ping,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Context variable ────────────────────────────────────────────────────────
# Allows any helper in the call chain to access the current request's session.

db_session: ContextVar[AsyncSession | None] = ContextVar("db_session", default=None)


# ── FastAPI dependency ─────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield the current request's DB session.

    Creates a session from the factory, stores it in a ``ContextVar`` for
    nested access, and commits/rollbacks/closes at request end.
    """
    async with async_session_factory() as session:
        token = db_session.set(session)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            db_session.reset(token)


# ── Standalone session for background tasks / outbox worker ────────────────

@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Create a standalone session for background workers (Celery, outbox dispatch).

    Yields an un-bound session; the caller is responsible for commit/rollback.
    """
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_db_health() -> bool:
    """Ping the database and return True if reachable."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
