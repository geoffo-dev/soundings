"""My work (contract section 3.10): evaluations you owe, ideas you own by status,
recently active ideas in your projects, and the sidebar counts.

Phase 7 (contract-phase7 C1): My work lists the first 50 evaluations due (the count is
the total), ``list_evaluations_due`` pages through the rest, and ``get_work_counts``
answers the sidebar's badges with two aggregate queries.

Everything is filtered by ``idea.view`` and leaves out archived projects; score
fields follow blind evaluation (section 3.7) through the shared summary builder.

Phase 8b (contract-phase8b section 7): "Research to do", the ideas whose research you do
(as their live researcher, ``researched_ideas``, guest ideas included; or as their owner
while nobody is assigned and your role lets you answer) that still need it
(``research_to_do``); the first 50 and both counts in one statement, the checklist
progress in one grouped statement; ``list_research_to_do`` pages on. Owned groups hold
their first 10 ideas (``OWNED_GROUP_PREVIEW``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, exists, false, func, not_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.authz import (
    ASSIGNABLE_ROLES,
    researched_ideas,
    viewable_ideas,
    visible_projects,
)
from app.domain.principal import Principal
from app.models.base import utcnow
from app.models.enums import EvaluationStatus, IdeaStatus, ResearchStep
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaEvaluator
from app.models.project import Project, project_effective_roles
from app.models.research import ResearchAnswer, ResearchChecklistItem
from app.pagination import InvalidCursorProblem, decode_cursor, slice_page
from app.schemas.ideas import IdeaPage, IdeaSummary
from app.schemas.projects import DEFAULT_STATUS_LABELS
from app.schemas.research import ResearchProgress, gated_statuses, status_before_research
from app.schemas.users import UserRef
from app.schemas.work import (
    EVALUATIONS_DUE_PAGE,
    OWNED_GROUP_PREVIEW,
    RESEARCH_TO_DO_PAGE,
    Work,
    WorkCounts,
    WorkEvaluation,
    WorkEvaluationPage,
    WorkOwnedGroup,
    WorkRecentIdea,
    WorkResearch,
    WorkResearchPage,
)
from app.services.board import LIFECYCLE, Sort, count_ideas, fetch_page, pages_by_status
from app.services.feed import event_user_ids, latest_activity, latest_events
from app.services.refs import idea_ref
from app.services.summaries import IdeaRow, idea_facts, load_context, summary_fields, user_refs

__all__ = [
    "OWNED_GROUP_SIZE",
    "RECENT_SIZE",
    "get_my_work",
    "get_work_counts",
    "list_evaluations_due",
    "list_my_owned_ideas",
    "list_research_to_do",
    "research_still_to_do",
]

OWNED_GROUP_SIZE: Final = OWNED_GROUP_PREVIEW  # Phase 8b: 10 (was 50)
RECENT_SIZE: Final = 20
_RECENT_FIRST: Final = Sort("-updated")
_roles = project_effective_roles


def _active_projects() -> ColumnElement[bool]:
    return Idea.project_id.in_(select(Project.id).where(Project.archived_at.is_(None)))


def _owned(principal: Principal) -> list[ColumnElement[bool]]:
    return [Idea.owner_id == principal.user_id, _active_projects(), viewable_ideas(principal)]


async def _summaries(
    db: AsyncSession, principal: Principal, rows: Sequence[IdeaRow]
) -> dict[UUID, IdeaSummary]:
    if not rows:
        return {}
    context = await load_context(db, principal, rows)
    return {row.idea.id: IdeaSummary(**summary_fields(principal, row, context)) for row in rows}


def _due_where(principal: Principal) -> list[ColumnElement[bool]]:
    """Assigned, not submitted, evaluation open, member/admin, project not archived."""
    return [
        or_(Evaluation.status.is_(None), Evaluation.status != EvaluationStatus.SUBMITTED),
        Idea.evaluation_closed_at.is_(None),
        Idea.status != IdeaStatus.CLOSED,
        _roles.c.role.in_(list(ASSIGNABLE_ROLES)),
        Project.archived_at.is_(None),
        viewable_ideas(principal),
    ]


def _due_joins[*Ts](statement: Select[*Ts], me: UUID) -> Select[*Ts]:
    return (
        statement.join(Project, Project.id == Idea.project_id)
        .join(IdeaEvaluator, (IdeaEvaluator.idea_id == Idea.id) & (IdeaEvaluator.user_id == me))
        .join(_roles, (_roles.c.project_id == Idea.project_id) & (_roles.c.user_id == me))
        .outerjoin(Evaluation, (Evaluation.idea_id == Idea.id) & (Evaluation.evaluator_id == me))
    )


def _due_after(cursor: str) -> ColumnElement[bool]:
    """Rows after the cursor in (due date, nulls last; id) order (keyset)."""
    data = decode_cursor(cursor)
    try:
        if set(data) != {"due", "id"}:
            raise ValueError("foreign cursor")
        due = None if data["due"] is None else datetime.fromisoformat(str(data["due"]))
        if due is not None and due.tzinfo is None:
            raise ValueError("naive timestamp")
        last_id = UUID(str(data["id"]))
    except (ValueError, TypeError) as exc:
        raise InvalidCursorProblem from exc
    if due is None:  # already among the undated, which come last
        return and_(Idea.evaluation_due_at.is_(None), Idea.id > last_id)
    return or_(
        Idea.evaluation_due_at.is_(None),
        Idea.evaluation_due_at > due,
        and_(Idea.evaluation_due_at == due, Idea.id > last_id),
    )


_DUE_IDEA_COLUMNS: Final = load_only(
    Idea.id,
    Idea.project_id,
    Idea.number,
    Idea.title,
    Idea.status,
    Idea.resolution,
    Idea.owner_id,
    Idea.evaluation_due_at,
    raiseload=True,
)
_DUE_PROJECT_COLUMNS: Final = load_only(
    Project.id, Project.slug, Project.key, Project.name, Project.status_labels, raiseload=True
)
"""What an evaluation due shows (``idea_ref``, owner, due date): not the description."""


@dataclass(frozen=True, slots=True)
class _DuePage:
    rows: list[Any]  # (Idea, Project, evaluation status[, counts]) rows
    next_cursor: str | None
    counts: tuple[int, int]
    now: datetime

    @property
    def owner_ids(self) -> list[UUID | None]:
        return [row[0].owner_id for row in self.rows]

    def items(self, owners: Mapping[UUID, UserRef]) -> list[WorkEvaluation]:
        items = []
        for row in self.rows:
            idea, project, status = row[0], row[1], row[2]
            due_at = idea.evaluation_due_at
            items.append(
                WorkEvaluation(
                    idea=idea_ref(idea, project),
                    owner=owners.get(idea.owner_id) if idea.owner_id else None,
                    due_at=due_at,
                    overdue=due_at is not None and due_at < self.now,
                    state="draft" if status is EvaluationStatus.DRAFT else "invited",
                )
            )
        return items


async def _due_page(
    db: AsyncSession,
    principal: Principal,
    *,
    cursor: str | None,
    limit: int,
    with_counts: bool = False,
) -> _DuePage:
    """One page of the evaluations you owe: overdue first, then soonest due, undated
    last. ``with_counts`` (the first page only) also counts all of them and the overdue
    ones in the same statement (window aggregates over the rows the sort reads anyway);
    otherwise the counts are ``(0, 0)``. The owners' names come separately
    (:meth:`_DuePage.items`): My work loads them with the rest of its people."""
    if with_counts and cursor:
        raise ValueError("counts come with the first page")
    me = principal.user_id
    now = utcnow()
    columns: list[Any] = [Idea, Project, Evaluation.status]
    if with_counts:
        columns += [
            func.count().over().label("due_total"),
            func.count().filter(Idea.evaluation_due_at < now).over().label("overdue_total"),
        ]
    statement = (
        _due_joins(select(*columns), me)
        .where(*_due_where(principal))
        .options(_DUE_IDEA_COLUMNS, _DUE_PROJECT_COLUMNS)
    )
    if cursor:
        statement = statement.where(_due_after(cursor))
    rows = (
        await db.execute(
            statement.order_by(Idea.evaluation_due_at.asc().nulls_last(), Idea.id).limit(limit + 1)
        )
    ).all()
    counts = (
        (int(rows[0].due_total), int(rows[0].overdue_total)) if with_counts and rows else (0, 0)
    )
    page, next_cursor = slice_page(
        rows, limit, lambda row: {"due": row[0].evaluation_due_at, "id": row[0].id}
    )
    return _DuePage(rows=list(page), next_cursor=next_cursor, counts=counts, now=now)


async def _due_counts(db: AsyncSession, principal: Principal) -> tuple[int, int]:
    """(evaluations due, of which overdue): one aggregate over the same rows."""
    now = utcnow()
    statement = _due_joins(
        select(
            func.count(),
            func.count().filter(Idea.evaluation_due_at < now),
        ).select_from(Idea),
        principal.user_id,
    ).where(*_due_where(principal))
    due, overdue = (await db.execute(statement)).one()
    return int(due), int(overdue)


# --- Research to do (Phase 8b) ------------------------------------------------------------
_STEPS_ON: Final = (ResearchStep.BEFORE_EVALUATION, ResearchStep.BEFORE_PROPOSAL)


def _awaits_research() -> list[ColumnElement[bool]]:
    """``awaits_research`` in SQL: the step on, open and not past Research. Conjunctions
    only (no OR over the steps): the OR form took the planner ~3 ms to plan on every
    execution (custom plans), ten times the query itself."""
    # Closed, and past Research whatever the step (Proposal); then each step's own rest.
    common = {IdeaStatus.CLOSED} | set.intersection(
        *(set(gated_statuses(step)) for step in _STEPS_ON)
    )
    clauses: list[ColumnElement[bool]] = [
        Project.research_step != ResearchStep.OFF,
        Idea.status.not_in(sorted(common)),
    ]
    for step in _STEPS_ON:
        extra = sorted(gated_statuses(step) - common)
        if extra:
            clauses.append(not_(and_(Project.research_step == step, Idea.status.in_(extra))))
    return clauses


def _shows_progress() -> ColumnElement[bool]:
    """``shows_research_progress`` in SQL: in Research or the status right before it."""
    return or_(
        Idea.status == IdeaStatus.RESEARCH,
        *(
            and_(Project.research_step == step, Idea.status == status_before_research(step))
            for step in _STEPS_ON
        ),
    )


def _required_open() -> ColumnElement[bool]:
    """A required, active checklist item of the idea's project without its answer."""
    # Correlated explicitly: auto-correlation stops at the nearest enclosing SELECT, so
    # the inner EXISTS would otherwise get its own ``ideas`` (any idea's answer counted).
    answered = (
        exists()
        .where(
            ResearchAnswer.idea_id == Idea.id, ResearchAnswer.item_id == ResearchChecklistItem.id
        )
        .correlate_except(ResearchAnswer)
    )
    return (
        exists()
        .where(
            ResearchChecklistItem.project_id == Idea.project_id,
            ResearchChecklistItem.archived_at.is_(None),
            ResearchChecklistItem.required,
            ~answered,
        )
        .correlate_except(ResearchChecklistItem)
    )


