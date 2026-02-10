"""
Main logging interface for Modular File Manager.

Provides high-level API for structured logging with multiple destinations.

Usage:
    from logging_module import setup_logging, log_info, log_error

    # Setup logging
    await setup_logging()

    # Log messages
    await log_info("operation_completed", user_id=1, message="File copied successfully")
    await log_error("operation_failed", user_id=1, error="Permission denied")
"""

import os
from typing import Any, Optional

from loguru import logger

from logging_module.handlers import (
    FileHandler,
    DatabaseHandler,
    SyslogHandler,
    ExternalAPIHandler,
    MultiHandler,
)
from logging_module.models import (
    LogEntry,
    LogLevel,
    LogComponent,
    LoggingConfig,
    LogRotationConfig,
    OperationLog,
    AuthLog,
)
from logging_module.rotation import LogRotator
from logging_module.utils import get_utc_timestamp


# Global handler instance
_global_handler: Optional[MultiHandler] = None
_config: Optional[LoggingConfig] = None


def get_config() -> LoggingConfig:
    """
    Get logging configuration from environment variables.

    Returns:
        LoggingConfig instance
    """
    return LoggingConfig(
        # File logging
        enable_file_logging=os.getenv("ENABLE_FILE_LOGS", "true").lower() == "true",
        log_file_path=os.getenv("LOG_FILE_PATH", "/var/log/file-manager/app.log"),
        log_format=os.getenv("LOG_FORMAT", "json"),
        log_level=LogLevel(os.getenv("LOG_LEVEL", "INFO").upper()),
        # Database logging
        enable_database_logging=os.getenv(
            "ENABLE_DATABASE_LOGS", "true"
        ).lower() == "true",
        # Syslog
        enable_syslog=os.getenv("ENABLE_SYSLOG", "false").lower() == "true",
        syslog_host=os.getenv("SYSLOG_HOST"),
        syslog_port=int(os.getenv("SYSLOG_PORT", "514")),
        syslog_protocol=os.getenv("SYSLOG_PROTOCOL", "UDP"),
        syslog_format=os.getenv("SYSLOG_FORMAT", "RFC5424"),
        syslog_hostname=os.getenv("SYSLOG_HOSTNAME") or None,
        # External API
        enable_external_api=os.getenv(
            "ENABLE_REMOTE_AUDIT_API", "false"
        ).lower() == "true",
        external_api_url=os.getenv("REMOTE_AUDIT_API_URL"),
        external_api_token=os.getenv("REMOTE_AUDIT_API_TOKEN"),
        external_api_timeout=int(os.getenv("REMOTE_AUDIT_API_TIMEOUT", "5")),
        external_api_retries=int(os.getenv("EXTERNAL_API_RETRIES", "3")),
        # Rotation
        rotation_config=LogRotationConfig(
            log_dir=os.path.dirname(
                os.getenv("LOG_FILE_PATH", "/var/log/file-manager/app.log")
            ),
            retention_days=int(os.getenv("LOG_RETENTION_DAYS", "14")),
            compress_old=True,
        ),
    )


async def setup_logging(config: Optional[LoggingConfig] = None) -> MultiHandler:
    """
    Setup logging system with configured handlers.

    Args:
        config: Optional logging configuration (uses env vars if None)

    Returns:
        Configured MultiHandler instance
    """
    global _global_handler, _config

    if config is None:
        config = get_config()

    _config = config

    # Create multi-handler — always set _global_handler even if
    # individual handlers fail, so syslog can be added later.
    handler = MultiHandler()

    # File logging
    if config.enable_file_logging:
        try:
            rotator = LogRotator(config.rotation_config)
            file_handler = FileHandler(config.log_file_path, rotator)
            handler.add_handler(file_handler)
        except Exception as exc:
            logger.warning(f"Failed to initialize file handler: {exc}")

    # Database logging
    if config.enable_database_logging:
        try:
            db_handler = DatabaseHandler()
            handler.add_handler(db_handler)
        except Exception as exc:
            logger.warning(f"Failed to initialize database handler: {exc}")

    # Syslog
    if config.enable_syslog and config.syslog_host:
        try:
            syslog_handler = SyslogHandler(
                host=config.syslog_host,
                port=config.syslog_port,
                protocol=config.syslog_protocol,
                syslog_format=config.syslog_format,
                hostname=config.syslog_hostname or None,
            )
            handler.add_handler(syslog_handler)
        except Exception as exc:
            logger.warning(f"Failed to initialize syslog handler: {exc}")

    # External API
    if config.enable_external_api and config.external_api_url:
        try:
            api_handler = ExternalAPIHandler(
                api_url=config.external_api_url,
                api_token=config.external_api_token,
                timeout=config.external_api_timeout,
                retries=config.external_api_retries,
            )
            handler.add_handler(api_handler)
        except Exception as exc:
            logger.warning(f"Failed to initialize external API handler: {exc}")

    _global_handler = handler
    return handler


