"""
Directory Content Validation Service

Enforces the minimum-content rules before a catalog may be PUSHed or UPDATEd:

- at least ``push_validation_min_files`` image files (default 2)
- image files identified by extension AND, when
  ``push_validation_verify_content`` is on, by magic-byte sniffing on the
  worker, so a renamed .txt cannot pass as a .png

Anything that is not an image ("garbage") does not count toward the minimum
but is still reported, and is still included in the file list handed to PIM.

The listing happens once, on the worker, via the ``validate_dir`` command, and
its result feeds both this validation and the PIM ``files`` array.

Note: the worker's full response payload arrives in
``WorkerCommandResponse.error_details`` — that field doubles as the generic
data channel throughout this codebase (see ``list_directory`` in app.py).
"""

from dataclasses import dataclass, field
from typing import List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import WorkerRequest
from models import Config

_CONFIG_KEYS = [
    'push_validation_enabled',
    'push_validation_min_files',
    'push_validation_allowed_extensions',
    'push_validation_verify_content',
]

_DEFAULT_EXTENSIONS = "jpg,jpeg,png,gif,bmp,tif,tiff,webp"


@dataclass
class ContentValidationResult:
    """Outcome of a directory content validation attempt."""

    valid: bool
    path: str
    total_files: int = 0
    image_count: int = 0
    # Every top-level basename, images and garbage alike -> PIM files array
    files: List[str] = field(default_factory=list)
    non_image_files: List[str] = field(default_factory=list)
    # Files whose extension disagrees with their real content
    invalid_files: List[dict] = field(default_factory=list)
    min_required: int = 0
    allowed_extensions: List[str] = field(default_factory=list)
    # i18n key resolved by the frontend, never a user-facing English string
    reason: Optional[str] = None
    error_detail: Optional[str] = None
    skipped: bool = False

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "path": self.path,
            "total_files": self.total_files,
            "image_count": self.image_count,
            "files": self.files,
            "non_image_files": self.non_image_files,
            "invalid_files": self.invalid_files,
            "min_required": self.min_required,
            "allowed_extensions": self.allowed_extensions,
            "reason": self.reason,
            "error_detail": self.error_detail,
            "skipped": self.skipped,
        }


async def _get_validation_config(db: AsyncSession) -> dict:
    stmt = select(Config).where(Config.key.in_(_CONFIG_KEYS))
    result = await db.execute(stmt)
    return {c.key: c.value for c in result.scalars()}


