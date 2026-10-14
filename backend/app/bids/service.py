"""The call for bids' commands (contract-phase10 sections 3, 5, 7): the lifecycle, bids and
their must-haves, rejecting and reinstating, the section assessors and a person's
assessment.

Every command runs after :func:`app.bids.access.load_call` (or ``load_idea_for_call``)
with ``write=True``: project ``FOR KEY SHARE`` -> idea ``FOR UPDATE`` -> call ``FOR
UPDATE``, so every write to one call (and its bids) applies one after the other. The
caller has checked the call-level rule; each command raises the rest in the contract's
order (lookups' 404s, c29's 403s, the 422s, then the deferred 409s of the rule and the
call's state). Writes are audited (ids, fields and counts only: never names, prices,
scores or reasons' text) and never touch the idea's ``updated_at`` or
``last_activity_at``: only ``bid_call_changed`` feed events count as the idea's activity.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import usable
from app.authz import (
    ProjectFacts,
    Rule,
    assessor_eligible,
    bid_pending,
    effective_roles_of,
    not_found,
)
from app.bids import runs
from app.bids.access import LoadedCall, load_bid
from app.bids.data import CallData
from app.bids.problems import (
    assessor_not_eligible,
    conflict,
    forbidden,
    unknown_section,
    unprocessable,
)
from app.bids.templates import copy_into_call, project_template
from app.config import Settings
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.base import utcnow
from app.models.bid import (
    Bid,
    BidAiAssessment,
    BidAssessment,
    BidAssessmentAnswer,
    BidCall,
    BidCallMustHave,
    BidCallQuestion,
    BidDocument,
    BidMustHaveResult,
    BidSectionAssessor,
)
from app.models.enums import (
    AiRunKind,
    BidCallStatus,
    BidQuestionType,
    BidStatus,
    EvaluationStatus,
    IdeaStatus,
    MustHaveKind,
    MustHaveResult,
)
from app.models.idea import Idea
from app.models.proposal import Proposal
from app.models.user import User
from app.notifications import bids as bid_notifications
from app.schemas.bids import (
    BIDS_PER_CALL_MAX,
    BidAiInclusionUpdate,
    BidAssessorsUpdate,
    BidAwardIn,
    BidCallCancelIn,
    BidCallCreate,
    BidCallUpdate,
    BidIn,
    BidUpdate,
    MustHaveDecisionIn,
    MyBidAssessmentIn,
    call_bid_status,
)
from app.schemas.common import FieldError
from app.services import activity, audit
from app.services.ideas import LoadedIdea

__all__ = [
    "award_call",
    "cancel_call",
    "change_status",
    "create_bid",
    "create_call",
    "decide_must_have",
    "delete_bid",
    "delete_call",
    "has_submitted",
    "refresh_status",
    "refresh_statuses",
    "reinstate_bid",
    "reject_bid",
    "save_my_assessment",
    "set_ai_inclusion",
    "set_assessors",
    "sync_document_must_have",
    "update_bid",
    "update_call",
]

_TRANSITIONS: Final[Mapping[tuple[BidCallStatus, BidCallStatus], str]] = {
    (BidCallStatus.DRAFT, BidCallStatus.OPEN): "open",
    (BidCallStatus.OPEN, BidCallStatus.ASSESSING): "close",
    (BidCallStatus.ASSESSING, BidCallStatus.OPEN): "reopen",
}
"""``change_bid_call_status``'s moves (cancelling and awarding have their own routes)."""

_RECEIVED_MAX_AHEAD_SECONDS: Final = 5 * 60
_RECEIVED_MAX_BACK_DAYS: Final = 366


# --- Shared ----------------------------------------------------------------------------------
async def _audit(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedCall | LoadedIdea,
    action: str,
    rule: Rule,
    **details: Any,
) -> None:
    await audit.record(
        db,
        action,
        actor=principal,
        target_type="idea",
        target_id=loaded.idea.id,
        project_id=loaded.idea.project_id,
        details={"rule": rule, **details},
    )


async def _emit(
    db: AsyncSession,
    principal: Principal,
    idea: Idea,
    call: BidCall,
    from_status: BidCallStatus | None,
    to_status: BidCallStatus,
) -> None:
    """The feed's ``bid_call_changed`` (no bid data): the idea's only bid activity."""
    await activity.emit(
        db,
        idea,
        "bid_call_changed",
        actor=principal,
        payload={"call_id": call.id, "from_status": from_status, "to_status": to_status},
    )


def _late(call: BidCall, received_at: datetime) -> bool:
    return call.deadline_at is not None and received_at > call.deadline_at


