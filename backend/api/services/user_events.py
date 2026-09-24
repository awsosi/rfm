"""
Deliver an event to one user's open WebUI tabs, whichever API process holds them.

uvicorn runs several worker processes (``API_WORKERS``), each with its own
WebSocket connections, so ``ws_manager`` alone only reaches the tabs of the
process that happened to take the request. Events are published on Redis
instead, and every process forwards them to the matching sockets it holds.
"""

import asyncio
import json
from typing import Any

import redis.asyncio as aioredis
from loguru import logger

from api.config import get_settings

CHANNEL = "rfm:user_events"

_redis = None


def get_redis():
    """Process-wide Redis client (connections are pooled and opened lazily)."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            get_settings().redis_url, decode_responses=True, socket_connect_timeout=3
        )
    return _redis


async def publish_to_user(user_id: int, payload: dict[str, Any]) -> None:
    await get_redis().publish(CHANNEL, json.dumps({"user_id": user_id, "payload": payload}))


async def forward_user_events() -> None:
    """Relay published events to this process's sockets; runs for the app's lifetime."""
    from api.websocket_manager import ws_manager

    while True:
        pubsub = get_redis().pubsub()
        try:
            await pubsub.subscribe(CHANNEL)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                event = json.loads(message["data"])
                await ws_manager.send_to_user(event["user_id"], event["payload"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"User event relay interrupted, reconnecting in 5s: {exc}")
            await asyncio.sleep(5)
        finally:
            await pubsub.aclose()
