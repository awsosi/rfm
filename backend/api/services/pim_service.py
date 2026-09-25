"""
PIM (Product Information Manager) Signalling Service

Second, independent signalling target alongside ROSAPI. Notifies the PIM
system whenever a catalog operation completes:

    PUSH   -> eventType "created"
    PULL   -> eventType "deleted"
    UPDATE -> eventType "updated"

Delivery is reliable (transactional outbox):

1. ``enqueue_pim_event()`` stores a ``pim_events`` row when the operation
   completes. Nothing is sent inline, so a PIM outage never slows down or
   fails the operation, and a restart loses nothing.
2. ``deliver_due_events()`` sends due events. It runs right after enqueueing
   (so a healthy PIM hears within milliseconds) and from a background loop in
   every API process. Rows are claimed with ``FOR UPDATE SKIP LOCKED`` and a
   lease, so the four uvicorn processes never send the same attempt twice, and
   a process that dies mid-attempt only delays that event by the lease.
3. A failed attempt (network error, timeout, non-2xx, missing configuration,
   unresolvable tgId) is retried with exponential backoff and jitter:
   ``pim_retry_base_seconds`` doubling up to ``pim_retry_max_delay_seconds``.
   After ``pim_retry_max_hours`` (0 = never) the event is marked FAILED; a user
   can retry it from the operation details.
4. Events of one catalog are delivered in order: an event waits while an older
   event of the same catalog is still pending, so PIM never sees "updated"
   before "created".
5. A user can stop a PENDING event (``stop_pending_events``): it becomes
   CANCELLED, is never attempted again unless sent again by hand, and no longer
   holds back later events of its catalog. An attempt already on the wire when
   it is stopped may still reach PIM; its outcome is not recorded.

A timeout after PIM processed the request but before it answered causes a
repeat delivery; PIM receives the same event twice rather than never.

Authentication is a static ``X-API-TOKEN`` header. The request body is a
template stored in the ``config`` table and editable from the Admin Panel:

- ``{files}``        JSON array of top-level basenames (substituted as raw JSON)
- ``{catalog_name}`` catalog/folder name (``imageCatalog``)
- ``{event_type}``   resolved eventType for this operation
- ``{tg_id}``        product tgId, ``Polka27.elementy.grup_nazwe_kolor``; captured by
                     catalog validation, otherwise looked up at delivery time
- ``{operation_id}`` RFM operation ID
- ``{username}``     user who triggered the operation
- ``{source_path}`` / ``{dest_path}``
"""

import asyncio
import json
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import aliased

from database import DatabaseManager
from models import Config, Operation, OperationType, PimEvent, PimEventStatus

_CONFIG_KEYS = [
    'pim_enabled',
    'pim_base_url',
    'pim_endpoint',
    'pim_method',
    'pim_api_token',
    'pim_timeout',
    'pim_push_enabled',
    'pim_push_event_type',
    'pim_pull_enabled',
    'pim_pull_event_type',
    'pim_update_enabled',
    'pim_update_event_type',
    'pim_payload_template',
    'pim_retry_base_seconds',
    'pim_retry_max_delay_seconds',
    'pim_retry_max_hours',
]

DEFAULT_TEMPLATE = (
    '{"tgId": "{tg_id}", "imageCatalog": "{catalog_name}", '
    '"eventType": "{event_type}", "files": {files}}'
)

# Operation type -> (toggle key, eventType key, default eventType)
_EVENT_TOGGLES = {
    "PUSH": ('pim_push_enabled', 'pim_push_event_type', 'created'),
    "PULL": ('pim_pull_enabled', 'pim_pull_event_type', 'deleted'),
    "UPDATE": ('pim_update_enabled', 'pim_update_event_type', 'updated'),
}

# Keeps fire-and-forget delivery tasks referenced until they finish
_background_tasks: set = set()


class DeliveryError(Exception):
    """An attempt that cannot be made (configuration, template, tgId)."""


async def get_pim_config(db) -> dict:
    """Read all PIM config keys from the database."""
    result = await db.execute(
        select(Config.key, Config.value).where(Config.key.in_(_CONFIG_KEYS))
    )
    return {row.key: row.value for row in result}


