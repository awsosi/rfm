# TODO - RFM (Remote File Manager)

> **Projekt:** System zarządzania operacjami plikowymi z architekturą mikroserwisową
>
> **Status:** REDESIGN - VF Branch - Complete Application Makeover
>
> **Ostatnia aktualizacja:** 2026-01-28

---

## 🚨 REDESIGN PLAN - VF BRANCH (IN PROGRESS)

### Overview
Complete application makeover with simplified UI and new operation flow:
- **Single pane (Path A) + Operation Queue** layout
- **Directory-only operations** (no single file selections)
- **Single worker architecture** (simplified from multi-worker)
- **Push/Pull operations** with automatic archiving
- **Persistent operation history** with real-time status

### New Operation Flow
1. **User selects directory** in Path A pane
2. **Clicks Push >** button
3. **System copies** directory from Path A to preset Path B (admin-configured)
4. **System archives** original directory from Path A to preset Path C (admin-configured)
5. **Everything logged** with full audit trail
6. **Operation appears** in Operation Queue with real-time status
7. **Operation persists** indefinitely in history
8. **< Pull button** allows any authenticated user to revert (copy from Path B to original location, remove from Path B)

---

## 📋 REDESIGN TASKS - VF BRANCH

### ✅ Phase 0: Planning & Exploration
- ✅ Explore codebase structure
- ✅ Understand current architecture
- ✅ Create redesign TODO

### 🚧 Phase 1: Backend - Models & Database
- 📝 **Update models.py**
  - Add PUSH and PULL to OperationType enum
  - Add original_path field to Operation model (to track source for Pull)
  - Ensure operations are never deleted (only marked as complete/failed)
  - Add archive_path field to Operation model
- 📝 **Create database migration (004_redesign_vf.py)**
  - Add new operation types (PUSH, PULL)
  - Add original_path column to operations table
  - Add archive_path column to operations table
- 📝 **Update config.py**
  - Add PATH_B setting (destination path)
  - Add PATH_C setting (archive path)
  - Both should be overridable by admin settings

### 🚧 Phase 2: Backend - Business Logic
- 📝 **Create operation_service_v2.py** (or update existing)
  - Implement create_push_operation(user_id, source_dir, worker_id)
    - Validate source is a directory
    - Get PATH_B and PATH_C from config
    - Create operation record with PUSH type
    - Execute: copy source_dir to PATH_B, move source_dir to PATH_C
    - Track both operations (copy + archive)
    - Real-time status updates via WebSocket
  - Implement create_pull_operation(user_id, operation_id)
    - Get original operation details
    - Validate operation exists and is PUSH type
    - Create new operation record with PULL type
    - Execute: copy from PATH_B to original_path, delete from PATH_B
    - Link Pull operation to original Push operation
- 📝 **Update worker_service.py**
  - Add support for PUSH command (copy + move)
  - Add support for PULL command (copy + delete)
  - Ensure single worker handles all operations
  - Remove multi-worker logic

### 🚧 Phase 3: Backend - API Endpoints
- 📝 **Update app.py or create routes/operations.py**
  - POST /api/operations/push
    - Request: { source_path: string (directory only) }
    - Response: { operation_id, status, message }
  - POST /api/operations/pull
    - Request: { operation_id: string }
    - Response: { operation_id, status, message }
  - GET /api/operations/history
    - Return all operations (paginated)
    - Include: id, type, status, username, timestamp, paths
    - Filter by user, type, status, date range
  - GET /api/operations/{id}/status
    - Real-time operation status
- 📝 **Update admin endpoints**
  - Add PATH_B and PATH_C to admin config management
  - Restrict PATH_B/PATH_C changes to admin users only

### 🚧 Phase 4: Backend - Worker Updates
- 📝 **Update workers/FileManagerWorker/CommandHandler.cs**
  - Add 'push' command handler
    - Copy directory recursively
    - Move original directory to archive location
    - Return detailed status (files copied, size, errors)
  - Add 'pull' command handler
    - Copy directory from PATH_B to original location
    - Delete directory from PATH_B
    - Return detailed status
- 📝 **Update workers/FileManagerWorker/FileOperations.cs**
  - Ensure directory-only validation
  - Add archive operation support
  - Improve error handling for multi-step operations

