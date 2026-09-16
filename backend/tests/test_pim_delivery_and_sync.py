"""
Reliable PIM delivery, tgId resolution and image host sync verification.

Needs a real PostgreSQL (FOR UPDATE SKIP LOCKED, JSON), like
test_update_uploads.py, whose fixtures this module reuses:

    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/rfm_test pytest tests/test_pim_delivery_and_sync.py

One local HTTP server plays PIM, the PolkaSQL web service and the image host,
so what is asserted is what those systems actually receive.
"""

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from models import (
    Operation,
    OperationStatus,
    OperationType,
    PimEvent,
    RemoteSyncCheck,
    User,
)
from tests.test_update_uploads import (  # noqa: F401  (fixtures)
    HOSTNAME,
    TEST_DATABASE_URL,
    add_user,
    add_worker,
    db_manager,
    fake_request,
    migrated_database,
    session,
    set_config,
    settings,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set (needs a disposable PostgreSQL database)",
)

TORBA = "TORBA HB0788 FA0542-910 SILVER"
TORBA_TG = "TORBA HB0788 FA0542"
OZDOBA = "OZDOBA PS261403 0-BRASS"
OZDOBA_TG = "OZDOBA PS261403 0"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 100


class Remote:
    """PIM + RFM_ValidateProductName + image host, all on one local port."""

    def __init__(self):
        self.pim_received = []
        self.pim_statuses = []          # popped per POST; empty -> 200
        self.products = {TORBA: TORBA_TG, OZDOBA: OZDOBA_TG}
        self.omit_tg_id = False
        self.images = {}                # (catalog, file) -> (status, content type, body)
        self.image_requests = []
        remote = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status, body=b"", content_type="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                remote.pim_received.append({"path": self.path, "token": self.headers.get("X-API-TOKEN"),
                                            "body": body})
                status = remote.pim_statuses.pop(0) if remote.pim_statuses else 200
                self._send(status, b'{"ok": true}' if status < 300 else b'{"error": "unavailable"}')

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/RFM_ValidateProductName":
                    q = parse_qs(url.query)
                    name = q["CatalogName"][0]
                    tg_id = remote.products.get(name)
                    data = {"success": q["ApiKey"][0] == "key", "valid": tg_id is not None,
                            "catalog_name": name, "matched_name": name if tg_id else None,
                            "product_id": 1 if tg_id else None, "suggestions": []}
                    if not remote.omit_tg_id:
                        data["tg_id"] = tg_id
                    return self._send(200, json.dumps(data).encode())
                # /uploads/product_thumb/<catalog>/up/<file>
                parts = url.path.split("/")
                remote.image_requests.append(self.path)
                catalog, name = unquote(parts[3]), unquote(parts[5])
                status, content_type, body = remote.images.get((catalog, name), (404, "text/html", b"<h1>404</h1>"))
                self._send(status, body, content_type)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    async def wait_for_pim(self, count, timeout=10):
        deadline = asyncio.get_running_loop().time() + timeout
        while len(self.pim_received) < count and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
        return self.pim_received


@pytest.fixture
def remote():
    server = Remote()
    yield server
    server.server.shutdown()


@pytest.fixture
async def configured(session, remote):
    await set_config(
        session,
        pim_enabled="true", pim_base_url=remote.url, pim_endpoint="/api/v1/image_catalog/ftp_event",
        pim_api_token="pim-token", pim_retry_base_seconds="10", pim_retry_max_delay_seconds="600",
        pim_retry_max_hours="72",
        catalog_validation_url=f"{remote.url}/RFM_ValidateProductName", catalog_validation_api_key="key",
        remote_sync_check_url_template=remote.url + "/uploads/product_thumb/{catalog_name}/up/{file}",
        remote_sync_check_initial_delay_seconds="0", remote_sync_check_interval_seconds="120",
        remote_sync_check_timeout_minutes="180",
    )


