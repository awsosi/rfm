"""Update user roles from ADMIN/OPERATOR/VIEWER to ADMIN/USER and fix defaults

Revision ID: 004
Revises: 003
Create Date: 2026-01-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Update user roles enum and configuration defaults.

    Changes:
    - UserRole: ADMIN/OPERATOR/VIEWER -> ADMIN/USER
    - max_file_listing_items default: 1000 -> 20
    - Convert existing OPERATOR and VIEWER users to USER
    """

    # Step 1: Add USER to the enum
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'USER'")

    # Step 2: Update existing users with OPERATOR or VIEWER roles to USER
    op.execute("UPDATE users SET role = 'USER' WHERE role IN ('OPERATOR', 'VIEWER')")

    # Step 3: Update the max_file_listing_items default to 20
    op.execute("UPDATE config SET value = '20' WHERE key = 'max_file_listing_items'")

    # Note: PostgreSQL doesn't allow removing enum values in a simple way.
    # The OPERATOR and VIEWER values will remain in the enum type but won't be used.
    # For a complete cleanup, a more complex migration involving creating a new type would be needed.


def downgrade() -> None:
    """
    Revert to old role enum and defaults.

    Note: This cannot fully restore the enum since we can't easily remove enum values in PostgreSQL.
    Users with USER role will be converted to VIEWER.
    """

    # Convert USER back to VIEWER
    op.execute("UPDATE users SET role = 'VIEWER' WHERE role = 'USER'")

    # Restore the default for max_file_listing_items
    op.execute("UPDATE config SET value = '1000' WHERE key = 'max_file_listing_items'")
