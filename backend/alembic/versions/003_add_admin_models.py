"""add admin models - samba paths and system metrics

Revision ID: 003
Revises: 002
Create Date: 2026-01-22 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add admin-specific tables."""

    # Create samba_paths table
    op.create_table(
        'samba_paths',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('path_prefix', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('share_type', sa.String(length=50), nullable=True),
        sa.Column('requires_auth', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_samba_paths_id'), 'samba_paths', ['id'], unique=False)
    op.create_index(op.f('ix_samba_paths_name'), 'samba_paths', ['name'], unique=True)
    op.create_index(op.f('ix_samba_paths_is_active'), 'samba_paths', ['is_active'], unique=False)

    # Create system_metrics table
    op.create_table(
        'system_metrics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('active_operations', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active_workers', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active_users', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_operation_duration_seconds', sa.Integer(), nullable=True),
        sa.Column('operations_completed_last_hour', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('operations_failed_last_hour', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cpu_usage_percent', sa.Integer(), nullable=True),
        sa.Column('memory_usage_percent', sa.Integer(), nullable=True),
        sa.Column('disk_usage_percent', sa.Integer(), nullable=True),
        sa.Column('metrics_json', sa.JSON(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_system_metrics_id'), 'system_metrics', ['id'], unique=False)
    op.create_index(op.f('ix_system_metrics_timestamp'), 'system_metrics', ['timestamp'], unique=False)


def downgrade() -> None:
    """Remove admin-specific tables."""
    op.drop_index(op.f('ix_system_metrics_timestamp'), table_name='system_metrics')
    op.drop_index(op.f('ix_system_metrics_id'), table_name='system_metrics')
    op.drop_table('system_metrics')

    op.drop_index(op.f('ix_samba_paths_is_active'), table_name='samba_paths')
    op.drop_index(op.f('ix_samba_paths_name'), table_name='samba_paths')
    op.drop_index(op.f('ix_samba_paths_id'), table_name='samba_paths')
    op.drop_table('samba_paths')
