"""
Structured logging module for Modular File Manager.

Provides multi-destination logging with file rotation, database persistence,
syslog integration, and external API export.

Usage:
    from logging_module import setup_logging, log_info, log_operation

    # Setup logging
    await setup_logging()

    # Log messages
    await log_info("app_started", "Application started successfully")

    # Log operations
    await log_operation(
        operation_type="copy",
        message="File copied",
        user_id=1,
        operation_id=123,
        source_path="/path/a/file.txt",
        dest_path="/path/b/file.txt"
    )
"""

from logging_module.logger import (
    setup_logging,
    get_logger,
    log,
    log_debug,
    log_info,
    log_warning,
    log_error,
    log_critical,
    log_operation,
    log_auth,
    flush_logs,
    close_logging,
)
from logging_module.models import (
    LogEntry,
    LogLevel,
    LogComponent,
    OperationLog,
    AuthLog,
    LoggingConfig,
)

__version__ = "1.0.0"

__all__ = [
    # Main functions
    "setup_logging",
    "get_logger",
    # Generic logging
    "log",
    "log_debug",
    "log_info",
    "log_warning",
    "log_error",
    "log_critical",
    # Domain-specific
    "log_operation",
    "log_auth",
    # Utilities
    "flush_logs",
    "close_logging",
    # Models
    "LogEntry",
    "LogLevel",
    "LogComponent",
    "OperationLog",
    "AuthLog",
    "LoggingConfig",
]
