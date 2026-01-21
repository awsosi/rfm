"""
Logging middleware for request/response tracking and audit trail.

Logs all API requests with user context, timing, and response status.
Integrates with audit_logs table for compliance.
"""

import json
import time
from typing import Callable
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from loguru import logger

from api.middleware.auth import get_optional_user
from database import DatabaseManager
from models import AuditLog


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for logging all HTTP requests and responses.

    Logs request method, path, query params, user info, timing, and response status.
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """
        Process request and log details.

        Args:
            request: FastAPI request
            call_next: Next middleware/handler in chain

        Returns:
            Response from handler
        """
        # Generate unique request ID
        request_id = str(uuid4())
        request.state.request_id = request_id

        # Start timing
        start_time = time.time()

        # Extract request info
        method = request.method
        path = request.url.path
        query_params = dict(request.query_params)
        client_host = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")

        # Get authenticated user if present
        user = None
        user_id = None
        username = None

        try:
            # Try to get user from token (non-blocking)
            from api.config import get_settings
            from database import get_db

            settings = get_settings()
            async with DatabaseManager.session() as db:
                user = await get_optional_user(request, db, settings)
                if user:
                    user_id = user.id
                    username = user.username
                    request.state.user = user
        except Exception:
            pass

        # Log request start
        logger.info(
            "Request started",
            extra={
                "request_id": request_id,
                "method": method,
                "path": path,
                "query_params": query_params,
                "client_host": client_host,
                "user_id": user_id,
                "username": username,
                "user_agent": user_agent,
            },
        )

        # Process request
        try:
            response = await call_next(request)
            status_code = response.status_code

            # Calculate duration
            duration_ms = int((time.time() - start_time) * 1000)

            # Log response
            logger.info(
                "Request completed",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "user_id": user_id,
                    "username": username,
                },
            )

            # Add custom headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time"] = f"{duration_ms}ms"

            return response

        except Exception as exc:
            # Log error
            duration_ms = int((time.time() - start_time) * 1000)

            logger.error(
                "Request failed",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "duration_ms": duration_ms,
                    "user_id": user_id,
                    "username": username,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

            raise


async def create_audit_log(
    user_id: int,
    action: str,
    details: dict,
    operation_id: int = None,
    ip_address: str = None,
    user_agent: str = None,
) -> AuditLog:
    """
    Create audit log entry.

    Args:
        user_id: ID of user performing action
        action: Action description (e.g., "login", "file_copy")
        details: Additional details as JSON
        operation_id: Related operation ID if applicable
        ip_address: Client IP address
        user_agent: Client user agent

    Returns:
        Created AuditLog model
    """
    async with DatabaseManager.session() as db:
        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            details_json=details,
            operation_id=operation_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(audit_log)
        await db.commit()
        await db.refresh(audit_log)

    logger.info(
        f"Audit log created: {action}",
        extra={
            "audit_log_id": audit_log.id,
            "user_id": user_id,
            "action": action,
            "operation_id": operation_id,
        },
    )

    return audit_log


def setup_logging(log_level: str = "INFO", json_logs: bool = True):
    """
    Setup structured logging with loguru.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_logs: Whether to output JSON formatted logs
    """
    # Remove default handler
    logger.remove()

    if json_logs:
        # JSON structured logging for production
        logger.add(
            sink=lambda msg: print(msg, flush=True),
            format="{message}",
            level=log_level,
            serialize=True,
        )
    else:
        # Human-readable logging for development
        logger.add(
            sink=lambda msg: print(msg, flush=True),
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            level=log_level,
            colorize=True,
        )

    logger.info(f"Logging initialized at {log_level} level (JSON: {json_logs})")


class AuditLogger:
    """
    Helper class for creating audit log entries.

    Provides convenient methods for common audit actions.
    """

    @staticmethod
    async def log_authentication(
        user_id: int,
        action: str,
        success: bool,
        ip_address: str = None,
        user_agent: str = None,
        details: dict = None,
    ) -> AuditLog:
        """Log authentication attempt."""
        audit_details = {
            "success": success,
            "action_type": "authentication",
            **(details or {}),
        }

        return await create_audit_log(
            user_id=user_id,
            action=action,
            details=audit_details,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    @staticmethod
    async def log_operation(
        user_id: int,
        operation_id: int,
        action: str,
        details: dict,
        ip_address: str = None,
        user_agent: str = None,
    ) -> AuditLog:
        """Log file operation."""
        audit_details = {
            "action_type": "operation",
            **details,
        }

        return await create_audit_log(
            user_id=user_id,
            action=action,
            details=audit_details,
            operation_id=operation_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    @staticmethod
    async def log_admin_action(
        user_id: int,
        action: str,
        target: str,
        details: dict,
        ip_address: str = None,
        user_agent: str = None,
    ) -> AuditLog:
        """Log administrative action."""
        audit_details = {
            "action_type": "admin",
            "target": target,
            **details,
        }

        return await create_audit_log(
            user_id=user_id,
            action=action,
            details=audit_details,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    @staticmethod
    async def log_config_change(
        user_id: int,
        config_key: str,
        old_value: str,
        new_value: str,
        ip_address: str = None,
        user_agent: str = None,
    ) -> AuditLog:
        """Log configuration change."""
        audit_details = {
            "action_type": "config_change",
            "config_key": config_key,
            "old_value": old_value,
            "new_value": new_value,
        }

        return await create_audit_log(
            user_id=user_id,
            action="config_update",
            details=audit_details,
            ip_address=ip_address,
            user_agent=user_agent,
        )


def mask_sensitive_data(data: dict) -> dict:
    """
    Mask sensitive data in logs.

    Args:
        data: Dictionary potentially containing sensitive data

    Returns:
        Dictionary with sensitive fields masked
    """
    sensitive_keys = {
        "password",
        "token",
        "secret",
        "api_key",
        "private_key",
        "credit_card",
    }

    masked_data = {}
    for key, value in data.items():
        if any(sensitive in key.lower() for sensitive in sensitive_keys):
            masked_data[key] = "***MASKED***"
        elif isinstance(value, dict):
            masked_data[key] = mask_sensitive_data(value)
        else:
            masked_data[key] = value

    return masked_data
