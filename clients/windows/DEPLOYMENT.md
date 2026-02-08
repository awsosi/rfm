# RFM Windows Client - Deployment Guide

Guide for IT administrators deploying the RFM Windows Client.

## Pre-Deployment Planning

### Requirements

- **OS**: Windows 10 (1809+) or Windows 11
- **Framework**: .NET Framework 4.8 (usually pre-installed)
- **Permissions**: Administrator rights for installation
- **Network**: HTTPS access to RFM server

### Configuration Planning

Before deployment, determine:

1. **RFM Server URL**: `https://rfm.company.com`
2. **Allowed Paths**: Which network shares/drives can use RFM
3. **Default Language**: English or Polish
4. **Authentication**: Users need RFM accounts

## Configuration File Customization

### Default config.json

Located in installer at: `Installer/Files/config.json`

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

### Customization Steps

1. Edit `config.json` **before** building installer
2. Set `api_base_url` to your RFM server
3. Set `allowed_paths` to your network shares/drives
4. Set default `language` (users can change in web app)
5. Build installer with your configuration

### Path Configuration Guidelines

**UNC Paths** (recommended for network shares):
```json
"\\\\server\\share"
"\\\\192.168.1.100\\DaneFoto"
```

**Mapped Drives**:
```json
"G:\\"
"H:\\Projects"
```

**Local Paths** (if needed):
```json
"C:\\Data"
"D:\\Archive"
```

**Wildcard Matching**:
- Paths are prefix-matched
- `\\server\share` allows all subdirectories
- Be specific to limit access

## Deployment Methods

### Method 1: Interactive Installation

For individual workstations or small deployments.

```batch
RFM-Setup.msi
```

Users will:
1. See language selection dialog
2. Click through installation wizard
3. Complete installation

### Method 2: Silent Installation

For automated deployments.

```batch
msiexec /i RFM-Setup.msi /quiet /norestart LANGUAGE=en-US
```

Parameters:
- `/quiet`: No UI
- `/norestart`: Don't restart computer
- `LANGUAGE`: `en-US` or `pl-PL`

### Method 3: Group Policy Deployment

For enterprise-wide deployment.

#### Steps

1. **Copy MSI to Network Share**
   ```
   \\domain\SYSVOL\domain\software\RFM-Setup.msi
   ```

2. **Create GPO**
   - Open Group Policy Management
   - Create new GPO: "RFM Windows Client"
   - Edit GPO

3. **Configure Software Installation**
   - Computer Configuration → Policies → Software Settings → Software Installation
   - Right-click → New → Package
   - Browse to `\\domain\SYSVOL\domain\software\RFM-Setup.msi`
   - Deployment method: Assigned

4. **Set Installation Options**
   - Advanced → Deployment → Uninstall when policy no longer applies
   - Add transform (.mst) for custom properties if needed

5. **Link GPO**
   - Link to appropriate OU (e.g., Workstations)
   - Enforce if needed

6. **Verify Deployment**
   - Run `gpupdate /force` on test machine
   - Restart machine
   - Check: `Get-WmiObject -Class Win32_Product | Where-Object Name -like "*RFM*"`

### Method 4: SCCM/ConfigMgr Deployment

For System Center Configuration Manager environments.

1. **Create Application**
   - Software Library → Applications → Create Application
   - Type: Windows Installer
   - Location: `\\server\share\RFM-Setup.msi`

2. **Configure Detection Method**
   - Type: Windows Installer
   - Product Code: {GUID from MSI}

3. **Set Installation Command**
   ```
   msiexec /i RFM-Setup.msi /quiet /norestart LANGUAGE=en-US
   ```

4. **Set Uninstall Command**
   ```
   msiexec /x {PRODUCT-CODE} /quiet /norestart
   ```

5. **Deploy to Collection**
   - Right-click application → Deploy
   - Select collection (e.g., "All Workstations")
   - Purpose: Required
   - Schedule: ASAP or maintenance window

## Post-Deployment Verification

### Verify Installation

**Check Files Installed**:
```batch
dir "C:\Program Files\RFM"
```

Expected files:
- `RFMLauncher.exe`
- `RFMShellExt.dll` (if shell extension built)
- `config.json`
- `Newtonsoft.Json.dll`
- `CredentialManagement.dll`
- `locales\en-US.json`
- `locales\pl-PL.json`

**Check Registry**:
```batch
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s | findstr "RFM"
```

**Check COM Registration** (shell extension):
```batch
reg query "HKCR\Directory\shellex\ContextMenuHandlers\RFM"
```

### Test Functionality

1. **Open Windows Explorer**
2. **Navigate to allowed path**
   - Example: `\\192.168.100.4\DaneFoto-test`
3. **Right-click on a folder**
4. **Verify context menu options**:
   - "Prepare selected to be sent with RFM"
   - "Send selected with RFM" (single selection only)
5. **Click "Prepare selected to be sent with RFM"**
6. **Browser should open** with RFM login/device approval
7. **Authenticate** and verify folder is pre-selected

### Common Issues

**Context menu not appearing**:
- Restart Windows Explorer: `taskkill /f /im explorer.exe && start explorer.exe`
- Check path is in `allowed_paths`
- Re-register DLL: `regsvr32 "C:\Program Files\RFM\RFMShellExt.dll"`

**Browser doesn't open**:
- Check default browser is set
- Run manually: `"C:\Program Files\RFM\RFMLauncher.exe" --prepare "\\path\to\folder"`
- Check Event Viewer for errors

## Configuration Updates

### Update config.json Post-Deployment

If you need to update configuration after deployment:

