"""A project's proposal template (Phase 8, contract-phase8 section 2).

* :func:`project_template` reads the active sections (key, title, hint) in order: every
  proposal path (the editor, threads, suggestions, "Draft with AI", exports, MCP) resolves
  section keys against it, under the project's ``FOR KEY SHARE`` lock that idea writes
  take first, so a section can't be removed under a write to it.
* :func:`replace_template` (``project.edit_proposal_template``; the caller holds the
  project row ``FOR UPDATE``, like ``replace_rubric``) makes the active template exactly
  the request: existing keys keep their text (a removed key comes back with it), new
  sections get a key from their title, sections left out are archived when anything
  refers to them and deleted otherwise, and every proposal of the project gets a row for
  every active section.

Keys are stable and immutable; a key anything refers to is never deleted, so a stored key
always resolves within its idea's project (contract-phase8 section 2.6).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import Select, delete, func, literal, select, union
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Resource, Rule, authorize
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.ai import AiRun
from app.models.base import utcnow
from app.models.idea import Idea
from app.models.project import Project
from app.models.proposal import Proposal as ProposalRow
from app.models.proposal import ProposalSection as SectionRow
from app.models.proposal import ProposalSuggestion, ProposalThread
from app.models.proposal import ProposalTemplateSection as TemplateRow
from app.schemas.proposals import (
    ProposalTemplate,
    ProposalTemplateSection,
    ProposalTemplateUpdate,
    RemovedTemplateSection,
    section_key_for,
)
from app.services import audit
from app.services.sql import require_unique_lower

__all__ = [
    "Section",
    "Template",
    "UnknownSectionProblem",
    "get_template",
    "project_template",
    "replace_template",
    "require_section",
    "templates_of",
]

UNKNOWN_SECTION_DETAIL: Final = "That section isn't in this project's proposal template."


class UnknownSectionProblem(ProblemError):
    """422 ``unknown_section``: a key the project's template doesn't have (or a removed
    section's) in a thread, a suggestion, an AI draft or the template itself."""

    def __init__(self) -> None:
        super().__init__(422, "unknown_section", detail=UNKNOWN_SECTION_DETAIL)


@dataclass(frozen=True, slots=True)
class Section:
    key: str
    title: str
    hint: str


@dataclass(frozen=True, slots=True)
class Template:
    """A project's active sections, in order."""

    sections: tuple[Section, ...]
    _by_key: dict[str, Section] = field(init=False, repr=False, compare=False)
    _order: dict[str, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_key", {section.key: section for section in self.sections})
        object.__setattr__(
            self, "_order", {section.key: index for index, section in enumerate(self.sections)}
        )

    def get(self, key: str) -> Section | None:
        return self._by_key.get(key)

    def __contains__(self, key: object) -> bool:
        return key in self._by_key

    def position(self, key: str) -> int:
        """Template order of an active key (``KeyError`` for any other)."""
        return self._order[key]

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(section.key for section in self.sections)

    def require(self, key: str) -> Section:
        """The active section, or 422 ``unknown_section``."""
        section = self.get(key)
        if section is None:
            raise UnknownSectionProblem
        return section


def _active(project_ids: Iterable[UUID]) -> Select[TemplateRow]:
    return (
        select(TemplateRow)
        .where(TemplateRow.project_id.in_(list(project_ids)), TemplateRow.archived_at.is_(None))
        .order_by(TemplateRow.project_id, TemplateRow.position, TemplateRow.id)
    )


async def templates_of(db: AsyncSession, project_ids: Iterable[UUID]) -> dict[UUID, Template]:
    """Each project's active template (one statement)."""
    wanted = set(project_ids)
    rows: dict[UUID, list[Section]] = {project_id: [] for project_id in wanted}
    if wanted:
        for row in await db.scalars(_active(wanted)):
            rows[row.project_id].append(Section(row.key, row.title, row.hint))
    return {project_id: Template(tuple(sections)) for project_id, sections in rows.items()}


async def project_template(db: AsyncSession, project_id: UUID) -> Template:
    """The project's active template, in order."""
    return (await templates_of(db, [project_id]))[project_id]


def require_section(
    principal: Principal, rule: Rule, resource: Resource, template: Template, key: str
) -> Section:
    """``rule`` and the section a request names, in the contract's order: the rule's
    401/404/403, then 422 ``unknown_section`` (a key the template doesn't have, or a
    removed section's), then the rule's 409s."""
    decision = authorize(principal, rule, resource)
    if not decision.allowed and decision.status in (401, 403, 404):
        raise decision.problem()
    section = template.require(key)
    if not decision.allowed:
        raise decision.problem()
    return section


# --- Reading the settings ----------------------------------------------------------------
def _project_proposals(project_id: UUID) -> Select[UUID]:
    return (
        select(ProposalRow.id)
        .join(Idea, Idea.id == ProposalRow.idea_id)
        .where(Idea.project_id == project_id)
    )


async def _proposal_counts(db: AsyncSession, project_id: UUID) -> dict[str, int]:
    """Per key: proposals of the project with text in that section (one statement)."""
    rows = await db.execute(
        select(SectionRow.key, func.count())
        .where(
            SectionRow.proposal_id.in_(_project_proposals(project_id)),
            SectionRow.body_md != "",
        )
        .group_by(SectionRow.key)
    )
    return {key: int(count) for key, count in rows.all()}


async def _template_out(db: AsyncSession, project_id: UUID) -> ProposalTemplate:
    rows = list(
        await db.scalars(
            select(TemplateRow)
            .where(TemplateRow.project_id == project_id)
            .order_by(TemplateRow.position, TemplateRow.id)
            .execution_options(populate_existing=True)
        )
    )
    counts = await _proposal_counts(db, project_id)
    active = [row for row in rows if row.archived_at is None]
    removed = sorted(
        (row for row in rows if row.archived_at is not None),
        key=lambda row: (row.archived_at, row.key),
        reverse=True,
    )
    return ProposalTemplate(
        sections=[
            ProposalTemplateSection(
                key=row.key,
                title=row.title,
                hint=row.hint,
                position=index,
                proposal_count=counts.get(row.key, 0),
            )
            for index, row in enumerate(active)
        ],
        removed_sections=[
            RemovedTemplateSection(
                key=row.key,
                title=row.title,
                hint=row.hint,
                removed_at=row.archived_at,
                proposal_count=counts.get(row.key, 0),
            )
            for row in removed
            if row.archived_at is not None
        ],
    )


async def get_template(db: AsyncSession, project: Project) -> ProposalTemplate:
    """``get_proposal_template`` (``project.view``, checked by the caller)."""
    return await _template_out(db, project.id)


# --- Replacing ---------------------------------------------------------------------------
async def _referenced_keys(db: AsyncSession, project_id: UUID, keys: Iterable[str]) -> set[str]:
    """The keys among ``keys`` that something of the project refers to: text in a
    proposal, a margin thread, a suggestion (any status) or an AI run."""
    wanted = list(set(keys))
    if not wanted:
        return set()
    proposals = _project_proposals(project_id)
    found: Any = union(
        select(SectionRow.key.label("key")).where(
            SectionRow.proposal_id.in_(proposals),
            SectionRow.key.in_(wanted),
            SectionRow.body_md != "",
        ),
        select(ProposalThread.section_key.label("key")).where(
            ProposalThread.proposal_id.in_(proposals), ProposalThread.section_key.in_(wanted)
        ),
        select(ProposalSuggestion.section_key.label("key")).where(
            ProposalSuggestion.proposal_id.in_(proposals),
            ProposalSuggestion.section_key.in_(wanted),
        ),
        select(AiRun.section_key.label("key"))
        .join(Idea, Idea.id == AiRun.idea_id)
        .where(Idea.project_id == project_id, AiRun.section_key.in_(wanted)),
    )
    rows: Iterable[str | None] = await db.scalars(select(found.subquery().c.key))
    return {key for key in rows if key is not None}


async def fill_proposal_rows(db: AsyncSession, project_id: UUID) -> None:
    """Every proposal of the project gets the (empty, version 1) rows it lacks for the
    active sections, so a proposal always has a row for every active section."""
    now = utcnow()
    pairs = (
        select(
            ProposalRow.id,
            TemplateRow.key,
            literal(""),
            literal(1),
            literal(now),
        )
        .join(Idea, Idea.id == ProposalRow.idea_id)
        .join(
            TemplateRow,
            (TemplateRow.project_id == Idea.project_id) & TemplateRow.archived_at.is_(None),
        )
        .where(Idea.project_id == project_id)
    )
    await db.execute(
        insert(SectionRow)
        .from_select(
            [
                SectionRow.proposal_id,
                SectionRow.key,
                SectionRow.body_md,
                SectionRow.version,
                SectionRow.updated_at,
            ],
            pairs,
        )
        .on_conflict_do_nothing()
    )


async def replace_template(
    db: AsyncSession, principal: Principal, project: Project, body: ProposalTemplateUpdate
) -> ProposalTemplate:
    """Make the active template exactly ``body.sections``, in order (contract-phase8
    section 2.3). The caller holds the project row ``FOR UPDATE`` and has checked
    ``project.edit_proposal_template``; last write wins."""
    await require_unique_lower(
        db,
        [item.title for item in body.sections],
        field="sections",
        message="section titles must be unique",
    )
    rows = list(
        await db.scalars(
            select(TemplateRow)
            .where(TemplateRow.project_id == project.id)
            .order_by(TemplateRow.position, TemplateRow.id)
            .execution_options(populate_existing=True)
        )
    )
    by_key: Mapping[str, TemplateRow] = {row.key: row for row in rows}
    if any(item.key is not None and item.key not in by_key for item in body.sections):
        raise UnknownSectionProblem
    old_active = [row.key for row in rows if row.archived_at is None]
    requested = {item.key for item in body.sections if item.key is not None}

    # 1. Remove: archive what something refers to, delete the rest (with empty rows).
    removed = [by_key[key] for key in old_active if key not in requested]
    referenced = await _referenced_keys(db, project.id, (row.key for row in removed))
    now = utcnow()
    archived: list[str] = []
    deleted: list[str] = []
    for row in removed:
        if row.key in referenced:
            row.archived_at = now
            archived.append(row.key)
        else:
            deleted.append(row.key)
    if deleted:
        await db.execute(
            delete(SectionRow)
            .where(
                SectionRow.proposal_id.in_(_project_proposals(project.id)),
                SectionRow.key.in_(deleted),
            )
            .execution_options(synchronize_session=False)
        )
        for key in deleted:
            await db.delete(by_key[key])
    await db.flush()

    # 2. Rename and restore through a temporary title (the title index isn't deferrable).
    restored: list[str] = []
    renamed: list[str] = []
    moving: list[TemplateRow] = []
    for item in body.sections:
        if item.key is None:
            continue
        row = by_key[item.key]
        if row.archived_at is not None:
            restored.append(row.key)
        elif row.title != item.title or row.hint != item.hint:
            renamed.append(row.key)
        if row.archived_at is not None or row.title != item.title:
            row.title = f"~{row.id.hex}"
            moving.append(row)
    if moving:
        await db.flush()
    for position, item in enumerate(body.sections):
        if item.key is None:
            continue
        row = by_key[item.key]
        row.title, row.hint, row.position, row.archived_at = item.title, item.hint, position, None
    await db.flush()

    # 3. Add new sections with keys made from their titles.
    taken = {row.key for row in rows if row.key not in deleted}
    added: list[str] = []
    for position, item in enumerate(body.sections):
        if item.key is not None:
            continue
        key = section_key_for(item.title, taken)
        taken.add(key)
        added.append(key)
        db.add(
            TemplateRow(
                id=uuid4(),
                project_id=project.id,
                key=key,
                title=item.title,
                hint=item.hint,
                position=position,
            )
        )
    await db.flush()

    # 4. Every proposal follows the template at once.
    await fill_proposal_rows(db, project.id)

    kept_before = [key for key in old_active if key in requested]
    kept_after = [item.key for item in body.sections if item.key in old_active]
    reordered = kept_before != kept_after
    if added or restored or archived or deleted or renamed or reordered:
        await audit.record(
            db,
            "project.proposal_template_replace",
            actor=principal,
            target_type="project",
            target_id=project.id,
            project_id=project.id,
            details={
                "rule": Rule.PROJECT_EDIT_PROPOSAL_TEMPLATE,
                "added": added,
                "restored": restored,
                "archived": archived,
                "deleted": deleted,
                "renamed": renamed,
                "reordered": reordered,
            },
        )
    return await _template_out(db, project.id)
