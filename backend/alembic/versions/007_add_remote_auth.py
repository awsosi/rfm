"""Add PolkaSQL authentication fields to users table

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
    """Add PolkaSQL/Sybase authentication fields to users table."""
    # Add is_polka_auth column (default False for existing users)
    op.add_column(
        'users',
        sa.Column('is_polka_auth', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add polka_user_id column (nullable, stores PolkaSQL worker ID)
    op.add_column(
        'users',
        sa.Column('polka_user_id', sa.Integer(), nullable=True)
    )

    # Create indexes for efficient lookups
    op.create_index(
        'ix_users_is_polka_auth',
        'users',
        ['is_polka_auth']
    )

    op.create_index(
        'ix_users_polka_user_id',
        'users',
        ['polka_user_id']
    )


def downgrade():
    """Remove PolkaSQL authentication fields from users table."""
    # Drop indexes
    op.drop_index('ix_users_polka_user_id', table_name='users')
    op.drop_index('ix_users_is_polka_auth', table_name='users')

    # Drop columns
    op.drop_column('users', 'polka_user_id')
    op.drop_column('users', 'is_polka_auth')
