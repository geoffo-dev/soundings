"""Key lifecycle (contract-phase5 sections 2, 3.1, 3.6 and 3.8 "Key lifecycle"): shown
once, stored hashed, ``read`` added to ``write``/``evaluate``, unique names, the 25-key
limit under a lock, project restrictions, c20, revocation, the admin list and revoke,
deactivation, and the audit entries (never a key or a hash)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_keys.service import issue_key, revoke_all_for_user
from app.auth.sources import UnauthorizedProblem
from app.authz import Rule
from app.domain.principal import Principal
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.enums import ApiKeyScope, AuthMethod
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.schemas.api_keys import API_KEY_PATTERN, ApiKeyCreate
from tests.api_keys.helpers import (
    API,
    World,
    audit_rows,
    key_client,
    key_row,
    make_key,
    mark_seen,
    problem,
)
from tests.conftest import Login

KEYS = f"{API}/me/api-keys"
ADMIN_KEYS = f"{API}/admin/api-keys"


async def create(http: httpx.AsyncClient, **body: Any) -> httpx.Response:
    body.setdefault("name", "Claude Desktop")
    body.setdefault("scopes", ["read", "mcp"])
    return await http.post(KEYS, json=body)


def created(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# --- Creating: shown once, stored hashed ----------------------------------------------------
async def test_a_new_key_is_shown_once_and_stored_hashed(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    http = await login(world.carol)

    response = await create(
        http, scopes=["mcp", "evaluate"], project_ids=[str(world.cust.id)], name="Claude Desktop"
    )

    body = created(response)
    assert response.headers["cache-control"] == "no-store"
    secret = body["secret"]
    assert re.fullmatch(API_KEY_PATTERN, secret)
    key = body["key"]
    assert key["prefix"] == secret[:16]
    assert key["scopes"] == ["read", "evaluate", "mcp"]  # read added, canonical order
    assert key["restricted"] is True
    assert [p["slug"] for p in key["projects"]] == ["customer-innovation"]
    assert (key["state"], key["expires_at"], key["last_used_at"]) == ("active", None, None)
    row = await key_row(db_session, secret)
    assert row.secret_hash == hashlib.sha256(secret.encode()).hexdigest()
    assert row.lookup_id == secret[4:16]
    assert row.scopes == ["read", "evaluate", "mcp"]
    assert row.project_ids == [world.cust.id]
    assert row.created_by_id == world.carol.id
    assert row.created_auth_method is AuthMethod.DEV_LOGIN

    listed = (await http.get(KEYS)).json()
    assert [item["prefix"] for item in listed["items"]] == [key["prefix"]]
    assert "secret" not in listed["items"][0]
    for shown in (json.dumps(listed), (await http.get(f"{API}/auth/me")).text):
        assert secret not in shown
        assert secret[17:] not in shown
        assert row.secret_hash not in shown


async def test_creation_is_audited_without_the_key(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    http = await login(world.carol)
    expires = (utcnow() + timedelta(days=30)).isoformat()

    body = created(
        await create(http, scopes=["write"], project_ids=[str(world.tools.id)], expires_at=expires)
    )

    [entry] = await audit_rows(db_session, "api_key.create")
    row = await key_row(db_session, body["secret"])
    assert entry.actor_id == world.carol.id
    assert (entry.target_type, entry.target_id) == ("user", world.carol.id)
    details = dict(entry.details)
    assert details.pop("expires_at").startswith(row.expires_at.isoformat()[:19])  # type: ignore[union-attr]
    assert details == {
        "rule": "api_key.manage_own",
        "key_id": str(row.id),
        "prefix": body["key"]["prefix"],
        "scopes": ["read", "write"],
        "restricted": True,
        "project_ids": [str(world.tools.id)],
        "auth": "session",
        "auth_method": "dev_login",
    }
    dumped = json.dumps(entry.details)
    assert body["secret"] not in dumped
    assert row.secret_hash not in dumped


@pytest.mark.parametrize(
    ("asked", "stored"),
    [
        (["write"], ["read", "write"]),
        (["evaluate", "mcp"], ["read", "evaluate", "mcp"]),
        (["mcp", "write", "read", "evaluate"], ["read", "write", "evaluate", "mcp"]),
        (["mcp", "mcp"], ["mcp"]),
        (["read"], ["read"]),
    ],
)
async def test_write_and_evaluate_include_read(
    login: Login, world: World, asked: list[str], stored: list[str]
) -> None:
    http = await login(world.carol)

    body = created(await create(http, scopes=asked))

    assert body["key"]["scopes"] == stored


async def test_names_are_unique_in_any_case_until_revoked(login: Login, world: World) -> None:
    http = await login(world.carol)
    first = created(await create(http, name="Claude Desktop"))

    problem(await create(http, name="claude DESKTOP"), 409, "api_key_name_taken")
    other = await login(world.lead)  # names are per owner
    created(await create(other, name="Claude Desktop"))
    assert (await http.delete(f"{KEYS}/{first['key']['id']}")).status_code == 204
    created(await create(http, name="CLAUDE desktop"))


async def test_at_most_25_keys_that_are_not_revoked(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    for n in range(24):
        await make_key(db_session, world.carol, name=f"Key {n}")
    await make_key(db_session, world.carol, name="Old", expires_at=utcnow() - timedelta(days=1))
    http = await login(world.carol)

    listed = (await http.get(KEYS)).json()
    problem(await create(http), 409, "too_many_api_keys")  # expired keys count too
    assert (listed["max_keys"], listed["can_create"], len(listed["items"])) == (25, False, 25)
    expired = next(item for item in listed["items"] if item["name"] == "Old")
    assert expired["state"] == "expired"
    assert (await http.delete(f"{KEYS}/{expired['id']}")).status_code == 204
    assert (await http.get(KEYS)).json()["can_create"] is True
    created(await create(http))


async def test_two_parallel_creates_at_24_keys_leave_one_409(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    for n in range(24):
        await make_key(db_session, world.carol, name=f"Key {n}")
    first, second = await login(world.carol), await login(world.carol)

    responses = await asyncio.gather(create(first, name="A"), create(second, name="B"))

    assert sorted(r.status_code for r in responses) == [201, 409]
    assert {r.json()["code"] for r in responses if r.status_code == 409} == {"too_many_api_keys"}
    count = await db_session.scalar(
        select(func.count()).select_from(ApiKey).where(ApiKey.user_id == world.carol.id)
    )
    assert count == 25


async def test_restrictions_must_be_projects_you_can_view(login: Login, world: World) -> None:
    carol = await login(world.carol)
    outsider = await login(world.outsider)

    unknown = problem(await create(carol, project_ids=[str(uuid4())]), 422, "invalid_project")
    hidden = problem(
        await create(carol, project_ids=[str(world.secret.id)]), 422, "invalid_project"
    )
    mixed = problem(
        await create(carol, project_ids=[str(world.cust.id), str(world.secret.id)]),
        422,
        "invalid_project",
    )

    assert unknown["detail"] == hidden["detail"] == mixed["detail"]  # never says which
    # An internal project is viewable without a role; duplicates are merged.
    body = created(await create(outsider, project_ids=[str(world.tools.id), str(world.tools.id)]))
    assert [p["slug"] for p in body["key"]["projects"]] == ["internal-tools"]


async def test_an_archived_project_may_be_chosen(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Project).where(Project.id == world.cust.id).values(archived_at=utcnow())
    )
    await db_session.commit()
    http = await login(world.carol)

    created(await create(http, project_ids=[str(world.cust.id)]))


async def test_listed_projects_are_the_ones_that_still_exist_and_you_can_view(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    http = await login(world.carol)
    created(
        await create(http, scopes=["read"], project_ids=[str(world.cust.id), str(world.tools.id)])
    )
    # Carol leaves Customer Innovation: the key keeps the id, but the list doesn't name it.
    await db_session.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == world.cust.id, ProjectMember.user_id == world.carol.id
        )
    )
    await db_session.commit()

    [item] = (await http.get(KEYS)).json()["items"]

    assert item["restricted"] is True
    assert [p["slug"] for p in item["projects"]] == ["internal-tools"]


# --- c20: the break-glass account ------------------------------------------------------------
BREAK_GLASS = {
    "break_glass_enabled": True,
    "break_glass_username": "emergency-admin",
    "break_glass_password": "correct horse battery staple",
    "dev_login_enabled": False,
}


@pytest.mark.settings(**BREAK_GLASS)
async def test_the_break_glass_account_cannot_create_keys(client: httpx.AsyncClient) -> None:
    signed_in = await client.post(
        f"{API}/auth/break-glass",
        json={"username": "emergency-admin", "password": "correct horse battery staple"},
    )
    assert signed_in.status_code == 200, signed_in.text
    client.headers["X-CSRF-Token"] = client.cookies["soundings_csrf"]

    refused = problem(await create(client), 403, "break_glass_account")
    listed = (await client.get(KEYS)).json()
    revoke = await client.delete(f"{KEYS}/{uuid4()}")

    assert refused["detail"]
    assert (listed["items"], listed["can_create"]) == ([], False)
    problem(revoke, 404, "not_found")


async def test_issuing_a_key_for_a_break_glass_or_inactive_owner_fails(
    db_session: AsyncSession, world: World
) -> None:
    """Under the owner's row lock the create re-reads ``is_active``: a deactivation
    that committed first wins and nothing is created (contract-phase5 section 3.1)."""
    await db_session.execute(update(User).where(User.id == world.carol.id).values(is_active=False))
    await db_session.commit()
    body = ApiKeyCreate(name="Late", scopes=[ApiKeyScope.READ])

    with pytest.raises(UnauthorizedProblem):
        await issue_key(
            db_session,
            owner=world.carol,
            creator=Principal(user=world.carol, auth_method=AuthMethod.DEV_LOGIN),
            created_auth_method=AuthMethod.DEV_LOGIN,
            body=body,
        )
    await db_session.rollback()
    assert list(await db_session.scalars(select(ApiKey.id))) == []


async def test_a_create_waiting_on_a_deactivation_creates_nothing(
    app: FastAPI, login: Login, world: World, db_session: AsyncSession
) -> None:
    """The create locks the owner's row and re-reads ``is_active``: a deactivation that
    holds the row commits first, and the create then answers 401 with nothing stored."""
    http = await login(world.carol)
    async with app.state.sessionmaker() as deactivation:
        await deactivation.execute(
            update(User).where(User.id == world.carol.id).values(is_active=False)
        )
        pending = asyncio.create_task(create(http))
        for _ in range(200):  # until the create waits for the row lock
            waiting = await db_session.scalar(
                text("SELECT count(*) FROM pg_locks WHERE NOT granted")
            )
            if waiting:
                break
            await asyncio.sleep(0.02)
        assert waiting, "the create never waited for the lock"
        await deactivation.commit()
    response = await pending

    problem(response, 401, "unauthorized")
    assert list(await db_session.scalars(select(ApiKey.id))) == []


# --- Revoking --------------------------------------------------------------------------------
async def test_revoking_your_key(login: Login, world: World, db_session: AsyncSession) -> None:
    http = await login(world.carol)
    body = created(await create(http))
    key_id = body["key"]["id"]

    first = await http.delete(f"{KEYS}/{key_id}")
    again = await http.delete(f"{KEYS}/{key_id}")

    assert (first.status_code, again.status_code) == (204, 204)
    row = await key_row(db_session, body["secret"])
    assert row.revoked_at is not None
    assert row.revoked_by_id == world.carol.id
    assert (await http.get(KEYS)).json()["items"] == []
    [entry] = await audit_rows(db_session, "api_key.revoke")  # once, not per call
    assert (entry.actor_id, entry.target_type, entry.target_id) == (
        world.carol.id,
        "user",
        world.carol.id,
    )
    assert entry.details == {
        "rule": "api_key.manage_own",
        "key_id": key_id,
        "prefix": body["key"]["prefix"],
        "auth": "session",
        "auth_method": "dev_login",
    }


async def test_someone_elses_or_an_unknown_key_is_404(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    lead = await login(world.lead)
    carol = await login(world.carol)
    body = created(await create(lead))

    problem(await carol.delete(f"{KEYS}/{body['key']['id']}"), 404, "not_found")
    problem(await carol.delete(f"{KEYS}/{uuid4()}"), 404, "not_found")
    assert (await key_row(db_session, body["secret"])).revoked_at is None


async def test_keys_cannot_manage_keys(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    """Key management is session only: a leaked key can't mint or protect itself."""
    key = await make_key(db_session, world.platform)
    other = await make_key(db_session, world.carol)
    other_id = (await key_row(db_session, other)).id
    async with key_client(app, key) as http:
        responses = [
            await http.get(KEYS),
            await http.post(KEYS, json={"name": "Minted", "scopes": ["read"]}),
            await http.delete(f"{KEYS}/{uuid4()}"),
            await http.get(ADMIN_KEYS),
            await http.delete(f"{ADMIN_KEYS}/{other_id}"),
        ]

    for response in responses:
        problem(response, 403, "insufficient_scope")
    assert (await key_row(db_session, other)).revoked_at is None
    assert len(list(await db_session.scalars(select(ApiKey.id)))) == 2


