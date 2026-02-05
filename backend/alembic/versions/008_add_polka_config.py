"""Add PolkaSQL authentication configuration entries

Revision ID: 008
Revises: 007
Create Date: 2026-02-05

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    """Add PolkaSQL authentication configuration entries."""
    # Remove old Sybase auth config entries
    op.execute("""
        DELETE FROM config WHERE key IN (
            'enable_sybase_auth',
            'sybase_auth_url',
            'sybase_auth_timeout',
            'sybase_auth_stored_proc'
        );
    """)

    # Insert new PolkaSQL auth config entries
    op.execute("""
        INSERT INTO config (key, value, type, description) VALUES
        ('polka_auth_enabled', 'false', 'BOOLEAN', 'Enable PolkaSQL/Sybase authentication API'),
        ('polka_auth_url', '', 'STRING', 'PolkaSQL authentication API URL (e.g., http://polkaserver.local/RFM_Auth)'),
        ('polka_auth_api_key', '', 'STRING', 'API key for PolkaSQL authentication requests'),
        ('polka_auth_timeout', '5', 'INT', 'PolkaSQL authentication API timeout in seconds')
        ON CONFLICT (key) DO NOTHING;
    """)


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
