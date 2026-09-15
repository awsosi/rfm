"""
PIM (Product Information Manager) Signalling Service

Second, independent signalling target alongside ROSAPI. Notifies the PIM
system whenever a catalog operation completes:

    PUSH   -> eventType "created"
    PULL   -> eventType "updated"
    UPDATE -> eventType "updated"

Authentication is a static ``X-API-TOKEN`` header rather than ROSAPI's JWT
login/refresh flow, so there is no token cache here.

The request body is a fully customisable template stored in the ``config``
table and editable from the Admin Panel. Supported placeholders:

- ``{files}``        JSON array of top-level basenames (substituted as raw JSON)
- ``{catalog_name}`` catalog/folder name being signalled
- ``{event_type}``   resolved eventType for this operation
- ``{tg_id}``        TG identifier; empty string unless configured
- ``{operation_id}`` RFM operation ID
- ``{username}``     user who triggered the operation
- ``{source_path}`` / ``{dest_path}``

``tgId`` is deliberately absent from the default template.
"""

import json
import os
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import DatabaseManager
from models import Config

# Config keys owned by this service
_CONFIG_KEYS = [
    'pim_enabled',
    'pim_base_url',
    'pim_endpoint',
    'pim_method',
    'pim_api_token',
    'pim_timeout',
    'pim_push_enabled',
    'pim_push_event_type',
    'pim_pull_enabled',
    'pim_pull_event_type',
    'pim_update_enabled',
    'pim_update_event_type',
    'pim_payload_template',
    'pim_tg_id',
]

_DEFAULT_TEMPLATE = (
    '{"files": {files}, "imageCatalog": "{catalog_name}", "eventType": "{event_type}"}'
)


async def _get_pim_config(db: AsyncSession) -> dict:
    """Read all PIM config keys from the database."""
    result = await db.execute(
        select(Config.key, Config.value).where(Config.key.in_(_CONFIG_KEYS))
    )
    return {row.key: row.value for row in result}


def _json_string(value: str) -> str:
    """Escape a value for safe interpolation inside a JSON string literal."""
    # json.dumps gives us a quoted string; strip the surrounding quotes so the
    # template's own quotes stay in control of the result.
    return json.dumps(str(value))[1:-1]


def resolve_payload_template(
    template: str,
    files: list,
    catalog_name: str,
    event_type: str,
    operation_id: int,
    username: str,
    source_path: str,
    dest_path: str,
    tg_id: str = "",
) -> str:
    """
    Resolve placeholders in the payload template.

    ``{files}`` is substituted as a raw JSON array so the template can write
    ``"files": {files}``. Every other placeholder is escaped for use inside a
    JSON string literal.
    """
    result = template
    result = result.replace("{files}", json.dumps(list(files), ensure_ascii=False))
    result = result.replace("{catalog_name}", _json_string(catalog_name))
    result = result.replace("{event_type}", _json_string(event_type))
    result = result.replace("{tg_id}", _json_string(tg_id))
    result = result.replace("{username}", _json_string(username))
    result = result.replace("{source_path}", _json_string(source_path))
    result = result.replace("{dest_path}", _json_string(dest_path))
    # Numeric, not string-escaped
    result = result.replace("{operation_id}", str(operation_id))
    return result


def extract_catalog_name(op_type: str, source_path: str, dest_path: str) -> str:
    """
    Derive the catalog (folder) name for an operation.

    PUSH signals the destination that was just created in PATH_B; PULL and
    UPDATE both act on a path whose basename is already the catalog name, so
    the destination is preferred with the source as fallback.
    """
    op = (op_type or "").upper()
    path = dest_path if op == "PUSH" else (source_path or dest_path)
    if not path:
        path = dest_path or ""
    return os.path.basename(str(path).rstrip('/\\'))


