"""Create SQLite tables for E2E (replaces alembic for the throwaway test DB).

The main app relies on alembic migrations; for a disposable SQLite test DB we
just build the full schema directly. Import src.models to register all models.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SECRET_KEY", "e2e-test-secret-key-12345678")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./e2e_test.db")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("CORS_ORIGINS", '["*"]')
os.environ.setdefault("REDIS_URL", "")

from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
setattr(SQLiteTypeCompiler, "visit_JSONB", lambda self, type_, **kw: "JSON")

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from src.models import Base
import src.models as _all_models  # noqa: F401  (register all tables on Base.metadata)

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///./e2e_test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("E2E DB initialized (e2e_test.db)")

asyncio.run(main())