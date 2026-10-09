"""The research step (Phase 8, product owner 2026-10-07; contract-phase8 section 3).

* **Settings** (:func:`settings_out`, :func:`replace_settings`): the project's step and
  checklist, replaced like the rubric under the project row's ``FOR UPDATE`` lock (the
  caller takes it); removing an answered item archives it, restoring brings its answers
  back; changing the step is refused while ideas are in Research (409
  ``ideas_in_research``); with the step off the checklist is kept as it is.
* **Answers** (:func:`answer_item`, :func:`clear_item`): free text per idea and item,
  under the idea's lock (the caller loads it ``FOR UPDATE``).
* **The gate** (:func:`require_guarded`, :func:`check_gate`): one check for every request
  that can take an idea past Research (``ideas.change_status``, which ``create_proposal``
  goes through, ``evaluations.add_evaluators`` and "Ask AI to evaluate"). No bypass.
* **Progress** (:func:`progress_by_idea`): the cards' "2/3", one grouped statement per
  page, none when no idea on the page needs it.
* **Similar ideas** (:func:`similar_ideas`): ``pg_trgm`` over the ideas the principal may
  list (never held ones), across every project they can view.

Answers are plain text people wrote and hold no score data: everyone who can view the
idea reads them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import Numeric, String, and_, cast, exists, func, literal, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import (
    Resource,
    Rule,
    authorize,
    can,
    listed_ideas,
    require,
    research_assignment_flags,
    researched_ideas,
    visible_last_activity,
)
from app.domain.idea_keys import format_key
from app.domain.labels import status_label
from app.domain.principal import Principal
from app.errors import NotFoundProblem, ProblemError
from app.models.base import utcnow
from app.models.enums import IdeaStatus, ResearchStep
from app.models.idea import Idea
from app.models.project import Project
from app.models.research import ResearchAnswer as AnswerRow
from app.models.research import ResearchChecklistItem as ItemRow
from app.models.user import User
from app.schemas.ideas import SimilarIdea, SimilarIdeas
from app.schemas.research import (
    DEFAULT_RESEARCH_CHECKLIST,
    DefaultChecklistItem,
    IdeaResearch,
    IdeaResearchItem,
    IdeasInResearchProblem,
    RemovedResearchItem,
    ResearchAnswer,
    ResearchAnswerIn,
    ResearchChecklistItem,
    ResearchIncompleteProblem,
    ResearchOpenItem,
    ResearchOverride,
    ResearchPermissions,
    ResearchProgress,
    ResearchSettings,
    ResearchSettingsUpdate,
    gate_status,
    gated_statuses,
    shows_research_progress,
)
from app.schemas.users import UserRef
from app.services import audit, research_assignment
from app.services.refs import project_ref
from app.services.sql import any_of, require_unique_lower

__all__ = [
    "SIMILARITY_THRESHOLD",
    "SIMILAR_IDEAS_LIMIT",
    "GateOperation",
    "ResearchAnswerRequiredProblem",
    "ResearchIncompleteError",
    "ResearchStepOffProblem",
    "answer_item",
    "check_gate",
    "clear_item",
    "idea_research",
    "open_required_items",
    "past_research",
    "progress_by_idea",
    "replace_settings",
    "require_guarded",
    "required_open_count",
    "settings_out",
    "similar_ideas",
]

SIMILAR_IDEAS_LIMIT: Final = 5
SIMILARITY_THRESHOLD: Final = 0.3
SIMILAR_CANDIDATES: Final = 20
"""Nearest ideas taken per column (title, summary) before ranking: see ``similar_ideas``."""
"""``pg_trgm``'s default ``similarity_threshold``: the ``%`` operator (served by the
trigram indexes on ``ideas.title`` and ``ideas.summary``) uses it."""

GateOperation = str
"""The guarded request, for the audit entry: ``change_idea_status``, ``add_evaluators``,
``create_proposal`` or ``request_ai_evaluation``."""


class ResearchStepOffProblem(ProblemError):
    """409 ``research_step_off``: the project has no research step."""

    def __init__(self) -> None:
        super().__init__(409, "research_step_off", detail="This project has no research step.")


class ResearchIncompleteError(ProblemError):
    """409 ``research_incomplete`` with the open required items and ``can_override``."""

    def __init__(self, open_items: Sequence[ResearchOpenItem], *, can_override: bool) -> None:
        count = len(open_items)
        items = "item is" if count == 1 else "items are"
        super().__init__(
            409,
            "research_incomplete",
            detail=f"Finish the research checklist first: {count} required {items} open.",
            model=ResearchIncompleteProblem,
            extra={
                "open_items": [item.model_dump(mode="json") for item in open_items],
                "can_override": can_override,
            },
        )
        self.open_items = list(open_items)
        self.can_override = can_override


# --- The gate ------------------------------------------------------------------------------
def _overriding(override: ResearchOverride | None) -> bool:
    return override is not None and bool(override.override_research)


def require_guarded(
    principal: Principal, rule: Rule, resource: Resource, override: ResearchOverride | None
) -> None:
    """A guarded request's own rule and, when it says "Move anyway", the override's, in
    the contract's order (section 3.5): the rule's 401/404/403, then
    ``idea.research_override``'s 403 (``forbidden``; ``insufficient_scope`` for any API
    key: session only), then the rule's 422 and 409. The research gate itself
    (:func:`check_gate`) comes after the request's other 409s."""
    decision = authorize(principal, rule, resource)
    if not decision.allowed and decision.status in (401, 403, 404):
        raise decision.problem()
    if _overriding(override):
        allowed = authorize(principal, Rule.IDEA_RESEARCH_OVERRIDE, resource)
        if not allowed.allowed and allowed.status in (401, 403, 404):
            raise allowed.problem()
    if not decision.allowed:
        raise decision.problem()


