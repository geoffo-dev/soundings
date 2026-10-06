"""Proposal suggestions (contract-phase5 section 3.4): the whole new text of one section,
suggested by a member (REST), a person's MCP client or an AI agent (MCP
``propose_proposal_section``), which the owner or an admin accepts or discards.

* **Create** (``proposal.suggest_section``, c7) runs under the idea's lock
  (:func:`app.services.ideas.load_idea` with ``for_update``: project ``FOR KEY SHARE``,
  idea ``FOR UPDATE``), so it never interleaves with an accept or discard, which hold the
  idea ``FOR SHARE``. Under it, the author's earlier pending suggestion for the same
  section is discarded (``decided_by`` the author) and at most
  :data:`MAX_PENDING_SUGGESTIONS` stay pending per proposal.
* **Accept** (``proposal.write``, c7) takes a section save's locks
  (:func:`app.proposals.service.load_idea_shared`), then the suggestion ``FOR UPDATE``,
  and saves its text exactly like ``update_proposal_section`` with the decider's
  ``base_version`` (409 ``proposal_conflict`` with the section as saved now).
* **Discard** takes the same locks in the same order, so it can never overwrite an
  ``accepted`` status set by an accept that changed the section.

``source`` follows the author: ``ai`` for a service account whatever the channel, else
the channel a person used (``api`` or ``mcp``). Suggestions carry no score data, and
Phase 5 records no activity events, notifications or audit entries for them (the MCP
call itself is audited).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Rule, authorize, can, require
from app.domain.principal import Principal
from app.errors import ConflictProblem, NotFoundProblem, ProblemError
from app.models.base import utcnow
from app.models.enums import ProposalSectionKey, SuggestionSource, SuggestionStatus
from app.models.proposal import Proposal as ProposalRow
from app.models.proposal import ProposalSection as SectionRow
from app.models.proposal import ProposalSuggestion as SuggestionRow
from app.proposals.service import (
    SECTION_ORDER,
    load_idea_shared,
    require_proposal,
    update_section,
    user_refs,
)
from app.schemas.common import FieldError
from app.schemas.proposals import (
    MAX_PENDING_SUGGESTIONS,
    AcceptedProposalSuggestion,
    ProposalSectionUpdate,
    ProposalSuggestion,
    ProposalSuggestionAccept,
    ProposalSuggestionCreate,
    ProposalSuggestionList,
    ProposalSuggestionPermissions,
)
from app.services.ideas import LoadedIdea

__all__ = [
    "CreatedSuggestion",
    "accept_suggestion",
    "create_suggestion",
    "discard_suggestion",
    "list_suggestions",
    "suggestion_out",
    "suggestion_source",
]

_NOT_PENDING: Final = "This suggestion has already been accepted."
_NOT_FOUND: Final = "That suggestion isn't on this proposal."


@dataclass(frozen=True, slots=True)
class CreatedSuggestion:
    """A new suggestion, and the id of the author's earlier pending suggestion for the
    section that it replaced, if any."""

    suggestion: ProposalSuggestion
    replaced_id: UUID | None


def suggestion_source(principal: Principal, channel: SuggestionSource) -> SuggestionSource:
    """``ai`` whenever the author is a service account, else the person's channel."""
    if principal.user.is_service_account:
        return SuggestionSource.AI
    return channel


async def _versions(db: AsyncSession, proposal_id: UUID) -> dict[ProposalSectionKey, int]:
    rows = await db.execute(
        select(SectionRow.key, SectionRow.version)
        .where(SectionRow.proposal_id == proposal_id)
        .execution_options(populate_existing=True)
    )
    return {ProposalSectionKey(key): version for key, version in rows}


