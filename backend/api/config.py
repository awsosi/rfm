"""
Configuration management for Modular File Manager API.

Uses pydantic-settings to load configuration from environment variables
with type validation and default values.
"""

import secrets
from typing import Optional

from pydantic import AliasChoices, Field, field_validator, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via .env file or environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Modular File Manager API"
    app_version: str = "1.0.0"
    debug: bool = False

    # API Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 4
    api_reload: bool = False
    api_url_public: str = Field(
        default="http://localhost:8000",
        description="Public-facing API URL for external clients",
    )
    frontend_url_public: str = Field(
        default="http://localhost:3000",
        description="Public-facing frontend URL for browser pages (device authorization, etc.)",
    )

    # Database
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://filemanager:changeme@localhost:5432/filemanager",
        description="PostgreSQL connection URL",
    )
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600
    db_echo: bool = False

    # Security
    secret_key: str = Field(
        default_factory=lambda: secrets.token_urlsafe(64),
        description="Secret key for JWT token signing",
    )
    algorithm: str = "HS256"

    # Session policy (seeds the config table; the Admin Panel is authoritative)
    session_lifetime_days: int = 5          # admins, and users without "Remember me"
    session_remember_me_days: int = 30      # "Remember me" (never for admins)
    admin_reauth_minutes: int = 15          # admin password confirmation for system settings

    # TLS/SSL
    tls_enabled: bool = True
    tls_cert_path: Optional[str] = None
    tls_key_path: Optional[str] = None
    tls_min_version: str = "1.3"

    # CORS
    cors_origins: str | list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="Allowed CORS origins (comma-separated string or JSON array)",
    )

    # Redis (Session Storage & Caching)
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 50

    # Elasticsearch (Search & Indexing)
    elasticsearch_enabled: bool = True
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_username: Optional[str] = None
    elasticsearch_password: Optional[str] = None
    elasticsearch_index_operations: str = "rfm-operations"
    elasticsearch_index_files: str = "rfm-files"
    elasticsearch_max_retries: int = 3
    elasticsearch_timeout: int = 30

    # Worker Communication
    worker_timeout: int = 3600
    worker_retry_attempts: int = 3
    worker_retry_delays: list[int] = [2, 4, 8]
    worker_heartbeat_interval: int = 30
    worker_heartbeat_timeout: int = 180

    # External Integrations
    # PolkaSQL Authentication (Sybase SQL Anywhere 17 - RFM_Auth WebService)
    # Accepts both ENABLE_POLKA_AUTH and POLKA_AUTH_ENABLED env vars
    polka_auth_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices('enable_polka_auth', 'polka_auth_enabled'),
    )
    polka_auth_url: Optional[str] = None
    polka_auth_api_key: Optional[str] = None
    polka_auth_timeout: int = 5

    enable_syslog: bool = False
    syslog_host: Optional[str] = None
    syslog_port: int = 514
    syslog_protocol: str = "UDP"
    syslog_format: str = "RFC5424"
    syslog_hostname: Optional[str] = None

    enable_remote_audit_api: bool = False
    remote_audit_api_url: Optional[str] = None
    remote_audit_api_token: Optional[str] = None
    remote_audit_api_timeout: int = 5

    # ROSAPI - Remote Operation Signalling API (PIM Integration)
    rosapi_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices('enable_rosapi', 'rosapi_enabled'),
    )
    rosapi_base_url: Optional[str] = None

    # Authentication configuration
    rosapi_auth_base_url: Optional[str] = None  # Defaults to rosapi_base_url if not set
    rosapi_auth_login_endpoint: str = "/api/v1/auth/login"
    rosapi_auth_refresh_endpoint: str = "/api/v1/auth/refresh"
    rosapi_auth_email: Optional[str] = None
    rosapi_auth_password: Optional[str] = None
    rosapi_timeout: int = 10

    # PUSH operation signalling
    rosapi_push_enabled: bool = True
    rosapi_push_base_url: Optional[str] = None  # Defaults to rosapi_base_url if not set
    rosapi_push_endpoint: str = "/api/v1/products/tg/{folder_name}/set_image_catalog"
    rosapi_push_method: str = "POST"
    rosapi_push_payload: str = '{"generate_thumbnails": false}'

    # PULL operation signalling
    rosapi_pull_enabled: bool = False
    rosapi_pull_base_url: Optional[str] = None  # Defaults to rosapi_base_url if not set
    rosapi_pull_endpoint: str = ""
    rosapi_pull_method: str = "POST"
    rosapi_pull_payload: str = "{}"

    # Verification (optional)
    rosapi_verify_base_url: Optional[str] = None  # Defaults to rosapi_base_url if not set
    rosapi_verify_endpoint: Optional[str] = None

    # ------------------------------------------------------------------
    # PIM - Product Information Manager signalling
    # ------------------------------------------------------------------
    # Second, independent signalling target alongside ROSAPI. Authenticates
    # with a static X-API-TOKEN header rather than a JWT login flow.
    # Fires on PUSH (created), PULL (updated) and UPDATE (updated).
    pim_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices('enable_pim', 'pim_enabled'),
    )
    pim_base_url: str = "https://pim-api.vitkac.com"
    pim_endpoint: str = "/api/v1/image_catalog/ftp_event"
    pim_method: str = "POST"
    pim_api_token: Optional[str] = None
    pim_timeout: int = 10

    # Per-operation toggles and the eventType each one reports
    pim_push_enabled: bool = True
    pim_push_event_type: str = "created"
    pim_pull_enabled: bool = True
    pim_pull_event_type: str = "deleted"
    pim_update_enabled: bool = True
    pim_update_event_type: str = "updated"

    # Fully customisable payload body. Supported placeholders:
    #   {files}        -> JSON array of top-level basenames (unquoted, raw JSON)
    #   {catalog_name} -> catalog/folder name being signalled
    #   {event_type}   -> resolved eventType for this operation
    #   {tg_id}        -> product tgId (Polka27.elementy.grup_nazwe_kolor), the
    #                     matched_name from RFM_ValidateProductName
    #   {operation_id}, {username}, {source_path}, {dest_path}
    pim_payload_template: str = (
        '{"tgId": "{tg_id}", "imageCatalog": "{catalog_name}", '
        '"eventType": "{event_type}", "files": {files}}'
    )

    # Delivery retries: base delay doubling per failed attempt up to the max
    # delay; give up after pim_retry_max_hours (0 = keep retrying)
    pim_retry_base_seconds: int = 10
    pim_retry_max_delay_seconds: int = 600
    pim_retry_max_hours: int = 72

    # ------------------------------------------------------------------
    # Image host synchronization verification (off by default)
    # ------------------------------------------------------------------
    remote_sync_check_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices('enable_remote_sync_check', 'remote_sync_check_enabled'),
    )
    # Placeholders (URL-encoded): {catalog_name} {file} {tg_id}
    remote_sync_check_url_template: str = (
        "https://img.vitkac.com/uploads/product_thumb/{catalog_name}/up/{file}"
    )
    remote_sync_check_wait_for_pim: bool = True
    remote_sync_check_initial_delay_seconds: int = 60
    remote_sync_check_interval_seconds: int = 120
    remote_sync_check_timeout_minutes: int = 180
    remote_sync_check_request_timeout: int = 15
    # Bypass CDN caches, which were seen serving stale 404s and empty 200s
    remote_sync_check_cache_bust: bool = True

    # ------------------------------------------------------------------
    # Catalog name validation (PolkaSQL RFM_ValidateProductName)
    # ------------------------------------------------------------------
    catalog_validation_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices('enable_catalog_validation', 'catalog_validation_enabled'),
    )
    catalog_validation_url: Optional[str] = None
    catalog_validation_api_key: Optional[str] = None
    # A miss takes ~7 s on PolkaSQL: SIMILAR() over all ~1M elementy rows
    catalog_validation_timeout: int = 20
    catalog_validation_max_suggestions: int = 5
    # Fail-closed by default: an unreachable PolkaSQL refuses the operation.
    # Flip to true to let pushes through during a PolkaSQL outage.
    catalog_validation_fail_open: bool = False

    # ------------------------------------------------------------------
    # Directory content validation for PUSH / UPDATE
    # ------------------------------------------------------------------
    push_validation_enabled: bool = True
    push_validation_min_files: int = 2
    push_validation_allowed_extensions: str = "jpg,jpeg,png,gif,bmp,tif,tiff,webp"
    # Verify real file type from magic bytes, not just the extension
    push_validation_verify_content: bool = True
    # Require "<number>.<extension>" file names (e.g. "3.png"), the only form PIM accepts
    push_validation_file_names: bool = Field(
        default=True,
        validation_alias=AliasChoices('enable_push_validation_file_names', 'push_validation_file_names'),
    )
    # Suffixes also allowed between the number and the extension, e.g. "3_ai.png".
    # Comma-separated, matched case-insensitively; empty means numbers only.
    push_validation_name_suffixes: str = "_ai"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"
    log_retention_days: int = 14
    enable_json_logs: bool = True
    enable_file_logs: bool = False
    log_file_path: str = "/var/log/filemanager/api.log"

    # Application Limits
    max_concurrent_users: int = 30
    operation_timeout: int = 3600
    enable_auto_rollback: bool = True
    max_file_listing_items: int = 1000

    # Path Prefixes
    global_path_a_prefix: str = ""
    global_path_b_prefix: str = ""

    # VF Redesign: Preset paths for Push/Pull operations
    path_b: Optional[str] = Field(
        default=None,
        description="Destination path for PUSH operations (admin-configurable)",
    )
    path_c: Optional[str] = Field(
        default=None,
        description="Archive path for PUSH operations (admin-configurable)",
    )

    # PUSH operation behavior
    enable_push_flatten: bool = False
    enable_push_archive: bool = False
    push_ignore_file_masks: str = "Thumbs.db"
    # Also ignore (and destroy at source) OS metadata files: .DS_Store, ._*, Thumbs.db, desktop.ini, ...
    push_ignore_system_files: bool = Field(
        default=True,
        validation_alias=AliasChoices('enable_push_ignore_system_files', 'push_ignore_system_files'),
    )

    # UPDATE operation behavior
    # Mirrors in-place changes made in PATH_B into the PATH_C archive.
    # Defaults off: the downstream archive is not in use yet.
    enable_update_archive_mirror: bool = False

    # UPDATE uploads (files sent through the WebUI to replace/add catalog files)
    # Directory on the API host holding uploads until the worker fetches them.
    # Must be shared by every API process (a volume, not per-process /tmp).
    update_upload_dir: str = "/var/lib/file-manager/uploads"
    update_upload_max_mb: int = 200
    update_upload_ttl_hours: int = 24

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure database URL uses async driver."""
        if isinstance(v, str):
            if v.startswith("postgresql://"):
                v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif not v.startswith("postgresql+asyncpg://"):
                raise ValueError(
                    "DATABASE_URL must use postgresql:// or postgresql+asyncpg://"
                )
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v) -> list[str]:
        """Parse CORS origins from comma-separated string or list."""
        if isinstance(v, str):
            # Handle empty string or whitespace-only string
            if not v.strip():
                return ["http://localhost:3000", "http://localhost:8080"]
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        if isinstance(v, list):
            return v
        # Fallback to default
        return ["http://localhost:3000", "http://localhost:8080"]

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return v

    @property
    def database_url_str(self) -> str:
        """Get database URL as string."""
        return str(self.database_url)


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """
    Get application settings.

    Returns:
        Settings instance with configuration from environment.
    """
    return settings
