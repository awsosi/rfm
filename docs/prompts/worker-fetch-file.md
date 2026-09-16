# Worker change: `fetch_file` command for uploaded UPDATE files

You are working on the Windows worker (`workers/FileManagerWorker`, C# .NET 4.8) on the `dev-vf` branch. Read `CLAUDE.md` first; its rules apply (KISS, Windows shell compatibility, path traversal protection in `FileOperations.cs`).

The server side is done and deployed on dev (`api-dev.ff.vitkac.local`). **Pull `dev-vf` first**: the server code referenced below is in the repo. Your job is the worker side of one new command.

---

## Context

UPDATE can now **replace** a file in a pushed catalog or **add** a new one. The new content comes either from a file in Path A (the worker already handles that with the existing `copy` command) or from a file the user **uploaded through the WebUI**. Uploaded files are stored on the API host, which cannot reach the shares. So the worker has to download them, using a new command: `fetch_file`.

Server references (read them, don't change them):
- `backend/api/services/operation_service.py`, `_stage_update_content`: builds and sends the command.
- `backend/api/routes/worker.py`, `download_upload`: `GET /api/workers/{hostname}/uploads/{upload_id}?expires=…&token=…` serves the bytes. The link is HMAC-signed for this upload **and this worker's hostname**, and expires after 1 hour. It answers 403 for a bad or expired link or a non-ACTIVE worker, and 404 once the upload is gone.
- `backend/tests/update_fakes.py`: the in-memory fake worker the server tests run against. Its `fetch_file` branch is the behaviour the server expects from you.

How UPDATE uses the worker (all existing commands except `fetch_file`):
1. Stage new content into a working folder inside the catalog, `B:/<catalog>/.rfm-update-<operationId>/<NNN>_<name>`: **`copy`** a single Path A file there, or **`fetch_file`** an upload there.
2. **`validate_dir`** on that working folder (real-type check of the staged files).
3. **`move`** renames, then swaps: target → `…/previous_<NNN>_<name>`, then staged file → target.
4. **`delete`** for deletions, then `delete` (recursive) of the working folder.

On failure the server undoes everything by moving files back, so **nothing in the catalog changes until every file has been staged and checked**. A worker without `fetch_file` answers `Unknown command: fetch_file`. The server catches that before touching the catalog and tells the user to update the worker, so keep that message format for unknown commands.

## The command

Polled like any other command (`CommandRequest`):

```json
{
  "command_id": 123,
  "command": "fetch_file",
  "source_path": null,
  "dest_path": "B:/CATALOG NAME/.rfm-update-57/000_photo.jpg",
  "parameters": {
    "url": "/api/workers/DELA-5420-AW/uploads/3f2c…e1?expires=1789570000&token=9ab4…",
    "sha256": "<64 lowercase hex chars>",
    "size_bytes": 5242880
  }
}
```

`size_bytes` arrives as a JSON number (Newtonsoft may give you `long`). Use `Convert.ToInt64`.

## Required behaviour

1. **New case** `"fetch_file"` in `CommandHandler.ExecuteAsync`, with a `HandleFetchFileAsync` in the style of the other handlers.
2. **Validate the request** before doing any I/O:
   - `dest_path` present; `url`, `sha256`, `size_bytes` present.
   - `url` must be **relative and start with `/api/`**. Build the full URL as the configured API base URL + `url`. Never follow an absolute URL from a command, so a command can't point the worker at another host.
   - `sha256` is 64 hex characters; `size_bytes >= 0`.
3. **Resolve and check the destination** through `FileOperations` (`ResolvePath` + `ValidatePath`), like every other command. Add a `FileOperations` method for this, e.g. `ReceiveFileAsync(string destination, string tempFile)`. Don't resolve paths in `CommandHandler`.
4. **Download to a local temp file first, outside impersonation** (e.g. under the service's temp directory, as `RollbackManager` does). Share credentials are for the shares, not for talking to the API.
   - Use the same client certificate and TLS settings as `ApiClient`, but **not** its 30-second `HttpClient`: a large image over a slow link takes longer. Use a dedicated client or request with a long timeout (30 minutes is fine) and `HttpCompletionOption.ResponseHeadersRead`, and stream to disk. Never buffer the whole file in memory. A method on `ApiClient` (e.g. `DownloadToFileAsync(string relativeUrl, string localPath, CancellationToken)`) keeps HTTP in one place.
   - Hash while writing (SHA-256), count bytes.
   - A non-2xx answer fails the command with the status code and at most ~300 characters of the body (403 = expired/invalid link, 404 = upload no longer exists).
5. **Verify before touching the share**: if byte count ≠ `size_bytes` or the hash ≠ `sha256`, fail with a message containing `size/SHA-256 verification`. The destination must not be created.
6. **Place the file under impersonation** (`ExecuteWithImpersonation`):
   - Create the destination's parent folder (the working folder does not exist yet for the first staged file).
   - **Refuse to overwrite**: if the destination already exists, fail.
   - Copy the temp file to `<destination>.partial`, then `File.Move` it to the destination, so a half-written file never has the final name.
7. **Always clean up** the temp file and any `.partial` in `finally`.
8. **No `RollbackManager` backups** for this command: the destination must not exist, so there is nothing to back up.
9. **Response**: `CommandResponse.Success(cmdId, "File fetched", fileCount: 1, totalSize: size)`; failures via `CommandResponse.Failed(cmdId, message, errorDetails)` like the other handlers.
10. **Logging**: Info with destination, size, SHA-256 and duration. **Never log the query string** of the URL: the token is a credential. Log the path part only.

## Please also confirm (no change expected)

- `copy` of a **single file** from `A:/…` to a `B:/…/.rfm-update-N/…` path creates the missing parent folder (`CopyAsync` calls `Directory.CreateDirectory`). The server relies on this for Path A sources.
- `move` of a file onto an **existing** destination **fails** (`File.Move`). The server relies on this so "add" never overwrites a file that appeared meanwhile.
- `delete` of a missing path fails with a message containing `not found` (`FileNotFoundException("Path not found: …")`). The server treats that as "the working folder was never created".

## Observation for you to evaluate (out of scope unless it bites)

`HandleCopyAsync`, `HandleMoveAsync` and `HandleDeleteAsync` call `RollbackManager.CreateBackup(s)` with the **virtual** path (e.g. `C:/CATALOG/a.jpg`), not the resolved one. `File.Exists`/`Directory.Exists` then look at the real local drive letter on the worker host. For `A:`/`B:` that usually finds nothing, but `C:` is the system drive, and the PATH_C archive mirror uses `C:/<catalog>` paths. Check whether backups should use the resolved path, and report what you find.

## Verification

1. Build (`msbuild FileManagerWorker.sln /p:Configuration=Release`), deploy to `DELA-5420-AW`, and restart the service.
2. In the dev WebUI: push a test catalog (or use an existing one), open **Update catalog**, set a file to **Replace → Upload…**, and use **Upload new files…** to add one. Apply.
   - Expected: operation COMPLETED; the catalog has the new bytes; no `.rfm-update-*` folder left; worker log shows `fetch_file` with size and SHA-256 and no token.
3. Replace a file with an upload whose content is not an image (e.g. a `.txt` renamed to `.jpg`, with content verification on in the Admin Panel). Expected: HTTP 422 "not really an image", catalog unchanged, working folder removed.
4. Link check from the worker host: `curl.exe -k "https://api-dev.ff.vitkac.local/api/workers/DELA-5420-AW/uploads/00000000000000000000000000000000?expires=9999999999&token=bad"` → 403.
5. Report the worker log excerpts for 2 and 3, and your findings on the three "please confirm" items and the rollback observation.
