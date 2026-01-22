"""
Pydantic schemas for request/response validation in the API.

All models include proper type hints, validation, and serialization.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator

from models import (
    UserRole,
    WorkerStatus,
    OperationType,
    OperationStatus,
    ConfigType,
)


# =============================================================================
# Authentication Schemas
# =============================================================================


class LoginRequest(BaseModel):
    """Login request with username and password."""

    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Login response with access token."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Token lifetime in seconds")
    user_id: int
    username: str
    role: UserRole


class TokenData(BaseModel):
    """Token payload data."""

    user_id: int
    username: str
    role: UserRole
    session_id: int


# =============================================================================
# User Schemas
# =============================================================================


class UserBase(BaseModel):
    """Base user schema."""

    username: str = Field(..., min_length=1, max_length=100)
    role: UserRole


class UserCreate(UserBase):
    """User creation schema."""

    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    """User update schema."""

    password: Optional[str] = Field(None, min_length=8)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    """User response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Worker Schemas
# =============================================================================


class WorkerRegister(BaseModel):
    """Worker registration request."""

    name: str = Field(..., min_length=1, max_length=200)
    hostname: str = Field(..., max_length=255)
    public_key: str = Field(..., description="PEM-encoded RSA public key")
    path_a_prefix: Optional[str] = Field(None, max_length=500)
    path_b_prefix: Optional[str] = Field(None, max_length=500)
    version: Optional[str] = Field(None, max_length=50)


class WorkerUpdate(BaseModel):
    """Worker update request."""

    status: Optional[WorkerStatus] = None
    path_a_prefix: Optional[str] = Field(None, max_length=500)
    path_b_prefix: Optional[str] = Field(None, max_length=500)


class WorkerResponse(BaseModel):
    """Worker response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    hostname: Optional[str]
    path_a_prefix: Optional[str]
    path_b_prefix: Optional[str]
    status: WorkerStatus
    version: Optional[str]
    last_heartbeat: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class WorkerHeartbeat(BaseModel):
    """Worker heartbeat request."""

    worker_id: int
    timestamp: datetime


# =============================================================================
# File Operation Schemas
# =============================================================================


class FileInfo(BaseModel):
    """File/directory information."""

    name: str
    path: str
    is_directory: bool
    size_bytes: Optional[int] = None
    modified_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class DirectoryListRequest(BaseModel):
    """Directory listing request."""

    worker_id: int
    path: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=1000, ge=1, le=10000)


class DirectoryListResponse(BaseModel):
    """Directory listing response."""

    path: str
    items: list[FileInfo]
    total_count: int
    offset: int
    limit: int
    has_more: bool


class FileSearchRequest(BaseModel):
    """File search request."""

    worker_id: int
    path: str
    query: str = Field(..., min_length=1)
    recursive: bool = True
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


class FileSearchResponse(BaseModel):
    """File search response."""

    query: str
    results: list[FileInfo]
    total_count: int
    offset: int
    limit: int


class FileCopyRequest(BaseModel):
    """File copy operation request."""

    source_path: str = Field(..., min_length=1)
    dest_path: str = Field(..., min_length=1)
    worker_ids: list[int] = Field(..., min_items=1, max_items=2)
    overwrite: bool = False


class FileMoveRequest(BaseModel):
    """File move operation request."""

    source_path: str = Field(..., min_length=1)
    dest_path: str = Field(..., min_length=1)
    worker_ids: list[int] = Field(..., min_items=1, max_items=2)
    overwrite: bool = False


class FileDeleteRequest(BaseModel):
    """File delete operation request."""

    path: str = Field(..., min_length=1)
    worker_id: int
    recursive: bool = False


class FileMkdirRequest(BaseModel):
    """Directory creation request."""

    path: str = Field(..., min_length=1)
    worker_id: int
    parents: bool = True


# =============================================================================
# Operation Schemas
# =============================================================================


class OperationCreate(BaseModel):
    """Operation creation schema."""

    type: OperationType
    source_path: str
    dest_path: Optional[str] = None
    worker_ids: list[int]
    params: Optional[dict[str, Any]] = None


class OperationResponse(BaseModel):
    """Operation response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    type: OperationType
    source_path: str
    dest_path: Optional[str]
    status: OperationStatus
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_msg: Optional[str]
    file_count: Optional[int]
    total_size_bytes: Optional[int]
    params_json: Optional[dict[str, Any]]
    created_at: datetime


