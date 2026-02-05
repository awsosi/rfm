# TODO - RFM (Remote File Manager)

> **Project:** File operation management system with microservices architecture
> **Status:** Active Development ✅
> **Last Updated:** 2026-02-05

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
- [ ] Remote Authentication: Test login with remote API enabled
- [ ] Remote Authentication: Verify case-insensitive username/password matching
- [ ] Remote Authentication: Verify auto-creation of users on first remote auth
- [ ] Remote Authentication: Verify database config takes priority over .env
- [ ] Remote Authentication: Test timeout and error handling

---

## 🔧 RECENT FIXES (Last 7 Days)

### 2026-02-05 - Remove Duplicate Config Loading Logic (DRY Principle)
**Issue**: admin.html had duplicate config loading/saving logic that was out of sync with admin.js, violating DRY principle and causing maintenance issues.

**Root Cause**:
- admin.html contained inline JavaScript with `loadConfig()` function (73 lines) and `save-config-btn` event listener (59 lines)
- admin.js had AdminPanel class with proper config methods (loadConfiguration, saveConfiguration) but was never used
- This duplication required maintaining identical logic in two places, leading to sync issues in previous bugs

**Fix Applied**:
1. **admin.js**: Added standalone export functions `loadConfigurationData()` and `saveConfigurationData()` that can be imported independently
2. **admin.html**:
   - Imported the standalone functions from admin.js
   - Removed duplicate `loadConfig()` function (~73 lines removed)
   - Removed duplicate save-config-btn event listener (~59 lines removed)
   - Updated `loadTabData()` to call `loadConfigurationData()`
   - Replaced save button handler with simple call to `saveConfigurationData()`
3. **Result**: Single source of truth in admin.js, ~130 lines of duplicate code eliminated

**Files Modified**:
- `frontend/js/admin.js` (added lines 906-1036: standalone export functions)
- `frontend/pages/admin.html` (line 587: added import; line 656: updated loadTabData call; lines 1012-1020: replaced 135 lines of duplicate code with 9 lines calling imported functions)

**Result**:
✅ Configuration loading/saving now in single location (admin.js)
✅ ~130 lines of duplicate code eliminated
✅ Future config changes only need to be made in one place
✅ Follows DRY principle properly
✅ Reduced maintenance burden and eliminated sync issues

---

