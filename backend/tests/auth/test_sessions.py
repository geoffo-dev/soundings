"""Sessions and the dev login (contract "Auth", ADR 0005): cookies, CSRF, rotation,
expiry, sign-out, and what the database keeps."""

from __future__ import annotations

from datetime import timedelta
from http.cookies import SimpleCookie
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import hash_token
from app.auth.user_agent import summarise_user_agent
from app.models.activity import AuditLog
from app.models.base import utcnow
from app.models.enums import ProjectRole
from app.models.user import User, UserSession
from tests.conftest import Login
from tests.factories import make_project, make_user

LOGIN = "/api/v1/auth/dev/login"


def set_cookies(response: httpx.Response) -> dict[str, SimpleCookie]:
    cookies: dict[str, SimpleCookie] = {}
    for header in response.headers.get_list("set-cookie"):
        cookie: SimpleCookie = SimpleCookie()
        cookie.load(header)
        for name in cookie:
            cookies[name] = cookie
    return cookies


async def sessions_of(db: AsyncSession, user: User) -> list[UserSession]:
    """The user's session rows as the database has them now."""
    statement = (
        select(UserSession)
        .where(UserSession.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    return list(await db.scalars(statement))


# --- Dev login ------------------------------------------------------------------------------
async def test_dev_login_sets_session_and_csrf_cookies(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ada = await make_user(db_session, "Ada Lovelace", platform_admin=True)

    response = await client.post(
        LOGIN,
        json={"user_id": str(ada.id)},
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux) Firefox/130.0"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(ada.id),
        "display_name": "Ada Lovelace",
        "avatar_url": None,
        "initials": "AL",
        "email": ada.email,
        "is_platform_admin": True,
        "auth_method": "dev_login",
    }
    cookies = set_cookies(response)
    session_cookie = cookies["soundings_session"]["soundings_session"]
    csrf_cookie = cookies["soundings_csrf"]["soundings_csrf"]
    assert session_cookie["httponly"] is True
    assert session_cookie["samesite"] == "lax"
    assert session_cookie["path"] == "/"
    assert not session_cookie["secure"]  # plain-http test server outside production
    assert int(session_cookie["max-age"]) == 24 * 3600  # the 24-hour default
    assert not csrf_cookie["httponly"]  # the SPA reads it
    assert csrf_cookie["samesite"] == "lax"
    # Only the token's hash is stored; the CSRF token is bound to the session row.
    [row] = await sessions_of(db_session, ada)
    assert row.token_hash == hash_token(session_cookie.value)
    assert session_cookie.value not in row.token_hash
    assert row.csrf_token == csrf_cookie.value
    assert row.user_agent == "Firefox on Linux"
    assert row.expires_at - row.created_at == timedelta(hours=24)
    assert row.auth_method == "dev_login"
    assert row.id_token is None


@pytest.mark.settings(cookie_secure=True)
async def test_cookies_can_be_forced_secure(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ada = await make_user(db_session)

    response = await client.post(LOGIN, json={"user_id": str(ada.id)})

    # Secure cookies get the __Host- prefix (contract-phase2 section 1): no Domain,
    # Path=/, so a sibling subdomain can't plant or overwrite them.
    cookies = set_cookies(response)
    assert "soundings_session" not in cookies
    session = cookies["__Host-soundings_session"]["__Host-soundings_session"]
    csrf = cookies["__Host-soundings_csrf"]["__Host-soundings_csrf"]
    for cookie in (session, csrf):
        assert cookie["secure"] is True
        assert cookie["path"] == "/"
        assert not cookie["domain"]
    assert session["httponly"] is True
    assert not csrf["httponly"]


async def test_cookies_are_secure_over_https(app: FastAPI, db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as https:
        response = await https.post(LOGIN, json={"user_id": str(ada.id)})

    cookies = set_cookies(response)
    assert cookies["__Host-soundings_session"]["__Host-soundings_session"]["secure"] is True


async def test_get_me(login: Login, client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    bob = await make_user(db_session, "Bob Builder")
    http = await login(bob)

    me = await http.get("/api/v1/auth/me")
    anonymous = await client.get("/api/v1/auth/me")

    assert me.status_code == 200
    assert me.json()["id"] == str(bob.id)
    assert me.json()["is_platform_admin"] is False
    assert anonymous.status_code == 401
    assert anonymous.headers["content-type"] == "application/problem+json"
    assert anonymous.json()["code"] == "unauthorized"


@pytest.mark.parametrize("state", ["unknown", "inactive", "service_account"])
async def test_dev_login_refuses_users_who_cannot_sign_in(
    client: httpx.AsyncClient, db_session: AsyncSession, state: str
) -> None:
    user = await make_user(
        db_session, active=state != "inactive", service_account=state == "service_account"
    )
    user_id = "00000000-0000-4000-8000-000000000000" if state == "unknown" else str(user.id)

    response = await client.post(LOGIN, json={"user_id": user_id})

    assert response.status_code == 422
    assert response.json()["code"] == "user_not_found"
    assert "soundings_session" not in response.cookies


@pytest.mark.settings(dev_login_enabled=False)
@pytest.mark.parametrize(("method", "path"), [("GET", "/api/v1/auth/dev/users"), ("POST", LOGIN)])
async def test_dev_login_is_404_when_disabled(
    client: httpx.AsyncClient, db_session: AsyncSession, method: str, path: str
) -> None:
    ada = await make_user(db_session)

    response = await client.request(method, path, json={"user_id": str(ada.id)})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_list_dev_users(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await make_user(db_session, "Zed Zulu")
    await make_user(db_session, "Amy Admin", platform_admin=True)
    await make_user(db_session, "Bea Bee")
    await make_user(db_session, "Gone Away", active=False)
    await make_user(db_session, "Agent Smith", service_account=True)

    response = await client.get("/api/v1/auth/dev/users")

    assert response.status_code == 200
    assert [user["display_name"] for user in response.json()] == [
        "Amy Admin",
        "Bea Bee",
        "Zed Zulu",
    ]


async def test_sign_in_rotates_the_session(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ada = await make_user(db_session)
    bob = await make_user(db_session)
    await client.post(LOGIN, json={"user_id": str(ada.id)})
    first = client.cookies["soundings_session"]

    await client.post(LOGIN, json={"user_id": str(bob.id)})

    assert client.cookies["soundings_session"] != first
    assert await sessions_of(db_session, ada) == []  # the old session is gone
    assert len(await sessions_of(db_session, bob)) == 1
    client.cookies.clear()
    response = await client.get("/api/v1/auth/me", headers={"Cookie": f"soundings_session={first}"})
    assert response.status_code == 401


# --- CSRF -----------------------------------------------------------------------------------
async def test_unsafe_methods_need_the_csrf_header(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session, platform_admin=True)
    http = await login(admin)
    token = http.headers.pop("X-CSRF-Token")
    body = {"name": "Refunds", "slug": "refunds", "key": "REF"}

    missing = await http.post("/api/v1/projects", json=body)
    wrong = await http.post(
        "/api/v1/projects", json=body, headers={"X-CSRF-Token": token[:-1] + "x"}
    )
    # The cookie alone is not enough: the header must match the session's token.
    cookie_value = await http.post(
        "/api/v1/projects", json=body, headers={"X-CSRF-Token": http.cookies["soundings_session"]}
    )
    ok = await http.post("/api/v1/projects", json=body, headers={"X-CSRF-Token": token})
    safe = await http.get("/api/v1/projects")

    for response in (missing, wrong, cookie_value):
        assert response.status_code == 403
        assert response.json()["code"] == "csrf_failed"
    assert ok.status_code == 201
    assert safe.status_code == 200


async def test_csrf_is_checked_after_authentication(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/projects", json={})

    assert response.status_code == 401  # no session: 401 before 403 csrf_failed and 422


async def test_csrf_failure_comes_before_body_validation(
    login: Login, db_session: AsyncSession
) -> None:
    http = await login(await make_user(db_session, platform_admin=True))

    response = await http.post("/api/v1/projects", json={"slug": "x"}, headers={"X-CSRF-Token": ""})

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"


# --- Expiry and last seen -------------------------------------------------------------------
async def _age_session(db: AsyncSession, user: User, **changes: object) -> None:
    await db.execute(update(UserSession).where(UserSession.user_id == user.id).values(**changes))
    await db.commit()


async def test_idle_sessions_expire(login: Login, db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    http = await login(ada)
    await _age_session(db_session, ada, last_seen_at=utcnow() - timedelta(hours=12, seconds=1))

    response = await http.get("/api/v1/auth/me")

    assert response.status_code == 401


async def test_sessions_expire_at_the_absolute_limit_however_active(
    login: Login, db_session: AsyncSession
) -> None:
    ada = await make_user(db_session)
    http = await login(ada)
    await _age_session(db_session, ada, expires_at=utcnow() - timedelta(seconds=1))

    assert (await http.get("/api/v1/auth/me")).status_code == 401


async def test_activity_slides_the_idle_expiry_at_most_once_a_minute(
    login: Login, db_session: AsyncSession
) -> None:
    ada = await make_user(db_session)
    http = await login(ada)
    [row] = await sessions_of(db_session, ada)
    signed_in_at = row.last_seen_at

    await http.get("/api/v1/auth/me")
    [row] = await sessions_of(db_session, ada)
    assert row.last_seen_at == signed_in_at  # throttled: no write within a minute

    earlier = utcnow() - timedelta(hours=11)
    await _age_session(db_session, ada, last_seen_at=earlier)
    assert (await http.get("/api/v1/auth/me")).status_code == 200
    [row] = await sessions_of(db_session, ada)
    user = await db_session.get(User, ada.id, populate_existing=True)
    assert user is not None
    assert row.last_seen_at > earlier + timedelta(hours=10)  # slid forward
    assert user.last_seen_at == row.last_seen_at


async def test_the_keep_alive_is_its_own_short_transaction(
    login: Login, db_session: AsyncSession, app: FastAPI
) -> None:
    """Performance review B8: the throttled ``last_seen_at`` write runs after the
    response in a transaction of its own (guarded by the one-minute throttle), so a
    screen's parallel requests don't queue on the user's row lock until each commits.
    So it also survives a request that fails and rolls back."""
    ada = await make_user(db_session)
    http = await login(ada)
    earlier = utcnow() - timedelta(hours=2)
    await _age_session(db_session, ada, last_seen_at=earlier)
    await db_session.execute(update(User).where(User.id == ada.id).values(last_seen_at=earlier))
    await db_session.commit()
    statements: list[str] = []

    def record(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    engine = app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        missing = await http.get(f"/api/v1/ideas/{uuid4()}")  # 404: the request rolls back
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert missing.status_code == 404
    [row] = await sessions_of(db_session, ada)
    user = await db_session.get(User, ada.id, populate_existing=True)
    assert user is not None
    assert row.last_seen_at > earlier + timedelta(hours=1)
    assert user.last_seen_at == row.last_seen_at
    touches = [s for s in statements if s.lstrip().upper().startswith("UPDATE")]
    assert len(touches) == 2
    assert all("last_seen_at <=" in s or "last_seen_at IS NULL" in s for s in touches)


async def test_parallel_requests_touch_the_session_once(
    login: Login, db_session: AsyncSession, app: FastAPI
) -> None:
    ada = await make_user(db_session)
    http = await login(ada)
    earlier = utcnow() - timedelta(hours=2)
    await _age_session(db_session, ada, last_seen_at=earlier)
    from app.services.sessions import touch_session

    [row] = await sessions_of(db_session, ada)
    now = utcnow()
    first = await touch_session(app.state.sessionmaker, row.id, ada.id, now=now)
    second = await touch_session(
        app.state.sessionmaker, row.id, ada.id, now=now + timedelta(seconds=5)
    )

    assert (first, second) == (True, False)  # the guard: at most once a minute
    [row] = await sessions_of(db_session, ada)
    assert row.last_seen_at == now
    assert (await http.get("/api/v1/auth/me")).status_code == 200


async def test_deactivated_users_are_signed_out(login: Login, db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    http = await login(ada)
    await db_session.execute(update(User).where(User.id == ada.id).values(is_active=False))
    await db_session.commit()

    assert (await http.get("/api/v1/auth/me")).status_code == 401


async def test_expired_sessions_are_cleaned_up_at_the_next_sign_in(
    client: httpx.AsyncClient, login: Login, db_session: AsyncSession
) -> None:
    ada = await make_user(db_session)
    await login(ada)
    await _age_session(db_session, ada, expires_at=utcnow() - timedelta(seconds=1))

    await login(ada)

    assert len(await sessions_of(db_session, ada)) == 1


# --- Sign out -------------------------------------------------------------------------------
async def test_logout_ends_the_session_and_clears_cookies(
    login: Login, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ada = await make_user(db_session)
    http = await login(ada)
    token = http.cookies["soundings_session"]

    response = await http.post("/api/v1/auth/logout")

    assert response.status_code == 204
    cookies = set_cookies(response)
    assert cookies["soundings_session"]["soundings_session"].value == ""
    assert cookies["soundings_csrf"]["soundings_csrf"]["max-age"] == "0"
    assert await sessions_of(db_session, ada) == []
    replay = await client.get("/api/v1/auth/me", headers={"Cookie": f"soundings_session={token}"})
    assert replay.status_code == 401


async def test_logout_without_a_session_is_204(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    garbage = await client.post("/api/v1/auth/logout", headers={"Cookie": "soundings_session=x"})
    assert garbage.status_code == 204


async def test_sign_in_and_out_are_audited_without_personal_data(
    login: Login, db_session: AsyncSession
) -> None:
    ada = await make_user(db_session, "Ada Lovelace")
    http = await login(ada)
    token = http.cookies["soundings_session"]
    await http.post("/api/v1/auth/logout")

    entries = list(
        await db_session.scalars(select(AuditLog).order_by(AuditLog.created_at, AuditLog.action))
    )

    assert [(entry.action, entry.actor_id, entry.target_id) for entry in entries] == [
        ("session.sign_in", ada.id, ada.id),
        ("session.sign_out", ada.id, ada.id),
    ]
    rendered = str([entry.details for entry in entries])
    assert "Ada" not in rendered
    assert ada.email not in rendered
    assert token not in rendered
    assert hash_token(token) not in rendered


async def test_a_session_survives_membership_changes(
    login: Login, db_session: AsyncSession
) -> None:
    """Roles are read live on every request; the session only says who you are."""
    ada = await make_user(db_session)
    project = await make_project(db_session, members={ada: ProjectRole.MEMBER})
    http = await login(ada)

    assert (await http.get(f"/api/v1/projects/{project.slug}")).status_code == 200
    await db_session.execute(update(User).where(User.id == ada.id).values(display_name="Ada L."))
    await db_session.commit()
    me = await http.get("/api/v1/auth/me")
    assert me.json()["display_name"] == "Ada L."
    assert await db_session.scalar(select(func.count()).select_from(UserSession)) == 1


@pytest.mark.parametrize(
    ("header", "summary"),
    [
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit Version/17.5 Safari/605.1",
            "Safari on macOS",
        ),
        ("Mozilla/5.0 (Windows NT 10.0) Chrome/128.0 Safari/537.36 Edg/128.0", "Edge on Windows"),
        ("Mozilla/5.0 (Linux; Android 14) Chrome/128.0 Mobile Safari/537.36", "Chrome on Android"),
        ("curl/8.5.0", "curl"),
        (None, None),
    ],
)
def test_user_agent_summary(header: str | None, summary: str | None) -> None:
    assert summarise_user_agent(header) == summary


async def test_the_hourly_schedule_deletes_expired_sessions(
    login: Login, db_session: AsyncSession, app: FastAPI
) -> None:
    """Security review P7 L5: a leaver's expired session rows (with their user-agent
    summary) no longer wait for that person's next sign-in."""
    from app.notifications.schedule import run_schedule

    ada, bea, cal = [await make_user(db_session) for _ in range(3)]
    for person in (ada, bea, cal):
        await login(person)
    await _age_session(db_session, ada, expires_at=utcnow() - timedelta(seconds=1))
    await _age_session(db_session, bea, last_seen_at=utcnow() - timedelta(hours=13))

    await run_schedule(app.state.sessionmaker, app.state.settings, utcnow())

    assert await sessions_of(db_session, ada) == []
    assert await sessions_of(db_session, bea) == []
    assert len(await sessions_of(db_session, cal)) == 1