async def completed_operation(session, user, catalog=TORBA, op_type=OperationType.PUSH, **params) -> Operation:
    operation = Operation(
        user_id=user.id, type=op_type, source_path=f"A:/{catalog}", dest_path=f"B:/{catalog}",
        original_path=f"A:/{catalog}", status=OperationStatus.COMPLETED,
        params_json={"catalog_name": catalog, "files": ["1.png", "2.jpg"], "username": user.username, **params},
    )
    session.add(operation)
    await session.commit()
    await session.refresh(operation)
    return operation


async def event_of(db_manager, operation_id) -> PimEvent:
    async with db_manager.session() as s:
        return (await s.execute(select(PimEvent).where(PimEvent.operation_id == operation_id))).scalar_one()


async def check_of(db_manager, operation_id) -> RemoteSyncCheck:
    async with db_manager.session() as s:
        return (await s.execute(
            select(RemoteSyncCheck).where(RemoteSyncCheck.operation_id == operation_id)
        )).scalar_one_or_none()


async def make_due(db_manager, model=PimEvent):
    """Skip the backoff/interval wait."""
    column = PimEvent.next_attempt_at if model is PimEvent else RemoteSyncCheck.next_check_at
    async with db_manager.session() as s:
        await s.execute(update(model).values({column: datetime.now(timezone.utc) - timedelta(seconds=1)}))


# ---------------------------------------------------------------------------
# PIM delivery
# ---------------------------------------------------------------------------

def test_retry_delay_doubles_up_to_the_cap():
    from api.services.pim_service import retry_delay_seconds
    for attempts, expected in [(1, 10), (2, 20), (3, 40), (6, 320), (7, 600), (50, 600)]:
        delay = retry_delay_seconds(attempts, 10, 600)
        assert expected * 0.8 <= delay <= expected * 1.2, (attempts, delay)


async def test_failed_attempts_back_off_and_retry_until_delivered(session, db_manager, remote, configured):
    from api.app import get_operations_history
    from api.services.pim_service import deliver_due_events, enqueue_pim_event
    user = await add_user(session)
    push = await completed_operation(session, user, tg_id=TORBA_TG)
    remote.pim_statuses = [503, 502]

    assert await enqueue_pim_event(push) is not None

    started = datetime.now(timezone.utc)
    assert await deliver_due_events() == 1
    event = await event_of(db_manager, push.id)
    assert (event.status, event.attempts, event.last_status_code) == ("PENDING", 1, 503)
    assert event.last_error.startswith("HTTP 503")
    assert timedelta(seconds=7) < event.next_attempt_at - started < timedelta(seconds=13)
    assert await deliver_due_events() == 0  # not due yet

    await make_due(db_manager)
    await deliver_due_events()
    event = await event_of(db_manager, push.id)
    assert (event.status, event.attempts) == ("PENDING", 2)
    assert timedelta(seconds=15) < event.next_attempt_at - datetime.now(timezone.utc) < timedelta(seconds=25)

    await make_due(db_manager)
    await deliver_due_events()
    event = await event_of(db_manager, push.id)
    assert (event.status, event.attempts, event.last_error) == ("DELIVERED", 3, None)
    assert event.delivered_at is not None

    body = {"tgId": TORBA_TG, "imageCatalog": TORBA, "eventType": "created", "files": ["1.png", "2.jpg"]}
    assert [r["body"] for r in remote.pim_received] == [body] * 3
    assert remote.pim_received[0]["token"] == "pim-token"
    assert event.payload == body

    row = next(op for op in await get_operations_history(user, session) if op.id == push.id)
    assert row.pim_delivery.status == "DELIVERED" and row.pim_delivery.attempts == 3
    assert row.pim_delivery.tg_id == TORBA_TG