# --- Admin settings -> API keys ----------------------------------------------------------------
async def _admin_world(db: AsyncSession, world: World) -> dict[str, str]:
    keys = {
        "carol_claude": await make_key(
            db,
            world.carol,
            name="Claude Desktop",
            scopes=["read", "mcp"],
            project_ids=[world.cust.id],
        ),
        "carol_old": await make_key(
            db, world.carol, name="Old script", expires_at=utcnow() - timedelta(minutes=1)
        ),
        "lead_report": await make_key(db, world.lead, name="Weekly report", scopes=["read"]),
        "bot_agent": await make_key(
            db, world.bot, name="Agent", scopes=["read", "evaluate", "mcp"], creator=world.platform
        ),
        "revoked": await make_key(db, world.outsider, name="Gone"),
    }
    await db.execute(
        update(ApiKey).where(ApiKey.lookup_id == keys["revoked"][4:16]).values(revoked_at=utcnow())
    )
    # Lena hasn't signed in for 31 days: her key is dormant.
    await mark_seen(db, world.lead, utcnow() - timedelta(days=31))
    return keys


async def _names(http: httpx.AsyncClient, **params: Any) -> list[str]:
    response = await http.get(ADMIN_KEYS, params=params)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == len(page["items"]) or page["next_cursor"]
    return [item["name"] for item in page["items"]]


