# Windows Client Build Instructions

## Overview

This guide will help you build all three Windows components:
1. **Launcher** (C# .NET 4.8 Console Application)
2. **ShellExtension** (C++ ATL COM DLL)
3. **Installer** (WiX Toolset MSI)

## Prerequisites

### Already Installed
- ✅ Visual Studio 2022 with C++ build tools (v143)
- ✅ .NET Framework 4.8 SDK
- ✅ Windows SDK

### Need to Install
- ❌ WiX Toolset 3.11 or later (for Installer project)

## Step 1: Restore NuGet Packages (Launcher)

The Launcher project requires three NuGet packages:
- `Newtonsoft.Json` (v13.0.3) - JSON serialization
- `CredentialManagement` (v1.0.2) - Windows Credential Manager
- `System.IdentityModel.Tokens.Jwt` (v6.10.0) - JWT token parsing

**Option A: Using Visual Studio**
1. Open `clients\windows\RFM-Windows.sln` in Visual Studio
2. Right-click on the solution in Solution Explorer
3. Select **"Restore NuGet Packages"**
4. Wait for packages to download

**Option B: Using Command Line**
1. Open Command Prompt or PowerShell
2. Navigate to the Launcher directory:
   ```cmd
   cd C:\Users\olek\Documents\GitHub\rfm\clients\windows\Launcher
   ```
3. Restore packages using NuGet:
   ```cmd
   nuget restore RFMLauncher.csproj
   ```

   If `nuget.exe` is not in your PATH, download it from https://www.nuget.org/downloads and use:
   ```cmd
   path\to\nuget.exe restore RFMLauncher.csproj
   ```

**Option C: Using MSBuild**
1. Open Developer Command Prompt for VS 2022
2. Navigate to the solution directory:
   ```cmd
   cd C:\Users\olek\Documents\GitHub\rfm\clients\windows
   ```
3. Run:
   ```cmd
   msbuild RFM-Windows.sln /t:Restore
   ```

After restoring packages, verify that the `packages` folder exists at:
`C:\Users\olek\Documents\GitHub\rfm\clients\windows\packages\`

It should contain:
- `Newtonsoft.Json.13.0.3\`
- `CredentialManagement.1.0.2\`
- `System.IdentityModel.Tokens.Jwt.6.10.0\`

## Step 2: Build Launcher and ShellExtension

Now that platform toolset is updated to v143 and packages will be restored, you can build:

**Option A: Using Visual Studio**
1. Open `clients\windows\RFM-Windows.sln`
2. Select **Build → Build Solution** (or press F7)
3. Verify output in:
   - Launcher: `clients\windows\Launcher\bin\Debug\RFMLauncher.exe`
   - ShellExtension: `clients\windows\ShellExtension\x64\Debug\RFMShellExt.dll`

**Option B: Using Command Line**
1. Open Developer Command Prompt for VS 2022
2. Build Launcher:
   ```cmd
   cd C:\Users\olek\Documents\GitHub\rfm\clients\windows\Launcher
   msbuild RFMLauncher.csproj /p:Configuration=Release
   ```
3. Build ShellExtension:
   ```cmd
   cd C:\Users\olek\Documents\GitHub\rfm\clients\windows\ShellExtension
   msbuild RFMShellExt.vcxproj /p:Configuration=Release /p:Platform=x64
   ```

## Step 3: Install WiX Toolset (Required for Installer)

The Installer project uses WiX Toolset to create MSI installers.

**Installation Steps:**

1. **Download WiX Toolset**
   - Visit: https://wixtoolset.org/releases/
   - Download WiX Toolset 3.11.2 (latest stable)
   - Direct link: https://github.com/wixtoolset/wix3/releases/download/wix3112rtm/wix311.exe

2. **Install WiX Toolset**
   - Run the downloaded `wix311.exe` installer
   - Follow the installation wizard
   - Accept the license agreement
   - Complete the installation

3. **Install Visual Studio Extension (Optional but Recommended)**
   - In Visual Studio 2022, go to **Extensions → Manage Extensions**
   - Search for "WiX Toolset Visual Studio Extension"
   - Install the extension (requires VS restart)
   - This provides IntelliSense and project templates for WiX

**Alternative: WiX Toolset v4 (Preview)**
- If you prefer the newer version, you can install WiX v4
- Visit: https://wixtoolset.org/docs/intro/
- Note: The project files may need updates for v4 syntax

## Step 4: Build Installer (After WiX Installation)

**Option A: Using Visual Studio**
1. Restart Visual Studio after installing WiX
2. Open `clients\windows\RFM-Windows.sln`
3. Build the Installer project
4. Output: `clients\windows\Installer\bin\Release\RFM-Setup.msi`

**Option B: Using Command Line**
1. Open Developer Command Prompt for VS 2022
2. Ensure Launcher and ShellExtension are built first (they're referenced by the installer)
3. Build installer:
   ```cmd
   cd C:\Users\olek\Documents\GitHub\rfm\clients\windows\Installer
   msbuild RFMSetup.wixproj /p:Configuration=Release
   ```

## Troubleshooting

### NuGet Package Restore Fails

**Error**: "Unable to find version '13.0.3' of package 'Newtonsoft.Json'"
- **Solution**: Check your internet connection and NuGet sources
- **Check sources**:
  ```cmd
  nuget sources list
  ```
- **Add nuget.org source if missing**:
  ```cmd
  nuget sources Add -Name "nuget.org" -Source "https://api.nuget.org/v3/index.json"
  ```

### ShellExtension Build Errors

**Error**: "Cannot open include file: 'atlbase.h'"
- **Solution**: Install "Desktop development with C++" workload in Visual Studio
- Go to Visual Studio Installer → Modify → Select "Desktop development with C++"

**Error**: "MSB8036: The Windows SDK version X.Y was not found"
- **Solution**: Install the required Windows SDK version
- Or update `<WindowsTargetPlatformVersion>` in RFMShellExt.vcxproj to match your installed SDK

### Installer Build Errors

**Error**: "The WiX Toolset v3.11 (or newer) build tools must be installed"
- **Solution**: Complete Step 3 above to install WiX Toolset
- Restart Visual Studio after installation

**Error**: "Light.exe : error LGHT0103: The system cannot find the file"
- **Solution**: Ensure Launcher and ShellExtension are built before building Installer
- The installer references output files from these projects

### Missing Dependencies After Build

**Error**: Launcher.exe fails to run with "Could not load file or assembly 'Newtonsoft.Json'"
- **Solution**: Ensure NuGet packages were restored properly
- DLL files should be copied to the output directory automatically
- Check `bin\Debug` or `bin\Release` for:
  - Newtonsoft.Json.dll
  - CredentialManagement.dll
  - System.IdentityModel.Tokens.Jwt.dll

## Verification

After successful build, verify the following files exist:

**Launcher Output** (`Launcher\bin\Release\`):
- ✅ RFMLauncher.exe
- ✅ config.json
- ✅ Newtonsoft.Json.dll
- ✅ CredentialManagement.dll
- ✅ System.IdentityModel.Tokens.Jwt.dll
- ✅ locales\en-US.json
- ✅ locales\pl-PL.json

**ShellExtension Output** (`ShellExtension\x64\Release\`):
- ✅ RFMShellExt.dll

**Installer Output** (`Installer\bin\Release\`):
- ✅ RFM-Setup.msi

## Next Steps

1. **Test Launcher**: Run `RFMLauncher.exe --prepare "C:\Test"` to verify it works
2. **Register Shell Extension**: Use `regsvr32` to register the DLL for testing
3. **Install MSI**: Run `RFM-Setup.msi` on a test machine
4. **End-to-End Test**: Right-click folder → verify context menu appears

For detailed testing instructions, see:
- `clients\windows\Launcher\README.md`
- `clients\windows\ShellExtension\README.md`
- `clients\windows\Installer\README.md`

## Quick Build (All Components)

Once all prerequisites are installed:

```cmd
cd C:\Users\olek\Documents\GitHub\rfm\clients\windows
msbuild RFM-Windows.sln /t:Restore /p:Configuration=Release
msbuild RFM-Windows.sln /p:Configuration=Release
```

This will:
1. Restore all NuGet packages
2. Build Launcher (C#)
3. Build ShellExtension (C++)
4. Build Installer (WiX)

Output MSI will be at: `Installer\bin\Release\RFM-Setup.msi`