def research_still_to_do() -> list[ColumnElement[bool]]:
    """``WHERE`` clauses over ``ideas`` joined with ``projects``: the step on, the idea open
    and not past Research, a required item open (My work's "Research to do" and the
    research reminder scan, review N4)."""
    return [*_awaits_research(), _required_open()]


def _research_where(principal: Principal) -> list[ColumnElement[bool]]:
    """``research_to_do`` for the person (contract-phase8b section 7): the researcher
    branch is ``researched_ideas`` itself; the owner's needs nobody assigned, the owner
    overlay counting (member or admin there) or a platform admin, and the idea in
    Research or the status before it or a research due date set."""
    can_answer_as_owner = (
        true()
        if principal.is_platform_admin
        else Idea.project_id.in_(
            select(_roles.c.project_id).where(
                _roles.c.user_id == principal.user_id,
                _roles.c.role.in_(list(ASSIGNABLE_ROLES)),
            )
        )
    )
    # The role condition already means project.view (member or admin), so the owner's
    # branch needs no listed_ideas() (its visibility subplan doubled the planning time):
    # only "not held" and an API key's projects.
    in_key = (
        Idea.project_id.in_(principal.project_ids) if principal.project_ids is not None else true()
    )
    as_owner = and_(
        Idea.researcher_id.is_(None),
        Idea.owner_id == principal.user_id,
        Idea.held_for.is_(None),
        in_key,
        can_answer_as_owner,
        or_(Idea.research_due_at.is_not(None), _shows_progress()),
    )
    if principal.user.is_service_account or not principal.has_scope("read"):
        as_owner = false()  # agents never own ideas (c4); a key needs read
    return [
        or_(researched_ideas(principal), as_owner),
        Project.archived_at.is_(None),
        *_awaits_research(),
        _required_open(),
    ]


