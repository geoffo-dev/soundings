"""AI runs on an idea: request, list, read, cancel, and including an AI evaluation in the
aggregate (contract-phase6 sections 2, 3.3, 3.5 and 3.7).

**Requesting** (one transaction, under the idea's lock, which the route takes with
``load_idea(for_update=True)``): 404 (no proposal for a draft) -> the rule with its
conditions and c10 (403, 409 ``project_archived`` / ``awaiting_moderation`` / c5-c7 /
``ai_unavailable``) -> **idempotency** (the active run for the same idea, agent, kind and
section answers 200, unchanged, and isn't counted; one still queued past the queue
timeout is finished ``timed_out`` first and a new one starts) -> the per-person limit
(429 with ``Retry-After``) -> a new ``queued`` run, its first event, its ``run_ai`` job
deferred on the ``ai`` queue on the same connection, audit ``ai_run.request``, 201.
``uq_ai_runs_active`` keeps it race-free: a conflicting insert answers the active run.
"Ask AI to evaluate" also assigns the agent's service account as an evaluator when it
isn't one (activity ``evaluator_added`` by the requester, audit ``evaluator.add``; no
notification: service accounts are never notified) and remembers that it did
(``assigned_evaluator``), so a run that ends without its evaluation undoes it.

Runs, events and permission flags hold **no score data**: anyone who may view the idea
may read them, pending evaluators included.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import agents as agent_service
from app.ai.transitions import add_event, finish
from app.ai.transitions import cancel as cancel_run_status
from app.authz import Decision, Rule, authorize, can, require
from app.config import Settings
from app.domain.principal import Principal
from app.email.outbox import psycopg_connection
from app.errors import ConflictProblem, NotFoundProblem, ProblemError
from app.models.ai import AiAgent, AiRun, AiRunEvent
from app.models.base import utcnow
from app.models.enums import (
    AiRunError,
    AiRunEventType,
    AiRunKind,
    AiRunStatus,
    EvaluationStatus,
    ProposalSectionKey,
)
from app.models.evaluation import Evaluation
from app.models.idea import IdeaEvaluator
from app.models.user import User
from app.observability import AI_RUNS_REQUESTED
from app.proposals.service import find_proposal
from app.schemas import ai as schemas
from app.schemas.ai import (
    AI_RUN_QUEUE,
    AI_RUN_QUEUE_TIMEOUT,
    AI_RUNS_PER_USER_PER_HOUR,
    AiBlockedReason,
)
from app.schemas.evaluations import Evaluation as EvaluationOut
from app.services import activity, audit, evaluations
from app.services.ideas import LoadedIdea
from app.services.scoring import recompute_aggregates
from app.services.summaries import user_refs
from app.worker import procrastinate_app

__all__ = [
    "RUN_AI_TASK",
    "RUN_RULES",
    "cancel_run",
    "get_run",
    "list_runs",
    "permissions",
    "request_run",
    "run_out",
    "set_inclusion",
]

logger = logging.getLogger("soundings.ai")

RUN_AI_TASK: Final = "run_ai"
RUN_RULES: Final[dict[AiRunKind, Rule]] = {
    AiRunKind.EVALUATE: Rule.AI_REQUEST_EVALUATION,
    AiRunKind.RESEARCH: Rule.AI_RESEARCH,
    AiRunKind.DRAFT_SECTION: Rule.AI_DRAFT_SECTION,
}
_ACTIVE: Final = (AiRunStatus.QUEUED, AiRunStatus.RUNNING)
_REQUEST_WINDOW: Final = timedelta(hours=1)
_REASONS: Final[dict[str, AiBlockedReason]] = {
    "project_archived": AiBlockedReason.PROJECT_ARCHIVED,
    "awaiting_moderation": AiBlockedReason.AWAITING_MODERATION,
    "idea_closed": AiBlockedReason.IDEA_CLOSED,
    "evaluation_closed": AiBlockedReason.EVALUATION_CLOSED,
    "proposal_not_available": AiBlockedReason.PROPOSAL_NOT_AVAILABLE,
    "ai_unavailable": AiBlockedReason.NO_AGENT,
}


def _run_not_found() -> ProblemError:
    return NotFoundProblem("Not found.")


# --- Responses ----------------------------------------------------------------------------------
def _deadline(run: AiRun) -> datetime | None:
    if run.status is AiRunStatus.RUNNING and run.started_at is not None:
        return run.started_at + timedelta(seconds=run.timeout_seconds)
    return None


async def runs_out(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, runs: Sequence[AiRun]
) -> list[schemas.AiRun]:
    """The runs as anyone who may view the idea sees them (no score data)."""
    agent_ids = {run.agent_id for run in runs}
    agents: dict[UUID, AiAgent] = {}
    if agent_ids:
        found = await db.scalars(select(AiAgent).where(AiAgent.id.in_(agent_ids)))
        agents = {agent.id: agent for agent in found}
    users = await user_refs(db, (run.requested_by_id for run in runs))
    may_cancel = can(principal, Rule.AI_CANCEL_RUN, loaded.resource)
    out = []
    for run in runs:
        agent = agents[run.agent_id]
        out.append(
            schemas.AiRun(
                id=run.id,
                idea_id=run.idea_id,
                kind=run.kind,
                section_key=run.section_key,
                agent=agent_service.agent_ref(agent),
                requested_by=users.get(run.requested_by_id) if run.requested_by_id else None,
                status=run.status,
                created_at=run.created_at,
                started_at=run.started_at,
                finished_at=run.finished_at,
                deadline_at=_deadline(run),
                # "Cancelling" until it ends: an ended run (cancelled ones too) isn't.
                cancel_requested=run.cancel_requested_at is not None and run.finished_at is None,
                error=(
                    schemas.AiRunErrorInfo(code=run.error_code, message=run.error_message)
                    if run.error_code is not None and run.error_message is not None
                    else None
                ),
                result=schemas.AiRunResult(
                    evaluation_id=run.evaluation_id,
                    note_id=run.activity_event_id,
                    suggestion_id=run.suggestion_id,
                ),
                event_count=run.event_count,
                can_cancel=may_cancel and run.status in _ACTIVE,
            )
        )
    return out


async def run_out(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, run: AiRun
) -> schemas.AiRun:
    return (await runs_out(db, principal, loaded, [run]))[0]


async def _load_run(
    db: AsyncSession, loaded: LoadedIdea, run_id: UUID, *, for_update: bool = False
) -> AiRun:
    statement = select(AiRun).where(AiRun.id == run_id, AiRun.idea_id == loaded.idea.id)
    if for_update:
        statement = statement.with_for_update(key_share=True)
    run = await db.scalar(statement.execution_options(populate_existing=True))
    if run is None:
        raise _run_not_found()
    return run


# --- Permissions -------------------------------------------------------------------------------
def _blocked(decision: Decision, settings: Settings) -> AiBlockedReason | None:
    """The reason for a request rule's decision made with c10 assumed (see
    :func:`permissions`), in :class:`AiBlockedReason`'s order."""
    if not decision.allowed and decision.status in (401, 403, 404):
        return AiBlockedReason.NOT_ALLOWED
    if not settings.ai_enabled:
        return AiBlockedReason.AI_OFF
    if not decision.allowed:
        return _REASONS.get(decision.code, AiBlockedReason.NOT_ALLOWED)
    return None