def _open_required_statement(idea_id: UUID, project_id: UUID) -> Any:
    answered = exists().where(AnswerRow.idea_id == idea_id, AnswerRow.item_id == ItemRow.id)
    return (
        select(ItemRow.id, ItemRow.title)
        .where(
            ItemRow.project_id == project_id,
            ItemRow.archived_at.is_(None),
            ItemRow.required,
            ~answered,
        )
        .order_by(ItemRow.position, ItemRow.id)
    )


async def open_required_items(db: AsyncSession, idea: Idea) -> list[ResearchOpenItem]:
    """The project's active required items this idea hasn't answered, in order."""
    rows = await db.execute(_open_required_statement(idea.id, idea.project_id))
    return [ResearchOpenItem(item_id=item_id, title=title) for item_id, title in rows]


async def required_open_count(db: AsyncSession, idea: Idea) -> int:
    statement = _open_required_statement(idea.id, idea.project_id)
    count = await db.scalar(select(func.count()).select_from(statement.subquery()))
    return int(count or 0)


async def check_gate(
    db: AsyncSession,
    principal: Principal,
    idea: Idea,
    resource: Resource,
    *,
    operation: GateOperation,
    from_status: IdeaStatus,
    to_status: IdeaStatus,
    override: ResearchOverride | None,
) -> bool:
    """The research gate for a request whose "Guarded when" holds (the caller holds the
    idea's ``FOR UPDATE`` lock, so an answer or a clear is fully before or after). No
    required item open: pass (the flag changes nothing). Open and no override: 409
    ``research_incomplete``. Open and "Move anyway": audited ``idea.research_override``,
    and ``True`` (the status change records ``research_overridden``)."""
    open_items = await open_required_items(db, idea)
    if not open_items:
        return False
    if not _overriding(override):
        raise ResearchIncompleteError(
            open_items, can_override=can(principal, Rule.IDEA_RESEARCH_OVERRIDE, resource)
        )
    require(principal, Rule.IDEA_RESEARCH_OVERRIDE, resource)  # checked at the 403 stage too
    assert override is not None  # noqa: S101 - _overriding
    details: dict[str, Any] = {
        "rule": Rule.IDEA_RESEARCH_OVERRIDE,
        "operation": operation,
        "from_status": from_status,
        "to_status": to_status,
        "open_items": len(open_items),
    }
    if override.override_reason:
        details["reason"] = override.override_reason
    await audit.record(
        db,
        "idea.research_override",
        actor=principal,
        target_type="idea",
        target_id=idea.id,
        project_id=idea.project_id,
        details=details,
    )
    return True


# --- Progress on cards -------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Counted:
    answered: int
    total: int
    required_open: int