async def human_submitted(db: AsyncSession, call_id: UUID) -> bool:
    """A person's assessment of the call is submitted (the template lock; no reopening)."""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    BidAssessment.call_id == call_id,
                    BidAssessment.status == EvaluationStatus.SUBMITTED,
                )
            )
        )
    )


async def _results(db: AsyncSession, bid_id: UUID) -> list[MustHaveResult]:
    return list(
        await db.scalars(select(BidMustHaveResult.result).where(BidMustHaveResult.bid_id == bid_id))
    )


async def refresh_status(db: AsyncSession, bid: Bid) -> None:
    """Keep ``bids.status`` equal to :func:`call_bid_status` of its facts (before the
    award; an awarded or unsuccessful bid keeps its status)."""
    if bid.status in (BidStatus.AWARDED, BidStatus.UNSUCCESSFUL):
        return
    bid.status = call_bid_status(
        rejected=bid.status is BidStatus.REJECTED, results=await _results(db, bid.id)
    )


async def refresh_statuses(db: AsyncSession, call: BidCall) -> None:
    """:func:`refresh_status` for every bid of the call (after the template changed)."""
    bids = list(await db.scalars(select(Bid).where(Bid.call_id == call.id)))
    for bid in bids:
        await refresh_status(db, bid)
    await db.flush()


async def sync_document_must_have(
    db: AsyncSession, call_id: UUID, bid_id: UUID, must_have_id: UUID
) -> None:
    """A document must-have's result after its linked files changed (section 5.3): with a
    file it is met unless a person decided not met; without one it is missing again, a
    person's met included (it was about that file); a person's not met stays. Then the
    bid's status. For the document routes (link, unlink, delete) and the template copy."""
    result = await db.get(BidMustHaveResult, (bid_id, must_have_id), populate_existing=True)
    must_have = await db.get(BidCallMustHave, must_have_id)
    if result is None or must_have is None or must_have.kind is not MustHaveKind.DOCUMENT:
        return
    linked = int(
        await db.scalar(
            select(func.count())
            .select_from(BidDocument)
            .where(
                BidDocument.call_id == call_id,
                BidDocument.bid_id == bid_id,
                BidDocument.must_have_id == must_have_id,
            )
        )
        or 0
    )
    decided = result.decided_at is not None
    if linked == 0:
        if not (decided and result.result is MustHaveResult.NOT_MET):
            result.result = MustHaveResult.MISSING
            result.decided_by_id = None
            result.decided_at = None
    elif not decided:
        result.result = MustHaveResult.MET
    await db.flush()
    bid = await db.get(Bid, bid_id)
    if bid is not None:
        await refresh_status(db, bid)
        await db.flush()


# --- The call --------------------------------------------------------------------------------
async def create_call(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, body: BidCallCreate
) -> BidCall:
    """``bid.manage`` (checked by the caller, its 409s raised here) and c27: no call yet
    (409 ``bid_call_exists``), the idea in Proposal with a proposal (409
    ``bid_call_not_available``). A draft with a copy of the project's template."""
    from app.bids.access import call_of

    if await call_of(db, loaded.idea.id) is not None:
        raise conflict("bid_call_exists")
    idea = loaded.idea
    has_proposal = await db.scalar(select(exists().where(Proposal.idea_id == idea.id)))
    if idea.status is not IdeaStatus.PROPOSAL or not has_proposal:
        raise conflict("bid_call_not_available")
    call = BidCall(
        id=uuid4(),
        idea_id=idea.id,
        title=body.title,
        description=body.description,
        currency=body.currency,
        status=BidCallStatus.DRAFT,
        created_by_id=principal.user_id,
        scale=[],
    )
    template = await project_template(db, idea.project_id)
    call.scale = list(template.scale)
    db.add(call)
    await db.flush()
    await copy_into_call(db, call, template)
    await _emit(db, principal, idea, call, None, BidCallStatus.DRAFT)
    await _audit(db, principal, loaded, "bid_call.create", Rule.BID_MANAGE, call_id=call.id)
    await db.flush()
    return call


