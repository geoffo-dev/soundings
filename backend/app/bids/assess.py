"""The AI assessor (contract-phase10 section 9, ADR 0018 decision 8): assess runs, the
call's automatic pre-check, and recording the agent's assessment.

**Runs** are ordinary AI runs (``ai_runs.kind = assess_bid``, ``bid_id``,
``bid_call_id``) with their events, deadline, cancel and SSE (:mod:`app.ai`), one active
per idea, agent, kind and bid (``uq_ai_runs_active``). People ask for them ("Ask AI to
assess": :func:`request_assessment`; "Assess all with AI": :func:`request_all`), each new
run counting toward their 20 AI requests an hour (the batch starts what fits, in the
order the bids were received, and reports the rest as ``skipped``).

**The call's AI assessor** (``bid_calls.ai_assessor_id``) starts **one automatic run per
bid** (:func:`start_due_automatic_runs`: ``automatic``, requested by nobody, not counted,
not audited) once the call is open or being assessed, the bid isn't rejected, it has a
document and none is pending extraction, nothing was uploaded to it for
:data:`~app.schemas.bids.BID_AUTO_AI_QUIET`, the agent passes c10, and the bid has had no
automatic run (``bids.auto_ai_run_at``, set once and never reset). The worker checks after
each extraction, when the assessor is set or the call opens or closes to new bids (a
``check_bid_ai_assessor`` job: :func:`defer_automatic_check`), and every minute.

**The assessment** (:func:`record_assessment`, from MCP's ``submit_bid_assessment``):
every score question of the call once, every must-have it was shown (pricing ones are
never shown) once, quotes only from the documents it was given (pricing documents
never), each quote checked against its document's extracted text off the event loop
(:func:`app.schemas.bids.quotes_found`). It replaces the agent's earlier assessment of
the bid; a changed score leaves it out of the totals again.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import anyio
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import agents as agent_service
from app.ai.runs import _defer, _limit, run_out
from app.ai.transitions import add_event
from app.authz import Rule, authorize
from app.bids.access import LoadedCall
from app.bids.problems import conflict
from app.config import Settings
from app.db import SessionMaker, session_scope
from app.domain.principal import Principal
from app.email.outbox import psycopg_connection
from app.errors import ConflictProblem, ProblemError
from app.models.ai import AiRun
from app.models.base import utcnow
from app.models.bid import (
    Bid,
    BidAiAssessment,
    BidAiFinding,
    BidAiScore,
    BidCall,
    BidCallMustHave,
    BidCallQuestion,
    BidDocument,
    BidDocumentText,
)
from app.models.enums import (
    AiRunEventType,
    AiRunKind,
    AiRunStatus,
    BidCallStatus,
    BidQuestionType,
    BidStatus,
    ExtractionState,
    IdeaStatus,
)
from app.models.idea import Idea
from app.models.project import Project
from app.observability import AI_RUNS_REQUESTED
from app.schemas import ai as ai_schemas
from app.schemas.ai import AI_RUN_QUEUE_TIMEOUT, AI_RUNS_PER_USER_PER_HOUR
from app.schemas.bids import BID_AUTO_AI_QUIET, AiRunBatch, quotes_found
from app.schemas.common import FieldError
from app.services import audit
from app.services.ideas import LoadedIdea
from app.worker import procrastinate_app

__all__ = [
    "AUTO_CHECK_TASK",
    "Recorded",
    "active_run",
    "check_after_extraction",
    "defer_automatic_check",
    "record_assessment",
    "request_all",
    "request_assessment",
    "start_due_automatic_runs",
]

logger = logging.getLogger("soundings.ai")

AUTO_CHECK_TASK: Final = "check_bid_ai_assessor"
_ACTIVE: Final = (AiRunStatus.QUEUED, AiRunStatus.RUNNING)
_ASSESSABLE: Final = (BidCallStatus.OPEN, BidCallStatus.ASSESSING)
_AUTO_BATCH: Final = 100


# --- Runs ----------------------------------------------------------------------------------------
async def active_run(db: AsyncSession, idea_id: UUID, agent_id: UUID, bid_id: UUID) -> AiRun | None:
    """The agent's active assess run of the bid (one at most: ``uq_ai_runs_active``)."""
    run: AiRun | None = await db.scalar(
        select(AiRun)
        .where(
            AiRun.idea_id == idea_id,
            AiRun.agent_id == agent_id,
            AiRun.kind == AiRunKind.ASSESS_BID,
            AiRun.bid_id == bid_id,
            AiRun.status.in_(_ACTIVE),
        )
        .execution_options(populate_existing=True)
    )
    return run


