"""add worker command model for pull-based command distribution

Revision ID: 005
Revises: 004
Create Date: 2026-01-28

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create worker_commands table for pull-based command distribution."""

    # Create CommandStatus enum
    command_status_enum = postgresql.ENUM(
        'PENDING', 'SENT', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'TIMEOUT',
        name='commandstatus',
        create_type=False
    )
    command_status_enum.create(op.get_bind(), checkfirst=True)

    # Create worker_commands table
    op.create_table(
        'worker_commands',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('operation_id', sa.Integer(), nullable=True),
        sa.Column('command', sa.String(length=50), nullable=False),
        sa.Column('source_path', sa.Text(), nullable=True),
        sa.Column('dest_path', sa.Text(), nullable=True),
        sa.Column('params_json', sa.JSON(), nullable=True),
        sa.Column('status', command_status_enum, nullable=False, server_default='PENDING'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('response_status', sa.String(length=20), nullable=True),
        sa.Column('response_message', sa.Text(), nullable=True),
        sa.Column('response_data', sa.JSON(), nullable=True),
        sa.Column('error_msg', sa.Text(), nullable=True),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='300'),
        sa.ForeignKeyConstraint(['operation_id'], ['operations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('ix_worker_commands_id', 'worker_commands', ['id'])
    op.create_index('ix_worker_commands_worker_id', 'worker_commands', ['worker_id'])
    op.create_index('ix_worker_commands_operation_id', 'worker_commands', ['operation_id'])
    op.create_index('ix_worker_commands_status', 'worker_commands', ['status'])
    op.create_index('ix_worker_commands_created_at', 'worker_commands', ['created_at'])
    op.create_index('ix_worker_commands_worker_status', 'worker_commands', ['worker_id', 'status'])


def downgrade() -> None:
    """Drop worker_commands table."""
    op.drop_index('ix_worker_commands_worker_status', table_name='worker_commands')
    op.drop_index('ix_worker_commands_created_at', table_name='worker_commands')
    op.drop_index('ix_worker_commands_status', table_name='worker_commands')
    op.drop_index('ix_worker_commands_operation_id', table_name='worker_commands')
    op.drop_index('ix_worker_commands_worker_id', table_name='worker_commands')
    op.drop_index('ix_worker_commands_id', table_name='worker_commands')
    op.drop_table('worker_commands')

    # Drop enum type
    command_status_enum = postgresql.ENUM(name='commandstatus')
    command_status_enum.drop(op.get_bind(), checkfirst=True)
