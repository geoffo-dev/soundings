"""Loading an idea's call for bids with the principal's facts, in the order of checks the
contract fixes (contract-phase10 section 2.1):

1. 401 (the route's principal);
2. 404: the idea (``idea.view``; a guest researcher at every bid route: the guest route
   table hides them), then ``bid.view_call``, then the call when the operation needs one;
3. 403: the operation's **call-level** rule (or a key's scope, a session-only rule) before
   any bid, section, document or AI assessment is looked up, so a member gets the same
   403 for a real and an unknown bid id;
4. 404: a bid, section, must-have or AI assessment of another call; a rejected bid for an
   assessor who isn't a call manager; a pricing must-have without ``bid.view_price``;
5. 403: c29 ``not_section_assessor`` (and ``cannot_remove_self``);
6. 422 (bodies, c28), then 409: ``project_archived``, c19, c5 ``idea_closed`` (the
   call-level rule's own conditions, kept in :attr:`LoadedCall.deferred` and raised by
   :meth:`LoadedCall.check`), then the call's state, then the rest.

Writes lock project (``FOR KEY SHARE``) -> idea (``FOR UPDATE``) -> call (``FOR UPDATE``)
-> bid -> AI run (:func:`load_call` with ``write=True`` takes the first three).

Who is who, through the one policy (``app.authz``): :func:`manages` (a call manager: the
idea's owner with member or admin, project admins, platform admins; ``bid.view_scores``
without a section in question), :func:`sees_price` (``bid.view_price``), the +Asr overlay
from :class:`~app.authz.BidCallFacts`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import (
    BidCallFacts,
    Decision,
    Resource,
    Rule,
    authorize,
    not_found,
    require,
)
from app.bids.problems import forbidden
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.bid import Bid, BidCall, BidCallQuestion, BidCallSection, BidSectionAssessor
from app.models.enums import BidCallStatus, BidQuestionType, BidStatus
from app.models.idea import Idea
from app.models.project import Project
from app.services.ideas import LoadedIdea, load_idea

__all__ = [
    "FINISHED",
    "LoadedCall",
    "call_facts",
    "call_of",
    "load_bid",
    "load_call",
    "load_idea_for_call",
    "load_section",
    "manages",
    "require_section_rule",
    "sees_price",
]

FINISHED = frozenset({BidCallStatus.AWARDED, BidCallStatus.CANCELLED})
"""Read-only calls: every write is 409 ``bid_call_finished`` (deleting aside)."""


@dataclass(slots=True)
class LoadedCall:
    """An idea's call the principal may reach, with the facts for decisions."""

    idea: Idea
    project: Project
    call: BidCall
    resource: Resource
    deferred: ProblemError | None = None
    """The call-level rule's own state conditions (409 ``project_archived``, c19, c5), kept
    until the lookups and the 403s and 422s after them are done (:meth:`check`)."""

    def check(self) -> None:
        """Raise the call-level rule's deferred 409, if any (contract section 2.1, step 8)."""
        if self.deferred is not None:
            raise self.deferred

    def require_not_finished(self) -> None:
        """:meth:`check`, then 409 ``bid_call_finished`` for an awarded or cancelled call."""
        from app.bids.problems import conflict

        self.check()
        if self.call.status in FINISHED:
            raise conflict("bid_call_finished")

    @property
    def facts(self) -> BidCallFacts:
        facts = self.resource.bid_call
        assert facts is not None  # noqa: S101 - load_call always sets them
        return facts


def _decide(decision: Decision) -> ProblemError | None:
    """Raise a 401/403/404 now; hand back a 409 (or a condition's 422) for later."""
    if decision.allowed or decision.hidden:
        return None
    problem = decision.problem()
    if decision.status in (401, 403, 404):
        raise problem
    return problem


async def call_of(db: AsyncSession, idea_id: UUID, *, for_update: bool = False) -> BidCall | None:
    """The idea's call (one at most), optionally locked ``FOR UPDATE``."""
    statement = select(BidCall).where(BidCall.idea_id == idea_id)
    if for_update:
        statement = statement.with_for_update()
    call: BidCall | None = await db.scalar(statement.execution_options(populate_existing=True))
    return call


