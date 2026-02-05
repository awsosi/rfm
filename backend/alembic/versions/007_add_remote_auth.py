"""Add remote authentication fields to users table

Revision ID: 007
Revises: 006
Create Date: 2026-02-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    """Add remote authentication fields to users table."""
    # Add is_remote_auth column (default False for existing users)
    op.add_column(
        'users',
        sa.Column('is_remote_auth', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add remote_user_id column (nullable, stores external user ID from remote API)
    op.add_column(
        'users',
        sa.Column('remote_user_id', sa.Integer(), nullable=True)
    )

    # Create indexes for efficient lookups
    op.create_index(
        'ix_users_is_remote_auth',
        'users',
        ['is_remote_auth']
    )

    op.create_index(
        'ix_users_remote_user_id',
        'users',
        ['remote_user_id']
    )


def downgrade():
    """Remove remote authentication fields from users table."""
    # Drop indexes
    op.drop_index('ix_users_remote_user_id', table_name='users')
    op.drop_index('ix_users_is_remote_auth', table_name='users')

    # Drop columns
    op.drop_column('users', 'remote_user_id')
    op.drop_column('users', 'is_remote_auth')
