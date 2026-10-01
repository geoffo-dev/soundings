"""Evaluators, the due date, closing evaluation (contract section 3.5), your own
evaluation (3.6), the evaluations list and the aggregate (3.8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent, AuditLog
from app.models.base import utcnow
from app.models.enums import EvaluatorState, IdeaStatus, ProjectRole, Recommendation
from app.models.evaluation import Evaluation, EvaluationScore
from app.models.idea import Idea, IdeaEvaluator, IdeaWatcher
from app.models.project import ProjectMember
from tests.factories import add_evaluator, add_member, make_idea, make_project, make_user
from tests.ideas.conftest import AsUser, Team, assert_problem, full_scores, ok


async def feed(db: AsyncSession, idea: Idea | str) -> list[tuple[str, dict[str, Any]]]:
    idea_id = idea.id if isinstance(idea, Idea) else idea
    rows = await db.execute(
        select(ActivityEvent.type, ActivityEvent.payload)
        .where(ActivityEvent.idea_id == idea_id)
        .order_by(ActivityEvent.created_at, ActivityEvent.id)
    )
    return [(type_, payload) for type_, payload in rows]


async def cached(db: AsyncSession, idea: Idea) -> tuple[Decimal | None, int, bool]:
    fresh = await db.get(Idea, idea.id, populate_existing=True)
    assert fresh is not None
    return fresh.aggregate_score, fresh.aggregate_count, fresh.high_disagreement


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def days_ahead(days: int, hour: int = 17) -> datetime:
    """A due date ``days`` from today at ``hour`` UTC (due dates must be near now)."""
    return (utcnow() + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)


# --- Invite ----------------------------------------------------------------------------------
async def test_first_invite_adds_evaluators_and_the_default_due_date(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)
    olive = await api(team.owner)  # the owner manages evaluators
    eve1, eve2 = team.evaluators[:2]

    detail = ok(
        await olive.post(
            f"/ideas/{idea.id}/evaluators", {"user_ids": [str(eve1.id), str(eve2.id), str(eve1.id)]}
        )
    )

    assert [e["user"]["id"] for e in detail["evaluators"]] == [str(eve1.id), str(eve2.id)]
    assert {e["state"] for e in detail["evaluators"]} == {"invited"}
    assert all(e["is_ai"] is False and e["submitted_at"] is None for e in detail["evaluators"])
    assert detail["evaluator_progress"] == {"submitted": 0, "total": 2}
    due = parse(detail["evaluation_due_at"])
    assert timedelta(days=7) - timedelta(minutes=1) < due - datetime.now(UTC) <= timedelta(days=7)
    assert await feed(db_session, idea) == [
        ("evaluator_added", {"evaluator_id": str(eve1.id)}),
        ("evaluator_added", {"evaluator_id": str(eve2.id)}),
    ]  # the default due date is not an event
    watching = set(await db_session.scalars(select(IdeaWatcher.user_id)))
    assert watching == {eve1.id, eve2.id}
    audited = await db_session.scalars(
        select(AuditLog.target_id).where(AuditLog.action == "evaluator.add")
    )
    assert set(audited) == {eve1.id, eve2.id}


async def test_later_invites_never_touch_the_due_date(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    ada = await api(team.admin)
    eve1, eve2, eve3 = team.evaluators

    ok(await ada.post(f"/ideas/{idea.id}/evaluators", {"user_ids": [str(eve1.id)]}))
    cleared = ok(await ada.put(f"/ideas/{idea.id}/evaluation/due-date", {"due_at": None}))
    again = ok(await ada.post(f"/ideas/{idea.id}/evaluators", {"user_ids": [str(eve2.id)]}))

    assert cleared["evaluation_due_at"] is None
    assert again["evaluation_due_at"] is None  # a cleared date stays cleared
    # Already assigned users are skipped (no second event).
    ok(await ada.post(f"/ideas/{idea.id}/evaluators", {"user_ids": [str(eve1.id), str(eve3.id)]}))
    added = [p["evaluator_id"] for t, p in await feed(db_session, idea) if t == "evaluator_added"]
    assert added == [str(eve1.id), str(eve2.id), str(eve3.id)]


async def test_first_invite_keeps_an_existing_due_date(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    ada = await api(team.admin)
    due = days_ahead(60)
    ok(await ada.put(f"/ideas/{idea.id}/evaluation/due-date", {"due_at": iso(due)}))

    detail = ok(
        await ada.post(f"/ideas/{idea.id}/evaluators", {"user_ids": [str(team.evaluators[0].id)]})
    )

    assert parse(detail["evaluation_due_at"]) == due


async def test_invite_with_a_due_date(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project)
    ada = await api(team.admin)
    due = days_ahead(7)
    in_paris = due.astimezone(timezone(timedelta(hours=2))).isoformat()  # "…T19:00:00+02:00"
    body = {"user_ids": [str(team.evaluators[0].id)], "due_at": in_paris}

    detail = ok(await ada.post(f"/ideas/{idea.id}/evaluators", body))
    ok(await ada.post(f"/ideas/{idea.id}/evaluators", body))  # same date again: no event

    assert parse(detail["evaluation_due_at"]) == due
    changes = [p for t, p in await feed(db_session, idea) if t == "due_date_changed"]
    assert changes == [{"from_due_at": None, "to_due_at": due.isoformat()}]


async def test_one_ineligible_user_fails_the_whole_invite(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    inactive = await make_user(db_session, "Ina Active", active=False)
    await add_member(db_session, team.project, inactive, ProjectRole.MEMBER)
    ada = await api(team.admin)

    for ineligible in (team.viewer, team.outsider, team.platform, inactive):
        body = {"user_ids": [str(team.evaluators[0].id), str(ineligible.id)]}
        response = await ada.post(f"/ideas/{idea.id}/evaluators", body)
        assert_problem(response, 422, "assignee_not_eligible")
    body = {"user_ids": [str(uuid4())]}
    assert_problem(
        await ada.post(f"/ideas/{idea.id}/evaluators", body), 422, "assignee_not_eligible"
    )
    assert await db_session.scalar(select(func.count()).select_from(IdeaEvaluator)) == 0
    # Admins may evaluate (they hold a real role).
    ok(await ada.post(f"/ideas/{idea.id}/evaluators", {"user_ids": [str(team.admin.id)]}))


async def test_who_may_invite(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)
    body = {"user_ids": [str(team.evaluators[0].id)]}
    path = f"/ideas/{idea.id}/evaluators"

    assert_problem(await (await api(team.member)).post(path, body), 403, "forbidden")
    assert_problem(await (await api(team.viewer)).post(path, body), 403, "forbidden")
    assert_problem(await (await api(team.outsider)).post(path, body), 404, "not_found")
    ok(await (await api(team.platform)).post(path, body))


async def test_invite_needs_an_open_evaluation(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    ada = await api(team.admin)
    body = {"user_ids": [str(team.evaluators[0].id)]}

    ok(await ada.post(f"/ideas/{idea.id}/evaluation/close"))
    assert_problem(await ada.post(f"/ideas/{idea.id}/evaluators", body), 409, "evaluation_closed")
    ok(await ada.post(f"/ideas/{idea.id}/evaluation/reopen"))
    ok(await ada.post(f"/ideas/{idea.id}/status", {"status": "closed", "resolution": "rejected"}))
    assert_problem(await ada.post(f"/ideas/{idea.id}/evaluators", body), 409, "evaluation_closed")
    # c4 (422) is checked before c6 (409).
    ineligible = {"user_ids": [str(team.viewer.id)]}
    assert_problem(
        await ada.post(f"/ideas/{idea.id}/evaluators", ineligible), 422, "assignee_not_eligible"
    )


async def test_invite_validation(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project)
    ada = await api(team.admin)

    body: dict[str, Any]
    for body in (
        {"user_ids": []},
        {"user_ids": [str(uuid4()) for _ in range(21)]},
        {"user_ids": [str(team.member.id)], "due_at": "2026-10-07T17:00:00"},  # no offset
    ):
        assert_problem(
            await ada.post(f"/ideas/{idea.id}/evaluators", body), 422, "validation_error"
        )


# --- Remove ----------------------------------------------------------------------------------
async def test_remove_an_evaluator_and_their_draft(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)
    eve1, eve2 = team.evaluators[:2]
    await add_evaluator(db_session, idea, eve1, state=EvaluatorState.DRAFT, scores={"Value": 2})
    await add_evaluator(db_session, idea, eve2)
    olive = await api(team.owner)

    detail = ok(await olive.delete(f"/ideas/{idea.id}/evaluators/{eve1.id}"))

    assert [e["user"]["id"] for e in detail["evaluators"]] == [str(eve2.id)]
    assert await db_session.scalar(select(func.count()).select_from(Evaluation)) == 0
    assert await feed(db_session, idea) == [("evaluator_removed", {"evaluator_id": str(eve1.id)})]
    audited = await db_session.scalar(
        select(AuditLog.target_id).where(AuditLog.action == "evaluator.remove")
    )
    assert audited == eve1.id
    assert_problem(await olive.delete(f"/ideas/{idea.id}/evaluators/{eve1.id}"), 404, "not_found")


async def test_remove_rules(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)
    eve1, eve2 = team.evaluators[:2]
    await add_evaluator(db_session, idea, eve1, state=EvaluatorState.SUBMITTED)
    await add_evaluator(db_session, idea, eve2)
    await add_evaluator(db_session, idea, team.admin)
    ada = await api(team.admin)

    assert_problem(
        await ada.delete(f"/ideas/{idea.id}/evaluators/{eve1.id}"), 409, "evaluator_has_submitted"
    )
    assert_problem(
        await ada.delete(f"/ideas/{idea.id}/evaluators/{team.admin.id}"), 403, "cannot_remove_self"
    )
    assert_problem(await ada.delete(f"/ideas/{idea.id}/evaluators/{uuid4()}"), 404, "not_found")
    # Members (the evaluator themselves included) may not manage evaluators at all.
    for user in (team.member, eve2, team.viewer):
        response = await (await api(user)).delete(f"/ideas/{idea.id}/evaluators/{eve2.id}")
        assert_problem(response, 403, "forbidden")
    # Removal works when evaluation is closed, and when the idea is closed.
    ok(await ada.post(f"/ideas/{idea.id}/evaluation/close"))
    ok(await ada.post(f"/ideas/{idea.id}/status", {"status": "closed", "resolution": "parked"}))
    detail = ok(await ada.delete(f"/ideas/{idea.id}/evaluators/{eve2.id}"))
    assert {e["user"]["id"] for e in detail["evaluators"]} == {str(eve1.id), str(team.admin.id)}
    assert detail["permissions"]["can_remove_evaluators"] is True
    assert detail["permissions"]["can_invite_evaluators"] is False


# --- Due date, close and reopen --------------------------------------------------------------
async def test_due_date(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)
    olive = await api(team.owner)
    due = days_ahead(7)

    set_ = ok(await olive.put(f"/ideas/{idea.id}/evaluation/due-date", {"due_at": iso(due)}))
    ok(await olive.put(f"/ideas/{idea.id}/evaluation/due-date", {"due_at": iso(due)}))
    cleared = ok(await olive.put(f"/ideas/{idea.id}/evaluation/due-date", {"due_at": None}))

    assert parse(set_["evaluation_due_at"]) == due
    assert cleared["evaluation_due_at"] is None
    assert await feed(db_session, idea) == [
        ("due_date_changed", {"from_due_at": None, "to_due_at": due.isoformat()}),
        ("due_date_changed", {"from_due_at": due.isoformat(), "to_due_at": None}),
    ]
    path = f"/ideas/{idea.id}/evaluation/due-date"
    assert_problem(await (await api(team.member)).put(path, {"due_at": None}), 403, "forbidden")
    assert_problem(await olive.put(path, {}), 422, "validation_error")  # required
    assert_problem(await olive.put(path, {"due_at": "2026-10-07"}), 422, "validation_error")
    ok(await olive.post(f"/ideas/{idea.id}/evaluation/close"))
    assert_problem(await olive.put(path, {"due_at": None}), 409, "evaluation_closed")


@pytest.mark.parametrize(
    "due_at",
    [
        # Code review F5: these overflowed in astimezone(UTC) (500) or were stored as-is.
        "0001-01-01T00:00:00+05:00",
        "9999-12-31T23:59:00-05:00",
        "0001-01-01T00:00:00Z",
        "9999-12-31T23:59:59Z",
        "far-past",
        "far-future",
    ],
)
async def test_due_dates_outside_a_sane_window_are_a_422(
    api: AsUser, team: Team, db_session: AsyncSession, due_at: str
) -> None:
    """A due date is at most a year in the past and five years ahead (both routes)."""
    if due_at == "far-past":
        due_at = iso(utcnow() - timedelta(days=367))
    elif due_at == "far-future":
        due_at = iso(utcnow() + timedelta(days=5 * 366 + 1))
    idea = await make_idea(db_session, team.project, owner=team.owner)
    olive = await api(team.owner)

    response = await olive.put(f"/ideas/{idea.id}/evaluation/due-date", {"due_at": due_at})
    body = assert_problem(response, 422, "validation_error")
    assert body["errors"][0]["loc"] == ["body", "due_at"]
    invite = {"user_ids": [str(team.evaluators[0].id)], "due_at": due_at}
    response = await olive.post(f"/ideas/{idea.id}/evaluators", invite)
    assert_problem(response, 422, "validation_error")
    assert await feed(db_session, idea) == []


async def test_due_dates_inside_the_window_are_fine(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)
    olive = await api(team.owner)
    path = f"/ideas/{idea.id}/evaluation/due-date"

    for due in (utcnow() - timedelta(days=360), utcnow() + timedelta(days=5 * 365 - 1)):
        detail = ok(await olive.put(path, {"due_at": iso(due)}))
        assert parse(detail["evaluation_due_at"]) == due


async def test_close_and_reopen_are_idempotent(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)
    await add_evaluator(db_session, idea, team.evaluators[0])
    olive = await api(team.owner)

    closed = ok(await olive.post(f"/ideas/{idea.id}/evaluation/close"))
    ok(await olive.post(f"/ideas/{idea.id}/evaluation/close"))
    eve = await api(team.evaluators[0])
    blocked = await eve.put(f"/ideas/{idea.id}/evaluations/me", {"scores": [], "submit": False})
    mine = ok(await eve.get(f"/ideas/{idea.id}/evaluations/me"))
    reopened = ok(await olive.post(f"/ideas/{idea.id}/evaluation/reopen"))
    ok(await olive.post(f"/ideas/{idea.id}/evaluation/reopen"))

    assert closed["evaluation_closed_at"] is not None
    assert closed["evaluation_open"] is False
    assert closed["permissions"]["can_close_evaluation"] is True
    assert_problem(blocked, 409, "evaluation_closed")
    assert mine["editable"] is False
    assert (reopened["evaluation_closed_at"], reopened["evaluation_open"]) == (None, True)
    assert [t for t, _ in await feed(db_session, idea)] == [
        "evaluation_closed",
        "evaluation_reopened",
    ]


async def test_close_and_reopen_are_audited_once_each(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """Closing and reopening evaluation are audited (the no-op repeats are not)."""
    idea = await make_idea(db_session, team.project, owner=team.owner)
    olive = await api(team.owner)

    ok(await olive.post(f"/ideas/{idea.id}/evaluation/close"))
    ok(await olive.post(f"/ideas/{idea.id}/evaluation/close"))
    ok(await olive.post(f"/ideas/{idea.id}/evaluation/reopen"))
    ok(await olive.post(f"/ideas/{idea.id}/evaluation/reopen"))

    rows = (
        await db_session.execute(
            select(
                AuditLog.action,
                AuditLog.actor_id,
                AuditLog.target_type,
                AuditLog.target_id,
                AuditLog.project_id,
                AuditLog.details,
            )
            .where(AuditLog.action.in_(("evaluation.close", "evaluation.reopen")))
            .order_by(AuditLog.created_at, AuditLog.id)
        )
    ).all()
    assert [row.action for row in rows] == ["evaluation.close", "evaluation.reopen"]
    for row in rows:
        assert (row.actor_id, row.target_type, row.target_id, row.project_id) == (
            team.owner.id,
            "idea",
            idea.id,
            idea.project_id,
        )
        assert row.details["rule"] == "evaluation.close"


async def test_close_rules(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project, status=IdeaStatus.CLOSED)
    ada = await api(team.admin)

    assert_problem(await ada.post(f"/ideas/{idea.id}/evaluation/close"), 409, "idea_closed")
    assert_problem(await ada.post(f"/ideas/{idea.id}/evaluation/reopen"), 409, "idea_closed")
    open_idea = await make_idea(db_session, team.project)
    for user, code in ((team.member, 403), (team.viewer, 403), (team.outsider, 404)):
        response = await (await api(user)).post(f"/ideas/{open_idea.id}/evaluation/close")
        assert response.status_code == code


# --- My evaluation ---------------------------------------------------------------------------
async def test_my_evaluation_lifecycle(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project, status=IdeaStatus.EVALUATING)
    eve1 = team.evaluators[0]
    await add_evaluator(db_session, idea, eve1)
    eve = await api(eve1)
    value, feasibility = team.rubric[0], team.rubric[1]
    path = f"/ideas/{idea.id}/evaluations/me"

    invited = ok(await eve.get(path))
    draft = ok(
        await eve.put(
            path,
            {
                "scores": [
                    {"criterion_id": str(feasibility.id), "score": 2, "comment": "Hard."},
                    {"criterion_id": str(value.id), "score": None, "comment": "Unsure."},
                ],
                "recommendation": "maybe",
                "comment": "  First thoughts.  ",
                "submit": False,
            },
        )
    )
    last_activity = ok(await eve.get(f"/ideas/{idea.id}"))["last_activity_at"]
    replaced = ok(await eve.put(path, {"scores": [], "submit": False}))

    assert invited == {
        "idea_id": str(idea.id),
        "state": "invited",
        "editable": True,
        "due_at": None,
        "recommendation": None,
        "comment": "",
        "scores": [],
        "submitted_at": None,
        "updated_at": None,
    }
    assert draft["state"] == "draft"
    assert draft["scores"] == [  # rubric order
        {"criterion_id": str(value.id), "score": None, "comment": "Unsure."},
        {"criterion_id": str(feasibility.id), "score": 2, "comment": "Hard."},
    ]
    assert (draft["recommendation"], draft["comment"]) == ("maybe", "First thoughts.")
    assert draft["updated_at"] is not None
    assert draft["submitted_at"] is None
    # The body replaces what was saved.
    assert (replaced["scores"], replaced["recommendation"], replaced["comment"]) == ([], None, "")
    assert await feed(db_session, idea) == []  # drafts are not activity
    assert last_activity == ok(await eve.get(f"/ideas/{idea.id}"))["last_activity_at"]

    submitted = ok(
        await eve.put(
            path, {"scores": full_scores(team, 4), "recommendation": "go", "submit": True}
        )
    )

    assert submitted["state"] == "submitted"
    assert submitted["submitted_at"] is not None
    assert [s["score"] for s in submitted["scores"]] == [4] * len(team.rubric)
    assert await feed(db_session, idea) == [
        ("evaluation_submitted", {"evaluator_id": str(eve1.id)})
    ]
    # Effort and Risk are inverted: (4 + 4 + (6 - 4) + 4 + (6 - 4)) / 5 = 3.2.
    assert await cached(db_session, idea) == (Decimal("3.2"), 1, False)
    audited = await db_session.scalar(
        select(AuditLog.target_id).where(AuditLog.action == "evaluation.submit")
    )
    assert audited == idea.id


async def test_submitted_evaluations_can_be_edited_until_closed(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    eve1 = team.evaluators[0]
    await add_evaluator(db_session, idea, eve1)
    eve = await api(eve1)
    path = f"/ideas/{idea.id}/evaluations/me"
    first = ok(
        await eve.put(
            path, {"scores": full_scores(team, 3), "recommendation": "go", "submit": True}
        )
    )

    edited = ok(
        await eve.put(
            path, {"scores": full_scores(team, 5), "recommendation": "no", "submit": True}
        )
    )
    back_to_draft = await eve.put(path, {"scores": full_scores(team, 5), "submit": False})

    assert edited["submitted_at"] == first["submitted_at"]
    assert edited["state"] == "submitted"
    assert_problem(back_to_draft, 409, "evaluation_already_submitted")
    [listed] = ok(await eve.get(f"/ideas/{idea.id}/evaluations"))["items"]
    assert listed["edited_at"] is not None
    assert listed["recommendation"] == "no"
    assert [t for t, _ in await feed(db_session, idea)] == ["evaluation_submitted"]
    # Inverted criteria (Effort, Risk) count 6 - 5 = 1: (5 + 5 + 1 + 5 + 1) / 5 = 3.4.
    assert await cached(db_session, idea) == (Decimal("3.4"), 1, False)
    # Reopening keeps it submitted.
    ada = await api(team.admin)
    ok(await ada.post(f"/ideas/{idea.id}/evaluation/close"))
    assert_problem(
        await eve.put(
            path, {"scores": full_scores(team, 4), "recommendation": "go", "submit": True}
        ),
        409,
        "evaluation_closed",
    )
    ok(await ada.post(f"/ideas/{idea.id}/evaluation/reopen"))
    assert ok(await eve.get(path))["state"] == "submitted"


async def test_incomplete_submissions_list_every_gap(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    await add_evaluator(db_session, idea, team.evaluators[0])
    eve = await api(team.evaluators[0])
    scores = full_scores(team, 3)
    scores[1]["score"] = None
    del scores[3]

    response = await eve.put(f"/ideas/{idea.id}/evaluations/me", {"scores": scores, "submit": True})

    body = assert_problem(response, 422, "evaluation_incomplete")
    missing_score = {"msg": "Score this criterion.", "type": "missing"}
    assert body["errors"] == [
        {"loc": ["body", "scores", str(team.rubric[1].id)], **missing_score},
        {"loc": ["body", "scores", str(team.rubric[3].id)], **missing_score},
        {"loc": ["body", "recommendation"], "msg": "Choose a recommendation.", "type": "missing"},
    ]
    assert await db_session.scalar(select(func.count()).select_from(Evaluation)) == 0


async def test_unknown_and_archived_criteria_are_refused(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    other = await make_project(db_session, members={team.admin: ProjectRole.ADMIN})
    idea = await make_idea(db_session, team.project)
    await add_evaluator(db_session, idea, team.evaluators[0])
    eve = await api(team.evaluators[0])
    path = f"/ideas/{idea.id}/evaluations/me"
    [foreign, *_] = await criteria_of(db_session, other.id)
    team.rubric[4].archived_at = utcnow()
    db_session.add(team.rubric[4])
    await db_session.commit()

    body: dict[str, Any]
    for criterion_id in (uuid4(), foreign, team.rubric[4].id):
        body = {"scores": [{"criterion_id": str(criterion_id), "score": 3}], "submit": False}
        assert_problem(await eve.put(path, body), 422, "unknown_criterion")
    for body in (
        {"scores": [{"criterion_id": str(team.rubric[0].id), "score": 6}]},
        {"scores": [{"criterion_id": str(team.rubric[0].id), "score": 3}] * 2},
        {"recommendation": "yes"},
    ):
        assert_problem(await eve.put(path, body), 422, "validation_error")


async def test_save_checks_422_before_409(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """The contract's check order ends 403, 422 business codes, 409: a closed evaluation
    still answers a bad body with its 422 (the code review's contract deviation)."""
    idea = await make_idea(db_session, team.project)
    await add_evaluator(db_session, idea, team.evaluators[0])
    ok(await (await api(team.admin)).post(f"/ideas/{idea.id}/evaluation/close"))
    eve = await api(team.evaluators[0])
    path = f"/ideas/{idea.id}/evaluations/me"

    unknown = {"scores": [{"criterion_id": str(uuid4()), "score": 3}], "submit": False}
    assert_problem(await eve.put(path, unknown), 422, "unknown_criterion")
    incomplete = {"scores": full_scores(team, 3)[:2], "submit": True}
    assert_problem(await eve.put(path, incomplete), 422, "evaluation_incomplete")
    complete = {"scores": full_scores(team, 3), "recommendation": "go", "submit": True}
    assert_problem(await eve.put(path, complete), 409, "evaluation_closed")
    # 403 still comes first: not an evaluator.
    assert_problem(await (await api(team.member)).put(path, unknown), 403, "forbidden")


async def criteria_of(db: AsyncSession, project_id: Any) -> list[Any]:
    from app.models.project import RubricCriterion

    return list(
        await db.scalars(
            select(RubricCriterion.id)
            .where(RubricCriterion.project_id == project_id)
            .order_by(RubricCriterion.position)
        )
    )


async def test_who_may_evaluate(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project)
    eve1 = team.evaluators[0]
    await add_evaluator(db_session, idea, eve1)
    path = f"/ideas/{idea.id}/evaluations/me"
    body = {"scores": [], "submit": False}

    # Not assigned: 403 to save, null to read.
    for user in (team.member, team.admin, team.platform, team.viewer):
        assert_problem(await (await api(user)).put(path, body), 403, "forbidden")
        assert ok(await (await api(user)).get(path)) is None
    assert_problem(await (await api(team.outsider)).get(path), 404, "not_found")
    # A demoted evaluator keeps the assignment but may not save.
    member = await db_session.get(ProjectMember, (team.project.id, eve1.id))
    assert member is not None
    member.role = ProjectRole.VIEWER
    await db_session.commit()
    eve = await api(eve1)
    assert_problem(await eve.put(path, body), 403, "forbidden")
    mine = ok(await eve.get(path))
    assert (mine["state"], mine["editable"]) == ("invited", False)


async def test_new_criteria_must_be_scored_on_the_next_save(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    await add_evaluator(db_session, idea, team.evaluators[0])
    eve = await api(team.evaluators[0])
    path = f"/ideas/{idea.id}/evaluations/me"
    old_scores = full_scores(team, 4)
    ok(await eve.put(path, {"scores": old_scores, "recommendation": "go", "submit": True}))
    rubric = [
        {"id": str(c.id), "name": c.name, "inverted": c.inverted} for c in team.rubric[:4]
    ] + [{"name": "Urgency"}]  # Risk is archived (scored), Urgency is new
    ok(await (await api(team.admin)).put(f"/projects/{team.slug}/rubric", {"criteria": rubric}))

    mine = ok(await eve.get(path))
    response = await eve.put(
        path, {"scores": old_scores[:4], "recommendation": "go", "submit": True}
    )

    assert mine["state"] == "submitted"
    assert [s["criterion_id"] for s in mine["scores"]] == [str(c.id) for c in team.rubric[:4]]
    body = assert_problem(response, 422, "evaluation_incomplete")
    assert len(body["errors"]) == 1
    # The archived Risk score stays stored.
    stored = await db_session.scalar(
        select(func.count())
        .select_from(EvaluationScore)
        .where(EvaluationScore.criterion_id == team.rubric[4].id)
    )
    assert stored == 1


# --- Evaluations list and the aggregate ------------------------------------------------------
async def test_evaluations_list_and_aggregate(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    agent = await make_user(db_session, "Scout Agent", service_account=True)
    await add_member(db_session, team.project, agent, ProjectRole.MEMBER)
    eve1, eve2, eve3 = team.evaluators
    await add_evaluator(db_session, idea, team.member)  # invited, never submits
    for user in team.evaluators:
        await add_evaluator(db_session, idea, user)
    await add_evaluator(
        db_session,
        idea,
        agent,
        state=EvaluatorState.SUBMITTED,
        scores=dict.fromkeys(("Value", "Feasibility", "Effort", "Strategic fit", "Risk"), 1),
        recommendation=Recommendation.NO,
        include_in_aggregate=False,
    )
    scores = {
        eve1: {"Value": 4, "Feasibility": 4, "Effort": 2, "Strategic_fit": 4, "Risk": 2},
        eve2: {"Value": 5, "Feasibility": 3, "Effort": 4, "Strategic_fit": 3, "Risk": 3},
        eve3: {"Value": 2, "Feasibility": 3, "Effort": 3, "Strategic_fit": 5, "Risk": 1},
    }
    recommendation = {eve1: "go", eve2: "maybe", eve3: "go"}
    for user in (eve1, eve2, eve3):
        body = {
            "scores": full_scores(team, **scores[user]),
            "recommendation": recommendation[user],
            "comment": f"From {user.display_name}",
            "submit": True,
        }
        ok(await (await api(user)).put(f"/ideas/{idea.id}/evaluations/me", body))

    listing = ok(await (await api(team.viewer)).get(f"/ideas/{idea.id}/evaluations"))
    detail = ok(await (await api(team.viewer)).get(f"/ideas/{idea.id}"))

    assert listing["score_hidden"] is False
    assert [e["evaluator"]["id"] for e in listing["items"]] == [
        str(agent.id), str(eve1.id), str(eve2.id), str(eve3.id)
    ]  # fmt: skip
    ai, first = listing["items"][0], listing["items"][1]
    assert (ai["is_ai"], ai["include_in_aggregate"]) == (True, False)
    assert (first["is_ai"], first["include_in_aggregate"]) == (False, True)
    assert first["comment"] == f"From {eve1.display_name}"
    assert first["edited_at"] is None
    assert [s["criterion_id"] for s in first["scores"]] == [str(c.id) for c in team.rubric]
    assert [s["score"] for s in first["scores"]] == [4, 4, 2, 4, 2]
    # Adjusted means 11/3, 10/3, 3, 4, 4 (Effort and Risk inverted) -> 18/5 = 3.6.
    assert detail["score"] == {"overall": 3.6, "count": 3}
    assert (detail["score_hidden"], detail["high_disagreement"]) == (False, True)
    aggregate = detail["aggregate"]
    assert (aggregate["overall"], aggregate["count"], aggregate["high_disagreement"]) == (
        3.6,
        3,
        True,
    )
    assert aggregate["recommendations"] == {"go": 2, "maybe": 1, "no": 0}  # AI excluded
    assert [
        (c["name"], c["mean"], c["min"], c["max"], c["spread"], c["count"], c["inverted"])
        for c in aggregate["criteria"]
    ] == [
        ("Value", 3.7, 2, 5, 3, 3, False),
        ("Feasibility", 3.3, 3, 4, 1, 3, False),
        ("Effort", 3.0, 2, 4, 2, 3, True),
        ("Strategic fit", 4.0, 3, 5, 2, 3, False),
        ("Risk", 2.0, 1, 3, 2, 3, True),
    ]
    assert aggregate["criteria"][0]["weight"] == 1.0
    assert detail["evaluator_progress"] == {"submitted": 4, "total": 5}
    assert await cached(db_session, idea) == (Decimal("3.6"), 3, True)


async def test_rubric_changes_recompute_the_aggregate(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    await add_evaluator(db_session, idea, team.evaluators[0])
    eve = await api(team.evaluators[0])
    body = {
        "scores": full_scores(team, 4, Effort=5, Risk=5),
        "recommendation": "go",
        "submit": True,
    }
    ok(await eve.put(f"/ideas/{idea.id}/evaluations/me", body))
    assert await cached(db_session, idea) == (Decimal("2.8"), 1, False)  # (4+4+1+4+1)/5

    # Drop Effort and Risk (archived: scored) and weight Value 3x.
    rubric = [
        {"id": str(team.rubric[0].id), "name": "Value", "weight": 3},
        {"id": str(team.rubric[1].id), "name": "Feasibility"},
        {"id": str(team.rubric[3].id), "name": "Strategic fit"},
    ]
    ok(await (await api(team.admin)).put(f"/projects/{team.slug}/rubric", {"criteria": rubric}))

    assert await cached(db_session, idea) == (Decimal("4.0"), 1, False)
    detail = ok(await eve.get(f"/ideas/{idea.id}"))
    assert [c["name"] for c in detail["aggregate"]["criteria"]] == [
        "Value", "Feasibility", "Strategic fit"
    ]  # fmt: skip
    [evaluation] = ok(await eve.get(f"/ideas/{idea.id}/evaluations"))["items"]
    assert len(evaluation["scores"]) == 3  # archived criteria are left out


async def test_no_submissions_no_aggregate(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    await add_evaluator(db_session, idea, team.evaluators[0], state=EvaluatorState.DRAFT)

    detail = ok(await (await api(team.viewer)).get(f"/ideas/{idea.id}"))
    listing = ok(await (await api(team.viewer)).get(f"/ideas/{idea.id}/evaluations"))

    assert (detail["score"], detail["aggregate"], detail["score_hidden"]) == (None, None, False)
    assert listing == {"items": [], "score_hidden": False}


async def test_evaluation_routes_need_view_access(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    otto = await api(team.outsider)

    assert_problem(await otto.get(f"/ideas/{idea.id}/evaluations"), 404, "not_found")
    assert_problem(await otto.get(f"/ideas/{idea.id}/evaluations/me"), 404, "not_found")
    assert_problem(
        await otto.put(f"/ideas/{idea.id}/evaluations/me", {"scores": [], "submit": False}),
        404,
        "not_found",
    )
