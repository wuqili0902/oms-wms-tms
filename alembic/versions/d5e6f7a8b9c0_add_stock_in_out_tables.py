"""add stock in/out tables (stock_in, stock_in_lines, stock_out, stock_out_lines, stock_inventory_logs)

Revision ID: d5e6f7a8b9c0
Revises: c1d2e3f4a5b6
Create Date: 2026-08-05 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'd5e6f7a8b9c0'
down_revision: str | None = 'c1d2e3f4a5b6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Stock In ──────────────────────────────────────────────────────
    op.create_table('stock_in',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('warehouse_id', sa.UUID(), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('reference_type', sa.String(length=64), nullable=True),
        sa.Column('ref_no', sa.String(length=100), nullable=True),
        sa.Column('supplier_id', sa.UUID(), nullable=True),
        sa.Column('total_qty', sa.Numeric(18, 4), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['supplier_id'], ['vendors.id'], ),
        sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('stock_in_lines',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('stock_in_id', sa.UUID(), nullable=False),
        sa.Column('sku', sa.String(length=64), nullable=True),
        sa.Column('qty_received', sa.Numeric(18, 4), nullable=True),
        sa.Column('batch_no', sa.String(length=64), nullable=True),
        sa.Column('lot_no', sa.String(length=64), nullable=True),
        sa.Column('expiry_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(['stock_in_id'], ['stock_in.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # ── Stock Out ─────────────────────────────────────────────────────
    op.create_table('stock_out',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('warehouse_id', sa.UUID(), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('reference_type', sa.String(length=64), nullable=True),
        sa.Column('ref_no', sa.String(length=100), nullable=True),
        sa.Column('total_qty', sa.Numeric(18, 4), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('stock_out_lines',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('stock_out_id', sa.UUID(), nullable=False),
        sa.Column('sku', sa.String(length=64), nullable=True),
        sa.Column('qty_shipped', sa.Numeric(18, 4), nullable=True),
        sa.Column('batch_no', sa.String(length=64), nullable=True),
        sa.Column('lot_no', sa.String(length=64), nullable=True),
        sa.Column('expiry_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(['stock_out_id'], ['stock_out.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # ── Stock Inventory Log ───────────────────────────────────────────
    op.create_table('stock_inventory_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('warehouse_id', sa.UUID(), nullable=False),
        sa.Column('sku', sa.String(length=64), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('reference_type', sa.String(length=64), nullable=True),
        sa.Column('reference_id', sa.UUID(), nullable=True),
        sa.Column('quantity_change', sa.Numeric(18, 4), nullable=False),
        sa.Column('operator_id', sa.UUID(), nullable=True),
        sa.Column('reason', sa.String(length=32), nullable=True),
        sa.Column('remark', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('stock_inventory_logs')
    op.drop_table('stock_out_lines')
    op.drop_table('stock_out')
    op.drop_table('stock_in_lines')
    op.drop_table('stock_in')