async def permissions(
    db: AsyncSession,
    principal: Principal,
    settings: Settings,
    loaded: LoadedIdea,
    usable_kinds: set[AiRunKind],
) -> schemas.AiPermissions:
    """The idea page's AI flags: each request rule with its conditions **and** c10 for an
    agent with that purpose (``usable_kinds``), with the first reason it is blocked."""
    resource = loaded.resource.replace(ai_available=True)
    has_proposal = await find_proposal(db, loaded.idea.id) is not None
    reasons: dict[AiRunKind, AiBlockedReason | None] = {}
    for kind, rule in RUN_RULES.items():
        reason = _blocked(authorize(principal, rule, resource), settings)
        if reason is None and kind is AiRunKind.DRAFT_SECTION and not has_proposal:
            reason = AiBlockedReason.NO_PROPOSAL
        if reason is None and kind not in usable_kinds:
            reason = AiBlockedReason.NO_AGENT
        reasons[kind] = reason
    include = authorize(principal, Rule.EVALUATION_INCLUDE_AI, loaded.resource)
    include_reason: AiBlockedReason | None = None
    if not include.allowed:
        include_reason = _REASONS.get(include.code) if include.status == 409 else None
        include_reason = include_reason or AiBlockedReason.NOT_ALLOWED
    elif not can(principal, Rule.EVALUATION_VIEW_OTHERS, loaded.resource):
        include_reason = AiBlockedReason.NOT_ALLOWED  # a pending evaluator sees no evaluations
    return schemas.AiPermissions(
        can_request_evaluation=reasons[AiRunKind.EVALUATE] is None,
        request_evaluation_blocked_by=reasons[AiRunKind.EVALUATE],
        can_research=reasons[AiRunKind.RESEARCH] is None,
        research_blocked_by=reasons[AiRunKind.RESEARCH],
        can_draft_section=reasons[AiRunKind.DRAFT_SECTION] is None,
        draft_section_blocked_by=reasons[AiRunKind.DRAFT_SECTION],
        can_cancel=can(principal, Rule.AI_CANCEL_RUN, loaded.resource),
        can_include_ai=include_reason is None,
        include_ai_blocked_by=include_reason,
    )


