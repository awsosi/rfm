# TODO - RFM (Remote File Manager)

> **Project:** File operation management system with microservices architecture
> **Status:** Active Development
> **Last Updated:** 2026-02-07 (Redis health check restored)

---

## RULES (read before every change)

1. **Schema ↔ Endpoint ↔ Model must stay in sync.** When a DB model has a column, the registration/creation schema AND the endpoint code that builds the ORM object MUST include that field. Pydantic silently strips unknown fields — you will never get an error, just silent data loss.
   - Checklist before any "add column" change: `models.py` column → `schemas.py` request schema field → endpoint constructor/update kwargs → response schema field.
2. **Never mark a bug "likely fixed" without a code review.** Read the actual JS/Python that runs the feature end-to-end. "Likely" means "still broken until proven otherwise."
3. **Migrations are consolidated.** There is a single `001_initial_schema.py`. When adding new schema changes during pre-production, merge them into `001` instead of creating numbered follow-ups. Once the app goes to production, switch to incremental migrations.
4. **Every field the client sends must appear in the serialization payload.** When a C# worker (or any client) registers/updates via an API endpoint, every field in the Pydantic schema MUST be present in the JSON payload the client builds. A field that exists in the schema but is missing from the client payload will silently default to `None` — the server won't error, it will just store NULL. **Always diff the client-side JSON object against the Pydantic schema field-by-field.**
   - Checklist: `schemas.py` WorkerRegister fields → C# `registrationData` anonymous object properties → verify 1:1 match.
5. **Single source of truth for config: DB at runtime, env on startup.** Environment variables (`.env` → docker-compose → container env) are synced INTO the DB `config` table on every API startup (`_sync_env_config_to_db`). Runtime code reads ONLY from DB. Never add fallback-to-env logic in request handlers — that creates a dual-source-of-truth bug where DB and env can disagree silently.
   - If you need a new env-driven config: add it to `_sync_env_config_to_db()` in `app.py`, seed it in the migration, and read it from DB in handlers.
6. **Alembic `ON CONFLICT DO NOTHING` means "seed once, never update."** The migration's config seed only runs on first deployment. Changing `.env` values after that won't update the DB through the migration alone — that's why `_sync_env_config_to_db()` exists. Never rely on the migration to propagate env changes on re-deployment.
7. **Python async extras: always install `[async]` (or equivalent) when using async clients.**
   When a Python library offers async support via an extras group (e.g. `elasticsearch[async]`, `redis[hiredis]`, `httpx[http2]`), you MUST install the extra — not the bare package. The bare package lets you *import* the async class without error, but the class silently fails at runtime because its async HTTP transport dependency (e.g. `aiohttp`) is missing. The exception gets swallowed by generic `except Exception` handlers, and the service appears permanently broken with zero useful error messages.
   - **Checklist:** For every `pip install <package>` that will be used with `async`/`await`, verify that the correct extras group is specified in `requirements.txt`. Search the code for `Async` class names (e.g. `AsyncElasticsearch`, `AsyncClient`) and confirm the extras are installed.
   - **This bug is invisible at import time.** The import succeeds. The error only appears at runtime when the transport tries to load the missing dependency. Combined with a broad `except Exception` handler, the root cause is completely hidden.
8. **Env var names must match the project's naming convention — or accept both.**
   Most boolean toggles in this project use `ENABLE_*` prefix (`ENABLE_SYSLOG`, `ENABLE_REMOTE_AUDIT_API`, `ENABLE_JSON_LOGS`). If a new toggle uses a *different* pattern (e.g. `POLKA_AUTH_ENABLED` — suffix instead of prefix), users WILL type the wrong name (`ENABLE_POLKA_AUTH`) because that matches every other toggle they see. Pydantic's `extra="ignore"` silently drops unrecognized env vars, and docker-compose's `${VAR:-default}` silently falls back to the default. **Result: the user sets the value, everything looks correct, but the app ignores it with zero errors.**
   - **Prevention:** When adding a boolean env var, always use the `ENABLE_*` prefix convention. If you inherit a name that doesn't match, add `validation_alias=AliasChoices(...)` in the Settings field so BOTH names work. Also update docker-compose substitution to check both: `${ENABLE_X:-${X_ENABLED:-false}}`.
   - **This bug is invisible** — no error, no warning, no log. The only symptom is "the setting doesn't work." Always grep `.env.example` for naming consistency when adding new toggles.
