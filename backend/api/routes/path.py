"""
Path Resolution API Routes

Handles Windows path to virtual path conversion for Windows client integration.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.db import get_db
from backend.api.auth import get_current_user
from backend.models import User, Worker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/path", tags=["path"])


class PathResolveRequest(BaseModel):
    """Request to resolve Windows path to virtual path"""
    windows_path: str = Field(..., description="Real Windows path (e.g., \\\\server\\share\\folder)")
    worker_id: Optional[int] = Field(None, description="Worker ID (defaults to first worker if not provided)")


class PathResolveResponse(BaseModel):
    """Response with resolved virtual path information"""
    virtual_path: str = Field(..., description="Virtual path in RFM (e.g., A:/folder)")
    folder_name: str = Field(..., description="Name of the target folder")
    parent_path: str = Field(..., description="Parent directory path (e.g., A:/ or A:/parent)")
    worker_id: int = Field(..., description="Worker ID used for resolution")


@router.post("/resolve", response_model=PathResolveResponse)
async def resolve_path(
    request: PathResolveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Resolve Windows path to virtual path using worker's path_a_prefix.

    This endpoint is used by the Windows client to convert real Windows paths
    (e.g., \\\\server\\share\\projects\\MyFolder) to virtual paths (e.g., A:/projects/MyFolder).

    The conversion works by:
    1. Getting the worker's path_a_prefix (e.g., \\\\server\\share)
    2. Stripping this prefix from the Windows path
    3. Converting remaining path to virtual format (A:/...)

    Args:
        request: Path resolution request
        current_user: Authenticated user
        db: Database session

    Returns:
        PathResolveResponse with virtual path information

    Raises:
        HTTPException: If worker not found or path doesn't match worker's prefix
    """
    try:
        # Get worker (use provided worker_id or default to first worker)
        from sqlalchemy import select

        if request.worker_id:
            result = await db.execute(
                select(Worker).where(Worker.id == request.worker_id)
            )
            worker = result.scalar_one_or_none()

            if not worker:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Worker with ID {request.worker_id} not found"
                )
        else:
            # Default to first available worker
            result = await db.execute(
                select(Worker).order_by(Worker.id).limit(1)
            )
            worker = result.scalar_one_or_none()

            if not worker:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No workers available"
                )

        # Normalize paths for comparison (handle both forward and backward slashes)
        windows_path = request.windows_path.replace('/', '\\').rstrip('\\')
        path_a_prefix = (worker.path_a_prefix or '').replace('/', '\\').rstrip('\\')

        logger.info(f"Resolving path: {windows_path} with prefix: {path_a_prefix}")

        # If no prefix configured, assume the path is relative to root
        if not path_a_prefix:
            # Try to extract a meaningful relative path
            # For UNC paths: \\server\share\path\to\folder -> path/to/folder
            # For drive paths: G:\path\to\folder -> path/to/folder
            if windows_path.startswith('\\\\'):
                # UNC path: \\server\share\rest\of\path
                parts = windows_path.split('\\')
                # Skip empty strings and server/share parts
                parts = [p for p in parts if p]
                if len(parts) >= 3:
                    # Skip server (parts[0]) and share (parts[1]), use rest
                    relative_path = '/'.join(parts[2:])
                else:
                    # Just server and share, no subpath
                    relative_path = ''
            elif len(windows_path) >= 2 and windows_path[1] == ':':
                # Drive letter path: G:\rest\of\path
                relative_path = windows_path[3:].replace('\\', '/')  # Skip "G:\"
            else:
                # Relative path
                relative_path = windows_path.replace('\\', '/')

            virtual_path = f"A:/{relative_path}" if relative_path else "A:"
        else:
            # Check if Windows path starts with the worker's prefix
            if not windows_path.lower().startswith(path_a_prefix.lower()):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Path '{windows_path}' does not match worker's path_a_prefix '{path_a_prefix}'"
                )

            # Strip the prefix and convert to virtual path
            relative_path = windows_path[len(path_a_prefix):].lstrip('\\').replace('\\', '/')
            virtual_path = f"A:/{relative_path}" if relative_path else "A:"

        # Extract folder name (last component)
        if '/' in virtual_path and virtual_path != "A:/":
            folder_name = virtual_path.split('/')[-1]
            parent_path = '/'.join(virtual_path.split('/')[:-1])
        else:
            # Root level
            folder_name = virtual_path.split(':')[-1].lstrip('/')
            parent_path = "A:"

        logger.info(f"Resolved: virtual_path={virtual_path}, folder_name={folder_name}, parent_path={parent_path}")

        return PathResolveResponse(
            virtual_path=virtual_path,
            folder_name=folder_name,
            parent_path=parent_path,
            worker_id=worker.id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resolving path: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve path: {str(e)}"
        )
