"""Consolidated initial schema - all tables, enums, indexes, seeds

Merges migrations 001-009 into a single initial migration.
Pre-production consolidation — no discrete migration history needed.

Revision ID: 001
Revises:
Create Date: 2026-02-06 00:00:00.000000

"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create complete database schema.

    Tables: users, sessions, workers, worker_commands, operations,
            operation_workers, audit_logs, config, user_preferences,
            samba_paths, system_metrics

    Also creates: ENUMs, views, triggers, default config seed data.
    Default admin user is created in env.py from environment variables.
    """

    # --- Extensions ---
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

    # --- ENUM types ---
    for name, values in [
        ('userrole', "('ADMIN', 'USER')"),
        ('workerstatus', "('ACTIVE', 'SUSPENDED', 'PENDING')"),
        ('operationtype', "('COPY', 'MOVE', 'DELETE', 'MKDIR', 'PUSH', 'PULL')"),
        ('operationstatus', "('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'ROLLED_BACK')"),
        ('commandstatus', "('PENDING', 'SENT', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'TIMEOUT')"),
        ('configtype', "('STRING', 'INT', 'JSON', 'BOOLEAN')"),
    ]:
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{name}') THEN
                    CREATE TYPE {name} AS ENUM {values};
                END IF;
            END $$;
        """)

    # --- Tables ---

    # users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', postgresql.ENUM('ADMIN', 'USER', name='userrole', create_type=False), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_polka_auth', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('polka_user_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)
    op.create_index(op.f('ix_users_is_active'), 'users', ['is_active'], unique=False)
    op.create_index('ix_users_is_polka_auth', 'users', ['is_polka_auth'])
    op.create_index('ix_users_polka_user_id', 'users', ['polka_user_id'])

    # sessions
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

    # workers
    op.create_table(
        'workers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('hostname', sa.String(length=255), nullable=True),
        sa.Column('path_a_prefix', sa.String(length=500), nullable=True),
        sa.Column('path_b_prefix', sa.String(length=500), nullable=True),
        sa.Column('path_c_prefix', sa.String(length=500), nullable=True),
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

    # operations
    op.create_table(
        'operations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('type', postgresql.ENUM('COPY', 'MOVE', 'DELETE', 'MKDIR', 'PUSH', 'PULL', name='operationtype', create_type=False), nullable=False),
        sa.Column('source_path', sa.Text(), nullable=False),
        sa.Column('dest_path', sa.Text(), nullable=True),
        sa.Column('original_path', sa.Text(), nullable=True),
        sa.Column('archive_path', sa.Text(), nullable=True),
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

    # operation_workers
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

    # worker_commands
    op.create_table(
        'worker_commands',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('operation_id', sa.Integer(), nullable=True),
        sa.Column('command', sa.String(length=50), nullable=False),
        sa.Column('source_path', sa.Text(), nullable=True),
        sa.Column('dest_path', sa.Text(), nullable=True),
        sa.Column('params_json', sa.JSON(), nullable=True),
        sa.Column('status', postgresql.ENUM('PENDING', 'SENT', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'TIMEOUT', name='commandstatus', create_type=False), nullable=False, server_default='PENDING'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('response_status', sa.String(length=20), nullable=True),
        sa.Column('response_message', sa.Text(), nullable=True),
        sa.Column('response_data', sa.JSON(), nullable=True),
        sa.Column('error_msg', sa.Text(), nullable=True),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='300'),
        sa.ForeignKeyConstraint(['operation_id'], ['operations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_worker_commands_id', 'worker_commands', ['id'])
    op.create_index('ix_worker_commands_worker_id', 'worker_commands', ['worker_id'])
    op.create_index('ix_worker_commands_operation_id', 'worker_commands', ['operation_id'])
    op.create_index('ix_worker_commands_status', 'worker_commands', ['status'])
    op.create_index('ix_worker_commands_created_at', 'worker_commands', ['created_at'])
    op.create_index('ix_worker_commands_worker_status', 'worker_commands', ['worker_id', 'status'])

    # audit_logs
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

    # config
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

    # user_preferences
    op.create_table(
        'user_preferences',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('remember_last_paths', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_path_a', sa.String(length=1000), nullable=True),
        sa.Column('last_path_b', sa.String(length=1000), nullable=True),
        sa.Column('ui_theme', sa.String(length=50), nullable=False, server_default='system'),
        sa.Column('ui_language', sa.String(10), nullable=False, server_default='auto'),
        sa.Column('pane_layout', sa.String(length=50), nullable=False, server_default='horizontal'),
        sa.Column('custom_settings', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id')
    )

    # samba_paths
    op.create_table(
        'samba_paths',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('path_prefix', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('share_type', sa.String(length=50), nullable=True),
        sa.Column('requires_auth', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_samba_paths_id'), 'samba_paths', ['id'], unique=False)
    op.create_index(op.f('ix_samba_paths_name'), 'samba_paths', ['name'], unique=True)
    op.create_index(op.f('ix_samba_paths_is_active'), 'samba_paths', ['is_active'], unique=False)

    # system_metrics
    op.create_table(
        'system_metrics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('active_operations', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active_workers', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active_users', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_operation_duration_seconds', sa.Integer(), nullable=True),
        sa.Column('operations_completed_last_hour', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('operations_failed_last_hour', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cpu_usage_percent', sa.Integer(), nullable=True),
        sa.Column('memory_usage_percent', sa.Integer(), nullable=True),
        sa.Column('disk_usage_percent', sa.Integer(), nullable=True),
        sa.Column('metrics_json', sa.JSON(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_system_metrics_id'), 'system_metrics', ['id'], unique=False)
    op.create_index(op.f('ix_system_metrics_timestamp'), 'system_metrics', ['timestamp'], unique=False)

    # --- Seed default config ---
    # PolkaSQL config values are seeded from environment (docker-compose passthrough)
    polka_enabled = os.environ.get('ENABLE_POLKA_AUTH', os.environ.get('POLKA_AUTH_ENABLED', 'false')).lower()
    polka_url = os.environ.get('POLKA_AUTH_URL', '')
    polka_api_key = os.environ.get('POLKA_AUTH_API_KEY', '')
    polka_timeout = os.environ.get('POLKA_AUTH_TIMEOUT', '5')

    # ROSAPI config values seeded from environment
    rosapi_enabled = os.environ.get('ENABLE_ROSAPI', os.environ.get('ROSAPI_ENABLED', 'false')).lower()
    rosapi_base_url = os.environ.get('ROSAPI_BASE_URL', '')
    rosapi_auth_email = os.environ.get('ROSAPI_AUTH_EMAIL', '')
    rosapi_auth_password = os.environ.get('ROSAPI_AUTH_PASSWORD', '')
    rosapi_timeout = os.environ.get('ROSAPI_TIMEOUT', '10')
    rosapi_push_enabled = os.environ.get('ROSAPI_PUSH_ENABLED', 'true').lower()
    rosapi_push_endpoint = os.environ.get('ROSAPI_PUSH_ENDPOINT', '/api/v1/products/tg/{folder_name}/set_image_catalog')
    rosapi_push_method = os.environ.get('ROSAPI_PUSH_METHOD', 'POST')
    rosapi_push_payload = os.environ.get('ROSAPI_PUSH_PAYLOAD', '{"generate_thumbnails": false}')
    rosapi_pull_enabled = os.environ.get('ROSAPI_PULL_ENABLED', 'false').lower()
    rosapi_pull_endpoint = os.environ.get('ROSAPI_PULL_ENDPOINT', '')
    rosapi_pull_method = os.environ.get('ROSAPI_PULL_METHOD', 'POST')
    rosapi_pull_payload = os.environ.get('ROSAPI_PULL_PAYLOAD', '{}')
    rosapi_verify_url = os.environ.get('ROSAPI_VERIFY_URL', '')

    # Syslog config values seeded from environment
    syslog_enabled = os.environ.get('ENABLE_SYSLOG', 'false').lower()
    syslog_host = os.environ.get('SYSLOG_HOST', '')
    syslog_port = os.environ.get('SYSLOG_PORT', '514')
    syslog_protocol = os.environ.get('SYSLOG_PROTOCOL', 'UDP')
    syslog_format = os.environ.get('SYSLOG_FORMAT', 'RFC5424')
    syslog_hostname = os.environ.get('SYSLOG_HOSTNAME', '')

    # Remote Audit API config values seeded from environment
    remote_audit_enabled = os.environ.get('ENABLE_REMOTE_AUDIT_API', 'false').lower()
    remote_audit_url = os.environ.get('REMOTE_AUDIT_API_URL', '')
    remote_audit_token = os.environ.get('REMOTE_AUDIT_API_TOKEN', '')
    remote_audit_timeout = os.environ.get('REMOTE_AUDIT_API_TIMEOUT', '5')

    conn = op.get_bind()
    stmt = text(
        "INSERT INTO config (key, value, type, description) "
        "VALUES (:key, :value, :type, :description) "
        "ON CONFLICT (key) DO NOTHING"
    )
    config_rows = [
        # Concurrency & sessions
        ('max_concurrent_users', '30', 'INT', 'Maximum number of concurrent authenticated users'),
        ('session_lifetime_days', '30', 'INT', 'Session token lifetime in days'),
        # Path prefixes
        ('global_path_a_prefix', '', 'STRING', 'Global prefix for path A (can be overridden per worker)'),
        ('global_path_b_prefix', '', 'STRING', 'Global prefix for path B (can be overridden per worker)'),
        # PolkaSQL authentication (seeded from env)
        ('polka_auth_enabled', polka_enabled, 'BOOLEAN', 'Enable PolkaSQL/Sybase authentication API'),
        ('polka_auth_url', polka_url, 'STRING', 'PolkaSQL authentication API URL (e.g., http://polkaserver.local/RFM_Auth)'),
        ('polka_auth_api_key', polka_api_key, 'STRING', 'API key for PolkaSQL authentication requests'),
        ('polka_auth_timeout', polka_timeout, 'INT', 'PolkaSQL authentication API timeout in seconds'),
        # Syslog (seeded from env)
        ('enable_syslog', syslog_enabled, 'BOOLEAN', 'Enable syslog integration'),
        ('syslog_host', syslog_host, 'STRING', 'Syslog server hostname'),
        ('syslog_port', syslog_port, 'INT', 'Syslog server port'),
        ('syslog_protocol', syslog_protocol, 'STRING', 'Syslog protocol (UDP/TCP)'),
        ('syslog_format', syslog_format, 'STRING', 'Syslog message format (RFC3164 or RFC5424)'),
        ('syslog_hostname', syslog_hostname, 'STRING', 'Custom hostname for syslog messages (empty = auto-detect)'),
        # Remote audit API (seeded from env)
        ('enable_remote_audit_api', remote_audit_enabled, 'BOOLEAN', 'Enable remote audit log API push'),
        ('remote_audit_api_url', remote_audit_url, 'STRING', 'Remote audit API endpoint URL'),
        ('remote_audit_api_token', remote_audit_token, 'STRING', 'Authentication token for remote audit API'),
        ('remote_audit_api_timeout', remote_audit_timeout, 'INT', 'Remote audit API timeout in seconds'),
        # ROSAPI - Remote Operation Signalling (PIM integration)
        ('rosapi_enabled', rosapi_enabled, 'BOOLEAN', 'Enable ROSAPI signalling for completed PUSH/PULL operations'),
        ('rosapi_base_url', rosapi_base_url, 'STRING', 'ROSAPI base URL'),
        ('rosapi_auth_email', rosapi_auth_email, 'STRING', 'ROSAPI authentication email'),
        ('rosapi_auth_password', rosapi_auth_password, 'STRING', 'ROSAPI authentication password'),
        ('rosapi_timeout', rosapi_timeout, 'INT', 'ROSAPI HTTP request timeout in seconds'),
        ('rosapi_push_enabled', rosapi_push_enabled, 'BOOLEAN', 'Enable ROSAPI signal for PUSH operations'),
        ('rosapi_push_endpoint', rosapi_push_endpoint, 'STRING', 'ROSAPI PUSH endpoint template (supports {folder_name}, {operation_id}, {source_path}, {dest_path})'),
        ('rosapi_push_method', rosapi_push_method, 'STRING', 'ROSAPI PUSH HTTP method (POST/PUT/GET)'),
        ('rosapi_push_payload', rosapi_push_payload, 'STRING', 'ROSAPI PUSH JSON payload template'),
        ('rosapi_pull_enabled', rosapi_pull_enabled, 'BOOLEAN', 'Enable ROSAPI signal for PULL operations'),
        ('rosapi_pull_endpoint', rosapi_pull_endpoint, 'STRING', 'ROSAPI PULL endpoint template'),
        ('rosapi_pull_method', rosapi_pull_method, 'STRING', 'ROSAPI PULL HTTP method'),
        ('rosapi_pull_payload', rosapi_pull_payload, 'STRING', 'ROSAPI PULL JSON payload template'),
        ('rosapi_verify_url', rosapi_verify_url, 'STRING', 'ROSAPI verification URL template (optional)'),
        # Logging
        ('log_retention_days', '14', 'INT', 'Number of days to retain compressed logs'),
        ('enable_log_compression', 'true', 'BOOLEAN', 'Enable automatic log compression'),
        # Worker settings
        ('worker_heartbeat_interval', '30', 'INT', 'Worker heartbeat interval in seconds'),
        ('worker_heartbeat_timeout', '90', 'INT', 'Worker considered offline after this many seconds'),
        ('worker_timeout', '300', 'INT', 'Worker command timeout in seconds'),
        ('worker_retry_attempts', '3', 'INT', 'Number of retry attempts for failed worker operations'),
        # Operations
        ('operation_timeout', '3600', 'INT', 'Maximum operation execution time in seconds'),
        ('enable_auto_rollback', 'true', 'BOOLEAN', 'Automatically rollback failed operations'),
        ('max_file_listing_items', '20', 'INT', 'Maximum items to return in directory listing'),
        ('enable_lazy_loading', 'true', 'BOOLEAN', 'Enable lazy loading for large directory listings'),
        # Security
        ('enable_ip_whitelist', 'false', 'BOOLEAN', 'Enable IP address whitelisting'),
        ('ip_whitelist', '[]', 'JSON', 'JSON array of allowed IP addresses/ranges'),
        ('enable_rate_limiting', 'true', 'BOOLEAN', 'Enable API rate limiting'),
        ('rate_limit_requests_per_minute', '60', 'INT', 'Maximum API requests per minute per user'),
        # Maintenance
        ('maintenance_mode', 'false', 'BOOLEAN', 'Enable maintenance mode (API read-only)'),
        ('maintenance_message', 'System is under maintenance', 'STRING', 'Message displayed during maintenance'),
        # PUSH operation settings
        ('enable_push_flatten', 'false', 'BOOLEAN', 'Only copy root-level files to PATH_B during PUSH (skip subdirectories)'),
        ('enable_push_archive', 'false', 'BOOLEAN', 'Archive source to PATH_C after PUSH (when off, source is deleted)'),
        ('push_ignore_file_masks', 'Thumbs.db', 'STRING', 'Comma-separated file/extension masks to exclude and destroy during PUSH'),
    ]
    for key, value, type_, description in config_rows:
        conn.execute(stmt, {"key": key, "value": value, "type": type_, "description": description})

    # --- View ---
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

    # --- Trigger function + triggers for updated_at ---
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    for table in ('users', 'workers', 'config', 'user_preferences'):
        op.execute(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {table};")
        op.execute(f"""
            CREATE TRIGGER update_{table}_updated_at BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    """Drop everything — destructive, deletes all data."""

    # View
    op.execute("DROP VIEW IF EXISTS system_stats;")

    # Triggers
    for table in ('user_preferences', 'config', 'workers', 'users'):
        op.execute(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {table};")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")

    # Tables (order respects foreign keys)
    op.drop_index(op.f('ix_system_metrics_timestamp'), table_name='system_metrics')
    op.drop_index(op.f('ix_system_metrics_id'), table_name='system_metrics')
    op.drop_table('system_metrics')

    op.drop_index(op.f('ix_samba_paths_is_active'), table_name='samba_paths')
    op.drop_index(op.f('ix_samba_paths_name'), table_name='samba_paths')
    op.drop_index(op.f('ix_samba_paths_id'), table_name='samba_paths')
    op.drop_table('samba_paths')

    op.drop_table('user_preferences')
    op.drop_table('config')

    op.drop_index('ix_audit_logs_action_timestamp', table_name='audit_logs')
    op.drop_index('ix_audit_logs_user_timestamp', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_timestamp'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_operation_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_id'), table_name='audit_logs')
    op.drop_table('audit_logs')

    op.drop_index('ix_worker_commands_worker_status', table_name='worker_commands')
    op.drop_index('ix_worker_commands_created_at', table_name='worker_commands')
    op.drop_index('ix_worker_commands_status', table_name='worker_commands')
    op.drop_index('ix_worker_commands_operation_id', table_name='worker_commands')
    op.drop_index('ix_worker_commands_worker_id', table_name='worker_commands')
    op.drop_index('ix_worker_commands_id', table_name='worker_commands')
    op.drop_table('worker_commands')

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

    op.drop_index('ix_users_polka_user_id', table_name='users')
    op.drop_index('ix_users_is_polka_auth', table_name='users')
    op.drop_index(op.f('ix_users_is_active'), table_name='users')
    op.drop_index(op.f('ix_users_role'), table_name='users')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')

    # ENUM types
    for name in ('configtype', 'commandstatus', 'operationstatus', 'operationtype', 'workerstatus', 'userrole'):
        op.execute(f"DROP TYPE IF EXISTS {name};")

    # Extensions
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp";')
