"""Tests for database module — engine, session factory, ContextVar."""
import pytest

from src.core.database import async_session_factory, db_session, engine


class TestDatabaseModule:
    """Module-level constants and context variable."""

    def test_engine_created(self):
        """Engine should be instantiated at module load."""
        assert engine is not None

    def test_session_factory_created(self):
        """AsyncSession factory should be instantiated."""
        assert async_session_factory is not None

    def test_context_var_default_none(self):
        """ContextVar default should be None."""
        assert db_session.get() is None

    def test_context_var_set_get(self):
        """Setting a value should be retrievable."""
        token = db_session.set("test-session")
        assert db_session.get() == "test-session"
        db_session.reset(token)
        assert db_session.get() is None

    def test_context_var_reset_restores_previous(self):
        """Reset should restore previous context value."""
        token1 = db_session.set("first")
        token2 = db_session.set("second")
        assert db_session.get() == "second"
        db_session.reset(token2)
        assert db_session.get() == "first"
        db_session.reset(token1)
        assert db_session.get() is None