async def update_call(
    db: AsyncSession,
    principal: Principal,
    settings: Settings,
    loaded: LoadedCall,
    body: BidCallUpdate,
) -> None:
    """``bid.manage``: the call's settings until the award. The deadline only while a draft
    or open (409 ``bid_call_not_open``), never cleared while open (409
    ``bid_call_deadline_required``); a changed AI assessor must pass c10 for assess_bid
    (409 ``ai_unavailable``)."""
    loaded.require_not_finished()
    call = loaded.call
    changed: list[str] = []
    for field in ("title", "description", "currency"):
        if getattr(body, field) != getattr(call, field):
            changed.append(field)
    deadline_changed = body.deadline_at != call.deadline_at
    if deadline_changed:
        if call.status is BidCallStatus.ASSESSING:
            raise conflict("bid_call_not_open")
        if body.deadline_at is None and call.status is BidCallStatus.OPEN:
            raise conflict("bid_call_deadline_required")
        changed.append("deadline_at")
    if body.ai_assessor_id != call.ai_assessor_id:
        if body.ai_assessor_id is not None and (
            await usable(
                db, settings, body.ai_assessor_id, loaded.idea.project_id, AiRunKind.ASSESS_BID
            )
            is None
        ):
            raise ProblemError(
                409, "ai_unavailable", detail="That agent can't assess bids on this idea now."
            )
        changed.append("ai_assessor_id")
    if not changed:
        return
    call.title, call.description, call.currency = body.title, body.description, body.currency
    call.deadline_at = body.deadline_at
    call.ai_assessor_id = body.ai_assessor_id
    await _audit(
        db, principal, loaded, "bid_call.update", Rule.BID_MANAGE, call_id=call.id, fields=changed
    )
    await db.flush()
    if "ai_assessor_id" in changed and call.ai_assessor_id is not None:
        await _check_automatic(db, call)


async def _check_automatic(db: AsyncSession, call: BidCall) -> None:
    """The call's AI assessor may now start automatic runs: the worker checks once this
    commits (contract-phase10 section 9.1)."""
    from app.bids.assess import defer_automatic_check

    if call.status in (BidCallStatus.OPEN, BidCallStatus.ASSESSING):
        await defer_automatic_check(db, call.id)


async def change_status(
    db: AsyncSession, principal: Principal, loaded: LoadedCall, status: BidCallStatus
) -> None:
    """``bid.manage``: draft -> open (a deadline: 409 ``bid_call_deadline_required``), open
    -> assessing, assessing -> open (no person's assessment submitted: 409
    ``assessments_submitted``); anything else 409 ``invalid_bid_call_transition``."""
    loaded.require_not_finished()
    call = loaded.call
    move = _TRANSITIONS.get((call.status, status))
    if move is None:
        raise conflict("invalid_bid_call_transition")
    if move == "open" and call.deadline_at is None:
        raise conflict("bid_call_deadline_required")
    if move == "reopen" and await human_submitted(db, call.id):
        raise conflict("assessments_submitted")
    before = call.status
    call.status = status
    await _emit(db, principal, loaded.idea, call, before, status)
    await _audit(
        db,
        principal,
        loaded,
        "bid_call.status_change",
        Rule.BID_MANAGE,
        call_id=call.id,
        from_status=before,
        to_status=status,
    )
    await db.flush()
    if call.ai_assessor_id is not None:
        await _check_automatic(db, call)


async def cancel_call(
    db: AsyncSession, principal: Principal, loaded: LoadedCall, body: BidCallCancelIn
) -> None:
    """``bid.decide`` (session only): draft, open or assessing -> cancelled (read-only),
    the active assess runs cancelled. Finished already: 409 ``bid_call_finished``."""
    loaded.require_not_finished()
    call = loaded.call
    before = call.status
    call.status = BidCallStatus.CANCELLED
    call.cancelled_at = utcnow()
    call.cancel_reason = body.reason or None
    await db.flush()
    cancelled = await runs.cancel_assess_runs(db, principal, call)
    await _emit(db, principal, loaded.idea, call, before, BidCallStatus.CANCELLED)
    await _audit(
        db,
        principal,
        loaded,
        "bid_call.status_change",
        Rule.BID_DECIDE,
        call_id=call.id,
        from_status=before,
        to_status=BidCallStatus.CANCELLED,
        reason_given=bool(body.reason),
        cancelled_runs=cancelled,
    )
    await db.flush()


async def delete_call(db: AsyncSession, principal: Principal, loaded: LoadedCall) -> None:
    """``bid.delete_call`` (session only; c30 in the rule): the call with everything in it
    (bids, documents, assessments, AI assessments and runs cascade). The feed's
    ``bid_call_changed`` events stay (their call reads as null)."""
    loaded.check()
    call = loaded.call
    bids = int(
        await db.scalar(select(func.count()).select_from(Bid).where(Bid.call_id == call.id)) or 0
    )
    await _audit(
        db,
        principal,
        loaded,
        "bid_call.delete",
        Rule.BID_DELETE_CALL,
        call_id=call.id,
        status=call.status,
        bids=bids,
    )
    from app.bids.documents import unlink_documents

    await unlink_documents(db, call_id=call.id)
    await db.delete(call)
    await db.flush()


