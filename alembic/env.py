"""Alembic migrations environment configuration."""
from logging.config import fileConfig

from sqlalchemy import create_engine, engine_from_config, pool
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

# Patch: make JSONB usable on SQLite for autogeneration in CI
setattr(SQLiteTypeCompiler, "visit_JSONB", lambda self, type_, **kw: "JSON")

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import ALL models so Alembic can detect them via Base.metadata
from src.models import Base  # noqa: F401, E402
import src.models  # noqa: F401, E402 — triggers all model imports

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
elif config.get_main_option("sqlalchemy.url", "").startswith("sqlite"):
    # SQLite online mode — use for CI / offline autogeneration
    connectable = create_engine(config.get_main_option("sqlalchemy.url"))
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
else:
    run_migrations_online()
