"""
Authentication routes for login, logout, and session management.

Includes optional integration with external Sybase authentication API.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings, Settings
from api.middleware.auth import get_current_user
from api.middleware.logging import AuditLogger
from api.schemas import LoginRequest, LoginResponse
from database import get_db
from models import Session as SessionModel, User


router = APIRouter(prefix="/api/auth", tags=["Authentication"])
# OAuth2 compatible router (without /api prefix)
oauth_router = APIRouter(prefix="/auth", tags=["OAuth2"])
ph = PasswordHasher()


async def verify_sybase_credentials(
    username: str,
    password: str,
    settings: Settings,
) -> bool:
    """
    Verify credentials against external Sybase API.

    Args:
        username: Username to verify
        password: Password to verify
        settings: Application settings

    Returns:
        True if credentials are valid, False otherwise
    """
    if not settings.enable_sybase_auth or not settings.sybase_auth_url:
        return False

    try:
        async with httpx.AsyncClient(timeout=settings.sybase_auth_timeout) as client:
            response = await client.post(
                settings.sybase_auth_url,
                json={
                    "username": username,
                    "password": password,
                    "stored_proc": settings.sybase_auth_stored_proc,
                },
            )

            if response.status_code == 200:
                result = response.json()
                return result.get("authenticated", False)

            return False

    except httpx.TimeoutException:
        return False
    except Exception:
        return False


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    login_data: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    Authenticate user and return access token.

    Flow:
    1. Check if Sybase auth is enabled
    2. If enabled, verify with Sybase API (non-blocking)
    3. If Sybase succeeds OR disabled, verify local password
    4. Create session and generate JWT token
    5. Log authentication attempt

    Args:
        request: FastAPI request
        login_data: Login credentials
        db: Database session
        settings: Application settings

    Returns:
        LoginResponse with access token

    Raises:
        HTTPException: If authentication fails
    """
    # Get user from database
    stmt = select(User).where(User.username == login_data.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    # Verify password
    password_valid = False

    # Try Sybase auth if enabled
    if settings.enable_sybase_auth:
        sybase_valid = await verify_sybase_credentials(
            login_data.username,
            login_data.password,
            settings,
        )

        if not sybase_valid:
            # External auth failed - DENY (no fallback to local)
            await AuditLogger.log_authentication(
                user_id=user.id,
                action="login_failed_external_auth",
                success=False,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                details={"username": login_data.username, "reason": "external_auth_failed"},
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="External authentication failed",
            )

        password_valid = True

    # Local password verification (only if external auth not enabled)
    if not settings.enable_sybase_auth and not password_valid:
        try:
            ph.verify(user.password_hash, login_data.password)
            password_valid = True

            # Rehash if parameters changed
            if ph.check_needs_rehash(user.password_hash):
                user.password_hash = ph.hash(login_data.password)
                await db.commit()

        except VerifyMismatchError:
            pass

    if not password_valid:
        # Log failed attempt
        await AuditLogger.log_authentication(
            user_id=user.id,
            action="login_failed",
            success=False,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            details={"username": login_data.username},
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Create session
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.access_token_expire_days
    )

    session = SessionModel(
        user_id=user.id,
        token="",  # Will be set after generating JWT
        expires_at=expires_at,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(session)
    await db.flush()

    # Generate JWT token
    token_data = {
        "user_id": user.id,
        "username": user.username,
        "role": user.role.value,
        "session_id": session.id,
        "exp": expires_at,
    }

    access_token = jwt.encode(
        token_data,
        settings.secret_key,
        algorithm=settings.algorithm,
    )

    # Update session with token
    session.token = access_token
    await db.commit()

    # Log successful login
    await AuditLogger.log_authentication(
        user_id=user.id,
        action="login_success",
        success=True,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"session_id": session.id},
    )

    # Calculate expires_in seconds
    expires_in = int((expires_at - datetime.now(timezone.utc)).total_seconds())

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        user_id=user.id,
        username=user.username,
        role=user.role,
    )


@router.post("/logout")
async def logout(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Logout current user by invalidating session.

    Args:
        request: FastAPI request
        current_user: Authenticated user
        db: Database session

    Returns:
        Success message
    """
    # Get current session
    session = getattr(current_user, "_current_session", None)

    if session:
        # Delete session from database
        await db.delete(session)
        await db.commit()

        # Log logout
        await AuditLogger.log_authentication(
            user_id=current_user.id,
            action="logout",
            success=True,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            details={"session_id": session.id},
        )

    return {"message": "Successfully logged out"}


@router.get("/me", response_model=LoginResponse)
async def get_current_user_info(
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    Get current authenticated user information.

    Args:
        current_user: Authenticated user
        settings: Application settings

    Returns:
        LoginResponse with current user info
    """
    session = getattr(current_user, "_current_session", None)

    if session:
        expires_in = int(
            (session.expires_at - datetime.now(timezone.utc)).total_seconds()
        )
    else:
        expires_in = 0

    return LoginResponse(
        access_token=session.token if session else "",
        token_type="bearer",
        expires_in=expires_in,
        user_id=current_user.id,
        username=current_user.username,
        role=current_user.role,
    )


@router.post("/refresh")
async def refresh_token(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    Refresh access token (extends expiration).

    Args:
        current_user: Authenticated user
        db: Database session
        settings: Application settings

    Returns:
        New LoginResponse with refreshed token
    """
    session = getattr(current_user, "_current_session", None)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No active session",
        )

    # Extend expiration
    new_expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.access_token_expire_days
    )

    # Generate new token
    token_data = {
        "user_id": current_user.id,
        "username": current_user.username,
        "role": current_user.role.value,
        "session_id": session.id,
        "exp": new_expires_at,
    }

    new_token = jwt.encode(
        token_data,
        settings.secret_key,
        algorithm=settings.algorithm,
    )

    # Update session
    session.token = new_token
    session.expires_at = new_expires_at
    await db.commit()

    expires_in = int(
        (new_expires_at - datetime.now(timezone.utc)).total_seconds()
    )

    return LoginResponse(
        access_token=new_token,
        token_type="bearer",
        expires_in=expires_in,
        user_id=current_user.id,
        username=current_user.username,
        role=current_user.role,
    )


# ------------------------------------------------------------------------------
# OAuth2 Compatible Endpoints
# ------------------------------------------------------------------------------

@oauth_router.post("/token", response_model=LoginResponse)
async def oauth_token(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    OAuth2 compatible token endpoint.

    This endpoint follows OAuth2 Password Grant flow specification:
    - Accepts form data (application/x-www-form-urlencoded)
    - Returns access token in OAuth2 format

    Args:
        request: FastAPI request
        username: Username from form data
        password: Password from form data
        db: Database session
        settings: Application settings

    Returns:
        LoginResponse with access token

    Raises:
        HTTPException: If authentication fails
    """
    # Create LoginRequest from form data
    login_data = LoginRequest(username=username, password=password)

    # Use existing login logic
    return await login(request, login_data, db, settings)
