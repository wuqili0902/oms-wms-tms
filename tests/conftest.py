"""Test configuration and fixtures."""

import asyncio
import gc
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Patch JSONB → JSON for SQLite BEFORE any model imports
setattr(SQLiteTypeCompiler, "visit_JSONB", lambda self, type_, **kw: "JSON")

from src.core.database import get_db  # noqa: E402
from src.main import app  # noqa: E402
from src.models import Base  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def sqlite_engine():
    """Session-scoped async SQLite engine with all ORM tables created."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()
    # Force GC to clean up remaining aiosqlite connections before the event
    # loop shuts down, preventing ResourceWarning about unclosed databases.
    gc.collect()


@pytest_asyncio.fixture
async def db_session(sqlite_engine) -> AsyncGenerator[AsyncSession]:
    """Per-test async session with savepoint isolation.

    Uses ``begin_nested`` so service ``commit()`` commits to a savepoint
    within an outer transaction that is rolled back at teardown.
    """
    connection = await sqlite_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    await session.begin_nested()

    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


class _SharedSession:
    """Holds a single AsyncSession across multiple requests."""

    def __init__(self, engine):
        self.engine = engine
        self.session: AsyncSession | None = None
        self.connection = None
        self.transaction = None

    async def setup(self):
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(bind=self.connection, expire_on_commit=False)
        await self.session.begin_nested()

    async def teardown(self):
        if self.session:
            await self.session.close()
        if self.transaction:
            await self.transaction.rollback()
        if self.connection:
            await self.connection.close()


@pytest_asyncio.fixture
async def async_client(sqlite_engine) -> AsyncGenerator:
    """Async HTTP client with ``get_db`` overridden.

    All requests within a single test share the same SQLite session,
    allowing multi-step operations (register → login → me).
    The outer transaction is rolled back on teardown.
    """
    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _get_db_override() -> AsyncGenerator[AsyncSession]:
        """Yield the shared session for every request in the test."""
        yield shared.session

    app.dependency_overrides[get_db] = _get_db_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await shared.teardown()
