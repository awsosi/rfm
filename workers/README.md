# FileManagerWorker Installer

This directory contains the source code for the Windows Worker Service installer.

## Quick Start

1. Run `build.bat` to compile the installer
2. The output will be in `bin\FileManagerWorker.exe`
3. See [README-INSTALLER.md](../README-INSTALLER.md) for complete usage documentation

## Files

- **Installer.cs** - Main installer logic, command parsing, and validation
- **ServiceInstaller.cs** - Windows Service registration using Win32 API
- **build.bat** - Build script that compiles the installer using csc.exe
- **.gitignore** - Git ignore rules for build outputs

## Building

```cmd
build.bat
```

This will:
1. Locate the C# compiler (csc.exe)
2. Verify source files
3. Compile into a single .exe
4. Output to `bin\FileManagerWorker.exe`

## Requirements

- Windows operating system
- .NET Framework 4.x or Visual Studio 2019/2022
- C# compiler (csc.exe)

## Notes

- The installer must be run as Administrator on target machines
- No external dependencies are required for the compiled .exe
- The build script automatically finds csc.exe from common locations
- If you have an icon file (`icon.ico`), place it in this directory and the build script will embed it

## Complete Documentation

See [README-INSTALLER.md](../README-INSTALLER.md) for:
- Installation instructions
- Usage examples
- Troubleshooting guide
- Security considerations
- Deployment strategies
