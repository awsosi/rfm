# Windows Client Path Mapping Guide

This guide explains how to configure path mapping between Windows real paths and RFM virtual paths for the Windows context menu integration.

## Overview

The RFM Windows client sends **real Windows paths** (e.g., `\\server\share\folder`), which need to be mapped to **virtual paths** used by the WebUI (e.g., `A:/folder`).

The path resolution is handled by:
1. **Worker configuration** - Each worker has a `path_a_prefix` that defines the root path
2. **Path Resolution API** - `/api/path/resolve` converts Windows paths to virtual paths
3. **Frontend deep link handling** - Automatically navigates to the correct folder

## Configuration Steps

### Step 1: Configure Worker's path_a_prefix

Each worker must be configured with the root path it manages. This is done through the Admin Panel.

**Example configurations:**

#### UNC Path (Network Share)
```json
{
  "worker_id": 1,
  "name": "Photo Archive Worker",
  "path_a_prefix": "\\\\192.168.100.4\\DaneFoto-test"
}
```

#### Mapped Drive
```json
{
  "worker_id": 1,
  "name": "Local Drive Worker",
  "path_a_prefix": "G:\\"
}
```

### Step 2: Configure Windows Client allowed_paths

Edit `config.json` in the Windows client installation directory:

```json
{
  "api_base_url": "https://api.ff.vitkac.local",
  "frontend_base_url": "https://ff.vitkac.local",
  "allowed_paths": [
    "\\\\192.168.100.4\\DaneFoto-test",
    "\\\\HV2012R2.vitkac.local\\DaneFoto-test",
    "G:\\"
  ],
  "language": "pl-PL",
  "credential_target_prefix": "RFM_ContextMenu"
}
```

**Important:** The allowed_paths should match or be subpaths of the worker's `path_a_prefix`.

## How Path Mapping Works

### Example 1: Network Share with Subfolder

**Configuration:**
- Worker `path_a_prefix`: `\\192.168.100.4\DaneFoto-test`
- User right-clicks on: `\\192.168.100.4\DaneFoto-test\projects\2024\vacation`

**Conversion:**
1. Windows path: `\\192.168.100.4\DaneFoto-test\projects\2024\vacation`
2. Strip prefix: `projects\2024\vacation`
3. Convert to virtual: `A:/projects/2024/vacation`
4. Parent path: `A:/projects/2024`
5. Folder name: `vacation`

**Result:**
- WebUI navigates to `A:/projects/2024`
- Selects folder `vacation`

### Example 2: Root Level Folder

**Configuration:**
- Worker `path_a_prefix`: `G:\`
- User right-clicks on: `G:\MyProject`

**Conversion:**
1. Windows path: `G:\MyProject`
2. Strip prefix: `MyProject`
3. Convert to virtual: `A:/MyProject`
4. Parent path: `A:`
5. Folder name: `MyProject`

**Result:**
- WebUI stays at root `A:/`
- Selects folder `MyProject`

### Example 3: No Prefix Configured

If a worker has no `path_a_prefix` configured, the system will attempt to extract a relative path:

**UNC path:** `\\server\share\projects\folder` → `A:/projects/folder`
**Drive path:** `G:\projects\folder` → `A:/projects/folder`

## Troubleshooting

### Issue: "Path does not match worker's path_a_prefix"

**Cause:** The Windows path doesn't start with the worker's configured prefix.

**Solution:**
1. Check worker configuration in Admin Panel
2. Verify the worker's `path_a_prefix` matches the network share or drive
3. Ensure Windows client `allowed_paths` includes the path

### Issue: "Folder not found in directory"

**Cause:** The folder doesn't exist at the resolved virtual path.

**Solution:**
1. Verify the folder exists on the file system
2. Check worker has access to the path
3. Refresh the file listing in the WebUI

### Issue: "No workers available"

**Cause:** No workers are registered in the system.

**Solution:**
1. Register a worker through the Admin Panel
2. Configure the worker's `path_a_prefix`
3. Ensure the worker is online

## API Reference

### POST /api/path/resolve

Converts a Windows path to a virtual path.

**Request:**
```json
{
  "windows_path": "\\\\server\\share\\projects\\MyFolder",
  "worker_id": 1
}
```

**Response:**
```json
{
  "virtual_path": "A:/projects/MyFolder",
  "folder_name": "MyFolder",
  "parent_path": "A:/projects",
  "worker_id": 1
}
```

## Testing

### Test Path Resolution

1. Configure a worker with `path_a_prefix`
2. Right-click on a folder within the allowed path
3. Select "Prepare selected to be sent with RFM"
4. Verify:
   - Browser opens to correct WebUI URL
   - Navigates to correct parent directory
   - Selects the correct folder
   - Folder is highlighted briefly

### Test Push Operation

1. Right-click on a folder
2. Select "Send selected with RFM"
3. Verify:
   - Browser opens and navigates to folder
   - Folder is selected
   - Confirmation dialog appears
   - After confirmation, push operation starts

## Additional Notes

- Path mapping is case-insensitive on Windows
- Both forward slashes (/) and backslashes (\) are supported
- Trailing slashes are automatically removed
- The first registered worker is used if no worker_id is specified