def get_logger() -> MultiHandler:
    """
    Get global logger instance.

    Returns:
        MultiHandler instance

    Raises:
        RuntimeError: If logging not initialized
    """
    if _global_handler is None:
        raise RuntimeError(
            "Logging not initialized. Call setup_logging() first."
        )
    return _global_handler


async def log(
    level: LogLevel,
    component: LogComponent,
    action: str,
    message: str,
    user_id: Optional[int] = None,
    operation_id: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
    **kwargs,
) -> None:
    """
    Log a message with specified level and component.

    Args:
        level: Log level
        component: Component name
        action: Action being logged
        message: Log message
        user_id: Optional user ID
        operation_id: Optional operation ID
        details: Optional details dictionary
        **kwargs: Additional fields (ip_address, user_agent, request_id, etc.)
    """
    log_entry = LogEntry(
        timestamp=get_utc_timestamp(),
        level=level,
        component=component,
        user_id=user_id,
        operation_id=operation_id,
        action=action,
        message=message,
        details=details,
        **kwargs,
    )

    handler = get_logger()
    await handler.write_log(log_entry)


# Convenience functions for different log levels

async def log_debug(
    action: str,
    message: str,
    component: LogComponent = LogComponent.SYSTEM,
    **kwargs,
) -> None:
    """Log debug message."""
    await log(LogLevel.DEBUG, component, action, message, **kwargs)


async def log_info(
    action: str,
    message: str,
    component: LogComponent = LogComponent.SYSTEM,
    **kwargs,
) -> None:
    """Log info message."""
    await log(LogLevel.INFO, component, action, message, **kwargs)


async def log_warning(
    action: str,
    message: str,
    component: LogComponent = LogComponent.SYSTEM,
    **kwargs,
) -> None:
    """Log warning message."""
    await log(LogLevel.WARNING, component, action, message, **kwargs)


async def log_error(
    action: str,
    message: str,
    component: LogComponent = LogComponent.SYSTEM,
    **kwargs,
) -> None:
    """Log error message."""
    await log(LogLevel.ERROR, component, action, message, **kwargs)


async def log_critical(
    action: str,
    message: str,
    component: LogComponent = LogComponent.SYSTEM,
    **kwargs,
) -> None:
    """Log critical message."""
    await log(LogLevel.CRITICAL, component, action, message, **kwargs)


# Domain-specific logging functions

async def log_operation(
    operation_type: str,
    message: str,
    user_id: int,
    operation_id: int,
    source_path: Optional[str] = None,
    dest_path: Optional[str] = None,
    file_count: Optional[int] = None,
    total_size_bytes: Optional[int] = None,
    duration_ms: Optional[int] = None,
    worker_ids: Optional[list[int]] = None,
    **kwargs,
) -> None:
    """
    Log file operation.

    Args:
        operation_type: Type of operation (copy, move, delete, etc.)
        message: Log message
        user_id: User performing operation
        operation_id: Operation ID
        source_path: Source file path
        dest_path: Destination file path
        file_count: Number of files processed
        total_size_bytes: Total bytes processed
        duration_ms: Operation duration in milliseconds
        worker_ids: List of worker IDs involved
        **kwargs: Additional fields
    """
    op_log = OperationLog(
        timestamp=get_utc_timestamp(),
        level=LogLevel.INFO,
        component=LogComponent.OPERATION,
        user_id=user_id,
        operation_id=operation_id,
        action=f"operation_{operation_type}",
        message=message,
        operation_type=operation_type,
        source_path=source_path,
        dest_path=dest_path,
        file_count=file_count,
        total_size_bytes=total_size_bytes,
        duration_ms=duration_ms,
        worker_ids=worker_ids,
        details=kwargs.get("details"),
        **kwargs,
    )

    handler = get_logger()
    await handler.write_log(op_log)


async def log_auth(
    auth_method: str,
    success: bool,
    message: str,
    user_id: Optional[int] = None,
    session_id: Optional[int] = None,
    failure_reason: Optional[str] = None,
    **kwargs,
) -> None:
    """
    Log authentication event.

    Args:
        auth_method: Authentication method (local, external, admin_emergency)
        success: Whether authentication succeeded
        message: Log message
        user_id: User ID (if known)
        session_id: Session ID (if created)
        failure_reason: Reason for failure (if applicable)
        **kwargs: Additional fields
    """
    auth_log = AuthLog(
        timestamp=get_utc_timestamp(),
        level=LogLevel.INFO if success else LogLevel.WARNING,
        component=LogComponent.AUTH,
        user_id=user_id,
        action=f"auth_{auth_method}_{'success' if success else 'failure'}",
        message=message,
        auth_method=auth_method,
        success=success,
        failure_reason=failure_reason,
        session_id=session_id,
        details=kwargs.get("details"),
        **kwargs,
    )

    handler = get_logger()
    await handler.write_log(auth_log)


async def flush_logs() -> None:
    """Flush all pending logs to destinations."""
    handler = get_logger()
    await handler.flush()


def close_logging() -> None:
    """Close all logging handlers."""
    global _global_handler

    if _global_handler:
        _global_handler.close()
        _global_handler = None
