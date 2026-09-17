"""
Authentication routes for login, logout, and session management.

Includes optional integration with PolkaSQL/Sybase authentication API.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
import jwt
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings, Settings
from api.middleware.auth import get_current_user, get_session_policy, session_expiry
from api.middleware.logging import AuditLogger, get_client_ip
from api.schemas import (
    LoginRequest,
    LoginResponse,
    MessageResponse,
    ReauthenticateRequest,
    DeviceAuthorizationResponse,
    DeviceAuthorizationPollRequest,
    DeviceAuthorizationApprovalRequest,
)
from database import get_db
from models import Session as SessionModel, User, UserRole, DeviceAuthorizationRequest


router = APIRouter(prefix="/api/auth", tags=["Authentication"])
ph = PasswordHasher()


@router.get("/status")
async def get_auth_status(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Get authentication configuration status (public endpoint).

    Returns whether PolkaSQL authentication is enabled.
    Used by frontend to show/hide auth method selector.
    """
    from models import Config

    # DB is the single source of truth (env vars are synced into DB on startup)
    stmt = select(Config).where(Config.key == 'polka_auth_enabled')
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    enabled = bool(config and config.value.lower() in ('true', '1', 'yes'))

    return {
        "polka_auth_enabled": enabled
    }


async def verify_polka_credentials(
    username: str,
    password: str,
    db: AsyncSession,
) -> tuple[bool, dict | None]:
    """
    Verify credentials against PolkaSQL/Sybase RFM_Auth API.

    Reads all config from DB (env vars are synced into DB on startup).
    Username and password are case-insensitive per PolkaSQL API requirements.

    Returns:
        Tuple of (authenticated, user_data).
    """
    from models import Config

    # DB is the single source of truth (env vars are synced into DB on startup)
    stmt = select(Config).where(Config.key.in_([
        'polka_auth_enabled',
        'polka_auth_url',
        'polka_auth_api_key',
        'polka_auth_timeout'
    ]))
    result = await db.execute(stmt)
    db_configs = {config.key: config.value for config in result.scalars()}

    # Check if PolkaSQL auth is enabled
    enabled_str = db_configs.get('polka_auth_enabled', '')
    if enabled_str.lower() not in ('true', '1', 'yes'):
        return False, None

    polka_url = db_configs.get('polka_auth_url', '')
    if not polka_url:
        return False, None

    api_key = db_configs.get('polka_auth_api_key', '')
    if not api_key:
        return False, None

    try:
        timeout = int(db_configs.get('polka_auth_timeout', '5'))
    except (ValueError, TypeError):
        timeout = 5

    try:
        # Build query parameters (API uses GET request with query params)
        params = {
            "ApiKey": api_key,
            "UserName": username,  # API handles case-insensitivity
            "Password": password,  # API handles case-insensitivity
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                polka_url,
                params=params,
                headers={"Accept": "application/json"},
            )

            if response.status_code == 200:
                result = response.json()

                # Check if API call was successful
                if not result.get("success"):
                    return False, None

                # Check if user was authenticated
                if not result.get("authenticated"):
                    return False, None

                # Return user data
                user_data = {
                    "user_id": result.get("user_id"),
                    "username": result.get("username"),
                }

                return True, user_data

            return False, None

    except httpx.TimeoutException:
        return False, None
    except Exception:
        return False, None


