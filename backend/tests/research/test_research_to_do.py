"""Phase 8b: My work's "Research to do" (contract-phase8b section 7) and the owned groups'
first 10 ideas (section 12).

* Every row of ``TO_DO_CASES`` (tests/test_schemas_phase8b.py) through the API.
* The order (overdue, soonest due, no date, then id), the counts equal the list, paging
  with ``GET /me/research-to-do``.
* Never: an owner who can't answer (a viewer now), an archived project, a held idea.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.enums import HoldReason, IdeaStatus, ProjectRole, ResearchStep
from app.models.idea import Idea
from app.models.project import Project, ProjectMember
from app.schemas.work import OWNED_GROUP_PREVIEW
from tests.factories import make_idea, set_researcher
from tests.research.conftest import AsUser, Team, answer, assert_problem, key_of, ok, set_step
from tests.test_schemas_phase8b import TO_DO_CASES


@pytest.mark.parametrize(
    ("step", "status", "required_open", "assigned", "has_due_date", "expected"), TO_DO_CASES
)
async def test_every_case_through_the_api(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    step: ResearchStep,
    status: IdeaStatus,
    required_open: int,
    assigned: bool,
    has_due_date: bool,
    expected: bool,
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(research_step=step)
    )
    await db_session.commit()
    idea = await make_idea(db_session, team.project, owner=team.owner, status=status)
    required = [item for item in items if item.required]
    for item in required[: len(required) - required_open]:
        await answer(db_session, idea, item, team.owner)
    due = utcnow() + timedelta(days=3) if has_due_date else None
    await set_researcher(db_session, idea, team.member if assigned else None, due_at=due)
    person = team.member if assigned else team.owner

    work = ok(await (await api(person)).get("/me/work"))

    keys = [item["idea"]["key"] for item in work["research_to_do"]]
    assert (key_of(team.project, idea) in keys) is expected
    assert work["counts"]["research_to_do"] == (1 if expected else 0)
    if expected:
        (item,) = work["research_to_do"]
        assert item["as_owner"] is (not assigned)
        assert item["can_view_project"] is True
        assert item["progress"]["required_open"] == required_open
        assert item["owner"]["id"] == str(team.owner.id)


async def _ideas(db: AsyncSession, team: Team, dues: list[timedelta | None]) -> list[Idea]:
    await set_step(db, team.project, ResearchStep.BEFORE_EVALUATION)
    made = []
    for due in dues:
        idea = await make_idea(db, team.project, owner=team.owner, status=IdeaStatus.RESEARCH)
        await set_researcher(db, idea, team.member, due_at=utcnow() + due if due else None)
        made.append(idea)
    return made


async def test_overdue_first_then_soonest_then_no_date(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    late, soon, later, none_a, none_b = await _ideas(
        db_session,
        team,
        [timedelta(days=-1), timedelta(days=1), timedelta(days=5), None, None],
    )
    member = await api(team.member)

    work = ok(await member.get("/me/work"))

    undated = sorted([none_a, none_b], key=lambda idea: idea.id)
    expected = [key_of(team.project, idea) for idea in (late, soon, later, *undated)]
    assert [item["idea"]["key"] for item in work["research_to_do"]] == expected
    assert [item["overdue"] for item in work["research_to_do"]] == [
        True,
        False,
        False,
        False,
        False,
    ]
    assert work["research_to_do_next_cursor"] is None
    assert (work["counts"]["research_to_do"], work["counts"]["research_overdue"]) == (5, 1)
    counts = ok(await member.get("/me/work/counts"))
    assert (counts["research_to_do"], counts["research_overdue"]) == (5, 1)

    seen: list[str] = []
    cursor = None
    for _ in range(5):
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = ok(await member.get("/me/research-to-do", **params))
        seen += [item["idea"]["key"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == expected
    assert_problem(await member.get("/me/research-to-do", cursor="nope"), 400, "invalid_cursor")


async def test_another_ideas_answers_dont_count(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """Regression (found with the demo data): the "required item open" subquery must
    look at this idea's answers only."""
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    done = await make_idea(db_session, team.project, owner=team.owner, status=IdeaStatus.RESEARCH)
    for item in items:
        if item.required:
            await answer(db_session, done, item, team.owner)
    todo = await make_idea(db_session, team.project, owner=team.owner, status=IdeaStatus.RESEARCH)

    work = ok(await (await api(team.owner)).get("/me/work"))

    assert [item["idea"]["key"] for item in work["research_to_do"]] == [key_of(team.project, todo)]
    assert work["counts"]["research_to_do"] == 1


async def test_never_for_an_owner_who_cant_answer(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    await make_idea(db_session, team.project, owner=team.owner, status=IdeaStatus.RESEARCH)
    owner = await api(team.owner)
    assert ok(await owner.get("/me/work"))["counts"]["research_to_do"] == 1

    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.project_id == team.project.id, ProjectMember.user_id == team.owner.id)
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.commit()

    work = ok(await owner.get("/me/work"))
    assert work["research_to_do"] == []
    assert ok(await owner.get("/me/work/counts"))["research_to_do"] == 0


@pytest.mark.parametrize("state", ["archived", "held"])
async def test_never_archived_or_held(
    api: AsUser, team: Team, db_session: AsyncSession, state: str
) -> None:
    (idea,) = await _ideas(db_session, team, [timedelta(days=1)])
    if state == "archived":
        await db_session.execute(
            update(Project).where(Project.id == team.project.id).values(archived_at=utcnow())
        )
    else:
        await db_session.execute(
            update(Idea).where(Idea.id == idea.id).values(held_for=HoldReason.MODERATION)
        )
    await db_session.commit()

    work = ok(await (await api(team.member)).get("/me/work"))

    assert work["research_to_do"] == []
    assert work["counts"]["research_to_do"] == 0


async def test_owned_groups_hold_their_first_ten(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    for _ in range(OWNED_GROUP_PREVIEW + 2):
        await make_idea(db_session, team.project, owner=team.owner)

    work = ok(await (await api(team.owner)).get("/me/work"))

    (group,) = work["owned"]
    assert group["count"] == OWNED_GROUP_PREVIEW + 2
    assert len(group["ideas"]) == OWNED_GROUP_PREVIEW == 10
    assert group["next_cursor"] is not None
