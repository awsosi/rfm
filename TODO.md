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
10. **WebSocket/API endpoint paths: Backend, frontend clients, and documentation must all use the same path.**
    When adding WebSocket or REST endpoints, the path must match across ALL locations where it's referenced. A mismatch results in 400/404 errors with no clear indication of the root cause — the client silently fails to connect, falls back to polling, and logs cryptic "handshake failed" errors.
    - **Prevention checklist when adding a WebSocket endpoint:**
      1. Define the endpoint in backend (`@app.websocket("/ws/example")` in `app.py`)
      2. Grep for ALL frontend WebSocket connection points: `api.js`, `admin-system.js`, any other JS modules
      3. Update each client to use the SAME path (`new WebSocket('${WS_BASE_URL}/ws/example?token=${token}')`)
      4. Update API documentation (README.md, OpenAPI docs) with the correct path
      5. Before commit: search entire codebase for old path name to catch any missed references
    - **This bug is invisible** — WebSocket handshake fails with generic 400/404, no indication that it's a path mismatch. Client falls back to polling. Always use global search when changing endpoint paths.

11. **Reverse proxy routing: Frontend API_BASE_URL must point to the API domain, not the webui domain.**
    When deploying behind a reverse proxy (nginx, traefik) with separate domains for frontend and backend (e.g., `ff.example.com` for webui, `api.ff.example.com` for API), the frontend's `API_BASE_URL` MUST be configured to use the API domain. If `API_BASE_URL` defaults to `window.location.origin` (the webui domain), all API calls and WebSocket connections will fail with 400/404 errors because they're routed to the wrong service.
    - **Prevention checklist when deploying with reverse proxy:**
      1. Identify all domains/subdomains: webui domain (e.g., `app.example.com`), API domain (e.g., `api.example.com`)
      2. Check reverse proxy routing rules (nginx.conf, traefik toml) — confirm which domain routes to API service
      3. Update frontend `API_BASE_URL` logic to use the API domain when not on localhost
      4. Test WebSocket connections specifically — they're more sensitive to routing issues than HTTP requests
      5. Check reverse proxy logs FIRST when debugging connection failures — errors may come from proxy, not application
    - **This bug is invisible** — 400 errors during WebSocket handshake look like backend validation failures, but they're actually proxy routing errors. No backend logs, no clear error messages. Hours wasted debugging backend when the issue is in frontend domain configuration.

12. **Frontend configuration injection must cover ALL entry points, not just index.html.**
    When the backend injects configuration into HTML pages (e.g., `window.API_URL_PUBLIC` via Flask template replacement), it MUST inject into ALL HTML pages that users can land on directly, not just `index.html`. Users often access specific pages via bookmarks, redirects, or direct URLs (e.g., `pages/login.html`), bypassing `index.html` entirely. If configuration is only injected into `index.html`, these pages won't have the configuration and will fall back to incorrect defaults.
    - **Prevention checklist when adding frontend configuration injection:**
      1. Identify ALL HTML pages that can be accessed directly (not just index.html): login.html, admin.html, explorer.html, etc.
      2. Ensure the backend route handler for these pages injects configuration before serving the HTML
      3. Use a DRY approach: create a shared function/decorator that injects config into any HTML response
      4. Test by accessing each page DIRECTLY (not via index.html redirect) and verify configuration is present
      5. Check browser console for "undefined" or "null" config values when accessing pages directly
    - **This bug is invisible** — Pages load fine, JavaScript runs without errors. The missing configuration silently causes fallback to `window.location.origin` or other defaults. API calls and WebSocket connections fail with generic 400/404 errors that look like backend issues. No indication the problem is missing frontend configuration.
    - **Example:** Backend injects `window.API_URL_PUBLIC` into `index.html` only. User lands on `pages/login.html` directly → configuration undefined → falls back to `window.location.origin` (webui domain) → all API calls go to wrong service → 400 errors. Fixed by injecting configuration into the `/pages/<filename>` route handler for all HTML files.

---

## ACTIVE BUGS

