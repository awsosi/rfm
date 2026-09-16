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
    Config,
    Operation,
    OperationType,
    OperationStatus,
    OperationWorker,
    Worker,
    User,
)

# Global lock dictionary for path-based operation locking
# This ensures locks are shared across all OperationService instances
_operation_locks: dict[str, asyncio.Lock] = {}


class OperationError(Exception):
    """Base exception for operation errors."""

    pass


# Name of the per-operation working folder an UPDATE creates inside the catalog
UPDATE_STAGING_PREFIX = ".rfm-update-"


class UpdateContentRejected(OperationError):
    """
    New content staged by an UPDATE failed inspection; the catalog is unchanged.

    ``missing``: catalog entries whose source was not a plain file (e.g. a
    folder). ``invalid_files``: worker findings for files whose bytes
    contradict their extension, keyed by the catalog entry they were meant for.
    """

    def __init__(self, missing: list, invalid_files: list):
        self.missing = missing
        self.invalid_files = invalid_files
        parts = []
        if missing:
            parts.append(f"not a file: {', '.join(missing)}")
        if invalid_files:
            parts.append(
                "content does not match extension: "
                + ", ".join(str(f.get("name")) for f in invalid_files)
            )
        super().__init__("New content rejected (" + "; ".join(parts) + ")")