**Method 1: Manual Update**
1. Edit `C:\Program Files\RFM\config.json` on each machine
2. Restart Windows Explorer

**Method 2: GPO Preferences (Recommended)**
1. Create GPO with File Preference
2. Source: Master config.json on network share
3. Destination: `C:\Program Files\RFM\config.json`
4. Action: Replace
5. Apply to computer configuration

**Method 3: Logon Script**
```batch
copy /Y "\\server\share\config\rfm-config.json" "C:\Program Files\RFM\config.json"
taskkill /f /im explorer.exe
start explorer.exe
```

## Monitoring and Maintenance

### Log Monitoring

**Windows Event Viewer**:
- Check Application logs for RFM errors
- Filter by source: "RFMLauncher"

**User Reports**:
- Authentication failures
- Context menu not appearing
- Browser not opening

### Credential Management

**View Stored Credentials**:
```powershell
cmdkey /list | Select-String "RFM"
```

**Remove User Credentials** (troubleshooting):
```powershell
cmdkey /delete:RFM_ContextMenu
```

### Version Updates

**To update to newer version**:

1. Build new MSI with updated version number
2. Deploy via GPO/SCCM as upgrade
3. MSI will:
   - Uninstall old version
   - Install new version
   - Preserve config.json (if configured)

**Upgrade Command**:
```batch
msiexec /i RFM-Setup-v2.msi /quiet /norestart
```

## Uninstallation

### Silent Uninstall

```batch
msiexec /x {PRODUCT-CODE} /quiet /norestart
```

Find product code:
```powershell
Get-WmiObject -Class Win32_Product | Where-Object {$_.Name -like "*RFM*"} | Select-Object Name, IdentifyingNumber
```

### GPO Uninstall

1. Edit GPO with RFM software package
2. Right-click package → All Tasks → Remove
3. Choose: "Immediately uninstall the software from users and computers"
4. Run `gpupdate /force` on clients

### SCCM Uninstall

1. Right-click application → Deploy
2. Purpose: Uninstall
3. Select collection
4. Schedule deployment

## Security Considerations

### Firewall Rules

Ensure outbound HTTPS allowed to RFM server:
```
Protocol: TCP
Port: 443
Destination: rfm.company.com
```

### User Permissions

- Users need RFM accounts on server
- Users need read access to allowed network shares
- No admin rights needed for operation (only installation)

### Data Flow

1. User right-clicks folder → Shell extension validates path
2. Launcher checks credential manager → token found or auth needed
3. If auth needed → browser opens → user approves on RFM server
4. Token stored in Windows Credential Manager (encrypted)
5. Deep link opened with token → user auto-logged in

### Network Diagram

```
User Workstation                     RFM Server
├─ Shell Extension         ─────────►
├─ Launcher (auth)         ◄─────────  OAuth Device Flow
│  └─ Credential Manager
└─ Default Browser         ◄─────────  Deep Link (HTTPS)
```

## Scaling

### Performance

- Minimal resource usage (context menu only)
- No background services
- Authentication cached (15-minute device flow timeout)

### Large Deployments

For 1000+ workstations:

1. Use GPO or SCCM for centralized deployment
2. Pre-configure config.json in MSI
3. Monitor authentication failures via server logs
4. Consider staggered rollout (pilot → production)

### Network Bandwidth

- Initial auth: ~10KB (device flow)
- Subsequent operations: ~2KB (token refresh)
- Deep link: Browser downloads RFM web app (~500KB first load)

## Support Procedures

### Tier 1: User Issues

**User reports context menu not appearing**:
1. Verify path is in allowed list
2. Restart Windows Explorer
3. Escalate if persists

**User reports authentication failure**:
1. Check RFM server is accessible
2. Clear credentials: `cmdkey /delete:RFM_ContextMenu`
3. Try again (will re-authenticate)
4. Escalate if persists

### Tier 2: System Issues

**Shell extension not loading**:
1. Check COM registration:
   ```batch
   reg query "HKCR\Directory\shellex\ContextMenuHandlers\RFM"
   ```
2. Re-register:
   ```batch
   regsvr32 /u "C:\Program Files\RFM\RFMShellExt.dll"
   regsvr32 "C:\Program Files\RFM\RFMShellExt.dll"
   ```
3. Restart Explorer

**Launcher crashes**:
1. Check Event Viewer logs
2. Verify .NET 4.8 installed
3. Test manual run:
   ```batch
   "C:\Program Files\RFM\RFMLauncher.exe" --prepare "test\path"
   ```
4. Reinstall if corrupted

### Tier 3: Configuration Issues

**Need to change allowed paths**:
1. Update master config.json
2. Deploy via GPO File Preferences or script
3. Restart Explorer on affected machines

**Need to change RFM server URL**:
1. Update config.json
2. Clear all stored credentials:
   ```powershell
   cmdkey /delete:RFM_ContextMenu
   ```
3. Users will re-authenticate to new server

## Appendix: Configuration Schema

```json
{
  "api_base_url": "string (required) - RFM server URL",
  "allowed_paths": [
    "string (required) - Array of allowed path prefixes"
  ],
  "language": "string (optional, default: en-US) - Locale code",
  "credential_target_prefix": "string (optional, default: RFM_ContextMenu) - Credential Manager target"
}
```

## Appendix: MSI Properties

Custom properties for silent install:

- `LANGUAGE`: `en-US` or `pl-PL`
- `INSTALLLEVEL`: `1` (typical) or `3` (complete)

Example:
```batch
msiexec /i RFM-Setup.msi /quiet LANGUAGE=pl-PL
```
