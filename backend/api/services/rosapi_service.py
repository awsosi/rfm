"""
ROSAPI (Remote Operation Signalling API) Service

Signals an external PIM (Product Image Manager) system when PUSH/PULL operations
complete. Uses JWT authentication with token caching and automatic refresh.

Template variables supported in endpoints and payloads:
- {folder_name}: Extracted folder name (dest_path basename for PUSH, source_path for PULL)
- {operation_id}: RFM operation ID
- {source_path}: Operation source path
- {dest_path}: Operation destination path
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import DatabaseManager
from models import Config

# --- Token cache (module-level, per-process) ---
_access_token: Optional[str] = None
_refresh_token: Optional[str] = None
_token_expires_at: Optional[datetime] = None


async def _get_rosapi_config(db: AsyncSession) -> dict:
    """
    Read all ROSAPI config keys from the database.

    Returns a dict mapping config keys to their values.
    Pattern from verify_polka_credentials() in auth.py.
    """
    config_keys = [
        'rosapi_enabled',
        'rosapi_base_url',
        'rosapi_auth_email',
        'rosapi_auth_password',
        'rosapi_timeout',
        'rosapi_push_enabled',
        'rosapi_push_endpoint',
        'rosapi_push_method',
        'rosapi_push_payload',
        'rosapi_pull_enabled',
        'rosapi_pull_endpoint',
        'rosapi_pull_method',
        'rosapi_pull_payload',
        'rosapi_verify_url',
    ]

    result = await db.execute(
        select(Config.key, Config.value).where(Config.key.in_(config_keys))
    )
    config_dict = {row.key: row.value for row in result}

    return config_dict


async def _authenticate(
    base_url: str,
    email: str,
    password: str,
    timeout: int,
) -> tuple[str, str]:
    """
    Authenticate with ROSAPI and return (access_token, refresh_token).

    POST /api/v1/auth/login with {"email": ..., "password": ...}
    Expects response: {"access_token": "...", "refresh_token": "..."}
    """
    url = f"{base_url.rstrip('/')}/api/v1/auth/login"
    payload = {"email": email, "password": password}

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")

    if not access_token or not refresh_token:
        raise ValueError("ROSAPI authentication response missing tokens")

    return access_token, refresh_token


async def _refresh_access_token(
    base_url: str,
    refresh_token: str,
    timeout: int,
) -> tuple[str, str]:
    """
    Refresh the access token using the refresh token.

    POST /api/v1/auth/refresh with {"refresh_token": "..."}
    Expects response: {"access_token": "...", "refresh_token": "..."}
    """
    url = f"{base_url.rstrip('/')}/api/v1/auth/refresh"
    payload = {"refresh_token": refresh_token}

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    access_token = data.get("access_token")
    new_refresh_token = data.get("refresh_token")

    if not access_token or not new_refresh_token:
        raise ValueError("ROSAPI refresh response missing tokens")

    return access_token, new_refresh_token


async def _get_valid_token(
    base_url: str,
    email: str,
    password: str,
    timeout: int,
) -> str:
    """
    Get a valid access token, using cache if available, otherwise authenticate.

    Token cache has 50-minute expiry (10-min safety margin on 1-hour token).
    If cached token is expired, attempts refresh, falls back to full re-auth.
    """
    global _access_token, _refresh_token, _token_expires_at

    now = datetime.now(timezone.utc)

    # Check if cached token is still valid
    if _access_token and _token_expires_at and now < _token_expires_at:
        logger.debug("Using cached ROSAPI access token")
        return _access_token

    # Try to refresh if we have a refresh token
    if _refresh_token:
        try:
            logger.debug("Refreshing ROSAPI access token")
            _access_token, _refresh_token = await _refresh_access_token(
                base_url, _refresh_token, timeout
            )
            _token_expires_at = now + timedelta(minutes=50)
            logger.info("Successfully refreshed ROSAPI access token")
            return _access_token
        except Exception as exc:
            logger.warning(f"Failed to refresh ROSAPI token, re-authenticating: {exc}")
            # Clear cache and fall through to full auth
            _access_token = None
            _refresh_token = None
            _token_expires_at = None

    # Full authentication
    logger.debug("Performing full ROSAPI authentication")
    _access_token, _refresh_token = await _authenticate(
        base_url, email, password, timeout
    )
    _token_expires_at = now + timedelta(minutes=50)
    logger.info("Successfully authenticated with ROSAPI")
    return _access_token


def _resolve_template(
    template: str,
    operation_id: int,
    folder_name: str,
    source_path: str,
    dest_path: str,
) -> str:
    """
    Resolve template variables in a string.

    Supported variables: {folder_name}, {operation_id}, {source_path}, {dest_path}
    Uses str.format() with try/except for unknown variables.
    """
    try:
        return template.format(
            folder_name=folder_name,
            operation_id=operation_id,
            source_path=source_path,
            dest_path=dest_path,
        )
    except KeyError as exc:
        logger.warning(f"Unknown template variable in ROSAPI template: {exc}")
        # Return template as-is if unknown variable
        return template


def _extract_folder_name(op_type: str, source_path: str, dest_path: str) -> str:
    """
    Extract folder name from operation paths.

    - PUSH: basename of dest_path
    - PULL: basename of source_path
    """
    import os

    if op_type.upper() == "PUSH":
        path = dest_path
    else:  # PULL
        path = source_path

    # Extract basename (last component)
    folder_name = os.path.basename(path.rstrip('/\\'))
    return folder_name


async def _send_signal(
    base_url: str,
    token: str,
    method: str,
    endpoint: str,
    payload_str: str,
    timeout: int,
    operation_id: int,
    folder_name: str,
    source_path: str,
    dest_path: str,
) -> None:
    """
    Send HTTP signal to ROSAPI endpoint.

    Resolves templates in endpoint and payload, then sends request.
    """
    # Resolve endpoint template
    resolved_endpoint = _resolve_template(
        endpoint, operation_id, folder_name, source_path, dest_path
    )
    url = f"{base_url.rstrip('/')}{resolved_endpoint}"

    # Resolve payload template
    resolved_payload_str = _resolve_template(
        payload_str, operation_id, folder_name, source_path, dest_path
    )

    # Parse JSON payload
    try:
        payload = json.loads(resolved_payload_str)
    except json.JSONDecodeError as exc:
        logger.error(f"Invalid JSON in ROSAPI payload: {exc}")
        payload = {}

    # Build headers
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Send request
    async with httpx.AsyncClient(timeout=timeout) as client:
        if method.upper() == "POST":
            response = await client.post(url, json=payload, headers=headers)
        elif method.upper() == "PUT":
            response = await client.put(url, json=payload, headers=headers)
        elif method.upper() == "GET":
            response = await client.get(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()

    logger.info(
        f"ROSAPI signal sent successfully: {method} {url} -> {response.status_code}"
    )


async def signal_operation_completed_bg(
    operation_id: int,
    operation_type: str,
    source_path: str,
    dest_path: str,
) -> None:
    """
    Main entry point for signalling ROSAPI when an operation completes.

    This function is called via asyncio.create_task() in a fire-and-forget manner.
    Creates its own DB session to avoid session lifecycle issues.
    Catches all exceptions internally.

    On HTTP 401, clears token cache and retries once with fresh authentication.
    """
    global _access_token, _refresh_token, _token_expires_at

    try:
        # Create own DB session
        async with DatabaseManager.session() as db:
            config = await _get_rosapi_config(db)

        # Check if ROSAPI is enabled
        if config.get('rosapi_enabled', 'false').lower() != 'true':
            logger.debug("ROSAPI is disabled, skipping signal")
            return

        # Check if signalling is enabled for this operation type
        op_type_upper = operation_type.upper()
        if op_type_upper == "PUSH":
            if config.get('rosapi_push_enabled', 'false').lower() != 'true':
                logger.debug("ROSAPI PUSH signalling is disabled")
                return
            endpoint = config.get('rosapi_push_endpoint', '')
            method = config.get('rosapi_push_method', 'POST')
            payload = config.get('rosapi_push_payload', '{}')
        elif op_type_upper == "PULL":
            if config.get('rosapi_pull_enabled', 'false').lower() != 'true':
                logger.debug("ROSAPI PULL signalling is disabled")
                return
            endpoint = config.get('rosapi_pull_endpoint', '')
            method = config.get('rosapi_pull_method', 'POST')
            payload = config.get('rosapi_pull_payload', '{}')
        else:
            logger.debug(f"ROSAPI signalling not applicable for operation type: {operation_type}")
            return

        # Validate required config
        base_url = config.get('rosapi_base_url', '').strip()
        email = config.get('rosapi_auth_email', '').strip()
        password = config.get('rosapi_auth_password', '').strip()

        if not base_url or not email or not password:
            logger.warning("ROSAPI is enabled but missing required config (base_url, email, password)")
            return

        if not endpoint:
            logger.warning(f"ROSAPI {op_type_upper} signalling enabled but endpoint is empty")
            return

        # Parse timeout
        try:
            timeout = int(config.get('rosapi_timeout', '10'))
        except ValueError:
            timeout = 10

        # Extract folder name
        folder_name = _extract_folder_name(operation_type, source_path, dest_path)

        # Get valid token
        token = await _get_valid_token(base_url, email, password, timeout)

        # Send signal (with retry on 401)
        try:
            await _send_signal(
                base_url,
                token,
                method,
                endpoint,
                payload,
                timeout,
                operation_id,
                folder_name,
                source_path,
                dest_path,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                logger.warning("ROSAPI returned 401, clearing token cache and retrying")
                # Clear cache
                _access_token = None
                _refresh_token = None
                _token_expires_at = None
                # Retry with fresh auth
                token = await _get_valid_token(base_url, email, password, timeout)
                await _send_signal(
                    base_url,
                    token,
                    method,
                    endpoint,
                    payload,
                    timeout,
                    operation_id,
                    folder_name,
                    source_path,
                    dest_path,
                )
            else:
                raise

        logger.info(
            f"ROSAPI signal completed for {operation_type} operation {operation_id} (folder: {folder_name})"
        )

    except Exception as exc:
        logger.error(
            f"Failed to signal ROSAPI for operation {operation_id}: {exc}",
            exc_info=True,
        )