def _truthy(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ('true', '1', 'yes')


def _int(config: dict, key: str, default: int) -> int:
    try:
        return int(config.get(key, default))
    except (TypeError, ValueError):
        return default


def _json_string(value: str) -> str:
    """Escape a value for safe interpolation inside a JSON string literal."""
    # json.dumps gives us a quoted string; strip the surrounding quotes so the
    # template's own quotes stay in control of the result.
    return json.dumps(str(value))[1:-1]


def resolve_payload_template(
    template: str,
    files: list,
    catalog_name: str,
    event_type: str,
    operation_id: int,
    username: str,
    source_path: str,
    dest_path: str,
    tg_id: str = "",
) -> str:
    """
    Resolve placeholders in the payload template.

    ``{files}`` is substituted as a raw JSON array so the template can write
    ``"files": {files}``. Every other placeholder is escaped for use inside a
    JSON string literal.
    """
    result = template
    result = result.replace("{files}", json.dumps(list(files), ensure_ascii=False))
    result = result.replace("{catalog_name}", _json_string(catalog_name))
    result = result.replace("{event_type}", _json_string(event_type))
    result = result.replace("{tg_id}", _json_string(tg_id))
    result = result.replace("{username}", _json_string(username))
    result = result.replace("{source_path}", _json_string(source_path))
    result = result.replace("{dest_path}", _json_string(dest_path))
    # Numeric, not string-escaped
    result = result.replace("{operation_id}", str(operation_id))
    return result


def extract_catalog_name(op_type: str, source_path: str, dest_path: str) -> str:
    """
    Derive the catalog (folder) name for an operation.

    PUSH signals the destination that was just created in PATH_B; PULL and
    UPDATE both act on a path whose basename is already the catalog name, so
    the destination is preferred with the source as fallback.
    """
    op = (op_type or "").upper()
    path = dest_path if op == "PUSH" else (source_path or dest_path)
    if not path:
        path = dest_path or ""
    return os.path.basename(str(path).rstrip('/\\'))


def retry_delay_seconds(attempts: int, base: int, max_delay: int) -> float:
    """
    Delay before the next attempt after ``attempts`` failed ones.

    ``base * 2^(attempts-1)`` capped at ``max_delay``, with +/-20% jitter so
    events that failed together do not retry in lockstep.
    """
    base = max(1, base)
    max_delay = max(base, max_delay)
    delay = min(max_delay, base * (2 ** max(0, min(attempts - 1, 30))))
    return delay * random.uniform(0.8, 1.2)


async def notify_integration_update(operation_id: Optional[int]) -> None:
    """
    Tell this process's WebUI clients that an operation's PIM/sync state
    changed (``None``: several operations at once).
    """
    try:
        from api.websocket_manager import ws_manager
        await ws_manager.broadcast(
            {"type": "operation_integration_update", "operation_id": operation_id},
            topic="operations",
        )
    except Exception as exc:
        logger.debug(f"Integration update broadcast failed for operation {operation_id}: {exc}")


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

async def enqueue_pim_event(operation: Operation) -> Optional[int]:
    """
    Store the PIM event for a completed operation. Returns the event id, or
    None when PIM is not signalled for this operation.

    Never raises: signalling must not fail an operation that already succeeded.
    """
    try:
        op_type = operation.type.value if hasattr(operation.type, "value") else str(operation.type)
        if op_type not in _EVENT_TOGGLES:
            return None

        async with DatabaseManager.session() as db:
            config = await get_pim_config(db)
            if not _truthy(config.get('pim_enabled'), default=False):
                logger.debug("PIM signalling is disabled, skipping")
                return None

            enabled_key, event_key, event_default = _EVENT_TOGGLES[op_type]
            if not _truthy(config.get(enabled_key), default=True):
                logger.debug(f"PIM {op_type} signalling is disabled")
                return None
            event_type = (config.get(event_key) or event_default).strip() or event_default

            params = operation.params_json or {}
            tg_id = params.get("tg_id")
            if not tg_id and op_type == "PULL" and operation.rollback_operation_id:
                # A PULL carries its PUSH's product identity
                push = await db.get(Operation, operation.rollback_operation_id)
                tg_id = ((push.params_json or {}).get("tg_id") if push else None)

            now = datetime.now(timezone.utc)
            event = PimEvent(
                operation_id=operation.id,
                operation_type=op_type,
                event_type=event_type,
                catalog_name=params.get("catalog_name") or extract_catalog_name(
                    op_type, operation.source_path, operation.dest_path
                ),
                tg_id=tg_id or None,
                files=list(params.get("files") or []),
                username=params.get("username") or "",
                source_path=operation.source_path or "",
                dest_path=operation.dest_path or "",
                status=PimEventStatus.PENDING,
                attempts=0,
                queued_at=now,
                next_attempt_at=now,
            )
            db.add(event)
            await db.flush()
            event_id = event.id

        logger.info(
            f"PIM event {event_id} queued: operation={operation.id} {op_type} "
            f"eventType={event_type} imageCatalog={event.catalog_name!r} "
            f"tgId={event.tg_id!r} files={len(event.files)} user={event.username or 'unknown'}"
        )
        return event_id
    except Exception as exc:
        logger.error(
            f"Could not queue PIM event for operation {getattr(operation, 'id', '?')}: {exc}",
            exc_info=True,
        )
        return None


def kick_delivery() -> None:
    """Start a delivery pass now, without waiting for the background loop."""
    task = asyncio.create_task(deliver_due_events())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

async def _claim_next_event(lease_seconds: int) -> Optional[PimEvent]:
    """
    Claim one due event: count the attempt and push ``next_attempt_at`` out by
    the lease, in one transaction, so no other process picks it up meanwhile.
    """
    now = datetime.now(timezone.utc)
    older = aliased(PimEvent)
    async with DatabaseManager.session() as db:
        stmt = (
            select(PimEvent)
            .where(
                PimEvent.status == PimEventStatus.PENDING,
                PimEvent.next_attempt_at <= now,
                ~exists().where(
                    older.catalog_name == PimEvent.catalog_name,
                    older.status == PimEventStatus.PENDING,
                    older.id < PimEvent.id,
                ),
            )
            .order_by(PimEvent.id)
            .limit(1)
            .with_for_update(skip_locked=True, of=PimEvent)
        )
        event = (await db.execute(stmt)).scalars().first()
        if event is None:
            return None
        event.attempts += 1
        event.last_attempt_at = now
        event.next_attempt_at = now + timedelta(seconds=lease_seconds)
        await db.flush()
        db.expunge(event)
        return event


async def _build_request(event: PimEvent, config: dict) -> tuple:
    """Resolve URL, headers and body for one attempt. Raises DeliveryError."""
    base_url = (config.get('pim_base_url') or '').strip()
    endpoint = (config.get('pim_endpoint') or '').strip()
    method = (config.get('pim_method') or 'POST').strip().upper()
    api_token = (config.get('pim_api_token') or '').strip()
    template = (config.get('pim_payload_template') or '').strip() or DEFAULT_TEMPLATE

    for key, value in (('pim_base_url', base_url), ('pim_endpoint', endpoint), ('pim_api_token', api_token)):
        if not value:
            raise DeliveryError(f"{key} is not configured")
    if method not in ('POST', 'PUT', 'PATCH'):
        raise DeliveryError(f"unsupported pim_method {method!r}")

    tg_id = event.tg_id or ""
    if "{tg_id}" in template and not tg_id:
        from api.services.catalog_validation_service import lookup_tg_id
        async with DatabaseManager.session() as db:
            resolved, reason = await lookup_tg_id(event.catalog_name, db)
            if not resolved:
                raise DeliveryError(f"tgId could not be resolved: {reason}")
            await db.execute(
                update(PimEvent).where(PimEvent.id == event.id).values(tg_id=resolved)
            )
        tg_id = event.tg_id = resolved

    payload_str = resolve_payload_template(
        template=template,
        files=event.files or [],
        catalog_name=event.catalog_name,
        event_type=event.event_type,
        operation_id=event.operation_id,
        username=event.username or "",
        source_path=event.source_path or "",
        dest_path=event.dest_path or "",
        tg_id=tg_id,
    )
    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError as exc:
        raise DeliveryError(f"pim_payload_template does not produce valid JSON: {exc}")

    url = f"{base_url.rstrip('/')}{endpoint if endpoint.startswith('/') else '/' + endpoint}"
    headers = {
        "X-API-TOKEN": api_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    return method, url, headers, payload


async def _attempt(event: PimEvent, config: dict) -> None:
    """Make one delivery attempt and record its outcome."""
    status_code = None
    payload = None
    error = None
    try:
        method, url, headers, payload = await _build_request(event, config)
        timeout = _int(config, 'pim_timeout', 10)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, json=payload, headers=headers)
        status_code = response.status_code
        if not 200 <= status_code < 300:
            error = f"HTTP {status_code}: {response.text[:300]}"
    except DeliveryError as exc:
        error = str(exc)
    except httpx.TimeoutException as exc:
        error = f"timeout: {type(exc).__name__}"
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        logger.error(f"Unexpected error delivering PIM event {event.id}: {exc}", exc_info=True)
        error = f"{type(exc).__name__}: {exc}"

    now = datetime.now(timezone.utc)
    values = {"last_status_code": status_code, "payload": payload, "last_error": error}
    if error is None:
        values.update(status=PimEventStatus.DELIVERED, delivered_at=now)
        logger.info(
            f"PIM event {event.id} delivered (operation={event.operation_id} "
            f"{event.operation_type}, eventType={event.event_type}, "
            f"imageCatalog={event.catalog_name!r}, tgId={event.tg_id!r}, "
            f"attempt {event.attempts}) -> {status_code}"
        )
    else:
        max_hours = _int(config, 'pim_retry_max_hours', 72)
        queued_at = event.queued_at
        if queued_at.tzinfo is None:
            queued_at = queued_at.replace(tzinfo=timezone.utc)
        if max_hours > 0 and now - queued_at >= timedelta(hours=max_hours):
            values.update(status=PimEventStatus.FAILED)
            logger.error(
                f"PIM event {event.id} FAILED after {event.attempts} attempt(s) over "
                f"{max_hours}h (operation={event.operation_id}, "
                f"imageCatalog={event.catalog_name!r}): {error}"
            )
        else:
            delay = retry_delay_seconds(
                event.attempts,
                _int(config, 'pim_retry_base_seconds', 10),
                _int(config, 'pim_retry_max_delay_seconds', 600),
            )
            values.update(next_attempt_at=now + timedelta(seconds=delay))
            logger.warning(
                f"PIM event {event.id} attempt {event.attempts} failed "
                f"(operation={event.operation_id}, imageCatalog={event.catalog_name!r}): "
                f"{error}; retrying in {delay:.0f}s"
            )

    async with DatabaseManager.session() as db:
        # A manual retry or give-up that happened meanwhile wins
        await db.execute(
            update(PimEvent)
            .where(PimEvent.id == event.id, PimEvent.status == PimEventStatus.PENDING)
            .values(**values)
        )
    await notify_integration_update(event.operation_id)


async def deliver_due_events(limit: int = 50) -> int:
    """
    Deliver every due event, up to ``limit`` attempts. Returns attempts made.

    Safe to run concurrently in any number of processes. Does nothing while
    ``pim_enabled`` is off; queued events wait and go out once it is back on.
    """
    try:
        async with DatabaseManager.session() as db:
            config = await get_pim_config(db)
        if not _truthy(config.get('pim_enabled'), default=False):
            return 0

        lease = _int(config, 'pim_timeout', 10) + 120
        attempts = 0
        while attempts < limit:
            event = await _claim_next_event(lease)
            if event is None:
                break
            attempts += 1
            await _attempt(event, config)
        return attempts
    except Exception as exc:
        logger.error(f"PIM delivery pass failed: {exc}", exc_info=True)
        return 0


async def retry_event(operation_id: int, db) -> Optional[PimEvent]:
    """
    Make an operation's PENDING, FAILED or CANCELLED event due now, with a
    fresh retry window. Returns the event, or None if the operation has no
    event. Delivered events are left alone.
    """
    event = (
        await db.execute(select(PimEvent).where(PimEvent.operation_id == operation_id))
    ).scalars().first()
    if event is None or event.status == PimEventStatus.DELIVERED:
        return event
    now = datetime.now(timezone.utc)
    event.status = PimEventStatus.PENDING
    event.queued_at = now
    event.next_attempt_at = now
    event.cancelled_at = None
    event.cancelled_by = None
    await db.commit()
    await db.refresh(event)
    return event


async def stop_pending_events(db, username: str, operation_id: Optional[int] = None) -> list:
    """
    Stop PENDING events (waiting for their first attempt or retrying): they
    become CANCELLED and are not attempted again. Only the operation's event
    when ``operation_id`` is given, else every pending event. Returns the
    operation ids stopped. One statement, so a delivery pass never sees a
    half-stopped queue; an event claimed for an attempt right now is stopped
    too, and that attempt's outcome is discarded.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        update(PimEvent)
        .where(PimEvent.status == PimEventStatus.PENDING)
        .values(status=PimEventStatus.CANCELLED, cancelled_at=now, cancelled_by=username)
        .returning(PimEvent.operation_id)
    )
    if operation_id is not None:
        stmt = stmt.where(PimEvent.operation_id == operation_id)
    stopped = [row[0] for row in (await db.execute(stmt)).all()]
    await db.commit()
    if stopped:
        logger.info(f"PIM delivery stopped by '{username}' for operation(s) {stopped}")
    return stopped


async def queue_counts(db) -> dict:
    """PENDING events split into not yet attempted and retrying."""
    pending, retrying = (await db.execute(
        select(
            func.count().filter(PimEvent.attempts == 0),
            func.count().filter(PimEvent.attempts > 0),
        ).where(PimEvent.status == PimEventStatus.PENDING)
    )).one()
    return {"pim_pending": pending, "pim_retrying": retrying}
