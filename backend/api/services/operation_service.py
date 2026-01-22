"""
Operation orchestration service for managing file operations.

Handles:
- Single and multi-worker operation coordination
- Automatic rollback on failure
- Operation status tracking
- Conflict detection and queuing
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import Settings
from api.schemas import WorkerRequest, WorkerCommandResponse
from api.services.worker_service import (
    WorkerService,
    WorkerCommunicationError,
    get_worker_by_id,
)
from models import (
    Operation,
    OperationType,
    OperationStatus,
    OperationWorker,
    Worker,
    User,
)


class OperationError(Exception):
    """Base exception for operation errors."""

    pass


class OperationService:
    """
    Service for orchestrating file operations across workers.

    Manages operation lifecycle including creation, execution,
    monitoring, and rollback.
    """

    def __init__(self, settings: Settings, worker_service: WorkerService):
        """
        Initialize operation service.

        Args:
            settings: Application settings
            worker_service: Worker communication service
        """
        self.settings = settings
        self.worker_service = worker_service
        self._operation_locks: dict[str, asyncio.Lock] = {}

    async def create_operation(
        self,
        user: User,
        operation_type: OperationType,
        source_path: str,
        dest_path: Optional[str],
        worker_ids: List[int],
        db: AsyncSession,
        params: Optional[dict] = None,
    ) -> Operation:
        """
        Create new file operation.

        Args:
            user: User creating the operation
            operation_type: Type of operation
            source_path: Source file path
            dest_path: Destination path (if applicable)
            worker_ids: List of worker IDs
            db: Database session
            params: Additional parameters

        Returns:
            Created Operation model
        """
        # Create operation record
        operation = Operation(
            user_id=user.id,
            type=operation_type,
            source_path=source_path,
            dest_path=dest_path,
            status=OperationStatus.PENDING,
            params_json=params,
        )
        db.add(operation)
        await db.flush()

        # Create operation-worker associations
        for worker_id in worker_ids:
            op_worker = OperationWorker(
                operation_id=operation.id,
                worker_id=worker_id,
                worker_status=OperationStatus.PENDING,
            )
            db.add(op_worker)

        await db.commit()
        await db.refresh(operation)

        logger.info(
            f"Created operation {operation.id}: {operation_type.value} "
            f"from {source_path} with {len(worker_ids)} worker(s)"
        )

        return operation

    async def execute_operation(
        self,
        operation: Operation,
        db: AsyncSession,
    ) -> Operation:
        """
        Execute file operation.

        Args:
            operation: Operation to execute
            db: Database session

        Returns:
            Updated Operation model

        Raises:
            OperationError: If operation fails
        """
        # Get path lock to prevent concurrent operations on same path
        async with self._get_path_lock(operation.source_path):
            # Mark as in progress
            operation.status = OperationStatus.IN_PROGRESS
            operation.started_at = datetime.now(timezone.utc)
            await db.commit()

            try:
                # Get workers
                workers = await self._get_operation_workers(operation, db)

                if len(workers) == 1:
                    # Single worker operation
                    result = await self._execute_single_worker(
                        operation, workers[0], db
                    )
                elif len(workers) == 2:
                    # Two-worker operation (coordinated transfer)
                    result = await self._execute_two_worker(
                        operation, workers[0], workers[1], db
                    )
                else:
                    raise OperationError(
                        f"Invalid worker count: {len(workers)}. Expected 1 or 2."
                    )

                # Mark as completed
                operation.status = OperationStatus.COMPLETED
                operation.completed_at = datetime.now(timezone.utc)
                await db.commit()

                logger.info(f"Operation {operation.id} completed successfully")

                return operation

            except Exception as exc:
                # Mark as failed
                operation.status = OperationStatus.FAILED
                operation.error_msg = str(exc)
                operation.completed_at = datetime.now(timezone.utc)
                await db.commit()

                logger.error(f"Operation {operation.id} failed: {exc}")

                # Attempt automatic rollback if enabled
                if self.settings.enable_auto_rollback:
                    await self._rollback_operation(operation, db)

                raise OperationError(f"Operation failed: {exc}")

    async def _execute_single_worker(
        self,
        operation: Operation,
        worker: Worker,
        db: AsyncSession,
    ) -> WorkerCommandResponse:
        """
        Execute operation on single worker.

        Args:
            operation: Operation to execute
            worker: Worker to execute on
            db: Database session

        Returns:
            WorkerCommandResponse from worker
        """
        logger.info(f"Executing operation {operation.id} on worker {worker.name}")

        # Update worker status
        await self._update_worker_status(
            operation, worker, OperationStatus.IN_PROGRESS, db
        )

        try:
            # Send command based on operation type
            if operation.type == OperationType.COPY:
                response = await self.worker_service.copy_file(
                    worker, operation.source_path, operation.dest_path, db
                )
            elif operation.type == OperationType.MOVE:
                response = await self.worker_service.move_file(
                    worker, operation.source_path, operation.dest_path, db
                )
            elif operation.type == OperationType.DELETE:
                recursive = operation.params_json.get("recursive", False) if operation.params_json else False
                response = await self.worker_service.delete_file(
                    worker, operation.source_path, db, recursive
                )
            elif operation.type == OperationType.MKDIR:
                parents = operation.params_json.get("parents", True) if operation.params_json else True
                response = await self.worker_service.create_directory(
                    worker, operation.source_path, db, parents
                )
            else:
                raise OperationError(f"Unsupported operation type: {operation.type}")

            # Update operation metadata
            operation.file_count = response.file_count
            operation.total_size_bytes = response.total_size_bytes

            # Update worker status
            await self._update_worker_status(
                operation, worker, OperationStatus.COMPLETED, db
            )

            return response

        except WorkerCommunicationError as exc:
            await self._update_worker_status(
                operation, worker, OperationStatus.FAILED, db, str(exc)
            )
            raise

    async def _execute_two_worker(
        self,
        operation: Operation,
        worker1: Worker,
        worker2: Worker,
        db: AsyncSession,
    ) -> dict:
        """
        Execute operation coordinated across two workers.

        Flow:
        1. Worker1 performs operation (e.g., copy to shared location)
        2. Worker2 verifies completion
        3. Both workers confirm success

        Args:
            operation: Operation to execute
            worker1: First worker
            worker2: Second worker
            db: Database session

        Returns:
            Combined result from both workers
        """
        logger.info(
            f"Executing two-worker operation {operation.id} "
            f"on {worker1.name} and {worker2.name}"
        )

        # Execute on worker1
        try:
            response1 = await self._execute_single_worker(operation, worker1, db)
        except Exception as exc:
            logger.error(f"Worker1 failed: {exc}")
            raise

        # Verify on worker2
        try:
            # Wait a moment for file system to sync
            await asyncio.sleep(1)

            # Worker2 verifies the file exists at destination
            verify_command = WorkerRequest(
                command="list",
                source_path=operation.dest_path,
            )

            await self._update_worker_status(
                operation, worker2, OperationStatus.IN_PROGRESS, db
            )

            response2 = await self.worker_service.send_command(
                worker2, verify_command, db
            )

            if response2.status != "success":
                raise OperationError("Worker2 verification failed")

            await self._update_worker_status(
                operation, worker2, OperationStatus.COMPLETED, db
            )

            logger.info(f"Two-worker operation {operation.id} completed on both workers")

            return {"worker1": response1, "worker2": response2}

        except Exception as exc:
            logger.error(f"Worker2 failed: {exc}")

            # Rollback worker1's changes
            await self._rollback_worker_operation(operation, worker1, db)

            await self._update_worker_status(
                operation, worker2, OperationStatus.FAILED, db, str(exc)
            )

            raise OperationError(f"Worker2 failed, rolled back worker1: {exc}")

    async def _rollback_operation(
        self,
        operation: Operation,
        db: AsyncSession,
    ) -> None:
        """
        Rollback failed operation.

        Args:
            operation: Failed operation to rollback
            db: Database session
        """
        logger.info(f"Rolling back operation {operation.id}")

        # Create rollback operation
        rollback_op = Operation(
            user_id=operation.user_id,
            type=self._get_rollback_type(operation.type),
            source_path=operation.dest_path or operation.source_path,
            dest_path=operation.source_path,
            status=OperationStatus.IN_PROGRESS,
            rollback_operation_id=operation.id,
        )
        db.add(rollback_op)
        await db.commit()
        await db.refresh(rollback_op)

        try:
            # Execute rollback
            workers = await self._get_operation_workers(operation, db)
            for worker in workers:
                await self._rollback_worker_operation(operation, worker, db)

            rollback_op.status = OperationStatus.COMPLETED
            rollback_op.completed_at = datetime.now(timezone.utc)
            operation.status = OperationStatus.ROLLED_BACK
            await db.commit()

            logger.info(f"Successfully rolled back operation {operation.id}")

        except Exception as exc:
            rollback_op.status = OperationStatus.FAILED
            rollback_op.error_msg = str(exc)
            await db.commit()

            logger.error(f"Rollback failed for operation {operation.id}: {exc}")

    async def _rollback_worker_operation(
        self,
        operation: Operation,
        worker: Worker,
        db: AsyncSession,
    ) -> None:
        """
        Rollback operation on specific worker.

        Args:
            operation: Operation to rollback
            worker: Worker to rollback on
            db: Database session
        """
        try:
            if operation.type == OperationType.COPY:
                # Delete copied file
                await self.worker_service.delete_file(
                    worker, operation.dest_path, db, recursive=False
                )
            elif operation.type == OperationType.MOVE:
                # Move file back
                await self.worker_service.move_file(
                    worker, operation.dest_path, operation.source_path, db
                )
            elif operation.type == OperationType.MKDIR:
                # Remove created directory
                await self.worker_service.delete_file(
                    worker, operation.source_path, db, recursive=True
                )
            # DELETE operations cannot be rolled back

            logger.info(f"Rolled back operation {operation.id} on worker {worker.name}")

        except Exception as exc:
            logger.error(
                f"Failed to rollback operation {operation.id} on worker {worker.name}: {exc}"
            )
            raise

    def _get_rollback_type(self, operation_type: OperationType) -> OperationType:
        """
        Get the rollback operation type for given operation type.

        Args:
            operation_type: Original operation type

        Returns:
            Rollback operation type
        """
        rollback_map = {
            OperationType.COPY: OperationType.DELETE,
            OperationType.MOVE: OperationType.MOVE,
            OperationType.MKDIR: OperationType.DELETE,
            OperationType.DELETE: OperationType.COPY,  # Cannot truly rollback
        }
        return rollback_map.get(operation_type, operation_type)

    async def _get_operation_workers(
        self,
        operation: Operation,
        db: AsyncSession,
    ) -> List[Worker]:
        """
        Get workers associated with operation.

        Args:
            operation: Operation model
            db: Database session

        Returns:
            List of Worker models
        """
        stmt = (
            select(Worker)
            .join(OperationWorker)
            .where(OperationWorker.operation_id == operation.id)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def _update_worker_status(
        self,
        operation: Operation,
        worker: Worker,
        status: OperationStatus,
        db: AsyncSession,
        error_msg: Optional[str] = None,
    ) -> None:
        """
        Update worker status for operation.

        Args:
            operation: Operation model
            worker: Worker model
            status: New status
            db: Database session
            error_msg: Error message if failed
        """
        stmt = select(OperationWorker).where(
            OperationWorker.operation_id == operation.id,
            OperationWorker.worker_id == worker.id,
        )
        result = await db.execute(stmt)
        op_worker = result.scalar_one()

        op_worker.worker_status = status

        if status == OperationStatus.IN_PROGRESS:
            op_worker.worker_started_at = datetime.now(timezone.utc)
        elif status in (OperationStatus.COMPLETED, OperationStatus.FAILED):
            op_worker.worker_completed_at = datetime.now(timezone.utc)

        if error_msg:
            op_worker.worker_error_msg = error_msg

        await db.commit()

    def _get_path_lock(self, path: str) -> asyncio.Lock:
        """
        Get lock for specific file path to prevent concurrent operations.

        Args:
            path: File path

        Returns:
            Lock for path
        """
        if path not in self._operation_locks:
            self._operation_locks[path] = asyncio.Lock()
        return self._operation_locks[path]
