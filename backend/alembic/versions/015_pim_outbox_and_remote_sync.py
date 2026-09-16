"""PIM delivery outbox, remote sync verification, tgId from PolkaSQL

- ``pim_events``: every PIM notification is stored before it is sent and
  delivered with exponential backoff, so outages and restarts lose nothing.
- ``remote_sync_checks``: optional verification that a pushed catalog's images
  are served by the public image host (off by default).
- ``tgId`` is now resolved per product (``Polka27.elementy.grup_nazwe``) by
  RFM_ValidateProductName, so the static ``pim_tg_id`` setting is removed and
  the default payload template gains ``"tgId": "{tg_id}"``. A template an
  operator has edited is left alone.

Note on TODO.md rule 3 (consolidated migrations): as with 012-014, 001 is
already applied on live databases, so this arrives as its own revision.

Revision ID: 015
Revises: 014
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '015'
down_revision: Union[str, None] = '014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_TEMPLATE = '{"files": {files}, "imageCatalog": "{catalog_name}", "eventType": "{event_type}"}'
NEW_TEMPLATE = (
    '{"tgId": "{tg_id}", "imageCatalog": "{catalog_name}", '
    '"eventType": "{event_type}", "files": {files}}'
)

# (key, value, config_type, description)
_CONFIG_SEED = [
    ('pim_retry_base_seconds', '10', 'INT', 'Delay before the first PIM retry; doubles on every failed attempt'),
    ('pim_retry_max_delay_seconds', '600', 'INT', 'Longest delay between two PIM delivery attempts'),
    ('pim_retry_max_hours', '72', 'INT', 'Give up delivering a PIM event after this many hours (0 = never)'),
    ('remote_sync_check_enabled', 'false', 'BOOLEAN', 'Verify that pushed images are served by the public image host'),
    (
        'remote_sync_check_url_template',
        'https://img.vitkac.com/uploads/product_thumb/{catalog_name}/up/{file}',
        'STRING',
        'Image URL checked per file. Placeholders (URL-encoded): {catalog_name} {file} {tg_id}',
    ),
    ('remote_sync_check_wait_for_pim', 'true', 'BOOLEAN', 'Start checking only after PIM has received the event'),
    ('remote_sync_check_initial_delay_seconds', '60', 'INT', 'Wait this long before the first check'),
    ('remote_sync_check_interval_seconds', '120', 'INT', 'Time between checks of files not yet served'),
    ('remote_sync_check_timeout_minutes', '180', 'INT', 'Report a timeout when images are still missing after this long'),
    ('remote_sync_check_request_timeout', '15', 'INT', 'HTTP timeout per image request, in seconds'),
    ('remote_sync_check_cache_bust', 'true', 'BOOLEAN', 'Add a unique query parameter so CDN-cached answers are bypassed'),
]


def upgrade() -> None:
    op.create_table(
        'pim_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('operation_id', sa.Integer(), sa.ForeignKey('operations.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('operation_type', sa.String(16), nullable=False),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('catalog_name', sa.Text(), nullable=False),
        sa.Column('tg_id', sa.Text(), nullable=True),
        sa.Column('files', sa.JSON(), nullable=False),
        sa.Column('username', sa.Text(), nullable=True),
        sa.Column('source_path', sa.Text(), nullable=True),
        sa.Column('dest_path', sa.Text(), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('queued_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status_code', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_pim_events_catalog_name', 'pim_events', ['catalog_name'])
    op.create_index('ix_pim_events_status_next_attempt', 'pim_events', ['status', 'next_attempt_at'])

    op.create_table(
        'remote_sync_checks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('operation_id', sa.Integer(), sa.ForeignKey('operations.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('catalog_name', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('files', sa.JSON(), nullable=False),
        sa.Column('total_files', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('synced_files', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('wait_event_id', sa.Integer(), sa.ForeignKey('pim_events.id', ondelete='SET NULL'), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_check_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_remote_sync_checks_status_next_check', 'remote_sync_checks', ['status', 'next_check_at'])

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

    conn.execute(sa.text("DELETE FROM config WHERE key = 'pim_tg_id'"))
    conn.execute(
        sa.text("UPDATE config SET value = :new WHERE key = 'pim_payload_template' AND value = :old"),
        {"new": NEW_TEMPLATE, "old": OLD_TEMPLATE},
    )
    conn.execute(
        sa.text("UPDATE config SET description = :description WHERE key = 'pim_payload_template'"),
        {"description": 'PIM request body template. Placeholders: {files} {catalog_name} {event_type} '
                        '{tg_id} {operation_id} {username} {source_path} {dest_path}'},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE config SET value = :old WHERE key = 'pim_payload_template' AND value = :new"),
        {"new": NEW_TEMPLATE, "old": OLD_TEMPLATE},
    )
    conn.execute(
        sa.text(
            "INSERT INTO config (key, value, type, description) "
            "VALUES ('pim_tg_id', '', CAST('STRING' AS configtype), 'Optional TG identifier for {tg_id}') "
            "ON CONFLICT (key) DO NOTHING"
        )
    )
    conn.execute(
        sa.text("DELETE FROM config WHERE key = ANY(:keys)"),
        {"keys": [k for k, _, _, _ in _CONFIG_SEED]},
    )
    op.drop_table('remote_sync_checks')
    op.drop_table('pim_events')
