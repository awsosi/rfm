# FileManagerWorker - Windows Service Installer

Self-installing executable for deploying the FileManager Worker Service on Windows machines.

## Overview

The FileManagerWorker installer is a **single, standalone .exe file** with **no external dependencies**. It provides a simple command-line interface for installing, uninstalling, and testing the FileManager Worker Service.

## Features

- **Single File Deployment** - Everything embedded in one executable
- **No Dependencies** - No .NET Framework installation required (compiles to native)
- **Administrator Check** - Automatically verifies admin privileges
- **Credential Validation** - Validates service account exists and credentials are correct
- **URL Validation** - Ensures API URL uses HTTPS protocol
- **Registry Integration** - Creates proper registry entries for service tracking
- **Debug Mode** - Test the worker without installing as a service

## Building the Installer

### Prerequisites

- Windows machine with .NET Framework 4.x installed
- C# compiler (csc.exe) - included with .NET Framework
- OR Visual Studio 2019/2022

### Build Steps

1. Navigate to the `workers/Installer` directory
2. Run the build script:
   ```cmd
   build.bat
   ```

3. The installer will be created at: `bin\FileManagerWorker.exe`

### Build Output

```
workers/
└── Installer/
    ├── bin/
    │   └── FileManagerWorker.exe    ← Single standalone installer
    ├── Installer.cs
    ├── ServiceInstaller.cs
    └── build.bat
```

## Usage

### Installation

**IMPORTANT: Must be run as Administrator**

```cmd
FileManagerWorker.exe /install /url <api-url> /user <service-user> /pass <service-pass>
```

**Example:**
```cmd
FileManagerWorker.exe /install /url https://api.company.com:8000 /user svc_filemanager /pass MySecurePassword123
```

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `/url`    | Yes      | Central API URL (must be HTTPS) |
| `/user`   | Yes      | Windows user account for service (must exist on machine) |
| `/pass`   | Yes      | Password for service account |

**Installation Process:**

1. ✓ Validates API URL (must be HTTPS)
2. ✓ Validates user account exists on local machine
3. ✓ Validates credentials
4. ✓ Creates installation directory: `C:\Program Files\FileManager\Worker`
5. ✓ Copies executable to installation directory
6. ✓ Saves configuration file
7. ✓ Registers Windows Service
8. ✓ Creates registry entries

**After Installation:**

Start the service manually:
```cmd
net start FileManagerWorker
```

Or use Services Manager (services.msc) to start/configure the service.

### Uninstallation

```cmd
FileManagerWorker.exe /uninstall
```

**Uninstallation Process:**

1. ✓ Stops the service (if running)
2. ✓ Unregisters Windows Service
3. ✓ Removes registry entries
4. ✓ Cleans up installation directory

### Debug Mode

Run the worker in console mode for testing (no service installation required):

```cmd
FileManagerWorker.exe /debug
```

**Debug Mode:**
- Runs worker in console window
- Uses existing configuration from previous installation
- Press any key to stop
- Useful for troubleshooting

### Help

Display usage information:

```cmd
FileManagerWorker.exe /?
FileManagerWorker.exe /help
```

## Service Configuration

### Service Details

| Property | Value |
|----------|-------|
| **Service Name** | FileManagerWorker |
| **Display Name** | File Manager Worker Service |
| **Description** | Manages file operations for centralized file manager |
| **Start Type** | Manual (can be changed to Automatic) |
| **Install Path** | C:\Program Files\FileManager\Worker |
| **Binary Path** | C:\Program Files\FileManager\Worker\FileManagerWorker.exe |

### Registry Entries

The installer creates registry entries at:
```
HKEY_LOCAL_MACHINE\SOFTWARE\FileManager\Worker
```

**Values:**
- `InstallPath` - Installation directory path
- `ServiceName` - Windows Service name
- `ApiUrl` - Configured API URL
- `Version` - Installer version
- `InstalledDate` - Installation timestamp

### Configuration File

Located at: `C:\Program Files\FileManager\Worker\worker.config`

**Example:**
```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <appSettings>
    <add key="ApiUrl" value="https://api.example.com" />
    <add key="ServiceUser" value="svc_filemanager" />
    <add key="ServicePassword" value="[encrypted]" />
    <add key="PathAPrefix" value="C:\PathA" />
    <add key="PathBPrefix" value="C:\PathB" />
    <add key="PollingIntervalSeconds" value="5" />
    <add key="UseMtls" value="true" />
  </appSettings>
</configuration>
```

## Validation Rules

### URL Validation

- Must be a valid URL
- Must use HTTPS protocol (HTTP is rejected)
- Format: `https://host:port` or `https://domain.com`

**Valid URLs:**
```
https://api.example.com
https://api.example.com:8000
https://192.168.1.100:5001
```