### 🚧 Phase 5: Frontend - HTML Structure
- 📝 **Update frontend/pages/explorer.html**
  - Remove Path B pane (entire right side)
  - Keep Path A pane (left side, expand to ~40% width)
  - Add Operation Queue section (right side, ~55% width)
  - Add button container in the middle (~5% width)
  - Remove ALL existing operation buttons (copy, move, delete, mkdir)
  - Add only:
    - Button: "Push >" (top)
    - Button: "< Pull" (below Push)
  - Update Operation Queue section:
    - Table with columns: ID, Type, Status, Directory, User, Timestamp, Actions
    - Real-time status indicators (pending, in_progress, completed, failed)
    - Color coding for statuses
    - Expandable details for each operation

### 🚧 Phase 6: Frontend - CSS Styling
- 📝 **Update frontend/css/style.css**
  - New layout: .pane-a (40%) | .button-container (5%) | .operation-queue (55%)
  - Center button container vertically
  - Style Push > button (primary action, blue/green)
  - Style < Pull button (secondary action, orange/yellow)
  - Disable buttons when invalid selection
  - Style operation queue table (modern, clean)
  - Status indicators (colors, icons, animations)
  - Responsive design adjustments

### 🚧 Phase 7: Frontend - JavaScript
- 📝 **Update frontend/js/app.js**
  - Remove pane B state management
  - Add operation history state
  - Implement Push operation flow:
    - Validate directory selection
    - Show confirmation dialog
    - Call POST /api/operations/push
    - Update UI with operation status
  - Implement Pull operation flow:
    - Get selected operation from queue
    - Show confirmation dialog
    - Call POST /api/operations/pull
    - Update UI with operation status
  - Add WebSocket listener for operation updates
  - Auto-refresh operation queue on updates
- 📝 **Update frontend/js/ui.js**
  - Remove Path B rendering functions
  - Add renderOperationQueue() function
  - Add renderOperationStatus() function
  - Add updateOperationInQueue() function
  - Implement directory-only selection in file list
  - Disable file selection (only directories)
  - Update button states based on selection
- 📝 **Update frontend/js/api.js**
  - Add pushOperation(sourcePath) function
  - Add pullOperation(operationId) function
  - Add getOperationHistory(filters) function
  - Add getOperationStatus(operationId) function
  - Update WebSocket topic subscriptions

### 🚧 Phase 8: Frontend - Admin Panel
- 📝 **Update frontend/pages/admin.html**
  - Add PATH_B configuration field (admin only)
  - Add PATH_C configuration field (admin only)
  - Show warning that changing paths affects new operations only
- 📝 **Update frontend/js/admin-system.js**
  - Add PATH_B and PATH_C to configuration management
  - Validate paths before saving
  - Show confirmation dialog for path changes

### 🚧 Phase 9: Configuration & Environment
- 📝 **Update backend/.env.example**
  - Add PATH_B=/path/to/destination (default destination for Push)
  - Add PATH_C=/path/to/archive (default archive location)
- 📝 **Update root .env.example**
  - Document PATH_B and PATH_C variables

### 🚧 Phase 10: Testing & Validation
- 📝 **Test Push operation**
  - Select directory in Path A
  - Click Push >
  - Verify directory copied to PATH_B
  - Verify directory moved to PATH_C
  - Verify operation appears in queue
  - Verify real-time status updates
- 📝 **Test Pull operation**
  - Select completed Push operation
  - Click < Pull
  - Verify directory copied from PATH_B to original location
  - Verify directory removed from PATH_B
  - Verify operation appears in queue
- 📝 **Test edge cases**
  - Invalid directory selection
  - Missing PATH_B or PATH_C configuration
  - Insufficient permissions
  - Network errors
  - Worker offline
- 📝 **Test admin configuration**
  - Change PATH_B and PATH_C as admin
  - Verify new operations use new paths
  - Verify non-admin users cannot change paths

### 🚧 Phase 11: Documentation
- 📝 **Update README.md**
  - Document new operation flow
  - Document Push/Pull operations
  - Document PATH_B and PATH_C configuration
- 📝 **Update TODO.md** (this file)
  - Mark completed tasks
  - Add any new issues discovered

### 🚧 Phase 12: Deployment
- 📝 **Run database migration**
  - alembic upgrade head
- 📝 **Update worker installations**
  - Deploy new worker version with Push/Pull support
- 📝 **Test in staging environment**
- 📝 **Commit all changes**
- 📝 **Push to vf branch**
- 📝 **Create pull request** (if needed)

---

## 🎯 Key Design Principles for Redesign

