# Lessons Learned - RFM (Remote File Manager)

> **Critical patterns and anti-patterns discovered during development**
> **Purpose:** Prevent recurring bugs and document invisible failure modes
> **Last Updated:** 2026-02-09

---

## Generic Data Channels: Unwrap Once, In One Place

**Problem:** A catalog holding 4 valid images was rejected with "0 of 2 required image files - 0 files in total". The worker log for the very same directory read `7 file(s), 4 image(s), 1 non-image, 2 mismatched`. Nothing errored anywhere; the command round trip reported `success`.

**Root Cause:** The worker's result payload rides on `CommandResponse.error_details` - a field whose name says "errors" but which doubles as the generic data channel for every read-only command (`list`, `search`, `get_status`, `validate_dir`). It gets wrapped twice on the way in:

```
worker                     CommandResponse.error_details = payload
api/routes/worker.py       response_dict["error_details"] = payload      # nested
api/services/worker_service.py
                           WorkerCommandResponse.error_details = response_dict
```

So consumers receive `{"file_count": .., "total_size_bytes": .., "error_details": {...the real payload...}}`. `api/app.py` already unwrapped this in two places, with a comment naming the trap. The newer `validate_directory_content` did not - it read `data.get("files")` off the wrapper, got `None`, and computed `0`.

**Why it was invisible:** `0` is a legal value. Every layer succeeded, the worker was healthy, the command returned `success`, and the UI rendered a confident, specific, *wrong* number. A dropped payload and a genuinely empty directory are indistinguishable downstream - the failure mode is a plausible lie, not an exception.

**Rules:**
1. A field that carries real data must not be named `error_details`. If a channel is generic, name it generically (`data`, `result`) - the misleading name is why each new consumer re-learns the shape the hard way.
2. Unwrap at the seam, once. Every consumer that re-implements the unwrap is a future consumer that will forget it.
3. When a decoded payload yields a falsy count, distinguish "absent" from "zero". `data.get("image_count", 0)` silently turns a structural mismatch into a business verdict.
4. When adding a consumer to an existing channel, grep for how current consumers read it before assuming the obvious shape - in this codebase the existing unwrap was already documented in a comment.
5. Cross-check against the producer's own logs. The worker said 7 files and the server said 0; that contradiction is the fastest possible diagnosis and it was sitting in the log the whole time.

---

## Polling Loops: Never Let the Server Be Your Only Pacing

**Problem:** A single worker awaiting admin approval generated ~6 registrations + polls per second against the API. Nothing errored, nothing was logged as a failure, and the worker reported itself healthy the whole time.

**Root Cause:** `WorkerService.PollingLoop` delayed only in its `catch` block. On the success path it looped straight back into the next poll. That was survivable *only* because `/commands/poll?timeout=30` is a long poll — the server's 30s hold was the loop's sole rate limit.

Two cases break that assumption, and both answer instantly:
- Worker is `PENDING` approval → immediate `403`. `ApiClient` sets `_isRegistered = false` on 403, so each spin **also** re-registered.
- Worker is approved but no command is queued → immediate `204 No Content`.

`PollingIntervalSeconds` existed in config, was parsed, and was logged at startup — but was never referenced by the loop. It looked configured while doing nothing.

**Why it was invisible:** Every individual request *succeeded*. There was no exception, no error log, and no failing operation — just a correct-looking worker quietly saturating the API. It only surfaced because a log file grew 175 KB in 15 seconds.

**Correct Pattern:**
```csharp
var command = await _apiClient.PollForCommandAsync(cancellationToken);

if (command != null)
{
    // ... handle it ...
    continue;               // drain a backlog without an artificial wait
}

// Nothing waiting: pace the loop ourselves. Never assume the server's
// long poll is holding the connection - it does not when it rejects us
// (403 while PENDING) or when it has nothing to send (204).
await Task.Delay(
    _apiClient.IsRegistered
        ? TimeSpan.FromSeconds(_config.PollingIntervalSeconds)
        : TimeSpan.FromSeconds(UnauthorizedRetrySeconds),
    cancellationToken);
```

