"""Proposals: start one, read it, save a section (docs/api/contract-phase4.md 3.1, 3.2;
Phase 8: over the project's template, contract-phase8 section 2).

* **Start** (``proposal.write``, c7: Shortlisted or Proposal, Phase 8: or Research before a
  proposal step): the proposal and a section per active section of the project's
  template (version 1; a section keyed ``summary`` starts as the idea's summary), under
  the idea's lock. A Shortlisted idea (or one in Research) moves to Proposal in the same
  transaction through :func:`app.services.ideas.change_status`, so the move is an
  ordinary status change (activity event, notifications, the submitter's status email,
  audit) and the research gate and its "Move anyway" are change_status's.
* **Save a section** (``proposal.write``): optimistic concurrency per section. The
  project row ``FOR KEY SHARE``, then the idea row ``FOR SHARE`` (:func:`load_idea_shared`):
  saves to different sections run side by side, while a status change (which updates
  the idea row) and a save wait for each other, so c7 is checked against a status
  that can't change before the save commits; a template replacement (project ``FOR
  UPDATE``) waits too, so a section can't be removed under a save. Then one
  ``UPDATE ... WHERE version = :base_version`` per save; no row updated means someone
  saved since (409 ``proposal_conflict`` with the section as it is now), unless the
  text is already what was sent (a retried save: 200, unchanged). A key the template
  doesn't have (or a removed section's) is 404.

Section saves are not activity events and don't touch the idea row.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Resource, Rule, can, idea_resource, not_found, require, require_view
from app.domain.idea_keys import IdeaKey, parse_idea_ref
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.base import utcnow
from app.models.enums import IdeaStatus, ProposalSectionKey, ResearchStep
from app.models.idea import Idea
from app.models.project import Project
from app.models.proposal import Proposal as ProposalRow
from app.models.proposal import ProposalSection as SectionRow
from app.models.user import User
from app.proposals.template import Section, Template, project_template
from app.schemas.ideas import StatusChange
from app.schemas.proposals import (
    Proposal,
    ProposalPermissions,
    ProposalSection,
    ProposalSectionUpdate,
    ProposalStart,
    ProposalView,
)
from app.schemas.research import crosses_gate
from app.schemas.users import UserRef
from app.services import ideas, research
from app.services.ideas import LoadedIdea
from app.services.refs import idea_ref

__all__ = [
    "SectionConflict",
    "create_proposal",
    "find_proposal",
    "load_idea_shared",
    "proposal_permissions",
    "proposal_view",
    "require_proposal",
    "section_out",
    "section_rows",
    "update_section",
    "user_refs",
]


class SectionConflict(Exception):
    """409 ``proposal_conflict``: ``current`` is the section as saved now."""

    def __init__(self, current: ProposalSection) -> None:
        super().__init__("proposal_conflict")
        self.current = current


async def load_idea_shared(db: AsyncSession, principal: Principal, ref: str) -> LoadedIdea:
    """:func:`app.services.ideas.load_idea` for writes that don't change the idea row
    (section saves, margin comments): the project ``FOR KEY SHARE``, then the idea
    ``FOR SHARE`` (not ``FOR UPDATE``), so these writes don't queue behind each other
    but a status change waits for them and they wait for it (same lock order)."""
    try:
        parsed = parse_idea_ref(ref)
    except ValueError:
        raise not_found() from None
    statement = select(Idea, Project).join(Project, Project.id == Idea.project_id)
    if isinstance(parsed, IdeaKey):
        statement = statement.where(Project.key == parsed.project_key, Idea.number == parsed.number)
    else:
        statement = statement.where(Idea.id == parsed)
    key_share = statement.with_only_columns(Project.id).with_for_update(
        of=Project, read=True, key_share=True
    )
    if await db.scalar(key_share) is None:
        raise not_found()
    row = (
        await db.execute(
            statement.with_for_update(of=Idea, read=True).execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        raise not_found()
    idea, project = row
    resource = await idea_resource(db, principal, idea, project)
    require_view(principal, resource)
    return LoadedIdea(idea, project, resource)


async def find_proposal(
    db: AsyncSession, idea_id: UUID, *, for_update: bool = False
) -> ProposalRow | None:
    statement = select(ProposalRow).where(ProposalRow.idea_id == idea_id)
    if for_update:
        statement = statement.with_for_update()
    proposal: ProposalRow | None = await db.scalar(
        statement.execution_options(populate_existing=True)
    )
    return proposal


async def require_proposal(
    db: AsyncSession, loaded: LoadedIdea, *, for_update: bool = False
) -> ProposalRow:
    """The idea's proposal; 404 when none has been started."""
    proposal = await find_proposal(db, loaded.idea.id, for_update=for_update)
    if proposal is None:
        raise ProblemError(404, "not_found", detail="This idea has no proposal yet.")
    return proposal


