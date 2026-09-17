"""
UPDATE uploads, garbage collection, history links and the PIM event.

Needs a real PostgreSQL (conditional UPDATE ... RETURNING, JSON operators),
like test_worker_offline.py. The schema is built with ``alembic upgrade head``
and every test truncates the tables it uses.

    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/rfm_test pytest tests/test_update_uploads.py

The end-to-end tests call the real endpoint functions with the in-memory
worker from ``update_fakes`` and a local HTTP server standing in for PIM, so
what is asserted is what PIM actually receives.
"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from starlette.requests import Request

from database import DatabaseManager
from models import (
    Config,
    ConfigType,
    Operation,
    OperationStatus,
    OperationType,
    UpdateUpload,
    User,
    UserRole,
    Worker,
    WorkerStatus,
)

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set (needs a disposable PostgreSQL database)",
)

HOSTNAME = "TEST-WORKER-01"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def migrated_database():
    backend_dir = Path(__file__).resolve().parent.parent
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        check=True,
        capture_output=True,
    )


@pytest.fixture
async def db_manager(migrated_database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    await DatabaseManager.close()
    DatabaseManager.initialize(pool_size=5, max_overflow=5)
    async with DatabaseManager.session() as s:
        # A connection leaked by a failed test must not hang the suite
        await s.execute(text("SET LOCAL lock_timeout = '10s'"))
        await s.execute(text(
            "TRUNCATE users, workers, operations, operation_workers, worker_commands, "
            "update_uploads, pim_events, remote_sync_checks, audit_logs, config RESTART IDENTITY CASCADE"
        ))
    yield DatabaseManager
    await DatabaseManager.close()


@pytest.fixture
async def session(db_manager):
    async with db_manager.get_session_factory()() as s:
        yield s


@pytest.fixture
def settings(tmp_path):
    from api.config import get_settings
    return get_settings().model_copy(update={
        "update_upload_dir": str(tmp_path / "uploads"),
        "secret_key": "test-secret-key",
        "elasticsearch_enabled": False,
    })


def fake_request() -> Request:
    return Request({"type": "http", "headers": [], "client": ("10.0.0.1", 50000)})


async def add_user(session, username="alice") -> User:
    user = User(username=username, password_hash="x", role=UserRole.USER)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def add_worker(session) -> Worker:
    worker = Worker(name=HOSTNAME, hostname=HOSTNAME, public_key="k", status=WorkerStatus.ACTIVE,
                    last_heartbeat=datetime.now(timezone.utc))
    session.add(worker)
    await session.commit()
    await session.refresh(worker)
    return worker


async def set_config(session, **values) -> None:
    for key, value in values.items():
        session.add(Config(key=key, value=str(value), type=ConfigType.STRING))
    await session.commit()


async def chunks_of(data: bytes, size: int = 1000):
    for i in range(0, len(data), size):
        yield data[i:i + size]


async def upload(session, user, settings, data=b"\xff\xd8 image bytes", name="C:\\fakepath\\new.jpg"):
    from api.services.upload_service import store_upload
    return await store_upload(user, name, chunks_of(data), session, settings)


async def row(db_manager, upload_id) -> UpdateUpload:
    async with db_manager.session() as s:
        return await s.get(UpdateUpload, upload_id)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

async def test_upload_is_streamed_hashed_and_recorded(session, db_manager, settings):
    user = await add_user(session)
    data = os.urandom(5000)

    stored = await upload(session, user, settings, data)

    assert stored.original_filename == "new.jpg"  # browser path stripped
    assert stored.size_bytes == 5000
    assert stored.sha256 == hashlib.sha256(data).hexdigest()
    assert (Path(settings.update_upload_dir) / stored.id).read_bytes() == data
    assert list(Path(settings.update_upload_dir).iterdir()) == [Path(settings.update_upload_dir) / stored.id]
    ttl = stored.expires_at - stored.created_at
    assert timedelta(hours=23) < ttl <= timedelta(hours=24, minutes=1)


async def test_oversized_upload_is_refused_and_leaves_nothing(session, settings):
    from api.services.upload_service import UploadError
    user = await add_user(session)
    await set_config(session, update_upload_max_mb=1)

    with pytest.raises(UploadError) as exc:
        await upload(session, user, settings, b"x" * (1024 * 1024 + 1))

    assert exc.value.status_code == 413
    assert list(Path(settings.update_upload_dir).iterdir()) == []
    assert (await session.execute(select(UpdateUpload))).first() is None


async def test_upload_can_feed_one_operation_only(session, db_manager, settings):
    from api.services.upload_service import UploadError, attach_uploads, release_operation_uploads
    user = await add_user(session)
    stored = await upload(session, user, settings)
    ops = [Operation(user_id=user.id, type=OperationType.UPDATE, source_path="B:/C", status=OperationStatus.PENDING)
           for _ in range(2)]
    session.add_all(ops)
    await session.commit()

    await attach_uploads([stored.id], ops[0].id, session, settings)
    with pytest.raises(UploadError, match="used or removed concurrently"):
        await attach_uploads([stored.id], ops[1].id, session, settings)

    await release_operation_uploads(ops[0].id, session, settings)
    released = await row(db_manager, stored.id)
    assert released.deleted_at is not None and released.operation_id == ops[0].id
    assert not (Path(settings.update_upload_dir) / stored.id).exists()


async def test_only_the_owner_can_discard_an_unused_upload(session, db_manager, settings):
    from api.services.upload_service import UploadError, attach_uploads, delete_pending_upload
    alice, bob = await add_user(session, "alice"), await add_user(session, "bob")
    mine, used = await upload(session, alice, settings), await upload(session, alice, settings)
    op = Operation(user_id=alice.id, type=OperationType.UPDATE, source_path="B:/C", status=OperationStatus.PENDING)
    session.add(op)
    await session.commit()
    await attach_uploads([used.id], op.id, session, settings)

    with pytest.raises(UploadError) as exc:
        await delete_pending_upload(mine.id, bob, session, settings)
    assert exc.value.status_code == 404
    with pytest.raises(UploadError) as exc:
        await delete_pending_upload(used.id, alice, session, settings)
    assert exc.value.status_code == 409

    await delete_pending_upload(mine.id, alice, session, settings)
    assert (await row(db_manager, mine.id)).deleted_at is not None
    assert not (Path(settings.update_upload_dir) / mine.id).exists()


# ---------------------------------------------------------------------------
# Garbage collection
# ---------------------------------------------------------------------------

async def test_garbage_collection(session, db_manager, settings):
    from api.services.upload_service import collect_garbage
    user = await add_user(session)
    now = datetime.now(timezone.utc)

    finished = Operation(user_id=user.id, type=OperationType.UPDATE, source_path="B:/C", status=OperationStatus.FAILED)
    running = Operation(user_id=user.id, type=OperationType.UPDATE, source_path="B:/C", status=OperationStatus.IN_PROGRESS)
    stuck = Operation(user_id=user.id, type=OperationType.UPDATE, source_path="B:/C", status=OperationStatus.IN_PROGRESS)
    session.add_all([finished, running, stuck])
    await session.commit()

    uploads = {name: await upload(session, user, settings) for name in
               ("expired_unused", "fresh_unused", "finished_op", "running_op", "stuck_op")}
    uploads["expired_unused"].expires_at = now - timedelta(minutes=1)
    uploads["finished_op"].operation_id = finished.id
    uploads["running_op"].operation_id = running.id
    uploads["stuck_op"].operation_id = stuck.id
    uploads["stuck_op"].expires_at = now - timedelta(minutes=1)
    await session.commit()

    upload_dir = Path(settings.update_upload_dir)
    old_stray = upload_dir / ("f" * 32)
    old_part = upload_dir / ("e" * 32 + ".part")
    young_part = upload_dir / ("d" * 32 + ".part")
    for f in (old_stray, old_part, young_part):
        f.write_bytes(b"x")
    two_hours_ago = time.time() - 7200
    os.utime(old_stray, (two_hours_ago, two_hours_ago))
    os.utime(old_part, (two_hours_ago, two_hours_ago))

    removed = await collect_garbage(session, settings)

    assert removed == 3
    for name, gone in [("expired_unused", True), ("fresh_unused", False), ("finished_op", True),
                       ("running_op", False), ("stuck_op", True)]:
        assert ((await row(db_manager, uploads[name].id)).deleted_at is not None) is gone, name
        assert (upload_dir / uploads[name].id).exists() is not gone, name
    assert not old_stray.exists() and not old_part.exists()
    assert young_part.exists()

    # A second run (e.g. another API process) finds nothing more to do
    assert await collect_garbage(session, settings) == 0


# ---------------------------------------------------------------------------
# Worker download link
# ---------------------------------------------------------------------------

async def test_worker_download_link(session, db_manager, settings, monkeypatch):
    from fastapi.responses import FileResponse
    from urllib.parse import parse_qs, urlparse
    from api.routes.worker import download_upload
    from api.services import upload_service
    from api.services.upload_service import make_download_path

    user = await add_user(session)
    await add_worker(session)
    stored = await upload(session, user, settings)

    url = urlparse(make_download_path(settings, stored.id, HOSTNAME))
    q = parse_qs(url.query)
    expires, token = int(q["expires"][0]), q["token"][0]

    response = await download_upload(HOSTNAME, stored.id, session, settings, expires=expires, token=token)
    assert isinstance(response, FileResponse)

    for worker, exp, tok in [("OTHER-HOST", expires, token), (HOSTNAME, expires + 1, token)]:
        with pytest.raises(HTTPException) as exc:
            await download_upload(worker, stored.id, session, settings, expires=exp, token=tok)
        assert exc.value.status_code == 403

    monkeypatch.setattr(upload_service.time, "time", lambda: expires + 1)
    with pytest.raises(HTTPException) as exc:
        await download_upload(HOSTNAME, stored.id, session, settings, expires=expires, token=token)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# End to end: UPDATE endpoint -> worker -> history -> PIM
# ---------------------------------------------------------------------------

class PimServer:
    """Records every request PIM would receive."""

    def __init__(self):
        received = self.received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                received.append({"path": self.path, "token": self.headers.get("X-API-TOKEN"),
                                 "body": json.loads(body)})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    async def wait_for(self, count, timeout=10):
        deadline = time.monotonic() + timeout
        while len(self.received) < count and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        return self.received


@pytest.fixture
def pim():
    server = PimServer()
    yield server
    server.server.shutdown()


CATALOG_FILES = {
    "B:/CAT/a.jpg": b"old-a",
    "B:/CAT/b.jpg": b"old-b",
    "B:/CAT/c.jpg": b"old-c",
    "A:/incoming/new-b.jpg": b"new-b",
}


@pytest.fixture
async def update_setup(session, settings, pim, monkeypatch):
    """A pushed catalog B:/CAT, PIM pointed at the mock, the fake worker wired in."""
    import api.app as app_module
    from tests.update_fakes import FakeWorkerService

    user = await add_user(session)
    worker = await add_worker(session)
    push = Operation(user_id=user.id, type=OperationType.PUSH, source_path="A:/CAT", dest_path="B:/CAT",
                     original_path="A:/CAT", status=OperationStatus.COMPLETED)
    session.add(push)
    await session.commit()
    await set_config(
        session,
        pim_enabled="true", pim_base_url=pim.url, pim_endpoint="/api/v1/image_catalog/ftp_event",
        pim_api_token="pim-token", push_validation_min_files="2",
        # a.jpg/b.jpg: the PIM file name rule is covered by test_pim_delivery_and_sync.py
        push_validation_file_names="false",
        # Without {tg_id}: tgId resolution is covered by test_pim_delivery_and_sync.py
        pim_payload_template='{"files": {files}, "imageCatalog": "{catalog_name}", "eventType": "{event_type}"}',
    )

    fake = FakeWorkerService(CATALOG_FILES, settings)
    monkeypatch.setattr(app_module, "WorkerService", lambda _settings: fake)
    return {"user": user, "worker": worker, "push": push, "fake": fake}


async def call_update(session, settings, setup, actions):
    from api.app import update_operation
    from api.schemas import FileUpdateRequest
    request = FileUpdateRequest(catalog_path="B:/CAT", worker_id=setup["worker"].id,
                                push_operation_id=setup["push"].id, actions=actions)
    return await update_operation(request, fake_request(), setup["user"], session, settings)


async def test_update_replace_add_reaches_pim_history_and_pull(session, db_manager, settings, pim, update_setup):
    from api.app import get_operation_details, get_operations_history, pull_operation
    from api.schemas import FilePullRequest
    setup = update_setup
    stored = await upload(session, setup["user"], settings, b"uploaded-a", name="replacement.jpg")

    result = await call_update(session, settings, setup, [
        {"action": "replace", "source": "a.jpg", "upload_id": stored.id},
        {"action": "replace", "source": "b.jpg", "from_path": "A:/incoming/new-b.jpg", "remove_source": True},
        {"action": "add", "dest": "d.jpg", "from_path": "A:/incoming/new-b.jpg"},
    ])

    assert result.status == OperationStatus.COMPLETED
    assert setup["fake"].files == {
        "B:/CAT/a.jpg": b"uploaded-a", "B:/CAT/b.jpg": b"new-b",
        "B:/CAT/c.jpg": b"old-c", "B:/CAT/d.jpg": b"new-b",
    }

    # The history record says exactly what happened and who did it
    actions = result.params_json["actions"]
    assert result.user_name == "alice" and result.params_json["username"] == "alice"
    assert result.params_json["push_operation_id"] == setup["push"].id
    assert actions[0]["upload"] == {"filename": "replacement.jpg", "size_bytes": 10,
                                    "sha256": hashlib.sha256(b"uploaded-a").hexdigest()}
    assert actions[1]["source_removed"] is True

    # The uploaded bytes are gone once the UPDATE finished; the record stays
    assert (await row(db_manager, stored.id)).deleted_at is not None
    assert list(Path(settings.update_upload_dir).iterdir()) == []

    # PIM got an "updated" event with the resulting file list
    received = await pim.wait_for(1)
    assert len(received) == 1
    assert received[0]["token"] == "pim-token"
    assert received[0]["path"] == "/api/v1/image_catalog/ftp_event"
    assert received[0]["body"] == {"files": ["a.jpg", "b.jpg", "c.jpg", "d.jpg"],
                                   "imageCatalog": "CAT", "eventType": "updated"}

    # History: the PUSH references the UPDATE, details list who/what/when
    history = await get_operations_history(setup["user"], session)
    push_row = next(op for op in history if op.id == setup["push"].id)
    assert push_row.update_operation_ids == [result.id]
    details = await get_operation_details(setup["push"].id, setup["user"], session)
    assert [u.id for u in details.updates] == [result.id]
    assert details.updates[0].user_name == "alice"

    # PULL records which UPDATEs the pulled catalog contained, and signals PIM too
    pulled = await pull_operation(FilePullRequest(operation_id=setup["push"].id, worker_id=setup["worker"].id),
                                  fake_request(), setup["user"], session, settings)
    assert pulled.status == OperationStatus.COMPLETED
    assert pulled.params_json["update_operation_ids"] == [result.id]
    assert setup["fake"].files["A:/CAT/a.jpg"] == b"uploaded-a"  # the updated version came back
    received = await pim.wait_for(2)
    assert received[1]["body"]["eventType"] == "deleted"
    details = await get_operation_details(result.id, setup["user"], session)
    assert details.push.id == setup["push"].id and details.pull.id == pulled.id


async def test_rejected_upload_content_fails_cleanly(session, db_manager, settings, pim, update_setup):
    setup = update_setup
    await set_config(session, push_validation_verify_content="true")
    stored = await upload(session, setup["user"], settings, b"FAKE not an image", name="x.jpg")

    with pytest.raises(HTTPException) as exc:
        await call_update(session, settings, setup, [{"action": "replace", "source": "a.jpg", "upload_id": stored.id}])

    assert exc.value.status_code == 422
    content = exc.value.detail["content"]
    assert content["reason"] == "contentValidation.stagedTypeMismatch"
    assert [f["name"] for f in content["invalid_files"]] == ["a.jpg"]
    assert setup["fake"].files == CATALOG_FILES
    operation = (await session.execute(select(Operation).where(Operation.id == content["operation_id"]))).scalar_one()
    await session.refresh(operation)
    assert operation.status == OperationStatus.FAILED
    assert (await row(db_manager, stored.id)).deleted_at is not None
    await asyncio.sleep(0.5)
    assert pim.received == []  # a failed UPDATE changes nothing, so PIM hears nothing


async def test_update_refuses_a_pulled_catalog_and_foreign_uploads(session, settings, update_setup):
    setup = update_setup
    bob = await add_user(session, "bob")
    foreign = await upload(session, bob, settings)

    with pytest.raises(HTTPException) as exc:
        await call_update(session, settings, setup, [{"action": "replace", "source": "a.jpg", "upload_id": foreign.id}])
    assert exc.value.status_code == 400 and "not found or expired" in exc.value.detail

    session.add(Operation(user_id=setup["user"].id, type=OperationType.PULL, source_path="B:/CAT",
                          rollback_operation_id=setup["push"].id, status=OperationStatus.COMPLETED))
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await call_update(session, settings, setup, [{"action": "delete", "source": "c.jpg"}])
    assert exc.value.status_code == 400 and "already been pulled" in exc.value.detail
