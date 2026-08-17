"""fix TMS schema drift: estimated_delivery_date type + hub_connections unique index

Revision ID: e1a2b3c4d5e6
Revises: 26f0642a5601
Create Date: 2026-08-17 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'e1a2b3c4d5e6'
down_revision: str | None = '26f0642a5601'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fix estimated_delivery_date: model changed from String(30) to Date,
    # but migration was never updated. Convert existing string values to date.
    op.alter_column(
        'transport_orders',
        'estimated_delivery_date',
        existing_type=sa.String(length=30),
        type_=sa.Date(),
        existing_nullable=True,
        postgres_using="estimated_delivery_date::date",
    )

    # Add unique constraint on hub_connections(from_hub_code, to_hub_code).
    # First deduplicate existing rows (keep the earliest by created_at).
    op.execute("""
        DELETE FROM hub_connections
        WHERE id NOT IN (
            SELECT DISTINCT ON (from_hub_code, to_hub_code) id
            FROM hub_connections
            ORDER BY from_hub_code, to_hub_code, created_at ASC
        )
    """)
    op.create_index(
        'uq_hub_connections',
        'hub_connections',
        ['from_hub_code', 'to_hub_code'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_hub_connections', table_name='hub_connections')
    op.alter_column(
        'transport_orders',
        'estimated_delivery_date',
        existing_type=sa.Date(),
        type_=sa.String(length=30),
        existing_nullable=True,
    )
