# RFM Windows Client - Development Guide

Guide for developers building and extending the RFM Windows Client.

## Architecture Overview

The RFM Windows Client consists of three main components:

### 1. Launcher (C# .NET 4.8)
- **Purpose**: Authentication and deep linking
- **Technology**: .NET Framework 4.8 Console Application
- **Dependencies**: Newtonsoft.Json, CredentialManagement
- **Location**: `clients/windows/Launcher/`

### 2. Shell Extension (C++ ATL COM)
- **Purpose**: Windows Explorer context menu integration
- **Technology**: C++ ATL COM DLL
- **Dependencies**: Windows SDK, ATL
- **Location**: `clients/windows/ShellExtension/`

### 3. Installer (WiX)
- **Purpose**: MSI installer for deployment
- **Technology**: WiX Toolset 3.11
- **Dependencies**: WiX, custom actions
- **Location**: `clients/windows/Installer/`

## Development Environment Setup

### Prerequisites

1. **Visual Studio 2019 or later**
   - Workloads:
     - .NET desktop development
     - Desktop development with C++
   - Individual components:
     - Windows SDK (latest)
     - ATL for latest build tools

2. **WiX Toolset 3.11+**
   - Download: https://wixtoolset.org/
   - Install Visual Studio extension

3. **NuGet Package Manager**
   - Included with Visual Studio

### Repository Structure

```
clients/windows/
├── Launcher/               # C# authentication launcher
│   ├── RFMLauncher.csproj
│   ├── Program.cs
│   ├── AuthenticationManager.cs
│   ├── ConfigurationManager.cs
│   ├── DeepLinkBuilder.cs
│   ├── LocalizationManager.cs
│   ├── config.json
│   └── locales/
│       ├── en-US.json
│       └── pl-PL.json
├── ShellExtension/        # C++ shell extension (to be implemented)
│   ├── RFMShellExt.vcxproj
│   ├── RFMContextMenu.h
│   ├── RFMContextMenu.cpp
│   └── Utils.cpp
├── Installer/             # WiX installer (to be implemented)
│   ├── RFMSetup.wixproj
│   └── Product.wxs
├── README.md              # User documentation
├── DEPLOYMENT.md          # Admin deployment guide
└── DEVELOPMENT.md         # This file
```

## Building the Launcher

### Command Line Build

```batch
cd clients/windows/Launcher

# Restore NuGet packages
nuget restore RFMLauncher.csproj

# Build Debug
msbuild RFMLauncher.csproj /p:Configuration=Debug

# Build Release
msbuild RFMLauncher.csproj /p:Configuration=Release
```

### Visual Studio Build

1. Open `RFMLauncher.csproj` in Visual Studio
2. Right-click solution → Restore NuGet Packages
3. Build → Build Solution (or F7)

### Output

- Debug: `bin/Debug/RFMLauncher.exe`
- Release: `bin/Release/RFMLauncher.exe`

## Testing the Launcher

### Manual Testing

```batch
cd clients/windows/Launcher/bin/Debug

# Test prepare action
RFMLauncher.exe --prepare "C:\TestFolder"

# Test push action
RFMLauncher.exe --push "C:\TestFolder"
```

### Test Configuration

Create a test `config.json`:

```json
{
  "api_base_url": "http://localhost:3000",
  "allowed_paths": [
    "C:\\TestFolder",
    "C:\\Users\\YourName\\Documents"
  ],
  "language": "en-US",
  "credential_target_prefix": "RFM_ContextMenu_Test"
}
```

### Authentication Flow Testing

1. Run launcher with test path
2. Browser should open to device authorization page
3. Note user code displayed in console
4. Log in to RFM web app
5. Navigate to device authorization URL
6. Enter user code
7. Click "Approve"
8. Launcher should complete and open deep link

### Debugging

Enable verbose logging in `AuthenticationManager.cs`:

```csharp
Console.WriteLine($"Debug: Token expired check: {IsTokenExpired(token)}");
Console.WriteLine($"Debug: Polling device code: {deviceCode}");
```

## Building the Shell Extension

### Project Setup (C++)

1. Create new ATL Project in Visual Studio
2. Project type: DLL
3. Add ATL Simple Object: `RFMContextMenu`
4. Implement interfaces:
   - `IShellExtInit`
   - `IContextMenu`

### Implementation Overview

**RFMContextMenu.h**:
```cpp
class ATL_NO_VTABLE CRFMContextMenu :
    public CComObjectRootEx<CComSingleThreadModel>,
    public CComCoClass<CRFMContextMenu, &CLSID_RFMContextMenu>,
    public IShellExtInit,
    public IContextMenu
{
private:
    std::wstring m_selectedPath;
    bool m_isSingleSelection;

public:
    // IShellExtInit
    STDMETHODIMP Initialize(LPCITEMIDLIST, LPDATAOBJECT, HKEY);

    // IContextMenu
    STDMETHODIMP QueryContextMenu(HMENU, UINT, UINT, UINT, UINT);
    STDMETHODIMP InvokeCommand(LPCMINVOKECOMMANDINFO);
    STDMETHODIMP GetCommandString(UINT_PTR, UINT, UINT*, LPSTR, UINT);
};
```

