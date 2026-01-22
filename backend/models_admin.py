"""
Additional admin models for RFM system management.

These models extend the base models with admin-specific functionality:
- Samba path management
- System monitoring
- Worker provisioning
"""

from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.sql import func

from models import Base


class SambaPath(Base):
    """
    Samba/SMB share path configuration.

    Defines available path prefixes that can be used in the system.
    These paths are assigned to workers and made available to users.
    """
    __tablename__ = "samba_paths"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False, index=True)
    path_prefix = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    # Optional metadata
    share_type = Column(String(50), nullable=True)  # e.g., "smb", "nfs", "local"
    requires_auth = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(JSON, nullable=True)

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
        return f"<SambaPath(id={self.id}, name='{self.name}', prefix='{self.path_prefix}')>"


class SystemMetrics(Base):
    """
    System performance and health metrics.

    Periodically collected metrics about system health, performance,
    and resource utilization.
    """
    __tablename__ = "system_metrics"

    id = Column(Integer, primary_key=True, index=True)

    # Metrics
    active_operations = Column(Integer, nullable=False, default=0)
    active_workers = Column(Integer, nullable=False, default=0)
    active_users = Column(Integer, nullable=False, default=0)

    # Performance
    avg_operation_duration_seconds = Column(Integer, nullable=True)
    operations_completed_last_hour = Column(Integer, nullable=False, default=0)
    operations_failed_last_hour = Column(Integer, nullable=False, default=0)

    # Resource usage (optional - can be populated from monitoring)
    cpu_usage_percent = Column(Integer, nullable=True)
    memory_usage_percent = Column(Integer, nullable=True)
    disk_usage_percent = Column(Integer, nullable=True)

    # Additional metrics
    metrics_json = Column(JSON, nullable=True)

    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    def __repr__(self) -> str:
        return f"<SystemMetrics(timestamp={self.timestamp}, ops={self.active_operations}, workers={self.active_workers})>"
