"""What the bid routes answer, as each principal may see it (role matrix table M and
section 3a; contract-phase10 sections 3-10).

* **Call managers** see everything, except the scores of a (bid, section) they owe an
  assessment for themselves, and no ranks while they owe any.
* **Section assessors** see the call and its template, every bid that isn't rejected
  (bidder, received, documents, must-have results, the AI's findings), their own
  assessments, others' scores of a section after submitting it for that bid; prices and
  pricing documents only as the price section's assessors; never contacts, notes,
  rejection reasons, totals, ranks or rejected bids.
* **Everyone else** who can view the idea: the summary.

Prices follow ``bid.view_price``, pricing documents too (counted as "present
(restricted)", never named). Every check goes through the policy (``app.authz``).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import agent_ref, candidates
from app.authz import Resource, Rule, authorize, bid_pending, can
from app.bids.access import FINISHED, manages, sees_price
from app.bids.data import CallData, load_call_data
from app.bids.scoring import BidScores, lowest_scored_price, score_bid, score_call
from app.bids.templates import must_have_out, question_out
from app.config import Settings
from app.domain.principal import Principal
from app.models.ai import AiAgent
from app.models.base import utcnow
from app.models.bid import (
    Bid,
    BidAiAssessment,
    BidAiFinding,
    BidAssessment,
    BidAssessmentAnswer,
    BidCall,
    BidCallMustHave,
    BidCallQuestion,
    BidCallSection,
    BidDocument,
    BidMustHaveResult,
)
from app.models.enums import (
    AiMustHaveFinding,
    AiRunKind,
    BidCallStatus,
    BidQuestionType,
    BidStatus,
    EvaluationStatus,
    EvaluatorState,
    ExtractionState,
    MustHaveResult,
)
from app.models.user import User
from app.schemas.ai import AiAgentRef, AiBlockedReason
from app.schemas.bid_refs import BidCallRef, BidCallSummary, BidProgress, BidRef, BidSectionRef
from app.schemas.bids import (
    BID_TEXT_PAGE_CHARS,
    BidAiAssessmentList,
    BidAiFindingView,
    BidAiScoreView,
    BidAiSectionScores,
    BidAnswer,
    BidAssessmentView,
    BidAssessor,
    BidCallPermissions,
    BidCallTemplate,
    BidCallView,
    BidComparison,
    BidComparisonRow,
    BidComparisonSection,
    BidDetail,
    BidDocumentExtraction,
    BidEvidence,
    BidList,
    BidMustHaveCounts,
    BidMustHaveState,
    BidPermissions,
    BidQuestionStats,
    BidRejection,
    BidSectionAssessments,
    BidSectionScore,
    BidSectionState,
    MyBidAssessment,
    round_score,
)
from app.schemas.bids import Bid as BidOut
from app.schemas.bids import BidAiAssessment as BidAiAssessmentOut
from app.schemas.bids import BidCall as BidCallOut
from app.schemas.bids import BidCallSection as BidCallSectionOut
from app.schemas.bids import BidDocument as BidDocumentOut
from app.schemas.users import UserRef
from app.services.summaries import user_refs

__all__ = [
    "ai_assessments_out",
    "bid_detail",
    "bid_list",
    "bid_out",
    "call_permissions",
    "call_summary",
    "call_view",
    "comparison",
    "document_out",
    "must_have_state",
    "my_assessment",
    "section_assessments",
    "template_out",
]

_ASSESS_OPEN = (BidCallStatus.OPEN, BidCallStatus.ASSESSING)
_REASONS = {
    "project_archived": AiBlockedReason.PROJECT_ARCHIVED,
    "awaiting_moderation": AiBlockedReason.AWAITING_MODERATION,
    "idea_closed": AiBlockedReason.IDEA_CLOSED,
}


def _score(value: Any, places: int = 1, scale: int = 1) -> float | None:
    return None if value is None else round_score(value * scale, places)


def _section_ref(section: BidCallSection) -> BidSectionRef:
    return BidSectionRef(id=section.id, title=section.title)


def bid_ref(bid: Bid) -> BidRef:
    return BidRef(id=bid.id, bidder=bid.bidder, status=bid.status)


def _late(call: BidCall, bid: Bid) -> bool:
    return call.deadline_at is not None and bid.received_at > call.deadline_at


def _price(bid: Bid, visible: bool) -> str | None:
    return f"{bid.price:.2f}" if visible and bid.price is not None else None


def my_sections(principal: Principal, resource: Resource, data: CallData) -> list[BidCallSection]:
    """The sections the principal assesses now (the +Asr overlay with c29), in order."""
    mine = resource.bid_call.my_section_ids if resource.bid_call else frozenset()
    return [
        section
        for section in data.sections
        if section.id in mine
        and can(
            principal, Rule.BID_VIEW_OWN_ASSESSMENT, resource.replace(bid_section_id=section.id)
        )
    ]


def _owes(
    principal: Principal, data: CallData, bid: Bid, sections: Iterable[BidCallSection]
) -> list[UUID]:
    return [s.id for s in sections if not data.submitted(bid.id, s.id, principal.user_id)]


def owes_bid(principal: Principal, resource: Resource, data: CallData, bid: Bid) -> bool:
    """The principal is a pending assessor (section 3a) of some section of ``bid``."""
    return any(
        bid_pending(
            principal,
            resource.replace(
                bid_section_id=section.id,
                bid_section_submitted=data.submitted(bid.id, section.id, principal.user_id),
            ),
        )
        for section in data.sections
    )


def _finding_view(
    assessment: BidAiAssessment,
    finding: BidAiFinding,
    agent: UserRef,
    visible: set[UUID],
    *,
    verdict_only: bool,
) -> BidAiFindingView:
    """An AI must-have finding. ``verdict_only`` (review ACC-2 / L8): its rationale and
    quotes are the agent's free text, where scores can travel, so someone who still owes a
    section of the bid reads met / not met / unclear alone until they have submitted."""
    return BidAiFindingView(
        ai_assessment_id=assessment.id,
        must_have_id=finding.must_have_id,
        agent=agent,
        finding=finding.finding,
        rationale="" if verdict_only else finding.rationale,
        evidence=[] if verdict_only else _evidence(finding.evidence, visible),
        submitted_at=assessment.submitted_at,
    )


# --- The call ------------------------------------------------------------------------------------
async def call_summary(db: AsyncSession, call: BidCall) -> BidCallSummary:
    count = await db.scalar(select(func.count()).select_from(Bid).where(Bid.call_id == call.id))
    return BidCallSummary(
        id=call.id,
        title=call.title,
        status=call.status,
        deadline_at=call.deadline_at,
        bid_count=int(count or 0),
    )


async def _agents(db: AsyncSession, settings: Settings, project_id: UUID) -> list[AiAgentRef]:
    now = utcnow()
    return [
        agent_ref(c.agent)
        for c in await candidates(db, project_id)
        if c.usable(AiRunKind.ASSESS_BID, settings, now)
    ]


def _ai_blocked(
    principal: Principal,
    resource: Resource,
    settings: Settings,
    call: BidCall | None,
    agents: list[AiAgentRef],
    *,
    rejected: bool = False,
) -> AiBlockedReason | None:
    decision = authorize(principal, Rule.AI_ASSESS_BID, resource.replace(ai_available=True))
    if not decision.allowed and decision.status in (401, 403, 404):
        return AiBlockedReason.NOT_ALLOWED
    if not settings.ai_enabled:
        return AiBlockedReason.AI_OFF
    if not decision.allowed:
        return _REASONS.get(decision.code, AiBlockedReason.NOT_ALLOWED)
    if call is None or call.status not in _ASSESS_OPEN:
        return AiBlockedReason.BID_CALL_STATE
    if rejected:
        return AiBlockedReason.BID_REJECTED
    if not agents:
        return AiBlockedReason.NO_AGENT
    return None


def call_permissions(
    principal: Principal,
    resource: Resource,
    settings: Settings,
    call: BidCall | None,
    *,
    has_proposal: bool,
    locked: bool,
    agents: list[AiAgentRef],
    sections: list[BidCallSection],
) -> BidCallPermissions:
    finished = call is not None and call.status in FINISHED
    manage = can(principal, Rule.BID_MANAGE, resource)
    blocked = _ai_blocked(principal, resource, settings, call, agents)
    assessing = call is not None and call.status is BidCallStatus.ASSESSING
    can_assess = assessing and any(
        can(principal, Rule.BID_ASSESS, resource.replace(bid_section_id=s.id)) for s in sections
    )
    return BidCallPermissions(
        can_create=call is None
        and has_proposal
        and resource.idea is not None
        and resource.idea.status.value == "proposal"
        and manage,
        can_manage_call=call is not None and manage and not finished,
        can_edit_template=call is not None and manage and not finished and not locked,
        can_upload_documents=call is not None
        and not finished
        and can(principal, Rule.BID_UPLOAD_DOCUMENT, resource),
        can_decide=call is not None and not finished and can(principal, Rule.BID_DECIDE, resource),
        can_delete_call=call is not None and can(principal, Rule.BID_DELETE_CALL, resource),
        can_view_bids=call is not None and can(principal, Rule.BID_VIEW_BIDS, resource),
        can_see_prices=call is not None and sees_price(principal, resource),
        can_view_scores=call is not None and manages(principal, resource),
        can_assess=can_assess,
        assess_section_ids=[s.id for s in sections],
        can_request_ai=blocked is None,
        request_ai_blocked_by=blocked,
    )


async def call_view(
    db: AsyncSession,
    principal: Principal,
    settings: Settings,
    resource: Resource,
    call: BidCall | None,
    *,
    project_id: UUID,
    has_proposal: bool,
) -> BidCallView:
    """``BidCallView`` for the principal: the summary for everyone with ``bid.view_call``,
    the whole call for ``bid.view_bids``."""
    if call is None:
        manage = can(principal, Rule.BID_MANAGE, resource)
        agents = await _agents(db, settings, project_id) if manage else []
        return BidCallView(
            summary=None,
            call=None,
            ai_agents=agents,
            permissions=call_permissions(
                principal,
                resource,
                settings,
                None,
                has_proposal=has_proposal,
                locked=False,
                agents=agents,
                sections=[],
            ),
        )
    data = await load_call_data(db, call)
    summary = BidCallSummary(
        id=call.id,
        title=call.title,
        status=call.status,
        deadline_at=call.deadline_at,
        bid_count=len(data.bids),
    )
    manager = manages(principal, resource)
    agents = (
        await _agents(db, settings, project_id) if can(principal, Rule.BID_MANAGE, resource) else []
    )
    sections = my_sections(principal, resource, data)
    permissions = call_permissions(
        principal,
        resource,
        settings,
        call,
        has_proposal=has_proposal,
        locked=data.human_submitted,
        agents=agents,
        sections=sections,
    )
    full = None
    if can(principal, Rule.BID_VIEW_BIDS, resource):
        full = await _call_out(db, principal, resource, data, summary, manager=manager)
    return BidCallView(summary=summary, call=full, ai_agents=agents, permissions=permissions)


async def _call_out(
    db: AsyncSession,
    principal: Principal,
    resource: Resource,
    data: CallData,
    summary: BidCallSummary,
    *,
    manager: bool,
) -> BidCallOut:
    call = data.call
    users = await user_refs(db, [call.created_by_id])
    assessor = None
    if call.ai_assessor_id is not None:
        agent = await db.get(AiAgent, call.ai_assessor_id)
        assessor = agent_ref(agent) if agent is not None else None
    awarded = next((b for b in data.bids if b.status is BidStatus.AWARDED), None)
    return BidCallOut(
        **summary.model_dump(),
        description=call.description,
        currency=call.currency,
        assessment_due_at=call.assessment_due_at,
        created_by=users.get(call.created_by_id) if call.created_by_id else None,
        created_at=call.created_at,
        updated_at=call.updated_at,
        template=template_out(data),
        progress=data.call_progress(),
        ai_assessor=assessor,
        awarded_at=call.awarded_at,
        awarded_bid=bid_ref(awarded) if awarded is not None else None,
        award_reason=call.award_reason if manager else None,
        cancelled_at=call.cancelled_at,
        cancel_reason=call.cancel_reason if manager else None,
    )


def template_out(data: CallData) -> BidCallTemplate:
    """The call's template copy with each section's assessors and their progress."""
    call = data.call
    price = data.price_question
    sections = [
        BidCallSectionOut(
            id=section.id,
            position=section.position,
            title=section.title,
            guidance=section.guidance,
            weight=section.weight,
            questions=[question_out(q) for q in data.questions.get(section.id, [])],
            has_price=price is not None and price.section_id == section.id,
            assessors=[
                BidAssessor(
                    user=UserRef.model_validate(a.user),
                    assigned_at=a.assigned_at,  # type: ignore[arg-type]
                    can_assess=a.eligible,
                    progress=data.assignment_progress(a),
                )
                for a in data.section_users(section.id)
            ],
        )
        for section in data.sections
    ]
    return BidCallTemplate(
        scale=list(call.scale),
        sections=sections,
        must_haves=[must_have_out(m) for m in data.must_haves],
        price_question_id=price.id if price is not None else None,
        locked=data.human_submitted,
    )


# --- Bids ----------------------------------------------------------------------------------------
async def _document_counts(
    db: AsyncSession, call_id: UUID, bid_ids: list[UUID]
) -> dict[UUID, tuple[int, int]]:
    """Bid -> (documents, of which pricing): one grouped statement."""
    if not bid_ids:
        return {}
    rows = await db.execute(
        select(
            BidDocument.bid_id,
            func.count(),
            func.count().filter(BidDocument.pricing),
        )
        .where(BidDocument.call_id == call_id, BidDocument.bid_id.in_(bid_ids))
        .group_by(BidDocument.bid_id)
    )
    return {bid_id: (int(total), int(pricing)) for bid_id, total, pricing in rows}


def _counts(data: CallData, bid: Bid) -> BidMustHaveCounts:
    results = data.results_of(bid.id)
    return BidMustHaveCounts(
        met=results.count(MustHaveResult.MET),
        not_met=results.count(MustHaveResult.NOT_MET),
        missing=results.count(MustHaveResult.MISSING),
        unchecked=results.count(MustHaveResult.UNCHECKED),
    )


def _state(principal: Principal, data: CallData, bid: Bid, section_id: UUID) -> EvaluatorState:
    status = data.states.get((bid.id, section_id, principal.user_id))
    if status is EvaluationStatus.SUBMITTED:
        return EvaluatorState.SUBMITTED
    if status is EvaluationStatus.DRAFT:
        return EvaluatorState.DRAFT
    return EvaluatorState.INVITED


def bid_out(
    principal: Principal,
    resource: Resource,
    data: CallData,
    bid: Bid,
    documents: tuple[int, int],
    users: Mapping[UUID, UserRef],
    *,
    manager: bool,
    price_visible: bool,
    sections: list[BidCallSection],
) -> BidOut:
    total, pricing = documents
    rejection = None
    if manager and bid.rejected_at is not None:
        rejection = BidRejection(
            reason=bid.rejection_reason or "",
            rejected_by=users.get(bid.rejected_by_id) if bid.rejected_by_id else None,
            rejected_at=bid.rejected_at,
            reinstated_at=bid.reinstated_at,
            reinstated_by=users.get(bid.reinstated_by_id) if bid.reinstated_by_id else None,
        )
    mine = [
        BidSectionState(section=_section_ref(s), state=_state(principal, data, bid, s.id))
        for s in sections
    ]
    my_progress = (
        BidProgress(
            submitted=sum(1 for item in mine if item.state is EvaluatorState.SUBMITTED),
            total=len(mine),
        )
        if mine
        else None
    )
    return BidOut(
        id=bid.id,
        bidder=bid.bidder,
        status=bid.status,
        contact_name=bid.contact_name if manager else "",
        contact_email=bid.contact_email if manager else None,
        received_at=bid.received_at,
        late=_late(data.call, bid),
        price=_price(bid, price_visible),
        price_hidden=not price_visible,
        notes=bid.notes if manager else "",
        rejection=rejection,
        must_haves=_counts(data, bid),
        document_count=total if price_visible else total - pricing,
        restricted_document_count=0 if price_visible else pricing,
        progress=data.bid_progress(bid),
        my_progress=my_progress,
        my_sections=mine,
        entered_by=users.get(bid.entered_by_id) if bid.entered_by_id else None,
        created_at=bid.created_at,
        updated_at=bid.updated_at,
    )


def _bid_users(bids: Iterable[Bid]) -> list[UUID | None]:
    return [
        user_id
        for bid in bids
        for user_id in (bid.entered_by_id, bid.rejected_by_id, bid.reinstated_by_id)
    ]


async def bid_list(
    db: AsyncSession, principal: Principal, resource: Resource, call: BidCall
) -> BidList:
    """``list_bids``: in the order received; assessors don't get rejected bids."""
    data = await load_call_data(db, call, results=True)
    manager = manages(principal, resource)
    visible = [b for b in data.bids if manager or b.status is not BidStatus.REJECTED]
    documents = await _document_counts(db, call.id, [b.id for b in visible])
    users = await user_refs(db, _bid_users(visible))
    price = sees_price(principal, resource)
    sections = my_sections(principal, resource, data)
    return BidList(
        items=[
            bid_out(
                principal,
                resource,
                data,
                bid,
                documents.get(bid.id, (0, 0)),
                users,
                manager=manager,
                price_visible=price,
                sections=sections,
            )
            for bid in visible
        ]
    )


