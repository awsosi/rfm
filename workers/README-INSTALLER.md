# FileManagerWorker - Install, Update and Reconfigure

`FileManagerWorker.exe` installs and configures itself as a Windows service (Topshelf). There is no separate installer: the same executable runs the configuration wizard, installs or removes the service, and is the service.

> The `workers/Installer/` project (`/install /url /user /pass`, `C:\Program Files\FileManager\Worker`, `worker.config`) is an old standalone installer. It is not part of `FileManagerWorker.sln` and is not used.

## At a glance

| Item | Value |
|------|-------|
| Service name | `FileManagerWorker` (display name "FileManager Worker") |
| Service account | Network Service |
| Start type | Automatic; restarts 1 minute after a failure |
| Executable | Wherever `FileManagerWorker.exe` was when you ran `install` |
| Configuration | `C:\ProgramData\FileManagerWorker\config.dat` (DPAPI, LocalMachine scope) |
| mTLS certificate | `LocalMachine\My`, subject `CN=FileManagerWorker`, self-signed, valid 10 years |
| Worker identity on the server | The machine's hostname |
| Logs | Event Viewer → Windows Logs → Application, source `FileManagerWorker` |

## Building

Open a Developer Command Prompt for Visual Studio:

```cmd
cd workers
nuget restore FileManagerWorker.sln
msbuild FileManagerWorker.sln /p:Configuration=Release
```

Deploy **all** files from `workers\FileManagerWorker\bin\Release\`:

```
FileManagerWorker.exe
FileManagerWorker.exe.config
CredentialManagement.dll
Newtonsoft.Json.dll
NLog.dll
Topshelf.dll
Topshelf.NLog.dll
```

The `.pdb` is optional.

## Commands

Run every command from an **elevated** command prompt (Run as administrator).

| Command | What it does |
|---------|--------------|
| `FileManagerWorker.exe /config` | Configuration wizard: creates the mTLS certificate if missing, then saves the API URL, Samba credentials and path prefixes to `config.dat` |
| `FileManagerWorker.exe install` | Registers the Windows service (requires `/config` first). Does not start it |
| `FileManagerWorker.exe install --interactive` | Same, but Topshelf asks for the service account instead of using Network Service |
| `FileManagerWorker.exe uninstall` | Removes the Windows service. Leaves `config.dat` and the certificate |
| `FileManagerWorker.exe /debug` | Runs the worker in the console (see [Debug mode](#debug-mode)) |
| `FileManagerWorker.exe /?` | Usage |

Use `install` and `uninstall` without a slash. Topshelf reads the raw command line, so only the plain verbs are reliable.

## Fresh installation

1. Copy the Release files to a permanent folder, for example `C:\Program Files\FileManagerWorker\`. The service runs the exe from that folder, so don't install from a download or temp folder.
2. Configure:
   ```cmd
   cd "C:\Program Files\FileManagerWorker"
   FileManagerWorker.exe /config
   ```
   The wizard asks for:

   | Prompt | Notes |
   |--------|-------|
   | Central API URL | For example `https://rfm.example.com`. Not validated, so check it carefully |
   | Samba username | `DOMAIN\User`. Leave empty to access files as Network Service |
   | Samba password | Hidden input. Only asked if you entered a username |
   | Path A prefix | Source files. Default `C:\PathA` |
   | Path B prefix | Target of PUSH. Default `C:\PathB` |
   | Path C prefix | Archive after PUSH. Default `C:\PathC` |

3. Install and start:
   ```cmd
   FileManagerWorker.exe install
   net start FileManagerWorker
   ```
4. In the WebUI admin panel, approve the new worker. It registers as **PENDING** under the machine's hostname and gets no commands until approved.

## Updating to a new build

The configuration and certificate don't change, so there's no need to reinstall or run `/config` again:

```cmd
net stop FileManagerWorker
:: copy the new Release files over the existing ones in the install folder
net start FileManagerWorker
```

If `FileManagerWorker.exe.config` has local edits (for example `PollingIntervalSeconds`), merge them into the new file instead of overwriting.

## Reconfiguring (API URL, Samba credentials, path prefixes)

```cmd
net stop FileManagerWorker
FileManagerWorker.exe /config
net start FileManagerWorker
```

`/config` asks for **every** value again and overwrites `config.dat`, so re-enter the values you aren't changing. It reuses the existing certificate, so the server keeps the same worker record. On startup the worker registers again, and the server stores the new path prefixes.

## Reinstalling or moving the install folder

```cmd
net stop FileManagerWorker
FileManagerWorker.exe uninstall
:: copy the Release files to the new folder and run the rest from there
FileManagerWorker.exe install
net start FileManagerWorker
```

