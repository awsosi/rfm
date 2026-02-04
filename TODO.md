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

### 2026-02-04 - Fix Concurrent PUSH/PULL Operations Race Condition (Phantom Operations)
**Issue**: When 2 users push/pull the same directory concurrently, a phantom third operation appears with incorrect directory paths (shows B:/example when actual direction was A->B). The phantom operation completes successfully but makes no logical sense and isn't properly logged.

**Example from Operation History**:
```
39  PUSH  Completed     B:/anotherdir  user1  26m ago  (phantom - wrong source!)
38  PUSH  Rolled Back   A:/anotherdir  user1  26m ago
37  PUSH  Completed     A:/anotherdir  user2  26m ago
```

**Root Causes**:
1. **Auto-Rollback Bug**: When user1's operation failed (because user2 already moved the directory), auto-rollback kicked in and called `_get_rollback_type(OperationType.PUSH)`. Since PUSH wasn't in the rollback map, it returned PUSH as the rollback type (wrong!). This created a phantom PUSH operation with `source_path=B:/anotherdir` (from the failed operation's dest_path).
2. **Shared Lock Failure**: Path locks were stored in instance variable `self._operation_locks`, but each API request creates a new OperationService instance. This meant locks weren't shared across requests, defeating their purpose entirely.
3. **Lock Timing**: Path lock was acquired inside `execute_operation()` after the operation was already created in the database. Both users could create operations before either acquired the lock, leading to race conditions.
4. **No Existence Check**: PUSH operations didn't verify the source directory still existed before executing, so concurrent operations could attempt to push directories that were already moved/deleted by another user.

**Fixes Applied**:
1. **Disable Auto-Rollback for PUSH/PULL** (operation_service.py:240):
   - Added condition: `operation.type not in (OperationType.PUSH, OperationType.PULL)`
   - PUSH/PULL have their own undo mechanism (PULL reverts PUSH), so auto-rollback is inappropriate and creates phantom operations

2. **Global Lock Dictionary** (operation_service.py:36-38):
   - Moved `_operation_locks` from instance variable to module-level global: `_operation_locks: dict[str, asyncio.Lock] = {}`
   - Updated `_get_path_lock()` to use global dictionary (line 575-576)
   - Ensures locks are shared across ALL OperationService instances and requests

3. **Early Lock Acquisition** (app.py:579, 659):
   - Moved path lock acquisition to API endpoint level, BEFORE creating operations
   - PUSH endpoint: `async with operation_service._get_path_lock(request_data.source_path)`
   - PULL endpoint: `async with operation_service._get_path_lock(original_op.original_path)`
   - Entire create+execute flow is now atomic for a given path

4. **Source Directory Verification** (operation_service.py:788-804):
   - Added existence check in `_execute_push_operation()` before proceeding
   - Uses worker `list` command to verify directory exists and is accessible
   - Provides clear error message: "Source directory does not exist or is not accessible. It may have been moved or deleted by another operation."
   - Prevents attempting operations on non-existent paths

**Files Modified**:
- `backend/api/services/operation_service.py` (lines 36-38, 240, 575-576, 788-804)
- `backend/api/app.py` (lines 579, 648-659)

**Result**: ✅ No more phantom operations; ✅ Concurrent operations properly serialized; ✅ Clear error messages when conflicts occur; ✅ Operations marked as FAILED (not ROLLED_BACK with phantom operations)

**Design Notes**: KISS approach - global lock dictionary, early lock acquisition, simple existence check; DRY - reusable global lock mechanism applies to all operation types; Proper error handling - failed operations stay FAILED without creating phantom rollback operations

### 2026-02-04 - Fix Path A Pane Race Condition (Auto-Refresh Interruption)
**Issue**: Users unable to complete typing in Path A address bar; navigation gets reset during auto-refresh; search results cleared by refresh
**Root Cause**:
  - Auto-refresh runs every 5 seconds, calling `refreshPane('a')` unconditionally
  - `loadDirectory()` updates path input field via `setCurrentPath()`, erasing user's typing
  - Multiple navigation/search operations could race with auto-refresh, causing:
    - Path input value reset while user is typing
    - Search results cleared mid-browse
    - Navigation interrupted if auto-refresh triggers during directory load
**Fix Applied**:
  - Added `shouldSkipAutoRefresh()` function to detect user interaction before auto-refresh
  - Checks multiple conditions to prevent refresh interruption:
    1. **Navigation in progress**: `state.panes[paneId].isLoading` flag set during `loadDirectory()` and `handleSearch()`
    2. **Path input has focus**: User is actively typing in address bar
    3. **Recent input**: Skip refresh for 2 seconds after last keystroke
    4. **Search input has focus**: User is typing search query
  - Updated `loadDirectory()` and `handleSearch()` to set/clear `isLoading` flag in try/finally blocks
  - Added event listeners to path input to track typing activity (`input`, `focus`, `blur` events)
  - Added `userInteraction` state tracking to record last input timestamp
**Files Modified**:
  - `frontend/js/app.js`:
    - Lines 62-109: Added `isLoading` flags to pane state, added `userInteraction` tracking
    - Lines 186-245: Modified `startAutoRefresh()` to check conditions, added `shouldSkipAutoRefresh()`
    - Lines 330-364: Added input event listeners in `setupPaneControls()`
    - Lines 521-588: Added `isLoading` flag management in `loadDirectory()` (set at start, cleared in finally)
    - Lines 714-754: Added `isLoading` flag management in `handleSearch()` (set at start, cleared in finally)
**Result**: ✅ Users can complete typing without interruption; ✅ Navigation never gets reset; ✅ Search results remain stable during browsing
**Design Notes**: KISS approach - simple boolean flags and focus detection; DRY - reusable `shouldSkipAutoRefresh()` function; graceful degradation - auto-refresh resumes immediately after user interaction ends

### 2026-02-04 - Fix %appdata% Path Crash (Missing Logger Import)
**Issue**: When users typed `%appdata%` (or any other path that caused exceptions) into Path A address bar, the app returned 503 Service Unavailable with NameError
**Root Cause**:
  - `logger` was used in `backend/api/app.py` at lines 219, 247, and 258 but was never imported
  - When exceptions occurred in `list_directory()`, the exception handler tried to call `logger.error()` which failed with `NameError: name 'logger' is not defined`
  - This secondary error masked the original exception, making debugging difficult
**Fix Applied**:
  - Added `from loguru import logger` import to `backend/api/app.py` line 16
**Files Modified**:
  - `backend/api/app.py` (added import at line 16)
**Result**: ✅ Exception logging now works properly; ✅ Errors are logged with full context instead of crashing

### 2026-02-04 - Path A Restrictions & Single Selection UI
**Issues**:
  1. Users could enter invalid paths (B:, C:) in Path A pane, breaking the single-path design
  2. Multi-select checkboxes in file list didn't match VF redesign requirement (single selection only)
  3. Address bar needed to reflect current directory when navigating

**Root Causes**:
  1. **Path Validation**: No validation on API or UI to prevent absolute paths like B:, C: in Path A operations
  2. **Multi-Select**: Checkboxes allowed selecting multiple files, contradicting VF redesign single-directory operation model
  3. **Address Bar**: Already working correctly via `setCurrentPath()` in `loadDirectory()`

**Fixes Applied**:
  1. **Backend - Path Validation**: Added `validate_path_a()` function to validate all Path A operations
     - Rejects paths not starting with "A:"
     - Detects and blocks other drive letters (B:, C:, etc.) anywhere in path
     - Applied to: `/api/files/list`, `/api/files/search`, `/api/operations/push`
  2. **Frontend - Path Validation**: Added `validatePathA()` in `app.js` with same validation logic
     - Shows error toast if invalid path entered
     - Prevents API call for invalid paths
  3. **UI - Single Selection**: Converted file list from checkboxes to radio buttons
     - Removed "Select All" checkbox from table header
     - Changed `createFileRow()` to use radio buttons with shared name attribute
     - Updated `getSelectedFiles()` to return array with single item (backward compatible)
     - Updated `clearSelection()` to work with radio buttons
     - Changed event listener from checkbox to radio in `setupVFRedesignControls()`
  4. **Address Bar**: Confirmed already working - `setCurrentPath()` called in `loadDirectory()` updates input on navigation

**Files Modified**:
  - Backend: `backend/api/app.py` (added validate_path_a function, lines 134-166; applied to list/search/push endpoints)
  - Frontend: `frontend/js/app.js` (added validatePathA function, lines 445-468; updated loadDirectory, line 475-485; fixed radio event handler, line 1236)
  - Frontend: `frontend/js/ui.js` (converted to radio buttons in createFileRow, renderFileList, getSelectedFiles, clearSelection; lines 14-56, 73-179, 221-234, 240-246)
  - Frontend: `frontend/pages/explorer.html` (removed checkboxes from table headers, lines 53, 115)

**Result**: ✅ Path A restricted to relative paths only; ✅ Single-selection radio buttons replace multi-select checkboxes; ✅ Address bar updates on navigation (already working)

**Design Notes**: Changes follow KISS principle - validation in both backend (security) and frontend (UX), minimal changes to existing code, backward-compatible API

### 2026-02-04 - Fix File Manager API 503 Error (Nested error_details)
**Issue**: After recent changes, file listing (Path A pane) stopped working completely - returned 503 Service Unavailable error
**Root Cause**:
  - Previous commit changed `worker_service.py` to pass entire `response_data` as `error_details`
  - However, `worker.py` wraps worker's error_details inside a `response_dict`, creating nested structure:
    ```json
    {
      "file_count": 10,
      "total_size_bytes": 0,
      "error_details": {
        "items": [...],
        "total": 10
      }
    }
    ```
  - App.py expected `error_details["items"]` but actual structure was `error_details["error_details"]["items"]`
**Fixes Applied**:
  1. **Backend - List Directory**: Updated to handle both nested and flat error_details structures for backward compatibility
  2. **Backend - Search Files**: Applied same fix to search endpoint
  3. **Backend - Error Logging**: Added proper error logging to diagnose 503 errors instead of generic exceptions
**Files Modified**:
  - `backend/api/app.py` (lines 156-183 for list, 283-313 for search, 212-214 for error logging)
**Result**: ✅ File listing works again; ✅ Search works with nested structure; ✅ Better error visibility

### 2026-02-04 - Fix Search 503 Error and Layout Adjustment
**Issues**:
  1. Search in Path A pane returned 503 Service Unavailable error
  2. Layout not evenly distributed between Path A and Operation History panels

**Root Causes**:
  1. **503 Error**: Worker service was correctly returning search results in `response_data`, but `worker_service.py` was trying to extract nested `"error_details"` key that didn't exist
  2. **Layout Issue**: CSS grid was set to 60% Path A / 35% Operation History instead of 50/50

**Fixes Applied**:
  1. **Backend - Search Response**: Fixed `worker_service.py` line 128 to pass entire `response_data` as `error_details` instead of trying to extract nested key
     - Previously: `error_details=completed_command.response_data.get("error_details")`
     - Now: `error_details=completed_command.response_data`
  2. **Frontend - Layout**: Adjusted CSS grid columns from `60% 5% 35%` to `47.5% 5% 47.5%` for equal distribution
     - Updated both default and responsive (1400px) breakpoints

**Files Modified**:
  - `backend/api/services/worker_service.py` (line 128)
  - `frontend/css/style.css` (lines 1305, 1636)

**Result**: ✅ Search now returns results properly; ✅ Path A and Operation History panels are equal size (50/50)

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
