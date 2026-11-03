"""add shipments.shipment_no

The 发货管理 screen's first column asks the API for ``shipment_no``.  It never
had one: every row rendered blank, and the only handle on a shipment — in the
list, on the carrier handover, in the 对账 sheet — was its uuid.

``shipment_no`` is the number those documents already name.  It is generated at
creation from the ship date and a uuid suffix, the way ``create_order``
generates ``order_no``, and it is unique so two shipments can never arrive at a
carrier under the same number.

Existing rows get a number derived from their id backfill, so the column is
NOT NULL/unique on a populated table rather than an empty string repeated once
per row (which a unique index would reject outright).

Revision ID: c7f3a91b4d02
Revises: f3a6b1c9d248
Create Date: 2026-11-03 09:30:00.000000
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'c7f3a91b4d02'
# The version graph has several heads (a4b8c2d3e4f5, b0c1d2e3f4a5, d2873c1fc104,
# eb47b7e1074b, f6e7d8c9b0a1).  This extends the newest-dated one; joining the
# heads into a single line is a separate, deliberate cleanup — inventing a
# merge here would claim an upgrade order for migrations that were never
# checked against each other.
down_revision: str | None = 'f3a6b1c9d248'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'shipments',
        sa.Column('shipment_no', sa.String(length=50), nullable=True),
    )

    # Backfill before the unique index: a table of shipments that all answered
    # "no number" cannot get the same empty string 40 times under a unique
    # constraint.  SHIP-<uuid hex8> is not the shape new rows use (they carry
    # the ship date), but it is stable, unique, and derived from data the row
    # already has.
    existing_ids = op.get_bind().execute(sa.text('SELECT id FROM shipments')).scalars()
    update = sa.text('UPDATE shipments SET shipment_no = :no WHERE id = :id')
    for shipment_id in existing_ids:
        op.get_bind().execute(
            update,
            {'no': f"SHIP-{uuid.UUID(str(shipment_id)).hex[:8].upper()}", 'id': str(shipment_id)},
        )

    op.alter_column('shipments', 'shipment_no', existing_type=sa.String(length=50), nullable=False)
    op.create_index(op.f('ix_shipments_shipment_no'), 'shipments', ['shipment_no'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_shipments_shipment_no'), table_name='shipments')
    op.drop_column('shipments', 'shipment_no')
