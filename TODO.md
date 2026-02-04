# TODO - RFM (Remote File Manager)

> **Project:** File operation management system with microservices architecture
> **Status:** Active Development ✅
> **Last Updated:** 2026-02-04

---

## 📋 ACTIVE TODO ITEMS

### Testing Checklist
- [ ] Push Operation: Select directory in Path A → verify copy to PATH_B and move to PATH_C
- [ ] Push Operation: Verify operation appears in queue with real-time status updates
- [ ] Pull Operation: Select completed Push → verify restore to original location
- [ ] Pull Operation: Verify directory removed from PATH_B after pull
- [ ] Error Handling: Test invalid directory, missing paths, insufficient permissions
- [ ] Admin Panel: Change PATH_B and PATH_C → verify new operations use new paths
- [ ] Admin Panel: Verify non-admin users cannot change paths
- [ ] Worker: Integration testing in staging environment
- [ ] Worker: Verify PathCPrefix configuration updates

---

## 🔧 RECENT FIXES (Last 7 Days)

### 2026-02-04 - Fix Persistent Issues (500 Errors & Empty Search)
**Issues**:
  1. PUSH/PULL operations succeeded but still showed error 500 toast
  2. Search returned empty list even for exact file/directory name matches

**Root Causes**:
  1. **500 Error**: WebSocket broadcast exception was propagating up and causing HTTP 500 response despite successful operation
  2. **Empty Search**: Worker response used different key names (sometimes "files", sometimes "items"), and search endpoint only checked "files" key

**Fixes Applied**:
  1. **Backend - WebSocket Error Handling**: Wrapped WebSocket broadcast in try-except block to prevent operation failure if broadcast fails
     - Fixed topic name from "operation" to "operations" (plural)
     - Added warning log if broadcast fails
     - Operations now return 200 even if WebSocket notification fails
  2. **Backend - Search Response Handling**: Updated search endpoint to check both "files" and "items" keys in error_details
     - Added debug logging to diagnose search response format
     - Added warning if error_details is None/missing
     - Handles empty search results gracefully

**Files Modified**:
  - `backend/api/app.py` (lines 523-548, 587-612 for WebSocket; lines 268-297 for search)

**Result**: ✅ PUSH/PULL operations complete with proper 200 status; ✅ Search now handles multiple response formats

### 2026-02-04 - Fix PUSH/PULL Operation 500 Errors
**Issue**: PUSH and PULL operations succeeded but returned 500 Internal Server Error to the client
**Root Causes**:
  1. WebSocket broadcast arguments were in wrong order: passing string as data and dict as topic
  2. OperationResponse schema missing `original_path` and `archive_path` fields used by PUSH/PULL operations
**Fixes Applied**:
  1. **Backend - WebSocket**: Fixed broadcast call to pass data dict first, topic second
  2. **Backend - Schema**: Added `original_path` and `archive_path` fields to OperationResponse
**Files Modified**:
  - `backend/api/app.py` (lines 531-539, 595-603)
  - `backend/api/schemas.py` (lines 271-272)
**Result**: ✅ PUSH/PULL operations now complete successfully with proper 200 responses

### 2026-02-04 - Path A Search Returning No Results
**Issue**: File/directory search in Path A pane returned absolutely nothing (no files, no directories)
**Root Causes**:
  1. Backend looked for `error_details["results"]` but worker sent `error_details["files"]` (key mismatch)
  2. Worker only searched files using `Directory.GetFiles()`, never searched directories
  3. Frontend filtered results to directories only (VF redesign filter)
**Fixes Applied**:
  1. **Backend**: Changed to look for `"files"` key in worker response, added `is_directory` default
  2. **Worker**: Added `Directory.GetDirectories()` to search both files AND directories, added `is_directory` flag
  3. **Frontend**: Removed directory-only filter from `handleSearch()`
**Files**: `backend/api/app.py:269-281`, `workers/FileManagerWorker/FileOperations.cs:628-705`, `frontend/js/app.js:620-624`

### 2026-02-04 - Complete Fix for PR#79 and PR#80 Issues
**Issue**: Operations succeeded but returned 500 error; selections lost on refresh; could re-pull already-reverted operations
**Root Causes**:
  1. Pydantic v2 immutability: Direct assignment after `model_validate()` in 3 more endpoints (history, search, list)
  2. Database session detachment: Operation objects expired after commit, causing serialization failures
  3. Frontend selection persistence: File/operation selections cleared on every refresh
  4. Missing pulled status: Operations could be pulled multiple times

**Fixes Applied**:
  1. **Backend - Pydantic**: Fixed remaining 3 endpoints to use `model_copy(update={...})`
  2. **Backend - Session**: Added `await db.refresh(operation)` after all `execute_operation()` calls
  3. **Frontend - Path A Selection**: Save/restore selected file paths during `renderFileList()`
  4. **Frontend - Operation History**: Preserve selected operation ID during refresh (already implemented)
  5. **Backend/Frontend - Pull Prevention**: Added `has_been_pulled` field to `OperationResponse`, query for existing PULL operations, disable checkbox for pulled operations

**Files Modified**:
  - `backend/api/app.py` (lines 333, 380, 426, 472, 516, 580, 637-664)
  - `backend/api/schemas.py` (lines 278-279)
  - `frontend/js/ui.js` (lines 22-60, 615)

**All Issues Resolved**: ✅ 500 errors fixed, ✅ selections persist, ✅ no duplicate pulls

### 2026-02-04 - Complete Pydantic Immutability Fix (PR#79/80)
**Issue**: All operation endpoints returned 500 error on success
**Fixed**: 6 endpoints now use `model_copy(update={...})` instead of direct assignment
**Endpoints**: `/api/files/copy`, `/api/files/move`, `/api/files/delete`, `/api/files/mkdir`, `/api/operations/push`, `/api/operations/pull`
**Files**: `backend/api/app.py`

