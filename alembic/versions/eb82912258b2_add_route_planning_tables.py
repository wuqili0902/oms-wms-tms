"""Add route planning tables (TransferHub, CarrierRoute, etc.)

Revision ID: eb82912258b2
Revises: ac07bc39423d
Create Date: 2026-07-19 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'eb82912258b2'
down_revision: Union[str, None] = 'ac07bc39423d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### transfer_hubs ###
    op.create_table('transfer_hubs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('hub_type', sa.Enum('PRIMARY', 'SECONDARY', 'CARGO_STATION', name='transferhubtype'), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=False),
        sa.Column('address', sa.JSON(), nullable=True),
        sa.Column('capacity_weight_kg', sa.Numeric(20, 4), nullable=True),
        sa.Column('contact_name', sa.String(length=100), nullable=True),
        sa.Column('contact_phone', sa.String(length=30), nullable=True),
        sa.Column('status', sa.Enum('OPEN', 'MAINTENANCE', 'CLOSED', name='hubstatus'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_transfer_hubs_code'), 'transfer_hubs', ['code'], unique=True)
    op.create_index(op.f('ix_transfer_hubs_city'), 'transfer_hubs', ['city'], unique=False)
    op.create_index(op.f('ix_transfer_hubs_id'), 'transfer_hubs', ['id'], unique=False)

    # ### carrier_routes ###
    op.create_table('carrier_routes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('carrier_code', sa.Enum('SF_EXPRESS', 'ZTO', 'YUNDA', 'JD_LOGISTICS', 'EMS', name='carriercode'), nullable=False),
        sa.Column('origin_city', sa.String(length=100), nullable=False),
        sa.Column('dest_city', sa.String(length=100), nullable=False),
        sa.Column('distance_km', sa.Numeric(20, 4), nullable=True),
        sa.Column('transit_hours', sa.Numeric(10, 1), nullable=True),
        sa.Column('base_price_per_kg', sa.Numeric(18, 4), nullable=True),
        sa.Column('express_surcharge', sa.Numeric(18, 4), nullable=True),
        sa.Column('min_charge_weight', sa.Numeric(20, 4), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_carrier_routes_origin_city'), 'carrier_routes', ['origin_city'], unique=False)
    op.create_index(op.f('ix_carrier_routes_id'), 'carrier_routes', ['id'], unique=False)

    # ### transport_segments ###
    op.create_table('transport_segments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('transport_order_id', sa.UUID(), nullable=True),
        sa.Column('segment_no', sa.Integer(), nullable=True),
        sa.Column('origin_hub_code', sa.String(length=50), nullable=True),
        sa.Column('dest_hub_code', sa.String(length=50), nullable=True),
        sa.Column('carrier_code', sa.Enum('SF_EXPRESS', 'ZTO', 'YUNDA', 'JD_LOGISTICS', 'EMS', name='carriercode'), nullable=True),
        sa.Column('status', sa.Enum('DRAFT', 'DISPATCHED', 'PICKUP', 'IN_TRANSIT', 'TRANSIT_HUB_ARRIVED', 'SORTING_CENTER', 'OUT_FOR_DELIVERY', 'COMPLETED', 'EXCEPTION', 'CANCELLED', name='transportsegmentstatus'), nullable=True),
        sa.Column('tracking_number', sa.String(length=100), nullable=True),
        sa.Column('estimated_departure_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('actual_departure_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expected_arrival_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('actual_arrival_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('weight_kg', sa.Numeric(20, 4), nullable=True),
        sa.Column('cost_amount', sa.Numeric(18, 2), nullable=True),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(['transport_order_id'], ['transport_orders.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_transport_segments_transport_order_id'), 'transport_segments', ['transport_order_id'], unique=False)
    op.create_index(op.f('ix_transport_segments_id'), 'transport_segments', ['id'], unique=False)

    # ### hub_connections ###
    op.create_table('hub_connections',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('from_hub_code', sa.String(length=50), nullable=False),
        sa.Column('to_hub_code', sa.String(length=50), nullable=False),
        sa.Column('distance_km', sa.Numeric(20, 4), nullable=True),
        sa.Column('transit_hours', sa.Numeric(10, 1), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_hub_connections_id'), 'hub_connections', ['id'], unique=False)

    # ### route_plans ###
    op.create_table('route_plans',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('transport_order_id', sa.UUID(), nullable=False),
        sa.Column('type', sa.Enum('AUTO_GEN', 'MANUAL', name='routeplantype'), nullable=True),
        sa.Column('status', sa.Enum('ROUTE_ACTIVE', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', name='routeplanstatus'), nullable=True),
        sa.Column('origin_city', sa.String(length=100), nullable=False),
        sa.Column('destination_city', sa.String(length=100), nullable=False),
        sa.Column('total_distance_km', sa.Numeric(20, 4), nullable=True),
        sa.Column('total_cost_amount', sa.Numeric(18, 2), nullable=True),
        sa.Column('estimated_transit_hours', sa.Numeric(10, 1), nullable=True),
        sa.Column('plan_json', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['transport_order_id'], ['transport_orders.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('transport_order_id'),
    )
    op.create_index(op.f('ix_route_plans_id'), 'route_plans', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_route_plans_id'), table_name='route_plans')
    op.drop_table('route_plans')
    op.drop_index(op.f('ix_hub_connections_id'), table_name='hub_connections')
    op.drop_table('hub_connections')
    op.drop_index(op.f('ix_transport_segments_id'), table_name='transport_segments')
    op.drop_index(op.f('ix_transport_segments_transport_order_id'), table_name='transport_segments')
    op.drop_table('transport_segments')
    op.drop_index(op.f('ix_carrier_routes_id'), table_name='carrier_routes')
    op.drop_index(op.f('ix_carrier_routes_origin_city'), table_name='carrier_routes')
    op.drop_table('carrier_routes')
    op.drop_index(op.f('ix_transfer_hubs_id'), table_name='transfer_hubs')
    op.drop_index(op.f('ix_transfer_hubs_city'), table_name='transfer_hubs')
    op.drop_index(op.f('ix_transfer_hubs_code'), table_name='transfer_hubs')
    op.drop_table('transfer_hubs')
    # ### enum cleanup (PostgreSQL only — skip for SQLite compat)
    # op.execute('DROP TYPE IF EXISTS transferhubtype')
    # op.execute('DROP TYPE IF EXISTS hubstatus')
    # op.execute('DROP TYPE IF EXISTS transportsegmentstatus')
    # op.execute('DROP TYPE IF EXISTS routeplantype')
    # op.execute('DROP TYPE IF EXISTS routeplanstatus')