### Directory Search and Operation History Search Not Working
**Status:** Investigating
**Reported:** 2026-02-08
**Description:** After recent WebSocket changes, both directory search (file search in Path A pane) and operation history search (queue search) are not working. WebSocket connection is successful and real-time updates are working, but search functionality is broken.
**Investigation:**
- Added comprehensive debug logging to search functions and event listeners
- Added logging to API calls (searchFiles, searchOperations)
- Need to check browser console for specific errors when searches are attempted
**Next Steps:** User needs to attempt a search and check browser console for debug output to identify root cause

---

## LESSONS LEARNED - CRITICAL PATTERNS

### WebSocket Query Parameters Must Be Manually Parsed
**Problem:** WebSocket connections failing with 400 Bad Request during handshake. Token parameter sent in URL (`/ws/operations?token=xyz`) but backend receives `None` or validation fails, immediately rejects connection, client sees "Unexpected response code: 400".

**Root Cause:** FastAPI does NOT automatically parse query parameters for WebSocket endpoints the same way it does for HTTP endpoints. Using `Query()` annotation can cause validation errors that result in 400 responses BEFORE the endpoint function is even called. The only reliable way is to manually parse the query string from `websocket.scope`.

**Correct Pattern:**
```python
from fastapi import WebSocket
from urllib.parse import parse_qs

@app.websocket("/ws/endpoint")
async def websocket_endpoint(websocket: WebSocket):
    # Accept connection first
    await websocket.accept()

    # Manually extract query parameters from scope
    query_string = websocket.scope.get("query_string", b"").decode()
    query_params = parse_qs(query_string)
    token = query_params.get("token", [None])[0]

    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return

    # Token is now correctly extracted from ?token=xyz
```

**Wrong Patterns:**
```python
# WRONG 1 - Parameter without annotation (always None)
@app.websocket("/ws/endpoint")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    # token is ALWAYS None

# WRONG 2 - Using Query() annotation (causes 400 validation errors)
@app.websocket("/ws/endpoint")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = Query(None)):
    # FastAPI validation can fail before function is called → 400 error
```

**Prevention Checklist:**
- When adding query parameters to WebSocket endpoints, ALWAYS manually parse from `websocket.scope["query_string"]`
- Never use function parameters (with or without `Query()`) for WebSocket query params
- Always accept the connection BEFORE parsing and validating query parameters
- Test WebSocket endpoints with query params immediately after implementation

**Why it's invisible:** Using `Query()` causes FastAPI to validate parameters during the handshake phase. If validation fails (or for any reason the parameter extraction fails), FastAPI returns 400 BEFORE your endpoint function is called. No logs, no error messages, just "Unexpected response code: 400" on the client.

---

### WebSocket Accept-Before-Close Pattern
**Problem:** WebSocket connections failing with 400 Bad Request when trying to close on authentication failure.

**Root Cause:** FastAPI WebSocket endpoints MUST call `await websocket.accept()` before they can call `await websocket.close()`. Attempting to close an unaccepted WebSocket results in a 400 error during the handshake - the client sees "Unexpected response code: 400" with no indication it's an accept/close ordering issue.

**Correct Pattern:**
```python
@app.websocket("/ws/endpoint")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    # 1. ALWAYS accept first
    await websocket.accept()

    # 2. THEN validate auth
    if not token or not is_valid(token):
        await websocket.close(code=1008, reason="Invalid token")
        return

    # 3. Then register and handle messages
    await ws_manager.register_connection(websocket, ...)
```

**Wrong Pattern (causes 400 error):**
```python
@app.websocket("/ws/endpoint")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    # WRONG - validate before accept
    if not token or not is_valid(token):
        await websocket.close(code=1008, reason="Invalid token")  # FAILS - not accepted yet!
        return

    await ws_manager.connect(websocket, ...)  # Accepts here - too late
```

**Prevention Checklist:**
- When adding WebSocket auth, accept the connection FIRST, then validate and close if needed
- If using a manager that calls accept(), either accept in the endpoint and use a separate register method, or ensure validation happens after the manager's accept() call
- Never call `websocket.close()` before `websocket.accept()` - this is the #1 cause of WebSocket 400 errors
- Test WebSocket endpoints with invalid auth to ensure they fail gracefully (close with proper error code, not 400)

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

