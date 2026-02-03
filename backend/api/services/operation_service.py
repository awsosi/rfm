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
from api.services.elasticsearch_service import get_elasticsearch_service
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

    async def _index_operation_in_elasticsearch(
        self, operation: Operation, user_name: Optional[str] = None, db: Optional[AsyncSession] = None
    ) -> None:
        """
        Index operation in Elasticsearch.

        Args:
            operation: Operation to index
            user_name: User name (optional, will be fetched if not provided)
            db: Database session (optional, needed to fetch user_name if not provided)
        """
        try:
            es_service = await get_elasticsearch_service()

            # Get user_name if not provided
            if not user_name and db:
                stmt = select(User).where(User.id == operation.user_id)
                result = await db.execute(stmt)
                user = result.scalar_one_or_none()
                user_name = user.username if user else None

            # Prepare operation data for Elasticsearch
            operation_data = {
                "operation_id": operation.id,
                "user_id": operation.user_id,
                "user_name": user_name,
                "operation_type": operation.type.value if operation.type else None,
                "status": operation.status.value if operation.status else None,
                "source_path": operation.source_path,
                "dest_path": operation.dest_path,
                "original_path": operation.original_path,
                "archive_path": operation.archive_path,
                "error_msg": operation.error_msg,
                "file_count": operation.file_count,
                "total_size_bytes": operation.total_size_bytes,
                "created_at": operation.created_at.isoformat() if operation.created_at else None,
                "started_at": operation.started_at.isoformat() if operation.started_at else None,
                "completed_at": operation.completed_at.isoformat() if operation.completed_at else None,
            }

            await es_service.index_operation(operation_data)
        except Exception as e:
            # Log error but don't fail the operation
            logger.warning(f"Failed to index operation {operation.id} in Elasticsearch: {e}")

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

        # Index in Elasticsearch
        await self._index_operation_in_elasticsearch(operation, user.username, db)

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

            # Update in Elasticsearch
            await self._index_operation_in_elasticsearch(operation, None, db)

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

                # Update in Elasticsearch
                await self._index_operation_in_elasticsearch(operation, None, db)

                return operation

            except Exception as exc:
                # Mark as failed
                operation.status = OperationStatus.FAILED
                operation.error_msg = str(exc)
                operation.completed_at = datetime.now(timezone.utc)
                await db.commit()

                logger.error(f"Operation {operation.id} failed: {exc}")

                # Update in Elasticsearch
                await self._index_operation_in_elasticsearch(operation, None, db)

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
            elif operation.type == OperationType.PUSH:
                # PUSH: Copy to pathB + Archive to pathC
                response = await self._execute_push_operation(operation, worker, db)
            elif operation.type == OperationType.PULL:
                # PULL: Revert from pathB to original location
                response = await self._execute_pull_operation(operation, worker, db)
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

    async def create_push_operation(
        self,
        user: User,
        source_dir: str,
        worker_id: int,
        db: AsyncSession,
    ) -> Operation:
        """
        Create and execute a PUSH operation.

        PUSH: Copy directory from source to PATH_B, then archive to PATH_C.

        Args:
            user: User creating the operation
            source_dir: Source directory path (from Path A)
            worker_id: Worker ID to execute operation
            db: Database session

        Returns:
            Created Operation model

        Raises:
            OperationError: If PATH_B or PATH_C not configured or operation fails
        """
        # Get worker and validate PATH_B and PATH_C are configured
        worker = await get_worker_by_id(worker_id, db)
        if not worker:
            raise OperationError(f"Worker {worker_id} not found")

        if not worker.path_b_prefix:
            raise OperationError(
                f"PATH_B not configured for worker '{worker.name}'. "
                "Configure in Admin Panel -> System -> Worker Configuration."
            )
        if not worker.path_c_prefix:
            raise OperationError(
                f"PATH_C not configured for worker '{worker.name}'. "
                "Configure in Admin Panel -> System -> Worker Configuration."
            )

        # Extract directory name from source path
        import os
        dir_name = os.path.basename(source_dir.rstrip('/\\'))

        # Build destination paths using B: and C: prefixes for worker resolution
        # Worker will resolve B: and C: to actual paths via PathBPrefix/PathCPrefix
        dest_path_b = f"B:/{dir_name}"
        archive_path_c = f"C:/{dir_name}"

        # Create operation record
        operation = Operation(
            user_id=user.id,
            type=OperationType.PUSH,
            source_path=source_dir,
            dest_path=dest_path_b,
            original_path=source_dir,  # Save original for PULL operations
            archive_path=archive_path_c,
            status=OperationStatus.PENDING,
        )
        db.add(operation)
        await db.flush()

        # Create operation-worker association
        op_worker = OperationWorker(
            operation_id=operation.id,
            worker_id=worker_id,
            worker_status=OperationStatus.PENDING,
        )
        db.add(op_worker)

        await db.commit()
        await db.refresh(operation)

        logger.info(
            f"Created PUSH operation {operation.id}: {source_dir} -> "
            f"pathB:{dest_path_b}, archive:{archive_path_c}"
        )

        # Index in Elasticsearch
        await self._index_operation_in_elasticsearch(operation, user.username, db)

        return operation

    async def create_pull_operation(
        self,
        user: User,
        original_operation_id: int,
        worker_id: int,
        db: AsyncSession,
    ) -> Operation:
        """
        Create and execute a PULL operation (revert a PUSH).

        PULL: Copy directory from PATH_B back to original location, then remove from PATH_B.

        Args:
            user: User creating the operation
            original_operation_id: ID of the original PUSH operation to revert
            worker_id: Worker ID to execute operation
            db: Database session

        Returns:
            Created Operation model

        Raises:
            OperationError: If original operation not found or invalid
        """
        # Get original PUSH operation
        stmt = select(Operation).where(Operation.id == original_operation_id)
        result = await db.execute(stmt)
        original_op = result.scalar_one_or_none()

        if not original_op:
            raise OperationError(f"Operation {original_operation_id} not found")

        if original_op.type != OperationType.PUSH:
            raise OperationError(
                f"Operation {original_operation_id} is not a PUSH operation. "
                f"Only PUSH operations can be reverted."
            )

        if not original_op.original_path:
            raise OperationError(
                f"Original path not found for operation {original_operation_id}. "
                f"Cannot revert."
            )

        # Create PULL operation
        operation = Operation(
            user_id=user.id,
            type=OperationType.PULL,
            source_path=original_op.dest_path,  # Copy from PATH_B
            dest_path=original_op.original_path,  # Back to original location
            original_path=original_op.original_path,
            rollback_operation_id=original_operation_id,  # Link to original PUSH
            status=OperationStatus.PENDING,
        )
        db.add(operation)
        await db.flush()

        # Create operation-worker association
        op_worker = OperationWorker(
            operation_id=operation.id,
            worker_id=worker_id,
            worker_status=OperationStatus.PENDING,
        )
        db.add(op_worker)

        await db.commit()
        await db.refresh(operation)

        logger.info(
            f"Created PULL operation {operation.id}: revert PUSH {original_operation_id} "
            f"from {original_op.dest_path} to {original_op.original_path}"
        )

        # Index in Elasticsearch
        await self._index_operation_in_elasticsearch(operation, user.username, db)

        return operation

    async def _execute_push_operation(
        self,
        operation: Operation,
        worker: Worker,
        db: AsyncSession,
    ) -> WorkerCommandResponse:
        """
        Execute PUSH operation on worker.

        Steps:
        1. Copy directory from source to PATH_B
        2. Move directory from source to PATH_C (archive)

        Args:
            operation: PUSH operation to execute
            worker: Worker to execute on
            db: Database session

        Returns:
            WorkerCommandResponse from worker
        """
        logger.info(
            f"Executing PUSH operation {operation.id}: "
            f"{operation.source_path} -> {operation.dest_path} + archive to {operation.archive_path}"
        )

        # Update worker status
        await self._update_worker_status(
            operation, worker, OperationStatus.IN_PROGRESS, db
        )

        try:
            # Step 1: Copy to PATH_B
            logger.info(f"PUSH Step 1: Copying {operation.source_path} to {operation.dest_path}")
            copy_response = await self.worker_service.copy_file(
                worker, operation.source_path, operation.dest_path, db
            )

            # Step 2: Move to PATH_C (archive)
            logger.info(f"PUSH Step 2: Archiving {operation.source_path} to {operation.archive_path}")
            archive_response = await self.worker_service.move_file(
                worker, operation.source_path, operation.archive_path, db
            )

            # Combine results
            total_files = (copy_response.file_count or 0) + (archive_response.file_count or 0)
            total_size = (copy_response.total_size_bytes or 0) + (archive_response.total_size_bytes or 0)

            # Update operation metadata
            operation.file_count = total_files
            operation.total_size_bytes = total_size

            # Update worker status
            await self._update_worker_status(
                operation, worker, OperationStatus.COMPLETED, db
            )

            logger.info(f"PUSH operation {operation.id} completed: {total_files} files, {total_size} bytes")

            # Return combined response
            return WorkerCommandResponse(
                status="success",
                message=f"PUSH completed: copied to {operation.dest_path} and archived to {operation.archive_path}",
                file_count=total_files,
                total_size_bytes=total_size,
            )

        except WorkerCommunicationError as exc:
            await self._update_worker_status(
                operation, worker, OperationStatus.FAILED, db, str(exc)
            )
            raise OperationError(f"PUSH operation failed: {exc}")

    async def _execute_pull_operation(
        self,
        operation: Operation,
        worker: Worker,
        db: AsyncSession,
    ) -> WorkerCommandResponse:
        """
        Execute PULL operation on worker.

        Steps:
        1. Copy directory from PATH_B back to original location
        2. Delete directory from PATH_B

        Args:
            operation: PULL operation to execute
            worker: Worker to execute on
            db: Database session

        Returns:
            WorkerCommandResponse from worker
        """
        logger.info(
            f"Executing PULL operation {operation.id}: "
            f"{operation.source_path} -> {operation.dest_path}"
        )

        # Update worker status
        await self._update_worker_status(
            operation, worker, OperationStatus.IN_PROGRESS, db
        )

        try:
            # Step 1: Copy from PATH_B to original location
            logger.info(f"PULL Step 1: Copying {operation.source_path} to {operation.dest_path}")
            copy_response = await self.worker_service.copy_file(
                worker, operation.source_path, operation.dest_path, db
            )

            # Step 2: Delete from PATH_B
            logger.info(f"PULL Step 2: Deleting {operation.source_path} from PATH_B")
            delete_response = await self.worker_service.delete_file(
                worker, operation.source_path, db, recursive=True
            )

            # Update operation metadata
            operation.file_count = copy_response.file_count
            operation.total_size_bytes = copy_response.total_size_bytes

            # Update worker status
            await self._update_worker_status(
                operation, worker, OperationStatus.COMPLETED, db
            )

            logger.info(
                f"PULL operation {operation.id} completed: "
                f"{copy_response.file_count} files restored, {operation.source_path} removed from PATH_B"
            )

            # Return response
            return WorkerCommandResponse(
                status="success",
                message=f"PULL completed: restored to {operation.dest_path} and removed from PATH_B",
                file_count=copy_response.file_count,
                total_size_bytes=copy_response.total_size_bytes,
            )

        except WorkerCommunicationError as exc:
            await self._update_worker_status(
                operation, worker, OperationStatus.FAILED, db, str(exc)
            )
            raise OperationError(f"PULL operation failed: {exc}")
