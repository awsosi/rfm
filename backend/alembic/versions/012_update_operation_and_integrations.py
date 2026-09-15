"""Add UPDATE operation type and seed PIM / validation config

Adds the UPDATE value to the operationtype enum and seeds the config rows for
the PIM signalling target, PolkaSQL catalog-name validation and PUSH/UPDATE
content validation.

Note on TODO.md rule 3 (consolidated migrations): 001 is already applied on
live databases, so the enum value has to arrive as its own revision rather
than being merged into 001.

Revision ID: 012
Revises: 011
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '012'
down_revision: Union[str, None] = '011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (key, value, config_type, description)
_CONFIG_SEED = [
    # --- PIM signalling -------------------------------------------------
    ('pim_enabled', 'false', 'BOOLEAN', 'Enable PIM signalling for completed PUSH/PULL/UPDATE operations'),
    ('pim_base_url', 'https://pim-api.vitkac.com', 'STRING', 'PIM API base URL'),
    ('pim_endpoint', '/api/v1/image_catalog/ftp_event', 'STRING', 'PIM ftp_event endpoint path'),
    ('pim_method', 'POST', 'STRING', 'HTTP method used for PIM signalling'),
    ('pim_api_token', '', 'STRING', 'Value sent in the X-API-TOKEN header'),
    ('pim_timeout', '10', 'INT', 'PIM request timeout in seconds'),
    ('pim_push_enabled', 'true', 'BOOLEAN', 'Signal PIM on PUSH'),
    ('pim_push_event_type', 'created', 'STRING', 'eventType reported for PUSH'),
    ('pim_pull_enabled', 'true', 'BOOLEAN', 'Signal PIM on PULL'),
    ('pim_pull_event_type', 'updated', 'STRING', 'eventType reported for PULL'),
    ('pim_update_enabled', 'true', 'BOOLEAN', 'Signal PIM on UPDATE'),
    ('pim_update_event_type', 'updated', 'STRING', 'eventType reported for UPDATE'),
    ('pim_tg_id', '', 'STRING', 'Optional TG identifier for {tg_id}; empty by default'),
    (
        'pim_payload_template',
        '{"files": {files}, "imageCatalog": "{catalog_name}", "eventType": "{event_type}"}',
        'STRING',
        'PIM request body template. Placeholders: {files} {catalog_name} {event_type} {tg_id} {operation_id} {username} {source_path} {dest_path}',
    ),
    # --- PolkaSQL catalog name validation --------------------------------
    ('catalog_validation_enabled', 'false', 'BOOLEAN', 'Validate catalog names against PolkaSQL RFM_ValidateProductName'),
    ('catalog_validation_url', '', 'STRING', 'RFM_ValidateProductName web service URL'),
    ('catalog_validation_api_key', '', 'STRING', 'API key passed to RFM_ValidateProductName'),
    ('catalog_validation_timeout', '5', 'INT', 'Catalog validation timeout in seconds'),
    ('catalog_validation_max_suggestions', '5', 'INT', 'Maximum number of name suggestions to return'),
    ('catalog_validation_fail_open', 'false', 'BOOLEAN', 'Allow operations when PolkaSQL is unreachable (default: fail closed)'),
    # --- PUSH / UPDATE content validation --------------------------------
    ('push_validation_enabled', 'true', 'BOOLEAN', 'Validate directory contents before PUSH/UPDATE'),
    ('push_validation_min_files', '2', 'INT', 'Minimum number of image files required'),
    ('push_validation_allowed_extensions', 'jpg,jpeg,png,gif,bmp,tif,tiff,webp', 'STRING', 'Extensions counted as images'),
    ('push_validation_verify_content', 'true', 'BOOLEAN', 'Verify real file type from magic bytes, not just the extension'),
    # --- UPDATE behaviour -------------------------------------------------
    ('enable_update_archive_mirror', 'false', 'BOOLEAN', 'Mirror UPDATE changes from PATH_B into the PATH_C archive'),
]


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on
    # PostgreSQL < 12; COMMIT first so this works on every supported server.
    op.execute("COMMIT")
    op.execute("ALTER TYPE operationtype ADD VALUE IF NOT EXISTS 'UPDATE'")

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
    keys = [k for k, _, _, _ in _CONFIG_SEED]
    conn.execute(
        sa.text("DELETE FROM config WHERE key = ANY(:keys)"),
        {"keys": keys},
    )
    # PostgreSQL cannot remove a value from an enum type. Rows of type UPDATE
    # would have to be migrated before the label could be dropped, so the enum
    # value is intentionally left in place.