async def _out(
    db: AsyncSession, rows: Sequence[SuggestionRow], proposal_id: UUID
) -> list[ProposalSuggestion]:
    versions = await _versions(db, proposal_id)
    users = await user_refs(
        db, [user for row in rows for user in (row.author_id, row.decided_by_id)]
    )
    return [
        ProposalSuggestion(
            id=row.id,
            section_key=row.section_key,
            body_md=row.body_md,
            base_version=row.base_version,
            section_changed=versions.get(row.section_key, row.base_version) > row.base_version,
            author=users.get(row.author_id) if row.author_id else None,
            source=row.source,
            status=row.status,
            created_at=row.created_at,
            decided_at=row.decided_at,
            decided_by=users.get(row.decided_by_id) if row.decided_by_id else None,
        )
        for row in rows
    ]


async def suggestion_out(
    db: AsyncSession, row: SuggestionRow, proposal_id: UUID
) -> ProposalSuggestion:
    [suggestion] = await _out(db, [row], proposal_id)
    return suggestion


# --- Reading ---------------------------------------------------------------------------
async def list_suggestions(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea
) -> ProposalSuggestionList:
    """``proposal.view``: the pending suggestions in template order, then oldest first,
    with what the principal may do. 404 when the idea has no proposal."""
    proposal = await require_proposal(db, loaded)
    require(principal, Rule.PROPOSAL_VIEW, loaded.resource)
    rows = list(
        await db.scalars(
            select(SuggestionRow)
            .where(
                SuggestionRow.proposal_id == proposal.id,
                SuggestionRow.status == SuggestionStatus.PENDING,
            )
            .order_by(SuggestionRow.created_at, SuggestionRow.id)
            .limit(MAX_PENDING_SUGGESTIONS)
        )
    )
    rows.sort(key=lambda row: SECTION_ORDER[row.section_key])  # stable: oldest first within
    return ProposalSuggestionList(
        items=await _out(db, rows, proposal.id),
        permissions=ProposalSuggestionPermissions(
            can_suggest=can(principal, Rule.PROPOSAL_SUGGEST_SECTION, loaded.resource),
            can_decide=can(principal, Rule.PROPOSAL_WRITE, loaded.resource),
        ),
    )


# --- Create ----------------------------------------------------------------------------
class BaseVersionAheadProblem(ProblemError):
    def __init__(self) -> None:
        super().__init__(
            422,
            "validation_error",
            title="Validation Failed",
            detail="base_version is above the section's current version.",
            errors=[
                FieldError(
                    loc=["body", "base_version"],
                    msg="Above the section's current version.",
                    type="value_error",
                )
            ],
        )


async def create_suggestion(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedIdea,
    body: ProposalSuggestionCreate,
    *,
    channel: SuggestionSource,
) -> CreatedSuggestion:
    """``proposal.suggest_section`` (c7). ``loaded`` must hold the idea's ``FOR UPDATE``
    lock (``load_idea(..., for_update=True)``). 404 without a proposal; 403 for a role
    that may not suggest; 422 for a ``base_version`` above the section's; then the
    policy's 409s (c7, archived; the contract's check order puts them after the body's
    422) and 409 ``too_many_suggestions`` past 50 pending."""
    proposal = await require_proposal(db, loaded)
    decision = authorize(principal, Rule.PROPOSAL_SUGGEST_SECTION, loaded.resource)
    if not decision.allowed and decision.status != 409:
        raise decision.problem()
    current = await db.scalar(
        select(SectionRow.version).where(
            SectionRow.proposal_id == proposal.id, SectionRow.key == body.section_key
        )
    )
    if current is None:  # pragma: no cover - every proposal has all eight sections
        raise NotFoundProblem("This idea has no proposal yet.")
    base_version = current if body.base_version is None else body.base_version
    if base_version > current:
        raise BaseVersionAheadProblem
    if not decision.allowed:
        raise decision.problem()
    now = utcnow()
    replaced_id = await db.scalar(
        update(SuggestionRow)
        .where(
            SuggestionRow.proposal_id == proposal.id,
            SuggestionRow.section_key == body.section_key,
            SuggestionRow.author_id == principal.user_id,
            SuggestionRow.status == SuggestionStatus.PENDING,
        )
        .values(status=SuggestionStatus.DISCARDED, decided_by_id=principal.user_id, decided_at=now)
        .returning(SuggestionRow.id)
        .execution_options(synchronize_session=False)
    )
    pending = await db.scalar(
        select(func.count())
        .select_from(SuggestionRow)
        .where(
            SuggestionRow.proposal_id == proposal.id,
            SuggestionRow.status == SuggestionStatus.PENDING,
        )
    )
    if int(pending or 0) >= MAX_PENDING_SUGGESTIONS:
        raise ConflictProblem(
            f"This proposal already has {MAX_PENDING_SUGGESTIONS} suggestions waiting for a "
            "decision: accept or discard some first.",
            code="too_many_suggestions",
        )
    row = SuggestionRow(
        id=uuid4(),
        proposal_id=proposal.id,
        section_key=body.section_key,
        body_md=body.body_md,
        base_version=base_version,
        author_id=principal.user_id,
        source=suggestion_source(principal, channel),
        status=SuggestionStatus.PENDING,
        created_at=now,
    )
    db.add(row)
    await db.flush()
    return CreatedSuggestion(await suggestion_out(db, row, proposal.id), replaced_id)


