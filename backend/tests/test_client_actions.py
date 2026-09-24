"""
RFMLauncher hands a context-menu action to an open WebUI tab instead of
opening a new one (api/routes/client_actions.py).

Runs the real Redis relay (api/services/user_events.py) against fakeredis and
fake tab sockets, so what is asserted is exactly-once handling: one tab or the
launcher performs the action, never both and never two tabs.
"""

import asyncio

import fakeredis
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.middleware.auth import get_current_user
from api.routes import client_actions
from api.services import user_events
from api.websocket_manager import ws_manager


class User:
    def __init__(self, user_id):
        self.id = user_id
        self.username = f"user{user_id}"


class Tab:
    """A WebUI tab: claims every client_action it receives, like app.js does."""

    def __init__(self, client, user_id, claim=True):
        self.client, self.user_id, self.claim = client, user_id, claim
        self.received, self.claims = [], []

    async def send_json(self, data):
        self.received.append(data)
        if data.get("type") == "client_action" and self.claim:
            asyncio.get_running_loop().create_task(self._claim(data["action_id"]))

    async def _claim(self, action_id):
        response = await self.client.post(
            f"/api/client-actions/{action_id}/claim", headers={"X-User": str(self.user_id)}
        )
        self.claims.append(response.json()["claimed"])


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(user_events, "_redis", fakeredis.aioredis.FakeRedis(decode_responses=True))

    app = FastAPI()
    app.include_router(client_actions.router)

    from fastapi import Request

    async def current_user(request: Request):
        return User(int(request.headers["X-User"]))

    app.dependency_overrides[get_current_user] = current_user

    relay = asyncio.create_task(user_events.forward_user_events())
    await asyncio.sleep(0.05)  # let the relay subscribe
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    relay.cancel()
    for connection_id in list(ws_manager.active_connections):
        ws_manager.active_connections.pop(connection_id, None)
        ws_manager.connection_metadata.pop(connection_id, None)


def open_tab(client, connection_id, user_id, claim=True):
    tab = Tab(client, user_id, claim)
    ws_manager.active_connections[connection_id] = tab
    ws_manager.connection_metadata[connection_id] = {"user_id": user_id, "topics": set()}
    return tab


async def hand_off(client, user_id, wait_seconds=1.0):
    response = await client.post(
        "/api/client-actions",
        json={"action": "push", "paths": [r"\\hv2012r2\DaneFoto\DO KATALOGU\Ewa\TORBA X"],
              "wait_seconds": wait_seconds},
        headers={"X-User": str(user_id)},
    )
    assert response.status_code == 200
    return response.json()


async def test_no_open_tab_leaves_it_to_the_launcher(client):
    assert (await hand_off(client, 1, wait_seconds=0.3))["handled_by"] == "launcher"


async def test_open_tab_takes_the_action(client):
    tab = open_tab(client, "c1", 1)
    result = await hand_off(client, 1)
    assert result["handled_by"] == "tab"
    assert tab.claims == [True]
    assert tab.received[0]["paths"] == [r"\\hv2012r2\DaneFoto\DO KATALOGU\Ewa\TORBA X"]


async def test_only_one_of_several_tabs_acts(client):
    tabs = [open_tab(client, f"c{i}", 1) for i in range(3)]
    assert (await hand_off(client, 1))["handled_by"] == "tab"
    await asyncio.sleep(0.1)
    assert sorted(claim for tab in tabs for claim in tab.claims) == [False, False, True]


async def test_other_users_tabs_neither_see_nor_claim_it(client):
    stranger = open_tab(client, "c1", 2)
    assert (await hand_off(client, 1, wait_seconds=0.3))["handled_by"] == "launcher"
    assert stranger.received == []

    # Even with the id in hand, a claim by another user is refused
    action = await hand_off(client, 1, wait_seconds=0)
    response = await client.post(f"/api/client-actions/{action['action_id']}/claim", headers={"X-User": "2"})
    assert response.json() == {"claimed": False}


async def test_late_tab_claim_loses_to_the_launcher(client):
    open_tab(client, "c1", 1, claim=False)
    action = await hand_off(client, 1, wait_seconds=0.2)
    assert action["handled_by"] == "launcher"
    response = await client.post(f"/api/client-actions/{action['action_id']}/claim", headers={"X-User": "1"})
    assert response.json() == {"claimed": False}