async def signal_pim_event_bg(
    operation_id: int,
    operation_type: str,
    source_path: str,
    dest_path: str,
    files: Optional[list] = None,
    username: str = "",
    catalog_name: Optional[str] = None,
) -> None:
    """
    Notify PIM that an operation completed. Fire-and-forget.

    Called via ``asyncio.create_task``. Creates its own DB session and swallows
    every exception so a PIM outage can never fail the underlying operation.
    """
    try:
        async with DatabaseManager.session() as db:
            config = await _get_pim_config(db)

        if config.get('pim_enabled', 'false').lower() not in ('true', '1', 'yes'):
            logger.debug("PIM signalling is disabled, skipping")
            return

        op_type_upper = (operation_type or "").upper()
        toggles = {
            "PUSH": ('pim_push_enabled', 'pim_push_event_type', 'created'),
            "PULL": ('pim_pull_enabled', 'pim_pull_event_type', 'updated'),
            "UPDATE": ('pim_update_enabled', 'pim_update_event_type', 'updated'),
        }
        if op_type_upper not in toggles:
            logger.debug(f"PIM signalling not applicable for operation type: {operation_type}")
            return

        enabled_key, event_key, event_default = toggles[op_type_upper]
        if config.get(enabled_key, 'true').lower() not in ('true', '1', 'yes'):
            logger.debug(f"PIM {op_type_upper} signalling is disabled")
            return

        event_type = (config.get(event_key) or event_default).strip() or event_default

        base_url = (config.get('pim_base_url') or '').strip()
        endpoint = (config.get('pim_endpoint') or '').strip()
        method = (config.get('pim_method') or 'POST').strip().upper()
        api_token = (config.get('pim_api_token') or '').strip()
        tg_id = (config.get('pim_tg_id') or '').strip()
        template = (config.get('pim_payload_template') or '').strip() or _DEFAULT_TEMPLATE

        if not base_url:
            logger.warning("PIM signalling enabled but pim_base_url is empty")
            return
        if not endpoint:
            logger.warning("PIM signalling enabled but pim_endpoint is empty")
            return
        if not api_token:
            logger.warning("PIM signalling enabled but pim_api_token is empty")
            return

        try:
            timeout = int(config.get('pim_timeout', '10'))
        except (TypeError, ValueError):
            timeout = 10

        resolved_catalog = catalog_name or extract_catalog_name(
            op_type_upper, source_path, dest_path
        )

        payload_str = resolve_payload_template(
            template=template,
            files=files or [],
            catalog_name=resolved_catalog,
            event_type=event_type,
            operation_id=operation_id,
            username=username,
            source_path=source_path or "",
            dest_path=dest_path or "",
            tg_id=tg_id,
        )

        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError as exc:
            logger.error(
                f"PIM payload template produced invalid JSON for operation "
                f"{operation_id}: {exc}. Template: {template!r}"
            )
            return

        url = f"{base_url.rstrip('/')}{endpoint if endpoint.startswith('/') else '/' + endpoint}"
        headers = {
            "X-API-TOKEN": api_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "POST":
                response = await client.post(url, json=payload, headers=headers)
            elif method == "PUT":
                response = await client.put(url, json=payload, headers=headers)
            elif method == "PATCH":
                response = await client.patch(url, json=payload, headers=headers)
            else:
                logger.error(f"Unsupported PIM HTTP method: {method}")
                return
            response.raise_for_status()

        logger.info(
            f"PIM signal sent: {method} {url} eventType={event_type} "
            f"imageCatalog={resolved_catalog!r} files={len(files or [])} "
            f"operation={operation_id} user={username or 'unknown'} "
            f"-> {response.status_code}"
        )

    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = exc.response.text[:500]
        except Exception:
            pass
        logger.error(
            f"PIM signal failed for operation {operation_id} "
            f"({operation_type}, user={username or 'unknown'}): "
            f"HTTP {exc.response.status_code} {body}"
        )
    except Exception as exc:
        logger.error(
            f"Failed to signal PIM for operation {operation_id} "
            f"({operation_type}, user={username or 'unknown'}): {exc}",
            exc_info=True,
        )
