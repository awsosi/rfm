# TODO - RFM (Remote File Manager)

> **Project:** File operation management system with microservices architecture
> **Status:** Active Development
> **Last Updated:** 2026-02-06

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

---

## ACTIVE BUGS

None.

---

## ACTIVE TODO ITEMS

### Verification Needed (requires running app with Docker)
- [ ] Verify Admin Panel after DRY refactor (all tabs: Users, Workers, Config, System, Logs)
- [ ] Verify worker Remove button works after refactor
- [ ] Verify worker Suspend/Activate buttons work
- [ ] Verify fresh deployment with `POLKA_AUTH_ENABLED=true` in `.env` — PolkaSQL auth should be active without touching Admin Panel
- [ ] Verify re-deployment: change `POLKA_AUTH_ENABLED` from `false` to `true` in `.env`, restart — should take effect immediately
- [ ] Verify worker PathC: run `/config` wizard, set custom Path C, register worker — admin panel should show the correct Path C value
- [ ] Verify fresh deployment after migration consolidation — `docker-compose up` should create all tables from single `001_initial_schema.py`

### Future Work
- [ ] Worker: Integration testing of C# FileManagerWorker in staging (ops/deployment — push/pull round-trip)
- [ ] Consider migrating to a component framework (React/Vue) for better DOM/JS sync and type safety — long-term

---

## COMPLETED (Compact Log)

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
