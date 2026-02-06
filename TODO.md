# TODO - RFM (Remote File Manager)

> **Project:** File operation management system with microservices architecture
> **Status:** Active Development
> **Last Updated:** 2026-02-06 (admin panel overhaul)

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
7. **Env var names must match the project's naming convention — or accept both.**
   Most boolean toggles in this project use `ENABLE_*` prefix (`ENABLE_SYSLOG`, `ENABLE_REMOTE_AUDIT_API`, `ENABLE_JSON_LOGS`). If a new toggle uses a *different* pattern (e.g. `POLKA_AUTH_ENABLED` — suffix instead of prefix), users WILL type the wrong name (`ENABLE_POLKA_AUTH`) because that matches every other toggle they see. Pydantic's `extra="ignore"` silently drops unrecognized env vars, and docker-compose's `${VAR:-default}` silently falls back to the default. **Result: the user sets the value, everything looks correct, but the app ignores it with zero errors.**
   - **Prevention:** When adding a boolean env var, always use the `ENABLE_*` prefix convention. If you inherit a name that doesn't match, add `validation_alias=AliasChoices(...)` in the Settings field so BOTH names work. Also update docker-compose substitution to check both: `${ENABLE_X:-${X_ENABLED:-false}}`.
   - **This bug is invisible** — no error, no warning, no log. The only symptom is "the setting doesn't work." Always grep `.env.example` for naming consistency when adding new toggles.

---

## ACTIVE BUGS

None.

---

## ACTIVE TODO ITEMS

### Verification Needed (requires running app with Docker)
- [ ] Verify Admin Panel overhaul: theme, user CRUD, PolkaSQL badge, worker control buttons, system stats real-time
- [ ] Verify delete user works (showConfirm modal was missing from admin.html — now added)
- [ ] Verify PolkaSQL users: can change role/active, cannot change username/password
- [ ] Verify last-admin protection: cannot delete, demote, or deactivate the sole admin
- [ ] Verify worker Ping/Status/Provision buttons in Worker Management tab
- [ ] Verify System Statistics auto-refresh (5s interval when System tab is active)
- [ ] Verify System Health shows database, elasticsearch, api, webui components
- [ ] Verify theme is applied on Admin Panel (reads user preference from /api/preferences/me)
- [ ] Verify fresh deployment with `ENABLE_POLKA_AUTH=true` in `.env`
- [ ] Verify fresh deployment after migration consolidation

### Future Work
- [ ] Worker: Integration testing of C# FileManagerWorker in staging
- [ ] Consider migrating to a component framework (React/Vue) — long-term

---

## COMPLETED (Compact Log)

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
