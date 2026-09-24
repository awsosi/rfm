# RFM Windows Client Integration

Windows context menu integration for RFM (Remote File Manager).

## Overview

The RFM Windows Client provides seamless integration between Windows Explorer and the RFM web application through:

- **Shell Extension**: Right-click context menu in Windows Explorer
- **Launcher Application**: OAuth device flow authentication and deep linking
- **RFM Tray**: sends catalog folders dropped into watched folders automatically ([Tray/README.md](Tray/README.md))
- **MSI Installer**: Easy deployment and configuration

## Architecture

### Components

1. **Shell Extension** (C++ ATL COM DLL)
   - Registers in Windows Explorer context menu
   - Validates selected paths against allowed prefixes
   - Launches the Launcher application with appropriate parameters

2. **Launcher Application** (C# .NET 4.8 Console)
   - Handles OAuth device flow authentication
   - Stores/retrieves tokens from Windows Credential Manager
   - Hands the action to an RFM tab that is already open and signed in
     (`POST /api/client-actions`); only when no tab takes it within 3 s does it
     build a deep link URL and open a new tab

3. **RFM Tray** (C# .NET 4.8 WinForms, `Tray/`)
   - Tray icon started at sign-in by a scheduled task
   - Watches the user's hand-off folders and PUSHes each finished folder under the user's sign-in
   - Shows RFM's refusals (name, suggestions, contents) and renames a folder in one click

4. **Configuration File** (JSON)
   - Stores allowed path prefixes, API URL, language preference
   - Per-machine configuration

5. **Installer** (WiX Toolset)
   - Deploys shell extension DLL, launcher EXE and RFM Tray
   - Registers the `RFM\RFM Tray` sign-in task
   - Prompts for language during installation
   - Registers COM shell extension

## Installation

### User Installation

1. Download `RFM-Setup.msi`
2. Run the installer
3. Select language (English or Polish)
4. Complete installation
5. Right-click on a folder in Windows Explorer to see RFM menu items

### Silent Installation (IT Admins)

```batch
msiexec /i RFM-Setup.msi /quiet LANGUAGE=en-US
```

Parameters:
- `LANGUAGE`: `en-US` or `pl-PL`

### Configuration

Edit `C:\Program Files\RFM\config.json` after installation:

```json
{
  "api_base_url": "https://rfm.company.com",
  "allowed_paths": [
    "\\\\192.168.100.4\\DaneFoto-test",
    "\\\\HV2012R2.vitkac.local\\DaneFoto-test",
    "G:\\"
  ],
  "language": "en-US",
  "credential_target_prefix": "RFM_ContextMenu"
}
```

Optional keys:
- `watch_folders`: RFM Tray's watched folders until a user picks their own (installer: `WATCH_FOLDERS="path1;path2"`)
- `browser_window_titles`: parts of the RFM tab title used to bring its browser window to the front
  (default: the Explorer page title in English and Polish)

**Important**: Restart Windows Explorer after editing `config.json`:
```batch
taskkill /f /im explorer.exe
start explorer.exe
```

## Usage

### Context Menu Options

When you right-click on a folder in an allowed path:

If RFM is already open and signed in, both options run in that tab instead of
opening a new one; its title flashes if it is in the background.

1. **"Prepare selected to be sent with RFM"**
   - Always available
   - Opens RFM web app
   - Pre-selects the folder
   - Ready for you to click "Push"

2. **"Send selected with RFM"**
   - Only for single folder selection
   - Opens RFM web app
   - Auto-triggers push operation

### First Use - Authentication

On first use, the launcher will:

1. Open your browser to the RFM authentication page
2. Display a user code (e.g., "ABC-123")
3. You enter the code in the browser
4. Click "Approve Device"
5. Credentials are stored securely

Future operations use the stored credentials automatically.

## Building from Source

### Prerequisites

- Visual Studio 2019 or later
- .NET Framework 4.8 SDK
- Windows SDK (for C++ shell extension)
- WiX Toolset 3.11 or later

### Build Steps

1. **Launcher**
   ```
   cd clients/windows/Launcher
   nuget restore RFMLauncher.csproj
   msbuild RFMLauncher.csproj /p:Configuration=Release
   ```

2. **Shell Extension** (see `ShellExtension/README.md`)

3. **Installer** (see `Installer/README.md`)

## Deployment

### Fast Provisioning

For quick deployment with pre-configured settings:

1. Edit `Launcher/config.json` with your settings
2. Build the installer
3. Distribute the MSI to users

The installer includes your pre-configured `config.json`.

### Group Policy Deployment

Deploy via GPO:

1. Copy MSI to network share
2. Create GPO: Computer Configuration → Software Installation
3. Add package: `\\server\share\RFM-Setup.msi`
4. Configure installation options

## Troubleshooting

### Context Menu Not Appearing

**Symptoms**: Right-click menu doesn't show RFM options

**Solutions**:
1. Check if path is in `allowed_paths` in `config.json`
2. Restart Windows Explorer:
   ```batch
   taskkill /f /im explorer.exe
   start explorer.exe
   ```
3. Re-register shell extension:
   ```batch
   cd "C:\Program Files\RFM"
   regsvr32 RFMShellExt.dll
   ```

### Authentication Issues

**Symptoms**: "Authentication failed or timed out"

**Solutions**:
1. Check network connectivity to RFM server
2. Verify `api_base_url` in `config.json`
3. Clear stored credentials:
   - Control Panel → Credential Manager
   - Windows Credentials → Remove "RFM_ContextMenu"
4. Try again (will trigger re-authentication)

### Token Expired

**Symptoms**: Opens browser but shows login page instead of auto-login

**Solutions**:
- Launcher automatically refreshes tokens
- If refresh fails, clear credentials (see above) and re-authenticate

### Browser Doesn't Open

**Symptoms**: Nothing happens after right-click action

**Solutions**:
1. Check default browser is set
2. Run launcher manually to see errors:
   ```batch
   cd "C:\Program Files\RFM"
   RFMLauncher.exe --prepare "\\server\share\folder"
   ```
3. Check Windows Event Viewer for errors

### Path Not Allowed

**Symptoms**: "Path not allowed" message

**Solutions**:
1. Verify exact path in `allowed_paths`
2. Use correct separators (backslashes for UNC)
3. Example allowed path formats:
   - `\\server\share` (UNC)
   - `G:\` (mapped drive)
   - `C:\Data` (local path)

## Security

- **OAuth Device Flow**: Secure authentication without exposing passwords
- **Windows Credential Manager**: Encrypted credential storage
- **HTTPS Required**: All API communication over HTTPS
- **Token Refresh**: Automatic token renewal
- **No Local Passwords**: Only tokens stored, passwords never cached

## Uninstallation

### Via Control Panel

1. Control Panel → Programs and Features
2. Select "RFM Windows Integration"
3. Click Uninstall

### Silent Uninstall

```batch
msiexec /x {PRODUCT-CODE-GUID} /quiet
```

Find product code in registry:
```
HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall
```

## Support

For issues or questions:
- Check troubleshooting section above
- Review logs in Windows Event Viewer
- Contact your RFM administrator

## Version History

### 1.1.0 (2026-09-24)
- Context menu runs in the RFM tab that is already open instead of opening a new one
- RFM Tray: sends finished folders from watched folders (`WATCH_FOLDERS`), started at sign-in
- Upgrades 1.0.0 in place (the version must rise with every release, or MSI installs side by side)

### 1.0.0 (2026-02-08)
- Initial release
- OAuth device flow authentication
- Context menu integration
- English and Polish localization
- Deep linking support