class OperationStatusUpdate(BaseModel):
    """Operation status update from worker."""

    operation_id: int
    worker_id: int
    status: OperationStatus
    error_msg: Optional[str] = None
    file_count: Optional[int] = None
    total_size_bytes: Optional[int] = None


# =============================================================================
# Audit Log Schemas
# =============================================================================


class AuditLogResponse(BaseModel):
    """Audit log response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int]
    operation_id: Optional[int]
    action: str
    details_json: Optional[dict[str, Any]]
    remote_api_sent: bool
    remote_api_sent_at: Optional[datetime]
    ip_address: Optional[str]
    user_agent: Optional[str]
    timestamp: datetime


class AuditLogFilter(BaseModel):
    """Audit log filter parameters."""

    user_id: Optional[int] = None
    operation_id: Optional[int] = None
    action: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


# =============================================================================
# Configuration Schemas
# =============================================================================


class ConfigResponse(BaseModel):
    """Configuration entry response."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str
    type: ConfigType
    description: Optional[str]
    created_at: datetime
    updated_at: datetime


class ConfigUpdate(BaseModel):
    """Configuration update request."""

    value: str
    type: Optional[ConfigType] = None
    description: Optional[str] = None


class ConfigBulkUpdate(BaseModel):
    """Bulk configuration update request."""

    configs: dict[str, str] = Field(..., description="Key-value pairs to update")


# =============================================================================
# User Preferences Schemas
# =============================================================================


class UserPreferencesResponse(BaseModel):
    """User preferences response schema."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    remember_last_paths: bool
    last_path_a: Optional[str]
    last_path_b: Optional[str]
    ui_theme: str
    pane_layout: str
    show_hidden_files: bool
    default_sort_by: str
    default_sort_order: str
    items_per_page: int
    custom_settings: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class UserPreferencesUpdate(BaseModel):
    """User preferences update request."""

    remember_last_paths: Optional[bool] = None
    last_path_a: Optional[str] = Field(None, max_length=1000)
    last_path_b: Optional[str] = Field(None, max_length=1000)
    ui_theme: Optional[str] = Field(None, pattern="^(light|dark)$")
    pane_layout: Optional[str] = Field(None, pattern="^(horizontal|vertical)$")
    show_hidden_files: Optional[bool] = None
    default_sort_by: Optional[str] = Field(None, pattern="^(name|size|date)$")
    default_sort_order: Optional[str] = Field(None, pattern="^(asc|desc)$")
    items_per_page: Optional[int] = Field(None, ge=10, le=1000)
    custom_settings: Optional[dict[str, Any]] = None


# =============================================================================
# WebSocket Schemas
# =============================================================================


class WebSocketMessage(BaseModel):
    """WebSocket message schema."""

    type: str = Field(..., description="Message type: operation_update, worker_status, etc.")
    data: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class OperationProgressUpdate(BaseModel):
    """Real-time operation progress update."""

    operation_id: int
    status: OperationStatus
    progress_percent: Optional[float] = Field(None, ge=0, le=100)
    current_file: Optional[str] = None
    files_processed: Optional[int] = None
    total_files: Optional[int] = None
    bytes_transferred: Optional[int] = None
    total_bytes: Optional[int] = None
    error_msg: Optional[str] = None


# =============================================================================
# Common Response Schemas
# =============================================================================


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str
    detail: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response schema."""

    error: str
    detail: Optional[str] = None
    code: Optional[str] = None


class PaginatedResponse(BaseModel):
    """Generic paginated response."""

    items: list[Any]
    total: int
    offset: int
    limit: int
    has_more: bool


class HealthCheckResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    version: str
    database: bool
    redis: bool
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Worker Communication Schemas (Internal)
# =============================================================================


class WorkerRequest(BaseModel):
    """Request sent to worker."""

    command: str = Field(..., description="Command: copy, move, delete, mkdir, list")
    source_path: Optional[str] = None
    dest_path: Optional[str] = None
    params: Optional[dict[str, Any]] = None


class WorkerCommandResponse(BaseModel):
    """Response from worker."""

    status: str = Field(..., description="Status: success, failed")
    message: str = ""
    completion_time_ms: Optional[int] = None
    file_count: Optional[int] = None
    total_size_bytes: Optional[int] = None
    error_details: Optional[dict[str, Any]] = None
