"""Session lifetime, "Remember me" and admin password confirmation

``sessions`` gains:
- ``remember_me``: the session was opened with "Remember me" (never for an
  admin); it lives ``session_remember_me_days`` instead of
  ``session_lifetime_days``.
- ``reauthenticated_at``: when the user last typed their password in this
  session (login or confirmation). Admin changes to system settings require it
  within ``admin_reauth_minutes``.

``session_lifetime_days`` existed but was never read; its seeded 30 becomes 5.
Any other value was set by an operator and is kept.

Note on TODO.md rule 3 (consolidated migrations): as with 012-019, 001 is
already applied on live databases, so this arrives as its own revision.

Revision ID: 020
Revises: 019
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '020'
down_revision: Union[str, None] = '019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (key, value, config_type, description)
_CONFIG_SEED = [
    ('session_remember_me_days', '30', 'INT', 'Session lifetime in days with "Remember me" (not for admins)'),
    ('admin_reauth_minutes', '15', 'INT', 'Minutes an admin password confirmation stays valid for system setting changes'),
]


def upgrade() -> None:
    op.add_column('sessions', sa.Column('remember_me', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('sessions', sa.Column('reauthenticated_at', sa.DateTime(timezone=True), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE config SET value = '5', description = 'Session lifetime in days (admins, and users without \"Remember me\")' "
        "WHERE key = 'session_lifetime_days' AND value = '30'"
    ))
    for key, value, config_type, description in _CONFIG_SEED:
        conn.execute(
            sa.text(
                "INSERT INTO config (key, value, type, description) "
                "VALUES (:key, :value, CAST(:type AS configtype), :description) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "value": value, "type": config_type, "description": description},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM config WHERE key IN ('session_remember_me_days', 'admin_reauth_minutes')"
    ))
    conn.execute(sa.text(
        "UPDATE config SET value = '30', description = 'Session token lifetime in days' "
        "WHERE key = 'session_lifetime_days' AND value = '5'"
    ))
    op.drop_column('sessions', 'reauthenticated_at')
    op.drop_column('sessions', 'remember_me')
