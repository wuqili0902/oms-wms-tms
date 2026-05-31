"""Test configuration and fixtures."""

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.main import app
from src.config import settings
from src.core.database import get_db

TEST_DATABASE_URL = settings.database_url


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator:
    """Create async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator:
    """Create test database session.
    In CI without DB, this will be skipped gracefully."""
    try:
        engine = create_async_engine(TEST_DATABASE_URL)
        async_session = async_sessionmaker(engine, class_=AsyncSession)

        async with async_session() as session:
            yield session
            await session.close()
        await engine.dispose()
    except Exception:
        pytest.skip("Database not available for this test")
