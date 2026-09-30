"""Shared services the ideas endpoints build on: activity events, the audit log and
the aggregate-score cache (contract sections 3.8 and 3.13)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.principal import Principal
from app.models.activity import ActivityEvent, AuditLog
from app.models.enums import EvaluatorState, IdeaStatus, ProjectRole, Recommendation
from app.models.idea import Idea
from app.schemas.activity import ACTIVITY_TYPES
from app.services import activity, audit
from app.services.activity import PAYLOAD_KEYS
from app.services.scoring import recompute_aggregates
from tests.factories import add_evaluator, make_idea, make_project, make_user


# --- Activity -------------------------------------------------------------------------------
async def test_emit_records_the_event_and_bumps_last_activity(db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    project = await make_project(db_session)
    idea = await make_idea(db_session, project, last_activity_at=datetime(2026, 1, 1, tzinfo=UTC))

    event = await activity.emit(
        db_session,
        idea,
        "status_changed",
        actor=Principal(user=ada),
        payload={
            "from_status": IdeaStatus.NEW,
            "from_resolution": None,
            "to_status": IdeaStatus.EVALUATING,
            "to_resolution": None,
        },
    )
    await db_session.commit()

    stored = await db_session.scalar(select(ActivityEvent).where(ActivityEvent.id == event.id))
    assert stored is not None
    assert (stored.project_id, stored.idea_id, stored.actor_id, stored.type) == (
        project.id,
        idea.id,
        ada.id,
        "status_changed",
    )
    assert stored.payload == {
        "from_status": "new",
        "from_resolution": None,
        "to_status": "evaluating",
        "to_resolution": None,
    }
    await db_session.refresh(idea)
    assert idea.last_activity_at == stored.created_at
    assert idea.last_activity_at > datetime.now(UTC) - timedelta(minutes=1)


async def test_emit_serialises_ids_and_dates(db_session: AsyncSession) -> None:
    project = await make_project(db_session)
    idea = await make_idea(db_session, project)
    someone = uuid4()
    due = datetime(2026, 10, 7, 17, tzinfo=UTC)

    added = await activity.emit(
        db_session, idea, "evaluator_added", actor=None, payload={"evaluator_id": someone}
    )
    dated = await activity.emit(
        db_session,
        idea,
        "due_date_changed",
        actor=None,
        payload={"from_due_at": None, "to_due_at": due},
    )

    assert added.payload == {"evaluator_id": str(someone)}
    assert dated.payload == {"from_due_at": None, "to_due_at": due.isoformat()}


@pytest.mark.parametrize(
    ("type_", "payload", "comment_id"),
    [
        ("vote_added", {}, None),  # not a Phase 1 type
        ("evaluation_submitted", {"evaluator_id": uuid4(), "score": 4}, None),  # never scores
        ("evaluation_submitted", {}, None),  # missing key
        ("idea_edited", {"fields": [1.5]}, None),  # not an id, date, flag or name
        ("comment", {}, None),  # comments need their comment_id
        ("idea_created", {}, uuid4()),  # only comments carry one
    ],
)
async def test_emit_refuses_what_the_feed_must_not_hold(
    db_session: AsyncSession, type_: str, payload: dict[str, object], comment_id: object
) -> None:
    project = await make_project(db_session)
    idea = await make_idea(db_session, project)

    with pytest.raises((ValueError, TypeError)):
        await activity.emit(
            db_session,
            idea,
            type_,
            actor=None,
            payload=payload,
            comment_id=comment_id,  # type: ignore[arg-type]
        )


def test_payload_keys_cover_every_activity_type() -> None:
    assert set(PAYLOAD_KEYS) == set(ACTIVITY_TYPES)
    assert not any("score" in key for keys in PAYLOAD_KEYS.values() for key in keys)


# --- Audit ----------------------------------------------------------------------------------
async def test_audit_record(db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    project = await make_project(db_session)

    await audit.record(
        db_session,
        "project.member_add",
        actor=Principal(user=ada),
        target_type="user",
        target_id=ada.id,
        project_id=project.id,
        details={"rule": "project.manage_members", "role": ProjectRole.VIEWER, "ids": {uuid4()}},
    )
    await db_session.commit()

    entry = await db_session.scalar(select(AuditLog))
    assert entry is not None
    assert entry.actor_id == ada.id
    assert entry.details["auth"] == "session"
    assert entry.details["role"] == "viewer"
    assert entry.details["rule"] == "project.manage_members"


async def test_audit_refuses_unknown_actions_and_values(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="unknown audit action"):
        await audit.record(db_session, "project.teleport", actor=None)
    with pytest.raises(TypeError):
        await audit.record(db_session, "project.update", actor=None, details={"x": object()})


# --- Aggregate cache ------------------------------------------------------------------------
async def test_recompute_aggregates(db_session: AsyncSession) -> None:
    users = [await make_user(db_session) for _ in range(5)]
    project = await make_project(db_session, members=dict.fromkeys(users, ProjectRole.MEMBER))
    idea = await make_idea(db_session, project)
    untouched = await make_idea(db_session, project)
    everything = {"Value": 4, "Feasibility": 4, "Effort": 2, "Strategic fit": 4, "Risk": 2}
    # Included: two submitted human evaluations (adjusted 4 everywhere, and 3 everywhere).
    await add_evaluator(
        db_session, idea, users[0], state=EvaluatorState.SUBMITTED, scores=everything
    )
    await add_evaluator(
        db_session,
        idea,
        users[1],
        state=EvaluatorState.SUBMITTED,
        scores=dict.fromkeys(everything, 3),
    )
    # Left out: a draft, an excluded (AI) evaluation, and an assignment with nothing saved.
    await add_evaluator(db_session, idea, users[2], state=EvaluatorState.DRAFT, scores={"Value": 1})
    await add_evaluator(
        db_session,
        idea,
        users[3],
        state=EvaluatorState.SUBMITTED,
        scores=dict.fromkeys(everything, 1),
        include_in_aggregate=False,
        recommendation=Recommendation.NO,
    )
    await add_evaluator(db_session, idea, users[4])

    await recompute_aggregates(db_session, idea_ids=[idea.id])
    await db_session.commit()

    await db_session.refresh(idea)
    await db_session.refresh(untouched)
    assert (idea.aggregate_score, idea.aggregate_count, idea.high_disagreement) == (
        Decimal("3.5"),
        2,
        False,
    )
    assert (untouched.aggregate_score, untouched.aggregate_count) == (None, 0)


async def test_recompute_without_included_evaluations_clears_the_cache(
    db_session: AsyncSession,
) -> None:
    project = await make_project(db_session)
    idea = await make_idea(db_session, project)
    idea.aggregate_score, idea.aggregate_count, idea.high_disagreement = Decimal("4.0"), 1, True
    await db_session.commit()

    await recompute_aggregates(db_session, project_id=project.id)
    await db_session.commit()

    fresh = await db_session.scalar(
        select(Idea).where(Idea.id == idea.id).execution_options(populate_existing=True)
    )
    assert fresh is not None
    assert (fresh.aggregate_score, fresh.aggregate_count, fresh.high_disagreement) == (
        None,
        0,
        False,
    )


async def test_recompute_needs_a_target(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="project_id or idea_ids"):
        await recompute_aggregates(db_session)
