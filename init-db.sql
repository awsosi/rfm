-- ==============================================================================
-- Modular File Manager - Database Initialization Script
-- ==============================================================================
-- PostgreSQL 16+ compatible schema with all tables, indexes, and default data
-- ==============================================================================
-- NOTE: This file is used by Docker for initial database setup only.
-- Alembic migrations will be applied by the API container on startup.
-- ==============================================================================

-- Ensure we're using UTF8 encoding
SET client_encoding = 'UTF8';

-- Create extensions if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==============================================================================
-- ENUM TYPES
-- ==============================================================================

-- User roles for RBAC
CREATE TYPE userrole AS ENUM ('admin', 'operator', 'viewer');

-- Worker status
CREATE TYPE workerstatus AS ENUM ('active', 'suspended', 'pending');

-- Operation types
CREATE TYPE operationtype AS ENUM ('copy', 'move', 'delete', 'mkdir');

-- Operation status
CREATE TYPE operationstatus AS ENUM ('pending', 'in_progress', 'completed', 'failed', 'rolled_back');

-- Configuration value types
CREATE TYPE configtype AS ENUM ('string', 'int', 'json', 'boolean');

-- ==============================================================================
-- TABLES
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- Users Table (Authentication & Authorization)
-- ------------------------------------------------------------------------------
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role userrole NOT NULL DEFAULT 'viewer',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_users_id ON users(id);
CREATE INDEX ix_users_username ON users(username);
CREATE INDEX ix_users_role ON users(role);
CREATE INDEX ix_users_is_active ON users(is_active);

COMMENT ON TABLE users IS 'User accounts with role-based access control';
COMMENT ON COLUMN users.password_hash IS 'Argon2id password hash';

-- ------------------------------------------------------------------------------
-- Sessions Table (JWT Token Management)
-- ------------------------------------------------------------------------------
CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(512) NOT NULL UNIQUE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    ip_address VARCHAR(45),
    user_agent TEXT
);

CREATE INDEX ix_sessions_id ON sessions(id);
CREATE INDEX ix_sessions_user_id ON sessions(user_id);
CREATE INDEX ix_sessions_token ON sessions(token);
CREATE INDEX ix_sessions_expires_at ON sessions(expires_at);

COMMENT ON TABLE sessions IS 'Active JWT authentication sessions';

-- ------------------------------------------------------------------------------
-- Workers Table (Windows Worker Services)
-- ------------------------------------------------------------------------------
CREATE TABLE workers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL UNIQUE,
    hostname VARCHAR(255),
    path_a_prefix VARCHAR(500),
    path_b_prefix VARCHAR(500),
    public_key TEXT NOT NULL,
    status workerstatus NOT NULL DEFAULT 'pending',
    version VARCHAR(50),
    last_heartbeat TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_workers_id ON workers(id);
CREATE INDEX ix_workers_name ON workers(name);
CREATE INDEX ix_workers_status ON workers(status);
CREATE INDEX ix_workers_last_heartbeat ON workers(last_heartbeat);

COMMENT ON TABLE workers IS 'Windows worker services for file operations';
COMMENT ON COLUMN workers.public_key IS 'RSA public key for worker authentication';

-- ------------------------------------------------------------------------------
-- Operations Table (File Operation Tracking)
-- ------------------------------------------------------------------------------
CREATE TABLE operations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type operationtype NOT NULL,
    source_path TEXT NOT NULL,
    dest_path TEXT,
    status operationstatus NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_msg TEXT,
    rollback_operation_id INTEGER REFERENCES operations(id) ON DELETE SET NULL,
    file_count INTEGER,
    total_size_bytes BIGINT,
    params_json JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_operations_id ON operations(id);
CREATE INDEX ix_operations_user_id ON operations(user_id);
CREATE INDEX ix_operations_type ON operations(type);
CREATE INDEX ix_operations_status ON operations(status);
CREATE INDEX ix_operations_started_at ON operations(started_at);
CREATE INDEX ix_operations_completed_at ON operations(completed_at);
CREATE INDEX ix_operations_created_at ON operations(created_at);
CREATE INDEX ix_operations_user_status ON operations(user_id, status);

