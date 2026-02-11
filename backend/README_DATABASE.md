# Database Layer - Modular File Manager

Complete PostgreSQL schema with async SQLAlchemy ORM and Alembic migrations.

## 📋 Overview

This database layer provides:

- **6 Core Tables**: users, sessions, workers, operations, audit_logs, config
- **Async Support**: Full async/await with asyncpg driver
- **RBAC**: Role-based access control (admin, user)
- **Audit Trail**: Immutable logging of all operations
- **Migration Management**: Alembic for schema versioning
- **Security**: Argon2 password hashing, indexed queries
- **Default Admin**: username `admin`, password `admin123` (change immediately!)

## 🗄️ Schema Overview

### Users Table
- Authentication and RBAC
- Argon2 password hashing
- Roles: admin, user

### Sessions Table
- Token-based authentication
- 30-day long-lived sessions
- IP and user agent tracking

### Workers Table
- Windows service registration
- Public key authentication
- Path prefixes for dual-pane operations
- Heartbeat monitoring

### Operations Table
- Complete file operation audit trail
- Multi-worker coordination
- Rollback support
- Status tracking (pending, in_progress, completed, failed, rolled_back)

### Operation_Workers Table
- Many-to-many association
- Per-worker status tracking

### Audit_Logs Table
- Immutable event logging
- Remote API sync tracking
- Indexed for fast queries

### Config Table
- Runtime parameters
- Type-safe values (string, int, json, boolean)
- Default settings pre-populated

## 🚀 Setup Instructions

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your database credentials
```

**Minimum required variables:**
```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/filemanager
SECRET_KEY=<generate-with-secrets.token_urlsafe(64)>
```

### 3. Create Database

```bash
# Using psql
createdb filemanager

# Or via PostgreSQL client
psql -U postgres
CREATE DATABASE filemanager;
```

### 4. Run Migrations

```bash
cd backend
alembic upgrade head
```

This will:
- Create all tables with proper indexes
- Create ENUM types
- Insert default admin user
- Insert default configuration values
- Set up auto-update triggers

### 5. Verify Schema

```bash
python verify_schema.py
```

Expected output:
```
✓ Database connection successful
✓ All 6 tables created
✓ Default admin user exists (id=1)
✓ 18 default config entries loaded
✓ All indexes created
✓ Schema verification complete!
```

## 🔐 Default Admin User

**Username:** `admin`
**Password:** `admin123`

**⚠️ SECURITY WARNING:** Change this password immediately after first login!

The password hash in the migration is:
```
$argon2id$v=19$m=65536,t=3,p=4$kxMCoNQ6p1QqxTiHUGqNUQ$+yGg0YZMk3gqGZb5ZZWqJqHZ5C8xLBzN5sZq4gZQwWk
```

## 📊 Default Configuration Values

The migration inserts these default configs:

| Key | Value | Type | Description |
|-----|-------|------|-------------|
| max_concurrent_users | 30 | int | Maximum concurrent users |
| session_lifetime_days | 30 | int | Session token lifetime |
| global_path_a_prefix | "" | string | Global path A prefix |
| global_path_b_prefix | "" | string | Global path B prefix |
| enable_sybase_auth | false | boolean | External Sybase auth |
| enable_syslog | false | boolean | Syslog integration |
| enable_remote_audit_api | false | boolean | Remote audit API |
| log_retention_days | 14 | int | Log retention period |
| worker_heartbeat_interval | 30 | int | Heartbeat interval (seconds) |
| worker_heartbeat_timeout | 90 | int | Heartbeat timeout (seconds) |
| operation_timeout | 3600 | int | Max operation time (seconds) |
| enable_auto_rollback | true | boolean | Auto-rollback on failure |
| max_file_listing_items | 20 | int | Max items in dir listing |

## 🔄 Migration Commands

### Create New Migration
```bash
alembic revision --autogenerate -m "description"
```

### Upgrade to Latest
```bash
alembic upgrade head
```

### Downgrade One Version
```bash
alembic downgrade -1
```

### Show Current Version
```bash
alembic current
```

### Show Migration History
```bash
alembic history
```

## 🧪 Testing Database Operations

### Using Python

```python
import asyncio
from database import DatabaseManager, get_db_session
from models import User, Config

