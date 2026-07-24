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
from datetime import date, timedelta
import math
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


class InventoryAnalyticsService(BaseModel):
    """Compute ABC-XYZ segmentation and generate reorder recommendations."""

    redis_client: Any  # Redis client handle (injected)

    async def compute_segmentation(self, warehouse_id: str) -> list[SKUSegment]:
        """Run full ABC-XYZ analysis for a warehouse. Returns sorted SKUs."""
        ...

    async def get_reorder_suggestions(
        self, warehouse_id: str, top_n: int = 100
    ) -> list[tuple[str, int]]:
        """Return [(sku, order_qty), ...] for the next PO.

        Priority logic:
            1. CY (erratic demand — high safety stock needed)
            2. CZ (erratic + low value — still risky)
            3. AY (variable demand with lead time risk)
        """
        ...


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
