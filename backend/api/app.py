"""
FastAPI application for Modular File Manager.

Complete REST API with authentication, file operations, worker management,
and admin functionality.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Dict, List, Optional, Any

from fastapi import FastAPI, Depends, HTTPException, status, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import select, desc, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings, Settings
from api.middleware.auth import get_current_user, require_admin, require_user
from api.middleware.logging import (
    RequestLoggingMiddleware,
    setup_logging,
    AuditLogger,
    get_client_ip,
)
from api.schemas import *
from api.services.worker_service import WorkerService, get_worker_by_id, get_active_workers
from api.services.operation_service import OperationService
from database import init_database, close_database, get_db, health_check
from models import User, Worker, Operation, Config, AuditLog, WorkerStatus, OperationType

# Import routes
from api.routes.auth import router as auth_router
from api.routes.admin import router as admin_router
from api.routes.admin_system import router as admin_system_router
from api.routes.preferences import router as preferences_router
from api.routes.worker import router as worker_router
from api.routes.path import router as path_router


async def _sync_env_config_to_db(settings: Settings) -> None:
    """
    Sync environment-driven config into the DB config table on every startup.

    This ensures .env changes take effect after restart without touching
    the admin panel.  DB becomes the single source of truth at runtime.
    """
    from database import DatabaseManager
    from sqlalchemy import text

    env_configs = {
        "polka_auth_enabled": str(settings.polka_auth_enabled).lower(),
        "polka_auth_url": settings.polka_auth_url or "",
        "polka_auth_api_key": settings.polka_auth_api_key or "",
        "polka_auth_timeout": str(settings.polka_auth_timeout),
        # ROSAPI
        "rosapi_enabled": str(settings.rosapi_enabled).lower(),
        "rosapi_base_url": settings.rosapi_base_url or "",
        "rosapi_auth_email": settings.rosapi_auth_email or "",
        "rosapi_auth_password": settings.rosapi_auth_password or "",
        "rosapi_timeout": str(settings.rosapi_timeout),
        "rosapi_push_enabled": str(settings.rosapi_push_enabled).lower(),
        "rosapi_push_endpoint": settings.rosapi_push_endpoint or "",
        "rosapi_push_method": settings.rosapi_push_method or "POST",
        "rosapi_push_payload": settings.rosapi_push_payload or "{}",
        "rosapi_pull_enabled": str(settings.rosapi_pull_enabled).lower(),
        "rosapi_pull_endpoint": settings.rosapi_pull_endpoint or "",
        "rosapi_pull_method": settings.rosapi_pull_method or "POST",
        "rosapi_pull_payload": settings.rosapi_pull_payload or "{}",
        "rosapi_verify_url": settings.rosapi_verify_url or "",
    }

    try:
        async with DatabaseManager.session() as session:
            for key, value in env_configs.items():
                await session.execute(
                    text("UPDATE config SET value = :value WHERE key = :key"),
                    {"key": key, "value": value},
                )
        logger.info(
            "Synced env config to DB: polka_auth_enabled={}, rosapi_enabled={}",
            env_configs["polka_auth_enabled"],
            env_configs["rosapi_enabled"],
        )
    except Exception as exc:
        logger.warning(f"Failed to sync env config to DB: {exc}")


async def _reconfigure_logging_from_db() -> None:
    """
    Reconfigure the structured logging module from DB config.

    At startup, setup_structured_logging() runs before the DB is available,
    so it only reads env vars.  If syslog was enabled via the admin UI
    (stored in DB), this function picks up those settings and adds the
    SyslogHandler to the global MultiHandler.
    """
    from database import DatabaseManager
    from sqlalchemy import select
    import logging_module.logger as lm_logger
    from logging_module.handlers import SyslogHandler, MultiHandler

    # Create MultiHandler if it doesn't exist (e.g. setup_structured_logging
    # was skipped or failed).  Without this, syslog can never be added.
    if lm_logger._global_handler is None:
        lm_logger._global_handler = MultiHandler()
        logger.info("Created MultiHandler for logging reconfiguration (was None)")

    handler = lm_logger._global_handler

    async with DatabaseManager.session() as session:
        config_keys = ['enable_syslog', 'syslog_host', 'syslog_port', 'syslog_protocol']
        config_values = {}
        for key in config_keys:
            stmt = select(Config).where(Config.key == key)
            result = await session.execute(stmt)
            cfg = result.scalar_one_or_none()
            if cfg:
                config_values[key] = cfg.value

    is_enabled = config_values.get('enable_syslog', 'false').lower() == 'true'
    host = config_values.get('syslog_host')
    port = int(config_values.get('syslog_port', '514'))
    protocol = config_values.get('syslog_protocol', 'UDP')

    # Check if syslog handler already exists (from env vars)
    has_syslog = any(isinstance(h, SyslogHandler) for h in handler.handlers)

    if is_enabled and host and not has_syslog:
        syslog_handler = SyslogHandler(host=host, port=port, protocol=protocol)
        handler.add_handler(syslog_handler)
        logger.info(f"Syslog handler configured from DB: {host}:{port}/{protocol}")
    elif not is_enabled and has_syslog:
        # DB says disabled but env started it — remove
        handler.handlers = [
            h for h in handler.handlers
            if not isinstance(h, SyslogHandler)
        ]
        logger.info("Syslog handler removed (disabled in DB config)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    settings = get_settings()

    # Setup logging
    setup_logging(settings.log_level, settings.enable_json_logs)

    # Initialize structured logging module (for syslog, file rotation, etc.)
    try:
        from logging_module import setup_logging as setup_structured_logging
        await setup_structured_logging()
        logger.info("Structured logging module initialized")
    except Exception as exc:
        logger.warning(f"Failed to initialize structured logging module: {exc}")

    # Initialize database
    await init_database(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        echo=settings.db_echo,
    )

    # Sync env-driven config into DB so .env changes take effect on restart
    await _sync_env_config_to_db(settings)

    # Reconfigure structured logging from DB config (syslog may have been
    # enabled via admin UI and stored in DB, but setup_structured_logging()
    # above only reads env vars since DB wasn't initialized yet)
    try:
        await _reconfigure_logging_from_db()
    except Exception as exc:
        logger.warning(f"Failed to reconfigure logging from DB: {exc}")

    # Initialize Elasticsearch
    from api.services.elasticsearch_service import get_elasticsearch_service
    es_service = await get_elasticsearch_service()

    # Start WebSocket manager
    from api.websocket_manager import ws_manager
    await ws_manager.start()

    # Start background tasks (command cleanup, worker health checks)
    from api.background_tasks import start_background_tasks
    await start_background_tasks(settings)

    yield

    # Shutdown
    # Stop background tasks
    from api.background_tasks import stop_background_tasks
    await stop_background_tasks()

    # Stop WebSocket manager
    from api.websocket_manager import ws_manager
    await ws_manager.stop()

    # Close Elasticsearch
    from api.services.elasticsearch_service import close_elasticsearch_service
    await close_elasticsearch_service()

    # Close structured logging module
    try:
        from logging_module import close_logging
        close_logging()
        logger.info("Structured logging module closed")
    except Exception:
        pass

    await close_database()


# Create FastAPI app
app = FastAPI(
    title="Modular File Manager API",
    description="Enterprise file operations management API",
    version="1.0.0",
    lifespan=lifespan,
)

# Add middleware
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)

# Include routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(admin_system_router)
app.include_router(preferences_router)
app.include_router(worker_router)
app.include_router(path_router)


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health", response_model=HealthCheckResponse)
async def health_check_endpoint():
    """Health check endpoint."""
    db_healthy = await health_check()

    try:
        import redis.asyncio as aioredis
        settings = get_settings()
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
        redis_healthy = bool(await r.ping())
        await r.aclose()
    except Exception:
        redis_healthy = False

    all_healthy = db_healthy and redis_healthy
    return HealthCheckResponse(
        status="healthy" if all_healthy else "degraded",
        version="1.0.0",
        database=db_healthy,
        redis=redis_healthy,
    )


# =============================================================================
# File Operations
# =============================================================================

def validate_path_a(path: str) -> None:
    """
    Validate that path is a valid Path A path.

    Path A paths must:
    - Start with 'A:' or 'a:'
    - Not contain other drive letters (B:, C:, etc.)
    - Be treated as relative paths from Path A root

    Raises HTTPException if validation fails.
    """
    if not path:
        raise HTTPException(status_code=400, detail="Path cannot be empty")

    # Normalize path to uppercase for comparison
    path_upper = path.upper()

    # Path must start with A:
    if not path_upper.startswith('A:'):
        raise HTTPException(
            status_code=400,
            detail="Path A operations must use paths starting with 'A:'. Other drive letters (B:, C:) are not allowed."
        )

    # Check for other drive letters in the path (B:, C:, D:, etc.)
    # This prevents paths like "A:/some/B:/path"
    path_after_a = path[2:]  # Remove "A:" prefix
    for letter in 'BCDEFGHIJKLMNOPQRSTUVWXYZ':
        if f'{letter}:' in path_after_a.upper():
            raise HTTPException(
                status_code=400,
                detail=f"Invalid path: Drive letter '{letter}:' not allowed in Path A. Use relative paths only."
            )


@app.get("/api/files/list", response_model=DirectoryListResponse)
async def list_directory(
    worker_id: int,
    path: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    offset: int = 0,
    limit: int = 1000,
):
    """List directory contents on worker."""
    # Validate Path A
    validate_path_a(path)

    worker = await get_worker_by_id(worker_id, db)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    worker_service = WorkerService(settings)

    try:
        response = await worker_service.list_directory(
            worker, path, db, offset, limit
        )

        # Parse response into FileInfo objects
        # The response structure has error_details nested inside error_details
        # because worker.py wraps the worker's error_details in a response_dict
        items = []
        data = None

        if response.error_details:
            # Check if error_details is nested (new structure after recent changes)
            if "error_details" in response.error_details:
                data = response.error_details["error_details"]
            # Or if items is directly in error_details (old structure)
            elif "items" in response.error_details:
                data = response.error_details

        if data and "items" in data:
            # Transform worker response format to FileInfo format
            for item in data["items"]:
                # Convert 'size' to 'size_bytes' for backward compatibility
                if "size" in item and "size_bytes" not in item:
                    item["size_bytes"] = item.pop("size")
                # Convert 'modified' to 'modified_at' for backward compatibility
                if "modified" in item and "modified_at" not in item:
                    item["modified_at"] = item.pop("modified")
                items.append(FileInfo(**item))
        else:
            logger.warning(f"No items in response. error_details={response.error_details}")

        total_count = data.get("total") if data else len(items)

        # Index files in Elasticsearch in background (non-blocking)
        try:
            from api.services.elasticsearch_service import get_elasticsearch_service
            import os

            es_service = await get_elasticsearch_service()
            if es_service.is_enabled and items:
                # Prepare file documents for indexing
                file_docs = []
                for item in items:
                    file_docs.append({
                        "path": item.path,
                        "name": item.name,
                        "parent_path": path,
                        "is_directory": item.is_directory,
                        "size": item.size_bytes,
                        "modified_at": item.modified_at.isoformat() if item.modified_at else None,
                        "worker_id": worker_id,
                    })

                # Index in background (don't await)
                asyncio.create_task(es_service.bulk_index_files(file_docs))
        except Exception as e:
            # Log error but don't fail the request
            logger.warning(f"Failed to index files in Elasticsearch: {e}")

        return DirectoryListResponse(
            path=path,
            items=items,
            total_count=total_count,
            offset=offset,
            limit=limit,
            has_more=(offset + len(items)) < total_count,
        )
    except Exception as exc:
        logger.error(f"List directory failed: {exc}", exc_info=True)
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/files/search", response_model=FileSearchResponse)
async def search_files(
    worker_id: int,
    path: str,
    query: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    recursive: bool = True,
    offset: int = 0,
    limit: int = 100,
):
    """Search for files on worker using Elasticsearch or worker service."""
    # Validate Path A
    validate_path_a(path)

    worker = await get_worker_by_id(worker_id, db)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    try:
        # Try Elasticsearch first
        from api.services.elasticsearch_service import get_elasticsearch_service

        es_service = await get_elasticsearch_service()
        if es_service.is_enabled:
            # Use Elasticsearch for search
            result = await es_service.search_files(
                query=query,
                worker_id=worker_id,
                parent_path=path,
                is_directory=None,
                offset=offset,
                limit=limit,
            )

            # Convert ES results to FileInfo objects
            results = []
            for hit in result["hits"]:
                from datetime import datetime
                results.append(FileInfo(
                    name=hit.get("name", ""),
                    path=hit.get("path", ""),
                    is_directory=hit.get("is_directory", False),
                    size=hit.get("size", 0),
                    modified_at=datetime.fromisoformat(hit["modified_at"]) if hit.get("modified_at") else None,
                ))

            return FileSearchResponse(
                query=query,
                results=results,
                total_count=result["total"],
                offset=offset,
                limit=limit,
            )
        else:
            # Fall back to worker service search
            worker_service = WorkerService(settings)
            response = await worker_service.search_files(
                worker, path, query, db, recursive
            )

            results = []
            # Check if response has results
            # The response structure has error_details nested inside error_details
            # because worker.py wraps the worker's error_details in a response_dict
            data = None

            if response.error_details:
                # Check if error_details is nested (new structure after recent changes)
                if "error_details" in response.error_details:
                    data = response.error_details["error_details"]
                # Or if data is directly in error_details (old structure)
                else:
                    data = response.error_details

            if data:
                # Handle both 'files', 'results', and 'items' keys
                files_data = data.get("files") or data.get("results") or data.get("items") or []
                # Transform worker response format to FileInfo format
                for item in files_data:
                    # Convert 'size' to 'size_bytes' for backward compatibility
                    if "size" in item and "size_bytes" not in item:
                        item["size_bytes"] = item.pop("size")
                    # Convert 'modified' to 'modified_at' for backward compatibility
                    if "modified" in item and "modified_at" not in item:
                        item["modified_at"] = item.pop("modified")
                    # Add is_directory field if missing (defaults to False for files)
                    if "is_directory" not in item:
                        item["is_directory"] = False
                    results.append(FileInfo(**item))
            else:
                logger.warning(f"Search returned no data for query: {query} in path: {path}")

            return FileSearchResponse(
                query=query,
                results=results,
                total_count=len(results),
                offset=offset,
                limit=limit,
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/files/copy", response_model=OperationResponse)
async def copy_file(
    request_data: FileCopyRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Copy file operation."""
    worker_service = WorkerService(settings)
    operation_service = OperationService(settings, worker_service)

    # Create operation
    operation = await operation_service.create_operation(
        user=current_user,
        operation_type=OperationType.COPY,
        source_path=request_data.source_path,
        dest_path=request_data.dest_path,
        worker_ids=request_data.worker_ids,
        db=db,
        params={"overwrite": request_data.overwrite},
    )

    # Log operation
    await AuditLogger.log_operation(
        user_id=current_user.id,
        operation_id=operation.id,
        action="file_copy",
        details={
            "source": request_data.source_path,
            "dest": request_data.dest_path,
            "workers": request_data.worker_ids,
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    # Execute operation asynchronously
    # In production, this would be handled by a background task queue
    try:
        operation = await operation_service.execute_operation(operation, db)
        # Refresh operation to ensure all attributes are loaded after commit
        await db.refresh(operation)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Use model_copy to update immutable Pydantic model
    op_response = OperationResponse.model_validate(operation)
    return op_response.model_copy(update={"user_name": current_user.username})


@app.post("/api/files/move", response_model=OperationResponse)
async def move_file(
    request_data: FileMoveRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Move file operation."""
    worker_service = WorkerService(settings)
    operation_service = OperationService(settings, worker_service)

    operation = await operation_service.create_operation(
        user=current_user,
        operation_type=OperationType.MOVE,
        source_path=request_data.source_path,
        dest_path=request_data.dest_path,
        worker_ids=request_data.worker_ids,
        db=db,
        params={"overwrite": request_data.overwrite},
    )

    await AuditLogger.log_operation(
        user_id=current_user.id,
        operation_id=operation.id,
        action="file_move",
        details={
            "source": request_data.source_path,
            "dest": request_data.dest_path,
            "workers": request_data.worker_ids,
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    try:
        operation = await operation_service.execute_operation(operation, db)
        # Refresh operation to ensure all attributes are loaded after commit
        await db.refresh(operation)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Use model_copy to update immutable Pydantic model
    op_response = OperationResponse.model_validate(operation)
    return op_response.model_copy(update={"user_name": current_user.username})


@app.post("/api/files/delete", response_model=OperationResponse)
async def delete_file(
    request_data: FileDeleteRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Delete file operation."""
    worker_service = WorkerService(settings)
    operation_service = OperationService(settings, worker_service)

    operation = await operation_service.create_operation(
        user=current_user,
        operation_type=OperationType.DELETE,
        source_path=request_data.path,
        dest_path=None,
        worker_ids=[request_data.worker_id],
        db=db,
        params={"recursive": request_data.recursive},
    )

    await AuditLogger.log_operation(
        user_id=current_user.id,
        operation_id=operation.id,
        action="file_delete",
        details={
            "path": request_data.path,
            "recursive": request_data.recursive,
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    try:
        operation = await operation_service.execute_operation(operation, db)
        # Refresh operation to ensure all attributes are loaded after commit
        await db.refresh(operation)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Use model_copy to update immutable Pydantic model
    op_response = OperationResponse.model_validate(operation)
    return op_response.model_copy(update={"user_name": current_user.username})


@app.post("/api/files/mkdir", response_model=OperationResponse)
async def create_directory(
    request_data: FileMkdirRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Create directory operation."""
    worker_service = WorkerService(settings)
    operation_service = OperationService(settings, worker_service)

    operation = await operation_service.create_operation(
        user=current_user,
        operation_type=OperationType.MKDIR,
        source_path=request_data.path,
        dest_path=None,
        worker_ids=[request_data.worker_id],
        db=db,
        params={"parents": request_data.parents},
    )

    await AuditLogger.log_operation(
        user_id=current_user.id,
        operation_id=operation.id,
        action="directory_create",
        details={
            "path": request_data.path,
            "parents": request_data.parents,
        },
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    try:
        operation = await operation_service.execute_operation(operation, db)
        # Refresh operation to ensure all attributes are loaded after commit
        await db.refresh(operation)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Use model_copy to update immutable Pydantic model
    op_response = OperationResponse.model_validate(operation)
    return op_response.model_copy(update={"user_name": current_user.username})


@app.post("/api/operations/push", response_model=OperationResponse)
async def push_operation(
    request_data: FilePushRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    PUSH operation: Copy directory to PATH_B and archive to PATH_C.

    VF Redesign: This replaces the dual-pane copy operation.
    """
    # Validate Path A
    validate_path_a(request_data.source_path)

    worker_service = WorkerService(settings)
    operation_service = OperationService(settings, worker_service)

    # Acquire path lock BEFORE creating the operation to prevent race conditions
    # where two users try to push the same directory concurrently
    async with operation_service._get_path_lock(request_data.source_path):
        try:
            # Create and execute PUSH operation
            operation = await operation_service.create_push_operation(
                user=current_user,
                source_dir=request_data.source_path,
                worker_id=request_data.worker_id,
                db=db,
            )

            # Log operation
            await AuditLogger.log_operation(
                user_id=current_user.id,
                operation_id=operation.id,
                action="push",
                details={
                    "source_directory": request_data.source_path,
                    "target_directory": operation.dest_path,
                    "archive_directory": operation.archive_path,
                },
                ip_address=get_client_ip(request),
                user_agent=request.headers.get("user-agent"),
                username=current_user.username,
            )

            # Execute operation
            operation = await operation_service.execute_operation(operation, db)

            # Refresh operation to ensure all attributes are loaded after commit
            await db.refresh(operation)

            # Broadcast to WebSocket clients (don't fail request if broadcast fails)
            try:
                from api.websocket_manager import ws_manager
                await ws_manager.broadcast(
                    {
                        "type": "operation_update",
                        "operation_id": operation.id,
                        "status": operation.status.value,
                        "user": current_user.username,
                    },
                    topic="operations"
                )
            except Exception as ws_exc:
                logger.warning(f"Failed to broadcast operation update: {ws_exc}")

            # Use model_copy to update immutable Pydantic model
            op_response = OperationResponse.model_validate(operation)
            return op_response.model_copy(update={"user_name": current_user.username})

        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/operations/pull", response_model=OperationResponse)
async def pull_operation(
    request_data: FilePullRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    PULL operation: Revert PUSH operation by copying from PATH_B to original location.

    VF Redesign: Any authenticated user can revert any operation.
    """
    worker_service = WorkerService(settings)
    operation_service = OperationService(settings, worker_service)

    # Fetch original operation to get the lock path
    from sqlalchemy import select
    from models import Operation as OperationModel
    stmt = select(OperationModel).where(OperationModel.id == request_data.operation_id)
    result = await db.execute(stmt)
    original_op = result.scalar_one_or_none()

    if not original_op or not original_op.original_path:
        raise HTTPException(status_code=400, detail="Original operation not found or has no original path")

    # Acquire path lock on the destination (original_path) to prevent race conditions
    async with operation_service._get_path_lock(original_op.original_path):
        try:
            # Create and execute PULL operation
            operation = await operation_service.create_pull_operation(
                user=current_user,
                original_operation_id=request_data.operation_id,
                worker_id=request_data.worker_id,
                db=db,
            )

            # Log operation
            await AuditLogger.log_operation(
                user_id=current_user.id,
                operation_id=operation.id,
                action="pull",
                details={
                    "original_operation_id": request_data.operation_id,
                    "source_directory": operation.source_path,
                    "target_directory": operation.dest_path,
                    "archive_directory": original_op.archive_path,
                },
                ip_address=get_client_ip(request),
                user_agent=request.headers.get("user-agent"),
                username=current_user.username,
            )

            # Execute operation
            operation = await operation_service.execute_operation(operation, db)

            # Refresh operation to ensure all attributes are loaded after commit
            await db.refresh(operation)

            # Broadcast to WebSocket clients (don't fail request if broadcast fails)
            try:
                from api.websocket_manager import ws_manager
                await ws_manager.broadcast(
                    {
                        "type": "operation_update",
                        "operation_id": operation.id,
                        "status": operation.status.value,
                        "user": current_user.username,
                    },
                    topic="operations"
                )
            except Exception as ws_exc:
                logger.warning(f"Failed to broadcast operation update: {ws_exc}")

            # Use model_copy to update immutable Pydantic model
            op_response = OperationResponse.model_validate(operation)
            return op_response.model_copy(update={"user_name": current_user.username})

        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/operations/history", response_model=List[OperationResponse])
async def get_operations_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 100,
    offset: int = 0,
    operation_type: Optional[str] = None,
    status: Optional[str] = None,
):
    """
    Get operation history for all users (VF redesign).

    Returns paginated list of all operations with filters.
    """
    try:
        # Build query with User join to get username
        query = select(Operation, User).join(User, Operation.user_id == User.id).order_by(desc(Operation.created_at))

        # Apply filters
        if operation_type:
            query = query.where(Operation.type == operation_type.upper())
        if status:
            query = query.where(Operation.status == status.upper())

        # Pagination
        query = query.limit(limit).offset(offset)

        result = await db.execute(query)
        rows = result.all()

        # Build response with username and check if PUSH operations have been pulled
        responses = []
        for operation, user in rows:
            op_response = OperationResponse.model_validate(operation)

            # Check if this PUSH operation has been pulled
            has_been_pulled = False
            if operation.type == OperationType.PUSH and operation.status == OperationStatus.COMPLETED:
                # Query for a completed PULL operation that references this PUSH
                pull_check_query = select(Operation).where(
                    Operation.rollback_operation_id == operation.id,
                    Operation.type == OperationType.PULL,
                    Operation.status == OperationStatus.COMPLETED
                )
                pull_result = await db.execute(pull_check_query)
                has_been_pulled = pull_result.scalar_one_or_none() is not None

            # Use model_copy to update immutable Pydantic model
            op_response = op_response.model_copy(update={
                "user_name": user.username,
                "has_been_pulled": has_been_pulled
            })
            responses.append(op_response)

        return responses

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/operations/search", response_model=Dict[str, Any])
async def search_operations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    operation_type: Optional[str] = None,
    status: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
):
    """
    Search operations using Elasticsearch.

    Provides full-text search across operation paths, usernames, and error messages.
    Falls back to database query if Elasticsearch is disabled.
    """
    try:
        from api.services.elasticsearch_service import get_elasticsearch_service

        es_service = await get_elasticsearch_service()

        if es_service.is_enabled and q:
            # Use Elasticsearch for search
            filters = {}
            if operation_type:
                filters["operation_type"] = operation_type.upper()
            if status:
                filters["status"] = status.upper()

            result = await es_service.search_operations(
                query=q,
                filters=filters,
                offset=offset,
                limit=limit,
                sort_by=sort_by,
                sort_order=sort_order,
            )

            # Convert hits to OperationResponse format
            operations = []
            for hit in result["hits"]:
                operations.append({
                    "id": hit["operation_id"],
                    "user_id": hit["user_id"],
                    "user_name": hit.get("user_name"),
                    "type": hit["operation_type"],
                    "source_path": hit["source_path"],
                    "dest_path": hit.get("dest_path"),
                    "status": hit["status"],
                    "started_at": hit.get("started_at"),
                    "completed_at": hit.get("completed_at"),
                    "error_msg": hit.get("error_msg"),
                    "file_count": hit.get("file_count"),
                    "total_size_bytes": hit.get("total_size_bytes"),
                    "params_json": None,
                    "created_at": hit["created_at"],
                    "_score": hit.get("_score"),
                })

            return {
                "total": result["total"],
                "operations": operations,
                "offset": result["offset"],
                "limit": result["limit"],
            }
        else:
            # Fall back to database query (no full-text search)
            query = select(Operation, User).join(User, Operation.user_id == User.id).order_by(desc(Operation.created_at))

            # Apply filters
            if operation_type:
                query = query.where(Operation.type == operation_type.upper())
            if status:
                query = query.where(Operation.status == status.upper())
            if q:
                # Basic path search using SQL LIKE
                search_pattern = f"%{q}%"
                query = query.where(
                    or_(
                        Operation.source_path.ilike(search_pattern),
                        Operation.dest_path.ilike(search_pattern),
                        User.username.ilike(search_pattern),
                    )
                )

            # Pagination
            query = query.limit(limit).offset(offset)

            result = await db.execute(query)
            rows = result.all()

            # Build response
            operations = []
            for operation, user in rows:
                op_response = OperationResponse.model_validate(operation)
                # Use model_copy to update immutable Pydantic model
                op_response = op_response.model_copy(update={"user_name": user.username})
                operations.append(op_response.model_dump())

            # Get total count (approximate)
            count_query = select(func.count(Operation.id))
            if operation_type:
                count_query = count_query.where(Operation.type == operation_type.upper())
            if status:
                count_query = count_query.where(Operation.status == status.upper())

            count_result = await db.execute(count_query)
            total = count_result.scalar()

            return {
                "total": total,
                "operations": operations,
                "offset": offset,
                "limit": limit,
            }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# =============================================================================
# Workers
# =============================================================================

@app.get("/api/workers/list", response_model=List[WorkerResponse])
async def list_workers(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all active workers."""
    workers = await get_active_workers(db)
    return [WorkerResponse.model_validate(w) for w in workers]


@app.post("/api/workers/register", response_model=WorkerResponse)
async def register_worker(
    worker_data: WorkerRegister,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Register new worker (self-registration with PENDING status).

    Workers can register themselves using mTLS authentication.
    Status is set to PENDING and requires admin approval to become active.
    """
    # Check if worker with same hostname already exists
    stmt = select(Worker).where(Worker.hostname == worker_data.hostname)
    result = await db.execute(stmt)
    existing_worker = result.scalar_one_or_none()

    if existing_worker:
        # Update existing worker
        existing_worker.name = worker_data.name
        existing_worker.public_key = worker_data.public_key
        existing_worker.path_a_prefix = worker_data.path_a_prefix
        existing_worker.path_b_prefix = worker_data.path_b_prefix
        existing_worker.path_c_prefix = worker_data.path_c_prefix
        existing_worker.version = worker_data.version
        existing_worker.last_heartbeat = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(existing_worker)

        return WorkerResponse.model_validate(existing_worker)

    # Create new worker with pending status
    worker = Worker(
        name=worker_data.name,
        hostname=worker_data.hostname,
        public_key=worker_data.public_key,
        path_a_prefix=worker_data.path_a_prefix,
        path_b_prefix=worker_data.path_b_prefix,
        path_c_prefix=worker_data.path_c_prefix,
        version=worker_data.version,
        status=WorkerStatus.PENDING,
        last_heartbeat=datetime.now(timezone.utc),
    )

    db.add(worker)
    await db.commit()
    await db.refresh(worker)

    await AuditLogger.log_admin_action(
        user_id=None,
        action="worker_register",
        target="worker",
        details={"worker_id": worker.id, "worker_name": worker.name, "hostname": worker.hostname},
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return WorkerResponse.model_validate(worker)


# =============================================================================
# Admin
# =============================================================================

@app.get("/api/admin/users", response_model=List[UserResponse])
async def list_users(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all users."""
    stmt = select(User)
    result = await db.execute(stmt)
    users = result.scalars().all()
    return [UserResponse.model_validate(u) for u in users]


@app.get("/api/admin/config", response_model=List[ConfigResponse])
async def list_config(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all configuration entries."""
    stmt = select(Config)
    result = await db.execute(stmt)
    configs = result.scalars().all()
    return [ConfigResponse.model_validate(c) for c in configs]


@app.get("/api/admin/logs", response_model=List[AuditLogResponse])
async def list_audit_logs(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    offset: int = 0,
    limit: int = 100,
):
    """List audit logs."""
    stmt = (
        select(AuditLog)
        .order_by(desc(AuditLog.timestamp))
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return [AuditLogResponse.model_validate(log) for log in logs]


@app.get("/api/operations/list", response_model=List[OperationResponse])
async def list_operations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Optional[str] = None,
    offset: int = 0,
    limit: int = 100,
):
    """List operations with optional status filter."""
    from models import OperationStatus

    stmt = select(Operation, User).join(User, Operation.user_id == User.id).where(Operation.user_id == current_user.id)

    # Apply status filter if provided
    if status:
        try:
            status_enum = OperationStatus(status.upper())
            stmt = stmt.where(Operation.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status}. Valid values: pending, in_progress, completed, failed, rolled_back"
            )

    # Order by most recent first
    stmt = stmt.order_by(desc(Operation.created_at)).offset(offset).limit(limit)

    result = await db.execute(stmt)
    rows = result.all()

    # Build response with username
    responses = []
    for operation, user in rows:
        op_response = OperationResponse.model_validate(operation)
        # Use model_copy to update immutable Pydantic model
        op_response = op_response.model_copy(update={"user_name": user.username})
        responses.append(op_response)

    return responses


# =============================================================================
# WebSocket
# =============================================================================

@app.websocket("/ws/operations")
async def websocket_operations(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.

    Supports:
    - Operation progress updates
    - Worker status changes
    - System alerts
    - Log streaming

    Usage:
        ws://localhost:8000/ws/operations?token=<jwt_token>
    """
    from api.websocket_manager import ws_manager
    from api.middleware.auth import verify_token
    from api.config import get_settings
    from fastapi import WebSocketDisconnect
    from loguru import logger
    from datetime import datetime, timezone
    import uuid
    from urllib.parse import parse_qs

    connection_id = str(uuid.uuid4())
    user_id = None

    # Accept WebSocket connection first (must accept before we can close on auth failure)
    await websocket.accept()

    # Extract token from query string manually
    query_string = websocket.scope.get("query_string", b"").decode()
    query_params = parse_qs(query_string)
    token = query_params.get("token", [None])[0]

    # Authenticate token (required for this endpoint)
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return

    try:
        settings = get_settings()
        token_data = await verify_token(token, settings)
        user_id = token_data.user_id
    except Exception as e:
        logger.warning(f"WebSocket auth failed: {e}")
        await websocket.close(code=1008, reason="Invalid token")
        return

    # Register connection with WebSocket manager (connection already accepted above)
    await ws_manager.register_connection(
        websocket,
        connection_id,
        user_id=user_id,
        topics=["operations", "workers", "alerts", "logs", "file_changes"],
    )

    try:
        # Listen for messages from client
        while True:
            message = await websocket.receive_json()

            # Handle client messages
            if message.get("type") == "subscribe":
                topic = message.get("topic")
                if topic:
                    await ws_manager.subscribe(connection_id, topic)

            elif message.get("type") == "unsubscribe":
                topic = message.get("topic")
                if topic:
                    await ws_manager.unsubscribe(connection_id, topic)

            elif message.get("type") == "ping":
                await ws_manager.send_to_connection(
                    connection_id,
                    {"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()},
                )

    except WebSocketDisconnect:
        await ws_manager.disconnect(connection_id)
    except Exception as exc:
        logger.error(f"WebSocket error for {connection_id}: {exc}")
        await ws_manager.disconnect(connection_id)


# =============================================================================
# Error Handlers
# =============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )
