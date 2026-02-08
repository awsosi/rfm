"""Add device authorization requests table for OAuth device flow

Revision ID: 011
Revises: 001
Create Date: 2026-02-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '011'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create device_authorization_requests table for Windows client integration."""

    # Create device_authorization_requests table
    op.create_table(
        'device_authorization_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_code', sa.String(length=64), nullable=False),
        sa.Column('user_code', sa.String(length=16), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('approved', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_code'),
        sa.UniqueConstraint('user_code')
    )

    # Create indexes for efficient lookups
    op.create_index('ix_device_authorization_requests_id', 'device_authorization_requests', ['id'])
    op.create_index('ix_device_authorization_requests_device_code', 'device_authorization_requests', ['device_code'])
    op.create_index('ix_device_authorization_requests_user_code', 'device_authorization_requests', ['user_code'])
    op.create_index('ix_device_authorization_requests_user_id', 'device_authorization_requests', ['user_id'])
    op.create_index('ix_device_authorization_requests_expires_at', 'device_authorization_requests', ['expires_at'])


def downgrade() -> None:
    """Drop device_authorization_requests table and related indexes."""

    # Drop indexes
    op.drop_index('ix_device_authorization_requests_expires_at', table_name='device_authorization_requests')
    op.drop_index('ix_device_authorization_requests_user_id', table_name='device_authorization_requests')
    op.drop_index('ix_device_authorization_requests_user_code', table_name='device_authorization_requests')
    op.drop_index('ix_device_authorization_requests_device_code', table_name='device_authorization_requests')
    op.drop_index('ix_device_authorization_requests_id', table_name='device_authorization_requests')

    # Drop table
    op.drop_table('device_authorization_requests')