9. **Frontend-backend data format alignment: Pydantic validation patterns must match HTML form values exactly.**
   When HTML forms send data to API endpoints validated by Pydantic schemas, the frontend values and backend regex patterns MUST align. If they don't, the API returns 422 "Unprocessable Content" but the frontend may not surface this clearly — user sees generic "Failed to save" with no hint that it's a validation mismatch. Example: HTML `<select>` with `<option value="en-US">` sending "en-US", but Pydantic field has `pattern="^[a-z]{2}$"` expecting only 2 letters → instant 422, zero indication of why.
   - **Prevention checklist when adding a new user-facing setting:**
     1. Look at the HTML `<select>`, `<input>`, or JS code that builds the request payload. Note the exact string format sent (e.g. "auto", "en-US", "pl-PL").
     2. Find the Pydantic schema field in `schemas.py`. If it has a `pattern=` constraint, verify the regex accepts ALL valid values from step 1.
     3. Check database model default in `models.py` and migration `server_default=` — ensure they match a valid frontend value (not a legacy placeholder like "en" when frontend expects "auto" or "en-US").
     4. Check endpoint reset-to-defaults code (e.g. `preferences.py` reset handler) — hardcoded defaults must also match frontend expectations.
     5. If the field format changes (e.g. from 2-letter codes "en" to full locale codes "en-US"), update ALL four places in one commit: HTML, schema pattern, model default, migration default.
   - **Test before commit:** Use browser DevTools Network tab → look at request payload → confirm it matches the backend pattern. A single typo in the regex breaks the entire feature silently (users can't save, no useful error).

---

## ACTIVE BUGS

None.

---

## ACTIVE TODO ITEMS

### Verification Needed (requires running app with Docker)
- [x] **Rebuild Docker image** after `elasticsearch[async]` fix, verify Elasticsearch shows "Connected" in System Health
- [x] Verify syslog persists across restart (enabled in DB → `_reconfigure_logging_from_db()` picks it up)
- [x] Verify Logging Configuration in Logs tab: load, save, syslog runtime reconfiguration
- [x] Verify Audit Log Viewer: filter, pagination, export
- [x] Verify removed sections (Logging & Audit, Global Path Prefixes, VF Redesign) no longer appear in Configuration tab
- [x] Verify Admin Panel overhaul: theme, user CRUD, PolkaSQL badge, worker control buttons, system stats real-time
- [x] Worker: Integration testing of C# FileManagerWorker in staging

### Future Work
- [ ] Verify remote syslog: enable via Logs tab config, perform an action, confirm messages arrive at syslog server
- [ ] Consider migrating to a component framework (React/Vue) — long-term

---

## COMPLETED (Compact Log)

### 2026-02-07 - Fix i18n validation pattern mismatch (frontend-backend misalignment)
- **Bug:** i18n implementation failed completely. Settings → Language dropdown was empty. Selecting any language (System/English/Polish) → "Failed to save: ui_language: String should match pattern '^[a-z]{2}'" + 422 Unprocessable Content. Console error: "Failed to load locale en, falling back to en-US: SyntaxError: Unexpected token '<', '<!DOCTYPE'..." (server returned HTML 404 page when trying to load non-existent locale file).
- **Root cause:** Backend validation pattern in `schemas.py` was `^[a-z]{2}$` (2 lowercase letters like "en", "pl"), but frontend HTML sent "auto", "en-US", "pl-PL" → all rejected. Also: model default was "en" instead of "auto", migration default was "en", preferences reset hardcoded "en" → four places with wrong/inconsistent defaults.
- **Fix:**
  - **Backend:** Updated validation pattern to `^(auto|[a-z]{2}(-[A-Z]{2})?)$` to accept "auto", short codes ("en", "pl" for backward compat), and full locale codes ("en-US", "pl-PL"). Changed all defaults from "en" → "auto" in: `models.py` (Column default), `001_initial_schema.py` (server_default), `preferences.py` (reset handler).
  - **Frontend:** Added normalization in `app.js` to convert legacy 2-letter codes ("en" → "en-US", "pl" → "pl-PL") when loading preferences into the dropdown, preventing empty selection when DB contains old "en" value.
- **Lesson learned:** Added Rule 9 — Frontend-backend data format alignment checklist. When adding user-facing settings: (1) note exact format sent by HTML/JS, (2) verify Pydantic pattern accepts all values, (3) check model default, (4) check migration default, (5) check endpoint reset code. All must match. Test with DevTools Network tab before commit. A regex typo breaks the feature silently with generic 422 errors.

### 2026-02-07 - Full i18n implementation for user-facing pages
- Implemented internationalization (i18n) system for login page, file explorer, user settings, and all toasts/popups
- Created modular locales system: `locales/locales.json` lists available locales `["en-US", "pl-PL"]`
- Created `locales/en-US.json` with all English translations, `locales/pl-PL.json` as placeholder (user will complete)
- Created `js/i18n.js` module: auto-detects browser language, loads locale files with fallback to en-US, provides `t()` translation function with parameter replacement
- Auto-detection: checks `navigator.languages`, finds exact match or language prefix match (e.g., `pl` matches `pl-PL`), defaults to `en-US`
- User Settings → Language selector: options are "System (Auto)" (default), "English", "Polish"
  - "System (Auto)" follows browser/OS preference
  - Changing language saves to preferences and applies immediately via `setLocale()` which triggers page re-translation
- Updated HTML: all user-visible text uses `data-i18n`, `data-i18n-placeholder`, `data-i18n-title` attributes
- Updated JavaScript: all toast messages, error messages, confirmations use `t()` function
- Settings modal updated: replaced "More languages coming soon (i18n implementation planned)" with "System setting follows your browser/OS preference"
- `translatePage()` scans DOM for i18n attributes and applies translations; re-runs on locale change
- Login page, explorer page, settings modal, context menu, modals all fully internationalized
- Page titles update dynamically when locale changes

### 2026-02-07 - Restore Redis health check to System Health tile
- Redis component was removed from System Health during Admin Panel overhaul (commit 85eecc6) along with other placeholder checks
- Added `_check_redis()` helper in `admin_system.py` — pings Redis via `redis.asyncio` using configured `REDIS_URL` with 3s timeout
- `/api/admin/health` now includes `redis` component (Connected/Connection failed) alongside database, elasticsearch, api, webui
- `/api/admin/stats/system` `redis_healthy` field now uses actual ping instead of hardcoded `True`
- `/health` endpoint now checks Redis (was hardcoded `redis=True` with TODO comment); overall status degrades if Redis is down
- `SystemHealthResponse` schema default components updated to include `redis`
- No frontend changes needed — JS dynamically renders all components from the health response dict

### 2026-02-07 - Fix Elasticsearch "connection failed" (AsyncElasticsearch missing aiohttp)
- **Bug:** System Health shows `⚠ elasticsearch: Enabled but connection failed (will retry)` despite ES container being healthy. Persists indefinitely — retries never succeed.
- **Root cause:** `requirements.txt` had `elasticsearch==8.12.0` (bare package). The code uses `AsyncElasticsearch` which requires `aiohttp` for its async HTTP transport (`AiohttpHttpNode`). Without the `[async]` extras group, `aiohttp` is never installed. `AsyncElasticsearch` *imports* fine, but fails at runtime when trying to create the transport. The error is caught by `except Exception`, `_client` is set to `None`, and every retry fails the same way.
- **Fix:** Changed to `elasticsearch[async]==8.12.0` (installs `aiohttp`). Also fixed resource leak: `initialize()` now closes the ES client on failure before setting it to `None` (previously leaked unclosed `AsyncElasticsearch` instances on each retry).
- **Lesson learned:** Added Rule 8 — always install `[async]` extras for async Python clients. Added checklist to prevent recurrence.

### 2026-02-07 - Fix ES Health + Syslog Delivery (2 changes)
5. **Fix Elasticsearch "Not enabled":** `get_elasticsearch_service()` was a one-shot init — if ES wasn't ready on first call, service stayed failed forever. Added retry: if `elasticsearch_enabled=True` but `_initialized=False`, re-attempt `initialize()` on each `get_elasticsearch_service()` call. Health endpoint now checks `settings.elasticsearch_enabled` first to distinguish "disabled in config" from "enabled but not connected".
6. **Fix remote syslog not receiving messages:** Root cause: `create_audit_log()` wrote only to DB — the logging_module's `SyslogHandler` was never called for auth, admin, config, or user events (only file operations had syslog forwarding). Fix: `create_audit_log()` now forwards every audit event to the logging_module's non-DB handlers (syslog, file, external API), skipping `DatabaseHandler` to avoid duplicate DB entries. Also: added `_reconfigure_logging_from_db()` at startup so syslog config saved via admin UI persists across restarts. Fixed socket timeout (2s UDP, 5s TCP) and socket reset on failure for reconnection.

### 2026-02-07 - Health Fix, Config Cleanup, Log Viewer Overhaul (4 changes)
1. **Fix System Health "Connection failed":** `database.py` `health_check()` used bare string `"SELECT 1"` — SQLAlchemy 2.0 requires `text()` wrapper. Exception was silently caught → returned `False`. Fixed with `text("SELECT 1")`.
2. **Remove config sections:** Removed "Logging & Audit", "Global Path Prefixes", and "VF Redesign: Push/Pull Operation Paths" from Configuration tab (HTML + JS field mappings). Logging config is now exclusively in the Logs tab.
3. **Logging Configuration (Logs tab):** Fully functional load/save. Frontend loads config from `GET /api/admin/logs/config` on tab open, saves via new `PUT /api/admin/logs/config` endpoint. Backend endpoint persists to DB config table and reconfigures syslog handler at runtime (removes old SyslogHandler, creates new one with updated host/port/protocol). Added `LogConfigUpdate` Pydantic schema.
4. **Audit Log Viewer overhaul:** Renamed "Log Viewer" → "Audit Log Viewer". Removed "Audit Logs (Database) / Application Logs (File)" type selector. Removed log level selector. Renamed "Search logs..." → "Filter logs..." and implemented backend `search_query` filter (searches across `action`, `ip_address`, `details_json` via `ILIKE`). Fixed export (was requesting `limit=10000` exceeding API max of 1000 — now fetches in batches of 1000). Replaced "Load More" with proper page-number pagination (50 per page, prev/next, page numbers with ellipsis). Cleaned up dead code from `admin-system.js` (removed duplicate `loadLogs`/`renderLogs`).

### 2026-02-06 - Admin Panel Overhaul (11 fixes/changes)
1. **Theme:** Admin Panel now loads and applies user's theme preference (system/light/dark) from Settings/Display Preferences
2. **Delete user fix:** Added generic modal (`#modal`) to admin.html — `showConfirm()` from utils.js now works (was silently failing because modal DOM elements didn't exist)
3. **Last admin deletion protection:** Frontend disables Delete button for last admin; backend already had protection
4. **PolkaSQL user deactivation:** Removed false blocking — `is_active` changes now pass through for PolkaSQL users (only username/password are blocked)
5. **PolkaSQL credential restriction:** Backend blocks username/password changes for `is_polka_auth` users; frontend disables those fields in edit modal
6. **PolkaSQL auth indication:** Added "Auth" column to User Management table showing "PolkaSQL" or "Local" badge; added `is_polka_auth` to `UserResponse` schema
7. **ADMIN role for PolkaSQL users:** Role dropdown works for all users (no PolkaSQL restriction on role changes)
8. **Last admin role protection:** Backend prevents changing last admin to USER; frontend disables the delete button
9. **Removed Samba Paths Management:** Removed from System tab HTML and admin-system.js; removed `samba_paths_active` from stats schema/endpoint; backend routes still exist but UI is gone
10. **Worker Control moved to Workers tab:** Ping, Status, Provision buttons added as actions in Worker Management table; Reload Config removed (not working); Worker Control section removed from System tab
11. **System Statistics real-time:** Auto-refreshes every 5s when System tab is active; stops when leaving tab. Health endpoint now checks database, elasticsearch, api, webui (removed redis/workers placeholders)

### 2026-02-06 - Fix ENABLE_POLKA_AUTH env var silently ignored
- **Bug:** User sets `ENABLE_POLKA_AUTH=true` in `.env` (following the `ENABLE_*` convention used by every other toggle). Silently ignored because: (1) Pydantic field `polka_auth_enabled` maps to env var `POLKA_AUTH_ENABLED` (suffix, not prefix), (2) docker-compose `${POLKA_AUTH_ENABLED:-false}` doesn't match `ENABLE_POLKA_AUTH`, defaults to `false`, (3) Pydantic `extra="ignore"` drops the unrecognized var with zero warnings.
- **Fix:** Added `validation_alias=AliasChoices('enable_polka_auth', 'polka_auth_enabled')` to Settings field — accepts both env var names. Updated docker-compose to `${ENABLE_POLKA_AUTH:-${POLKA_AUTH_ENABLED:-false}}`. Updated migration seed to check both names. Updated `.env.example` to use `ENABLE_POLKA_AUTH` (consistent convention).
- **Root cause:** Inconsistent naming convention. Added Rule 7 to prevent recurrence.

### 2026-02-06 - Fix env config ignored + worker PathC not sent
- **Bug 1 — POLKA_AUTH_ENABLED in .env ignored after first deploy:** The migration seeds config with `ON CONFLICT DO NOTHING`, so `.env` changes after initial deploy never reached the DB. Auth code had fragile fallback logic (DB false → check env) creating a dual-source-of-truth. **Fix:** Added `_sync_env_config_to_db()` in `app.py` lifespan — syncs `POLKA_AUTH_*` env vars into DB `config` table on every startup. Simplified auth.py to read ONLY from DB (no fallback to env).
- **Bug 2 — Worker Path C ignored from .exe.config / /config wizard:** `ApiClient.cs` `RegisterWorkerAsync()` built the registration JSON with `path_a_prefix` and `path_b_prefix` but **omitted `path_c_prefix`**. Server stored NULL for path_c. **Fix:** Added `path_c_prefix = _config?.PathCPrefix ?? @"C:\PathC"` to registration payload.
- Root cause for both: silent data loss — Pydantic strips missing fields without error, `ON CONFLICT DO NOTHING` silently skips updates.

### 2026-02-06 - Consolidate Alembic Migrations
- Merged 9 numbered migrations (`001`–`009`) into single `001_initial_schema.py`
- Deleted `002_add_user_preferences`, `003_add_admin_models`, `004_vf_redesign_push_pull`, `005_add_worker_command`, `006_add_path_c_prefix`, `007_add_remote_auth`, `008_add_polka_config`, `009_add_ui_language_system_theme`
- Consolidated migration creates all 11 tables, 6 ENUMs, all indexes, system_stats view, updated_at triggers, and config seed data (with env-based PolkaSQL config) in one pass
- No old Sybase config entries — only current PolkaSQL keys seeded from environment
- `ui_theme` default changed from `light` to `system` (matches model)
- DRY: ENUM creation uses loop, trigger creation uses loop

### 2026-02-06 - Fix .env Variables, Bugs, Admin DRY Refactor, Settings Cleanup
- Fixed docker-compose env var passthrough (Sybase→Polka rename), migration 008 seeds from env
- Fixed PathC not saved during worker registration
- Moved ~600 lines of inline admin script to `admin.js`, removed unused AdminPanel class
- Removed unused File Listing settings and "Show hidden files" toggle
- Login screen cleanup (Auth Method placement, removed Sybase text/footer)

### 2026-02-05 - PolkaSQL Auth + Theme System
- Full PolkaSQL remote auth implementation with auto-user-creation
- Fixed config key mismatches, admin panel fieldMapping, duplicate config loading
- Fixed admin.js crash (missing showNotification export), theme switcher, system theme support

### 2026-02-04 - Admin Panel Fixes
- Fixed missing audit logs (element ID mismatch), enhanced system logs table
