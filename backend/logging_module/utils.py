"""
Utility functions for structured logging.

Provides JSON encoding, timestamp handling, and log sanitization.
"""

import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def get_utc_timestamp() -> datetime:
    """
    Get current UTC timestamp.

    Returns:
        Current datetime in UTC with timezone info
    """
    return datetime.now(timezone.utc)


def format_timestamp(dt: datetime) -> str:
    """
    Format datetime as ISO 8601 string.

    Args:
        dt: Datetime to format

    Returns:
        ISO 8601 formatted string (e.g., "2026-01-21T10:00:00.000Z")
    """
    return dt.isoformat()


def parse_timestamp(timestamp_str: str) -> datetime:
    """
    Parse ISO 8601 timestamp string.

    Args:
        timestamp_str: ISO 8601 formatted string

    Returns:
        Datetime object

    Raises:
        ValueError: If timestamp format is invalid
    """
    try:
        # Try parsing with fromisoformat
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        return dt
    except ValueError:
        # Fallback to manual parsing
        return datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )


def encode_json(data: dict) -> str:
    """
    Encode dictionary as compact JSON string.

    Args:
        data: Dictionary to encode

    Returns:
        JSON string (single line, no pretty printing)
    """
    return json.dumps(data, separators=(",", ":"), default=json_default_handler)


def json_default_handler(obj: Any) -> Any:
    """
    Default handler for JSON encoding of complex types.

    Args:
        obj: Object to serialize

    Returns:
        JSON-serializable representation

    Raises:
        TypeError: If object cannot be serialized
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, Path):
        return str(obj)
    elif hasattr(obj, "to_dict"):
        return obj.to_dict()
    elif hasattr(obj, "__dict__"):
        return obj.__dict__
    else:
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def sanitize_log_data(data: dict) -> dict:
    """
    Remove sensitive data from log entries.

    Args:
        data: Log data to sanitize

    Returns:
        Sanitized dictionary with sensitive fields masked
    """
    sensitive_keys = {
        "password",
        "token",
        "secret",
        "api_key",
        "private_key",
        "password_hash",
        "authorization",
        "session_token",
    }

    sanitized = {}
    for key, value in data.items():
        # Check if key contains sensitive words
        if any(sensitive in key.lower() for sensitive in sensitive_keys):
            sanitized[key] = "***REDACTED***"
        elif isinstance(value, dict):
            # Recursively sanitize nested dicts
            sanitized[key] = sanitize_log_data(value)
        elif isinstance(value, list):
            # Sanitize lists of dicts
            sanitized[key] = [
                sanitize_log_data(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value

    return sanitized


def get_hostname() -> str:
    """
    Get current hostname for syslog messages.

    Returns:
        Hostname string
    """
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def ensure_log_directory(log_path: str) -> Path:
    """
    Ensure log directory exists.

    Args:
        log_path: Path to log file

    Returns:
        Path object for log directory
    """
    log_file = Path(log_path)
    log_dir = log_file.parent

    # Create directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)

    return log_dir


def get_log_file_size(log_path: str) -> int:
    """
    Get size of log file in bytes.

    Args:
        log_path: Path to log file

    Returns:
        File size in bytes, 0 if file doesn't exist
    """
    try:
        return Path(log_path).stat().st_size
    except FileNotFoundError:
        return 0


def truncate_message(message: str, max_length: int = 1000) -> str:
    """
    Truncate long log messages.

    Args:
        message: Message to truncate
        max_length: Maximum message length

    Returns:
        Truncated message with ellipsis if needed
    """
    if len(message) <= max_length:
        return message

    return message[: max_length - 3] + "..."


def format_log_line(log_entry: dict) -> str:
    """
    Format log entry as single JSON line.

    Args:
        log_entry: Log entry dictionary

    Returns:
        JSON string with newline
    """
    return encode_json(log_entry) + "\n"


def parse_log_line(line: str) -> Optional[dict]:
    """
    Parse JSON log line.

    Args:
        line: JSON log line

    Returns:
        Parsed dictionary or None if invalid
    """
    try:
        return json.loads(line.strip())
    except json.JSONDecodeError:
        return None


def get_log_level_priority(level: str) -> int:
    """
    Get numeric priority for log level (for sorting/filtering).

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        Numeric priority (0-50)
    """
    level_map = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }
    return level_map.get(level.upper(), 20)


def should_log(
    message_level: str,
    configured_level: str = "INFO",
) -> bool:
    """
    Check if message should be logged based on configured level.

    Args:
        message_level: Level of log message
        configured_level: Minimum configured log level

    Returns:
        True if message should be logged
    """
    return get_log_level_priority(message_level) >= get_log_level_priority(
        configured_level
    )


class CircularBuffer:
    """
    Circular buffer for in-memory log caching.

    Used to hold logs temporarily if external services are unavailable.
    """

    def __init__(self, max_size: int = 1000):
        """
        Initialize circular buffer.

        Args:
            max_size: Maximum number of log entries to store
        """
        self.max_size = max_size
        self.buffer: list[dict] = []
        self.index = 0

    def add(self, log_entry: dict) -> None:
        """
        Add log entry to buffer.

        Args:
            log_entry: Log entry dictionary
        """
        if len(self.buffer) < self.max_size:
            self.buffer.append(log_entry)
        else:
            # Overwrite oldest entry
            self.buffer[self.index] = log_entry
            self.index = (self.index + 1) % self.max_size

    def get_all(self) -> list[dict]:
        """
        Get all log entries in chronological order.

        Returns:
            List of log entries
        """
        if len(self.buffer) < self.max_size:
            return self.buffer.copy()
        else:
            # Reorder to chronological
            return self.buffer[self.index :] + self.buffer[: self.index]

    def clear(self) -> None:
        """Clear all log entries."""
        self.buffer.clear()
        self.index = 0

    def __len__(self) -> int:
        """Get number of entries in buffer."""
        return len(self.buffer)
