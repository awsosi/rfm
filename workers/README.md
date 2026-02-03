# FileManager Worker Service

Windows Worker Service for remote file operations with mTLS authentication.

## Overview

The FileManager Worker Service is a self-installing Windows service that connects to a Central API and executes file operations (copy, move, delete, mkdir, list, search) with automatic rollback support.

## Features

- **Self-Installing**: Single executable with command-line installation
- **mTLS Security**: Mutual TLS authentication using Windows Certificate Store
- **File Operations**: Copy, move, delete, mkdir, list, search
- **Automatic Rollback**: Failed operations are automatically rolled back
- **Event Viewer Logging**: No disk logs, all logging to Windows Event Viewer
- **Long-Polling**: Continuous connection to Central API for commands
- **Progress Reporting**: Real-time progress updates for large operations

## Requirements

- Windows Server 2012 R2 or later
- .NET Framework 4.8 or later
- Administrator privileges for installation
- Network access to Central API
- File system permissions for target directories

## Build Instructions

### Using Visual Studio

1. Open `FileManagerWorker.sln` in Visual Studio 2019 or later
2. Restore NuGet packages (automatic)
3. Build in Release mode: `Build > Build Solution`
4. Output will be in `bin\Release\FileManagerWorker.exe`

### Using Command Line (MSBuild)

```cmd
# Restore NuGet packages
nuget restore FileManagerWorker.sln

# Build in Release mode
msbuild FileManagerWorker.sln /p:Configuration=Release /p:Platform="Any CPU"
```

### Using .NET CLI (if using SDK-style project)

```cmd
dotnet restore
dotnet build -c Release
```

## Installation

### Basic Installation

Run the executable with administrator privileges:

```cmd
FileManagerWorker.exe /install /url https://api.example.com /user "DOMAIN\ServiceUser" /pass "P@ssw0rd"
```

### Parameters

- `/install` - Install the service
- `/url <api-url>` - Central API URL (required)
- `/user <username>` - Windows service account username (required)
- `/pass <password>` - Service account password (required)
- `/uninstall` - Uninstall the service
- `/debug` - Run in console mode for testing
- `/help` or `/?` - Show usage information

### Installation Steps

1. **Prepare Service Account**
   - Create a Windows user account with necessary file system permissions
   - Grant read/write access to target directories (Path A and Path B)

2. **Configure App.config** (optional)
   - Edit `App.config` before installation to set default paths
   - Set `PathAPrefix`, `PathBPrefix` and `PathCPrefix` for virtual drive mappings

3. **Install Service**
   ```cmd
   FileManagerWorker.exe /install /url https://central-api.example.com /user "DOMAIN\FileManagerSvc" /pass "SecurePassword123"
   ```

4. **Verify Installation**
   - Check Windows Services: `services.msc`
   - Look for "FileManager Worker" service
   - Service should start automatically

5. **Check Event Viewer**
   - Open Event Viewer: `eventvwr.msc`
   - Navigate to: Windows Logs > Application
   - Filter by Source: "FileManagerWorker"
   - Verify successful startup and registration

## Configuration

Configuration is stored in `App.config`:

```xml
<appSettings>
  <!-- Central API URL -->
  <add key="ApiUrl" value="https://localhost:5001" />

  <!-- Path Prefixes for A: and B: virtual drives -->
  <add key="PathAPrefix" value="C:\PathA" />
  <add key="PathBPrefix" value="C:\PathB" />
  <add key="PathCPrefix" value="C:\PathC" />

  <!-- Polling interval in seconds -->
  <add key="PollingIntervalSeconds" value="5" />

  <!-- Enable mTLS -->
  <add key="UseMtls" value="true" />
</appSettings>
```

### Path Mapping

Commands use virtual drive prefixes:
- `A:\path\to\file` → `C:\PathA\path\to\file` (source directory)
- `B:\path\to\file` → `C:\PathB\path\to\file` (destination directory)
- `C:\path\to\file` → `C:\PathC\path\to\file` (archive directory)

**Example for PUSH operation:**
- Source: `A:/photos/2024` → resolves to PathAPrefix + `/photos/2024`
- Destination: `B:/photos/2024` → resolves to PathBPrefix + `/photos/2024`
- Archive: `C:/photos/2024` → resolves to PathCPrefix + `/photos/2024`

## Usage

### Debug Mode

Test the service without installation:

```cmd
FileManagerWorker.exe /debug
```

This runs the service in console mode with verbose logging.

### Uninstallation

```cmd
FileManagerWorker.exe /uninstall
```

### Starting/Stopping Service

```cmd
# Start service
net start FileManagerWorker

# Stop service
net stop FileManagerWorker

# Restart service
net stop FileManagerWorker && net start FileManagerWorker
```

