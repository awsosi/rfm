# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**Modular File Manager (RFM/OPUS)** - Enterprise file operations management with centralized control, distributed workers, and complete audit trail.

### Architecture

Multi-tier distributed system with three main components:

1. **Backend (Python/FastAPI)** - Central API server (`backend/`)
   - Async PostgreSQL (asyncpg + SQLAlchemy 2.x)
   - Redis session storage
   - Elasticsearch indexing (optional)
   - JWT authentication with Argon2 password hashing
   - WebSocket real-time updates

2. **Frontend (Vanilla JS)** - WebUI (`frontend/`)
   - Dual-pane file explorer
   - Flask development server with API proxy
   - No framework - pure HTML/CSS/JS

3. **Windows Workers (C# .NET 4.8)** - Distributed file operation executors (`workers/`)
   - Windows Service using Topshelf
   - mTLS authentication with central API
   - Native Windows file operations with impersonation
   - Self-installing executable

### Key Integration Points

- **Backend ↔ Database**: All runtime config reads from `config` table (env vars sync on startup via `_sync_env_config_to_db()`)
- **Backend ↔ Frontend**: REST API + WebSocket (`/ws/operations`)
- **Backend ↔ Workers**: mTLS mutual authentication, command queue via Redis
- **Frontend ↔ Backend**: API calls to `API_URL` (internal) or `API_URL_PUBLIC` (external)
- **Windows Client ↔ Backend**: OAuth device flow with Windows Credential Manager storage

---

## Development Commands

### Backend (Python FastAPI)

```bash
cd backend

# Setup
make setup              # Copy .env.example, install dependencies
make install            # Install Python dependencies
pip install -r requirements.txt

# Database
make migrate            # Run migrations (alembic upgrade head)
make migrate-create MSG="description"  # Create new migration
make verify             # Verify database schema
make psql               # Open PostgreSQL shell
make reset              # Drop, create, migrate (DESTRUCTIVE!)

# Development
uvicorn api.app:app --reload --host 0.0.0.0 --port 8000

# Testing
make test               # Run pytest
make test-cov           # Run tests with coverage report
pytest -v

# Code Quality
make format             # Run black and isort
make lint               # Run ruff and mypy
black .
isort .
ruff check .
mypy .

# Cleanup
make clean              # Remove __pycache__, .pyc, etc.
```

### Frontend (Vanilla JS)

```bash
cd frontend

# Development server (Flask with API proxy)
python server.py        # Starts on port 3000

# Or simple static server (no API proxy)
python -m http.server 3000
```

### Windows Workers (C# .NET 4.8)

```bash
# Build (using Visual Studio Developer Command Prompt)
cd workers
msbuild FileManagerWorker.sln /p:Configuration=Release

# Or open in Visual Studio
start FileManagerWorker.sln
```

### Windows Client (C# .NET 4.8 + C++ COM)

See `clients/windows/BUILD_INSTRUCTIONS.md` for detailed build steps.

```bash
cd clients/windows

# Restore NuGet packages
nuget restore RFM-Windows.sln
# Or: msbuild RFM-Windows.sln /t:Restore

# Build Launcher (C#)
cd Launcher
msbuild RFMLauncher.csproj /p:Configuration=Release

# Build ShellExtension (C++ COM DLL)
cd ../ShellExtension
msbuild RFMShellExt.vcxproj /p:Configuration=Release /p:Platform=x64

# Build Installer (WiX - requires WiX Toolset installed)
cd ../Installer
msbuild RFMInstaller.wixproj /p:Configuration=Release
```

### Docker (Complete Stack)

```bash
# Setup
cp .env.example .env
# Edit .env with configuration

# Start all services (API, WebUI, PostgreSQL, Redis, Elasticsearch)
docker-compose up -d

# View logs
docker-compose logs -f
docker-compose logs -f api

# Stop
docker-compose down

# Stop and remove volumes (DATA LOSS!)
docker-compose down -v

# Restart specific service
docker-compose restart api

# Shell into container
docker-compose exec api /bin/bash
docker-compose exec postgres psql -U filemanager
```

---

## Architecture Deep Dive

### Database Layer (`backend/models.py`, `backend/database.py`)

**Single Migration Strategy**: During pre-production, all schema changes are consolidated into `backend/alembic/versions/001_initial_schema.py`. Do not create new migrations - merge changes into the initial schema.

**Key Tables**:
- `users` - Authentication with Argon2 password hashing
- `sessions` - 30-day JWT tokens (HS256)
- `workers` - Windows service registration, public keys, heartbeat tracking
- `operations` - File operation audit trail with rollback tracking
- `operation_workers` - Multi-worker coordination
- `audit_logs` - Immutable event logging
- `config` - Runtime configuration (type-safe: string, int, json, boolean)

**Connection Pooling**:
- Pool size: 20 (default)
- Max overflow: 10
- Pool recycle: 3600s (1 hour)
- All queries use async/await with `AsyncSession`

### Configuration System

**Two-Phase Loading**:
1. **Startup**: Environment variables are synced to `config` table via `_sync_env_config_to_db()` in `backend/api/app.py`
2. **Runtime**: All config reads from database via `Config` model

**Naming Convention**:
- Boolean toggles: `ENABLE_*` prefix (e.g., `ENABLE_POLKA_AUTH`)
- If legacy env var differs, use `validation_alias=AliasChoices(...)` in Pydantic model
- Example: `POLKA_AUTH_ENABLED` accepts both `ENABLE_POLKA_AUTH` and `POLKA_AUTH_ENABLED`

### WebSocket Integration (`backend/api/websocket_manager.py`)

**Critical Pattern**: FastAPI does NOT auto-parse query parameters for WebSocket endpoints.

```python
# CORRECT - Manual parsing from scope
@app.websocket("/ws/operations")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()  # MUST accept first

    # Manually extract query params
    query_string = websocket.scope.get("query_string", b"").decode()
    query_params = parse_qs(query_string)
    token = query_params.get("token", [None])[0]
```

**Wrong Pattern**: Using `Query()` annotation causes 400 errors before endpoint runs.

### Worker Communication

**Path Mapping**: Workers have `path_a_prefix` (Windows UNC path) and `path_b_prefix` (virtual path prefix). Backend converts between Windows paths and virtual paths via `/api/path/resolve` endpoint.

**Command Queue**: Commands are queued in Redis, workers poll via WebSocket or HTTP long-polling.

**Rollback**: `RollbackManager.cs` tracks file operations for automatic rollback on failure (if `ENABLE_AUTO_ROLLBACK=true`).

### Frontend Architecture

**No Framework**: Uses vanilla JavaScript with modules:
- `js/app.js` - Main application entry point
- `js/api.js` - API client
- `js/auth.js` - Authentication (JWT storage in localStorage)
- `js/ui.js` - UI state management
- `js/utils.js` - Utilities

**Configuration Injection**: `frontend/server.py` injects `API_URL_PUBLIC` into HTML before serving. This must be done for ALL entry points (index.html, explorer.html, admin.html), not just index.html.

**Internationalization**: Locales in `frontend/locales/` (en-US.json, pl-PL.json), loaded by `js/i18n.js`.

---

## Critical Development Rules

These rules prevent recurring bugs documented in `TODO.md` and `LESSONS_LEARNED.md`:

### 1. Schema ↔ Endpoint ↔ Model Sync

When adding a database field:
1. Add column to `backend/models.py`
2. Add field to `backend/api/schemas.py` (both request AND response schemas)
3. Update endpoint to include field in ORM object creation
4. Merge into `backend/alembic/versions/001_initial_schema.py`

**Why**: Pydantic silently strips unknown fields. Missing any step causes data loss.

### 2. WebSocket Endpoints

- Manually parse query parameters from `websocket.scope`
- Call `await websocket.accept()` BEFORE any other operations
- Update ALL frontend clients (grep for WebSocket connections)

**Why**: Using `Query()` causes 400 errors. Parsing after operations causes connection failures.

### 3. Python Async Extras

Always install async extras: `pip install package[async]`

Examples:
- `sqlalchemy[asyncio]` not `sqlalchemy`
- `elasticsearch[async]` not `elasticsearch`

**Why**: Missing extras cause silent runtime failures (imports succeed but functionality breaks).

### 4. Environment Variables

- Use `ENABLE_*` prefix for boolean toggles
- If legacy name exists, add `validation_alias=AliasChoices(...)` to Pydantic model
- Sync env vars to DB on startup via `_sync_env_config_to_db()`
- Runtime code reads from DB, NOT env vars

### 5. Windows Client Credential Storage

When storing OAuth tokens in Windows Credential Manager (`clients/windows/Launcher/AuthenticationManager.cs`):
- Access token → `Credential.Password` field
- Refresh token → `Credential.Description` field
- Username → `Credential.Username` field

**Why**: Mismatched save/load fields cause silent failures. Token refresh appears to work but refresh token is never loaded, causing re-authentication every hour.

### 6. Path Resolution

Windows paths must be resolved to virtual paths via `/api/path/resolve` endpoint. Uses worker's `path_a_prefix` to strip Windows UNC prefix and convert to virtual path.

**Why**: Simple folder name extraction only works for root-level folders, fails for nested paths.

### 7. KISS and DRY

- **KISS**: Only add what's requested or clearly necessary. No premature optimization or abstraction.
- **DRY**: Extract common patterns to shared functions. Use config files for repeated values.

---

## Testing

### Backend Tests

```bash
cd backend
pytest -v                          # Run all tests
pytest tests/test_auth.py -v       # Run specific test file
pytest --cov=. --cov-report=html   # Coverage report
```

**Note**: Currently only `tests/test_auth.py` exists. Expand test coverage as needed.

### Manual Integration Testing

1. Start Docker stack: `docker-compose up -d`
2. Access WebUI: http://localhost:3000
3. Default credentials: `admin` / `admin123`
4. Test file operations via dual-pane explorer
5. Check audit logs in admin panel

---

## Common Pitfalls

### Database Schema Changes Not Appearing

**Symptom**: Added field to `models.py` but data isn't saved.

**Fix**: Check all 4 sync points:
1. `models.py` - Column definition
2. `schemas.py` - Request schema
3. `schemas.py` - Response schema
4. Endpoint - Include field in object constructor

### WebSocket Returns 400

**Symptom**: WebSocket connection fails immediately with "Unexpected response code: 400".

**Fix**: Remove `Query()` annotations, use manual parsing from `websocket.scope`.

### Token Refresh Not Working

**Symptom**: Windows client requires device flow authentication every hour.

**Fix**: Check `AuthenticationManager.cs` - ensure refresh token is loaded from `Description` field (line ~106), not `SecurePassword` field.

### Nested Path Deep Links Fail

**Symptom**: Windows shell extension context menu works for root folders but fails for nested folders.

**Fix**: Call `/api/path/resolve` endpoint to convert Windows path to virtual path, then navigate to parent directory before selecting folder.

### Environment Variable Ignored

**Symptom**: Changed `.env` value but nothing happens.

**Fix**:
1. Restart services (env vars read on startup)
2. Check variable is in `_sync_env_config_to_db()` in `backend/api/app.py`
3. Verify naming convention matches (use `ENABLE_*` prefix)

---

## Project Documentation Files

**Active Development**:
- `TODO.md` - Active bugs and future work
- `DONE.md` - Completed work log (chronological)
- `LESSONS_LEARNED.md` - Critical patterns and anti-patterns
- `.claude/instructions.md` - Claude Code session instructions

**Component Documentation**:
- `README.md` - Main project documentation
- `backend/README_DATABASE.md` - Database layer details
- `workers/README.md` - Windows Worker documentation
- `workers/README-INSTALLER.md` - Worker installer guide
- `clients/windows/BUILD_INSTRUCTIONS.md` - Windows client build guide
- `clients/windows/DEPLOYMENT.md` - Windows client deployment
- `frontend/README.md` - Frontend documentation

**Update These Files**:
- After completing work → Add to `DONE.md`
- After discovering invisible bugs → Add pattern to `LESSONS_LEARNED.md`
- When adding/changing tasks → Update `TODO.md`

---

## Default Credentials

**Database** (Docker):
- User: `filemanager` (configurable via `POSTGRES_USER`)
- Password: `changeme` (configurable via `POSTGRES_PASSWORD`)
- Database: `filemanager` (configurable via `POSTGRES_DB`)

**Application**:
- Username: `admin`
- Password: `admin123`

**IMPORTANT**: Change admin password immediately after first login.

---

## Security Notes

- SECRET_KEY must be 64+ bytes random string: `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- mTLS certificates for worker authentication stored in `ssl/` directory
- Session tokens are 30-day long-lived JWTs (configurable via `ACCESS_TOKEN_EXPIRE_DAYS`)
- External auth (Sybase/PolkaSQL) supported via `ENABLE_POLKA_AUTH`
- All passwords hashed with Argon2id (OWASP recommended)
- Path traversal protection in `workers/FileManagerWorker/FileOperations.cs`

---

## Additional Resources

- Docker Compose config: `docker-compose.yml` (includes Elasticsearch, Redis, PostgreSQL)
- Alembic migrations: `backend/alembic/versions/001_initial_schema.py`
- API routes: `backend/api/routes/*.py` (auth, admin, worker, path, preferences)
- Worker service: `workers/FileManagerWorker/WorkerService.cs`
- Shell extension: `clients/windows/ShellExtension/` (C++ ATL COM)