def _research_after(cursor: str) -> ColumnElement[bool]:
    """Rows after the cursor in (research due date, nulls last; id) order."""
    data = decode_cursor(cursor)
    try:
        if set(data) != {"rdue", "id"}:
            raise ValueError("foreign cursor")
        due = None if data["rdue"] is None else datetime.fromisoformat(str(data["rdue"]))
        if due is not None and due.tzinfo is None:
            raise ValueError("naive timestamp")
        last_id = UUID(str(data["id"]))
    except (ValueError, TypeError) as exc:
        raise InvalidCursorProblem from exc
    if due is None:
        return and_(Idea.research_due_at.is_(None), Idea.id > last_id)
    return or_(
        Idea.research_due_at.is_(None),
        Idea.research_due_at > due,
        and_(Idea.research_due_at == due, Idea.id > last_id),
    )


_RESEARCH_IDEA_COLUMNS: Final = load_only(
    Idea.id,
    Idea.project_id,
    Idea.number,
    Idea.title,
    Idea.status,
    Idea.resolution,
    Idea.owner_id,
    Idea.researcher_id,
    Idea.research_due_at,
    raiseload=True,
)


@dataclass(frozen=True, slots=True)
class _ResearchPage:
    rows: list[Any]  # (Idea, Project, can view project[, counts]) rows
    next_cursor: str | None
    counts: tuple[int, int]
    progress: Mapping[UUID, ResearchProgress]
    now: datetime

    @property
    def owner_ids(self) -> list[UUID | None]:
        return [row[0].owner_id for row in self.rows]

    def items(self, owners: Mapping[UUID, UserRef]) -> list[WorkResearch]:
        empty = ResearchProgress(answered=0, total=0, required_open=0)
        items = []
        for row in self.rows:
            idea, project, can_view_project = row[0], row[1], row[2]
            due_at = idea.research_due_at
            items.append(
                WorkResearch(
                    idea=idea_ref(idea, project),
                    can_view_project=bool(can_view_project),
                    owner=owners.get(idea.owner_id) if idea.owner_id else None,
                    as_owner=idea.researcher_id is None,
                    due_at=due_at,
                    overdue=due_at is not None and due_at < self.now,
                    progress=self.progress.get(idea.id, empty),
                )
            )
        return items


