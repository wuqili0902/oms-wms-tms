"""ABC-XYZ inventory analysis for stock optimisation.

ABC classification
------------------
Based on cumulative consumption value (Pareto):
  - **A**: top 20 % of SKUs by value (≈80 % of total value)
  - **B**: next 30 % of SKUs
  - **C**: bottom 50 % of SKUs

XYZ classification
------------------
Based on demand volatility (Coefficient of Variation, CV):
  - **X**: CV < 0.5  — stable, predictable demand
  - **Y**: 0.5 ≤ CV < 1.0 — moderate fluctuations
  - **Z**: CV ≥ 1.0  — irregular, erratic demand

Combined ABC‑XYZ matrix drives stocking policies:
  - AX: high-value + stable → lean / just-in-time
  - CZ: low-value + erratic → safety stock or make-to-order
"""
import math
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.wms.models import SKU, StockMovement

# ── Analysis helpers ─────────────────────────────────────────────────────────


def _abc_category(cumul_ratio: float) -> str:
    if cumul_ratio <= 0.80 + 1e-10:
        return "A"
    if cumul_ratio <= 0.95 + 1e-10:
        return "B"
    return "C"


def _cv_category(cv: float) -> str:
    if cv < 0.5:
        return "X"
    if cv < 1.0:
        return "Y"
    return "Z"


# ── Public API ────────────────────────────────────────────────────────────────


async def compute_abc_analysis(
    db: AsyncSession,
    months: int = 6,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Compute ABC classification for all SKUs based on movement data.

    Each SKU's total movement quantity (outbound) over the last ``months``
    months is summed, sorted descending, and classified by cumulative share.
    Returns a list of dicts sorted by rank.
    """
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(days=30 * months)

    stmt = (
        select(
            StockMovement.sku_id,
            func.sum(StockMovement.quantity).label("total_qty"),
        )
        .where(
            StockMovement.created_at >= cutoff,
            StockMovement.quantity < 0,
        )
        .group_by(StockMovement.sku_id)
        .order_by(func.sum(StockMovement.quantity).asc())
    )
    if top_n:
        stmt = stmt.limit(top_n)

    result = await db.execute(stmt)
    rows = result.all()

    total_value = abs(sum(row.total_qty or 0 for row in rows)) or 1
    cumulative = 0.0
    output: list[dict[str, Any]] = []

    sku_ids = {row.sku_id for row in rows if row.sku_id}
    abc_sku_map: dict[uuid.UUID, SKU] = {}
    if sku_ids:
        abc_skus = await db.execute(select(SKU).where(SKU.id.in_(list(sku_ids))))
        abc_sku_map = {s.id: s for s in abc_skus.scalars().all()}

    for rank, row in enumerate(rows, 1):
        sku_id = row.sku_id
        qty = abs(float(row.total_qty or 0))
        share = qty / float(total_value)
        cumulative += share
        abc = _abc_category(cumulative)
        sku = abc_sku_map.get(sku_id)

        output.append({
            "rank": rank,
            "sku_id": str(sku_id),
            "sku_code": sku.sku if sku else "",
            "sku_name": sku.name if sku else "",
            "total_qty": qty,
            "share_pct": round(share * 100, 2),
            "cumul_pct": round(cumulative * 100, 2),
            "abc_category": abc,
        })

    return output


async def compute_xyz_analysis(
    db: AsyncSession,
    months: int = 6,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Compute XYZ classification for all SKUs.

    Calculates the Coefficient of Variation (CV = σ / μ) of monthly
    demand over the last ``months`` months.
    """
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(days=30 * months)

    stmt = (
        select(
            StockMovement.sku_id,
            func.date_trunc("month", StockMovement.created_at).label("month"),
            func.sum(StockMovement.quantity).label("monthly_qty"),
        )
        .where(
            StockMovement.created_at >= cutoff,
            StockMovement.quantity < 0,
        )
        .group_by(StockMovement.sku_id, func.date_trunc("month", StockMovement.created_at))
    )
    if top_n:
        stmt = stmt.limit(top_n)

    result = await db.execute(stmt)
    rows = result.all()

    sku_monthly: dict[str, list[float]] = {}
    for row in rows:
        sku_id = str(row.sku_id)
        qty = abs(float(row.monthly_qty or 0))
        sku_monthly.setdefault(sku_id, []).append(qty)

    sku_uuids = [uuid.UUID(sid) for sid in sku_monthly if uuid.UUID(sid)]
    xyz_sku_map: dict[uuid.UUID, SKU] = {}
    if sku_uuids:
        xyz_skus = await db.execute(select(SKU).where(SKU.id.in_(sku_uuids)))
        xyz_sku_map = {s.id: s for s in xyz_skus.scalars().all()}

    output: list[dict[str, Any]] = []
    for sku_id, monthly_qties in sku_monthly.items():
        n = len(monthly_qties)
        if n < 2:
            continue
        mean = sum(monthly_qties) / n
        variance = sum((v - mean) ** 2 for v in monthly_qties) / (n - 1)
        std_dev = math.sqrt(variance)
        cv = std_dev / mean if mean > 0 else 0.0
        xyz = _cv_category(cv)

        sku = xyz_sku_map.get(uuid.UUID(sku_id))

        output.append({
            "sku_id": sku_id,
            "sku_code": sku.sku if sku else "",
            "sku_name": sku.name if sku else "",
            "monthly_values": monthly_qties,
            "mean": round(mean, 2),
            "std_dev": round(std_dev, 2),
            "cv": round(cv, 4),
            "xyz_category": xyz,
        })

    return sorted(output, key=lambda x: x["cv"])


async def compute_abc_xyz_matrix(
    db: AsyncSession,
    months: int = 6,
) -> dict[str, list[dict[str, Any]]]:
    """Combine ABC and XYZ into a 3×3 matrix.

    Returns a dict keyed by matrix cell like ``"AX"``, ``"AY"``, …, ``"CZ"``.
    """
    abc = await compute_abc_analysis(db, months=months)
    xyz = await compute_xyz_analysis(db, months=months)

    xyz_map: dict[str, dict] = {s["sku_id"]: s for s in xyz}

    matrix: dict[str, list[dict[str, Any]]] = {
        f"{a}{z}": [] for a in "ABC" for z in "XYZ"
    }

    for item in abc:
        xyz_item = xyz_map.get(item["sku_id"])
        xyz_cat = xyz_item["xyz_category"] if xyz_item else "X"
        cell = f"{item['abc_category']}{xyz_cat}"
        matrix.setdefault(cell, []).append({
            "sku_id": item["sku_id"],
            "sku_code": item["sku_code"],
            "sku_name": item["sku_name"],
            "share_pct": item["share_pct"],
            "cv": xyz_item["cv"] if xyz_item else 0,
            "abc": item["abc_category"],
            "xyz": xyz_cat,
        })

    return matrix
