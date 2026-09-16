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
from database import get_db_session


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

                async with get_db_session() as db:
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

        Marks ACTIVE workers as OFFLINE when their last heartbeat is older than
        the worker_heartbeat_timeout config value. OFFLINE workers return to
        ACTIVE on their own when they check in again; SUSPENDED is reserved for
        administrators and is never set here.
        """
        from api.middleware.logging import AuditLogger
        from api.services.worker_service import (
            get_worker_heartbeat_timeout,
            mark_stale_workers_offline,
        )

        interval = 60  # Check every minute

        while self._running:
            try:
                await asyncio.sleep(interval)

                if not self._running:
                    break

                logger.debug("Checking worker health...")

                async with get_db_session() as db:
                    heartbeat_timeout = await get_worker_heartbeat_timeout(db)
                    offline_workers = await mark_stale_workers_offline(db, heartbeat_timeout)

                for worker_id, worker_name, last_heartbeat in offline_workers:
                    logger.warning(
                        f"Worker {worker_name} marked as OFFLINE "
                        f"(last heartbeat: {last_heartbeat}, timeout: {heartbeat_timeout}s)"
                    )
                    await AuditLogger.log_admin_action(
                        user_id=None,
                        action="worker_offline",
                        target="worker",
                        details={
                            "worker_id": worker_id,
                            "worker_name": worker_name,
                            "last_heartbeat": last_heartbeat.isoformat() if last_heartbeat else None,
                            "heartbeat_timeout": heartbeat_timeout,
                        },
                    )

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
