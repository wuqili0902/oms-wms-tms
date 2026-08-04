"""add notifications and notification_preferences tables

Revision ID: f6e7d8c9b0a1
Revises: a4b8c2d3e4f5
Create Date: 2026-07-26 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f6e7d8c9b0a1'
down_revision: Union[str, None] = 'a4b8c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('notifications',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('type', sa.Enum('ORDER_STATUS_CHANGE', 'ORDER_CREATED', 'LOW_STOCK_ALERT',
                                  'TRANSPORT_STATUS_CHANGE', 'DELIVERY_CONFIRMED',
                                  'EXCEPTION_OCCURRED', 'SYSTEM_ALERT',
                                  name='notificationtype'), nullable=False),
        sa.Column('channel', sa.Enum('EMAIL', 'WEBSOCKET', 'PUSH',
                                     name='notificationchannel'), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('data', sa.Text(), nullable=True),
        sa.Column('is_read', sa.Boolean(), default=False, nullable=False),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)

    op.create_table('notification_preferences',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('notification_type', sa.Enum('ORDER_STATUS_CHANGE', 'ORDER_CREATED', 'LOW_STOCK_ALERT',
                                                'TRANSPORT_STATUS_CHANGE', 'DELIVERY_CONFIRMED',
                                                'EXCEPTION_OCCURRED', 'SYSTEM_ALERT',
                                                name='notificationtype'), nullable=False),
        sa.Column('channel', sa.Enum('EMAIL', 'WEBSOCKET', 'PUSH',
                                     name='notificationchannel'), nullable=False),
        sa.Column('enabled', sa.Boolean(), default=True, nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_notification_preferences_user_id'), 'notification_preferences', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_notification_preferences_user_id'), table_name='notification_preferences')
    op.drop_table('notification_preferences')
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_table('notifications')
    op.execute('DROP TYPE IF EXISTS notificationtype')
    op.execute('DROP TYPE IF EXISTS notificationchannel')
