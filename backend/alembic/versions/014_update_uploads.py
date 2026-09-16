"""Add update_uploads table and UPDATE upload config

UPDATE can now replace or add catalog files with files uploaded through the
WebUI. The uploaded bytes are kept on the API host until the worker has
fetched them; this table records each upload (who, name, size, SHA-256) and
drives garbage collection of the stored files.

Note on TODO.md rule 3 (consolidated migrations): as with 012 and 013, 001 is
already applied on live databases, so the table arrives as its own revision.

Revision ID: 014
Revises: 013
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '014'
down_revision: Union[str, None] = '013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (key, value, config_type, description)
_CONFIG_SEED = [
    ('update_upload_max_mb', '200', 'INT', 'Largest file accepted by UPDATE uploads, in MB'),
    ('update_upload_ttl_hours', '24', 'INT', 'Unused UPDATE uploads are deleted after this many hours'),
]


def upgrade() -> None:
    op.create_table(
        'update_uploads',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('original_filename', sa.Text(), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('operation_id', sa.Integer(), sa.ForeignKey('operations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_update_uploads_user_id', 'update_uploads', ['user_id'])
    op.create_index('ix_update_uploads_operation_id', 'update_uploads', ['operation_id'])
    op.create_index('ix_update_uploads_expires_at', 'update_uploads', ['expires_at'])

    conn = op.get_bind()
    for key, value, config_type, description in _CONFIG_SEED:
        # Never clobber a value an operator already set in the Admin Panel.
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
    conn.execute(
        sa.text("DELETE FROM config WHERE key = ANY(:keys)"),
        {"keys": [k for k, _, _, _ in _CONFIG_SEED]},
    )
    # Files already stored under update_upload_dir are not removed here.
    op.drop_table('update_uploads')
