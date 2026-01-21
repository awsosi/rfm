# Modular File Manager Application

Enterprise file operations management with centralized control, distributed workers, and complete audit trail.

## 🎯 Overview

A production-ready, modular file management system designed for enterprise environments with:

- **Central API** (Python FastAPI) - Orchestration, authentication, and logging
- **WebUI** (Flask/FastAPI + HTML/JS) - Dual-pane file explorer with real-time updates
- **Windows Workers** (C# .NET 4.8+) - Native services executing file operations
- **PostgreSQL** - Configuration, users, and audit logs
- **WebSockets** - Real-time communication between components

## 🏗️ Architecture

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   WebUI     │◄───────►│  Central API │◄───────►│   Worker 1  │
│ (Browser)   │  HTTPS  │  (FastAPI)   │  mTLS   │ (Win Svc)   │
└─────────────┘         └──────────────┘         └─────────────┘
                              │                         │
                              ├──────────┐              │
                              │          │              │
                         ┌────▼────┐ ┌──▼───┐     ┌────▼────┐
                         │  Redis  │ │ Post │     │  Samba  │
                         │ (Cache) │ │ greSQL    │  Share  │
                         └─────────┘ └──────┘     └─────────┘
```

## ✨ Features

### Security
- ✅ HTTPS + TLS 1.3 minimum
- ✅ Public key authentication for workers
- ✅ 30-day long-lived session tokens (HS256)
- ✅ Argon2 password hashing
- ✅ Role-based access control (admin, operator, viewer)
- ✅ Complete audit trail

### File Operations
- ✅ Copy, move, delete, mkdir
- ✅ Multi-worker coordination
- ✅ Automatic rollback on failure
- ✅ Real-time progress via WebSockets
- ✅ Path prefix management (per-worker and global)

### Administration
- ✅ Web-based admin panel
- ✅ Worker registration and management
- ✅ User management
- ✅ Configuration via database
- ✅ Audit log viewer

### Integrations (Optional)
- ✅ Sybase 17 authentication API
- ✅ Syslog structured logging
- ✅ Custom audit API for external systems

## 📁 Project Structure

```
rfm/
├── backend/                      # Database layer & API
│   ├── models.py                 # SQLAlchemy ORM models
│   ├── database.py               # Connection management
│   ├── alembic/                  # Database migrations
│   │   ├── env.py                # Alembic async config
│   │   └── versions/
│   │       └── 001_initial_schema.py
│   ├── .env.example              # Environment template
│   ├── requirements.txt          # Python dependencies
│   ├── pyproject.toml            # Modern Python config
│   ├── Makefile                  # Common commands
│   └── verify_schema.py          # Schema verification
│
├── api/                          # FastAPI application (TBD)
├── webui/                        # Web interface (TBD)
├── worker/                       # C# Windows Service (TBD)
├── docker-compose.yml            # Docker orchestration (TBD)
└── README.md                     # This file
```

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **PostgreSQL 14+**
- **Redis 7+** (for sessions)
- **Docker** (optional, for containerized deployment)

### 1. Database Setup

```bash
# Navigate to backend
cd backend

# Copy environment template
cp .env.example .env

# Edit .env with your database credentials
nano .env

# Install dependencies
pip install -r requirements.txt

# Or use make
make setup

# Create database
createdb filemanager

# Run migrations
alembic upgrade head

# Verify schema
python verify_schema.py
```

Expected output:
```
✓ Database connection successful
✓ All 6 required tables exist
✓ Default admin user exists (username: admin, role: admin)
✓ All 18 default config entries exist
✓ Schema verification complete!
```

### 2. Default Credentials

**⚠️ CHANGE IMMEDIATELY AFTER FIRST LOGIN!**

- **Username:** `admin`
- **Password:** `admin123`

### 3. Using Makefile Commands

```bash
# Show all available commands
make help

# Complete setup (install, migrate, verify)
make all

# Run migrations
make migrate

# Create new migration
make migrate-create MSG="add new field"

# Verify schema
make verify

# Open psql shell
make psql

# Reset database (DESTRUCTIVE!)
make reset

# Format code
make format

# Run linters
make lint

# Run tests
make test
```

## 📊 Database Schema

### Core Tables

| Table | Description |
|-------|-------------|
| **users** | Authentication, RBAC (admin/operator/viewer) |
| **sessions** | Long-lived token authentication |
| **workers** | Windows service registration, public keys |
| **operations** | File operation audit trail |
| **operation_workers** | Multi-worker coordination |
| **audit_logs** | Immutable event logging |
| **config** | Runtime configuration (type-safe) |

### Key Features

- **Full async support** with asyncpg
- **Automatic timestamps** with triggers
- **Indexed queries** for performance
- **Foreign key cascades** for data integrity
- **ENUM types** for type safety
- **JSON fields** for flexible metadata

See [backend/README_DATABASE.md](backend/README_DATABASE.md) for detailed schema documentation.

## 🔧 Configuration

All configuration is stored in the `config` table and can be managed via the admin UI or SQL:

```sql
SELECT key, value, type FROM config ORDER BY key;
```

Key settings:
- `max_concurrent_users`: Maximum simultaneous users (default: 4)
- `session_lifetime_days`: Session token lifetime (default: 30)
- `worker_heartbeat_interval`: Worker check-in frequency (default: 30s)
- `enable_auto_rollback`: Automatic rollback on failure (default: true)
- `operation_timeout`: Max operation execution time (default: 3600s)

## 🔐 Security Best Practices

1. **Change default password** immediately
2. **Use strong DATABASE_URL** credentials
3. **Generate random SECRET_KEY** (64+ bytes)
4. **Enable TLS** for all connections
5. **Restrict PostgreSQL** to internal network
6. **Monitor audit_logs** for suspicious activity
7. **Rotate session tokens** periodically
8. **Keep dependencies updated**

## 📖 Documentation

- [Database Layer Documentation](backend/README_DATABASE.md)
- [Central API Documentation](backend/api/README_API.md)
- WebUI Guide (coming soon)
- Worker Deployment Guide (coming soon)

## 🧪 Development

### Running Tests

```bash
cd backend
pytest -v
```

### Code Quality

```bash
# Format code
make format

# Run linters
make lint

# Type checking
mypy .
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1

# Show history
alembic history
```

## 📝 License

Proprietary - All rights reserved

## 🤝 Contributing

Internal project - see team documentation for contribution guidelines.

## 📞 Support

For issues or questions, contact the development team.

---

**Status:** 🟢 Database Layer Complete | 🟢 Central API Complete | 🔴 WebUI Pending | 🔴 Worker Pending
