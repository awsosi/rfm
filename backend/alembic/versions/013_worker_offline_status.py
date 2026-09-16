"""Add OFFLINE worker status and a working heartbeat timeout

The health check used to mark workers that stopped heartbeating as SUSPENDED,
the same status an administrator sets, so the server could never tell the two
apart and a worker that rebooted stayed out of service until someone
reactivated it by hand. OFFLINE is set only by the health check, and a worker
returns from OFFLINE to ACTIVE by itself when it checks in again.

worker_heartbeat_timeout is now actually read by the health check. Its seed
value of 90s was never used; with a 60s worker heartbeat it would flag a worker
after a single lost heartbeat, so it moves to 180s unless an operator already
changed it.

Note on TODO.md rule 3 (consolidated migrations): 001 is already applied on
live databases, so the enum value has to arrive as its own revision rather
than only being merged into 001 (001 carries it too, for fresh installs).

Existing SUSPENDED workers are left SUSPENDED: rows suspended by the old health
check cannot be told apart from administrator suspensions.

Revision ID: 013
Revises: 012
"""
from typing import Sequence, Union

from alembic import op

revision: str = '013'
down_revision: Union[str, None] = '012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TIMEOUT_DESCRIPTION = 'Worker marked OFFLINE after this many seconds without a heartbeat'


def upgrade() -> None:
    # PostgreSQL 12+ allows ADD VALUE inside a transaction; the new value just
    # cannot be used before commit, and nothing below uses it. Both compose
    # files run postgres:16-alpine.
    op.execute("ALTER TYPE workerstatus ADD VALUE IF NOT EXISTS 'OFFLINE'")

    # Only move the untouched seed value; keep anything an operator set.
    op.execute(
        "UPDATE config SET value = '180' "
        "WHERE key = 'worker_heartbeat_timeout' AND value = '90'"
    )
    op.execute(
        f"UPDATE config SET description = '{_TIMEOUT_DESCRIPTION}' "
        "WHERE key = 'worker_heartbeat_timeout'"
    )


def downgrade() -> None:
    # PostgreSQL cannot remove a value from an enum type, so OFFLINE stays in
    # the type. Previous code cannot load OFFLINE rows; fall back to the old
    # behaviour, where an administrator reactivates such workers.
    op.execute("UPDATE workers SET status = 'SUSPENDED' WHERE status = 'OFFLINE'")
    op.execute(
        "UPDATE config SET value = '90', "
        "description = 'Worker considered offline after this many seconds' "
        "WHERE key = 'worker_heartbeat_timeout' AND value = '180'"
    )
