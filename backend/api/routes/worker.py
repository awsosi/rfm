"""
Worker API routes for pull-based command distribution.

Provides endpoints for:
- Command polling (long-poll)
- Command response submission
- Heartbeat updates
- Configuration retrieval
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings, Settings
from api.schemas import (
    CommandPollResponse,
    CommandResponseRequest,
    WorkerConfigResponse,
)
from api.services.command_queue_service import CommandQueueService
from database import get_db
from models import Worker, WorkerStatus

router = APIRouter(prefix="/api/workers", tags=["workers"])


async def get_worker_by_hostname(
    hostname: str,
    db: AsyncSession,
) -> Optional[Worker]:
    """Get worker by hostname (used as workerId in URLs)."""
    stmt = select(Worker).where(Worker.hostname == hostname)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.get("/{worker_id}/commands/poll")
async def poll_commands(
    worker_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    timeout: int = Query(default=30, ge=1, le=60),
) -> CommandPollResponse:
    """
    Long-poll for pending commands (worker-side).

    Workers call this endpoint to check for new commands.
    The endpoint will wait up to `timeout` seconds for a command to become available.

    Args:
        worker_id: Worker hostname/name
        timeout: Max seconds to wait for a command (long-polling)

    Returns:
        CommandPollResponse with command details or empty response if no command
    """
    # Get worker by hostname
    worker = await get_worker_by_hostname(worker_id, db)
    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker '{worker_id}' not found"
        )

    # Check if worker is active
    if worker.status != WorkerStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Worker is not active (status: {worker.status.value})"
        )

    # Update last heartbeat
    worker.last_heartbeat = datetime.now(timezone.utc)
    await db.commit()

    # Poll for commands
    command_service = CommandQueueService(settings)
    command = await command_service.poll_commands(
        worker.id,
        db,
        timeout_seconds=timeout,
    )

    if command:
        # Return command details
        return CommandPollResponse(
            command_id=command.id,
            command=command.command,
            source_path=command.source_path,
            dest_path=command.dest_path,
            parameters=command.params_json,
        )
    else:
        # No command available
        return CommandPollResponse()


@router.post("/{worker_id}/commands/{command_id}/response")
async def submit_command_response(
    worker_id: str,
    command_id: int,
    response_data: CommandResponseRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """
    Submit command execution response (worker-side).

    Workers call this endpoint after executing a command to report the result.

    Args:
        worker_id: Worker hostname/name
        command_id: Command ID
        response_data: Response data from worker

    Returns:
        Success confirmation
    """
    # Get worker by hostname
    worker = await get_worker_by_hostname(worker_id, db)
    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker '{worker_id}' not found"
        )

    # Update command with response
    command_service = CommandQueueService(settings)

    # Build response data dict
    response_dict = {}
    if response_data.file_count is not None:
        response_dict["file_count"] = response_data.file_count
    if response_data.total_size_bytes is not None:
        response_dict["total_size_bytes"] = response_data.total_size_bytes
    if response_data.error_details:
        response_dict["error_details"] = response_data.error_details

    try:
        command = await command_service.update_command_response(
            command_id,
            response_data.status,
            response_data.message,
            response_dict if response_dict else None,
            db,
        )

        # Update operation status if linked
        if command.operation_id:
            from models import Operation, OperationStatus

            stmt = select(Operation).where(Operation.id == command.operation_id)
            result = await db.execute(stmt)
            operation = result.scalar_one_or_none()

            if operation:
                if response_data.status == "success":
                    # Check if all commands for this operation are completed
                    # For simplicity, mark operation as completed immediately
                    operation.status = OperationStatus.COMPLETED
                    operation.completed_at = datetime.now(timezone.utc)
                    if response_data.file_count:
                        operation.file_count = response_data.file_count
                    if response_data.total_size_bytes:
                        operation.total_size_bytes = response_data.total_size_bytes
                else:
                    operation.status = OperationStatus.FAILED
                    operation.error_msg = response_data.message
                    operation.completed_at = datetime.now(timezone.utc)

                await db.commit()

        return {"status": "ok", "message": "Response recorded"}

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post("/{worker_id}/heartbeat")
async def submit_heartbeat(
    worker_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Submit worker heartbeat (worker-side).

    Workers call this endpoint periodically to indicate they're online.

    Args:
        worker_id: Worker hostname/name

    Returns:
        Success confirmation
    """
    # Get worker by hostname
    worker = await get_worker_by_hostname(worker_id, db)
    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker '{worker_id}' not found"
        )

    # Update last heartbeat
    worker.last_heartbeat = datetime.now(timezone.utc)
    await db.commit()

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/{worker_id}/config")
async def get_worker_config(
    worker_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> WorkerConfigResponse:
    """
    Get worker configuration (worker-side).

    Workers can call this endpoint to get runtime configuration updates.

    Args:
        worker_id: Worker hostname/name

    Returns:
        WorkerConfigResponse with configuration
    """
    # Get worker by hostname
    worker = await get_worker_by_hostname(worker_id, db)
    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker '{worker_id}' not found"
        )

    # Return configuration
    return WorkerConfigResponse(
        path_a_prefix=worker.path_a_prefix,
        path_b_prefix=worker.path_b_prefix,
        path_c_prefix=settings.path_c,  # Global path C configuration
        polling_interval_seconds=5,
    )
