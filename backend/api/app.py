"""
FastAPI application for Modular File Manager.

Complete REST API with authentication, file operations, worker management,
and admin functionality.
"""

from contextlib import asynccontextmanager
from typing import Annotated, List

from fastapi import FastAPI, Depends, HTTPException, status, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings, Settings
from api.middleware.auth import get_current_user, require_admin, require_operator
from api.middleware.logging import (
    RequestLoggingMiddleware,
    setup_logging,
    AuditLogger,
)
from api.schemas import *
from api.services.worker_service import WorkerService, get_worker_by_id, get_active_workers
from api.services.operation_service import OperationService
from database import init_database, close_database, get_db, health_check
from models import User, Worker, Operation, Config, AuditLog, WorkerStatus, OperationType

# Import auth routes
from api.routes.auth import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    settings = get_settings()

    # Setup logging
    setup_logging(settings.log_level, settings.enable_json_logs)

    # Initialize database
    await init_database(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        echo=settings.db_echo,
    )

    yield

    # Shutdown
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


# =============================================================================
# Health Check
# =============================================================================

@app.get("/health", response_model=HealthCheckResponse)
async def health_check_endpoint():
    """Health check endpoint."""
    db_healthy = await health_check()

    return HealthCheckResponse(
        status="healthy" if db_healthy else "degraded",
        version="1.0.0",
        database=db_healthy,
        redis=True,  # TODO: Add Redis health check
    )


# =============================================================================
# File Operations
# =============================================================================

@app.get("/api/files/list", response_model=DirectoryListResponse)
async def list_directory(
    worker_id: int,
    path: str,
    offset: int = 0,
    limit: int = 1000,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """List directory contents on worker."""
    worker = await get_worker_by_id(worker_id, db)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    worker_service = WorkerService(settings)

    try:
        response = await worker_service.list_directory(
            worker, path, db, offset, limit
        )

        # Parse response into FileInfo objects
        items = []
        if response.error_details and "items" in response.error_details:
            items = [FileInfo(**item) for item in response.error_details["items"]]

        total_count = response.file_count or len(items)

        return DirectoryListResponse(
            path=path,
            items=items,
            total_count=total_count,
            offset=offset,
            limit=limit,
            has_more=(offset + len(items)) < total_count,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/files/search", response_model=FileSearchResponse)
async def search_files(
    worker_id: int,
    path: str,
    query: str,
    recursive: bool = True,
    offset: int = 0,
    limit: int = 100,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Search for files on worker."""
    worker = await get_worker_by_id(worker_id, db)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    worker_service = WorkerService(settings)

    try:
        response = await worker_service.search_files(
            worker, path, query, db, recursive
        )

        results = []
        if response.error_details and "results" in response.error_details:
            results = [FileInfo(**item) for item in response.error_details["results"]]

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
    current_user: Annotated[User, Depends(require_operator)],
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
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    # Execute operation asynchronously
    # In production, this would be handled by a background task queue
    try:
        operation = await operation_service.execute_operation(operation, db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return OperationResponse.model_validate(operation)


@app.post("/api/files/move", response_model=OperationResponse)
async def move_file(
    request_data: FileMoveRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_operator)],
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
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    try:
        operation = await operation_service.execute_operation(operation, db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return OperationResponse.model_validate(operation)


@app.post("/api/files/delete", response_model=OperationResponse)
async def delete_file(
    request_data: FileDeleteRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_operator)],
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
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    try:
        operation = await operation_service.execute_operation(operation, db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return OperationResponse.model_validate(operation)


@app.post("/api/files/mkdir", response_model=OperationResponse)
async def create_directory(
    request_data: FileMkdirRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_operator)],
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
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    try:
        operation = await operation_service.execute_operation(operation, db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return OperationResponse.model_validate(operation)


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
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Register new worker (requires admin approval)."""
    # Create worker with pending status
    worker = Worker(
        name=worker_data.name,
        hostname=worker_data.hostname,
        public_key=worker_data.public_key,
        path_a_prefix=worker_data.path_a_prefix,
        path_b_prefix=worker_data.path_b_prefix,
        version=worker_data.version,
        status=WorkerStatus.PENDING,
    )

    db.add(worker)
    await db.commit()
    await db.refresh(worker)

    await AuditLogger.log_admin_action(
        user_id=current_user.id,
        action="worker_register",
        target="worker",
        details={"worker_id": worker.id, "worker_name": worker.name},
        ip_address=request.client.host if request.client else None,
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
    offset: int = 0,
    limit: int = 100,
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
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


# =============================================================================
# WebSocket
# =============================================================================

@app.websocket("/ws/operations")
async def websocket_operations(websocket: WebSocket):
    """WebSocket endpoint for real-time operation updates."""
    await websocket.accept()

    try:
        while True:
            # In production, this would stream real operation updates
            # For now, send periodic pings
            await websocket.send_json({"type": "ping", "data": {}})
            await asyncio.sleep(30)
    except Exception:
        pass
    finally:
        await websocket.close()


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