async def progress_by_idea(
    db: AsyncSession, ideas: Iterable[tuple[UUID, UUID, IdeaStatus]], steps: Mapping[UUID, Any]
) -> dict[UUID, ResearchProgress]:
    """``IdeaSummary.research`` for a page: ``ideas`` are ``(id, project_id, status)``,
    ``steps`` each project's research step. One grouped statement over the ideas that
    show progress (:func:`shows_research_progress`); none when no idea needs it."""
    wanted = {
        idea_id: project_id
        for idea_id, project_id, status in ideas
        if shows_research_progress(steps.get(project_id, ResearchStep.OFF), status)
    }
    if not wanted:
        return {}
    answered = AnswerRow.idea_id.is_not(None)
    rows = await db.execute(
        select(
            Idea.id,
            func.count(ItemRow.id),
            func.count(ItemRow.id).filter(answered),
            func.count(ItemRow.id).filter(and_(ItemRow.required, ~answered)),
        )
        .join(
            ItemRow,
            and_(ItemRow.project_id == Idea.project_id, ItemRow.archived_at.is_(None)),
        )
        .outerjoin(AnswerRow, and_(AnswerRow.idea_id == Idea.id, AnswerRow.item_id == ItemRow.id))
        .where(any_of(Idea.id, wanted))
        .group_by(Idea.id)
    )
    counted = {
        idea_id: ResearchProgress(answered=done, total=total, required_open=open_)
        for idea_id, total, done, open_ in rows
    }
    empty = ResearchProgress(answered=0, total=0, required_open=0)
    return {idea_id: counted.get(idea_id, empty) for idea_id in wanted}


# --- Settings ------------------------------------------------------------------------------
async def _items(db: AsyncSession, project_id: UUID) -> list[ItemRow]:
    return list(
        await db.scalars(
            select(ItemRow)
            .where(ItemRow.project_id == project_id)
            .order_by(ItemRow.position, ItemRow.id)
            .execution_options(populate_existing=True)
        )
    )


async def ideas_in_research(db: AsyncSession, project_id: UUID) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(Idea)
        .where(Idea.project_id == project_id, Idea.status == IdeaStatus.RESEARCH)
    )
    return int(count or 0)


async def settings_out(db: AsyncSession, project: Project) -> ResearchSettings:
    """``get_research_settings`` (``project.view``, checked by the caller)."""
    rows = await _items(db, project.id)
    archived = [row for row in rows if row.archived_at is not None]
    counts: dict[UUID, int] = {}
    if archived:
        found = await db.execute(
            select(AnswerRow.item_id, func.count())
            .where(any_of(AnswerRow.item_id, [row.id for row in archived]))
            .group_by(AnswerRow.item_id)
        )
        counts = {item_id: int(count) for item_id, count in found.all()}
    removed = sorted(
        (row for row in archived if counts.get(row.id, 0) > 0),
        key=lambda row: (row.archived_at, row.id),
        reverse=True,
    )
    return ResearchSettings(
        step=project.research_step,
        items=[
            ResearchChecklistItem(
                id=row.id, position=index, title=row.title, hint=row.hint, required=row.required
            )
            for index, row in enumerate(row for row in rows if row.archived_at is None)
        ],
        removed_items=[
            RemovedResearchItem(
                id=row.id,
                title=row.title,
                hint=row.hint,
                required=row.required,
                position=row.position,  # Phase 8b: Restore puts it back there
                removed_at=row.archived_at,
                answer_count=counts[row.id],
            )
            for row in removed
            if row.archived_at is not None
        ],
        default_items=[
            DefaultChecklistItem(title=item.title, hint=item.hint, required=item.required)
            for item in DEFAULT_RESEARCH_CHECKLIST
        ],
        ideas_in_research=await ideas_in_research(db, project.id),
    )


