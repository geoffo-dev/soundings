"""The break-glass admin (contract-phase2 section 3.8): availability, the constant-time
credential check, the per-client throttle, the account, and the audit trail."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.break_glass import credentials_match
from app.auth.throttle import Throttle, client_key
from app.config import Settings
from app.models.user import BREAK_GLASS_EMAIL, User, UserSession
from tests.conftest import make_settings
from tests.identity.helpers import audit_entries

URL = "/api/v1/auth/break-glass"
USERNAME = "emergency-admin"
PASSWORD = "correct horse battery staple"
GOOD = {"username": USERNAME, "password": PASSWORD}


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {
        "break_glass_enabled": True,
        "break_glass_username": USERNAME,
        "break_glass_password": PASSWORD,
        "dev_login_enabled": False,
    }


async def account(db: AsyncSession) -> User | None:
    return await db.scalar(
        select(User).where(User.is_break_glass.is_(True)).execution_options(populate_existing=True)
    )


# --- Availability ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "overrides",
    [
        {"break_glass_enabled": False},
        {"break_glass_password": None},
        {"break_glass_username": ""},
        {"oidc_issuer": "https://idp.example.com/realms/acme"},  # off once SSO is configured
    ],
)
async def test_unavailable_is_404(
    database_url: str, settings: Settings, overrides: dict[str, Any]
) -> None:
    from app.main import create_app

    app = create_app(make_settings(**{**settings.model_dump(), **overrides}))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(URL, json=GOOD)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --- Signing in -------------------------------------------------------------------------------
async def test_first_sign_in_creates_the_account(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post(URL, json=GOOD)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == BREAK_GLASS_EMAIL
    assert body["display_name"] == "Break-glass admin"
    assert body["is_platform_admin"] is True
    assert body["auth_method"] == "break_glass"
    created = await account(db_session)
    assert created is not None
    assert (created.is_active, created.is_platform_admin, created.is_break_glass) == (True,) * 3
    [session] = list(await db_session.scalars(select(UserSession)))
    assert session.auth_method == "break_glass"
    assert session.user_id == created.id
    cookie = response.headers.get_list("set-cookie")
    assert any(h.startswith("soundings_session=") and "Max-Age=28800" in h for h in cookie)
    me = await client.get("/api/v1/auth/me")
    assert me.json()["auth_method"] == "break_glass"
    actions = [(e.action, e.details) for e in await audit_entries(db_session)]
    assert actions == [
        (
            "user.create",
            {
                "source": "break_glass",
                "is_platform_admin": True,
                "external_id_kinds": [],
                "auth_method": "break_glass",
            },
        ),
        (
            "session.sign_in",
            {"method": "break_glass", "session_id": str(session.id), "auth_method": "break_glass"},
        ),
    ]


async def test_later_sign_ins_reuse_the_account_and_restore_admin(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await client.post(URL, json=GOOD)
    first = await account(db_session)
    assert first is not None
    first.is_platform_admin = False
    await db_session.commit()

    response = await client.post(URL, json=GOOD)

    assert response.status_code == 200
    again = await account(db_session)
    assert again is not None
    assert again.id == first.id
    assert again.is_platform_admin is True
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    assert len(await audit_entries(db_session, "user.create")) == 1


async def test_a_deactivated_account_is_refused(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await client.post(URL, json=GOOD)
    disabled = await account(db_session)
    assert disabled is not None
    disabled.is_active = False
    await db_session.commit()
    client.cookies.clear()

    response = await client.post(URL, json=GOOD)

    assert response.status_code == 403
    assert response.json()["code"] == "account_disabled"
    assert "set-cookie" not in response.headers
    [denied] = await audit_entries(db_session, "session.sign_in_denied")
    assert denied.actor_id is None
    assert (denied.target_type, denied.target_id) == ("user", disabled.id)
    assert denied.details == {"method": "break_glass", "reason": "account_disabled"}


@pytest.mark.parametrize(
    "body",
    [
        {"username": USERNAME, "password": "wrong"},
        {"username": "wrong", "password": PASSWORD},
        {"username": USERNAME, "password": PASSWORD + " "},  # never trimmed
        {"username": " " + USERNAME, "password": PASSWORD},
        {"username": USERNAME.upper(), "password": PASSWORD},
    ],
)
async def test_wrong_credentials(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    body: dict[str, str],
) -> None:
    caplog.set_level(logging.DEBUG)

    response = await client.post(URL, json=body)

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"
    assert await account(db_session) is None
    [denied] = await audit_entries(db_session, "session.sign_in_denied")
    assert (denied.actor_id, denied.target_type, denied.target_id) == (None, None, None)
    assert denied.details == {"method": "break_glass", "reason": "invalid_credentials"}
    # The submitted username or password is never recorded or logged.
    for value in body.values():
        assert value.strip() not in str(denied.details)
        assert value.strip() not in caplog.text


# --- Throttle ---------------------------------------------------------------------------------
async def test_five_failures_then_429_without_checking_credentials(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    wrong = {"username": USERNAME, "password": "nope"}
    statuses = [(await client.post(URL, json=wrong)).status_code for _ in range(5)]

    locked = await client.post(URL, json=GOOD)  # even the right password
    again = await client.post(URL, json=wrong)

    assert statuses == [401] * 5
    assert locked.status_code == 429
    assert locked.json()["code"] == "too_many_attempts"
    assert 0 < int(locked.headers["retry-after"]) <= 15 * 60
    assert again.status_code == 429
    assert await account(db_session) is None
    reasons = [
        e.details["reason"] for e in await audit_entries(db_session, "session.sign_in_denied")
    ]
    assert reasons == ["invalid_credentials"] * 5 + ["too_many_attempts"]  # one 429 audited


async def test_successful_sign_ins_are_not_throttled(client: httpx.AsyncClient) -> None:
    statuses = [(await client.post(URL, json=GOOD)).status_code for _ in range(8)]

    assert statuses == [200] * 8


async def test_the_throttle_is_per_client(app: FastAPI, db_session: AsyncSession) -> None:
    async def post(client_ip: str, body: dict[str, str]) -> int:
        transport = httpx.ASGITransport(app=app, client=(client_ip, 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            return (await http.post(URL, json=body)).status_code

    wrong = {"username": USERNAME, "password": "nope"}
    for _ in range(5):
        await post("203.0.113.7", wrong)

    assert await post("203.0.113.7", GOOD) == 429
    assert await post("203.0.113.8", GOOD) == 200
    for _ in range(5):
        await post("2001:db8:1:2::10", wrong)
    assert await post("2001:db8:1:2:ffff::1", GOOD) == 429  # the same /64
    assert await post("2001:db8:1:3::1", GOOD) == 200


@pytest.mark.parametrize(
    ("host", "key"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),
        ("::ffff:203.0.113.7", "203.0.113.7"),
        ("testclient", "unknown"),
        ("pwn-123", "unknown"),
    ],
)
def test_client_key(host: str, key: str) -> None:
    class FakeRequest:
        client = type("Client", (), {"host": host})()

    assert client_key(FakeRequest()) == key  # type: ignore[arg-type]


def test_throttle_window_and_retry_after() -> None:
    now = [1000.0]
    throttle = Throttle(2, 60.0, clock=lambda: now[0])

    throttle.hit("a")
    now[0] += 10
    throttle.hit("a")
    blocked = throttle.retry_after("a")
    first, second = throttle.first_refusal("a"), throttle.first_refusal("a")
    now[0] += 50.5  # the first hit leaves the window
    reopened = throttle.retry_after("a")

    assert blocked == pytest.approx(50.0)
    assert (first, second) == (True, False)
    assert reopened is None
    assert throttle.retry_after("b") is None


def test_throttle_memory_is_bounded() -> None:
    throttle = Throttle(5, 60.0, max_keys=100)

    for n in range(1000):
        throttle.hit(f"10.0.{n // 256}.{n % 256}")

    assert len(throttle._hits) <= 100


# --- The credential check -------------------------------------------------------------------
@pytest.mark.parametrize(
    ("username", "password", "expected"),
    [
        (USERNAME, PASSWORD, True),
        (USERNAME, "", False),
        ("", PASSWORD, False),
        (USERNAME, PASSWORD[:-1], False),
        ("ünïcode", "pässwörd", False),
    ],
)
def test_credentials_match(
    settings: Settings, username: str, password: str, expected: bool
) -> None:
    assert credentials_match(settings, username, password) is expected


def test_no_configured_credentials_never_match(settings: Settings) -> None:
    empty = settings.model_copy(update={"break_glass_username": None, "break_glass_password": None})

    assert credentials_match(empty, "", "") is False


# --- Its sessions -----------------------------------------------------------------------------
async def test_break_glass_session_ends_once_sso_is_configured(
    app: FastAPI, client: httpx.AsyncClient, settings: Settings
) -> None:
    await client.post(URL, json=GOOD)
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    app.state.settings = make_settings(
        **{**settings.model_dump(), "oidc_issuer": "https://idp.example.com/realms/acme"}
    )

    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"username": USERNAME},
        {"password": PASSWORD},
        {"username": "", "password": PASSWORD},
        {"username": USERNAME, "password": "x" * 1025},
        {"username": "a\x00b", "password": PASSWORD},
        {"username": USERNAME, "password": PASSWORD, "remember": True},
    ],
)
async def test_malformed_bodies_are_422(
    client: httpx.AsyncClient, db_session: AsyncSession, body: dict[str, Any]
) -> None:
    response = await client.post(URL, json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert await audit_entries(db_session) == []  # nothing counted or audited
