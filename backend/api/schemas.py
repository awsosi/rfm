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
    auth_method: Optional[str] = Field(
        default="auto",
        description="Authentication method: 'auto' (try PolkaSQL first, fallback to local), 'polka' (only PolkaSQL), 'local' (only local)"
    )

    @field_validator('auth_method')
    @classmethod
    def validate_auth_method(cls, v: Optional[str]) -> str:
        """Validate auth_method is one of allowed values."""
        if v is None:
            return "auto"
        if v not in ["auto", "polka", "local"]:
            raise ValueError("auth_method must be one of: auto, polka, local")
        return v


class LoginResponse(BaseModel):
    """Login response with access token."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Token lifetime in seconds")
    user_id: int
    username: str
    role: UserRole
    refresh_token: Optional[str] = Field(None, description="Refresh token for device flow")


class DeviceAuthorizationResponse(BaseModel):
    """Device authorization request response (OAuth device flow)."""

    device_code: str = Field(..., description="Device code for polling")
    user_code: str = Field(..., description="User-friendly code for approval")
    verification_uri: str = Field(..., description="URL for user to approve device")
    expires_in: int = Field(..., description="Expiration time in seconds")


class DeviceAuthorizationPollRequest(BaseModel):
    """Device authorization polling request."""

    device_code: str = Field(..., min_length=1, max_length=64)


class DeviceAuthorizationApprovalRequest(BaseModel):
    """Device authorization approval request."""

    user_code: str = Field(..., min_length=1, max_length=16)


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

    username: Optional[str] = Field(None, min_length=1, max_length=100)
    password: Optional[str] = Field(None, min_length=8)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    """User response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    is_polka_auth: bool = False
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
    path_c_prefix: Optional[str] = Field(None, max_length=500)
    version: Optional[str] = Field(None, max_length=50)


class WorkerUpdate(BaseModel):
    """Worker update request."""

    status: Optional[WorkerStatus] = None
    path_a_prefix: Optional[str] = Field(None, max_length=500)
    path_b_prefix: Optional[str] = Field(None, max_length=500)
    path_c_prefix: Optional[str] = Field(None, max_length=500)


class WorkerResponse(BaseModel):
    """Worker response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    hostname: Optional[str]
    path_a_prefix: Optional[str]
    path_b_prefix: Optional[str]
    path_c_prefix: Optional[str]
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


class FilePushRequest(BaseModel):
    """File push operation request (VF redesign)."""

    source_path: str = Field(..., min_length=1, description="Source directory path from Path A")
    worker_id: int = Field(..., description="Worker ID to execute operation")


class UpdateAction(BaseModel):
    """
    A single in-place change inside an already-pushed catalog.

    - ``rename``/``move``: ``source`` -> ``dest``
    - ``delete``: ``source``
    - ``replace``: overwrite ``source`` with new content
    - ``add``: create ``dest`` with new content

    New content (replace/add) comes from exactly one of ``from_path`` (a file
    in Path A) or ``upload_id`` (a file uploaded via ``POST /api/uploads``).
    Semantic rules live in ``validate_update_actions``.
    """

    action: str = Field(
        ...,
        description="One of: move, rename, delete, replace, add",
    )
    source: Optional[str] = Field(
        None,
        description="Entry to act on, relative to the catalog root (not used by add)",
    )
    dest: Optional[str] = Field(
        None,
        description="New location relative to the catalog root (move/rename/add)",
    )
    recursive: bool = Field(
        True,
        description="Delete directories recursively (delete only)",
    )
    from_path: Optional[str] = Field(
        None,
        description="Path A file providing the new content (replace/add)",
    )
    upload_id: Optional[str] = Field(
        None,
        description="Uploaded file providing the new content (replace/add)",
    )
    remove_source: bool = Field(
        False,
        description="Delete from_path from Path A once the UPDATE succeeded",
    )

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        allowed = {"move", "rename", "delete", "replace", "add"}
        normalised = (v or "").strip().lower()
        if normalised not in allowed:
            raise ValueError(f"action must be one of: {', '.join(sorted(allowed))}")
        return normalised


class FileUpdateRequest(BaseModel):
    """
    UPDATE operation request (VF redesign).

    Changes the contents of a catalog that already lives in PATH_B.
    All action paths are relative to ``catalog_path``.
    """

    catalog_path: str = Field(
        ...,
        min_length=1,
        description="Path of the already-pushed catalog (Path B)",
    )
    worker_id: int = Field(..., description="Worker ID to execute operation")
    push_operation_id: Optional[int] = Field(
        None,
        description=(
            "PUSH operation that created the catalog. Resolved from catalog_path "
            "when omitted."
        ),
    )
    actions: list[UpdateAction] = Field(
        ...,
        min_items=1,
        description="Changes to apply inside the catalog",
    )


class UploadResponse(BaseModel):
    """A file stored for use by an UPDATE (replace/add)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    size_bytes: int
    sha256: str
    created_at: datetime
    expires_at: datetime


