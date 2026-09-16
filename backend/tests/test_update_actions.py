"""
UPDATE replace/add: action rules, post-update predictions and execution order.

No database needed. Execution runs the real ``OperationService`` against the
in-memory worker in ``update_fakes``; what is asserted is the state of the
(fake) shares afterwards - the catalog, the staging folder and Path A - for
success, rejected content and failures at each stage.
"""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.app import _check_update_targets
from api.services import content_validation_service as cvs
from api.services.content_validation_service import (
    UpdateActionError,
    invalid_files_after_actions,
    predict_files_after_actions,
    validate_update_actions,
)
from api.services.operation_service import (
    OperationError,
    OperationService,
    UpdateContentRejected,
)
from models import Operation, OperationType
from tests.update_fakes import FakeWorkerService

UPLOAD_ID = "a" * 32


# ---------------------------------------------------------------------------
# validate_update_actions
# ---------------------------------------------------------------------------

def test_replace_and_add_are_normalised():
    actions = validate_update_actions([
        {"action": "replace", "source": "a.jpg", "from_path": "A:\\new\\a.jpg", "remove_source": True},
        {"action": "add", "dest": "b.jpg", "upload_id": UPLOAD_ID.upper()},
    ])
    assert actions == [
        {"action": "replace", "source": "a.jpg", "from_path": "A:/new/a.jpg", "remove_source": True},
        {"action": "add", "dest": "b.jpg", "upload_id": UPLOAD_ID},
    ]


@pytest.mark.parametrize("action, message", [
    ({"action": "replace", "source": "a.jpg"}, "exactly one of from_path or upload_id"),
    ({"action": "replace", "source": "a.jpg", "from_path": "A:/x.jpg", "upload_id": UPLOAD_ID}, "exactly one"),
    ({"action": "add", "upload_id": UPLOAD_ID}, "dest must not be empty"),
    ({"action": "add", "dest": "b.jpg", "upload_id": "../../etc"}, "upload_id is malformed"),
    ({"action": "add", "dest": "b.jpg", "upload_id": UPLOAD_ID, "remove_source": True}, "only to Path A"),
    ({"action": "replace", "source": "a.jpg", "from_path": "B:/CAT/a.jpg"}, "must be a Path A file"),
    ({"action": "replace", "source": "a.jpg", "from_path": "A:/x/../../secret"}, "traverse outside"),
    ({"action": "replace", "source": "a.jpg", "from_path": "A:/"}, "must name a file"),
    ({"action": "replace", "source": "a.jpg", "from_path": "A:/x/C:/y"}, "another drive letter"),
    ({"action": "add", "dest": "../b.jpg", "upload_id": UPLOAD_ID}, "traverse outside"),
    ({"action": "rename", "source": "a.jpg", "dest": "b.jpg", "from_path": "A:/x.jpg"}, "does not take"),
])
def test_invalid_content_actions_are_refused(action, message):
    with pytest.raises(UpdateActionError, match=message):
        validate_update_actions([action])


def test_an_entry_can_be_touched_by_one_action_only():
    with pytest.raises(UpdateActionError, match="b.jpg is targeted by more than one action"):
        validate_update_actions([
            {"action": "rename", "source": "a.jpg", "dest": "b.jpg"},
            {"action": "add", "dest": "b.jpg", "upload_id": UPLOAD_ID},
        ])
    with pytest.raises(UpdateActionError, match="a.jpg is targeted"):
        validate_update_actions([
            {"action": "replace", "source": "a.jpg", "upload_id": UPLOAD_ID},
            {"action": "delete", "source": "a.jpg"},
        ])


# ---------------------------------------------------------------------------
# Predictions used by the content gate and PIM
# ---------------------------------------------------------------------------

def test_predicted_files_after_replace_add_rename_delete():
    actions = validate_update_actions([
        {"action": "replace", "source": "a.jpg", "upload_id": UPLOAD_ID},
        {"action": "add", "dest": "new.png", "from_path": "A:/n.png"},
        {"action": "add", "dest": "sub/nested.png", "from_path": "A:/m.png"},
        {"action": "rename", "source": "b.jpg", "dest": "b2.jpg"},
        {"action": "delete", "source": "c.jpg"},
    ])
    assert predict_files_after_actions(["a.jpg", "b.jpg", "c.jpg"], actions) == ["a.jpg", "new.png", "b2.jpg"]


