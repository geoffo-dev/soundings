"""Proposals: start one, read it, save a section (docs/api/contract-phase4.md 3.1, 3.2).

* **Start** (``proposal.write``, c7: Shortlisted or Proposal): the proposal and its
  eight sections (version 1; Summary starts as the idea's summary), under the idea's
  lock. A Shortlisted idea moves to Proposal in the same transaction through
  :func:`app.services.ideas.change_status`, so the move is an ordinary status change
  (activity event, notifications, the submitter's status email, audit).
* **Save a section** (``proposal.write``): optimistic concurrency per section. The
  project row ``FOR KEY SHARE``, then the idea row ``FOR SHARE`` (:func:`load_idea_shared`):
  saves to different sections run side by side, while a status change (which updates
  the idea row) and a save wait for each other, so c7 is checked against a status
  that can't change before the save commits. Then one
  ``UPDATE ... WHERE version = :base_version`` per save; no row updated means someone
  saved since (409 ``proposal_conflict`` with the section as it is now), unless the
  text is already what was sent (a retried save: 200, unchanged).

Section saves are not activity events and don't touch the idea row.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Resource, Rule, can, idea_resource, not_found, require, require_view
from app.domain.idea_keys import IdeaKey, parse_idea_ref
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.base import utcnow
from app.models.enums import IdeaStatus, ProposalSectionKey
from app.models.idea import Idea
from app.models.project import Project
from app.models.proposal import Proposal as ProposalRow
from app.models.proposal import ProposalSection as SectionRow
from app.models.user import User
from app.schemas.ideas import StatusChange
from app.schemas.proposals import (
    PROPOSAL_TEMPLATE,
    Proposal,
    ProposalPermissions,
    ProposalSection,
    ProposalSectionUpdate,
    ProposalView,
    TemplateSection,
)
from app.schemas.users import UserRef
from app.services import ideas
from app.services.ideas import LoadedIdea
from app.services.refs import idea_ref

__all__ = [
    "SECTION_ORDER",
    "SectionConflict",
    "create_proposal",
    "find_proposal",
    "load_idea_shared",
    "proposal_permissions",
    "proposal_view",
    "require_proposal",
    "section_rows",
    "update_section",
    "user_refs",
]

TEMPLATE: Final[dict[ProposalSectionKey, TemplateSection]] = {
    section.key: section for section in PROPOSAL_TEMPLATE
}
SECTION_ORDER: Final[dict[ProposalSectionKey, int]] = {
    section.key: index for index, section in enumerate(PROPOSAL_TEMPLATE)
}


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
    principal: Principal, resource: Resource, *, exists: bool
) -> ProposalPermissions:
    write = can(principal, Rule.PROPOSAL_WRITE, resource)
    return ProposalPermissions(
        can_create=write and not exists,
        can_edit=write and exists,
        can_comment=can(principal, Rule.PROPOSAL_COMMENT, resource),
        can_export=exists and can(principal, Rule.PROPOSAL_EXPORT, resource),
    )


async def user_refs(db: AsyncSession, user_ids: Iterable[UUID | None]) -> dict[UUID, UserRef]:
    wanted = {user_id for user_id in user_ids if user_id is not None}
    if not wanted:
        return {}
    users = await db.scalars(select(User).where(User.id.in_(wanted)))
    return {user.id: UserRef.model_validate(user) for user in users}


def section_out(row: SectionRow, users: dict[UUID, UserRef]) -> ProposalSection:
    template = TEMPLATE[row.key]
    return ProposalSection(
        key=row.key,
        title=template.title,
        prompt=template.prompt,
        body_md=row.body_md,
        version=row.version,
        updated_at=row.updated_at,
        updated_by=users.get(row.updated_by_id) if row.updated_by_id else None,
    )


async def section_rows(db: AsyncSession, proposal_id: UUID) -> list[SectionRow]:
    """All eight sections, in template order."""
    rows = await db.scalars(
        select(SectionRow)
        .where(SectionRow.proposal_id == proposal_id)
        .execution_options(populate_existing=True)
    )
    return sorted(rows, key=lambda row: SECTION_ORDER[row.key])


async def _proposal_out(db: AsyncSession, loaded: LoadedIdea, proposal: ProposalRow) -> Proposal:
    rows = await section_rows(db, proposal.id)
    users = await user_refs(db, [proposal.created_by_id, *(row.updated_by_id for row in rows)])
    return Proposal(
        id=proposal.id,
        idea=idea_ref(loaded.idea, loaded.project),
        sections=[section_out(row, users) for row in rows],
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
    return ProposalView(
        proposal=None if proposal is None else await _proposal_out(db, loaded, proposal),
        permissions=proposal_permissions(principal, resource, exists=proposal is not None),
    )


async def create_proposal(db: AsyncSession, principal: Principal, loaded: LoadedIdea) -> None:
    """Start the proposal (``loaded`` must hold the idea's ``FOR UPDATE`` lock)."""
    require(principal, Rule.PROPOSAL_WRITE, loaded.resource)
    idea = loaded.idea
    if await find_proposal(db, idea.id) is not None:
        raise ProblemError(409, "proposal_exists", detail="This idea already has a proposal.")
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
            body_md=idea.summary if section.key is ProposalSectionKey.SUMMARY else "",
            version=1,
            updated_by_id=None,
            updated_at=now,
        )
        for section in PROPOSAL_TEMPLATE
    )
    await db.flush()
    if idea.status is IdeaStatus.SHORTLISTED:
        await ideas.change_status(db, principal, loaded, StatusChange(status=IdeaStatus.PROPOSAL))


async def update_section(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedIdea,
    key: ProposalSectionKey,
    body: ProposalSectionUpdate,
) -> ProposalSection:
    """Save one section (``loaded`` from :func:`load_idea_shared`). Raises
    :class:`SectionConflict` when the section changed since ``base_version``."""
    proposal = await require_proposal(db, loaded)
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
    if current is None:  # pragma: no cover - every proposal has all eight sections
        raise not_found()
    section = section_out(current, await user_refs(db, [current.updated_by_id]))
    if saved is None and current.body_md != body.body_md:
        raise SectionConflict(section)
    return section
