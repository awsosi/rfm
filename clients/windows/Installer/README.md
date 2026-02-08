# RFM Windows Installer

WiX Toolset installer for RFM Windows Integration.

## Overview

The RFM Installer packages the Launcher and Shell Extension into a single MSI installer with:

- Language selection during installation (English/Polish)
- .NET Framework 4.8 prerequisite checking
- COM registration for shell extension
- Configuration file deployment
- Start Menu shortcuts
- Automatic Windows Explorer restart

## Prerequisites

### Build Requirements

- WiX Toolset 3.11 or later
  - Download: https://wixtoolset.org/
  - Install Visual Studio extension
- Visual Studio 2019 or later
- .NET Framework 4.8 SDK
- Windows SDK

### Runtime Requirements (Target Systems)

- Windows 10 (1809+) or Windows 11
- .NET Framework 4.8 (installer checks for this)
- Administrator rights for installation

## Building

### Visual Studio Build

1. Open `RFMSetup.wixproj` in Visual Studio
2. Ensure Launcher and ShellExtension projects are built first
3. Build → Build Solution (or F7)
4. Output: `bin\Release\RFM-Setup.msi`

### Command Line Build

```batch
# Build dependencies first
cd ..\Launcher
msbuild RFMLauncher.csproj /p:Configuration=Release

cd ..\ShellExtension
msbuild RFMShellExt.vcxproj /p:Configuration=Release /p:Platform=x64

# Build installer
cd ..\Installer
msbuild RFMSetup.wixproj /p:Configuration=Release
```

### Using WiX Command Line Tools

```batch
# Compile WiX source to object file
candle Product.wxs

# Link to create MSI
light -out RFM-Setup.msi Product.wixobj
```

## Configuration

### Pre-Deployment Customization

Edit `Files\config.json` **before** building the installer to pre-configure:

```json
{
  "api_base_url": "https://your-rfm-server.com",
  "allowed_paths": [
    "\\\\your-server\\share",
    "G:\\"
  ],
  "language": "en-US",
  "credential_target_prefix": "RFM_ContextMenu"
}
```

This configuration will be deployed to all target machines.

### Post-Installation Updates

To update configuration on deployed machines:

**Option 1: Manual Edit**
- Edit `C:\Program Files\RFM\config.json`
- Restart Windows Explorer

**Option 2: GPO Deployment**
- Create GPO with File Preferences
- Source: `\\domain\share\rfm-config.json`
- Destination: `C:\Program Files\RFM\config.json`
- Action: Replace

## Installation

### Interactive Installation

```batch
RFM-Setup.msi
```

User will see:
1. Welcome screen
2. License agreement
3. Installation progress
4. Completion message

### Silent Installation

```batch
msiexec /i RFM-Setup.msi /quiet /norestart
```

### Silent Installation with Log

```batch
msiexec /i RFM-Setup.msi /quiet /norestart /l*v install.log
```

### Group Policy Deployment

1. Copy MSI to network share: `\\domain\SYSVOL\software\RFM-Setup.msi`
2. Open Group Policy Management
3. Create new GPO: "RFM Windows Client"
4. Computer Configuration → Policies → Software Settings → Software Installation
5. Right-click → New → Package
6. Select `RFM-Setup.msi`
7. Deployment method: Assigned
8. Link GPO to target OU

### SCCM Deployment

1. Software Library → Applications → Create Application
2. Type: Windows Installer (`RFM-Setup.msi`)
3. Detection Method: Windows Installer (Product Code)
4. Installation command:
   ```
   msiexec /i RFM-Setup.msi /quiet /norestart
   ```
5. Uninstall command:
   ```
   msiexec /x {PRODUCT-CODE} /quiet /norestart
   ```
6. Deploy to collection

## Testing

### Test on Clean VM

1. Create Windows 10/11 VM snapshot
2. Copy MSI to VM
3. Install: `msiexec /i RFM-Setup.msi /l*v install.log`
4. Verify installation:
   - Files in `C:\Program Files\RFM\`
   - Registry entries for COM registration
   - Context menu appears in Windows Explorer
5. Test functionality:
   - Right-click folder in allowed path
   - Verify menu items appear
   - Click "Prepare selected to be sent with RFM"
   - Verify launcher opens browser
6. Uninstall: `msiexec /x {PRODUCT-CODE} /quiet`
7. Verify clean removal:
   - Files deleted
   - Registry entries removed
   - Context menu no longer appears

### Test Upgrade

1. Install version 1.0: `msiexec /i RFM-Setup-1.0.msi`
2. Install version 1.1: `msiexec /i RFM-Setup-1.1.msi`
3. Verify old version is removed
4. Verify new version is installed
5. Verify config.json is preserved (if configured)

## Installer Components

### Files Deployed

- **RFMLauncher.exe** - Main launcher application
- **RFMShellExt.dll** - Context menu shell extension
- **config.json** - Configuration file
- **Newtonsoft.Json.dll** - JSON library
- **CredentialManagement.dll** - Credential Manager library
- **locales/en-US.json** - English localization
- **locales/pl-PL.json** - Polish localization

### Registry Entries

**COM Registration**:
```
HKCR\CLSID\{C3D4E5F6-A7B8-9012-CDEF-123456789ABC}
HKCR\CLSID\{...}\InprocServer32 = "C:\Program Files\RFM\RFMShellExt.dll"
```

**Context Menu Handlers**:
```
HKCR\Directory\shellex\ContextMenuHandlers\RFM = "{CLSID}"
HKCR\*\shellex\ContextMenuHandlers\RFM = "{CLSID}"
HKCR\Folder\shellex\ContextMenuHandlers\RFM = "{CLSID}"
```

**Installation Marker**:
```
HKCU\Software\RFM\Integration\installed = 1
```

### Custom Actions

- **RestartExplorer** (install): Restarts Windows Explorer to load shell extension

## Versioning

### Version Number Format

```
Major.Minor.Patch.Build
Example: 1.0.0.0
```

Update version in `Product.wxs`:

```xml
<Product Id="*"
         Name="RFM Windows Integration"
         Version="1.1.0.0"
         ...>
