"""
Background tasks for maintenance and cleanup.

Includes:
- Worker command queue cleanup
- Stale worker detection
- Metrics collection
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import Settings
from api.services.command_queue_service import CommandQueueService
from database import get_db_context


class BackgroundTaskManager:
    """
    Manages background maintenance tasks.

    Tasks run periodically to clean up old data and maintain system health.
    """

    def __init__(self, settings: Settings):
        """
        Initialize background task manager.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.command_queue = CommandQueueService(settings)
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self):
        """Start all background tasks."""
        if self._running:
            logger.warning("Background tasks already running")
            return

        self._running = True

        # Start cleanup tasks
        self._tasks.append(asyncio.create_task(self._command_cleanup_loop()))
        self._tasks.append(asyncio.create_task(self._worker_health_check_loop()))

        logger.info("Background tasks started")

    async def stop(self):
        """Stop all background tasks."""
        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete
        await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()
        logger.info("Background tasks stopped")

    async def _command_cleanup_loop(self):
        """
        Periodic cleanup of old worker commands.

        Runs every 6 hours and removes completed/failed commands older than 7 days.
        """
        interval = 6 * 60 * 60  # 6 hours
        retention_days = 7

        while self._running:
            try:
                await asyncio.sleep(interval)

                if not self._running:
                    break

                logger.info("Running command queue cleanup...")

                async with get_db_context() as db:
                    count = await self.command_queue.cleanup_old_commands(
                        db,
                        days=retention_days
                    )

                if count > 0:
                    logger.info(f"Cleaned up {count} old commands")
                else:
                    logger.debug("No old commands to clean up")

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in command cleanup loop: {exc}")

    async def _worker_health_check_loop(self):
        """
        Periodic worker health check.

        Marks workers as SUSPENDED if no heartbeat for 5 minutes.
        """
        interval = 60  # Check every minute
        heartbeat_timeout = 5 * 60  # 5 minutes

        while self._running:
            try:
                await asyncio.sleep(interval)

                if not self._running:
                    break

                logger.debug("Checking worker health...")

                async with get_db_context() as db:
                    from models import Worker, WorkerStatus
                    from sqlalchemy import select, and_

                    # Find active workers with stale heartbeats
                    cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=heartbeat_timeout)

                    stmt = select(Worker).where(
                        and_(
                            Worker.status == WorkerStatus.ACTIVE,
                            Worker.last_heartbeat < cutoff_time
                        )
                    )

                    result = await db.execute(stmt)
                    stale_workers = result.scalars().all()

                    for worker in stale_workers:
                        logger.warning(
                            f"Worker {worker.name} marked as SUSPENDED "
                            f"(last heartbeat: {worker.last_heartbeat})"
                        )
                        worker.status = WorkerStatus.SUSPENDED
                        await db.commit()

                    if stale_workers:
                        logger.info(f"Marked {len(stale_workers)} workers as SUSPENDED")

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in worker health check loop: {exc}")


# Global background task manager instance
_task_manager: Optional[BackgroundTaskManager] = None


async def start_background_tasks(settings: Settings):
    """
    Start background task manager.

    Args:
        settings: Application settings
    """
    global _task_manager

    if _task_manager is None:
        _task_manager = BackgroundTaskManager(settings)

    await _task_manager.start()


async def stop_background_tasks():
    """Stop background task manager."""
    global _task_manager

    if _task_manager:
        await _task_manager.stop()
