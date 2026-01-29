"""add path_c_prefix column to workers table

Revision ID: 006
Revises: 005
Create Date: 2026-01-29

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add path_c_prefix column to workers table for archive paths."""
    op.add_column(
        'workers',
        sa.Column('path_c_prefix', sa.String(length=500), nullable=True)
    )


def downgrade() -> None:
    """Remove path_c_prefix column from workers table."""
    op.drop_column('workers', 'path_c_prefix')