async def award_call(
    db: AsyncSession, principal: Principal, loaded: LoadedCall, body: BidAwardIn
) -> None:
    """``bid.decide`` (session only), while assessing: one qualified bid is awarded (409
    ``bid_rejected`` / ``bid_not_qualified``), every other bid that isn't rejected becomes
    unsuccessful, the call is awarded (read-only) and its active assess runs cancelled."""
    bid = await load_bid(db, principal, loaded, body.bid_id)
    loaded.require_not_finished()
    call = loaded.call
    if call.status is not BidCallStatus.ASSESSING:
        raise conflict("bid_call_not_assessing")
    if bid.status is BidStatus.REJECTED:
        raise conflict("bid_rejected")
    if bid.status is not BidStatus.QUALIFIED:
        raise conflict("bid_not_qualified")
    for other in await db.scalars(select(Bid).where(Bid.call_id == call.id)):
        if other.id == bid.id:
            other.status = BidStatus.AWARDED
        elif other.status is not BidStatus.REJECTED:
            other.status = BidStatus.UNSUCCESSFUL
    call.status = BidCallStatus.AWARDED
    call.awarded_at = utcnow()
    call.awarded_by_id = principal.user_id
    call.award_reason = body.reason or None
    await db.flush()
    cancelled = await runs.cancel_assess_runs(db, principal, call)
    await _emit(db, principal, loaded.idea, call, BidCallStatus.ASSESSING, BidCallStatus.AWARDED)
    await _audit(
        db,
        principal,
        loaded,
        "bid_call.award",
        Rule.BID_DECIDE,
        call_id=call.id,
        bid_id=bid.id,
        reason_given=bool(body.reason),
        cancelled_runs=cancelled,
    )
    await db.flush()


# --- Bids ------------------------------------------------------------------------------------
async def _price_question(db: AsyncSession, call_id: UUID) -> bool:
    return bool(
        await db.scalar(
            select(
                exists().where(
                    BidCallQuestion.call_id == call_id,
                    BidCallQuestion.type == BidQuestionType.PRICE,
                )
            )
        )
    )


def _check_received(value: datetime) -> datetime:
    """A changed ``received_at`` on update: within a year back and not ahead (422)."""
    utc = value.astimezone(UTC)
    now = datetime.now(UTC)
    if not (
        now.timestamp() - _RECEIVED_MAX_BACK_DAYS * 86400
        <= utc.timestamp()
        <= now.timestamp() + _RECEIVED_MAX_AHEAD_SECONDS
    ):
        raise ProblemError(
            422,
            "validation_error",
            title="Validation Failed",
            detail="The request is invalid; see errors for details.",
            errors=[
                FieldError(
                    loc=["body", "received_at"],
                    msg="Value error, received_at must be in the past year (not in the future)",
                    type="value_error",
                )
            ],
        )
    return utc


async def create_bid(
    db: AsyncSession, principal: Principal, loaded: LoadedCall, body: BidIn
) -> Bid:
    """``bid.manage``, while the call is open (409 ``bid_call_not_open``): its must-haves
    start missing (documents) or unchecked (confirmations); a call without must-haves
    qualifies it at once. 50 per call (409 ``too_many_bids``)."""
    call = loaded.call
    if body.price is not None and not await _price_question(db, call.id):
        raise unprocessable("price_not_asked", loc=["body", "price"])
    loaded.require_not_finished()
    if call.status is not BidCallStatus.OPEN:
        raise conflict("bid_call_not_open")
    count = int(
        await db.scalar(select(func.count()).select_from(Bid).where(Bid.call_id == call.id)) or 0
    )
    if count >= BIDS_PER_CALL_MAX:
        raise conflict("too_many_bids")
    bid = Bid(
        id=uuid4(),
        call_id=call.id,
        bidder=body.bidder,
        contact_name=body.contact_name,
        contact_email=body.contact_email,
        received_at=body.received_at or utcnow(),
        price=body.price,
        notes=body.notes,
        status=BidStatus.RECEIVED,
        entered_by_id=principal.user_id,
    )
    db.add(bid)
    await db.flush()
    must_haves = list(
        await db.scalars(select(BidCallMustHave).where(BidCallMustHave.call_id == call.id))
    )
    for must_have in must_haves:
        db.add(
            BidMustHaveResult(
                bid_id=bid.id,
                must_have_id=must_have.id,
                call_id=call.id,
                result=MustHaveResult.MISSING
                if must_have.kind is MustHaveKind.DOCUMENT
                else MustHaveResult.UNCHECKED,
            )
        )
    await db.flush()
    await refresh_status(db, bid)
    await _audit(
        db, principal, loaded, "bid.create", Rule.BID_MANAGE, call_id=call.id, bid_id=bid.id
    )
    await db.flush()
    return bid