def proposal_permissions(
    principal: Principal,
    resource: Resource,
    *,
    exists: bool,
    start_blocked_by_research: bool = False,
) -> ProposalPermissions:
    write = can(principal, Rule.PROPOSAL_WRITE, resource)
    return ProposalPermissions(
        can_create=write and not exists,
        can_edit=write and exists,
        can_comment=can(principal, Rule.PROPOSAL_COMMENT, resource),
        can_export=exists and can(principal, Rule.PROPOSAL_EXPORT, resource),
        start_blocked_by_research=start_blocked_by_research and not exists,
    )


async def _start_blocked_by_research(db: AsyncSession, loaded: LoadedIdea) -> bool:
    """Starting now would cross the research gate (before a proposal step, from
    Shortlisted or Research) while required checklist items are open."""
    step, idea = loaded.project.research_step, loaded.idea
    if step is not ResearchStep.BEFORE_PROPOSAL or not crosses_gate(
        step, idea.status, IdeaStatus.PROPOSAL
    ):
        return False
    if idea.status not in (IdeaStatus.SHORTLISTED, IdeaStatus.RESEARCH):
        return False
    return await research.required_open_count(db, idea) > 0


async def user_refs(db: AsyncSession, user_ids: Iterable[UUID | None]) -> dict[UUID, UserRef]:
    wanted = {user_id for user_id in user_ids if user_id is not None}
    if not wanted:
        return {}
    users = await db.scalars(select(User).where(User.id.in_(wanted)))
    return {user.id: UserRef.model_validate(user) for user in users}


def section_out(row: SectionRow, section: Section, users: dict[UUID, UserRef]) -> ProposalSection:
    return ProposalSection(
        key=row.key,
        title=section.title,
        prompt=section.hint,
        body_md=row.body_md,
        version=row.version,
        updated_at=row.updated_at,
        updated_by=users.get(row.updated_by_id) if row.updated_by_id else None,
    )


async def section_rows(
    db: AsyncSession, proposal_id: UUID, template: Template
) -> list[tuple[SectionRow, Section]]:
    """The proposal's rows of the template's active sections, in template order (rows of
    removed sections keep their text, hidden)."""
    rows = await db.scalars(
        select(SectionRow)
        .where(SectionRow.proposal_id == proposal_id, SectionRow.key.in_(template.keys))
        .execution_options(populate_existing=True)
    )
    found = sorted(rows, key=lambda row: template.position(row.key))
    return [(row, template.require(row.key)) for row in found]


async def _proposal_out(db: AsyncSession, loaded: LoadedIdea, proposal: ProposalRow) -> Proposal:
    template = await project_template(db, loaded.project.id)
    rows = await section_rows(db, proposal.id, template)
    users = await user_refs(db, [proposal.created_by_id, *(row.updated_by_id for row, _ in rows)])
    return Proposal(
        id=proposal.id,
        idea=idea_ref(loaded.idea, loaded.project),
        sections=[section_out(row, section, users) for row, section in rows],
        created_at=proposal.created_at,
        created_by=users.get(proposal.created_by_id) if proposal.created_by_id else None,
        updated_at=proposal.updated_at,
    )