def _truthy(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ('true', '1', 'yes')


async def validate_directory_content(
    worker,
    path: str,
    worker_service,
    db: AsyncSession,
) -> ContentValidationResult:
    """
    Validate the contents of ``path`` on ``worker``.

    Returns a result object; never raises for worker/transport problems. A
    worker that cannot be reached fails closed (valid=False) because we cannot
    prove the directory satisfies the rules.
    """
    config = await _get_validation_config(db)

    try:
        min_files = int(config.get('push_validation_min_files', '2'))
    except (TypeError, ValueError):
        min_files = 2

    ext_str = config.get('push_validation_allowed_extensions') or _DEFAULT_EXTENSIONS
    allowed_extensions = [
        e.strip().lower().lstrip('.') for e in ext_str.split(',') if e.strip()
    ]
    verify_content = _truthy(config.get('push_validation_verify_content'), default=True)

    if not _truthy(config.get('push_validation_enabled'), default=True):
        logger.debug("Directory content validation is disabled, skipping")
        return ContentValidationResult(
            valid=True,
            path=path,
            min_required=min_files,
            allowed_extensions=allowed_extensions,
            skipped=True,
        )

    command = WorkerRequest(
        command="validate_dir",
        source_path=path,
        params={
            "allowed_extensions": allowed_extensions,
            "verify_content": verify_content,
        },
    )

    try:
        response = await worker_service.send_command(worker, command, db)
    except Exception as exc:
        logger.error(
            f"Content validation could not reach worker for {path!r}: {exc}"
        )
        return ContentValidationResult(
            valid=False,
            path=path,
            min_required=min_files,
            allowed_extensions=allowed_extensions,
            reason="contentValidation.workerUnavailable",
            error_detail=str(exc),
        )

    if response.status != "success":
        return ContentValidationResult(
            valid=False,
            path=path,
            min_required=min_files,
            allowed_extensions=allowed_extensions,
            reason="contentValidation.listFailed",
            error_detail=response.message,
        )

    data = response.error_details or {}

    files = [str(f) for f in (data.get("files") or [])]
    non_image_files = [str(f) for f in (data.get("non_image_files") or [])]
    invalid_files = data.get("invalid_files") or []
    if not isinstance(invalid_files, list):
        invalid_files = []

    try:
        image_count = int(data.get("image_count", 0))
    except (TypeError, ValueError):
        image_count = 0
    try:
        total_files = int(data.get("total_files", len(files)))
    except (TypeError, ValueError):
        total_files = len(files)

    result = ContentValidationResult(
        valid=True,
        path=path,
        total_files=total_files,
        image_count=image_count,
        files=files,
        non_image_files=non_image_files,
        invalid_files=invalid_files,
        min_required=min_files,
        allowed_extensions=allowed_extensions,
    )

    if image_count < min_files:
        result.valid = False
        result.reason = "contentValidation.tooFewImages"
        logger.warning(
            f"Content validation failed for {path!r}: {image_count} image file(s), "
            f"{min_files} required (total files: {total_files}, "
            f"non-image: {len(non_image_files)}, mismatched: {len(invalid_files)})"
        )
        return result

    if invalid_files:
        # An extension/content mismatch is a hard failure: the file claims to be
        # an image but is not, so it must not be counted or silently shipped.
        result.valid = False
        result.reason = "contentValidation.typeMismatch"
        logger.warning(
            f"Content validation failed for {path!r}: "
            f"{len(invalid_files)} file(s) whose content does not match their extension: "
            f"{[f.get('name') for f in invalid_files][:10]}"
        )
        return result

    logger.info(
        f"Content validation passed for {path!r}: {image_count} image(s), "
        f"{total_files} file(s) total, {len(non_image_files)} non-image"
    )
    return result


# ----------------------------------------------------------------------
# UPDATE action validation
# ----------------------------------------------------------------------

_ALLOWED_ACTIONS = ("move", "rename", "delete")


class UpdateActionError(ValueError):
    """Raised when an UPDATE action list is malformed or unsafe."""


def _safe_relative(value: str, field_name: str) -> str:
    """
    Normalise a catalog-relative path and refuse anything that could escape it.

    Rejects absolute paths, drive-prefixed worker paths (A:/B:/C:) and any
    component that walks upward. This is the boundary that keeps an UPDATE
    confined to the catalog it names.
    """
    raw = (value or "").strip()
    if not raw:
        raise UpdateActionError(f"{field_name} must not be empty")

    unified = raw.replace('\\', '/')

    # Test for an absolute path BEFORE stripping separators, otherwise the
    # leading slash disappears and the check silently passes.
    if unified.startswith('/'):
        raise UpdateActionError(f"{field_name} must be relative to the catalog")

    normalised = unified.strip('/')
    if not normalised:
        raise UpdateActionError(f"{field_name} must not be empty")

    # Worker drive prefixes such as "B:/..." are absolute in worker terms
    if len(normalised) >= 2 and normalised[1] == ':':
        raise UpdateActionError(
            f"{field_name} must be relative to the catalog, not a drive path"
        )

    parts = [p for p in normalised.split('/') if p]
    for part in parts:
        if part == '..':
            raise UpdateActionError(
                f"{field_name} must not traverse outside the catalog"
            )
        if part == '.':
            raise UpdateActionError(f"{field_name} contains an invalid path segment")

    return '/'.join(parts)


def validate_update_actions(actions: list) -> list:
    """
    Validate and normalise a list of UPDATE actions.

    Returns the normalised list. Raises ``UpdateActionError`` on the first
    problem so the caller can surface it verbatim.
    """
    if not actions:
        raise UpdateActionError("At least one action is required")

    normalised = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise UpdateActionError(f"Action {index} is not an object")

        kind = str(action.get("action") or "").strip().lower()
        if kind not in _ALLOWED_ACTIONS:
            raise UpdateActionError(
                f"Action {index} has unsupported type {kind!r}; "
                f"expected one of {', '.join(_ALLOWED_ACTIONS)}"
            )

        source = _safe_relative(action.get("source"), f"Action {index} source")

        entry = {"action": kind, "source": source}

        if kind in ("move", "rename"):
            dest = _safe_relative(action.get("dest"), f"Action {index} dest")
            if dest == source:
                raise UpdateActionError(
                    f"Action {index} source and dest are identical ({source})"
                )
            entry["dest"] = dest
        else:
            entry["recursive"] = bool(action.get("recursive", True))

        normalised.append(entry)

    # A catalog entry must not be both moved away and acted on twice
    seen_sources = set()
    for entry in normalised:
        if entry["source"] in seen_sources:
            raise UpdateActionError(
                f"{entry['source']} is targeted by more than one action"
            )
        seen_sources.add(entry["source"])

    return normalised


def predict_files_after_actions(files: List[str], actions: list) -> List[str]:
    """
    Compute the top-level file list a catalog will have once ``actions`` apply.

    Only top-level basenames are tracked, matching what PIM receives and what
    the minimum-count rule counts. An action whose destination is nested drops
    the entry from the top level; one that moves a nested file up adds it.
    """
    remaining = list(files)

    for action in actions:
        source = action["source"]
        kind = action["action"]

        # Only top-level entries appear in the tracked list
        source_is_top_level = '/' not in source

        if kind == "delete":
            if source_is_top_level and source in remaining:
                remaining.remove(source)
            continue

        dest = action.get("dest", "")
        dest_is_top_level = '/' not in dest

        if source_is_top_level and source in remaining:
            remaining.remove(source)
        if dest_is_top_level and dest not in remaining:
            remaining.append(dest)

    return remaining


def count_image_files(
    files: List[str],
    allowed_extensions: List[str],
    excluded: Optional[List[str]] = None,
) -> int:
    """
    Count files that qualify as images by extension.

    ``excluded`` carries names already proven to be content mismatches by the
    worker, so they are never counted even though their extension looks right.
    """
    allowed = {e.strip().lower().lstrip('.') for e in allowed_extensions}
    skip = set(excluded or [])
    count = 0
    for name in files:
        if name in skip:
            continue
        _, _, ext = name.rpartition('.')
        if ext and ext.lower() in allowed:
            count += 1
    return count
