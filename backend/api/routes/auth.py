"""
Authentication routes for login, logout, and session management.

Includes optional integration with external Sybase authentication API.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings, Settings
from api.middleware.auth import get_current_user
from api.middleware.logging import AuditLogger, get_client_ip
from api.schemas import LoginRequest, LoginResponse
from database import get_db
from models import Session as SessionModel, User


router = APIRouter(prefix="/api/auth", tags=["Authentication"])
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


async def _perform_login(
    request: Request,
    login_data: LoginRequest,
    db: AsyncSession,
    settings: Settings,
) -> LoginResponse:
    """
    Internal function to perform login logic.
    Used by both /token and /login endpoints.
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
                ip_address=get_client_ip(request),
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
            ip_address=get_client_ip(request),
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
        ip_address=get_client_ip(request),
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
        ip_address=get_client_ip(request),
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


@router.post("/token", response_model=LoginResponse)
async def token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    OAuth2-compatible token endpoint for authentication.

    This endpoint follows the OAuth2 password flow specification.
    Accepts form data (application/x-www-form-urlencoded) with username and password.

    Args:
        request: FastAPI request
        form_data: OAuth2 password form data
        db: Database session
        settings: Application settings

    Returns:
        LoginResponse with access token

    Raises:
        HTTPException: If authentication fails
    """
    # Convert OAuth2 form to LoginRequest
    login_data = LoginRequest(username=form_data.username, password=form_data.password)

    # Use the existing login logic
    return await _perform_login(request, login_data, db, settings)


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    login_data: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    Authenticate user and return access token (JSON version).

    This endpoint accepts JSON login data.
    For OAuth2-compatible form-based login, use /token endpoint.

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
    return await _perform_login(request, login_data, db, settings)


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
            ip_address=get_client_ip(request),
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
