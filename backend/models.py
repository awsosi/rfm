"""
SQLAlchemy ORM models for the Modular File Manager Application.

All models follow enterprise standards:
- UTC timezone-aware timestamps
- Proper foreign key relationships with cascades
- Indexed columns for query optimization
- Type hints for all fields
"""

from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class UserRole(str, PyEnum):
    """User role enumeration for RBAC."""
    ADMIN = "ADMIN"
    USER = "USER"


class WorkerStatus(str, PyEnum):
    """Worker status enumeration."""
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    PENDING = "PENDING"


class OperationType(str, PyEnum):
    """File operation types."""
    COPY = "COPY"
    MOVE = "MOVE"
    DELETE = "DELETE"
    MKDIR = "MKDIR"
    PUSH = "PUSH"  # Copy to pathB + archive to pathC
    PULL = "PULL"  # Revert from pathB to original location


class OperationStatus(str, PyEnum):
    """Operation execution status."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class CommandStatus(str, PyEnum):
    """Worker command execution status."""
    PENDING = "PENDING"
    SENT = "SENT"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class User(Base):
    """
    User model for authentication and authorization.

    Passwords are stored as Argon2 hashes. Role-based access control
    determines what operations users can perform.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.USER)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    is_active = Column(Boolean, nullable=False, default=True)

    # Relationships
    sessions = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    operations = relationship(
        "Operation",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    audit_logs = relationship(
        "AuditLog",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', role={self.role.value})>"


class Session(Base):
    """
    Session model for token-based authentication.

    Long-lived sessions (30 days) with HS256 signed tokens.
    """
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token = Column(String(512), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="sessions")

    def __repr__(self) -> str:
        return f"<Session(id={self.id}, user_id={self.user_id}, expires_at={self.expires_at})>"

    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now(timezone.utc) > self.expires_at


class Worker(Base):
    """
    Worker model representing Windows service workers.

    Each worker has path prefixes for paths A and B, and uses
    public key authentication for secure communication.
    """
    __tablename__ = "workers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False, index=True)
    hostname = Column(String(255), nullable=True)

    # Path prefixes for dual-pane operations
    path_a_prefix = Column(String(500), nullable=True)
    path_b_prefix = Column(String(500), nullable=True)

    # Public key for authentication (PEM format)
    public_key = Column(Text, nullable=False)

    status = Column(
        Enum(WorkerStatus),
        nullable=False,
        default=WorkerStatus.PENDING,
        index=True,
    )

    # Worker metadata
    version = Column(String(50), nullable=True)
    last_heartbeat = Column(DateTime(timezone=True), nullable=True, index=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    operations = relationship(
        "Operation",
        secondary="operation_workers",
        back_populates="workers",
    )

    def __repr__(self) -> str:
        return f"<Worker(id={self.id}, name='{self.name}', status={self.status.value})>"


class WorkerCommand(Base):
    """
    Worker command model for pull-based command distribution.

    Commands are created by the API and polled by workers.
    Workers execute commands and report results back via response endpoint.
    """
    __tablename__ = "worker_commands"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(
        Integer,
        ForeignKey("workers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_id = Column(
        Integer,
        ForeignKey("operations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Command details
    command = Column(String(50), nullable=False)  # copy, move, delete, mkdir, list, search, etc.
    source_path = Column(Text, nullable=True)
    dest_path = Column(Text, nullable=True)
    params_json = Column(JSON, nullable=True)  # Additional parameters

    # Status tracking
    status = Column(
        Enum(CommandStatus),
        nullable=False,
        default=CommandStatus.PENDING,
        index=True,
    )

    # Timing
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    sent_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Response data
    response_status = Column(String(20), nullable=True)  # success, failed, error
    response_message = Column(Text, nullable=True)
    response_data = Column(JSON, nullable=True)  # File count, size, error details, etc.
    error_msg = Column(Text, nullable=True)

    # Timeout management
    timeout_seconds = Column(Integer, nullable=False, default=300)  # 5 minutes default

    # Relationships
    worker = relationship("Worker")
    operation = relationship("Operation")

    # Indexes for polling queries
    __table_args__ = (
        Index("ix_worker_commands_worker_status", "worker_id", "status"),
        Index("ix_worker_commands_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<WorkerCommand(id={self.id}, worker_id={self.worker_id}, command='{self.command}', status={self.status.value})>"


class Operation(Base):
    """
    Operation model tracking all file operations.

    Complete audit trail with user, workers, paths, status, and timing.
    Supports rollback and multi-worker coordination.
    """
    __tablename__ = "operations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Operation details
    type = Column(Enum(OperationType), nullable=False, index=True)
    source_path = Column(Text, nullable=False)
    dest_path = Column(Text, nullable=True)
    original_path = Column(Text, nullable=True)  # Original location for PULL operations
    archive_path = Column(Text, nullable=True)  # Archive location for PUSH operations

    # Status tracking
    status = Column(
        Enum(OperationStatus),
        nullable=False,
        default=OperationStatus.PENDING,
        index=True,
    )

    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # Error handling
    error_msg = Column(Text, nullable=True)
    rollback_operation_id = Column(
        Integer,
        ForeignKey("operations.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Additional metadata
    file_count = Column(Integer, nullable=True)
    total_size_bytes = Column(Integer, nullable=True)
    params_json = Column(JSON, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    user = relationship("User", back_populates="operations")
    workers = relationship(
        "Worker",
        secondary="operation_workers",
        back_populates="operations",
    )
    audit_logs = relationship(
        "AuditLog",
        back_populates="operation",
        cascade="all, delete-orphan",
    )
    rollback_of = relationship(
        "Operation",
        remote_side=[id],
        foreign_keys=[rollback_operation_id],
    )

    # Indexes for common queries
    __table_args__ = (
        Index("ix_operations_user_status", "user_id", "status"),
        Index("ix_operations_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Operation(id={self.id}, type={self.type.value}, status={self.status.value})>"


class OperationWorker(Base):
    """
    Association table linking operations to workers.

    Supports multi-worker operations where multiple workers must
    coordinate to complete a single operation.
    """
    __tablename__ = "operation_workers"

    operation_id = Column(
        Integer,
        ForeignKey("operations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    worker_id = Column(
        Integer,
        ForeignKey("workers.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Worker-specific status
    worker_status = Column(
        Enum(OperationStatus),
        nullable=False,
        default=OperationStatus.PENDING,
    )
    worker_started_at = Column(DateTime(timezone=True), nullable=True)
    worker_completed_at = Column(DateTime(timezone=True), nullable=True)
    worker_error_msg = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<OperationWorker(op={self.operation_id}, worker={self.worker_id}, status={self.worker_status.value})>"


class AuditLog(Base):
    """
    Immutable audit log for all system actions.

    Every operation, authentication event, and configuration change
    is logged with full context for compliance and debugging.
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    operation_id = Column(
        Integer,
        ForeignKey("operations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Event details
    action = Column(String(100), nullable=False, index=True)
    details_json = Column(JSON, nullable=True)

    # External API logging
    remote_api_sent = Column(Boolean, nullable=False, default=False)
    remote_api_sent_at = Column(DateTime(timezone=True), nullable=True)

    # Context
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # Relationships
    user = relationship("User", back_populates="audit_logs")
    operation = relationship("Operation", back_populates="audit_logs")

    # Indexes for queries
    __table_args__ = (
        Index("ix_audit_logs_user_timestamp", "user_id", "timestamp"),
        Index("ix_audit_logs_action_timestamp", "action", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action='{self.action}', timestamp={self.timestamp})>"


class ConfigType(str, PyEnum):
    """Configuration value type enumeration."""
    STRING = "STRING"
    INT = "INT"
    JSON = "JSON"
    BOOLEAN = "BOOLEAN"


class Config(Base):
    """
    Configuration table for runtime parameters.

    All magic strings and tuneable parameters are stored here.
    Supports different value types with proper type casting.
    """
    __tablename__ = "config"

    key = Column(String(200), primary_key=True)
    value = Column(Text, nullable=False)
    type = Column(
        Enum(ConfigType),
        nullable=False,
        default=ConfigType.STRING,
    )
    description = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<Config(key='{self.key}', value='{self.value}', type={self.type.value})>"

    def get_typed_value(self):
        """Return value cast to the appropriate type."""
        if self.type == ConfigType.INT:
            return int(self.value)
        elif self.type == ConfigType.BOOLEAN:
            return self.value.lower() in ("true", "1", "yes")
        elif self.type == ConfigType.JSON:
            import json
            return json.loads(self.value)
        else:
            return self.value


class UserPreferences(Base):
    """
    User preferences for UI customization and behavior.

    Stores individual user settings like last visited paths,
    UI layout preferences, filters, etc.
    """
    __tablename__ = "user_preferences"

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # UI Preferences
    remember_last_paths = Column(Boolean, nullable=False, default=True)
    last_path_a = Column(String(1000), nullable=True)
    last_path_b = Column(String(1000), nullable=True)

    # Layout preferences
    ui_theme = Column(String(50), nullable=False, default="light")  # light, dark
    pane_layout = Column(String(50), nullable=False, default="horizontal")  # horizontal, vertical
    show_hidden_files = Column(Boolean, nullable=False, default=False)
    default_sort_by = Column(String(50), nullable=False, default="name")  # name, size, date
    default_sort_order = Column(String(50), nullable=False, default="asc")  # asc, desc

    # Pagination preferences
    items_per_page = Column(Integer, nullable=False, default=100)

    # Additional settings (JSON for flexibility)
    custom_settings = Column(JSON, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user = relationship("User", backref="preferences")

    def __repr__(self) -> str:
        return f"<UserPreferences(user_id={self.user_id}, theme='{self.ui_theme}')>"
