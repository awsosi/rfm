"""
Pydantic schemas for admin endpoints.

Includes schemas for:
- Samba path management
- Worker provisioning and configuration
- System monitoring and metrics
- Real-time log streaming
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


# =============================================================================
# Samba Path Schemas
# =============================================================================

class SambaPathCreate(BaseModel):
    """Create new Samba path configuration."""
    name: str = Field(..., min_length=1, max_length=200)
    path_prefix: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    is_active: bool = True
    share_type: Optional[str] = "smb"
    requires_auth: bool = True
    metadata_json: Optional[Dict[str, Any]] = None


class SambaPathUpdate(BaseModel):
    """Update Samba path configuration."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    path_prefix: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    share_type: Optional[str] = None
    requires_auth: Optional[bool] = None
    metadata_json: Optional[Dict[str, Any]] = None


class SambaPathResponse(BaseModel):
    """Samba path response."""
    id: int
    name: str
    path_prefix: str
    description: Optional[str]
    is_active: bool
    share_type: Optional[str]
    requires_auth: bool
    metadata_json: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# Worker Provisioning Schemas
# =============================================================================

class WorkerConfigRequest(BaseModel):
    """Worker configuration to provision."""
    path_a_prefix: Optional[str] = None
    path_b_prefix: Optional[str] = None
    path_c_prefix: Optional[str] = None
    polling_interval_seconds: Optional[int] = Field(None, ge=1, le=300)
    max_concurrent_operations: Optional[int] = Field(None, ge=1, le=10)
    enable_verbose_logging: Optional[bool] = None
    custom_settings: Optional[Dict[str, Any]] = None


class WorkerStatusResponse(BaseModel):
    """Worker realtime status response."""
    worker_id: int
    worker_name: str
    hostname: str
    status: str
    last_heartbeat: Optional[datetime]

    # Current configuration
    current_config: Optional[Dict[str, Any]] = None

    # Performance metrics
    uptime_seconds: Optional[int] = None
    operations_processed: Optional[int] = None
    operations_in_queue: Optional[int] = None
    cpu_usage_percent: Optional[float] = None
    memory_usage_mb: Optional[int] = None
    disk_free_gb: Optional[float] = None

    # Health status
    is_healthy: bool = True
    health_issues: List[str] = []


class WorkerProvisionRequest(BaseModel):
    """Provision worker with configuration."""
    config: WorkerConfigRequest
    restart_required: bool = False


# =============================================================================
# System Monitoring Schemas
# =============================================================================

class SystemStatsResponse(BaseModel):
    """System-wide statistics and metrics."""
    timestamp: datetime

    # Active counts
    active_operations: int
    active_workers: int
    active_users: int
    pending_workers: int

    # Operation statistics
    operations_completed_last_hour: int
    operations_failed_last_hour: int
    operations_in_progress: int
    operations_pending: int

    # Worker statistics
    workers_healthy: int
    workers_suspended: int
    workers_offline: int

    # User statistics
    total_users: int
    admin_users: int
    operator_users: int
    viewer_users: int

    # Performance
    avg_operation_duration_seconds: Optional[float] = None

    # System health
    database_healthy: bool
    redis_healthy: bool

    # Additional metrics
    total_audit_logs: int


class SystemHealthResponse(BaseModel):
    """System health check with detailed component status."""
    overall_status: str  # "healthy", "degraded", "critical"
    timestamp: datetime

    components: Dict[str, Dict[str, Any]] = {
        "database": {"status": "unknown", "message": ""},
        "elasticsearch": {"status": "unknown", "message": ""},
        "redis": {"status": "unknown", "message": ""},
        "api": {"status": "unknown", "message": ""},
        "webui": {"status": "unknown", "message": ""},
    }

    alerts: List[Dict[str, Any]] = []


# =============================================================================
# Log Streaming Schemas
# =============================================================================

class LogFilter(BaseModel):
    """Filters for log queries."""
    user_id: Optional[int] = None
    action: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    search_query: Optional[str] = None
    level: Optional[str] = None  # INFO, WARN, ERROR


class LogEntry(BaseModel):
    """Single log entry."""
    id: int
    timestamp: datetime
    level: str
    user_id: Optional[int]
    username: Optional[str]
    action: str
    details: Optional[Dict[str, Any]]
    ip_address: Optional[str]
    user_agent: Optional[str]


class LogStreamResponse(BaseModel):
    """Log streaming response with pagination."""
    logs: List[LogEntry]
    total_count: int
    offset: int
    limit: int
    has_more: bool


# =============================================================================
# Worker Command Schemas (for realtime control)
# =============================================================================

class WorkerCommandRequest(BaseModel):
    """Send command to worker in realtime."""
    command: str = Field(..., description="Command type: ping, restart, reload_config, get_status")
    params: Optional[Dict[str, Any]] = None
    timeout_seconds: int = Field(30, ge=1, le=300)


class WorkerCommandResponse(BaseModel):
    """Worker command execution response."""
    command_id: str
    worker_id: int
    status: str  # "success", "failed", "timeout"
    message: str
    data: Optional[Dict[str, Any]] = None
    duration_ms: int


# =============================================================================
# Real-time Event Schemas (WebSocket)
# =============================================================================

class RealtimeEvent(BaseModel):
    """Real-time event pushed via WebSocket."""
    event_type: str  # "operation_update", "worker_status", "system_alert", "log_entry"
    timestamp: datetime
    data: Dict[str, Any]


class OperationUpdateEvent(BaseModel):
    """Operation progress update event."""
    operation_id: int
    status: str
    progress_percent: Optional[int] = None
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class WorkerStatusEvent(BaseModel):
    """Worker status change event."""
    worker_id: int
    worker_name: str
    old_status: str
    new_status: str
    reason: Optional[str] = None


class SystemAlertEvent(BaseModel):
    """System alert event."""
    severity: str  # "info", "warning", "error", "critical"
    title: str
    message: str
    details: Optional[Dict[str, Any]] = None


# =============================================================================
# Application Log Schemas
# =============================================================================

class AppLogEntry(BaseModel):
    """Single application log entry (from stdout/file)."""
    timestamp: datetime
    level: str
    message: str
    logger: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class AppLogResponse(BaseModel):
    """Application log response with pagination."""
    logs: List[AppLogEntry]
    total_lines: int
    offset: int
    limit: int
    has_more: bool
    log_source: str  # "file", "memory"


class LogConfigUpdate(BaseModel):
    """Update logging configuration."""
    enable_syslog: Optional[bool] = None
    syslog_host: Optional[str] = None
    syslog_port: Optional[int] = Field(None, ge=1, le=65535)
    syslog_protocol: Optional[str] = Field(None, pattern="^(UDP|TCP)$")
    log_retention_days: Optional[int] = Field(None, ge=1, le=365)
    enable_log_compression: Optional[bool] = None


class LogConfigResponse(BaseModel):
    """Current logging configuration."""
    log_level: str
    enable_file_logs: bool
    log_file_path: Optional[str]
    enable_syslog: bool
    syslog_host: Optional[str]
    syslog_port: int
    syslog_protocol: str
    log_retention_days: int
    enable_log_compression: bool
