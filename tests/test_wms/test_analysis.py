"""Tests for WMS inventory analysis (ABC‑XYZ classification).

Note: compute_xyz_analysis uses PostgreSQL ``date_trunc`` which is not
available on the SQLite test backend — those tests are skipped here.
"""
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import insert

from src.wms.analysis import _abc_category, _cv_category, compute_abc_analysis
from src.wms.models import SKU, StockMovement


# ── Pure unit tests (no DB needed) ────────────────────────────────────────────

class TestABCCategory:
    def test_a_top_80(self):
        assert _abc_category(0.0) == "A"
        assert _abc_category(0.5) == "A"
        assert _abc_category(0.8) == "A"

    def test_b_next_15(self):
        assert _abc_category(0.81) == "B"
        assert _abc_category(0.90) == "B"
        assert _abc_category(0.95) == "B"

    def test_c_bottom_5(self):
        assert _abc_category(0.951) == "C"
        assert _abc_category(1.0) == "C"


class TestXYZCategory:
    def test_x_stable(self):
        assert _cv_category(0.0) == "X"
        assert _cv_category(0.49) == "X"

    def test_y_moderate(self):
        assert _cv_category(0.5) == "Y"
        assert _cv_category(0.99) == "Y"

    def test_z_irregular(self):
        assert _cv_category(1.0) == "Z"
        assert _cv_category(5.0) == "Z"


# ── ABC analysis integration tests ────────────────────────────────────────────

class TestComputeABC:
    """Note: use ``flush()`` not ``commit()`` to avoid cross-test isolation."""

    @pytest.mark.asyncio
    async def test_empty_db(self, db_session):
        assert await compute_abc_analysis(db_session, months=12) == []

    @pytest.mark.asyncio
    async def test_basic_classification(self, db_session):
        """Create multiple SKUs + movements — verify ABC ranking."""
        sku_a, sku_b = uuid.uuid4(), uuid.uuid4()
        now = datetime.now(UTC)
        for sid, code in ((sku_a, "SKU-AB"), (sku_b, "SKU-CC")):
            await db_session.execute(insert(SKU).values(id=sid, sku=code, name="T"))
        for sid, qty in ((sku_a, "-800"), (sku_b, "-200")):
            await db_session.execute(insert(StockMovement).values(
                id=uuid.uuid4(), sku_id=sid, quantity=Decimal(qty),
                movement_type="outbound", created_at=now,
            ))
        await db_session.flush()

        result = await compute_abc_analysis(db_session, months=12)
        assert len(result) == 2
        # SKU with 80% share is A, 20% share is C
        assert result[0]["abc_category"] == "A"
        assert result[1]["abc_category"] == "C"

    @pytest.mark.asyncio
    async def test_top_n_limit(self, db_session):
        for i in range(5):
            sid = uuid.uuid4()
            await db_session.execute(insert(SKU).values(id=sid, sku=f"SKU-TN-{i}", name="T"))
            await db_session.execute(insert(StockMovement).values(
                id=uuid.uuid4(), sku_id=sid, quantity=Decimal(f"-{(5-i)*100}"),
                movement_type="outbound", created_at=datetime.now(UTC),
            ))
        await db_session.flush()

        assert len(await compute_abc_analysis(db_session, months=12, top_n=3)) == 3

    @pytest.mark.asyncio
    async def test_ignore_inbound_movements(self, db_session):
        """Positive quantity (inbound) should be excluded."""
        sid = uuid.uuid4()
        await db_session.execute(insert(SKU).values(id=sid, sku="SKU-IB", name="I"))
        await db_session.execute(insert(StockMovement).values(
            id=uuid.uuid4(), sku_id=sid, quantity=Decimal("500"),
            movement_type="inbound", created_at=datetime.now(UTC),
        ))
        await db_session.flush()

        assert await compute_abc_analysis(db_session, months=12) == []

    @pytest.mark.asyncio
    async def test_single_sku_is_category_c(self, db_session):
        """Single SKU → 100% cumulative share → C."""
        sid = uuid.uuid4()
        await db_session.execute(insert(SKU).values(id=sid, sku="SKU-C", name="Single"))
        await db_session.execute(insert(StockMovement).values(
            id=uuid.uuid4(), sku_id=sid, quantity=Decimal("-200"),
            movement_type="outbound", created_at=datetime.now(UTC),
        ))
        await db_session.flush()

        result = await compute_abc_analysis(db_session, months=12)
        assert len(result) == 1
        assert result[0]["abc_category"] == "C"
        assert result[0]["share_pct"] == 100.0


# ── ABC‑XYZ matrix tests (mocked, since XYZ needs PostgreSQL date_trunc) ──────

# ── XYZ analysis tests (mocked execute to avoid PostgreSQL date_trunc) ────────

