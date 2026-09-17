"""PULL reports eventType "deleted" to PIM

A PULL removes the catalog from PATH_B, so PIM must hear "deleted", not
"updated". Migration 012 seeded ``pim_pull_event_type = 'updated'``; that
seeded default is switched. Any other value was set by an operator and is kept.

Note on TODO.md rule 3 (consolidated migrations): as with 012-018, 001 is
already applied on live databases, so this arrives as its own revision.

Revision ID: 019
Revises: 018
"""
from typing import Sequence, Union

from alembic import op

revision: str = '019'
down_revision: Union[str, None] = '018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE config SET value = 'deleted' "
        "WHERE key = 'pim_pull_event_type' AND value = 'updated'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE config SET value = 'updated' "
        "WHERE key = 'pim_pull_event_type' AND value = 'deleted'"
    )
