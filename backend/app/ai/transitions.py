"""A run's status changes and progress events (contract-phase6 sections 3.3 and 3.4).

**Compare-and-set.** Every status change is one ``UPDATE ai_runs SET ... WHERE id = :id
AND status IN (...) RETURNING ...``: no row means someone else got there first (a
duplicate job, the sweep, a cancel), and the caller re-reads and acts on what it finds.
:func:`finish` computes the final status **in the same statement** from the cancel
request and the result columns: a cancel request that lands while the agent's task
completes ends the run ``cancelled`` (the result stays), and a run whose result was
recorded otherwise succeeds whatever the task's final state.

**Lock order** (CLAUDE.md "Locking"): project ``FOR KEY SHARE``, idea ``FOR UPDATE``,
then the run. :func:`finish` takes the first two itself (no-ops for a caller that holds
them), because a run that assigned the agent as an evaluator and ends without its
submitted evaluation removes that assignment in the same transaction. Events and
heartbeats lock only the run row.

**Events** are numbered by ``ai_runs.event_count`` (``UPDATE ... RETURNING``, so commit
order is ``seq`` order) and capped at :data:`~app.schemas.ai.AI_RUN_EVENTS_MAX`, the
final event included. Messages are Soundings' fixed sentences only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import String, case, delete, false, func, literal, null, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Rule
from app.models.ai import AiAgent, AiRun, AiRunEvent
from app.models.base import utcnow
from app.models.enums import AiRunError, AiRunEventType, AiRunKind, AiRunStatus, EvaluationStatus
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaEvaluator
from app.models.project import Project
from app.observability import AI_RUN_DURATION, AI_RUNS_FINISHED
from app.schemas.ai import (
    AI_RUN_EVENT_MESSAGES,
    AI_RUN_EVENTS_MAX,
    AI_RUN_FINAL_EVENTS,
    run_error_message,
)
from app.services import activity, audit
from app.services.scoring import recompute_aggregates

__all__ = [
    "RESULT_MESSAGES",
    "Finished",
    "add_event",
    "cancel",
    "finish",
    "lock_idea",
    "start",
]

logger = logging.getLogger("soundings.ai")

RESULT_MESSAGES: Final[dict[AiRunKind, str]] = {
    AiRunKind.EVALUATE: "Evaluation submitted",
    AiRunKind.RESEARCH: "Research note saved",
    AiRunKind.DRAFT_SECTION: "Suggestion saved",
}
"""``result_recorded`` messages per kind."""

_ACTIVE: Final = (AiRunStatus.QUEUED, AiRunStatus.RUNNING)
_FINAL_EVENT: Final[dict[AiRunStatus, AiRunEventType]] = {
    AiRunStatus.SUCCEEDED: AiRunEventType.SUCCEEDED,
    AiRunStatus.FAILED: AiRunEventType.FAILED,
    AiRunStatus.CANCELLED: AiRunEventType.CANCELLED,
    AiRunStatus.TIMED_OUT: AiRunEventType.TIMED_OUT,
}


# --- Events ----------------------------------------------------------------------------------
async def add_event(
    db: AsyncSession, run_id: UUID, type_: AiRunEventType, message: str | None = None
) -> int | None:
    """Append an event (``message`` defaults to the type's fixed sentence); its ``seq``,
    or ``None`` when the run is gone or full (once a run has 199 events only the final
    one still fits) or, for any other event, already over (nothing follows the final
    event). Locks the run row until the caller commits."""
    if message is None:
        message = AI_RUN_EVENT_MESSAGES[type_]
    final = type_ in AI_RUN_FINAL_EVENTS
    limit = AI_RUN_EVENTS_MAX if final else AI_RUN_EVENTS_MAX - 1
    where = [AiRun.id == run_id, AiRun.event_count < limit]
    if not final:
        where.append(AiRun.status.in_(_ACTIVE))
    seq = await db.scalar(
        update(AiRun)
        .where(*where)
        .values(event_count=AiRun.event_count + 1)
        .returning(AiRun.event_count)
        .execution_options(synchronize_session=False)
    )
    if seq is None:
        return None
    db.add(AiRunEvent(run_id=run_id, seq=seq, type=type_, message=message, created_at=utcnow()))
    await db.flush()
    return int(seq)


# --- Locks -----------------------------------------------------------------------------------
async def lock_idea(db: AsyncSession, idea_id: UUID) -> Idea | None:
    """Project ``FOR KEY SHARE`` then idea ``FOR UPDATE``, as
    :func:`app.services.ideas.load_idea` does (``None``: the idea is gone)."""
    project_id = await db.scalar(
        select(Project.id)
        .join(Idea, Idea.project_id == Project.id)
        .where(Idea.id == idea_id)
        .with_for_update(of=Project, read=True, key_share=True)
    )
    if project_id is None:
        return None
    idea: Idea | None = await db.scalar(
        select(Idea)
        .where(Idea.id == idea_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return idea


# --- Transitions -------------------------------------------------------------------------
async def start(db: AsyncSession, run_id: UUID, now: datetime) -> bool:
    """``queued`` -> ``running`` (the job): ``False`` when it isn't queued any more."""
    started = await db.scalar(
        update(AiRun)
        .where(AiRun.id == run_id, AiRun.status == AiRunStatus.QUEUED)
        .values(status=AiRunStatus.RUNNING, started_at=now, heartbeat_at=now)
        .returning(AiRun.id)
        .execution_options(synchronize_session=False)
    )
    return started is not None


@dataclass(frozen=True, slots=True)
class Finished:
    """A run that just ended: its final status and error."""

    status: AiRunStatus
    error_code: AiRunError | None
    error_message: str | None


_HAS_RESULT = or_(
    AiRun.evaluation_id.is_not(None),
    AiRun.activity_event_id.is_not(None),
    AiRun.suggestion_id.is_not(None),
)


async def finish(
    db: AsyncSession,
    run_id: UUID,
    *,
    from_status: AiRunStatus,
    status: AiRunStatus,
    error: AiRunError | None = None,
    http_status: int | None = None,
    a2a_state: str | None = None,
    cancelled_by: UUID | None = None,
    now: datetime | None = None,
) -> Finished | None:
    """End a run that is ``from_status`` (one CAS statement). ``status`` / ``error`` is the
    outcome when nothing overrides it: a cancel request makes it ``cancelled``; a recorded
    result (from ``running``) makes it ``succeeded``. Writes the final event, and for an
    evaluate run that assigned the agent removes the assignment unless the agent
    submitted. ``cancelled_by``: who cancelled a queued run (kept as its cancel request).
    ``None`` when the run wasn't ``from_status`` (someone else finished it)."""
    if (status in (AiRunStatus.FAILED, AiRunStatus.TIMED_OUT)) != (error is not None):
        raise ValueError("failed and timed_out runs (and only they) carry an error")
    now = now or utcnow()
    run = await db.get(AiRun, run_id)
    if run is None:
        return None
    await lock_idea(db, run.idea_id)
    message = (
        run_error_message(error, http_status=http_status, a2a_state=a2a_state)
        if error is not None
        else None
    )
    cancelled = AiRun.cancel_requested_at.is_not(None)
    succeeded = _HAS_RESULT if from_status is AiRunStatus.RUNNING else false()
    final_status = case(
        (cancelled, AiRunStatus.CANCELLED.value),
        (succeeded, AiRunStatus.SUCCEEDED.value),
        else_=status.value,
    )
    plain = or_(cancelled, succeeded)
    values: dict[str, object] = {
        "status": final_status,
        "error_code": case(
            (plain, null()), else_=literal(error.value, String) if error else null()
        ),
        "error_message": case(
            (plain, null()), else_=literal(message, String) if message else null()
        ),
        "finished_at": now,
    }
    if cancelled_by is not None:
        values["cancel_requested_at"] = func.coalesce(AiRun.cancel_requested_at, now)
        values["cancel_requested_by_id"] = func.coalesce(AiRun.cancel_requested_by_id, cancelled_by)
    row = (
        await db.execute(
            update(AiRun)
            .where(AiRun.id == run_id, AiRun.status == from_status)
            .values(values)
            .returning(AiRun.status, AiRun.error_code, AiRun.error_message, AiRun.started_at)
            .execution_options(synchronize_session=False)
        )
    ).first()
    if row is None:
        return None
    final = AiRunStatus(row[0])
    code = AiRunError(row[1]) if row[1] is not None else None
    await add_event(db, run_id, _FINAL_EVENT[final], row[2])
    await db.refresh(run)
    if run.kind is AiRunKind.EVALUATE and run.assigned_evaluator:
        await _undo_assignment(db, run)
    AI_RUNS_FINISHED.labels(kind=run.kind.value, status=final.value).inc()
    if row[3] is not None:
        AI_RUN_DURATION.labels(kind=run.kind.value).observe((now - row[3]).total_seconds())
    logger.info(
        "ai run finished",
        extra={
            "run_id": str(run_id),
            "agent_id": str(run.agent_id),
            "status": final.value,
            "error_code": code.value if code else None,
        },
    )
    return Finished(status=final, error_code=code, error_message=row[2])


async def _undo_assignment(db: AsyncSession, run: AiRun) -> None:
    """The run assigned the agent; without its submitted evaluation the assignment (and
    its draft) goes again, so "all evaluations are in" never waits for it (activity
    ``evaluator_removed`` and audit ``evaluator.remove`` without an actor)."""
    service_account_id = await db.scalar(
        select(AiAgent.service_account_id).where(AiAgent.id == run.agent_id)
    )
    if service_account_id is None:  # pragma: no cover - agents are never deleted
        return
    submitted = await db.scalar(
        select(Evaluation.id).where(
            Evaluation.idea_id == run.idea_id,
            Evaluation.evaluator_id == service_account_id,
            Evaluation.status == EvaluationStatus.SUBMITTED,
        )
    )
    if submitted is not None:
        return
    removed = await db.execute(
        delete(IdeaEvaluator)
        .where(IdeaEvaluator.idea_id == run.idea_id, IdeaEvaluator.user_id == service_account_id)
        .returning(IdeaEvaluator.user_id)
        .execution_options(synchronize_session=False)
    )
    if removed.first() is None:
        return  # someone removed it by hand already
    await db.execute(
        delete(Evaluation)
        .where(Evaluation.idea_id == run.idea_id, Evaluation.evaluator_id == service_account_id)
        .execution_options(synchronize_session=False)
    )
    idea = await db.get(Idea, run.idea_id)
    assert idea is not None  # noqa: S101 - locked by finish()
    await activity.emit(
        db, idea, "evaluator_removed", actor=None, payload={"evaluator_id": service_account_id}
    )
    await audit.record(
        db,
        "evaluator.remove",
        actor=None,
        target_type="user",
        target_id=service_account_id,
        project_id=idea.project_id,
        details={
            "rule": Rule.AI_REQUEST_EVALUATION,
            "idea_id": idea.id,
            "run_id": run.id,
            "reason": "ai_run_ended",
        },
    )
    await db.flush()
    await recompute_aggregates(db, idea_ids=[idea.id])


async def cancel(
    db: AsyncSession, run_id: UUID, *, by_id: UUID | None, now: datetime | None = None
) -> AiRunStatus | None:
    """Cancel a run: ``queued`` ends ``cancelled`` at once; ``running`` gets a cancel
    request (the worker stops it within seconds). Returns the status it has now, or
    ``None`` when it was already final. The caller holds the idea's lock."""
    now = now or utcnow()
    done = await finish(
        db,
        run_id,
        from_status=AiRunStatus.QUEUED,
        status=AiRunStatus.CANCELLED,
        cancelled_by=by_id,
        now=now,
    )
    if done is not None:
        return done.status
    requested = await db.scalar(
        update(AiRun)
        .where(
            AiRun.id == run_id,
            AiRun.status == AiRunStatus.RUNNING,
            AiRun.cancel_requested_at.is_(None),
        )
        .values(cancel_requested_at=now, cancel_requested_by_id=by_id)
        .returning(AiRun.id)
        .execution_options(synchronize_session=False)
    )
    if requested is not None:
        await add_event(db, run_id, AiRunEventType.CANCEL_REQUESTED)
        return AiRunStatus.RUNNING
    still = await db.scalar(
        select(func.count()).where(AiRun.id == run_id, AiRun.status == AiRunStatus.RUNNING)
    )
    return AiRunStatus.RUNNING if still else None
