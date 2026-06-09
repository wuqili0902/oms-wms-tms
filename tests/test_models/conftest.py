"""Test fixtures for DB-backed service tests — async SQLite in-memory.

All service-level tests use these fixtures to run against SQLite so CI
does not require a PostgreSQL server.

Design notes:
- ``async_engine`` (session scope): creates all tables once.
- ``db_session`` (per-test): nested savepoint so service ``commit()``
  is captured and rolled back at teardown. This lets service functions
  call ``await db.commit()`` normally while tests remain isolated.
"""

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Patch JSONB → JSON for SQLite BEFORE any model imports
setattr(SQLiteTypeCompiler, "visit_JSONB", lambda self, type_, **kw: "JSON")

from src.models import Base  # noqa: E402  — populates metadata


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def async_engine():
    """Session-scoped async SQLite engine with all ORM tables created."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession]:
    """Per-test async session — uses ``begin_nested`` so that any
    ``session.commit()`` called inside the test (e.g. by service functions)
    commits to a savepoint rather than the outer transaction.
    The outer transaction is rolled back at teardown, providing isolation.
    """
    connection = await async_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)

    # Create a savepoint — the service's commit() will commit to this
    # savepoint, not the outer transaction.
    await session.begin_nested()

    try:
        yield session
    finally:
        await transaction.rollback()
        await connection.close()
