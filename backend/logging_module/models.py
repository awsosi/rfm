"""
Pydantic models for structured logging.

All log entries follow a consistent JSON schema with proper type validation.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict


class LogLevel(str, Enum):
    """Log severity levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogComponent(str, Enum):
    """System components for log tagging."""
    API = "api"
    WORKER = "worker"
    DATABASE = "database"
    AUTH = "auth"
    OPERATION = "operation"
    SYSTEM = "system"


class LogEntry(BaseModel):
    """
    Base log entry schema.

    All log entries (file, syslog, API) follow this structure.
    """
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    level: LogLevel
    component: LogComponent
    user_id: Optional[int] = None
    operation_id: Optional[int] = None
    action: str
    message: str
    details: Optional[dict[str, Any]] = None

    # Context fields
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[str] = None

    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
        }
    )

    def to_json_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "component": self.component.value,
            "user_id": self.user_id,
            "operation_id": self.operation_id,
            "action": self.action,
            "message": self.message,
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "request_id": self.request_id,
        }


class OperationLog(LogEntry):
    """
    Operation-specific log entry.

    Extends LogEntry with operation-specific fields.
    """
    operation_type: str
    source_path: Optional[str] = None
    dest_path: Optional[str] = None
    file_count: Optional[int] = None
    total_size_bytes: Optional[int] = None
    duration_ms: Optional[int] = None
    worker_ids: Optional[list[int]] = None


class AuthLog(LogEntry):
    """
    Authentication-specific log entry.

    Used for login, logout, token refresh, etc.
    """
    auth_method: str  # local, external, admin_emergency
    success: bool
    failure_reason: Optional[str] = None
    session_id: Optional[int] = None


class AuditLogEntry(BaseModel):
    """
    Audit log entry for database storage.

    Maps to audit_logs table structure.
    """
    user_id: Optional[int] = None
    operation_id: Optional[int] = None
    action: str
    details_json: Optional[dict[str, Any]] = None
    remote_api_sent: bool = False
    remote_api_sent_at: Optional[datetime] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(from_attributes=True)


class SyslogMessage(BaseModel):
    """
    Syslog message supporting both RFC 5424 and RFC 3164 formats.

    RFC 5424: <PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID STRUCTURED-DATA MSG
    RFC 3164: <PRI>TIMESTAMP HOSTNAME APP-NAME[PID]: MSG
    """
    facility: int = 16  # Local0
    severity: int = 6   # Informational
    hostname: str
    app_name: str = "file-manager"
    proc_id: str = "-"
    msg_id: str = "-"
    structured_data: dict[str, Any]
    message: str

    @property
    def priority(self) -> int:
        """Calculate PRI value: (facility * 8 + severity)."""
        return (self.facility * 8) + self.severity

    def to_rfc5424(self) -> str:
        """
        Format as RFC 5424 syslog message.

        Returns:
            Formatted syslog string
        """
        # Structured data format: [sd-id param="value" ...]
        sd_parts = []
        for key, value in self.structured_data.items():
            # RFC 5424 requires escaping \, ], " in param values
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("]", "\\]")
            sd_parts.append(f'{key}="{escaped}"')
        sd_str = f"[filemanager {' '.join(sd_parts)}]" if sd_parts else "-"

        return (
            f"<{self.priority}>1 "
            f"{datetime.utcnow().isoformat()}Z "
            f"{self.hostname} "
            f"{self.app_name} "
            f"{self.proc_id} "
            f"{self.msg_id} "
            f"{sd_str} "
            f"{self.message}"
        )

    def to_rfc3164(self) -> str:
        """
        Format as RFC 3164 (BSD syslog) message.

        Format: <PRI>TIMESTAMP HOSTNAME TAG: MSG
        Timestamp is BSD format: "Mmm dd HH:MM:SS"

        Returns:
            Formatted syslog string
        """
        now = datetime.utcnow()
        # RFC 3164 timestamp: "Feb 10 20:53:28" (day is space-padded, not zero-padded)
        day = f"{now.day:2d}"
        timestamp = now.strftime(f"%b {day} %H:%M:%S")

        # RFC 3164 has no structured data; include key context in message body
        context_parts = []
        for key, value in self.structured_data.items():
            context_parts.append(f"{key}={value}")
        context_str = " ".join(context_parts)

        msg = f"{self.message} [{context_str}]" if context_parts else self.message

        # RFC 3164: <PRI>TIMESTAMP HOSTNAME TAG: MSG
        # TAG is app_name (max 32 chars per RFC), no space between TAG and colon
        return (
            f"<{self.priority}>"
            f"{timestamp} "
            f"{self.hostname} "
            f"{self.app_name}: "
            f"{msg}"
        )


class ExternalAPILogRequest(BaseModel):
    """
    Request payload for external log API (Sybase).

    Simplified format for external consumption.
    """
    timestamp: str  # ISO 8601
    user_id: Optional[int] = None
    operation_id: Optional[int] = None
    action: str
    details: Optional[dict[str, Any]] = None
    level: str = "INFO"


class LogRotationConfig(BaseModel):
    """Configuration for log file rotation."""
    log_dir: str
    max_bytes: int = 100 * 1024 * 1024  # 100 MB
    backup_count: int = 14  # Keep 14 days
    rotate_daily: bool = True
    compress_old: bool = True
    retention_days: int = 14


class LoggingConfig(BaseModel):
    """Complete logging configuration."""
    # File logging
    enable_file_logging: bool = True
    log_file_path: str = "/var/log/file-manager/app.log"
    log_format: str = "json"
    log_level: LogLevel = LogLevel.INFO

    # Database logging
    enable_database_logging: bool = True

    # Syslog
    enable_syslog: bool = False
    syslog_host: Optional[str] = None
    syslog_port: int = 514
    syslog_protocol: str = "UDP"  # UDP or TCP
    syslog_format: str = "RFC5424"  # RFC3164 or RFC5424
    syslog_hostname: Optional[str] = None  # Custom hostname override

    # External API
    enable_external_api: bool = False
    external_api_url: Optional[str] = None
    external_api_token: Optional[str] = None
    external_api_timeout: int = 5
    external_api_retries: int = 3

    # Rotation
    rotation_config: LogRotationConfig = Field(
        default_factory=lambda: LogRotationConfig(
            log_dir="/var/log/file-manager",
            retention_days=14,
        )
    )