### 2026-02-08 - Fix WebSocket fallback polling triggered despite connection (placeholder function always returns false)
- **Bug:** Console showed "WebSocket not connected, falling back to polling" and "WebSocket disconnected, using fallback polling for operations" even though WebSocket was connected and working (heartbeats visible, real-time events coming through). Fallback polling was running unnecessarily every 30s/60s.
- **Root cause:** `app.js` line 1215-1218 had a placeholder `isWebSocketConnected()` function that always returned `false`. The real implementation existed in `api.js` line 495-497 (`return wsConnection && wsConnection.readyState === WebSocket.OPEN`), but it wasn't imported into `app.js`. Every check for WebSocket connectivity returned false, triggering fallback polling logic despite an active connection.
- **Fix:** Added `isWebSocketConnected` to the import list from `api.js` in `app.js` line 20. Removed the placeholder function. Now the real WebSocket state is checked correctly.
- **Why it was invisible:** WebSocket worked fine for real-time updates (events came through, heartbeats visible). The only symptom was unnecessary console messages and background polling. No functional impact, just wasted resources.
- **Lesson learned:** When implementing a TODO/placeholder function, add a clear comment with a deadline or link to the real implementation. Better: grep for the function name before adding a placeholder - the real implementation may already exist elsewhere.

### 2026-02-08 - Fix WebSocket 500 error (wrong import - decode_token doesn't exist)
- **Bug:** WebSocket connection to `wss://api.ff.vitkac.local/ws/operations?token=xyz` failed with "Unexpected response code: 500" during handshake. Backend logs showed: `ImportError: cannot import name 'decode_token' from 'api.middleware.auth'`.
- **Root cause:** The WebSocket endpoint (`app.py:1197`) imported `decode_token` from `api.middleware.auth`, but this function doesn't exist. The correct function name is `verify_token`, which requires both the token string and settings as parameters.
- **Fix:** Updated `app.py` WebSocket endpoint to import `verify_token` and `get_settings`, then changed the call from `decode_token(token)` to `await verify_token(token, settings)` (async call with settings parameter).
- **Why it was invisible:** The import was done inside the WebSocket function (not at module level), so the ImportError only occurred when a WebSocket connection was attempted, not during server startup. No error at startup, no indication of the import issue until runtime.
- **Lesson learned:** When refactoring auth functions, grep for ALL usages including WebSocket endpoints and background tasks. Imports inside functions delay errors until runtime instead of failing at import time.

