"""Initial schema with all tables and default admin user

Revision ID: 001
Revises:
Create Date: 2026-01-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create all tables and insert default configuration.

    Includes:
    - Users table with RBAC
    - Sessions table for authentication
    - Workers table for Windows services
    - Operations table with audit trail
    - Operation-Worker association table
    - Audit logs table (immutable)
    - Config table for parameters
    - Default configuration values
    
    Note: Default admin user is created during env.py migration process
    from INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PASSWORD environment variables.
    """

    # Create extensions
    op.execute("""
        CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    """)

    # Create ENUM types (with IF NOT EXISTS check)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'userrole') THEN
                CREATE TYPE userrole AS ENUM ('ADMIN', 'OPERATOR', 'VIEWER');
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'workerstatus') THEN
                CREATE TYPE workerstatus AS ENUM ('ACTIVE', 'SUSPENDED', 'PENDING');
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'operationtype') THEN
                CREATE TYPE operationtype AS ENUM ('COPY', 'MOVE', 'DELETE', 'MKDIR');
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'operationstatus') THEN
                CREATE TYPE operationstatus AS ENUM ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'ROLLED_BACK');
            END IF;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'configtype') THEN
                CREATE TYPE configtype AS ENUM ('STRING', 'INT', 'JSON', 'BOOLEAN');
            END IF;
        END $$;
    """)

    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', postgresql.ENUM('ADMIN', 'OPERATOR', 'VIEWER', name='userrole', create_type=False), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)
    op.create_index(op.f('ix_users_is_active'), 'users', ['is_active'], unique=False)

    # Create sessions table
    op.create_table(
        'sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=512), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sessions_id'), 'sessions', ['id'], unique=False)
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_index(op.f('ix_sessions_token'), 'sessions', ['token'], unique=True)
    op.create_index(op.f('ix_sessions_expires_at'), 'sessions', ['expires_at'], unique=False)

    # Create workers table
    op.create_table(
        'workers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('hostname', sa.String(length=255), nullable=True),
        sa.Column('path_a_prefix', sa.String(length=500), nullable=True),
        sa.Column('path_b_prefix', sa.String(length=500), nullable=True),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('status', postgresql.ENUM('ACTIVE', 'SUSPENDED', 'PENDING', name='workerstatus', create_type=False), nullable=False),
        sa.Column('version', sa.String(length=50), nullable=True),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workers_id'), 'workers', ['id'], unique=False)
    op.create_index(op.f('ix_workers_name'), 'workers', ['name'], unique=True)
    op.create_index(op.f('ix_workers_status'), 'workers', ['status'], unique=False)
    op.create_index(op.f('ix_workers_last_heartbeat'), 'workers', ['last_heartbeat'], unique=False)

    # Create operations table
    op.create_table(
        'operations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('type', postgresql.ENUM('COPY', 'MOVE', 'DELETE', 'MKDIR', name='operationtype', create_type=False), nullable=False),
        sa.Column('source_path', sa.Text(), nullable=False),
        sa.Column('dest_path', sa.Text(), nullable=True),
        sa.Column('status', postgresql.ENUM('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'ROLLED_BACK', name='operationstatus', create_type=False), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_msg', sa.Text(), nullable=True),
        sa.Column('rollback_operation_id', sa.Integer(), nullable=True),
        sa.Column('file_count', sa.Integer(), nullable=True),
        sa.Column('total_size_bytes', sa.Integer(), nullable=True),
        sa.Column('params_json', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['rollback_operation_id'], ['operations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_operations_id'), 'operations', ['id'], unique=False)
    op.create_index(op.f('ix_operations_user_id'), 'operations', ['user_id'], unique=False)
    op.create_index(op.f('ix_operations_type'), 'operations', ['type'], unique=False)
    op.create_index(op.f('ix_operations_status'), 'operations', ['status'], unique=False)
    op.create_index(op.f('ix_operations_started_at'), 'operations', ['started_at'], unique=False)
    op.create_index(op.f('ix_operations_completed_at'), 'operations', ['completed_at'], unique=False)
    op.create_index('ix_operations_user_status', 'operations', ['user_id', 'status'], unique=False)
    op.create_index('ix_operations_created_at', 'operations', ['created_at'], unique=False)

    # Create operation_workers association table
    op.create_table(
        'operation_workers',
        sa.Column('operation_id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('worker_status', postgresql.ENUM('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'ROLLED_BACK', name='operationstatus', create_type=False), nullable=False),
        sa.Column('worker_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('worker_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('worker_error_msg', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['operation_id'], ['operations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('operation_id', 'worker_id')
    )

    # Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('operation_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('details_json', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('remote_api_sent', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('remote_api_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['operation_id'], ['operations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_id'), 'audit_logs', ['id'], unique=False)
    op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_operation_id'), 'audit_logs', ['operation_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_timestamp'), 'audit_logs', ['timestamp'], unique=False)
    op.create_index('ix_audit_logs_user_timestamp', 'audit_logs', ['user_id', 'timestamp'], unique=False)
    op.create_index('ix_audit_logs_action_timestamp', 'audit_logs', ['action', 'timestamp'], unique=False)

    # Create config table
    op.create_table(
        'config',
        sa.Column('key', sa.String(length=200), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('type', postgresql.ENUM('STRING', 'INT', 'JSON', 'BOOLEAN', name='configtype', create_type=False), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )

    # Insert default admin user
    # Password: admin123
    # Hash generated with: argon2-cffi with default parameters
    #op.execute("""
    #    INSERT INTO users (id, username, password_hash, role, is_active)
    #    VALUES (
    #        1,
    #        'admin',
    #        '$argon2id$v=19$m=65536,t=3,p=4$kxMCoNQ6p1QqxTiHUGqNUQ$+yGg0YZMk3gqGZb5ZZWqJqHZ5C8xLBzN5sZq4gZQwWk',
    #        'ADMIN',
    #        true
    #    )
    #    ON CONFLICT (username) DO NOTHING;
    #""")

    # Insert default configuration values
    op.execute("""
        INSERT INTO config (key, value, type, description) VALUES
        ('max_concurrent_users', '4', 'INT','Maximum number of concurrent authenticated users'),
        ('session_lifetime_days', '30', 'INT','Session token lifetime in days'),
        ('global_path_a_prefix', '', 'STRING','Global prefix for path A (can be overridden per worker)'),
        ('global_path_b_prefix', '', 'STRING','Global prefix for path B (can be overridden per worker)'),
        ('enable_sybase_auth', 'false', 'BOOLEAN','Enable external Sybase authentication'),
        ('sybase_auth_url', '', 'STRING','Sybase API URL for authentication'),
        ('sybase_auth_timeout', '2', 'INT','Sybase authentication timeout in seconds'),
        ('sybase_auth_stored_proc', '', 'STRING','Sybase stored procedure name for auth'),
        ('enable_syslog', 'false', 'BOOLEAN','Enable syslog integration'),
        ('syslog_host', '', 'STRING','Syslog server hostname'),
        ('syslog_port', '514', 'INT','Syslog server port'),
        ('syslog_protocol', 'UDP', 'STRING','Syslog protocol (UDP/TCP)'),
        ('enable_remote_audit_api', 'false', 'BOOLEAN','Enable remote audit log API push'),
        ('remote_audit_api_url', '', 'STRING','Remote audit API endpoint URL'),
        ('remote_audit_api_token', '', 'STRING','Authentication token for remote audit API'),
        ('remote_audit_api_timeout', '5', 'INT','Remote audit API timeout in seconds'),
        ('log_retention_days', '14', 'INT','Number of days to retain compressed logs'),
        ('enable_log_compression', 'true', 'BOOLEAN','Enable automatic log compression'),
        ('worker_heartbeat_interval', '30', 'INT','Worker heartbeat interval in seconds'),
        ('worker_heartbeat_timeout', '90', 'INT','Worker considered offline after this many seconds'),
        ('worker_timeout', '300', 'INT','Worker command timeout in seconds'),
        ('worker_retry_attempts', '3', 'INT','Number of retry attempts for failed worker operations'),
        ('operation_timeout', '3600', 'INT','Maximum operation execution time in seconds'),
        ('enable_auto_rollback', 'true', 'BOOLEAN','Automatically rollback failed operations'),
        ('max_file_listing_items', '1000', 'INT','Maximum items to return in directory listing'),
        ('enable_lazy_loading', 'true', 'BOOLEAN','Enable lazy loading for large directory listings'),
        ('enable_ip_whitelist', 'false', 'BOOLEAN','Enable IP address whitelisting'),
        ('ip_whitelist', '[]', 'JSON','JSON array of allowed IP addresses/ranges'),
        ('enable_rate_limiting', 'true', 'BOOLEAN','Enable API rate limiting'),
        ('rate_limit_requests_per_minute', '60', 'INT','Maximum API requests per minute per user'),
        ('maintenance_mode', 'false', 'BOOLEAN','Enable maintenance mode (API read-only)'),
        ('maintenance_message', 'System is under maintenance', 'STRING','Message displayed during maintenance')
        ON CONFLICT (key) DO NOTHING;
    """)

    # Create system statistics view
    op.execute("""
        CREATE OR REPLACE VIEW system_stats AS
        SELECT
            (SELECT COUNT(*) FROM users WHERE is_active = true) as active_users,
            (SELECT COUNT(*) FROM workers WHERE status = 'ACTIVE') as active_workers,
            (SELECT COUNT(*) FROM operations WHERE status = 'IN_PROGRESS') as operations_in_progress,
            (SELECT COUNT(*) FROM operations WHERE created_at > NOW() - INTERVAL '24 hours') as operations_today,
            (SELECT COUNT(*) FROM sessions WHERE expires_at > NOW()) as active_sessions,
            (SELECT pg_size_pretty(pg_database_size(current_database()))) as database_size;
    """)

    # Create trigger to auto-update updated_at timestamp
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    op.execute("DROP TRIGGER IF EXISTS update_users_updated_at ON users;")
    op.execute("""
        CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    op.execute("DROP TRIGGER IF EXISTS update_workers_updated_at ON workers;")
    op.execute("""
        CREATE TRIGGER update_workers_updated_at BEFORE UPDATE ON workers
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    op.execute("DROP TRIGGER IF EXISTS update_config_updated_at ON config;")
    op.execute("""
        CREATE TRIGGER update_config_updated_at BEFORE UPDATE ON config
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    """
    Drop all tables and types.

    WARNING: This is destructive and will delete all data.
    """
    # Drop view
    op.execute("DROP VIEW IF EXISTS system_stats;")

    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS update_config_updated_at ON config;")
    op.execute("DROP TRIGGER IF EXISTS update_workers_updated_at ON workers;")
    op.execute("DROP TRIGGER IF EXISTS update_users_updated_at ON users;")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")

    # Drop tables
    op.drop_table('config')
    op.drop_index('ix_audit_logs_action_timestamp', table_name='audit_logs')
    op.drop_index('ix_audit_logs_user_timestamp', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_timestamp'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_operation_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_id'), table_name='audit_logs')
    op.drop_table('audit_logs')

    op.drop_table('operation_workers')

    op.drop_index('ix_operations_created_at', table_name='operations')
    op.drop_index('ix_operations_user_status', table_name='operations')
    op.drop_index(op.f('ix_operations_completed_at'), table_name='operations')
    op.drop_index(op.f('ix_operations_started_at'), table_name='operations')
    op.drop_index(op.f('ix_operations_status'), table_name='operations')
    op.drop_index(op.f('ix_operations_type'), table_name='operations')
    op.drop_index(op.f('ix_operations_user_id'), table_name='operations')
    op.drop_index(op.f('ix_operations_id'), table_name='operations')
    op.drop_table('operations')

    op.drop_index(op.f('ix_workers_last_heartbeat'), table_name='workers')
    op.drop_index(op.f('ix_workers_status'), table_name='workers')
    op.drop_index(op.f('ix_workers_name'), table_name='workers')
    op.drop_index(op.f('ix_workers_id'), table_name='workers')
    op.drop_table('workers')

    op.drop_index(op.f('ix_sessions_expires_at'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_token'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_id'), table_name='sessions')
    op.drop_table('sessions')

    op.drop_index(op.f('ix_users_is_active'), table_name='users')
    op.drop_index(op.f('ix_users_role'), table_name='users')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')

    # Drop ENUM types
    op.execute("DROP TYPE IF EXISTS configtype;")
    op.execute("DROP TYPE IF EXISTS operationstatus;")
    op.execute("DROP TYPE IF EXISTS operationtype;")
    op.execute("DROP TYPE IF EXISTS workerstatus;")
    op.execute("DROP TYPE IF EXISTS userrole;")

    # Drop extensions
    op.execute("DROP EXTENSION IF EXISTS \"uuid-ossp\";")
