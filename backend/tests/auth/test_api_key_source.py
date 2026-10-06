"""Authenticating with an API key (contract-phase5 sections 3.2 and 3.8
"Authentication"): every refusal is the same 401, keys come before cookies and need no
CSRF token, the throttles, ``last_used_at``, and owner changes taking effect on the
very next request."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.key_auth import (
    KEY_FAILURE_THROTTLE,
    KEY_REQUEST_THROTTLE,
    KEY_WRITE_THROTTLE,
    bearer_token,
)
from app.auth.throttle import Throttle, get_throttle
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.enums import AuthMethod, ProjectRole
from app.models.project import ProjectMember
from app.models.user import User
from app.schemas.api_keys import (
    API_KEY_FAILURES_PER_MINUTE,
    API_KEY_REQUESTS_PER_MINUTE,
    API_KEY_WRITES_PER_MINUTE,
)
from tests.api_keys.helpers import (
    API,
    World,
    key_client,
    key_row,
    make_key,
    mark_seen,
    problem,
)
from tests.conftest import Login
from tests.factories import make_idea
from tests.mcp.conftest import headers, rpc

ME = f"{API}/auth/me"
UNAUTHORIZED_DETAIL = (
    "The API key is missing, invalid, expired or revoked, or its owner needs to sign in "
    "to Soundings again."
)


def refused(response: httpx.Response) -> None:
    """The one 401 every refused key gets, whatever the reason."""
    body = problem(response, 401, "unauthorized")
    assert body["detail"] == UNAUTHORIZED_DETAIL
    assert response.headers["www-authenticate"] == 'Bearer realm="soundings"'


async def me(app: FastAPI, key: str, **headers: str) -> httpx.Response:
    async with key_client(app, key, **headers) as http:
        return await http.get(ME)


@pytest.fixture
def statements(app: FastAPI) -> Iterator[list[str]]:
    """SQL statements the app runs while the test does."""
    seen: list[str] = []

    def record(*args: Any) -> None:
        seen.append(str(args[2]))

    engine = app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    yield seen
    event.remove(engine, "before_cursor_execute", record)


# --- The header -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("header", "token"),
    [
        (None, None),
        ("", None),
        ("Basic dXNlcjpwYXNz", None),
        ("Bearer abc", "abc"),
        ("bearer abc", "abc"),
        ("BEARER   abc  ", "abc"),
        ("Bearer", ""),
        ("Bearer ", ""),
        ("Token abc", None),
    ],
)
def test_bearer_token(header: str | None, token: str | None) -> None:
    assert bearer_token(header) == token


# --- Accepted -------------------------------------------------------------------------------
async def test_a_valid_key_acts_as_its_owner(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol, scopes=["read"])

    response = await me(app, key)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(world.carol.id)


async def test_a_service_accounts_key_works_without_ever_signing_in(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    """Phase 6 (c22): REST refuses an agent's key with 403 ``insufficient_scope`` after
    the key check (not 401: the key itself is good) and ``/mcp`` accepts it."""
    key = await make_key(db_session, world.bot, scopes=["read", "mcp"])
    assert (await db_session.get(User, world.bot.id)).last_seen_at is None  # type: ignore[union-attr]

    rest = await me(app, key)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        mcp = await http.post(
            "/mcp",
            json=rpc("tools/call", {"name": "list_projects", "arguments": {}}),
            headers=headers(key),
        )

    assert (rest.status_code, rest.json()["code"]) == (403, "insufficient_scope")
    assert mcp.status_code == 200, mcp.text
    assert mcp.json()["result"]["isError"] is False


# --- Refused: one answer for every reason ----------------------------------------------------
@pytest.mark.parametrize(
    "token",
    [
        "",
        "sdg_",
        "not-a-key",
        "sdg_Ab12Cd34Ef56_" + "x" * 39,
        "sdg_Ab12Cd34Ef56_" + "x" * 41,
        "sdg_Ab12Cd34Ef5!_" + "x" * 40,
        "sdg_Ab12Cd34Ef56-" + "x" * 40,
        "SDG_Ab12Cd34Ef56_" + "x" * 40,
    ],
)
async def test_malformed_keys_are_refused_without_a_query(
    app: FastAPI, world: World, statements: list[str], token: str
) -> None:
    async with key_client(app) as http:
        response = await http.get(ME, headers={"Authorization": f"Bearer {token}"})

    refused(response)
    assert statements == []


async def test_unknown_and_wrong_keys_are_refused(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol)
    unknown = "sdg_" + "Z" * 12 + key[16:]
    wrong_secret = key[:-1] + ("a" if key[-1] != "a" else "b")

    refused(await me(app, unknown))
    refused(await me(app, wrong_secret))
    assert (await me(app, key)).status_code == 200


async def test_revoked_and_expired_keys_are_refused_on_the_next_request(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    revoked = await make_key(db_session, world.carol, name="Revoked")
    expired = await make_key(db_session, world.carol, name="Expired")
    assert (await me(app, revoked)).status_code == 200
    assert (await me(app, expired)).status_code == 200

    await db_session.execute(
        update(ApiKey).where(ApiKey.lookup_id == revoked[4:16]).values(revoked_at=utcnow())
    )
    await db_session.execute(
        update(ApiKey)
        .where(ApiKey.lookup_id == expired[4:16])
        .values(expires_at=utcnow() - timedelta(seconds=1))
    )
    await db_session.commit()

    refused(await me(app, revoked))
    refused(await me(app, expired))


async def test_revoking_through_the_api_cuts_access_at_once(
    app: FastAPI, login: Login, world: World
) -> None:
    session = await login(world.carol)
    created = await session.post(f"{API}/me/api-keys", json={"name": "Script", "scopes": ["read"]})
    key = created.json()["secret"]
    assert (await me(app, key)).status_code == 200

    assert (
        await session.delete(f"{API}/me/api-keys/{created.json()['key']['id']}")
    ).status_code == 204

    refused(await me(app, key))


async def test_keys_of_inactive_and_break_glass_owners_are_refused(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    inactive = await make_key(db_session, world.carol)
    glass = await make_key(db_session, world.lead)
    await db_session.execute(update(User).where(User.id == world.carol.id).values(is_active=False))
    await db_session.execute(
        update(User).where(User.id == world.lead.id).values(is_break_glass=True)
    )
    await db_session.commit()

    refused(await me(app, inactive))
    refused(await me(app, glass))


@pytest.mark.settings(dev_login_enabled=False)
async def test_a_dev_login_key_stops_when_dev_login_is_off(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol, method=AuthMethod.DEV_LOGIN)
    sso = await make_key(db_session, world.lead, method=AuthMethod.SSO)
    glass = await make_key(db_session, world.platform, method=AuthMethod.BREAK_GLASS)

    refused(await me(app, key))
    refused(await me(app, sso))  # SSO isn't configured either
    refused(await me(app, glass))  # nor break-glass


async def test_an_sso_key_stops_while_sso_is_not_configured(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol, method=AuthMethod.SSO)

    refused(await me(app, key))


async def test_a_persons_key_pauses_after_30_days_without_signing_in(
    app: FastAPI, login: Login, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol)
    never = await make_key(db_session, world.lead, seen=False)  # last_seen_at null
    await mark_seen(db_session, world.carol, utcnow() - timedelta(days=30, minutes=-1))
    assert (await me(app, key)).status_code == 200  # 30 days less a minute: still fine

    await mark_seen(db_session, world.carol, utcnow() - timedelta(days=30, seconds=1))
    refused(await me(app, key))
    refused(await me(app, never))

    await login(world.carol)  # signing in reactivates it
    assert (await me(app, key)).status_code == 200


async def test_key_use_does_not_count_as_using_the_app(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol, seen=False)
    seen = utcnow() - timedelta(days=3)
    await mark_seen(db_session, world.carol, seen)

    assert (await me(app, key)).status_code == 200

    user = await db_session.scalar(
        select(User).where(User.id == world.carol.id).execution_options(populate_existing=True)
    )
    assert user is not None
    assert user.last_seen_at == seen


# --- Keys and cookies -------------------------------------------------------------------------
async def test_basic_authorization_falls_through_to_the_session(login: Login, world: World) -> None:
    http = await login(world.carol)

    response = await http.get(ME, headers={"Authorization": "Basic dXNlcjpwYXNz"})

    assert response.status_code == 200
    assert response.json()["id"] == str(world.carol.id)


async def test_a_key_decides_over_a_session_cookie(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    http = await login(world.carol)
    lead_key = await make_key(db_session, world.lead, scopes=["read"])
    revoked = await make_key(db_session, world.carol, name="Gone")
    await db_session.execute(
        update(ApiKey).where(ApiKey.lookup_id == revoked[4:16]).values(revoked_at=utcnow())
    )
    await db_session.commit()

    as_lead = await http.get(ME, headers={"Authorization": f"Bearer {lead_key}"})
    bad = await http.get(ME, headers={"Authorization": f"Bearer {revoked}"})
    garbage = await http.get(ME, headers={"Authorization": "Bearer nonsense"})

    assert as_lead.json()["id"] == str(world.lead.id)
    refused(bad)  # never falls back to the valid cookie
    refused(garbage)


async def test_no_csrf_token_with_a_key_but_still_with_a_cookie(
    app: FastAPI, login: Login, world: World, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, world.cust, submitted_by=world.carol)
    key = await make_key(db_session, world.carol, scopes=["write"])
    session = await login(world.carol)
    del session.headers["X-CSRF-Token"]

    async with key_client(app, key) as http:
        with_key = await http.post(f"{API}/ideas/{idea.id}/comments", json={"body_md": "Hi"})
    with_cookie = await session.post(f"{API}/ideas/{idea.id}/comments", json={"body_md": "Hi"})

    assert with_key.status_code == 201, with_key.text
    problem(with_cookie, 403, "csrf_failed")


# --- Throttles ----------------------------------------------------------------------------------
async def test_failing_keys_from_one_address_are_throttled_but_valid_keys_still_work(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol)
    wrong = key[:-1] + ("a" if key[-1] != "a" else "b")

    for _ in range(API_KEY_FAILURES_PER_MINUTE):
        refused(await me(app, wrong))
    throttled = await me(app, wrong)
    malformed = await me(app, "nonsense")
    valid = await me(app, key)

    problem(throttled, 429, "too_many_attempts")
    assert 1 <= int(throttled.headers["retry-after"]) <= 60
    problem(malformed, 429, "too_many_attempts")
    assert valid.status_code == 200


async def test_failures_are_counted_per_address(app: FastAPI, world: World) -> None:
    throttle = get_throttle(app, KEY_FAILURE_THROTTLE)
    for _ in range(API_KEY_FAILURES_PER_MINUTE):
        throttle.hit("192.0.2.1")  # someone else's address

    refused(await me(app, "nonsense"))  # the test client isn't throttled


async def test_each_key_has_a_request_rate(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol, scopes=["read"])
    other = await make_key(db_session, world.carol, scopes=["read"], name="Other")
    key_id = str((await key_row(db_session, key)).id)
    throttle = get_throttle(app, KEY_REQUEST_THROTTLE)
    for _ in range(API_KEY_REQUESTS_PER_MINUTE - 1):
        throttle.hit(key_id)

    last = await me(app, key)  # the 300th
    over = await me(app, key)  # the 301st

    assert last.status_code == 200
    problem(over, 429, "too_many_attempts")
    assert int(over.headers["retry-after"]) >= 1
    assert (await me(app, other)).status_code == 200  # per key


async def test_requests_are_counted(app: FastAPI, world: World, db_session: AsyncSession) -> None:
    key = await make_key(db_session, world.carol, scopes=["read"])
    get_throttle(app, KEY_REQUEST_THROTTLE)  # creates the app's throttles
    app.state.throttles[KEY_REQUEST_THROTTLE[0]] = Throttle(3, 60.0)

    statuses = [(await me(app, key)).status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]


async def test_each_key_has_a_write_cap_but_reads_still_work(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, world.cust, submitted_by=world.carol)
    key = await make_key(db_session, world.carol, scopes=["write"])

    async with key_client(app, key) as http:
        writes = [
            (await http.put(f"{API}/ideas/{idea.id}/watch")).status_code
            for _ in range(API_KEY_WRITES_PER_MINUTE + 1)
        ]
        read = await http.get(f"{API}/ideas/{idea.id}")

    assert writes[:-1] == [200] * API_KEY_WRITES_PER_MINUTE
    assert writes[-1] == 429
    assert read.status_code == 200
    assert get_throttle(app, KEY_WRITE_THROTTLE).retry_after(
        str((await key_row(db_session, key)).id)
    )


# --- last_used_at ---------------------------------------------------------------------------------
async def test_last_used_moves_at_most_once_a_minute(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol)
    assert (await key_row(db_session, key)).last_used_at is None

    await me(app, key)
    first = (await key_row(db_session, key)).last_used_at
    await me(app, key)
    second = (await key_row(db_session, key)).last_used_at
    old = utcnow() - timedelta(minutes=2)
    await db_session.execute(
        update(ApiKey).where(ApiKey.lookup_id == key[4:16]).values(last_used_at=old)
    )
    await db_session.commit()
    await me(app, key)
    third = (await key_row(db_session, key)).last_used_at

    assert first is not None
    assert second == first
    assert third is not None
    assert third > old + timedelta(minutes=1)


async def test_last_used_is_saved_even_when_the_request_fails(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    """Its own transaction: a request that rolls back still records the use."""
    key = await make_key(db_session, world.carol, scopes=["read"])

    async with key_client(app, key) as http:
        response = await http.get(f"{API}/ideas/NOPE-1")

    assert response.status_code == 404
    assert (await key_row(db_session, key)).last_used_at is not None


async def test_refused_keys_are_not_marked_used(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol)
    await db_session.execute(
        update(ApiKey).where(ApiKey.lookup_id == key[4:16]).values(revoked_at=utcnow())
    )
    await db_session.commit()

    refused(await me(app, key))

    assert (await key_row(db_session, key)).last_used_at is None


# --- The owner, live ---------------------------------------------------------------------------
async def test_a_demoted_owner_loses_the_right_on_the_next_request(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol, scopes=["write"])
    slug = world.cust.slug
    body = {"title": "Faster refunds", "summary": "Refund without a call."}

    async with key_client(app, key) as http:
        allowed = await http.post(f"{API}/projects/{slug}/ideas", json=body)
        await db_session.execute(
            update(ProjectMember)
            .where(
                ProjectMember.project_id == world.cust.id, ProjectMember.user_id == world.carol.id
            )
            .values(role=ProjectRole.VIEWER)
        )
        await db_session.commit()
        demoted = await http.post(f"{API}/projects/{slug}/ideas", json=body)
        await db_session.execute(
            update(ProjectMember)
            .where(
                ProjectMember.project_id == world.cust.id, ProjectMember.user_id == world.carol.id
            )
            .values(role=ProjectRole.MEMBER)
        )
        await db_session.commit()
        promoted = await http.post(f"{API}/projects/{slug}/ideas", json=body)

    assert allowed.status_code == 201, allowed.text
    problem(demoted, 403, "forbidden")
    assert promoted.status_code == 201, promoted.text


async def test_a_platform_admins_key_follows_the_flag(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.platform, scopes=["read"])
    path = f"{API}/projects/{world.secret.slug}"

    async with key_client(app, key) as http:
        admin = await http.get(path)
        await db_session.execute(
            update(User).where(User.id == world.platform.id).values(is_platform_admin=False)
        )
        await db_session.commit()
        plain = await http.get(path)

    assert admin.status_code == 200
    problem(plain, 404, "not_found")
