# Modular File Manager (RFM/OPUS)

Enterprise file operations management with centralized control, distributed workers, and complete audit trail.

## 🎯 Overview

A production-ready, modular file management system designed for enterprise environments with:

- **Central API** (Python FastAPI) - Orchestration, authentication, and logging
- **WebUI** (Vanilla JS) - Dual-pane file explorer with real-time updates
- **Windows Workers** (C# .NET 4.8) - Native services executing file operations
- **PostgreSQL 16** - Configuration, users, and audit logs
- **Redis 7** - Session storage and caching
- **WebSockets** - Real-time communication between components
- **Docker Compose** - Complete containerized deployment

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
                         │  Redis  │ │PostgreSQL  │  Samba  │
                         │ (Cache) │ │   DB   │   │  Share  │
                         └─────────┘ └────────┘   └─────────┘
```

## ✨ Features

### Security
- ✅ HTTPS + TLS 1.3 minimum
- ✅ mTLS (mutual TLS) for worker authentication
- ✅ 30-day long-lived session tokens (HS256 JWT)
- ✅ Argon2id password hashing
- ✅ Role-based access control (admin, operator, viewer)
- ✅ Complete immutable audit trail
- ✅ Path traversal protection
- ✅ External authentication support (Sybase 17)

### File Operations
- ✅ Copy, move, delete, mkdir, list, search
- ✅ Multi-worker coordination
- ✅ Automatic rollback on failure
- ✅ Real-time progress via WebSockets
- ✅ Path prefix management (per-worker and global)
- ✅ Dual-pane file explorer interface

### Administration
- ✅ Web-based admin panel
- ✅ Worker registration and management
- ✅ User management with RBAC
- ✅ Configuration via database
- ✅ Audit log viewer with filtering
- ✅ Health monitoring and heartbeat tracking

### Integrations (Optional)
- ✅ Sybase 17 authentication API
- ✅ Syslog structured logging (RFC 5424)
- ✅ Custom audit API for external systems
- ✅ Exponential backoff retry logic

## 📁 Project Structure

```
rfm/
├── backend/                          # Python Backend Layer
│   ├── models.py                     # SQLAlchemy ORM models
│   ├── database.py                   # Async connection management
│   ├── alembic/                      # Database migrations
│   │   ├── env.py                    # Alembic async config
│   │   └── versions/
│   │       └── 001_initial_schema.py # Initial schema
│   ├── api/                          # FastAPI Application
│   │   ├── app.py                    # Main API application
│   │   ├── config.py                 # Settings management
│   │   ├── schemas.py                # Pydantic models
│   │   ├── middleware/               # Auth & logging middleware
│   │   │   ├── auth.py               # JWT authentication
│   │   │   └── logging.py            # Request logging
│   │   ├── routes/                   # API endpoints
│   │   │   └── auth.py               # Authentication routes
│   │   └── services/                 # Business logic
│   │       ├── worker_service.py     # Worker communication
│   │       └── operation_service.py  # File operations
│   ├── auth/                         # Authentication Module
│   │   ├── authenticator.py          # JWT & auth logic
│   │   ├── utils.py                  # Password hashing
│   │   └── exceptions.py             # Auth exceptions
│   ├── logging_module/               # Structured Logging Module
│   │   ├── logger.py                 # Logger configuration
│   │   ├── handlers.py               # Multi-destination handlers
│   │   ├── models.py                 # Log data models
│   │   └── rotation.py               # Log rotation logic
│   ├── .env.example                  # Environment template
│   ├── requirements.txt              # Python dependencies
│   ├── pyproject.toml                # Modern Python config
│   └── Makefile                      # Common commands
│
├── frontend/                         # Web UI Layer
│   ├── pages/                        # HTML pages
│   │   ├── login.html                # Login page
│   │   ├── explorer.html             # Dual-pane file explorer
│   │   └── admin.html                # Admin panel
│   ├── js/                           # JavaScript modules
│   │   ├── app.js                    # Main application
│   │   ├── api.js                    # API client
│   │   ├── auth.js                   # Authentication
│   │   ├── ui.js                     # UI state management
│   │   └── utils.js                  # Utility functions
│   └── css/                          # Stylesheets
│       ├── style.css                 # Main styles
│       └── responsive.css            # Responsive design
│
├── workers/                          # C# Windows Worker Services
│   ├── FileManagerWorker/            # Main Worker Service
│   │   ├── Program.cs                # Service entry point
│   │   ├── WorkerService.cs          # Windows service impl
│   │   ├── FileOperations.cs         # File operation handlers
│   │   ├── CommandHandler.cs         # Command processing
│   │   ├── ApiClient.cs              # API communication
│   │   ├── CertificateManager.cs     # mTLS certificates
│   │   ├── RollbackManager.cs        # Transaction rollback
│   │   └── Models/                   # Data models
│   └── Installer/                    # Windows Service Installer
│       ├── Installer.cs              # Self-installing .exe
│       └── ServiceInstaller.cs       # Service registration
│
├── docker-compose.yml                # Docker orchestration
├── Dockerfile.api                    # API container build
├── Dockerfile.webui                  # WebUI container build
├── INTEGRATION_VERIFICATION_REPORT.md # Integration verification
└── README.md                         # This file
```

## 🚀 Quick Start

### Option 1: Docker Compose (Recommended)

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Access WebUI
open http://localhost:3000
```

**Default credentials:**
- Username: `admin`
- Password: `admin123`

### Option 2: Manual Setup

#### Prerequisites

- **Python 3.11+**
- **PostgreSQL 16+**
- **Redis 7+**
- **Node.js 18+** (for frontend dev server, optional)

#### 1. Database Setup

```bash
cd backend

# Copy environment template
cp .env.example .env

# Edit .env with your database credentials
nano .env

# Install dependencies
pip install -r requirements.txt

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
✓ All config entries exist
✓ Schema verification complete!
```

#### 2. Start API Server

```bash
cd backend/api

# Development mode
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Production mode
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

#### 3. Start WebUI

```bash
cd frontend

# Serve static files (Python)
python -m http.server 3000

# Or use any static file server
npx serve -p 3000
```

#### 4. Deploy Windows Worker

```bash
# On Windows machine
cd workers\Installer

# Build installer
build.bat

# Install service (requires Administrator)
FileManagerWorker.exe /install ^
  --url https://api.example.com ^
  --user DOMAIN\ServiceUser ^
  --password SecurePassword123

# Start service
sc start FileManagerWorker

# View logs
Get-EventLog -LogName Application -Source FileManagerWorker -Newest 10
```

## 📊 Database Schema

### Core Tables

| Table | Description |
|-------|-------------|
| **users** | Authentication, RBAC (admin/operator/viewer) |
| **sessions** | Long-lived JWT token authentication |
| **workers** | Windows service registration, public keys, status |
| **operations** | File operation audit trail with rollback tracking |
| **operation_workers** | Multi-worker coordination and status |
| **audit_logs** | Immutable event logging for compliance |
| **config** | Runtime configuration (type-safe: string, int, json, boolean) |

### Key Features

- **Full async support** with asyncpg and SQLAlchemy 2.x
- **Automatic timestamps** (created_at, updated_at) with UTC timezone
- **Indexed queries** for performance (username, token, operation_id)
- **Foreign key cascades** for data integrity
- **ENUM types** for type safety (roles, statuses, operations)
- **JSON fields** for flexible metadata storage

See [backend/README_DATABASE.md](backend/README_DATABASE.md) for detailed schema documentation.

## 🔧 Configuration

### Environment Variables

All settings can be configured via `.env` file:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/filemanager

# Security
SECRET_KEY=<64-byte-random-string>
ACCESS_TOKEN_EXPIRE_DAYS=30

# Workers
WORKER_HEARTBEAT_INTERVAL=30
WORKER_TIMEOUT=3600
ENABLE_AUTO_ROLLBACK=true

# External Auth (Optional)
ENABLE_SYBASE_AUTH=false
SYBASE_AUTH_URL=https://auth.example.com/api

# Logging
LOG_LEVEL=INFO
ENABLE_FILE_LOGS=true
LOG_RETENTION_DAYS=14
```

### Runtime Configuration

Settings stored in the `config` table can be modified via admin UI or SQL:

```sql
SELECT key, value, type FROM config ORDER BY key;

-- Update configuration
UPDATE config SET value = '60' WHERE key = 'worker_heartbeat_interval';
```

Key settings:
- `max_concurrent_users`: Maximum simultaneous users (default: 4)
- `session_lifetime_days`: Session token lifetime (default: 30)
- `worker_heartbeat_interval`: Worker check-in frequency (default: 30s)
- `enable_auto_rollback`: Automatic rollback on failure (default: true)
- `operation_timeout`: Max operation execution time (default: 3600s)

## 🔐 Security Best Practices

1. **Change default password** immediately after first login
2. **Use strong DATABASE_URL** credentials (20+ character random password)
3. **Generate random SECRET_KEY** (64+ bytes): `python -c "import secrets; print(secrets.token_urlsafe(64))"`
4. **Enable TLS 1.3** for all connections
5. **Restrict PostgreSQL** to internal network only
6. **Monitor audit_logs** for suspicious activity
7. **Rotate session tokens** periodically (set shorter expiration)
8. **Keep dependencies updated** with `pip install --upgrade -r requirements.txt`
9. **Use RBAC** - limit admin privileges to necessary personnel only
10. **Enable external auth** (Sybase) for centralized authentication

## 📖 API Documentation

### Authentication Endpoints

- `POST /api/auth/login` - Authenticate user and get JWT token
- `POST /api/auth/logout` - Invalidate session
- `GET /api/auth/me` - Get current user info
- `POST /api/auth/refresh` - Refresh JWT token

### File Operations

- `GET /api/files/list` - List directory contents (paginated)
- `GET /api/files/search` - Search files by pattern
- `POST /api/files/copy` - Copy files/directories
- `POST /api/files/move` - Move files/directories
- `POST /api/files/delete` - Delete files/directories
- `POST /api/files/mkdir` - Create directory

### Worker Management

- `GET /api/workers/list` - List all active workers
- `POST /api/workers/register` - Register new worker (admin only)

### Administration

- `GET /api/admin/users` - List all users (admin only)
- `GET /api/admin/config` - Get configuration (admin only)
- `GET /api/admin/logs` - View audit logs (admin only)

### WebSocket

- `WS /ws/operations` - Real-time operation updates

## 🧪 Development

### Running Tests

```bash
cd backend
pytest -v

# With coverage
pytest --cov=. --cov-report=html
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

### Using Makefile

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
```

## 📚 Documentation

- [Database Layer Documentation](backend/README_DATABASE.md)
- [API Documentation](backend/api/README_API.md)
- [Worker Documentation](workers/README.md)
- [Worker Installer Guide](workers/README-INSTALLER.md)
- [Docker Deployment Guide](README-DOCKER.md)
- [Frontend Documentation](frontend/README.md)
- [Integration Verification Report](INTEGRATION_VERIFICATION_REPORT.md)

## 🔄 Recent Updates

### Version 1.0.0 (2026-01-21)

**6 PRs Merged - All Core Components Complete:**

1. ✅ **PR#1** - Database layer (PostgreSQL + Alembic + ORM)
2. ✅ **PR#2** - Central API (FastAPI with auth, workers, operations)
3. ✅ **PR#3** - WebUI frontend (vanilla JS dual-pane explorer)
4. ✅ **PR#4** - Windows Worker Service (C# .NET 4.8)
5. ✅ **PR#5** - Docker Compose (complete orchestration)
6. ✅ **PR#6** - Worker Service Installer (.exe self-installing)

**Recent Fixes:**
- 🔧 Fixed external auth fallback to DENY on failure (security fix)
- 🔧 Fixed frontend API endpoint mismatch (copy/move operations)
- 🔧 Added asyncio import to app.py
- 🔧 Enhanced path traversal validation in FileOperations.cs
- 📝 Updated README to reflect current state

**Integration Status:**
- ✅ All integration points verified
- ✅ Database ↔ API ↔ Auth ↔ Logging fully integrated
- ✅ WebUI ↔ API endpoints matching
- ✅ Worker ↔ API communication with mTLS
- ✅ Docker Compose orchestration complete

See [INTEGRATION_VERIFICATION_REPORT.md](INTEGRATION_VERIFICATION_REPORT.md) for detailed verification results.

## 🚦 Project Status

**Overall Status:** 🟢 PRODUCTION-READY (after critical fixes applied)

| Component | Status | Notes |
|-----------|--------|-------|
| Database Layer | 🟢 Complete | PostgreSQL 16, Alembic migrations |
| Central API | 🟢 Complete | FastAPI, async/await, JWT auth |
| Authentication | 🟢 Complete | Argon2, JWT, external auth support |
| Logging Module | 🟢 Complete | Multi-destination, structured logs |
| WebUI | 🟢 Complete | Vanilla JS, dual-pane explorer |
| Windows Workers | 🟢 Complete | C# .NET 4.8, Windows Service |
| Worker Installer | 🟢 Complete | Self-installing .exe |
| Docker Compose | 🟢 Complete | Full orchestration |
| Documentation | 🟢 Complete | README, guides, API docs |
| Tests | 🟡 Partial | Auth tests only (needs expansion) |

## 📝 License

Proprietary - All rights reserved

## 🤝 Contributing

Internal project - see team documentation for contribution guidelines.

## 📞 Support

For issues or questions, contact the development team or create an issue in the repository.

---

**Built with:** FastAPI • SQLAlchemy • PostgreSQL • Redis • C# .NET • Docker
