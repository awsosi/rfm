# RFM Launcher

Windows context menu launcher application for RFM (Remote File Manager).

## Overview

The RFM Launcher is a .NET Framework 4.8 console application that:

1. Authenticates users via OAuth device flow
2. Stores credentials securely in Windows Credential Manager
3. Opens the RFM web application with deep link parameters

## Building

### Prerequisites

- Visual Studio 2019 or later
- .NET Framework 4.8 SDK
- NuGet Package Manager

### Build Steps

1. Open `RFMLauncher.csproj` in Visual Studio
2. Restore NuGet packages:
   - Newtonsoft.Json 13.0.3
   - CredentialManagement 1.0.2
3. Build the solution (Release configuration recommended)

### Command Line Build

```bash
# Restore NuGet packages
nuget restore RFMLauncher.csproj

# Build
msbuild RFMLauncher.csproj /p:Configuration=Release
```

## Configuration

Edit `config.json` to customize:

- `api_base_url`: RFM server URL
- `allowed_paths`: List of allowed Windows paths
- `language`: Locale code (en-US, pl-PL)
- `credential_target_prefix`: Windows Credential Manager target name

Example:

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

## Usage

```bash
# Prepare (select folder in RFM web UI)
RFMLauncher.exe --prepare "\\server\share\folder"

# Push (auto-trigger push operation)
RFMLauncher.exe --push "\\server\share\folder"
```

## Dependencies

- **Newtonsoft.Json**: JSON serialization
- **CredentialManagement**: Windows Credential Manager integration
- **System.IdentityModel.Tokens.Jwt**: JWT token parsing (built-in .NET)

## Security

- Access tokens stored in Windows Credential Manager (encrypted by OS)
- OAuth device flow (RFC 8628) for secure authentication
- No passwords stored locally

## Localization

Supported languages:
- `en-US`: English
- `pl-PL`: Polish

Add new languages by creating `locales/{language}.json` files.

## Troubleshooting

### Authentication Issues

- Check network connectivity to RFM server
- Verify `api_base_url` in config.json
- Clear stored credentials: Control Panel → Credential Manager → Windows Credentials → Remove "RFM_ContextMenu"

### Path Not Allowed

- Verify path is listed in `allowed_paths` in config.json
- Check path separators (use backslashes for UNC paths)

### Token Expired

- Launcher automatically refreshes tokens
- If refresh fails, re-authentication is triggered
