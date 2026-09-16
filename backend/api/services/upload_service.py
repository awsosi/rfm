"""
UPDATE upload storage and garbage collection.

Files a user uploads through the WebUI to replace or add catalog entries are
written to ``update_upload_dir/<id>`` on the API host. When the UPDATE runs,
the worker is sent a ``fetch_file`` command carrying a short-lived signed URL
and downloads the bytes itself; the API host never needs access to the shares.

Lifecycle of an upload:

1. ``store_upload``: streamed to ``<id>.part`` while hashing, size-capped,
   renamed to ``<id>`` and recorded in ``update_uploads`` with
   ``expires_at = now + update_upload_ttl_hours``.
2. ``attach_uploads``: an UPDATE claims it (``operation_id``). Claiming is a
   conditional UPDATE, so one upload can never feed two operations.
3. ``release_operation_uploads``: once that UPDATE finishes (success or
   failure) the file is deleted. The row stays as the audit record.
4. ``collect_garbage``: safety net run periodically by every API process.
   Deletes unused uploads past ``expires_at``, uploads whose operation already
   finished, and stray files on disk with no live row (e.g. an interrupted
   upload's ``.part``).

Deleting a file twice is harmless and every row transition is conditional, so
the four uvicorn processes may all run the collector concurrently.
"""

import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from loguru import logger
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import Settings
from models import Config, Operation, OperationStatus, UpdateUpload, User

_CHUNK = 1024 * 1024
# Stray files younger than this may belong to an upload still being written
_STRAY_GRACE_SECONDS = 3600
# Lifetime of a worker download link; the worker fetches right after receiving
# the command, the margin covers a busy queue.
DOWNLOAD_LINK_TTL_SECONDS = 3600

_TERMINAL = (OperationStatus.COMPLETED, OperationStatus.FAILED, OperationStatus.ROLLED_BACK)


