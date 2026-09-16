"""
In-memory stand-in for the Windows worker, for UPDATE tests.

Mirrors the worker semantics UPDATE relies on:
- ``move`` fails when the destination exists (File.Move) or the source is missing
- ``copy`` overwrites (File.Copy(..., true)) and creates parent folders
- ``delete`` fails for a missing path ("Path not found")
- ``validate_dir`` lists top-level files; a file whose extension is not in
  ``allowed_extensions`` is a non-image, and content starting with ``b"FAKE"``
  is reported as not an image when content verification is on
- ``copy`` of a folder skips files matching ``ignore_masks``, as PUSH asks
- ``fetch_file`` downloads through the real signed-link check and verifies
  size and SHA-256, like the worker is specified to
- an unknown command fails with "Unknown command: ..."

Failures are raised as ``WorkerCommunicationError``, as ``send_command`` does.
"""

import hashlib
from urllib.parse import parse_qs, urlparse

from api.schemas import WorkerCommandResponse
from api.services.worker_service import WorkerCommunicationError


class FakeWorkerService:
    def __init__(self, files: dict, settings=None, supports_fetch=True, fail_on=None):
        # virtual path ("B:/CAT/a.jpg") -> bytes
        self.files = dict(files)
        self.settings = settings
        self.supports_fetch = supports_fetch
        self.fail_on = fail_on  # callable(command, source, dest) -> bool
        self.commands = []

    # -- helpers ---------------------------------------------------------
    def _is_dir(self, path):
        prefix = path.rstrip("/") + "/"
        return any(p.startswith(prefix) for p in self.files)

    def _exists(self, path):
        return path in self.files or self._is_dir(path)

    def _fail(self, message):
        raise WorkerCommunicationError(f"Worker TEST command failed: {message}")

    def _ok(self, **payload):
        return WorkerCommandResponse(
            status="success", message="ok", error_details={"error_details": payload} if payload else None
        )

    # -- WorkerService API used by OperationService -----------------------
    async def move_file(self, worker, src, dst, db):
        return await self._run("move", src, dst, None)

    async def copy_file(self, worker, src, dst, db):
        return await self._run("copy", src, dst, None)

    async def delete_file(self, worker, path, db, recursive=False):
        return await self._run("delete", path, None, None)

    async def send_command(self, worker, command, db, operation_id=None):
        return await self._run(command.command, command.source_path, command.dest_path, command.params or {})

    async def _run(self, name, source, dest, params):
        self.commands.append((name, source, dest, params))
        if self.fail_on and self.fail_on(name, source, dest):
            self._fail(f"injected failure for {name} {source} -> {dest}")

        if name == "list":
            path = params["path"]
            if not self._is_dir(path):
                self._fail(f"Directory not found: {path}")
            return self._ok(path=path)

        if name == "validate_dir":
            if not self._is_dir(source):
                self._fail(f"Directory not found: {source}")
            prefix = source.rstrip("/") + "/"
            names = sorted(p[len(prefix):] for p in self.files if p.startswith(prefix) and "/" not in p[len(prefix):])
            allowed = params.get("allowed_extensions") or []
            non_image = [n for n in names if n.rsplit(".", 1)[-1].lower() not in allowed]
            invalid = []
            if params.get("verify_content"):
                invalid = [
                    {"name": n, "extension": n.rsplit(".", 1)[-1], "detected": "unknown", "reason": "not_an_image"}
                    for n in names if n not in non_image and self.files[prefix + n].startswith(b"FAKE")
                ]
            return self._ok(path=source, files=names, total_files=len(names),
                            image_count=len(names) - len(non_image) - len(invalid),
                            non_image_files=non_image, invalid_files=invalid)

        if name == "move":
            if not self._exists(source):
                self._fail(f"Source not found: {source}")
            if self._exists(dest):
                self._fail(f"Cannot create a file when that file already exists: {dest}")
            moved = {p: c for p, c in self.files.items() if p == source or p.startswith(source.rstrip("/") + "/")}
            for p, c in moved.items():
                del self.files[p]
                self.files[dest + p[len(source):]] = c
            return self._ok()

        if name == "copy":
            if source in self.files:
                self.files[dest] = self.files[source]
            elif self._is_dir(source):
                from api.services.content_validation_service import matches_ignore_mask
                masks = (params or {}).get("ignore_masks") or []
                for p, c in list(self.files.items()):
                    if p.startswith(source.rstrip("/") + "/") and not matches_ignore_mask(p.rsplit("/", 1)[-1], masks):
                        self.files[dest + p[len(source):]] = c
            else:
                self._fail(f"Source not found: {source}")
            return self._ok()

        if name == "delete":
            if not self._exists(source):
                self._fail(f"Path not found: {source}")
            for p in [p for p in self.files if p == source or p.startswith(source.rstrip("/") + "/")]:
                del self.files[p]
            return self._ok()

        if name == "fetch_file" and self.supports_fetch:
            from api.services.upload_service import upload_path, verify_download_token

            url = urlparse(params["url"])
            parts = url.path.split("/")  # /api/workers/<host>/uploads/<id>
            host, upload_id = parts[3], parts[5]
            query = parse_qs(url.query)
            if not verify_download_token(self.settings, upload_id, host, int(query["expires"][0]), query["token"][0]):
                self._fail("download refused: 403")
            data = upload_path(self.settings, upload_id).read_bytes()
            if len(data) != params["size_bytes"] or hashlib.sha256(data).hexdigest() != params["sha256"]:
                self._fail("downloaded file failed size/SHA-256 verification")
            if self._exists(dest):
                self._fail(f"Destination exists: {dest}")
            self.files[dest] = data
            return self._ok()

        self._fail(f"Unknown command: {name}")
