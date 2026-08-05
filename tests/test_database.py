"""Tests for src.core.database — engine, session factory, get_db, check_db_health."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDbSessionContext:
    def test_context_var_defaults_to_none(self):
        from src.core.database import db_session

        assert db_session.get() is None

    def test_context_var_set_and_reset(self):
        from src.core.database import db_session

        token = db_session.set("session1")
        assert db_session.get() == "session1"
        db_session.reset(token)
        assert db_session.get() is None


class TestGetDb:
    async def test_yields_session_and_commits(self):
        mock_session = AsyncMock()
        mock_gen = MagicMock()
        mock_gen.__aenter__.return_value = mock_session
        mock_gen.__aexit__.return_value = None

        mod = __import__("src.core.database", fromlist=["get_db"])
        with patch.object(mod, "async_session_factory", return_value=mock_gen):
            gen = mod.get_db()
            session = await gen.__anext__()
            assert session is mock_session
            try:
                await gen.__anext__()
            except StopAsyncIteration:
                pass
            mock_session.commit.assert_awaited_once()

    async def test_rollback_on_exception(self):
        mock_session = AsyncMock()
        mock_gen = MagicMock()
        mock_gen.__aenter__.return_value = mock_session
        mock_gen.__aexit__.return_value = None

        mod = __import__("src.core.database", fromlist=["get_db"])
        with patch.object(mod, "async_session_factory", return_value=mock_gen):
            gen = mod.get_db()
            await gen.__anext__()
            with pytest.raises(RuntimeError):
                await gen.athrow(RuntimeError("fail"))
            mock_session.rollback.assert_awaited_once()


class TestGetSession:
    async def test_yields_session_and_closes(self):
        mock_session = AsyncMock()
        mock_gen = MagicMock()
        mock_gen.__aenter__.return_value = mock_session
        mock_gen.__aexit__.return_value = None

        mod = __import__("src.core.database", fromlist=["get_session"])
        with patch.object(mod, "async_session_factory", return_value=mock_gen):
            async with mod.get_session() as session:
                assert session is mock_session
            mock_session.close.assert_awaited_once()


class TestCheckDbHealth:
    async def test_returns_true_on_success(self):
        mod = __import__("src.core.database", fromlist=["check_db_health"])
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn
        mod.engine = mock_engine

        result = await mod.check_db_health()
        assert result is True
        mock_conn.execute.assert_awaited_once()

    async def test_returns_false_on_exception(self):
        mod = __import__("src.core.database", fromlist=["check_db_health"])
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("down")
        mod.engine = mock_engine

        result = await mod.check_db_health()
        assert result is False
