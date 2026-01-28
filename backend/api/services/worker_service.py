"""
Worker communication service using pull-based command queue.

Handles all communication with Windows worker services including:
- Command queue management (pull-based architecture)
- Command execution and response tracking
- Health checks and heartbeat monitoring
- Timeout management
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import Settings
from api.schemas import WorkerRequest, WorkerCommandResponse
from api.services.command_queue_service import CommandQueueService
from models import Worker, WorkerStatus, CommandStatus


class WorkerCommunicationError(Exception):
    """Base exception for worker communication errors."""

    pass


class WorkerOfflineError(WorkerCommunicationError):
    """Worker is offline or unreachable."""

    pass


class WorkerAuthenticationError(WorkerCommunicationError):
    """Worker authentication failed."""

    pass


class WorkerTimeoutError(WorkerCommunicationError):
    """Worker request timed out."""

    pass


class WorkerService:
    """
    Service for communicating with Windows worker services via command queue.

    Provides methods for creating commands, waiting for responses,
    and managing worker health status.
    """

    def __init__(self, settings: Settings):
        """
        Initialize worker service.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.timeout = settings.worker_timeout or 300
        self.command_queue = CommandQueueService(settings)

    async def send_command(
        self,
        worker: Worker,
        command: WorkerRequest,
        db: AsyncSession,
        operation_id: Optional[int] = None,
    ) -> WorkerCommandResponse:
        """
        Send command to worker via command queue.

        Args:
            worker: Worker model
            command: Command to send
            db: Database session
            operation_id: Optional operation ID to link command

        Returns:
            WorkerCommandResponse from worker

        Raises:
            WorkerOfflineError: If worker is not active
            WorkerTimeoutError: If command times out
            WorkerCommunicationError: If command fails
        """
        if worker.status != WorkerStatus.ACTIVE:
            raise WorkerOfflineError(f"Worker {worker.name} is not active (status: {worker.status.value})")

        logger.info(
            f"Creating command for worker {worker.name}: {command.command} "
            f"(source: {command.source_path}, dest: {command.dest_path})"
        )

        # Create command in queue
        worker_command = await self.command_queue.create_command(
            worker_id=worker.id,
            command=command.command,
            db=db,
            operation_id=operation_id,
            source_path=command.source_path,
            dest_path=command.dest_path,
            params=command.params,
            timeout_seconds=self.timeout,
        )

        try:
            # Wait for worker to execute command
            completed_command = await self.command_queue.wait_for_command_completion(
                worker_command.id,
                db,
                timeout_seconds=self.timeout,
            )

            # Convert command response to WorkerCommandResponse
            if completed_command.response_status == "success":
                return WorkerCommandResponse(
                    status="success",
                    message=completed_command.response_message or "Command completed successfully",
                    file_count=completed_command.response_data.get("file_count") if completed_command.response_data else None,
                    total_size_bytes=completed_command.response_data.get("total_size_bytes") if completed_command.response_data else None,
                    error_details=completed_command.response_data.get("error_details") if completed_command.response_data else None,
                )
            else:
                raise WorkerCommunicationError(
                    f"Worker command failed: {completed_command.response_message or completed_command.error_msg}"
                )

        except TimeoutError as exc:
            logger.error(f"Command {worker_command.id} timed out for worker {worker.name}")
            raise WorkerTimeoutError(f"Worker {worker.name} command timed out") from exc
        except Exception as exc:
            logger.error(f"Command {worker_command.id} failed for worker {worker.name}: {exc}")
            raise WorkerCommunicationError(f"Worker {worker.name} command failed: {exc}") from exc

    async def _update_worker_heartbeat(
        self,
        worker: Worker,
        db: AsyncSession,
    ) -> None:
        """
        Update worker's last heartbeat timestamp.

        Args:
            worker: Worker model
            db: Database session
        """
        worker.last_heartbeat = datetime.now(timezone.utc)
        await db.commit()

    async def _mark_worker_suspended(
        self,
        worker: Worker,
        db: AsyncSession,
        reason: str,
    ) -> None:
        """
        Mark worker as suspended due to communication failure.

        Args:
            worker: Worker model
            db: Database session
            reason: Reason for suspension
        """
        logger.error(f"Suspending worker {worker.name}: {reason}")

        worker.status = WorkerStatus.SUSPENDED
        await db.commit()

    async def check_worker_health(
        self,
        worker: Worker,
        db: AsyncSession,
    ) -> bool:
        """
        Check if worker is healthy and responsive.

        Args:
            worker: Worker model
            db: Database session

        Returns:
            True if worker is healthy, False otherwise
        """
        try:
            ping_command = WorkerRequest(
                command="ping",
            )

            response = await self.send_command(worker, ping_command, db)
            return response.status == "success"

        except WorkerCommunicationError:
            return False

    async def list_directory(
        self,
        worker: Worker,
        path: str,
        db: AsyncSession,
        offset: int = 0,
        limit: int = 1000,
    ) -> WorkerCommandResponse:
        """
        List directory contents on worker.

        Args:
            worker: Worker model
            path: Directory path to list
            db: Database session
            offset: Pagination offset
            limit: Max items to return

        Returns:
            WorkerCommandResponse with directory listing
        """
        command = WorkerRequest(
            command="list",
            source_path=path,
            params={"offset": offset, "limit": limit},
        )

        return await self.send_command(worker, command, db)

    async def search_files(
        self,
        worker: Worker,
        path: str,
        query: str,
        db: AsyncSession,
        recursive: bool = True,
    ) -> WorkerCommandResponse:
        """
        Search for files on worker.

        Args:
            worker: Worker model
            path: Base path to search
            query: Search query
            db: Database session
            recursive: Whether to search recursively

        Returns:
            WorkerCommandResponse with search results
        """
        command = WorkerRequest(
            command="search",
            source_path=path,
            params={"query": query, "recursive": recursive},
        )

        return await self.send_command(worker, command, db)

    async def copy_file(
        self,
        worker: Worker,
        source_path: str,
        dest_path: str,
        db: AsyncSession,
    ) -> WorkerCommandResponse:
        """
        Copy file on worker.

        Args:
            worker: Worker model
            source_path: Source file path
            dest_path: Destination file path
            db: Database session

        Returns:
            WorkerCommandResponse with operation result
        """
        command = WorkerRequest(
            command="copy",
            source_path=source_path,
            dest_path=dest_path,
        )

        return await self.send_command(worker, command, db)

    async def move_file(
        self,
        worker: Worker,
        source_path: str,
        dest_path: str,
        db: AsyncSession,
    ) -> WorkerCommandResponse:
        """
        Move file on worker.

        Args:
            worker: Worker model
            source_path: Source file path
            dest_path: Destination file path
            db: Database session

        Returns:
            WorkerCommandResponse with operation result
        """
        command = WorkerRequest(
            command="move",
            source_path=source_path,
            dest_path=dest_path,
        )

        return await self.send_command(worker, command, db)

    async def delete_file(
        self,
        worker: Worker,
        path: str,
        db: AsyncSession,
        recursive: bool = False,
    ) -> WorkerCommandResponse:
        """
        Delete file on worker.

        Args:
            worker: Worker model
            path: File path to delete
            db: Database session
            recursive: Whether to delete recursively

        Returns:
            WorkerCommandResponse with operation result
        """
        command = WorkerRequest(
            command="delete",
            source_path=path,
            params={"recursive": recursive},
        )

        return await self.send_command(worker, command, db)

    async def create_directory(
        self,
        worker: Worker,
        path: str,
        db: AsyncSession,
        parents: bool = True,
    ) -> WorkerCommandResponse:
        """
        Create directory on worker.

        Args:
            worker: Worker model
            path: Directory path to create
            db: Database session
            parents: Whether to create parent directories

        Returns:
            WorkerCommandResponse with operation result
        """
        command = WorkerRequest(
            command="mkdir",
            source_path=path,
            params={"parents": parents},
        )

        return await self.send_command(worker, command, db)


async def get_worker_by_id(
    worker_id: int,
    db: AsyncSession,
) -> Optional[Worker]:
    """
    Get worker by ID from database.

    Args:
        worker_id: Worker ID
        db: Database session

    Returns:
        Worker model or None if not found
    """
    stmt = select(Worker).where(Worker.id == worker_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_active_workers(db: AsyncSession) -> list[Worker]:
    """
    Get all active workers from database.

    Args:
        db: Database session

    Returns:
        List of active Worker models
    """
    stmt = select(Worker).where(Worker.status == WorkerStatus.ACTIVE)
    result = await db.execute(stmt)
    return list(result.scalars().all())
