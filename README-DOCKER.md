# Modular File Manager - Docker Deployment Guide

Complete guide for deploying the Modular File Manager using Docker Compose with centralized API, WebUI, PostgreSQL, and Redis.

---

## 📋 Table of Contents

- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Service Details](#service-details)
- [Security](#security)
- [Management Commands](#management-commands)
- [Troubleshooting](#troubleshooting)
- [Production Deployment](#production-deployment)
- [Backup & Recovery](#backup--recovery)

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Host Machine                             │
│  ┌────────────┐                                                  │
│  │   Client   │                                                  │
│  │  Browser   │                                                  │
│  └─────┬──────┘                                                  │
│        │                                                          │
│        │ :3000 (WebUI)         :8000 (API)                       │
├────────┼─────────────────────────┼────────────────────────────────┤
│        │                         │                                │
│  ┌─────▼──────────────┐   ┌─────▼────────────────┐              │
│  │  WebUI Container   │   │   API Container      │              │
│  │  (Flask + Static)  │   │   (FastAPI)          │              │
│  │  Port: 3000        │───│   Port: 8000/8443    │              │
│  └────────────────────┘   └──────┬───────────────┘              │
│                                   │                               │
│          ┌────────────────────────┼───────────────┐              │
│          │                        │               │              │
│  ┌───────▼────────┐    ┌─────────▼──────┐  ┌────▼──────┐       │
│  │   PostgreSQL   │    │     Redis      │  │  Workers  │       │
│  │   Container    │    │   Container    │  │ (External)│       │
│  │   Port: 5432   │    │   Port: 6379   │  └───────────┘       │
│  └────────────────┘    └────────────────┘                       │
│         │                      │                                 │
│  ┌──────▼──────────────────────▼─────────────┐                  │
│  │        Internal Bridge Network            │                  │
│  │        (file-manager-network)              │                  │
│  └────────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Service | Image | Purpose | Exposed Ports |
|---------|-------|---------|---------------|
| **postgres** | postgres:16-alpine | Primary database | 5432 (localhost only) |
| **redis** | redis:7-alpine | Session store & cache | 6379 (localhost only) |
| **api** | Custom (FastAPI) | REST API backend | 8000 (HTTP), 8443 (HTTPS) |
| **webui** | Custom (Flask) | Frontend + API proxy | 3000 |

---

## ✅ Prerequisites

### Required Software

- **Docker**: Version 20.10+ ([Install Docker](https://docs.docker.com/get-docker/))
- **Docker Compose**: Version 2.0+ ([Install Compose](https://docs.docker.com/compose/install/))

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | 2 cores | 4+ cores |
| **RAM** | 4 GB | 8+ GB |
| **Disk Space** | 10 GB | 20+ GB |
| **OS** | Linux, macOS, Windows with WSL2 | Linux (production) |

### Network Ports

Ensure the following ports are available:

- `3000` - WebUI (can be changed via `WEBUI_HOST_PORT`)
- `8000` - API HTTP (can be changed via `API_HOST_PORT`)
- `8443` - API HTTPS (can be changed via `API_HOST_PORT_HTTPS`)
- `5432` - PostgreSQL (localhost only, for debugging)
- `6379` - Redis (localhost only, for debugging)

---

## 🚀 Quick Start

### 1. Clone Repository

```bash
cd /path/to/rfm
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Generate secure secret key
python3 -c "import secrets; print(secrets.token_urlsafe(64))" > secret.key

# Edit .env and set:
# - SECRET_KEY (paste from secret.key)
# - POSTGRES_PASSWORD (strong password)
# - REDIS_PASSWORD (strong password)
nano .env
```

### 3. Launch Services

```bash
# Start all services in detached mode
docker-compose up -d

# View logs
docker-compose logs -f
```

### 4. Verify Deployment

```bash
# Check service status
docker-compose ps

# Expected output:
# NAME                    STATUS              PORTS
# file-manager-api        Up (healthy)        0.0.0.0:8000->8000/tcp
# file-manager-webui      Up (healthy)        0.0.0.0:3000->3000/tcp
# file-manager-postgres   Up (healthy)        127.0.0.1:5432->5432/tcp
# file-manager-redis      Up (healthy)        127.0.0.1:6379->6379/tcp
```

### 5. Access Application

- **WebUI**: http://localhost:3000
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

**Default Credentials:**
- Username: `admin`
- Password: `admin123`

⚠️ **IMPORTANT**: Change the default password immediately after first login!

---

## ⚙️ Configuration

### Environment Variables

Edit `.env` file to customize deployment:

#### Essential Configuration

```bash
# Security (REQUIRED - change these!)
SECRET_KEY=YOUR_RANDOM_64_CHAR_STRING
POSTGRES_PASSWORD=your_secure_postgres_password
REDIS_PASSWORD=your_secure_redis_password

# Database
POSTGRES_USER=filemanager
POSTGRES_DB=filemanager
DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}

# API Configuration
API_WORKERS=4                        # Number of uvicorn workers
CORS_ORIGINS=http://localhost:3000   # Allowed CORS origins

# Ports
API_HOST_PORT=8000                   # API HTTP port on host
API_HOST_PORT_HTTPS=8443             # API HTTPS port on host
WEBUI_HOST_PORT=3000                 # WebUI port on host
```

#### Optional Configuration

```bash
# TLS/SSL
TLS_ENABLED=true
TLS_MIN_VERSION=1.3

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_RETENTION_DAYS=14

# Performance
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
REDIS_MAX_CONNECTIONS=50

# Application
MAX_CONCURRENT_USERS=4
OPERATION_TIMEOUT=3600
ENABLE_AUTO_ROLLBACK=true

# External Integrations
ENABLE_SYBASE_AUTH=false
ENABLE_SYSLOG=false
ENABLE_REMOTE_AUDIT_API=false
```

See `.env.example` for complete configuration options.

---

## 📦 Service Details

### PostgreSQL Database

- **Image**: `postgres:16-alpine`
- **Purpose**: Primary data store for users, operations, audit logs
- **Persistence**: `postgres-data` volume (survives container restarts)
- **Initialization**: Runs `init-db.sql` on first startup
- **Health Check**: `pg_isready` every 10 seconds

**Access PostgreSQL Shell:**

```bash
docker-compose exec postgres psql -U filemanager -d filemanager
```

### Redis Cache

- **Image**: `redis:7-alpine`
- **Purpose**: Session storage, caching
- **Configuration**: 256MB maxmemory, LRU eviction, AOF persistence
- **Persistence**: `redis-data` volume
- **Health Check**: Redis ping every 10 seconds

**Access Redis CLI:**

```bash
docker-compose exec redis redis-cli -a ${REDIS_PASSWORD}
```

### FastAPI Backend

- **Base Image**: `python:3.11-slim`
- **Server**: Uvicorn with multiple workers
- **Features**:
  - Automatic database migrations (Alembic)
  - Self-signed SSL certificate generation
  - Async PostgreSQL and Redis connections
  - JWT authentication
  - WebSocket support for real-time updates
- **Health Check**: HTTP GET `/health` every 15 seconds

**View API Logs:**

```bash
docker-compose logs -f api
```

### WebUI Frontend

- **Base Image**: `python:3.11-slim`
- **Server**: Gunicorn with Flask
- **Features**:
  - Static file serving (HTML, CSS, JS)
  - Optional API proxy (CORS-friendly)
  - Dual-pane file explorer
  - Real-time operation updates
- **Health Check**: HTTP GET `/health` every 15 seconds

**View WebUI Logs:**

```bash
docker-compose logs -f webui
```

---

## 🔒 Security

### Security Features Included

✅ **Authentication**
- Argon2id password hashing (OWASP recommended)
- JWT tokens with 30-day expiration
- Session management with IP tracking

✅ **Network Security**
- Internal bridge network (no direct DB exposure)
- PostgreSQL and Redis only accessible from containers
- Optional HTTPS with self-signed certificates

✅ **Container Security**
- Non-root users in all containers
- Read-only volume mounts where possible
- Resource limits enforced

✅ **Audit Trail**
- Immutable audit logs for all operations
- IP address and user agent tracking
- Complete operation history

### Production Security Checklist

Before deploying to production:

- [ ] Change default admin password
- [ ] Generate strong `SECRET_KEY` (64+ characters)
- [ ] Use strong passwords for PostgreSQL and Redis
- [ ] Mount production SSL certificates (replace self-signed)
- [ ] Remove PostgreSQL and Redis port mappings in `docker-compose.yml`
- [ ] Enable firewall rules to restrict access
- [ ] Configure `CORS_ORIGINS` to match production domains
- [ ] Enable rate limiting and IP whitelisting
- [ ] Set up regular backups (see [Backup & Recovery](#backup--recovery))
- [ ] Monitor logs for suspicious activity
- [ ] Keep Docker images updated

### Generating Secure Secrets

```bash
# SECRET_KEY (64 characters)
python3 -c "import secrets; print(secrets.token_urlsafe(64))"

# Random password (32 characters)
openssl rand -base64 32

# PostgreSQL password hash for admin
python3 -c "from passlib.hash import argon2; print(argon2.hash('your_password'))"
```

---

## 🔧 Management Commands

### Starting & Stopping

```bash
# Start all services
docker-compose up -d

# Start specific service
docker-compose up -d api

# Stop all services
docker-compose down

# Stop and remove volumes (DATA LOSS!)
docker-compose down -v

# Restart service
docker-compose restart api

# View status
docker-compose ps
```

### Logs & Debugging

```bash
# View all logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f api
docker-compose logs -f webui

# View last 100 lines
docker-compose logs --tail=100 api

# Save logs to file
docker-compose logs --no-color > logs.txt
```

### Executing Commands

```bash
# Shell into API container
docker-compose exec api /bin/bash

# Shell into PostgreSQL container
docker-compose exec postgres /bin/bash

# Run Python script in API container
docker-compose exec api python /app/backend/scripts/migrate.py

# PostgreSQL query
docker-compose exec postgres psql -U filemanager -d filemanager -c "SELECT * FROM users;"

# Redis command
docker-compose exec redis redis-cli -a ${REDIS_PASSWORD} KEYS "*"
```

### Database Operations

```bash
# Run migrations manually
docker-compose exec api alembic upgrade head

# Create new migration
docker-compose exec api alembic revision -m "description"

# Rollback migration
docker-compose exec api alembic downgrade -1

# Check migration status
docker-compose exec api alembic current

# Database backup
docker-compose exec postgres pg_dump -U filemanager filemanager > backup.sql

# Database restore
cat backup.sql | docker-compose exec -T postgres psql -U filemanager filemanager
```

### Maintenance

```bash
# Update images
docker-compose pull

# Rebuild containers after code changes
docker-compose up -d --build

# Remove old images
docker image prune -a

# View resource usage
docker stats

# Check disk usage
docker system df
```

---

## 🐛 Troubleshooting

### Common Issues

#### 1. Services Won't Start

**Symptom:** Containers exit immediately

```bash
# Check logs for errors
docker-compose logs api
docker-compose logs postgres

# Common causes:
# - Port already in use
# - Invalid environment variables
# - Permission issues with volumes
```

**Solution:**

```bash
# Check port usage
sudo netstat -tulpn | grep -E '(3000|8000|5432|6379)'

# Validate .env file
cat .env | grep -E '^[A-Z_]+='

# Fix permissions
sudo chown -R $(id -u):$(id -g) .
```

#### 2. Database Connection Errors

**Symptom:** API logs show "could not connect to server"

```bash
# Check PostgreSQL health
docker-compose exec postgres pg_isready -U filemanager

# Verify password
docker-compose exec postgres psql -U filemanager -d filemanager -c "SELECT 1;"
```

**Solution:**

```bash
# Ensure DATABASE_URL matches POSTGRES_* variables
# Restart services in order
docker-compose restart postgres
docker-compose restart redis
docker-compose restart api
```

#### 3. WebUI Can't Connect to API

**Symptom:** WebUI shows "Backend API unavailable"

```bash
# Test API health
curl http://localhost:8000/health

# Check API logs
docker-compose logs -f api
```

**Solution:**

```bash
# Verify API_URL in .env
grep API_URL .env

# Should be: API_URL=http://api:8000 (internal network)
# Not: API_URL=http://localhost:8000

# Restart WebUI
docker-compose restart webui
```

#### 4. Permission Denied Errors

**Symptom:** Containers can't write logs or data

```bash
# Fix volume permissions
docker-compose down
sudo chown -R 1000:1000 ./logs ./config
docker-compose up -d
```

#### 5. Out of Memory

**Symptom:** Containers killed by OOM

```bash
# Check memory usage
docker stats

# Add resource limits to docker-compose.yml
services:
  api:
    deploy:
      resources:
        limits:
          memory: 2G
```

### Health Checks

```bash
# API health
curl http://localhost:8000/health

# WebUI health
curl http://localhost:3000/health

# PostgreSQL health
docker-compose exec postgres pg_isready

# Redis health
docker-compose exec redis redis-cli -a ${REDIS_PASSWORD} ping
```

### Debug Mode

Enable debug logging:

```bash
# Edit .env
DEBUG=true
LOG_LEVEL=DEBUG
SQL_ECHO=true

# Restart services
docker-compose restart api webui
```

---

## 🌐 Production Deployment

### Production Checklist

#### 1. Environment Configuration

```bash
# Production .env settings
DEBUG=false
LOG_LEVEL=INFO
SQL_ECHO=false
API_RELOAD=false
FLASK_ENV=production
FLASK_DEBUG=false
```

#### 2. Remove Debug Ports

Edit `docker-compose.yml` and remove PostgreSQL/Redis port mappings:

```yaml
services:
  postgres:
    # Remove these lines in production
    # ports:
    #   - "127.0.0.1:5432:5432"

  redis:
    # Remove these lines in production
    # ports:
    #   - "127.0.0.1:6379:6379"
```

#### 3. Use Production SSL Certificates

```bash
# Mount real certificates
mkdir -p ./ssl
cp /path/to/your/cert.pem ./ssl/
cp /path/to/your/key.pem ./ssl/

# Update docker-compose.yml
volumes:
  - ./ssl:/etc/ssl/file-manager:ro
```

#### 4. Configure Reverse Proxy (Nginx)

```nginx
# /etc/nginx/sites-available/filemanager
server {
    listen 80;
    server_name filemanager.example.com;

    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name filemanager.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # WebUI
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # API
    location /api/ {
        proxy_pass http://localhost:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://localhost:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

#### 5. Resource Limits

Add to `docker-compose.yml`:

```yaml
services:
  api:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G

  postgres:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
```

#### 6. Monitoring

Set up monitoring with Docker stats or Prometheus:

```bash
# View real-time stats
docker stats --no-stream

# Export metrics (Prometheus format)
curl http://localhost:8000/metrics
```

---

## 💾 Backup & Recovery

### Automated Backups

Create backup script `/usr/local/bin/backup-filemanager.sh`:

```bash
#!/bin/bash
set -e

BACKUP_DIR="/backups/filemanager"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

echo "[$(date)] Starting backup..."

# Database backup
docker-compose exec -T postgres pg_dump -U filemanager filemanager | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# Volume backups
docker run --rm -v file-manager-postgres-data:/data -v $BACKUP_DIR:/backup alpine tar czf /backup/postgres_data_$DATE.tar.gz -C /data .
docker run --rm -v file-manager-redis-data:/data -v $BACKUP_DIR:/backup alpine tar czf /backup/redis_data_$DATE.tar.gz -C /data .
docker run --rm -v file-manager-logs:/data -v $BACKUP_DIR:/backup alpine tar czf /backup/logs_$DATE.tar.gz -C /data .

# Cleanup old backups (keep last 7 days)
find $BACKUP_DIR -name "*.gz" -mtime +7 -delete

echo "[$(date)] Backup completed: $BACKUP_DIR"
```

Schedule with cron:

```bash
chmod +x /usr/local/bin/backup-filemanager.sh

# Daily backup at 2 AM
echo "0 2 * * * /usr/local/bin/backup-filemanager.sh >> /var/log/filemanager-backup.log 2>&1" | sudo crontab -
```

### Manual Backup

```bash
# Database only
docker-compose exec postgres pg_dump -U filemanager filemanager > backup_$(date +%Y%m%d).sql

# Complete backup (all volumes)
docker-compose down
tar -czf backup_complete_$(date +%Y%m%d).tar.gz \
    -C /var/lib/docker/volumes file-manager-postgres-data \
    -C /var/lib/docker/volumes file-manager-redis-data \
    -C /var/lib/docker/volumes file-manager-logs
docker-compose up -d
```

### Recovery

```bash
# Stop services
docker-compose down

# Restore database
cat backup.sql | docker-compose up -d postgres
sleep 10
cat backup.sql | docker-compose exec -T postgres psql -U filemanager filemanager

# Restore volumes (if needed)
docker run --rm -v file-manager-postgres-data:/data -v $(pwd):/backup alpine sh -c "cd /data && tar xzf /backup/postgres_data_TIMESTAMP.tar.gz"

# Start all services
docker-compose up -d
```

---

## 📚 Additional Resources

### Documentation

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [PostgreSQL Docker Hub](https://hub.docker.com/_/postgres)
- [Redis Docker Hub](https://hub.docker.com/_/redis)
- [Docker Compose Reference](https://docs.docker.com/compose/compose-file/)

### Project Files

- `docker-compose.yml` - Service orchestration
- `Dockerfile.api` - API container build
- `Dockerfile.webui` - WebUI container build
- `init-db.sql` - Database initialization
- `.env.example` - Configuration template

### Support

For issues and questions:
1. Check logs: `docker-compose logs -f`
2. Review this guide's [Troubleshooting](#troubleshooting) section
3. Check database status: `docker-compose exec postgres pg_isready`
4. Verify network connectivity: `docker network inspect file-manager-network`

---

## 📄 License

Modular File Manager - Enterprise File Management System

---

**Quick Commands Reference:**

```bash
# Start
docker-compose up -d

# Stop
docker-compose down

# Logs
docker-compose logs -f

# Status
docker-compose ps

# Shell
docker-compose exec api /bin/bash

# Backup DB
docker-compose exec postgres pg_dump -U filemanager filemanager > backup.sql

# Rebuild
docker-compose up -d --build
```

**Default Access:**
- WebUI: http://localhost:3000
- API: http://localhost:8000
- Username: `admin`
- Password: `admin123` (change immediately!)

---
