# Central API - Modular File Manager

FastAPI REST API for orchestrating file operations and managing workers.

## 🎯 Overview

The Central API provides:

- **Authentication** - JWT token-based auth with 30-day sessions
- **File Operations** - List, search, copy, move, delete, mkdir
- **Worker Management** - Registration, health monitoring, communication
- **Admin Panel** - User, config, and audit log management
- **WebSocket** - Real-time operation status updates
- **External Integration** - Optional Sybase authentication

## 📋 Features

### Security
- ✅ JWT tokens (HS256) with database-backed sessions
- ✅ Role-based access control (admin, user)
- ✅ Argon2 password hashing
- ✅ Public key authentication for workers
- ✅ Complete audit trail

### File Operations
- ✅ Directory listing with pagination (lazy loading)
- ✅ File search (recursive)
- ✅ Copy/move/delete/mkdir operations
- ✅ Multi-worker coordination (2-worker transfers)
- ✅ Automatic rollback on failure
- ✅ Conflict detection and queueing

### Worker Communication
- ✅ HTTPS with TLS 1.3
- ✅ Retry logic with exponential backoff (3 attempts: 2s, 4s, 8s)
- ✅ Health checks and heartbeat monitoring
- ✅ Automatic suspension on failure

## 🚀 Quick Start

### 1. Setup Environment

```bash
cd backend

# Create .env if not exists
cp .env.example .env

# Edit with your settings
nano .env
```

### 2. Run API Server

```bash
# Development mode (with reload)
python -m api.main

# Or with uvicorn directly
uvicorn api.app:app --reload --host 0.0.0.0 --port 8000

# Production mode
uvicorn api.app:app --host 0.0.0.0 --port 8000 --workers 4
```

### 3. Access API Documentation

Open browser:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## 📡 API Endpoints

### Authentication

#### Login
```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123"
}

Response:
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 2592000,
  "user_id": 1,
  "username": "admin",
  "role": "admin"
}
```

#### Logout
```http
POST /api/auth/logout
Authorization: Bearer {token}

Response:
{
  "message": "Successfully logged out"
}
```

#### Get Current User
```http
GET /api/auth/me
Authorization: Bearer {token}

Response:
{
  "access_token": "...",
  "token_type": "bearer",
  "expires_in": 2591999,
  "user_id": 1,
  "username": "admin",
  "role": "admin"
}
```

### File Operations

#### List Directory
```http
GET /api/files/list?worker_id=1&path=/share/data&offset=0&limit=1000
Authorization: Bearer {token}

Response:
{
  "path": "/share/data",
  "items": [
    {
      "name": "file.txt",
      "path": "/share/data/file.txt",
      "is_directory": false,
      "size_bytes": 1024,
      "modified_at": "2026-01-21T10:00:00Z"
    }
  ],
  "total_count": 50,
  "offset": 0,
  "limit": 1000,
  "has_more": false
}
```

#### Search Files
```http
GET /api/files/search?worker_id=1&path=/share&query=*.pdf&recursive=true
Authorization: Bearer {token}

Response:
{
  "query": "*.pdf",
  "results": [...],
  "total_count": 10,
  "offset": 0,
  "limit": 100
}
```

#### Copy File
```http
POST /api/files/copy
Authorization: Bearer {token}
Content-Type: application/json

{
  "source_path": "/share/pathA/file.txt",
  "dest_path": "/share/pathB/file.txt",
  "worker_ids": [1, 2],
  "overwrite": false
}

Response:
{
  "id": 1,
  "user_id": 1,
  "type": "copy",
  "source_path": "/share/pathA/file.txt",
  "dest_path": "/share/pathB/file.txt",
  "status": "completed",
  "started_at": "2026-01-21T10:00:00Z",
  "completed_at": "2026-01-21T10:00:05Z",
  "file_count": 1,
  "total_size_bytes": 1024,
  "created_at": "2026-01-21T10:00:00Z"
}
```

#### Move File
```http
POST /api/files/move
Authorization: Bearer {token}
Content-Type: application/json

{
  "source_path": "/share/pathA/file.txt",
  "dest_path": "/share/pathB/file.txt",
  "worker_ids": [1],
  "overwrite": false
}
```

#### Delete File
```http
POST /api/files/delete
Authorization: Bearer {token}
Content-Type: application/json

{
  "path": "/share/data/file.txt",
  "worker_id": 1,
  "recursive": false
}
```

#### Create Directory
```http
POST /api/files/mkdir
Authorization: Bearer {token}
Content-Type: application/json

{
  "path": "/share/data/new_folder",
  "worker_id": 1,
  "parents": true
}
```

### Workers

#### List Active Workers
```http
GET /api/workers/list
Authorization: Bearer {token}

Response:
[
  {
    "id": 1,
    "name": "worker-01",
    "hostname": "worker01.example.com",
    "path_a_prefix": "/mnt/shareA",
    "path_b_prefix": "/mnt/shareB",
    "status": "active",
    "version": "1.0.0",
    "last_heartbeat": "2026-01-21T10:00:00Z",
    "created_at": "2026-01-20T00:00:00Z",
    "updated_at": "2026-01-21T10:00:00Z"
  }
]
```