### 2026-02-05 - Fix PolkaSQL Settings Not Persisting in WebUI (Missed Inline Script During Refactor)
**Issue**: After PR #103, PolkaSQL settings still not persisting in Admin Panel despite being saved to database and working in backend:
1. User saves Polka auth settings in Admin Panel → settings work (remote auth succeeds) ✓
2. Database contains correct values ✓
3. Backend reads and uses settings correctly ✓
4. But on page reload, Admin Panel form fields show empty (settings don't persist in webui) ✗

**Root Cause**:
PR #103 fixed backend (config.py, auth.py, .env.example) and admin.js, but **MISSED** the inline JavaScript in admin.html that also loads config into form fields.

**Problem Location** (frontend/pages/admin.html:1037-1040):
- The inline `loadConfig()` function had outdated Sybase fieldMapping from the original Sybase→Polka refactor
- It was looking for: `enable_sybase_auth`, `sybase_auth_url`, `sybase_auth_timeout`, `sybase_auth_stored_proc`
- Should have been: `polka_auth_enabled`, `polka_auth_url`, `polka_auth_api_key`, `polka_auth_timeout`
- Result: On page load or tab switch, inline script tried to populate Polka form fields using Sybase config keys (wrong keys), so fields remained empty

**Why This Was Missed**:
1. PR #103 focused on backend config.py, auth.py, and .env - didn't search frontend HTML files
2. admin.js was updated correctly (lines 504-507), but admin.html has DUPLICATE inline code that was overlooked
3. There are TWO separate implementations of config loading:
   - admin.js `populateConfigForm()` (correct, updated in PR #102)
   - admin.html inline `loadConfig()` (incorrect, still had Sybase keys from original refactor)
4. The inline script in admin.html overrides or runs alongside admin.js code

**Fix Applied** (frontend/pages/admin.html:1037-1040):
- Replaced outdated Sybase fieldMapping with Polka fieldMapping:
  ```javascript
  // OLD (wrong):
  'config-sybase-enabled': 'enable_sybase_auth',
  'config-sybase-url': 'sybase_auth_url',
  'config-sybase-timeout': 'sybase_auth_timeout',
  'config-sybase-proc': 'sybase_auth_stored_proc',

  // NEW (correct):
  'config-polka-auth-enabled': 'polka_auth_enabled',
  'config-polka-auth-url': 'polka_auth_url',
  'config-polka-auth-api-key': 'polka_auth_api_key',
  'config-polka-auth-timeout': 'polka_auth_timeout',
  ```

**Files Modified**:
- `frontend/pages/admin.html` (lines 1037-1040: replaced Sybase with Polka in inline loadConfig fieldMapping)

**Result**:
✅ Admin Panel now correctly populates Polka auth fields on page load
✅ Settings persist in webui after save and reload
✅ Complete consistency: backend, admin.js, and admin.html all use correct Polka field names

**CRITICAL LESSON LEARNED - SEARCH EVERYWHERE DURING REFACTORS**:
**When renaming/refactoring features across a codebase:**

1. ✅ **SEARCH HTML FILES TOO** - Don't just grep .js/.py files; inline JavaScript in .html files is CODE TOO
   - Use: `rg -i "old_feature_name"` (searches ALL file types by default)
   - Don't use: `rg -i "old_feature_name" --type js --type py` (misses HTML!)

2. ✅ **LOOK FOR DUPLICATE IMPLEMENTATIONS** - If you find config loading in admin.js, check if admin.html also has inline config loading
   - Inline `<script>` blocks in HTML often duplicate functionality from .js files
   - Check for: inline event handlers, inline API calls, inline form population logic

3. ✅ **REFACTOR CHECKLIST MUST INCLUDE HTML FILES**:
   - [ ] Backend models/services (.py files)
   - [ ] API routes and config (.py files)
   - [ ] Frontend JavaScript (.js files)
   - [ ] **Frontend HTML inline scripts (.html <script> blocks)** ← OFTEN MISSED!
   - [ ] Database migrations
   - [ ] .env.example
   - [ ] Schema verification scripts

4. ✅ **TEST THE ACTUAL UI** - Don't just verify API responses; open the Admin Panel and test:
   - Save settings → reload page → verify fields still populated
   - This would have caught the issue immediately

5. ✅ **ELIMINATE DUPLICATE CODE** - If both admin.js AND admin.html have config loading logic:
   - Consider removing inline code and using only the .js module
   - Or document why duplication exists and keep them in sync
   - Current state: admin.html inline code should probably be removed, let admin.js handle it

**How to NEVER make this mistake again**:
1. When refactoring, use `rg -i "old_name"` WITHOUT file type filters to catch ALL occurrences
2. Search for patterns like `loadConfig`, `saveConfig`, `fieldMapping` to find duplicate implementations
3. Check EVERY HTML file that might have inline `<script>` tags related to the feature
4. Create refactor checklist that explicitly includes "inline HTML scripts"
5. Test UI functionality end-to-end after refactors (not just API tests)
6. Consider moving ALL JavaScript from inline HTML to .js modules for better maintainability

**Root Cause of Root Cause**:
This bug exists because admin.html has duplicate/conflicting logic instead of using a single source of truth (admin.js). The real fix would be to eliminate the inline code entirely, but for minimal changes, we just synchronized the fieldMappings.

**Future Improvement**:
Refactor admin.html to remove inline `loadConfig()` and `save-config-btn` event listener, let admin.js handle everything through the AdminSystem class. This would follow DRY principle and prevent future sync issues.

---

### 2026-02-05 - Fix PolkaSQL Auth .env Ignored and Admin Panel Not Persisting (Config Key Mismatch) [PARTIAL FIX - See above for complete fix]
**Issue**: PolkaSQL authentication had two critical bugs after the Sybase→PolkaSQL rename:
1. Environment variables (ENABLE_POLKA_AUTH, POLKA_AUTH_URL, POLKA_AUTH_API_KEY, POLKA_AUTH_TIMEOUT) completely ignored
2. Admin Panel settings saved successfully but didn't show on page reload (form fields remained empty)

**Root Causes**:
1. **Settings class field name mismatch** (backend/api/config.py:94): Settings class used `enable_polka_auth` but database config used `polka_auth_enabled`
   - Database migration 008 creates: `polka_auth_enabled`, `polka_auth_url`, `polka_auth_api_key`, `polka_auth_timeout`
   - Settings class defined: `enable_polka_auth`, `polka_auth_url`, `polka_auth_api_key`, `polka_auth_timeout`
   - Frontend fieldMapping (admin.js:504-507): `polka_auth_enabled` (correct)
   - .env.example: `ENABLE_POLKA_AUTH` (mapped to `enable_polka_auth` by pydantic - WRONG!)
   - Result: .env values loaded into `settings.enable_polka_auth`, but auth.py looked for `settings.polka_auth_enabled`

2. **Database default override behavior** (backend/api/routes/auth.py:95-102): Migration creates `polka_auth_enabled='false'` as default
   - Logic was: `if enabled_str:` then use database value, else use .env
   - Since `'false'` is truthy (non-empty string), database always took priority over .env
   - Result: .env values ignored even when database had migration defaults

**Fixes Applied**:

1. **Settings Class Field Rename** (backend/api/config.py:94):
   - Changed `enable_polka_auth` → `polka_auth_enabled` to match database keys
   - Now pydantic maps `POLKA_AUTH_ENABLED` env var → `polka_auth_enabled` field

2. **Updated .env.example** (.env.example:154):
   - Changed `ENABLE_POLKA_AUTH` → `POLKA_AUTH_ENABLED` to match new field name

3. **Fixed Fallback Logic** (backend/api/routes/auth.py:95-102, 48-54):
   - Old: `if enabled_str:` (treats 'false' as set) → `enabled = parse('false')` → False
   - New: `if enabled_str and enabled_str in ('true', '1', 'yes'):` → `enabled = True` else fall back to .env
   - Now migration default `'false'` treated as "not explicitly set", allowing .env to override
   - Applied to both `verify_polka_credentials()` and `get_auth_status()` endpoints

4. **Updated Auth.py References** (backend/api/routes/auth.py:102, 54):
   - Changed `settings.enable_polka_auth` → `settings.polka_auth_enabled` (2 occurrences)

**Files Modified**:
- `backend/api/config.py` (line 94: renamed field)
- `.env.example` (line 154: renamed env var)
- `backend/api/routes/auth.py` (lines 48-54: fixed /status endpoint fallback; lines 95-102: fixed verify_polka fallback; lines 102, 54: updated settings references)

**Result**:
✅ .env values now respected when database has migration defaults
✅ Admin Panel settings save and persist correctly (form fields populate on reload)
✅ Database config `'true'` takes priority (explicit enable)
✅ Database config `'false'`/empty treated as "not set", .env takes priority
✅ Field names consistent across Settings class, database, frontend, and .env

**CRITICAL LESSON LEARNED - CONFIG FIELD NAME CONSISTENCY**:
**When implementing dual-config systems (env + database):**
1. ✅ **IDENTICAL FIELD NAMES EVERYWHERE** - Settings class, database keys, frontend fieldMapping, .env vars must ALL match
2. ✅ **USE SNAKE_CASE CONSISTENTLY** - Don't mix `enable_polka_auth` and `polka_auth_enabled` - pick ONE pattern
3. ✅ **CHECK ALL LAYERS** - Config.py Settings class, database migration inserts, frontend JavaScript fieldMapping, .env.example
4. ✅ **MIGRATION DEFAULTS DON'T OVERRIDE .ENV** - Use NULL or treat defaults as "not set" so .env can override
5. ✅ **TEST BOTH CONFIG SOURCES** - Verify .env works, database works, and database priority works
6. ✅ **VERIFY FORM POPULATION** - After saving in Admin Panel, reload page and check fields still show values

**How to never make this mistake again:**
- When renaming config fields, use global search to find ALL references: `rg -i "enable_polka|polka.*enabled"`
- Create checklist for config fields:
  - [ ] Settings class field name (config.py)
  - [ ] Database migration key (alembic/versions/*.py)
  - [ ] Frontend fieldMapping (admin.js)
  - [ ] .env.example variable name
  - [ ] Backend code that reads Settings (auth.py, etc.)
  - [ ] Schema verification (verify_schema.py)
- Use consistent naming: prefer `feature_enabled` over `enable_feature` for boolean flags
- Document config priority chain in code comments: "Database → .env → default"
- Write integration test: set .env value, verify it works; set DB value, verify it overrides
- Use NULL in migrations instead of hardcoded defaults to allow .env fallback
- If using hardcoded defaults in migrations, treat them as "not set" in fallback logic (like we did with 'false')

**Design Notes**:
- KISS: Simple fallback logic, consistent naming across all layers
- DRY: Single source of truth for field names (Settings class definition drives everything)
- Backward compatible: Existing database values still work, just added proper .env fallback
- Clear priority: Database 'true' > .env > Database 'false'/empty/NULL

**Testing Recommendations** (when docker available):
1. Test .env only: Set `POLKA_AUTH_ENABLED=true` in .env, no DB override → should enable
2. Test database priority: Set .env=false, DB='true' → should enable (DB wins)
3. Test migration defaults: Fresh DB with migration → .env values should work
4. Test Admin Panel: Save settings, reload page → fields should remain populated
5. Test form empty values: Clear fields in Admin Panel, save → should fall back to .env
6. Test all 4 settings: enabled, url, api_key, timeout from both .env and database

---

### 2026-02-05 - Fix PolkaSQL Auth Settings Not Persisting (Incomplete Implementation) [SUPERSEDED BY ABOVE]
**Issue**: PolkaSQL authentication settings completely broken after refactor from Sybase to PolkaSQL:
1. Environment variables (ENABLE_POLKA_AUTH, POLKA_AUTH_URL, POLKA_AUTH_API_KEY, POLKA_AUTH_TIMEOUT) not respected by the app
2. Admin Panel settings for Polka auth not saved - fields empty on reload even after saving
3. Frontend login screen doesn't change even when .env is configured

**Root Causes**:
1. **Missing fieldMapping entries** (frontend/js/admin.js:501-534): The `populateConfigForm()` function's fieldMapping object still referenced old Sybase auth fields instead of new Polka fields
   - Had: `enable_sybase_auth`, `sybase_auth_url`, `sybase_auth_timeout`, `sybase_auth_stored_proc`
   - Needed: `polka_auth_enabled`, `polka_auth_url`, `polka_auth_api_key`, `polka_auth_timeout`
   - Result: Form fields never populated from database on load, appeared empty even if values existed

2. **Incomplete config reading** (backend/api/routes/auth.py:84-89, 127-129): The `verify_polka_credentials()` function only loaded 3 config keys from database (`polka_auth_enabled`, `polka_auth_url`, `polka_auth_api_key`) but not `polka_auth_timeout`
   - Timeout was hardcoded to read from env settings only (lines 127-129)
   - Never checked database config for timeout value
   - Database config priority promise broken for timeout setting

3. **Missing database migration**: No migration existed to create Polka auth config entries in the database
   - Initial migration (001_initial_schema.py) still created old Sybase config entries
   - No migration removed old Sybase entries or added new Polka entries
   - Config table missing `polka_auth_enabled`, `polka_auth_url`, `polka_auth_api_key`, `polka_auth_timeout` rows

4. **Incomplete schema verification** (backend/verify_schema.py:161-163): Required configs list had `enable_polka_auth` (wrong name) instead of `polka_auth_enabled`, and was missing `polka_auth_api_key` entirely

**Fixes Applied**:

1. **Frontend - Admin Panel fieldMapping** (frontend/js/admin.js:504-507):
   - Removed old Sybase auth fields: `enable_sybase_auth`, `sybase_auth_url`, `sybase_auth_timeout`, `sybase_auth_stored_proc`
   - Added new Polka auth fields: `polka_auth_enabled`, `polka_auth_url`, `polka_auth_api_key`, `polka_auth_timeout`
   - Form fields now populate correctly from database on Admin Panel load

2. **Backend - Config Loading** (backend/api/routes/auth.py:84-89, 127-139):
   - Added `polka_auth_timeout` to database config query (line 88)
   - Updated timeout loading to check database first, then fall back to env (lines 127-139)
   - Handles invalid timeout strings gracefully with try/except
   - Database config priority now applies to ALL Polka settings

3. **Database Migration** (backend/alembic/versions/008_add_polka_config.py):
   - Created new migration 008 to add Polka auth config entries
   - Deletes old Sybase config entries (enable_sybase_auth, sybase_auth_url, sybase_auth_timeout, sybase_auth_stored_proc)
   - Inserts new Polka config entries with proper types and descriptions
   - Includes downgrade path to restore Sybase entries if needed

4. **Schema Verification** (backend/verify_schema.py:161-164):
   - Changed `enable_polka_auth` to `polka_auth_enabled` (correct config key name)
   - Added missing `polka_auth_api_key` to required configs
   - Verification now checks all 4 Polka auth config keys

**Files Modified**:
- `frontend/js/admin.js` (lines 504-507: replaced Sybase fields with Polka fields in fieldMapping)
- `backend/api/routes/auth.py` (line 88: added timeout to query; lines 127-139: read timeout from database first)
- `backend/alembic/versions/008_add_polka_config.py` (new migration file)
- `backend/verify_schema.py` (lines 161-164: fixed config key names, added api_key)

**Result**:
✅ Admin Panel Polka auth fields now save and load correctly
✅ Environment variables respected when database config not present
✅ Database config takes priority over .env for all 4 settings
✅ Frontend login screen shows auth method selector when Polka auth enabled
✅ All config keys properly validated in schema verification

**CRITICAL LESSON LEARNED - COMPLETE YOUR REFACTORS**:
**When renaming/refactoring a feature:**
1. ✅ **SEARCH THE ENTIRE CODEBASE** - Don't just rename the obvious files, search for ALL references to old names
2. ✅ **CHECK FRONTEND AND BACKEND** - JavaScript fieldMappings, database queries, migrations, schema validators, etc.
3. ✅ **VERIFY DATA LAYER** - Ensure database migrations create/update all necessary entries
4. ✅ **TEST ALL CONFIG SOURCES** - If dual-config (env + database), test BOTH sources and priority
5. ✅ **UPDATE SCHEMA VERIFICATION** - Required configs lists, verification scripts, documentation
6. ✅ **DON'T ASSUME IT WORKS** - Test the actual functionality end-to-end, don't just check if code compiles

**How to never make this mistake again:**
- Use global search (grep/ripgrep) for old names BEFORE committing refactor: `rg -i "sybase_auth|enable_sybase"`
- Create checklist for refactors: [ ] Backend models [ ] API routes [ ] Frontend JS [ ] HTML forms [ ] Migrations [ ] Verification [ ] Tests
- Test with fresh database to ensure migrations work: `docker-compose down -v && docker-compose up`
- Check Admin Panel UI after refactor: verify all fields load, save, and persist correctly
- Review all files in the PR diff to catch leftover references
- When renaming config keys, write a migration to rename database entries (don't leave orphaned data)
- Add schema verification tests to CI/CD to catch missing config entries

**Design Notes**:
- KISS approach: Reused existing patterns (fieldMapping, config priority chain, migration structure)
- DRY: Single source of truth for config keys (database with env fallback)
- Complete solution: Fixed all 4 layers (frontend UI, backend API, database schema, verification)
- Backward compatible: Old Sybase entries removed cleanly with downgrade path
- Clear separation: Form field names match config keys exactly (no translation needed)

**Testing Recommendations** (for when docker is available):
1. Test fresh start with no database config: Polka settings from .env should work
2. Test Admin Panel save: Set Polka values, save, reload page - fields should remain populated
3. Test database priority: Set different values in .env and database, database should win
4. Test timeout config: Verify timeout from database used instead of .env default
5. Test schema verification: Run verify_schema.py to ensure all 4 config keys exist
6. Test migration: Apply 008 migration on existing database with Sybase entries, verify clean transition
7. Test frontend: Enable Polka in Admin Panel, verify login page shows auth method selector
8. Test disabled state: Disable Polka, verify auth method selector hidden and local auth works

---

### 2026-02-05 - Fix Login Failure After Fresh Start (Frontend Auth Method Bug)
**Issue**: After PRs #99 and #100 (PolkaSQL rename), users couldn't login to the app after fresh start. Login returned 401 Unauthorized even with correct credentials for local admin user.

**Root Cause**: Frontend auth method selector bug caused login failures even when PolkaSQL was disabled:
1. The auth method `<select>` element defaults to first `<option>` which is `"polka"` (line 22 in login.html)
2. When PolkaSQL is disabled, frontend hides the selector (line 86) but doesn't change its value
3. On form submit, `authMethodSelect.value` is still `"polka"` even though selector is hidden (line 103)
4. Backend receives `auth_method: "polka"` and tries PolkaSQL auth, which is disabled
5. Backend doesn't fall back to local auth because `auth_method == "polka"` (not "auto")
6. Backend returns 401 even though the admin user exists and password is correct

**Additional Issue**: Missing imports in auth.py would have caused NameError if PolkaSQL was enabled:
- `func` from sqlalchemy (used on line 209 for case-insensitive username lookup)
- `UserRole` from models (used on line 223 when auto-creating users)

**Fixes Applied**:

1. **Frontend - Auth Method Default** (frontend/pages/login.html:87, 93):
   - When hiding auth method selector, explicitly set value to `'local'`
   - Applied to both main hide logic (polka_auth_enabled == false) and error handler
   - Ensures hidden selector doesn't send `"polka"` value when PolkaSQL is disabled

2. **Backend - Missing Imports** (backend/api/routes/auth.py:16, 24):
   - Added `func` to sqlalchemy import (line 16)
   - Added `UserRole` to models import (line 24)
   - Prevents NameError when PolkaSQL auth creates new users with case-insensitive lookup

**Files Modified**:
- `frontend/pages/login.html` (lines 87, 93: set authMethodSelect.value = 'local' when hiding selector)
- `backend/api/routes/auth.py` (line 16: added func to imports; line 24: added UserRole to imports)

**Result**:
✅ Local users can login successfully when PolkaSQL is disabled
✅ Auth method selector properly defaults to 'local' when hidden
✅ Backend imports are complete and won't cause NameError
✅ PolkaSQL auth still works correctly when enabled

**CRITICAL LESSON LEARNED - ALWAYS TEST HIDDEN FORM ELEMENTS**:
**When hiding form inputs dynamically:**
1. ✅ **ALWAYS reset hidden element values to safe defaults** - Don't assume hidden elements won't submit their values
2. ✅ **Test with feature flags disabled** - If UI hides features based on config, test with feature OFF, not just ON
3. ✅ **Verify imports for all code paths** - Even if code isn't executed in default config, imports must be complete
4. ✅ **Check select element defaults** - `<select>` defaults to first `<option>`, not empty/undefined
5. ✅ **Test form submission with hidden fields** - Hidden fields still submit unless explicitly reset

**How to never make this mistake again:**
- When hiding a `<select>` element, explicitly set its value to a safe default (e.g., 'local', 'auto')
- Don't rely on `|| 'default'` fallback if element value could be non-empty but wrong
- Test authentication with all feature flags in both enabled and disabled states
- Always run import verification even for code paths that aren't executed in default config
- Use browser DevTools to inspect form data BEFORE submission to verify hidden field values
- Consider using disabled attribute instead of hiding, or clear value when hiding

**Testing Recommendations**:
1. Test login with PolkaSQL disabled (default .env) - should use local auth
2. Test login with PolkaSQL enabled but unreachable - should show appropriate error
3. Test login with PolkaSQL enabled and working - should allow both polka and local auth
4. Test auth method selector visibility based on polka_auth_enabled status
5. Verify imports are complete by attempting PolkaSQL auth with auto-user-creation

---

### 2026-02-05 - Implement Remote Authentication API Integration (renamed to PolkaSQL)
**Issue**: Need to support remote authentication against external API (PolkaSQL/RFM_Auth) with case-insensitive credentials and auto-user-creation.

**Requirements**:
1. Configure via .env and AdminPanel (database config takes priority)
2. Auto-create users when authenticated remotely
3. Verify password on each login against remote API
4. Username and password case-insensitive (unusual requirement but mandated by remote API)
5. Read-only mode - no password changes in RFM app

**Implementation**:

1. **Configuration** (.env.example, backend/api/config.py):
   - Added `ENABLE_REMOTE_AUTH`, `REMOTE_AUTH_URL`, `REMOTE_AUTH_API_KEY`, `REMOTE_AUTH_TIMEOUT`
   - Settings class updated to load from environment
   - Database config table used for runtime configuration (takes priority over .env)

2. **Database Schema** (backend/models.py, backend/alembic/versions/007_add_remote_auth.py):
   - Added `is_remote_auth` boolean field to User model
   - Added `remote_user_id` integer field (stores external user ID from remote API)
   - Created migration 007_add_remote_auth with indexes for efficient lookups

3. **Remote Auth Service** (backend/api/routes/auth.py:73-183):
   - Created `verify_remote_credentials()` async function
   - Checks database config first (priority), then falls back to .env settings
   - Makes GET request to remote API with ApiKey, UserName, Password query params
   - API returns JSON with success, authenticated, user_id, username fields
   - Handles timeouts, network errors gracefully

4. **Login Logic Update** (backend/api/routes/auth.py:186-341):
   - Modified `_perform_login()` to try remote auth first (if enabled)
   - Uses case-insensitive username lookup: `func.lower(User.username) == func.lower(login_data.username)`
   - Auto-creates users with `is_remote_auth=True` and random password_hash (not used for auth)
   - Updates `remote_user_id` if changed on subsequent logins
   - Falls back to local/Sybase auth if remote auth disabled or fails

5. **Admin API Endpoints** (backend/api/routes/admin.py):
   - Added GET `/api/admin/config` to list all configs
   - Added GET `/api/admin/config/{key}` to get specific config
   - Added POST `/api/admin/config/{key}` to create or update config
   - Existing PUT and bulk endpoints already support remote auth config keys

6. **Admin Panel UI** (frontend/pages/admin.html):
   - Added "Remote Authentication (RFM API)" section in Configuration tab
   - Fields: enabled checkbox, API URL, API key (password field), timeout
   - Added help text explaining case-insensitive and read-only behavior
   - Updated JavaScript fieldMappings to include remote auth config keys
   - Config automatically saved to database on "Save Configuration" button click

7. **Auth Method Selector** (backend/api/schemas.py, backend/api/routes/auth.py, frontend):
   - Added `auth_method` parameter to `LoginRequest` schema with validator
   - Auth methods: "auto" (try remote first, fallback to local), "remote" (only remote), "local" (only local)
   - Added GET `/api/auth/status` endpoint to check if remote auth is enabled
   - Updated `_perform_login()` to respect auth_method choice
   - If auth_method="remote" and remote auth fails, don't fallback (fail immediately)
   - If auth_method="local", skip remote auth entirely
   - Login UI shows auth method selector dropdown ONLY when remote auth is enabled
   - Selector defaults to "Remote" when visible, hidden when remote auth disabled
   - Updated auth.js to accept authMethod parameter and use JSON login endpoint
   - JavaScript checks `/api/auth/status` on page load to show/hide selector

**Files Modified**:
- `.env.example` (lines 155-163: added remote auth env vars)
- `backend/api/config.py` (lines 98-102: added Settings fields)
- `backend/models.py` (lines 85-87, 109-110: updated User model docstring and fields)
- `backend/alembic/versions/007_add_remote_auth.py` (new migration file)
- `backend/api/schemas.py` (lines 26-44: added auth_method to LoginRequest with validator)
- `backend/api/routes/auth.py` (lines 31-57: added get_auth_status endpoint; lines 73-183: verify_remote_credentials; lines 215-380: updated _perform_login with auth_method logic)
- `backend/api/routes/admin.py` (lines 465-673: added config endpoints and create_or_update)
- `frontend/pages/admin.html` (lines 162-188: added UI section; lines 1117-1120: added fieldMappings)
- `frontend/pages/login.html` (lines 19-28: added auth method selector; lines 73-96: added checkAuthStatus function; lines 103,115: pass authMethod to login)
- `frontend/js/auth.js` (lines 23-36: updated login function to accept authMethod; lines 26,56,163: fixed API paths to /api/auth/*)

**Result**:
✅ Remote authentication fully implemented
✅ Configurable via .env (default) and AdminPanel (priority)
✅ Case-insensitive username/password matching
✅ Auto-creates users on first remote auth (is_remote_auth=True)
✅ Verifies password against remote API on each login
✅ Read-only mode - password_hash is random placeholder, not used for auth
✅ Database config prioritized over .env settings
✅ Graceful error handling for timeouts and network errors
✅ Audit logging for remote user creation
✅ Auth method selector shown only when remote auth is enabled
✅ Defaults to "Remote" when selector visible, allows switching to "Local"
✅ Local database auth always possible regardless of remote auth status
✅ Users can choose between remote and local authentication

**Design Notes**:
- KISS approach: Reused existing config management pattern, simple async HTTP client
- DRY: Config loading logic checks database first, falls back to .env consistently
- Security: API key stored in password field in admin UI, transmitted securely to backend
- Backward compatible: Existing local and Sybase auth still work, remote auth is opt-in
- Read-only enforcement: Remote users have random password_hash that's never used for verification
- Case-insensitivity handled by: 1) database lookup with `func.lower()`, 2) API itself handles case-insensitive matching

**CRITICAL LESSON LEARNED - ALWAYS VERIFY CONFIGURATION PRIORITY**:
**When implementing dual-config systems (env + database):**
1. ✅ **ALWAYS check database config first** - Database should take priority for runtime configurability
2. ✅ **Provide clear fallback chain** - Database → .env → default, document it clearly
3. ✅ **Test both config sources** - Verify env-only, db-only, and db-priority scenarios
4. ✅ **Document priority in UI** - Admin panel should indicate that database config overrides .env
5. ✅ **Audit config changes** - Log all config updates for security and compliance

**How to never make configuration mistakes again:**
- Always implement config loading as: check DB → check env → use default
- Add clear comments in code explaining priority chain
- Test with: 1) no config, 2) env only, 3) db only, 4) both (db should win)
- Document config priority in admin UI help text
- Use separate functions for loading from each source, compose them clearly
- Never mutate config objects - use immutable reads from each source

**Testing Recommendations** (for when docker is available):
1. Test remote auth with valid credentials (should create user and login)
2. Test remote auth with invalid credentials (should reject)
3. Test case-insensitive username (john vs JOHN vs JoHn should all match)
4. Test case-insensitive password (different cases should authenticate)
5. Test database config priority (set in both .env and DB, DB should win)
6. Test timeout handling (set very short timeout, verify graceful failure)
7. Test network error handling (invalid URL, verify fallback to local auth)
8. Test user auto-creation (first login should create user with is_remote_auth=True)
9. Test subsequent logins (remote_user_id should update if changed)
10. Test admin panel config save/load (verify all fields persist correctly)
11. **Test auth method selector UI**:
    - With remote auth disabled: selector should be hidden, only local auth works
    - With remote auth enabled: selector should be visible and default to "Remote"
    - Switch selector to "Local": should authenticate against local database
    - Switch selector to "Remote": should authenticate against remote API
12. **Test auth method API logic**:
    - auth_method="remote": should ONLY try remote, fail if remote auth fails (no fallback)
    - auth_method="local": should ONLY try local, skip remote entirely
    - auth_method="auto": should try remote first, fallback to local if remote fails
13. **Test /api/auth/status endpoint**: should return correct remote_auth_enabled value

---

### 2026-02-04 - Fix Missing Audit Logs (Element ID Mismatch)
**Issue**: After the previous system logs enhancement, the audit logs table appeared completely empty in the Admin Panel. No logs were displayed at all, even though the API was functioning correctly and returning data.

**Root Cause**: Element ID mismatch in the JavaScript `loadLogs()` function. The function was trying to populate a non-existent element:
- **Incorrect**: Function tried to populate `document.getElementById('log-entries')` (line 1145)
- **Correct**: The actual table body element has ID `logs-table-body` (line 502)

Since the element didn't exist, the logs were never rendered to the page, resulting in a completely empty table.

**Fixes Applied**:

1. **Admin HTML - Load Logs Function** (admin.html:1144-1271):
   - Changed target element from `log-entries` to `logs-table-body` (actual table tbody ID)
   - Updated to use proper API endpoint `/api/admin/logs/stream` instead of `getLogs()` helper
   - Fixed response handling to use `response.logs` array from API
   - Added proper query parameter building using URLSearchParams
   - Implemented table row creation (TR/TD elements) instead of div elements
   - Added full timestamp formatting (YYYY-MM-DD HH:mm:SS.milliseconds)
   - Added relative time formatting helper function
   - Extracted source/target directories from log.details for push/pull operations
   - Updated pagination info display using response.total_count and response.has_more
   - Fixed error display to show in table format (colspan 8)

**Files Modified**:
- `frontend/pages/admin.html` (lines 1144-1271: complete rewrite of loadLogs function and added formatRelativeTime helper)

**Result**:
✅ Audit logs now display correctly in the table
✅ All 8 columns populated with proper data
✅ Pagination works correctly with "Load More" button
✅ Full and relative timestamps both display
✅ Source/target directories extracted from details_json for push/pull operations
✅ Filtering and search functionality works

**CRITICAL LESSON LEARNED - ALWAYS VERIFY ELEMENT IDS**:
**When implementing UI changes:**
1. ✅ **ALWAYS verify HTML element IDs match JavaScript selectors** - Use browser DevTools or grep to confirm IDs exist
2. ✅ **Test the actual UI after making changes** - Even simple changes can break functionality
3. ✅ **Check for element existence before populating** - Add defensive checks like `if (!element) return;`
4. ✅ **Use consistent naming** - If table body is `logs-table-body`, don't reference `log-entries`
5. ✅ **Read the actual HTML structure** - Don't assume element IDs based on similar code elsewhere

**How to prevent this mistake in the future:**
- Before writing JavaScript to populate an element, search the HTML file for that element ID
- Use `document.getElementById()` checks and log warnings if element not found
- When copying code from another component, verify all element references are updated
- Always test functionality end-to-end after changes, even "simple" ones

**Design Notes**: This was a simple but critical bug - the fix was just changing one element ID and ensuring the data format matched the table structure. KISS approach - no complex logic needed, just proper element targeting. The mistake teaches the importance of verifying assumptions about the DOM structure.

### 2026-02-04 - Enhanced System Logs Display in Admin Panel
**Issue**: System logs in Admin Panel showed minimal information without proper table structure. Logs displayed only basic data and lacked source/target directory information for PUSH/PULL operations.

**Requirements**: Display comprehensive log information in a structured table:
- Full timestamp (YYYY-MM-DD HH:mm:SS.milliseconds format)
- Relative timestamp (Just now, X mins ago, X hours ago)
- Operation type (push, pull, login_success, worker_provision, etc.)
- Source directory (for push/pull operations)
- Target directory (for push/pull operations)
- User ID
- Username
- IP Address

**Fixes Applied**:

1. **Admin HTML - Table Structure** (admin.html:489-504):
   - Replaced simple div#log-entries with proper data-table structure
   - Added 8 columns: Timestamp, Time, Operation, Source Directory, Target Directory, User ID, Username, IP Address
   - Added pagination info display
   - Maintains existing log controls (filters, refresh, export)

2. **Admin JS - Logs Rendering** (admin-system.js:354-415):
   - Updated `renderLogs()` to extract source_directory and target_directory from details_json
   - Shows '-' for non-PUSH/PULL operations where directories aren't applicable
   - Displays full timestamp (YYYY-MM-DD HH:mm:SS.milliseconds format) as first column
   - Displays relative timestamps using formatRelativeTime() method as second column
   - Shows username or 'System' when user information not available
   - Updated column span from 6 to 8 for "No logs found" message

3. **Admin JS - Time Formatting** (admin-system.js:570-603):
   - Added `formatRelativeTime()` method to AdminSystem class
   - Formats timestamps as: "Just now" (<1 min), "X mins ago" (<1 hour), "X hours ago" (<24 hours), "X days ago" (<7 days)
   - Falls back to localized date/time for older entries
   - Handles invalid timestamps gracefully

**Files Modified**:
- `frontend/pages/admin.html` (lines 489-504: replaced log-entries div with 8-column table structure)
- `frontend/js/admin-system.js` (lines 354-415: updated renderLogs with YYYY-MM-DD HH:mm:SS.milliseconds timestamp formatting; lines 578-611: added formatRelativeTime)

**Result**:
✅ System logs display in structured table with all required columns
✅ Full timestamp displayed as first column for precise time reference
✅ Relative timestamps show "Just now", "X mins ago", "X hours ago" for quick reference
✅ PUSH/PULL operations show source_directory and target_directory from details_json
✅ User ID and Username displayed for all operations
✅ IP addresses visible for audit purposes
✅ Maintains existing filtering, refresh, and export functionality

**Example Display**:
```
Timestamp                   Time        Operation         Source Dir    Target Dir    User ID  Username  IP Address
2026-02-04 10:30:45.123     Just now    pull              B:/data       A:/data       2        john      192.168.200.7
2026-02-04 10:30:42.456     Just now    push              A:/test       B:/test       2        john      192.168.200.7
2026-02-04 10:29:15.789     1 min ago   login_success     -             -             2        john      192.168.200.7
2026-02-04 10:28:52.012     1 min ago   worker_provision  -             -             1        admin     192.168.200.7
2026-02-04 10:28:10.345     2 mins ago  user_create       -             -             1        admin     192.168.200.7
```

**Design Notes**: KISS approach - simple table structure with data extraction from existing details_json; DRY - reusable formatRelativeTime() method consistent with existing utils.js patterns; Dual timestamp display provides both precise time (for audit trail) and relative time (for quick reference); Maintains existing backend API contract - no backend changes needed as details_json already contains all required information

### 2026-02-04 - Fix PUSH Operation Failing with Null Reference Exception
**Issue**: PUSH operations failed immediately with "Object reference not set to an instance of an object" error from the worker. The operation created successfully but failed during execution when trying to verify the source directory exists.

**Root Cause**: The `list` command verification step in PUSH and two-worker operations was using incorrect parameter format. The worker expects the path in `params["path"]`, but the code was passing it as `source_path` instead. This caused a null reference exception on the worker side when it tried to read the missing `params["path"]` value.

**Incorrect Code**:
```python
verify_command = WorkerRequest(
    command="list",
    source_path=operation.source_path,  # WRONG - not read by worker
)
```

**Correct Code**:
```python
verify_command = WorkerRequest(
    command="list",
    params={"path": operation.source_path},  # Correct format
)
```

**Fixes Applied**:
1. **PUSH Operation Verification** (operation_service.py:798-801): Changed `source_path=operation.source_path` to `params={"path": operation.source_path}`
2. **Two-Worker Operation Verification** (operation_service.py:361-364): Changed `source_path=operation.dest_path` to `params={"path": operation.dest_path}`

**Files Modified**:
- `backend/api/services/operation_service.py` (lines 800, 363)

**Result**: ✅ PUSH operations now execute successfully; ✅ Source directory verification works correctly; ✅ Worker receives proper command parameters; ✅ No more null reference exceptions

**Design Notes**: KISS approach - used the same parameter format consistently across all `list` command usage; aligned with existing `list_directory()` method in worker_service.py

### 2026-02-04 - Fix PUSH/PULL Operations Stuck in PENDING (Double-Locking Deadlock)
**Issue**: After collision prevention changes (commit bf78d76), ALL operations created but never executed - stayed in PENDING status forever. Users saw operations in history but they never transitioned to IN_PROGRESS or COMPLETED.

**Root Cause**: Double-locking deadlock introduced by collision prevention fix. Path locks were added at TWO levels:
1. API endpoint level (app.py:596, 677) - acquired lock BEFORE creating operation
2. Execution level (operation_service.py:189) - `execute_operation()` tried to acquire SAME lock

Since `asyncio.Lock()` is not reentrant, the same async task cannot acquire the same lock twice. Flow:
1. Endpoint acquires lock for path "A:/test"
2. Inside lock: creates operation (PENDING) ✅
3. Inside lock: creates audit log ✅
4. Inside lock: calls `execute_operation()` which tries to acquire same lock ❌
5. **DEADLOCK** - hangs forever waiting for lock it already holds
6. Operation never transitions to IN_PROGRESS
7. Request times out or hangs indefinitely

**Fix Applied**: Remove duplicate path lock from `execute_operation()` method (operation_service.py:188-189)
- Path locking now only at API endpoint level (as intended by collision prevention fix)
- Lock acquired BEFORE operation creation ensures atomicity
- No need for second lock inside `execute_operation()` since caller already holds it

**Files Modified**:
- `backend/api/services/operation_service.py` (lines 188-189: removed async with lock block, unindented code)

**Result**: ✅ Operations now execute immediately after creation; ✅ Proper status transitions (PENDING → IN_PROGRESS → COMPLETED); ✅ No deadlocks; ✅ Collision prevention still works correctly

**Design Notes**: KISS approach - single lock point at API level is sufficient; collision prevention logic preserved; no duplicate locking needed

### 2026-02-04 - Improve Logging System for PUSH/PULL Operations
**Issue**: Admin Panel Log Viewer and syslog showed minimal information for PUSH/PULL operations - only generic field names (source, path_b, path_c) that weren't descriptive, and PULL operations were missing complete path information (source and archive directories).

**Example of Previous Logging**:
```
1 min ago   push   User ID: 2   IP: 192.168.200.76
Details: {"source": "A:/data", "path_b": "B:/data", "path_c": "C:/data"}
```

**Requirements**:
- PUSH/PULL logs should show: operation type, source directory, target directory, archive directory, user ID, username, and IP address
- Field names should be descriptive and consistent
- PULL operations should include complete path information from original PUSH operation

**Fixes Applied**:

1. **PUSH Operation Logging** (app.py:611-615):
   - Changed field names to be more descriptive:
     - `"source"` → `"source_directory"` (PATH_A)
     - `"path_b"` → `"target_directory"` (PATH_B)
     - `"path_c"` → `"archive_directory"` (PATH_C)
   - Already includes: user_id, username, ip_address, operation_id

2. **PULL Operation Logging** (app.py:692-697):
   - Added complete path information:
     - `"source_directory"` (PATH_B - where files are being pulled from)
     - `"target_directory"` (PATH_A - restore location)
     - `"archive_directory"` (PATH_C - from original PUSH operation)
     - `"original_operation_id"` (reference to original PUSH)
   - Already includes: user_id, username, ip_address, operation_id

**Result**:
✅ Admin Panel Log Viewer now displays complete operation details with clear field names
✅ Syslog messages include all path information (source, target, archive directories)
✅ PUSH operations: Shows source (PATH_A) → target (PATH_B) + archive (PATH_C)
✅ PULL operations: Shows source (PATH_B) → target (PATH_A) + archive reference (PATH_C)
✅ All logs include: operation type, user ID, username, IP address, and timestamp

**Example of Improved Logging**:
```
Admin Panel & Database:
1 min ago   push   User ID: 2   Username: john   IP: 192.168.200.76
Details: {
  "source_directory": "A:/data/project",
  "target_directory": "B:/data/project",
  "archive_directory": "C:/data/project"
}

2 mins ago   pull   User ID: 3   Username: alice   IP: 192.168.200.7
Details: {
  "original_operation_id": 123,
  "source_directory": "B:/data/project",
  "target_directory": "A:/data/project",
  "archive_directory": "C:/data/project"
}

Syslog (RFC 5424):
<134>1 2026-02-04T10:30:00Z hostname file-manager - - [filemanager user_id="2" operation_id="456" action="push" username="john" ip_address="192.168.200.76" source_path="A:/data/project" dest_path="B:/data/project"] User john performed push operation
```

**Files Modified**:
- `backend/api/app.py` (lines 611-615: PUSH logging; lines 692-697: PULL logging)

**Design Notes**: KISS approach - updated field names to be self-documenting; DRY - consistent naming across PUSH/PULL operations; Complete audit trail - all relevant paths logged for both operations; Backward compatible - existing syslog handler already supports these fields

### 2026-02-04 - Fix Path Logic Descriptions in Configuration Wizard
**Issue**: Configuration wizard displayed incorrect descriptions for Path B and Path C, causing confusion about operation flow.

**Wrong Descriptions**:
- Path B: "Archive location (backed up files)" ❌
- Path C: "Final storage (moved files)" ❌

**Correct Logic**:
- Path A: Source files
- Path B: Target (destination for PUSH operations)
- Path C: Archive (final storage after PUSH)

**Operation Flow**:
- PUSH: A → B (copy) + A → C (move)
- PULL: B → A (restore from target)

**Fixes Applied**:
1. **Worker Configuration Wizard** (Program.cs:178-189):
   - Updated Path B description: "Target (destination for PUSH operations)"
   - Updated Path C description: "Archive (final storage after PUSH)"
   - Added operation logic explanation to wizard output

**Files Modified**:
- `workers/FileManagerWorker/Program.cs` (lines 178-189)

**Verification**:
- ✅ Backend logic already correct (operation_service.py PUSH/PULL implementation)
- ✅ Frontend admin panel already has correct descriptions
- ✅ Database schema comments already correct
- ✅ Only configuration wizard had incorrect text

**Result**: ✅ Configuration wizard now displays correct path purposes and operation flow

**Design Notes**: KISS approach - corrected misleading descriptions to match actual operation logic; DRY - verified rest of codebase already had correct understanding

### 2026-02-04 - Fix Worker PathC/PathB/PathA Prefix Configuration
**Issue**: PathCPrefix (and PathAPrefix, PathBPrefix) set in App.config were not being applied. The `/config` wizard didn't prompt for these values and didn't store them in secure storage (DPAPI), causing workers to always use hardcoded defaults.

**Root Cause**: Path prefixes were only read from App.config file with hardcoded defaults, but were NOT stored in the SecureConfigStorage (DPAPI) system. The `/config` wizard only saved ApiUrl, ServiceUser, and ServicePassword to secure storage.

**Fixes Applied**:
1. **SecureConfigStorage.cs**: Added PathAPrefix, PathBPrefix, PathCPrefix to ConfigData class (lines 31-33)
2. **SecureConfigStorage.cs**: Updated SaveConfiguration() to accept and store path prefixes with defaults (lines 39-40, 57-59)
3. **SecureConfigStorage.cs**: Updated LoadConfiguration() to return path prefixes (lines 92-93, 98-100, 128-130)
4. **Program.cs**: Added path prefix prompts in `/config` wizard with defaults (lines 178-199)
5. **Program.cs**: Updated SaveConfiguration call to include path prefixes (line 226)
6. **Program.cs**: Updated HandleInstall to load and display path prefixes (lines 428-429, 445-447)
7. **WorkerService.cs**: Updated LoadConfiguration to load paths from secure storage with App.config fallback (lines 255-257, 262-263, 307-319, 327-329)

**Files Modified**:
- `workers/FileManagerWorker/SecureConfigStorage.cs` (ConfigData, SaveConfiguration, LoadConfiguration)
- `workers/FileManagerWorker/Program.cs` (HandleConfig, HandleInstall)
- `workers/FileManagerWorker/WorkerService.cs` (LoadConfiguration)

**Result**: ✅ Path prefixes now properly configured during `/config` wizard; ✅ Stored securely in DPAPI; ✅ App.config serves as fallback for backward compatibility; ✅ Worker logs show loaded path prefixes on startup

**Configuration**: Run `FileManagerWorker.exe /config` and enter path prefixes when prompted (or press Enter for defaults: C:\PathA, C:\PathB, C:\PathC)

**Design Notes**: KISS approach - added path configuration to existing secure storage system; DRY - reused existing DPAPI encryption; backward compatible - App.config still works as fallback

### 2026-02-04 - Improve Audit Logs with Real Client IP and Enhanced Syslog
**Issue**: Application running behind Traefik reverse proxy captured Traefik's IP instead of real client IP. Audit logs needed real client IP, and syslog messages lacked operation details (directory, username).

**Requirements**:
1. Capture real client IP from Traefik headers (X-Forwarded-For, X-Real-IP)
2. Ensure PUSH/PULL operation logs contain: operation ID, directory, username, time, and real client IP
3. Send operation logs to syslog if configured
4. Make logs available in Admin Panel and syslog with complete information

**Root Causes**:
1. **Wrong IP Capture**: Application used `request.client.host` which returns Traefik's IP, not the original client
2. **Traefik Headers**: Traefik forwards real client IP in `X-Forwarded-For` (leftmost IP is original client) and `X-Real-IP`
3. **Incomplete Syslog**: Syslog messages only included user_id, operation_id, action, and level - missing IP, username, and directory
4. **No Syslog for Operations**: PUSH/PULL operations only logged to database, not to syslog (logging_module not initialized)

**Fixes Applied**:
1. **Client IP Utility** (api/middleware/logging.py:23-58):
   - Created `get_client_ip(request)` function to extract real IP from Traefik headers
   - Priority: X-Forwarded-For (leftmost) → X-Real-IP → request.client.host (fallback)
   - Handles comma-separated proxy chains correctly

2. **Updated All IP Capture Points** (6 files, 30+ occurrences):
   - Replaced all `request.client.host if request.client else None` with `get_client_ip(request)`
   - Files: app.py, routes/auth.py, routes/admin.py, routes/admin_system.py, routes/preferences.py
   - Also updated RequestLoggingMiddleware to use new function

3. **Enhanced Syslog Handler** (logging_module/handlers.py:177-225):
   - Added ip_address to structured_data
   - Added operation-specific fields: source_path, dest_path, operation_type (for OperationLog)
   - Added username from details if present
   - Added directory info (extracts from "source" or "restore_to" in details)
   - Converts user_id and operation_id to strings for RFC 5424 compliance

4. **Integrated Syslog for Operations** (api/middleware/logging.py:295-352):
   - Modified `AuditLogger.log_operation()` to accept username parameter
   - Added call to logging_module's `log_operation()` to send to syslog (if configured)
   - Includes username in details and message
   - Graceful fallback: database audit log always created even if syslog fails

5. **Pass Username to Audit Logger** (app.py:602, 682):
   - PUSH operation: Added `username=current_user.username` to log_operation call
   - PULL operation: Added `username=current_user.username` to log_operation call
   - Username now included in both database and syslog logs

6. **Initialize Logging Module** (app.py:51-57, 93-99):
   - Added logging_module initialization in application startup (lifespan)
   - Graceful handling: logs warning if initialization fails, app continues
   - Added close_logging() call in shutdown for proper cleanup

**Files Modified**:
- `backend/api/middleware/logging.py` (lines 23-58: get_client_ip; 97, 295-352: AuditLogger enhancement)
- `backend/api/app.py` (lines 26: import get_client_ip; 51-57: init logging_module; 93-99: close; 602, 682: add username; all ip_address captures)
- `backend/api/routes/auth.py` (lines 21: import; all ip_address captures)
- `backend/api/routes/admin.py` (lines 15: import; all ip_address captures)
- `backend/api/routes/admin_system.py` (lines 22: import; all ip_address captures)
- `backend/api/routes/preferences.py` (lines 14: import; all ip_address captures)
- `backend/logging_module/handlers.py` (lines 177-225: enhanced SyslogHandler.write_log)

**Result**:
✅ Real client IP captured from Traefik headers across all audit logs
✅ Admin Panel shows real client IPs
✅ Syslog messages include operation ID, username, directory, IP address, and timestamp
✅ PUSH/PULL operations logged to both database and syslog (if configured)
✅ Backward compatible - works with or without syslog configuration

**Configuration**: To enable syslog, set environment variables:
- `ENABLE_SYSLOG=true`
- `SYSLOG_HOST=your.syslog.server`
- `SYSLOG_PORT=514` (default)
- `SYSLOG_PROTOCOL=UDP` or `TCP`

**Syslog Message Format** (RFC 5424):
```
<134>1 2026-02-04T10:30:00.000000Z hostname file-manager - - [filemanager user_id="1" operation_id="123" action="push" level="INFO" ip_address="192.168.1.100" username="john" directory="A:/data/folder"] User john performed push operation
```

**Design Notes**: KISS approach - single utility function for IP extraction used everywhere; DRY - reusable get_client_ip() function; graceful degradation - app works without syslog, logs to database always; proper Traefik integration - handles X-Forwarded-For proxy chains correctly.

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

## 🎯 PERMANENT LESSONS - CODE QUALITY PRINCIPLES

### ⚠️ CRITICAL: Preventing Duplicate Code (DRY Principle Violations)

**BEFORE writing any new function, component, or module:**

1. **✅ SEARCH FIRST** - Always search the entire codebase for existing implementations
   ```bash
   # Search for similar functions/features
   rg -i "function_name|feature_name" --type js --type py

   # Check inline HTML scripts for duplicates
   rg -i "addEventListener|async function" frontend/pages/*.html
   ```

2. **✅ CHECK BOTH HTML AND JS** - Inline scripts in HTML often duplicate .js modules
   - Before adding inline JavaScript in .html files, check if a .js module already exists
   - If both exist, the .js module should be the single source of truth
   - HTML should import and call .js functions, not reimplement them

3. **✅ EXTRACT, DON'T DUPLICATE** - If you find similar code in multiple places:
   - Extract to a shared module/function
   - Export as standalone functions if needed (like loadConfigurationData/saveConfigurationData)
   - Import and reuse, never copy-paste

4. **✅ REFACTOR CHECKLIST** - When modifying functionality:
   - [ ] Search entire codebase for ALL references (use `rg -i` without file filters)
   - [ ] Check .html files for inline `<script>` blocks
   - [ ] Check .js modules for similar functions
   - [ ] If duplicates found, consolidate into single source of truth
   - [ ] Update all call sites to use consolidated version

5. **✅ CODE REVIEW RED FLAGS** - These indicate DRY violations:
   - Same fieldMapping/config object in multiple files
   - Same event listener logic in .html and .js
   - Similar function names (loadConfig vs loadConfiguration)
   - Copy-pasted code blocks with minor differences

**How This Principle Prevented Bugs:**
- Previous bug: admin.html inline script had outdated Sybase fields → Polka settings didn't persist
- Root cause: Two separate implementations (admin.html inline + admin.js) got out of sync
- Solution: Remove duplicate, use single source of truth (admin.js)
- Future: Any config changes only need to happen in ONE place

**Remember:**
- "Don't Repeat Yourself" (DRY) isn't just about code size
- It's about maintainability: ONE place to fix bugs, ONE place to add features
- Always ask: "Does this already exist somewhere else?"
- If yes: refactor to reuse. If no: make it reusable from the start.

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