def document_out(document: BidDocument, users: Mapping[UUID, UserRef]) -> BidDocumentOut:
    done = document.extraction_state is ExtractionState.DONE
    chars = document.text_chars if done else None
    return BidDocumentOut(
        id=document.id,
        filename=document.filename,
        type=document.type,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        must_have_id=document.must_have_id,
        pricing=document.pricing,
        active_content=document.active_content,
        uploaded_by=users.get(document.uploaded_by_id) if document.uploaded_by_id else None,
        uploaded_at=document.uploaded_at,
        extraction=BidDocumentExtraction(
            state=document.extraction_state,
            error=document.extraction_error,
            chars=chars,
            truncated=document.text_truncated,
            page_count=math.ceil((chars or 0) / BID_TEXT_PAGE_CHARS) if done else 0,
        ),
    )


def _evidence(items: Iterable[Mapping[str, Any]], visible: set[UUID]) -> list[BidEvidence]:
    """The stored quotes, for documents the principal may see (never a pricing one's)."""
    out = []
    for item in items:
        try:
            document_id = UUID(str(item.get("document_id")))
        except ValueError:
            continue
        if document_id in visible:
            out.append(
                BidEvidence(
                    document_id=document_id,
                    quote=str(item.get("quote", "")),
                    found=bool(item.get("found", False)),
                )
            )
    return out


