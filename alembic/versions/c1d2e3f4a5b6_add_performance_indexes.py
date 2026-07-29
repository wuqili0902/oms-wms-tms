"""add performance indexes (orders.created_at, stock_movements.sku_id, stock_movements.created_at)

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-07-26 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # orders.created_at — used in analytics get_order_trends() date filtering/grouping
    op.create_index("ix_orders_created_at", "orders", ["created_at"], unique=False)

    # stock_movements.sku_id — used in ABC/XYZ analysis GROUP BY sku_id
    op.create_index("ix_stock_movements_sku_id", "stock_movements", ["sku_id"], unique=False)

    # stock_movements.created_at — used in ABC/XYZ analysis date range filtering
    op.create_index("ix_stock_movements_created_at", "stock_movements", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_index("ix_stock_movements_sku_id", table_name="stock_movements")
    op.drop_index("ix_stock_movements_created_at", table_name="stock_movements")