async def test_network_errors_and_missing_settings_are_retried(session, db_manager, remote, configured):
    from api.services.pim_service import deliver_due_events, enqueue_pim_event
    user = await add_user(session)
    push = await completed_operation(session, user, tg_id=TORBA_TG)
    await enqueue_pim_event(push)

    await set_config_value(session, pim_base_url="http://127.0.0.1:9")  # nothing listens
    await deliver_due_events()
    event = await event_of(db_manager, push.id)
    assert event.status == "PENDING" and event.last_error.startswith("ConnectError")

    await set_config_value(session, pim_base_url=remote.url, pim_api_token="")
    await make_due(db_manager)
    await deliver_due_events()
    event = await event_of(db_manager, push.id)
    assert event.status == "PENDING" and event.last_error == "pim_api_token is not configured"
    assert remote.pim_received == []

    # Fixing the configuration fixes the queued event
    await set_config_value(session, pim_api_token="pim-token")
    await make_due(db_manager)
    await deliver_due_events()
    assert (await event_of(db_manager, push.id)).status == "DELIVERED"
    assert len(remote.pim_received) == 1


async def set_config_value(session, **values):
    from models import Config
    for key, value in values.items():
        await session.execute(update(Config).where(Config.key == key).values(value=value))
    await session.commit()


async def test_gives_up_after_the_retry_window_and_can_be_retried(session, db_manager, remote, configured):
    from api.app import retry_pim_delivery
    from api.services.pim_service import deliver_due_events, enqueue_pim_event
    user = await add_user(session)
    push = await completed_operation(session, user, tg_id=TORBA_TG)
    await enqueue_pim_event(push)
    async with db_manager.session() as s:
        await s.execute(update(PimEvent).values(queued_at=datetime.now(timezone.utc) - timedelta(hours=73)))
    remote.pim_statuses = [500]

    await deliver_due_events()
    event = await event_of(db_manager, push.id)
    assert event.status == "FAILED" and event.attempts == 1
    await make_due(db_manager)
    assert await deliver_due_events() == 0  # failed events are not picked up

    state = await retry_pim_delivery(push.id, fake_request(), user, session)
    assert state.status == "PENDING"
    await remote.wait_for_pim(2)
    for _ in range(100):
        if (await event_of(db_manager, push.id)).status == "DELIVERED":
            break
        await asyncio.sleep(0.05)
    event = await event_of(db_manager, push.id)
    assert event.status == "DELIVERED" and event.attempts == 2

    with pytest.raises(HTTPException) as exc:
        await retry_pim_delivery(999999, fake_request(), user, session)
    assert exc.value.status_code == 404


async def test_events_of_one_catalog_keep_their_order(session, db_manager, remote, configured):
    from api.services.pim_service import deliver_due_events, enqueue_pim_event
    user = await add_user(session)
    push = await completed_operation(session, user, TORBA, tg_id=TORBA_TG)
    update_op = await completed_operation(session, user, TORBA, op_type=OperationType.UPDATE, tg_id=TORBA_TG)
    other = await completed_operation(session, user, OZDOBA, tg_id=OZDOBA_TG)
    for op in (push, update_op, other):
        await enqueue_pim_event(op)
    remote.pim_statuses = [503]  # the PUSH event fails first

    await deliver_due_events()

    sent = [(r["body"]["imageCatalog"], r["body"]["eventType"]) for r in remote.pim_received]
    assert sent == [(TORBA, "created"), (OZDOBA, "created")]  # UPDATE waits behind its PUSH
    assert (await event_of(db_manager, update_op.id)).attempts == 0

    await make_due(db_manager)
    await deliver_due_events()
    sent = [(r["body"]["imageCatalog"], r["body"]["eventType"]) for r in remote.pim_received]
    assert sent[2:] == [(TORBA, "created"), (TORBA, "updated")]


async def test_concurrent_delivery_passes_send_each_event_once(session, db_manager, remote, configured):
    from api.services.pim_service import deliver_due_events, enqueue_pim_event
    user = await add_user(session)
    for i in range(8):
        await enqueue_pim_event(await completed_operation(session, user, f"CAT {i}", tg_id=f"TG {i}"))

    await asyncio.gather(*(deliver_due_events() for _ in range(4)))

    assert sorted(r["body"]["imageCatalog"] for r in remote.pim_received) == [f"CAT {i}" for i in range(8)]


