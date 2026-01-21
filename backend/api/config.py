"""
Configuration management for Modular File Manager API.

Uses pydantic-settings to load configuration from environment variables
with type validation and default values.
"""

import secrets
from typing import Optional

from pydantic import Field, field_validator, PostgresDsn
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
    access_token_expire_days: int = 30

    # TLS/SSL
    tls_enabled: bool = True
    tls_cert_path: Optional[str] = None
    tls_key_path: Optional[str] = None
    tls_min_version: str = "1.3"

    # CORS
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="Allowed CORS origins",
    )

    # Redis (Session Storage & Caching)
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 50

    # Worker Communication
    worker_timeout: int = 3600
    worker_retry_attempts: int = 3
    worker_retry_delays: list[int] = [2, 4, 8]
    worker_heartbeat_interval: int = 30
    worker_heartbeat_timeout: int = 90

    # External Integrations
    enable_sybase_auth: bool = False
    sybase_auth_url: Optional[str] = None
    sybase_auth_timeout: int = 2
    sybase_auth_stored_proc: Optional[str] = None

    enable_syslog: bool = False
    syslog_host: Optional[str] = None
    syslog_port: int = 514
    syslog_protocol: str = "UDP"

    enable_remote_audit_api: bool = False
    remote_audit_api_url: Optional[str] = None
    remote_audit_api_token: Optional[str] = None
    remote_audit_api_timeout: int = 5

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"
    log_retention_days: int = 14
    enable_json_logs: bool = True
    enable_file_logs: bool = False
    log_file_path: str = "/var/log/filemanager/api.log"

    # Application Limits
    max_concurrent_users: int = 4
    operation_timeout: int = 3600
    enable_auto_rollback: bool = True
    max_file_listing_items: int = 1000

    # Path Prefixes
    global_path_a_prefix: str = ""
    global_path_b_prefix: str = ""

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
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

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
