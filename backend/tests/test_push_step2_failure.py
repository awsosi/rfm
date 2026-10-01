"""
A PUSH whose Step 2 (delete or archive the source) fails must never delete the
only complete copy of the catalog.

Prod, 2026-09-30, operation 1607 (SKARPETY JV7410 0-WHITE): deleting the
source stopped with "The directory is not empty." after the photos were gone,
and the rollback then deleted the copy in the catalog. Prod, 2026-10-01: two
PUSHes of one folder ran at once in different API processes; the one that
found the source already moved rolled back the other one's catalog.
"""

import asyncio
from types import SimpleNamespace

import fakeredis
import pytest

import api.services.user_events as user_events
from api.config import get_settings
from api.services.operation_service import OperationError, OperationService, path_lock
from api.services.worker_service import WorkerCommunicationError, WorkerTimeoutError

SOURCE = "A:/DO KATALOGU/Lena/SKARPETY JV7410 0-WHITE"
DEST = "B:/SKARPETY JV7410 0-WHITE"


def listing(*names):
    """A worker "list" response, nested the way the worker route delivers it."""
    items = [{"name": name, "type": "file"} for name in names]
    return SimpleNamespace(status="success", error_details={"error_details": {"items": items}})


class FakeWorker:
    """Copies 3 files, then fails to delete the source with ``delete_error``."""

    def __init__(self, delete_error, left_in_source):
        self.delete_error = delete_error
        self.left_in_source = left_in_source
        self.deleted = []

    async def send_command(self, worker, command, db, operation_id=None):
        if command.command == "copy":
            return SimpleNamespace(status="success", file_count=3, total_size_bytes=300)
        if command.command == "list" and command.params.get("recursive"):
            if isinstance(self.left_in_source, Exception):
                raise self.left_in_source
            return listing(*self.left_in_source)
        if command.command == "list":
            return listing("1.jpg", "2.jpg", "3.jpg")  # the check before Step 1
        raise AssertionError(f"unexpected command {command.command}")

    async def delete_file(self, worker, path, db, recursive=False):
        self.deleted.append(path)
        if path == SOURCE:
            raise self.delete_error
        return SimpleNamespace(status="success")


class FakeDb:
    async def execute(self, stmt):
        return SimpleNamespace(scalars=lambda: [])  # no config rows: defaults


async def push(fake):
    service = OperationService(get_settings(), fake)

    async def update_worker_status(*args, **kwargs):
        pass

    service._update_worker_status = update_worker_status
    operation = SimpleNamespace(id=1607, source_path=SOURCE, dest_path=DEST, archive_path=None)
    return await service._execute_push_operation(operation, SimpleNamespace(name="HV2012R2"), FakeDb())


not_empty = WorkerCommunicationError("Worker HV2012R2 command failed: Worker command failed: The directory is not empty.")


async def test_partly_deleted_source_keeps_the_catalog():
    # Only the junk the delete could not remove is left
    fake = FakeWorker(not_empty, left_in_source=["Thumbs.db", ".BridgeSort"])

    response = await push(fake)

    assert fake.deleted == [SOURCE]  # the catalog copy was not touched
    assert response.status == "success"
    assert "only partly removed" in response.message


async def test_vanished_source_keeps_the_catalog():
    gone = WorkerCommunicationError("Worker command failed: Directory not found: " + SOURCE)
    fake = FakeWorker(WorkerCommunicationError("Path not found"), left_in_source=gone)

    await push(fake)

    assert fake.deleted == [SOURCE]


async def test_timed_out_delete_keeps_the_catalog():
    # The worker may still be deleting: the source cannot be judged
    fake = FakeWorker(WorkerTimeoutError("timed out"), left_in_source=["1.jpg", "2.jpg", "3.jpg"])

    await push(fake)

    assert fake.deleted == [SOURCE]


async def test_untouched_source_is_rolled_back():
    in_use = WorkerCommunicationError("The process cannot access the file '1.jpg' because it is being used")
    fake = FakeWorker(in_use, left_in_source=["1.jpg", "2.jpg", "3.jpg", "Thumbs.db"])

    with pytest.raises(OperationError, match="rolled back"):
        await push(fake)

    assert fake.deleted == [SOURCE, DEST]


@pytest.fixture
def redis(monkeypatch):
    monkeypatch.setattr(user_events, "_redis", fakeredis.aioredis.FakeRedis(decode_responses=True))


async def test_path_lock_holds_a_folder_across_processes(redis):
    # Each API process has its own client; they meet only in Redis
    second_entered = asyncio.Event()

    async def second_push():
        async with path_lock(SOURCE.upper() + "/"):
            second_entered.set()

    async with path_lock(SOURCE):
        waiting = asyncio.create_task(second_push())
        await asyncio.sleep(0.5)
        assert not second_entered.is_set()

    await asyncio.wait_for(waiting, timeout=2)
    assert second_entered.is_set()
