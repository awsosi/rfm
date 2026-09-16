"""
Advanced admin routes for system management.

Includes:
- Samba path management
- Worker provisioning and real-time control
- System monitoring and statistics
- Real-time log viewing
- Elasticsearch file indexing
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from loguru import logger
from sqlalchemy import select, update, delete, func, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings, Settings
from api.middleware.auth import require_admin
from api.middleware.logging import AuditLogger, get_client_ip
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
    AppLogEntry,
    AppLogResponse,
    LogConfigUpdate,
    LogConfigResponse,
)
from api.services.worker_service import WorkerService, get_worker_by_id, unwrap_worker_data
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
        ip_address=get_client_ip(request),
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
        ip_address=get_client_ip(request),
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
        ip_address=get_client_ip(request),
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
            # The worker route nests the worker's payload inside error_details;
            # reading it directly returned None for every field below.
            status_data = unwrap_worker_data(response)
            current_config = status_data.get("config")
            uptime_seconds = status_data.get("uptime_seconds")
            operations_processed = status_data.get("operations_processed")
            operations_in_queue = status_data.get("operations_in_queue")
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
    if provision_data.config.path_c_prefix:
        update_data["path_c_prefix"] = provision_data.config.path_c_prefix

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
        ip_address=get_client_ip(request),
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
            ip_address=get_client_ip(request),
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


@router.post("/test-path")
async def test_path(
    request: Request,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Test if a path is accessible by an active worker."""
    body = await request.json()
    path = body.get("path")
    path_type = body.get("path_type", "Unknown")

    if not path:
        raise HTTPException(status_code=400, detail="Path is required")

    # Get any active worker
    stmt = select(Worker).where(Worker.status == WorkerStatus.ACTIVE).limit(1)
    result = await db.execute(stmt)
    worker = result.scalar_one_or_none()

    if not worker:
        raise HTTPException(
            status_code=503,
            detail="No active workers available to test path"
        )

    # Send info command to check if path exists
    worker_service = WorkerService(settings)

    try:
        from api.schemas import WorkerRequest

        command = WorkerRequest(
            command="info",
            params={"path": path}
        )

        response = await worker_service.send_command(worker, command, db)

        # Audit log
        await AuditLogger.log_admin_action(
            user_id=current_user.id,
            action="test_path",
            target="system",
            details={
                "path": path,
                "path_type": path_type,
                "worker_id": worker.id,
                "success": response.status == "success",
            },
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )

        return {
            "success": response.status == "success",
            "message": response.message,
            "path": path,
            "path_type": path_type,
            "worker": worker.name,
        }

    except Exception as exc:
        await AuditLogger.log_admin_action(
            user_id=current_user.id,
            action="test_path",
            target="system",
            details={
                "path": path,
                "path_type": path_type,
                "worker_id": worker.id,
                "success": False,
                "error": str(exc),
            },
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )

        return {
            "success": False,
            "error": str(exc),
            "path": path,
            "path_type": path_type,
        }


# =============================================================================
# System Monitoring & Statistics
# =============================================================================


