# Completed Work - RFM (Remote File Manager)

> **Chronological log of completed features, fixes, and improvements**
> **Purpose:** Track project progress and implementation history
> **Last Updated:** 2026-09-17

---

## 2026-09-17 - Secret rotation script; promotion script brought up to date

**Why.** Internal secrets (`.env`) and external API keys (`config` table) are plain text readable by anyone with shell/docker access on the host, which includes AI coding tools. Encrypting them cannot keep out a user in the `docker`/`sudo` groups, so secrets are rotated after such sessions instead.

**`scripts/rotate-secrets.sh`** (`dev`, `prod`, or both; `--dry-run`, `--force`): new random `POSTGRES_PASSWORD`, `REDIS_PASSWORD` (256-bit hex) and `SECRET_KEY`, one ENTER to confirm.
- Preflight: required keys present, `DATABASE_URL`/`REDIS_URL` either reference `${POSTGRES_PASSWORD}`/`${REDIS_PASSWORD}` or contain the literal password (rewritten), compose services exist, containers running, no PENDING/IN_PROGRESS operations.
- Values move only through files and pipes, never argv or output. The role password goes to PostgreSQL as a SCRAM-SHA-256 verifier computed locally (no plain text in server logs). `.env` is replaced atomically and set to 600; the backup is removed on success.
- `docker compose up -d --no-build` for postgres/redis/api, then checks each container really restarted and `/health` reports `database` and `redis` true.
- On failure, prints the state per stage and how to recover (rerunning is always safe: the DB socket inside the container needs no password).
- Lists external keys still set in `.env` and the `config` table, and active users that still accept `admin123`/`INITIAL_ADMIN_PASSWORD`.

**`scripts/promote-dev-to-prod.sh`** had fallen behind (migrations 014-020):
- Preflight checks the backup directory is writable (`/opt/docker/rfm-vf-backups` is owned by root, so the first real promotion would have failed after the confirmation) and that local `vf` matches `origin/vf`.
- Backups are created 700; `pg_dump --clean --if-exists` so the printed restore command works on the existing database.
- Verifies the database is at the Alembic head of the promoted tree instead of only printing the version.
- Rollback note covers 012-020 (all additive); rollback command runs the dev copy of the script (the rollback resets the prod tree); `die` after the backup also prints it.
- Post-promotion notes list the behaviour changes since `vf`: 5-day sessions and admin password confirmation, OS metadata files ignored and destroyed on PUSH, `<number>.<ext>` file names.

**Verified.** SCRAM verifier against a throwaway role over the Docker network (right password accepted, wrong rejected); `.env` rewrite on a fake file (quotes, literal and `${}` URLs, mismatch and duplicate keys refused); full rotation of dev (40 s, API healthy on new passwords, backup removed, `.env` 600); promotion `--dry-run` up to the dirty-tree check.

---

## 2026-09-17 - Explorer: right-click "Push", button states, Polish dates and numbers

Found while writing the Polish user guide (`docs/instructions/`).

**Right-click "Push >" did nothing.** The Path A context menu offered `push`, but `handleContextMenuAction` (`frontend/js/app.js`) had no case for it. It now selects exactly the right-clicked folder and runs the normal PUSH (same confirmation and validation); a file or `..` shows "Select a directory (not a file)".

**Push/Pull/Update stayed enabled with nothing selected.** Button state was recomputed only on checkbox/radio `change` events. Re-renders that drop a selection fire none: after a PUSH (the folder leaves Path A, `clearSelection` sets `checked` directly), after navigating to another folder, after a PULL (the pulled PUSH loses its radio). `updateVFButtonStates()` now runs after every Path A and history render and after the post-PUSH `clearSelection`.

**Dates, times and numbers in the UI language.** `formatDate` returned hard-coded English ("5 mins ago", "Mar 30, 2026, 01:06 PM"), the history used its own English "5m ago", full timestamps used the browser locale, and sizes always used a dot. Now in `utils.js`: `formatDate` (relative via `time.*` keys, older dates via `toLocaleString(uiLocale)`), new `formatDateTime` (history tooltip, operation details, PIM/sync tooltips), `formatFileSize` with the locale decimal separator. PL: "Przed chwilą", "31 min temu", "4 godz. temu", "1 dzień temu", "3 dni temu", "17.09.2026, 15:42:47", "1013,75 KB". The admin panel loads no translations, so these fall back to English there. New key `time.oneDayAgo` (Polish "1 dzień", not "1 dni"); en-US time keys aligned with the fallback.

**Other untranslated strings on user pages.** History "Unknown" user, "unknown error" in PUSH batch failures, Windows deep-link "Folder not found" / "No paths could be resolved", device approval "Unknown error". `resolveWindowsPath` now uses `apiRequest`: it read `error.detail` from a `{"error": ...}` body, so every failure said "Failed to resolve path". `handlePushAction` printed a raw `{error}` placeholder. The admin panel itself is still English only.

**Verified** with Playwright against the dev WebUI in pl-PL and en-US (no console errors or missing keys), the English fallback on a page without i18n, and after redeploy real runs as `tester`: PUSH #35/#36 (Push disabled afterwards), PULL #37 and #41 (Pull/Update disabled afterwards), UPDATE #38-#40, right-click push of one folder while another was ticked (#42, only the right-clicked one pushed; pulled back in #43).

## 2026-09-17 - Session lifetime, "Remember me", admin password confirmation

**Why.** WebUI users were logged out every 30 min: `auth.js` ignored the server's `expires_in` and hard-coded 30 min in `sessionStorage` (see LESSONS_LEARNED). The Admin Panel's "Session Lifetime (days)" was never read; the API used env `ACCESS_TOKEN_EXPIRE_DAYS` (30).

**Session policy** (config table, Admin Panel > Configuration > Session & User Management; env `SESSION_LIFETIME_DAYS` / `SESSION_REMEMBER_ME_DAYS` / `ADMIN_REAUTH_MINUTES` seed it only when set):
- `session_lifetime_days` = 5: admins, and users without "Remember me". The token lives in `sessionStorage` (ends with the tab).
- `session_remember_me_days` = 30: "Remember me" / "Zapamiętaj mnie" (the checkbox existed but did nothing). Token in `localStorage`, survives closing the browser. Never for admins: the API ignores the flag for them, also on refresh (a promoted user loses it). The login page says so under the checkbox.
- Windows client device flow sessions count as remembered (not for admins). `ACCESS_TOKEN_EXPIRE_DAYS` removed.
- An open page refreshes its token once half of the lifetime has passed (every minute and when the tab becomes visible); the server extends it by the current policy.

**Expired session -> login.** `redirectToLogin()` for: a stored session past its expiry, any 401 (fetch and upload), WebSocket closed 1008, failed refresh. It goes to `login.html?expired=1&return=<page>`, which shows "Your session has expired" (EN/PL) and returns to the page after sign-in. `return` must be same-origin (it was followed blindly before). The admin page now also refreshes its session.

**Admin password confirmation.** `require_recent_auth` guards changes to system settings: users (create/update/delete), workers (update/approve/suspend/delete/provision), config (PUT, POST, bulk), Samba paths, logging config. The password must have been typed in this session within `admin_reauth_minutes` (15); login counts, approving a device does not. Otherwise 403 `{"code": "reauth_required"}`; `apiRequest` opens a password dialog (a `<form>` with read-only `autocomplete="username"` and `autocomplete="current-password"`, so password managers fill it), `POST /api/auth/reauthenticate` (local hash or PolkaSQL; wrong password is 403 and keeps the session; audit `reauthenticate` / `reauthenticate_failed`), then retries the request once. Cancel/Escape sends nothing ("Password not confirmed. Nothing was changed."). Operational actions (worker commands, stop-all, test path, indexing) are not guarded.

**Schema.** Migration `020`: `sessions.remember_me`, `sessions.reauthenticated_at`; seeds `session_remember_me_days`, `admin_reauth_minutes`; `session_lifetime_days` 30 -> 5 unless set by hand. Existing sessions keep their expiry; admins confirm their password on the first settings change.

**Tests.** 111 passed, 17 errors (pre-existing `test_auth.py` fixture), PostgreSQL 16. `test_session_policy.py` (6) over HTTP through the real app: lifetimes with/without remember for user and admin, adjustable lifetime followed by refresh, promotion drops remember, expired session 401, guarded bulk/PUT config and user creation refused past the window with nothing written, reads unguarded, wrong password keeps the session, confirmation unlocks, audit rows, adjustable window, device flow sessions (admin device session must confirm). Mutation-checked: remembering admins, accepting sessions never confirmed, ignoring the configured window, login not counting, unguarding bulk config each turn a test red. Migration 020 downgrade/upgrade round-trip, hand-set value kept. Browser: 39 Playwright checks against the dev WebUI with a mocked API (storage per remember/admin, EN/PL labels and hint, expired notice and return with hash, foreign return ignored, 401 and WS 1008 redirects, half-life refresh, admin session fields load/save, dialog attributes, wrong password, retry once, Escape cancels, PL texts). They caught a real bug: parallel 401s overwrote the redirect and lost `expired=1`.