async def _replace_checklist(
    db: AsyncSession, project: Project, rows: list[ItemRow], body: ResearchSettingsUpdate
) -> dict[str, int]:
    """Make the active checklist exactly ``body.items`` (the project row is locked)."""
    by_id = {row.id: row for row in rows}
    active = [row for row in rows if row.archived_at is None]
    requested = {item.id for item in body.items if item.id is not None}
    removed = [row for row in active if row.id not in requested]
    answered: set[UUID] = set()
    if removed:
        answered = set(
            await db.scalars(
                select(AnswerRow.item_id)
                .where(any_of(AnswerRow.item_id, [row.id for row in removed]))
                .distinct()
            )
        )
    now = utcnow()
    counts = {"added": 0, "restored": 0, "archived": 0, "deleted": 0, "changed": 0}
    for row in removed:
        if row.id in answered:
            row.archived_at = now
            counts["archived"] += 1
        else:
            await db.delete(row)
            counts["deleted"] += 1
    await db.flush()

    moving = False
    for position, item in enumerate(body.items):
        if item.id is None:
            continue
        row = by_id[item.id]
        if row.archived_at is not None:
            counts["restored"] += 1
        elif (row.title, row.hint, row.required, row.position) != (
            item.title,
            item.hint,
            item.required,
            position,
        ):
            counts["changed"] += 1
        if row.archived_at is not None or row.title != item.title:
            row.title = f"~{row.id.hex}"  # frees the title (the index isn't deferrable)
            moving = True
    if moving:
        await db.flush()
    for position, item in enumerate(body.items):
        if item.id is None:
            continue
        row = by_id[item.id]
        row.title, row.hint, row.required = item.title, item.hint, item.required
        row.position, row.archived_at = position, None
    await db.flush()
    for position, item in enumerate(body.items):
        if item.id is None:
            db.add(
                ItemRow(
                    id=uuid4(),
                    project_id=project.id,
                    position=position,
                    title=item.title,
                    hint=item.hint,
                    required=item.required,
                )
            )
            counts["added"] += 1
    await db.flush()
    return counts


async def replace_settings(
    db: AsyncSession, principal: Principal, project: Project, body: ResearchSettingsUpdate
) -> ResearchSettings:
    """``replace_research_settings`` (contract-phase8 section 3.3). The caller holds the
    project row ``FOR UPDATE`` and has checked ``project.edit_research``."""
    step_on = body.step is not ResearchStep.OFF
    if step_on:
        await require_unique_lower(
            db,
            [item.title for item in body.items],
            field="items",
            message="item titles must be unique",
        )
    rows = await _items(db, project.id)
    if step_on:
        known = {row.id for row in rows}
        if any(item.id is not None and item.id not in known for item in body.items):
            raise ProblemError(
                422,
                "unknown_research_item",
                detail="A checklist item id is not in this project's research checklist.",
            )
    previous = project.research_step
    if body.step is not previous:
        waiting = await ideas_in_research(db, project.id)
        if waiting:
            ideas = "idea is" if waiting == 1 else "ideas are"
            raise ProblemError(
                409,
                "ideas_in_research",
                detail=f"{waiting} {ideas} in Research: move them to another status first.",
                model=IdeasInResearchProblem,
                extra={"idea_count": waiting},
            )
        project.research_step = body.step
        await db.flush()
        await audit.record(
            db,
            "project.research_step_change",
            actor=principal,
            target_type="project",
            target_id=project.id,
            project_id=project.id,
            details={"rule": Rule.PROJECT_EDIT_RESEARCH, "from": previous, "to": body.step},
        )
        if body.step is ResearchStep.OFF:
            # Phase 8b (review S8): turning the step off ends every research assignment in
            # the project (audited, no event; moving the step keeps them).
            await research_assignment.clear_where(
                db, Idea.project_id == project.id, actor=principal, reason="step_off"
            )
    if step_on:
        counts = await _replace_checklist(db, project, rows, body)
        if any(counts.values()):
            await audit.record(
                db,
                "project.research_checklist_replace",
                actor=principal,
                target_type="project",
                target_id=project.id,
                project_id=project.id,
                details={"rule": Rule.PROJECT_EDIT_RESEARCH, **counts},
            )
    return await settings_out(db, project)


# --- An idea's research --------------------------------------------------------------------
async def _users(db: AsyncSession, ids: Iterable[UUID | None]) -> dict[UUID, UserRef]:
    wanted = {user_id for user_id in ids if user_id is not None}
    if not wanted:
        return {}
    found = await db.scalars(select(User).where(any_of(User.id, wanted)))
    return {user.id: UserRef.model_validate(user) for user in found}


