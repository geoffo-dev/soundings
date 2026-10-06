"""Service accounts over HTTP (contract-phase5 sections 2 and 3.7): an AI agent never
owns an idea (c4) or holds the admin role, its evaluation is left out of the aggregate,
and deactivating anyone (agent or person) revokes their keys for good. Phase 6 (c22): an
agent's key works on ``/mcp`` only, inside an open run."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx2
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.principal import Principal
from app.models.enums import AiRunKind, EvaluationStatus, IdeaStatus, ProjectRole
from app.models.evaluation import Evaluation
from app.models.user import User
from app.pagination import PageParams
from app.services import users
from tests.ai.helpers import make_agent, open_run
from tests.api_keys.helpers import API, World, audit_rows, key_client, key_row, make_key, problem
from tests.conftest import Login
from tests.factories import add_evaluator, add_member, criteria, make_idea, make_user
from tests.mcp.conftest import headers, rpc


async def _scores(db: AsyncSession, world: World, value: int) -> list[dict[str, Any]]:
    return [{"criterion_id": str(c.id), "score": value} for c in await criteria(db, world.cust)]


async def test_an_agent_can_not_be_made_an_ideas_owner(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, world.cust)
    lead = await login(world.lead)

    refused = await lead.put(f"{API}/ideas/{idea.id}/owner", json={"user_id": str(world.bot.id)})
    person = await lead.put(f"{API}/ideas/{idea.id}/owner", json={"user_id": str(world.carol.id)})

    problem(refused, 422, "assignee_not_eligible")
    assert person.status_code == 200, person.text
    assert person.json()["owner"]["id"] == str(world.carol.id)


async def test_an_agent_is_never_a_project_admin(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    other = await make_user(db_session, "Second Agent", service_account=True)
    lead = await login(world.lead)
    members = f"{API}/projects/{world.cust.slug}/members"

    added_admin = await lead.post(members, json={"user_id": str(other.id), "role": "admin"})
    promoted = await lead.patch(f"{members}/{world.bot.id}", json={"role": "admin"})
    added_viewer = await lead.post(members, json={"user_id": str(other.id), "role": "viewer"})
    to_member = await lead.patch(f"{members}/{other.id}", json={"role": "member"})
    unchanged = await lead.patch(f"{members}/{world.bot.id}", json={"role": "member"})

    problem(added_admin, 409, "system_account")
    problem(promoted, 409, "system_account")
    assert added_viewer.status_code == 201, added_viewer.text
    assert to_member.status_code == 200, to_member.text
    assert unchanged.status_code == 200, unchanged.text
    roles = {m["user"]["id"]: m["role"] for m in (await lead.get(members)).json()}
    assert roles[str(world.bot.id)] == "member"
    assert roles[str(other.id)] == "member"


async def test_a_person_can_still_be_made_an_admin(
    login: Login, world: World, db_session: AsyncSession
) -> None:
    lead = await login(world.lead)

    response = await lead.patch(
        f"{API}/projects/{world.cust.slug}/members/{world.carol.id}", json={"role": "admin"}
    )

    assert response.status_code == 200, response.text


async def _mcp_submit(
    app: FastAPI,
    key: str,
    idea: str,
    scores: list[dict[str, Any]],
    *,
    submit: bool,
    run_id: str | None = None,
) -> dict[str, Any]:
    arguments: dict[str, Any] = {"idea": idea, "scores": scores, "submit": submit}
    if run_id is not None:  # an agent's call names its run (c22)
        arguments["run_id"] = run_id
    if submit:
        arguments["recommendation"] = "no"
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.post(
            "/mcp",
            json=rpc("tools/call", {"name": "submit_evaluation", "arguments": arguments}),
            headers=headers(key),
        )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["result"]
    return result


async def test_an_agents_evaluation_is_left_out_of_the_aggregate(
    app: FastAPI, login: Login, world: World, db_session: AsyncSession
) -> None:
    """Phase 6: an agent evaluates through ``/mcp`` during its open evaluate run (c22)."""
    idea = await make_idea(db_session, world.cust, status=IdeaStatus.EVALUATING)
    await add_evaluator(db_session, idea, world.bot)
    await add_evaluator(db_session, idea, world.carol)
    agent = await make_agent(
        db_session, [world.cust], user=world.bot, role=None, purposes=[AiRunKind.EVALUATE]
    )
    run_id = str((await open_run(db_session, agent, idea, AiRunKind.EVALUATE)).id)
    agent_key = await make_key(db_session, world.bot, scopes=["read", "evaluate", "mcp"])
    url = f"{API}/ideas/{idea.id}/evaluations/me"
    carol = await login(world.carol)
    agent_scores = [
        {**score, "comment": "Why this score."} for score in await _scores(db_session, world, 1)
    ]

    draft = await _mcp_submit(
        app, agent_key, str(idea.id), agent_scores, submit=False, run_id=run_id
    )
    submitted = await _mcp_submit(
        app, agent_key, str(idea.id), agent_scores, submit=True, run_id=run_id
    )
    async with key_client(app, agent_key) as rest:
        problem(await rest.put(url, json={"scores": agent_scores}), 403, "insufficient_scope")
    person = await carol.put(
        url,
        json={
            "scores": await _scores(db_session, world, 4),
            "recommendation": "go",
            "submit": True,
        },
    )
    detail = (await carol.get(f"{API}/ideas/{idea.id}")).json()
    listing = (await carol.get(f"{API}/ideas/{idea.id}/evaluations")).json()

    assert draft["isError"] is False, draft
    assert submitted["isError"] is False, submitted
    assert person.status_code == 200, person.text
    assert detail["aggregate"]["count"] == 1
    assert detail["aggregate"]["overall"] == detail["score"]["overall"]
    flags = {
        e["evaluator"]["id"]: (e["is_ai"], e["include_in_aggregate"]) for e in listing["items"]
    }
    assert flags == {str(world.bot.id): (True, False), str(world.carol.id): (False, True)}


async def test_a_persons_evaluation_through_a_key_stays_included(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, world.cust, status=IdeaStatus.EVALUATING)
    await add_evaluator(db_session, idea, world.carol)
    key = await make_key(db_session, world.carol, scopes=["read", "evaluate"])

    async with key_client(app, key) as carol:
        response = await carol.put(
            f"{API}/ideas/{idea.id}/evaluations/me",
            json={
                "scores": await _scores(db_session, world, 3),
                "recommendation": "go",
                "submit": True,
            },
        )

    assert response.status_code == 200, response.text
    stored = await db_session.scalar(
        select(Evaluation)
        .where(Evaluation.idea_id == idea.id, Evaluation.evaluator_id == world.carol.id)
        .execution_options(populate_existing=True)
    )
    assert stored is not None
    assert (stored.status, stored.include_in_aggregate) == (EvaluationStatus.SUBMITTED, True)


async def test_deactivating_a_user_revokes_their_keys_for_good(
    app: FastAPI, login: Login, world: World, db_session: AsyncSession
) -> None:
    first = await make_key(db_session, world.carol, scopes=["read"], name="Laptop")
    second = await make_key(db_session, world.carol, scopes=["read", "mcp"], name="Agent")
    agent = await make_key(db_session, world.bot, scopes=["read", "mcp"])
    admin = await login(world.platform)

    for user in (world.carol, world.bot):
        off = await admin.patch(f"{API}/admin/users/{user.id}", json={"is_active": False})
        assert off.status_code == 200, off.text
        on = await admin.patch(f"{API}/admin/users/{user.id}", json={"is_active": True})
        assert on.status_code == 200, on.text

    for key in (first, second, agent):
        async with key_client(app, key) as client:
            problem(await client.get(f"{API}/auth/me"), 401, "unauthorized")
        row = await key_row(db_session, key)
        assert row.revoked_at is not None
        assert row.revoked_by_id == world.platform.id
    revokes = await audit_rows(db_session, "api_key.revoke")
    assert len(revokes) == 3
    assert {entry.target_id for entry in revokes} == {world.carol.id, world.bot.id}
    assert all(entry.details["reason"] == "deactivated" for entry in revokes)
    assert all(entry.details["rule"] == "platform.manage_users" for entry in revokes)
    assert all(entry.actor_id == world.platform.id for entry in revokes)


# --- People search (security review L4) ---------------------------------------------------
# Phase 6 (c22): an agent's key is refused on every REST route, ``/users`` too; the
# service's co-member filter stays as a second fence and is tested on the service.
async def _names(app: FastAPI, key: str, query: str = "") -> set[str]:
    async with key_client(app, key) as client:
        response = await client.get(f"{API}/users", params={"q": query, "limit": 100})
    assert response.status_code == 200, response.text
    return {item["display_name"] for item in response.json()["items"]}


async def _agent_names(
    db: AsyncSession, agent: User, query: str = "", project_ids: set[UUID] | None = None
) -> set[str]:
    principal = Principal(
        user=agent,
        auth="api_key",
        scopes=frozenset({"read"}),
        project_ids=None if project_ids is None else frozenset(project_ids),
    )
    found = await users.search_users(
        db,
        q=query or None,
        project=None,
        page=PageParams(cursor=None, limit=100),
        co_members_of=principal,
    )
    return {item.display_name for item in found.items}


async def test_an_agents_key_can_not_search_people_over_rest(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    agent = await make_key(db_session, world.bot, scopes=["read"])
    person = await make_key(db_session, world.carol, scopes=["read"])

    async with key_client(app, agent) as client:
        problem(await client.get(f"{API}/users", params={"q": "carol"}), 403, "insufficient_scope")
    assert {"Pat Platform", "Otto Outsider", "Carol Chen"} <= await _names(app, person)


async def test_an_agent_finds_only_people_who_share_a_project_with_it(
    world: World, db_session: AsyncSession
) -> None:
    """The service searches an agent's co-members, not the whole directory."""
    tia = await make_user(db_session, "Tia Tools")
    await add_member(db_session, world.tools, tia, ProjectRole.MEMBER)

    assert await _agent_names(db_session, world.bot) == {"Lena Lead", "Carol Chen", "Vic Viewer"}
    assert await _agent_names(db_session, world.bot, "tia") == set()
    assert await _agent_names(db_session, world.bot, "carol") == {"Carol Chen"}


async def test_an_agents_people_search_stays_inside_its_keys_projects(
    world: World, db_session: AsyncSession
) -> None:
    tia = await make_user(db_session, "Tia Tools")
    await add_member(db_session, world.tools, tia, ProjectRole.MEMBER)
    await add_member(db_session, world.tools, world.bot, ProjectRole.MEMBER)

    assert "Tia Tools" in await _agent_names(db_session, world.bot)
    assert await _agent_names(db_session, world.bot, project_ids={world.cust.id}) == {
        "Lena Lead",
        "Carol Chen",
        "Vic Viewer",
    }


async def test_an_agent_without_a_project_finds_nobody(
    world: World, db_session: AsyncSession
) -> None:
    loner = await make_user(db_session, "Idle Agent", service_account=True)

    assert await _agent_names(db_session, loner) == set()