**Invalid URLs:**
```
http://api.example.com          ← HTTP not allowed
api.example.com                 ← Missing protocol
ftp://api.example.com           ← Wrong protocol
```

### User Account Validation

- User must exist on the local machine
- Can use formats:
  - `username` (local account)
  - `DOMAIN\username` (domain account)
  - `username@domain.com` (UPN format)
- Credentials are validated against Windows
- Service will run under the specified account

**Valid User Formats:**
```
svc_filemanager
.\svc_filemanager
MYCOMPANY\svc_filemanager
svc_filemanager@mycompany.com
```

### Password Validation

- Must be provided
- Validated against Windows user account
- Stored encrypted in configuration file
- Used for service logon credentials

## Troubleshooting

### "Must be run as Administrator"

**Problem:** Installer requires elevated privileges

**Solution:**
- Right-click the executable
- Select "Run as administrator"
- Or run from an elevated command prompt

### "User account does not exist"

**Problem:** Specified user account not found on machine

**Solution:**
- Verify the username is correct
- Create the user account first:
  ```cmd
  net user svc_filemanager Password123 /add
  ```
- For domain accounts, ensure machine is domain-joined

### "Invalid password"

**Problem:** Credentials validation failed

**Solution:**
- Verify password is correct
- Check account is not locked
- Ensure account has "Log on as a service" rights

### "URL must be a valid HTTPS URL"

**Problem:** API URL validation failed

**Solution:**
- Ensure URL starts with `https://`
- Check URL format is correct
- Use IP address if hostname resolution fails

### "Service already exists"

**Problem:** Service is already installed

**Solution:**
- Uninstall first: `FileManagerWorker.exe /uninstall`
- Then reinstall with new parameters

### "Configuration not found" (Debug Mode)

**Problem:** Trying to run debug mode without installation

**Solution:**
- Install the service first with `/install`
- Or manually create configuration file at installation path

## Security Considerations

### Administrator Rights

The installer requires administrator privileges to:
- Create directories in `C:\Program Files`
- Register Windows Services
- Create registry entries
- Configure service credentials

### Password Encryption

Passwords are stored using Base64 encoding in the configuration file. For production:

- Consider using Windows Credential Manager
- Implement proper encryption (DPAPI)
- Use Managed Service Accounts (MSA) or Group Managed Service Accounts (gMSA)
- Restrict file permissions on configuration file

### Service Account Permissions

The service account should have:
- Read/write access to PathA and PathB directories
- Network access to reach the Central API
- "Log on as a service" right (automatically granted during installation)

**Grant permissions:**
```cmd
icacls "C:\PathA" /grant svc_filemanager:(OI)(CI)F
icacls "C:\PathB" /grant svc_filemanager:(OI)(CI)F
```

### HTTPS Requirement

The installer enforces HTTPS for API communication to ensure:
- Encrypted data transmission
- Protection against man-in-the-middle attacks
- Secure credential exchange

## Deployment

### Single Machine Deployment

1. Copy `FileManagerWorker.exe` to target machine
2. Run as administrator:
   ```cmd
   FileManagerWorker.exe /install /url https://api.example.com /user svc_filemanager /pass Password123
   ```
3. Start the service:
   ```cmd
   net start FileManagerWorker
   ```

### Mass Deployment

For deploying to multiple machines, use:

**Group Policy:**
- Create a startup script that runs the installer
- Deploy via GPO to target machines

**PowerShell Remote:**
```powershell
$machines = @("SERVER01", "SERVER02", "SERVER03")
$creds = Get-Credential

foreach ($machine in $machines) {
    Invoke-Command -ComputerName $machine -Credential $creds -ScriptBlock {
        & "\\share\FileManagerWorker.exe" /install /url https://api.example.com /user svc_filemanager /pass Password123
    }
}
```

**Configuration Management:**
- SCCM
- Ansible
- Chef
- Puppet

### Silent Installation

The installer runs silently from command line (no GUI prompts). Perfect for automation.

## Architecture

### Installer Components

```
FileManagerWorker.exe
├── Installer.cs              ← Main entry point, command parsing, validation
├── ServiceInstaller.cs       ← Windows Service registration via Win32 API
└── [Embedded Resources]      ← Configuration templates, etc.
```

### Installation Directory Structure

```
C:\Program Files\FileManager\Worker\
├── FileManagerWorker.exe     ← Service executable
└── worker.config             ← Service configuration
```

### Win32 API Usage

The installer uses Win32 API directly (not .NET ServiceInstaller) for:
- Service creation: `CreateService()`
- Service deletion: `DeleteService()`
- Service control: `ControlService()`
- No InstallUtil.exe dependency
- Smaller, faster, more reliable

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-01 | Initial release |

## Support

For issues or questions:
- Check the troubleshooting section above
- Review service logs in Event Viewer (Application log)
- Check worker logs in installation directory
- Contact system administrator

## License

Internal use only - Centralized File Manager System
