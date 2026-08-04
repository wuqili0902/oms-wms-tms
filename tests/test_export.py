"""Tests for src.core.export — CSV streaming and data export."""


import pytest


@pytest.fixture
def sample_rows():
    return [
        {"col_a": "val1", "col_b": "123"},
        {"col_a": "val2", "col_b": "456"},
    ]


class TestStreamCSV:
    async def _collect(self, gen):
        chunks = []
        async for chunk in gen:
            chunks.append(chunk)
        return b"".join(chunks)

    async def test_stream_csv_basic(self, sample_rows):
        from src.core.export import stream_csv

        result = await self._collect(stream_csv(sample_rows, ["col_a", "col_b"]))
        assert b"col_a,col_b" in result
        assert b"val1,123" in result
        assert b"val2,456" in result

    async def test_stream_csv_utf8_sig_header(self, sample_rows):
        from src.core.export import stream_csv

        result = await self._collect(stream_csv(sample_rows, ["col_a"]))
        assert result.startswith(b"\xef\xbb\xbf")

    async def test_stream_csv_empty_rows(self):
        from src.core.export import stream_csv

        result = await self._collect(stream_csv([], ["col_a", "col_b"]))
        assert result == b"\xef\xbb\xbfcol_a,col_b\r\n"

    async def test_stream_csv_missing_column_fills_empty(self, sample_rows):
        from src.core.export import stream_csv

        result = await self._collect(stream_csv(sample_rows, ["col_a", "col_c"]))
        assert b"val1," in result
        assert b"," in result

    async def test_stream_csv_different_columns_order(self, sample_rows):
        from src.core.export import stream_csv

        result = await self._collect(stream_csv(sample_rows, ["col_b", "col_a"]))
        lines = result.decode("utf-8-sig").strip().split("\r\n")
        assert lines[0] == "col_b,col_a"
        assert lines[1] == "123,val1"