**Key Functions**:

1. `Initialize`: Get selected path from data object
2. `QueryContextMenu`: Add menu items if path allowed
3. `InvokeCommand`: Launch RFMLauncher.exe with parameters

### COM Registration

**Developer Registration** (manual):
```batch
regsvr32 RFMShellExt.dll
```

**Debugging**:
```batch
# Unregister
regsvr32 /u RFMShellExt.dll

# Re-register
regsvr32 RFMShellExt.dll

# Restart Explorer
taskkill /f /im explorer.exe
start explorer.exe
```

**Registry Entries**:
```
HKEY_CLASSES_ROOT\CLSID\{YOUR-GUID}\InprocServer32
HKEY_CLASSES_ROOT\Directory\shellex\ContextMenuHandlers\RFM
```

## Building the Installer

### WiX Project Setup

1. Create new WiX Setup Project
2. Add references to Launcher and ShellExtension projects
3. Configure Product.wxs

### Product.wxs Structure

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="RFM Windows Integration" Version="1.0.0.0" ...>

    <!-- Components -->
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFilesFolder">
        <Directory Id="INSTALLFOLDER" Name="RFM">

          <!-- Launcher files -->
          <Component Id="LauncherComponent">
            <File Source="..\Launcher\bin\Release\RFMLauncher.exe" />
            <File Source="..\Launcher\bin\Release\config.json" />
            <!-- ... NuGet DLLs, locales ... -->
          </Component>

          <!-- Shell extension -->
          <Component Id="ShellExtComponent">
            <File Source="..\ShellExtension\Release\RFMShellExt.dll" />
            <!-- COM registration -->
            <Class Id="{CLSID}" Context="InprocServer32" ... />
            <RegistryValue Root="HKCR"
                           Key="Directory\shellex\ContextMenuHandlers\RFM"
                           Value="{CLSID}" />
          </Component>

        </Directory>
      </Directory>
    </Directory>

    <!-- Features -->
    <Feature Id="ProductFeature" Title="RFM Integration" Level="1">
      <ComponentRef Id="LauncherComponent" />
      <ComponentRef Id="ShellExtComponent" />
    </Feature>

  </Product>
</Wix>
```

### Building MSI

```batch
cd clients/windows/Installer

# Build with WiX
candle Product.wxs
light -out RFM-Setup.msi Product.wixobj
```

### Testing Installer

```batch
# Install
msiexec /i RFM-Setup.msi /l*v install.log

# Uninstall
msiexec /x RFM-Setup.msi /l*v uninstall.log

# Review logs for errors
notepad install.log
```

## Adding Localization

### Launcher Localization

1. Create new locale file: `locales/{language}.json`

```json
{
  "auth": {
    "browserOpening": "Translated text...",
    "waitingApproval": "Translated text with {code} placeholder",
    ...
  },
  "errors": {
    ...
  }
}
```

2. Update `config.json` to use new locale:
```json
{
  "language": "es-ES"
}
```

3. Test with new locale

### Shell Extension Localization

Add string resources to `.rc` file:

```rc
STRINGTABLE
BEGIN
    IDS_MENU_PREPARE_EN  "Prepare selected to be sent with RFM"
    IDS_MENU_PREPARE_PL  "Przygotuj wybrane do wysłania za pomocą RFM"
END
```

Load based on system locale in `LoadLocalizedString()`.

## Code Style and Best Practices

### C# (Launcher)

- Follow Microsoft C# Coding Conventions
- Use PascalCase for public members
- Use camelCase for private fields (prefix with `_`)
- Add XML documentation comments for public APIs
- Handle exceptions gracefully (log, don't crash)

Example:
```csharp
/// <summary>
/// Builds deep link URL with action, path, and token
/// </summary>
/// <param name="apiBaseUrl">Base URL of RFM server</param>
/// <param name="action">Action: "prepare" or "push"</param>
/// <returns>Complete deep link URL</returns>
public static string Build(string apiBaseUrl, string action, ...)
{
    // Implementation
}
```

### C++ (Shell Extension)

- Follow Windows ATL/COM conventions
- Use HRESULT return codes
- Always check HRESULT with `SUCCEEDED()` or `FAILED()`
- Clean up COM objects (smart pointers recommended)
- Use RAII for resource management

Example:
```cpp
STDMETHODIMP CRFMContextMenu::Initialize(
    LPCITEMIDLIST pidlFolder,
    LPDATAOBJECT pDataObj,
    HKEY hKeyProgID)
{
    if (!pDataObj)
        return E_INVALIDARG;

    // Get selected path
    HRESULT hr = GetPathFromDataObject(pDataObj, m_selectedPath);
    if (FAILED(hr))
        return hr;

    // Validate path
    if (!IsPathAllowed(m_selectedPath))
        return E_FAIL;

    return S_OK;
}
```

## Debugging Tips

### Launcher Debugging

**Attach to Process**:
1. Right-click context menu in Explorer
2. Visual Studio → Debug → Attach to Process
3. Find `RFMLauncher.exe`
4. Set breakpoints in code

**Console Output**:
- Run from command line to see console output
- Add `Console.ReadKey()` before exit to pause

**Credential Manager**:
```batch
# List credentials
cmdkey /list

