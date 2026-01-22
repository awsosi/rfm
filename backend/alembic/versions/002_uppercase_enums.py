"""Uppercase enum values

Revision ID: 002
Revises: 001
Create Date: 2026-01-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Update all enum types to use uppercase values.

    This migration:
    1. Creates new enum types with uppercase values
    2. Converts columns to use new types with data conversion
    3. Removes old enum types
    """

    # UserRole enum update
    op.execute("CREATE TYPE userrole_new AS ENUM ('ADMIN', 'OPERATOR', 'VIEWER')")
    op.execute("""
        ALTER TABLE users
        ALTER COLUMN role TYPE userrole_new
        USING (UPPER(role::text)::userrole_new)
    """)
    op.execute("DROP TYPE userrole")
    op.execute("ALTER TYPE userrole_new RENAME TO userrole")

    # WorkerStatus enum update
    op.execute("CREATE TYPE workerstatus_new AS ENUM ('ACTIVE', 'SUSPENDED', 'PENDING')")
    op.execute("""
        ALTER TABLE workers
        ALTER COLUMN status TYPE workerstatus_new
        USING (UPPER(status::text)::workerstatus_new)
    """)
    op.execute("DROP TYPE workerstatus")
    op.execute("ALTER TYPE workerstatus_new RENAME TO workerstatus")

    # OperationType enum update
    op.execute("CREATE TYPE operationtype_new AS ENUM ('COPY', 'MOVE', 'DELETE', 'MKDIR')")
    op.execute("""
        ALTER TABLE operations
        ALTER COLUMN type TYPE operationtype_new
        USING (UPPER(type::text)::operationtype_new)
    """)
    op.execute("DROP TYPE operationtype")
    op.execute("ALTER TYPE operationtype_new RENAME TO operationtype")

    # OperationStatus enum update
    op.execute("CREATE TYPE operationstatus_new AS ENUM ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'ROLLED_BACK')")
    op.execute("""
        ALTER TABLE operations
        ALTER COLUMN status TYPE operationstatus_new
        USING (
            CASE
                WHEN status::text = 'in_progress' THEN 'IN_PROGRESS'
                WHEN status::text = 'rolled_back' THEN 'ROLLED_BACK'
                ELSE UPPER(status::text)
            END::operationstatus_new
        )
    """)
    op.execute("DROP TYPE operationstatus")
    op.execute("ALTER TYPE operationstatus_new RENAME TO operationstatus")

    # ConfigType enum update
    op.execute("CREATE TYPE configtype_new AS ENUM ('STRING', 'INT', 'JSON', 'BOOLEAN')")
    op.execute("""
        ALTER TABLE config
        ALTER COLUMN type TYPE configtype_new
        USING (UPPER(type::text)::configtype_new)
    """)
    op.execute("DROP TYPE configtype")
    op.execute("ALTER TYPE configtype_new RENAME TO configtype")


def downgrade() -> None:
    """
    Revert enum types to lowercase values.
    """

    # ConfigType enum revert
    op.execute("CREATE TYPE configtype_new AS ENUM ('string', 'int', 'json', 'boolean')")
    op.execute("""
        ALTER TABLE config
        ALTER COLUMN type TYPE configtype_new
        USING (LOWER(type::text)::configtype_new)
    """)
    op.execute("DROP TYPE configtype")
    op.execute("ALTER TYPE configtype_new RENAME TO configtype")

    # OperationStatus enum revert
    op.execute("CREATE TYPE operationstatus_new AS ENUM ('pending', 'in_progress', 'completed', 'failed', 'rolled_back')")
    op.execute("""
        ALTER TABLE operations
        ALTER COLUMN status TYPE operationstatus_new
        USING (
            CASE
                WHEN status::text = 'IN_PROGRESS' THEN 'in_progress'
                WHEN status::text = 'ROLLED_BACK' THEN 'rolled_back'
                ELSE LOWER(status::text)
            END::operationstatus_new
        )
    """)
    op.execute("DROP TYPE operationstatus")
    op.execute("ALTER TYPE operationstatus_new RENAME TO operationstatus")

    # OperationType enum revert
    op.execute("CREATE TYPE operationtype_new AS ENUM ('copy', 'move', 'delete', 'mkdir')")
    op.execute("""
        ALTER TABLE operations
        ALTER COLUMN type TYPE operationtype_new
        USING (LOWER(type::text)::operationtype_new)
    """)
    op.execute("DROP TYPE operationtype")
    op.execute("ALTER TYPE operationtype_new RENAME TO operationtype")

    # WorkerStatus enum revert
    op.execute("CREATE TYPE workerstatus_new AS ENUM ('active', 'suspended', 'pending')")
    op.execute("""
        ALTER TABLE workers
        ALTER COLUMN status TYPE workerstatus_new
        USING (LOWER(status::text)::workerstatus_new)
    """)
    op.execute("DROP TYPE workerstatus")
    op.execute("ALTER TYPE workerstatus_new RENAME TO workerstatus")

    # UserRole enum revert
    op.execute("CREATE TYPE userrole_new AS ENUM ('admin', 'operator', 'viewer')")
    op.execute("""
        ALTER TABLE users
        ALTER COLUMN role TYPE userrole_new
        USING (LOWER(role::text)::userrole_new)
    """)
    op.execute("DROP TYPE userrole")
    op.execute("ALTER TYPE userrole_new RENAME TO userrole")
