# Lessons Learned - RFM (Remote File Manager)

> **Critical patterns and anti-patterns discovered during development**
> **Purpose:** Prevent recurring bugs and document invisible failure modes
> **Last Updated:** 2026-02-09

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