# --- Reading -------------------------------------------------------------------------------------
async def list_runs(
    db: AsyncSession,
    principal: Principal,
    settings: Settings,
    loaded: LoadedIdea,
    *,
    kind: AiRunKind | None,
    limit: int,
) -> schemas.AiRunList:
    """``GET /ideas/{idea}/ai-runs`` (``idea.view``, checked by ``load_idea``)."""
    statement = select(AiRun).where(AiRun.idea_id == loaded.idea.id)
    if kind is not None:
        statement = statement.where(AiRun.kind == kind)
    runs = list(
        await db.scalars(statement.order_by(AiRun.created_at.desc(), AiRun.id.desc()).limit(limit))
    )
    now = utcnow()
    found = await agent_service.candidates(db, loaded.project.id)
    usable = [(candidate, set(candidate.kinds(settings, now))) for candidate in found]
    usable = [(candidate, kinds) for candidate, kinds in usable if kinds]
    usable_kinds = {kind for _, kinds in usable for kind in kinds}
    return schemas.AiRunList(
        items=await runs_out(db, principal, loaded, runs),
        ai_enabled=settings.ai_enabled,
        agents=[agent_service.agent_ref(candidate.agent) for candidate, _ in usable],
        permissions=await permissions(db, principal, settings, loaded, usable_kinds),
    )


async def get_run(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, run_id: UUID
) -> schemas.AiRunDetail:
    """``GET /ideas/{idea}/ai-runs/{run_id}``: the run and every event (the polling
    fallback of the stream)."""
    run = await _load_run(db, loaded, run_id)
    events = await db.scalars(
        select(AiRunEvent).where(AiRunEvent.run_id == run.id).order_by(AiRunEvent.seq)
    )
    base = await run_out(db, principal, loaded, run)
    return schemas.AiRunDetail(
        **base.model_dump(),
        events=[
            schemas.AiRunEvent(
                seq=event.seq, type=event.type, message=event.message, created_at=event.created_at
            )
            for event in events
        ],
    )


# --- Requesting ----------------------------------------------------------------------------------
async def _active_run(
    db: AsyncSession,
    idea_id: UUID,
    agent_id: UUID,
    kind: AiRunKind,
    section_key: ProposalSectionKey | None,
) -> AiRun | None:
    statement = select(AiRun).where(
        AiRun.idea_id == idea_id,
        AiRun.agent_id == agent_id,
        AiRun.kind == kind,
        AiRun.status.in_(_ACTIVE),
    )
    statement = statement.where(
        AiRun.section_key.is_(None) if section_key is None else AiRun.section_key == section_key
    )
    run: AiRun | None = await db.scalar(statement.execution_options(populate_existing=True))
    return run


async def _limit(db: AsyncSession, principal: Principal, now: datetime) -> None:
    """20 new runs per person per hour (429 ``too_many_attempts`` with ``Retry-After``)."""
    since = now - _REQUEST_WINDOW
    rows = list(
        await db.scalars(
            select(AiRun.created_at)
            .where(AiRun.requested_by_id == principal.user_id, AiRun.created_at > since)
            .order_by(AiRun.created_at.desc())
            .limit(AI_RUNS_PER_USER_PER_HOUR)
        )
    )
    if len(rows) < AI_RUNS_PER_USER_PER_HOUR:
        return
    retry_after = max(1, math.ceil((rows[-1] + _REQUEST_WINDOW - now).total_seconds()))
    raise ProblemError(
        429,
        "too_many_attempts",
        detail=f"You asked for {AI_RUNS_PER_USER_PER_HOUR} AI runs in the last hour. Try later.",
        headers={"Retry-After": str(retry_after)},
    )