Run `/config` before `install` only if you also want to change settings. `uninstall` always prints "uninstalled successfully", so check with `sc query FileManagerWorker` (it should report that the service does not exist).

## Removing completely

```cmd
net stop FileManagerWorker
FileManagerWorker.exe uninstall
del "C:\ProgramData\FileManagerWorker\config.dat"
```

Remove the certificate (PowerShell, elevated):

```powershell
Get-ChildItem Cert:\LocalMachine\My | Where-Object Subject -eq 'CN=FileManagerWorker' | Remove-Item
```

Then delete the install folder, and delete or suspend the worker in the admin panel.

## Configuration details

### Where settings come from

| Setting | Source |
|---------|--------|
| API URL, Samba user and password, Path A/B/C prefixes | `config.dat` (written by `/config`) |
| `PollingIntervalSeconds`, `UseMtls` | `FileManagerWorker.exe.config` → `appSettings` |

If `config.dat` is missing or can't be decrypted, the service falls back to `ApiUrl` and the path prefixes in `FileManagerWorker.exe.config` and logs a warning. Don't rely on this fallback. Without an API URL from either source the service refuses to start.

`config.dat` is encrypted with DPAPI for the machine it was created on. It can't be copied to another machine; run `/config` there instead.

### Samba credentials and file access

- **Username set:** every file operation runs impersonated as that user (network logon). The user needs read/write rights on the Path A, B and C locations.
- **Username empty:** file operations run as Network Service. Local folders need NTFS rights for `NETWORK SERVICE`. UNC shares need rights for the machine account (`DOMAIN\HOSTNAME$`).

The service's API connection always uses the mTLS certificate, never the Samba credentials.

### Server identity and approval

The worker registers with `POST /api/workers/register` using `Environment.MachineName` as the hostname.

- **Known hostname:** the server updates the existing record (public key, path prefixes, version) and keeps its status.
- **New hostname:** creates a new **PENDING** worker. This includes a renamed machine, which needs approval again.
- **Certificate deleted and recreated by `/config`:** the new public key replaces the old one on the same record.

Worker statuses:

| Status | Meaning | Returns to ACTIVE |
|--------|---------|-------------------|
| PENDING | Awaiting approval | When an administrator approves it |
| ACTIVE | Receiving commands | - |
| OFFLINE | Missed heartbeats (e.g. reboot, outage) | Automatically when the worker registers, polls or sends a heartbeat |
| SUSPENDED | Suspended by an administrator | Only when an administrator reactivates it |

## Debug mode

`FileManagerWorker.exe /debug` runs the worker in the console with full Debug-level output. Press any key to stop.

- It reads the same `config.dat` as the service.
- It looks for the certificate in **`CurrentUser\My`**, not `LocalMachine\My`. `/config` doesn't create a certificate there, so on a normally configured machine `/debug` stops with "no mTLS certificate in the CurrentUser certificate store".
- If a `CurrentUser` certificate does exist, `/debug` registers with it and replaces the public key the server holds for this hostname. Restarting the service registers the machine certificate again.
- Stop the service first (`net stop FileManagerWorker`) so two instances don't poll for the same worker.

For troubleshooting a deployed worker, the Event Viewer log is usually the better place to look.

## Troubleshooting

Look in Event Viewer → Application, source `FileManagerWorker`. It records service start and stop, connectivity changes, and all warnings and errors. Routine Info messages only appear in `/debug`.

| Symptom | Cause / fix |
|---------|-------------|
| `/config`: "This wizard must be run as Administrator" | Run the prompt elevated. Creating the certificate in `LocalMachine\My` needs admin rights |
| `install`: "Configuration not found in secure storage" | Run `/config` first on this machine. A `config.dat` copied from another machine can't be decrypted |
| Service starts and immediately stops; log says "no mTLS certificate in the LocalMachine certificate store" | The certificate was deleted. Run `/config` again, then approve or check the worker in the admin panel |
| Log says "API URL is not configured" | Run `/config` |
| Worker never appears in the admin panel | Wrong API URL, or the API isn't reachable from this machine. Check the warnings in Event Viewer and run `/config` again if the URL is wrong |
| Worker is shown but gets no commands | Status is PENDING or SUSPENDED. Approve or reactivate it in the admin panel |
| Commands fail with "Impersonation failed for user ..." | Wrong Samba password, account disabled or locked, or the account has no network logon right. Run `/config` again with correct credentials |
| Commands fail with access denied (no Samba user) | Grant rights to `NETWORK SERVICE` (local folders) or the machine account (shares), or configure a Samba user |
| A new worker appeared after renaming the machine | The server identifies workers by hostname. Approve the new record and delete the old one |
