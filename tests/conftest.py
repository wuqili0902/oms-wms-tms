"""Test configuration and fixtures."""

import asyncio
import gc
import os
import tempfile
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

# Patch JSONB -> JSON for SQLite BEFORE any model imports
setattr(SQLiteTypeCompiler, "visit_JSONB", lambda self, type_, **kw: "JSON")

from src.config import settings  # noqa: E402

settings.testing = True

# Tests get their own Redis DB index, applied BEFORE anything imports the
# module-level Redis clients (src.cache.redis_client.redis_client,
# src.core.rate_limiter.rate_limiter, ...), which capture the URL at import.
#
# Sharing DB 0 with a running dev server is not hypothetical contamination:
#   * @cached writes analytics/tms results that the next test then reads back,
#     so a test asserting on its own mocked data receives another test's numbers;
#   * the WS fan-out (P1-14) publishes on Redis pub/sub, so a test notification
#     is delivered to whichever sockets the real server is holding;
#   * rate-limit buckets and locks are shared too.
TEST_REDIS_DB = 15


def _retarget_redis_db(url: str, db: int) -> str:
    """Swap the DB index of a redis URL, leaving scheme/auth/host intact."""
    from urllib.parse import urlsplit, urlunsplit

    if not url:
        return url
    parts = urlsplit(url)
    if not parts.scheme:
        return url  # not a URL we should rewrite (cache disabled upstream)
    return urlunsplit((parts.scheme, parts.netloc, f"/{db}", parts.query, parts.fragment))


settings.redis_url = _retarget_redis_db(settings.redis_url, TEST_REDIS_DB)

from src.core.database import get_db  # noqa: E402
from src.main import app  # noqa: E402
from src.models import Base  # noqa: E402

_DB_FILE = os.path.join(tempfile.gettempdir(), "oms_wms_tms_test.sqlite")

# Keys the suite itself can leave behind: @cached() prefixes in use across src/
# (see src/cache/decorators.py), the limiter/lock namespaces, and the idempotency
# guards (src/core/idempotency.py) — a guard left by one test would answer the
# next test's identical replay with the first test's response.
_CACHE_KEY_PATTERNS = ("analytics:*", "tms:*", "cache:*", "rate_limit:*", "lock:*", "idempotency:*")

# NOTE: The suite intentionally runs against a temp-file SQLite DB. PostgreSQL
# is validated separately in CI by applying the Alembic migrations
# (``alembic upgrade head``) against the provisioned postgres service, which
# covers the production schema path. Changing this fixture to asyncpg would
# require a session-wide event loop — asyncpg pools cannot cross event loops,
# and pytest-asyncio (auto mode) gives each test its own loop.


@pytest.fixture(scope="session")
def _test_redis():
    """Sync client on the test Redis DB, or None when Redis is unreachable."""
    import redis as redis_sync

    try:
        client = redis_sync.Redis.from_url(
            settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        client.ping()
    except Exception:  # noqa: BLE001 — no Redis in this environment
        return None
    yield client
    try:
        client.close()
    except Exception:  # noqa: BLE001 — teardown is best effort
        pass


@pytest.fixture(scope="session", autouse=True)
def _flush_test_redis(_test_redis):
    """Each run starts from an empty test keyspace."""
    if _test_redis is not None:
        _test_redis.flushdb()


@pytest.fixture(autouse=True)
def _clear_cached_results(_test_redis):
    """Per-test: drop the app's @cached() results.

    ``skip_args=1`` keeps the db session out of the cache key, so every call to
    e.g. get_dashboard_stats() shares a single key.  With a reachable Redis that
    meant test A's numbers were served to test B's assertions — analytics tests
    failed or passed depending on which test ran first.
    """
    if _test_redis is None:
        return
    pipe = _test_redis.pipeline(transaction=False)
    for pattern in _CACHE_KEY_PATTERNS:
        for key in _test_redis.scan_iter(match=pattern, count=500):
            pipe.delete(key)
    pipe.execute()


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def sqlite_engine():
    """Session-scoped engine backed by a temp file — shared across tests.

    ``NullPool`` is load-bearing here.  pytest-asyncio gives each test its own
    event loop, and an aiosqlite connection binds its internal execute lock to
    whichever loop first used it.  A pooled connection therefore survives the
    test that created it and poisons the next one with
    ``RuntimeError: ... is bound to a different event loop`` — surfacing as a
    500 on /health, an analytics query, or an auth-seeding fixture, none of
    which say anything about the real cause.  The database itself is a file, so
    opening a fresh connection per checkout is cheap and loses nothing.
    """
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{_DB_FILE}", echo=False, poolclass=NullPool
    )
    async with engine.begin() as conn:
        # Drop first: a previous run that was interrupted (timeout/crash)
        # skipped the teardown drop and left stale rows + old-schema debris
        # in the temp file, polluting later runs (leaked users, int-in-uuid
        # rows, phantom counts).
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    # On Windows the file stays locked briefly: aiosqlite closes every
    # connection on its own worker thread and dispose() does not wait for those
    # threads, so a bare os.remove() raced them and raised WinError 32 at
    # session teardown.  The file is wiped and rebuilt at the next session
    # start regardless, so a delete that keeps losing the race must not turn
    # into a teardown error.
    for _ in range(10):
        try:
            if os.path.exists(_DB_FILE):
                os.remove(_DB_FILE)
            break
        except PermissionError:
            gc.collect()
            await asyncio.sleep(0.1)
    gc.collect()


@pytest_asyncio.fixture
async def db_session(sqlite_engine) -> AsyncGenerator[AsyncSession]:
    """Per-test session with savepoint — rollback ensures isolation."""
    connection = await sqlite_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    await session.begin_nested()
    # Clear all tables to prevent cross-test pollution
    from src.models import Base
    meta = Base.metadata
    for table in reversed(meta.sorted_tables):
        await session.execute(table.delete())
    await session.flush()
    try:
        yield session
    finally:
        await session.close()
        if not connection.closed:
            await transaction.rollback()
            await connection.close()


class _SharedSession:
    """Holds a single AsyncSession across multiple requests."""

    def __init__(self, engine):
        self.engine = engine
        self.session = None
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
    """Async HTTP client with ``get_db`` overridden."""
    # Reset admin seeding flag so _ensure_admin re-seeds after DB rollback
    from src.auth import service as _auth_svc
    _auth_svc._admin_seeded = False

    shared = _SharedSession(sqlite_engine)
    await shared.setup()

    async def _get_db_override() -> AsyncGenerator[AsyncSession]:
        yield shared.session

    app.dependency_overrides[get_db] = _get_db_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client._shared_session = shared.session  # expose for test seeding
        yield client

    app.dependency_overrides.clear()
    await shared.teardown()
