"""
Catalog Name Validation Service (PolkaSQL RFM_ValidateProductName)

Validates that the catalog/folder name a user is about to PUSH or UPDATE
corresponds to a real product in the PolkaSQL (SQL Anywhere 17) database,
matching against ``Polka27.elementy.grup_nazwe_kolor``.

Mirrors the transport and AAA conventions of ``verify_polka_credentials()``
in ``api/routes/auth.py``: a Raw GET web service, API key as a query
parameter, JSON response body.

Expected response shape from RFM_ValidateProductName:

    {
      "success": true,
      "valid": true,
      "error": null,
      "catalog_name": "TORBA HB0788 FA0542-910 SILVER",
      "matched_name": "TORBA HB0788 FA0542-910 SILVER",
      "product_id": 2473757,
      "tg_id": "TORBA HB0788 FA0542",
      "suggestions": []
    }

On a miss, ``valid`` is false, ``matched_name`` and ``tg_id`` are null and
``suggestions`` carries the closest names ranked by similarity.

The tgId PIM expects is ``Polka27.elementy.grup_nazwe_kolor`` of the matched
row, which the procedure returns as ``matched_name``. Its own ``tg_id`` field
(``grup_nazwe``) is not what PIM wants and is ignored. ``lookup_tg_id()``
resolves the tgId for PIM delivery even when the validation gate itself is
switched off.

Enforcement is fail-closed: if validation is enabled and the service cannot
be reached, the operation is refused. Set ``catalog_validation_fail_open`` to
true to invert that during a PolkaSQL outage.
"""

from dataclasses import dataclass, field
from typing import List, Optional

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.polka import POLKA_HEADERS, polka_json
from models import Config

_CONFIG_KEYS = [
    'catalog_validation_enabled',
    'catalog_validation_url',
    'catalog_validation_api_key',
    'catalog_validation_timeout',
    'catalog_validation_max_suggestions',
    'catalog_validation_fail_open',
]


@dataclass
class CatalogValidationResult:
    """Outcome of a catalog name validation attempt."""

    valid: bool
    catalog_name: str
    matched_name: Optional[str] = None
    product_id: Optional[int] = None
    tg_id: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)
    # i18n key the frontend resolves; never a user-facing English string
    reason: Optional[str] = None
    error_detail: Optional[str] = None
    # True when validation was skipped because the feature is disabled
    skipped: bool = False

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "catalog_name": self.catalog_name,
            "matched_name": self.matched_name,
            "product_id": self.product_id,
            "tg_id": self.tg_id,
            "suggestions": self.suggestions,
            "reason": self.reason,
            "error_detail": self.error_detail,
            "skipped": self.skipped,
        }


async def _get_validation_config(db: AsyncSession) -> dict:
    stmt = select(Config).where(Config.key.in_(_CONFIG_KEYS))
    result = await db.execute(stmt)
    return {c.key: c.value for c in result.scalars()}


def _truthy(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ('true', '1', 'yes')


def _clean_tg_id(value) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


async def lookup_tg_id(catalog_name: str, db: AsyncSession) -> tuple:
    """
    Resolve the tgId of a catalog through RFM_ValidateProductName.

    Independent of ``catalog_validation_enabled``: that switch controls the
    PUSH/UPDATE gate, while PIM needs the tgId whenever its payload uses it.
    Only the URL and API key must be configured.

    Returns ``(tg_id, None)`` on success, ``(None, reason)`` otherwise. The
    reason is operator-facing English for the delivery log; the caller retries.
    """
    name = (catalog_name or "").strip()
    config = await _get_validation_config(db)
    url = (config.get('catalog_validation_url') or '').strip()
    api_key = (config.get('catalog_validation_api_key') or '').strip()
    if not name:
        return None, "catalog name is empty"
    if not url or not api_key:
        return None, "catalog_validation_url or catalog_validation_api_key is not configured"

    try:
        timeout = int(config.get('catalog_validation_timeout', '20'))
    except (TypeError, ValueError):
        timeout = 20

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                url,
                params={"ApiKey": api_key, "CatalogName": name, "MaxSuggestions": 1},
                headers=POLKA_HEADERS,
            )
        if response.status_code != 200:
            return None, f"RFM_ValidateProductName returned HTTP {response.status_code}"
        data = polka_json(response)
    except Exception as exc:
        return None, f"RFM_ValidateProductName unreachable: {type(exc).__name__}: {exc}"

    if not data.get("success"):
        return None, f"RFM_ValidateProductName error: {data.get('error') or 'unknown error'}"
    if not data.get("valid"):
        return None, f"no product matches catalog {name!r}"
    tg_id = _clean_tg_id(data.get("matched_name"))
    if not tg_id:
        return None, "RFM_ValidateProductName returned no matched_name"
    return tg_id, None


