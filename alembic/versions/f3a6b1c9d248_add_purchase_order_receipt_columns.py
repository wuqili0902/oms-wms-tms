"""add received_qty / received_at to purchase_order_lines

``receive_goods()`` used to be a status flip: it set
``purchase_orders.status = 'received'`` and committed, adding nothing to
inventory and recording nothing about how much of each line arrived.  A vendor
that shipped half an order looked identical to one that shipped all of it, and
the PDA's per-line quantities had nowhere to be stored.

Receiving now books stock per line, which needs the landing quantity on the
line itself — that is what decides whether the PO is ``partial`` or
``received``, and what a second (or replayed) receipt is measured against.

Revision ID: f3a6b1c9d248
Revises: b2c3d4e5f6a7
Create Date: 2026-11-02 09:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'f3a6b1c9d248'
down_revision: str | None = 'b2c3d4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default keeps the backfill single-statement: every existing line is
    # "nothing received yet", which is the only reading that is true of a table
    # that never stored a receipt.
    op.add_column(
        'purchase_order_lines',
        sa.Column(
            'received_qty',
            sa.Numeric(18, 4),
            nullable=False,
            server_default=sa.text('0'),
        ),
    )
    op.add_column(
        'purchase_order_lines',
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('purchase_order_lines', 'received_at')
    op.drop_column('purchase_order_lines', 'received_qty')
