"""Phase 8b: the researcher picker (``search_users?include_non_members=true``, contract-
phase8b section 2.2) and leavers (``soundings anonymise-user`` on a former researcher:
nothing left to clear, answers kept under the placeholder name; review C3)."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ResearchStep
from app.models.idea import Idea
from app.models.research import ResearchAnswer
from app.models.user import User
from app.services.anonymise import anonymise_user
from tests.factories import make_idea, make_user
from tests.research.conftest import (
    AsUser,
    Team,
    answer,
    assert_problem,
    assign,
    key_of,
    ok,
    set_step,
)


async def test_the_picker_lists_everyone_active_marking_non_members(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await make_user(db_session, "Sid Service", service_account=True)
    await make_user(db_session, "Dee Deactivated", active=False)
    glass = await make_user(db_session, "Bea Breakglass")
    await db_session.execute(update(User).where(User.id == glass.id).values(is_break_glass=True))
    await db_session.commit()
    owner = await api(team.owner)

    picker = ok(await owner.get("/users", project=team.slug, include_non_members="true", limit=100))
    members = ok(await owner.get("/users", project=team.slug, limit=100))

    roles = {item["display_name"]: item["project_role"] for item in picker["items"]}
    assert roles["Otto Outsider"] is None
    assert roles["Pat Platform"] is None
    assert roles["Ada Admin"] == "admin"
    assert roles["Vic Viewer"] == "viewer"
    assert not {"Sid Service", "Dee Deactivated", "Bea Breakglass"} & set(roles)
    assert "Otto Outsider" not in {item["display_name"] for item in members["items"]}
    found = ok(await owner.get("/users", project=team.slug, include_non_members="true", q="otto"))
    assert [item["display_name"] for item in found["items"]] == ["Otto Outsider"]


async def test_the_picker_needs_the_project(api: AsUser, team: Team) -> None:
    response = await (await api(team.outsider)).get(
        "/users", project=team.slug, include_non_members="true"
    )

    assert_problem(response, 404, "not_found")


async def test_anonymising_a_former_researcher(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, owner=team.owner)
    ok(await assign(await api(team.admin), key_of(team.project, idea), team.outsider))
    await answer(db_session, idea, items[0], team.outsider)
    platform = await api(team.platform)
    ok(await platform.patch(f"/admin/users/{team.outsider.id}", {"is_active": False}))

    await anonymise_user(db_session, team.outsider.email)
    await db_session.commit()

    row = await db_session.get(Idea, idea.id, populate_existing=True)
    assert row is not None
    assert row.researcher_id is None
    kept = await db_session.scalar(
        select(ResearchAnswer)
        .where(ResearchAnswer.idea_id == idea.id)
        .execution_options(populate_existing=True)
    )
    assert kept is not None
    assert kept.answered_by_id == team.outsider.id
    research = ok(
        await (await api(team.owner)).get(f"/ideas/{key_of(team.project, idea)}/research")
    )
    answered = research["items"][0]["answer"]["answered_by"]
    assert answered["display_name"] != "Otto Outsider"