async def validate_catalog_name(
    catalog_name: str,
    db: AsyncSession,
) -> CatalogValidationResult:
    """
    Validate a catalog name against PolkaSQL.

    Returns a result object rather than raising, so callers decide how to
    surface the failure. Never raises for transport problems.
    """
    name = (catalog_name or "").strip()
    config = await _get_validation_config(db)

    if not _truthy(config.get('catalog_validation_enabled')):
        logger.debug("Catalog name validation is disabled, skipping")
        return CatalogValidationResult(
            valid=True, catalog_name=name, skipped=True
        )

    fail_open = _truthy(config.get('catalog_validation_fail_open'), default=False)

    if not name:
        return CatalogValidationResult(
            valid=False,
            catalog_name=name,
            reason="catalogValidation.emptyName",
        )

    url = (config.get('catalog_validation_url') or '').strip()
    api_key = (config.get('catalog_validation_api_key') or '').strip()

    if not url or not api_key:
        logger.warning(
            "Catalog name validation is enabled but URL or API key is not configured"
        )
        return CatalogValidationResult(
            valid=fail_open,
            catalog_name=name,
            reason=None if fail_open else "catalogValidation.notConfigured",
            error_detail="catalog_validation_url or catalog_validation_api_key is empty",
        )

    try:
        timeout = int(config.get('catalog_validation_timeout', '20'))
    except (TypeError, ValueError):
        timeout = 20

    try:
        max_suggestions = int(config.get('catalog_validation_max_suggestions', '5'))
    except (TypeError, ValueError):
        max_suggestions = 5

    params = {
        "ApiKey": api_key,
        "CatalogName": name,
        "MaxSuggestions": max_suggestions,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                url, params=params, headers=POLKA_HEADERS
            )

        if response.status_code != 200:
            logger.error(
                f"Catalog validation HTTP {response.status_code} for {name!r}"
            )
            return CatalogValidationResult(
                valid=fail_open,
                catalog_name=name,
                reason=None if fail_open else "catalogValidation.serviceUnavailable",
                error_detail=f"HTTP {response.status_code}",
            )

        data = polka_json(response)

        if not data.get("success"):
            err = data.get("error") or "unknown error"
            logger.error(f"Catalog validation service error for {name!r}: {err}")
            return CatalogValidationResult(
                valid=fail_open,
                catalog_name=name,
                reason=None if fail_open else "catalogValidation.serviceError",
                error_detail=str(err),
            )

        is_valid = bool(data.get("valid"))
        suggestions = data.get("suggestions") or []
        if not isinstance(suggestions, list):
            suggestions = []
        suggestions = [str(s) for s in suggestions][:max_suggestions]

        if is_valid:
            logger.info(
                f"Catalog name {name!r} validated against PolkaSQL "
                f"(product_id={data.get('product_id')})"
            )
            return CatalogValidationResult(
                valid=True,
                catalog_name=name,
                matched_name=data.get("matched_name") or name,
                product_id=data.get("product_id"),
                tg_id=_clean_tg_id(data.get("matched_name")),
            )

        logger.warning(
            f"Catalog name {name!r} did not match any product; "
            f"{len(suggestions)} suggestion(s) offered"
        )
        return CatalogValidationResult(
            valid=False,
            catalog_name=name,
            suggestions=suggestions,
            reason="catalogValidation.noMatch",
        )

    except httpx.TimeoutException:
        logger.error(f"Catalog validation timed out after {timeout}s for {name!r}")
        return CatalogValidationResult(
            valid=fail_open,
            catalog_name=name,
            reason=None if fail_open else "catalogValidation.timeout",
            error_detail=f"timeout after {timeout}s",
        )
    except Exception as exc:
        logger.error(
            f"Catalog validation failed for {name!r}: {exc}", exc_info=True
        )
        return CatalogValidationResult(
            valid=fail_open,
            catalog_name=name,
            reason=None if fail_open else "catalogValidation.serviceUnavailable",
            error_detail=str(exc),
        )
