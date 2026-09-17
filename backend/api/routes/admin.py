"""
Admin API routes for user management, worker management, and system configuration.

All endpoints require ADMIN role.
"""

from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings, Settings
from api.middleware.auth import get_current_user, require_admin, require_recent_auth
from api.middleware.logging import AuditLogger, get_client_ip
from api.schemas import (
    IntegrationQueueResponse,
    IntegrationStopResponse,
    UserCreate,
    UserUpdate,
    UserResponse,
    WorkerUpdate,
    WorkerResponse,
    ConfigResponse,
    ConfigUpdate,
    ConfigBulkUpdate,
    MessageResponse,
)
from auth.utils import hash_password
from database import get_db
from models import User, Worker, Config, ConfigType, WorkerStatus, UserRole
from sqlalchemy import func


router = APIRouter(prefix="/api/admin", tags=["admin"])


# =============================================================================
# User Management
# =============================================================================


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_recent_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a new user."""
    # Check if username already exists
    stmt = select(User).where(User.username == user_data.username)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with username '{user_data.username}' already exists",
        )

    # Hash password
    password_hash = hash_password(user_data.password)

    # Create user
    user = User(
        username=user_data.username,
        password_hash=password_hash,
        role=user_data.role,
        is_active=True,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="user_create",
        target="user",
        details={
            "created_user_id": user.id,
            "username": user.username,
            "role": user.role.value,
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return UserResponse.model_validate(user)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_recent_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update user information."""
    # Get user
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found",
        )

    # Block username/password changes for PolkaSQL auth users
    if user.is_polka_auth:
        if user_data.username is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot modify username for PolkaSQL-authenticated users",
            )
        if user_data.password is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot modify password for PolkaSQL-authenticated users",
            )

    # Prevent self-deactivation
    if user.id == current_user.id and user_data.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    # Prevent demoting or deactivating the last admin
    if user.role == UserRole.ADMIN:
        is_role_change = user_data.role is not None and user_data.role != UserRole.ADMIN
        is_deactivation = user_data.is_active is False

        if is_role_change or is_deactivation:
            # Count active admins
            stmt = select(func.count()).select_from(User).where(
                User.role == UserRole.ADMIN,
                User.is_active == True
            )
            result = await db.execute(stmt)
            admin_count = result.scalar()

            if admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot demote or deactivate the last admin user",
                )

    # Update fields
    update_data = {}
    if user_data.username is not None:
        update_data["username"] = user_data.username
    if user_data.password is not None:
        update_data["password_hash"] = hash_password(user_data.password)
    if user_data.role is not None:
        update_data["role"] = user_data.role
    if user_data.is_active is not None:
        update_data["is_active"] = user_data.is_active

    if update_data:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(**update_data)
        )
        await db.execute(stmt)
        await db.commit()
        await db.refresh(user)

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="user_update",
        target="user",
        details={
            "updated_user_id": user.id,
            "username": user.username,
            "changes": user_data.model_dump(exclude_none=True, exclude={"password"}),
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return UserResponse.model_validate(user)


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: int,
    request: Request,
    current_user: Annotated[User, Depends(require_recent_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a user."""
    # Prevent self-deletion
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    # Get user
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found",
        )

    # Prevent deleting the last admin
    if user.role == UserRole.ADMIN:
        stmt = select(func.count()).select_from(User).where(
            User.role == UserRole.ADMIN,
            User.is_active == True
        )
        result = await db.execute(stmt)
        admin_count = result.scalar()

        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last admin user",
            )

    username = user.username

    # Delete user (cascade will handle sessions, operations, audit logs)
    stmt = delete(User).where(User.id == user_id)
    await db.execute(stmt)
    await db.commit()

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="user_delete",
        target="user",
        details={
            "deleted_user_id": user_id,
            "username": username,
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return MessageResponse(
        message="User deleted successfully",
        detail=f"User '{username}' has been deleted",
    )


# =============================================================================
# Worker Management
# =============================================================================


@router.get("/workers", response_model=List[WorkerResponse])
async def list_all_workers(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    include_pending: bool = True,
):
    """List all workers including pending approvals."""
    stmt = select(Worker)
    if not include_pending:
        stmt = stmt.where(Worker.status != WorkerStatus.PENDING)

    result = await db.execute(stmt)
    workers = result.scalars().all()
    return [WorkerResponse.model_validate(w) for w in workers]


@router.put("/workers/{worker_id}", response_model=WorkerResponse)
async def update_worker(
    worker_id: int,
    worker_data: WorkerUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_recent_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update worker configuration (approve, suspend, update paths)."""
    # Get worker
    stmt = select(Worker).where(Worker.id == worker_id)
    result = await db.execute(stmt)
    worker = result.scalar_one_or_none()

    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker with ID {worker_id} not found",
        )

    # Update fields
    update_data = {}
    if worker_data.status is not None:
        update_data["status"] = worker_data.status
    if worker_data.path_a_prefix is not None:
        update_data["path_a_prefix"] = worker_data.path_a_prefix
    if worker_data.path_b_prefix is not None:
        update_data["path_b_prefix"] = worker_data.path_b_prefix
    if worker_data.path_c_prefix is not None:
        update_data["path_c_prefix"] = worker_data.path_c_prefix

    if update_data:
        stmt = (
            update(Worker)
            .where(Worker.id == worker_id)
            .values(**update_data)
        )
        await db.execute(stmt)
        await db.commit()
        await db.refresh(worker)

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="worker_update",
        target="worker",
        details={
            "worker_id": worker.id,
            "worker_name": worker.name,
            "changes": worker_data.model_dump(exclude_none=True),
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return WorkerResponse.model_validate(worker)


@router.post("/workers/{worker_id}/approve", response_model=WorkerResponse)
async def approve_worker(
    worker_id: int,
    request: Request,
    current_user: Annotated[User, Depends(require_recent_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Approve a pending worker."""
    # Get worker
    stmt = select(Worker).where(Worker.id == worker_id)
    result = await db.execute(stmt)
    worker = result.scalar_one_or_none()

    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker with ID {worker_id} not found",
        )

    if worker.status != WorkerStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Worker is not in PENDING status (current: {worker.status.value})",
        )

    # Approve worker
    stmt = (
        update(Worker)
        .where(Worker.id == worker_id)
        .values(status=WorkerStatus.ACTIVE)
    )
    await db.execute(stmt)
    await db.commit()
    await db.refresh(worker)

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="worker_approve",
        target="worker",
        details={
            "worker_id": worker.id,
            "worker_name": worker.name,
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return WorkerResponse.model_validate(worker)


@router.post("/workers/{worker_id}/suspend", response_model=WorkerResponse)
async def suspend_worker(
    worker_id: int,
    request: Request,
    current_user: Annotated[User, Depends(require_recent_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Suspend an active worker."""
    # Get worker
    stmt = select(Worker).where(Worker.id == worker_id)
    result = await db.execute(stmt)
    worker = result.scalar_one_or_none()

    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker with ID {worker_id} not found",
        )

    # Suspend worker
    stmt = (
        update(Worker)
        .where(Worker.id == worker_id)
        .values(status=WorkerStatus.SUSPENDED)
    )
    await db.execute(stmt)
    await db.commit()
    await db.refresh(worker)

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="worker_suspend",
        target="worker",
        details={
            "worker_id": worker.id,
            "worker_name": worker.name,
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return WorkerResponse.model_validate(worker)


@router.delete("/workers/{worker_id}", response_model=MessageResponse)
async def delete_worker(
    worker_id: int,
    request: Request,
    current_user: Annotated[User, Depends(require_recent_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a worker."""
    # Get worker
    stmt = select(Worker).where(Worker.id == worker_id)
    result = await db.execute(stmt)
    worker = result.scalar_one_or_none()

    if not worker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker with ID {worker_id} not found",
        )

    worker_name = worker.name

    # Delete worker
    stmt = delete(Worker).where(Worker.id == worker_id)
    await db.execute(stmt)
    await db.commit()

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="worker_delete",
        target="worker",
        details={
            "worker_id": worker_id,
            "worker_name": worker_name,
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return MessageResponse(
        message="Worker deleted successfully",
        detail=f"Worker '{worker_name}' has been deleted",
    )


# =============================================================================
# Configuration Management
# =============================================================================


@router.get("/config", response_model=List[ConfigResponse])
async def list_all_configs(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all configuration entries."""
    stmt = select(Config)
    result = await db.execute(stmt)
    configs = result.scalars().all()
    return [ConfigResponse.model_validate(c) for c in configs]


@router.get("/config/{key}", response_model=ConfigResponse)
async def get_config(
    key: str,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a specific configuration entry."""
    stmt = select(Config).where(Config.key == key)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuration key '{key}' not found",
        )

    return ConfigResponse.model_validate(config)


@router.put("/config/{key}", response_model=ConfigResponse)
async def update_config(
    key: str,
    config_data: ConfigUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_recent_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update a configuration entry."""
    # Get config
    stmt = select(Config).where(Config.key == key)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuration key '{key}' not found",
        )

    old_value = config.value

    # Update fields
    update_data = {"value": config_data.value}
    if config_data.type is not None:
        update_data["type"] = config_data.type
    if config_data.description is not None:
        update_data["description"] = config_data.description

    stmt = (
        update(Config)
        .where(Config.key == key)
        .values(**update_data)
    )
    await db.execute(stmt)
    await db.commit()
    await db.refresh(config)

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="config_update",
        target="config",
        details={
            "config_key": key,
            "old_value": old_value,
            "new_value": config.value,
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return ConfigResponse.model_validate(config)


@router.post("/config/bulk", response_model=MessageResponse)
async def bulk_update_config(
    bulk_data: ConfigBulkUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_recent_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Bulk update multiple configuration entries."""
    updated_count = 0
    errors = []

    for key, value in bulk_data.configs.items():
        # Check if key exists
        stmt = select(Config).where(Config.key == key)
        result = await db.execute(stmt)
        config = result.scalar_one_or_none()

        if config:
            # Update value
            stmt = (
                update(Config)
                .where(Config.key == key)
                .values(value=value)
            )
            await db.execute(stmt)
            updated_count += 1
        else:
            # UPSERT: key not found, insert new row with sensible defaults
            inferred_type = ConfigType.BOOLEAN if key.startswith('enable_') else ConfigType.STRING
            new_config = Config(
                key=key,
                value=value,
                type=inferred_type,
                description='Auto-created by bulk update',
            )
            db.add(new_config)
            updated_count += 1

    await db.commit()

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="config_bulk_update",
        target="config",
        details={
            "updated_count": updated_count,
            "updated_keys": list(bulk_data.configs.keys()),
            "errors": errors,
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    message = f"Updated {updated_count} configuration entries"
    if errors:
        message += f". Errors: {', '.join(errors)}"

    return MessageResponse(
        message=message,
        detail=f"{updated_count}/{len(bulk_data.configs)} entries updated",
    )


@router.post("/config/{key}", response_model=ConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update_config(
    key: str,
    config_data: ConfigUpdate,
    request: Request,
    current_user: Annotated[User, Depends(require_recent_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create or update a configuration entry."""
    # Check if config exists
    stmt = select(Config).where(Config.key == key)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    if config:
        # Update existing config
        old_value = config.value
        update_data = {"value": config_data.value}
        if config_data.type is not None:
            update_data["type"] = config_data.type
        if config_data.description is not None:
            update_data["description"] = config_data.description

        stmt = (
            update(Config)
            .where(Config.key == key)
            .values(**update_data)
        )
        await db.execute(stmt)
        await db.commit()
        await db.refresh(config)

        action = "config_update"
        details = {
            "config_key": key,
            "old_value": old_value,
            "new_value": config.value,
        }
    else:
        # Create new config
        config = Config(
            key=key,
            value=config_data.value,
            type=config_data.type or "STRING",
            description=config_data.description,
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)

        action = "config_create"
        details = {
            "config_key": key,
            "value": config.value,
        }

    # Audit log
    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action=action,
        target="config",
        details=details,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return ConfigResponse.model_validate(config)


# ---------------------------------------------------------------------------
# Background integrations: PIM deliveries and image host checks
# ---------------------------------------------------------------------------

@router.get("/integrations/queue", response_model=IntegrationQueueResponse)
async def get_integration_queue(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """How many PIM notifications and image host checks are still scheduled to run."""
    from api.services import pim_service, remote_sync_service

    return IntegrationQueueResponse(
        **await pim_service.queue_counts(db),
        **await remote_sync_service.queue_counts(db),
    )


@router.post("/integrations/pim/stop-all", response_model=IntegrationStopResponse)
async def stop_all_pim_deliveries(
    request: Request,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Stop every PIM notification waiting to be sent or retrying."""
    from api.services.pim_service import stop_pending_events

    stopped = await stop_pending_events(db, current_user.username)
    return await _report_stopped(stopped, "pim_stop_all", "pim_events", current_user, request)


@router.post("/integrations/remote-sync/stop-all", response_model=IntegrationStopResponse)
async def stop_all_remote_sync_checks(
    request: Request,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Stop every image host check waiting for PIM or checking."""
    from api.services.remote_sync_service import stop_active_checks

    stopped = await stop_active_checks(db, current_user.username)
    return await _report_stopped(stopped, "remote_sync_stop_all", "remote_sync_checks", current_user, request)


async def _report_stopped(stopped: list, action: str, target: str, current_user: User, request: Request):
    from api.services.pim_service import notify_integration_update

    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action=action,
        target=target,
        details={"stopped": len(stopped), "operation_ids": stopped},
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    if stopped:
        # One refresh for every open WebUI, not one per operation
        await notify_integration_update(None)
    return IntegrationStopResponse(stopped=len(stopped), operation_ids=stopped)
