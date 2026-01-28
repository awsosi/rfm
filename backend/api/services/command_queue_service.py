"""
Command queue service for managing worker commands.

Provides pull-based command distribution where workers poll for commands
and report back with responses.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from loguru import logger
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models import WorkerCommand, Worker, Operation, CommandStatus
from api.config import Settings


class CommandQueueService:
    """
    Service for managing worker command queue.

    Handles command creation, polling, response processing, and timeouts.
    """

    def __init__(self, settings: Settings):
        """
        Initialize command queue service.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self._command_locks: Dict[int, asyncio.Lock] = {}

    async def create_command(
        self,
        worker_id: int,
        command: str,
        db: AsyncSession,
        operation_id: Optional[int] = None,
        source_path: Optional[str] = None,
        dest_path: Optional[str] = None,
        params: Optional[dict] = None,
        timeout_seconds: int = 300,
    ) -> WorkerCommand:
        """
        Create a new command for a worker.

        Args:
            worker_id: Worker ID
            command: Command type (copy, move, delete, etc.)
            db: Database session
            operation_id: Optional operation ID
            source_path: Source path
            dest_path: Destination path
            params: Additional parameters
            timeout_seconds: Command timeout in seconds

        Returns:
            Created WorkerCommand
        """
        cmd = WorkerCommand(
            worker_id=worker_id,
            operation_id=operation_id,
            command=command,
            source_path=source_path,
            dest_path=dest_path,
            params_json=params,
            status=CommandStatus.PENDING,
            timeout_seconds=timeout_seconds,
        )

        db.add(cmd)
        await db.commit()
        await db.refresh(cmd)

        logger.info(
            f"Created command {cmd.id} for worker {worker_id}: {command} "
            f"(operation_id={operation_id})"
        )

        return cmd

    async def poll_commands(
        self,
        worker_id: int,
        db: AsyncSession,
        timeout_seconds: int = 30,
    ) -> Optional[WorkerCommand]:
        """
        Poll for pending commands for a worker (long-polling).

        Args:
            worker_id: Worker ID
            db: Database session
            timeout_seconds: How long to wait for a command (long-polling)

        Returns:
            WorkerCommand if available, None otherwise
        """
        start_time = datetime.now(timezone.utc)
        poll_interval = 1  # Check every second

        while (datetime.now(timezone.utc) - start_time).total_seconds() < timeout_seconds:
            # Get oldest pending command for this worker
            stmt = (
                select(WorkerCommand)
                .where(
                    and_(
                        WorkerCommand.worker_id == worker_id,
                        WorkerCommand.status == CommandStatus.PENDING,
                    )
                )
                .order_by(WorkerCommand.created_at.asc())
                .limit(1)
            )

            result = await db.execute(stmt)
            command = result.scalar_one_or_none()

            if command:
                # Mark as SENT
                command.status = CommandStatus.SENT
                command.sent_at = datetime.now(timezone.utc)
                await db.commit()
                await db.refresh(command)

                logger.info(f"Worker {worker_id} polling: sent command {command.id}")
                return command

            # No command available, wait before checking again
            await asyncio.sleep(poll_interval)

        # Timeout reached with no command
        logger.debug(f"Worker {worker_id} poll timeout (no commands available)")
        return None

    async def update_command_response(
        self,
        command_id: int,
        response_status: str,
        response_message: Optional[str],
        response_data: Optional[dict],
        db: AsyncSession,
    ) -> WorkerCommand:
        """
        Update command with worker response.

        Args:
            command_id: Command ID
            response_status: Response status (success, failed, error)
            response_message: Response message
            response_data: Response data (file count, size, etc.)
            db: Database session

        Returns:
            Updated WorkerCommand
        """
        stmt = select(WorkerCommand).where(WorkerCommand.id == command_id)
        result = await db.execute(stmt)
        command = result.scalar_one_or_none()

        if not command:
            raise ValueError(f"Command {command_id} not found")

        # Update response
        command.response_status = response_status
        command.response_message = response_message
        command.response_data = response_data
        command.completed_at = datetime.now(timezone.utc)

        # Update status based on response
        if response_status == "success":
            command.status = CommandStatus.COMPLETED
        else:
            command.status = CommandStatus.FAILED
            command.error_msg = response_message

        await db.commit()
        await db.refresh(command)

        logger.info(
            f"Command {command_id} completed with status: {response_status}"
        )

        return command

    async def get_command_by_id(
        self,
        command_id: int,
        db: AsyncSession,
    ) -> Optional[WorkerCommand]:
        """
        Get command by ID.

        Args:
            command_id: Command ID
            db: Database session

        Returns:
            WorkerCommand or None
        """
        stmt = select(WorkerCommand).where(WorkerCommand.id == command_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def wait_for_command_completion(
        self,
        command_id: int,
        db: AsyncSession,
        timeout_seconds: Optional[int] = None,
    ) -> WorkerCommand:
        """
        Wait for a command to complete.

        Args:
            command_id: Command ID
            db: Database session
            timeout_seconds: Max time to wait (uses command's timeout if not specified)

        Returns:
            Completed WorkerCommand

        Raises:
            TimeoutError: If command times out
            ValueError: If command not found
        """
        command = await self.get_command_by_id(command_id, db)
        if not command:
            raise ValueError(f"Command {command_id} not found")

        timeout = timeout_seconds or command.timeout_seconds
        start_time = datetime.now(timezone.utc)
        check_interval = 1  # Check every second

        while (datetime.now(timezone.utc) - start_time).total_seconds() < timeout:
            # Refresh command from database
            await db.refresh(command)

            if command.status in (CommandStatus.COMPLETED, CommandStatus.FAILED):
                return command

            await asyncio.sleep(check_interval)

        # Timeout reached
        command.status = CommandStatus.TIMEOUT
        command.error_msg = f"Command timed out after {timeout} seconds"
        await db.commit()

        logger.error(f"Command {command_id} timed out")
        raise TimeoutError(f"Command {command_id} timed out")

    async def cleanup_old_commands(
        self,
        db: AsyncSession,
        days: int = 7,
    ) -> int:
        """
        Clean up old completed/failed commands.

        Args:
            db: Database session
            days: Commands older than this many days will be deleted

        Returns:
            Number of commands deleted
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = select(WorkerCommand).where(
            and_(
                WorkerCommand.completed_at < cutoff_date,
                WorkerCommand.status.in_([CommandStatus.COMPLETED, CommandStatus.FAILED, CommandStatus.TIMEOUT]),
            )
        )

        result = await db.execute(stmt)
        commands = result.scalars().all()

        count = len(commands)
        for command in commands:
            await db.delete(command)

        await db.commit()

        if count > 0:
            logger.info(f"Cleaned up {count} old commands")

        return count

    async def cancel_pending_commands(
        self,
        worker_id: int,
        db: AsyncSession,
    ) -> int:
        """
        Cancel all pending commands for a worker.

        Args:
            worker_id: Worker ID
            db: Database session

        Returns:
            Number of commands cancelled
        """
        stmt = select(WorkerCommand).where(
            and_(
                WorkerCommand.worker_id == worker_id,
                WorkerCommand.status.in_([CommandStatus.PENDING, CommandStatus.SENT]),
            )
        )

        result = await db.execute(stmt)
        commands = result.scalars().all()

        count = len(commands)
        for command in commands:
            command.status = CommandStatus.FAILED
            command.error_msg = "Cancelled by system"
            command.completed_at = datetime.now(timezone.utc)

        await db.commit()

        if count > 0:
            logger.info(f"Cancelled {count} pending commands for worker {worker_id}")

        return count

    async def get_worker_queue_status(
        self,
        worker_id: int,
        db: AsyncSession,
    ) -> Dict[str, int]:
        """
        Get command queue status for a worker.

        Args:
            worker_id: Worker ID
            db: Database session

        Returns:
            Dictionary with counts by status
        """
        status_counts = {
            "pending": 0,
            "sent": 0,
            "in_progress": 0,
            "completed": 0,
            "failed": 0,
            "timeout": 0,
        }

        for status in CommandStatus:
            stmt = select(WorkerCommand).where(
                and_(
                    WorkerCommand.worker_id == worker_id,
                    WorkerCommand.status == status,
                )
            )
            result = await db.execute(stmt)
            count = len(result.scalars().all())
            status_counts[status.value.lower()] = count

        return status_counts