async def get_update_ids_for_pushes(
    db: AsyncSession, push_ids: List[int]
) -> dict[int, List[int]]:
    """Map each PUSH id to the ids of COMPLETED UPDATEs of its catalog, oldest first."""
    if not push_ids:
        return {}
    push_ref = Operation.params_json["push_operation_id"].as_integer()
    result = await db.execute(
        select(push_ref, Operation.id)
        .where(
            Operation.type == OperationType.UPDATE,
            Operation.status == OperationStatus.COMPLETED,
            push_ref.in_(push_ids),
        )
        .order_by(Operation.id)
    )
    mapping: dict[int, List[int]] = {}
    for push_id, update_id in result:
        mapping.setdefault(push_id, []).append(update_id)
    return mapping


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

    async def _broadcast_operation_update(
        self,
        operation: Operation,
        user_name: Optional[str] = None,
    ) -> None:
        """
        Broadcast operation update via WebSocket.

        Args:
            operation: Operation that was updated
            user_name: Username (optional)
        """
        try:
            from api.websocket_manager import ws_manager

            await ws_manager.broadcast(
                {
                    "event_type": "operation_update",
                    "type": "operation_update",
                    "operation_id": operation.id,
                    "status": operation.status.value if operation.status else None,
                    "operation_type": operation.type.value if operation.type else None,
                    "user_name": user_name,
                    "source_path": operation.source_path,
                    "dest_path": operation.dest_path,
                    "error_msg": operation.error_msg,
                },
                topic="operations"
            )
            logger.debug(f"Broadcast operation {operation.id} update: {operation.status}")
        except Exception as exc:
            logger.warning(f"Failed to broadcast operation update: {exc}")

    async def _broadcast_file_list_changed(
        self,
        operation: Operation,
    ) -> None:
        """
        Broadcast file listing change via WebSocket.

        Notifies clients that file listings may have changed for affected paths.

        Args:
            operation: Operation that affected file system
        """
        try:
            from api.websocket_manager import ws_manager
            import os

            # Collect affected paths
            affected_paths = []

            if operation.source_path:
                # Get parent directory of source path for refresh
                source_parent = os.path.dirname(operation.source_path.rstrip('/\\'))
                if not source_parent or source_parent == operation.source_path:
                    # If at root, use the source path itself
                    source_parent = operation.source_path
                affected_paths.append(source_parent)

            if operation.dest_path:
                # Get parent directory of dest path for refresh
                dest_parent = os.path.dirname(operation.dest_path.rstrip('/\\'))
                if not dest_parent or dest_parent == operation.dest_path:
                    dest_parent = operation.dest_path
                affected_paths.append(dest_parent)

            if operation.original_path:
                # For PULL operations, also refresh original path
                original_parent = os.path.dirname(operation.original_path.rstrip('/\\'))
                if not original_parent or original_parent == operation.original_path:
                    original_parent = operation.original_path
                if original_parent not in affected_paths:
                    affected_paths.append(original_parent)

            # Broadcast file list changed event for each affected path
            for path in affected_paths:
                await ws_manager.broadcast(
                    {
                        "event_type": "file_list_changed",
                        "type": "file_list_changed",
                        "path": path,
                        "operation_id": operation.id,
                        "operation_type": operation.type.value if operation.type else None,
                    },
                    topic="file_changes"
                )
                logger.debug(f"Broadcast file list changed for path: {path}")
        except Exception as exc:
            logger.warning(f"Failed to broadcast file list changed: {exc}")

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

        # Broadcast operation creation via WebSocket
        await self._broadcast_operation_update(operation, user.username)

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
        # Path locking is now handled at the API endpoint level (app.py)
        # to prevent race conditions before operation creation

        # Mark as in progress
        operation.status = OperationStatus.IN_PROGRESS
        operation.started_at = datetime.now(timezone.utc)
        await db.commit()

        # Update in Elasticsearch
        await self._index_operation_in_elasticsearch(operation, None, db)

        # Broadcast operation start via WebSocket
        await self._broadcast_operation_update(operation)

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

            # Broadcast operation completion via WebSocket
            await self._broadcast_operation_update(operation)

            # Broadcast file listing changes for affected paths
            await self._broadcast_file_list_changed(operation)

            # Signal external systems for completed catalog operations
            # (fire-and-forget; a signalling outage must never fail the operation)
            if operation.type in (OperationType.PUSH, OperationType.PULL):
                from api.services.rosapi_service import signal_operation_completed_bg
                asyncio.create_task(
                    signal_operation_completed_bg(
                        operation_id=operation.id,
                        operation_type=operation.type.value,
                        source_path=operation.source_path,
                        dest_path=operation.dest_path,
                    )
                )

            if operation.type in (
                OperationType.PUSH,
                OperationType.PULL,
                OperationType.UPDATE,
            ):
                from api.services.pim_service import signal_pim_event_bg

                # File list and catalog name were captured during validation and
                # stored on the operation, so PIM needs no extra worker round-trip.
                params = operation.params_json or {}
                asyncio.create_task(
                    signal_pim_event_bg(
                        operation_id=operation.id,
                        operation_type=operation.type.value,
                        source_path=operation.source_path,
                        dest_path=operation.dest_path,
                        files=params.get("files") or [],
                        username=params.get("username") or "",
                        catalog_name=params.get("catalog_name"),
                    )
                )

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

            # Broadcast operation failure via WebSocket
            await self._broadcast_operation_update(operation)

            # Broadcast file listing changes for affected paths (operation may have partially completed)
            await self._broadcast_file_list_changed(operation)

            # Attempt automatic rollback if enabled
            # PUSH/PULL operations should not use auto-rollback (they have their own undo mechanism via PULL);
            # UPDATE reverts its own changes before it fails.
            if self.settings.enable_auto_rollback and operation.type not in (
                OperationType.PUSH, OperationType.PULL, OperationType.UPDATE
            ):
                await self._rollback_operation(operation, db)

            raise OperationError(f"Operation failed: {exc}") from exc

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
            elif operation.type == OperationType.UPDATE:
                # UPDATE: in-place move/rename/delete inside a pushed catalog
                response = await self._execute_update_operation(operation, worker, db)
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
                params={"path": operation.dest_path},
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

        Uses global lock dictionary to ensure locks are shared across all
        OperationService instances and prevent concurrent operations on the
        same path from different requests.

        Args:
            path: File path

        Returns:
            Lock for path
        """
        if path not in _operation_locks:
            _operation_locks[path] = asyncio.Lock()
        return _operation_locks[path]

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
        # Get worker and validate PATH_B (and PATH_C if archive enabled)
        # Configuration hierarchy: worker-specific -> global settings
        worker = await get_worker_by_id(worker_id, db)
        if not worker:
            raise OperationError(f"Worker {worker_id} not found")

        # Read push settings from DB (runtime source of truth)
        push_config_keys = ['enable_push_archive']
        stmt = select(Config).where(Config.key.in_(push_config_keys))
        result = await db.execute(stmt)
        push_config = {c.key: c.value for c in result.scalars()}
        archive_enabled = push_config.get("enable_push_archive", "false").lower() == "true"

        # Use worker-specific path_b_prefix or fall back to global settings
        # Note: settings.path_b is used as fallback for VF redesign PUSH operations
        path_b = worker.path_b_prefix or self.settings.path_b or self.settings.global_path_b_prefix
        if not path_b:
            raise OperationError(
                f"PATH_B not configured for worker '{worker.name}'. "
                "Configure in Admin Panel -> System -> Worker Configuration or set PATH_B/GLOBAL_PATH_B_PREFIX in .env."
            )

        # Use worker-specific path_c_prefix or fall back to global settings
        # Only required when archiving is enabled
        path_c = worker.path_c_prefix or self.settings.path_c
        if archive_enabled and not path_c:
            raise OperationError(
                f"PATH_C not configured for worker '{worker.name}' but archiving is enabled. "
                "Configure in Admin Panel -> System -> Worker Configuration or set PATH_C in .env."
            )

        # Extract directory name from source path
        import os
        dir_name = os.path.basename(source_dir.rstrip('/\\'))

        # Build destination paths using B: and C: prefixes for worker resolution
        # Worker will resolve B: and C: to actual paths via PathBPrefix/PathCPrefix
        dest_path_b = f"B:/{dir_name}"
        archive_path_c = f"C:/{dir_name}" if archive_enabled else None

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

        # Broadcast operation creation via WebSocket
        await self._broadcast_operation_update(operation, user.username)

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

        # Check if this operation has already been pulled
        existing_pull_stmt = (
            select(Operation)
            .where(Operation.rollback_operation_id == original_operation_id)
            .where(Operation.type == OperationType.PULL)
            .where(Operation.status == OperationStatus.COMPLETED)
        )
        existing_pull_result = await db.execute(existing_pull_stmt)
        existing_pull = existing_pull_result.scalar_one_or_none()

        if existing_pull:
            raise OperationError(
                f"Operation {original_operation_id} has already been pulled "
                f"(PULL operation {existing_pull.id}). Cannot pull again."
            )

        # A PULL brings back the catalog as it is now in PATH_B, including every
        # UPDATE made since the PUSH; record which ones for the history.
        update_ids = (await get_update_ids_for_pushes(db, [original_operation_id])).get(
            original_operation_id, []
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
            params_json={
                "username": user.username,
                "push_operation_id": original_operation_id,
                "update_operation_ids": update_ids,
            },
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

        # Broadcast operation creation via WebSocket
        await self._broadcast_operation_update(operation, user.username)

        return operation

    async def _execute_push_operation(
        self,
        operation: Operation,
        worker: Worker,
        db: AsyncSession,
    ) -> WorkerCommandResponse:
        """
        Execute PUSH operation on worker with transactional rollback on failure.

        Steps:
        1. Copy directory from source to PATH_B (respecting flatten/ignore settings)
           → If fails: raise error, PATH_A untouched
        2a. [archive=True] Move entire PATH_A source to PATH_C
           → If fails: rollback Step 1 (delete PATH_B copy), raise error, PATH_A untouched
        2b. [archive=True, after Step 2 success] Cleanup PATH_C: remove subfolders/ignored
           (best-effort, non-fatal — PATH_A is never touched by cleanup)
        3.  [archive=False] Delete PATH_A entirely
           → If fails: rollback Step 1 (delete PATH_B copy), raise error, PATH_A untouched

        Critical guarantee: PATH_A is NEVER modified until both Step 1 (copy to B) AND
        Step 2 (archive/delete A) have both succeeded.

        Args:
            operation: PUSH operation to execute
            worker: Worker to execute on
            db: Database session

        Returns:
            WorkerCommandResponse from worker
        """
        # Read push settings from DB (runtime source of truth)
        push_config_keys = ['enable_push_flatten', 'enable_push_archive', 'push_ignore_file_masks']
        stmt = select(Config).where(Config.key.in_(push_config_keys))
        result = await db.execute(stmt)
        push_config = {c.key: c.value for c in result.scalars()}

        flatten = push_config.get("enable_push_flatten", "false").lower() == "true"
        archive = push_config.get("enable_push_archive", "false").lower() == "true"
        ignore_masks_str = push_config.get("push_ignore_file_masks", "Thumbs.db")
        ignore_masks = [m.strip() for m in ignore_masks_str.split(",") if m.strip()]

        logger.info(
            f"Executing PUSH operation {operation.id}: "
            f"{operation.source_path} -> {operation.dest_path} "
            f"(flatten={flatten}, archive={archive}, ignore_masks={ignore_masks})"
        )

        # Update worker status
        await self._update_worker_status(
            operation, worker, OperationStatus.IN_PROGRESS, db
        )

        copy_completed = False

        try:
            # Verify source directory exists before proceeding
            # This prevents race conditions where another user already moved/deleted the directory
            verify_command = WorkerRequest(
                command="list",
                params={"path": operation.source_path},
            )
            verify_response = await self.worker_service.send_command(
                worker, verify_command, db
            )

            if verify_response.status != "success":
                raise OperationError(
                    f"Source directory {operation.source_path} does not exist or is not accessible. "
                    f"It may have been moved or deleted by another operation."
                )

            logger.info(f"PUSH: Verified source directory {operation.source_path} exists")

            # Step 1: Copy to PATH_B (with optional flatten and ignore_masks)
            copy_params = {}
            if flatten:
                copy_params["flatten"] = True
            if ignore_masks:
                copy_params["ignore_masks"] = ignore_masks

            logger.info(f"PUSH Step 1: Copying {operation.source_path} to {operation.dest_path} (params={copy_params})")
            copy_command = WorkerRequest(
                command="copy",
                source_path=operation.source_path,
                dest_path=operation.dest_path,
                params=copy_params if copy_params else None,
            )
            copy_response = await self.worker_service.send_command(worker, copy_command, db)

            # Validate copy completed successfully
            if copy_response.status != "success":
                raise OperationError(f"PUSH Step 1 failed: Copy to PATH_B failed: {copy_response.message}")

            if not copy_response.file_count:
                logger.warning(
                    f"PUSH Step 1: Worker did not report file_count "
                    f"(got {copy_response.file_count}). Proceeding based on success status."
                )

            copy_completed = True
            logger.info(f"PUSH Step 1 completed: {copy_response.file_count} files, {copy_response.total_size_bytes} bytes")

            # Step 2: Archive to PATH_C or delete source (PATH_A is NOT touched before this)
            if archive:
                # Step 2: Move entire PATH_A source to PATH_C (archive)
                logger.info(f"PUSH Step 2: Archiving {operation.source_path} to {operation.archive_path}")
                try:
                    archive_response = await self.worker_service.move_file(
                        worker, operation.source_path, operation.archive_path, db
                    )

                    # Validate archive completed
                    if archive_response.status != "success":
                        raise OperationError(f"PUSH Step 2 failed: Move to PATH_C failed: {archive_response.message}")

                    if not archive_response.file_count:
                        logger.warning(
                            f"PUSH Step 2: Worker did not report file_count "
                            f"(got {archive_response.file_count}). Proceeding based on success status."
                        )

                except Exception as step2_exc:
                    # CRITICAL: Step 2 failed, rollback Step 1 (delete from PATH_B)
                    # PATH_A is still intact at this point
                    logger.error(f"PUSH Step 2 failed: {step2_exc}. Rolling back Step 1 (deleting from PATH_B)...")

                    try:
                        rollback_response = await self.worker_service.delete_file(
                            worker, operation.dest_path, db, recursive=True
                        )
                        if rollback_response.status == "success":
                            logger.info(f"Successfully rolled back Step 1: Deleted {operation.dest_path} from PATH_B")
                        else:
                            logger.error(
                                f"Rollback of Step 1 failed: Could not delete {operation.dest_path} from PATH_B. "
                                f"MANUAL CLEANUP REQUIRED!"
                            )
                    except Exception as rollback_exc:
                        logger.error(
                            f"CRITICAL: Rollback of Step 1 failed with exception: {rollback_exc}. "
                            f"PATH_B may contain partial data at {operation.dest_path}. "
                            f"MANUAL CLEANUP REQUIRED!"
                        )

                    raise OperationError(
                        f"PUSH Step 2 (archive to PATH_C) failed: {step2_exc}. "
                        f"Step 1 (copy to PATH_B) has been rolled back. PATH_A is untouched."
                    )

                # Step 2 succeeded: PATH_A is now in PATH_C.
                # Step 2b: Cleanup PATH_C (best-effort, non-fatal).
                # PATH_A is no longer modified — we clean the archive copy only.
                if flatten or ignore_masks:
                    try:
                        cleanup_command = WorkerRequest(
                            command="push_cleanup",
                            source_path=operation.archive_path,
                            params={"flatten": flatten, "ignore_masks": ignore_masks},
                        )
                        cleanup_response = await self.worker_service.send_command(worker, cleanup_command, db)
                        if cleanup_response.status != "success":
                            logger.warning(f"PUSH archive cleanup reported issues: {cleanup_response.message}")
                        else:
                            logger.info(f"PUSH Step 2b: Archive (PATH_C) cleanup completed")
                    except Exception as cleanup_exc:
                        logger.warning(f"PUSH archive cleanup failed (non-fatal): {cleanup_exc}")

                # Both steps completed successfully
                total_files = (copy_response.file_count or 0) + (archive_response.file_count or 0)
                total_size = (copy_response.total_size_bytes or 0) + (archive_response.total_size_bytes or 0)
            else:
                # Step 2: Delete source (no archive) — Step 1.5 is redundant since
                # entire source is deleted here anyway
                logger.info(f"PUSH Step 2: Deleting source {operation.source_path} (archiving disabled)")
                try:
                    delete_response = await self.worker_service.delete_file(
                        worker, operation.source_path, db, recursive=True
                    )

                    if delete_response.status != "success":
                        raise OperationError(f"PUSH Step 2 failed: Delete source failed: {delete_response.message}")

                except Exception as step2_exc:
                    # CRITICAL: Step 2 failed, rollback Step 1
                    # PATH_A is still intact at this point
                    logger.error(f"PUSH Step 2 (delete source) failed: {step2_exc}. Rolling back Step 1 (deleting from PATH_B)...")

                    try:
                        rollback_response = await self.worker_service.delete_file(
                            worker, operation.dest_path, db, recursive=True
                        )
                        if rollback_response.status == "success":
                            logger.info(f"Successfully rolled back Step 1: Deleted {operation.dest_path} from PATH_B")
                        else:
                            logger.error(
                                f"Rollback of Step 1 failed: Could not delete {operation.dest_path} from PATH_B. "
                                f"MANUAL CLEANUP REQUIRED!"
                            )
                    except Exception as rollback_exc:
                        logger.error(
                            f"CRITICAL: Rollback of Step 1 failed with exception: {rollback_exc}. "
                            f"PATH_B may contain partial data at {operation.dest_path}. "
                            f"MANUAL CLEANUP REQUIRED!"
                        )

                    raise OperationError(
                        f"PUSH Step 2 (delete source) failed: {step2_exc}. "
                        f"Step 1 (copy to PATH_B) has been rolled back. PATH_A is untouched."
                    )

                total_files = copy_response.file_count or 0
                total_size = copy_response.total_size_bytes or 0

            # Update operation metadata
            operation.file_count = total_files
            operation.total_size_bytes = total_size

            # Update worker status
            await self._update_worker_status(
                operation, worker, OperationStatus.COMPLETED, db
            )

            step2_desc = f"archived to {operation.archive_path}" if archive else "source deleted"
            logger.info(f"PUSH operation {operation.id} completed: {total_files} files, {total_size} bytes")

            # Return combined response
            return WorkerCommandResponse(
                status="success",
                message=f"PUSH completed: copied to {operation.dest_path}, {step2_desc}",
                file_count=total_files,
                total_size_bytes=total_size,
            )

        except WorkerCommunicationError as exc:
            # If Step 1 completed but Step 2 failed, the rollback would have already happened above
            await self._update_worker_status(
                operation, worker, OperationStatus.FAILED, db, str(exc)
            )
            raise OperationError(f"PUSH operation failed: {exc}")
        except Exception as exc:
            # Unexpected error - may need manual cleanup
            if copy_completed:
                logger.error(
                    f"PUSH operation {operation.id} failed after Step 1 completed. "
                    f"PATH_B may contain data at {operation.dest_path}. "
                    f"Consider manual cleanup or investigation."
                )
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
        Execute PULL operation on worker with transactional rollback on failure.

        Steps:
        1. Copy directory from PATH_B back to original location
        2. Delete directory from PATH_B

        If Step 2 fails, Step 1 is NOT rolled back (restored data remains).
        This is safer - we'd rather have duplicate data than lost data.

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

        copy_completed = False

        try:
            # Verify source exists in PATH_B before proceeding
            verify_command = WorkerRequest(
                command="list",
                params={"path": operation.source_path},
            )
            verify_response = await self.worker_service.send_command(
                worker, verify_command, db
            )

            if verify_response.status != "success":
                raise OperationError(
                    f"Source directory {operation.source_path} does not exist in PATH_B. "
                    f"Cannot restore - data may have been already pulled or manually deleted."
                )

            logger.info(f"PULL: Verified source directory {operation.source_path} exists in PATH_B")

            # Step 1: Copy from PATH_B to original location
            logger.info(f"PULL Step 1: Copying {operation.source_path} to {operation.dest_path}")
            copy_response = await self.worker_service.copy_file(
                worker, operation.source_path, operation.dest_path, db
            )

            # Validate copy completed successfully
            if copy_response.status != "success":
                raise OperationError(f"PULL Step 1 failed: Copy from PATH_B failed: {copy_response.message}")

            if not copy_response.file_count:
                logger.warning(
                    f"PULL Step 1: Worker did not report file_count "
                    f"(got {copy_response.file_count}). Proceeding based on success status."
                )

            copy_completed = True
            logger.info(f"PULL Step 1 completed: {copy_response.file_count} files restored")

            # Step 2: Delete from PATH_B (only if Step 1 succeeded)
            logger.info(f"PULL Step 2: Deleting {operation.source_path} from PATH_B")
            try:
                delete_response = await self.worker_service.delete_file(
                    worker, operation.source_path, db, recursive=True
                )

                if delete_response.status != "success":
                    logger.warning(
                        f"PULL Step 2 failed: Could not delete {operation.source_path} from PATH_B. "
                        f"Data was successfully restored to {operation.dest_path}, but PATH_B still contains data. "
                        f"Manual cleanup may be required."
                    )
                    # Don't raise - restore succeeded, cleanup failed is acceptable
            except Exception as step2_exc:
                logger.warning(
                    f"PULL Step 2 failed with exception: {step2_exc}. "
                    f"Data was successfully restored to {operation.dest_path}, but PATH_B still contains data at {operation.source_path}. "
                    f"Manual cleanup may be required."
                )
                # Don't raise - restore succeeded, cleanup failed is acceptable

            # Update operation metadata (from Step 1 - the restore)
            operation.file_count = copy_response.file_count
            operation.total_size_bytes = copy_response.total_size_bytes

            # Update worker status
            await self._update_worker_status(
                operation, worker, OperationStatus.COMPLETED, db
            )

            logger.info(
                f"PULL operation {operation.id} completed: "
                f"{copy_response.file_count} files restored to {operation.dest_path}"
            )

            # Return response
            return WorkerCommandResponse(
                status="success",
                message=f"PULL completed: restored {copy_response.file_count} files to {operation.dest_path}",
                file_count=copy_response.file_count,
                total_size_bytes=copy_response.total_size_bytes,
            )

        except WorkerCommunicationError as exc:
            error_msg = str(exc)
            if copy_completed:
                error_msg = (
                    f"PULL partially completed: Data restored to {operation.dest_path}, "
                    f"but cleanup from PATH_B failed. Original error: {exc}"
                )
            await self._update_worker_status(
                operation, worker, OperationStatus.FAILED, db, error_msg
            )
            raise OperationError(f"PULL operation failed: {error_msg}")
        except Exception as exc:
            error_msg = str(exc)
            if copy_completed:
                error_msg = (
                    f"PULL partially completed: Data restored to {operation.dest_path}, "
                    f"but cleanup from PATH_B failed. Original error: {exc}"
                )
            await self._update_worker_status(
                operation, worker, OperationStatus.FAILED, db, error_msg
            )
            raise OperationError(f"PULL operation failed: {error_msg}")

    # ------------------------------------------------------------------
    # UPDATE operation
    # ------------------------------------------------------------------

    @staticmethod
    def _join_catalog_path(catalog_path: str, relative: str) -> str:
        """
        Join a relative entry onto a catalog root using worker path syntax.

        Relative paths are already confirmed to be catalog-local by
        ``validate_update_actions``; this only normalises separators.
        """
        rel = str(relative).replace('\\', '/').strip('/')
        return f"{catalog_path.rstrip('/')}/{rel}"

    async def create_update_operation(
        self,
        user: User,
        catalog_path: str,
        actions: list,
        worker_id: int,
        db: AsyncSession,
        catalog_name: Optional[str] = None,
        predicted_files: Optional[list] = None,
        push_operation_id: Optional[int] = None,
    ) -> Operation:
        """
        Create an UPDATE operation against an already-pushed catalog.

        UPDATE changes the contents of a catalog that already lives in PATH_B:
        renaming or moving entries within it, replacing or adding files (from
        Path A or an upload), and deleting entries. When
        ``enable_update_archive_mirror`` is on, the same changes are replayed
        against the PATH_C archive copy.

        Validation (catalog name + resulting content) is performed by the
        caller before this point, and its results are carried in params_json
        so the PIM signal needs no extra worker round-trip. ``actions`` is also
        the history record of the operation, so callers enrich upload actions
        with the uploaded file's name, size and SHA-256.
        """
        worker = await get_worker_by_id(worker_id, db)
        if not worker:
            raise OperationError(f"Worker {worker_id} not found")

        stmt = select(Config).where(Config.key == 'enable_update_archive_mirror')
        result = await db.execute(stmt)
        row = result.scalars().first()
        mirror_enabled = bool(row) and (row.value or '').lower() == 'true'

        import os
        resolved_name = catalog_name or os.path.basename(catalog_path.rstrip('/\\'))

        archive_path = None
        if mirror_enabled:
            path_c = worker.path_c_prefix or self.settings.path_c
            if not path_c:
                raise OperationError(
                    f"PATH_C not configured for worker '{worker.name}' but UPDATE "
                    "archive mirroring is enabled. Configure it in Admin Panel -> "
                    "System -> Worker Configuration or set PATH_C in .env."
                )
            archive_path = f"C:/{resolved_name}"

        operation = Operation(
            user_id=user.id,
            type=OperationType.UPDATE,
            source_path=catalog_path,
            dest_path=catalog_path,  # in-place
            archive_path=archive_path,
            status=OperationStatus.PENDING,
            params_json={
                "actions": actions,
                "catalog_name": resolved_name,
                "files": predicted_files or [],
                "username": user.username,
                "archive_mirror": mirror_enabled,
                "push_operation_id": push_operation_id,
            },
        )
        db.add(operation)
        await db.flush()

        db.add(OperationWorker(
            operation_id=operation.id,
            worker_id=worker_id,
            worker_status=OperationStatus.PENDING,
        ))

        await db.commit()
        await db.refresh(operation)

        logger.info(
            f"Created UPDATE operation {operation.id} by user '{user.username}' on "
            f"catalog {resolved_name!r} ({catalog_path}, PUSH {push_operation_id}): "
            f"{len(actions)} action(s), archive_mirror={mirror_enabled}"
        )

        await self._index_operation_in_elasticsearch(operation, user.username, db)
        await self._broadcast_operation_update(operation, user.username)

        return operation

    @staticmethod
    def _update_staging_path(catalog_path: str, operation_id: int) -> str:
        """Working folder inside the catalog; same share, so swaps are renames."""
        return f"{catalog_path.rstrip('/')}/{UPDATE_STAGING_PREFIX}{operation_id}"

    async def _move_checked(self, worker: Worker, src: str, dst: str, db: AsyncSession, what: str) -> None:
        """Move on the worker; any failure names the step it happened in."""
        try:
            response = await self.worker_service.move_file(worker, src, dst, db)
        except WorkerCommunicationError as exc:
            raise OperationError(f"UPDATE failed {what}: {exc}") from exc
        if response.status != "success":
            raise OperationError(f"UPDATE failed {what}: {response.message}")

    async def _stage_update_content(
        self,
        operation: Operation,
        worker: Worker,
        action: dict,
        staged_path: str,
        db: AsyncSession,
    ) -> None:
        """Place an action's new content at ``staged_path`` without touching the catalog."""
        target = action.get("source") or action["dest"]

        if action.get("from_path"):
            logger.info(f"UPDATE {operation.id}: staging {action['from_path']} for {target}")
            response = await self.worker_service.send_command(
                worker,
                WorkerRequest(command="copy", source_path=action["from_path"], dest_path=staged_path),
                db,
            )
            if response.status != "success":
                raise OperationError(
                    f"UPDATE could not copy {action['from_path']} for {target}: {response.message}"
                )
            return

        from api.services.upload_service import make_download_path

        upload = action.get("upload") or {}
        logger.info(
            f"UPDATE {operation.id}: staging upload {action['upload_id']} "
            f"({upload.get('filename')!r}) for {target}"
        )
        try:
            response = await self.worker_service.send_command(
                worker,
                WorkerRequest(
                    command="fetch_file",
                    dest_path=staged_path,
                    params={
                        "url": make_download_path(self.settings, action["upload_id"], worker.hostname),
                        "sha256": upload.get("sha256"),
                        "size_bytes": upload.get("size_bytes"),
                    },
                ),
                db,
            )
        except WorkerCommunicationError as exc:
            if "Unknown command" in str(exc):
                raise OperationError(
                    f"Worker '{worker.name}' does not support uploaded files yet "
                    "(no fetch_file command); update the worker, or pick the file from Path A."
                ) from exc
            raise
        if response.status != "success":
            raise OperationError(
                f"UPDATE could not transfer uploaded file {upload.get('filename')!r} "
                f"for {target}: {response.message}"
            )

    async def _execute_update_operation(
        self,
        operation: Operation,
        worker: Worker,
        db: AsyncSession,
    ) -> WorkerCommandResponse:
        """
        Execute an UPDATE operation.

        Ordering keeps the catalog recoverable until the last possible moment:

        1. Stage: new content for every replace/add is copied from Path A or
           fetched from the API into a working folder inside the catalog. The
           catalog itself is untouched.
        2. Inspect: the staged files must be plain files whose bytes match their
           extension. A rejection raises ``UpdateContentRejected`` and nothing
           in the catalog has changed.
        3. Rename/move entries.
        4. Swap in new content: a replaced file is first moved into the working
           folder, then the staged file moved into its place.
        5. Delete entries - the only irreversible step, so it runs last.

        A failure in steps 1-5 moves everything applied so far back, in reverse
        order, and removes the working folder. After success the working folder
        (holding the previous versions of replaced files) is removed, Path A
        sources marked ``remove_source`` are deleted, and, when enabled, the
        changes are mirrored to PATH_C. Those three are best-effort: the
        catalog is already correct, so their failures become warnings recorded
        on the operation instead of failing it.
        """
        from api.services.content_validation_service import CONTENT_ACTIONS, inspect_staged_files

        params = operation.params_json or {}
        actions = [dict(a) for a in (params.get("actions") or [])]
        username = params.get("username") or "unknown"
        catalog_path = operation.source_path
        staging = self._update_staging_path(catalog_path, operation.id)

        moves = [a for a in actions if a.get("action") in ("move", "rename")]
        contents = [(i, a) for i, a in enumerate(actions) if a.get("action") in CONTENT_ACTIONS]
        deletes = [a for a in actions if a.get("action") == "delete"]

        logger.info(
            f"Executing UPDATE operation {operation.id} by user '{username}' on "
            f"{catalog_path}: {len(moves)} move/rename, "
            f"{sum(1 for _, a in contents if a['action'] == 'replace')} replace, "
            f"{sum(1 for _, a in contents if a['action'] == 'add')} add, {len(deletes)} delete"
        )

        await self._update_worker_status(
            operation, worker, OperationStatus.IN_PROGRESS, db
        )

        applied = []  # (src, dst) moves already made, undone in reverse order
        staging_used = False
        warnings = []

        try:
            # Confirm the catalog is still there before changing anything
            verify = await self.worker_service.send_command(
                worker, WorkerRequest(command="list", params={"path": catalog_path}), db
            )
            if verify.status != "success":
                raise OperationError(
                    f"Catalog {catalog_path} does not exist or is not accessible. "
                    "It may have been pulled or removed by another operation."
                )

            # Phase 1 - stage new content (catalog untouched)
            staged_names = {}
            for i, action in contents:
                target = action.get("source") or action["dest"]
                staged_names[i] = f"{i:03d}_{target.rsplit('/', 1)[-1]}"
                staging_used = True
                await self._stage_update_content(
                    operation, worker, action, f"{staging}/{staged_names[i]}", db
                )

            # Phase 2 - inspect staged content
            if contents:
                missing, invalid = await inspect_staged_files(
                    worker, staging, list(staged_names.values()), self.worker_service, db
                )
                if missing or invalid:
                    target_of = {
                        staged_names[i]: (a.get("source") or a["dest"]) for i, a in contents
                    }
                    raise UpdateContentRejected(
                        missing=[target_of[n] for n in missing],
                        invalid_files=[{**item, "name": target_of[item["name"]]} for item in invalid],
                    )

            # Phase 3 - renames/moves
            for action in moves:
                src = self._join_catalog_path(catalog_path, action["source"])
                dst = self._join_catalog_path(catalog_path, action["dest"])
                logger.info(f"UPDATE {operation.id}: move {src} -> {dst}")
                await self._move_checked(
                    worker, src, dst, db, f"moving {action['source']} -> {action['dest']}"
                )
                applied.append((src, dst))

            # Phase 4 - swap in new content
            for i, action in contents:
                staged = f"{staging}/{staged_names[i]}"
                if action["action"] == "replace":
                    target = self._join_catalog_path(catalog_path, action["source"])
                    previous = f"{staging}/previous_{staged_names[i]}"
                    logger.info(f"UPDATE {operation.id}: replace {target}")
                    await self._move_checked(
                        worker, target, previous, db, f"setting aside {action['source']}"
                    )
                    applied.append((target, previous))
                    what = f"replacing {action['source']}"
                else:
                    target = self._join_catalog_path(catalog_path, action["dest"])
                    logger.info(f"UPDATE {operation.id}: add {target}")
                    what = f"adding {action['dest']}"
                await self._move_checked(worker, staged, target, db, what)
                applied.append((staged, target))

            # Phase 5 - irreversible deletes, only after everything else succeeded
            for action in deletes:
                target = self._join_catalog_path(catalog_path, action["source"])
                recursive = bool(action.get("recursive", True))
                logger.info(f"UPDATE {operation.id}: delete {target}")
                response = await self.worker_service.delete_file(
                    worker, target, db, recursive
                )
                if response.status != "success":
                    raise OperationError(
                        f"UPDATE failed deleting {action['source']}: {response.message}"
                    )

        except Exception as exc:
            # Unwind whatever reversible work already landed
            if applied:
                logger.warning(
                    f"UPDATE operation {operation.id} failed; reverting "
                    f"{len(applied)} move(s)"
                )
                for src, dst in reversed(applied):
                    try:
                        await self.worker_service.move_file(worker, dst, src, db)
                        logger.info(f"UPDATE {operation.id}: reverted {dst} -> {src}")
                    except Exception as revert_exc:
                        logger.error(
                            f"UPDATE {operation.id}: could not revert {dst} -> {src}: "
                            f"{revert_exc}"
                        )
            if staging_used:
                await self._remove_update_staging(operation, worker, staging, db)

            await self._update_worker_status(
                operation, worker, OperationStatus.FAILED, db, str(exc)
            )
            raise

        logger.info(
            f"UPDATE operation {operation.id} applied {len(actions)} action(s) "
            f"to PATH_B by user '{username}'"
        )

        # Previous versions of replaced files live in the working folder
        if staging_used and not await self._remove_update_staging(operation, worker, staging, db):
            warnings.append(f"Working folder {staging} could not be removed; delete it manually.")

        # Remove Path A sources the user asked to consume (each path once)
        removed = {}
        for action in actions:
            path = action.get("from_path")
            if not action.get("remove_source") or not path:
                continue
            if path not in removed:
                try:
                    response = await self.worker_service.delete_file(worker, path, db, recursive=False)
                    removed[path] = response.status == "success"
                except Exception as exc:
                    logger.warning(f"UPDATE {operation.id}: could not remove {path}: {exc}")
                    removed[path] = False
                if removed[path]:
                    logger.info(f"UPDATE {operation.id}: removed source {path} from Path A")
                else:
                    warnings.append(f"{path} could not be removed from Path A.")
            action["source_removed"] = removed[path]

        if operation.archive_path:
            warnings.extend(await self._mirror_update_to_archive(
                operation, worker, actions, db
            ))

        # Reassign so SQLAlchemy persists the per-action results and warnings
        operation.params_json = {**params, "actions": actions, "warnings": warnings}

        return WorkerCommandResponse(
            status="success",
            message=f"UPDATE completed: {len(actions)} action(s)",
            file_count=len(actions),
        )

    async def _remove_update_staging(
        self, operation: Operation, worker: Worker, staging: str, db: AsyncSession
    ) -> bool:
        """Delete the UPDATE working folder. Best-effort; returns success."""
        try:
            response = await self.worker_service.delete_file(worker, staging, db, recursive=True)
            if response.status == "success":
                return True
            message = response.message
        except Exception as exc:
            message = str(exc)
        # Never created (e.g. the first staging copy failed) is not a problem
        if "not found" in (message or "").lower():
            return True
        logger.error(f"UPDATE {operation.id}: could not remove working folder {staging}: {message}")
        return False

    async def _mirror_update_to_archive(
        self,
        operation: Operation,
        worker: Worker,
        actions: list,
        db: AsyncSession,
    ) -> list:
        """
        Replay UPDATE actions against the PATH_C archive copy.

        Best-effort by design: PATH_B is the live copy and has already been
        updated successfully by the time this runs, so a stale or missing
        archive must not fail the user's operation. Every failure is logged
        and returned as a warning. New content is copied from its final place
        in PATH_B, so the archive receives exactly what the catalog now holds.
        """
        archive_path = operation.archive_path
        catalog_path = operation.source_path
        logger.info(
            f"UPDATE {operation.id}: mirroring {len(actions)} action(s) to archive {archive_path}"
        )

        try:
            verify = await self.worker_service.send_command(
                worker, WorkerRequest(command="list", params={"path": archive_path}), db
            )
            if verify.status != "success":
                logger.warning(
                    f"UPDATE {operation.id}: archive copy {archive_path} not found; "
                    "skipping mirror"
                )
                return [f"Archive copy {archive_path} not found; changes were not mirrored."]
        except Exception as exc:
            logger.warning(
                f"UPDATE {operation.id}: could not inspect archive {archive_path}: "
                f"{exc}; skipping mirror"
            )
            return [f"Archive copy {archive_path} could not be inspected; changes were not mirrored."]

        failures = []
        ordered = (
            [a for a in actions if a["action"] in ("move", "rename")]
            + [a for a in actions if a["action"] in ("replace", "add")]
            + [a for a in actions if a["action"] == "delete"]
        )
        for action in ordered:
            kind = action["action"]
            try:
                if kind in ("move", "rename"):
                    await self.worker_service.move_file(
                        worker,
                        self._join_catalog_path(archive_path, action["source"]),
                        self._join_catalog_path(archive_path, action["dest"]),
                        db,
                    )
                elif kind in ("replace", "add"):
                    entry = action.get("source") or action["dest"]
                    await self.worker_service.copy_file(
                        worker,
                        self._join_catalog_path(catalog_path, entry),
                        self._join_catalog_path(archive_path, entry),
                        db,
                    )
                else:
                    await self.worker_service.delete_file(
                        worker,
                        self._join_catalog_path(archive_path, action["source"]),
                        db,
                        bool(action.get("recursive", True)),
                    )
            except Exception as exc:
                entry = action.get("source") or action.get("dest")
                logger.error(
                    f"UPDATE {operation.id}: archive mirror failed to {kind} {entry}: {exc}"
                )
                failures.append(f"Archive mirror failed to {kind} {entry}.")

        logger.info(f"UPDATE {operation.id}: archive mirror pass completed")
        return failures