async def _perform_login(
    request: Request,
    login_data: LoginRequest,
    db: AsyncSession,
    settings: Settings,
) -> LoginResponse:
    """
    Internal function to perform login logic.
    Used by both /token and /login endpoints.

    Supports:
    - Local authentication (password hash)
    - PolkaSQL/Sybase authentication (RFM_Auth API, case-insensitive, auto-create users)

    Auth method selection:
    - "auto": Try PolkaSQL first (if enabled), fallback to local
    - "polka": Only PolkaSQL authentication
    - "local": Only local authentication
    """
    # Determine auth method
    auth_method = login_data.auth_method or "auto"

    # Try PolkaSQL authentication (if requested)
    polka_authenticated = False
    polka_user_data = None

    if auth_method in ["auto", "polka"]:
        polka_authenticated, polka_user_data = await verify_polka_credentials(
            login_data.username,
            login_data.password,
            db,
        )

    if polka_authenticated:
        # PolkaSQL auth successful - find or create user
        # Use case-insensitive lookup for PolkaSQL auth users
        stmt = select(User).where(func.lower(User.username) == func.lower(login_data.username))
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            # Create new user from PolkaSQL auth
            # Generate a random password hash (won't be used for auth)
            import secrets
            random_password = secrets.token_urlsafe(32)
            password_hash = ph.hash(random_password)

            user = User(
                username=login_data.username.lower(),  # Store as lowercase
                password_hash=password_hash,
                role=UserRole.USER,  # Default role for PolkaSQL users
                is_active=True,
                is_polka_auth=True,
                polka_user_id=polka_user_data["user_id"],
            )

            db.add(user)
            await db.commit()
            await db.refresh(user)

            # Log user creation
            await AuditLogger.log_admin_action(
                user_id=None,
                action="user_create_polka_auth",
                target="user",
                details={
                    "username": user.username,
                    "polka_user_id": polka_user_data["user_id"],
                    "source": "polka_authentication",
                },
                ip_address=get_client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )

        else:
            # Existing PolkaSQL auth user - update polka_user_id if changed
            if user.is_polka_auth and user.polka_user_id != polka_user_data["user_id"]:
                user.polka_user_id = polka_user_data["user_id"]
                await db.commit()

        # Check if user is active
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled",
            )

        # Continue to session creation (skip password verification)
        password_valid = True

    else:
        # PolkaSQL auth not enabled, failed, or not requested
        # If auth_method is "polka", fail here (no fallback)
        if auth_method == "polka":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="PolkaSQL authentication failed",
            )

        # Try local auth (auth_method is "auto" or "local")
        # Get user from database (exact match for local users)
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

        # Verify password - local password hash verification only
        password_valid = False

        # Local password verification
        if not password_valid:
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

    # The password was just typed: counts as a confirmation for admin changes
    session = await _open_session(
        request, db, settings, user,
        remember_me=login_data.remember_me,
        reauthenticated_at=datetime.now(timezone.utc),
    )

    # Log successful login
    await AuditLogger.log_authentication(
        user_id=user.id,
        action="login_success",
        success=True,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        details={"session_id": session.id, "remember_me": session.remember_me},
    )

    return _session_response(session, user)