async def test_admins_list_every_key_that_is_not_revoked(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    keys = await _admin_world(db_session, world)
    http = await login(world.platform)

    page = (await http.get(ADMIN_KEYS)).json()

    assert [item["name"] for item in page["items"]] == [
        "Agent",
        "Weekly report",
        "Old script",
        "Claude Desktop",
    ]  # newest first, the revoked one left out
    assert page["total"] == 4
    by_name = {item["name"]: item for item in page["items"]}
    agent = by_name["Agent"]
    assert agent["owner"]["display_name"] == "Research Agent"
    assert agent["owner_is_service_account"] is True
    assert agent["created_by"]["display_name"] == "Pat Platform"
    assert agent["state"] == "active"  # service accounts are never dormant
    assert by_name["Claude Desktop"]["owner_email"] == world.carol.email
    assert by_name["Claude Desktop"]["created_by"]["id"] == str(world.carol.id)
    assert [p["slug"] for p in by_name["Claude Desktop"]["projects"]] == ["customer-innovation"]
    assert by_name["Old script"]["state"] == "expired"
    assert by_name["Weekly report"]["state"] == "dormant"
    text = json.dumps(page)
    for key in keys.values():
        assert key not in text
        assert key[17:] not in text


async def test_admin_filters(login: Login, world: World, db_session: AsyncSession) -> None:
    keys = await _admin_world(db_session, world)
    http = await login(world.platform)
    claude = keys["carol_claude"]

    assert await _names(http, q="claude") == ["Claude Desktop"]
    assert await _names(http, q="CAROL") == ["Old script", "Claude Desktop"]
    assert await _names(http, q=world.lead.email.upper()) == ["Weekly report"]
    assert await _names(http, q=claude[:16]) == ["Claude Desktop"]  # the prefix
    assert await _names(http, q=claude[4:16]) == ["Claude Desktop"]  # the lookup id
    assert await _names(http, q=claude[:20]) == ["Claude Desktop"]  # cut to its prefix
    assert await _names(http, q=claude[:10]) == []  # part of a prefix isn't a match
    assert await _names(http, q=keys["revoked"][:16]) == []
    assert await _names(http, user_id=str(world.carol.id)) == ["Old script", "Claude Desktop"]
    assert await _names(http, state="active") == ["Agent", "Claude Desktop"]
    assert await _names(http, state="expired") == ["Old script"]
    assert await _names(http, state="dormant") == ["Weekly report"]
    assert await _names(http, q="carol", state="active") == ["Claude Desktop"]
    assert await _names(http, q="100%_") == []  # LIKE wildcards are literal


async def test_admin_list_pages(login: Login, world: World, db_session: AsyncSession) -> None:
    await _admin_world(db_session, world)
    http = await login(world.platform)

    first = (await http.get(ADMIN_KEYS, params={"limit": 3})).json()
    second = (
        await http.get(ADMIN_KEYS, params={"limit": 3, "cursor": first["next_cursor"]})
    ).json()

    assert [i["name"] for i in first["items"]] == ["Agent", "Weekly report", "Old script"]
    assert [i["name"] for i in second["items"]] == ["Claude Desktop"]
    assert (first["total"], second["total"], second["next_cursor"]) == (4, 4, None)
    problem(
        await http.get(ADMIN_KEYS, params={"cursor": "bm90LWEtY3Vyc29y"}), 400, "invalid_cursor"
    )


async def test_only_platform_admins_list_and_revoke_any_key(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    keys = await _admin_world(db_session, world)
    lead = await login(world.lead)  # a project admin, not a platform admin
    agent_id = (await key_row(db_session, keys["bot_agent"])).id

    problem(await lead.get(ADMIN_KEYS), 403, "forbidden")
    problem(await lead.delete(f"{ADMIN_KEYS}/{uuid4()}"), 403, "forbidden")  # 403 before 404
    problem(await lead.delete(f"{ADMIN_KEYS}/{agent_id}"), 403, "forbidden")
    assert (await key_row(db_session, keys["bot_agent"])).revoked_at is None


async def test_admins_revoke_any_key(login: Login, world: World, db_session: AsyncSession) -> None:
    keys = await _admin_world(db_session, world)
    http = await login(world.platform)
    agent = await key_row(db_session, keys["bot_agent"])

    problem(await http.delete(f"{ADMIN_KEYS}/{uuid4()}"), 404, "not_found")
    assert (await http.delete(f"{ADMIN_KEYS}/{agent.id}")).status_code == 204
    assert (await http.delete(f"{ADMIN_KEYS}/{agent.id}")).status_code == 204

    revoked = await key_row(db_session, keys["bot_agent"])
    assert revoked.revoked_by_id == world.platform.id
    [entry] = await audit_rows(db_session, "api_key.revoke")
    assert (entry.actor_id, entry.target_id) == (world.platform.id, world.bot.id)
    assert entry.details["rule"] == "api_key.manage_any"
    assert entry.details["prefix"] == keys["bot_agent"][:16]
    assert "Agent" not in await _names(http)


# --- Deactivation ------------------------------------------------------------------------------
async def test_deactivating_revokes_every_key(world: World, db_session: AsyncSession) -> None:
    first = await make_key(db_session, world.carol, name="One")
    second = await make_key(db_session, world.carol, name="Two")
    already = await make_key(db_session, world.carol, name="Three")
    await db_session.execute(
        update(ApiKey).where(ApiKey.lookup_id == already[4:16]).values(revoked_at=utcnow())
    )
    await db_session.commit()
    admin = Principal(user=world.platform, auth_method=AuthMethod.DEV_LOGIN)

    world.carol.is_active = False
    revoked = await revoke_all_for_user(db_session, world.carol.id, actor=admin)
    await db_session.commit()

    assert revoked == 2
    for key in (first, second):
        row = await key_row(db_session, key)
        assert row.revoked_at is not None
        assert row.revoked_by_id == world.platform.id
    entries = await audit_rows(db_session, "api_key.revoke")
    assert len(entries) == 2
    for entry in entries:
        assert entry.target_id == world.carol.id
        assert entry.details["rule"] == Rule.PLATFORM_MANAGE_USERS
        assert entry.details["reason"] == "deactivated"