async def test_disabled_pim_queues_nothing_and_holds_queued_events(session, db_manager, remote, configured):
    from api.services.pim_service import deliver_due_events, enqueue_pim_event
    user = await add_user(session)
    queued = await completed_operation(session, user, tg_id=TORBA_TG)
    await enqueue_pim_event(queued)

    await set_config_value(session, pim_enabled="false")
    assert await enqueue_pim_event(await completed_operation(session, user, OZDOBA)) is None
    assert await deliver_due_events() == 0
    assert (await event_of(db_manager, queued.id)).status == "PENDING"

    await set_config_value(session, pim_enabled="true")
    await deliver_due_events()
    assert (await event_of(db_manager, queued.id)).status == "DELIVERED"


# ---------------------------------------------------------------------------
# tgId
# ---------------------------------------------------------------------------

async def test_catalog_validation_returns_tg_id(session, remote, configured):
    from api.services.catalog_validation_service import validate_catalog_name
    await set_config(session, catalog_validation_enabled="true")

    result = await validate_catalog_name(OZDOBA, session)
    assert result.valid and result.tg_id == OZDOBA_TG
    assert result.to_dict()["tg_id"] == OZDOBA_TG

    miss = await validate_catalog_name("OZDOBA PS261403 0-GOLD", session)
    assert not miss.valid and miss.tg_id is None


async def test_missing_tg_id_is_looked_up_at_delivery_or_retried(session, db_manager, remote, configured):
    from api.services.pim_service import deliver_due_events, enqueue_pim_event
    user = await add_user(session)

    # Not captured at PUSH time (validation off): looked up and kept
    push = await completed_operation(session, user, TORBA)
    await enqueue_pim_event(push)
    await deliver_due_events()
    event = await event_of(db_manager, push.id)
    assert event.status == "DELIVERED" and event.tg_id == TORBA_TG
    assert remote.pim_received[0]["body"]["tgId"] == TORBA_TG

    # The procedure is an old version without tg_id: never sent without it
    remote.omit_tg_id = True
    old = await completed_operation(session, user, OZDOBA)
    await enqueue_pim_event(old)
    await deliver_due_events()
    event = await event_of(db_manager, old.id)
    assert event.status == "PENDING" and "returned no tg_id" in event.last_error
    assert len(remote.pim_received) == 1

    # A template without {tg_id} needs no lookup
    remote.omit_tg_id = False
    await set_config_value(session, catalog_validation_url="")
    await set_config(session, pim_payload_template='{"imageCatalog": "{catalog_name}", "files": {files}}')
    unknown = await completed_operation(session, user, "NO SUCH PRODUCT")
    await enqueue_pim_event(unknown)
    await make_due(db_manager)
    await deliver_due_events()
    assert (await event_of(db_manager, unknown.id)).status == "DELIVERED"


# ---------------------------------------------------------------------------
# Image host sync verification
# ---------------------------------------------------------------------------