async def idea_research(
    db: AsyncSession, principal: Principal, idea: Idea, project: Project, resource: Resource
) -> IdeaResearch:
    """``get_idea_research`` (``idea.view``, checked by the caller). Phase 8b: who does
    the research (``assignment``) and the gate status's label (a guest researcher can't
    read the project's labels)."""
    step = project.research_step
    assign, assign_outside, hand_back = research_assignment_flags(principal, resource)
    permissions = ResearchPermissions(
        can_answer=step is not ResearchStep.OFF
        and can(principal, Rule.IDEA_ANSWER_RESEARCH, resource),
        can_override=step is not ResearchStep.OFF
        and can(principal, Rule.IDEA_RESEARCH_OVERRIDE, resource),
        can_assign=assign,
        can_assign_outside_researcher=assign_outside,
        can_hand_back=hand_back,
    )
    if step is ResearchStep.OFF:
        return IdeaResearch(
            step=step,
            gate_status=None,
            items=[],
            progress=ResearchProgress(answered=0, total=0, required_open=0),
            blocking=False,
            permissions=permissions,
        )
    rows = (
        await db.execute(
            select(ItemRow, AnswerRow)
            .outerjoin(
                AnswerRow, and_(AnswerRow.item_id == ItemRow.id, AnswerRow.idea_id == idea.id)
            )
            .where(ItemRow.project_id == project.id, ItemRow.archived_at.is_(None))
            .order_by(ItemRow.position, ItemRow.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    users = await _users(
        db,
        [
            user
            for _, answer in rows
            if answer
            for user in (answer.answered_by_id, answer.updated_by_id)
        ],
    )
    items = [
        IdeaResearchItem(
            item_id=item.id,
            title=item.title,
            hint=item.hint,
            required=item.required,
            answer=None
            if answer is None
            else ResearchAnswer(
                answer=answer.answer,
                answered_by=users.get(answer.answered_by_id) if answer.answered_by_id else None,
                answered_at=answer.answered_at,
                updated_by=users.get(answer.updated_by_id) if answer.updated_by_id else None,
                updated_at=answer.updated_at,
            ),
        )
        for item, answer in rows
    ]
    required_open = sum(1 for item in items if item.required and item.answer is None)
    blocking = (
        required_open > 0
        and idea.status is not IdeaStatus.CLOSED
        and idea.status not in gated_statuses(step)
    )
    gate = gate_status(step)
    return IdeaResearch(
        step=step,
        gate_status=gate,
        gate_status_label=status_label(project.status_labels, gate, None) if gate else None,
        assignment=await research_assignment.assignment_out(
            db, idea, project, required_open=required_open
        ),
        items=items,
        progress=ResearchProgress(
            answered=sum(1 for item in items if item.answer is not None),
            total=len(items),
            required_open=required_open,
        ),
        blocking=blocking,
        permissions=permissions,
    )


async def _active_item(db: AsyncSession, project_id: UUID, item_id: UUID) -> ItemRow:
    item = await db.scalar(
        select(ItemRow).where(
            ItemRow.id == item_id, ItemRow.project_id == project_id, ItemRow.archived_at.is_(None)
        )
    )
    if item is None:
        raise NotFoundProblem("Not found.")
    return item


async def _require_answering(
    db: AsyncSession, principal: Principal, project: Project, resource: Resource, item_id: UUID
) -> ItemRow:
    """401 -> 404 (the item) -> 403 / 409 (``idea.answer_research``) -> 409 step off."""
    item = await _active_item(db, project.id, item_id)
    require(principal, Rule.IDEA_ANSWER_RESEARCH, resource)
    if project.research_step is ResearchStep.OFF:
        raise ResearchStepOffProblem
    return item


async def answer_item(
    db: AsyncSession,
    principal: Principal,
    idea: Idea,
    project: Project,
    resource: Resource,
    item_id: UUID,
    body: ResearchAnswerIn,
) -> None:
    """Answer an item, or replace its answer (the caller holds the idea's lock). The
    first answer's author and time are kept; identical text changes nothing."""
    item = await _require_answering(db, principal, project, resource, item_id)
    existing = await db.get(AnswerRow, (idea.id, item.id), populate_existing=True)
    now = utcnow()
    if existing is None:
        db.add(
            AnswerRow(
                idea_id=idea.id,
                item_id=item.id,
                answer=body.answer,
                answered_by_id=principal.user_id,
                answered_at=now,
                updated_by_id=principal.user_id,
                updated_at=now,
            )
        )
    elif existing.answer != body.answer:
        existing.answer = body.answer
        existing.updated_by_id = principal.user_id
        existing.updated_at = now
    await db.flush()


class ResearchAnswerRequiredProblem(ProblemError):
    """409 ``research_answer_required``: clearing a required item's answer on an idea past
    Research (code review M1)."""

    def __init__(self) -> None:
        super().__init__(
            409,
            "research_answer_required",
            detail=(
                "This idea is past Research: a required item's answer can be changed but not "
                "cleared."
            ),
        )


def past_research(step: ResearchStep, status: IdeaStatus) -> bool:
    """The idea is in a status after Research (Closed excluded: no answer changes there,
    c5): it crossed the gate, or was there before the step existed or moved."""
    return status in gated_statuses(step)


async def clear_item(
    db: AsyncSession,
    principal: Principal,
    idea: Idea,
    project: Project,
    resource: Resource,
    item_id: UUID,
) -> None:
    """Delete an item's answer (idempotent). Never moves the idea.

    Code review M1: once the idea is past Research a **required** item's answer is kept
    (409 ``research_answer_required``; editing it stays allowed, and records who and
    when), so an answer that let the idea through can't vanish and leave it in Proposal
    at 0/3 with no trace. Optional items, and ideas in Research or before it (where
    clearing re-arms the gate), clear as before."""
    item = await _require_answering(db, principal, project, resource, item_id)
    existing = await db.get(AnswerRow, (idea.id, item.id))
    if existing is None:
        return
    if item.required and past_research(project.research_step, idea.status):
        raise ResearchAnswerRequiredProblem
    await db.delete(existing)
    await db.flush()


# --- Similar ideas -------------------------------------------------------------------------
async def similar_ideas(db: AsyncSession, principal: Principal, idea: Idea) -> SimilarIdeas:
    """Up to 5 ideas like this one (contract-phase8 section 3.7): the principal may list
    them (``listed_ideas``: ``idea.view`` in every project they can view, archived ones
    included, inside a key's projects, never a held idea; Phase 8b: or the ideas they
    research, ``researched_ideas``), never this idea, ``pg_trgm``
    similarity >= 0.3 on the title or the summary, most similar first, then the most
    recently active. No score data.

    The candidates are the nearest titles and the nearest summaries by trigram distance
    (``<->``, served in order by the GiST indexes of migration 0013), so the cost doesn't
    grow with how many ideas match: ``%`` on a project of near-identical summaries
    matched every idea. Any idea in the top 5 by the larger of its two similarities is
    among the nearest few by that column, so ``SIMILAR_CANDIDATES`` per column (well
    above 5, for ties at the shown two decimals) finds the same ideas as a full scan
    unless more than that many tie for fifth place."""
    # Phase 8b: ideas a guest researcher researches count as ones they may list (never
    # the private project's others: contract-phase8b section 4.5).
    visible = (or_(listed_ideas(principal), researched_ideas(principal)), Idea.id != idea.id)
    nearest = [
        select(Idea.id)
        .where(*visible)
        .order_by(Idea.title.op("<->")(literal(idea.title, String)))
        .limit(SIMILAR_CANDIDATES)
    ]
    if idea.summary:
        nearest.append(
            select(Idea.id)
            .where(*visible)
            .order_by(Idea.summary.op("<->")(literal(idea.summary, String)))
            .limit(SIMILAR_CANDIDATES)
        )
    candidates = union(*(query.subquery().select() for query in nearest)).subquery()
    score = func.greatest(
        func.similarity(Idea.title, literal(idea.title, String)),
        func.similarity(Idea.summary, literal(idea.summary, String)),
    )
    shown = func.round(cast(score, Numeric), 2)  # ties as shown: then the latest activity
    # Phase 8b guest review L1: another idea the caller researches as its guest shows (and
    # sorts on) the time of its guest feed's newest event.
    active = visible_last_activity(principal).label("active")
    rows = await db.execute(
        select(Idea, Project, shown.label("score"), active)
        .join(Project, Project.id == Idea.project_id)
        .where(Idea.id.in_(select(candidates.c.id)), score >= SIMILARITY_THRESHOLD)
        .order_by(shown.desc(), active.desc(), Idea.id)
        .limit(SIMILAR_IDEAS_LIMIT)
    )
    found = [(row[0], row[1], float(row[2]), row[3]) for row in rows]
    users = await _users(db, [other.owner_id for other, _, _, _ in found])
    return SimilarIdeas(
        items=[
            SimilarIdea(
                id=other.id,
                key=format_key(project.key, other.number),
                number=other.number,
                project=project_ref(project),
                title=other.title,
                status=other.status,
                resolution=other.resolution,
                status_label=status_label(project.status_labels, other.status, other.resolution),
                summary=other.summary,
                owner=users.get(other.owner_id) if other.owner_id else None,
                last_activity_at=active_at,
                similarity=min(1.0, round(value, 2)),
            )
            for other, project, value, active_at in found
        ]
    )
