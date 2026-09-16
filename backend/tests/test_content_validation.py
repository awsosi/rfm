"""
Unit tests for the directory content validation service.

Focus: the shape of the ``validate_dir`` payload as it reaches
``validate_directory_content``.

The worker returns its full result dictionary on
``CommandResponse.error_details``. That payload is then wrapped twice on the
way in:

    worker            CommandResponse.error_details = payload
    api/routes/worker.py      response_dict["error_details"] = payload
    api/services/worker_service.py
                      WorkerCommandResponse.error_details = response_dict

so the service receives ``{"file_count": .., "total_size_bytes": ..,
"error_details": {...the real payload...}}``. Reading ``files``/``image_count``
straight off that wrapper silently yields 0 images and 0 files, which surfaces
in the UI as "0 of 2 required image files - 0 files in total" for a catalog
that is actually fine.

These tests pin both the nested shape (what the server produces today) and the
flat shape (should that seam ever be flattened).
"""

import pytest

from api.services.content_validation_service import validate_directory_content


# The payload a worker actually produced for a catalog holding 4 genuine
# images, 1 non-image, and 2 files whose bytes contradict their extension.
WORKER_PAYLOAD = {
    "path": "A:/TEST CATALOG",
    "files": [
        "fake.jpg",
        "mismatch.png",
        "notes.txt",
        "real.jpg",
        "real.png",
        "real.webp",
        "scan.tiff",
    ],
    "total_files": 7,
    "image_count": 4,
    "non_image_files": ["notes.txt"],
    "invalid_files": [
        {
            "name": "mismatch.png",
            "extension": "png",
            "detected": "jpeg",
            "reason": "extension_mismatch",
        },
        {
            "name": "fake.jpg",
            "extension": "jpg",
            "detected": "unknown",
            "reason": "not_an_image",
        },
    ],
    "subdirectory_count": 1,
    "total_size_bytes": 683,
}


def nested_payload():
    """The shape produced by worker.py + worker_service.py today."""
    return {
        "file_count": WORKER_PAYLOAD["total_files"],
        "total_size_bytes": WORKER_PAYLOAD["total_size_bytes"],
        "error_details": dict(WORKER_PAYLOAD),
    }


class _FakeResponse:
    def __init__(self, error_details):
        self.status = "success"
        self.message = "Directory validation completed"
        self.error_details = error_details


class _FakeWorkerService:
    def __init__(self, error_details):
        self._error_details = error_details
        self.sent_command = None

    async def send_command(self, worker, command, db):
        self.sent_command = command
        return _FakeResponse(self._error_details)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return list(self._rows)


class _FakeDb:
    """Returns no Config rows, so the service uses its documented defaults
    (min 2 images, content verification on)."""

    async def execute(self, stmt):
        return _FakeResult([])


async def _validate(error_details, path="A:/TEST CATALOG"):
    return await validate_directory_content(
        worker=object(),
        path=path,
        worker_service=_FakeWorkerService(error_details),
        db=_FakeDb(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_details, shape",
    [
        (nested_payload(), "nested"),
        (dict(WORKER_PAYLOAD), "flat"),
    ],
)
async def test_reads_worker_payload_in_either_shape(error_details, shape):
    """The counts must survive the wrapping worker.py applies."""
    result = await _validate(error_details)

    assert result.total_files == 7, f"{shape}: lost the file count"
    assert result.image_count == 4, f"{shape}: lost the image count"
    assert len(result.files) == 7, f"{shape}: lost the file list PIM needs"
    assert result.non_image_files == ["notes.txt"]
    assert len(result.invalid_files) == 2
    assert result.min_required == 2


@pytest.mark.asyncio
async def test_nested_payload_is_not_reported_as_empty():
    """Regression: the wrapper used to read as 0 images / 0 files, which
    rejected a perfectly valid catalog with 'at least 2 are required'."""
    result = await _validate(nested_payload())

    assert result.reason != "contentValidation.tooFewImages"
    assert result.image_count >= result.min_required


@pytest.mark.asyncio
async def test_mismatched_files_still_rejected():
    """4 images clears the minimum, but the 2 contradicting files must still
    fail the catalog rather than pass silently."""
    result = await _validate(nested_payload())

    assert result.valid is False
    assert [f["name"] for f in result.invalid_files] == ["mismatch.png", "fake.jpg"]


@pytest.mark.asyncio
async def test_genuinely_empty_directory_still_fails():
    """The unwrap must not turn a real empty result into a pass."""
    result = await _validate({}, path="A:/EMPTY")

    assert result.total_files == 0
    assert result.image_count == 0
    assert result.valid is False
    assert result.reason == "contentValidation.tooFewImages"


@pytest.mark.asyncio
async def test_command_sent_matches_the_worker_contract():
    """The worker dispatches on this exact command name and params."""
    worker_service = _FakeWorkerService(nested_payload())
    await validate_directory_content(
        worker=object(),
        path="A:/TEST CATALOG",
        worker_service=worker_service,
        db=_FakeDb(),
    )

    sent = worker_service.sent_command
    assert sent.command == "validate_dir"
    assert sent.source_path == "A:/TEST CATALOG"
    assert sent.params["verify_content"] is True
    assert "jpg" in sent.params["allowed_extensions"]
