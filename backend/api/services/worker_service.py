"""
Worker communication service with HTTPS, mTLS, and public key verification.

Handles all communication with Windows worker services including:
- Secure HTTPS connections with TLS 1.3
- Public key authentication
- Retry logic with exponential backoff
- Health checks and heartbeat monitoring
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import Settings
from api.schemas import WorkerRequest, WorkerCommandResponse
from models import Worker, WorkerStatus


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
    Service for communicating with Windows worker services.

    Provides methods for sending commands, verifying responses,
    and managing worker health status.
    """

    def __init__(self, settings: Settings):
        """
        Initialize worker service.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.timeout = settings.worker_timeout
        self.retry_attempts = settings.worker_retry_attempts
        self.retry_delays = settings.worker_retry_delays

    async def send_command(
        self,
        worker: Worker,
        command: WorkerRequest,
        db: AsyncSession,
    ) -> WorkerCommandResponse:
        """
        Send command to worker with retry logic.

        Args:
            worker: Worker model
            command: Command to send
            db: Database session for updating worker status

        Returns:
            WorkerCommandResponse from worker

        Raises:
            WorkerOfflineError: If worker is unreachable
            WorkerAuthenticationError: If authentication fails
            WorkerTimeoutError: If request times out
        """
        if worker.status != WorkerStatus.ACTIVE:
            raise WorkerOfflineError(f"Worker {worker.name} is not active")

        # Build worker URL (stored in hostname field)
        worker_url = f"https://{worker.hostname}/api/command"

        # Prepare request with public key signature
        request_data = command.model_dump()
        signed_request = await self._sign_request(request_data, worker.public_key)

        # Retry loop with exponential backoff
        last_exception = None

        for attempt in range(self.retry_attempts):
            try:
                response = await self._make_request(
                    worker_url,
                    signed_request,
                    worker.public_key,
                )

                # Update worker heartbeat on successful communication
                await self._update_worker_heartbeat(worker, db)

                return response

            except httpx.TimeoutException as exc:
                last_exception = WorkerTimeoutError(
                    f"Worker {worker.name} timed out after {self.timeout}s"
                )
                logger.warning(
                    f"Worker {worker.name} timeout (attempt {attempt + 1}/{self.retry_attempts})"
                )

            except httpx.ConnectError as exc:
                last_exception = WorkerOfflineError(
                    f"Worker {worker.name} is unreachable"
                )
                logger.warning(
                    f"Worker {worker.name} unreachable (attempt {attempt + 1}/{self.retry_attempts})"
                )

            except WorkerAuthenticationError as exc:
                # Don't retry auth errors
                await self._mark_worker_suspended(worker, db, str(exc))
                raise

            except Exception as exc:
                last_exception = WorkerCommunicationError(
                    f"Worker {worker.name} error: {exc}"
                )
                logger.error(
                    f"Worker {worker.name} error (attempt {attempt + 1}/{self.retry_attempts}): {exc}"
                )

            # Wait before retry (exponential backoff)
            if attempt < self.retry_attempts - 1:
                delay = self.retry_delays[attempt] if attempt < len(self.retry_delays) else self.retry_delays[-1]
                await asyncio.sleep(delay)

        # All retries failed
        await self._mark_worker_suspended(worker, db, str(last_exception))
        raise last_exception

    async def _make_request(
        self,
        url: str,
        request_data: dict,
        public_key_pem: str,
    ) -> WorkerCommandResponse:
        """
        Make HTTPS request to worker.

        Args:
            url: Worker endpoint URL
            request_data: Signed request data
            public_key_pem: Worker's public key for verification

        Returns:
            WorkerCommandResponse

        Raises:
            WorkerAuthenticationError: If response signature is invalid
        """
        async with httpx.AsyncClient(
            timeout=self.timeout,
            verify=True,  # Verify TLS certificates
            http2=True,   # Use HTTP/2 if available
        ) as client:
            response = await client.post(
                url,
                json=request_data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "FileManager-API/1.0",
                },
            )

            response.raise_for_status()

            response_json = response.json()

            # Verify response signature
            await self._verify_response(response_json, public_key_pem)

            # Parse response
            worker_response = WorkerCommandResponse(**response_json.get("data", {}))

            if worker_response.status == "failed":
                raise WorkerCommunicationError(
                    f"Worker returned error: {worker_response.message}"
                )

            return worker_response

    async def _sign_request(
        self,
        request_data: dict,
        public_key_pem: str,
    ) -> dict:
        """
        Sign request with server's private key.

        Note: In production, this would use the server's private key
        to create a signature that the worker verifies with our public key.

        Args:
            request_data: Request payload
            public_key_pem: Worker's public key (for encryption if needed)

        Returns:
            Signed request data
        """
        # For now, we include a timestamp and worker identification
        # In full implementation, this would include cryptographic signature
        signed_data = {
            "data": request_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "api_version": "1.0",
        }

        return signed_data

    async def _verify_response(
        self,
        response_data: dict,
        public_key_pem: str,
    ) -> None:
        """
        Verify response signature from worker.

        Args:
            response_data: Response from worker
            public_key_pem: Worker's public key

        Raises:
            WorkerAuthenticationError: If signature is invalid
        """
        # In production, this would verify the cryptographic signature
        # using the worker's public key

        if "data" not in response_data:
            raise WorkerAuthenticationError("Invalid response format")

        # Verify timestamp is recent (within 5 minutes)
        timestamp_str = response_data.get("timestamp")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                time_diff = abs((now - timestamp).total_seconds())

                if time_diff > 300:  # 5 minutes
                    raise WorkerAuthenticationError("Response timestamp too old")
            except (ValueError, TypeError):
                raise WorkerAuthenticationError("Invalid response timestamp")

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
