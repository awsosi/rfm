"""PIM file name rule for PUSH/UPDATE

Seeds ``push_validation_file_names`` (on): every catalog file must be named
``<number>.<extension>`` (e.g. ``3.png``), the only form PIM accepts. Without
it the operation succeeds and PIM answers 422 afterwards.

Note on TODO.md rule 3 (consolidated migrations): as with 012-015, 001 is
already applied on live databases, so this arrives as its own revision.

Revision ID: 016
Revises: 015
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '016'
down_revision: Union[str, None] = '015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Never clobber a value an operator already set in the Admin Panel.
    op.get_bind().execute(
        sa.text(
            "INSERT INTO config (key, value, type, description) "
            "VALUES ('push_validation_file_names', 'true', CAST('BOOLEAN' AS configtype), "
            "'Require <number>.<extension> file names (e.g. 3.png), the only form PIM accepts') "
            "ON CONFLICT (key) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM config WHERE key = 'push_validation_file_names'")
    )
