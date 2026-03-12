• # Production Context Summary (RFM-VF)

  This file captures the current findings and a concrete plan for the next run.
  No changes were applied yet.

  ## Scope

  Required changes:
  1. Allow users to multiselect folders to be PUSHed (full stack: web app, Windows client, worker if needed).
  2. Fix file masks filtering for PUSH (reported: `Thumbs.db` not excluded).

  ## Current Behavior (Key Findings)

  ### PUSH is single-folder only end-to-end
  - Web UI selection is radio-based and returns exactly one item.
    - `/opt/docker/rfm-vf/frontend/js/ui.js` `renderFileList`, `getSelectedFiles`.
  - Push handler blocks multiple selections.
    - `/opt/docker/rfm-vf/frontend/js/app.js` `handlePushOperation`.
  - API accepts only one `source_path`.
    - `/opt/docker/rfm-vf/backend/api/schemas.py` `FilePushRequest`.
    - `/opt/docker/rfm-vf/backend/api/app.py` `/api/operations/push`.
  - Windows shell extension only shows menu for a single directory.
    - `/opt/docker/rfm-vf/clients/windows/ShellExtension/RFMContextMenu.cpp`.
  - Windows launcher and deep link accept only one path.
    - `/opt/docker/rfm-vf/clients/windows/Launcher/Program.cs`.
    - `/opt/docker/rfm-vf/clients/windows/Launcher/DeepLinkBuilder.cs`.
    - `/opt/docker/rfm-vf/frontend/js/app.js` deep link parsing, `handlePrepareAction`, `handlePushAction`.

  ### PUSH ignore masks exist but cleanup is shallow
  - Config key `push_ignore_file_masks` exists and is used.
    - `/opt/docker/rfm-vf/backend/api/services/operation_service.py` `ignore_masks`.
  - Worker filters ignore masks during copy to PATH_B.
    - `/opt/docker/rfm-vf/workers/FileManagerWorker/FileOperations.cs` `CopyDirectorySync` + `MatchesIgnoreMask`.
  - When archive is enabled, source is moved to PATH_C, then cleanup runs.
    - `/opt/docker/rfm-vf/backend/api/services/operation_service.py` Step 2 and `push_cleanup`.
  - `push_cleanup` only deletes ignored files in the top-level of the archive, not recursively.
    - `/opt/docker/rfm-vf/workers/FileManagerWorker/FileOperations.cs` `PushCleanupAsync`.

  Likely failure mode observed by user:
  `Thumbs.db` is skipped for PATH_B but still appears in PATH_C due to non-recursive cleanup and/or nested placement.

  ## Proposed Implementation (Next Run)

  ### 1) Batch PUSH API (backend)
  Goal: enable multiselect safely without changing worker protocol.

  - Keep `/api/operations/push` for backward compatibility.
  - Add new endpoint, e.g. `/api/operations/push/batch`.
    - Request: `source_paths: list[str]`, `worker_id: int`.
    - Validate each path as Path A, deduplicate, reject empty or mixed invalid types.
    - Acquire path locks per folder and execute sequentially to reuse existing rollback safety.
    - Return per-folder results: success/error, operation ID, error message.
    - Keep audit log entries per operation.
    - No DB schema changes required if we create multiple normal operations.

  ### 2) Web UI multiselect
  - Replace radio-based single selection in Path A with multiselect (checkboxes or multi-select rows).
  - Update selection logic in `/opt/docker/rfm-vf/frontend/js/ui.js`.
  - Update push button enablement and handler in `/opt/docker/rfm-vf/frontend/js/app.js`:
    - Allow one or more directories, reject files.
    - Build batch confirmation message with count and names (limit UI size).
    - Call new batch endpoint.
  - Ensure operation queue shows per-operation entries and stays compatible with PULL behavior.

  ### 3) Windows client multiselect
  - Shell extension: allow multiple selected directories.
    - Modify `GetPathFromDataObject` to collect all selected paths, require all directories, allowed paths.
  - Launcher: accept multiple paths and build deep link with multiple entries.
    - Define deep link query format, e.g. `paths=...` (URL-encoded list).
  - Frontend deep link handling:
    - Parse multiple paths, resolve each via `/api/path/resolve`, select them, then trigger batch push.

  ### 4) Fix ignore masks for PUSH
  Safest fix: keep current transactional copy + archive flow, then perform deterministic recursive cleanup in PATH_C.

  - Update worker `PushCleanupAsync` to delete ignored files recursively, not only top-level.
  - Add logging of counts and failures for recursive cleanup.
  - Verify ignore masks apply to files (not directories) unless explicitly desired.
  - Tests:
    - Nested `Thumbs.db` with archive on/off.
    - Wildcard masks (e.g. `*.tmp`).
    - Flatten on/off interactions.

  ## Notes / Risks
  - Do not change worker protocol for batch push unless needed; fan-out is safer.
  - Keep existing endpoint signatures for backward compatibility.
  - No schema migrations expected if batch = multiple single ops.
  - Ensure UI behavior stays safe with auto-refresh and selections.

  ## Files of Interest
  Backend:
  - `/opt/docker/rfm-vf/backend/api/app.py`
  - `/opt/docker/rfm-vf/backend/api/schemas.py`
  - `/opt/docker/rfm-vf/backend/api/services/operation_service.py`
  - `/opt/docker/rfm-vf/backend/api/routes/path.py`

  Frontend:
  - `/opt/docker/rfm-vf/frontend/js/app.js`
  - `/opt/docker/rfm-vf/frontend/js/ui.js`
  - `/opt/docker/rfm-vf/frontend/js/api.js`
  - `/opt/docker/rfm-vf/frontend/pages/explorer.html`

  Windows client:
  - `/opt/docker/rfm-vf/clients/windows/ShellExtension/RFMContextMenu.cpp`
  - `/opt/docker/rfm-vf/clients/windows/Launcher/Program.cs`
  - `/opt/docker/rfm-vf/clients/windows/Launcher/DeepLinkBuilder.cs`

  Worker:
  - `/opt/docker/rfm-vf/workers/FileManagerWorker/FileOperations.cs`
  - `/opt/docker/rfm-vf/workers/FileManagerWorker/CommandHandler.cs`