### KISS (Keep It Simple, Stupid)
- ✅ Single pane instead of dual-pane (simpler mental model)
- ✅ Only 2 buttons instead of 6+ buttons
- ✅ Directory-only operations (no file selection complexity)
- ✅ Single worker (no multi-worker coordination complexity)
- ✅ Preset destinations (no user path selection)

### DRY (Don't Repeat Yourself)
- ✅ Reuse existing operation framework
- ✅ Reuse WebSocket infrastructure
- ✅ Reuse authentication/authorization
- ✅ Reuse audit logging

### Security First
- ✅ Admin-only PATH_B and PATH_C configuration
- ✅ Validate all directory paths
- ✅ Prevent path traversal attacks
- ✅ Full audit trail for all operations
- ✅ Any authenticated user can Pull (revert)

### User Experience
- ✅ Clear, simple UI with minimal cognitive load
- ✅ Real-time operation status (no guessing)
- ✅ Persistent history (never lose track)
- ✅ Easy revert with Pull operation
- ✅ Clear status indicators and timestamps

---

## 📊 Progress Tracker

| Phase | Status | Completion |
|-------|--------|------------|
| Phase 0: Planning | ✅ | 100% |
| Phase 1: Backend Models | 📝 | 0% |
| Phase 2: Backend Logic | 📝 | 0% |
| Phase 3: Backend API | 📝 | 0% |
| Phase 4: Worker Updates | 📝 | 0% |
| Phase 5: Frontend HTML | 📝 | 0% |
| Phase 6: Frontend CSS | 📝 | 0% |
| Phase 7: Frontend JS | 📝 | 0% |
| Phase 8: Admin Panel | 📝 | 0% |
| Phase 9: Configuration | 📝 | 0% |
| Phase 10: Testing | 📝 | 0% |
| Phase 11: Documentation | 📝 | 0% |
| Phase 12: Deployment | 📝 | 0% |

**Overall Progress: 8% (1/12 phases complete)**

---

## 📋 Original TODO (Pre-Redesign) - Archived

<details>
<summary>Click to expand original TODO items (for reference)</summary>

### Moduły Główne (Original)
| Moduł | Status | Kompletność | Priorytet |
|-------|--------|-------------|-----------|
| **Autentykacja & Autoryzacja** | ✅ | 95% | Wysoki |
| **Panel Administracyjny** | ✅ | 95% | Wysoki |
| **Operacje Plikowe** | 🔄 | 90% → REDESIGNED | Wysoki |
| **Worker Management** | 🔄 | 85% → SIMPLIFIED | Wysoki |
| **WebSocket Real-time** | ✅ | 90% | Średni |

### Notes on Original Features
- Dual-pane explorer → REMOVED (single pane now)
- Multi-worker coordination → REMOVED (single worker now)
- File-level operations → REMOVED (directories only now)
- Manual path selection → REMOVED (preset paths now)

</details>

---

## 🔥 Critical Notes

### IMPORTANT: Single Worker Architecture
- All operations must go through ONE worker
- Remove any multi-worker selection logic
- Simplify operation routing
- Ensure worker is properly configured with PATH_B and PATH_C access

### IMPORTANT: Directory-Only Operations
- No single file selection allowed
- UI must disable file selection
- Backend must validate directory-only
- Error messages for invalid selections

### IMPORTANT: PATH_B and PATH_C Security
- Only settable via .env OR admin users
- Regular users CANNOT change these paths
- Validate paths exist and are accessible
- Prevent path traversal attacks

### IMPORTANT: Operation History
- Operations NEVER deleted
- Keep full history indefinitely
- Pagination for performance
- Filters for usability (user, type, status, date)

---

## 📞 Questions/Clarifications Needed

- ❓ Should PATH_B and PATH_C be per-worker or global? (Assuming global for now)
- ❓ Should we support subdirectory creation in PATH_B (e.g., /path/b/username/dirname)? (Assuming flat structure for now)
- ❓ Archive PATH_C: should it preserve directory structure or flatten? (Assuming preserve structure)
- ❓ Pull operation: should it delete from PATH_C as well? (Assuming no - archive remains)
- ❓ Should regular users see all operations or only their own? (Assuming all for transparency)

---

**Last Updated:** 2026-01-28
**Branch:** vf
**Status:** In Progress - Phase 1 starting

---

*KISS principle: Make it simple. Make it work. Make it maintainable.*
