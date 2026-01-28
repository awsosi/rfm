"""vf redesign - add PUSH and PULL operation types

Revision ID: 004
Revises: 003
Create Date: 2026-01-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add PUSH and PULL operation types and new operation columns."""

    # Add new values to OperationType enum
    # PostgreSQL requires special handling for enum alterations
    op.execute("ALTER TYPE operationtype ADD VALUE IF NOT EXISTS 'PUSH'")
    op.execute("ALTER TYPE operationtype ADD VALUE IF NOT EXISTS 'PULL'")

    # Add original_path column to operations table (for tracking source in PULL operations)
    op.add_column('operations',
        sa.Column('original_path', sa.Text(), nullable=True)
    )

    # Add archive_path column to operations table (for tracking archive location in PUSH operations)
    op.add_column('operations',
        sa.Column('archive_path', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Remove PUSH and PULL operation types and new operation columns."""

    # Remove new columns
    op.drop_column('operations', 'archive_path')
    op.drop_column('operations', 'original_path')

    # Note: PostgreSQL doesn't support removing enum values directly
    # This would require recreating the enum type, which is complex
    # For downgrade, we'll leave the enum values but document this limitation
    pass
