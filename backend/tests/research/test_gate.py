"""The research gate (contract-phase8 section 3.5), tests first: every path that can take
an idea past Research (status changes and board drags, reopening a closed idea, the first
evaluator, starting a proposal; "Ask AI to evaluate" is in tests/ai/test_research_gate.py),
for owners, project admins, platform admins and API keys; "Move anyway" (allowed,
audited, refused for owners and keys, ignored when nothing blocks); all-optional
checklists; clearing re-arms; the 409's open items; concurrency with answers."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent, AuditLog
from app.models.enums import HoldReason, IdeaStatus, ResearchStep
from app.models.idea import Idea, IdeaEvaluator
from app.models.research import ResearchAnswer
from app.models.user import User
from tests.api_keys.helpers import key_client, make_key
from tests.factories import add_evaluator, make_idea
from tests.research.conftest import (
    AsUser,
    Team,
    answer,
    answer_required,
    assert_problem,
    key_of,
    ok,
    open_titles,
    set_step,
)
from tests.test_schemas_phase8 import GATE_CASES

S = IdeaStatus
ON_CASES = [case for case in GATE_CASES if case[0] is not ResearchStep.OFF]


async def _idea(db: AsyncSession, team: Team, status: IdeaStatus = S.NEW) -> Idea:
    return await make_idea(db, team.project, status=status, owner=team.owner, title="Lockers")


def _move(status: IdeaStatus, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"status": status.value, **extra}
    if status is S.CLOSED:
        body.setdefault("resolution", "parked")
    return body


async def _audits(db: AsyncSession, action: str) -> list[AuditLog]:
    return list(
        await db.scalars(
            select(AuditLog)
            .where(AuditLog.action == action)
            .order_by(AuditLog.created_at)
            .execution_options(populate_existing=True)
        )
    )


async def _status_events(db: AsyncSession, idea: Idea) -> list[dict[str, Any]]:
    rows: Any = await db.scalars(
        select(ActivityEvent.payload)
        .where(ActivityEvent.idea_id == idea.id, ActivityEvent.type == "status_changed")
        .order_by(ActivityEvent.created_at, ActivityEvent.id)
    )
    return list(rows)


# --- Status changes (the menu, the board drag, Undo, the keyboard: one request) ---------
@pytest.mark.parametrize(("step", "before", "after", "guarded"), ON_CASES)
async def test_status_changes_follow_the_gate(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    step: ResearchStep,
    before: IdeaStatus,
    after: IdeaStatus,
    guarded: bool,
) -> None:
    await set_step(db_session, team.project, step)
    idea = await _idea(db_session, team, before)
    olive = await api(team.owner)

    response = await olive.post(f"/ideas/{idea.id}/status", _move(after))

    if guarded:
        body = assert_problem(response, 409, "research_incomplete")
        assert open_titles(body) == [
            "Not already being done elsewhere",
            "Departments or teams consulted",
        ]
        assert body["can_override"] is False  # owners can't move anyway
        assert body["detail"] == ("Finish the research checklist first: 2 required items are open.")
        await db_session.refresh(idea)
        assert idea.status is before  # nothing changed
    else:
        assert ok(response)["status"] == after.value


@pytest.mark.parametrize(("step", "before", "after", "guarded"), ON_CASES)
async def test_an_answered_checklist_lets_every_move_through(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    step: ResearchStep,
    before: IdeaStatus,
    after: IdeaStatus,
    guarded: bool,
) -> None:
    items = await set_step(db_session, team.project, step)
    idea = await _idea(db_session, team, before)
    await answer_required(db_session, idea, items, team.owner)  # the optional one stays open

    response = await (await api(team.owner)).post(f"/ideas/{idea.id}/status", _move(after))

    assert ok(response)["status"] == after.value
    assert await _audits(db_session, "idea.research_override") == []


@pytest.mark.parametrize("who", ["owner", "admin", "platform"])
async def test_the_gate_holds_for_everyone_without_the_override(
    api: AsUser, team: Team, db_session: AsyncSession, who: str
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.RESEARCH)
    user: User = getattr(team, who)

    response = await (await api(user)).post(f"/ideas/{idea.id}/status", _move(S.EVALUATING))

    body = assert_problem(response, 409, "research_incomplete")
    assert body["can_override"] is (who != "owner")


async def test_research_needs_the_step(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await _idea(db_session, team)

    response = await (await api(team.owner)).post(f"/ideas/{idea.id}/status", _move(S.RESEARCH))

    assert_problem(response, 409, "research_step_off")


async def test_with_the_step_off_nothing_is_guarded(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.OFF)  # a checklist kept, hidden
    idea = await _idea(db_session, team)

    response = await (await api(team.owner)).post(f"/ideas/{idea.id}/status", _move(S.PROPOSAL))

    assert ok(response)["status"] == "proposal"


async def test_an_all_optional_checklist_never_blocks(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(
        db_session,
        team.project,
        ResearchStep.BEFORE_EVALUATION,
        [("Similar work", "", False), ("Who you asked", "", False)],
    )
    idea = await _idea(db_session, team)

    response = await (await api(team.owner)).post(f"/ideas/{idea.id}/status", _move(S.EVALUATING))

    assert ok(response)["status"] == "evaluating"


async def test_the_409_lists_exactly_the_open_required_items(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.RESEARCH)
    await answer(db_session, idea, items[0], team.owner)
    await answer(db_session, idea, items[2], team.owner)  # the optional one

    response = await (await api(team.owner)).post(f"/ideas/{idea.id}/status", _move(S.EVALUATING))

    body = assert_problem(response, 409, "research_incomplete")
    assert body["open_items"] == [{"item_id": str(items[1].id), "title": items[1].title}]
    assert body["detail"] == "Finish the research checklist first: 1 required item is open."


async def test_clearing_an_answer_rearms_the_gate_but_never_moves_the_idea(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.RESEARCH)
    await answer_required(db_session, idea, items, team.owner)
    olive = await api(team.owner)
    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.EVALUATING)))
    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.RESEARCH)))  # back: never guarded

    ok(await olive.delete(f"/ideas/{idea.id}/research/items/{items[0].id}"))
    response = await olive.post(f"/ideas/{idea.id}/status", _move(S.EVALUATING))

    assert_problem(response, 409, "research_incomplete")
    await db_session.refresh(idea)
    assert idea.status is S.RESEARCH


async def test_changing_the_checklist_never_moves_an_idea_past_research(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    passed = await _idea(db_session, team, S.EVALUATING)  # passed before the item existed
    ada = await api(team.admin)
    body = {
        "step": "before_evaluation",
        "items": [
            *({"id": str(item.id), "title": item.title, "required": True} for item in items),
            {"title": "Security reviewed", "required": True},
        ],
    }

    ok(await ada.put(f"/projects/{team.slug}/research", body))
    shortlisted = await (await api(team.owner)).post(
        f"/ideas/{passed.id}/status", _move(S.SHORTLISTED)
    )

    await db_session.refresh(passed)
    assert ok(shortlisted)["status"] == "shortlisted"  # moving among gated statuses: free


# --- Reopening a closed idea (REOPEN_CASES through the API) ------------------------------
async def test_undo_of_a_close_works_for_an_idea_past_research(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.EVALUATING)  # e.g. past it before the step
    olive = await api(team.owner)

    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.CLOSED)))
    undo = await olive.post(f"/ideas/{idea.id}/status", _move(S.EVALUATING))

    assert ok(undo)["status"] == "evaluating"


async def test_a_re_resolution_keeps_the_status_it_was_closed_from(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    idea = await _idea(db_session, team, S.PROPOSAL)
    olive = await api(team.owner)
    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.CLOSED, resolution="accepted")))
    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.CLOSED, resolution="parked")))

    reopened = await olive.post(f"/ideas/{idea.id}/status", _move(S.PROPOSAL))

    assert ok(reopened)["status"] == "proposal"


@pytest.mark.parametrize("closed_from", [S.NEW, S.RESEARCH])
async def test_closing_from_before_research_does_not_skip_the_check(
    api: AsUser, team: Team, db_session: AsyncSession, closed_from: IdeaStatus
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, closed_from)
    olive = await api(team.owner)
    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.CLOSED)))

    response = await olive.post(f"/ideas/{idea.id}/status", _move(S.EVALUATING))
    back = await olive.post(f"/ideas/{idea.id}/status", _move(closed_from))

    assert_problem(response, 409, "research_incomplete")
    assert ok(back)["status"] == closed_from.value  # reopening into it is never guarded


async def test_a_closed_idea_without_history_counts_as_new(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.CLOSED)  # no status_changed event at all

    response = await (await api(team.owner)).post(f"/ideas/{idea.id}/status", _move(S.EVALUATING))

    assert_problem(response, 409, "research_incomplete")


async def test_an_idea_moved_on_anyway_reopens_freely_for_its_owner(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.RESEARCH)
    ok(
        await (await api(team.admin)).post(
            f"/ideas/{idea.id}/status", _move(S.EVALUATING, override_research=True)
        )
    )
    olive = await api(team.owner)
    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.CLOSED)))

    undo = await olive.post(f"/ideas/{idea.id}/status", _move(S.EVALUATING))

    assert ok(undo)["status"] == "evaluating"


# --- Move anyway --------------------------------------------------------------------------
@pytest.mark.parametrize("who", ["admin", "platform"])
async def test_admins_move_anyway_audited(
    api: AsUser, team: Team, db_session: AsyncSession, who: str
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.RESEARCH)
    user: User = getattr(team, who)

    moved = await (await api(user)).post(
        f"/ideas/{idea.id}/status",
        _move(S.EVALUATING, override_research=True, override_reason="Legal said yes by phone"),
    )

    assert ok(moved)["status"] == "evaluating"
    [entry] = await _audits(db_session, "idea.research_override")
    assert entry.actor_id == user.id
    assert (entry.target_type, entry.target_id, entry.project_id) == (
        "idea",
        idea.id,
        team.project.id,
    )
    assert {key: value for key, value in entry.details.items() if not key.startswith("auth")} == {
        "rule": "idea.research_override",
        "operation": "change_idea_status",
        "from_status": "research",
        "to_status": "evaluating",
        "open_items": 2,
        "reason": "Legal said yes by phone",
    }
    [event] = await _status_events(db_session, idea)
    assert event["research_overridden"] is True
    feed = ok(await (await api(team.member)).get(f"/ideas/{idea.id}/activity"))
    assert [
        item["research_overridden"] for item in feed["items"] if item["type"] == "status_changed"
    ] == [True]


async def test_the_override_is_ignored_when_nothing_blocks(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.RESEARCH)
    await answer_required(db_session, idea, items, team.owner)

    moved = await (await api(team.admin)).post(
        f"/ideas/{idea.id}/status", _move(S.EVALUATING, override_research=True)
    )

    assert ok(moved)["status"] == "evaluating"
    assert await _audits(db_session, "idea.research_override") == []
    [event] = await _status_events(db_session, idea)
    assert "research_overridden" not in event


@pytest.mark.parametrize("blocking", [True, False])
async def test_owners_may_not_move_anyway_even_when_nothing_would_block(
    api: AsUser, team: Team, db_session: AsyncSession, blocking: bool
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.RESEARCH)
    if not blocking:
        await answer_required(db_session, idea, items, team.owner)

    response = await (await api(team.owner)).post(
        f"/ideas/{idea.id}/status", _move(S.EVALUATING, override_research=True)
    )

    assert_problem(response, 403, "forbidden")
    await db_session.refresh(idea)
    assert idea.status is S.RESEARCH


async def test_the_override_403_comes_before_the_requests_409s(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team)
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(held_for=HoldReason.MODERATION)
    )
    await db_session.commit()

    owner = await (await api(team.owner)).post(
        f"/ideas/{idea.id}/status", _move(S.EVALUATING, override_research=True)
    )
    admin = await (await api(team.admin)).post(
        f"/ideas/{idea.id}/status", _move(S.EVALUATING, override_research=True)
    )

    assert_problem(owner, 404, "not_found")  # held: only admins see it (c12)
    assert_problem(admin, 409, "awaiting_moderation")


# --- API keys -------------------------------------------------------------------------------
async def test_a_write_key_is_gated_and_can_never_move_anyway(
    app: FastAPI, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.RESEARCH)
    secret = await make_key(db_session, team.admin, scopes=["read", "write"])
    url = f"/api/v1/ideas/{idea.id}/status"

    async with key_client(app, secret) as client:
        gated = await client.post(url, json=_move(S.EVALUATING))
        anyway = await client.post(url, json=_move(S.EVALUATING, override_research=True))

    body = assert_problem(gated, 409, "research_incomplete")
    assert body["can_override"] is False  # session only
    assert_problem(anyway, 403, "insufficient_scope")


# --- Evaluator invites --------------------------------------------------------------------
async def test_the_first_invite_starts_evaluation_and_is_guarded(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.RESEARCH)
    olive = await api(team.owner)
    body = {"user_ids": [str(team.evaluators[0].id)]}

    detail = ok(await olive.get(f"/ideas/{idea.id}"))
    refused = await olive.post(f"/ideas/{idea.id}/evaluators", body)

    assert detail["permissions"]["invite_blocked_by_research"] is True
    problem = assert_problem(refused, 409, "research_incomplete")
    assert problem["can_override"] is False
    assert (
        await db_session.scalar(
            select(IdeaEvaluator.user_id).where(IdeaEvaluator.idea_id == idea.id)
        )
        is None
    )


async def test_later_invites_are_not_guarded(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.NEW)
    await add_evaluator(db_session, idea, team.evaluators[0])  # e.g. before the step
    olive = await api(team.owner)

    detail = ok(await olive.get(f"/ideas/{idea.id}"))
    invited = await olive.post(
        f"/ideas/{idea.id}/evaluators", {"user_ids": [str(team.evaluators[1].id)]}
    )

    assert detail["permissions"]["invite_blocked_by_research"] is False
    assert len(ok(invited)["evaluators"]) == 2


async def test_invites_are_free_before_a_proposal_step(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    idea = await _idea(db_session, team, S.NEW)

    invited = await (await api(team.owner)).post(
        f"/ideas/{idea.id}/evaluators", {"user_ids": [str(team.evaluators[0].id)]}
    )

    assert len(ok(invited)["evaluators"]) == 1


async def test_an_admin_invites_anyway_audited(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.NEW)
    body = {"user_ids": [str(team.evaluators[0].id)], "override_research": True}

    invited = await (await api(team.admin)).post(f"/ideas/{idea.id}/evaluators", body)
    owner = await (await api(team.owner)).post(
        f"/ideas/{idea.id}/evaluators",
        {"user_ids": [str(team.evaluators[1].id)], "override_research": True},
    )

    assert len(ok(invited)["evaluators"]) == 1
    [entry] = await _audits(db_session, "idea.research_override")
    assert entry.details["operation"] == "add_evaluators"
    assert entry.details["open_items"] == 2
    assert_problem(owner, 403, "forbidden")


async def test_an_answered_checklist_lets_the_first_invite_through(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.RESEARCH)
    await answer_required(db_session, idea, items, team.owner)

    invited = await (await api(team.owner)).post(
        f"/ideas/{idea.id}/evaluators", {"user_ids": [str(team.evaluators[0].id)]}
    )

    assert len(ok(invited)["evaluators"]) == 1


# --- Starting a proposal --------------------------------------------------------------------
@pytest.mark.parametrize("status", [S.SHORTLISTED, S.RESEARCH])
async def test_starting_a_proposal_is_guarded_before_a_proposal_step(
    api: AsUser, team: Team, db_session: AsyncSession, status: IdeaStatus
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    idea = await _idea(db_session, team, status)
    olive = await api(team.owner)

    view = ok(await olive.get(f"/ideas/{idea.id}/proposal"))
    refused = await olive.post(f"/ideas/{idea.id}/proposal")

    assert view["permissions"]["can_create"] is True  # c7 allows Research here
    assert view["permissions"]["start_blocked_by_research"] is True
    assert_problem(refused, 409, "research_incomplete")
    assert ok(await olive.get(f"/ideas/{idea.id}/proposal"))["proposal"] is None


@pytest.mark.parametrize("status", [S.SHORTLISTED, S.RESEARCH])
async def test_an_answered_checklist_starts_the_proposal_and_moves_the_idea(
    api: AsUser, team: Team, db_session: AsyncSession, status: IdeaStatus
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    idea = await _idea(db_session, team, status)
    await answer_required(db_session, idea, items, team.owner)

    view = ok(await (await api(team.owner)).post(f"/ideas/{idea.id}/proposal"), 201)

    assert view["proposal"] is not None
    assert view["permissions"]["start_blocked_by_research"] is False
    await db_session.refresh(idea)
    assert idea.status is S.PROPOSAL


async def test_an_admin_starts_anyway_with_one_audit_entry(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    idea = await _idea(db_session, team, S.RESEARCH)

    started = await (await api(team.admin)).post(
        f"/ideas/{idea.id}/proposal", {"override_research": True, "override_reason": "Board ask"}
    )

    assert ok(started, 201)["proposal"] is not None
    [entry] = await _audits(db_session, "idea.research_override")
    assert entry.details["operation"] == "create_proposal"
    assert (entry.details["from_status"], entry.details["to_status"]) == ("research", "proposal")
    assert entry.details["reason"] == "Board ask"
    [event] = await _status_events(db_session, idea)
    assert event["research_overridden"] is True
    assert len(await _audits(db_session, "idea.status_change")) == 1


async def test_an_owner_may_not_start_anyway(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    idea = await _idea(db_session, team, S.SHORTLISTED)

    response = await (await api(team.owner)).post(
        f"/ideas/{idea.id}/proposal", {"override_research": True}
    )

    assert_problem(response, 403, "forbidden")


async def test_a_research_step_before_evaluation_doesnt_guard_proposals(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.SHORTLISTED)  # already past Research

    view = ok(await (await api(team.owner)).post(f"/ideas/{idea.id}/proposal"), 201)

    assert view["proposal"] is not None
    research = await (await api(team.owner)).post(
        f"/ideas/{key_of(team.project, idea)}/status", _move(S.RESEARCH)
    )
    assert ok(research)["status"] == "research"
    again = await (await api(team.owner)).get(f"/ideas/{idea.id}/proposal")
    assert ok(again)["permissions"]["can_edit"] is False  # c7: Research before evaluation


async def test_proposal_exists_comes_before_the_gate(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.OFF)
    idea = await _idea(db_session, team, S.SHORTLISTED)
    olive = await api(team.owner)
    ok(await olive.post(f"/ideas/{idea.id}/proposal"), 201)
    await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    await db_session.execute(update(Idea).where(Idea.id == idea.id).values(status=S.RESEARCH))
    await db_session.commit()

    response = await olive.post(f"/ideas/{idea.id}/proposal")

    assert_problem(response, 409, "proposal_exists")


# --- Concurrency ------------------------------------------------------------------------------
async def test_an_answer_and_a_move_on_the_same_idea_serialise(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """The move and the answers each hold the idea's lock: the move sees the checklist
    either before (refused) or after (allowed) the last answer, never half of it."""
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await _idea(db_session, team, S.RESEARCH)
    await answer(db_session, idea, items[0], team.owner)
    olive, ada = await api(team.owner), await api(team.admin)

    answered, moved = await asyncio.gather(
        ada.put(
            f"/ideas/{idea.id}/research/items/{items[1].id}",
            {"answer": "Finance and Legal, 2 Oct: no objections."},
        ),
        olive.post(f"/ideas/{idea.id}/status", _move(S.EVALUATING)),
    )

    ok(answered)
    await db_session.refresh(idea)
    if moved.status_code == 200:
        assert idea.status is S.EVALUATING
    else:
        assert_problem(moved, 409, "research_incomplete")
        assert idea.status is S.RESEARCH
    count = await db_session.scalar(
        select(ResearchAnswer.item_id).where(
            ResearchAnswer.idea_id == idea.id, ResearchAnswer.item_id == items[1].id
        )
    )
    assert count == items[1].id