class CatalogValidationResponse(BaseModel):
    """Result of validating a catalog name against PolkaSQL."""

    valid: bool
    catalog_name: str
    matched_name: Optional[str] = None
    product_id: Optional[int] = None
    # Polka27.elementy.grup_nazwe of the matched product, sent to PIM as tgId
    tg_id: Optional[str] = None
    suggestions: list[str] = Field(default_factory=list)
    reason: Optional[str] = Field(
        None, description="i18n key describing why validation failed"
    )
    error_detail: Optional[str] = None
    skipped: bool = False


class ContentValidationResponse(BaseModel):
    """Result of validating the contents of a catalog directory."""

    valid: bool
    path: str
    total_files: int = 0
    image_count: int = 0
    files: list[str] = Field(default_factory=list)
    non_image_files: list[str] = Field(default_factory=list)
    invalid_files: list[dict[str, Any]] = Field(default_factory=list)
    invalid_names: list[str] = Field(
        default_factory=list,
        description='Files not named "<number>.<extension>", the only form PIM accepts',
    )
    min_required: int = 0
    allowed_extensions: list[str] = Field(default_factory=list)
    reason: Optional[str] = Field(
        None, description="i18n key describing why validation failed"
    )
    error_detail: Optional[str] = None
    skipped: bool = False


class PushPreflightResponse(BaseModel):
    """Combined name + content validation result for a candidate catalog."""

    ok: bool
    catalog: CatalogValidationResponse
    content: ContentValidationResponse


class FilePushBatchRequest(BaseModel):
    """Batch file push operation request (VF redesign)."""

    source_paths: list[str] = Field(
        ...,
        min_items=1,
        description="Source directory paths from Path A",
    )
    worker_id: int = Field(..., description="Worker ID to execute operation")


class FilePushBatchResult(BaseModel):
    """Batch push result for a single source path."""

    source_path: str
    success: bool
    operation_id: Optional[int] = None
    error: Optional[str] = None
    # Structured preflight rejection (catalog name / content), so the WebUI can
    # render i18n reasons and name suggestions per directory rather than a
    # flattened English string.
    validation: Optional[dict[str, Any]] = None


class FilePushBatchResponse(BaseModel):
    """Batch push response with per-path results."""

    results: list[FilePushBatchResult]


class FilePullRequest(BaseModel):
    """File pull operation request (VF redesign)."""

    operation_id: int = Field(..., description="ID of the original PUSH operation to revert")
    worker_id: int = Field(..., description="Worker ID to execute operation")


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


class PimDeliveryResponse(BaseModel):
    """Delivery state of an operation's PIM event (see pim_service)."""

    status: str  # PENDING | DELIVERED | FAILED | CANCELLED
    event_type: str
    tg_id: Optional[str] = None
    attempts: int = 0
    last_error: Optional[str] = None
    last_status_code: Optional[int] = None
    next_attempt_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[str] = None


class RemoteSyncFileResponse(BaseModel):
    name: str
    synced: bool = False
    status_code: Optional[int] = None


