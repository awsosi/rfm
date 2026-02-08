# RFM Shell Extension

Windows Explorer context menu extension for RFM (Remote File Manager).

## Overview

The RFM Shell Extension is a C++ ATL COM DLL that integrates with Windows Explorer's context menu. When users right-click on folders in allowed paths, the extension adds RFM menu items.

## Features

- **Context Menu Integration**: Right-click → "Prepare selected to be sent with RFM" and "Send selected with RFM"
- **Path Validation**: Only shows menu items for paths configured in `config.json`
- **Single/Multiple Selection**: "Send" option only appears for single folder selection
- **Launcher Integration**: Invokes `RFMLauncher.exe` with appropriate parameters

## Building

### Prerequisites

- Visual Studio 2019 or later
- Windows SDK 10.0 or later
- ATL libraries (included with Visual Studio C++ workload)

### Build Steps

1. Open `RFMShellExt.vcxproj` in Visual Studio
2. Select configuration (Debug or Release)
3. Select platform (Win32 or x64)
4. Build → Build Solution (or F7)

### Command Line Build

```batch
# Build Release x64
msbuild RFMShellExt.vcxproj /p:Configuration=Release /p:Platform=x64

# Build Debug x86
msbuild RFMShellExt.vcxproj /p:Configuration=Debug /p:Platform=Win32
```

## Registration

### Developer Registration (Manual)

```batch
# Register (requires Administrator)
regsvr32 RFMShellExt.dll

# Unregister
regsvr32 /u RFMShellExt.dll

# Restart Windows Explorer
taskkill /f /im explorer.exe
start explorer.exe
```

### Installer Registration

The WiX installer handles COM registration automatically.

## Configuration

The shell extension reads `config.json` from the same directory as `RFMLauncher.exe`:

```json
{
  "allowed_paths": [
    "\\\\server\\share",
    "G:\\"
  ]
}
```

Only folders within these paths will show RFM context menu items.

## Architecture

### COM Interfaces Implemented

- **IShellExtInit**: Initializes the shell extension with selected file/folder information
- **IContextMenu**: Provides context menu items and handles command invocation

### Key Components

1. **CRFMContextMenu**: Main COM class implementing shell extension interfaces
2. **Utils**: Helper functions for path validation and configuration loading
3. **Registry Scripts (.rgs)**: COM registration entries

### Menu Items

- **IDM_RFM_PREPARE** (ID: 0): "Prepare selected to be sent with RFM"
  - Always shown for allowed paths
  - Launches: `RFMLauncher.exe --prepare "path"`

- **IDM_RFM_SEND** (ID: 1): "Send selected with RFM"
  - Only shown for single folder selection
  - Launches: `RFMLauncher.exe --push "path"`

## Code Structure

```
RFMShellExt/
├── RFMShellExt.vcxproj      # Visual Studio project
├── RFMShellExt.idl          # COM interface definition
├── RFMShellExt.def          # DLL exports
├── RFMShellExt.rc           # Resources (version, strings)
├── RFMShellExt.rgs          # COM registration script
├── dllmain.cpp              # DLL entry point
├── RFMContextMenu.h         # Context menu class header
├── RFMContextMenu.cpp       # Context menu implementation
├── RFMContextMenu.rgs       # Context menu registration
├── Utils.h                  # Utility functions header
├── Utils.cpp                # Path validation, config loading
├── pch.h/cpp                # Precompiled headers
└── framework.h              # ATL/Windows headers
```

## Debugging

### Attach to Explorer

1. Build Debug configuration
2. Visual Studio → Debug → Attach to Process
3. Find `explorer.exe`
4. Attach debugger
5. Set breakpoints in shell extension code
6. Right-click a folder to trigger breakpoints

### Debug Output

Add debug output:

```cpp
OutputDebugString(L"RFM: Initialize called\n");
OutputDebugString((L"RFM: Path: " + m_selectedPath).c_str());
```

View with [DebugView](https://docs.microsoft.com/en-us/sysinternals/downloads/debugview).

### Common Issues

**Context menu doesn't appear**:
- Check path is in `allowed_paths`
- Verify DLL is registered: `reg query "HKCR\Directory\shellex\ContextMenuHandlers\RFM"`
- Restart Windows Explorer
- Check Event Viewer for COM errors

**DLL won't register**:
- Run regsvr32 as Administrator
- Verify all dependencies are present (ATL DLLs)
- Check for missing exports in .def file

**Crashes in Explorer**:
- Check for memory leaks (unreleased COM objects)
- Validate all pointers before use
- Test with Debug build to catch assertions

## Testing

### Unit Testing

Test path validation:

```cpp
// Test allowed path
ASSERT_TRUE(Utils::IsPathAllowed(L"\\\\server\\share\\folder"));

// Test disallowed path
ASSERT_FALSE(Utils::IsPathAllowed(L"C:\\Windows"));
```

### Integration Testing

1. Register DLL
2. Open Windows Explorer
3. Navigate to allowed path
4. Right-click folder
5. Verify menu items appear
6. Click "Prepare selected to be sent with RFM"
7. Verify launcher opens browser

## Performance Considerations

- **Fast Path Validation**: Early exit for non-allowed paths (no menu items added)
- **Lazy Config Loading**: Configuration loaded on first Initialize call
- **Minimal Resource Usage**: No background threads, timers, or polling
- **Quick Menu Display**: QueryContextMenu completes in <10ms

## Security

- **Path Validation**: Only allowed paths trigger RFM operations
- **No Elevation**: Shell extension runs with user privileges (no admin required)
- **Safe Process Launch**: Command line properly escaped to prevent injection
- **Read-Only Config**: Configuration file is read-only (no write operations)

## Troubleshooting

### Explorer Crashes

If Explorer crashes after installing shell extension:

1. Boot into Safe Mode
2. Unregister DLL:
   ```batch
   regsvr32 /u C:\Path\To\RFMShellExt.dll
   ```
3. Reboot normally
4. Review code for bugs (null pointers, memory leaks, deadlocks)

### Menu Items Missing

Check registry entries:

```batch
# Directories
reg query "HKCR\Directory\shellex\ContextMenuHandlers\RFM"

# Files
reg query "HKCR\*\shellex\ContextMenuHandlers\RFM"

# Folders
reg query "HKCR\Folder\shellex\ContextMenuHandlers\RFM"
```

Expected value: `{C3D4E5F6-A7B8-9012-CDEF-123456789ABC}` (CLSID)

### Launcher Not Found

Shell extension looks for `RFMLauncher.exe` in:
1. Same directory as DLL
2. Parent directory
3. `C:\Program Files\RFM\`

Ensure launcher is installed in one of these locations.

## Deployment

The shell extension is deployed via the WiX installer (see `../Installer/`). The installer:

1. Copies DLL to `C:\Program Files\RFM\`
2. Registers COM server (`regsvr32`)
3. Adds context menu handler registry entries
4. Restarts Windows Explorer (optional)

## Uninstallation

The WiX installer handles uninstallation:

1. Unregisters COM server (`regsvr32 /u`)
2. Removes registry entries
3. Deletes DLL
4. Restarts Windows Explorer

## Resources

- [Windows Shell Extensions](https://docs.microsoft.com/en-us/windows/win32/shell/shell-exts)
- [IContextMenu Interface](https://docs.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-icontextmenu)
- [IShellExtInit Interface](https://docs.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-ishellextinit)
- [ATL COM Tutorial](https://docs.microsoft.com/en-us/cpp/atl/introduction-to-atl)
