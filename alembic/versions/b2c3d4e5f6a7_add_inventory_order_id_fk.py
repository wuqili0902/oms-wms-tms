"""Add order_id FK to inventory for scoped release.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-06
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Add order_id column to inventory table
    op.add_column('inventory', sa.Column('order_id', sa.UUID(), nullable=True))
    op.create_index('ix_inventory_order_id', 'inventory', ['order_id'])
    op.create_foreign_key('fk_inventory_order_id', 'inventory', 'orders', ['order_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_inventory_order_id', 'inventory', type_='foreignkey')
    op.drop_index('ix_inventory_order_id', table_name='inventory')
    op.drop_column('inventory', 'order_id')
