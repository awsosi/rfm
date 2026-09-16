# Server fix: workers must come back ACTIVE on their own after a restart

You are working on the RFM backend (`backend/`, FastAPI + async SQLAlchemy + PostgreSQL) on the `dev-vf` branch. Read `CLAUDE.md` first; its rules apply (single consolidated migration, schema/endpoint/model sync, runtime config read from the `config` table, `ENABLE_*` naming, KISS).

The Windows worker side of this problem is already fixed (`workers/FileManagerWorker`) and running against the dev stack as `DELA-5420-AW`; the section **Worker contract** describes exactly what it does now. Your job is the server side.

---

## The bug

A worker that was approved and working goes offline for more than 5 minutes (reboot, Windows Update, service restart, network outage). When it comes back it can never receive commands again until an administrator manually reactivates it in the admin panel.

Observed on dev (2026-09-16): worker `DELA-5420-AW` (id=2) was ACTIVE, the host rebooted for a scheduled Windows update at 06:04, and from then on every poll was refused with `403 Worker is not active (status: SUSPENDED)`, even though the worker was running, registering and heartbeating normally.

## Root cause (verified in code)

1. **Automatic offline detection and administrator suspension write the same status.**
   - `backend/api/background_tasks.py:103` `_worker_health_check_loop` sets `worker.status = WorkerStatus.SUSPENDED` (line 143) for any ACTIVE worker whose `last_heartbeat` is older than 5 minutes.
   - `backend/api/routes/admin.py:385` `suspend_worker` also sets `WorkerStatus.SUSPENDED`.
   - Nothing records *why* a worker is SUSPENDED, so the server cannot safely undo the automatic case without also undoing a deliberate administrator suspension.

2. **There is no path from SUSPENDED back to ACTIVE except the admin approve endpoint** (`admin.py:334` `approve_worker`).
   - `POST /api/workers/register` (`backend/api/app.py:1624`) for an existing hostname updates name/key/prefixes/`last_heartbeat` but keeps the status.
   - `POST /api/workers/{id}/heartbeat` (`backend/api/routes/worker.py:186`) updates `last_heartbeat` for any status and never changes status.
   - `GET /api/workers/{id}/commands/poll` (`worker.py:41`) returns 403 for any non-ACTIVE worker before it touches anything.
   - So the server *has* the evidence that the worker is alive again (fresh heartbeats) and ignores it.

3. Related inconsistencies you will touch anyway:
   - The health check hardcodes `heartbeat_timeout = 5 * 60` (`background_tasks.py:110`) while a runtime config key `worker_heartbeat_timeout` = `90` exists (`001_initial_schema.py:397`, `api/config.py:98`) and is never read. Per `CLAUDE.md`, runtime code reads config from the DB.
   - `WorkerService._mark_worker_suspended` (`backend/api/services/worker_service.py:190`) has no callers.

## Required behaviour

1. A worker that stops checking in is marked with a status that is **distinct from an administrator suspension**.
2. When that worker checks in again (heartbeat, poll, or register), the server returns it to **ACTIVE automatically**, without administrator action, and records that in the audit log.
3. A worker **suspended by an administrator stays SUSPENDED** across worker restarts, heartbeats and re-registrations. A **PENDING** worker stays PENDING.
4. Nothing about a worker's first-time approval flow changes.

## Recommended design (verify against the code before committing to it)

**Status.** Add a new `WorkerStatus.OFFLINE` value rather than overloading SUSPENDED.
Reason: status stays the single source of truth; the admin UI can show "offline" differently from "suspended"; every existing `status != ACTIVE` check keeps doing the right thing; the worker already handles arbitrary status names (see Worker contract).
The alternative is keeping SUSPENDED plus a nullable `suspended_reason` column. Both need a schema change; pick one and say why in your summary.

**Schema / migration.** `workerstatus` is a native PostgreSQL enum (`001_initial_schema.py:44`, `:109`). `CLAUDE.md` says to merge schema changes into `001_initial_schema.py` rather than add migrations — but the dev and prod databases already exist and will not re-run 001. Update 001 for fresh installs **and** work out how existing databases receive the new value (`ALTER TYPE workerstatus ADD VALUE IF NOT EXISTS 'OFFLINE'`; both compose files run `postgres:16-alpine`, where `ADD VALUE` is allowed inside a transaction but the new value cannot be used until that transaction commits). Look at `scripts/promote-dev-to-prod.sh` for how schema changes currently reach existing databases. **If this conflicts with the single-migration rule, stop and state the conflict and your proposed resolution instead of silently adding a migration file.**

**Health check** (`background_tasks.py`):
- ACTIVE with stale heartbeat → OFFLINE (not SUSPENDED).
- Read the timeout from the `config` table (`worker_heartbeat_timeout`) instead of the hardcoded 5 minutes. Note the current values disagree (90s vs 300s). The worker heartbeats every 60s and every successful poll also refreshes `last_heartbeat`; with automatic recovery a shorter timeout is cheap, but decide deliberately and document the chosen value.
- Log and audit the transition.
- When a worker goes OFFLINE, consider cancelling its PENDING/SENT commands with the existing `CommandQueueService.cancel_pending_commands` (`command_queue_service.py:293`). Today `send_command` already marks a command TIMEOUT after `worker_timeout` (300s) so stale commands are not picked up later, but a command marked SENT right at the edge can still be executed after the caller gave up. Confirm this does not break an operation that is legitimately mid-flight.