async def _ai_agents(
    db: AsyncSession, assessments: Iterable[BidAiAssessment]
) -> dict[UUID, UserRef]:
    """AI assessment's agent -> its service account (the AI badge's name)."""
    agent_ids = {a.agent_id for a in assessments}
    if not agent_ids:
        return {}
    rows = await db.execute(
        select(AiAgent.id, User)
        .join(User, User.id == AiAgent.service_account_id)
        .where(AiAgent.id.in_(agent_ids))
    )
    return {agent_id: UserRef.model_validate(user) for agent_id, user in rows}


def must_have_state(
    must_have: BidCallMustHave,
    result: BidMustHaveResult | None,
    documents: list[BidDocument],
    findings: list[BidAiFindingView],
    users: Mapping[UUID, UserRef],
    *,
    price_visible: bool,
) -> BidMustHaveState:
    linked = [d for d in documents if d.must_have_id == must_have.id]
    shown = [d.id for d in linked if price_visible or not d.pricing]
    # Review ACC-1 (role matrix 3a rule 4): a pricing must-have's note is where a manager
    # writes about the price, so it (and who decided, when) is for bid.view_price only.
    decision = result if result is not None and (price_visible or not must_have.pricing) else None
    return BidMustHaveState(
        must_have=must_have_out(must_have),
        result=result.result if result is not None else MustHaveResult.MISSING,
        automatic=result is None or result.decided_at is None,
        decided_by=(
            users.get(decision.decided_by_id)
            if decision is not None and decision.decided_by_id
            else None
        ),
        decided_at=decision.decided_at if decision is not None else None,
        note=decision.note if decision is not None else "",
        document_ids=shown,
        restricted_document_count=len(linked) - len(shown),
        ai_findings=[] if must_have.pricing else findings,
    )