**Rules:**
1. A polling loop owns its own pacing. Server-side long-poll timeouts are an optimization, not a rate limit.
2. If a config value names an interval, the loop must actually use it — otherwise delete it rather than log it.
3. Treat "auth rejected" as a distinct, slower backoff. Retrying an authorization decision at full speed can never help; only an admin action changes it.
4. Watch log growth rate, not just log contents. An all-`INFO` log growing at 10 KB/s is an incident.

---

## Windows Client Integration: Credential Storage and Path Mapping

**Problem:** Windows client required authentication every time despite implementing OAuth device flow. Additionally, deep links only worked for root-level folders, not nested directory structures.

**Root Cause 1 - Token Refresh Bug:** Refresh token was saved to `Credential.Description` field (line 311 in AuthenticationManager.cs: `cred.Description = refreshToken`) but loaded from `Credential.SecurePassword` field (line 106: `string refreshToken = cred.SecurePassword?.ToString()`). This mismatch meant the refresh token was never actually loaded, causing token refresh to fail silently. When the access token expired (typically after 1 hour), the launcher couldn't refresh it and had to fall back to device flow authentication every time.

**Root Cause 2 - Missing Path Mapping:** The Windows launcher sent real Windows paths (e.g., `\\server\share\path\to\nested\MyFolder`), but the frontend only extracted the last folder name (`MyFolder`) and looked for it in the current directory. There was no:
- API endpoint to convert Windows paths → virtual paths
- Navigation to the correct parent directory
- Usage of worker's `path_a_prefix` configuration for path resolution

**Correct Pattern:**
```csharp
// AuthenticationManager.cs - CORRECT token loading
public string GetValidToken()
{
    var cred = LoadCredential(_config.CredentialTargetPrefix);
    if (cred == null) return null;

    string accessToken = cred.Password;

    if (IsTokenExpired(accessToken))
    {
        // Load refresh token from Description field (matches save location)
        string refreshToken = cred.Description;
        if (!string.IsNullOrEmpty(refreshToken))
        {
            string newToken = RefreshToken(refreshToken);
            if (newToken != null)
            {
                SaveCredential(_config.CredentialTargetPrefix, cred.Username, newToken, refreshToken);
                return newToken;
            }
        }
        return null;
    }
    return accessToken;
}
```

**Path Resolution API:**
```python
# Backend: POST /api/path/resolve
@router.post("/resolve", response_model=PathResolveResponse)
async def resolve_path(request: PathResolveRequest):
    # Get worker's path_a_prefix (e.g., \\server\share)
    worker = await db.get(Worker, request.worker_id)

    # Strip prefix from Windows path
    windows_path = request.windows_path  # \\server\share\path\to\folder
    path_a_prefix = worker.path_a_prefix  # \\server\share
    relative_path = windows_path[len(path_a_prefix):].replace('\\', '/')

    # Convert to virtual path
    virtual_path = f"A:/{relative_path}"  # A:/path/to/folder
    parent_path = '/'.join(virtual_path.split('/')[:-1])  # A:/path/to
    folder_name = virtual_path.split('/')[-1]  # folder

    return PathResolveResponse(
        virtual_path=virtual_path,
        parent_path=parent_path,
        folder_name=folder_name
    )
```

**Frontend Deep Link Handling:**
```javascript
// Frontend: Call API, navigate to parent, select folder
async function handlePrepareAction(targetPath) {
    // 1. Resolve Windows path to virtual path
    const response = await fetch('/api/path/resolve', {
        method: 'POST',
        body: JSON.stringify({ windows_path: targetPath, worker_id: state.workerId })
    });
    const pathInfo = await response.json();

    // 2. Navigate to parent directory
    await loadDirectory('a', pathInfo.parent_path);

    // 3. Select folder in file list
    setTimeout(() => {
        const rows = document.querySelectorAll('#file-list-body-a tr');
        for (const row of rows) {
            const nameCell = row.querySelector('.file-name');
            if (nameCell?.textContent.trim() === pathInfo.folder_name) {
                row.querySelector('input[type="radio"]').checked = true;
                break;
            }
        }
    }, 800);
}
```