class RemoteSyncResponse(BaseModel):
    """Image host verification of a PUSH (see remote_sync_service)."""

    status: str  # WAITING | CHECKING | SYNCED | TIMEOUT | CANCELLED
    total_files: int = 0
    synced_files: int = 0
    files: list[RemoteSyncFileResponse] = Field(default_factory=list)
    attempts: int = 0
    started_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    next_check_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_error: Optional[str] = None
    # Set when a user stopped the check; a PULL cancels without them
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[str] = None


class IntegrationQueueResponse(BaseModel):
    """Background PIM deliveries and image host checks still scheduled to run."""

    pim_pending: int = 0
    pim_retrying: int = 0
    sync_waiting: int = 0
    sync_checking: int = 0


class IntegrationStopResponse(BaseModel):
    """Result of stopping queued PIM deliveries or image host checks."""

    stopped: int
    operation_ids: list[int] = Field(default_factory=list)


class OperationResponse(BaseModel):
    """Operation response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    user_name: Optional[str] = None  # Username for display in operation queue
    type: OperationType
    source_path: str
    dest_path: Optional[str]
    original_path: Optional[str] = None  # Original location for PUSH/PULL operations
    archive_path: Optional[str] = None  # Archive location for PUSH operations
    status: OperationStatus
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_msg: Optional[str]
    file_count: Optional[int]
    total_size_bytes: Optional[int]
    params_json: Optional[dict[str, Any]]
    rollback_operation_id: Optional[int] = None  # ID of original operation if this is a PULL
    has_been_pulled: bool = False  # True if this PUSH has been successfully pulled/reverted
    # PUSH only: completed UPDATE operations that changed this catalog, oldest first
    update_operation_ids: list[int] = Field(default_factory=list)
    # PUSH/PULL/UPDATE: PIM notification state, when PIM was signalled
    pim_delivery: Optional[PimDeliveryResponse] = None
    # PUSH only: image host verification, when enabled
    remote_sync: Optional[RemoteSyncResponse] = None
    created_at: datetime


class OperationDetailsResponse(BaseModel):
    """
    One operation with the operations linked to it, for the history details view.

    For a PUSH: every UPDATE made to its catalog (any status) and the PULL, if
    any. For an UPDATE or PULL: the PUSH it belongs to.
    """

    operation: OperationResponse
    push: Optional[OperationResponse] = None
    updates: list[OperationResponse] = Field(default_factory=list)
    pull: Optional[OperationResponse] = None


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
    ui_language: str
    pane_layout: str
    custom_settings: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class UserPreferencesUpdate(BaseModel):
    """User preferences update request."""

    remember_last_paths: Optional[bool] = None
    last_path_a: Optional[str] = Field(None, max_length=1000)
    last_path_b: Optional[str] = Field(None, max_length=1000)
    ui_theme: Optional[str] = Field(None, pattern="^(system|light|dark)$")
    ui_language: Optional[str] = Field(None, pattern="^(auto|[a-z]{2}(-[A-Z]{2})?)$")  # "auto", short codes ("en", "pl"), or full locale codes ("en-US", "pl-PL")
    pane_layout: Optional[str] = Field(None, pattern="^(horizontal|vertical)$")
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
    command_id: Optional[str] = None
    completion_time_ms: Optional[int] = None
    file_count: Optional[int] = None
    total_size_bytes: Optional[int] = None
    error_details: Optional[dict[str, Any]] = None


class CommandPollResponse(BaseModel):
    """Response for command polling endpoint."""

    command_id: Optional[int] = None
    command: Optional[str] = None
    source_path: Optional[str] = None
    dest_path: Optional[str] = None
    parameters: Optional[dict[str, Any]] = None


class CommandResponseRequest(BaseModel):
    """Request to submit command response."""

    status: str = Field(..., description="Response status: success, failed, error")
    message: Optional[str] = None
    file_count: Optional[int] = None
    total_size_bytes: Optional[int] = None
    error_details: Optional[dict[str, Any]] = None


class WorkerConfigResponse(BaseModel):
    """Worker configuration response."""

    path_a_prefix: Optional[str] = None
    path_b_prefix: Optional[str] = None
    path_c_prefix: Optional[str] = None
    polling_interval_seconds: int = 5
