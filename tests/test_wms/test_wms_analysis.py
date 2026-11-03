"""Tests for wms/analysis.py — ABC-XYZ inventory analysis."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.wms.analysis import (
    _abc_category,
    _cv_category,
    compute_abc_analysis,
    compute_abc_xyz_matrix,
    compute_xyz_analysis,
)


class TestAbcCategory:
    def test_a_category(self):
        assert _abc_category(0.5) == "A"
        assert _abc_category(0.80) == "A"

    def test_b_category(self):
        assert _abc_category(0.81) == "B"
        assert _abc_category(0.95) == "B"

    def test_c_category(self):
        assert _abc_category(0.96) == "C"
        assert _abc_category(1.0) == "C"


class TestCvCategory:
    def test_x_category(self):
        assert _cv_category(0.0) == "X"
        assert _cv_category(0.49) == "X"

    def test_y_category(self):
        assert _cv_category(0.5) == "Y"
        assert _cv_category(0.99) == "Y"

    def test_z_category(self):
        assert _cv_category(1.0) == "Z"
        assert _cv_category(2.5) == "Z"


class TestComputeAbcAnalysis:
    @pytest.fixture
    def mock_db(self):
        return AsyncMock(spec=AsyncSession)

    async def test_empty_movements(self, mock_db):
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await compute_abc_analysis(mock_db, months=6)
        assert result == []

    async def test_single_sku(self, mock_db):
        sku_id = uuid.uuid4()
        row = MagicMock()
        row.sku_id = sku_id
        row.total_qty = -100

        mock_select_result = MagicMock()
        mock_select_result.all.return_value = [row]

        sku = MagicMock()
        sku.id = sku_id
        sku.sku = "SKU-1"
        sku.name = "Test SKU"
        mock_sku_result = MagicMock()
        mock_sku_result.scalars.return_value.all.return_value = [sku]

        mock_db.execute = AsyncMock(side_effect=[mock_select_result, mock_sku_result])
        result = await compute_abc_analysis(mock_db, months=6)
        assert len(result) == 1
        assert result[0]["abc_category"] == "C"  # 100% share = C
        assert result[0]["sku_code"] == "SKU-1"
        assert result[0]["total_qty"] == 100.0

    async def test_multiple_skus_abc_split(self, mock_db):
        rows = []
        for i, qty in enumerate([-400, -300, -200, -100]):
            row = MagicMock()
            row.sku_id = uuid.uuid4()
            row.total_qty = qty
            rows.append(row)

        mock_select_result = MagicMock()
        mock_select_result.all.return_value = rows
        mock_sku_result = MagicMock()
        mock_sku_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[mock_select_result, mock_sku_result])
        result = await compute_abc_analysis(mock_db, months=6)
        assert len(result) == 4
        cats = [r["abc_category"] for r in result]
        assert "A" in cats
        assert "C" in cats

    async def test_top_n_limit(self, mock_db):
        rows = []
        for _ in range(5):
            row = MagicMock()
            row.sku_id = uuid.uuid4()
            row.total_qty = -100
            rows.append(row)

        mock_select_result = MagicMock()
        mock_select_result.all.return_value = rows[:2]
        mock_sku_result = MagicMock()
        mock_sku_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[mock_select_result, mock_sku_result])
        result = await compute_abc_analysis(mock_db, months=6, top_n=2)
        assert len(result) == 2


class TestComputeXyzAnalysis:
    @pytest.fixture
    def mock_db(self):
        return AsyncMock(spec=AsyncSession)

    async def test_empty(self, mock_db):
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await compute_xyz_analysis(mock_db, months=6)
        assert result == []

    async def test_single_month_skipped(self, mock_db):
        """SKUs with only 1 month of data are skipped (need n >= 2)."""
        row = MagicMock()
        row.sku_id = uuid.uuid4()
        row.monthly_qty = -100

        mock_select_result = MagicMock()
        mock_select_result.all.return_value = [row]
        mock_sku_result = MagicMock()
        mock_sku_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[mock_select_result, mock_sku_result])
        result = await compute_xyz_analysis(mock_db, months=6)
        assert result == []

    async def test_stable_demand_x(self, mock_db):
        """Constant demand → low CV → X category."""
        sku_id = uuid.uuid4()
        rows = []
        for _ in range(3):
            row = MagicMock()
            row.sku_id = sku_id
            row.monthly_qty = -100
            rows.append(row)

        mock_select_result = MagicMock()
        mock_select_result.all.return_value = rows
        mock_sku_result = MagicMock()
        mock_sku_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[mock_select_result, mock_sku_result])
        result = await compute_xyz_analysis(mock_db, months=6)
        assert len(result) == 1
        assert result[0]["xyz_category"] == "X"
        assert result[0]["cv"] == 0.0

    async def test_volatile_demand_z(self, mock_db):
        """High variance → high CV → Z category."""
        sku_id = uuid.uuid4()
        quantities = [-10, -500, -5, -600]
        rows = []
        for q in quantities:
            row = MagicMock()
            row.sku_id = sku_id
            row.monthly_qty = q
            rows.append(row)

        mock_select_result = MagicMock()
        mock_select_result.all.return_value = rows
        mock_sku_result = MagicMock()
        mock_sku_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[mock_select_result, mock_sku_result])
        result = await compute_xyz_analysis(mock_db, months=6)
        assert len(result) == 1
        assert result[0]["xyz_category"] == "Z"
        assert result[0]["cv"] >= 1.0


class TestComputeAbcXyzMatrix:
    @pytest.fixture
    def mock_db(self):
        return AsyncMock(spec=AsyncSession)

    async def test_empty(self, mock_db):
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await compute_abc_xyz_matrix(mock_db, months=6)
        assert all(isinstance(v, list) for v in result.values())

    async def test_abc_xyz_combination(self, mock_db):
        sku_id = uuid.uuid4()

        abc_row = MagicMock()
        abc_row.sku_id = sku_id
        abc_row.total_qty = -100

        xyz_row_month1 = MagicMock()
        xyz_row_month1.sku_id = sku_id
        xyz_row_month1.monthly_qty = -50

        xyz_row_month2 = MagicMock()
        xyz_row_month2.sku_id = sku_id
        xyz_row_month2.monthly_qty = -50

        mock_sku_result = MagicMock()
        mock_sku_result.scalars.return_value.all.return_value = []

        call_count = [0]

        async def mock_execute(stmt):
            call_count[0] += 1
            if call_count[0] == 1:
                m = MagicMock()
                m.all.return_value = [abc_row]
                return m
            elif call_count[0] == 2:
                m = MagicMock()
                m.all.return_value = [xyz_row_month1, xyz_row_month2]
                return m
            return mock_sku_result

        mock_db.execute = mock_execute
        result = await compute_abc_xyz_matrix(mock_db, months=6)
        assert isinstance(result, dict)
        has_content = any(len(v) > 0 for v in result.values())
        assert has_content
