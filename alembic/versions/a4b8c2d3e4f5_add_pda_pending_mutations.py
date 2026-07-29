"""add pda_pending_mutations table

Revision ID: a4b8c2d3e4f5
Revises: d2873c1fc104
Create Date: 2026-07-26 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a4b8c2d3e4f5'
down_revision: Union[str, None] = 'd2873c1fc104'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('pda_pending_mutations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('device_id', sa.String(length=50), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.String(length=100), nullable=False),
        sa.Column('operation', sa.String(length=20), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('synced_at', sa.DateTime(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_pda_pending_mutations_device_id'), 'pda_pending_mutations', ['device_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_pda_pending_mutations_device_id'), table_name='pda_pending_mutations')
    op.drop_table('pda_pending_mutations')