async def test_sync_check_waits_for_pim_then_checks_until_every_image_is_served(
    session, db_manager, remote, configured
):
    from api.app import get_operations_history
    from api.services.pim_service import deliver_due_events, enqueue_pim_event
    from api.services.remote_sync_service import process_due_checks, track_operation
    await set_config(session, remote_sync_check_enabled="true")
    user = await add_user(session)
    push = await completed_operation(session, user, tg_id=TORBA_TG)
    push.params_json = {**push.params_json, "files": ["1.png", "2.jpg", "notes.txt"]}
    await session.commit()

    remote.pim_statuses = [503]
    event_id = await enqueue_pim_event(push)
    await track_operation(push, event_id)
    check = await check_of(db_manager, push.id)
    assert check.status == "WAITING" and [f["name"] for f in check.files] == ["1.png", "2.jpg"]

    await deliver_due_events()  # PIM fails
    await process_due_checks()
    assert (await check_of(db_manager, push.id)).status == "WAITING"
    assert remote.image_requests == []

    await make_due(db_manager)
    await deliver_due_events()  # PIM accepts
    delivered_at = (await event_of(db_manager, push.id)).delivered_at

    # Clock starts at delivery; with no initial delay the first check follows in the same pass
    remote.images[(TORBA, "1.png")] = (200, "image/png", PNG)
    await make_due(db_manager, RemoteSyncCheck)
    await process_due_checks()
    check = await check_of(db_manager, push.id)
    assert check.started_at == delivered_at
    assert (check.status, check.synced_files, check.total_files) == ("CHECKING", 1, 2)
    assert {f["name"]: f["status_code"] for f in check.files} == {"1.png": 200, "2.jpg": 404}
    assert check.next_check_at - datetime.now(timezone.utc) > timedelta(seconds=100)
    # The catalog name is URL-encoded and every request bypasses the CDN cache
    first = remote.image_requests[0]
    assert "/uploads/product_thumb/TORBA%20HB0788%20FA0542-910%20SILVER/up/" in first
    assert "?rfm_sync=" in first

    remote.images[(TORBA, "2.jpg")] = (200, "image/jpeg", b"\xff\xd8\xff" + b"x" * 50)
    remote.image_requests.clear()
    await make_due(db_manager, RemoteSyncCheck)
    await process_due_checks()
    check = await check_of(db_manager, push.id)
    assert (check.status, check.synced_files) == ("SYNCED", 2)
    assert len(remote.image_requests) == 1 and "/up/2.jpg" in remote.image_requests[0]  # served files are not re-requested

    row = next(op for op in await get_operations_history(user, session) if op.id == push.id)
    assert row.remote_sync.status == "SYNCED" and row.remote_sync.synced_files == 2


async def test_empty_or_non_image_answers_do_not_count_and_time_out(session, db_manager, remote, configured):
    from api.app import recheck_remote_sync
    from api.services.remote_sync_service import process_due_checks, track_operation
    await set_config(session, remote_sync_check_enabled="true")
    user = await add_user(session)
    push = await completed_operation(session, user)
    await track_operation(push, None)  # PIM not signalled -> checks right away
    assert (await check_of(db_manager, push.id)).status == "CHECKING"

    # What the CDN was seen doing: cached empty 200 image/jpeg; and an HTML page
    remote.images[(TORBA, "1.png")] = (200, "image/png", b"")
    remote.images[(TORBA, "2.jpg")] = (200, "text/html", b"<html>not found</html>")
    async with db_manager.session() as s:
        await s.execute(update(RemoteSyncCheck).values(started_at=datetime.now(timezone.utc) - timedelta(hours=4)))
    await process_due_checks()
    check = await check_of(db_manager, push.id)
    assert (check.status, check.synced_files) == ("TIMEOUT", 0)
    assert check.completed_at is not None

    remote.images[(TORBA, "1.png")] = (200, "image/png", PNG)
    remote.images[(TORBA, "2.jpg")] = (200, "image/jpeg", PNG)
    state = await recheck_remote_sync(push.id, user, session)
    assert state.status == "CHECKING" and state.completed_at is None
    await process_due_checks()
    assert (await check_of(db_manager, push.id)).status == "SYNCED"

    await set_config_value(session, remote_sync_check_enabled="false")
    with pytest.raises(HTTPException) as exc:
        await recheck_remote_sync(push.id, user, session)
    assert exc.value.status_code == 409


async def test_disabled_sync_check_tracks_nothing(session, db_manager, remote, configured):
    from api.services.remote_sync_service import track_operation
    user = await add_user(session)
    push = await completed_operation(session, user)
    await track_operation(push, None)
    assert await check_of(db_manager, push.id) is None


# ---------------------------------------------------------------------------
# End to end: PUSH -> PIM created -> synced -> UPDATE -> PIM updated -> re-check -> PULL
# ---------------------------------------------------------------------------

