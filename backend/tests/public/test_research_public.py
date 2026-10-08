"""Public tracking and the submitter's status emails never show Research (contract-phase8
section 3.9): it is reported as the status before it in the project's lifecycle (New
before evaluation, Shortlisted before the proposal), and a move that changes nothing
reported adds no history row and sends no email."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EmailType, IdeaStatus, ResearchStep
from app.models.idea import Idea
from tests.public.conftest import AsUser, Team, ok
from tests.public.test_emails import emails_of, move, opted_in
from tests.public.test_tracking import track
from tests.research.conftest import set_step

pytestmark = pytest.mark.usefixtures("form")

OPTIONAL = [("Similar work elsewhere", "", False)]  # never blocks: the moves are free

# (step, the idea's status first, the moves, reported now, history rows, status emails)
CASES = [
    (ResearchStep.BEFORE_EVALUATION, "new", ["research"], ("new", "New"), [], 0),
    (
        ResearchStep.BEFORE_EVALUATION,
        "new",
        ["research", "evaluating"],
        ("evaluating", "Evaluating"),
        ["evaluating"],
        1,
    ),
    (ResearchStep.BEFORE_EVALUATION, "new", ["research", "new"], ("new", "New"), [], 0),
    (
        ResearchStep.BEFORE_EVALUATION,
        "new",
        ["evaluating", "research"],
        ("new", "New"),
        ["evaluating", "new"],  # back to Research reads like back to New
        2,
    ),
    (
        ResearchStep.BEFORE_PROPOSAL,
        "shortlisted",
        ["research"],
        ("shortlisted", "Shortlisted"),
        [],
        0,
    ),
    (
        ResearchStep.BEFORE_PROPOSAL,
        "shortlisted",
        ["research", "proposal"],
        ("proposal", "Proposal"),
        ["proposal"],
        1,
    ),
    (
        ResearchStep.BEFORE_PROPOSAL,
        "shortlisted",
        ["research", "shortlisted"],
        ("shortlisted", "Shortlisted"),
        [],
        0,
    ),
]


@pytest.mark.parametrize(("step", "start", "moves", "now", "history", "emails"), CASES)
async def test_submitters_see_a_move_only_when_the_reported_status_changes(
    anon: httpx.AsyncClient,
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    step: ResearchStep,
    start: str,
    moves: list[str],
    now: tuple[str, str],
    history: list[str],
    emails: int,
) -> None:
    token, idea = await opted_in(anon, team, db_session)
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(status=IdeaStatus(start))
    )
    await db_session.commit()
    await set_step(db_session, team.project, step, OPTIONAL)

    for status in moves:
        await move(api, team, idea, status)
    body = ok(await track(anon, token))

    assert (body["status"], body["status_label"]) == now
    assert [row["status"] for row in body["history"]] == history
    assert "research" not in str(body).lower()
    assert len(await emails_of(db_session, EmailType.SUBMISSION_STATUS_CHANGED)) == emails


async def test_moving_the_step_later_never_rewrites_the_history(
    anon: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """Code review L3: each move is read with the step it happened under (recorded on
    the event), not the project's current one, so switching the step afterwards never
    adds a status the submitter's idea never had."""
    token, idea = await opted_in(anon, team, db_session)
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION, OPTIONAL)
    for status in ("research", "evaluating", "shortlisted"):
        await move(api, team, idea, status)
    before = [row["status"] for row in ok(await track(anon, token))["history"]]

    await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    after = ok(await track(anon, token))
    await set_step(db_session, team.project, ResearchStep.OFF)
    off = ok(await track(anon, token))

    assert before == ["evaluating", "shortlisted"]
    assert [row["status"] for row in after["history"]] == before
    assert [row["status"] for row in off["history"]] == before
    assert after["status"] == off["status"] == "shortlisted"
