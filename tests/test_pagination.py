"""Tests for src.core.pagination — paginate and PaginatedResponse."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest


class TestPaginatedResponse:
    def test_model(self):
        from src.core.pagination import PaginatedResponse

        r = PaginatedResponse(items=[1, 2], total=10, page=1, page_size=20, total_pages=1)
        assert r.items == [1, 2]
        assert r.total == 10
        assert r.total_pages == 1


class TestPaginate:
    @staticmethod
    def _make_real_select():
        """Create a real SQLAlchemy Select statement from an inline table."""
        from sqlalchemy import Column, Integer, MetaData, Table, select

        t = Table("t", MetaData(), Column("x", Integer))
        return select(t.c.x)

    async def _run(self, mock_total, mock_items, page=1, page_size=20):
        from src.core.pagination import paginate

        stmt = self._make_real_select()
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = mock_total
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = mock_items
        db.execute = AsyncMock(side_effect=[count_result, items_result])

        return await paginate(stmt, db, page=page, page_size=page_size)

    async def test_first_page(self):
        result = await self._run(50, ["a", "b"], page=1, page_size=20)
        assert result.total == 50
        assert result.items == ["a", "b"]
        assert result.page == 1
        assert result.page_size == 20
        assert result.total_pages == 3

    async def test_last_page(self):
        result = await self._run(41, ["a"], page=3, page_size=20)
        assert result.total_pages == 3

    async def test_empty(self):
        result = await self._run(0, [])
        assert result.total == 0
        assert result.items == []
        assert result.total_pages == 0

    async def test_total_is_none(self):
        result = await self._run(None, [])
        assert result.total == 0
