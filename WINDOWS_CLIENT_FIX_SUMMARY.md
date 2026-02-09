# Windows Client Integration Fix - Summary

## Issues Fixed

### ✅ Issue #1: Token Refresh Bug
**Problem:** Refresh token was saved to `Description` field but loaded from `SecurePassword`, causing authentication to fail every time the access token expired.

**Fix:** Updated `clients/windows/Launcher/AuthenticationManager.cs:106`
```csharp
// OLD (BROKEN):
string refreshToken = cred.SecurePassword?.ToString();

// NEW (FIXED):
string refreshToken = cred.Description;
```

**Impact:** Users will now only need to authenticate once. The launcher will automatically refresh the access token when it expires, eliminating the need to go through the device flow on every run.

---

### ✅ Issue #2: Path Mapping (Windows Path → Virtual Path)
**Problem:** The Windows client sent real Windows paths (e.g., `\\server\share\path\to\folder`), but the WebUI only extracted the last folder name and looked for it in the current directory. Nested folders were never found.

**Fix:** Implemented complete path resolution system:

#### Backend Changes:
1. **New API endpoint:** `backend/api/routes/path.py`
   - POST `/api/path/resolve` - Converts Windows paths to virtual paths
   - Uses worker's `path_a_prefix` configuration
   - Handles UNC paths, drive letters, and relative paths

2. **Registered route:** `backend/api/app.py`
   - Added path router to main application

#### Frontend Changes:
3. **Updated deep link handling:** `frontend/js/app.js`
   - `handlePrepareAction()` - Now calls `/api/path/resolve` API
   - Navigates to parent directory before selecting folder
   - Properly handles nested folder structures
   - `handlePushAction()` - Awaits prepare action completion

**Impact:** Windows client deep links now work correctly for folders at any depth in the directory structure.

---

## Files Changed

### Backend
- `backend/api/routes/path.py` - **NEW** - Path resolution API endpoint
- `backend/api/app.py` - Added path router registration

### Frontend
- `frontend/js/app.js` - Updated deep link handling (handlePrepareAction, handlePushAction)

### Windows Client
- `clients/windows/Launcher/AuthenticationManager.cs` - Fixed refresh token loading

### Documentation
- `clients/windows/PATH_MAPPING_GUIDE.md` - **NEW** - Path mapping configuration guide
- `WINDOWS_CLIENT_FIX_SUMMARY.md` - **NEW** - This file

---

## Configuration Required

### 1. Worker Configuration (Admin Panel)

Each worker must be configured with `path_a_prefix` that matches the Windows file paths.

**Example:**
```
Worker ID: 1
Name: Photo Archive Worker
path_a_prefix: \\192.168.100.4\DaneFoto-test
```

### 2. Windows Client Configuration

Edit `clients/windows/Launcher/config.json`:

```json
{
  "api_base_url": "https://api.ff.vitkac.local",
  "frontend_base_url": "https://ff.vitkac.local",
  "allowed_paths": [
    "\\\\192.168.100.4\\DaneFoto-test",
    "\\\\HV2012R2.vitkac.local\\DaneFoto-test"
  ],
  "language": "pl-PL",
  "credential_target_prefix": "RFM_ContextMenu"
}
```

**Note:** Make sure `frontend_base_url` is set (this was already added in your config).

---

## Testing Instructions

### Test 1: Token Refresh (Verify No Re-authentication)
1. Delete existing credentials from Windows Credential Manager:
   - Open Credential Manager (Control Panel → User Accounts → Credential Manager)
   - Remove any credentials with target `RFM_ContextMenu`
2. Right-click on a folder → "Prepare selected to be sent with RFM"
3. Authenticate via browser (first time only)
4. Wait 1-2 hours (or set shorter token expiry for testing)
5. Right-click on another folder → "Prepare selected to be sent with RFM"
6. **Expected:** No authentication required, browser opens directly to explorer

### Test 2: Nested Folder Selection (Path Mapping)
1. Configure worker with `path_a_prefix` in Admin Panel
2. Test folder at root level:
   - Right-click: `\\192.168.100.4\DaneFoto-test\TestFolder`
   - **Expected:** Browser opens, navigates to `A:/`, selects `TestFolder`
3. Test nested folder:
   - Right-click: `\\192.168.100.4\DaneFoto-test\path\to\nested\MyFolder`
   - **Expected:** Browser opens, navigates to `A:/path/to/nested`, selects `MyFolder`

### Test 3: Push Operation with Confirmation
1. Right-click on a folder → "Send selected with RFM"
2. **Expected:**
   - Browser opens and authenticates (if needed)
   - Navigates to correct parent directory
   - Selects the folder (highlighted briefly)
   - Confirmation dialog appears: "Push MyFolder?"
   - After confirmation, push operation starts

### Test 4: Different Path Types
Test with various path formats:
- UNC path: `\\server\share\folder`
- Mapped drive: `G:\folder`
- Nested UNC: `\\server\share\path\to\deep\folder`
- Root level: `\\server\share\RootFolder`

---

## Rollback Instructions

If issues occur, you can rollback these changes:

### Backend Rollback:
```bash
# Remove path router registration
# Edit backend/api/app.py and remove:
from api.routes.path import router as path_router
app.include_router(path_router)

# Delete new file
rm backend/api/routes/path.py
```

### Frontend Rollback:
```bash
git checkout frontend/js/app.js
```

### Windows Client Rollback:
```bash
git checkout clients/windows/Launcher/AuthenticationManager.cs
```

---

## Next Steps

1. **Rebuild Windows client:**
   ```bash
   cd clients/windows
   dotnet build -c Release
   ```

2. **Rebuild backend** (if deploying via Docker):
   ```bash
   docker-compose down
   docker-compose build api
   docker-compose up -d
   ```

3. **Configure worker in Admin Panel:**
   - Login to WebUI as admin
   - Navigate to Admin Panel → Workers
   - Edit worker and set `path_a_prefix`

4. **Test all scenarios** as described above

5. **Deploy updated Windows client** to user machines

---

## Known Limitations

- Path resolution requires at least one worker to be registered
- Worker must be online for path resolution to work
- If no `path_a_prefix` is configured, the system attempts to guess the relative path (may not work correctly)

---

## Support

For issues or questions:
- Check the PATH_MAPPING_GUIDE.md for detailed configuration instructions
- Verify worker configuration in Admin Panel
- Check API logs for path resolution errors
- Test path resolution API directly using Swagger UI at `/docs`
