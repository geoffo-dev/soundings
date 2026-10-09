"""Adversarial check L2 (2026-10-09): past Research, nobody new is asked to research.

After lead decision D1 a researcher who isn't the owner or an admin can't change the
answers once the idea is past Research, so naming someone new there would only grant read
access (a guest's view of a private idea) and send an "Asked to research" notice for work
nobody can do. So ``set_research_assignment`` refuses **a researcher other than the
current one** once the idea is past Research: 409 ``research_finished`` (after the 403,
422 and the other 409s), for everyone who may assign (the owner, project and platform
admins), whoever is named (a member, an outsider, the owner by name, an admin). Removing
the researcher (``researcher_id: null``, or ``DELETE``), handing it back and keeping the
same researcher (a due-date change) still work; moving the idea back to Research (or
before it) lets the owner ask someone again.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import IdeaStatus, ProjectRole, ResearchStep, Resolution
from app.models.idea import Idea
from app.models.notification import Notification
from app.models.project import ProjectMember
from app.models.user import User
from tests.factories import make_idea, make_user, set_researcher
from tests.research.conftest import (
    AsUser,
    Team,
    assert_problem,
    assign,
    feed_types,
    key_of,
    ok,
    researcher_audit,
    set_step,
)

S = IdeaStatus
DUE = "2026-12-11T17:00:00+00:00"
LATER = "2026-12-18T17:00:00+00:00"
PAST_RESEARCH = [
    (ResearchStep.BEFORE_EVALUATION, S.EVALUATING),
    (ResearchStep.BEFORE_EVALUATION, S.SHORTLISTED),
    (ResearchStep.BEFORE_EVALUATION, S.PROPOSAL),
    (ResearchStep.BEFORE_PROPOSAL, S.PROPOSAL),
]


async def _idea(
    team: Team,
    db: AsyncSession,
    status: IdeaStatus,
    *,
    step: ResearchStep = ResearchStep.BEFORE_EVALUATION,
    researcher: User | None = None,
) -> Idea:
    await set_step(db, team.project, step)
    idea = await make_idea(db, team.project, status=status, owner=team.owner)
    if researcher is not None:  # asked while it was still in Research
        await set_researcher(db, idea, researcher)
    return idea


async def _notifications(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(Notification)) or 0)


def _named(team: Team, who: str) -> User:
    return {
        "member": team.member,
        "outsider": team.outsider,
        "owner": team.owner,
        "admin": team.admin,
    }[who]


@pytest.mark.parametrize(("step", "status"), PAST_RESEARCH)
@pytest.mark.parametrize("by", ["owner", "admin", "platform"])
@pytest.mark.parametrize("who", ["member", "outsider", "owner", "admin"])
async def test_past_research_nobody_new_is_asked(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    step: ResearchStep,
    status: IdeaStatus,
    by: str,
    who: str,
) -> None:
    if by == "owner" and who in ("outsider",):
        pytest.skip("the owner of a private idea can't name an outsider at all (c25: 403)")
    idea = await _idea(team, db_session, status, step=step)
    before = await _notifications(db_session)

    refused = await assign(
        await api(getattr(team, by)), key_of(team.project, idea), _named(team, who), DUE
    )

    body = assert_problem(refused, 409, "research_finished")
    assert "nobody new" in body["detail"]
    await db_session.refresh(idea)
    assert idea.researcher_id is None
    assert idea.research_due_at is None
    assert await researcher_audit(db_session, idea) == []
    assert "researcher_changed" not in await feed_types(db_session, idea)
    assert await _notifications(db_session) == before


@pytest.mark.parametrize(("step", "status"), PAST_RESEARCH)
async def test_past_research_a_new_researcher_replacing_one_is_refused_too(
    api: AsUser, team: Team, db_session: AsyncSession, step: ResearchStep, status: IdeaStatus
) -> None:
    idea = await _idea(team, db_session, status, step=step, researcher=team.member)

    refused = await assign(await api(team.admin), key_of(team.project, idea), team.outsider, DUE)

    assert_problem(refused, 409, "research_finished")
    await db_session.refresh(idea)
    assert idea.researcher_id == team.member.id


@pytest.mark.parametrize(("step", "status"), PAST_RESEARCH)
async def test_past_research_the_researcher_is_kept_removed_or_handed_back(
    api: AsUser, team: Team, db_session: AsyncSession, step: ResearchStep, status: IdeaStatus
) -> None:
    """Only naming someone new is refused: the same researcher again (a due-date change),
    nobody (Remove), ``DELETE`` and "Hand back" still work."""
    owner = await api(team.owner)
    kept = await _idea(team, db_session, status, step=step, researcher=team.outsider)
    removed = await make_idea(db_session, team.project, status=status, owner=team.owner)
    await set_researcher(db_session, removed, team.member)
    deleted = await make_idea(db_session, team.project, status=status, owner=team.owner)
    await set_researcher(db_session, deleted, team.member)
    handed = await make_idea(db_session, team.project, status=status, owner=team.owner)
    await set_researcher(db_session, handed, team.outsider)

    ok(await assign(owner, key_of(team.project, kept), team.outsider, LATER))
    ok(await assign(owner, key_of(team.project, removed), None, None))
    gone = await owner.delete(f"/ideas/{key_of(team.project, deleted)}/research/assignment")
    back = await (await api(team.outsider)).delete(
        f"/ideas/{key_of(team.project, handed)}/research/assignment"
    )

    assert gone.status_code == 204, gone.text
    assert back.status_code == 204, back.text
    for idea in (kept, removed, deleted, handed):
        await db_session.refresh(idea)
    assert kept.researcher_id == team.outsider.id
    assert kept.research_due_at is not None
    assert kept.research_due_at.isoformat() == LATER
    assert removed.researcher_id is None
    assert deleted.researcher_id is None
    assert handed.researcher_id is None
    assert [entry.details["reason"] for entry in await researcher_audit(db_session, handed)] == [
        "handed_back"
    ]


async def test_back_in_research_the_owner_asks_someone_again(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await _idea(team, db_session, S.EVALUATING)
    owner = await api(team.owner)
    key = key_of(team.project, idea)

    refused = await assign(owner, key, team.member, DUE)
    ok(await owner.post(f"/ideas/{key}/status", {"status": "research"}))
    asked = ok(await assign(owner, key, team.member, DUE))

    assert_problem(refused, 409, "research_finished")
    assert asked["assignment"]["researcher"]["id"] == str(team.member.id)


@pytest.mark.parametrize("status", [S.NEW, S.RESEARCH])
async def test_in_or_before_research_anyone_eligible_can_still_be_asked(
    api: AsUser, team: Team, db_session: AsyncSession, status: IdeaStatus
) -> None:
    idea = await _idea(team, db_session, status)
    asked = ok(await assign(await api(team.admin), key_of(team.project, idea), team.outsider, DUE))
    assert asked["assignment"]["researcher"]["id"] == str(team.outsider.id)


async def test_the_check_order_puts_research_finished_last(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """403 (may not assign; c25) -> 422 (c23) -> 409 (closed, archived) -> 409
    research_finished: nothing about the research being over leaks to someone who may
    not assign, and an ineligible person is still a 422."""
    idea = await _idea(team, db_session, S.EVALUATING)
    key = key_of(team.project, idea)
    service = await make_user(db_session, "Bot Account", service_account=True)
    db_session.add(
        ProjectMember(project_id=team.project.id, user_id=service.id, role=ProjectRole.MEMBER)
    )
    await db_session.commit()

    viewer = await assign(await api(team.viewer), key, team.member, DUE)
    outsider = await assign(await api(team.owner), key, team.outsider, DUE)  # c25
    ineligible = await assign(await api(team.admin), key, service, DUE)
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(status=S.CLOSED, resolution=Resolution.PARKED)
    )
    await db_session.commit()
    closed = await assign(await api(team.admin), key, team.member, DUE)

    assert_problem(viewer, 403, "forbidden")
    assert_problem(outsider, 403, "outside_researcher_needs_admin")
    assert_problem(ineligible, 422, "researcher_not_eligible")
    assert closed.status_code == 409
    assert closed.json()["code"] != "research_finished"


async def test_the_flags_still_let_owners_and_admins_change_the_assignment(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """``can_assign`` stays true past Research: Remove and the due date go through it."""
    idea = await _idea(team, db_session, S.EVALUATING, researcher=team.member)
    panel = ok(await (await api(team.owner)).get(f"/ideas/{idea.id}/research"))
    detail = ok(await (await api(team.owner)).get(f"/ideas/{idea.id}"))
    assert panel["permissions"]["can_assign"] is True
    assert detail["permissions"]["can_assign_researcher"] is True