async def bid_detail(
    db: AsyncSession,
    principal: Principal,
    resource: Resource,
    settings: Settings,
    call: BidCall,
    bid: Bid,
    *,
    project_id: UUID,
) -> BidDetail:
    data = await load_call_data(db, call, results=True, ai=True)
    manager = manages(principal, resource)
    price = sees_price(principal, resource)
    documents = list(
        await db.scalars(
            select(BidDocument)
            .where(BidDocument.call_id == call.id, BidDocument.bid_id == bid.id)
            .order_by(BidDocument.uploaded_at, BidDocument.id)
        )
    )
    visible_docs = [d for d in documents if price or not d.pricing]
    visible_ids = {d.id for d in visible_docs}
    ai = data.ai.get(bid.id, [])
    agents = await _ai_agents(db, ai)
    findings: dict[UUID, list[BidAiFindingView]] = defaultdict(list)
    if ai:
        by_id = {a.id: a for a in ai}
        verdict_only = owes_bid(principal, resource, data, bid)
        for finding in await db.scalars(
            select(BidAiFinding).where(BidAiFinding.ai_assessment_id.in_(list(by_id)))
        ):
            assessment = by_id[finding.ai_assessment_id]
            findings[finding.must_have_id].append(
                _finding_view(
                    assessment,
                    finding,
                    agents.get(assessment.agent_id)
                    or UserRef(id=assessment.agent_id, display_name="AI"),
                    visible_ids,
                    verdict_only=verdict_only,
                )
            )
    results = data.results.get(bid.id, {})
    users = await user_refs(
        db,
        [
            *_bid_users([bid]),
            *(d.uploaded_by_id for d in visible_docs),
            *(r.decided_by_id for r in results.values()),
        ],
    )
    counts = (len(documents), sum(1 for d in documents if d.pricing))
    sections = my_sections(principal, resource, data)
    base = bid_out(
        principal,
        resource,
        data,
        bid,
        counts,
        users,
        manager=manager,
        price_visible=price,
        sections=sections,
    )
    states = [
        must_have_state(
            m,
            results.get(m.id),
            documents,
            findings.get(m.id, []),
            users,
            price_visible=price,
        )
        for m in data.must_haves
    ]
    rejected = bid.status is BidStatus.REJECTED
    finished = call.status in FINISHED
    agents_usable = (
        await _agents(db, settings, project_id) if can(principal, Rule.BID_MANAGE, resource) else []
    )
    suggested = any(
        s.result in (MustHaveResult.MISSING, MustHaveResult.NOT_MET)
        or any(f.finding is AiMustHaveFinding.NOT_MET for f in s.ai_findings)
        for s in states
    )
    decide = can(principal, Rule.BID_DECIDE, resource) and not finished
    manage = can(principal, Rule.BID_MANAGE, resource) and not finished
    permissions = BidPermissions(
        can_edit=manage,
        can_delete=can(principal, Rule.BID_DECIDE, resource)
        and call.status in (BidCallStatus.DRAFT, BidCallStatus.OPEN),
        can_upload=can(principal, Rule.BID_UPLOAD_DOCUMENT, resource) and not finished,
        can_decide_must_haves=manage,
        can_reject=decide and not rejected,
        can_reinstate=decide and rejected,
        reject_suggested=decide and not rejected and suggested,
        can_assess=call.status is BidCallStatus.ASSESSING
        and not rejected
        and any(
            can(principal, Rule.BID_ASSESS, resource.replace(bid_section_id=s.id)) for s in sections
        ),
        can_request_ai=_ai_blocked(
            principal, resource, settings, call, agents_usable, rejected=rejected
        )
        is None,
        can_view_ai=manager,
    )
    return BidDetail(
        **base.model_dump(),
        documents=[document_out(d, users) for d in visible_docs],
        must_have_results=states,
        permissions=permissions,
    )