class UploadError(ValueError):
    """Upload rejected; ``status_code`` is the HTTP status to answer with."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


async def get_upload_limits(db: AsyncSession, settings: Settings) -> tuple[int, int]:
    """Return ``(max_bytes, ttl_hours)`` from the config table."""
    result = await db.execute(
        select(Config.key, Config.value).where(
            Config.key.in_(("update_upload_max_mb", "update_upload_ttl_hours"))
        )
    )
    values = {row.key: row.value for row in result}

    def _int(key: str, default: int) -> int:
        try:
            value = int(values.get(key, default))
            return value if value > 0 else default
        except (TypeError, ValueError):
            return default

    max_mb = _int("update_upload_max_mb", settings.update_upload_max_mb)
    ttl_hours = _int("update_upload_ttl_hours", settings.update_upload_ttl_hours)
    return max_mb * 1024 * 1024, ttl_hours


def upload_path(settings: Settings, upload_id: str) -> Path:
    return Path(settings.update_upload_dir) / upload_id


def clean_filename(name: Optional[str]) -> str:
    """Keep only the final path component of a browser-supplied file name."""
    base = (name or "").replace("\\", "/").split("/")[-1].strip()
    return base or "upload"


async def store_upload(
    user: User,
    filename: Optional[str],
    chunks,
    db: AsyncSession,
    settings: Settings,
) -> UpdateUpload:
    """
    Stream ``chunks`` (an async iterator of bytes) to disk and record the upload.

    Raises ``UploadError`` (413) as soon as the configured size is exceeded;
    the partial file is removed.
    """
    max_bytes, ttl_hours = await get_upload_limits(db, settings)

    upload_dir = Path(settings.update_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    upload_id = uuid.uuid4().hex
    final_path = upload_dir / upload_id
    part_path = upload_dir / f"{upload_id}.part"

    digest = hashlib.sha256()
    size = 0
    try:
        with open(part_path, "wb") as fh:
            async for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise UploadError(
                        f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit",
                        status_code=413,
                    )
                digest.update(chunk)
                fh.write(chunk)
        if size == 0:
            raise UploadError("Uploaded file is empty")
        os.replace(part_path, final_path)
    except BaseException:
        part_path.unlink(missing_ok=True)
        raise

    now = datetime.now(timezone.utc)
    upload = UpdateUpload(
        id=upload_id,
        user_id=user.id,
        original_filename=clean_filename(filename),
        size_bytes=size,
        sha256=digest.hexdigest(),
        expires_at=now + timedelta(hours=ttl_hours),
    )
    db.add(upload)
    try:
        await db.commit()
    except BaseException:
        final_path.unlink(missing_ok=True)
        raise
    await db.refresh(upload)

    logger.info(
        f"Stored UPDATE upload {upload_id} for user '{user.username}': "
        f"{upload.original_filename!r}, {size} bytes, sha256={upload.sha256}"
    )
    return upload


def _delete_file(settings: Settings, upload_id: str) -> None:
    upload_path(settings, upload_id).unlink(missing_ok=True)
    (Path(settings.update_upload_dir) / f"{upload_id}.part").unlink(missing_ok=True)


async def _delete_uploads(ids: Iterable[str], db: AsyncSession, settings: Settings) -> List[str]:
    """
    Mark rows deleted (conditionally) and remove their files.

    Returns the ids this call transitioned, so each deletion is logged once
    across processes. Files are removed for every id regardless: a process
    that lost the row race still leaves nothing behind.
    """
    ids = list(ids)
    if not ids:
        return []
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(UpdateUpload)
        .where(UpdateUpload.id.in_(ids), UpdateUpload.deleted_at.is_(None))
        .values(deleted_at=now)
        .returning(UpdateUpload.id)
    )
    transitioned = [row[0] for row in result]
    await db.commit()
    for upload_id in ids:
        _delete_file(settings, upload_id)
    return transitioned


async def delete_pending_upload(
    upload_id: str, user: User, db: AsyncSession, settings: Settings
) -> None:
    """Discard an upload the user no longer wants (not yet used by an UPDATE)."""
    upload = await db.get(UpdateUpload, upload_id)
    if not upload or upload.deleted_at is not None:
        raise UploadError("Upload not found", status_code=404)
    if upload.user_id != user.id:
        raise UploadError("Upload not found", status_code=404)
    if upload.operation_id is not None:
        raise UploadError("Upload is already used by an UPDATE operation", status_code=409)
    await _delete_uploads([upload_id], db, settings)
    logger.info(f"UPDATE upload {upload_id} discarded by user '{user.username}'")


async def load_uploads_for_update(
    upload_ids: List[str], user: User, db: AsyncSession
) -> dict:
    """
    Return ``{id: UpdateUpload}`` for uploads this user may use in an UPDATE.

    Raises ``UploadError`` for any id that is unknown, belongs to someone
    else, was already deleted, or is already claimed by another operation.
    """
    if not upload_ids:
        return {}
    result = await db.execute(select(UpdateUpload).where(UpdateUpload.id.in_(upload_ids)))
    found = {u.id: u for u in result.scalars()}
    for upload_id in upload_ids:
        upload = found.get(upload_id)
        if not upload or upload.user_id != user.id or upload.deleted_at is not None:
            raise UploadError(f"Upload {upload_id} not found or expired; upload the file again")
        if upload.operation_id is not None:
            raise UploadError(f"Upload {upload_id} was already used by operation {upload.operation_id}")
    return found


async def attach_uploads(
    upload_ids: List[str], operation_id: int, db: AsyncSession, settings: Settings
) -> None:
    """
    Claim uploads for an operation and push their expiry past its runtime.

    Conditional on ``operation_id IS NULL`` so a concurrent UPDATE cannot claim
    the same upload; losing that race raises ``UploadError``.
    """
    if not upload_ids:
        return
    _, ttl_hours = await get_upload_limits(db, settings)
    result = await db.execute(
        update(UpdateUpload)
        .where(
            UpdateUpload.id.in_(upload_ids),
            UpdateUpload.operation_id.is_(None),
            UpdateUpload.deleted_at.is_(None),
        )
        .values(
            operation_id=operation_id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
        )
        .returning(UpdateUpload.id)
    )
    claimed = {row[0] for row in result}
    await db.commit()
    missing = set(upload_ids) - claimed
    if missing:
        raise UploadError(
            f"Upload(s) {', '.join(sorted(missing))} were used or removed concurrently"
        )


async def release_operation_uploads(operation_id: int, db: AsyncSession, settings: Settings) -> None:
    """Delete the stored files of every upload an operation used."""
    result = await db.execute(
        select(UpdateUpload.id).where(
            UpdateUpload.operation_id == operation_id,
            UpdateUpload.deleted_at.is_(None),
        )
    )
    ids = [row[0] for row in result]
    deleted = await _delete_uploads(ids, db, settings)
    if deleted:
        logger.info(f"Released {len(deleted)} upload(s) of operation {operation_id}")


async def collect_garbage(db: AsyncSession, settings: Settings) -> int:
    """
    Delete uploads that can no longer be used. Returns the number of rows removed.

    - unused (no operation) and past ``expires_at``
    - claimed by an operation that has finished
    - claimed by an operation that is still not finished long after
      ``expires_at`` (a crashed API process left it IN_PROGRESS)
    - files on disk with no live row, older than an hour
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(UpdateUpload.id)
        .outerjoin(Operation, Operation.id == UpdateUpload.operation_id)
        .where(
            UpdateUpload.deleted_at.is_(None),
            or_(
                and_(UpdateUpload.operation_id.is_(None), UpdateUpload.expires_at < now),
                Operation.status.in_(_TERMINAL),
                and_(UpdateUpload.operation_id.is_not(None), UpdateUpload.expires_at < now),
            ),
        )
    )
    deleted = await _delete_uploads([row[0] for row in result], db, settings)

    upload_dir = Path(settings.update_upload_dir)
    stray = 0
    if upload_dir.is_dir():
        live = {
            row[0]
            for row in await db.execute(
                select(UpdateUpload.id).where(UpdateUpload.deleted_at.is_(None))
            )
        }
        cutoff = time.time() - _STRAY_GRACE_SECONDS
        for entry in upload_dir.iterdir():
            upload_id = entry.name.removesuffix(".part")
            if not entry.is_file():
                continue
            if upload_id in live and not entry.name.endswith(".part"):
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink(missing_ok=True)
                    stray += 1
            except FileNotFoundError:
                pass

    if deleted or stray:
        logger.info(f"Upload garbage collection: {len(deleted)} upload(s), {stray} stray file(s) removed")
    return len(deleted)


# ----------------------------------------------------------------------
# Worker download links
# ----------------------------------------------------------------------

def _signature(settings: Settings, upload_id: str, worker_hostname: str, expires: int) -> str:
    message = f"{upload_id}:{worker_hostname}:{expires}".encode()
    return hmac.new(settings.secret_key.encode(), message, hashlib.sha256).hexdigest()


def make_download_path(settings: Settings, upload_id: str, worker_hostname: str) -> str:
    """
    API-relative URL the worker fetches an upload from.

    Relative on purpose: the worker prepends the API base URL it is already
    configured with, so a command can never point it at another host.
    """
    expires = int(time.time()) + DOWNLOAD_LINK_TTL_SECONDS
    token = _signature(settings, upload_id, worker_hostname, expires)
    return f"/api/workers/{worker_hostname}/uploads/{upload_id}?expires={expires}&token={token}"


def verify_download_token(
    settings: Settings, upload_id: str, worker_hostname: str, expires: int, token: str
) -> bool:
    if expires < int(time.time()):
        return False
    expected = _signature(settings, upload_id, worker_hostname, expires)
    return hmac.compare_digest(expected, token or "")
