"""add missing tables (vendors, addresses, purchase_orders, invoices, credit_memos, address_master, sku columns)

Revision ID: d2873c1fc104
Revises: eb47b7e1074b
Create Date: 2026-07-25 14:55:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd2873c1fc104'
down_revision: Union[str, None] = 'eb47b7e1074b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── SKU additional columns ──────────────────────────────────────────
    op.add_column('skus', sa.Column('weight_kg', sa.Numeric(12, 4), nullable=True))
    op.add_column('skus', sa.Column('volume_m3', sa.Numeric(12, 6), nullable=True))
    op.add_column('skus', sa.Column('hs_code', sa.String(12), nullable=True))
    op.add_column('skus', sa.Column('unit_of_measure', sa.String(10), nullable=True))

    # ── Vendors ─────────────────────────────────────────────────────────
    op.create_table('vendors',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vendors_code'), 'vendors', ['code'], unique=True)
    op.create_index(op.f('ix_vendors_id'), 'vendors', ['id'], unique=False)
    op.create_index(op.f('ix_vendors_is_deleted'), 'vendors', ['is_deleted'], unique=False)

    # ── Addresses ───────────────────────────────────────────────────────
    op.create_table('addresses',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('entity_type', sa.String(length=20), nullable=False),
        sa.Column('entity_id', sa.UUID(), nullable=True),
        sa.Column('address_type', sa.String(length=20), nullable=False),
        sa.Column('contact_name', sa.String(length=100), nullable=True),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('address_line_1', sa.String(length=255), nullable=True),
        sa.Column('address_line_2', sa.String(length=255), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('state', sa.String(length=100), nullable=True),
        sa.Column('postal_code', sa.String(length=20), nullable=True),
        sa.Column('country', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_addresses_entity_type'), 'addresses', ['entity_type'], unique=False)
    op.create_index(op.f('ix_addresses_entity_id'), 'addresses', ['entity_id'], unique=False)
    op.create_index(op.f('ix_addresses_id'), 'addresses', ['id'], unique=False)

    # ── Purchase Orders ─────────────────────────────────────────────────
    op.create_table('purchase_orders',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('po_number', sa.String(length=50), nullable=True),
        sa.Column('vendor_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('expected_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('total_amount', sa.Numeric(18, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_purchase_orders_po_number'), 'purchase_orders', ['po_number'], unique=True)
    op.create_index(op.f('ix_purchase_orders_id'), 'purchase_orders', ['id'], unique=False)
    op.create_index(op.f('ix_purchase_orders_is_deleted'), 'purchase_orders', ['is_deleted'], unique=False)

    op.create_table('purchase_order_lines',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('purchase_order_id', sa.UUID(), nullable=False),
        sa.Column('sku_id', sa.UUID(), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('unit_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['purchase_order_id'], ['purchase_orders.id'], ),
        sa.ForeignKeyConstraint(['sku_id'], ['skus.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_purchase_order_lines_id'), 'purchase_order_lines', ['id'], unique=False)

    # ── Invoices ────────────────────────────────────────────────────────
    op.create_table('invoices',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('invoice_number', sa.String(length=50), nullable=True),
        sa.Column('entity_type', sa.String(length=20), nullable=False),
        sa.Column('entity_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('issue_date', sa.Date(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('total_amount', sa.Numeric(18, 2), nullable=True),
        sa.Column('paid_amount', sa.Numeric(18, 2), nullable=True),
        sa.Column('reference_number', sa.String(length=100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invoices_invoice_number'), 'invoices', ['invoice_number'], unique=True)
    op.create_index(op.f('ix_invoices_id'), 'invoices', ['id'], unique=False)
    op.create_index(op.f('ix_invoices_is_deleted'), 'invoices', ['is_deleted'], unique=False)

    op.create_table('invoice_lines',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('invoice_id', sa.UUID(), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('unit_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invoice_lines_id'), 'invoice_lines', ['id'], unique=False)

    # ── Credit Memos ────────────────────────────────────────────────────
    op.create_table('credit_memos',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('credit_memo_number', sa.String(length=50), nullable=True),
        sa.Column('invoice_id', sa.UUID(), nullable=True),
        sa.Column('entity_type', sa.String(length=20), nullable=False),
        sa.Column('entity_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('issue_date', sa.Date(), nullable=True),
        sa.Column('total_amount', sa.Numeric(18, 2), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_credit_memos_credit_memo_number'), 'credit_memos', ['credit_memo_number'], unique=True)
    op.create_index(op.f('ix_credit_memos_id'), 'credit_memos', ['id'], unique=False)
    op.create_index(op.f('ix_credit_memos_is_deleted'), 'credit_memos', ['is_deleted'], unique=False)

    op.create_table('credit_memo_lines',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('credit_memo_id', sa.UUID(), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('unit_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['credit_memo_id'], ['credit_memos.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_credit_memo_lines_id'), 'credit_memo_lines', ['id'], unique=False)

    # ── Address Master (shared core) ────────────────────────────────────
    op.create_table('address_master',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=True),
        sa.Column('entity_type', sa.String(length=20), nullable=False),
        sa.Column('entity_id', sa.UUID(), nullable=True),
        sa.Column('address_type', sa.String(length=20), nullable=False),
        sa.Column('contact_name', sa.String(length=100), nullable=True),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('address_line_1', sa.String(length=255), nullable=True),
        sa.Column('address_line_2', sa.String(length=255), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('state', sa.String(length=100), nullable=True),
        sa.Column('postal_code', sa.String(length=20), nullable=True),
        sa.Column('country', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_address_master_label'), 'address_master', ['label'], unique=False)
    op.create_index(op.f('ix_address_master_entity_type'), 'address_master', ['entity_type'], unique=False)
    op.create_index(op.f('ix_address_master_entity_id'), 'address_master', ['entity_id'], unique=False)
    op.create_index(op.f('ix_address_master_id'), 'address_master', ['id'], unique=False)


def downgrade() -> None:
    op.drop_table('credit_memo_lines')
    op.drop_table('credit_memos')
    op.drop_table('invoice_lines')
    op.drop_table('invoices')
    op.drop_table('purchase_order_lines')
    op.drop_table('purchase_orders')
    op.drop_table('addresses')
    op.drop_table('vendors')
    op.drop_table('address_master')
    op.drop_column('skus', 'unit_of_measure')
    op.drop_column('skus', 'hs_code')
    op.drop_column('skus', 'volume_m3')
    op.drop_column('skus', 'weight_kg')