async def test_push_update_pull_through_the_endpoints(session, db_manager, settings, remote, configured, monkeypatch):
    import api.app as app_module
    from api.app import get_operation_details, pull_operation, push_operation, update_operation
    from api.schemas import FilePullRequest, FilePushRequest, FileUpdateRequest
    from api.services.pim_service import deliver_due_events
    from api.services.remote_sync_service import process_due_checks
    from tests.update_fakes import FakeWorkerService

    await set_config(session, catalog_validation_enabled="true", remote_sync_check_enabled="true",
                     push_validation_min_files="2")
    user = await add_user(session)
    worker = await add_worker(session)
    worker.path_b_prefix = "\\\\server\\b"
    await session.commit()
    fake = FakeWorkerService({
        # Thumbs.db is what Windows leaves in an image folder (operation #9 on dev)
        f"A:/{TORBA}/1.png": PNG, f"A:/{TORBA}/2.png": PNG, f"A:/{TORBA}/Thumbs.db": b"cache",
        "A:/incoming/3.png": PNG,
    }, settings)
    monkeypatch.setattr(app_module, "WorkerService", lambda _settings: fake)

    # PUSH: validation captures tgId; PIM hears "created" with it; sync starts after delivery.
    # Thumbs.db is not copied, so PIM is not told about it (it would answer 422).
    push = await push_operation(FilePushRequest(source_path=f"A:/{TORBA}", worker_id=worker.id),
                                fake_request(), user, session, settings)
    assert push.status == OperationStatus.COMPLETED
    assert push.params_json["tg_id"] == TORBA_TG
    assert f"B:/{TORBA}/Thumbs.db" not in fake.files and f"B:/{TORBA}/1.png" in fake.files
    received = await remote.wait_for_pim(1)
    assert received[0]["body"] == {"tgId": TORBA_TG, "imageCatalog": TORBA, "eventType": "created",
                                   "files": ["1.png", "2.png"]}

    for name in ("1.png", "2.png"):
        remote.images[(TORBA, name)] = (200, "image/png", PNG)
    for _ in range(100):
        if (await event_of(db_manager, push.id)).status == "DELIVERED":
            break
        await asyncio.sleep(0.05)
    await make_due(db_manager, RemoteSyncCheck)
    await process_due_checks()  # WAITING -> CHECKING -> checked
    check = await check_of(db_manager, push.id)
    assert (check.status, check.synced_files, check.total_files) == ("SYNCED", 2, 2)

    # UPDATE adds 3.png: PIM hears "updated"; the check waits for it, then verifies 3.png only
    remote.image_requests.clear()
    update = await update_operation(
        FileUpdateRequest(catalog_path=f"B:/{TORBA}", worker_id=worker.id, push_operation_id=push.id,
                          actions=[{"action": "add", "dest": "3.png", "from_path": "A:/incoming/3.png"}]),
        fake_request(), user, session, settings,
    )
    assert update.status == OperationStatus.COMPLETED and update.params_json["tg_id"] == TORBA_TG
    received = await remote.wait_for_pim(2)
    assert received[1]["body"] == {"tgId": TORBA_TG, "imageCatalog": TORBA, "eventType": "updated",
                                   "files": ["1.png", "2.png", "3.png"]}
    check = await check_of(db_manager, push.id)
    assert check.status in ("WAITING", "CHECKING") and (check.synced_files, check.total_files) == (2, 3)

    remote.images[(TORBA, "3.png")] = (200, "image/png", PNG)
    for _ in range(100):
        if (await event_of(db_manager, update.id)).status == "DELIVERED":
            break
        await asyncio.sleep(0.05)
    await make_due(db_manager, RemoteSyncCheck)
    await process_due_checks()
    await make_due(db_manager, RemoteSyncCheck)
    await process_due_checks()
    check = await check_of(db_manager, push.id)
    assert (check.status, check.synced_files) == ("SYNCED", 3)
    assert all("/up/3.png" in path for path in remote.image_requests)

    details = await get_operation_details(push.id, user, session)
    assert details.operation.remote_sync.status == "SYNCED"
    assert details.operation.pim_delivery.status == "DELIVERED"
    assert details.updates[0].pim_delivery.event_type == "updated"

    # PULL: PIM hears "updated" with the PUSH's tgId; a finished check stays as the record
    pulled = await pull_operation(FilePullRequest(operation_id=push.id, worker_id=worker.id),
                                  fake_request(), user, session, settings)
    assert pulled.status == OperationStatus.COMPLETED
    received = await remote.wait_for_pim(3)
    assert received[2]["body"]["tgId"] == TORBA_TG and received[2]["body"]["eventType"] == "updated"
    assert (await check_of(db_manager, push.id)).status == "SYNCED"


