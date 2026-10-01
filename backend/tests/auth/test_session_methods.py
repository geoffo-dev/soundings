"""Sessions by sign-in method (contract-phase2 sections 1, 3.8 and 3.9): every method's
sessions work only while it is available, break-glass sessions are short, the ID token
is kept only when small, and secure cookies use the ``__Host-`` names."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.base import utcnow
from app.models.enums import AuthMethod
from app.models.user import User, UserSession
from app.services import sessions
from tests.conftest import make_settings
from tests.factories import make_user

ME = "/api/v1/auth/me"
ISSUER = "https://idp.example.com/realms/acme"
SSO_ON = {"oidc_issuer": ISSUER}
BREAK_GLASS_ON = {
    "break_glass_enabled": True,
    "break_glass_username": "admin",
    "break_glass_password": "correct horse battery staple",
}


async def start(
    db: AsyncSession,
    user: User,
    settings: Settings,
    method: AuthMethod,
    *,
    id_token: str | None = None,
) -> tuple[str, UserSession]:
    started = await sessions.start_session(
        db, user, settings=settings, auth_method=method, id_token=id_token
    )
    await db.commit()
    return started.token, started.row


async def me(client: httpx.AsyncClient, token: str, name: str = "soundings_session") -> int:
    response = await client.get(ME, headers={"Cookie": f"{name}={token}"})
    return response.status_code


async def age(db: AsyncSession, row: UserSession, **changes: object) -> None:
    await db.execute(update(UserSession).where(UserSession.id == row.id).values(**changes))
    await db.commit()


# --- Each method needs to be available --------------------------------------------------------
@pytest.mark.parametrize(
    ("method", "available", "unavailable"),
    [
        (AuthMethod.DEV_LOGIN, {"dev_login_enabled": True}, {"dev_login_enabled": False}),
        (AuthMethod.SSO, SSO_ON, {"oidc_issuer": None}),
        (AuthMethod.BREAK_GLASS, BREAK_GLASS_ON, {**BREAK_GLASS_ON, **SSO_ON}),
        (AuthMethod.BREAK_GLASS, BREAK_GLASS_ON, {**BREAK_GLASS_ON, "break_glass_enabled": False}),
    ],
)
async def test_sessions_follow_their_methods_availability(
    database_url: str,
    db_session: AsyncSession,
    settings: Settings,
    method: AuthMethod,
    available: dict[str, object],
    unavailable: dict[str, object],
) -> None:
    from app.main import create_app

    user = await make_user(db_session, "Ada")
    token, _ = await start(db_session, user, settings, method)

    async def status_with(overrides: dict[str, object]) -> int:
        app = create_app(type(settings)(**{**settings.model_dump(), **overrides}))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                return await me(c, token)

    assert await status_with(available) == 200
    assert await status_with(unavailable) == 401


# Break-glass and SSO are never available together: break-glass has its own test below.
@pytest.mark.parametrize("method", [AuthMethod.SSO, AuthMethod.DEV_LOGIN])
@pytest.mark.settings(**SSO_ON, dev_login_enabled=True)
async def test_me_says_how_you_signed_in(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings, method: AuthMethod
) -> None:
    user = await make_user(db_session, "Ada")
    token, _ = await start(db_session, user, settings, method)

    response = await client.get(ME, headers={"Cookie": f"soundings_session={token}"})

    assert response.status_code == 200
    assert response.json()["auth_method"] == method.value


@pytest.mark.settings(**BREAK_GLASS_ON)
async def test_me_in_a_break_glass_session(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db_session, "Break-glass admin", platform_admin=True)
    token, _ = await start(db_session, user, settings, AuthMethod.BREAK_GLASS)

    response = await client.get(ME, headers={"Cookie": f"soundings_session={token}"})

    assert response.json()["auth_method"] == "break_glass"


# --- Break-glass sessions are short (8 hours, 1 hour idle) ------------------------------------
@pytest.mark.settings(**BREAK_GLASS_ON)
async def test_break_glass_sessions_last_at_most_eight_hours(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db_session, platform_admin=True)
    token, row = await start(db_session, user, settings, AuthMethod.BREAK_GLASS)

    assert row.expires_at - row.created_at == timedelta(hours=8)
    await age(db_session, row, created_at=utcnow() - timedelta(hours=8, seconds=1))
    assert await me(client, token) == 401


@pytest.mark.settings(**BREAK_GLASS_ON)
async def test_break_glass_sessions_end_after_an_idle_hour(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db_session, platform_admin=True)
    token, row = await start(db_session, user, settings, AuthMethod.BREAK_GLASS)

    await age(db_session, row, last_seen_at=utcnow() - timedelta(minutes=59))
    assert await me(client, token) == 200
    await age(db_session, row, last_seen_at=utcnow() - timedelta(hours=1, seconds=1))
    assert await me(client, token) == 401


@pytest.mark.settings(**BREAK_GLASS_ON, session_idle_timeout=timedelta(minutes=20))
async def test_the_shorter_idle_limit_applies(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db_session, platform_admin=True)
    token, row = await start(db_session, user, settings, AuthMethod.BREAK_GLASS)

    await age(db_session, row, last_seen_at=utcnow() - timedelta(minutes=21))

    assert await me(client, token) == 401


@pytest.mark.settings(dev_login_enabled=True)
async def test_other_sessions_keep_the_configured_limits(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db_session)
    token, row = await start(db_session, user, settings, AuthMethod.DEV_LOGIN)

    await age(db_session, row, last_seen_at=utcnow() - timedelta(hours=11))

    assert row.expires_at - row.created_at == timedelta(hours=24)
    assert await me(client, token) == 200


@pytest.mark.parametrize("method", [AuthMethod.SSO, AuthMethod.DEV_LOGIN])
def test_sessions_last_at_most_a_day_by_default(method: AuthMethod) -> None:
    """The absolute lifetime defaults to 24 hours for every sign-in method (idle 12 h);
    break-glass keeps its own shorter limits."""
    defaults = make_settings()

    assert sessions.session_limits(defaults, method) == (timedelta(hours=24), timedelta(hours=12))
    assert sessions.session_limits(defaults, AuthMethod.BREAK_GLASS) == (
        sessions.BREAK_GLASS_MAX_AGE,
        sessions.BREAK_GLASS_IDLE_TIMEOUT,
    )


# --- The ID token -----------------------------------------------------------------------------
@pytest.mark.settings(**SSO_ON)
@pytest.mark.parametrize(("length", "kept"), [(3072, True), (3073, False)])
async def test_id_token_is_kept_only_up_to_3072_characters(
    db_session: AsyncSession, settings: Settings, length: int, kept: bool
) -> None:
    user = await make_user(db_session)
    _, row = await start(db_session, user, settings, AuthMethod.SSO, id_token="x" * length)

    assert (row.id_token is not None) is kept
    assert row.auth_method == "sso"


async def test_id_token_is_only_for_sso_sessions(
    db_session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db_session)
    _, row = await start(db_session, user, settings, AuthMethod.DEV_LOGIN, id_token="x.y.z")

    assert row.id_token is None


# --- Ending sessions ----------------------------------------------------------------------------
@pytest.mark.settings(**SSO_ON, dev_login_enabled=True)
async def test_end_user_sessions_by_method(db_session: AsyncSession, settings: Settings) -> None:
    ada = await make_user(db_session)
    bob = await make_user(db_session)
    await start(db_session, ada, settings, AuthMethod.SSO)
    await start(db_session, ada, settings, AuthMethod.SSO)
    await start(db_session, ada, settings, AuthMethod.DEV_LOGIN)
    await start(db_session, bob, settings, AuthMethod.SSO)

    sso = await sessions.end_user_sessions(db_session, ada.id, auth_method=AuthMethod.SSO)
    rest = await sessions.end_user_sessions(db_session, ada.id)
    await db_session.commit()

    assert (sso, rest) == (2, 1)
    assert await sessions.end_user_sessions(db_session, bob.id) == 1


# --- Cookie names ---------------------------------------------------------------------------
async def test_plain_http_ignores_the_host_prefixed_cookie(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db_session)
    token, _ = await start(db_session, user, settings, AuthMethod.DEV_LOGIN)

    assert await me(client, token, "__Host-soundings_session") == 401
    assert await me(client, token, "soundings_session") == 200


async def test_https_reads_only_the_host_prefixed_cookie(
    app: FastAPI, db_session: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db_session)
    token, _ = await start(db_session, user, settings, AuthMethod.DEV_LOGIN)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as https:
        tossed = await me(https, token, "soundings_session")
        own = await me(https, token, "__Host-soundings_session")

    assert (tossed, own) == (401, 200)


@pytest.mark.settings(cookie_secure=True)
async def test_logout_clears_the_secure_cookies(
    login_secure: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    response = await login_secure.post("/api/v1/auth/logout")

    cleared = response.headers.get_list("set-cookie")
    assert any(header.startswith("__Host-soundings_session=") for header in cleared)
    assert any(header.startswith("__Host-soundings_csrf=") for header in cleared)
    assert all("Max-Age=0" in header for header in cleared)


@pytest.fixture
async def login_secure(client: httpx.AsyncClient, db_session: AsyncSession) -> httpx.AsyncClient:
    user = await make_user(db_session)
    response = await client.post("/api/v1/auth/dev/login", json={"user_id": str(user.id)})
    assert response.status_code == 200
    # httpx doesn't resend Secure cookies over http: send them by hand.
    token = response.cookies["__Host-soundings_session"]
    client.headers["Cookie"] = f"__Host-soundings_session={token}"
    return client


# --- Dev login never signs in the break-glass account -------------------------------------
async def test_dev_login_refuses_the_break_glass_account(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    account = await make_user(db_session, "Break-glass admin", platform_admin=True)
    account.is_break_glass = True
    await db_session.commit()

    response = await client.post("/api/v1/auth/dev/login", json={"user_id": str(account.id)})

    assert response.status_code == 422
    assert response.json()["code"] == "user_not_found"