```

### Upgrade Strategy

The installer uses `MajorUpgrade` element:
- Automatically removes old versions
- Prevents downgrades
- Preserves configuration (if configured)

## Troubleshooting

### Build Errors

**"WiX Toolset not found"**:
- Install WiX Toolset 3.11+
- Restart Visual Studio
- Verify WiX build tools in PATH

**"Referenced project output not found"**:
- Build Launcher project first
- Build ShellExtension project first
- Verify output paths match project references

**"Harvesting failed"**:
- Disable harvesting: `<DoNotHarvest>True</DoNotHarvest>`
- Manually specify files in Product.wxs

### Installation Errors

**"This application requires .NET Framework 4.8"**:
- Install .NET Framework 4.8 on target system
- Download: https://dotnet.microsoft.com/download/dotnet-framework/net48

**"Installation failed with error 1603"**:
- Check install log: `msiexec /i RFM-Setup.msi /l*v install.log`
- Look for errors in log (search for "return value 3")
- Common causes:
  - Insufficient permissions (not Administrator)
  - Conflicting previous installation
  - COM registration failure

**"Shell extension doesn't appear after install"**:
- Check if Explorer restarted (log out/log in if not)
- Manually restart Explorer:
  ```batch
  taskkill /f /im explorer.exe
  start explorer.exe
  ```
- Verify registry entries exist (see Registry Entries section)

### Uninstallation Errors

**"Product not found"**:
- Find product code:
  ```powershell
  Get-WmiObject -Class Win32_Product | Where-Object {$_.Name -like "*RFM*"}
  ```
- Use correct product code for uninstall

**"Files not removed"**:
- Manually remove: `C:\Program Files\RFM\`
- Clean registry (run as Administrator):
  ```batch
  reg delete "HKCR\CLSID\{C3D4E5F6-A7B8-9012-CDEF-123456789ABC}" /f
  reg delete "HKCR\Directory\shellex\ContextMenuHandlers\RFM" /f
  ```

## Advanced Customization

### Add Language Selection Dialog

To prompt user for language during installation:

1. Create custom UI dialog in WiX
2. Add property: `<Property Id="LANGUAGE_CHOICE" Value="en-US" />`
3. Add custom action to update config.json with selected language
4. Update `<UIRef>` to include custom dialog

### Conditional Features

To make shell extension optional:

```xml
<Feature Id="ShellExtFeature"
         Title="Context Menu Integration"
         Level="1"
         AllowAdvertise="no">
  <ComponentRef Id="ShellExtComponent" />
</Feature>
```

User can deselect during custom installation.

### Transform Files (.mst)

To create pre-configured installers:

1. Install Orca (MSI editor)
2. Open RFM-Setup.msi
3. Modify properties/files
4. Save as transform: File → Generate Transform
5. Deploy with transform:
   ```batch
   msiexec /i RFM-Setup.msi TRANSFORMS=custom.mst
   ```

## Security Considerations

### Code Signing

Sign the MSI before distribution:

```batch
signtool sign /f certificate.pfx /p password /t http://timestamp.server RFM-Setup.msi
```

Benefits:
- Prevents "Unknown Publisher" warning
- Verifies authenticity
- Required for some enterprise deployments

### Installation Permissions

- Installer requires Administrator rights (installs to Program Files)
- Shell extension runs with user privileges (no elevation needed)
- No services or drivers installed

### File Permissions

Default permissions:
- `C:\Program Files\RFM\` - Read/Execute for Users, Full Control for Administrators
- `config.json` - Read for Users (to prevent tampering)

## Resources

- [WiX Toolset Documentation](https://wixtoolset.org/documentation/)
- [Windows Installer (MSI) Guide](https://docs.microsoft.com/en-us/windows/win32/msi/windows-installer-portal)
- [Group Policy Software Installation](https://docs.microsoft.com/en-us/troubleshoot/windows-server/group-policy/use-group-policy-to-install-software)
- [SCCM Application Deployment](https://docs.microsoft.com/en-us/mem/configmgr/apps/deploy-use/deploy-applications)