async def proposal_view(db: AsyncSession, principal: Principal, loaded: LoadedIdea) -> ProposalView:
    """The Proposal tab (``proposal.view``): the proposal or null, and the flags. The
    principal's facts are re-read, so the flags follow a change just made."""
    require(principal, Rule.PROPOSAL_VIEW, loaded.resource)
    proposal = await find_proposal(db, loaded.idea.id)
    resource = await idea_resource(db, principal, loaded.idea, loaded.project)
    blocked = proposal is None and await _start_blocked_by_research(db, loaded)
    return ProposalView(
        proposal=None if proposal is None else await _proposal_out(db, loaded, proposal),
        permissions=proposal_permissions(
            principal, resource, exists=proposal is not None, start_blocked_by_research=blocked
        ),
    )


async def create_proposal(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedIdea,
    body: ProposalStart | None = None,
) -> None:
    """Start the proposal (``loaded`` must hold the idea's ``FOR UPDATE`` lock). Order:
    ``proposal.write`` (403; then the override's 403 when ``body`` says "Move anyway";
    then c7, archived, c19) -> 409 ``proposal_exists`` -> the move to Proposal through
    :func:`app.services.ideas.change_status` (the research gate, 409
    ``research_incomplete``, and the override's audit entry are its)."""
    research.require_guarded(principal, Rule.PROPOSAL_WRITE, loaded.resource, body)
    idea = loaded.idea
    if await find_proposal(db, idea.id) is not None:
        raise ProblemError(409, "proposal_exists", detail="This idea already has a proposal.")
    if idea.status in (IdeaStatus.SHORTLISTED, IdeaStatus.RESEARCH):
        change = StatusChange(
            status=IdeaStatus.PROPOSAL,
            override_research=body.override_research if body else None,
            override_reason=body.override_reason if body else None,
        )
        await ideas.change_status(db, principal, loaded, change, operation="create_proposal")
    template = await project_template(db, loaded.project.id)
    now = utcnow()
    proposal = ProposalRow(
        id=uuid4(), idea_id=idea.id, created_by_id=principal.user_id, created_at=now, updated_at=now
    )
    db.add(proposal)
    await db.flush()
    db.add_all(
        SectionRow(
            proposal_id=proposal.id,
            key=section.key,
            body_md=idea.summary if section.key == ProposalSectionKey.SUMMARY else "",
            version=1,
            updated_by_id=None,
            updated_at=now,
        )
        for section in template.sections
    )
    await db.flush()


async def update_section(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedIdea,
    key: str,
    body: ProposalSectionUpdate,
) -> ProposalSection:
    """Save one section (``loaded`` from :func:`load_idea_shared`). Raises
    :class:`SectionConflict` when the section changed since ``base_version``; 404 for a
    key that isn't an active section of the project's template."""
    proposal = await require_proposal(db, loaded)
    section = (await project_template(db, loaded.project.id)).get(key)
    if section is None:
        raise ProblemError(404, "not_found", detail="This section isn't in the proposal template.")
    require(principal, Rule.PROPOSAL_WRITE, loaded.resource)
    now = utcnow()
    saved = (
        await db.execute(
            update(SectionRow)
            .where(
                SectionRow.proposal_id == proposal.id,
                SectionRow.key == key,
                SectionRow.version == body.base_version,
                SectionRow.body_md.is_distinct_from(body.body_md),
            )
            .values(
                body_md=body.body_md,
                version=SectionRow.version + 1,
                updated_by_id=principal.user_id,
                updated_at=now,
            )
            .returning(SectionRow.proposal_id)
            .execution_options(synchronize_session=False)
        )
    ).first()
    if saved is not None:
        await db.execute(
            update(ProposalRow)
            .where(ProposalRow.id == proposal.id)
            .values(updated_at=now)
            .execution_options(synchronize_session=False)
        )
    current = await db.scalar(
        select(SectionRow)
        .where(SectionRow.proposal_id == proposal.id, SectionRow.key == key)
        .execution_options(populate_existing=True)
    )
    if current is None:  # pragma: no cover - a proposal has a row per active section
        raise not_found()
    out = section_out(current, section, await user_refs(db, [current.updated_by_id]))
    if saved is None and current.body_md != body.body_md:
        raise SectionConflict(out)
    return out
