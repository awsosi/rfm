"""
Session lifetime, "Remember me" and admin password confirmation.

Runs the real app over HTTP (routes, dependencies, exception handler) on a
real PostgreSQL, like test_update_uploads.py whose fixtures this reuses:

    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/rfm_test pytest tests/test_session_policy.py
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from argon2 import PasswordHasher
from sqlalchemy import select, update

from models import AuditLog, Config, Session as SessionModel, User, UserRole
from tests.test_update_uploads import (  # noqa: F401  (fixtures)
    TEST_DATABASE_URL,
    db_manager,
    migrated_database,
    session,
    set_config,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set (needs a disposable PostgreSQL database)",
)

PASSWORD = "correct horse"
DAY = 86400


@pytest.fixture
async def client(db_manager):
    from api.app import app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def policy(session):
    await set_config(session, session_lifetime_days=5, session_remember_me_days=30, admin_reauth_minutes=15)


async def add_account(session, username, role=UserRole.USER) -> User:
    user = User(username=username, password_hash=PasswordHasher().hash(PASSWORD), role=role)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def login(client, username, remember_me=False) -> dict:
    response = await client.post("/api/auth/login", json={
        "username": username, "password": PASSWORD, "auth_method": "local", "remember_me": remember_me,
    })
    assert response.status_code == 200, response.text
    return response.json()


def auth(data) -> dict:
    return {"Authorization": f"Bearer {data['access_token']}"}


async def stored_session(db_manager, username) -> SessionModel:
    async with db_manager.session() as s:
        return (await s.execute(
            select(SessionModel).join(User).where(User.username == username)
            .order_by(SessionModel.id.desc())
        )).scalars().first()


def days(data) -> float:
    return data["expires_in"] / DAY


async def test_remember_me_lengthens_user_sessions_but_never_admin_sessions(client, session, db_manager, policy):
    await add_account(session, "alice")
    await add_account(session, "root", UserRole.ADMIN)

    plain = await login(client, "alice")
    assert plain["remember_me"] is False and 4.99 < days(plain) <= 5

    remembered = await login(client, "alice", remember_me=True)
    assert remembered["remember_me"] is True and 29.99 < days(remembered) <= 30
    assert (await stored_session(db_manager, "alice")).remember_me is True

    admin = await login(client, "root", remember_me=True)
    assert admin["remember_me"] is False and 4.99 < days(admin) <= 5
    assert (await stored_session(db_manager, "root")).remember_me is False

    me = (await client.get("/api/auth/me", headers=auth(remembered))).json()
    assert me["remember_me"] is True and 29.99 < days(me) <= 30


async def test_lifetime_is_adjustable_and_refresh_follows_it(client, session, db_manager, policy):
    user = await add_account(session, "alice")
    remembered = await login(client, "alice", remember_me=True)

    await session.execute(update(Config).where(Config.key == "session_remember_me_days").values(value="60"))
    await session.commit()
    refreshed = (await client.post("/api/auth/refresh", headers=auth(remembered))).json()
    assert refreshed["remember_me"] is True and 59.99 < days(refreshed) <= 60

    # Promoted to admin: the session keeps working but is no longer remembered
    await session.execute(update(User).where(User.id == user.id).values(role=UserRole.ADMIN))
    await session.commit()
    promoted = (await client.post("/api/auth/refresh", headers=auth(refreshed))).json()
    assert promoted["remember_me"] is False and 4.99 < days(promoted) <= 5


async def test_expired_session_is_rejected(client, session, db_manager, policy):
    await add_account(session, "alice")
    data = await login(client, "alice")
    async with db_manager.session() as s:
        await s.execute(update(SessionModel).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))

    response = await client.get("/api/auth/me", headers=auth(data))
    assert response.status_code == 401


async def test_admin_confirms_password_before_changing_system_settings(client, session, db_manager, policy):
    await add_account(session, "root", UserRole.ADMIN)
    admin = await login(client, "root")
    change = {"configs": {"maintenance_message": "back soon"}}

    # Typing the password at login counts as a confirmation
    assert (await client.post("/api/admin/config/bulk", json=change, headers=auth(admin))).status_code == 200

    # Past the window: refused, nothing changed
    async with db_manager.session() as s:
        await s.execute(update(SessionModel).values(
            reauthenticated_at=datetime.now(timezone.utc) - timedelta(minutes=16)))
    change = {"configs": {"maintenance_message": "changed"}}
    for method, url, body in (
        ("POST", "/api/admin/config/bulk", change),
        ("PUT", "/api/admin/config/maintenance_message", {"value": "changed"}),
        ("POST", "/api/admin/users", {"username": "bob", "password": "password123", "role": "USER"}),
    ):
        refused = await client.request(method, url, json=body, headers=auth(admin))
        assert refused.status_code == 403, (url, refused.text)
        assert refused.json()["error"]["code"] == "reauth_required"
    async with db_manager.session() as s:
        stored = await s.scalar(select(Config.value).where(Config.key == "maintenance_message"))
        assert stored == "back soon"
        assert await s.scalar(select(User).where(User.username == "bob")) is None

    # Reading is not guarded
    assert (await client.get("/api/admin/config", headers=auth(admin))).status_code == 200

    # A wrong password is refused without ending the session
    wrong = await client.post("/api/auth/reauthenticate", json={"password": "nope"}, headers=auth(admin))
    assert wrong.status_code == 403
    assert (await client.get("/api/auth/me", headers=auth(admin))).status_code == 200
    assert (await client.post("/api/admin/config/bulk", json=change, headers=auth(admin))).status_code == 403

    confirmed = await client.post("/api/auth/reauthenticate", json={"password": PASSWORD}, headers=auth(admin))
    assert confirmed.status_code == 200
    assert (await client.post("/api/admin/config/bulk", json=change, headers=auth(admin))).status_code == 200

    async with db_manager.session() as s:
        actions = (await s.execute(
            select(AuditLog.action).where(AuditLog.action.like("reauthenticate%")).order_by(AuditLog.id)
        )).scalars().all()
    assert actions == ["reauthenticate_failed", "reauthenticate"]


async def test_confirmation_window_is_adjustable(client, session, db_manager, policy):
    await add_account(session, "root", UserRole.ADMIN)
    admin = await login(client, "root")
    async with db_manager.session() as s:
        await s.execute(update(SessionModel).values(
            reauthenticated_at=datetime.now(timezone.utc) - timedelta(minutes=16)))
    change = {"configs": {"maintenance_message": "x"}}
    assert (await client.post("/api/admin/config/bulk", json=change, headers=auth(admin))).status_code == 403

    await session.execute(update(Config).where(Config.key == "admin_reauth_minutes").values(value="60"))
    await session.commit()
    assert (await client.post("/api/admin/config/bulk", json=change, headers=auth(admin))).status_code == 200


async def test_device_flow_session_is_remembered_for_users_only(client, session, db_manager, policy):
    for username, role, remembered in (("alice", UserRole.USER, True), ("root", UserRole.ADMIN, False)):
        user = await add_account(session, username, role)
        web = await login(client, username)
        codes = (await client.post("/api/auth/device/request")).json()
        approved = await client.post("/api/auth/device/approve", json={"user_code": codes["user_code"]},
                                     headers=auth(web))
        assert approved.status_code == 200
        device = (await client.post("/api/auth/device/poll", json={"device_code": codes["device_code"]})).json()
        assert device["remember_me"] is remembered, username
        assert (29.99 < days(device) <= 30) if remembered else (4.99 < days(device) <= 5)
        # Approving from the browser is not a password confirmation
        stored = await stored_session(db_manager, username)
        assert stored.reauthenticated_at is None and stored.user_id == user.id

    # ...so the admin's device session must confirm before changing settings
    change = await client.post("/api/admin/config/bulk", json={"configs": {"maintenance_message": "x"}},
                               headers=auth(device))
    assert change.status_code == 403 and change.json()["error"]["code"] == "reauth_required"