async def _new_run(
    db: AsyncSession,
    settings: Settings,
    *,
    idea_id: UUID,
    agent_id: UUID,
    bid: Bid,
    requested_by: UUID | None,
    now: datetime,
) -> AiRun | None:
    """A queued assess run with its first event and its ``run_ai`` job (on this
    transaction's connection); ``None`` when another request won the race for it."""
    run = AiRun(
        id=uuid4(),
        idea_id=idea_id,
        agent_id=agent_id,
        kind=AiRunKind.ASSESS_BID,
        bid_id=bid.id,
        bid_call_id=bid.call_id,
        automatic=requested_by is None,
        requested_by_id=requested_by,
        status=AiRunStatus.QUEUED,
        timeout_seconds=settings.ai_run_timeout_seconds,
        created_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(run)
    except IntegrityError:
        return None
    await add_event(db, run.id, AiRunEventType.QUEUED)
    await _defer(db, run.id)
    AI_RUNS_REQUESTED.labels(kind=AiRunKind.ASSESS_BID.value).inc()
    return run


async def _finish_stale(db: AsyncSession, run: AiRun | None, now: datetime) -> AiRun | None:
    """An active run still queued past the queue timeout ends ``timed_out`` (as Phase 6's
    requests do), so a new one can start."""
    from app.ai.transitions import finish
    from app.models.enums import AiRunError

    if (
        run is not None
        and run.status is AiRunStatus.QUEUED
        and now - run.created_at > AI_RUN_QUEUE_TIMEOUT
    ):
        await finish(
            db,
            run.id,
            from_status=AiRunStatus.QUEUED,
            status=AiRunStatus.TIMED_OUT,
            error=AiRunError.QUEUE_TIMEOUT,
            now=now,
        )
        return None
    return run


async def _audit_request(
    db: AsyncSession, principal: Principal, loaded: LoadedCall, run: AiRun
) -> None:
    await audit.record(
        db,
        "ai_run.request",
        actor=principal,
        target_type="idea",
        target_id=loaded.idea.id,
        project_id=loaded.idea.project_id,
        details={
            "rule": Rule.AI_ASSESS_BID,
            "run_id": run.id,
            "agent_id": run.agent_id,
            "kind": AiRunKind.ASSESS_BID,
            "bid_id": run.bid_id,
        },
    )


async def _checked(
    db: AsyncSession, principal: Principal, settings: Settings, loaded: LoadedCall, agent_id: UUID
) -> None:
    """``ai.assess_bid`` with c10 for the agent: the 403s were raised by ``load_call``;
    the rule's 409s (archived, c19, c5, c10 ``ai_unavailable``) are deferred for
    :meth:`LoadedCall.require_not_finished`."""
    candidate = await agent_service.usable(
        db, settings, agent_id, loaded.idea.project_id, AiRunKind.ASSESS_BID
    )
    decision = authorize(
        principal,
        Rule.AI_ASSESS_BID,
        loaded.resource.replace(ai_available=candidate is not None),
    )
    if not decision.allowed and decision.status in (401, 403, 404):  # pragma: no cover
        raise decision.problem()
    loaded.deferred = None if decision.allowed else decision.problem()


def _as_idea(loaded: LoadedCall) -> LoadedIdea:
    return LoadedIdea(idea=loaded.idea, project=loaded.project, resource=loaded.resource)


def _require_assessable(loaded: LoadedCall) -> None:
    loaded.require_not_finished()
    if loaded.call.status not in _ASSESSABLE:
        raise conflict("bid_call_not_assessable")


async def request_assessment(
    db: AsyncSession,
    principal: Principal,
    settings: Settings,
    loaded: LoadedCall,
    bid: Bid,
    agent_id: UUID,
) -> tuple[ai_schemas.AiRun, bool]:
    """ "Ask AI to assess" (``ai.assess_bid``, c5, c10; the route locked project, idea,
    call and the bid): the call open or being assessed, the bid not rejected; the active
    run answers 200 unchanged; a new one counts toward the hourly limit (429)."""
    await _checked(db, principal, settings, loaded, agent_id)
    _require_assessable(loaded)
    if bid.status is BidStatus.REJECTED:
        raise conflict("bid_rejected")
    now = utcnow()
    active = await _finish_stale(db, await active_run(db, loaded.idea.id, agent_id, bid.id), now)
    if active is not None:
        return await run_out(db, principal, _as_idea(loaded), active), False
    await _limit(db, principal, now)
    run = await _new_run(
        db,
        settings,
        idea_id=loaded.idea.id,
        agent_id=agent_id,
        bid=bid,
        requested_by=principal.user_id,
        now=now,
    )
    if run is None:  # another request for it won the race
        existing = await active_run(db, loaded.idea.id, agent_id, bid.id)
        assert existing is not None  # noqa: S101 - the index names an active run
        return await run_out(db, principal, _as_idea(loaded), existing), False
    await _audit_request(db, principal, loaded, run)
    await db.flush()
    await db.refresh(run)
    return await run_out(db, principal, _as_idea(loaded), run), True


async def _requested_since(db: AsyncSession, user_id: UUID, since: datetime) -> list[datetime]:
    return list(
        await db.scalars(
            select(AiRun.created_at)
            .where(AiRun.requested_by_id == user_id, AiRun.created_at > since)
            .order_by(AiRun.created_at.desc())
            .limit(AI_RUNS_PER_USER_PER_HOUR)
        )
    )


async def request_all(
    db: AsyncSession,
    principal: Principal,
    settings: Settings,
    loaded: LoadedCall,
    agent_id: UUID,
) -> AiRunBatch:
    """ "Assess all with AI": a run for every bid that isn't rejected, in the order the bids
    were received; active runs are returned as they are; new runs as long as the hourly
    limit allows, the rest ``skipped`` (429 only when none could start)."""
    await _checked(db, principal, settings, loaded, agent_id)
    _require_assessable(loaded)
    now = utcnow()
    bids = list(
        await db.scalars(
            select(Bid)
            .where(Bid.call_id == loaded.call.id, Bid.status != BidStatus.REJECTED)
            .order_by(Bid.received_at, Bid.id)
        )
    )
    window = timedelta(hours=1)
    used = len(await _requested_since(db, principal.user_id, now - window))
    room = max(0, AI_RUNS_PER_USER_PER_HOUR - used)
    runs: list[AiRun] = []
    created = skipped = 0
    for bid in bids:
        active = await _finish_stale(
            db, await active_run(db, loaded.idea.id, agent_id, bid.id), now
        )
        if active is not None:
            runs.append(active)
            continue
        if created >= room:
            skipped += 1
            continue
        run = await _new_run(
            db,
            settings,
            idea_id=loaded.idea.id,
            agent_id=agent_id,
            bid=bid,
            requested_by=principal.user_id,
            now=now,
        )
        if run is None:
            existing = await active_run(db, loaded.idea.id, agent_id, bid.id)
            if existing is not None:
                runs.append(existing)
            continue
        await _audit_request(db, principal, loaded, run)
        runs.append(run)
        created += 1
    if skipped and not created:
        await _limit(db, principal, now)  # raises the 429 with its Retry-After
    await db.flush()
    for run in runs:
        await db.refresh(run)
    items = [await run_out(db, principal, _as_idea(loaded), run) for run in runs]
    return AiRunBatch(items=items, created=created, skipped=skipped)


# --- The call's AI assessor: automatic runs -------------------------------------------------
_DUE = """
    SELECT b.id FROM bids b
    JOIN bid_calls c ON c.id = b.call_id
    WHERE c.ai_assessor_id IS NOT NULL
      AND c.status IN ('open', 'assessing')
      AND b.status <> 'rejected'
      AND b.auto_ai_run_at IS NULL
      AND EXISTS (SELECT 1 FROM bid_documents d WHERE d.bid_id = b.id)
      AND NOT EXISTS (
        SELECT 1 FROM bid_documents d WHERE d.bid_id = b.id AND d.extraction_state = 'pending'
      )
      AND (SELECT max(d.uploaded_at) FROM bid_documents d WHERE d.bid_id = b.id) <= :quiet
      {filters}
    ORDER BY b.received_at, b.id
    LIMIT :limit
"""


async def _due_bids(
    db: AsyncSession, now: datetime, *, bid_id: UUID | None, call_id: UUID | None
) -> list[UUID]:
    filters = []
    params: dict[str, Any] = {"quiet": now - BID_AUTO_AI_QUIET, "limit": _AUTO_BATCH}
    if bid_id is not None:
        filters.append("AND b.id = :bid_id")
        params["bid_id"] = bid_id
    if call_id is not None:
        filters.append("AND c.id = :call_id")
        params["call_id"] = call_id
    statement = text(_DUE.format(filters=" ".join(filters)))
    return list(await db.scalars(statement, params))


async def _start_automatic(
    db: AsyncSession, settings: Settings, bid_id: UUID, now: datetime
) -> bool:
    """One bid's automatic run, under project -> idea -> call -> bid locks, its
    conditions read again. ``True`` when a run was started."""
    row = (
        await db.execute(
            select(Idea.id, Idea.project_id)
            .join(BidCall, BidCall.idea_id == Idea.id)
            .join(Bid, Bid.call_id == BidCall.id)
            .where(Bid.id == bid_id)
        )
    ).first()
    if row is None:
        return False
    idea_id, project_id = row
    project = await db.scalar(
        select(Project).where(Project.id == project_id).with_for_update(read=True, key_share=True)
    )
    idea = await db.scalar(
        select(Idea)
        .where(Idea.id == idea_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    call = await db.scalar(
        select(BidCall)
        .where(BidCall.idea_id == idea_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    bid = await db.scalar(
        select(Bid)
        .where(Bid.id == bid_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if project is None or idea is None or call is None or bid is None:
        return False
    if (
        not settings.ai_enabled
        or project.archived_at is not None
        or idea.status is IdeaStatus.CLOSED
        or idea.held_for is not None
        or call.ai_assessor_id is None
        or call.status not in _ASSESSABLE
        or bid.status is BidStatus.REJECTED
        or bid.auto_ai_run_at is not None
    ):
        return False
    pending = await db.scalar(
        select(func.count())
        .select_from(BidDocument)
        .where(
            BidDocument.bid_id == bid.id, BidDocument.extraction_state == ExtractionState.PENDING
        )
    )
    last_upload = await db.scalar(
        select(func.max(BidDocument.uploaded_at)).where(BidDocument.bid_id == bid.id)
    )
    if pending or last_upload is None or last_upload > now - BID_AUTO_AI_QUIET:
        return False
    agent_id = call.ai_assessor_id
    if await agent_service.usable(db, settings, agent_id, project.id, AiRunKind.ASSESS_BID) is None:
        return False  # tried again later, while the bid still has no automatic run
    bid.auto_ai_run_at = now
    await db.flush()
    if await active_run(db, idea.id, agent_id, bid.id) is not None:
        return False  # someone asked that agent already: that run is the pre-check
    run = await _new_run(
        db, settings, idea_id=idea.id, agent_id=agent_id, bid=bid, requested_by=None, now=now
    )
    return run is not None


async def start_due_automatic_runs(
    sessionmaker: SessionMaker,
    settings: Settings,
    *,
    bid_id: UUID | None = None,
    call_id: UUID | None = None,
    now: datetime | None = None,
) -> int:
    """Start the automatic runs that are due (one bid, one call, or all), each in a
    transaction of its own. How many started."""
    if not settings.ai_enabled:
        return 0
    now = now or utcnow()
    async with session_scope(sessionmaker, settings=settings) as db:
        due = await _due_bids(db, now, bid_id=bid_id, call_id=call_id)
    started = 0
    for due_bid in due:
        try:
            async with session_scope(sessionmaker, settings=settings) as db:
                started += int(await _start_automatic(db, settings, due_bid, now))
        except Exception:  # one bid's failure never stops the others
            logger.exception("automatic bid assessment failed", extra={"bid_id": str(due_bid)})
    if started:
        logger.info("automatic bid assessments started", extra={"count": started})
    return started


async def defer_automatic_check(
    db: AsyncSession, call_id: UUID, *, at: datetime | None = None
) -> None:
    """The ``check_bid_ai_assessor`` job for the call, on the session's connection (it
    runs once the change that may start automatic runs has committed), at ``at`` if
    given (the end of a bid's quiet period)."""
    connection = await psycopg_connection(db)
    await procrastinate_app.configure_task(
        AUTO_CHECK_TASK, connection=connection, queue="notifications", schedule_at=at
    ).defer_async(call_id=str(call_id))


async def check_after_extraction(
    sessionmaker: SessionMaker, settings: Settings, bid_id: UUID, *, now: datetime | None = None
) -> int:
    """After a document of the bid was read: start its automatic run if it is due, else
    (the call has an AI assessor and nothing is pending) check again at the end of the
    quiet period after the bid's last upload."""
    now = now or utcnow()
    started = await start_due_automatic_runs(sessionmaker, settings, bid_id=bid_id, now=now)
    if started or not settings.ai_enabled:
        return started
    async with session_scope(sessionmaker, settings=settings) as db:
        row = (
            await db.execute(
                select(BidCall.id, func.max(BidDocument.uploaded_at))
                .join(Bid, Bid.call_id == BidCall.id)
                .join(BidDocument, BidDocument.bid_id == Bid.id)
                .where(
                    Bid.id == bid_id,
                    Bid.auto_ai_run_at.is_(None),
                    BidCall.ai_assessor_id.is_not(None),
                    BidCall.status.in_(_ASSESSABLE),
                )
                .group_by(BidCall.id)
            )
        ).first()
        if row is not None and row[1] is not None and row[1] + BID_AUTO_AI_QUIET > now:
            await defer_automatic_check(
                db, row[0], at=row[1] + BID_AUTO_AI_QUIET + timedelta(seconds=1)
            )
    return 0


# --- The agent's assessment ---------------------------------------------------------------
class Recorded:
    """What :func:`record_assessment` stored."""

    def __init__(
        self, assessment: BidAiAssessment, *, replaced: bool, checked: int, not_found: int
    ) -> None:
        self.assessment = assessment
        self.replaced = replaced
        self.checked = checked
        self.not_found = not_found


def _invalid(fields: Sequence[tuple[str, ...]], detail: str) -> ProblemError:
    return ProblemError(
        422,
        "validation_error",
        detail=detail,
        errors=[FieldError(loc=list(loc), msg=detail, type="value_error") for loc in fields][:20],
    )


async def assessable_documents(db: AsyncSession, bid: Bid) -> list[BidDocument]:
    """The bid's documents the AI may read: every one but the pricing documents."""
    return list(
        await db.scalars(
            select(BidDocument)
            .where(BidDocument.bid_id == bid.id, BidDocument.pricing.is_(False))
            .order_by(BidDocument.uploaded_at, BidDocument.id)
        )
    )


async def assessable_must_haves(db: AsyncSession, call_id: UUID) -> list[BidCallMustHave]:
    """The must-haves the AI is asked about: every one but the pricing ones."""
    return list(
        await db.scalars(
            select(BidCallMustHave)
            .where(BidCallMustHave.call_id == call_id, BidCallMustHave.pricing.is_(False))
            .order_by(BidCallMustHave.position)
        )
    )


async def score_questions(db: AsyncSession, call_id: UUID) -> list[BidCallQuestion]:
    return list(
        await db.scalars(
            select(BidCallQuestion)
            .where(
                BidCallQuestion.call_id == call_id, BidCallQuestion.type == BidQuestionType.SCORE
            )
            .order_by(BidCallQuestion.position)
        )
    )


async def _check_quotes(db: AsyncSession, cited: Sequence[tuple[UUID, str]]) -> list[bool]:
    """Every quote checked against its document's text, **one document at a time** (review
    L5: a bid's 30 documents of 2 M characters each, normalised, were about 250 MB at once
    in the API pod; now one text and its normalised copy), off the event loop."""
    by_document: dict[UUID, list[int]] = {}
    for index, (document_id, _) in enumerate(cited):
        by_document.setdefault(document_id, []).append(index)
    found = [False] * len(cited)
    for document_id, indexes in sorted(by_document.items()):
        text = await db.scalar(
            select(BidDocumentText.text).where(BidDocumentText.document_id == document_id)
        )
        if text is None:
            continue  # no text (not read yet, none, failed): nothing is found in it
        results = await anyio.to_thread.run_sync(
            quotes_found, [cited[i] for i in indexes], {document_id: text}
        )
        for index, result in zip(indexes, results, strict=True):
            found[index] = result
        del text
    return found


async def record_assessment(
    db: AsyncSession,
    *,
    idea: Idea,
    project: Project,
    call: BidCall,
    bid: Bid,
    agent_id: UUID,
    scores: Sequence[Any],
    findings: Sequence[Any],
) -> Recorded:
    """The agent's assessment of the bid (the caller holds project, idea, call, bid and
    the run, and checked c22): every score question once, every must-have it was shown
    once, quotes from its documents only; then every quote checked against its document's
    text, off the event loop. Replaces the agent's earlier one; a changed score sets
    ``included`` false again (a re-submission is judged again by a person). An archived
    project or a closed idea is read-only for the agent too (409 ``project_archived`` /
    ``idea_closed``, contract section 3.1; review M1)."""
    if project.archived_at is not None:
        raise ConflictProblem("The project is archived.", code="project_archived")
    if idea.status is IdeaStatus.CLOSED:
        raise ConflictProblem("The idea is closed.", code="idea_closed")
    if call.status in (BidCallStatus.AWARDED, BidCallStatus.CANCELLED):
        raise conflict("bid_call_finished")
    if call.status not in _ASSESSABLE:
        raise conflict("bid_call_not_assessable")
    if bid.status is BidStatus.REJECTED:
        raise conflict("bid_rejected")
    questions = {q.id for q in await score_questions(db, call.id)}
    must_haves = {m.id for m in await assessable_must_haves(db, call.id)}
    documents = {d.id: d for d in await assessable_documents(db, bid)}
    given_questions = [score.question_id for score in scores]
    given_findings = [finding.must_have_id for finding in findings]
    unknown = [("scores", str(n)) for n, q in enumerate(given_questions) if q not in questions]
    unknown += [("findings", str(n)) for n, m in enumerate(given_findings) if m not in must_haves]
    if unknown:
        raise _invalid(unknown, "That isn't a score question or must-have this bid is assessed on.")
    missing = [("scores", str(q)) for q in questions - set(given_questions)]
    missing += [("findings", str(m)) for m in must_haves - set(given_findings)]
    if missing:
        raise _invalid(missing, "Every score question and every must-have needs an answer.")
    cited: list[tuple[UUID, str]] = []
    foreign: list[tuple[str, ...]] = []
    for group, items in (("scores", scores), ("findings", findings)):
        for n, item in enumerate(items):
            for m, evidence in enumerate(item.evidence):
                if evidence.document_id not in documents:
                    foreign.append((group, str(n), "evidence", str(m)))
                cited.append((evidence.document_id, evidence.quote))
    if foreign:
        raise _invalid(foreign, "Quote only the bid's documents you were given.")
    found = await _check_quotes(db, cited)
    checks = iter(found)

    def evidence_of(item: Any) -> list[dict[str, Any]]:
        return [
            {"document_id": str(e.document_id), "quote": e.quote, "found": next(checks)}
            for e in item.evidence
        ]

    stored_scores = [(score, evidence_of(score)) for score in scores]
    stored_findings = [(finding, evidence_of(finding)) for finding in findings]
    existing: BidAiAssessment | None = await db.scalar(
        select(BidAiAssessment)
        .where(BidAiAssessment.bid_id == bid.id, BidAiAssessment.agent_id == agent_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = utcnow()
    replaced = existing is not None
    if existing is None:
        existing = BidAiAssessment(id=uuid4(), bid_id=bid.id, agent_id=agent_id, submitted_at=now)
        db.add(existing)
        await db.flush()
    else:
        before = dict(
            (
                await db.execute(
                    select(BidAiScore.question_id, BidAiScore.score).where(
                        BidAiScore.ai_assessment_id == existing.id
                    )
                )
            ).all()
        )
        after = {score.question_id: score.score for score in scores}
        if before != after:
            existing.included = False
        existing.submitted_at = now
        await db.execute(delete(BidAiScore).where(BidAiScore.ai_assessment_id == existing.id))
        await db.execute(delete(BidAiFinding).where(BidAiFinding.ai_assessment_id == existing.id))
    db.add_all(
        BidAiScore(
            ai_assessment_id=existing.id,
            question_id=score.question_id,
            score=score.score,
            rationale=score.rationale,
            evidence=evidence,
        )
        for score, evidence in stored_scores
    )
    db.add_all(
        BidAiFinding(
            ai_assessment_id=existing.id,
            must_have_id=finding.must_have_id,
            finding=finding.finding,
            rationale=finding.rationale,
            evidence=evidence,
        )
        for finding, evidence in stored_findings
    )
    await db.flush()
    return Recorded(
        existing, replaced=replaced, checked=len(found), not_found=sum(1 for f in found if not f)
    )