async def update_bid(
    db: AsyncSession, principal: Principal, loaded: LoadedCall, bid: Bid, body: BidUpdate
) -> None:
    """``bid.manage``: the complete new state until the award (the stored ``received_at``
    is always accepted; a changed one within a year back and not ahead)."""
    received = body.received_at.astimezone(UTC)
    if received != bid.received_at:
        received = _check_received(received)
    if body.price is not None and not await _price_question(db, loaded.call.id):
        raise unprocessable("price_not_asked", loc=["body", "price"])
    loaded.require_not_finished()
    changed = [
        field
        for field, value in (
            ("bidder", body.bidder),
            ("contact_name", body.contact_name),
            ("contact_email", body.contact_email),
            ("received_at", received),
            ("price", body.price),
            ("notes", body.notes),
        )
        if value != getattr(bid, field)
    ]
    if not changed:
        return
    was_late = _late(loaded.call, bid.received_at)
    bid.bidder, bid.contact_name, bid.contact_email = (
        body.bidder,
        body.contact_name,
        body.contact_email,
    )
    bid.received_at, bid.price, bid.notes = received, body.price, body.notes
    await _audit(
        db,
        principal,
        loaded,
        "bid.update",
        Rule.BID_MANAGE,
        call_id=loaded.call.id,
        bid_id=bid.id,
        fields=changed,
        # Review N4: whether the change made it late or not late any more.
        late=_late(loaded.call, received),
        late_changed=_late(loaded.call, received) != was_late,
    )
    await db.flush()


async def delete_bid(db: AsyncSession, principal: Principal, loaded: LoadedCall, bid: Bid) -> None:
    """``bid.decide`` (session only), while the call is a draft or open (409
    ``bid_call_not_open``): the bid with its documents, results and runs."""
    loaded.require_not_finished()
    if loaded.call.status not in (BidCallStatus.DRAFT, BidCallStatus.OPEN):
        raise conflict("bid_call_not_open")
    await _audit(
        db, principal, loaded, "bid.delete", Rule.BID_DECIDE, call_id=loaded.call.id, bid_id=bid.id
    )
    await db.delete(bid)
    await db.flush()


async def reject_bid(
    db: AsyncSession, principal: Principal, loaded: LoadedCall, bid: Bid, reason: str
) -> None:
    """``bid.decide`` (session only), any time before the award (a new reason replaces the
    old one): out of the queues, the totals, the price formula and the ranking; its active
    assess runs cancelled. Blindness for it never ends (role matrix 3a)."""
    loaded.require_not_finished()
    again = bid.status is BidStatus.REJECTED
    bid.status = BidStatus.REJECTED
    bid.rejected_at = utcnow()
    bid.rejected_by_id = principal.user_id
    bid.rejection_reason = reason
    bid.reinstated_at = None
    bid.reinstated_by_id = None
    await db.flush()
    cancelled = await runs.cancel_assess_runs(db, principal, loaded.call, bid_id=bid.id)
    # Its outstanding assessments are no longer expected (contract section 8, "Progress").
    bid_notifications.queue_completion_check(db, loaded.call.id, principal.user_id)
    await _audit(
        db,
        principal,
        loaded,
        "bid.reject",
        Rule.BID_DECIDE,
        call_id=loaded.call.id,
        bid_id=bid.id,
        again=again,
        cancelled_runs=cancelled,
    )
    await db.flush()


async def reinstate_bid(
    db: AsyncSession, principal: Principal, loaded: LoadedCall, bid: Bid
) -> None:
    """``bid.decide`` (session only), before the award; idempotent. Received or qualified
    again by its must-haves; the last rejection stays on record."""
    loaded.require_not_finished()
    if bid.status is not BidStatus.REJECTED:
        return
    bid.status = call_bid_status(rejected=False, results=await _results(db, bid.id))
    bid.reinstated_at = utcnow()
    bid.reinstated_by_id = principal.user_id
    await _audit(
        db,
        principal,
        loaded,
        "bid.reinstate",
        Rule.BID_DECIDE,
        call_id=loaded.call.id,
        bid_id=bid.id,
    )
    await db.flush()


