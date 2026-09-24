"""
Hand an Explorer context-menu action to a WebUI tab the user already has open.

RFMLauncher used to open a new tab (deep link) for every click. Now it first
posts the action here: it is pushed to the user's open Explorer tabs, and the
first tab to claim it performs it. When no tab claims it within
``wait_seconds``, the launcher claims it and opens the deep link as before.
The claim is one atomic SET NX, so the action runs exactly once whoever wins.
"""

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from api.middleware.auth import get_current_user
from api.services.user_events import get_redis, publish_to_user
from models import User

router = APIRouter(prefix="/api/client-actions", tags=["client-actions"])

_TTL_SECONDS = 60
_OWNER_KEY = "rfm:client_action:{}:owner"
_CLAIM_KEY = "rfm:client_action:{}:claim"


class ClientActionRequest(BaseModel):
    action: Literal["prepare", "push"]
    paths: list[str] = Field(..., min_length=1, description="Windows paths, as in the deep link")
    wait_seconds: float = Field(3.0, ge=0, le=10)


class ClientActionResponse(BaseModel):
    action_id: str
    handled_by: Literal["tab", "launcher"]


class ClientActionClaimResponse(BaseModel):
    claimed: bool


@router.post("", response_model=ClientActionResponse)
async def hand_off_action(
    request_data: ClientActionRequest,
    current_user: User = Depends(get_current_user),
):
    """Offer the action to the user's open tabs; ``handled_by`` says who performs it."""
    action_id = uuid.uuid4().hex
    claim_key = _CLAIM_KEY.format(action_id)
    try:
        redis = get_redis()
        await redis.set(_OWNER_KEY.format(action_id), str(current_user.id), ex=_TTL_SECONDS)
        await publish_to_user(current_user.id, {
            "type": "client_action",
            "action_id": action_id,
            "action": request_data.action,
            "paths": request_data.paths,
        })

        loop = asyncio.get_running_loop()
        deadline = loop.time() + request_data.wait_seconds
        while loop.time() < deadline and not await redis.exists(claim_key):
            await asyncio.sleep(0.1)

        # No tab answered in time: the launcher takes it, unless one just did
        if await redis.set(claim_key, "launcher", nx=True, ex=_TTL_SECONDS):
            handled_by = "launcher"
        else:
            handled_by = "tab"
    except RedisError as exc:
        logger.warning(f"Client action hand-off unavailable: {exc}")
        raise HTTPException(status_code=503, detail="Client action hand-off unavailable") from exc

    logger.info(
        f"Client action {request_data.action} of {len(request_data.paths)} path(s) "
        f"by {current_user.username} handled by {handled_by}"
    )
    return ClientActionResponse(action_id=action_id, handled_by=handled_by)


@router.post("/{action_id}/claim", response_model=ClientActionClaimResponse)
async def claim_action(
    action_id: str,
    current_user: User = Depends(get_current_user),
):
    """Called by a tab before it performs the action; only the first claim wins."""
    try:
        redis = get_redis()
        owner = await redis.get(_OWNER_KEY.format(action_id))
        if owner != str(current_user.id):
            return ClientActionClaimResponse(claimed=False)
        claimed = await redis.set(_CLAIM_KEY.format(action_id), "tab", nx=True, ex=_TTL_SECONDS)
    except RedisError as exc:
        logger.warning(f"Client action claim unavailable: {exc}")
        raise HTTPException(status_code=503, detail="Client action hand-off unavailable") from exc
    return ClientActionClaimResponse(claimed=bool(claimed))