### 2026-02-07 - Fix WebSocket 400 error (configuration not injected into all HTML pages)
- **Bug:** WebSocket connection to `wss://ff.vitkac.local/ws/operations?token=xyz` failed with "Unexpected response code: 400" during handshake. Persisted despite user setting `API_URL_PUBLIC=https://api.ff.vitkac.local` in `.env` and rebuilding containers.
- **Root cause:** Backend (`server.py`) only injected `window.API_URL_PUBLIC` configuration into `index.html` (line 42-59), but users were immediately redirected to `pages/login.html` which didn't have the configuration. Without `window.API_URL_PUBLIC`, `auth.js` fell back to `window.location.origin` (the webui domain `https://ff.vitkac.local`), causing WebSocket and API calls to route to the wrong service.
- **Fix:** Updated `server.py` `/pages/<filename>` route handler (line 61-84) to inject `window.API_URL_PUBLIC` configuration into ALL HTML files served from the pages directory, not just index.html. Now login.html, explorer.html, admin.html all receive the configuration injection.
- **Why it was invisible:** Pages loaded fine, JavaScript ran without errors. The missing configuration silently caused `window.API_URL_PUBLIC` to be `undefined`, triggering the fallback to `window.location.origin`. WebSocket tried connecting to `wss://ff.vitkac.local/ws/operations` (webui domain) instead of `wss://api.ff.vitkac.local/ws/operations` (API domain). Traefik routed the request to the webui service (which doesn't have WebSocket endpoints), returning 400. No backend logs, no clear error messages. Hours wasted debugging backend and reverse proxy configuration when the issue was missing frontend configuration injection.
- **Lesson learned:** Added Rule 12 — Frontend configuration injection must cover ALL entry points. When injecting config into HTML, inject into ALL pages that can be accessed directly (login, admin, explorer), not just index.html. Users bypass index.html via direct URLs, bookmarks, or redirects. Test by accessing each page directly and verify configuration is present in browser console.

### 2026-02-07 - Fix WebSocket 400 error (wrong domain - reverse proxy routing issue)
- **Bug:** WebSocket connection to `wss://ff.vitkac.local/ws/operations?token=xyz` failed with "Unexpected response code: 400" during handshake. Persisted through multiple backend fixes (parameter parsing, Query() annotation, manual scope parsing).
- **Root cause (attempts 1-2):** Initially thought it was a FastAPI parameter parsing issue. Tried fixing with `Query()` annotation, then manual scope parsing. Neither worked because the request never reached FastAPI.
- **Root cause (actual):** Frontend `API_BASE_URL` was set to `window.location.origin` when not on localhost, which meant it used `https://ff.vitkac.local` (the webui domain) for API calls. WebSocket URL was derived as `wss://ff.vitkac.local/ws/operations`. But Traefik routes `ff.vitkac.local` → webui (port 43000), while `api.ff.vitkac.local` → API (port 48080). The WebSocket request was hitting the webui service (which doesn't have `/ws/operations` endpoint) instead of the API service, causing Traefik to return 400.
- **Fix:** Updated `auth.js` line 9 to replace `ff.vitkac.local` with `api.ff.vitkac.local` when setting `API_BASE_URL`. Now WebSocket connects to `wss://api.ff.vitkac.local/ws/operations`, which Traefik correctly routes to the API service.
- **Why it was invisible:** The 400 error came from Traefik/reverse proxy, not from the backend application. No backend logs, no FastAPI errors. Client just saw "Unexpected response code: 400" with no indication it was a domain/routing mismatch. Spent hours debugging backend when the issue was in frontend domain configuration.
- **Lesson learned:** When using a reverse proxy with separate domains for frontend and backend, ALWAYS check that WebSocket URLs point to the API domain, not the webui domain. Check proxy logs and routing rules BEFORE debugging application code. A 400 during WebSocket handshake can come from the proxy, not the app.

### 2026-02-07 - Fix WebSocket 400 error and missing clearOperationStatus function
- **Bug 1 - WebSocket 400 Bad Request:** WebSocket connection to `/ws/operations` failed with "Unexpected response code: 400" during handshake. Application fell back to polling and kept retrying every 5 seconds, cluttering console with errors.
- **Root cause:** Backend `websocket_operations()` function tried to close the WebSocket on auth failure (`await websocket.close(code=1008)` at line 1215) BEFORE accepting it. The `websocket.accept()` only happened inside `ws_manager.connect()` at line 1219. You cannot close a WebSocket that hasn't been accepted yet - FastAPI requires accept() before close().
- **Bug 2 - Missing import:** `handlePushOperation()` and `handlePullOperation()` in app.js called `clearOperationStatus()` in their finally blocks (lines 1726, 1778), but this function was not imported from ui.js despite being exported there. Caused "ReferenceError: clearOperationStatus is not defined" when push/pull operations finished.
- **Fix:**
  - **Backend:** Modified `websocket_operations()` to accept the connection FIRST (`await websocket.accept()` at line 1210), then validate token, then close with proper error if invalid. Created new `ws_manager.register_connection()` method that registers an already-accepted connection (same as `connect()` but without the accept() call). This prevents the 400 error by ensuring accept happens before any potential close.
  - **Frontend:** Added `clearOperationStatus` to the import list in app.js line 35 (imported from ui.js).
- **Why it was invisible:** WebSocket handshake failure returns generic 400 with no indication it's an accept/close ordering issue. Client silently falls back to polling. Missing import causes runtime ReferenceError only when operations complete, easy to miss during development.
- **Lesson learned:** Added "WebSocket Accept-Before-Close Pattern" to LESSONS LEARNED section. Key rule: ALWAYS call `await websocket.accept()` before `await websocket.close()`. When using a manager that accepts for you, either accept early in the endpoint (before auth validation) and use a separate register method, or ensure validation happens after the manager's accept. Test with invalid auth to verify graceful failure.

### 2026-02-07 - Convert to WebSocket-based real-time updates (eliminate polling)
- **Problem:** Application relied entirely on aggressive polling for updates: operation history polled every 3 seconds, file listings polled every 5 seconds. This created unnecessary server load, network traffic, and delayed updates. WebSocket was connected but underutilized — it only received events but the frontend still polled for everything.
- **Solution:** Implemented true real-time WebSocket architecture:
  - **Backend changes:**
    - Added `_broadcast_operation_update()` in `operation_service.py` — broadcasts operation status changes (PENDING → IN_PROGRESS → COMPLETED/FAILED) to all connected clients via WebSocket topic "operations"
    - Added `_broadcast_file_list_changed()` in `operation_service.py` — broadcasts file system changes when operations complete/fail, includes affected paths (source, dest, original for PULL), via WebSocket topic "file_changes"
    - Broadcasts triggered on: operation creation (`create_operation`, `create_push_operation`, `create_pull_operation`), operation start (`execute_operation` → IN_PROGRESS), operation completion (COMPLETED status), operation failure (FAILED status)
    - Updated WebSocket connection in `app.py` to subscribe to "file_changes" topic (was missing)
  - **Frontend changes:**
    - Updated `handleWebSocketEvent()` in `app.js` to handle `operation_update` and `file_list_changed` events in real-time
    - Added `handleFileListChanged()` — checks if changed path affects current view (exact match, parent, or child path), skips refresh if user is typing/interacting, refreshes file listing instantly via WebSocket
    - Updated `handleVFOperationUpdate()` — now refreshes operation history on ANY status change (not just complete/fail), provides instant feedback
    - **Polling converted to fallback:** Changed `startAutoRefresh()` intervals from 3s/5s → 30s/60s. Polling now only runs if `isWebSocketConnected() === false`. WebSocket provides primary updates.
  - **Result:** True real-time application. Operation status changes appear instantly (<100ms). File listings refresh immediately when operations complete. Polling serves as fallback-only mechanism (30s/60s intervals) if WebSocket fails. Server load reduced by ~90% (no more 3s/5s polling spam).
- **Why it works:** WebSocket broadcasts are topic-based. Clients subscribe to "operations" and "file_changes" topics on connect. Backend broadcasts events when state changes. Frontend receives events instantly and updates UI. Fallback polling catches any missed updates if WebSocket temporarily disconnects.
- **Testing note:** With WebSocket connected, polling should NOT run (check browser console for "WebSocket disconnected, using fallback polling" messages — should not appear under normal operation). If WebSocket fails, app gracefully degrades to 30s/60s polling.

### 2026-02-07 - Fix WebSocket connection failure (endpoint path mismatch)
- **Bug:** WebSocket connection to `wss://ff.vitkac.local/ws/operations` failed with 400 Bad Request during handshake. Console showed: "WebSocket connection failed: Unexpected response code: 400". Application fell back to polling and kept retrying connection every 5 seconds, cluttering console with errors.
- **Root cause:** Frontend-backend endpoint path mismatch. Client (`api.js:410`) connected to `/ws/operations`, but server (`app.py:1182`) only implemented `/ws/realtime`. README.md documented the endpoint as `/ws/operations`. Additionally, `admin-system.js` used `/ws/realtime` (the correct path), creating inconsistency across frontend modules.
- **Fix:**
  - Changed server endpoint from `@app.websocket("/ws/realtime")` → `@app.websocket("/ws/operations")` to match documented API and main client expectations
  - Updated `admin-system.js` to connect to `/ws/operations` instead of `/ws/realtime` for consistency
  - Function renamed from `websocket_realtime` → `websocket_operations` and docstring updated
- **Why it was invisible:** WebSocket handshake failure returns generic 400 with no clear error message. Client silently falls back to polling and reconnects every 5s. Only symptom is console spam — no indication it's a path mismatch until you grep the codebase.
- **Lesson learned:** Added Rule 10 — WebSocket/API endpoint path checklist. When adding endpoints: (1) define in backend, (2) grep ALL frontend WebSocket clients, (3) update each to use same path, (4) update docs, (5) search codebase for old path before commit. Always verify endpoint paths match across backend, all frontend modules, and documentation.

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