---

## 2026-09-17 - PULL reports eventType "deleted" to PIM

**Bug.** Dev PULL #21 (`OZDOBA PS261403 0-BRASS`) sent PIM `eventType "updated"` (event 13, delivered 200). PULL removes the catalog from PATH_B, so PIM must hear `deleted`. The code default, `Settings`, the env sync fallback, `.env.example` and the value seeded by migration 012 all said `updated` (the original mapping); PIM keys sync from env only when set, so the seeded DB value was what counted.

**Fix.** Default `deleted` in `pim_service._EVENT_TOGGLES`, `config.py`, `app.py`, `.env.example` and the Admin Panel placeholder. Migration `019` switches `pim_pull_event_type` from `updated` to `deleted`; any other operator-set value is kept (downgrade reverses only `deleted`). PUSH (`created`) and UPDATE (`updated`) unchanged.

**Tests.** 105 passed, 17 errors (pre-existing `test_auth.py` fixture), PostgreSQL 16; the PULL assertions in `test_pim_delivery_and_sync.py` and `test_update_uploads.py` now expect `deleted`. Migration 019 downgrade/upgrade round-trip, custom value left alone.

---

## 2026-09-17 - Stop pending PIM deliveries and image host checks

**What.** Queued background jobs can now be stopped instead of retrying for up to 72 h (e.g. dev event 1, PUSH #9, stuck on 422).
- **PIM:** a PENDING event (not yet attempted, or retrying) becomes `CANCELLED` with `cancelled_at`/`cancelled_by`. It is never attempted again and no longer holds back later events of its catalog. "Send to PIM again" clears the stop and delivers.
- **Image host sync:** a WAITING or CHECKING check becomes `CANCELLED` with `cancelled_by`. Unlike a PULL's cancellation (no `cancelled_by`, catalog gone), "Check image host again" restarts it. Stopping works while verification is disabled, so leftovers can be cleared.
- Stopped rows stay in the history; nothing is deleted. Finished jobs (DELIVERED, FAILED, SYNCED, TIMEOUT) have nothing to stop: 409.

**Races.** Each stop is one conditional `UPDATE ... RETURNING`. An attempt or check already under way when stopped keeps running, but its result is discarded (the existing "apply only to an unchanged row" guards); a PIM request already on the wire may still reach PIM.

**API.** `POST /api/operations/{id}/pim/stop`, `POST /api/operations/{id}/remote-sync/stop` (any user, like retry; 404 without a job, 409 when not active; audit `pim_stop` / `remote_sync_stop`). Admin: `GET /api/admin/integrations/queue` (pending / retrying / waiting / checking counts), `POST /api/admin/integrations/pim/stop-all`, `POST /api/admin/integrations/remote-sync/stop-all` (audit `pim_stop_all` / `remote_sync_stop_all` with the operation ids). Responses carry `cancelled_at`/`cancelled_by`. One WebSocket refresh per bulk stop. Migration `018` adds the columns; its downgrade turns stopped PIM events into FAILED so they are not sent.

**UI.** Operation details: "Stop sending to PIM" / "Stop checking image host", each behind a confirmation; "Stopped: <time> by <user>". Badges `PIM: stopped`, `Sync: stopped n/m` (PULL keeps `Sync: cancelled`), tooltip names who stopped it. Admin Panel: Notification Queue under PIM and Active Checks under Image Host Sync, with live counts and "Stop all" (disabled when empty). EN + PL, 311 keys each.

**Tests.** 105 passed, 17 errors (pre-existing `test_auth.py` fixture), real PostgreSQL 16: stop a retrying event -> no attempts -> 409 twice / 404 -> send again -> delivered; a stopped PUSH event releases its UPDATE event; stop during an attempt discards a 200; stop during a probe discards served files, then restart -> SYNCED; PULL-cancelled check cannot be restarted; admin counts, stop-all of each kind leaves finished jobs alone; audit rows. Mutation-checked (in-flight guard, PULL restart guard, clearing the stop on retry): each turns a test red. Migration 018 downgrade/upgrade round-trip. Browser: 35 Playwright checks against the dev WebUI with a mocked API (badges and tooltips in en-US/pl-PL, buttons per state, cancelled confirmation sends nothing, confirmed stop posts once and refreshes, Admin Panel counts / disabled / stop-all). They caught a real bug: `showDialog` resolves `{confirmed}`, so `!await showDialog(...)` never saw Cancel.

---

## 2026-09-17 - Ignore OS metadata files on PUSH (`.DS_Store` blocked a catalog)

**Report.** `A:/olek/AKCESORIA 001GDM301031M 0-YELLOW` (4 images, 5 files) was refused by the new PIM file name rule: "Rename or remove: .DS_Store". macOS metadata is not catalog content and may be destroyed.

**Fix.** New `push_ignore_system_files` (**on by default**, migration `017`, env `ENABLE_PUSH_IGNORE_SYSTEM_FILES`, Admin Panel -> PUSH Operation Settings -> Ignore operating system files). While on, `SYSTEM_FILE_MASKS` (`.DS_Store`, `._*`, `.localized`, `.apdisk`, `Thumbs.db`, `ehthumbs.db`, `desktop.ini`) are added to `push_ignore_file_masks` (case-insensitive, no duplicates) by one helper, `ignore_masks_from_config`, used by:
- content validation (PUSH and UPDATE): not counted, not name-checked, not sent to PIM
- PUSH execution: the worker does not copy them, and archive cleanup destroys them (no worker change, it already takes `ignore_masks`)
- `/api/config/push-settings`: the push confirmation lists the effective masks

The toggle lives in the optional env block, so an Admin Panel change survives restarts (unlike `push_ignore_file_masks`, see TODO).

**Tests.** 99 passed, 17 errors (pre-existing `test_auth.py` fixture). Unit: default/off/deduplicated masks, the reported folder shape (`.DS_Store`, `._1.jpg`) valid by default and refused when off. End to end through `push_operation`: off -> 422 naming `.DS_Store`, `._1.png`, `desktop.ini`; on -> completed, only `1.png`/`2.png` copied, the copy command carries the masks, PIM body `["1.png", "2.png"]`, confirmation shows the masks. Mutation: defaulting the toggle to off fails both unit tests.

---

## 2026-09-17 - PIM 422 on `Thumbs.db`; PIM file name rule in preflight

**Bug.** PUSH #9 (`A:/olek/TORBA HB0788 FA0542-910 SILVER`, 7 files) completed, but PIM answered `HTTP 422 ... "files[7]": Nazwa pliku musi mieć format "<numer>.<rozszerzenie>"` on every retry. The event's `files` were `["1.png", ..., "7.png", "Thumbs.db"]`.
- **Root cause:** preflight `validate_dir` lists *every* top-level file, and that list was stored on the operation for PIM. The copy then skips `push_ignore_file_masks` (`Thumbs.db`), so PIM was told about a file that never reached Path B, with a name PIM rejects. Retries resend the stored list, so they cannot succeed.
- **Fix:** `validate_directory_content` drops files matching `push_ignore_file_masks` from `files`, `non_image_files`, `invalid_files` and the counts. Matching is the worker's `MatchesIgnoreMask` (case-insensitive, exact or `*`/`?` glob): `matches_ignore_mask`, `parse_ignore_masks` (also used by PUSH execution now). Applies to PUSH and UPDATE (a `Thumbs.db` in a Path B catalog stays out of PIM too).

**PIM file name rule** (`push_validation_file_names`, **on by default**, env `ENABLE_PUSH_VALIDATION_FILE_NAMES`, Admin Panel -> Content Validation -> Require PIM File Names).
- Every (non-ignored) file must fullmatch `[0-9]+\.[A-Za-z0-9]+` (ASCII digits only, e.g. `3.png`); otherwise preflight fails with `contentValidation.invalidFileNames` and `invalid_names`, before anything is copied: single PUSH and UPDATE -> 422, batch PUSH -> per-directory `validation_failed`, `/api/operations/preflight` -> `ok: false`.
- `invalid_names` is filled even when another rule fails first (e.g. too few images), and the WebUI shows both messages at once. A rejected name is left out of the "non-image files will still be sent to PIM" note.
- UPDATE judges the names after its actions: renaming `front.png` -> `2.png` fixes a catalog pushed before the rule, adding `back.png` is refused.
- The rule needs the listing, so it is off while `push_validation_enabled` is off.
- Migration `016` seeds the key (`ON CONFLICT DO NOTHING`). `ContentValidationResponse` gains `invalid_names`. EN + PL message (300 keys each).

**Tests.** 96 passed, 17 errors (pre-existing `test_auth.py` `db_session` fixture), on a disposable PostgreSQL 16:
- `test_content_validation.py`: mask matching like the worker (case, globs, regex metacharacters), the name regex (incl. `1.png.bak`, `1 .png`, Arabic-Indic digit), ignored files and counts, rule default-on / off, names reported alongside `tooFewImages`.
- `test_pim_delivery_and_sync.py`, through the real endpoints with the fake worker and a mock PIM: the PUSH -> UPDATE -> PULL flow now has a `Thumbs.db` in the source (not copied, not in either PIM body); a bad name refuses preflight, PUSH and batch PUSH with no worker command but `validate_dir`, no operation, no PIM call, then passes once renamed; the rule switched off; UPDATE judged after its actions.
- `update_fakes.FakeWorkerService` now honours `ignore_masks` on copy and reports non-images by extension, like the worker.
- Mutation-checked: removing the mask filter fails 6 tests; removing the UPDATE re-judgement fails the UPDATE test.
- WebUI message rendering checked with Node against both locale files.

---

## 2026-09-16 - Worker docs: README-INSTALLER.md matches the real deployment

`workers/README-INSTALLER.md` described the unused `workers/Installer/` project (`/install /url /user /pass`, `worker.config`, `C:\Program Files\FileManager\Worker`). Rewritten from `Program.cs`, `WorkerService.cs`, `CertificateManager.cs` and `/api/workers/register`: `/config` then `install`, `config.dat` (DPAPI) plus a `LocalMachine\My` certificate, Network Service, and step-by-step fresh install, update, reconfigure, reinstall and removal. Also documents hostname-based identity, worker statuses (OFFLINE returns to ACTIVE on its own, SUSPENDED doesn't), the Samba impersonation model, and that `/debug` looks in `CurrentUser\My`, which `/config` doesn't populate.

---

## 2026-09-16 - PIM: tgId from PolkaSQL, reliable delivery; image host sync verification

**tgId.** Confirmed from `Polka27.elementy`: `tgId` is `grup_nazwe` of the product row, `imageCatalog` is `grup_nazwe_kolor` (`TORBA HB0788 FA0542` / `TORBA HB0788 FA0542-910 SILVER`, `OZDOBA PS261403 0` / `OZDOBA PS261403 0-BRASS`). `RFM_sp_ValidateProductName` already matches `grup_nazwe_kolor`, so it now also returns `tg_id` from the matched row (`docs/polkasql/RFM_ValidateProductName.sql`, ALTER PROCEDURE only). No second procedure/web service. The suggestions for a miss are unchanged.
- PUSH/UPDATE store `tg_id` on the operation (`params_json`); PULL uses its PUSH's.
- When it was not captured (the validation gate is off, or the operation predates this), delivery looks it up through the same web service (`lookup_tg_id`, independent of `catalog_validation_enabled`, needs URL + key). An unresolvable tgId is a failed attempt and is retried. The event is never sent without it.
- Default template is now `{"tgId": "{tg_id}", "imageCatalog": "{catalog_name}", "eventType": "{event_type}", "files": {files}}`. Migration 015 switches a DB still holding the old default, leaves an edited template alone, and removes the static `pim_tg_id` setting (a single value for every product was never right).

**Reliable PIM delivery** (`api/services/pim_service.py`, table `pim_events`). The old fire-and-forget `asyncio.create_task` lost the event on any PIM/network error or restart.
- Transactional outbox: the event (event type, files, catalog, tgId, user) is stored when the operation completes, then delivered right away (`kick_delivery`) and by a 5 s loop in every API process.
- Claimed with `FOR UPDATE SKIP LOCKED` + a lease (`pim_timeout + 120 s`), so 4 uvicorn processes never double-send, and a process that dies mid-attempt only delays the event.
- Any failure (connect error, timeout, non-2xx, missing URL/token, invalid template, unresolved tgId) -> retry after `pim_retry_base_seconds` doubling up to `pim_retry_max_delay_seconds`, ±20% jitter. After `pim_retry_max_hours` (default 72, 0 = never) it becomes FAILED.
- Per-catalog ordering: an event waits while an older event of the same catalog is pending, so PIM never gets `updated` before `created`.
- URL, token and template are read per attempt, so fixing the configuration also fixes queued events. While `pim_enabled` is off nothing is queued, and already-queued events are held.
- `POST /api/operations/{id}/pim/retry` (details dialog, audit-logged): FAILED gets a fresh window, PENDING skips its remaining delay.
- Trade-off: a timeout after PIM processed the request re-sends it (at-least-once).

**Image host sync verification** (`api/services/remote_sync_service.py`, table `remote_sync_checks`). Optional, **off by default**, Admin Panel -> Configuration -> Image Host Sync Verification.
- One check per PUSH over the catalog's top-level image files (image extensions from content validation). It polls `remote_sync_check_url_template` (default `https://img.vitkac.com/uploads/product_thumb/{catalog_name}/up/{file}`, placeholders URL-encoded).
- WAITING until the PUSH's PIM event is delivered (`remote_sync_check_wait_for_pim`), then CHECKING: first check after `initial_delay`, then only files not yet served every `interval`. It ends SYNCED, or TIMEOUT after `timeout_minutes`. `POST /api/operations/{id}/remote-sync/recheck` starts the clock again.
- UPDATE re-targets the check to the new file list, re-checks files it added/replaced/renamed, and waits for the UPDATE's PIM event. PULL cancels an active check.
- **Served = HTTP 200 + `image/*` + non-empty body, fetched with a unique `rfm_sync` query parameter.** Measured on img.vitkac.com (Cloudflare): `.../TORBA HB0788 FA0542-910 SILVER/up/1.jpg` returns a cached `200 image/jpeg` with a 0-byte body, but 404 from the origin. 404s are cached with `max-age=3600`. A plain status check would report a missing file as synced, and a freshly synced file as missing for up to an hour.
- Same claim/lease pattern as PIM, 10 s loop.

**UI.** The operation history shows translated badges under the status: `PIM: notified / sending / retrying (n) / failed` and `Sync: waiting for PIM / n/m / Synced n/m / timed out n/m / cancelled` (tooltips: attempts, tgId, next attempt, last error, files not served yet). The details dialog lists the same facts plus per-file results, with "Send to PIM again" and "Check image host again". The queue's operation status is now translated too (it was English-only). PL + EN, 299 keys each. History, DB search, ES search and details all carry `pim_delivery` / `remote_sync` (shared `get_integration_status`). Admin Panel: Delivery & Retries under PIM, the new sync section, TG Identifier field removed.

**Tests:** `tests/test_pim_delivery_and_sync.py`, 14 tests on real PostgreSQL 16 with one local server playing PIM, `RFM_ValidateProductName` and the image host:
- backoff timings over 503/502/200 with identical bodies
- connect error, and missing token fixed by config
- give-up plus manual retry, per-catalog order, 4 concurrent passes send each event exactly once, disabled PIM holds events
- tgId from validation, lookup at delivery, old procedure without `tg_id` retried
- sync WAITING -> CHECKING (clock = delivery time) -> partial -> SYNCED without re-requesting served files, URL encoding and cache-busting
- empty 200 and `text/html` 200 not counted -> TIMEOUT -> recheck -> SYNCED
- the full PUSH -> UPDATE -> PULL through the real endpoints with the exact PIM bodies

`test_update_uploads.py` pins the legacy template, since tgId is covered here. Mutation-checked: removing the per-catalog ordering, or counting an empty body as served, each turns a test red. Full suite: 80 passed, 17 errors (pre-existing `test_auth.py` fixture). Browser: 39 Playwright checks against the dev WebUI with a mocked API (badges and tooltips for every state in en-US and pl-PL, details facts and file list, both action buttons post, no missing translations, Admin Panel loads/saves the new keys, TG field gone).

**Dev deploy:** api-dev rebuilt, `014 -> 015` applied (template switched, `pim_tg_id` removed, 11 keys seeded, PIM and sync still off on dev). From inside the container, the real probe against img.vitkac.com: TORBA `1.png`/`3.png` and OZDOBA `1.png` served, `99.png` 404, `1.jpg` 404 with cache-busting (empty body without it). **Not exercised live:** real PIM delivery (PIM is disabled on dev) and the updated procedure (not deployed in PolkaSQL yet, see TODO). No worker change was needed.

---

## 2026-09-16 - Worker: `fetch_file` for uploaded UPDATE files; worker-side backups removed

**`fetch_file`** (`CommandHandler.HandleFetchFileAsync`) downloads a WebUI upload from the API and places it at `dest_path`:
- Checks `dest_path`, `url` (must start with `/api/`; `ApiClient` also requires the configured host and does not follow redirects), `sha256` (64 hex) and `size_bytes >= 0`, then `FileOperations.EnsureAllowedPath`, before any I/O.
- `ApiClient.DownloadToFileAsync` uses the same client certificate on a separate `HttpClient` with a 30-minute limit, streams to the service's temp folder, and hashes and counts while writing. An error response fails the command with the status code plus at most 300 characters of the body.
- A size or hash mismatch fails with `size/SHA-256 verification`, before the share is touched.
- `FileOperations.ReceiveFileAsync` opens the temp file before switching to the share account, then as that account creates the parent folder, refuses an existing destination, writes `<dest>.partial` and renames it. The temp file and `.partial` are removed in `finally`.
- Logs destination, size, SHA-256 and duration. The URL query string (signed token) is never logged.

**Removed `RollbackManager`** and the 6-hourly cleanup loop. `copy`/`move`/`delete`/`mkdir` backed up the *virtual* path (`B:/cat/a.jpg`), outside impersonation and before path validation:
- For `A:`/`B:` nothing existed locally, so nothing was ever backed up or restored.
- For `C:` it read the worker host's own system drive, and on failure deleted and rewrote that path, outside the system-directory check.
- Using resolved paths instead would have copied whole catalogs to local temp before every PUSH/delete.

Undo is the server's job (`operation_service.py`: PUSH/PULL and UPDATE have their own undo, others use `_rollback_operation`). Nothing on the server read `rollback_status`. Failed commands still report `error_type`.

**Confirmed for the UPDATE flow (no change):** single-file `copy` creates the missing parent. `move` onto an existing file fails when both paths share a root (a cross-root move is copy with overwrite plus delete). `delete` of a missing path fails with `Path not found: ...`, which is also what an access-denied path looks like, because `File/Directory.Exists` return false.

**Verified:** Release build succeeds, and the build runs as `DELA-5420-AW` against dev (ACTIVE). A bad signed link on api-dev -> 403 `Invalid or expired download link`. **Not yet verified:** an end-to-end UPDATE through the WebUI (upload replace/add, and the non-image 422). On this host the worker uses local `C:\RFM-Dev` paths without share credentials, so the impersonated write path was not exercised.

---

## 2026-09-16 - UPDATE: replace/add files, uploads, history details, suppressible confirmations

UPDATE could only rename or delete. It can now also **replace** a catalog file and **add** new ones. New content comes from a **Path A file** (default) or a **WebUI upload**.

**Execution order** (`OperationService._execute_update_operation`), so the catalog stays recoverable until the last step:
1. Stage new content in `B:/<catalog>/.rfm-update-<op>/`: `copy` from Path A, or the new worker command `fetch_file` for uploads.
2. `validate_dir` on the staged files: a folder picked as a source, or bytes that contradict the extension, fail with `UpdateContentRejected` → HTTP 422 (`contentValidation.stagedTypeMismatch` / `stagedNotAFile`). Nothing in the catalog has changed at this point.
3. Renames, then swaps (target → working folder, staged → target), each recorded and undone in reverse on any failure.
4. Deletes (irreversible) last, then the working folder is removed.
5. Best-effort after success, recorded as `params_json.warnings` instead of failing: working-folder cleanup, **per-file "remove from Path A"** (`remove_source`), archive mirror (now also copies replaced/added files to PATH_C).

**Uploads** (`api/services/upload_service.py`, `api/routes/uploads.py`, table `update_uploads`, migration **014**):
- `POST /api/uploads` streams to `update_upload_dir/<id>.part` while hashing (SHA-256), refuses more than `update_upload_max_mb` (default 200) early from Content-Length and again while streaming, then renames the file. `DELETE /api/uploads/{id}` discards an unused upload; the WebUI calls it when a change is removed or the dialog is closed.
- An UPDATE claims its uploads with a conditional `UPDATE … WHERE operation_id IS NULL`, so an upload feeds exactly one operation. The worker downloads through `GET /api/workers/{host}/uploads/{id}`, an HMAC link bound to upload + worker hostname with a 1-hour expiry; the worker verifies size and SHA-256.
- **Garbage collection:** the endpoint deletes the files as soon as its UPDATE finishes (success or failure); the row stays as the audit record (name, size, SHA-256, user, operation). A background loop (1 min after start, then every 15 min, safe across the 4 uvicorn processes) removes unused uploads past `update_upload_ttl_hours` (default 24), uploads of finished operations, uploads of operations stuck past expiry, and stray/`.part` files older than an hour. Storage is a named volume (`file-manager-uploads[-dev]`), shared by all API processes.
- Limits are Admin Panel config (`UPDATE Behaviour`), seeded by 014, env `UPDATE_UPLOAD_MAX_MB` / `UPDATE_UPLOAD_TTL_HOURS` (optional sync).

**PIM:** unchanged mechanism, now verified end to end. Every completed UPDATE (including a replace-only one, whose file list is unchanged) sends `eventType "updated"` with the predicted post-update file list. A failed or rejected UPDATE sends nothing. PULL now records `username`, so its PIM event names the user.

**Content gate for UPDATE** (`run_catalog_preflight`): mismatch findings now follow their files. A deleted or replaced mismatched file no longer blocks, and a rename to the extension matching the real bytes fixes one. Before this, a catalog with one mislabelled image could not be repaired by UPDATE at all. Replace targets must exist and add targets must not (400 before anything runs). Listing failures keep their own reason instead of being overwritten.

**History:**
- UPDATE is linked to its PUSH (`params_json.push_operation_id`, resolved/validated server-side; refuses a pulled PUSH). PUSH rows carry `update_operation_ids` (history, DB search, ES search) and show "updated by #N" in the queue.
- `GET /api/operations/{id}/details`: the operation plus its PUSH, every UPDATE (any status) and the PULL. Operation numbers and "updated by" links open a details dialog: who, when, status, paths, each action in words (uploaded file name/size/SHA-256, Path A source and whether it was removed), warnings, errors.
- PULL records `update_operation_ids`: which UPDATEs the pulled catalog contained.

**PULL after UPDATE:** unchanged mechanics. PULL already copies the current PATH_B catalog back, so it restores the updated version. A PUSH with updates now gets its own confirmation (`pull.confirmAfterUpdate`) saying the CURRENT, updated version goes back, and naming the UPDATE numbers.

**Suppressible confirmations** (`frontend/js/dialogs.js`), PL + EN: push, pull, pull-after-update, update, update-destructive (delete/replace/remove from Path A), discard unsaved update changes, settings reset. The dialog has a "Don't ask again" checkbox; each key can be turned back on under **Settings → Confirmations**; Reset to Defaults turns all of them back on. Stored in `user_preferences.custom_settings.suppressed_dialogs` (merged, other custom settings kept). Validation and error popups stay mandatory, now a single Close button. The legacy dual-pane copy/move/delete confirmations are unreachable in this layout and were left as they are.

**Fixed along the way:**
- `frontend/js/api.js` read only `detail` from error bodies, but the API's `HTTPException` handler returns `{"error": …}`. Every server message reached the UI as "Request failed with status N", and the structured UPDATE validation popup could never render. Both shapes are now read.
- Generic `#modal` came before the update modal in the DOM, so a confirmation opened from inside the update dialog stacked underneath it. It is now last.
- UPDATE is excluded from `enable_auto_rollback`, which would have created a phantom rollback "UPDATE" operation (it reverts itself).

**Tests:** `tests/test_update_actions.py` (30, no DB: action rules, predictions, execution against an in-memory worker, including rejection, revert on swap and delete failure, missing `fetch_file`, SHA mismatch, cleanup warnings). `tests/test_update_uploads.py` (9, real PostgreSQL 16 + a local HTTP server as PIM: storage, size limit, single claim, owner-only discard, GC rules, signed link, full UPDATE endpoint → history → details → PULL with the exact PIM bodies, staged rejection → 422 with no PIM event, pulled/foreign-upload refusals). Mutation-checked: removing UPDATE from PIM signalling, dropping the finished-operation GC rule, or skipping upload release each turns a test red. Full suite: 66 passed, 17 errors (pre-existing `test_auth.py` fixture). Browser: 48 Playwright checks against the dev WebUI with a mocked API (details, picker, uploads, draft validation, exact request payload, suppression and granularity, settings toggles, discard, PULL notice, Polish strings).

**Dev deploy:** api-dev rebuilt, `013 -> 014` applied, config seeded, uploads volume mounted. Live in-process check: upload 201 → file on disk → discard 204 → file gone → 404; history/details served. **Not exercised live:** an actual UPDATE against the shares (dev has no pushed catalog right now), and uploads end to end, which need the worker's `fetch_file` command: `docs/prompts/worker-fetch-file.md`. Until the worker is updated, Path A replace/add works, and an upload-based UPDATE fails before touching the catalog with "worker does not support uploaded files yet".

---

## 2026-09-16 - Fix: UPDATE button returned 400 before the modal opened

Selecting a pushed catalog and clicking **Update** showed a 400 in the WebUI. `openUpdateModal` lists the catalog (`operation.dest_path`, e.g. `B:/subfolder`) through `GET /api/files/list`, which called `validate_path_a` and rejected every non-`A:` path. The endpoint was written for the Path A explorer; the UPDATE UI (2f5c7d8) was the first caller to list Path B.

**Fix:**
- `/api/files/list` validates `B:` paths with `validate_path_b` and everything else with `validate_path_a`. `C:` and mixed drive letters are still refused. Elasticsearch indexing of the listed entries is unchanged; file search filters on exact `parent_path`, so B entries do not appear in Path A search.
- Second bug behind the first: `listFiles()` returns the items array, but `openUpdateModal` read `listing.items`, so the modal would always have opened empty. Now uses the array directly.

**No worker change:** `FileOperations.ResolvePath` already maps `A:`, `B:` and `C:`, and UPDATE only sends existing commands (`list`, `validate_dir`, `move`, `delete`).

**Verified:** in-process against the real worker `DELA-5420-AW`, before the fix `B:/subfolder` -> 400 (`Path A operations must use paths starting with 'A:'`); after: 200 with the catalog entries, `A:/TEST CATALOG` still 200, `C:/x` and `B:/x/A:/y` still 400. api-dev rebuilt and healthy. The apply step (`POST /api/operations/update`) was not exercised, as it would have changed files on the real share.

---

## 2026-09-16 - Fix: workers stayed SUSPENDED after a restart until an admin reactivated them

Observed on dev: `DELA-5420-AW` (id=2) rebooted for a Windows update at 06:04 and from then on every poll got `403 Worker is not active (status: SUSPENDED)`, although it was running, registering and heartbeating normally.

- `background_tasks._worker_health_check_loop` set `SUSPENDED` on any ACTIVE worker with a heartbeat older than a hardcoded 5 minutes - the same status `admin.suspend_worker` sets. Nothing recorded *why*, so the server could not undo the automatic case without also undoing a deliberate administrator suspension.
- Nothing ever moved a worker back: register, heartbeat and poll all ignored status, and poll refused non-ACTIVE workers before touching anything. The evidence the worker was alive (fresh heartbeats) was stored and ignored.
- The `worker_heartbeat_timeout` config row (90) was never read; `WorkerService._mark_worker_suspended` had no callers.

**Fix:**
- New `WorkerStatus.OFFLINE`, set only by the health check. `SUSPENDED` is now administrator-only. Chosen over a `suspended_reason` column: status stays the single source of truth, every existing `status != ACTIVE` check already does the right thing, and the admin UI can show the two differently without a second field.
- Health check reads `worker_heartbeat_timeout` from the `config` table and moves stale ACTIVE workers to OFFLINE with one conditional `UPDATE ... WHERE status='ACTIVE' AND last_heartbeat < cutoff RETURNING`. uvicorn runs 4 processes, each with its own loop; the conditional update means exactly one of them reports and audits (`worker_offline`) each transition.
- `worker_service.reactivate_offline_worker` is called from heartbeat, poll and register. It runs `UPDATE ... SET status='ACTIVE' WHERE id=:id AND status='OFFLINE'`, so a concurrent administrator suspension is never overwritten, writes `worker_auto_reactivate` (`user_id=None`, trigger, client IP) and logs at INFO. In poll it runs *before* the ACTIVE check, so the poll that proves the worker is alive is served normally. SUSPENDED and PENDING are never touched. The 403 message format (`... (status: OFFLINE)`) that the worker parses is unchanged.
- Timeout **180s** (was: 300s hardcoded, 90s seeded but unused). The worker heartbeats every 60s on its own task, independent of command execution, so 180s tolerates two lost heartbeats (e.g. an API restart during a long copy) while detecting a dead worker within ~4 minutes (timeout + 60s check interval). Recovery is automatic, so a flap costs only an audit pair.
- **Commands are deliberately not cancelled** when a worker goes OFFLINE. Heartbeats keep running while a command executes, so OFFLINE with a SENT command means the worker lost contact, not that it stopped work: during a network outage it may still finish and report. `cancel_pending_commands` would mark it FAILED, the caller would report failure, and the late response would then flip the command and operation to COMPLETED. PENDING commands are already bounded by `worker_timeout` and marked TIMEOUT, so they are not picked up after the caller gave up. The edge race the brief mentioned is in `wait_for_command_completion` and is unrelated to OFFLINE - see TODO.md.
- `admin_system` stats: `workers_offline` now counts OFFLINE status (was: ACTIVE with a 5-minute-old heartbeat); `workers_healthy` = ACTIVE.
- Admin UI: OFFLINE workers stay in the approved list with a grey badge and tooltip, and offer **Suspend** (to keep a dead worker from coming back) rather than Activate. Badge classes are now lowercased so the existing `.status-*` styles apply (they never matched the uppercase status before); added `.status-suspended`.
- Removed dead `WorkerService._mark_worker_suspended`.

**Schema:** `OFFLINE` added to `workerstatus` in `001` (fresh installs) and in new revision **`013_worker_offline_status.py`** for existing databases, following 012's precedent and agreed as the resolution to TODO.md rule 3. 013 also moves `worker_heartbeat_timeout` 90 -> 180 only if still at the untouched seed. Downgrade maps OFFLINE rows to SUSPENDED (older code cannot load OFFLINE). `promote-dev-to-prod.sh` verifies the enum value and its rollback text explains the OFFLINE caveat.

**Rollout note:** workers that the *old* health check suspended are indistinguishable from administrator suspensions and stay SUSPENDED. An administrator reactivates each one once. Dev id=2 was in exactly that state.

**Tests:** `backend/tests/test_worker_offline.py`, 18 tests against real PostgreSQL 16 (schema built with `alembic upgrade head`; set `TEST_DATABASE_URL`). They cover the health-check transition via the real loop (config-driven timeout, audit, SUSPENDED/PENDING untouched), invalid-config fallback, 4 concurrent health checks -> 1 transition, reactivation via poll/heartbeat/register with audit, no reactivation from SUSPENDED/PENDING for each trigger (including the exact 403 text), the conditional guard against a concurrent admin suspension, and concurrent check-ins -> 1 audit entry. All 18 pass. Mutation-checked: dropping the `status='OFFLINE'` guard, writing SUSPENDED on stale, or reactivating any non-ACTIVE status each turns the matching tests red. Full suite: 33 passed, 17 errors - all 17 in the pre-existing `test_auth.py`, which requests a `db_session` fixture that does not exist.

**Migration verified** on a throwaway postgres:16-alpine: 011 -> 013 in one run (prod path) and 012 -> 013 (dev path) both give `{ACTIVE,SUSPENDED,PENDING,OFFLINE}`, timeout 180, existing SUSPENDED row untouched; re-run is a no-op; downgrade maps OFFLINE -> SUSPENDED and restores 90.

**Dev deploy (2026-09-16 08:40 UTC):** api-dev rebuilt, migration `012 -> 013` ran, `worker_heartbeat_timeout=180`. The real worker's first heartbeat on the new code (08:41:08) left id=2 SUSPENDED, as designed. Acceptance criteria 1-2 (stop the Windows service > timeout, start it, see OFFLINE -> ACTIVE and the worker's `ACTIVE again ... (was OFFLINE)` log) require stopping the service on the Windows host and were not run from the server.

**Not addressed here:** worker identity is not verified at all - see TODO.md.

---

## 2026-09-16 - Fix: worker reconnect path and Event Viewer noise

**Reconnect (worker side).** After the dev host rebooted, the approved worker came back and was refused forever with `403 (status: SUSPENDED)`.
- **Root cause is server-side:** the health check (`background_tasks.py`) and the admin suspend action both write `SUSPENDED`, and nothing ever moves a worker back to ACTIVE except manual approval. The worker cannot and must not activate itself. Server fix handed off as `docs/prompts/server-worker-auto-reactivation.md`.
- Worker-side defects in the same path, fixed:
  - registration logged "status is PENDING - awaiting admin approval" unconditionally; it now logs the status the server returned;
  - every 403 was logged as "certificate has been revoked" and triggered a re-registration (rewriting the stored key every 30s); the worker now reads the real status from the 403 body, keeps its registration, and re-registers only on 404;
  - an empty poll answers `200` with `command_id: null`, which the worker treated as a command (failing it and posting a response for command 0). It was masked because the poll's server timeout (30s) equalled `HttpClient.Timeout` (30s), so idle polls normally ended in a swallowed client timeout. The worker now asks for `timeout=25` and ignores null commands;
  - connectivity problems (502 during a redeploy, refused connections) were logged per retry; they are now logged once, with a matching recovery entry.

**Event Viewer.** Every Info line went to the Windows Application log: 3,146 entries in a few hours of one worker on dev. Multi-line banners also wrote one event per line (a failed registration was ~15 Error events).
- NLog now sends only Warn and above to Event Viewer, plus a dedicated `Lifecycle` logger for started / stopped / ACTIVE again / API reachable again. Everything else stays on the console (`/debug`).
- Banners collapsed into single entries (registration, missing certificate, missing API URL, network-share credentials, impersonation failure).
- Recurring conditions log on state change, not per retry.

**Verified.**
- Scripted fake API driving SUSPENDED → 502 outage → ACTIVE → 404 → PENDING → ACTIVE, through a harness hosting `WorkerService` Start/Stop like Topshelf: 2 registrations (startup and after 404, none on 403); exactly 30.0s backoff while SUSPENDED and PENDING; heartbeats continued while suspended; the command after recovery ran and returned 9 items; no response for the empty poll; **exactly 10 Event Viewer entries for the whole run**, all Warn or Lifecycle, in the expected order.
- Live on dev: 3 Event Viewer entries on startup (deprecated App.config API URL, SUSPENDED, started).
- `validate_dir` suite 15/15.
- The `UnauthorizedRetrySeconds` branch from the polling-loop fix below is now measured: 403 retries at exactly 30s, live on dev and in the harness.

**Not done:** Info-level detail now exists only on the console; a service install has no Info log at all. Add an NLog file target if that is needed for troubleshooting.

---

## 2026-09-16 - Fix: validate_dir result was dropped, rejecting valid catalogs

A catalog with 4 genuine images was refused with "0 of 2 required image files - 0 files in total", while the worker had correctly logged `7 file(s), 4 image(s), 1 non-image, 2 mismatched` for the same directory.

- **Not a worker bug.** The worker returned the right payload on `CommandResponse.error_details`.
- `api/routes/worker.py` stores the worker's `error_details` *nested* inside the command's `response_data`, and `worker_service.send_command` then hands that whole wrapper back as `WorkerCommandResponse.error_details`.
- So the service received `{file_count, total_size_bytes, error_details: {...real payload...}}`. `validate_directory_content` read `files`/`image_count` straight off the wrapper, got `None`, and fell through to `0` images and `0` files - which trips the minimum-image gate and blocks PUSH/UPDATE.
- The `list`/`search` consumers in `api/app.py` already unwrap this (with a comment describing the exact trap); the newer validation service did not.

**Fix:** `validate_directory_content` unwraps one level when it sees a nested `error_details`, tolerating both shapes so it keeps working if that seam is ever flattened. Single call site, so this covers PUSH, UPDATE and the PIM `files` array.

**Tests:** `backend/tests/test_content_validation.py` (6 tests) pins the nested and flat shapes, that a genuinely empty directory still fails, that mismatched files still reject, and the `validate_dir` command contract. Verified to fail without the fix - 3 tests red, logging the exact production message `0 image file(s), 2 required (total files: 0...)`.

**Still open:** the double-wrap itself at the `worker.py` / `worker_service.py` seam. `admin_system.py` reads `response.error_details.get("config")` for `get_status`, which the wrapper also defeats. Fixing the seam once and dropping the per-consumer unwraps is the better end state, but it touches ~6 consumers and was not attempted here.

---

## 2026-09-16 - Fix: worker polling loop hammered the API instead of backing off

Found while building `dev-vf` and pairing a worker with the dev stack.

- `WorkerService.PollingLoop` had no delay on its normal path — only inside its `catch`. Pacing relied entirely on the API holding the long poll (`?timeout=30`).
- Whenever the API answered immediately the loop spun flat out: **94 registrations in 15s (~6/s)** from a single worker awaiting approval. A `PENDING` worker gets an instant 403, and `ApiClient` resets `_isRegistered` on 403, so every spin also re-registered.
- The same spin hit **approved** workers, which get an immediate `204 No Content` when no command is queued.
- `PollingIntervalSeconds` was parsed and logged but never actually used to pace anything.

**Fix:** `PollingLoop` now waits when no command came back — `PollingIntervalSeconds` normally, `UnauthorizedRetrySeconds` (30s) while the API is rejecting the worker, via the new `ApiClient.IsRegistered`. After processing a command it `continue`s, so a queued backlog still drains without waiting.

**Verified (approved worker, 90s sample against the dev stack):** 1 registration, 0 spins, 20 commands executed (`list`/`ping`/`get_status`); log 17.6 KB vs 174.6 KB in 15s before the fix. Idle polls settle to a steady ~5.1s, matching `PollingIntervalSeconds`, and a queued backlog still drains back-to-back (0.1s between two commands), confirming the `continue`.

**Not separately re-measured at the time (since measured, see the reconnect entry above):** the `UnauthorizedRetrySeconds` branch. The worker was approved on the dev stack before the fixed build existed, so the post-fix `PENDING` path could not be observed without suspending it. The 94-registrations-in-15s figure is the *pre-fix* `PENDING` measurement. Both branches are the same `Task.Delay`, differing only in the constant.

---

## 2026-09-16 - Feature: UPDATE operation, PIM signalling, catalog & content validation

Implemented on `dev-vf` and verified against the dev stack.

### 1. UPDATE operation (third operation type)
- `OperationType.UPDATE` — in-place move/rename/delete inside a catalog already pushed to PATH_B.
- Orchestrated server-side like PUSH/PULL; the worker only gained one new read-only command.
- **Ordering guarantee:** reversible actions (move/rename) run first; irreversible deletes run only after they all succeed. A mid-flight failure unwinds the applied moves in reverse order, leaving the catalog as found.
- Optional PATH_C archive mirror (`enable_update_archive_mirror`), **off by default**, best-effort: PATH_B is the live copy and is already correct by then, so a stale archive never fails the operation.
- Action paths are catalog-relative. Absolute, UNC, drive-prefixed (`B:/…`) and `..`-traversing paths are refused by `_safe_relative()`.
- Entry point in the WebUI is the operation queue (same as Pull), because this layout has a single file pane and the catalog is identified by the PUSH that created it.

### 2. Catalog name validation (PolkaSQL `RFM_ValidateProductName`)
- Hard block: a catalog whose folder name matches no product in `Polka27.elementy.grup_nazwe_kolor` cannot be pushed or updated.
- Returns ranked suggestions on a miss (SQL Anywhere `SIMILAR()`, first-token prefilter to avoid scanning all of `elementy`).
- **Fail-closed** when PolkaSQL is unreachable. `catalog_validation_fail_open` inverts this for an outage.
- Procedure + web service definition: `docs/polkasql/RFM_ValidateProductName.sql`.

### 3. PIM signalling (second, independent target alongside ROSAPI)
- `POST {base}/api/v1/image_catalog/ftp_event` with a static `X-API-TOKEN` header (no JWT flow).
- PUSH → `created`, PULL → `updated`, UPDATE → `updated`; each separately toggleable with its own configurable eventType.
- Payload body is a template editable in the Admin Panel. `{files}` is substituted as a raw JSON array; every other placeholder is JSON-escaped, so a quote in a catalog name cannot inject keys.
- `tgId` is absent from the default template pending confirmation of its meaning; adding `"tgId": "{tg_id}"` plus `pim_tg_id` is all that is needed.
- The file list is captured during validation and carried on the operation, so signalling needs no extra worker round-trip.

### 4. Directory content validation
- At least `push_validation_min_files` (default 2) genuine image files, else the operation is refused.
- New `validate_dir` worker command sniffs magic bytes (JPEG/PNG/GIF/BMP/TIFF/WebP), so a renamed `.txt` cannot pass as a `.png`. A mismatch is a hard failure.
- Non-image files do not count toward the minimum but **are** reported and **are** still sent to PIM.
- For UPDATE the gate judges the post-action state, so an update can neither leave a catalog short nor be blocked by one it repairs.
- Messages are i18n keys resolved client-side; full en-US/pl-PL parity (181 keys each).

### 5. Logging
- Username is recorded on every operation, audit entry and outbound signal, so a bad catalog can be traced to whoever pushed it.

### Bugs found and fixed during implementation
- `_safe_relative()` accepted `/etc/passwd`: the leading-slash test ran *after* separators were stripped, so it never fired.
- The PUSH endpoint's blanket `except Exception` turned every 422 validation rejection into a 500, hiding the suggestions from the UI.
- `/api/operations/push/batch` — the endpoint the WebUI actually calls — was initially left ungated while only the single-push endpoint enforced the gates.
- `apiRequest()` stringified structured 422 bodies to `[object Object]`, losing the suggestions.

### Notes / deviations
- **TODO.md rule 3 (consolidated migrations):** 001 is already applied on live databases, so the enum value and config seeds had to arrive as their own revision (`012`). Seeds use `ON CONFLICT DO NOTHING` and never clobber an operator's value.
- **`_sync_env_config_to_db()` overwrites the DB on every boot**, which silently reverts Admin Panel edits. The new PIM/validation keys sync **only when their env var is present**, so the panel stays authoritative. Existing ROSAPI keys were left on the old behaviour — changing them is a separate decision.
- Promotion script: `scripts/promote-dev-to-prod.sh` (backup, merge, rebuild, verify, `--rollback`, `--dry-run`).

---

## 2026-02-10 - Fix: Remote Syslog Delivery Not Working
- **Issue:** Syslog settings persisted correctly but audit messages never arrived at remote syslog server.
- **Root causes (5 interconnected bugs):**
  1. `setup_logging()` in `logger.py` had no error isolation — if FileHandler init failed (e.g. can't create `/var/log/file-manager/`), `_global_handler` was never set (`None`), making syslog permanently broken.
  2. `_reconfigure_logging_from_db()` in `app.py` silently returned when `_global_handler` was `None` — no recovery path.
  3. Admin UI reconfiguration in `admin_system.py` skipped when `_global_handler` was `None` — same issue.
  4. `SyslogHandler.write_log()` used synchronous socket I/O, blocking the async event loop.
  5. `create_audit_log()` in middleware had `except Exception: pass` — all syslog errors silently swallowed, making diagnosis impossible.
- **Fixes applied:**
  - `logger.py`: Each handler init wrapped in its own try-except; `_global_handler` always set even if individual handlers fail.
  - `app.py`: `_reconfigure_logging_from_db()` creates a `MultiHandler` if `_global_handler` is None.
  - `admin_system.py`: Admin reconfiguration creates `MultiHandler` if `_global_handler` is None.
  - `handlers.py`: Socket I/O moved to `run_in_executor()` to avoid blocking the event loop.
  - `middleware/logging.py`: Silent `pass` replaced with `logger.warning()` for error visibility.

## 2026-02-09 - Verification: Admin Panel, Elasticsearch, Logging, Audit, Windows Client
- Verified Elasticsearch shows "Connected" in System Health
- Verified syslog settings persist across restart (but delivery still broken - messages don't arrive)
- Verified Logging Configuration in Logs tab (load, save, runtime reconfiguration)
- Verified Audit Log Viewer (filter, pagination, export)
- Verified Admin Panel overhaul (theme, user CRUD, PolkaSQL badge, worker controls, real-time stats)
- Verified Windows client: WiX installer works, context menu integration works, Polish localization works for installer
- Known issue: Device authorization page still English-only (not localized)

## 2026-02-09 - Windows Client Fixes: Token Refresh + Path Mapping
- **Issue 1 - Token Refresh Bug:** Windows launcher required authentication every time (every hour when token expired) despite OAuth device flow implementation.
  - **Root cause:** Refresh token saved to `Credential.Description` field but loaded from `Credential.SecurePassword` field (field mismatch). Token refresh silently failed, forcing device flow re-authentication.
  - **Fix:** Updated `AuthenticationManager.cs:106` to load refresh token from `Description` field: `string refreshToken = cred.Description;` (matches save location at line 311).
  - **Impact:** Users now authenticate once, then automatic token refresh works indefinitely. No more browser popups every hour.
- **Issue 2 - Path Mapping Missing:** Deep links only worked for root-level folders. Nested folders (e.g., `\\server\share\path\to\nested\MyFolder`) were never found.
  - **Root cause:** Frontend only extracted last folder name (`MyFolder`) and looked for it in current directory. No path resolution system. Worker's `path_a_prefix` configuration was unused.
  - **Fix - Backend:** Created new API endpoint `POST /api/path/resolve` in `backend/api/routes/path.py`:
    - Accepts Windows path and worker_id
    - Gets worker's `path_a_prefix` (e.g., `\\server\share`)
    - Strips prefix from Windows path to get relative path
    - Converts to virtual path format (`A:/path/to/folder`)
    - Returns virtual_path, parent_path, folder_name
    - Handles UNC paths, drive letters, nested directories
  - **Fix - Frontend:** Updated `handlePrepareAction()` and `handlePushAction()` in `frontend/js/app.js`:
    - Calls `/api/path/resolve` API to convert Windows path → virtual path
    - Navigates to parent directory first
    - Then selects folder in file list
    - Properly handles nested folder structures
  - **Fix - Backend Registration:** Registered path router in `backend/api/app.py`
  - **Impact:** Deep links now work for folders at any depth. Right-click on `\\server\share\projects\2024\MyFolder` → navigates to `A:/projects/2024` → selects `MyFolder`.
- **Documentation:**
  - Created `clients/windows/PATH_MAPPING_GUIDE.md` - Complete path mapping configuration guide
  - Created `WINDOWS_CLIENT_FIX_SUMMARY.md` - Testing instructions, configuration, rollback procedures
- **Configuration Required:**
  - Worker must be configured with `path_a_prefix` in Admin Panel (e.g., `\\192.168.100.4\DaneFoto-test`)
  - Windows client `config.json` must include `frontend_base_url` (already configured)
  - Allowed paths must match or be subpaths of worker's `path_a_prefix`
- **Files modified:**
  - Backend: `backend/api/routes/path.py` (NEW), `backend/api/app.py` (router registration)
  - Frontend: `frontend/js/app.js` (deep link handling with path resolution API)
  - Windows: `clients/windows/Launcher/AuthenticationManager.cs` (token refresh fix)
  - Docs: `clients/windows/PATH_MAPPING_GUIDE.md` (NEW), `WINDOWS_CLIENT_FIX_SUMMARY.md` (NEW)
- **Lesson learned:** Added comprehensive Windows client integration pattern to LESSONS_LEARNED.md covering credential storage field mapping and path resolution architecture

---

### 2026-02-08 - Windows Context Menu Integration (OAuth Device Flow + Deep Linking)
- **Feature:** Implemented complete Windows Explorer context menu integration for RFM
- **Backend - Device Authorization Flow (RFC 8628):**
  - Added `DeviceAuthorizationRequest` model to `models.py` with device_code, user_code, user_id, approved, expires_at
  - Created migration `011_device_authorization.py` with device_authorization_requests table and indexes
  - Implemented three API endpoints in `auth.py`:
    1. `POST /api/auth/device/request` - Generate device_code and user_code for authentication
    2. `POST /api/auth/device/poll` - Client polls for user approval (returns token when approved)
    3. `POST /api/auth/device/approve` - User approves device in browser (authenticated endpoint)
  - Added device flow schemas: `DeviceAuthorizationResponse`, `DeviceAuthorizationPollRequest`, `DeviceAuthorizationApprovalRequest`
  - Device flow uses 15-minute expiration, 5-second polling interval
  - Returns access_token + refresh_token for long-lived client sessions
- **Frontend - Device Authorization UI:**
  - Created `pages/device.html` - Device authorization approval page with user_code display
  - Created `js/device.js` - Handles device approval/denial with auto-close on success
  - Added CSS styles for user code display (`.user-code-display`, `.button-group`, `.success-message`)
  - User lands on device page with code, clicks "Approve Device", returns to launcher
- **Frontend - Deep Linking Support:**
  - Modified `app.js` init() to parse URL parameters: `action` (prepare/push), `path` (Windows path), `token` (JWT)
  - Implemented token-based auto-login: validates token via `/api/auth/me`, stores in sessionStorage
  - Added `handlePrepareAction(targetPath)` - Pre-selects folder in file list based on Windows path
  - Added `handlePushAction(targetPath)` - Auto-triggers push operation after selection
  - Cleans URL parameters after handling to prevent re-trigger on refresh
  - Deep link format: `https://rfm.company.com/pages/explorer.html?action=prepare&path=\\server\share\folder&token=xyz`
- **Windows Launcher (C# .NET 4.8):**
  - Created `clients/windows/Launcher/` directory with complete C# project
  - `Program.cs` - Entry point, parses --prepare/--push arguments, validates paths, launches browser
  - `AuthenticationManager.cs` - OAuth device flow implementation, Windows Credential Manager integration, JWT token expiration checking, token refresh
  - `ConfigurationManager.cs` - Loads config.json with api_base_url, allowed_paths, language
  - `DeepLinkBuilder.cs` - Builds deep link URLs with query parameters
  - `LocalizationManager.cs` - Loads locale files (en-US.json, pl-PL.json), flattens nested JSON
  - `config.json` - Configuration for API URL, allowed Windows paths, language preference
  - NuGet dependencies: Newtonsoft.Json (JSON), CredentialManagement (Windows Credential Manager)
  - Credentials stored securely in Windows Credential Manager (encrypted by OS)
  - Supports path validation (only launches for allowed paths)
- **Localization:**
  - Added device flow strings to `frontend/locales/en-US.json` and `pl-PL.json`
  - Device page instructions, user code display, approve/deny buttons, success/error messages
  - Added error strings for noWorkerAvailable, pathNotAllowed
  - Windows launcher includes en-US and pl-PL locale files for console messages
  - Language preference syncs between installer, client config, and user preferences
- **Documentation:**
  - Created `clients/windows/README.md` - User guide (installation, usage, troubleshooting)
  - Created `clients/windows/DEPLOYMENT.md` - IT admin deployment guide (GPO, SCCM, silent install)
  - Created `clients/windows/DEVELOPMENT.md` - Developer guide (building, debugging, contributing)
  - Created `clients/windows/Launcher/README.md` - Launcher-specific build/config docs
  - Comprehensive troubleshooting sections for common issues
- **Shell Extension & Installer (Planned):**
  - Shell extension (C++ ATL COM) - Context menu registration, path validation, launcher invocation (template/placeholder files)
  - WiX installer (MSI) - Language selection, component deployment, COM registration (template/placeholder files)
  - Full implementation deferred for future completion
- **Architecture:**
  - Simplified design: Windows client sends real Windows paths, server/worker handles PathA mapping
  - No localhost server needed (device flow), works with SSO/PolkaSQL authentication
  - Deep linking provides seamless browser integration with auto-login
  - Fast provisioning: distribute pre-configured installer with custom config.json
- **Security:**
  - OAuth Device Flow (RFC 8628) - Secure authentication without passwords
  - Windows Credential Manager - Encrypted token storage
  - HTTPS required for all API communication
  - Token refresh for long-lived sessions
  - Path validation prevents unauthorized access
- **Files created/modified:**
  - Backend: `models.py`, `api/routes/auth.py`, `api/schemas.py`, `alembic/versions/011_device_authorization.py`
  - Frontend: `pages/device.html`, `js/device.js`, `js/app.js` (deep linking), `css/style.css` (device page styles)
  - Locales: `locales/en-US.json`, `locales/pl-PL.json` (device flow strings)
  - Windows: `clients/windows/Launcher/` (11 files), `clients/windows/` (3 documentation files)

### 2026-02-08 - UI improvements: wildcard search, status column centering, responsive button arrows
- **Issue 1 - Wildcard search NOT working:** Directory search in left pane (Path A) should support partial/substring matching. Typing "anoth" should find "anotherdir". User reported this was NOT working despite 2026-02-08 Elasticsearch fix.
  - **Root cause 1 (Elasticsearch):** `elasticsearch_service.py:495-501` used `multi_match` with `type: "phrase"` for wildcard queries, but `multi_match` with `type: "phrase"` does NOT support wildcards. This was a bug in the original "fix".
  - **Root cause 2 (Worker fallback):** When Elasticsearch is disabled, search falls back to worker service which sends pattern to C# worker. The C# worker uses `Directory.GetFiles(pattern)` which requires explicit wildcards (`*pattern*`). If user types "anoth" without wildcards, it won't match "anotherdir".
  - **Fix 1:** Replaced `multi_match` with actual `wildcard` queries on `.keyword` fields in `elasticsearch_service.py:494-510`. Now uses separate `wildcard` queries for `path.keyword` and `name.keyword` with pattern `*{query}*`.
  - **Fix 2:** Modified `worker_service.py:230-256` to automatically wrap search query with wildcards before sending to worker (adds `*` prefix/suffix if not already present). This allows "anoth" to match "anotherdir" even when Elasticsearch is disabled.
  - **Result:** Substring matching now works in both code paths (Elasticsearch and worker fallback). Typing "anoth" finds "anotherdir" correctly.
- **Issue 2 - Status column vertical alignment:** Operation History table status badges were aligned to top instead of centered vertically within table cells.
  - **Fix:** Added `vertical-align: middle;` to `.queue-table td` selector in `style.css:1530`. All table cells now center content vertically.
- **Issue 3 - Push/Pull button arrows:** When panes are side-by-side (horizontal layout), `Push >` and `< Pull` make sense. When panes are stacked vertically (mobile/tablet), the horizontal arrows `>` and `<` are confusing.
  - **Fix:** Implemented responsive arrow display:
    1. Updated HTML (`explorer.html:77-82`): Split button text into separate spans for label and arrows. Added both horizontal (`>`, `<`) and vertical (`↓`, `↑`) arrow spans.
    2. Added CSS rules (`style.css:1422-1443`): By default (horizontal layout), show horizontal arrows, hide vertical arrows.
    3. Added media query (`style.css:1698-1711`): At `@media (max-width: 1024px)` (stacked layout), hide horizontal arrows, show vertical arrows.
    4. Result: Desktop/horizontal shows "Push >" and "< Pull". Mobile/tablet shows "Push ↓" and "↑ Pull".
- **Files modified:** `elasticsearch_service.py` (fixed wildcard query), `worker_service.py` (auto-wrap pattern with wildcards), `style.css` (vertical-align, arrow visibility, media query), `explorer.html` (button HTML structure with arrow spans)

### 2026-02-08 - Implement silent background polling for real-time external file changes
- **Issue:** After WebSocket implementation, polling interval was changed from 5s → 60s to reduce load. But this meant external file changes (files added/modified directly on Samba share, outside the app) took 60 seconds to appear. Also, polling caused screen flicker with "Loading" indicator.
- **User requirements:**
  1. Detect external file changes in real-time (5-second polling required)
  2. NO screen flicker - polling must be silent (no loading indicators)
  3. NO interruption while typing in address bar or search bar
  4. Loading indicator only for user-initiated actions that take >1-2 seconds
- **Solution:** Implemented "silent" background polling:
  1. Added `silent` parameter to `loadDirectory()` and `refreshPane()` functions
  2. When `silent: true`, loading indicators are NOT shown (`showLoading()` / `hideLoading()` skipped)
  3. Background polling uses `silent: true` - updates data without visual feedback
  4. User-initiated actions (click refresh, navigate, search) use `silent: false` (default) - show loading
  5. WebSocket real-time updates also use `silent: true` - seamless updates
  6. File list polling: **5 seconds** (silent, detects external changes)
  7. Operation history polling: **10 seconds** (silent, slower because operations always trigger WebSocket)
  8. Existing protection: `shouldSkipAutoRefresh()` prevents refresh while user is typing
- **Result:**
  - External file changes appear within 5 seconds ✓
  - No screen flicker or loading indicators during polling ✓
  - Typing is never interrupted ✓
  - Only manual actions show loading (when appropriate) ✓
  - WebSocket provides instant updates (0s latency) ✓
  - Best of both worlds: instant WebSocket + 5s safety net for external changes
- **Files modified:** `app.js:604-689` (loadDirectory silent param), `app.js:771-776` (refreshPane silent param), `app.js:236-271` (silent polling), `app.js:1895` (WebSocket silent refresh)

### 2026-02-08 - Fix Elasticsearch substring/partial matching for searches
- **Bug:** Directory search and operation history search were not finding partial matches. Searching for "another" did not find "anotherdir". Search appeared to be intermittent - sometimes worked (exact/full word match) and sometimes failed (partial match).
- **Root cause:** Elasticsearch search queries used `operator: "and"` which required exact token matching (with fuzzy tolerance for typos only). The multi_match query was not configured for substring/containment matching. Searching for "another" would not match "anotherdir" because they are different tokens.
- **Fix:** Modified both `search_operations()` and `search_files()` in elasticsearch_service.py:
  1. Changed `operator: "and"` → `operator: "or"` for better partial matching
  2. Added wildcard query (`*query*`) on `.keyword` fields for true substring matching
  3. Wrapped in `bool` query with `should` clause - tries both fuzzy match and wildcard match
  4. `minimum_should_match: 1` means at least one query type must match
- **Result:** Searches now support:
  - Exact matches (highest score)
  - Fuzzy matches for typos (AUTO fuzziness)
  - Substring/partial matches via wildcards
  - Searching "another" now correctly finds "anotherdir"
- **Bonus fix:** Fixed unrelated Pull operation bug - `operation.original_path` was undefined, causing "Cannot read properties of undefined (reading 'startsWith')" error. Added null check.
- **Debug logging:** Added comprehensive logging (`[Search]`, `[OpHistory]`, `[API]` prefixes) which helped identify the issue.
- **Lesson learned:** Elasticsearch `operator: "and"` requires all terms to match, which breaks partial/substring matching. Use `operator: "or"` + wildcard queries for user-friendly search behavior.

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
