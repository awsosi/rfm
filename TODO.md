# TODO - RFM (Remote File Manager)

> **Project:** File operation management system with microservices architecture
> **Status:** Active Development
> **Last Updated:** 2026-09-17

---

## CRITICAL RULES (Read Before Every Change)

1. **Schema ↔ Endpoint ↔ Model must stay in sync.** Pydantic silently strips unknown fields. Checklist: `models.py` column → `schemas.py` request schema → endpoint constructor → response schema.

2. **Never mark a bug "likely fixed" without code review.** Read the actual code end-to-end. "Likely" means "still broken until proven otherwise."

3. **Migrations are consolidated.** Single `001_initial_schema.py`. Merge schema changes into it during pre-production.

4. **Every client field must appear in serialization payload.** Missing fields silently default to `None`. Diff client JSON against Pydantic schema field-by-field.

5. **Single source of truth: DB at runtime, env on startup.** Env vars sync INTO DB via `_sync_env_config_to_db()`. Runtime reads ONLY from DB.

6. **Python async extras: always install `[async]`.** e.g., `elasticsearch[async]`, not bare `elasticsearch`. Missing extras cause silent runtime failures.

7. **Env var naming convention: `ENABLE_*` prefix.** If inherited name differs, add `validation_alias=AliasChoices(...)` to accept both.

8. **Frontend-backend format alignment.** HTML form values must match Pydantic validation patterns exactly. Test with DevTools Network tab.

9. **WebSocket/API endpoint paths must match everywhere.** Backend, all frontend clients, and docs must use same path. Grep before changing.

10. **Reverse proxy: Frontend `API_BASE_URL` must point to API domain,** not webui domain.

11. **Frontend config injection: ALL entry points,** not just `index.html`. Users access pages directly.

12. **Keep It Simple, Stupid (KISS).** Avoid over-engineering. Only add what's requested or clearly necessary.

13. **Don't Repeat Yourself (DRY).** Extract common patterns. Use shared functions/utilities instead of duplicating code.

> **See LESSONS_LEARNED.md for detailed patterns and examples.**

---

## ACTIVE BUGS

- [ ] **SECURITY - worker identity is not verified.** A worker is identified only by
      the hostname in the URL. `public_key` (the worker actually sends its full
      client certificate PEM) is stored on register and never checked; no
      client-certificate or signature verification exists anywhere. Traefik routers
      `api-dev.ff.vitkac.local` / `api.ff.vitkac.local` are plain `tls = true` with
      no client auth, and the API ports are published on `0.0.0.0:58080` / `:48080`,
      so Traefik can be bypassed entirely. Verified 2026-09-16: an unauthenticated
      `curl` polled `DELA-5420-AW`'s command queue and got 200. Anyone who can reach
      the API can take a worker's commands (poll marks them SENT), post forged
      results (e.g. a `validate_dir` result that passes content validation and feeds
      PIM), or re-register a hostname with their own key while it stays ACTIVE.
      Proposed fix (pending sign-off): dedicated worker hostname with Traefik
      `RequireAnyClientCert` + `passTLSClientCert`, API ports bound to 127.0.0.1,
      header stripped on the other routers, backend pins the presented certificate
      against the stored one; a changed certificate on register -> PENDING + audit.
- [ ] **SECURITY - the worker accepts any server certificate**
      (`ApiClient.cs`: `ServerCertificateValidationCallback = ... => true`, commented
      "for testing - remove in production"). Anyone who can intercept worker traffic
      can impersonate the API and send it commands. Needs a worker change.
- [ ] **Audit IPs are spoofable:** `get_client_ip` trusts the leftmost
      `X-Forwarded-For` from any client, and the API is reachable without Traefik.
- [ ] **`wait_for_command_completion` can mark a delivered command TIMEOUT.** It sets
      `TIMEOUT` unconditionally; a poll that marked the command SENT after the
      waiter's last refresh is overwritten, the worker still executes it, and its
      late response flips the command/operation to COMPLETED after the caller
      reported a timeout. Make the TIMEOUT update conditional on `status='PENDING'`
      and decide what a late response to a TIMEOUT command should do.
