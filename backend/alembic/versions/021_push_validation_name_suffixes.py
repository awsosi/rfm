"""Configurable file name suffixes for the PIM file name rule

Seeds ``push_validation_name_suffixes`` (``_ai``): the suffixes a catalog file
may carry between the number and the extension, so ``1_ai.png`` passes the
``push_validation_file_names`` rule alongside ``1.png``. Matching is
case-insensitive, so ``_ai``, ``_AI``, ``_Ai`` and ``_aI`` all pass. An empty
value means numbers only, i.e. the rule as it behaved before this revision.

Also refreshes the ``push_validation_file_names`` description, which still
promised ``<number>.<extension>`` as the only accepted form.

Note on TODO.md rule 3 (consolidated migrations): as with 012-020, 001 is
already applied on live databases, so this arrives as its own revision.

Revision ID: 021
Revises: 020
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '021'
down_revision: Union[str, None] = '020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DESCRIPTION = (
    'Suffixes allowed between the number and the extension, e.g. "_ai" accepts '
    '1_ai.png next to 1.png. Comma-separated, case-insensitive; empty means '
    'numbers only'
)

_FILE_NAMES_DESCRIPTION = (
    'Require <number>[<suffix>].<extension> file names (e.g. 3.png, 3_ai.png), '
    'the only form PIM accepts'
)


def upgrade() -> None:
    bind = op.get_bind()
    # Never clobber a value an operator already set in the Admin Panel.
    bind.execute(
        sa.text(
            "INSERT INTO config (key, value, type, description) "
            "VALUES ('push_validation_name_suffixes', '_ai', CAST('STRING' AS configtype), "
            ":description) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"description": _DESCRIPTION},
    )
    # The description is ours, not the operator's, so it is safe to correct.
    bind.execute(
        sa.text(
            "UPDATE config SET description = :description "
            "WHERE key = 'push_validation_file_names'"
        ),
        {"description": _FILE_NAMES_DESCRIPTION},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM config WHERE key = 'push_validation_name_suffixes'")
    )
    bind.execute(
        sa.text(
            "UPDATE config SET description = "
            "'Require <number>.<extension> file names (e.g. 3.png), the only form PIM accepts' "
            "WHERE key = 'push_validation_file_names'"
        )
    )