# --- Assessments ---------------------------------------------------------------------------------
async def my_assessment(
    db: AsyncSession,
    call: BidCall,
    bid: Bid,
    section: BidCallSection,
    principal: Principal,
    *,
    can_edit: bool,
) -> MyBidAssessment:
    assessment: BidAssessment | None = await db.scalar(
        select(BidAssessment)
        .where(
            BidAssessment.bid_id == bid.id,
            BidAssessment.section_id == section.id,
            BidAssessment.assessor_id == principal.user_id,
        )
        .execution_options(populate_existing=True)
    )
    questions = list(
        await db.scalars(
            select(BidCallQuestion)
            .where(BidCallQuestion.section_id == section.id)
            .order_by(BidCallQuestion.position, BidCallQuestion.id)
        )
    )
    answers: dict[UUID, BidAssessmentAnswer] = {}
    if assessment is not None:
        answers = {
            a.question_id: a
            for a in await db.scalars(
                select(BidAssessmentAnswer).where(
                    BidAssessmentAnswer.assessment_id == assessment.id
                )
            )
        }
    state = EvaluatorState.INVITED
    if assessment is not None:
        state = (
            EvaluatorState.SUBMITTED
            if assessment.status is EvaluationStatus.SUBMITTED
            else EvaluatorState.DRAFT
        )
    return MyBidAssessment(
        bid_id=bid.id,
        section=_section_ref(section),
        state=state,
        answers=[
            BidAnswer(question_id=q.id, score=answers[q.id].score, comment=answers[q.id].comment)
            for q in questions
            if q.id in answers and q.type is not BidQuestionType.PRICE
        ],
        submitted_at=assessment.submitted_at if assessment is not None else None,
        edited_at=assessment.edited_at if assessment is not None else None,
        can_edit=can_edit,
    )