- [ ] **`tests/test_auth.py` cannot run:** 17 tests request a `db_session` fixture
      that exists nowhere (no `conftest.py`).
- [ ] **`Base.metadata.create_all` fails:** `WorkerCommand.created_at` has
      `index=True` *and* an explicit `Index("ix_worker_commands_created_at")`.
      Harmless for Alembic deployments; blocks metadata-built test schemas.

---

## ACTIVE TODO ITEMS

### Known Issues
- [x] **Remote syslog delivery not working:** Fixed — see DONE.md 2026-02-10 entry.

### Future Work (Windows Client)
- [ ] Device authorization page localization (currently English-only, installer has Polish)
- [ ] Add additional languages beyond English and Polish (optional)

### Future Work (General)
- [ ] Consider migrating to a component framework (React/Vue) — long-term

### Follow-ups from PIM delivery / tgId / image host sync (2026-09-16)
- [ ] **DBA: deploy the updated `RFM_sp_ValidateProductName`** (`docs/polkasql/RFM_ValidateProductName.sql`,
      ALTER PROCEDURE only; the web service is unchanged). Until then the procedure returns no
      `tg_id`, and with PIM enabled every event whose template uses `{tg_id}` waits in retry
      with "returned no tg_id" instead of being sent without it.
- [ ] Turn on PIM (with a real or mock endpoint) and `remote_sync_check_enabled` on dev and
      watch a real PUSH go WAITING -> CHECKING -> SYNCED in the history.
- [ ] An UPDATE that *replaces* a file cannot be verified on the image host by existence:
      the old image already answers 200. Comparing `Last-Modified`/`ETag` to the UPDATE time
      would work if the host changes them.
- [ ] WebSocket `operation_integration_update` reaches only clients of the API process
      that made the change (4 uvicorn processes, no shared pub/sub); the 10 s history
      polling covers the rest. Same limitation as every other broadcast.

### Follow-ups from stopping PIM / sync jobs (2026-09-17)
- [ ] A sync check WAITING for a PIM event that was stopped (or FAILED) keeps waiting, polled
      every 15 s, until the event is sent again or the check is stopped too. Stopping PIM does
      not stop the check on purpose: sending again should resume both.

### Follow-ups from the PIM file name rule (2026-09-17)
- [ ] With `enable_push_flatten` on, nested files are copied flat into Path B, but the PIM
      list and the name rule only see top-level files, so PIM is not told about them.
- [ ] PIM events queued before the fix keep their stored `files` (dev: event 1 / operation 9
      still lists `Thumbs.db` and keeps failing with 422). Stop it from the operation details
      (or Admin Panel -> PIM -> Stop all). Sending it again resends the same stored list.

### Follow-ups from UPDATE replace/add (2026-09-16)
- [ ] **UPDATE and PULL of the same catalog are not mutually exclusive.** UPDATE locks
      the B: path, PULL the A: path, and `_operation_locks` is per process (4 uvicorn
      workers), so neither lock covers the other request anyway.
- [ ] Explorer console error on load when active operations exist:
      `loadActiveOperations` -> `addOperationToQueue` expects the legacy dual-pane queue
      element (`querySelector` of null). Pre-existing.

### Follow-ups from the 2026-09-16 integration work
- [ ] **Ask the DBA whether `RFM_sp_Auth`'s second API key slot is free for dev.**
      Dev and prod currently share every secret, including `POLKA_AUTH_API_KEY`;
      a JWT minted by dev validates against prod.
- [ ] Decide whether existing ROSAPI config keys should stop being overwritten by
      `_sync_env_config_to_db()` on every restart, as the new PIM keys now are.
      Today an Admin Panel edit to any ROSAPI key is silently reverted on restart.
      `push_ignore_file_masks`, `enable_push_flatten` and `enable_push_archive` are in the
      same always-synced block, so a mask added in the Admin Panel is lost on restart.
- [ ] Admin Panel markup has no `data-i18n` attributes at all (explorer has 70),
      so the panel is English-only. New sections follow that existing convention.

---

> **Completed work:** See DONE.md
> **Lessons learned:** See LESSONS_LEARNED.md
