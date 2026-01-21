"""
Log handlers for different destinations.

Implements:
- FileHandler: JSON logs to local file with rotation
- DatabaseHandler: Logs to audit_logs table (async)
- SyslogHandler: RFC 5424 syslog messages (async, non-blocking)
- ExternalAPIHandler: HTTP POST to Sybase API (async with retry)
"""

import asyncio
import socket
from pathlib import Path
from typing import Optional

import aiofiles
import httpx
from loguru import logger
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from database import DatabaseManager
from logging_module.models import (
    LogEntry,
    AuditLogEntry,
    SyslogMessage,
    ExternalAPILogRequest,
)
from logging_module.rotation import LogRotator
from logging_module.utils import (
    format_log_line,
    get_hostname,
    sanitize_log_data,
    CircularBuffer,
)
from models import AuditLog


class FileHandler:
    """
    Asynchronous file logging handler.

    Writes JSON logs to local file with automatic rotation.
    """

    def __init__(self, log_file: str, rotator: Optional[LogRotator] = None):
        """
        Initialize file handler.

        Args:
            log_file: Path to log file
            rotator: Optional log rotator for automatic rotation
        """
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.rotator = rotator
        self._lock = asyncio.Lock()

    async def write_log(self, log_entry: LogEntry) -> None:
        """
        Write log entry to file.

        Args:
            log_entry: Log entry to write
        """
        async with self._lock:
            try:
                # Check rotation before writing
                if self.rotator:
                    self.rotator.rotate_if_needed(self.log_file)

                # Write log line
                log_line = format_log_line(log_entry.to_json_dict())

                async with aiofiles.open(self.log_file, mode="a") as f:
                    await f.write(log_line)

            except Exception as exc:
                logger.error(f"Failed to write log to file: {exc}")

    async def flush(self) -> None:
        """Flush is automatic with aiofiles."""
        pass


class DatabaseHandler:
    """
    Asynchronous database logging handler.

    Writes logs to audit_logs table (immutable, INSERT only).
    """

    def __init__(self):
        """Initialize database handler."""
        pass

    async def write_log(self, log_entry: LogEntry) -> None:
        """
        Write log entry to database.

        Args:
            log_entry: Log entry to write
        """
        try:
            async with DatabaseManager.session() as db:
                # Create audit log entry
                audit_log = AuditLog(
                    user_id=log_entry.user_id,
                    operation_id=log_entry.operation_id,
                    action=log_entry.action,
                    details_json=log_entry.details,
                    ip_address=log_entry.ip_address,
                    user_agent=log_entry.user_agent,
                    timestamp=log_entry.timestamp,
                )

                db.add(audit_log)
                await db.commit()

        except Exception as exc:
            logger.error(f"Failed to write log to database: {exc}")

    async def flush(self) -> None:
        """Database commits are immediate."""
        pass


class SyslogHandler:
    """
    Asynchronous syslog handler.

    Sends RFC 5424 structured syslog messages (UDP or TCP).
    Non-blocking with circular buffer for failed sends.
    """

    def __init__(
        self,
        host: str,
        port: int = 514,
        protocol: str = "UDP",
        buffer_size: int = 1000,
    ):
        """
        Initialize syslog handler.

        Args:
            host: Syslog server hostname
            port: Syslog server port
            protocol: "UDP" or "TCP"
            buffer_size: Circular buffer size for failed sends
        """
        self.host = host
        self.port = port
        self.protocol = protocol.upper()
        self.buffer = CircularBuffer(max_size=buffer_size)
        self._socket: Optional[socket.socket] = None
        self._lock = asyncio.Lock()

    def _get_socket(self) -> socket.socket:
        """
        Get or create socket connection.

        Returns:
            Socket for syslog communication
        """
        if self._socket is None:
            if self.protocol == "UDP":
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            elif self.protocol == "TCP":
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._socket.connect((self.host, self.port))
            else:
                raise ValueError(f"Invalid protocol: {self.protocol}")

        return self._socket

    async def write_log(self, log_entry: LogEntry) -> None:
        """
        Send log entry to syslog server.

        Args:
            log_entry: Log entry to send
        """
        async with self._lock:
            try:
                # Create syslog message
                syslog_msg = SyslogMessage(
                    hostname=get_hostname(),
                    structured_data={
                        "user_id": log_entry.user_id or "-",
                        "operation_id": log_entry.operation_id or "-",
                        "action": log_entry.action,
                        "level": log_entry.level.value,
                    },
                    message=log_entry.message,
                )

                # Format as RFC 5424
                message_str = syslog_msg.to_rfc5424()
                message_bytes = message_str.encode("utf-8")

                # Send to syslog server
                sock = self._get_socket()

                if self.protocol == "UDP":
                    sock.sendto(message_bytes, (self.host, self.port))
                elif self.protocol == "TCP":
                    sock.sendall(message_bytes + b"\n")

            except Exception as exc:
                # Buffer log for retry
                self.buffer.add(log_entry.to_json_dict())
                logger.error(f"Failed to send log to syslog: {exc}")

    async def flush(self) -> None:
        """Attempt to flush buffered logs."""
        buffered_logs = self.buffer.get_all()

        for log_data in buffered_logs:
            try:
                # Reconstruct LogEntry from buffered data
                log_entry = LogEntry(**log_data)
                await self.write_log(log_entry)
            except Exception:
                pass  # Keep in buffer for next flush

        if not buffered_logs:
            self.buffer.clear()

    def close(self) -> None:
        """Close socket connection."""
        if self._socket:
            self._socket.close()
            self._socket = None


