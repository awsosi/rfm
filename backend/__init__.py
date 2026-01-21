"""
Modular File Manager - Backend Package

Enterprise file operations management with centralized control and distributed workers.
"""

__version__ = "1.0.0"
__author__ = "Modular File Manager Team"

from database import (
    DatabaseManager,
    get_db,
    get_db_session,
    init_database,
    close_database,
    health_check,
)
from models import (
    Base,
    User,
    UserRole,
    Session,
    Worker,
    WorkerStatus,
    Operation,
    OperationType,
    OperationStatus,
    OperationWorker,
    AuditLog,
    Config,
    ConfigType,
)

__all__ = [
    # Database
    "DatabaseManager",
    "get_db",
    "get_db_session",
    "init_database",
    "close_database",
    "health_check",
    # Models
    "Base",
    "User",
    "UserRole",
    "Session",
    "Worker",
    "WorkerStatus",
    "Operation",
    "OperationType",
    "OperationStatus",
    "OperationWorker",
    "AuditLog",
    "Config",
    "ConfigType",
]
