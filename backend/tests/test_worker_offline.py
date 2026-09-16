"""
Tests for automatic worker OFFLINE detection and reactivation.

A worker that stops checking in is marked OFFLINE by the health check, and
returns to ACTIVE by itself on its next heartbeat, poll or registration.
SUSPENDED is an administrator decision and PENDING awaits approval; neither
is ever changed automatically.

These tests need a real PostgreSQL (native enum, UPDATE ... RETURNING and
row-level concurrency are what is under test). Point TEST_DATABASE_URL at a
disposable database: the schema is built with ``alembic upgrade head`` and
every test truncates the worker, command, audit and config tables.

    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/rfm_test pytest tests/test_worker_offline.py
"""

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, update
from starlette.requests import Request

from database import DatabaseManager
from models import AuditLog, Config, ConfigType, Worker, WorkerStatus

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set (needs a disposable PostgreSQL database)",
)

HOSTNAME = "TEST-WORKER-01"
CLIENT_IP = "10.20.30.40"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def migrated_database():
    """Build the schema from the real migrations, as a deployment does."""
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
        await s.execute(text(
            "TRUNCATE workers, worker_commands, audit_logs, config RESTART IDENTITY CASCADE"
        ))
    yield DatabaseManager
    await DatabaseManager.close()


@pytest.fixture
async def session(db_manager):
    async with db_manager.get_session_factory()() as s:
        yield s


def fake_request() -> Request:
    return Request({"type": "http", "headers": [], "client": (CLIENT_IP, 50000)})


async def add_worker(session, status: WorkerStatus, heartbeat_age_seconds: int = 0,
                     hostname: str = HOSTNAME) -> Worker:
    worker = Worker(
        name=hostname,
        hostname=hostname,
        public_key="test-key",
        status=status,
        last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=heartbeat_age_seconds),
    )
    session.add(worker)
    await session.commit()
    await session.refresh(worker)
    return worker


async def set_heartbeat_timeout(session, value: str) -> None:
    session.add(Config(key="worker_heartbeat_timeout", value=value, type=ConfigType.INT))
    await session.commit()


async def db_status(db_manager, worker_id: int) -> WorkerStatus:
    async with db_manager.session() as s:
        return (await s.execute(select(Worker.status).where(Worker.id == worker_id))).scalar_one()


async def audit_entries(db_manager, action: str) -> list[AuditLog]:
    async with db_manager.session() as s:
        stmt = select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)
        return list((await s.execute(stmt)).scalars().all())


async def check_in(trigger: str, session):
    """Perform a worker check-in through the real endpoint function."""
    if trigger == "poll":
        from api.routes.worker import poll_commands
        return await poll_commands(HOSTNAME, fake_request(), session, MagicMock(), timeout=1)
    if trigger == "heartbeat":
        from api.routes.worker import submit_heartbeat
        return await submit_heartbeat(HOSTNAME, fake_request(), session)
    if trigger == "register":
        from api.app import register_worker
        from api.schemas import WorkerRegister
        data = WorkerRegister(name=HOSTNAME, hostname=HOSTNAME, public_key="test-key", version="1.0")
        return await register_worker(data, fake_request(), session)
    raise ValueError(trigger)


# ---------------------------------------------------------------------------
# Health check: ACTIVE -> OFFLINE
# ---------------------------------------------------------------------------

async def run_health_check_once(monkeypatch):
    """Run exactly one iteration of the real health check loop."""
    import api.background_tasks as bt

    manager = bt.BackgroundTaskManager(MagicMock())
    manager._running = True
    calls = 0

    async def fake_sleep(_seconds):
        nonlocal calls
        calls += 1
        if calls > 1:
            manager._running = False

    monkeypatch.setattr(bt.asyncio, "sleep", fake_sleep)
    await manager._worker_health_check_loop()


async def test_health_check_marks_stale_active_worker_offline(db_manager, session, monkeypatch):
    # 150s differs from both the old hardcoded 300s and the 180s fallback, so
    # the outcome proves the timeout is read from the config table.
    await set_heartbeat_timeout(session, "150")
    stale = await add_worker(session, WorkerStatus.ACTIVE, 160, "STALE")
    fresh = await add_worker(session, WorkerStatus.ACTIVE, 120, "FRESH")
    suspended = await add_worker(session, WorkerStatus.SUSPENDED, 3600, "SUSPENDED")
    pending = await add_worker(session, WorkerStatus.PENDING, 3600, "PENDING")

    await run_health_check_once(monkeypatch)

    assert await db_status(db_manager, stale.id) == WorkerStatus.OFFLINE
    assert await db_status(db_manager, fresh.id) == WorkerStatus.ACTIVE
    assert await db_status(db_manager, suspended.id) == WorkerStatus.SUSPENDED
    assert await db_status(db_manager, pending.id) == WorkerStatus.PENDING

    entries = await audit_entries(db_manager, "worker_offline")
    assert len(entries) == 1
    assert entries[0].user_id is None
    assert entries[0].details_json["worker_id"] == stale.id
    assert entries[0].details_json["heartbeat_timeout"] == 150


