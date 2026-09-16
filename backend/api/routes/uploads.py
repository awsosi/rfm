"""
UPDATE upload routes (user-side).

Files uploaded here can replace or add catalog files in an UPDATE. They are
kept only until the UPDATE that uses them finishes, or until the configured
TTL if never used (see api/services/upload_service.py).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import Settings, get_settings
from api.middleware.auth import require_user
from api.schemas import UploadResponse
from api.services.upload_service import (
    UploadError,
    delete_pending_upload,
    get_upload_limits,
    store_upload,
)
from database import get_db
from models import User

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

# Multipart framing around the file; a request larger than max + this is
# refused from Content-Length before its body is read.
_MULTIPART_OVERHEAD = 64 * 1024


async def _chunks(file: UploadFile):
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        yield chunk


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Store one file for a later UPDATE replace/add action."""
    max_bytes, _ = await get_upload_limits(db, settings)
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        declared = 0
    if declared > max_bytes + _MULTIPART_OVERHEAD:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit",
        )

    try:
        upload = await store_upload(current_user, file.filename, _chunks(file), db, settings)
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except OSError as exc:
        logger.error(f"Could not store upload from user '{current_user.username}': {exc}")
        raise HTTPException(status_code=500, detail="Upload could not be stored")
    finally:
        await file.close()

    return UploadResponse.model_validate(upload)


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_upload(
    upload_id: str,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Delete an upload that is no longer wanted (e.g. the UPDATE dialog was cancelled)."""
    try:
        await delete_pending_upload(upload_id, current_user, db, settings)
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