async def _assign_agent(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, service_account_id: UUID
) -> bool:
    """Make the agent's service account an evaluator unless it is one: ``True`` if this
    request assigned it."""
    idea = loaded.idea
    if await db.get(IdeaEvaluator, (idea.id, service_account_id)) is not None:
        return False
    db.add(
        IdeaEvaluator(
            idea_id=idea.id,
            user_id=service_account_id,
            invited_by_id=principal.user_id,
            invited_at=utcnow(),
        )
    )
    await db.flush()
    await activity.emit(
        db, idea, "evaluator_added", actor=principal, payload={"evaluator_id": service_account_id}
    )
    await audit.record(
        db,
        "evaluator.add",
        actor=principal,
        target_type="user",
        target_id=service_account_id,
        project_id=idea.project_id,
        details={"rule": Rule.AI_REQUEST_EVALUATION, "idea_id": idea.id},
    )
    return True


async def _defer(db: AsyncSession, run_id: UUID) -> None:
    """The ``run_ai`` job, on the ``ai`` queue, on the request's connection (it becomes
    visible to the worker when the request commits, or never)."""
    connection = await psycopg_connection(db)
    deferrer = procrastinate_app.configure_task(
        RUN_AI_TASK, connection=connection, queue=AI_RUN_QUEUE
    )
    await deferrer.defer_async(run_id=str(run_id))