async def _checklist_progress(
    db: AsyncSession, ideas: Sequence[tuple[UUID, UUID]]
) -> dict[UUID, ResearchProgress]:
    """``(idea id, project id)`` -> its checklist at a glance: one grouped statement."""
    if not ideas:
        return {}
    answered = ResearchAnswer.idea_id.is_not(None)
    rows = await db.execute(
        select(
            Idea.id,
            func.count(ResearchChecklistItem.id),
            func.count(ResearchChecklistItem.id).filter(answered),
            func.count(ResearchChecklistItem.id).filter(
                and_(ResearchChecklistItem.required, ~answered)
            ),
        )
        .join(
            ResearchChecklistItem,
            and_(
                ResearchChecklistItem.project_id == Idea.project_id,
                ResearchChecklistItem.archived_at.is_(None),
            ),
        )
        .outerjoin(
            ResearchAnswer,
            and_(
                ResearchAnswer.idea_id == Idea.id,
                ResearchAnswer.item_id == ResearchChecklistItem.id,
            ),
        )
        .where(Idea.id.in_([idea_id for idea_id, _ in ideas]))
        .group_by(Idea.id)
    )
    return {
        idea_id: ResearchProgress(answered=done, total=total, required_open=open_)
        for idea_id, total, done, open_ in rows
    }