class ExternalAPIHandler:
    """
    Asynchronous external API handler for Sybase log export.

    Sends logs via HTTP POST with retry logic and exponential backoff.
    Non-blocking with circular buffer for failed sends.
    """

    def __init__(
        self,
        api_url: str,
        api_token: Optional[str] = None,
        timeout: int = 5,
        retries: int = 3,
        buffer_size: int = 1000,
    ):
        """
        Initialize external API handler.

        Args:
            api_url: API endpoint URL
            api_token: Optional authentication token
            timeout: Request timeout in seconds
            retries: Number of retry attempts
            buffer_size: Circular buffer size for failed sends
        """
        self.api_url = api_url
        self.api_token = api_token
        self.timeout = timeout
        self.retries = retries
        self.buffer = CircularBuffer(max_size=buffer_size)
        self._lock = asyncio.Lock()

    async def write_log(self, log_entry: LogEntry) -> None:
        """
        Send log entry to external API.

        Args:
            log_entry: Log entry to send
        """
        async with self._lock:
            # Prepare request payload
            request = ExternalAPILogRequest(
                timestamp=log_entry.timestamp.isoformat(),
                user_id=log_entry.user_id,
                operation_id=log_entry.operation_id,
                action=log_entry.action,
                details=sanitize_log_data(log_entry.details or {}),
                level=log_entry.level.value,
            )

            # Retry with exponential backoff
            retry_delays = [1, 2, 4]  # seconds

            for attempt in range(self.retries):
                try:
                    await self._send_request(request)
                    return  # Success!

                except httpx.TimeoutException:
                    logger.warning(
                        f"External API timeout (attempt {attempt + 1}/{self.retries})"
                    )

                except httpx.HTTPError as exc:
                    logger.warning(
                        f"External API HTTP error (attempt {attempt + 1}/{self.retries}): {exc}"
                    )

                except Exception as exc:
                    logger.error(
                        f"External API error (attempt {attempt + 1}/{self.retries}): {exc}"
                    )

                # Wait before retry (exponential backoff)
                if attempt < self.retries - 1:
                    delay = retry_delays[attempt] if attempt < len(retry_delays) else retry_delays[-1]
                    await asyncio.sleep(delay)

            # All retries failed - buffer for later
            self.buffer.add(log_entry.to_json_dict())
            logger.error(f"Failed to send log to external API after {self.retries} attempts")

    async def _send_request(self, request: ExternalAPILogRequest) -> None:
        """
        Send HTTP POST request to API.

        Args:
            request: Log request to send

        Raises:
            httpx.HTTPError: If request fails
        """
        headers = {"Content-Type": "application/json"}

        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.api_url,
                json=request.model_dump(),
                headers=headers,
            )

            response.raise_for_status()

    async def flush(self) -> None:
        """Attempt to flush buffered logs."""
        buffered_logs = self.buffer.get_all()
        successful = []

        for log_data in buffered_logs:
            try:
                # Reconstruct LogEntry and send
                log_entry = LogEntry(**log_data)
                await self.write_log(log_entry)
                successful.append(log_data)
            except Exception:
                pass  # Keep in buffer

        # Remove successful entries from buffer
        for log_data in successful:
            try:
                self.buffer.buffer.remove(log_data)
            except ValueError:
                pass


class MultiHandler:
    """
    Composite handler that writes to multiple destinations.

    Coordinates file, database, syslog, and external API logging.
    """

    def __init__(self):
        """Initialize multi-handler."""
        self.handlers: list = []

    def add_handler(self, handler) -> None:
        """
        Add handler to the list.

        Args:
            handler: Handler instance to add
        """
        self.handlers.append(handler)

    async def write_log(self, log_entry: LogEntry) -> None:
        """
        Write log to all handlers concurrently.

        Args:
            log_entry: Log entry to write
        """
        # Write to all handlers in parallel
        tasks = [handler.write_log(log_entry) for handler in self.handlers]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def flush(self) -> None:
        """Flush all handlers."""
        tasks = [handler.flush() for handler in self.handlers]
        await asyncio.gather(*tasks, return_exceptions=True)

    def close(self) -> None:
        """Close all handlers."""
        for handler in self.handlers:
            if hasattr(handler, "close"):
                handler.close()
