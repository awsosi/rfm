"""
PUSH with ``refuse_existing`` (set by RFM Tray) must not touch a catalog that
is already published: the worker's copy merges into an existing B:/<name>,
so a repeated push would silently change the published catalog instead of
going through UPDATE.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.app as app_module
from api.config import get_settings
from api.schemas import FilePushRequest
from api.services.worker_service import WorkerService

SOURCE = "A:/DO KATALOGU/Ewa/TORBA HB0788 FA0542-910 SILVER"


@pytest.fixture
def worker(monkeypatch):
    listed = []

    async def get_worker_by_id(worker_id, db):
        return SimpleNamespace(id=worker_id)

    async def list_directory(self, worker, path, db, offset=0, limit=1000):
        listed.append(path)
        return SimpleNamespace(status="success" if path in published else "error")

    published = set()
    monkeypatch.setattr(app_module, "get_worker_by_id", get_worker_by_id)
    monkeypatch.setattr(WorkerService, "list_directory", list_directory)
    return SimpleNamespace(published=published, listed=listed)


async def push(refuse_existing):
    return await app_module.push_operation(
        FilePushRequest(source_path=SOURCE, worker_id=1, refuse_existing=refuse_existing),
        request=None, current_user=SimpleNamespace(username="ewa"), db=None, settings=get_settings(),
    )


async def test_published_catalog_is_refused_before_anything_runs(worker, monkeypatch):
    async def preflight(*args, **kwargs):
        raise AssertionError("no validation or copy for a refused push")

    monkeypatch.setattr(app_module, "run_catalog_preflight", preflight)
    worker.published.add("B:/TORBA HB0788 FA0542-910 SILVER")

    with pytest.raises(HTTPException) as exc:
        await push(refuse_existing=True)

    assert exc.value.status_code == 409
    assert exc.value.detail == {"error": "catalog_exists", "catalog_path": "B:/TORBA HB0788 FA0542-910 SILVER"}


async def test_new_catalog_goes_on_to_validation(worker, monkeypatch):
    class Reached(Exception):
        pass

    async def preflight(*args, **kwargs):
        raise Reached

    monkeypatch.setattr(app_module, "run_catalog_preflight", preflight)

    with pytest.raises(HTTPException) as exc:
        await push(refuse_existing=True)
    # The endpoint turns unexpected errors into 500; reaching preflight is the point
    assert exc.value.status_code == 500
    assert worker.listed == ["B:/TORBA HB0788 FA0542-910 SILVER"]


async def test_webui_push_is_unchanged(worker, monkeypatch):
    async def preflight(*args, **kwargs):
        raise RuntimeError("stop")

    monkeypatch.setattr(app_module, "run_catalog_preflight", preflight)
    worker.published.add("B:/TORBA HB0788 FA0542-910 SILVER")

    with pytest.raises(HTTPException):
        await push(refuse_existing=False)
    assert worker.listed == []