async def request_run(
    db: AsyncSession,
    principal: Principal,
    settings: Settings,
    loaded: LoadedIdea,
    kind: AiRunKind,
    agent_id: UUID,
    section_key: ProposalSectionKey | None = None,
) -> tuple[schemas.AiRun, bool]:
    """``POST /ideas/{idea}/ai-runs/...`` (see the module docstring): the run, and
    ``True`` when it is new (201) or ``False`` for the active one (200)."""
    idea = loaded.idea
    if kind is AiRunKind.DRAFT_SECTION and await find_proposal(db, idea.id) is None:
        raise NotFoundProblem("This idea has no proposal yet.")
    candidate = await agent_service.usable(db, settings, agent_id, loaded.project.id, kind)
    require(principal, RUN_RULES[kind], loaded.resource.replace(ai_available=candidate is not None))
    assert candidate is not None  # noqa: S101 - c10 passed
    now = utcnow()
    active = await _active_run(db, idea.id, agent_id, kind, section_key)
    if (
        active is not None
        and active.status is AiRunStatus.QUEUED
        and (now - active.created_at > AI_RUN_QUEUE_TIMEOUT)
    ):
        await finish(
            db,
            active.id,
            from_status=AiRunStatus.QUEUED,
            status=AiRunStatus.TIMED_OUT,
            error=AiRunError.QUEUE_TIMEOUT,
            now=now,
        )
        active = None
    if active is not None:
        return await run_out(db, principal, loaded, active), False
    await _limit(db, principal, now)
    run = AiRun(
        id=uuid4(),
        idea_id=idea.id,
        agent_id=agent_id,
        kind=kind,
        section_key=section_key,
        requested_by_id=principal.user_id,
        status=AiRunStatus.QUEUED,
        timeout_seconds=settings.ai_run_timeout_seconds,
        created_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(run)
    except IntegrityError:
        # Another request for the same run won the race (uq_ai_runs_active).
        existing = await _active_run(db, idea.id, agent_id, kind, section_key)
        if existing is None:  # pragma: no cover - the index names an active run
            raise
        return await run_out(db, principal, loaded, existing), False
    await add_event(db, run.id, AiRunEventType.QUEUED)
    if kind is AiRunKind.EVALUATE and await _assign_agent(
        db, principal, loaded, candidate.agent.service_account_id
    ):
        await db.execute(
            update(AiRun)
            .where(AiRun.id == run.id)
            .values(assigned_evaluator=True)
            .execution_options(synchronize_session=False)
        )
        run.assigned_evaluator = True
    await _defer(db, run.id)
    await audit.record(
        db,
        "ai_run.request",
        actor=principal,
        target_type="idea",
        target_id=idea.id,
        project_id=idea.project_id,
        details={
            "rule": RUN_RULES[kind],
            "run_id": run.id,
            "agent_id": agent_id,
            "kind": kind,
            "section_key": section_key,
        },
    )
    await db.flush()
    await db.refresh(run)
    AI_RUNS_REQUESTED.labels(kind=kind.value).inc()
    logger.info(
        "ai run requested",
        extra={"run_id": str(run.id), "agent_id": str(agent_id), "kind": kind.value},
    )
    return await run_out(db, principal, loaded, run), True


# --- Cancel --------------------------------------------------------------------------------------
async def cancel_run(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, run_id: UUID
) -> schemas.AiRun:
    """``POST .../cancel`` (``ai.cancel_run``; the route holds the idea's lock): 404 ->
    403 -> 409 ``ai_run_finished``. Idempotent while the run is active."""
    run = await _load_run(db, loaded, run_id)
    require(principal, Rule.AI_CANCEL_RUN, loaded.resource)
    already = run.cancel_requested_at is not None and run.status is AiRunStatus.RUNNING
    status = await cancel_run_status(db, run.id, by_id=principal.user_id)
    if status is None:
        raise ConflictProblem("This AI run has already ended.", code="ai_run_finished")
    if not already:
        await audit.record(
            db,
            "ai_run.cancel",
            actor=principal,
            target_type="idea",
            target_id=loaded.idea.id,
            project_id=loaded.idea.project_id,
            details={
                "rule": Rule.AI_CANCEL_RUN,
                "run_id": run.id,
                "agent_id": run.agent_id,
                "status": status,
            },
        )
    await db.flush()
    return await run_out(db, principal, loaded, await _load_run(db, loaded, run_id))


# --- The include-AI toggle ------------------------------------------------------------------------
async def set_inclusion(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, evaluation_id: UUID, include: bool
) -> EvaluationOut:
    """``PUT .../include-in-aggregate`` (``evaluation.include_ai``; the route holds the
    idea's lock): 404 (not this idea's submitted evaluation, or hidden from you: a pending
    evaluator sees none) -> 403 -> 409 (archived, c19, ``not_ai_evaluation``).
    Idempotent; a change recomputes the aggregate and is audited."""
    row = (
        await db.execute(
            select(Evaluation, User)
            .join(User, User.id == Evaluation.evaluator_id)
            .where(
                Evaluation.id == evaluation_id,
                Evaluation.idea_id == loaded.idea.id,
                Evaluation.status == EvaluationStatus.SUBMITTED,
            )
            .with_for_update(of=Evaluation)
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None or not can(principal, Rule.EVALUATION_VIEW_OTHERS, loaded.resource):
        raise NotFoundProblem("Not found.")
    evaluation, evaluator = row
    require(principal, Rule.EVALUATION_INCLUDE_AI, loaded.resource)
    if not evaluator.is_service_account:
        raise ConflictProblem(
            "People's evaluations always count; only AI evaluations can be left out.",
            code="not_ai_evaluation",
        )
    if evaluation.include_in_aggregate != include:
        evaluation.include_in_aggregate = include
        await db.flush()
        await recompute_aggregates(db, idea_ids=[loaded.idea.id])
        await audit.record(
            db,
            "evaluation.include_ai",
            actor=principal,
            target_type="idea",
            target_id=loaded.idea.id,
            project_id=loaded.idea.project_id,
            details={
                "rule": Rule.EVALUATION_INCLUDE_AI,
                "evaluation_id": evaluation.id,
                "evaluator_id": evaluator.id,
                "include": include,
            },
        )
    found = await evaluations.list_evaluations(db, principal, loaded)
    for item in found.items:
        if item.id == evaluation.id:
            return item
    raise NotFoundProblem("Not found.")  # pragma: no cover - it is submitted and visible


async def count_requested(db: AsyncSession, user_id: UUID, since: datetime) -> int:
    """Runs ``user_id`` requested since ``since`` (tests, diagnostics)."""
    return int(
        await db.scalar(
            select(func.count())
            .select_from(AiRun)
            .where(AiRun.requested_by_id == user_id, AiRun.created_at > since)
        )
        or 0
    )
