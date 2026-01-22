"""
Advanced admin routes for system management.

Includes:
- Samba path management
- Worker provisioning and real-time control
- System monitoring and statistics
- Real-time log viewing
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy import select, update, delete, func, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings, Settings
from api.middleware.auth import require_admin
from api.middleware.logging import AuditLogger
from api.schemas import MessageResponse, WorkerResponse
from api.schemas_admin import (
    SambaPathCreate,
    SambaPathUpdate,
    SambaPathResponse,
    WorkerConfigRequest,
    WorkerStatusResponse,
    WorkerProvisionRequest,
    WorkerCommandRequest,
    WorkerCommandResponse,
    SystemStatsResponse,
    SystemHealthResponse,
    LogFilter,
    LogEntry,
    LogStreamResponse,
)
from api.services.worker_service import WorkerService, get_worker_by_id
from database import get_db
from models import User, Worker, Operation, AuditLog, WorkerStatus, OperationStatus
from models_admin import SambaPath, SystemMetrics


router = APIRouter(prefix="/api/admin", tags=["admin-system"])


# =============================================================================
# Samba Path Management
# =============================================================================

@router.get("/samba-paths", response_model=List[SambaPathResponse])
async def list_samba_paths(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = False,
):
    """List all Samba path configurations."""
    stmt = select(SambaPath)
    if not include_inactive:
        stmt = stmt.where(SambaPath.is_active == True)

    result = await db.execute(stmt)
    paths = result.scalars().all()
    return [SambaPathResponse.model_validate(p) for p in paths]


@router.post("/samba-paths", response_model=SambaPathResponse, status_code=status.HTTP_201_CREATED)
async def create_samba_path(
    path_data: SambaPathCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create new Samba path configuration."""
    # Check if name already exists
    stmt = select(SambaPath).where(SambaPath.name == path_data.name)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Samba path with name '{path_data.name}' already exists",
        )

    # Create path
    samba_path = SambaPath(
        name=path_data.name,
        path_prefix=path_data.path_prefix,
        description=path_data.description,
        is_active=path_data.is_active,
        share_type=path_data.share_type,
        requires_auth=path_data.requires_auth,
        metadata_json=path_data.metadata_json,
    )

    db.add(samba_path)
    await db.commit()
    await db.refresh(samba_path)

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="samba_path_create",
        target="samba_path",
        details={
            "path_id": samba_path.id,
            "name": samba_path.name,
            "prefix": samba_path.path_prefix,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return SambaPathResponse.model_validate(samba_path)


@router.put("/samba-paths/{path_id}", response_model=SambaPathResponse)
async def update_samba_path(
    path_id: int,
    path_data: SambaPathUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update Samba path configuration."""
    stmt = select(SambaPath).where(SambaPath.id == path_id)
    result = await db.execute(stmt)
    samba_path = result.scalar_one_or_none()

    if not samba_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Samba path with ID {path_id} not found",
        )

    # Update fields
    update_data = {}
    if path_data.name is not None:
        update_data["name"] = path_data.name
    if path_data.path_prefix is not None:
        update_data["path_prefix"] = path_data.path_prefix
    if path_data.description is not None:
        update_data["description"] = path_data.description
    if path_data.is_active is not None:
        update_data["is_active"] = path_data.is_active
    if path_data.share_type is not None:
        update_data["share_type"] = path_data.share_type
    if path_data.requires_auth is not None:
        update_data["requires_auth"] = path_data.requires_auth
    if path_data.metadata_json is not None:
        update_data["metadata_json"] = path_data.metadata_json

    if update_data:
        stmt = (
            update(SambaPath)
            .where(SambaPath.id == path_id)
            .values(**update_data)
        )
        await db.execute(stmt)
        await db.commit()
        await db.refresh(samba_path)

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="samba_path_update",
        target="samba_path",
        details={
            "path_id": path_id,
            "changes": path_data.model_dump(exclude_none=True),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return SambaPathResponse.model_validate(samba_path)


@router.delete("/samba-paths/{path_id}", response_model=MessageResponse)
async def delete_samba_path(
    path_id: int,
    request: Request,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete Samba path configuration."""
    stmt = select(SambaPath).where(SambaPath.id == path_id)
    result = await db.execute(stmt)
    samba_path = result.scalar_one_or_none()

    if not samba_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Samba path with ID {path_id} not found",
        )

    path_name = samba_path.name

    # Delete path
    stmt = delete(SambaPath).where(SambaPath.id == path_id)
    await db.execute(stmt)
    await db.commit()

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="samba_path_delete",
        target="samba_path",
        details={
            "path_id": path_id,
            "name": path_name,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return MessageResponse(
        message="Samba path deleted successfully",
        detail=f"Samba path '{path_name}' has been deleted",
    )


# =============================================================================
# Worker Provisioning & Control
# =============================================================================

@router.get("/workers/{worker_id}/status", response_model=WorkerStatusResponse)
async def get_worker_status(
    worker_id: int,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Get real-time worker status including configuration and performance metrics."""
    worker = await get_worker_by_id(worker_id, db)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    worker_service = WorkerService(settings)

    # Try to get real-time status from worker
    current_config = None
    uptime_seconds = None
    operations_processed = None
    operations_in_queue = None
    is_healthy = False
    health_issues = []

    try:
        # Send status command to worker
        from api.schemas import WorkerRequest
        status_cmd = WorkerRequest(command="get_status")
        response = await worker_service.send_command(worker, status_cmd, db)

        if response.status == "success" and response.error_details:
            current_config = response.error_details.get("config")
            uptime_seconds = response.error_details.get("uptime_seconds")
            operations_processed = response.error_details.get("operations_processed")
            operations_in_queue = response.error_details.get("operations_in_queue")
            is_healthy = True
    except Exception as exc:
        health_issues.append(f"Failed to communicate with worker: {str(exc)}")
        is_healthy = False

    # Check last heartbeat
    if worker.last_heartbeat:
        heartbeat_age = (datetime.now(timezone.utc) - worker.last_heartbeat).total_seconds()
        if heartbeat_age > 300:  # 5 minutes
            health_issues.append(f"Last heartbeat {int(heartbeat_age)}s ago")
            is_healthy = False

    return WorkerStatusResponse(
        worker_id=worker.id,
        worker_name=worker.name,
        hostname=worker.hostname,
        status=worker.status.value,
        last_heartbeat=worker.last_heartbeat,
        current_config=current_config,
        uptime_seconds=uptime_seconds,
        operations_processed=operations_processed,
        operations_in_queue=operations_in_queue,
        is_healthy=is_healthy,
        health_issues=health_issues,
    )


@router.post("/workers/{worker_id}/provision", response_model=WorkerResponse)
async def provision_worker(
    worker_id: int,
    provision_data: WorkerProvisionRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Provision worker with new configuration in real-time."""
    worker = await get_worker_by_id(worker_id, db)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    worker_service = WorkerService(settings)

    # Send configuration to worker
    try:
        from api.schemas import WorkerRequest
        config_cmd = WorkerRequest(
            command="update_config",
            params=provision_data.config.model_dump(exclude_none=True),
        )
        response = await worker_service.send_command(worker, config_cmd, db)

        if response.status != "success":
            raise HTTPException(
                status_code=500,
                detail=f"Worker rejected configuration: {response.message}",
            )

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to provision worker: {str(exc)}",
        )

    # Update database with new configuration
    update_data = {}
    if provision_data.config.path_a_prefix:
        update_data["path_a_prefix"] = provision_data.config.path_a_prefix
    if provision_data.config.path_b_prefix:
        update_data["path_b_prefix"] = provision_data.config.path_b_prefix

    if update_data:
        stmt = update(Worker).where(Worker.id == worker_id).values(**update_data)
        await db.execute(stmt)
        await db.commit()
        await db.refresh(worker)

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="worker_provision",
        target="worker",
        details={
            "worker_id": worker.id,
            "worker_name": worker.name,
            "config": provision_data.config.model_dump(exclude_none=True),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return WorkerResponse.model_validate(worker)


@router.post("/workers/{worker_id}/command", response_model=WorkerCommandResponse)
async def send_worker_command(
    worker_id: int,
    command_data: WorkerCommandRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Send real-time command to worker (ping, restart, reload_config, get_status)."""
    worker = await get_worker_by_id(worker_id, db)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    worker_service = WorkerService(settings)

    # Send command
    start_time = datetime.now(timezone.utc)
    try:
        from api.schemas import WorkerRequest
        cmd = WorkerRequest(
            command=command_data.command,
            params=command_data.params,
        )

        response = await worker_service.send_command(worker, cmd, db)
        duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        # Audit log
        await AuditLogger.log_admin_action(
            user_id=current_user.id,
            action="worker_command",
            target="worker",
            details={
                "worker_id": worker.id,
                "command": command_data.command,
                "status": response.status,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        return WorkerCommandResponse(
            command_id=response.command_id or "unknown",
            worker_id=worker.id,
            status=response.status,
            message=response.message,
            data=response.error_details,
            duration_ms=duration_ms,
        )

    except Exception as exc:
        duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        return WorkerCommandResponse(
            command_id="error",
            worker_id=worker.id,
            status="failed",
            message=str(exc),
            duration_ms=duration_ms,
        )


# =============================================================================
# System Monitoring & Statistics
# =============================================================================

@router.get("/stats/system", response_model=SystemStatsResponse)
async def get_system_stats(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get comprehensive system statistics."""
    from sqlalchemy import func as sql_func

    # Count active operations
    active_ops_stmt = select(sql_func.count(Operation.id)).where(
        Operation.status.in_([OperationStatus.PENDING, OperationStatus.IN_PROGRESS])
    )
    active_ops = (await db.execute(active_ops_stmt)).scalar() or 0

    # Count operations by status
    in_progress_stmt = select(sql_func.count(Operation.id)).where(
        Operation.status == OperationStatus.IN_PROGRESS
    )
    in_progress = (await db.execute(in_progress_stmt)).scalar() or 0

    pending_stmt = select(sql_func.count(Operation.id)).where(
        Operation.status == OperationStatus.PENDING
    )
    pending = (await db.execute(pending_stmt)).scalar() or 0

    # Count operations in last hour
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    completed_last_hour_stmt = select(sql_func.count(Operation.id)).where(
        Operation.status == OperationStatus.COMPLETED,
        Operation.completed_at >= one_hour_ago,
    )
    completed_last_hour = (await db.execute(completed_last_hour_stmt)).scalar() or 0

    failed_last_hour_stmt = select(sql_func.count(Operation.id)).where(
        Operation.status == OperationStatus.FAILED,
        Operation.completed_at >= one_hour_ago,
    )
    failed_last_hour = (await db.execute(failed_last_hour_stmt)).scalar() or 0

    # Count workers by status
    active_workers_stmt = select(sql_func.count(Worker.id)).where(
        Worker.status == WorkerStatus.ACTIVE
    )
    active_workers = (await db.execute(active_workers_stmt)).scalar() or 0

    suspended_workers_stmt = select(sql_func.count(Worker.id)).where(
        Worker.status == WorkerStatus.SUSPENDED
    )
    suspended_workers = (await db.execute(suspended_workers_stmt)).scalar() or 0

    pending_workers_stmt = select(sql_func.count(Worker.id)).where(
        Worker.status == WorkerStatus.PENDING
    )
    pending_workers = (await db.execute(pending_workers_stmt)).scalar() or 0

    # Count offline workers (no heartbeat in 5 minutes)
    five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
    offline_workers_stmt = select(sql_func.count(Worker.id)).where(
        Worker.status == WorkerStatus.ACTIVE,
        or_(
            Worker.last_heartbeat < five_min_ago,
            Worker.last_heartbeat == None,
        ),
    )
    offline_workers = (await db.execute(offline_workers_stmt)).scalar() or 0

    # Count users by role
    from models import UserRole
    total_users_stmt = select(sql_func.count(User.id))
    total_users = (await db.execute(total_users_stmt)).scalar() or 0

    admin_users_stmt = select(sql_func.count(User.id)).where(User.role == UserRole.ADMIN)
    admin_users = (await db.execute(admin_users_stmt)).scalar() or 0

    operator_users_stmt = select(sql_func.count(User.id)).where(User.role == UserRole.OPERATOR)
    operator_users = (await db.execute(operator_users_stmt)).scalar() or 0

    viewer_users_stmt = select(sql_func.count(User.id)).where(User.role == UserRole.VIEWER)
    viewer_users = (await db.execute(viewer_users_stmt)).scalar() or 0

    # Count active sessions (active users)
    from models import Session
    active_sessions_stmt = select(sql_func.count(Session.id)).where(
        Session.expires_at > datetime.now(timezone.utc)
    )
    active_users = (await db.execute(active_sessions_stmt)).scalar() or 0

    # Count samba paths
    samba_paths_stmt = select(sql_func.count(SambaPath.id)).where(
        SambaPath.is_active == True
    )
    samba_paths_active = (await db.execute(samba_paths_stmt)).scalar() or 0

    # Count audit logs
    audit_logs_stmt = select(sql_func.count(AuditLog.id))
    total_audit_logs = (await db.execute(audit_logs_stmt)).scalar() or 0

    # Calculate average operation duration
    avg_duration_stmt = select(
        sql_func.avg(
            sql_func.extract('epoch', Operation.completed_at - Operation.started_at)
        )
    ).where(
        Operation.status == OperationStatus.COMPLETED,
        Operation.completed_at.isnot(None),
        Operation.started_at.isnot(None),
    )
    avg_duration = (await db.execute(avg_duration_stmt)).scalar()

    return SystemStatsResponse(
        timestamp=datetime.now(timezone.utc),
        active_operations=active_ops,
        active_workers=active_workers,
        active_users=active_users,
        pending_workers=pending_workers,
        operations_completed_last_hour=completed_last_hour,
        operations_failed_last_hour=failed_last_hour,
        operations_in_progress=in_progress,
        operations_pending=pending,
        workers_healthy=active_workers - offline_workers,
        workers_suspended=suspended_workers,
        workers_offline=offline_workers,
        total_users=total_users,
        admin_users=admin_users,
        operator_users=operator_users,
        viewer_users=viewer_users,
        avg_operation_duration_seconds=float(avg_duration) if avg_duration else None,
        database_healthy=True,
        redis_healthy=True,
        samba_paths_active=samba_paths_active,
        total_audit_logs=total_audit_logs,
    )


@router.get("/health", response_model=SystemHealthResponse)
async def get_system_health(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get detailed system health status."""
    from database import health_check

    components = {}
    alerts = []
    overall_status = "healthy"

    # Check database
    db_healthy = await health_check()
    components["database"] = {
        "status": "healthy" if db_healthy else "critical",
        "message": "Connected" if db_healthy else "Connection failed",
    }
    if not db_healthy:
        overall_status = "critical"
        alerts.append({
            "severity": "critical",
            "component": "database",
            "message": "Database connection failed",
        })

    # Check Redis (placeholder)
    components["redis"] = {
        "status": "healthy",
        "message": "Connected",
    }

    # Check workers
    active_workers_stmt = select(func.count(Worker.id)).where(
        Worker.status == WorkerStatus.ACTIVE
    )
    active_workers_count = (await db.execute(active_workers_stmt)).scalar() or 0

    if active_workers_count == 0:
        components["workers"] = {
            "status": "warning",
            "message": "No active workers",
        }
        overall_status = "degraded" if overall_status == "healthy" else overall_status
        alerts.append({
            "severity": "warning",
            "component": "workers",
            "message": "No active workers available",
        })
    else:
        components["workers"] = {
            "status": "healthy",
            "message": f"{active_workers_count} active workers",
        }

    # Check API
    components["api"] = {
        "status": "healthy",
        "message": "Running",
    }

    return SystemHealthResponse(
        overall_status=overall_status,
        timestamp=datetime.now(timezone.utc),
        components=components,
        alerts=alerts,
    )


# =============================================================================
# Real-time Log Viewing
# =============================================================================

@router.get("/logs/stream", response_model=LogStreamResponse)
async def stream_logs(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    search_query: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    """Stream audit logs with filtering and pagination."""
    stmt = select(AuditLog).order_by(desc(AuditLog.timestamp))

    # Apply filters
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)

    if action is not None:
        stmt = stmt.where(AuditLog.action.like(f"%{action}%"))

    if start_time is not None:
        stmt = stmt.where(AuditLog.timestamp >= start_time)

    if end_time is not None:
        stmt = stmt.where(AuditLog.timestamp <= end_time)

    # Get total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = (await db.execute(count_stmt)).scalar() or 0

    # Apply pagination
    stmt = stmt.offset(offset).limit(limit)

    result = await db.execute(stmt)
    logs = result.scalars().all()

    # Convert to log entries
    log_entries = []
    for log in logs:
        # Get username
        username = None
        if log.user_id:
            user_stmt = select(User.username).where(User.id == log.user_id)
            username_result = await db.execute(user_stmt)
            username = username_result.scalar_one_or_none()

        log_entries.append(LogEntry(
            id=log.id,
            timestamp=log.timestamp,
            level="INFO",  # Default level
            user_id=log.user_id,
            username=username,
            action=log.action,
            details=log.details_json,
            ip_address=log.ip_address,
            user_agent=log.user_agent,
        ))

    return LogStreamResponse(
        logs=log_entries,
        total_count=total_count,
        offset=offset,
        limit=limit,
        has_more=(offset + len(log_entries)) < total_count,
    )