def _stats(item: Any) -> BidQuestionStats:
    """A question's counted scores (the price question: its automatic score only)."""
    price = item.question.type is BidQuestionType.PRICE
    counted = item.counted
    return BidQuestionStats(
        question_id=item.question.id,
        type=item.question.type,
        mean=_score(item.score, 2),
        min=None if price or not counted else min(counted),
        max=None if price or not counted else max(counted),
        count=(1 if item.score is not None else 0) if price else len(counted),
        disagreement=item.disagreement,
    )


async def section_assessments(
    db: AsyncSession,
    call: BidCall,
    bid: Bid,
    section: BidCallSection,
    *,
    hidden: bool,
    price_visible: bool,
) -> BidSectionAssessments:
    """``list_bid_section_assessments``: nothing but ``hidden`` for a pending assessor."""
    if hidden:
        return BidSectionAssessments(
            bid_id=bid.id,
            section=_section_ref(section),
            hidden=True,
            assessments=[],
            ai=[],
            questions=[],
            section_score=None,
        )
    data = await load_call_data(db, call, answers=True, results=True, ai=True)
    # One bid's scores (the price formula still reads every bid's price): review M2.
    mine = score_bid(data, bid, lowest_scored_price(data)).sections[section.id]
    order = [q.id for q in data.questions.get(section.id, [])]
    rows = await db.execute(
        select(BidAssessment, User)
        .join(User, User.id == BidAssessment.assessor_id)
        .where(
            BidAssessment.bid_id == bid.id,
            BidAssessment.section_id == section.id,
            BidAssessment.status == EvaluationStatus.SUBMITTED,
        )
        .order_by(BidAssessment.submitted_at, BidAssessment.id)
    )
    assessments = []
    for assessment, user in rows:
        answers = data.answers.get((bid.id, section.id, user.id), {})
        assessments.append(
            BidAssessmentView(
                assessor=UserRef.model_validate(user),
                submitted_at=assessment.submitted_at or assessment.updated_at,
                edited_at=assessment.edited_at,
                answers=[
                    BidAnswer(
                        question_id=qid, score=answers[qid].score, comment=answers[qid].comment
                    )
                    for qid in order
                    if qid in answers
                ],
            )
        )
    ai = data.ai.get(bid.id, [])
    agents = await _ai_agents(db, ai)
    visible_docs = await _visible_document_ids(db, call.id, bid.id, price_visible=price_visible)
    score_questions = [
        q.id for q in data.questions.get(section.id, []) if q.type is BidQuestionType.SCORE
    ]
    ai_out = [
        BidAiSectionScores(
            ai_assessment_id=assessment.id,
            agent=agents.get(assessment.agent_id)
            or UserRef(id=assessment.agent_id, display_name="AI"),
            included=assessment.included,
            submitted_at=assessment.submitted_at,
            scores=[
                _ai_score(data.ai_scores[assessment.id][qid], visible_docs)
                for qid in score_questions
                if qid in data.ai_scores.get(assessment.id, {})
            ],
        )
        for assessment in ai
    ]
    return BidSectionAssessments(
        bid_id=bid.id,
        section=_section_ref(section),
        hidden=False,
        assessments=assessments,
        ai=ai_out,
        questions=[_stats(item) for item in mine.questions],
        section_score=_score(mine.score, 1, 20),
    )


