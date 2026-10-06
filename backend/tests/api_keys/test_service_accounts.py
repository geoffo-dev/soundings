"""Service accounts over HTTP (contract-phase5 sections 2 and 3.7): an AI agent never
owns an idea (c4) or holds the admin role, its evaluation is left out of the aggregate,
and deactivating anyone (agent or person) revokes their keys for good."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EvaluationStatus, IdeaStatus, ProjectRole
from app.models.evaluation import Evaluation
from tests.api_keys.helpers import API, World, audit_rows, key_client, key_row, make_key, problem
from tests.conftest import Login
from tests.factories import add_evaluator, add_member, criteria, make_idea, make_user


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


async def test_an_agents_evaluation_is_left_out_of_the_aggregate(
    app: FastAPI, login: Login, world: World, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, world.cust, status=IdeaStatus.EVALUATING)
    await add_evaluator(db_session, idea, world.bot)
    await add_evaluator(db_session, idea, world.carol)
    agent_key = await make_key(db_session, world.bot, scopes=["read", "evaluate"])
    url = f"{API}/ideas/{idea.id}/evaluations/me"
    carol = await login(world.carol)

    async with key_client(app, agent_key) as agent:
        draft = await agent.put(url, json={"scores": await _scores(db_session, world, 1)})
        submitted = await agent.put(
            url,
            json={
                "scores": await _scores(db_session, world, 1),
                "recommendation": "no",
                "submit": True,
            },
        )
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

    assert draft.status_code == 200, draft.text
    assert submitted.status_code == 200, submitted.text
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
async def _names(app: FastAPI, key: str, query: str = "") -> set[str]:
    async with key_client(app, key) as client:
        response = await client.get(f"{API}/users", params={"q": query, "limit": 100})
    assert response.status_code == 200, response.text
    return {item["display_name"] for item in response.json()["items"]}


async def test_an_agent_finds_only_people_who_share_a_project_with_it(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    """An agent's key searches the people of its own projects, not the whole directory
    (a person's key, like a session, still finds everyone)."""
    tia = await make_user(db_session, "Tia Tools")
    await add_member(db_session, world.tools, tia, ProjectRole.MEMBER)
    agent = await make_key(db_session, world.bot, scopes=["read"])
    person = await make_key(db_session, world.carol, scopes=["read"])

    found = await _names(app, agent)
    everyone = await _names(app, person)

    assert found == {"Lena Lead", "Carol Chen", "Vic Viewer"}
    assert {"Tia Tools", "Pat Platform", "Otto Outsider"} <= everyone
    assert await _names(app, agent, "tia") == set()
    assert await _names(app, agent, "carol") == {"Carol Chen"}


async def test_an_agents_people_search_stays_inside_its_keys_projects(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    tia = await make_user(db_session, "Tia Tools")
    await add_member(db_session, world.tools, tia, ProjectRole.MEMBER)
    await add_member(db_session, world.tools, world.bot, ProjectRole.MEMBER)
    unrestricted = await make_key(db_session, world.bot, scopes=["read"])
    cust_only = await make_key(db_session, world.bot, scopes=["read"], project_ids=[world.cust.id])

    assert "Tia Tools" in await _names(app, unrestricted)
    assert await _names(app, cust_only) == {"Lena Lead", "Carol Chen", "Vic Viewer"}


async def test_an_agent_without_a_project_finds_nobody(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    loner = await make_user(db_session, "Idle Agent", service_account=True)
    key = await make_key(db_session, loner, scopes=["read"])

    assert await _names(app, key) == set()
