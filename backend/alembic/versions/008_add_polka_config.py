"""Add PolkaSQL authentication configuration entries

Revision ID: 008
Revises: 007
Create Date: 2026-02-05

"""
import os

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    """Add PolkaSQL authentication configuration entries.

    Seeds DB config from environment variables so fresh deployments
    respect .env settings passed via docker-compose.
    """
    # Remove old Sybase auth config entries
    op.execute("""
        DELETE FROM config WHERE key IN (
            'enable_sybase_auth',
            'sybase_auth_url',
            'sybase_auth_timeout',
            'sybase_auth_stored_proc'
        );
    """)

    # Read from environment (set by docker-compose from .env) with safe defaults
    polka_enabled = os.environ.get('POLKA_AUTH_ENABLED', 'false').lower()
    polka_url = os.environ.get('POLKA_AUTH_URL', '')
    polka_api_key = os.environ.get('POLKA_AUTH_API_KEY', '')
    polka_timeout = os.environ.get('POLKA_AUTH_TIMEOUT', '5')

    # Insert config entries seeded from env (parameterized to avoid injection)
    conn = op.get_bind()
    stmt = text(
        "INSERT INTO config (key, value, type, description) "
        "VALUES (:key, :value, :type, :description) "
        "ON CONFLICT (key) DO NOTHING"
    )
    for key, value, type_, description in [
        ('polka_auth_enabled', polka_enabled, 'BOOLEAN',
         'Enable PolkaSQL/Sybase authentication API'),
        ('polka_auth_url', polka_url, 'STRING',
         'PolkaSQL authentication API URL (e.g., http://polkaserver.local/RFM_Auth)'),
        ('polka_auth_api_key', polka_api_key, 'STRING',
         'API key for PolkaSQL authentication requests'),
        ('polka_auth_timeout', polka_timeout, 'INT',
         'PolkaSQL authentication API timeout in seconds'),
    ]:
        conn.execute(stmt, {
            "key": key, "value": value,
            "type": type_, "description": description,
        })


def downgrade():
    """Remove PolkaSQL config entries and restore Sybase entries."""
    # Remove PolkaSQL config entries
    op.execute("""
        DELETE FROM config WHERE key IN (
            'polka_auth_enabled',
            'polka_auth_url',
            'polka_auth_api_key',
            'polka_auth_timeout'
        );
    """)

    # Restore old Sybase config entries
    op.execute("""
        INSERT INTO config (key, value, type, description) VALUES
        ('enable_sybase_auth', 'false', 'BOOLEAN', 'Enable external Sybase authentication'),
        ('sybase_auth_url', '', 'STRING', 'Sybase API URL for authentication'),
        ('sybase_auth_timeout', '2', 'INT', 'Sybase authentication timeout in seconds'),
        ('sybase_auth_stored_proc', '', 'STRING', 'Sybase stored procedure name for auth')
        ON CONFLICT (key) DO NOTHING;
    """)