async def test_pull_cancels_an_active_check(session, db_manager, remote, configured):
    from api.services.remote_sync_service import track_operation
    await set_config(session, remote_sync_check_enabled="true")
    user = await add_user(session)
    push = await completed_operation(session, user)
    await track_operation(push, None)

    pull = Operation(user_id=user.id, type=OperationType.PULL, source_path=push.dest_path,
                     dest_path=push.original_path, rollback_operation_id=push.id,
                     status=OperationStatus.COMPLETED, params_json={"username": user.username})
    session.add(pull)
    await session.commit()
    await track_operation(pull, None)

    check = await check_of(db_manager, push.id)
    assert check.status == "CANCELLED" and check.completed_at is not None


# ---------------------------------------------------------------------------
# PIM file name rule: only "<number>.<extension>" reaches PIM
# ---------------------------------------------------------------------------

@pytest.fixture
async def name_rule_setup(session, settings, remote, configured, monkeypatch):
    """Catalog validation on, the fake worker wired in; each test fills the shares."""
    import api.app as app_module
    from tests.update_fakes import FakeWorkerService

    await set_config(session, catalog_validation_enabled="true", push_validation_min_files="2",
                     push_validation_file_names="true", push_ignore_file_masks="Thumbs.db,*.tmp")
    user = await add_user(session)
    worker = await add_worker(session)
    worker.path_b_prefix = "\\\\server\\b"
    await session.commit()
    fake = FakeWorkerService({}, settings)
    monkeypatch.setattr(app_module, "WorkerService", lambda _settings: fake)
    return {"user": user, "worker": worker, "fake": fake}


async def operation_count(db_manager) -> tuple:
    async with db_manager.session() as s:
        operations = len((await s.execute(select(Operation.id))).all())
        events = len((await s.execute(select(PimEvent.id))).all())
    return operations, events


async def test_name_rule_refuses_push_before_anything_is_copied(
    session, db_manager, settings, remote, name_rule_setup
):
    from api.app import preflight_catalog, push_operation, push_operation_batch
    from api.schemas import FilePushBatchRequest, FilePushRequest

    user, worker, fake = name_rule_setup["user"], name_rule_setup["worker"], name_rule_setup["fake"]
    source = f"A:/{TORBA}"
    fake.files.update({
        f"{source}/1.png": PNG, f"{source}/front.png": PNG, f"{source}/notes.txt": b"text",
        f"{source}/Thumbs.db": b"cache", f"{source}/~lock.TMP": b"x",
    })
    request = FilePushRequest(source_path=source, worker_id=worker.id)

    # Preflight names every offender; ignored files are not among them
    preflight = await preflight_catalog(request, user, session, settings)
    assert preflight.ok is False
    assert preflight.content.reason == "contentValidation.invalidFileNames"
    assert preflight.content.invalid_names == ["front.png", "notes.txt"]
    assert preflight.content.files == ["1.png", "front.png", "notes.txt"]
    assert (preflight.content.total_files, preflight.content.image_count) == (3, 2)
    assert preflight.content.non_image_files == ["notes.txt"]

    # Single PUSH: 422 with the same detail, nothing copied, nothing recorded, PIM not called
    with pytest.raises(HTTPException) as refused:
        await push_operation(request, fake_request(), user, session, settings)
    assert refused.value.status_code == 422
    content = refused.value.detail["content"]
    assert content["reason"] == "contentValidation.invalidFileNames"
    assert content["invalid_names"] == ["front.png", "notes.txt"]

    # Batch PUSH (what the WebUI calls): refused per directory the same way
    batch = await push_operation_batch(FilePushBatchRequest(source_paths=[source], worker_id=worker.id),
                                       fake_request(), user, session, settings)
    result = batch.results[0]
    assert result.success is False and result.error == "validation_failed"
    assert result.validation["content"]["invalid_names"] == ["front.png", "notes.txt"]

    assert [c for c in fake.commands if c[0] != "validate_dir"] == []
    assert not any(p.startswith("B:/") for p in fake.files)
    assert await operation_count(db_manager) == (0, 0)
    assert remote.pim_received == []

    # Fixed names pass; PIM receives exactly the renamed files
    fake.files[f"{source}/2.png"] = fake.files.pop(f"{source}/front.png")
    del fake.files[f"{source}/notes.txt"]
    push = await push_operation(request, fake_request(), user, session, settings)
    assert push.status == OperationStatus.COMPLETED
    received = await remote.wait_for_pim(1)
    assert received[0]["body"]["files"] == ["1.png", "2.png"]
    assert sorted(p for p in fake.files if p.startswith("B:/")) == [f"B:/{TORBA}/1.png", f"B:/{TORBA}/2.png"]


