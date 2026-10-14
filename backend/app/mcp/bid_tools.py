"""The AI assessor's three MCP tools (contract-phase10 section 9.2, role matrix c22): every
call names its open assess run (``run_id``), whose bid ``bid_id`` must be, **before
anything is looked up** (``ai_run_not_active``, whether the bid exists or not); people
get ``forbidden`` (``bid.ai_assess`` is granted only through such a run); the key needs
``evaluate``.

* ``get_bid_for_assessment``: the call (title, description, scale, sections with their
  **score** questions, the must-haves **except pricing ones**), the bid (id, bidder,
  received), its documents **except pricing ones** with their extraction state, and the
  agent's own last assessment of it. Never other bids, people's scores, the price,
  pricing documents, the contact or the notes.
* ``get_bid_document_text``: one page of a document of that bid (a pricing document or
  another bid's: ``not_found``).
* ``submit_bid_assessment``: the run kind's one write (:func:`app.bids.assess.record_assessment`),
  attached to the run as its result.

Everything they return is the bidder's (or the team's) text: marked untrusted in the tool
descriptions, and passed through :func:`app.mcp.text.visible_text` like every result.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.ai import results as ai_results
from app.ai import scope as ai_scope
from app.authz import Decision, Rule, not_found
from app.bids import assess, documents
from app.domain.principal import Principal
from app.mcp.tools import ToolContext, _idea
from app.models.bid import (
    Bid,
    BidAiAssessment,
    BidAiFinding,
    BidAiScore,
    BidCall,
    BidCallSection,
    BidDocument,
)
from app.schemas.mcp import (
    GetBidDocumentTextInput,
    GetBidDocumentTextOutput,
    GetBidForAssessmentInput,
    GetBidForAssessmentOutput,
    McpBid,
    McpBidAiAssessment,
    McpBidAiFinding,
    McpBidAiScore,
    McpBidCall,
    McpBidDocument,
    McpBidEvidence,
    McpBidMustHave,
    McpBidQuestion,
    McpBidSection,
    SubmitBidAssessmentInput,
    SubmitBidAssessmentOutput,
)

__all__ = ["get_bid_document_text", "get_bid_for_assessment", "submit_bid_assessment"]


def _require_evaluate(principal: Principal) -> None:
    if not principal.has_scope("evaluate"):
        raise Decision(Rule.BID_AI_ASSESS, False, 403, "insufficient_scope").problem()


async def _run(ctx: ToolContext, run_id: UUID | None, bid_id: UUID, tool: str) -> Any:
    """c22 first, then the key's scope, then the run's idea as REST loads it (``not_found``
    while held)."""
    run = await ai_scope.require_bid_run(ctx.db, ctx.principal, run_id, bid_id, tool=tool)
    ctx.event_run = run.id
    _require_evaluate(ctx.principal)
    return run


async def _bid(
    ctx: ToolContext, run: ai_scope.NamedRun, *, for_update: bool = False
) -> tuple[BidCall, Bid]:
    call = await ctx.db.scalar(
        (
            select(BidCall).where(BidCall.idea_id == run.idea_id).with_for_update()
            if for_update
            else select(BidCall).where(BidCall.idea_id == run.idea_id)
        ).execution_options(populate_existing=True)
    )
    statement = select(Bid).where(Bid.id == run.bid_id)
    if for_update:
        statement = statement.with_for_update()
    bid = await ctx.db.scalar(statement.execution_options(populate_existing=True))
    if call is None or bid is None or bid.call_id != call.id:
        raise not_found()
    return call, bid


def _evidence(stored: Any, visible: set[UUID]) -> list[McpBidEvidence]:
    out = []
    for item in stored or []:
        try:
            document_id = UUID(str(item.get("document_id")))
        except (ValueError, AttributeError):
            continue
        if document_id in visible:
            out.append(
                McpBidEvidence(
                    document_id=document_id,
                    quote=str(item.get("quote", "")),
                    found=bool(item.get("found", False)),
                )
            )
    return out


async def _previous(
    ctx: ToolContext, bid: Bid, agent_id: UUID, visible: set[UUID], must_haves: set[UUID]
) -> McpBidAiAssessment | None:
    assessment = await ctx.db.scalar(
        select(BidAiAssessment).where(
            BidAiAssessment.bid_id == bid.id, BidAiAssessment.agent_id == agent_id
        )
    )
    if assessment is None:
        return None
    scores = await ctx.db.scalars(
        select(BidAiScore).where(BidAiScore.ai_assessment_id == assessment.id)
    )
    findings = await ctx.db.scalars(
        select(BidAiFinding).where(BidAiFinding.ai_assessment_id == assessment.id)
    )
    return McpBidAiAssessment(
        submitted_at=assessment.submitted_at,
        scores=[
            McpBidAiScore(
                question_id=score.question_id,
                score=score.score,
                rationale=score.rationale,
                evidence=_evidence(score.evidence, visible),
            )
            for score in scores
        ],
        findings=[
            McpBidAiFinding(
                must_have_id=finding.must_have_id,
                finding=finding.finding,
                rationale=finding.rationale,
                evidence=_evidence(finding.evidence, visible),
            )
            for finding in findings
            if finding.must_have_id in must_haves
        ],
    )


async def _agent_id(ctx: ToolContext) -> UUID:
    from app.models.ai import AiAgent

    agent_id = await ctx.db.scalar(
        select(AiAgent.id).where(AiAgent.service_account_id == ctx.principal.user_id)
    )
    if agent_id is None:  # pragma: no cover - c22 found the agent's run
        raise ai_scope.RunNotActiveProblem
    return agent_id


async def get_bid_for_assessment(
    ctx: ToolContext, args: GetBidForAssessmentInput
) -> GetBidForAssessmentOutput:
    run = await _run(ctx, args.run_id, args.bid_id, "get_bid_for_assessment")
    await _idea(ctx, str(run.idea_id))
    call, bid = await _bid(ctx, run)
    sections = list(
        await ctx.db.scalars(
            select(BidCallSection)
            .where(BidCallSection.call_id == call.id)
            .order_by(BidCallSection.position)
        )
    )
    questions = await assess.score_questions(ctx.db, call.id)
    must_haves = await assess.assessable_must_haves(ctx.db, call.id)
    visible = await assess.assessable_documents(ctx.db, bid)
    visible_ids = {d.id for d in visible}
    linked = list(
        await ctx.db.execute(
            select(BidDocument.must_have_id, BidDocument.id, BidDocument.pricing).where(
                BidDocument.bid_id == bid.id, BidDocument.must_have_id.is_not(None)
            )
        )
    )
    return GetBidForAssessmentOutput(
        call=McpBidCall(
            id=call.id,
            title=call.title,
            description=call.description,
            scale=list(call.scale),
            sections=[
                McpBidSection(
                    id=section.id,
                    title=section.title,
                    guidance=section.guidance,
                    weight=section.weight,
                    questions=[
                        McpBidQuestion(id=q.id, text=q.text, guidance=q.guidance, weight=q.weight)
                        for q in questions
                        if q.section_id == section.id
                    ],
                )
                for section in sections
            ],
            must_haves=[
                McpBidMustHave(
                    id=m.id,
                    text=m.text,
                    kind=m.kind,
                    document_ids=[d for mh, d, pricing in linked if mh == m.id and not pricing],
                    restricted_document_count=sum(
                        1 for mh, _, pricing in linked if mh == m.id and pricing
                    ),
                )
                for m in must_haves
            ],
        ),
        bid=McpBid(id=bid.id, bidder=bid.bidder, received_at=bid.received_at),
        documents=[
            McpBidDocument(
                id=d.id,
                filename=d.filename,
                type=d.type,
                size_bytes=d.size_bytes,
                extraction_state=d.extraction_state,
                page_count=documents.page_count(d),
                must_have_id=d.must_have_id,
            )
            for d in visible
        ],
        previous=await _previous(
            ctx, bid, await _agent_id(ctx), visible_ids, {m.id for m in must_haves}
        ),
    )


async def get_bid_document_text(
    ctx: ToolContext, args: GetBidDocumentTextInput
) -> GetBidDocumentTextOutput:
    run = await _run(ctx, args.run_id, args.bid_id, "get_bid_document_text")
    await _idea(ctx, str(run.idea_id))
    _call, bid = await _bid(ctx, run)
    document = await ctx.db.scalar(
        select(BidDocument).where(
            BidDocument.id == args.document_id,
            BidDocument.bid_id == bid.id,
            BidDocument.pricing.is_(False),
        )
    )
    if document is None:
        raise not_found()
    page = await documents.document_text(ctx.db, document, args.page)
    return GetBidDocumentTextOutput(
        document_id=page.document_id,
        state=page.state,
        page=page.page,
        page_count=page.page_count,
        text=page.text,
        truncated=page.truncated,
    )


async def submit_bid_assessment(
    ctx: ToolContext, args: SubmitBidAssessmentInput
) -> SubmitBidAssessmentOutput:
    named = await _run(ctx, args.run_id, args.bid_id, "submit_bid_assessment")
    ai_scope.check_write(ctx.principal, "submit_bid_assessment", named)
    # Lock order: project (KEY SHARE) -> idea -> call -> bid -> run.
    loaded = await _idea(ctx, str(named.idea_id), for_update=True)
    call, bid = await _bid(ctx, named, for_update=True)
    run = await ai_scope.lock_run(ctx.db, ctx.principal, named)
    assert run is not None  # noqa: S101 - an agent's run (lock_run raises otherwise)
    recorded = await assess.record_assessment(
        ctx.db,
        idea=loaded.idea,
        project=loaded.project,
        call=call,
        bid=bid,
        agent_id=run.agent_id,
        scores=args.scores,
        findings=args.findings,
    )
    if await ai_results.attach(ctx.db, run, bid_ai_assessment_id=recorded.assessment.id):
        ctx.recorded.append((run.id, run.kind))
    return SubmitBidAssessmentOutput(
        ai_assessment_id=recorded.assessment.id,
        bid_id=bid.id,
        replaced=recorded.replaced,
        included=recorded.assessment.included,
        quotes_checked=recorded.checked,
        quotes_not_found=recorded.not_found,
    )
