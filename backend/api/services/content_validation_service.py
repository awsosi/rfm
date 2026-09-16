"""
Directory Content Validation Service

Enforces the minimum-content rules before a catalog may be PUSHed or UPDATEd:

- at least ``push_validation_min_files`` image files (default 2)
- image files identified by extension AND, when
  ``push_validation_verify_content`` is on, by magic-byte sniffing on the
  worker, so a renamed .txt cannot pass as a .png

Anything that is not an image ("garbage") does not count toward the minimum
but is still reported, and is still included in the file list handed to PIM.

Files matching ``push_ignore_file_masks`` (default ``Thumbs.db``) are dropped
from the listing: PUSH does not copy them, so they must neither count nor be
announced to PIM.

When ``push_validation_file_names`` is on (default), every remaining file must
be named ``<number>.<extension>`` (e.g. ``3.png``), the only form PIM accepts.
Otherwise PIM answers 422 after the files were already copied.

The listing happens once, on the worker, via the ``validate_dir`` command, and
its result feeds both this validation and the PIM ``files`` array.

Note: the worker's payload arrives on
``WorkerCommandResponse.error_details`` — that field doubles as the generic
data channel throughout this codebase — and is nested one level deeper by the
worker route. ``unwrap_worker_data()`` handles both shapes; reading
``error_details`` directly yields an empty result that looks like an empty
directory.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import WorkerRequest
from api.services.worker_service import unwrap_worker_data
from models import Config

_CONFIG_KEYS = [
    'push_validation_enabled',
    'push_validation_min_files',
    'push_validation_allowed_extensions',
    'push_validation_verify_content',
    'push_validation_file_names',
    'push_ignore_file_masks',
]

_DEFAULT_EXTENSIONS = "jpg,jpeg,png,gif,bmp,tif,tiff,webp"
DEFAULT_IGNORE_MASKS = "Thumbs.db"

# The file name form PIM accepts: "<number>.<extension>", e.g. "3.png"
_PIM_FILE_NAME_RE = re.compile(r"[0-9]+\.[A-Za-z0-9]+")


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
    # Files not named "<number>.<extension>" (only filled while the rule is on)
    invalid_names: List[str] = field(default_factory=list)
    min_required: int = 0
    allowed_extensions: List[str] = field(default_factory=list)
    # i18n key resolved by the frontend, never a user-facing English string
    reason: Optional[str] = None
    error_detail: Optional[str] = None
    skipped: bool = False
    # Whether push_validation_file_names applies; lets UPDATE re-judge names
    check_file_names: bool = False

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "path": self.path,
            "total_files": self.total_files,
            "image_count": self.image_count,
            "files": self.files,
            "non_image_files": self.non_image_files,
            "invalid_files": self.invalid_files,
            "invalid_names": self.invalid_names,
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


def parse_ignore_masks(value: Optional[str]) -> List[str]:
    """Split the ``push_ignore_file_masks`` setting into its masks."""
    return [m.strip() for m in (value or "").split(",") if m.strip()]


def matches_ignore_mask(name: str, masks: List[str]) -> bool:
    """
    Same matching as the worker's ``MatchesIgnoreMask``: case-insensitive,
    exact, or a glob where only ``*`` and ``?`` are wildcards.
    """
    for mask in masks:
        if '*' in mask or '?' in mask:
            pattern = re.escape(mask).replace(r'\*', '.*').replace(r'\?', '.')
            if re.fullmatch(pattern, name, re.IGNORECASE):
                return True
        elif name.lower() == mask.lower():
            return True
    return False


def invalid_file_names(files: List[str]) -> List[str]:
    """Names PIM rejects: anything not ``<number>.<extension>``."""
    return [name for name in files if not _PIM_FILE_NAME_RE.fullmatch(name)]


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
    check_file_names = _truthy(config.get('push_validation_file_names'), default=True)
    ignore_masks = parse_ignore_masks(config.get('push_ignore_file_masks', DEFAULT_IGNORE_MASKS))

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

    # ``worker.py`` stores the worker's own ``error_details`` nested inside the
    # command's ``response_data``, and ``worker_service.send_command`` hands that
    # whole wrapper back as ``error_details``. ``unwrap_worker_data`` takes one
    # level off when it sees it and tolerates the flat shape, so this keeps
    # working if that seam is ever flattened.
    data = unwrap_worker_data(response)

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

    # Ignored files are never copied, so they neither count nor reach PIM
    ignored = [name for name in files if matches_ignore_mask(name, ignore_masks)]
    if ignored:
        invalid_ignored = [f.get("name") for f in invalid_files if f.get("name") in ignored]
        image_count -= count_image_files(ignored, allowed_extensions, excluded=invalid_ignored)
        total_files -= len(ignored)
        files = [name for name in files if name not in ignored]
        non_image_files = [name for name in non_image_files if name not in ignored]
        invalid_files = [f for f in invalid_files if f.get("name") not in ignored]
        logger.info(f"Content validation of {path!r} ignores {ignored} (push_ignore_file_masks)")

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
        check_file_names=check_file_names,
    )
    if check_file_names:
        # Filled even when another rule fails, so the user sees every problem
        result.invalid_names = invalid_file_names(files)

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

    if result.invalid_names:
        result.valid = False
        result.reason = "contentValidation.invalidFileNames"
        logger.warning(
            f"Content validation failed for {path!r}: "
            f"{len(result.invalid_names)} file(s) not named <number>.<extension>: "
            f"{result.invalid_names[:10]}"
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

_ALLOWED_ACTIONS = ("move", "rename", "delete", "replace", "add")
# Actions whose new content comes from Path A or an upload
CONTENT_ACTIONS = ("replace", "add")

_UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# Extension -> the type the worker's magic-byte sniffer reports for it
# (FileOperations.ExpectedImageType on the worker)
_EXPECTED_TYPE = {
    "jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif",
    "bmp": "bmp", "tif": "tiff", "tiff": "tiff", "webp": "webp",
}


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


def _safe_path_a(value: str, field_name: str) -> str:
    """Normalise a Path A file path (``A:/dir/file.jpg``) and refuse escapes."""
    raw = (value or "").strip().replace('\\', '/')
    if raw[:2].upper() != 'A:':
        raise UpdateActionError(f"{field_name} must be a Path A file (A:/...)")
    rest = raw[2:].strip('/')
    if not rest:
        raise UpdateActionError(f"{field_name} must name a file, not the Path A root")
    if ':' in rest:
        raise UpdateActionError(f"{field_name} must not contain another drive letter")
    return "A:/" + _safe_relative(rest, field_name)


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

        entry = {"action": kind}

        if kind != "add":
            entry["source"] = _safe_relative(action.get("source"), f"Action {index} source")

        if kind in ("move", "rename", "add"):
            entry["dest"] = _safe_relative(action.get("dest"), f"Action {index} dest")
            if entry["dest"] == entry.get("source"):
                raise UpdateActionError(
                    f"Action {index} source and dest are identical ({entry['dest']})"
                )

        if kind == "delete":
            entry["recursive"] = bool(action.get("recursive", True))

        if kind in CONTENT_ACTIONS:
            from_path = action.get("from_path")
            upload_id = action.get("upload_id")
            if bool(from_path) == bool(upload_id):
                raise UpdateActionError(
                    f"Action {index} ({kind}) needs exactly one of from_path or upload_id"
                )
            if from_path:
                entry["from_path"] = _safe_path_a(from_path, f"Action {index} from_path")
                entry["remove_source"] = bool(action.get("remove_source", False))
            else:
                upload_id = str(upload_id).strip().lower()
                if not _UPLOAD_ID_RE.match(upload_id):
                    raise UpdateActionError(f"Action {index} upload_id is malformed")
                entry["upload_id"] = upload_id
                if action.get("remove_source"):
                    raise UpdateActionError(
                        f"Action {index}: remove_source applies only to Path A files"
                    )
        elif action.get("from_path") or action.get("upload_id"):
            raise UpdateActionError(
                f"Action {index} ({kind}) does not take from_path or upload_id"
            )

        normalised.append(entry)

    # Every catalog entry may be touched by one action only: acting on a name
    # that another action moves away or creates would depend on ordering.
    seen = set()
    for entry in normalised:
        for key in ("source", "dest"):
            name = entry.get(key)
            if name is None:
                continue
            if name in seen:
                raise UpdateActionError(f"{name} is targeted by more than one action")
            seen.add(name)

    return normalised


def predict_files_after_actions(files: List[str], actions: list) -> List[str]:
    """
    Compute the top-level file list a catalog will have once ``actions`` apply.

    Only top-level basenames are tracked, matching what PIM receives and what
    the minimum-count rule counts. An action whose destination is nested drops
    the entry from the top level; one that moves a nested file up adds it.
    A replace keeps the name, so the list is unchanged by it.
    """
    remaining = list(files)

    for action in actions:
        kind = action["action"]
        source = action.get("source")

        if kind == "replace":
            continue

        if source is not None and '/' not in source and source in remaining:
            remaining.remove(source)

        if kind == "delete":
            continue

        dest = action.get("dest", "")
        if '/' not in dest and dest not in remaining:
            remaining.append(dest)

    return remaining


def invalid_files_after_actions(invalid_files: List[dict], actions: list) -> List[dict]:
    """
    Carry the worker's content-mismatch findings over to the post-update names.

    A deleted or replaced file no longer counts against the catalog (a replaced
    file's new content is checked separately once staged). A renamed file keeps
    its real content: it stays invalid under its new name unless the new
    extension matches what its bytes are, which is how a rename fixes a
    mislabelled image. A file moved out of the top level is no longer tracked.
    """
    by_source = {a.get("source"): a for a in actions if a.get("source") is not None}
    result = []
    for item in invalid_files or []:
        name = item.get("name")
        action = by_source.get(name)
        if action is None:
            result.append(item)
            continue
        if action["action"] in ("delete", "replace"):
            continue
        dest = action.get("dest", "")
        if '/' in dest:
            continue
        _, _, ext = dest.rpartition('.')
        if _EXPECTED_TYPE.get(ext.lower()) == item.get("detected"):
            continue
        result.append({**item, "name": dest, "extension": ext.lower()})
    return result


async def inspect_staged_files(
    worker,
    staging_path: str,
    expected_names: List[str],
    worker_service,
    db: AsyncSession,
) -> tuple[List[str], List[dict]]:
    """
    Check files an UPDATE staged before they replace or join the catalog.

    Returns ``(missing, invalid)``: names that are not plain files in the
    staging directory (e.g. a Path A *folder* was picked), and worker content
    findings for files whose bytes contradict their extension. Content is only
    judged when validation and ``push_validation_verify_content`` are on, the
    same switches PUSH honours; the presence check always runs.

    Raises on worker/transport failure: without the listing nothing is proven.
    """
    config = await _get_validation_config(db)
    enabled = _truthy(config.get('push_validation_enabled'), default=True)
    verify_content = enabled and _truthy(config.get('push_validation_verify_content'), default=True)
    ext_str = config.get('push_validation_allowed_extensions') or _DEFAULT_EXTENSIONS
    allowed_extensions = [e.strip().lower().lstrip('.') for e in ext_str.split(',') if e.strip()]

    response = await worker_service.send_command(
        worker,
        WorkerRequest(
            command="validate_dir",
            source_path=staging_path,
            params={"allowed_extensions": allowed_extensions, "verify_content": verify_content},
        ),
        db,
    )
    if response.status != "success":
        raise RuntimeError(f"Could not inspect staged files: {response.message}")

    data = unwrap_worker_data(response)
    present = {str(f) for f in (data.get("files") or [])}
    missing = [name for name in expected_names if name not in present]
    invalid = [
        item for item in (data.get("invalid_files") or [])
        if isinstance(item, dict) and item.get("name") in expected_names
    ] if verify_content else []
    return missing, invalid


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