def _ai_score(score: Any, visible: set[UUID]) -> BidAiScoreView:
    return BidAiScoreView(
        question_id=score.question_id,
        score=score.score,
        rationale=score.rationale,
        evidence=_evidence(score.evidence, visible),
    )


async def _visible_document_ids(
    db: AsyncSession, call_id: UUID, bid_id: UUID, *, price_visible: bool
) -> set[UUID]:
    statement = select(BidDocument.id).where(
        BidDocument.call_id == call_id, BidDocument.bid_id == bid_id
    )
    if not price_visible:
        statement = statement.where(BidDocument.pricing.is_(False))
    return set(await db.scalars(statement))


# --- The comparison ------------------------------------------------------------------------------
def _hidden(
    principal: Principal, resource: Resource, data: CallData, bid: Bid, section_id: UUID
) -> bool:
    """Section 3a: the principal owes this (bid, section) (through the policy's ✱)."""
    decision = authorize(
        principal,
        Rule.BID_VIEW_SCORES,
        resource.replace(
            bid_section_id=section_id,
            bid_section_submitted=data.submitted(bid.id, section_id, principal.user_id),
        ),
    )
    return decision.hidden


def comparison(principal: Principal, resource: Resource, data: CallData) -> BidComparison:
    """``get_bid_comparison`` (``bid.view_scores``; needs ``answers``, ``results``, ``ai``):
    ranked bids, then the other bids that aren't rejected by when they were received, then
    rejected ones without scores; cells the principal owes are hidden, and while any total
    of a bid that isn't rejected is hidden, no row has a rank (``ranking_hidden``, rows by
    received). Rejected bids' rows show no scores (and hide nothing more: they aren't
    ranked)."""
    call = data.call
    scores, ranking = score_call(data)
    ranks = {item.bid_id: item for item in ranking}
    rows: dict[UUID, BidComparisonRow] = {}
    any_hidden = False
    for bid in data.bids:
        item: BidScores = scores[bid.id]
        rejected = bid.status is BidStatus.REJECTED
        cells = []
        hidden_any = False
        for section in data.sections:
            hidden = not rejected and _hidden(principal, resource, data, bid, section.id)
            hidden_any = hidden_any or hidden
            section_item = item.sections[section.id]
            show = not hidden and not rejected
            cells.append(
                BidSectionScore(
                    section_id=section.id,
                    score=_score(section_item.score, 1, 20) if show else None,
                    hidden=hidden,
                    progress=data.bid_section_progress(bid, section.id),
                    disagreement=section_item.disagreement if show else False,
                )
            )
        any_hidden = any_hidden or hidden_any
        rank = ranks.get(bid.id)
        rows[bid.id] = BidComparisonRow(
            bid=bid_ref(bid),
            received_at=bid.received_at,
            late=_late(call, bid),
            price=_price(bid, True),
            price_score=_score(item.price_score, 2) if not rejected else None,
            sections=cells,
            total=_score(item.total, 1) if not hidden_any and not rejected else None,
            total_hidden=hidden_any,
            rank=rank.rank if rank is not None else None,
            tied=rank.tied if rank is not None else False,
            ai_included=item.ai_included and not rejected,
            progress=data.bid_progress(bid),
        )
    if any_hidden:
        ordered = [rows[b.id] for b in data.bids]
        ordered = [row.model_copy(update={"rank": None, "tied": False}) for row in ordered]
    else:
        ranked = [rows[item.bid_id] for item in ranking]
        rest = [
            rows[b.id]
            for b in data.bids
            if b.id not in ranks and b.status is not BidStatus.REJECTED
        ]
        rejected_rows = [rows[b.id] for b in data.bids if b.status is BidStatus.REJECTED]
        ordered = ranked + rest + rejected_rows
    lowest = lowest_scored_price(data)
    price = data.price_question
    return BidComparison(
        call=BidCallRef(id=call.id, title=call.title, status=call.status),
        currency=call.currency,
        sections=[
            BidComparisonSection(id=s.id, title=s.title, weight=s.weight) for s in data.sections
        ],
        price_section_id=price.section_id if price is not None else None,
        lowest_price=f"{lowest:.2f}" if lowest is not None else None,
        ranking_hidden=any_hidden,
        rows=ordered,
        progress=data.call_progress(),
        complete=data.complete(),
    )


