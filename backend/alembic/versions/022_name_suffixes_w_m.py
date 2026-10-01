"""Accept the _w and _m photo markers in catalog file names

Product photos are now marked with ``_w`` and ``_m`` (``2_w.jpg``,
``3_m.jpg``), also on AI-generated images (``2_w_ai.jpg``, ``3_m_ai.jpg``).
Each entry of ``push_validation_name_suffixes`` is one whole suffix, so the
combinations are listed too.

Only the untouched default ``_ai`` is replaced: a value an operator set in the
Admin Panel is left alone.

Note: ``PUSH_VALIDATION_NAME_SUFFIXES``, when present in the API container's
environment, overrides this row on every restart (``_sync_env_config_to_db``).
docker-compose.yml does not pass it, so the row decides.

Revision ID: 022
Revises: 021
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '022'
down_revision: Union[str, None] = '021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = '_ai'
_NEW = '_ai,_w,_m,_w_ai,_m_ai'

_DESCRIPTION = (
    'Suffixes allowed between the number and the extension, e.g. "_ai" accepts '
    '1_ai.png next to 1.png. Each entry is one whole suffix: list every '
    'combination (_w_ai for 2_w_ai.jpg). Comma-separated, case-insensitive; '
    'empty means numbers only'
)

_OLD_DESCRIPTION = (
    'Suffixes allowed between the number and the extension, e.g. "_ai" accepts '
    '1_ai.png next to 1.png. Comma-separated, case-insensitive; empty means '
    'numbers only'
)


def _replace(old: str, new: str, description: str) -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE config SET value = :new "
            "WHERE key = 'push_validation_name_suffixes' AND value = :old"
        ),
        {"old": old, "new": new},
    )
    bind.execute(
        sa.text(
            "UPDATE config SET description = :description "
            "WHERE key = 'push_validation_name_suffixes'"
        ),
        {"description": description},
    )


def upgrade() -> None:
    _replace(_OLD, _NEW, _DESCRIPTION)


def downgrade() -> None:
    _replace(_NEW, _OLD, _OLD_DESCRIPTION)