async def decide_must_have(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedCall,
    bid: Bid,
    must_have: BidCallMustHave,
    body: MustHaveDecisionIn,
) -> BidMustHaveResult:
    """``bid.manage``, before the award: met or not met (with a note), or clear the decision
    (null: a document's result follows its files again, a confirmation is unchecked). A
    document without a linked file can't be met (409 ``document_missing``)."""
    loaded.require_not_finished()
    result = await db.get(BidMustHaveResult, (bid.id, must_have.id), populate_existing=True)
    if result is None:  # a row for every pair is written with the bid or the must-have
        result = BidMustHaveResult(
            bid_id=bid.id,
            must_have_id=must_have.id,
            call_id=loaded.call.id,
            result=MustHaveResult.UNCHECKED,
        )
        db.add(result)
    linked = 0
    if must_have.kind is MustHaveKind.DOCUMENT:
        linked = int(
            await db.scalar(
                select(func.count())
                .select_from(BidDocument)
                .where(BidDocument.bid_id == bid.id, BidDocument.must_have_id == must_have.id)
            )
            or 0
        )
    if body.result is MustHaveResult.MET and must_have.kind is MustHaveKind.DOCUMENT and not linked:
        raise conflict("document_missing")
    if body.result is None:
        if must_have.kind is MustHaveKind.DOCUMENT:
            result.result = MustHaveResult.MET if linked else MustHaveResult.MISSING
        else:
            result.result = MustHaveResult.UNCHECKED
        result.decided_by_id = None
        result.decided_at = None
        result.note = ""
    else:
        result.result = body.result
        result.decided_by_id = principal.user_id
        result.decided_at = utcnow()
        result.note = body.note
    await db.flush()
    await refresh_status(db, bid)
    await _audit(
        db,
        principal,
        loaded,
        "bid.must_have_decide",
        Rule.BID_MANAGE,
        call_id=loaded.call.id,
        bid_id=bid.id,
        must_have_id=must_have.id,
        result=result.result,
        decided=body.result is not None,
    )
    await db.flush()
    return result


# --- Assessors (c28) -------------------------------------------------------------------------
async def _owes(db: AsyncSession, call_id: UUID, section_id: UUID, user_id: UUID) -> bool:
    """The person still owes the section for a bid of the call (rejected ones included):
    a bid without their submitted assessment of it."""
    submitted = (
        exists()
        .where(
            BidAssessment.bid_id == Bid.id,
            BidAssessment.section_id == section_id,
            BidAssessment.assessor_id == user_id,
            BidAssessment.status == EvaluationStatus.SUBMITTED,
        )
        .correlate_except(BidAssessment)
    )
    return bool(await db.scalar(select(exists().where(Bid.call_id == call_id, ~submitted))))


async def _has_submitted(db: AsyncSession, section_id: UUID, user_id: UUID) -> bool:
    return bool(
        await db.scalar(
            select(
                exists().where(
                    BidAssessment.section_id == section_id,
                    BidAssessment.assessor_id == user_id,
                    BidAssessment.status == EvaluationStatus.SUBMITTED,
                )
            )
        )
    )