**Automatic reactivation**:
- On heartbeat, poll and register from a worker whose status is OFFLINE: set ACTIVE, refresh `last_heartbeat`, write an audit entry (e.g. action `worker_auto_reactivate`, `user_id=None`), log at INFO.
- Do it with a **conditional update** (`UPDATE workers SET status='ACTIVE' WHERE id=:id AND status='OFFLINE'`) so a concurrent administrator suspension is never overwritten.
- In the poll endpoint, reactivate **before** the `status != ACTIVE` check, so the poll that proves the worker is alive is served normally.
- Never transition SUSPENDED → ACTIVE or PENDING → ACTIVE automatically.

**Existing rows.** Workers currently SUSPENDED by the old health check are indistinguishable from administrator suspensions. Leave them SUSPENDED (an administrator reactivates them once) and say so in your rollout note. Dev worker id=2 is in exactly this state right now.

**Admin UI / API surface** (keep schemas in sync per `CLAUDE.md` rule 1):
- `frontend/js/admin-system.js:279` status badge mapping — add OFFLINE.
- `frontend/js/admin.js:509` splits PENDING from everything else — make sure OFFLINE workers show with the active/approved list, visibly marked.
- `backend/api/routes/admin_system.py:575` counts SUSPENDED workers into `workers_suspended` (`schemas_admin.py:125`) — add an offline count or fold it in deliberately.
- Localized labels in `frontend/locales/en-US.json` and `pl-PL.json` if statuses are translated; keep key parity.

**Dead code.** Remove `WorkerService._mark_worker_suspended` or leave it untouched; do not start using it.

## Worker contract (implemented and running on dev — do not break)

The worker (`workers/FileManagerWorker/ApiClient.cs`, `WorkerService.cs`) now behaves as follows:

- **Register** `POST /api/workers/register` on startup and after a 404. Reads `status` from the JSON response and logs it truthfully. It does **not** re-register on 403.
- **Poll** `GET /api/workers/{hostname}/commands/poll?timeout=25`.
  - `200` with `command_id: null` → no command.
  - `403` → worker is not active. The worker extracts the status from the response body with the regex `status:\s*([A-Za-z_]+)`, so **keep the message format `... (status: OFFLINE)`**. While rejected it retries every 30s and logs the state once, not per retry.
  - `404` → the worker record is gone; the worker registers again.
  - any other non-2xx or network failure → "API unreachable", logged once, retried.
  - The first successful poll after a rejection logs "Worker … is ACTIVE again".
- **Heartbeat** `POST /api/workers/{hostname}/heartbeat` every 60s **regardless of status**. This is the liveness signal automatic reactivation can rely on, so keep accepting heartbeats from non-ACTIVE workers.

So with your change a restarted worker returns to service within one heartbeat (≤60s) or one rejected-poll retry (≤30s), whichever reaches the server first.

## Separate, pre-existing security gap (report it; fix it as its own change)

Worker identity is currently just the hostname in the URL. Nothing verifies it:

- `public_key` is stored on register (`app.py:1631`, `:1647`) and never checked anywhere.
- No client-certificate or signature verification exists anywhere in the repository. Traefik's configuration lives on the host, outside the repo — inspect it.
- **Verified on dev 2026-09-16:** a plain `curl` with no client certificate called `GET https://api-dev.ff.vitkac.local/api/workers/DELA-5420-AW/commands/poll?timeout=1` and received `200` (the queue happened to be empty). Anyone who can reach the API can therefore poll an ACTIVE worker's commands (the poll marks them SENT, so the real worker never runs them), post forged results (for example a fabricated `validate_dir` result that passes content validation and feeds PIM), and re-register an existing hostname with their own `public_key` while the server keeps it ACTIVE.
- The worker already presents its client certificate on every request. The certificate is self-signed and **every worker uses the same subject `CN=FileManagerWorker`**, so identity must be established from the public key (pinning against the stored `public_key`), never from the CN.
- Constraints to respect:
  - Traefik client-auth is configured per TLS option / host (SNI), not per path. Requiring a client certificate on `api-dev.ff.vitkac.local` breaks the browser WebUI that uses the same host. Options include a dedicated worker hostname with `RequireAnyClientCert`, or `RequestClientCert` plus the `passTLSClientCert` middleware with the backend enforcing a matching key only on `/api/workers/*`.
  - A register call for an already-approved hostname whose key differs must not silently replace the key; it should require re-approval (PENDING) and be audited.
  - If you choose a request-signing scheme instead of mTLS, the worker must change — say so explicitly so it can be implemented on the worker side.

On ordering: automatic reactivation does **not** materially widen today's exposure (an impostor can already take over an ACTIVE worker, and its own heartbeats would keep that worker from ever going offline), so the reactivation fix does not need to wait for the identity fix. Do not describe worker authentication as existing in any summary or documentation.

## Acceptance criteria

1. Stop the dev worker for longer than the heartbeat timeout → its status becomes OFFLINE (not SUSPENDED) and the admin UI shows it as offline.
2. Start it again → it is ACTIVE within 60 seconds with no administrator action; an audit entry records the automatic reactivation; the worker log shows `Worker DELA-5420-AW is ACTIVE again ... (was OFFLINE)`.
3. An administrator-suspended worker remains SUSPENDED through a worker restart, heartbeats and re-registration. A PENDING worker remains PENDING.
4. A concurrent administrator suspension is never overwritten by automatic reactivation.
5. Tests in `backend/tests/` cover: health-check transition to OFFLINE; reactivation from OFFLINE via poll, heartbeat and register; no reactivation from SUSPENDED or PENDING; the conditional-update guard. Run them and report the actual results.
6. `DONE.md` and `LESSONS_LEARNED.md` are updated as `CLAUDE.md` requires.

## Out of scope

- The double-wrapped `error_details` seam between `api/routes/worker.py` and `api/services/worker_service.py` (tracked in `DONE.md`, 2026-09-16).
- Any change to the worker code — coordinate instead.