COMMENT ON TABLE operations IS 'File operations with full audit trail';

-- ------------------------------------------------------------------------------
-- Operation-Worker Association Table
-- ------------------------------------------------------------------------------
CREATE TABLE operation_workers (
    operation_id INTEGER NOT NULL REFERENCES operations(id) ON DELETE CASCADE,
    worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
    worker_status operationstatus NOT NULL DEFAULT 'pending',
    worker_started_at TIMESTAMP WITH TIME ZONE,
    worker_completed_at TIMESTAMP WITH TIME ZONE,
    worker_error_msg TEXT,
    PRIMARY KEY (operation_id, worker_id)
);

CREATE INDEX ix_operation_workers_operation_id ON operation_workers(operation_id);
CREATE INDEX ix_operation_workers_worker_id ON operation_workers(worker_id);
CREATE INDEX ix_operation_workers_status ON operation_workers(worker_status);

COMMENT ON TABLE operation_workers IS 'Multi-worker operation coordination';

-- ------------------------------------------------------------------------------
-- Audit Logs Table (Immutable Audit Trail)
-- ------------------------------------------------------------------------------
CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    operation_id INTEGER REFERENCES operations(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    details_json JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    remote_api_sent BOOLEAN NOT NULL DEFAULT false,
    remote_api_sent_at TIMESTAMP WITH TIME ZONE,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_audit_logs_id ON audit_logs(id);
CREATE INDEX ix_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX ix_audit_logs_operation_id ON audit_logs(operation_id);
CREATE INDEX ix_audit_logs_action ON audit_logs(action);
CREATE INDEX ix_audit_logs_timestamp ON audit_logs(timestamp);
CREATE INDEX ix_audit_logs_user_timestamp ON audit_logs(user_id, timestamp);
CREATE INDEX ix_audit_logs_action_timestamp ON audit_logs(action, timestamp);

COMMENT ON TABLE audit_logs IS 'Immutable audit trail for compliance';

-- ------------------------------------------------------------------------------
-- Configuration Table (Runtime Configuration)
-- ------------------------------------------------------------------------------
CREATE TABLE config (
    key VARCHAR(200) PRIMARY KEY,
    value TEXT NOT NULL,
    type configtype NOT NULL DEFAULT 'string',
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_config_key ON config(key);
CREATE INDEX ix_config_type ON config(type);

COMMENT ON TABLE config IS 'Runtime configuration parameters';

-- ==============================================================================
-- TRIGGERS
-- ==============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_workers_updated_at
    BEFORE UPDATE ON workers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_config_updated_at
    BEFORE UPDATE ON config
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==============================================================================
-- DEFAULT DATA
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- Default Admin User
-- ------------------------------------------------------------------------------
-- Username: admin
-- Password: admin123
-- Hash: Argon2id (m=65536, t=3, p=4)
-- IMPORTANT: Change password immediately after first login!
-- ------------------------------------------------------------------------------
INSERT INTO users (id, username, password_hash, role, is_active)
VALUES (
    1,
    'admin',
    '$argon2id$v=19$m=65536,t=3,p=4$kxMCoNQ6p1QqxTiHUGqNUQ$+yGg0YZMk3gqGZb5ZZWqJqHZ5C8xLBzN5sZq4gZQwWk',
    'admin',
    true
);

-- Set sequence to continue from 2
SELECT setval('users_id_seq', 1, true);

-- ------------------------------------------------------------------------------
-- Default Configuration Values
-- ------------------------------------------------------------------------------
INSERT INTO config (key, value, type, description) VALUES
    -- User & Session Management
    ('max_concurrent_users', '4', 'int', 'Maximum number of concurrent authenticated users'),
    ('session_lifetime_days', '30', 'int', 'Session token lifetime in days'),

    -- Path Configuration
    ('global_path_a_prefix', '', 'string', 'Global prefix for path A (can be overridden per worker)'),
    ('global_path_b_prefix', '', 'string', 'Global prefix for path B (can be overridden per worker)'),

    -- External Authentication
    ('enable_sybase_auth', 'false', 'boolean', 'Enable external Sybase authentication'),
    ('sybase_auth_url', '', 'string', 'Sybase API URL for authentication'),
    ('sybase_auth_timeout', '2', 'int', 'Sybase authentication timeout in seconds'),
    ('sybase_auth_stored_proc', '', 'string', 'Sybase stored procedure name for auth'),

    -- Logging & Auditing
    ('enable_syslog', 'false', 'boolean', 'Enable syslog integration'),
    ('syslog_host', '', 'string', 'Syslog server hostname'),
    ('syslog_port', '514', 'int', 'Syslog server port'),
    ('syslog_protocol', 'UDP', 'string', 'Syslog protocol (UDP/TCP)'),

    -- Remote Audit API
    ('enable_remote_audit_api', 'false', 'boolean', 'Enable remote audit log API push'),
    ('remote_audit_api_url', '', 'string', 'Remote audit API endpoint URL'),
    ('remote_audit_api_token', '', 'string', 'Authentication token for remote audit API'),
    ('remote_audit_api_timeout', '5', 'int', 'Remote audit API timeout in seconds'),

    -- Log Retention
    ('log_retention_days', '14', 'int', 'Number of days to retain compressed logs'),
    ('enable_log_compression', 'true', 'boolean', 'Enable automatic log compression'),

    -- Worker Management
    ('worker_heartbeat_interval', '30', 'int', 'Worker heartbeat interval in seconds'),
    ('worker_heartbeat_timeout', '90', 'int', 'Worker considered offline after this many seconds'),
    ('worker_timeout', '300', 'int', 'Worker command timeout in seconds'),
    ('worker_retry_attempts', '3', 'int', 'Number of retry attempts for failed worker operations'),

    -- File Operations
    ('operation_timeout', '3600', 'int', 'Maximum operation execution time in seconds'),
    ('enable_auto_rollback', 'true', 'boolean', 'Automatically rollback failed operations'),
    ('max_file_listing_items', '1000', 'int', 'Maximum items to return in directory listing'),
    ('enable_lazy_loading', 'true', 'boolean', 'Enable lazy loading for large directory listings'),

    -- Security
    ('enable_ip_whitelist', 'false', 'boolean', 'Enable IP address whitelisting'),
    ('ip_whitelist', '[]', 'json', 'JSON array of allowed IP addresses/ranges'),
    ('enable_rate_limiting', 'true', 'boolean', 'Enable API rate limiting'),
    ('rate_limit_requests_per_minute', '60', 'int', 'Maximum API requests per minute per user'),

    -- Maintenance
    ('maintenance_mode', 'false', 'boolean', 'Enable maintenance mode (API read-only)'),
    ('maintenance_message', 'System is under maintenance', 'string', 'Message displayed during maintenance');

-- ==============================================================================
-- DATABASE INFORMATION
-- ==============================================================================

-- Create a view for system statistics
CREATE OR REPLACE VIEW system_stats AS
SELECT
    (SELECT COUNT(*) FROM users WHERE is_active = true) as active_users,
    (SELECT COUNT(*) FROM workers WHERE status = 'active') as active_workers,
    (SELECT COUNT(*) FROM operations WHERE status = 'in_progress') as operations_in_progress,
    (SELECT COUNT(*) FROM operations WHERE created_at > NOW() - INTERVAL '24 hours') as operations_today,
    (SELECT COUNT(*) FROM sessions WHERE expires_at > NOW()) as active_sessions,
    (SELECT pg_size_pretty(pg_database_size(current_database()))) as database_size;

COMMENT ON VIEW system_stats IS 'Real-time system statistics dashboard';

-- Grant permissions (if needed for specific users)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO filemanager;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO filemanager;

-- ==============================================================================
-- Initialization Complete
-- ==============================================================================

-- Log initialization
DO $$
BEGIN
    RAISE NOTICE '==============================================================================';
    RAISE NOTICE 'Modular File Manager - Database Initialized Successfully';
    RAISE NOTICE '==============================================================================';
    RAISE NOTICE 'Default Admin Credentials:';
    RAISE NOTICE '  Username: admin';
    RAISE NOTICE '  Password: admin123';
    RAISE NOTICE '';
    RAISE NOTICE 'SECURITY WARNING: Change the default password immediately!';
    RAISE NOTICE '==============================================================================';
END $$;