async def set_assessors(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedCall,
    data: CallData,
    body: BidAssessorsUpdate,
) -> dict[UUID, list[UUID]]:
    """``bid.manage`` (session only by decision): every section's assessors and the
    assessment due date, the complete state. In order: removing yourself from a section you
    still owe (403 ``cannot_remove_self``), a section left out or of another call (422
    ``unknown_section``), someone added who isn't eligible (422 ``assessor_not_eligible``,
    c28, their user row read ``FOR SHARE``), then the 409s (the rule's, the call finished,
    removing someone who submitted that section: ``assessor_has_submitted``). Removing
    someone deletes their drafts of the section. Returns the people added, by section
    (for "Asked to assess bids")."""
    call = loaded.call
    current: dict[UUID, set[UUID]] = {s.id: set() for s in data.sections}
    for assignment in data.assignments:
        current.setdefault(assignment.section_id, set()).add(assignment.user.id)
    wanted = {item.section_id: list(item.user_ids) for item in body.sections}

    # 403: stepping out of a section you owe (review M3).
    for section_id, holders in current.items():
        leaving = principal.user_id in holders and principal.user_id not in wanted.get(
            section_id, []
        )
        if leaving and await _owes(db, call.id, section_id, principal.user_id):
            raise forbidden("cannot_remove_self")
    # 422: the sections, exactly.
    for index, item in enumerate(body.sections):
        if item.section_id not in current:
            raise unknown_section(["body", "sections", index, "section_id"])
    if set(wanted) != set(current):
        raise unknown_section(["body", "sections"])
    # 422: c28 for everyone added, their rows locked FOR SHARE (as c25 reads them).
    added: dict[UUID, list[UUID]] = {}
    newcomers = sorted(
        {
            user_id
            for sid, users in wanted.items()
            for user_id in users
            if user_id not in current[sid]
        }
    )
    if newcomers:
        users = {
            user.id: user
            for user in await db.scalars(
                select(User)
                .where(User.id.in_(newcomers))
                .order_by(User.id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        }
        roles = await effective_roles_of(db, loaded.project.id, newcomers)
        facts = ProjectFacts.of(loaded.project)
        for index, item in enumerate(body.sections):
            for position, user_id in enumerate(item.user_ids):
                if user_id in current[item.section_id]:
                    continue
                user = users.get(user_id)
                if user is None or not assessor_eligible(user, roles.get(user_id), facts):
                    raise assessor_not_eligible(
                        user.display_name if user is not None else None,
                        ["body", "sections", index, "user_ids", position],
                    )
                added.setdefault(item.section_id, []).append(user_id)
    # 409s.
    loaded.require_not_finished()
    removed: dict[UUID, list[UUID]] = {}
    for section_id, holders in current.items():
        for user_id in sorted(holders - set(wanted[section_id])):
            if await _has_submitted(db, section_id, user_id):
                raise conflict("assessor_has_submitted")
            removed.setdefault(section_id, []).append(user_id)

    for section_id, user_ids in removed.items():
        await db.execute(
            delete(BidSectionAssessor).where(
                BidSectionAssessor.section_id == section_id,
                BidSectionAssessor.user_id.in_(user_ids),
            )
        )
    now = utcnow()
    for section_id, user_ids in added.items():
        for user_id in user_ids:
            db.add(
                BidSectionAssessor(
                    section_id=section_id,
                    user_id=user_id,
                    call_id=call.id,
                    assigned_by_id=principal.user_id,
                    assigned_at=now,
                )
            )
    due_changed = body.due_at != call.assessment_due_at
    call.assessment_due_at = body.due_at
    await db.flush()
    # "Asked to assess bids" for the people added (one each, with the due date this request
    # set), and (someone removed) whether nothing expected is outstanding any more.
    bid_notifications.queue_assessors_added(
        db, call.id, principal.user_id, (u for users in added.values() for u in users)
    )
    if removed:
        bid_notifications.queue_completion_check(db, call.id, principal.user_id)
    if added or removed or due_changed:
        await _audit(
            db,
            principal,
            loaded,
            "bid_call.assessors_change",
            Rule.BID_MANAGE,
            call_id=call.id,
            added={str(k): v for k, v in added.items()},
            removed={str(k): v for k, v in removed.items()},
            due_at_changed=due_changed,
        )
        await db.flush()
    return added


# --- A person's assessment -------------------------------------------------------------------
async def save_my_assessment(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedCall,
    bid: Bid,
    section_id: UUID,
    body: MyBidAssessmentIn,
) -> BidAssessment:
    """``bid.assess`` for this section (checked by the caller): the answers replace the saved
    ones; ``submit`` needs every score question scored (422 ``assessment_incomplete``); a
    submitted assessment stays submitted (``edited_at`` on later saves). 422
    ``unknown_question`` / ``not_assessable``; then the 409s: the rule's, the call not
    being assessed, the bid rejected. The first submission is audited (and locks the
    template), and so is every later change to a submitted one (review L7: ``edited``, the
    questions changed)."""
    questions = {
        q.id: q
        for q in await db.scalars(
            select(BidCallQuestion).where(
                BidCallQuestion.call_id == loaded.call.id, BidCallQuestion.section_id == section_id
            )
        )
    }
    for index, answer in enumerate(body.answers):
        question = questions.get(answer.question_id)
        if question is None:
            raise unprocessable("unknown_question", loc=["body", "answers", index, "question_id"])
        if question.type is BidQuestionType.PRICE or (
            question.type is BidQuestionType.COMMENT and answer.score is not None
        ):
            raise unprocessable("not_assessable", loc=["body", "answers", index])
    existing: BidAssessment | None = await db.scalar(
        select(BidAssessment)
        .where(
            BidAssessment.bid_id == bid.id,
            BidAssessment.section_id == section_id,
            BidAssessment.assessor_id == principal.user_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    submitted_before = existing is not None and existing.status is EvaluationStatus.SUBMITTED
    before: dict[UUID, tuple[int | None, str | None]] = {}
    if body.submit or submitted_before:
        scored = {a.question_id for a in body.answers if a.score is not None}
        missing = [
            q for q in questions.values() if q.type is BidQuestionType.SCORE and q.id not in scored
        ]
        if missing:
            raise unprocessable("assessment_incomplete", loc=["body", "answers"])
    loaded.require_not_finished()
    if loaded.call.status is not BidCallStatus.ASSESSING:
        raise conflict("bid_call_not_assessing")
    if bid.status is BidStatus.REJECTED:
        raise conflict("bid_rejected")
    now = utcnow()
    if existing is None:
        existing = BidAssessment(
            id=uuid4(),
            bid_id=bid.id,
            section_id=section_id,
            assessor_id=principal.user_id,
            call_id=loaded.call.id,
            status=EvaluationStatus.DRAFT,
        )
        db.add(existing)
        await db.flush()
    else:
        if submitted_before:
            before = {
                question_id: (score, comment)
                for question_id, score, comment in await db.execute(
                    select(
                        BidAssessmentAnswer.question_id,
                        BidAssessmentAnswer.score,
                        BidAssessmentAnswer.comment,
                    ).where(BidAssessmentAnswer.assessment_id == existing.id)
                )
            }
        await db.execute(
            delete(BidAssessmentAnswer).where(BidAssessmentAnswer.assessment_id == existing.id)
        )
    for answer in body.answers:
        db.add(
            BidAssessmentAnswer(
                assessment_id=existing.id,
                question_id=answer.question_id,
                score=answer.score,
                comment=answer.comment,
            )
        )
    if submitted_before:
        existing.edited_at = now
        # Review L7: after submitting, the assessor sees the others' scores: a change then
        # is audited (which questions, never a score or comment).
        after = {a.question_id: (a.score, a.comment or "") for a in body.answers}
        was = {q: (score, comment or "") for q, (score, comment) in before.items()}
        changed = sorted(
            str(q) for q in questions if was.get(q, (None, "")) != after.get(q, (None, ""))
        )
        if changed:
            await _audit(
                db,
                principal,
                loaded,
                "bid_assessment.submit",
                Rule.BID_ASSESS,
                call_id=loaded.call.id,
                bid_id=bid.id,
                section_id=section_id,
                edited=True,
                changed_question_ids=changed,
            )
    elif body.submit:
        existing.status = EvaluationStatus.SUBMITTED
        existing.submitted_at = now
        bid_notifications.queue_completion_check(db, loaded.call.id, principal.user_id)
        await _audit(
            db,
            principal,
            loaded,
            "bid_assessment.submit",
            Rule.BID_ASSESS,
            call_id=loaded.call.id,
            bid_id=bid.id,
            section_id=section_id,
        )
    existing.updated_at = now
    await db.flush()
    return existing


async def has_submitted(db: AsyncSession, bid_id: UUID, section_id: UUID, user_id: UUID) -> bool:
    """The person has submitted their assessment of the section for the bid (section 3a:
    after that they see its scores)."""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    BidAssessment.bid_id == bid_id,
                    BidAssessment.section_id == section_id,
                    BidAssessment.assessor_id == user_id,
                    BidAssessment.status == EvaluationStatus.SUBMITTED,
                )
            )
        )
    )