async def test_name_rule_can_be_switched_off(session, db_manager, settings, remote, name_rule_setup):
    from api.app import push_operation
    from api.schemas import FilePushRequest

    user, worker, fake = name_rule_setup["user"], name_rule_setup["worker"], name_rule_setup["fake"]
    await set_config_value(session, push_validation_file_names="false")
    fake.files.update({f"A:/{TORBA}/front.png": PNG, f"A:/{TORBA}/back.png": PNG,
                       f"A:/{TORBA}/Thumbs.db": b"cache"})

    push = await push_operation(FilePushRequest(source_path=f"A:/{TORBA}", worker_id=worker.id),
                                fake_request(), user, session, settings)

    assert push.status == OperationStatus.COMPLETED
    received = await remote.wait_for_pim(1)
    # Ignored files stay out of PIM whether or not the name rule is on
    assert received[0]["body"]["files"] == ["back.png", "front.png"]


async def test_name_rule_judges_update_after_its_actions(session, db_manager, settings, remote, name_rule_setup):
    from api.app import update_operation
    from api.schemas import FileUpdateRequest

    user, worker, fake = name_rule_setup["user"], name_rule_setup["worker"], name_rule_setup["fake"]
    catalog = f"B:/{TORBA}"
    # Pushed before the rule existed: front.png is already in the catalog, and
    # Windows has since left a Thumbs.db there
    fake.files.update({f"{catalog}/1.png": PNG, f"{catalog}/front.png": PNG, f"{catalog}/Thumbs.db": b"cache",
                       "A:/incoming/3.png": PNG, "A:/incoming/back.png": PNG})
    push = await completed_operation(session, user, tg_id=TORBA_TG)
    before = dict(fake.files)

    async def update(actions):
        return await update_operation(
            FileUpdateRequest(catalog_path=catalog, worker_id=worker.id, push_operation_id=push.id, actions=actions),
            fake_request(), user, session, settings,
        )

    # Leaving the bad name in place, or adding another one, is refused and changes nothing
    for actions, names in (
        ([{"action": "add", "dest": "3.png", "from_path": "A:/incoming/3.png"}], ["front.png"]),
        ([{"action": "rename", "source": "front.png", "dest": "2.png"},
          {"action": "add", "dest": "back.png", "from_path": "A:/incoming/back.png"}], ["back.png"]),
    ):
        with pytest.raises(HTTPException) as refused:
            await update(actions)
        assert refused.value.status_code == 422
        assert refused.value.detail["content"]["reason"] == "contentValidation.invalidFileNames"
        assert refused.value.detail["content"]["invalid_names"] == names
        assert fake.files == before

    # Renaming the offender fixes the catalog; PIM hears the corrected list, without Thumbs.db
    done = await update([{"action": "rename", "source": "front.png", "dest": "2.png"}])
    assert done.status == OperationStatus.COMPLETED
    assert done.params_json["files"] == ["1.png", "2.png"]
    received = await remote.wait_for_pim(1)
    assert received[0]["body"]["files"] == ["1.png", "2.png"]
    assert received[0]["body"]["eventType"] == "updated"