async def call_facts(db: AsyncSession, principal: Principal, call: BidCall) -> BidCallFacts:
    """The call's facts for the principal: its status, the sections they are assigned to
    (the +Asr overlay, which the policy grants only while c28 holds now) and the section
    holding the price question (c29 for prices). One statement."""
    mine = (
        select(func.array_agg(BidSectionAssessor.section_id))
        .where(
            BidSectionAssessor.call_id == call.id,
            BidSectionAssessor.user_id == principal.user_id,
        )
        .scalar_subquery()
    )
    price = (
        select(BidCallQuestion.section_id)
        .where(BidCallQuestion.call_id == call.id, BidCallQuestion.type == BidQuestionType.PRICE)
        .limit(1)
        .scalar_subquery()
    )
    sections, price_section = (await db.execute(select(mine, price))).one()
    return BidCallFacts(
        id=call.id,
        status=call.status,
        my_section_ids=frozenset(sections or ()),
        price_section_id=price_section,
    )


async def load_idea_for_call(
    db: AsyncSession, principal: Principal, ref: str, *, write: bool = False
) -> LoadedIdea:
    """Steps 1-2 without the call: the idea (404 unless viewable), then ``bid.view_call``
    (404 for a guest researcher)."""
    loaded = await load_idea(db, principal, ref, for_update=write)
    require(principal, Rule.BID_VIEW_CALL, loaded.resource)
    return loaded


async def load_call(
    db: AsyncSession,
    principal: Principal,
    ref: str,
    rule: Rule,
    *,
    write: bool = False,
) -> LoadedCall:
    """Steps 1-3: the idea, ``bid.view_call``, the call (404 when there is none), then the
    call-level ``rule`` (its 403s now, its 409s deferred). ``write`` locks project, idea
    and call in that order."""
    loaded = await load_idea_for_call(db, principal, ref, write=write)
    call = await call_of(db, loaded.idea.id, for_update=write)
    if call is None:
        raise not_found()
    resource = loaded.resource.replace(bid_call=await call_facts(db, principal, call))
    deferred = _decide(authorize(principal, rule, resource))
    return LoadedCall(loaded.idea, loaded.project, call, resource, deferred)


def manages(principal: Principal, resource: Resource) -> bool:
    """A call manager (the idea's owner with member or admin, project admins, platform
    admins): ``bid.view_scores`` with no section in question (so never hidden), which only
    they hold (role matrix table M). Through a key, ``read`` is enough."""
    return authorize(principal, Rule.BID_VIEW_SCORES, resource.replace(bid_section_id=None)).allowed


def sees_price(principal: Principal, resource: Resource) -> bool:
    """``bid.view_price``: call managers and the price section's assessors (c29)."""
    return authorize(principal, Rule.BID_VIEW_PRICE, resource).allowed


async def load_bid(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedCall,
    bid_id: UUID,
    *,
    for_update: bool = False,
) -> Bid:
    """Step 4: the call's bid (another call's or unknown: 404); a rejected bid is 404 for a
    section assessor who isn't a call manager (it left their queue)."""
    statement = select(Bid).where(Bid.id == bid_id, Bid.call_id == loaded.call.id)
    if for_update:
        statement = statement.with_for_update()
    bid: Bid | None = await db.scalar(statement.execution_options(populate_existing=True))
    if bid is None:
        raise not_found()
    if bid.status is BidStatus.REJECTED and not manages(principal, loaded.resource):
        raise not_found()
    return bid


async def load_section(db: AsyncSession, loaded: LoadedCall, section_id: UUID) -> BidCallSection:
    """Step 4: a section of the call's template (another call's or unknown: 404)."""
    section: BidCallSection | None = await db.scalar(
        select(BidCallSection).where(
            BidCallSection.id == section_id, BidCallSection.call_id == loaded.call.id
        )
    )
    if section is None:
        raise not_found()
    return section


def require_section_rule(
    principal: Principal,
    loaded: LoadedCall,
    rule: Rule,
    section_id: UUID,
    *,
    submitted: bool = False,
) -> Decision:
    """Step 5: ``rule`` for one section (c29). A 403 is ``not_section_assessor`` (a call
    manager who doesn't assess the section included: only assessors hold these rules on a
    section); a 409 joins the deferred ones (the caller raises it with :meth:`check` after
    its 422s). Returns the decision (``hidden``: blind for the principal, section 3a)."""
    decision = authorize(
        principal,
        rule,
        loaded.resource.replace(bid_section_id=section_id, bid_section_submitted=submitted),
    )
    if decision.allowed or decision.hidden:
        return decision
    if decision.status in (401, 404):
        raise decision.problem()
    if decision.status == 403:
        if decision.code == "insufficient_scope":
            raise decision.problem()
        raise forbidden("not_section_assessor")
    if loaded.deferred is None:
        loaded.deferred = decision.problem()
    return decision