def _encode_session_token(session: SessionModel, user: User, settings: Settings) -> str:
    return jwt.encode(
        {
            "user_id": user.id,
            "username": user.username,
            "role": user.role.value,
            "session_id": session.id,
            "exp": session.expires_at,
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )


async def _open_session(
    request: Request,
    db: AsyncSession,
    settings: Settings,
    user: User,
    remember_me: bool,
    reauthenticated_at: datetime | None = None,
) -> SessionModel:
    """Create and commit a session whose lifetime follows the session policy."""
    expires_at, remember = session_expiry(await get_session_policy(db), user, remember_me)
    session = SessionModel(
        user_id=user.id,
        token="",  # Set once the id is known
        expires_at=expires_at,
        remember_me=remember,
        reauthenticated_at=reauthenticated_at,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(session)
    await db.flush()
    session.token = _encode_session_token(session, user, settings)
    await db.commit()
    return session


def _session_response(session: SessionModel, user: User, **extra) -> LoginResponse:
    return LoginResponse(
        access_token=session.token,
        token_type="bearer",
        expires_in=max(int((session.expires_at - datetime.now(timezone.utc)).total_seconds()), 0),
        user_id=user.id,
        username=user.username,
        role=user.role,
        remember_me=session.remember_me,
        **extra,
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

    if not session:
        return LoginResponse(
            access_token="",
            expires_in=0,
            user_id=current_user.id,
            username=current_user.username,
            role=current_user.role,
        )
    return _session_response(session, current_user)


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

    # Extend by the current policy; a user promoted to admin loses "Remember me"
    session.expires_at, session.remember_me = session_expiry(
        await get_session_policy(db), current_user, session.remember_me
    )
    session.token = _encode_session_token(session, current_user, settings)
    await db.commit()

    return _session_response(session, current_user)


@router.post("/reauthenticate", response_model=MessageResponse)
async def reauthenticate(
    request: Request,
    body: ReauthenticateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Confirm the current user's password within this session.

    Admin changes to system settings require a confirmation no older than
    ``admin_reauth_minutes`` (see ``require_recent_auth``).
    """
    session = getattr(current_user, "_current_session", None)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active session")

    if current_user.is_polka_auth:
        valid, _ = await verify_polka_credentials(current_user.username, body.password, db)
    else:
        try:
            valid = ph.verify(current_user.password_hash, body.password)
        except VerifyMismatchError:
            valid = False

    await AuditLogger.log_authentication(
        user_id=current_user.id,
        action="reauthenticate" if valid else "reauthenticate_failed",
        success=valid,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        details={"session_id": session.id},
    )
    if not valid:
        # 403, not 401: a wrong password must not end the session
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid password")

    session.reauthenticated_at = datetime.now(timezone.utc)
    await db.commit()
    return MessageResponse(message="Password confirmed")


# =============================================================================
# Device Authorization Flow (OAuth Device Flow - RFC 8628)
# =============================================================================


def generate_device_code() -> str:
    """Generate a secure device code (32 bytes hex)."""
    import secrets
    return secrets.token_hex(32)


def generate_user_code() -> str:
    """Generate a user-friendly code (format: ABC-123)."""
    import secrets
    import string
    # Generate 6 random uppercase alphanumeric characters
    chars = string.ascii_uppercase + string.digits
    code = ''.join(secrets.choice(chars) for _ in range(6))
    # Format as XXX-XXX for readability
    return f"{code[:3]}-{code[3:]}"


@router.post("/device/request", response_model=DeviceAuthorizationResponse)
async def device_authorization_request(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    Request device authorization (step 1 of OAuth device flow).

    Generates device_code and user_code for device authorization.
    Client should poll /device/poll with device_code and direct user to verification_uri.

    Returns:
        DeviceAuthorizationResponse with device_code, user_code, verification_uri, and expires_in
    """
    # Generate codes
    device_code = generate_device_code()
    user_code = generate_user_code()

    # Set expiration (15 minutes)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    # Create device authorization request
    device_auth = DeviceAuthorizationRequest(
        device_code=device_code,
        user_code=user_code,
        user_id=None,
        approved=False,
        expires_at=expires_at,
    )

    db.add(device_auth)
    await db.commit()

    # Build verification URI
    # Use public-facing frontend URL for browser pages
    base_url = settings.frontend_url_public.rstrip('/')
    verification_uri = f"{base_url}/pages/device.html"

    # Calculate expires_in
    expires_in = 900  # 15 minutes in seconds

    return DeviceAuthorizationResponse(
        device_code=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        expires_in=expires_in,
    )


@router.post("/device/poll", response_model=LoginResponse)
async def device_authorization_poll(
    request: Request,
    poll_request: DeviceAuthorizationPollRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """
    Poll for device authorization approval (step 2 of OAuth device flow).

    Client should poll this endpoint with device_code until user approves or request expires.

    Args:
        poll_request: Contains device_code

    Returns:
        LoginResponse if approved, or error if pending/expired

    Raises:
        HTTPException 400: authorization_pending or expired_token
    """
    # Find device authorization request
    stmt = select(DeviceAuthorizationRequest).where(
        DeviceAuthorizationRequest.device_code == poll_request.device_code
    )
    result = await db.execute(stmt)
    device_auth = result.scalar_one_or_none()

    if not device_auth:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expired_token",
        )

    # Check if expired
    if device_auth.is_expired:
        # Clean up expired request
        await db.delete(device_auth)
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expired_token",
        )

    # Check if approved
    if not device_auth.approved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="authorization_pending",
        )

    # Approved - get user
    stmt = select(User).where(User.id == device_auth.user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found",
        )

    # The Windows client keeps its credentials, like "Remember me" (not for admins)
    session = await _open_session(request, db, settings, user, remember_me=True)

    # Clean up device authorization request
    await db.delete(device_auth)
    await db.commit()

    # Log successful device authorization
    await AuditLogger.log_authentication(
        user_id=user.id,
        action="device_authorization_success",
        success=True,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        details={"device_code": device_auth.device_code, "user_code": device_auth.user_code},
    )

    # Refresh token is the access token for now
    return _session_response(session, user, refresh_token=session.token)


@router.post("/device/approve")
async def device_authorization_approve(
    request: Request,
    approval_request: DeviceAuthorizationApprovalRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Approve device authorization (step 3 of OAuth device flow - user action).

    User must be authenticated via web browser to approve device.
    Finds pending device authorization by user_code and approves it.

    Args:
        approval_request: Contains user_code to approve
        current_user: Authenticated user (from web browser)

    Returns:
        Success message

    Raises:
        HTTPException: If user_code not found or expired
    """
    # Find device authorization request by user_code
    stmt = select(DeviceAuthorizationRequest).where(
        DeviceAuthorizationRequest.user_code == approval_request.user_code
    )
    result = await db.execute(stmt)
    device_auth = result.scalar_one_or_none()

    if not device_auth:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired authorization code",
        )

    # Check if expired
    if device_auth.is_expired:
        # Clean up expired request
        await db.delete(device_auth)
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authorization code has expired",
        )

    # Approve the request
    device_auth.approved = True
    device_auth.user_id = current_user.id
    await db.commit()

    # Log device approval
    await AuditLogger.log_authentication(
        user_id=current_user.id,
        action="device_authorization_approved",
        success=True,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        details={"user_code": device_auth.user_code},
    )

    return {"message": "Device authorized successfully"}