class TestComputeXYZ:
    @pytest.mark.asyncio
    async def test_empty_db(self):
        from src.wms.analysis import compute_xyz_analysis
        from unittest.mock import AsyncMock, MagicMock

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        result = await compute_xyz_analysis(mock_db, months=12)
        assert result == []

    @pytest.mark.asyncio
    async def test_classification(self):
        from src.wms.analysis import compute_xyz_analysis
        from unittest.mock import AsyncMock, MagicMock
        import uuid

        sku_id = str(uuid.uuid4())
        mock_rows = [
            MagicMock(sku_id=uuid.UUID(sku_id), monthly_qty=-100),
            MagicMock(sku_id=uuid.UUID(sku_id), monthly_qty=-50),
            MagicMock(sku_id=uuid.UUID(sku_id), monthly_qty=0),
        ]
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(all=MagicMock(return_value=mock_rows)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ])
        result = await compute_xyz_analysis(mock_db, months=12)
        assert len(result) == 1
        assert result[0]["xyz_category"] == "Z"
        assert result[0]["cv"] == 1.0

    @pytest.mark.asyncio
    async def test_stable_demand(self):
        from src.wms.analysis import compute_xyz_analysis
        from unittest.mock import AsyncMock, MagicMock
        import uuid

        sku_id = str(uuid.uuid4())
        mock_rows = [
            MagicMock(sku_id=uuid.UUID(sku_id), monthly_qty=-50)
            for _ in range(12)
        ]
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(all=MagicMock(return_value=mock_rows)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ])
        result = await compute_xyz_analysis(mock_db, months=12)
        assert len(result) == 1
        assert result[0]["xyz_category"] == "X"
        assert result[0]["cv"] == 0.0

    @pytest.mark.asyncio
    async def test_top_n(self):
        from src.wms.analysis import compute_xyz_analysis
        from unittest.mock import AsyncMock, MagicMock
        import uuid

        sku_id = str(uuid.uuid4())
        mock_rows = [
            MagicMock(sku_id=uuid.UUID(sku_id), monthly_qty=-50 + i)
            for i in range(4)
        ]
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            MagicMock(all=MagicMock(return_value=mock_rows)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ])
        result = await compute_xyz_analysis(mock_db, months=12, top_n=3)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_single_month_skipped(self):
        from src.wms.analysis import compute_xyz_analysis
        from unittest.mock import AsyncMock, MagicMock
        import uuid

        mock_rows = [
            MagicMock(sku_id=uuid.uuid4(), monthly_qty=-100),
        ]
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=mock_rows)))

        result = await compute_xyz_analysis(mock_db, months=12)
        assert result == []


class TestComputeABCXYZMatrix:
    @pytest.mark.asyncio
    async def test_matrix_returns_nine_cells(self):
        from src.wms.analysis import compute_abc_xyz_matrix
        from unittest.mock import patch, AsyncMock

        abc_result = [
            {"sku_id": "111", "sku_code": "A1", "sku_name": "Alpha",
             "share_pct": 50.0, "abc_category": "A"},
            {"sku_id": "222", "sku_code": "C1", "sku_name": "Charlie",
             "share_pct": 5.0, "abc_category": "C"},
        ]
        xyz_result = [
            {"sku_id": "111", "monthly_values": [], "mean": 100, "std_dev": 10,
             "cv": 0.1, "xyz_category": "X"},
            {"sku_id": "222", "monthly_values": [], "mean": 10, "std_dev": 15,
             "cv": 1.5, "xyz_category": "Z"},
        ]

        with patch("src.wms.analysis.compute_abc_analysis", new=AsyncMock(return_value=abc_result)):
            with patch("src.wms.analysis.compute_xyz_analysis", new=AsyncMock(return_value=xyz_result)):
                matrix = await compute_abc_xyz_matrix(db=None, months=6)

        assert sorted(matrix.keys()) == [f"{a}{z}" for a in "ABC" for z in "XYZ"]
        # SKU 111 is A+X → AX cell
        assert len(matrix["AX"]) == 1
        assert matrix["AX"][0]["sku_id"] == "111"
        assert matrix["AX"][0]["abc"] == "A"
        assert matrix["AX"][0]["xyz"] == "X"
        # SKU 222 is C+Z → CZ cell
        assert len(matrix["CZ"]) == 1
        assert matrix["CZ"][0]["sku_id"] == "222"

    @pytest.mark.asyncio
    async def test_matrix_fills_empty_cells(self):
        from src.wms.analysis import compute_abc_xyz_matrix
        from unittest.mock import patch, AsyncMock

        with patch("src.wms.analysis.compute_abc_analysis", new=AsyncMock(return_value=[])):
            with patch("src.wms.analysis.compute_xyz_analysis", new=AsyncMock(return_value=[])):
                matrix = await compute_abc_xyz_matrix(db=None, months=6)

        for cell in [f"{a}{z}" for a in "ABC" for z in "XYZ"]:
            assert cell in matrix
            assert matrix[cell] == []
