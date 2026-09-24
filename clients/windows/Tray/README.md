# RFM Tray

Sends catalog folders to RFM automatically once they have finished copying into
a watched folder (e.g. `\\hv2012r2\DaneFoto\DO KATALOGU\Ewa`), so a batch of
folders no longer has to be clicked through the WebUI one by one.

Nothing about validation, logging or accountability changes: every folder goes
through the normal `POST /api/operations/push` under the user's own RFM sign-in
(PolkaSQL login, device flow, the same credential the context menu uses). RFM
validates the name against PolkaSQL, checks the contents, logs the push against
that user and notifies PIM exactly as for a WebUI push. The audit log's user
agent reads `RFMTray/<version>`, so automatic pushes can be told apart.

## How it behaves

| Situation | What the user sees |
|---|---|
| Folder pushed | Nothing (it leaves the watched folder; the Activity window lists it as sent) |
| Name not a product / contents rejected | Notification. Clicking it opens the reasons (same text as the WebUI) with RFM's name suggestions; **Rename and send** renames the folder and sends it |
| Catalog already published | Notification: changing a published catalog is an UPDATE, done in RFM. RFM Tray never re-pushes it (`refuse_existing`, HTTP 409) |
| RFM / PolkaSQL / worker unavailable | Retried after 1, 2, 5, 10, then every 15 minutes; notification after the 3rd failure |
| Not signed in / session expired | Notification; **Sign in…** opens the browser approval |
| Many problems at once | One notification ("12 folders need your attention") opening the Activity window |

A refused folder stays where it is and is not retried until it changes (new,
removed or edited files, or a rename) or the user clicks **Try again**.

## When is a folder "finished"?

The part to get right: a folder must not be pushed half-copied. A folder directly
inside a watched folder is sent only when **all** of these hold:

1. it contains at least one file (a freshly created "New folder" is ignored);
2. no partial/temporary file is present (`*.tmp`, `*.part`, `*.partial`,
   `*.crdownload`, `*.download`, `~$*`, `.~lock*`);
3. nothing in it has changed (file count, folder count, sizes, newest write time)
   for the quiet period, 60 s by default (Settings, minimum 15 s);
4. every file can be opened while denying writers: a copy still in progress
   holds its file open, which is a sharing violation even over SMB.

Folders are scanned every 10 s. File system notifications only trigger an
earlier scan: over SMB they can be lost or overflow, so the rescan is what the
decision rests on. Folders are sent one at a time, oldest change first, so
30 folders dropped at once form a queue.

**Pause automatic sending** (tray menu or Settings) holds everything, for a
user who wants to stage a batch and release it later. **Send now** skips the
quiet period for one folder.

## Accountability

- It runs only in the signed-in Windows user's session, as that user, with that
  user's RFM sign-in. Without a sign-in nothing is sent.
- Watched folders are chosen per user (Settings, stored in
  `%APPDATA%\RFM\tray.json`) and must lie inside `allowed_paths`, like the
  context menu. `watch_folders` in `config.json` (installer `WATCH_FOLDERS`)
  only presets them for a user who has not chosen any.
- A user watching someone else's folder pushes under their own name; the audit
  log shows who. Keep one folder per person (`DO KATALOGU\Ewa`, `\Lena`, ...).
- If two PCs watch the same folder, RFM's path lock lets one push win; the other
  sees the folder gone and drops it silently.

## Start at sign-in

The installer runs `RFMTray.exe --install-task` (elevated), registering the
scheduled task `RFM\RFM Tray`: logon trigger for any user (30 s delay), the
Users group (`S-1-5-32-545`), least privilege, in the user's own session.
Uninstall runs `--uninstall-task`. Started by the task (`--autostart`), RFM Tray
exits at once for a user with no watched folder, so users of the context menu
alone get no extra icon; the Start menu shortcut **RFM Tray** always opens it.

## Files

| File | Purpose |
|---|---|
| `CatalogWatcher.cs` | Scanning, the "finished" rules, queue, retries |
| `RfmClient.cs` | `path/resolve` + `operations/push`, maps responses to outcomes |
| `TrayContext.cs` | Tray icon, menu, notifications, sign-in |
| `ActivityForm.cs` / `IssueForm.cs` / `SettingsForm.cs` | Windows |
| `ValidationText.cs` | Port of the WebUI's `formatValidationFailure()` |
| `ScheduledTask.cs` | Sign-in task XML (`schtasks /Create /XML`) |

Shared with RFMLauncher (linked, not copied): `AuthenticationManager.cs`,
`ConfigurationManager.cs`, `LocalizationManager.cs`, `PathRules.cs`, and
`Launcher/locales/*.json` (`tray.*` and `validation.*` keys).

## Build

```bat
msbuild RFM-Windows.sln /p:Configuration=Release /p:Platform=x64
```