#### Register Worker (Admin Only)
```http
POST /api/workers/register
Authorization: Bearer {admin_token}
Content-Type: application/json

{
  "name": "worker-02",
  "hostname": "worker02.example.com",
  "public_key": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----",
  "path_a_prefix": "/mnt/shareA",
  "path_b_prefix": "/mnt/shareB",
  "version": "1.0.0"
}

Response:
{
  "id": 2,
  "name": "worker-02",
  ...
  "status": "pending"
}
```

### Admin

#### List Users (Admin Only)
```http
GET /api/admin/users
Authorization: Bearer {admin_token}

Response:
[
  {
    "id": 1,
    "username": "admin",
    "role": "admin",
    "is_active": true,
    "created_at": "2026-01-20T00:00:00Z",
    "updated_at": "2026-01-21T10:00:00Z"
  }
]
```

#### List Configuration (Admin Only)
```http
GET /api/admin/config
Authorization: Bearer {admin_token}

Response:
[
  {
    "key": "max_concurrent_users",
    "value": "4",
    "type": "int",
    "description": "Maximum number of concurrent authenticated users",
    "created_at": "2026-01-20T00:00:00Z",
    "updated_at": "2026-01-20T00:00:00Z"
  }
]
```

#### List Audit Logs (Admin Only)
```http
GET /api/admin/logs?offset=0&limit=100
Authorization: Bearer {admin_token}

Response:
[
  {
    "id": 1,
    "user_id": 1,
    "operation_id": 1,
    "action": "login_success",
    "details_json": {"session_id": 1},
    "remote_api_sent": false,
    "ip_address": "192.168.1.100",
    "user_agent": "Mozilla/5.0...",
    "timestamp": "2026-01-21T10:00:00Z"
  }
]
```

### WebSocket

#### Operation Updates
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/operations');

ws.onmessage = (event) => {
  const update = JSON.parse(event.data);
  console.log('Operation update:', update);
};
```

## 🔧 Configuration

### Environment Variables

Key settings in `.env`:

```bash
# API Server
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4

# Security
SECRET_KEY=<generate-with-secrets.token_urlsafe(64)>
ACCESS_TOKEN_EXPIRE_DAYS=30

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/filemanager

# Workers
WORKER_TIMEOUT=3600
WORKER_RETRY_ATTEMPTS=3

# Sybase Authentication (Optional)
ENABLE_SYBASE_AUTH=false
SYBASE_AUTH_URL=http://sybase-api.example.com/auth
SYBASE_AUTH_TIMEOUT=2

# Logging
LOG_LEVEL=INFO
ENABLE_JSON_LOGS=true
```

## 🏗️ Architecture

### Request Flow

```
Client → FastAPI → Middleware (Auth/Logging) → Route Handler
         ↓
    Services (Worker/Operation)
         ↓
    Worker Communication (HTTPS + mTLS)
         ↓
    Database (Audit Log)
```

### Multi-Worker Operation Flow

```
1. User requests copy from Path A to Path B
2. API validates request and creates Operation
3. Worker 1 copies file to shared location
4. Worker 1 confirms success
5. Worker 2 verifies file exists
6. Worker 2 confirms success
7. Both workers complete → Operation status: completed
8. If any failure → Automatic rollback
```

## 🛠️ Development

### Running Tests

```bash
pytest backend/api/tests -v
```

### Code Quality

```bash
# Format
black backend/api
isort backend/api

# Lint
ruff check backend/api

# Type check
mypy backend/api
```

### Hot Reload

```bash
uvicorn api.app:app --reload
```

## 🔒 Security

### Authentication Flow

1. User sends username/password to `/api/auth/login`
2. API verifies password (Argon2 hash)
3. Optional: Verify with Sybase API (2s timeout)
4. Create session in database
5. Generate JWT token with session ID
6. Return token to user
7. User includes token in `Authorization: Bearer {token}` header
8. Middleware validates token and session on each request

### Worker Authentication

1. Worker registers with public key
2. Admin approves worker (status: pending → active)
3. API signs requests with server private key
4. Worker verifies signature with API public key
5. Worker signs responses with its private key
6. API verifies signature with worker public key

## 📊 Monitoring

### Health Check

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "database": true,
  "redis": true,
  "timestamp": "2026-01-21T10:00:00Z"
}
```

### Logs

Structured JSON logs with loguru:

```json
{
  "timestamp": "2026-01-21T10:00:00.000Z",
  "level": "INFO",
  "message": "Request completed",
  "request_id": "abc123",
  "method": "POST",
  "path": "/api/files/copy",
  "status_code": 200,
  "duration_ms": 1234,
  "user_id": 1
}
```

## 🚨 Error Handling

### HTTP Status Codes

- `200 OK` - Success
- `201 Created` - Resource created
- `400 Bad Request` - Invalid request data
- `401 Unauthorized` - Authentication required
- `403 Forbidden` - Permission denied
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error
- `503 Service Unavailable` - Worker offline

### Error Response Format

```json
{
  "error": "Worker offline",
  "detail": "Worker worker-01 is unreachable"
}
```

## 📝 License

Part of the Modular File Manager Application.
