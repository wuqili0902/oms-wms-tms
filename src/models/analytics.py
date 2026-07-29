"""ABC-XYZ Inventory Analysis Dashboard — SKU segmentation & demand analytics.

Design
------
The ABC-XYZ model combines two orthogonal classifications to produce a 9-cell matrix:

    A-level (High-value)   >70% of annual revenue
    B-level (Medium-value)  20%-70%
    C-level (Low-value)     <20%

    X-class (Stable demand) CV ≤ 1.0
    Y-class (Variable demand) 1.0 < CV < 2.0
    Z-class (Erratic demand) CV ≥ 2.0

Combined classification: AX, AY, AZ, BX, BY, BZ, CX, CY, CZ → 9 cells

Each cell gets a unique reorder policy derived from the cell's demand pattern.

Key concepts:
    - ABC analysis = Pareto-based revenue segmentation (Pareto principle)
    - XYZ analysis = Coefficient of Variation (CV) of monthly demand
    - Safety stock formula varies by cell (e.g., AX has lowest, CZ highest)

Safety Stock Formulas:
    AX  → Zα × σ_d × √LT        (stable, high-value — low safety stock)
    AY  → Zα × σ_d × √(LT + LT_lead) / 2   (variable demand — medium buffer)
    AZ  → Zα × σ_d × √(LT + 3*LT_lead)     (erratic — large buffer)
"""
import math
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel

# ── ABC Classification ───────────────────────────────────────────────────


class ABCCategory(str):
    A = "A"           # Top 70% of revenue (Pareto)
    B = "B"           # Next 20%
    C = "C"           # Bottom 10%


# ── XYZ Classification ──────────────────────────────────────────────────


class XYZCategory(str):
    X = "X"           # CV ≤ 1.0 (stable demand)
    Y = "Y"           # 1.0 < CV < 2.0 (variable demand)
    Z = "Z"           # CV ≥ 2.0 (erratic / zero-demand)


# ── Analytics Model ─────────────────────────────────────────────────────


class SKUSegment(BaseModel):
    """Single SKU ABC-XYZ classification with derived metrics."""

    sku: str
    category: ABCCategory
    xyz_class: XYZCategory
    annual_revenue: float       # total revenue last 12 months
    monthly_demand_avg: float   # average monthly units sold
    demand_cv: float            # coefficient of variation (std / mean)
    lead_time_days: int         # supplier lead time
    safety_stock_units: int     # computed based on XYZ class
    reorder_point_units: int    # ROP = avg_demand × lead_time + safety_stock
    max_inventory_units: int    # target max inventory level

    def cell_label(self) -> str:
        """Combined classification, e.g. 'AX', 'BZ'."""
        return f"{self.category.value}{self.xyz_class.value}"


def _compute_safety_stock(avg_demand: float, cv: float, lead_time_days: int) -> float:
    z_alpha = 1.65
    demand_std = avg_demand * cv
    if cv <= 1.0:
        return z_alpha * demand_std * math.sqrt(lead_time_days)
    if cv < 2.0:
        return z_alpha * demand_std * math.sqrt((lead_time_days + lead_time_days) / 2)
    return z_alpha * demand_std * math.sqrt(lead_time_days + 3 * lead_time_days)