## Certificate Management

### Automatic Certificate Generation

On first run, the service automatically:
1. Generates a self-signed X.509 certificate
2. Stores the private key in Windows Certificate Store (LocalMachine\My)
3. Sends the public key to Central API for approval

### Manual Certificate Management

View certificates:
```powershell
Get-ChildItem Cert:\LocalMachine\My | Where-Object {$_.Subject -eq "CN=FileManagerWorker"}
```

Delete certificate:
```powershell
$cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object {$_.Subject -eq "CN=FileManagerWorker"}
Remove-Item $cert.PSPath
```

## Supported Commands

### Copy
```json
{
  "command": "copy",
  "parameters": {
    "source": "A:\\source\\file.txt",
    "destination": "B:\\dest\\file.txt"
  }
}
```

### Move
```json
{
  "command": "move",
  "parameters": {
    "source": "A:\\source\\file.txt",
    "destination": "B:\\dest\\file.txt"
  }
}
```

### Delete
```json
{
  "command": "delete",
  "parameters": {
    "path": "A:\\file.txt"
  }
}
```

### Create Directory
```json
{
  "command": "mkdir",
  "parameters": {
    "path": "A:\\new\\directory"
  }
}
```

### List Files
```json
{
  "command": "list",
  "parameters": {
    "path": "A:\\directory",
    "recursive": "true"
  }
}
```

### Search Files
```json
{
  "command": "search",
  "parameters": {
    "path": "A:\\",
    "pattern": "*.txt",
    "recursive": "true"
  }
}
```

### Get File Info
```json
{
  "command": "info",
  "parameters": {
    "path": "A:\\file.txt"
  }
}
```

## Rollback Behavior

All destructive operations (copy, move, delete, mkdir) create automatic backups:

- **Copy**: Backs up destination before overwriting
- **Move**: Backs up both source and destination
- **Delete**: Backs up file/directory before deletion
- **Mkdir**: Records if directory didn't exist

If an operation fails:
1. Automatic rollback is attempted
2. Response includes `rollback_status: "success"` or `"failed"`
3. Backups are cleaned up after 24 hours

## Troubleshooting

### Service Won't Start

1. Check Event Viewer for errors
2. Verify service account has file system permissions
3. Verify API URL is accessible
4. Run in debug mode: `FileManagerWorker.exe /debug`

### Certificate Errors

1. Verify Windows Certificate Store access
2. Check LocalMachine\My store for certificate
3. Verify service account has permission to access certificates

### Connection Issues

1. Verify network connectivity to API
2. Check firewall rules
3. Verify mTLS certificate is approved by Central API
4. Check Event Viewer for detailed error messages

### Permission Denied

1. Verify service account has read/write access to target directories
2. Check NTFS permissions on PathA and PathB
3. For network shares, verify service account has network access

## Security Considerations

- Service account should have minimal necessary permissions
- Certificate private key is protected by Windows Certificate Store
- All communication uses HTTPS with mTLS
- Samba credentials stored securely in Windows Credential Manager (encrypted by OS)
- **Impersonation**: All file operations use samba credentials via Windows impersonation
- No credentials or sensitive data stored on disk (except in Windows Certificate Store)
- All operations are scoped to configured path prefixes (PathA, PathB, PathC)

### Credential Usage Model

The worker uses a two-tier security model:

1. **Service Account** (Network Service):
   - Used to run the worker service process
   - Handles API communication and service lifecycle
   - Minimal permissions required

2. **Samba Account** (configured during `/config`):
   - Used for all file system operations via Windows impersonation
   - Requires read/write permissions on network shares
   - Credentials stored in Windows Credential Manager
   - Example: `VITKAC\fotosamba` with full control on shares

## Architecture

```
FileManagerWorker.exe
├── Program.cs              # Entry point, command-line handling
├── WorkerService.cs        # Main service loop (TopShelf)
├── CertificateManager.cs   # mTLS certificate management
├── ApiClient.cs            # HTTPS communication with Central API
├── FileOperations.cs       # File operation implementations
├── CommandHandler.cs       # Command parsing and execution
├── RollbackManager.cs      # Automatic rollback logic
└── Models/
    ├── CommandRequest.cs   # Incoming command model
    ├── CommandResponse.cs  # Outgoing response model
    └── ServiceConfiguration.cs
```

## NuGet Dependencies

- **Topshelf 4.3.0**: Service installation and lifecycle management
- **Topshelf.NLog 4.3.0**: NLog integration for TopShelf
- **NLog 5.2.8**: Logging to Event Viewer
- **Newtonsoft.Json 13.0.3**: JSON serialization
- **System.Net.Http 4.3.4**: HTTP client for API communication

## License

See main project LICENSE file.