# --- The AI's assessments in the totals ------------------------------------------------------
async def set_ai_inclusion(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedCall,
    data: CallData,
    bid: Bid,
    ai_assessment_id: UUID,
    body: BidAiInclusionUpdate,
) -> None:
    """``bid.manage``: count an AI assessment in its bid's scores or leave it out
    (idempotent). 404 for another bid's, and while the principal owes an assessment of the
    bid (section 3a: they don't see the AI's scores yet); 409 once the call is finished."""
    assessment = next((a for a in data.ai.get(bid.id, []) if a.id == ai_assessment_id), None)
    if assessment is None:
        raise not_found()
    for section in data.sections:
        if bid_pending(
            principal,
            loaded.resource.replace(
                bid_section_id=section.id,
                bid_section_submitted=data.submitted(bid.id, section.id, principal.user_id),
            ),
        ):
            raise not_found()
    loaded.require_not_finished()
    if assessment.included == body.include:
        return
    row = await db.get(BidAiAssessment, assessment.id, with_for_update=True)
    if row is None:  # pragma: no cover - read in this transaction
        raise not_found()
    row.included = body.include
    await _audit(
        db,
        principal,
        loaded,
        "bid_assessment.include_ai",
        Rule.BID_MANAGE,
        call_id=loaded.call.id,
        bid_id=bid.id,
        ai_assessment_id=assessment.id,
        include=body.include,
    )
    await db.flush()
