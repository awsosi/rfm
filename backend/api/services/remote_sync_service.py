"""
Remote synchronization verification (optional, off by default).

After a PUSH, downstream systems copy the catalog's images to the public
image host, which can take 15-30 minutes or more. When
``remote_sync_check_enabled`` is on, RFM polls one URL per image file, e.g.

    https://img.vitkac.com/uploads/product_thumb/{catalog_name}/up/{file}

and reports per PUSH: waiting for PIM, checking (n of m served), synced,
timed out, or cancelled (pulled first).

Lifecycle of a ``remote_sync_checks`` row (one per PUSH):

- PUSH completes -> WAITING until its PIM event is delivered (when PIM is
  signalled and ``remote_sync_check_wait_for_pim`` is on), else CHECKING.
- CHECKING starts ``remote_sync_check_initial_delay_seconds`` after that, then
  re-checks the files not yet served every ``remote_sync_check_interval_seconds``.
  All served -> SYNCED. Still missing after ``remote_sync_check_timeout_minutes``
  -> TIMEOUT. A user can start the clock again ("check again").
- UPDATE completes -> the row is re-targeted to the new file list: files the
  UPDATE added, replaced or renamed into place are checked again, and it
  waits for the UPDATE's PIM event.
- PULL completes -> an active row is CANCELLED.
- A user stops an active row (``stop_active_checks``) -> CANCELLED with
  ``cancelled_by``; unlike a PULL's, it can be started again ("check again").

What counts as served: HTTP 200 with an ``image/*`` content type and a
non-empty body. The image host sits behind Cloudflare, which was observed to
serve a cached ``200 image/jpeg`` with an empty body for a file the origin
answers 404 for, and to cache 404s for an hour. ``remote_sync_check_cache_bust``
(default on) adds a unique query parameter so each check reaches the origin.

Rows are claimed with ``FOR UPDATE SKIP LOCKED`` and a lease, so the API
processes never check the same catalog at the same time.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import httpx
from loguru import logger
from sqlalchemy import func, select, update

from api.services.pim_service import notify_integration_update
from database import DatabaseManager
from models import (
    Config,
    Operation,
    OperationType,
    PimEvent,
    PimEventStatus,
    RemoteSyncCheck,
    RemoteSyncStatus,
)

_CONFIG_KEYS = [
    'remote_sync_check_enabled',
    'remote_sync_check_url_template',
    'remote_sync_check_wait_for_pim',
    'remote_sync_check_initial_delay_seconds',
    'remote_sync_check_interval_seconds',
    'remote_sync_check_timeout_minutes',
    'remote_sync_check_request_timeout',
    'remote_sync_check_cache_bust',
    'push_validation_allowed_extensions',
]

DEFAULT_URL_TEMPLATE = "https://img.vitkac.com/uploads/product_thumb/{catalog_name}/up/{file}"
_DEFAULT_EXTENSIONS = "jpg,jpeg,png,gif,bmp,tif,tiff,webp"
_CONCURRENT_REQUESTS = 4
_LEASE_SECONDS = 300


async def get_sync_config(db) -> dict:
    result = await db.execute(select(Config.key, Config.value).where(Config.key.in_(_CONFIG_KEYS)))
    return {row.key: row.value for row in result}


def _truthy(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ('true', '1', 'yes')


def _int(config: dict, key: str, default: int) -> int:
    try:
        return max(0, int(config.get(key, default)))
    except (TypeError, ValueError):
        return default


def is_enabled(config: dict) -> bool:
    return _truthy(config.get('remote_sync_check_enabled'), default=False)


def image_files(files: list, config: dict) -> list:
    """Top-level files the image host is expected to serve: the image extensions."""
    allowed = {
        e.strip().lower().lstrip('.')
        for e in (config.get('push_validation_allowed_extensions') or _DEFAULT_EXTENSIONS).split(',')
        if e.strip()
    }
    return [
        str(name) for name in files
        if '/' not in str(name) and str(name).rpartition('.')[2].lower() in allowed
        and '.' in str(name)
    ]


def build_check_url(template: str, catalog_name: str, file_name: str, tg_id: str = "",
                    cache_bust: bool = True) -> str:
    url = (
        (template or DEFAULT_URL_TEMPLATE)
        .replace("{catalog_name}", quote(catalog_name, safe=""))
        .replace("{file}", quote(file_name, safe=""))
        .replace("{tg_id}", quote(tg_id or "", safe=""))
    )
    if cache_bust:
        url += ("&" if "?" in url else "?") + f"rfm_sync={time.time_ns()}"
    return url


def _touched_names(actions: list) -> set:
    """Top-level names whose content an UPDATE put in place."""
    names = set()
    for action in actions or []:
        kind = action.get("action")
        target = action.get("source") if kind == "replace" else action.get("dest")
        if kind in ("replace", "add", "rename", "move") and target and '/' not in target:
            names.add(target)
    return names


def _start_state(wait_event_id: Optional[int], config: dict, now: datetime) -> dict:
    """Status fields for a check that (re)starts now."""
    if wait_event_id and _truthy(config.get('remote_sync_check_wait_for_pim'), default=True):
        return {"status": RemoteSyncStatus.WAITING, "wait_event_id": wait_event_id,
                "started_at": None, "next_check_at": now}
    return {
        "status": RemoteSyncStatus.CHECKING, "wait_event_id": None, "started_at": now,
        "next_check_at": now + timedelta(seconds=_int(config, 'remote_sync_check_initial_delay_seconds', 60)),
    }


# ---------------------------------------------------------------------------
# Operation hooks
# ---------------------------------------------------------------------------

async def track_operation(operation: Operation, pim_event_id: Optional[int]) -> None:
    """
    Create, re-target or cancel the check for a completed catalog operation.

    Never raises: verification must not fail an operation that succeeded.
    """
    try:
        op_type = operation.type.value if hasattr(operation.type, "value") else str(operation.type)
        params = operation.params_json or {}
        now = datetime.now(timezone.utc)

        async with DatabaseManager.session() as db:
            config = await get_sync_config(db)

            if op_type == OperationType.PULL.value:
                push_id = operation.rollback_operation_id
                check = await _check_for(db, push_id, lock=True)
                if check and check.status in RemoteSyncStatus.ACTIVE:
                    check.status = RemoteSyncStatus.CANCELLED
                    check.completed_at = now
                    logger.info(f"Remote sync check of PUSH {push_id} cancelled by PULL {operation.id}")
                else:
                    return
            elif not is_enabled(config):
                return
            elif op_type == OperationType.PUSH.value:
                names = image_files(params.get("files") or [], config)
                if not names:
                    logger.info(f"PUSH {operation.id}: no image files to verify on the image host")
                    return
                push_id = operation.id
                check = RemoteSyncCheck(
                    operation_id=operation.id,
                    catalog_name=params.get("catalog_name") or "",
                    files=[{"name": n, "synced": False, "status_code": None} for n in names],
                    total_files=len(names),
                    synced_files=0,
                    attempts=0,
                    **_start_state(pim_event_id, config, now),
                )
                db.add(check)
            elif op_type == OperationType.UPDATE.value and params.get("push_operation_id"):
                push_id = params["push_operation_id"]
                names = image_files(params.get("files") or [], config)
                check = await _check_for(db, push_id, lock=True)
                if check is None:
                    if not names:
                        return
                    check = RemoteSyncCheck(operation_id=push_id, catalog_name=params.get("catalog_name") or "",
                                            files=[], attempts=0)
                    db.add(check)
                elif check.status == RemoteSyncStatus.CANCELLED:
                    return
                known = {f["name"]: f for f in (check.files or [])}
                touched = _touched_names(params.get("actions"))
                check.files = [
                    known[n] if n in known and n not in touched
                    else {"name": n, "synced": False, "status_code": None}
                    for n in names
                ]
                check.total_files = len(check.files)
                check.synced_files = sum(1 for f in check.files if f["synced"])
                check.completed_at = None
                check.last_error = None
                for key, value in _start_state(pim_event_id, config, now).items():
                    setattr(check, key, value)
                if check.files and check.synced_files == check.total_files and not pim_event_id:
                    check.status = RemoteSyncStatus.SYNCED
                    check.completed_at = now
            else:
                return

        logger.info(
            f"Remote sync check of PUSH {push_id} is {check.status} after "
            f"{op_type} {operation.id} ({check.synced_files}/{check.total_files} served)"
        )
        await notify_integration_update(push_id)
    except Exception as exc:
        logger.error(
            f"Could not update remote sync check for operation {getattr(operation, 'id', '?')}: {exc}",
            exc_info=True,
        )


async def _check_for(db, push_id, lock: bool = False) -> Optional[RemoteSyncCheck]:
    if push_id is None:
        return None
    stmt = select(RemoteSyncCheck).where(RemoteSyncCheck.operation_id == push_id)
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalars().first()


async def recheck(push_operation_id: int, db) -> Optional[RemoteSyncCheck]:
    """
    Check a PUSH's files again now, with a fresh timeout window.

    Files already served stay served. A check still waiting for PIM, or one
    cancelled by a PULL (the catalog is gone), is returned unchanged; one a
    user stopped starts again.
    """
    check = await _check_for(db, push_operation_id, lock=True)
    if check is None or check.status == RemoteSyncStatus.WAITING or (
        check.status == RemoteSyncStatus.CANCELLED and not check.cancelled_by
    ):
        return check
    now = datetime.now(timezone.utc)
    check.status = RemoteSyncStatus.CHECKING
    check.started_at = now
    check.next_check_at = now
    check.completed_at = None
    check.wait_event_id = None
    check.cancelled_at = None
    check.cancelled_by = None
    if check.synced_files == check.total_files:
        # "Check again" on a synced catalog verifies every file once more
        check.files = [{**f, "synced": False} for f in check.files]
        check.synced_files = 0
    await db.commit()
    await db.refresh(check)
    return check


async def stop_active_checks(db, username: str, push_operation_id: Optional[int] = None) -> list:
    """
    Stop WAITING and CHECKING checks: they become CANCELLED and are not checked
    again unless restarted by hand. Only the PUSH's check when
    ``push_operation_id`` is given, else every active check. Returns the PUSH
    operation ids stopped. A check being probed right now is stopped too; that
    pass's result is discarded (``_process`` applies only to an unchanged row).
    """
    now = datetime.now(timezone.utc)
    stmt = (
        update(RemoteSyncCheck)
        .where(RemoteSyncCheck.status.in_(RemoteSyncStatus.ACTIVE))
        .values(status=RemoteSyncStatus.CANCELLED, completed_at=now, cancelled_at=now, cancelled_by=username)
        .returning(RemoteSyncCheck.operation_id)
    )
    if push_operation_id is not None:
        stmt = stmt.where(RemoteSyncCheck.operation_id == push_operation_id)
    stopped = [row[0] for row in (await db.execute(stmt)).all()]
    await db.commit()
    if stopped:
        logger.info(f"Remote sync check stopped by '{username}' for PUSH(es) {stopped}")
    return stopped


async def queue_counts(db) -> dict:
    """Active checks by status."""
    rows = await db.execute(
        select(RemoteSyncCheck.status, func.count())
        .where(RemoteSyncCheck.status.in_(RemoteSyncStatus.ACTIVE))
        .group_by(RemoteSyncCheck.status)
    )
    counts = {"sync_waiting": 0, "sync_checking": 0}
    for status, count in rows.all():
        counts["sync_" + status.lower()] = count
    return counts


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------

async def _claim_next_check() -> Optional[RemoteSyncCheck]:
    now = datetime.now(timezone.utc)
    async with DatabaseManager.session() as db:
        stmt = (
            select(RemoteSyncCheck)
            .where(
                RemoteSyncCheck.status.in_(RemoteSyncStatus.ACTIVE),
                RemoteSyncCheck.next_check_at <= now,
            )
            .order_by(RemoteSyncCheck.next_check_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        check = (await db.execute(stmt)).scalars().first()
        if check is None:
            return None
        check.next_check_at = now + timedelta(seconds=_LEASE_SECONDS)
        await db.flush()
        db.expunge(check)
        return check


async def _probe(client: httpx.AsyncClient, url: str) -> tuple:
    """(served, status_code, error) for one image URL. Reads at most one chunk."""
    try:
        async with client.stream("GET", url) as response:
            content_type = response.headers.get("content-type", "").lower()
            if response.status_code != 200 or not content_type.startswith("image/"):
                return False, response.status_code, None
            async for chunk in response.aiter_bytes():
                if chunk:
                    return True, response.status_code, None
            return False, response.status_code, "empty body"
    except httpx.HTTPError as exc:
        return False, None, f"{type(exc).__name__}: {exc}"


async def _run_checks(check: RemoteSyncCheck, config: dict, tg_id: str) -> Optional[str]:
    """Probe every file not yet served; updates ``check.files`` in place."""
    template = (config.get('remote_sync_check_url_template') or '').strip() or DEFAULT_URL_TEMPLATE
    cache_bust = _truthy(config.get('remote_sync_check_cache_bust'), default=True)
    timeout = _int(config, 'remote_sync_check_request_timeout', 15) or 15
    semaphore = asyncio.Semaphore(_CONCURRENT_REQUESTS)
    errors = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async def probe(entry: dict) -> None:
            async with semaphore:
                url = build_check_url(template, check.catalog_name, entry["name"], tg_id, cache_bust)
                served, status_code, error = await _probe(client, url)
            entry["synced"] = served
            entry["status_code"] = status_code
            if error:
                errors.append(f"{entry['name']}: {error}")

        pending = [f for f in check.files if not f.get("synced")]
        await asyncio.gather(*(probe(entry) for entry in pending))

    return "; ".join(errors[:3]) if errors else None


async def _process(check: RemoteSyncCheck, config: dict) -> None:
    now = datetime.now(timezone.utc)
    values: dict = {}

    if check.status == RemoteSyncStatus.WAITING:
        async with DatabaseManager.session() as db:
            event = await db.get(PimEvent, check.wait_event_id) if check.wait_event_id else None
        if event is not None and event.status != PimEventStatus.DELIVERED:
            # Still waiting; the PIM badge shows why
            values["next_check_at"] = now + timedelta(seconds=15)
        else:
            started = (event.delivered_at if event is not None and event.delivered_at else now)
            values.update(
                status=RemoteSyncStatus.CHECKING,
                started_at=started,
                next_check_at=started + timedelta(
                    seconds=_int(config, 'remote_sync_check_initial_delay_seconds', 60)
                ),
            )
    else:
        started = check.started_at or now
        async with DatabaseManager.session() as db:
            push = await db.get(Operation, check.operation_id)
        tg_id = ((push.params_json or {}).get("tg_id") if push else None) or ""

        error = await _run_checks(check, config, tg_id)
        synced = sum(1 for f in check.files if f.get("synced"))
        values.update(
            files=check.files,
            synced_files=synced,
            attempts=check.attempts + 1,
            last_checked_at=now,
            last_error=error,
        )
        timeout = timedelta(minutes=_int(config, 'remote_sync_check_timeout_minutes', 180))
        if synced == check.total_files:
            values.update(status=RemoteSyncStatus.SYNCED, completed_at=now)
        elif now - started >= timeout:
            values.update(status=RemoteSyncStatus.TIMEOUT, completed_at=now)
        else:
            values["next_check_at"] = now + timedelta(
                seconds=max(10, _int(config, 'remote_sync_check_interval_seconds', 120))
            )

    async with DatabaseManager.session() as db:
        # Apply only if nobody (UPDATE, PULL, "check again") changed the row meanwhile
        current = await _check_for(db, check.operation_id, lock=True)
        if current is None or current.status != check.status or current.started_at != check.started_at \
                or current.wait_event_id != check.wait_event_id:
            return
        for key, value in values.items():
            setattr(current, key, value)

    if values.get("status") != check.status or values.get("synced_files", check.synced_files) != check.synced_files:
        logger.info(
            f"Remote sync check of PUSH {check.operation_id} ({check.catalog_name!r}): "
            f"{values.get('status', check.status)} "
            f"{values.get('synced_files', check.synced_files)}/{check.total_files} served"
            + (f"; errors: {values['last_error']}" if values.get("last_error") else "")
        )
        await notify_integration_update(check.operation_id)


async def process_due_checks(limit: int = 20) -> int:
    """Advance every due check, up to ``limit``. Safe in any number of processes."""
    try:
        async with DatabaseManager.session() as db:
            config = await get_sync_config(db)
        if not is_enabled(config):
            return 0
        processed = 0
        while processed < limit:
            check = await _claim_next_check()
            if check is None:
                break
            processed += 1
            try:
                await _process(check, config)
            except Exception as exc:
                logger.error(f"Remote sync check of PUSH {check.operation_id} failed: {exc}", exc_info=True)
        return processed
    except Exception as exc:
        logger.error(f"Remote sync pass failed: {exc}", exc_info=True)
        return 0