# --- Decide ----------------------------------------------------------------------------
async def _decision_target(
    db: AsyncSession, principal: Principal, ref: str, suggestion_id: UUID
) -> tuple[LoadedIdea, ProposalRow, SuggestionRow]:
    """A section save's locks (project ``FOR KEY SHARE``, idea ``FOR SHARE``), then the
    suggestion ``FOR UPDATE``; 404 when it isn't on this idea's proposal; then
    ``proposal.write`` (403, or 409 for c7, archived and held ideas)."""
    loaded = await load_idea_shared(db, principal, ref)
    proposal = await require_proposal(db, loaded)
    row = await db.scalar(
        select(SuggestionRow)
        .where(SuggestionRow.id == suggestion_id, SuggestionRow.proposal_id == proposal.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise NotFoundProblem(_NOT_FOUND)
    require(principal, Rule.PROPOSAL_WRITE, loaded.resource)
    return loaded, proposal, row


def _not_pending(row: SuggestionRow) -> ConflictProblem:
    if row.status is SuggestionStatus.ACCEPTED:
        return ConflictProblem(_NOT_PENDING, code="suggestion_not_pending")
    return ConflictProblem(
        "This suggestion has already been discarded.", code="suggestion_not_pending"
    )


async def accept_suggestion(
    db: AsyncSession,
    principal: Principal,
    ref: str,
    suggestion_id: UUID,
    body: ProposalSuggestionAccept,
) -> AcceptedProposalSuggestion:
    """Save the suggestion's text as its section's (raises
    :class:`app.proposals.service.SectionConflict` when the section changed since
    ``base_version``; equal text saves nothing), then mark it accepted."""
    loaded, proposal, row = await _decision_target(db, principal, ref, suggestion_id)
    if row.status is not SuggestionStatus.PENDING:
        raise _not_pending(row)
    section = await update_section(
        db,
        principal,
        loaded,
        row.section_key,
        ProposalSectionUpdate(body_md=row.body_md, base_version=body.base_version),
    )
    row.status = SuggestionStatus.ACCEPTED
    row.decided_by_id = principal.user_id
    row.decided_at = utcnow()
    await db.flush()
    return AcceptedProposalSuggestion(
        suggestion=await suggestion_out(db, row, proposal.id), section=section
    )


async def discard_suggestion(
    db: AsyncSession, principal: Principal, ref: str, suggestion_id: UUID
) -> ProposalSuggestion:
    """Dismiss a pending suggestion; idempotent for a discarded one, 409
    ``suggestion_not_pending`` for an accepted one."""
    _, proposal, row = await _decision_target(db, principal, ref, suggestion_id)
    if row.status is SuggestionStatus.ACCEPTED:
        raise _not_pending(row)
    if row.status is SuggestionStatus.PENDING:
        row.status = SuggestionStatus.DISCARDED
        row.decided_by_id = principal.user_id
        row.decided_at = utcnow()
        await db.flush()
    return await suggestion_out(db, row, proposal.id)
