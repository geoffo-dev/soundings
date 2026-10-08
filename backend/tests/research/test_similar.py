"""Similar ideas (contract-phase8 section 3.7): pg_trgm over the ideas the principal may
list, across every project they can view (archived ones included), never a held idea
(either kind, admins too), never the idea itself, other people's private projects never,
a key's project restriction applied; the threshold, the limit and the order; no score
data."""

from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.enums import EvaluatorState, HoldReason, IdeaStatus, ProjectRole, ProjectVisibility
from app.models.idea import Idea
from app.models.project import Project
from tests.api_keys.helpers import key_client, make_key
from tests.factories import add_evaluator, make_idea, make_project
from tests.research.conftest import AsUser, Team, ok

TITLE = "Self-service parcel lockers"
SUMMARY = "Let customers collect parcels from lockers at our stores."


async def _like(db: AsyncSession, project: Project, **extra: object) -> Idea:
    return await make_idea(
        db,
        project,
        title=str(extra.pop("title", TITLE + " for stores")),
        summary=str(extra.pop("summary", SUMMARY)),
        **extra,  # type: ignore[arg-type]
    )


async def _similar(
    api: AsUser, team: Team, idea: Idea, who: object = None
) -> list[dict[str, object]]:
    client = await api(who or team.owner)  # type: ignore[arg-type]
    items: list[dict[str, object]] = ok(await client.get(f"/ideas/{idea.id}/similar-ideas"))[
        "items"
    ]
    return items


async def test_similar_ideas_across_projects(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, title=TITLE, summary=SUMMARY, owner=team.owner)
    tools = await make_project(
        db_session, key="TOOLS", name="Internal Tools", visibility=ProjectVisibility.INTERNAL
    )
    there = await _like(db_session, tools, owner=team.admin, status=IdeaStatus.CLOSED)
    here = await _like(
        db_session,
        team.project,
        title="Parcel lockers in every store",
        summary="Collect parcels from lockers.",
    )
    await make_idea(db_session, team.project, title="Cafeteria menu", summary="Better lunches.")

    items = await _similar(api, team, idea)

    assert [item["id"] for item in items][:1] == [str(there.id)]  # most similar first
    assert {item["id"] for item in items} == {str(there.id), str(here.id)}
    first = items[0]
    assert first["key"] == f"TOOLS-{there.number}"
    assert first["project"]["key"] == "TOOLS"  # type: ignore[index]
    assert (first["status"], first["status_label"]) == ("closed", "Parked")
    assert first["owner"]["id"] == str(team.admin.id)  # type: ignore[index]
    assert first["summary"] == SUMMARY
    assert 0.3 <= float(first["similarity"]) <= 1  # type: ignore[arg-type]
    assert set(first) == {
        "id",
        "key",
        "number",
        "project",
        "title",
        "status",
        "resolution",
        "status_label",
        "summary",
        "owner",
        "last_activity_at",
        "similarity",
    }  # no score data


async def test_never_the_idea_itself_or_a_held_idea(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, title=TITLE, summary=SUMMARY)
    for reason in HoldReason:
        held = await _like(db_session, team.project)
        held.held_for = reason
    await db_session.commit()

    for who in (team.owner, team.admin, team.platform):
        assert await _similar(api, team, idea, who) == []


async def test_never_other_peoples_private_projects(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, title=TITLE, summary=SUMMARY)
    secret = await make_project(db_session, visibility=ProjectVisibility.PRIVATE)
    hidden = await _like(db_session, secret)

    mine = await _similar(api, team, idea, team.owner)
    platform = await _similar(api, team, idea, team.platform)

    assert mine == []
    assert [item["id"] for item in platform] == [str(hidden.id)]


async def test_archived_projects_are_included(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, title=TITLE, summary=SUMMARY)
    old = await make_project(
        db_session, archived=True, members={team.owner: ProjectRole.MEMBER}, name="Old ideas"
    )
    tried = await _like(db_session, old)

    assert [item["id"] for item in await _similar(api, team, idea)] == [str(tried.id)]


async def test_threshold_limit_and_order(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project, title=TITLE, summary=SUMMARY)
    now = utcnow()
    same = [
        await _like(
            db_session,
            team.project,
            title=TITLE,
            summary="Something else entirely about tea.",
            last_activity_at=now - timedelta(days=n),
        )
        for n in range(7)
    ]
    await make_idea(db_session, team.project, title="Lock", summary="Pars.")  # below 0.3

    items = await _similar(api, team, idea)

    assert len(items) == 5
    assert [item["id"] for item in items] == [str(row.id) for row in same[:5]]  # ties: recent
    assert all(item["similarity"] == 1.0 for item in items)


async def test_pending_evaluators_see_no_score_data(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, title=TITLE, summary=SUMMARY)
    other = await _like(db_session, team.project)
    await add_evaluator(db_session, other, team.evaluators[0], state=EvaluatorState.INVITED)

    items = await _similar(api, team, idea, team.evaluators[0])

    assert [item["id"] for item in items] == [str(other.id)]
    assert "score" not in items[0]


async def test_a_keys_project_restriction_applies(
    app: FastAPI, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, title=TITLE, summary=SUMMARY)
    tools = await make_project(db_session, key="TOOLS", members={team.owner: ProjectRole.MEMBER})
    await _like(db_session, tools)
    here = await _like(db_session, team.project)
    secret = await make_key(db_session, team.owner, scopes=["read"], project_ids=[team.project.id])

    async with key_client(app, secret) as client:
        response = await client.get(f"/api/v1/ideas/{idea.id}/similar-ideas")

    assert [item["id"] for item in ok(response)["items"]] == [str(here.id)]


async def test_the_nearest_candidates_match_a_full_scan(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """The service ranks only the nearest titles and summaries (the GiST indexes'
    order); on a project with many overlapping ideas it finds exactly what ranking every
    idea would, in the same order (shown similarity, then the latest activity)."""
    words = ["parcel", "locker", "store", "refund", "delivery", "customer", "returns"]
    places = ["warehouse", "stores", "the app", "partners"]
    now = utcnow()
    idea = await make_idea(
        db_session,
        team.project,
        title="Parcel locker returns for stores",
        summary="Customers return parcels at a store locker instead of the post office.",
        owner=team.owner,
    )
    for n in range(60):
        first, second = words[n % 7], words[(n * 3 + 1) % 7]
        await make_idea(
            db_session,
            team.project,
            title=f"{first.capitalize()} {second} for {places[n % 4]}",
            summary=f"Customers use a {second} for {first} at {places[(n + 1) % 4]}.",
            last_activity_at=now - timedelta(minutes=n),
        )
    scan = await db_session.execute(
        text(
            "SELECT number FROM (SELECT number, last_activity_at, id, round(greatest("
            "similarity(title, :title), similarity(summary, :summary))::numeric, 2) AS s"
            " FROM ideas WHERE id <> :id) ranked WHERE s >= 0.3"
            " ORDER BY s DESC, last_activity_at DESC, id LIMIT 5"
        ),
        {"title": idea.title, "summary": idea.summary, "id": idea.id},
    )
    expected = [f"CUST-{number}" for (number,) in scan]

    items = await _similar(api, team, idea)

    assert len(expected) == 5  # overlapping enough to rank
    assert [item["key"] for item in items] == expected