async def _research_page(
    db: AsyncSession,
    principal: Principal,
    *,
    cursor: str | None,
    limit: int,
    with_counts: bool = False,
) -> _ResearchPage:
    """One page of "Research to do" (overdue first, then soonest due, undated last, then
    id); ``with_counts`` (the first page) also counts all and the overdue ones in the same
    statement. Then the page's checklist progress (one grouped statement, none if empty)."""
    if with_counts and cursor:
        raise ValueError("counts come with the first page")
    now = utcnow()
    can_view_project = Project.id.in_(
        select(Project.id).where(visible_projects(principal)).correlate(None)
    )
    columns: list[Any] = [Idea, Project, can_view_project.label("can_view_project")]
    if with_counts:
        columns += [
            func.count().over().label("research_total"),
            func.count().filter(Idea.research_due_at < now).over().label("research_overdue"),
        ]
    statement = (
        select(*columns)
        .join(Project, Project.id == Idea.project_id)
        .where(*_research_where(principal))
        .options(_RESEARCH_IDEA_COLUMNS, _DUE_PROJECT_COLUMNS)
    )
    if cursor:
        statement = statement.where(_research_after(cursor))
    rows = (
        await db.execute(
            statement.order_by(Idea.research_due_at.asc().nulls_last(), Idea.id).limit(limit + 1)
        )
    ).all()
    counts = (
        (int(rows[0].research_total), int(rows[0].research_overdue))
        if with_counts and rows
        else (0, 0)
    )
    page, next_cursor = slice_page(
        rows, limit, lambda row: {"rdue": row[0].research_due_at, "id": row[0].id}
    )
    progress = await _checklist_progress(db, [(row[0].id, row[0].project_id) for row in page])
    return _ResearchPage(
        rows=list(page), next_cursor=next_cursor, counts=counts, progress=progress, now=now
    )


async def _research_counts(db: AsyncSession, principal: Principal) -> tuple[int, int]:
    """(research to do, of which overdue): one aggregate."""
    now = utcnow()
    statement = (
        select(func.count(), func.count().filter(Idea.research_due_at < now))
        .select_from(Idea)
        .join(Project, Project.id == Idea.project_id)
        .where(*_research_where(principal))
    )
    total, overdue = (await db.execute(statement)).one()
    return int(total), int(overdue)


async def list_research_to_do(
    db: AsyncSession, principal: Principal, *, cursor: str | None, limit: int
) -> WorkResearchPage:
    """``GET /me/research-to-do``: My work's "Research to do", page by page."""
    research = await _research_page(db, principal, cursor=cursor, limit=limit)
    owners = await user_refs(db, research.owner_ids)
    return WorkResearchPage(items=research.items(owners), next_cursor=research.next_cursor)


async def _owned_counts(db: AsyncSession, principal: Principal) -> dict[IdeaStatus, int]:
    counted = await db.execute(
        select(Idea.status, func.count()).where(*_owned(principal)).group_by(Idea.status)
    )
    return {status: int(n) for status, n in counted.all()}


def _counts(
    due: int,
    overdue: int,
    owned_counts: dict[IdeaStatus, int],
    research: tuple[int, int] = (0, 0),
) -> WorkCounts:
    return WorkCounts(
        evaluations_due=due,
        evaluations_overdue=overdue,
        owned_open=sum(n for status, n in owned_counts.items() if status is not IdeaStatus.CLOSED),
        research_to_do=research[0],
        research_overdue=research[1],
    )


async def get_work_counts(db: AsyncSession, principal: Principal) -> WorkCounts:
    """The sidebar badges alone (``GET /me/work/counts``): three aggregate queries."""
    return _counts(
        *await _due_counts(db, principal),
        await _owned_counts(db, principal),
        await _research_counts(db, principal),
    )


