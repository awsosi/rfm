"""Ignore operating system metadata files on PUSH

Seeds ``push_ignore_system_files`` (on): ``.DS_Store``, ``._*``, ``.localized``,
``.apdisk``, ``Thumbs.db``, ``ehthumbs.db`` and ``desktop.ini`` are treated as
ignored file masks (not copied, not validated, not sent to PIM, destroyed at
source) in addition to ``push_ignore_file_masks``.

Note on TODO.md rule 3 (consolidated migrations): as with 012-016, 001 is
already applied on live databases, so this arrives as its own revision.

Revision ID: 017
Revises: 016
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '017'
down_revision: Union[str, None] = '016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Never clobber a value an operator already set in the Admin Panel.
    op.get_bind().execute(
        sa.text(
            "INSERT INTO config (key, value, type, description) "
            "VALUES ('push_ignore_system_files', 'true', CAST('BOOLEAN' AS configtype), "
            "'Also ignore and destroy OS metadata files on PUSH: .DS_Store, ._*, .localized, .apdisk, "
            "Thumbs.db, ehthumbs.db, desktop.ini') "
            "ON CONFLICT (key) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM config WHERE key = 'push_ignore_system_files'")
    )
