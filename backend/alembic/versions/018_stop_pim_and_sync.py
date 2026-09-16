"""Stopping PIM deliveries and image host checks by hand

``pim_events`` and ``remote_sync_checks`` gain ``cancelled_at`` and
``cancelled_by``: who stopped a pending delivery or an active check, and when.
The CANCELLED status needs no schema change (status columns are plain strings).

Note on TODO.md rule 3 (consolidated migrations): as with 012-017, 001 is
already applied on live databases, so this arrives as its own revision.

Revision ID: 018
Revises: 017
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '018'
down_revision: Union[str, None] = '017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ('pim_events', 'remote_sync_checks')


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column('cancelled_by', sa.Text(), nullable=True))


def downgrade() -> None:
    # A stopped event would otherwise look pending again and be sent
    op.execute("UPDATE pim_events SET status = 'FAILED' WHERE status = 'CANCELLED'")
    for table in _TABLES:
        op.drop_column(table, 'cancelled_by')
        op.drop_column(table, 'cancelled_at')