async def test_db():
    # Initialize database
    DatabaseManager.initialize()

    # Query admin user
    async with get_db_session() as session:
        admin = await session.get(User, 1)
        print(f"Admin user: {admin.username}, role: {admin.role}")

        # Get config value
        config = await session.get(Config, "max_concurrent_users")
        print(f"Max users: {config.get_typed_value()}")

    await DatabaseManager.close()

asyncio.run(test_db())
```

### Using psql

```sql
-- Verify tables
\dt

-- Check admin user
SELECT id, username, role, is_active FROM users WHERE id = 1;

-- Check config values
SELECT key, value, type FROM config ORDER BY key;

-- Verify indexes
\di
```

## 📁 File Structure

```
backend/
├── models.py                    # SQLAlchemy ORM models
├── database.py                  # Connection & session management
├── alembic.ini                  # Alembic configuration
├── alembic/
│   ├── env.py                   # Alembic environment (async)
│   ├── script.py.mako           # Migration template
│   └── versions/
│       └── 001_initial_schema.py  # Initial migration
├── .env.example                 # Environment template
├── requirements.txt             # Python dependencies
├── README_DATABASE.md           # This file
└── verify_schema.py             # Schema verification script
```

## 🔍 Common Queries

### List All Users
```sql
SELECT id, username, role, is_active, created_at
FROM users
ORDER BY id;
```

### List Active Workers
```sql
SELECT id, name, hostname, status, last_heartbeat
FROM workers
WHERE status = 'active'
ORDER BY name;
```

### Recent Operations
```sql
SELECT o.id, u.username, o.type, o.status, o.source_path, o.created_at
FROM operations o
JOIN users u ON o.user_id = u.id
ORDER BY o.created_at DESC
LIMIT 10;
```

### Audit Trail for User
```sql
SELECT action, details_json, timestamp
FROM audit_logs
WHERE user_id = 1
ORDER BY timestamp DESC
LIMIT 20;
```

### Failed Operations
```sql
SELECT id, type, source_path, error_msg, started_at, completed_at
FROM operations
WHERE status = 'failed'
ORDER BY completed_at DESC;
```

## 🛠️ Troubleshooting

### Connection Issues

**Error:** `ValueError: DATABASE_URL environment variable not set`
- **Fix:** Copy `.env.example` to `.env` and configure `DATABASE_URL`

**Error:** `asyncpg.exceptions.InvalidCatalogNameError: database "filemanager" does not exist`
- **Fix:** Run `createdb filemanager` or create via PostgreSQL client

### Migration Issues

**Error:** `alembic.util.exc.CommandError: Can't locate revision identified by 'head'`
- **Fix:** Run `alembic upgrade head` to create initial schema

**Error:** `sqlalchemy.exc.ProgrammingError: relation "users" already exists`
- **Fix:** Database already initialized. Use `alembic current` to check version

### Password Hashing

To generate a new Argon2 hash for testing:

```python
from argon2 import PasswordHasher

ph = PasswordHasher()
hash = ph.hash("your_password")
print(hash)
```

## 🔒 Security Considerations

1. **Change Default Password**: Immediately change the default admin password
2. **Environment Variables**: Never commit `.env` to version control
3. **Database Credentials**: Use strong passwords for PostgreSQL
4. **TLS/SSL**: Enable SSL for database connections in production
5. **Network Security**: Restrict PostgreSQL to internal network only
6. **Audit Logs**: Monitor `audit_logs` table for suspicious activity
7. **Session Tokens**: Rotate `SECRET_KEY` if compromised

## 📈 Performance Tuning

### Connection Pooling
Adjust in `database.py` or environment variables:
```python
DatabaseManager.initialize(
    pool_size=20,        # Connections in pool
    max_overflow=10,     # Additional connections
    pool_recycle=3600,   # Recycle after 1 hour
)
```

### Indexes
All frequently queried columns are already indexed:
- `users.username`
- `sessions.token`, `sessions.expires_at`
- `operations.user_id`, `operations.status`
- `audit_logs.user_id`, `audit_logs.timestamp`

### Query Optimization
Use async queries with proper joins:
```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload

stmt = select(Operation).options(
    selectinload(Operation.user),
    selectinload(Operation.workers)
).where(Operation.status == 'completed')

result = await session.execute(stmt)
operations = result.scalars().all()
```

## 📝 License

Part of the Modular File Manager Application.
