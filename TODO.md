# TODO - RFM (Remote File Manager)

> **Projekt:** System zarządzania operacjami plikowymi z architekturą mikroserwisową
>
> **Status:** MVP w trakcie rozwoju
>
> **Ostatnia aktualizacja:** 2026-01-22

---

## 📋 Spis Treści

- [Legenda](#legenda)
- [Status Ogólny](#status-ogólny)
- [Backend - API & Core](#backend---api--core)
- [Frontend - WebUI](#frontend---webui)
- [Workers - Usługi Windows](#workers---usługi-windows)
- [Baza Danych](#baza-danych)
- [Infrastruktura & DevOps](#infrastruktura--devops)
- [Bezpieczeństwo](#bezpieczeństwo)
- [Logowanie & Audyt](#logowanie--audyt)
- [Dokumentacja](#dokumentacja)
- [Testy](#testy)
- [Optymalizacja & Performance](#optymalizacja--performance)
- [Przyszłe Funkcjonalności](#przyszłe-funkcjonalności)

---

## Legenda

- ✅ **Zrobione** - Feature zaimplementowany i przetestowany
- 🚧 **W trakcie** - Feature w trakcie implementacji
- 📝 **Zaplanowane** - Feature zaplanowany do implementacji
- ⚠️ **Wymaga uwagi** - Feature z problemami lub wymagający poprawek
- 🔄 **Do refaktoryzacji** - Feature wymaga przepisania/poprawy

---

## Status Ogólny

### Moduły Główne

| Moduł | Status | Kompletność | Priorytet |
|-------|--------|-------------|-----------|
| **Autentykacja & Autoryzacja** | ✅ | 95% | Wysoki |
| **Panel Administracyjny** | 🚧 | 85% | Wysoki |
| **Operacje Plikowe** | ✅ | 90% | Wysoki |
| **Worker Management** | ✅ | 85% | Wysoki |
| **WebSocket Real-time** | 📝 | 30% | Średni |
| **Zewnętrzna Autentykacja** | 📝 | 0% | Średni |
| **Remote Audit API** | 📝 | 0% | Niski |
| **Worker (Windows Service)** | ✅ | 90% | Wysoki |

---

## Backend - API & Core

### Autentykacja & Autoryzacja
- ✅ JWT token-based authentication (HS256)
- ✅ Argon2id password hashing
- ✅ RBAC (ADMIN, OPERATOR, VIEWER)
- ✅ Session management z długimi tokenami (30 dni)
- ✅ IP address & user agent tracking
- 📝 **Zewnętrzna autentykacja Sybase 17**
  - Przygotować connector do Sybase API
  - Zaimplementować fallback do lokalnej DB
  - Obsługa timeoutów (2s)
  - Stored procedure call: weryfikacja username/password
- 📝 **Admin zawsze loguje się z .env**
  - Hash hasła admina w .env
  - Oddzielna ścieżka logowania dla admina
  - Bypass external auth dla admina

### User Management
- ✅ Model User w bazie danych
- ✅ CRUD endpoints dla użytkowników (`/api/admin/users`)
- ✅ User preferences model (UserPreferences)
- ✅ Preferences API endpoints (`/api/preferences/me`)
- 📝 **Zaawansowane funkcje użytkownika**
  - Rate limiting per user
  - User activity tracking
  - Password reset flow (opcjonalny)
  - User groups/teams (future)

### Worker Management
- ✅ Worker registration z public key
- ✅ Worker approval workflow (PENDING → ACTIVE)
- ✅ Worker suspend/activate
- ✅ Heartbeat tracking
- ✅ Path prefix override per worker
- 📝 **Worker Health Monitoring**
  - Auto-suspend przy braku heartbeat
  - Worker performance metrics
  - Capacity planning (ile operacji może obsłużyć)
- 📝 **Worker Failover & Redundancy**
  - Automatic worker failover
  - Load balancing między workers
  - Worker clustering (2 workery = 1 para)

### Operacje Plikowe
- ✅ Copy operation (1 lub 2 workery)
- ✅ Move operation
- ✅ Delete operation
- ✅ Mkdir operation
- ✅ List directory (paginacja, lazy loading)
- ✅ Search files (recursive)
- 📝 **Rozszerzone operacje**
  - Rename file/folder
  - File properties/metadata viewing
  - Batch operations (multiple files at once)
  - Operation scheduling (zaplanuj operację na później)
- 📝 **Rollback & Recovery**
  - ✅ Auto-rollback on failure (basic)
  - Snapshot-based rollback
  - Manual rollback przez użytkownika
  - Rollback history & restore points
- 📝 **Operation Queue & Locking**
  - FIFO queue per worker
  - Resource locking (file/folder level)
  - Conflict detection & resolution
  - Max concurrent operations (parametryzowane, default: 4)
  - Queue status visibility dla użytkownika

### Configuration Management
- ✅ Config model w bazie danych
- ✅ 30+ parametrów konfiguracyjnych
- ✅ GET `/api/admin/config` endpoint
- ✅ PUT `/api/admin/config/{key}` endpoint
- ✅ POST `/api/admin/config/bulk` endpoint
- ✅ Frontend Configuration tab z wszystkimi parametrami
- 📝 **Configuration Validation**
  - Walidacja przed zapisem (typy, ranges)
  - Configuration backup & restore
  - Configuration versioning (history zmian)
- 📝 **Hot Configuration Reload**
  - Reload konfiguracji bez restartu
  - Broadcast zmian do workerów
  - Configuration change notifications

### API Endpoints - Missing
- 📝 **Statistics & Monitoring**
  - `/api/stats/operations` - statystyki operacji
  - `/api/stats/users` - aktywność użytkowników
  - `/api/stats/workers` - wydajność workerów
  - `/api/stats/system` - system resources
- 📝 **Batch Operations**
  - `/api/operations/batch` - multiple operations at once
  - `/api/operations/schedule` - scheduled operations
- 📝 **File Preview**
  - `/api/files/preview` - preview file content (text, images)
  - `/api/files/download` - download file through API (opcjonalne)

---

## Frontend - WebUI

### Dual-Pane Explorer
- ✅ Basic dual-pane layout (A/B)
- ✅ File listing z paginacją
- ✅ Breadcrumb navigation
- ✅ Search functionality
- ✅ Context menu (right-click)
- ✅ Select all/none checkboxes
- 📝 **Real-time Updates**
  - WebSocket connection for live updates
  - Auto-refresh directory on changes
  - Real-time operation progress
  - Worker status live updates
- 📝 **Zaawansowane UI Features**
  - Drag & drop między panelami
  - File icons based on type
  - File size visualization (progress bars)
  - Keyboard shortcuts (F5 refresh, Ctrl+A select, etc.)
  - Dual-pane sync scroll (opcjonalnie)
- 📝 **User Preferences**
  - Remember last paths (A i B)
  - Theme switcher (light/dark)
  - Layout preferences (horizontal/vertical)
  - Sort preferences persistence
  - Items per page customization

### Admin Panel
- ✅ User management (CRUD)
- ✅ Worker management (approve, suspend)
- ✅ Configuration tab z wszystkimi parametrami
- ✅ Audit logs viewer
- 🚧 **JavaScript Integration**
  - ⚠️ Istniejący inline script w admin.html
  - ✅ Nowy admin.js module (do integracji)
  - Zastąpić inline script modułowym kodem
  - Dodać proper error handling
  - Toast notifications zamiast alert()
- 📝 **Dashboard & Statistics**
  - Dashboard tab z key metrics
  - Real-time system stats
  - Charts (operacje, użytkownicy, workery)
  - Export reports (PDF, CSV)

### UI/UX Improvements
- 📝 **Responsive Design**
  - Mobile-friendly layout
  - Tablet optimization
  - Touch gestures support
- 📝 **Accessibility**
  - Keyboard navigation
  - Screen reader support
  - ARIA labels
  - High contrast mode
- 📝 **Loading States**
  - Skeleton screens
  - Progress indicators
  - Lazy loading dla dużych list
- 📝 **Error Handling**
  - Friendly error messages
  - Retry mechanisms
  - Fallback UI dla błędów

---

## Workers - Usługi Windows

### Core Functionality
- ✅ Windows Service (TopShelf framework)
- ✅ Self-installing .exe
- ✅ Configuration wizard (URL centrali, user/pass)
- ✅ Public/private key generation
- ✅ mTLS communication z centralą
- ✅ File operations (copy, move, delete, mkdir, list, search)
- ✅ Rollback manager
- ✅ Windows Credential Manager integration

### Wymagane Usprawnienia
- 📝 **Asynchroniczne Operacje**
  - ✅ Podstawowa asynchroniczność
  - Thread pool dla wielu operacji
  - Cancelation tokens
  - Progress reporting do centrali
- 📝 **Locking & Concurrency**
  - File-level locking
  - Folder-level locking
  - Lock timeout handling
  - Deadlock detection
- 📝 **Error Handling & Resilience**
  - Retry logic z exponential backoff
  - Circuit breaker pattern
  - Graceful degradation
  - Detailed error reporting
- 📝 **Logging (Local)**
  - Worker NIE zostawia logów (zgodnie z wymaganiami)
  - Debug mode: output do konsoli
  - Opcjonalny tryb verbose dla debugowania
- 📝 **Performance**
  - Bandwidth throttling (opcjonalne)
  - Compression dla dużych transferów (opcjonalne)
  - Resume interrupted operations
- 📝 **Compatibility**
  - ✅ Windows Server 2012 R2 (HV2012r2) minimum
  - Testowanie na różnych wersjach Windows
  - Obsługa różnych lokalizacji (non-English Windows)
- 📝 **Installation & Uninstallation**
  - ✅ Self-installing .exe
  - Uninstall command (`worker.exe /uninstall`)
  - Upgrade mechanism
  - Configuration migration przy upgrade
- 📝 **2-Worker Coordination**
  - Worker-to-worker communication
  - Push operation (A → B)
  - Weryfikacja przez drugi worker
  - Transaction coordination (2-phase commit)

---

## Baza Danych

### Aktualne Modele
- ✅ Users
- ✅ Sessions
- ✅ Workers
- ✅ Operations
- ✅ OperationWorkers (M2M)
- ✅ AuditLogs
- ✅ Config
- ✅ UserPreferences *(nowy)*

### Migracje
- ✅ `001_initial_schema.py` - Initial schema
- ✅ `002_add_user_preferences.py` - User preferences
- 📝 **Wymagane Migracje**
  - Uruchomić migrację 002 na środowisku
  - Dodać indeksy dla performance
  - Partycjonowanie tabeli audit_logs (jeśli duża)

### Optymalizacje
- 📝 **Indeksy**
  - Przeanalizować query patterns
  - Dodać composite indexes gdzie potrzeba
  - Index maintenance strategy
- 📝 **Partycjonowanie**
  - Partycjonowanie audit_logs po dacie
  - Archive old operations
- 📝 **Backup & Recovery**
  - Automated backup strategy
  - Point-in-time recovery
  - Disaster recovery plan
- 📝 **Views & Materialized Views**
  - ✅ system_stats view
  - Worker performance view
  - User activity summary view

---

## Infrastruktura & DevOps

### Docker & Compose
- ✅ docker-compose.yml z PostgreSQL, Redis, API, WebUI
- ✅ Dockerfiles dla API i WebUI
- ✅ Health checks
- ✅ Volume management
- ✅ Network isolation
- 📝 **Production Readiness**
  - Multi-stage builds dla mniejszych images
  - Secret management (nie .env w repo)
  - Docker secrets / Vault integration
  - Resource limits (CPU, memory)
  - Log aggregation (Fluentd, ELK)

### Deployment
- 📝 **CI/CD Pipeline**
  - GitHub Actions / GitLab CI
  - Automated tests before deploy
  - Blue-green deployment
  - Rollback mechanism
- 📝 **Environments**
  - Development
  - Staging
  - Production
  - Environment-specific configs
- 📝 **Monitoring**
  - Prometheus metrics
  - Grafana dashboards
  - Alerting (PagerDuty, Slack)
  - Uptime monitoring

### Scalability
- 📝 **Horizontal Scaling**
  - Load balancer przed API
  - Multiple API instances
  - Session affinity (sticky sessions)
  - Database connection pooling
- 📝 **Caching**
  - ✅ Redis dla sessions
  - Cache dla file listings
  - Cache dla configuration
  - Cache invalidation strategy

---

## Bezpieczeństwo

### Aktualne Zabezpieczenia
- ✅ JWT authentication
- ✅ Argon2id password hashing
- ✅ HTTPS/TLS 1.3
- ✅ mTLS dla worker-central communication
- ✅ Public key authentication dla workerów
- ✅ CORS configuration
- ⚠️ Default admin credentials (admin/admin123) - **ZMIENIĆ PRZED PRODUKCJĄ**
- ⚠️ Self-signed certificates - **prawdziwe certy w produkcji**

### Wymagane Usprawnienia
- 📝 **SSL/TLS**
  - Prawdziwe certyfikaty (Let's Encrypt)
  - Certificate rotation
  - Certificate pinning dla workerów
- 📝 **Secrets Management**
  - Usunąć hasła z .env
  - Hashicorp Vault / AWS Secrets Manager
  - Rotate secrets regularly
- 📝 **IP Whitelisting**
  - ✅ Config parametr enable_ip_whitelist
  - Implementacja IP filtering middleware
  - Geo-IP blocking (opcjonalnie)
- 📝 **Rate Limiting**
  - ✅ Config parametr enable_rate_limiting
  - Implementacja rate limiting middleware (per user, per IP)
  - DDoS protection
  - Brute force protection dla logowania
- 📝 **Audit & Compliance**
  - GDPR compliance (data retention, deletion)
  - SOC 2 requirements
  - PCI DSS (jeśli aplikable)
- 📝 **Security Scanning**
  - SAST (Bandit, Semgrep)
  - DAST (OWASP ZAP)
  - Dependency scanning (Snyk, Dependabot)
  - Container scanning (Trivy)

---

## Logowanie & Audyt

### Aktualne Logowanie
- ✅ Structured logging (loguru)
- ✅ Request/response logging
- ✅ Audit logs w bazie danych
- ✅ User action tracking
- ✅ Operation tracking
- ✅ Admin action tracking

### Wymagane Integracje
- 📝 **Syslog Integration**
  - ✅ Config parametry (host, port, protocol)
  - Implementacja syslog handler
  - Format zgodny z RFC 5424
  - UDP/TCP support
- 📝 **Remote Audit API (Sybase)**
  - ✅ Config parametry (URL, token, timeout)
  - Async push do zdalnego API
  - Retry logic przy failure
  - Batch sending (grupowanie logów)
  - Fallback przy niedostępności API
- 📝 **Log Rotation & Compression**
  - ✅ Config: log_retention_days, enable_log_compression
  - Implementacja automatycznej rotacji
  - Kompresja starszych logów (gzip)
  - Usuwanie po upływie retencji
  - Archiwizacja (opcjonalne)
- 📝 **Log Viewing & Search**
  - ✅ Basic log viewer w admin panel
  - Zaawansowane filtrowanie (date range, user, action)
  - Full-text search w logach
  - Log export (JSON, CSV, TXT)
  - Real-time log streaming (WebSocket)
- 📝 **Metrics & Analytics**
  - Operation success/failure rates
  - Average operation duration
  - User activity heatmaps
  - Worker utilization metrics

---

## Dokumentacja

### Istniejąca Dokumentacja
- ✅ README.md (główny)
- ✅ README_DATABASE.md
- ✅ README-DOCKER.md
- ✅ README_API.md (backend/api/)
- ✅ Workers documentation
- ✅ Installer guide

### Wymagana Dokumentacja
- ✅ TODO.md (ten plik)
- 📝 **Architecture Documentation**
  - System architecture diagram
  - Data flow diagrams
  - Sequence diagrams (operacje 1-worker, 2-worker)
  - Component interaction diagrams
- 📝 **API Documentation**
  - OpenAPI/Swagger spec
  - Postman collection
  - API usage examples
  - Rate limits documentation
- 📝 **Deployment Guide**
  - Production deployment checklist
  - Configuration guide
  - Backup & restore procedures
  - Troubleshooting guide
- 📝 **User Manual**
  - End-user guide (operatorzy)
  - Admin guide
  - FAQ
  - Video tutorials (opcjonalnie)
- 📝 **Developer Guide**
  - Development setup
  - Code style guide
  - Contributing guidelines
  - Git workflow
  - How to add new features

---

## Testy

### Aktualne Testy
- ✅ Auth tests only (basic)
- ❌ File operation tests
- ❌ Worker communication tests
- ❌ Integration tests
- ❌ E2E tests

### Wymagane Testy
- 📝 **Unit Tests**
  - Backend models (100% coverage)
  - API endpoints (90%+ coverage)
  - Auth & authorization logic
  - Configuration management
  - Utilities & helpers
- 📝 **Integration Tests**
  - Database operations
  - API with database
  - Worker communication
  - External API integration (Sybase mock)
- 📝 **E2E Tests**
  - User workflows (login → browse → copy file → logout)
  - Admin workflows (user management, worker approval)
  - 2-worker operations
  - Failure scenarios (rollback)
- 📝 **Performance Tests**
  - Load testing (JMeter, Locust)
  - Stress testing
  - Capacity planning
  - Database query optimization
- 📝 **Security Tests**
  - Penetration testing
  - Vulnerability scanning
  - Authentication bypass attempts
  - SQL injection, XSS tests

---

## Optymalizacja & Performance

### Backend Optimizations
- 📝 **Database**
  - Connection pooling (już jest, ale sprawdzić parametry)
  - Query optimization (EXPLAIN ANALYZE)
  - Eager loading vs. lazy loading
  - Caching frequently accessed data
- 📝 **API**
  - Response compression (gzip)
  - Pagination optimization
  - Async everywhere (już jest, ale weryfikacja)
  - Background tasks (Celery/RQ dla heavy operations)
- 📝 **Caching Strategy**
  - Redis caching dla config
  - File listing cache (short TTL)
  - Worker status cache
  - Cache warming

### Frontend Optimizations
- 📝 **Performance**
  - Code splitting
  - Lazy loading routes
  - Image optimization
  - Minification & bundling (Webpack/Vite)
- 📝 **Network**
  - Service Worker dla offline support
  - HTTP/2 push
  - CDN dla static assets

### Worker Optimizations
- 📝 **File Operations**
  - Parallel file transfers (threads)
  - Bandwidth throttling dla niezakłócania sieci
  - Smart retry logic
  - Resume partial transfers

---

## Przyszłe Funkcjonalności

### Planowane na Wersję 2.0
- 📝 **Scheduled Operations**
  - Zaplanowanie operacji na określony czas
  - Recurring operations (cron-like)
  - Operation templates
- 📝 **File Synchronization**
  - Automatic sync A ↔ B
  - Conflict resolution strategies
  - Sync scheduling
- 📝 **Multi-site Support**
  - Multiple locations (więcej niż 2)
  - Site-to-site replication
  - Geo-distributed workers
- 📝 **Advanced Permissions**
  - Folder-level permissions
  - User groups
  - ACL management UI
- 📝 **Notifications**
  - Email notifications
  - Slack/Teams integration
  - SMS notifications (critical alerts)
  - In-app notifications
- 📝 **Workflow Engine**
  - Define multi-step workflows
  - Approval workflows
  - Automated workflows (if X then Y)
- 📝 **API Webhooks**
  - Webhooks dla operation events
  - Webhook retry logic
  - Webhook logs
- 📝 **Multi-tenancy**
  - Separate tenants/organizations
  - Tenant isolation
  - Per-tenant configuration
- 📝 **Cloud Storage Integration**
  - AWS S3 support
  - Azure Blob Storage
  - Google Cloud Storage
  - Hybrid cloud/on-prem

### Planowane na Wersję 3.0+
- 📝 **Machine Learning**
  - Predictive analytics (które pliki będą przenoszone)
  - Anomaly detection (unusual operations)
  - Capacity forecasting
- 📝 **Mobile App**
  - iOS app
  - Android app
  - Mobile notifications
- 📝 **Linux Worker Support**
  - Linux worker implementation
  - Cross-platform compatibility
  - Docker-based workers
- 📝 **Advanced Reporting**
  - Custom reports
  - Report scheduling
  - Business intelligence dashboard

---

## Priorytety - Co Zrobić Najpierw?

### 🔥 Krytyczne (Przed Produkcją)
1. ⚠️ **Zmienić default admin credentials**
2. ⚠️ **Prawdziwe SSL/TLS certificates**
3. 📝 **Uruchomić migrację 002 (UserPreferences)**
4. 📝 **Zintegrować admin.js z admin.html** (usunąć duplicate code)
5. 📝 **Zewnętrzna autentykacja Sybase** (jeśli wymagana od razu)
6. 📝 **Rate limiting & IP whitelisting** (basic security)

### 🚀 Wysokie Priority (MVP)
1. 📝 **Real-time WebSocket updates** (kluczowe dla UX)
2. 📝 **Operation queue & locking** (prevent conflicts)
3. 📝 **2-worker coordination** (push A→B z weryfikacją)
4. 📝 **Syslog integration** (logowanie)
5. 📝 **Rollback improvements** (manual rollback UI)
6. 📝 **Worker failover** (high availability)

### 📊 Średnie Priority
1. 📝 **Dashboard & statistics** (admin panel)
2. 📝 **Drag & drop UI**
3. 📝 **File preview**
4. 📝 **Batch operations**
5. 📝 **User preferences UI**
6. 📝 **Dark mode**

### 🔮 Niskie Priority (Post-MVP)
1. 📝 **Remote Audit API (Sybase)** - jeśli nie wymagane od razu
2. 📝 **Operation scheduling**
3. 📝 **File synchronization**
4. 📝 **Notifications**
5. 📝 **Advanced reporting**

---

## Kontakt & Support

**Projekt:** RFM - Remote File Manager
**Wersja:** 1.0.0-beta
**Ostatnia aktualizacja:** 2026-01-22

Dla pytań i problemów:
- GitHub Issues: [awsosi/rfm/issues](https://github.com/awsosi/rfm/issues)
- Email: [contact email placeholder]

---

*Dokument będzie regularnie aktualizowany w miarę postępu projektu.*