def test_mismatch_findings_follow_their_files():
    invalid = [
        {"name": "deleted.png", "extension": "png", "detected": "jpeg"},
        {"name": "replaced.png", "extension": "png", "detected": "unknown"},
        {"name": "fixed.png", "extension": "png", "detected": "jpeg"},
        {"name": "still.png", "extension": "png", "detected": "jpeg"},
        {"name": "untouched.png", "extension": "png", "detected": "gif"},
    ]
    actions = validate_update_actions([
        {"action": "delete", "source": "deleted.png"},
        {"action": "replace", "source": "replaced.png", "upload_id": UPLOAD_ID},
        {"action": "rename", "source": "fixed.png", "dest": "fixed.jpg"},
        {"action": "rename", "source": "still.png", "dest": "still.gif"},
    ])
    result = invalid_files_after_actions(invalid, actions)
    assert [(f["name"], f["extension"]) for f in result] == [("still.gif", "gif"), ("untouched.png", "png")]


def test_replace_and_add_targets_are_checked_against_the_listing():
    files = ["a.jpg", "b.jpg"]
    _check_update_targets(validate_update_actions([
        {"action": "replace", "source": "a.jpg", "upload_id": UPLOAD_ID},
        {"action": "add", "dest": "c.jpg", "from_path": "A:/c.jpg"},
    ]), files)
    with pytest.raises(HTTPException, match="Cannot replace missing.jpg"):
        _check_update_targets(validate_update_actions(
            [{"action": "replace", "source": "missing.jpg", "upload_id": UPLOAD_ID}]), files)
    with pytest.raises(HTTPException, match="Cannot add b.jpg"):
        _check_update_targets(validate_update_actions(
            [{"action": "add", "dest": "b.jpg", "upload_id": UPLOAD_ID}]), files)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

CATALOG = {
    "B:/CAT/a.jpg": b"old-a",
    "B:/CAT/b.jpg": b"old-b",
    "B:/CAT/c.jpg": b"old-c",
    "A:/incoming/a.jpg": b"new-a",
    "A:/incoming/other.jpg": b"other",
}


@pytest.fixture
def settings(tmp_path):
    return SimpleNamespace(secret_key="test-secret", update_upload_dir=str(tmp_path))


@pytest.fixture(autouse=True)
def validation_config(monkeypatch):
    async def config(db):
        return {"push_validation_enabled": "true", "push_validation_verify_content": "true"}
    monkeypatch.setattr(cvs, "_get_validation_config", config)


