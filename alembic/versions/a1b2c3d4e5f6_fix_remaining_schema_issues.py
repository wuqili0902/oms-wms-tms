"""fix remaining schema issues: FK indexes, constraints, shipment dates, is_active columns

Revision ID: a1b2c3d4e5f6
Revises: e1a2b3c4d5e6
Create Date: 2026-09-06 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = 'e1a2b3c4d5e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. Add missing FK indexes ──────────────────────────────────────────

    # OMS
    op.create_index('ix_orders_customer_id', 'orders', ['customer_id'])
    op.create_index('ix_orders_warehouse_id', 'orders', ['warehouse_id'])
    op.create_index('ix_order_status_logs_order_id', 'order_status_logs', ['order_id'])
    op.create_index('ix_order_status_logs_operator_id', 'order_status_logs', ['operator_id'])
    op.create_index('ix_merge_groups_warehouse_id', 'merge_groups', ['warehouse_id'])
    op.create_index('ix_split_child_orders_parent_order_id', 'split_child_orders', ['parent_order_id'])
    op.create_index('ix_split_child_orders_child_order_id', 'split_child_orders', ['child_order_id'])
    op.create_index('ix_split_child_orders_merge_group_id', 'split_child_orders', ['merge_group_id'])

    # WMS
    op.create_index('ix_inventory_location_id', 'inventory', ['location_id'])
    op.create_index('ix_stock_movements_source_warehouse_id', 'stock_movements', ['source_warehouse_id'])
    op.create_index('ix_stock_movements_target_warehouse_id', 'stock_movements', ['target_warehouse_id'])
    op.create_index('ix_stock_movements_source_location_id', 'stock_movements', ['source_location_id'])
    op.create_index('ix_stock_movements_target_location_id', 'stock_movements', ['target_location_id'])
    op.create_index('ix_stock_movements_sku_id', 'stock_movements', ['sku_id'])
    op.create_index('ix_picking_waves_warehouse_id', 'picking_waves', ['warehouse_id'])
    op.create_index('ix_picking_waves_assignee_id', 'picking_waves', ['assignee_id'])
    op.create_index('ix_packing_records_picking_wave_id', 'packing_records', ['picking_wave_id'])
    op.create_index('ix_shipments_order_id', 'shipments', ['order_id'])
    op.create_index('ix_shipments_warehouse_id', 'shipments', ['warehouse_id'])
    op.create_index('ix_shipments_packing_record_id', 'shipments', ['packing_record_id'])
    op.create_index('ix_purchase_orders_vendor_id', 'purchase_orders', ['vendor_id'])
    op.create_index('ix_purchase_order_lines_purchase_order_id', 'purchase_order_lines', ['purchase_order_id'])
    op.create_index('ix_purchase_order_lines_sku_id', 'purchase_order_lines', ['sku_id'])
    op.create_index('ix_invoice_lines_invoice_id', 'invoice_lines', ['invoice_id'])
    op.create_index('ix_credit_memos_invoice_id', 'credit_memos', ['invoice_id'])
    op.create_index('ix_credit_memo_lines_credit_memo_id', 'credit_memo_lines', ['credit_memo_id'])
    op.create_index('ix_transfer_orders_source_warehouse_id', 'transfer_orders', ['source_warehouse_id'])
    op.create_index('ix_transfer_orders_target_warehouse_id', 'transfer_orders', ['target_warehouse_id'])
    op.create_index('ix_transfer_order_lines_transfer_order_id', 'transfer_order_lines', ['transfer_order_id'])
    op.create_index('ix_transfer_order_lines_sku_id', 'transfer_order_lines', ['sku_id'])

    # TMS
    op.create_index('ix_tracking_events_operator_id', 'tracking_events', ['operator_id'])
    op.create_index('ix_return_orders_transport_order_id', 'return_orders', ['transport_order_id'])
    op.create_index('ix_return_orders_destination_warehouse_id', 'return_orders', ['destination_warehouse_id'])
    op.create_index('ix_device_sessions_device_id', 'device_sessions', ['device_id'])
    op.create_index('ix_sync_logs_device_id', 'sync_logs', ['device_id'])

    # ── 2. Add missing unique constraints ──────────────────────────────────

    op.create_index(
        'uq_notification_preferences_user_type_channel',
        'notification_preferences',
        ['user_id', 'notification_type', 'channel'],
        unique=True,
    )

    # ── 3. Fix is_active columns (were Python attrs, now real DB columns) ──

    # carrier_configs.is_active
    op.add_column('carrier_configs', sa.Column('is_active', sa.Boolean(), server_default='true'))
    # carrier_routes.is_active
    op.add_column('carrier_routes', sa.Column('is_active', sa.Boolean(), server_default='true'))
    # hub_connections.is_active
    op.add_column('hub_connections', sa.Column('is_active', sa.Boolean(), server_default='true'))

    # ── 4. Fix FreightTier carrier_code (was primary_key=True, now just indexed)

    # The PK conflict is fixed in the model; no DB change needed since
    # UUIDMixin already provides the id PK. Just ensure carrier_code is indexed.

    # ── 5. Shipment dates: String(30) -> DateTime ──────────────────────────

    op.alter_column(
        'shipments',
        'shipped_at',
        existing_type=sa.String(length=30),
        type_=sa.DateTime(timezone=True),
        nullable=True,
        postgres_using="shipped_at::timestamp with time zone",
    )
    op.alter_column(
        'shipments',
        'delivered_at',
        existing_type=sa.String(length=30),
        type_=sa.DateTime(timezone=True),
        nullable=True,
        postgres_using="delivered_at::timestamp with time zone",
    )


def downgrade() -> None:
    # Reverse shipment date changes
    op.alter_column(
        'shipments', 'delivered_at',
        existing_type=sa.DateTime(timezone=True),
        type_=sa.String(length=30),
    )
    op.alter_column(
        'shipments', 'shipped_at',
        existing_type=sa.DateTime(timezone=True),
        type_=sa.String(length=30),
    )

    # Remove is_active columns
    op.drop_column('hub_connections', 'is_active')
    op.drop_column('carrier_routes', 'is_active')
    op.drop_column('carrier_configs', 'is_active')

    # Remove unique constraint
    op.drop_index('uq_notification_preferences_user_type_channel', table_name='notification_preferences')

    # Remove TMS indexes
    op.drop_index('ix_sync_logs_device_id', table_name='sync_logs')
    op.drop_index('ix_device_sessions_device_id', table_name='device_sessions')
    op.drop_index('ix_return_orders_destination_warehouse_id', table_name='return_orders')
    op.drop_index('ix_return_orders_transport_order_id', table_name='return_orders')
    op.drop_index('ix_tracking_events_operator_id', table_name='tracking_events')

    # Remove WMS indexes
    op.drop_index('ix_transfer_order_lines_sku_id', table_name='transfer_order_lines')
    op.drop_index('ix_transfer_order_lines_transfer_order_id', table_name='transfer_order_lines')
    op.drop_index('ix_transfer_orders_target_warehouse_id', table_name='transfer_orders')
    op.drop_index('ix_transfer_orders_source_warehouse_id', table_name='transfer_orders')
    op.drop_index('ix_credit_memo_lines_credit_memo_id', table_name='credit_memo_lines')
    op.drop_index('ix_credit_memos_invoice_id', table_name='credit_memos')
    op.drop_index('ix_invoice_lines_invoice_id', table_name='invoice_lines')
    op.drop_index('ix_purchase_order_lines_sku_id', table_name='purchase_order_lines')
    op.drop_index('ix_purchase_order_lines_purchase_order_id', table_name='purchase_order_lines')
    op.drop_index('ix_purchase_orders_vendor_id', table_name='purchase_orders')
    op.drop_index('ix_shipments_packing_record_id', table_name='shipments')
    op.drop_index('ix_shipments_warehouse_id', table_name='shipments')
    op.drop_index('ix_shipments_order_id', table_name='shipments')
    op.drop_index('ix_packing_records_picking_wave_id', table_name='packing_records')
    op.drop_index('ix_picking_waves_assignee_id', table_name='picking_waves')
    op.drop_index('ix_picking_waves_warehouse_id', table_name='picking_waves')
    op.drop_index('ix_stock_movements_sku_id', table_name='stock_movements')
    op.drop_index('ix_stock_movements_target_location_id', table_name='stock_movements')
    op.drop_index('ix_stock_movements_source_location_id', table_name='stock_movements')
    op.drop_index('ix_stock_movements_target_warehouse_id', table_name='stock_movements')
    op.drop_index('ix_stock_movements_source_warehouse_id', table_name='stock_movements')
    op.drop_index('ix_inventory_location_id', table_name='inventory')

    # Remove OMS indexes
    op.drop_index('ix_split_child_orders_merge_group_id', table_name='split_child_orders')
    op.drop_index('ix_split_child_orders_child_order_id', table_name='split_child_orders')
    op.drop_index('ix_split_child_orders_parent_order_id', table_name='split_child_orders')
    op.drop_index('ix_merge_groups_warehouse_id', table_name='merge_groups')
    op.drop_index('ix_order_status_logs_operator_id', table_name='order_status_logs')
    op.drop_index('ix_order_status_logs_order_id', table_name='order_status_logs')
    op.drop_index('ix_orders_warehouse_id', table_name='orders')
    op.drop_index('ix_orders_customer_id', table_name='orders')