class InventoryAnalyticsService(BaseModel):
    """Compute ABC-XYZ segmentation and generate reorder recommendations."""

    redis_client: Any  # Redis client handle (injected)

    async def compute_segmentation(self, warehouse_id: str) -> list[SKUSegment]:
        """Run full ABC-XYZ analysis for a warehouse. Returns sorted SKUs."""
        from src.core.database import async_session_factory
        from src.wms.models import StockMovement

        cutoff = datetime.now(UTC) - timedelta(days=365)
        async with async_session_factory() as session:
            from sqlalchemy import func, select

            result = await session.execute(
                select(
                    StockMovement.sku_id,
                    func.sum(StockMovement.quantity).label("total_qty"),
                )
                .where(
                    StockMovement.warehouse_id == warehouse_id,
                    StockMovement.created_at >= cutoff,
                )
                .group_by(StockMovement.sku_id)
            )
            rows = result.all()
            if not rows:
                return self._compute_segmentation_from_stats(warehouse_id)

            total_qty = sum(abs(r.total_qty) for r in rows)
            sorted_rows = sorted(rows, key=lambda r: abs(r.total_qty), reverse=True)

            cumulative = 0
            segments: list[SKUSegment] = []
            for row in sorted_rows:
                value = abs(row.total_qty)
                cumulative += value
                ratio = cumulative / total_qty if total_qty else 0
                if ratio <= 0.7:
                    abc = ABCCategory("A")
                elif ratio <= 0.9:
                    abc = ABCCategory("B")
                else:
                    abc = ABCCategory("C")

                monthly_result = await session.execute(
                    select(
                        func.date_trunc("month", StockMovement.created_at).label("month"),
                        func.sum(StockMovement.quantity).label("month_qty"),
                    )
                    .where(StockMovement.sku_id == row.sku_id, StockMovement.created_at >= cutoff)
                    .group_by("month")
                )
                monthly_qtys = [abs(m.month_qty) for m in monthly_result.all() if m.month_qty]
                demand_cv = (
                    (statistics.stdev(monthly_qtys) / statistics.mean(monthly_qtys))
                    if len(monthly_qtys) > 1 and statistics.mean(monthly_qtys) > 0
                    else 2.0
                )
                if demand_cv <= 1.0:
                    xyz = XYZCategory("X")
                elif demand_cv < 2.0:
                    xyz = XYZCategory("Y")
                else:
                    xyz = XYZCategory("Z")

                months = len(monthly_qtys) or 12
                avg_monthly = value / months
                lead_time = 7
                safety = int(_compute_safety_stock(avg_monthly, demand_cv, lead_time))
                segments.append(
                    SKUSegment(
                        sku=str(row.sku_id),
                        category=abc,
                        xyz_class=xyz,
                        annual_revenue=value,
                        monthly_demand_avg=avg_monthly,
                        demand_cv=demand_cv,
                        lead_time_days=lead_time,
                        safety_stock_units=safety,
                        reorder_point_units=int(avg_monthly * lead_time / 30 + safety),
                        max_inventory_units=int(avg_monthly * 3),
                    )
                )
        return segments

    def _compute_segmentation_from_stats(self, warehouse_id: str) -> list[SKUSegment]:
        """Fallback: return empty segmentation when no movement data exists."""
        return []

    async def get_reorder_suggestions(
        self, warehouse_id: str, top_n: int = 100
    ) -> list[tuple[str, int]]:
        """Return [(sku, order_qty), ...] for the next PO.

        Priority logic:
            1. CY (erratic demand — high safety stock needed)
            2. CZ (erratic + low value — still risky)
            3. AY (variable demand with lead time risk)
        """
        segments = await self.compute_segmentation(warehouse_id)
        priority = {"CZ": 0, "CY": 1, "BZ": 2, "AZ": 3, "AY": 4, "BY": 5, "BX": 6, "AX": 7, "CX": 8}

        def sort_key(seg: SKUSegment) -> tuple:
            return (priority.get(seg.cell_label(), 9), -seg.annual_revenue)

        sorted_segs = sorted(segments, key=sort_key)[:top_n]
        return [(seg.sku, seg.reorder_point_units) for seg in sorted_segs]


# ── Dashboard API Endpoints ──────────────────────────────────────────────

"""
GET /api/v1/analytics/abc-xyz?warehouse_id=WH001 → {segments: [...], summary: {...}}
GET /api/v1/analytics/reorder-suggestions?warehouse_id=WH001&top_n=50 → [{sku, qty}, ...]
POST /api/v1/analytics/regenerate?warehouse_id=WH001 → {status: "ok"}

Cache strategy:
    - Run full analysis daily at 2am UTC (cron)
    - Cache result in Redis with TTL = 6 hours
    - Regenerate on-demand when triggered by ops team
"""
