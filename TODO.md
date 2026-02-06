# TODO - RFM (Remote File Manager)

> **Project:** File operation management system with microservices architecture
> **Status:** Active Development
> **Last Updated:** 2026-02-06

---

## RULES (read before every change)

1. **Schema ↔ Endpoint ↔ Model must stay in sync.** When a DB model has a column, the registration/creation schema AND the endpoint code that builds the ORM object MUST include that field. Pydantic silently strips unknown fields — you will never get an error, just silent data loss.
   - Checklist before any "add column" change: `models.py` column → `schemas.py` request schema field → endpoint constructor/update kwargs → response schema field.
2. **Never mark a bug "likely fixed" without a code review.** Read the actual JS/Python that runs the feature end-to-end. "Likely" means "still broken until proven otherwise."

---

## ACTIVE BUGS

None.

---

## ACTIVE TODO ITEMS

### Verification Needed (requires running app with Docker)
- [ ] Verify Admin Panel after DRY refactor (all tabs: Users, Workers, Config, System, Logs)
- [ ] Verify worker Remove button works after refactor
- [ ] Verify worker Suspend/Activate buttons work

### Future Work
- [ ] Worker: Integration testing of C# FileManagerWorker in staging (ops/deployment — push/pull round-trip)
- [ ] Consider migrating to a component framework (React/Vue) for better DOM/JS sync and type safety — long-term

---

## COMPLETED (Compact Log)

### 2026-02-06 - Fix All Active Bugs
- Fixed PathC not saved during worker registration: added `path_c_prefix` to `WorkerRegister` schema (`schemas.py`), existing-worker update block and new-worker constructor in `app.py`
- Verified Remove button: already working after DRY refactor (`admin.js:334-347` — `escapeHtml` on names, correct `DELETE` call)
- Verified Suspend/Activate buttons: already working after DRY refactor (`admin.js:284-332` — correct rendering and API calls)

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