**Wrong Patterns:**
```csharp
// WRONG 1 - Loading from wrong field
string refreshToken = cred.SecurePassword?.ToString();  // Always null!

// WRONG 2 - No path resolution, only extracting folder name
const folderName = targetPath.split(/[\\\/]/).pop();
// Looks for "MyFolder" in current directory (A:/)
// Fails if folder is at A:/path/to/nested/MyFolder
```

**Prevention Checklist:**
- When storing related data in Windows Credential Manager across different fields (Password, Description, etc.), document the field mapping clearly and ensure save/load operations use matching fields
- Always add integration tests that verify token refresh works after token expiration
- For path-based integrations, implement proper path mapping/resolution rather than simple string manipulation
- Worker configuration (`path_a_prefix`) must be documented and properly utilized for Windows path → virtual path conversion
- Test deep links with nested folder structures, not just root-level folders

**Why it's invisible:**
- The refresh token mismatch causes no errors at save or load time. The credential is saved successfully, and `cred.SecurePassword` returns null without error (it's a valid but empty field). Token refresh silently fails and falls back to device flow, which works but creates a poor user experience (authentication required every hour).
- The path mapping issue only manifests when testing with nested folders. Root-level folder selection appears to work, giving a false sense of completeness. Hours wasted debugging "why doesn't this work for nested paths?" when the root cause is the lack of any path resolution system.

---

## Multi-Handler Init Must Be Fault-Isolated Per Handler

**Problem:** Remote syslog never delivered any messages despite correct configuration (enabled, host set, port set). Settings persisted across restart. No errors visible anywhere.

**Root Cause:** `setup_logging()` in `logging_module/logger.py` initialized handlers sequentially without error isolation. When `FileHandler` init failed (e.g. can't create `/var/log/file-manager/` — permission issue, missing volume, running on Windows), the exception propagated, `_global_handler` was never set, and stayed `None`. Downstream code (`_reconfigure_logging_from_db()`, admin UI, `create_audit_log()`) all checked `if _global_handler is not None` and silently skipped. The catch-all `except Exception: pass` in `create_audit_log()` hid the failure completely.

**Anti-pattern:**
```python
# BAD - One handler failure breaks ALL handlers
handler = MultiHandler()
rotator = LogRotator(config)           # If THIS fails...
file_handler = FileHandler(path, rotator)
handler.add_handler(file_handler)
handler.add_handler(SyslogHandler(...))  # ...this never runs
_global_handler = handler               # ...and this is never reached
```

**Correct pattern:**
```python
# GOOD - Each handler isolated
handler = MultiHandler()
try:
    handler.add_handler(FileHandler(path, LogRotator(config)))
except Exception as exc:
    logger.warning(f"File handler failed: {exc}")
try:
    handler.add_handler(SyslogHandler(...))
except Exception as exc:
    logger.warning(f"Syslog handler failed: {exc}")
_global_handler = handler  # Always set — some handlers may work even if others fail
```

**Additional rule:** When a global singleton (`_global_handler`) can be None, any code that needs to SET it must use `import module` (not `from module import var`), because `from X import Y` only copies the reference and can't update the module-level variable.

**Why it's invisible:** Five layers of silent swallowing: (1) `setup_logging()` exception caught by lifespan with just a warning, (2) `_reconfigure_logging_from_db()` silently returns on None, (3) admin UI reconfiguration silently skips on None, (4) `create_audit_log()` catches all exceptions with `pass`, (5) UDP socket sends "succeed" locally even if no server receives them. No single layer produces a visible error.

---

## WebSocket Query Parameters Must Be Manually Parsed

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

## WebSocket Accept-Before-Close Pattern

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

> **See TODO.md for additional rules and checklists**
> **See DONE.md for implementation history and bug fixes**