# Delete test credential
cmdkey /delete:RFM_ContextMenu_Test
```

### Shell Extension Debugging

**Debug in Visual Studio**:
1. Set debugger to `explorer.exe`
2. Set breakpoints in shell extension code
3. Start debugging (F5)
4. New Explorer window opens
5. Right-click folder to trigger breakpoints

**Debugging Output**:
```cpp
OutputDebugString(L"RFM: Initialize called\n");
OutputDebugString((L"RFM: Selected path: " + m_selectedPath).c_str());
```

View in DebugView: https://docs.microsoft.com/en-us/sysinternals/downloads/debugview

**Common Issues**:
- Explorer caches shell extensions (restart Explorer)
- 32-bit vs 64-bit mismatch (build both if needed)
- COM registration issues (run `regsvr32` as admin)

### Installer Debugging

**Enable Verbose Logging**:
```batch
msiexec /i RFM-Setup.msi /l*v install.log
```

**Check Event Viewer**:
- Windows Logs → Application
- Filter by source: MsiInstaller

**Test on Clean VM**:
- Use Windows Sandbox or Hyper-V
- Test fresh install, upgrade, uninstall

## Contributing

### Pull Request Process

1. Fork the repository
2. Create feature branch: `feature/your-feature-name`
3. Make changes
4. Test thoroughly:
   - Launcher authentication flow
   - Shell extension context menu
   - Installer deployment
5. Commit with clear messages
6. Push to your fork
7. Create Pull Request

### Testing Checklist

Before submitting PR:

- [ ] Launcher builds without errors
- [ ] Shell extension builds and registers
- [ ] Installer creates valid MSI
- [ ] Authentication flow works (device flow)
- [ ] Context menu appears in allowed paths
- [ ] Context menu doesn't appear in non-allowed paths
- [ ] "Prepare" action opens browser with correct URL
- [ ] "Push" action auto-triggers operation
- [ ] Localization works for both languages
- [ ] Uninstaller removes all components
- [ ] No errors in Event Viewer

## Performance Optimization

### Launcher

- Cache configuration (don't read file on every run)
- Use async HTTP calls (already implemented)
- Token validation before network calls

### Shell Extension

- Fast path validation (early exit for non-allowed paths)
- Minimize resource loading
- Cache launcher path (read registry once)

## Security Considerations

### Credential Storage

- Use Windows Credential Manager (encrypted by OS)
- Never log or display tokens in plain text
- Clear sensitive data from memory when done

### Input Validation

- Validate all paths from user/Explorer
- Escape shell arguments when launching processes
- Validate JSON configuration

### Network Security

- Enforce HTTPS for API calls
- Validate SSL certificates
- Use secure WebSocket (wss://)

## Troubleshooting Build Issues

### NuGet Restore Fails

```batch
# Clear NuGet cache
nuget locals all -clear

# Restore manually
nuget restore RFMLauncher.csproj -PackagesDirectory ..\packages
```

### ATL/COM Build Errors

- Ensure Windows SDK installed
- Check project targets correct platform (x64 vs x86)
- Verify ATL libraries included

### WiX Build Errors

- Check WiX Toolset version (3.11+)
- Ensure referenced files exist
- Validate XML syntax in Product.wxs

## Release Process

1. **Version Bump**
   - Update version in AssemblyInfo.cs (Launcher)
   - Update version in Product.wxs (Installer)
   - Update CHANGELOG.md

2. **Build Release**
   ```batch
   # Launcher
   msbuild Launcher/RFMLauncher.csproj /p:Configuration=Release

   # Shell Extension
   msbuild ShellExtension/RFMShellExt.vcxproj /p:Configuration=Release

   # Installer
   cd Installer
   candle Product.wxs
   light -out RFM-Setup.msi Product.wixobj
   ```

3. **Test on Clean System**
   - Install MSI
   - Test all functionality
   - Uninstall

4. **Sign Binaries** (production)
   ```batch
   signtool sign /f cert.pfx /p password /t http://timestamp.server RFMLauncher.exe
   signtool sign /f cert.pfx /p password /t http://timestamp.server RFMShellExt.dll
   signtool sign /f cert.pfx /p password /t http://timestamp.server RFM-Setup.msi
   ```

5. **Create Release**
   - Tag repository: `v1.0.0`
   - Upload MSI to release
   - Update documentation

## Resources

- [Windows Shell Extensions](https://docs.microsoft.com/en-us/windows/win32/shell/shell-exts)
- [ATL COM Tutorial](https://docs.microsoft.com/en-us/cpp/atl/introduction-to-atl)
- [WiX Toolset Documentation](https://wixtoolset.org/documentation/)
- [OAuth 2.0 Device Flow (RFC 8628)](https://tools.ietf.org/html/rfc8628)
- [.NET Framework 4.8](https://docs.microsoft.com/en-us/dotnet/framework/)