# --- The AI's assessments ------------------------------------------------------------------------
async def ai_assessments_out(
    db: AsyncSession,
    principal: Principal,
    resource: Resource,
    data: CallData,
    bid: Bid,
) -> BidAiAssessmentList:
    """``list_bid_ai_assessments`` (``bid.view_scores``; ``data`` with ``ai``): scores of
    the sections the principal owes for this bid left out (``hidden_section_ids``)."""
    hidden = [s.id for s in data.sections if _hidden(principal, resource, data, bid, s.id)]
    hidden_questions = {q.id for sid in hidden for q in data.questions.get(sid, [])}
    ai = data.ai.get(bid.id, [])
    agents = await _ai_agents(db, ai)
    visible = await _visible_document_ids(
        db, data.call.id, bid.id, price_visible=sees_price(principal, resource)
    )
    findings: dict[UUID, list[BidAiFinding]] = defaultdict(list)
    if ai:
        for finding in await db.scalars(
            select(BidAiFinding).where(BidAiFinding.ai_assessment_id.in_([a.id for a in ai]))
        ):
            findings[finding.ai_assessment_id].append(finding)
    order = {
        q.id: index
        for index, q in enumerate(q for s in data.sections for q in data.questions.get(s.id, []))
    }
    must_order = {m.id: index for index, m in enumerate(data.must_haves)}
    items = []
    for assessment in ai:
        agent = agents.get(assessment.agent_id) or UserRef(
            id=assessment.agent_id, display_name="AI"
        )
        stored = data.ai_scores.get(assessment.id, {})
        scores = [
            _ai_score(stored[qid], visible)
            for qid in sorted(stored, key=lambda qid: order.get(qid, 0))
            if qid not in hidden_questions
        ]
        finding_views = [
            _finding_view(assessment, f, agent, visible, verdict_only=bool(hidden))
            for f in sorted(
                findings.get(assessment.id, []), key=lambda f: must_order.get(f.must_have_id, 0)
            )
        ]
        not_found = sum(1 for s in scores for e in s.evidence if not e.found) + sum(
            1 for f in finding_views for e in f.evidence if not e.found
        )
        items.append(
            BidAiAssessmentOut(
                id=assessment.id,
                bid_id=bid.id,
                agent=agent,
                submitted_at=assessment.submitted_at,
                included=assessment.included,
                scores=scores,
                hidden_section_ids=hidden,
                findings=finding_views,
                quotes_not_found=not_found,
            )
        )
    return BidAiAssessmentList(
        items=items,
        # set_bid_ai_inclusion is 404 while the principal owes a section of this bid
        # (section 3a), so the switch isn't offered then either.
        can_include=can(principal, Rule.BID_MANAGE, resource)
        and data.call.status not in FINISHED
        and not hidden,
    )