def stored_upload(settings, data: bytes) -> dict:
    (Path(settings.update_upload_dir) / UPLOAD_ID).write_bytes(data)
    return {"filename": "from-browser.jpg", "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def make_service(settings, fake) -> OperationService:
    service = OperationService(settings, fake)

    async def no_status(*args, **kwargs):
        return None
    service._update_worker_status = no_status
    return service


def update_operation(actions) -> Operation:
    return Operation(
        id=7, type=OperationType.UPDATE, source_path="B:/CAT", dest_path="B:/CAT",
        archive_path=None, params_json={"actions": actions, "username": "alice"},
    )


WORKER = SimpleNamespace(name="TEST-WORKER", hostname="TEST-WORKER")


async def test_update_applies_every_kind_of_change(settings):
    upload = stored_upload(settings, b"uploaded-d")
    actions = validate_update_actions([
        {"action": "replace", "source": "a.jpg", "from_path": "A:/incoming/a.jpg", "remove_source": True},
        {"action": "add", "dest": "d.jpg", "upload_id": UPLOAD_ID},
        {"action": "rename", "source": "b.jpg", "dest": "b-renamed.jpg"},
        {"action": "delete", "source": "c.jpg"},
    ])
    actions[1]["upload"] = upload
    fake = FakeWorkerService(CATALOG, settings)
    operation = update_operation(actions)

    response = await make_service(settings, fake)._execute_update_operation(operation, WORKER, None)

    assert response.status == "success"
    assert fake.files == {
        "B:/CAT/a.jpg": b"new-a",
        "B:/CAT/b-renamed.jpg": b"old-b",
        "B:/CAT/d.jpg": b"uploaded-d",
        "A:/incoming/other.jpg": b"other",
    }
    # Per-action outcome is recorded for the history
    recorded = operation.params_json["actions"]
    assert recorded[0]["source_removed"] is True
    assert recorded[1]["upload"]["sha256"] == upload["sha256"]
    assert operation.params_json["warnings"] == []
    # Irreversible delete ran after every reversible step
    names = [c[0] for c in fake.commands]
    assert names.index("delete") > max(i for i, n in enumerate(names) if n == "move")


async def test_rejected_staged_content_leaves_catalog_untouched(settings):
    actions = validate_update_actions([
        {"action": "rename", "source": "b.jpg", "dest": "b2.jpg"},
        {"action": "replace", "source": "a.jpg", "from_path": "A:/incoming/fake.jpg"},
    ])
    fake = FakeWorkerService({**CATALOG, "A:/incoming/fake.jpg": b"FAKE text"}, settings)

    with pytest.raises(UpdateContentRejected) as rejected:
        await make_service(settings, fake)._execute_update_operation(update_operation(actions), WORKER, None)

    assert rejected.value.invalid_files[0]["name"] == "a.jpg"
    assert fake.files == {**CATALOG, "A:/incoming/fake.jpg": b"FAKE text"}


async def test_a_folder_picked_as_content_is_rejected(settings):
    actions = validate_update_actions([{"action": "replace", "source": "a.jpg", "from_path": "A:/incoming"}])
    fake = FakeWorkerService(CATALOG, settings)

    with pytest.raises(UpdateContentRejected) as rejected:
        await make_service(settings, fake)._execute_update_operation(update_operation(actions), WORKER, None)

    assert rejected.value.missing == ["a.jpg"]
    assert fake.files == CATALOG


async def test_failure_while_swapping_reverts_everything(settings):
    actions = validate_update_actions([
        {"action": "rename", "source": "b.jpg", "dest": "b2.jpg"},
        {"action": "replace", "source": "a.jpg", "from_path": "A:/incoming/a.jpg", "remove_source": True},
        # c.jpg exists, so moving the staged file into place fails
        {"action": "add", "dest": "c.jpg", "from_path": "A:/incoming/other.jpg"},
    ])
    fake = FakeWorkerService(CATALOG, settings)

    with pytest.raises(OperationError, match="adding c.jpg"):
        await make_service(settings, fake)._execute_update_operation(update_operation(actions), WORKER, None)

    assert fake.files == CATALOG


async def test_failed_delete_reverts_replacements(settings):
    actions = validate_update_actions([
        {"action": "replace", "source": "a.jpg", "from_path": "A:/incoming/a.jpg"},
        {"action": "delete", "source": "c.jpg"},
    ])
    fake = FakeWorkerService(CATALOG, settings, fail_on=lambda n, s, d: n == "delete" and s == "B:/CAT/c.jpg")

    with pytest.raises(Exception):
        await make_service(settings, fake)._execute_update_operation(update_operation(actions), WORKER, None)

    assert fake.files == CATALOG


async def test_worker_without_fetch_file_gets_a_clear_error(settings):
    upload = stored_upload(settings, b"uploaded")
    actions = validate_update_actions([{"action": "replace", "source": "a.jpg", "upload_id": UPLOAD_ID}])
    actions[0]["upload"] = upload
    fake = FakeWorkerService(CATALOG, settings, supports_fetch=False)

    with pytest.raises(OperationError, match="does not support uploaded files yet"):
        await make_service(settings, fake)._execute_update_operation(update_operation(actions), WORKER, None)

    assert fake.files == CATALOG


async def test_tampered_upload_is_refused_by_the_worker(settings):
    upload = stored_upload(settings, b"uploaded")
    upload["sha256"] = "0" * 64
    actions = validate_update_actions([{"action": "add", "dest": "d.jpg", "upload_id": UPLOAD_ID}])
    actions[0]["upload"] = upload
    fake = FakeWorkerService(CATALOG, settings)

    with pytest.raises(Exception, match="SHA-256"):
        await make_service(settings, fake)._execute_update_operation(update_operation(actions), WORKER, None)

    assert fake.files == CATALOG


async def test_cleanup_problems_become_warnings_not_failures(settings):
    actions = validate_update_actions([
        {"action": "replace", "source": "a.jpg", "from_path": "A:/incoming/a.jpg", "remove_source": True},
    ])
    fake = FakeWorkerService(
        CATALOG, settings,
        fail_on=lambda n, s, d: n == "delete" and (s.startswith("A:/") or ".rfm-update-" in s),
    )
    operation = update_operation(actions)

    response = await make_service(settings, fake)._execute_update_operation(operation, WORKER, None)

    assert response.status == "success"
    assert fake.files["B:/CAT/a.jpg"] == b"new-a"
    assert operation.params_json["actions"][0]["source_removed"] is False
    warnings = operation.params_json["warnings"]
    assert any("could not be removed from Path A" in w for w in warnings)
    assert any("Working folder" in w for w in warnings)