async def _check_redis() -> bool:
    """Ping Redis and return True if healthy."""
    try:
        import redis.asyncio as aioredis
        settings = get_settings()
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
        result = await r.ping()
        await r.aclose()
        return bool(result)
    except Exception:
        return False


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

    user_users_stmt = select(sql_func.count(User.id)).where(User.role == UserRole.USER)
    regular_users = (await db.execute(user_users_stmt)).scalar() or 0

    # Count active sessions (active users)
    from models import Session
    active_sessions_stmt = select(sql_func.count(Session.id)).where(
        Session.expires_at > datetime.now(timezone.utc)
    )
    active_users = (await db.execute(active_sessions_stmt)).scalar() or 0

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
        operator_users=0,  # Deprecated, kept for compatibility
        viewer_users=regular_users,  # Regular users (renamed from viewer)
        avg_operation_duration_seconds=float(avg_duration) if avg_duration else None,
        database_healthy=True,
        redis_healthy=await _check_redis(),
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

    # Check Elasticsearch
    try:
        settings = get_settings()
        if not settings.elasticsearch_enabled:
            components["elasticsearch"] = {
                "status": "warning",
                "message": "Disabled in configuration",
            }
        else:
            from api.services.elasticsearch_service import get_elasticsearch_service
            es_service = await get_elasticsearch_service()
            if es_service.is_enabled and es_service._client:
                try:
                    es_healthy = await es_service._client.ping()
                except Exception:
                    es_healthy = False
                components["elasticsearch"] = {
                    "status": "healthy" if es_healthy else "warning",
                    "message": "Connected" if es_healthy else "Connection failed",
                }
                if not es_healthy:
                    overall_status = "degraded" if overall_status == "healthy" else overall_status
                    alerts.append({
                        "severity": "warning",
                        "component": "elasticsearch",
                        "message": "Elasticsearch connection failed",
                    })
            else:
                # Enabled in config but initialization failed
                overall_status = "degraded" if overall_status == "healthy" else overall_status
                components["elasticsearch"] = {
                    "status": "warning",
                    "message": "Enabled but connection failed (will retry)",
                }
                alerts.append({
                    "severity": "warning",
                    "component": "elasticsearch",
                    "message": "Elasticsearch enabled but not connected",
                })
    except Exception:
        components["elasticsearch"] = {
            "status": "warning",
            "message": "Not available",
        }

    # Check Redis
    redis_healthy = await _check_redis()
    components["redis"] = {
        "status": "healthy" if redis_healthy else "warning",
        "message": "Connected" if redis_healthy else "Connection failed",
    }
    if not redis_healthy:
        overall_status = "degraded" if overall_status == "healthy" else overall_status
        alerts.append({
            "severity": "warning",
            "component": "redis",
            "message": "Redis connection failed",
        })

    # Check API (always healthy if we reached this point)
    components["api"] = {
        "status": "healthy",
        "message": "Running",
    }

    # Check WebUI (always healthy since it's served by the same stack)
    components["webui"] = {
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

    if search_query is not None and search_query.strip():
        search_term = f"%{search_query.strip()}%"
        from sqlalchemy import cast, String
        stmt = stmt.where(
            or_(
                AuditLog.action.ilike(search_term),
                AuditLog.ip_address.ilike(search_term),
                cast(AuditLog.details_json, String).ilike(search_term),
            )
        )

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


@router.get("/logs/application", response_model=AppLogResponse)
async def get_application_logs(
    current_user: Annotated[User, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    level: Optional[str] = Query(None, description="Filter by log level (DEBUG, INFO, WARNING, ERROR)"),
    search: Optional[str] = Query(None, description="Search in log messages"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    """
    Get application logs from log file.

    Reads from the configured log file path (LOG_FILE_PATH environment variable).
    If file logging is not enabled, returns empty result.
    """
    import os
    import json
    from pathlib import Path

    log_file_path = getattr(settings, 'log_file_path', '/var/log/filemanager/api.log')
    enable_file_logs = getattr(settings, 'enable_file_logs', False)

    if not enable_file_logs or not log_file_path:
        return AppLogResponse(
            logs=[],
            total_lines=0,
            offset=offset,
            limit=limit,
            has_more=False,
            log_source="file",
        )

    log_path = Path(log_file_path)
    if not log_path.exists():
        return AppLogResponse(
            logs=[],
            total_lines=0,
            offset=offset,
            limit=limit,
            has_more=False,
            log_source="file",
        )

    # Read log file (last N lines for efficiency)
    try:
        log_entries = []
        total_lines = 0

        with open(log_path, 'r') as f:
            # Read all lines and reverse for newest first
            lines = f.readlines()
            total_lines = len(lines)
            lines = list(reversed(lines))

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                try:
                    # Try to parse as JSON log
                    log_data = json.loads(line)
                    log_level = log_data.get('level', 'INFO').upper()
                    log_message = log_data.get('message', line)
                    log_timestamp = log_data.get('timestamp', datetime.now(timezone.utc).isoformat())
                except json.JSONDecodeError:
                    # Plain text log
                    log_level = 'INFO'
                    log_message = line
                    log_timestamp = datetime.now(timezone.utc).isoformat()
                    log_data = {}

                # Apply filters
                if level and log_level != level.upper():
                    continue
                if search and search.lower() not in log_message.lower():
                    continue

                # Parse timestamp
                try:
                    if isinstance(log_timestamp, str):
                        ts = datetime.fromisoformat(log_timestamp.replace('Z', '+00:00'))
                    else:
                        ts = log_timestamp
                except:
                    ts = datetime.now(timezone.utc)

                log_entries.append(AppLogEntry(
                    timestamp=ts,
                    level=log_level,
                    message=log_message,
                    logger=log_data.get('logger'),
                    extra=log_data.get('extra'),
                ))

        # Apply pagination
        total_filtered = len(log_entries)
        log_entries = log_entries[offset:offset + limit]

        return AppLogResponse(
            logs=log_entries,
            total_lines=total_filtered,
            offset=offset,
            limit=limit,
            has_more=(offset + len(log_entries)) < total_filtered,
            log_source="file",
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reading log file: {str(e)}",
        )


@router.get("/logs/config", response_model=LogConfigResponse)
async def get_logging_config(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Get current logging configuration from database and environment."""
    from models import Config

    # Get config values from database
    config_keys = [
        'enable_syslog', 'syslog_host', 'syslog_port', 'syslog_protocol',
        'syslog_format', 'syslog_hostname',
        'log_retention_days', 'enable_log_compression'
    ]

    config_values = {}
    for key in config_keys:
        stmt = select(Config).where(Config.key == key)
        result = await db.execute(stmt)
        config = result.scalar_one_or_none()
        if config:
            config_values[key] = config.value

    return LogConfigResponse(
        log_level=getattr(settings, 'log_level', 'INFO'),
        enable_file_logs=getattr(settings, 'enable_file_logs', False),
        log_file_path=getattr(settings, 'log_file_path', None),
        enable_syslog=config_values.get('enable_syslog', 'false').lower() == 'true',
        syslog_host=config_values.get('syslog_host'),
        syslog_port=int(config_values.get('syslog_port', '514')),
        syslog_protocol=config_values.get('syslog_protocol', 'UDP'),
        syslog_format=config_values.get('syslog_format', 'RFC5424'),
        syslog_hostname=config_values.get('syslog_hostname') or None,
        log_retention_days=int(config_values.get('log_retention_days', '14')),
        enable_log_compression=config_values.get('enable_log_compression', 'true').lower() == 'true',
    )


@router.put("/logs/config", response_model=LogConfigResponse)
async def update_logging_config(
    config_data: LogConfigUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Update logging configuration and reconfigure syslog handler at runtime."""
    from models import Config

    # Map schema fields to DB config keys
    field_to_key = {
        'enable_syslog': 'enable_syslog',
        'syslog_host': 'syslog_host',
        'syslog_port': 'syslog_port',
        'syslog_protocol': 'syslog_protocol',
        'syslog_format': 'syslog_format',
        'syslog_hostname': 'syslog_hostname',
        'log_retention_days': 'log_retention_days',
        'enable_log_compression': 'enable_log_compression',
    }

    updates = config_data.model_dump(exclude_none=True)
    updated_keys = []

    for field_name, db_key in field_to_key.items():
        if field_name not in updates:
            continue

        value = updates[field_name]
        # Convert booleans and ints to string for DB storage
        if isinstance(value, bool):
            value = 'true' if value else 'false'
        else:
            value = str(value)

        stmt = select(Config).where(Config.key == db_key)
        result = await db.execute(stmt)
        config = result.scalar_one_or_none()

        if config:
            stmt = update(Config).where(Config.key == db_key).values(value=value)
            await db.execute(stmt)
        else:
            # Create config entry if it doesn't exist
            new_config = Config(key=db_key, value=value, type='STRING')
            db.add(new_config)

        updated_keys.append(db_key)

    await db.commit()

    # Reconfigure syslog handler at runtime
    try:
        import logging_module.logger as lm_logger
        from logging_module.handlers import SyslogHandler, MultiHandler

        # Create MultiHandler if it doesn't exist
        if lm_logger._global_handler is None:
            lm_logger._global_handler = MultiHandler()
            logger.info("Created MultiHandler for syslog reconfiguration (was None)")

        handler = lm_logger._global_handler

        # If any syslog setting changed, reconfigure
        syslog_keys = ['enable_syslog', 'syslog_host', 'syslog_port', 'syslog_protocol', 'syslog_format', 'syslog_hostname']
        if any(k in updates for k in syslog_keys):
            # Remove existing syslog handlers
            handler.handlers = [
                h for h in handler.handlers
                if not isinstance(h, SyslogHandler)
            ]

            # Re-read full config from DB to get current values
            config_keys = ['enable_syslog', 'syslog_host', 'syslog_port', 'syslog_protocol', 'syslog_format', 'syslog_hostname']
            config_values = {}
            for key in config_keys:
                stmt = select(Config).where(Config.key == key)
                result = await db.execute(stmt)
                cfg = result.scalar_one_or_none()
                if cfg:
                    config_values[key] = cfg.value

            is_enabled = config_values.get('enable_syslog', 'false').lower() == 'true'
            host = config_values.get('syslog_host')
            port = int(config_values.get('syslog_port', '514'))
            protocol = config_values.get('syslog_protocol', 'UDP')
            syslog_format = config_values.get('syslog_format', 'RFC5424')
            syslog_hostname = config_values.get('syslog_hostname') or None

            if is_enabled and host:
                new_syslog = SyslogHandler(
                    host=host, port=port, protocol=protocol,
                    syslog_format=syslog_format, hostname=syslog_hostname,
                )
                handler.add_handler(new_syslog)
                logger.info(f"Syslog handler reconfigured: {host}:{port}/{protocol} format={syslog_format}")

    except Exception as exc:
        logger.warning(f"Failed to reconfigure syslog handler at runtime: {exc}")

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="logging_config_update",
        target="logging",
        details={"updated_keys": updated_keys, "values": updates},
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    # Return updated config
    return await get_logging_config(current_user, db, settings)


# =============================================================================
# Elasticsearch File Indexing
# =============================================================================

@router.post("/index-files/{worker_id}", response_model=MessageResponse)
async def index_worker_files(
    worker_id: int,
    request: Request,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    recursive: bool = Query(True, description="Recursively index all subdirectories"),
):
    """
    Trigger file indexing for a worker into Elasticsearch.
    
    This endpoint:
    1. Lists all files/directories from the worker's Path A
    2. Indexes them into Elasticsearch for fast searching
    3. Returns the count of indexed files
    
    Note: This may take time for large directory structures.
    """
    from api.services.elasticsearch_service import get_elasticsearch_service
    
    # Get worker
    worker = await get_worker_by_id(worker_id, db)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    # Check if worker is active
    if worker.status != WorkerStatus.ACTIVE:
        raise HTTPException(
            status_code=400,
            detail=f"Worker is not active (status: {worker.status.value})"
        )
    
    # Check if Elasticsearch is enabled
    es_service = await get_elasticsearch_service()
    if not es_service.is_enabled:
        raise HTTPException(
            status_code=503,
            detail="Elasticsearch is not enabled. File search will fall back to worker-side search."
        )
    
    try:
        # Initialize worker service
        worker_service = WorkerService(settings)
        
        # Get files from worker's Path A
        root_path = worker.path_a_prefix or "A:"
        
        async def index_directory(path: str, depth: int = 0) -> int:
            """Recursively index directory and its contents."""
            indexed_count = 0
            max_depth = 10  # Prevent infinite recursion
            
            if depth > max_depth:
                logger.warning(f"Max recursion depth reached at {path}")
                return indexed_count
            
            try:
                # List directory
                response = await worker_service.list_directory(
                    worker, path, db, offset=0, limit=1000
                )
                
                listing = unwrap_worker_data(response)
                if "items" in listing:
                    files_to_index = []
                    subdirs = []

                    for item in listing["items"]:
                        # Prepare file data for Elasticsearch
                        file_data = {
                            "path": item.get("path", ""),
                            "name": item.get("name", ""),
                            "parent_path": path,
                            "is_directory": item.get("is_directory", False),
                            "size": item.get("size_bytes", item.get("size", 0)),
                            "modified_at": item.get("modified_at"),
                            "worker_id": worker_id,
                        }
                        
                        files_to_index.append(file_data)
                        
                        # Track subdirectories for recursive indexing
                        if recursive and item.get("is_directory"):
                            subdirs.append(item.get("path", ""))
                    
                    # Bulk index current batch
                    if files_to_index:
                        count = await es_service.bulk_index_files(files_to_index)
                        indexed_count += count
                        logger.info(f"Indexed {count} items from {path}")
                    
                    # Recursively index subdirectories
                    if recursive:
                        for subdir in subdirs:
                            subcount = await index_directory(subdir, depth + 1)
                            indexed_count += subcount
                
            except Exception as e:
                logger.error(f"Error indexing directory {path}: {e}")
            
            return indexed_count
        
        # Start indexing from root
        logger.info(f"Starting file indexing for worker {worker_id} at {root_path}")
        total_indexed = await index_directory(root_path)
        
        # Log to audit trail
        await AuditLogger.log(
            db=db,
            request=request,
            user_id=current_user.id,
            action="index_files",
            details={
                "worker_id": worker_id,
                "worker_name": worker.hostname,
                "root_path": root_path,
                "total_indexed": total_indexed,
                "recursive": recursive,
            },
        )
        
        return MessageResponse(
            message=f"Successfully indexed {total_indexed} files/directories for worker {worker.hostname}",
            details={"total_indexed": total_indexed, "worker_id": worker_id}
        )
    
    except Exception as e:
        logger.error(f"File indexing failed for worker {worker_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"File indexing failed: {str(e)}"
        )