### 2026-02-04 - Worker Remove Button
**Issue**: Remove button in Admin Panel had no effect
**Fixed**: Added event listener for `.remove-worker-btn`
**Files**: `frontend/pages/admin.html`

### 2026-02-04 - Cross-Volume Moves
**Issue**: Move operations failed across different drive letters
**Fixed**: Detect cross-volume moves → use copy+delete instead of native move
**Files**: `workers/FileManagerWorker/FileOperations.cs`

### 2026-02-04 - Real-Time UI Updates
**Issue**: Operation history and file listing required manual refresh
**Fixed**: Auto-refresh intervals (3s for operations, 5s for files) + WebSocket event handling
**Files**: `frontend/js/app.js`

### 2026-02-04 - Credential Manager → DPAPI
**Issue**: Network Service couldn't access credentials stored in Windows Credential Manager
**Fixed**: Created `SecureConfigStorage.cs` using DPAPI with LocalMachine scope
**Storage**: `C:\ProgramData\FileManagerWorker\config.dat` (machine-wide encryption)
**Files**: `workers/FileManagerWorker/SecureConfigStorage.cs`, `Program.cs`, `WorkerService.cs`

### 2026-02-03 - Missing Samba Credentials Validation
**Issue**: Worker started without samba credentials, operations failed silently
**Fixed**: Added validation in `WorkerService.cs` → throws error on startup if missing
**Files**: `workers/FileManagerWorker/WorkerService.cs`

### 2026-02-03 - PUSH Operation Impersonation
**Issue**: PUSH operations didn't use impersonation for file access
**Fixed**: Added `using (new ImpersonationContext(...))` around PUSH logic
**Files**: `workers/FileManagerWorker/FileOperations.cs`

### 2026-02-03 - UI Bug Fixes (3 issues)
1. Operation History: PUSH operations showed placeholder dest_path instead of actual PATH_B
2. Operation History: Pull button enabled for PENDING/IN_PROGRESS operations
3. Duplicate Pull Prevention: Added validation to reject pulling already-pulled operations
**Files**: `frontend/js/ui.js`, `backend/api/services/operation_service.py`

### 2026-02-03 - PATH A Display Issues
1. File listing showed relative paths instead of absolute paths
2. Worker selection dropdown not showing actual worker names
**Files**: `backend/api/app.py`, `frontend/js/app.js`

### 2026-01-29 - File Listing Prefix Notation
**Issue**: File listing used hardcoded `/` paths instead of prefix notation
**Fixed**: Updated to use `path_a_prefix://path` format
**Files**: `backend/api/app.py`

### 2026-01-29 - Database Schema (path_c_prefix)
**Issue**: `path_c_prefix` column missing from workers table
**Fixed**: Added migration and updated schema
**Files**: `backend/api/migrations/`

### 2026-01-29 - Worker Certificate Generation
**Issue**: Certificate generation used deprecated `X509CertificateCreator` API
**Fixed**: Updated to use `CertificateRequest` with proper SAN extension
**Files**: `workers/FileManagerWorker/Program.cs`

### 2026-01-29 - Worker Service Mode Registration
**Issue**: Workers couldn't register when running as Windows Service
**Fixed**: Multiple fixes for service mode operation and registration polling
**Files**: `workers/FileManagerWorker/Program.cs`, `WorkerService.cs`

### 2026-01-28 - VF Redesign Implementation
**Status**: ✅ Complete
**Changes**: Dual-pane file manager → PUSH/PULL operations with PATH_B (archive) and PATH_C (archive)
**Architecture**: Single PATH_A view, queue-based operations, pull-based worker communication
**Files**: Full frontend and backend refactor

---

## 🏗️ ARCHITECTURE NOTES

### VF Redesign (Implemented 2026-01-28)
- **UI**: Single PATH_A pane + Operation History
- **Operations**: PUSH (copy to PATH_B, move to PATH_C) / PULL (restore from PATH_B)
- **Workers**: Pull-based polling (no inbound connections required)
- **Security**: mTLS client certificates, approval workflow, impersonation

### Worker Configuration
- **Storage**: `C:\ProgramData\FileManagerWorker\config.dat` (DPAPI encrypted)
- **Certificates**: Self-signed with proper SAN extensions
- **Service**: Runs as Network Service with impersonation for file operations
- **Paths**: Supports prefix notation (e.g., `samba://server/share`)

### Backend
- **Framework**: FastAPI + SQLAlchemy (async)
- **Database**: SQLite (async with aiosqlite)
- **Search**: Elasticsearch integration for file indexing
- **Auth**: Session-based with bcrypt password hashing
- **WebSocket**: Real-time operation status updates

### Frontend
- **Stack**: Vanilla JS (no framework)
- **Auto-refresh**: 3s for operations, 5s for file listings
- **WebSocket**: Immediate updates for operation status changes

---

## 🔐 SECURITY NOTES

- Workers use mTLS with self-signed certificates
- Approval workflow for new workers (pending → approved → active)
- File operations use Windows impersonation with configured Samba credentials
- Credentials stored using DPAPI LocalMachine scope (machine-wide encryption)
- Admin panel restricts PATH configuration to admin users only

---

## 🚀 DEPLOYMENT

### Backend
```bash
cd backend/api
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

### Worker (Windows Service)
```bash
# Configure
FileManagerWorker.exe /config

# Install service
sc create FileManagerWorker binPath="C:\path\to\FileManagerWorker.exe" start=auto
sc start FileManagerWorker

# Verify
sc query FileManagerWorker
```

---

*Maintained following KISS and DRY principles throughout the codebase.*
