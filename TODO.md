# TODO - RFM (Remote File Manager)

> **Project:** File operation management system with microservices architecture
> **Status:** Active Development
> **Last Updated:** 2026-02-06

---

## ACTIVE TODO ITEMS

### Current Sprint
- [ ] Verify Admin Panel loads and functions properly after export fix
- [ ] Test theme switching (System/Light/Dark) in user Settings panel
- [ ] Create DB migration to drop removed columns: `show_hidden_files`, `default_sort_by`, `default_sort_order`, `items_per_page` from `user_preferences` table (columns removed from code in 2026-02-06 cleanup, still exist in DB harmlessly)

### Testing Checklist
- [ ] Push Operation: Select directory in Path A -> verify copy to PATH_B and move to PATH_C
- [ ] Push Operation: Verify operation appears in queue with real-time status updates
- [ ] Pull Operation: Select completed Push -> verify restore to original location
- [ ] Pull Operation: Verify directory removed from PATH_B after pull
- [ ] Error Handling: Test invalid directory, missing paths, insufficient permissions
- [ ] Admin Panel: Change PATH_B and PATH_C -> verify new operations use new paths
- [ ] Admin Panel: Verify non-admin users cannot change paths
- [ ] Worker: Integration testing in staging environment
- [ ] Remote Authentication: Test login with remote API enabled
- [ ] Remote Authentication: Verify case-insensitive username/password matching
- [ ] Remote Authentication: Verify auto-creation of users on first remote auth
- [ ] Remote Authentication: Verify database config takes priority over .env
- [ ] Remote Authentication: Test timeout and error handling

### Future Improvements
- [ ] Refactor admin.html to remove remaining inline `<script>` logic — let admin.js handle everything via AdminSystem class (DRY)
- [ ] i18n implementation for multi-language support (ui_language field already in preferences)
- [ ] Consider migrating to a component framework (React/Vue) for better DOM/JS sync and type safety

---

## COMPLETED (Compact Log)

### 2026-02-06 - Cleanup Settings and Login Screen
- Removed unused "File Listing" settings section from Settings modal (Default Sort By, Sort Order, Items Per Page) — these preferences were stored but never applied; actual sorting is done via clickable column headers
- Removed "Show hidden files" toggle from Settings — stored in DB/preferences but never passed to file listing API or used in filtering logic (half-implemented feature)
- Cleaned up all references: `explorer.html`, `app.js` (openSettingsModal save/load/reset), `models.py`, `schemas.py`, `preferences.py`
- DB columns (`show_hidden_files`, `default_sort_by`, `default_sort_order`, `items_per_page`) left in place (no migration) — harmless, migration TODO added above
- Login screen: moved Authentication Method section below Remember Me
- Login screen: renamed "PolkaSQL Authentication" to "PolkaSQL", "Local Authentication" to "Local"
- Login screen: removed Sybase description text and "Remote File Manager v1.0" footer label

### 2026-02-05 - Admin Panel Freeze Fix + Theme Fix
- Fixed admin.js crash: missing `showNotification` export in utils.js (added alias for `showToast`)
- Fixed theme switcher: added `body[data-theme="dark"]` CSS variables that were missing
- Fixed Settings modal crash: removed stale `pane-layout` element references
- Added System theme option (follows OS preference via `prefers-color-scheme`)
- Added language selection field (English only, ready for i18n)
- Implemented Path A directory remembering (last_path_a saved/restored)

### 2026-02-05 - PolkaSQL Auth Fixes (3 rounds)
- Fixed config key mismatch: `enable_polka_auth` -> `polka_auth_enabled` across Settings class, .env, auth.py
- Fixed Admin Panel inline script fieldMapping: Sybase keys -> Polka keys in admin.html
- Removed duplicate config loading from admin.html inline script (DRY: now uses admin.js exports)
- Fixed login failure when PolkaSQL disabled: hidden auth selector defaulting to 'polka' instead of 'local'
- Added missing imports in auth.py (`func`, `UserRole`)

### 2026-02-05 - Remote Authentication (PolkaSQL) Implementation
- Full remote auth against external PolkaSQL API with case-insensitive credentials
- Auto-user-creation on first remote login (`is_remote_auth=True`)
- Dual config: .env defaults, database config takes priority
- Auth method selector on login (shown only when PolkaSQL enabled)
- Admin Panel UI for configuring PolkaSQL settings

### 2026-02-04 - Admin Panel Fixes
- Fixed missing audit logs (element ID mismatch: `log-entries` -> `logs-table-body`)
- Enhanced system logs with structured table, pagination, filtering, relative timestamps