async def list_evaluations_due(
    db: AsyncSession, principal: Principal, *, cursor: str | None, limit: int
) -> WorkEvaluationPage:
    """``GET /me/evaluations-due``: My work's list of evaluations due, page by page."""
    due = await _due_page(db, principal, cursor=cursor, limit=limit)
    owners = await user_refs(db, due.owner_ids)
    return WorkEvaluationPage(items=due.items(owners), next_cursor=due.next_cursor)


async def get_my_work(db: AsyncSession, principal: Principal) -> Work:
    """Phase 8 review (performance): the people (due evaluations' owners, the cards'
    owners, the latest activity's actors) are loaded in one statement with the rest of
    the page's context, and the latest events before it."""
    # The first 50 and how many there are in all (and overdue), in one statement.
    due = await _due_page(db, principal, cursor=None, limit=EVALUATIONS_DUE_PAGE, with_counts=True)
    # Phase 8b: the first 50 research to do and both counts, then their progress.
    research = await _research_page(
        db, principal, cursor=None, limit=RESEARCH_TO_DO_PAGE, with_counts=True
    )

    owned_counts = await _owned_counts(db, principal)
    groups: list[tuple[IdeaStatus, list[IdeaRow], str | None]] = []
    if owned_counts:
        # Every group's first page in one statement, as the board's columns (P7 perf).
        # Canonical order across projects (Research after New, only with ideas in it).
        statuses = [status for status in LIFECYCLE if owned_counts.get(status)]
        pages = await pages_by_status(
            db, principal, _owned(principal), _RECENT_FIRST, OWNED_GROUP_SIZE, statuses=statuses
        )
        groups = [(status, *pages[status]) for status in statuses]

    my_projects = Idea.project_id.in_(
        select(_roles.c.project_id).where(_roles.c.user_id == principal.user_id)
    )
    recent_rows, _ = await fetch_page(
        db,
        principal,
        [my_projects, _active_projects(), viewable_ideas(principal)],
        _RECENT_FIRST,
        cursor=None,
        limit=RECENT_SIZE,
    )

    all_rows = [row for _, rows, _ in groups for row in rows] + recent_rows
    recent = {row.idea.id: row for row in recent_rows}
    events = await latest_events(db, list(recent))
    context = await load_context(
        db,
        principal,
        all_rows,
        extra_users=[*due.owner_ids, *research.owner_ids, *event_user_ids(events)],
    )
    summaries = {
        row.idea.id: IdeaSummary(**summary_fields(principal, row, context)) for row in all_rows
    }
    latest = await latest_activity(
        db,
        principal,
        events,
        lambda idea_id: idea_facts(recent[idea_id], context),
        users=context.users,
        labels_for=lambda idea_id: context.projects[recent[idea_id].idea.project_id].status_labels,
    )
    return Work(
        counts=_counts(*due.counts, owned_counts, research.counts),
        evaluations_due=due.items(context.users),
        evaluations_due_next_cursor=due.next_cursor,
        research_to_do=research.items(context.users),
        research_to_do_next_cursor=research.next_cursor,
        owned=[
            WorkOwnedGroup(
                status=status,
                label=DEFAULT_STATUS_LABELS[status],
                count=owned_counts[status],
                ideas=[summaries[row.idea.id] for row in rows],
                next_cursor=next_cursor,
            )
            for status, rows, next_cursor in groups
        ],
        recent=[
            WorkRecentIdea(idea=summaries[row.idea.id], latest_activity=latest.get(row.idea.id))
            for row in recent_rows
        ],
    )


async def list_my_owned_ideas(
    db: AsyncSession,
    principal: Principal,
    statuses: Sequence[IdeaStatus],
    *,
    cursor: str | None,
    limit: int,
) -> IdeaPage:
    """Ideas you own in non-archived projects, most recently active first. The cursor
    format is ``list_ideas``' ``-updated`` one, so a My work group's cursor works here."""
    where = _owned(principal)
    if statuses:
        where.append(Idea.status.in_(list(statuses)))
    rows, next_cursor = await fetch_page(
        db, principal, where, _RECENT_FIRST, cursor=cursor, limit=limit
    )
    summaries = await _summaries(db, principal, rows)
    return IdeaPage(
        items=[summaries[row.idea.id] for row in rows],
        next_cursor=next_cursor,
        total=await count_ideas(db, where),
    )