@pytest.mark.parametrize("value", [None, "", "abc", "0", "-5"])
async def test_heartbeat_timeout_falls_back_when_config_invalid(session, value):
    from api.services.worker_service import (
        DEFAULT_WORKER_HEARTBEAT_TIMEOUT,
        get_worker_heartbeat_timeout,
    )

    if value is not None:
        await set_heartbeat_timeout(session, value)
    assert await get_worker_heartbeat_timeout(session) == DEFAULT_WORKER_HEARTBEAT_TIMEOUT


async def test_concurrent_health_checks_report_each_transition_once(db_manager, session):
    """uvicorn runs several processes, each with its own health check loop."""
    from api.services.worker_service import mark_stale_workers_offline

    worker = await add_worker(session, WorkerStatus.ACTIVE, 600)
    factory = db_manager.get_session_factory()

    async def one_check():
        async with factory() as s:
            return await mark_stale_workers_offline(s, 180)

    results = await asyncio.gather(*(one_check() for _ in range(4)))

    assert sorted(len(r) for r in results) == [0, 0, 0, 1]
    assert await db_status(db_manager, worker.id) == WorkerStatus.OFFLINE


# ---------------------------------------------------------------------------
# Automatic reactivation: OFFLINE -> ACTIVE
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("trigger", ["poll", "heartbeat", "register"])
async def test_offline_worker_is_reactivated_on_check_in(db_manager, session, trigger):
    worker = await add_worker(session, WorkerStatus.OFFLINE, 3600)

    response = await check_in(trigger, session)

    assert await db_status(db_manager, worker.id) == WorkerStatus.ACTIVE
    if trigger == "poll":
        assert response.command_id is None  # served normally, not 403
    if trigger == "register":
        assert response.status == WorkerStatus.ACTIVE

    async with db_manager.session() as s:
        heartbeat = (await s.execute(select(Worker.last_heartbeat).where(Worker.id == worker.id))).scalar_one()
    assert datetime.now(timezone.utc) - heartbeat < timedelta(seconds=30)

    entries = await audit_entries(db_manager, "worker_auto_reactivate")
    assert len(entries) == 1
    assert entries[0].user_id is None
    assert entries[0].ip_address == CLIENT_IP
    assert entries[0].details_json["trigger"] == trigger
    assert entries[0].details_json["previous_status"] == "OFFLINE"


@pytest.mark.parametrize("trigger", ["poll", "heartbeat", "register"])
@pytest.mark.parametrize("status", [WorkerStatus.SUSPENDED, WorkerStatus.PENDING])
async def test_suspended_and_pending_workers_are_never_reactivated(db_manager, session, trigger, status):
    worker = await add_worker(session, status, 3600)

    if trigger == "poll":
        with pytest.raises(HTTPException) as exc_info:
            await check_in(trigger, session)
        assert exc_info.value.status_code == 403
        # The worker parses this message with `status:\s*([A-Za-z_]+)`
        assert exc_info.value.detail == f"Worker is not active (status: {status.value})"
    else:
        await check_in(trigger, session)

    assert await db_status(db_manager, worker.id) == status
    assert await audit_entries(db_manager, "worker_auto_reactivate") == []


# ---------------------------------------------------------------------------
# Conditional update guard
# ---------------------------------------------------------------------------

async def test_reactivation_never_overwrites_concurrent_admin_suspension(db_manager, session):
    from api.services.worker_service import reactivate_offline_worker

    worker = await add_worker(session, WorkerStatus.OFFLINE, 3600)
    assert worker.status == WorkerStatus.OFFLINE  # what the check-in request loaded

    # An administrator suspends the worker in another session after the
    # check-in loaded it but before the check-in reactivates it.
    async with db_manager.session() as admin_session:
        await admin_session.execute(
            update(Worker).where(Worker.id == worker.id).values(status=WorkerStatus.SUSPENDED)
        )

    assert await reactivate_offline_worker(worker, session, "heartbeat", CLIENT_IP) is False
    assert worker.status == WorkerStatus.SUSPENDED  # refreshed from the DB
    assert await db_status(db_manager, worker.id) == WorkerStatus.SUSPENDED
    assert await audit_entries(db_manager, "worker_auto_reactivate") == []


async def test_concurrent_check_ins_reactivate_and_audit_once(db_manager, session):
    """Heartbeat and poll arriving together must produce a single audit entry."""
    from api.services.worker_service import reactivate_offline_worker

    worker = await add_worker(session, WorkerStatus.OFFLINE, 3600)
    factory = db_manager.get_session_factory()

    async def one_check_in(trigger):
        async with factory() as s:
            w = (await s.execute(select(Worker).where(Worker.id == worker.id))).scalar_one()
            return await reactivate_offline_worker(w, s, trigger, CLIENT_IP)

    results = await asyncio.gather(*(one_check_in(t) for t in ("poll", "heartbeat", "register")))

    assert sorted(results) == [False, False, True]
    assert await db_status(db_manager, worker.id) == WorkerStatus.ACTIVE
    assert len(await audit_entries(db_manager, "worker_auto_reactivate")) == 1
