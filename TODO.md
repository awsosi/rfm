# TODO - RFM (Remote File Manager)

> **Project:** File operation management system with microservices architecture
> **Status:** Active Development
> **Last Updated:** 2026-02-06

---

## ACTIVE BUGS

### Worker: PathC not saved during registration
**Root cause:** `WorkerRegister` schema (`schemas.py:109`) only accepts `path_a_prefix` and `path_b_prefix` — no `path_c_prefix` field. The `register_worker` endpoint (`app.py:960`) never stores `path_c_prefix` when creating a Worker. Even if the C# worker sends it, Pydantic silently strips it.
**Fix:** Add `path_c_prefix: Optional[str] = Field(None, max_length=500)` to `WorkerRegister` schema, and add `path_c_prefix=worker_data.path_c_prefix` to both the `Worker()` constructor (line 960) and the existing-worker update block (line 949).

### Worker: Remove button not working in Admin Panel
**Root cause (was):** The old inline script in `admin.html` attached event listeners to `.remove-worker-btn` — should have worked but may have been failing silently (e.g. `apiRequest` throwing, or worker names with special chars breaking HTML attributes).
**Status:** Likely fixed by admin.html DRY refactor (uses `escapeHtml` on names, cleaner error handling). **Needs verification.**

### Worker: No Suspend/Activate buttons in Workers tab
**Root cause (was):** The old inline script rendered only a "Remove" button — no Suspend or Activate. Backend endpoints exist: `POST /workers/{id}/suspend` and `PUT /workers/{id}` with `{status: "ACTIVE"}`.
**Status:** Fixed in admin.js refactor — rows now show "Suspend" for ACTIVE workers, "Activate" for SUSPENDED.

---

## ACTIVE TODO ITEMS

### Verification Needed
- [ ] Verify Admin Panel after DRY refactor (all tabs: Users, Workers, Config, System, Logs)
- [ ] Verify worker Remove button works after refactor
- [ ] Verify worker Suspend/Activate buttons work

### Future Work
- [ ] Fix worker PathC registration (see bug details above)
- [ ] Worker: Integration testing of C# FileManagerWorker in staging (ops/deployment — push/pull round-trip)
- [ ] Consider migrating to a component framework (React/Vue) for better DOM/JS sync and type safety — long-term

---

## COMPLETED (Compact Log)

### 2026-02-06 - Admin Panel DRY Refactor
- Moved ~600 lines of inline `<script>` from `admin.html` into `admin.js` as single source of truth
- `admin.html` now has 3-line bootstrap: `import { initAdminPanel }; initAdminPanel();`
- Removed unused `AdminPanel` class (never instantiated, caused confusion with duplicate logic)
- Added Suspend/Activate buttons to worker table rows
- Fixed `editUser()` to actually load user data from API (inline version had stub comment)
- Export log now uses JSON format via audit stream API

### 2026-02-06 - Cleanup Settings and Login Screen
- Removed unused "File Listing" settings (Sort By, Sort Order, Items Per Page) — stored but never applied
- Removed "Show hidden files" toggle — stored in DB but never used in file listing API
- Cleaned up: `explorer.html`, `app.js`, `models.py`, `schemas.py`, `preferences.py`
- Removed columns from migration 002 (clean schema from the start)
- Login screen: moved Auth Method below Remember Me, shortened labels to "PolkaSQL"/"Local"
- Login screen: removed Sybase description text and "Remote File Manager v1.0" footer

### 2026-02-05 - Admin Panel Freeze Fix + Theme Fix
- Fixed admin.js crash: missing `showNotification` export in utils.js
- Fixed theme switcher: added `body[data-theme="dark"]` CSS variables
- Added System theme, language selection, Path A remembering

### 2026-02-05 - PolkaSQL Auth Fixes (3 rounds)
- Fixed config key mismatch, Admin Panel fieldMapping, duplicate config loading (DRY)
- Fixed login failure when PolkaSQL disabled, added missing imports in auth.py

### 2026-02-05 - Remote Authentication (PolkaSQL) Implementation
- Full remote auth, auto-user-creation, dual config, auth method selector, Admin Panel UI

### 2026-02-04 - Admin Panel Fixes
- Fixed missing audit logs (element ID mismatch), enhanced system logs table
