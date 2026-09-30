"""My work (contract section 3.10): evaluations you owe, ideas you own by status,
recently active ideas in your projects, and the sidebar counts.

Everything is filtered by ``idea.view`` and leaves out archived projects; score
fields follow blind evaluation (section 3.7) through the shared summary builder.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import ASSIGNABLE_ROLES, viewable_ideas
from app.domain.principal import Principal
from app.models.base import utcnow
from app.models.enums import EvaluationStatus, IdeaStatus
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaEvaluator
from app.models.project import Project, project_effective_roles
from app.schemas.ideas import IdeaPage, IdeaSummary
from app.schemas.projects import DEFAULT_STATUS_LABELS
from app.schemas.work import Work, WorkCounts, WorkEvaluation, WorkOwnedGroup, WorkRecentIdea
from app.services.board import LIFECYCLE, Sort, count_ideas, fetch_page
from app.services.feed import latest_activity
from app.services.refs import idea_ref
from app.services.summaries import IdeaRow, idea_facts, load_context, summary_fields, user_refs

__all__ = ["OWNED_GROUP_SIZE", "RECENT_SIZE", "get_my_work", "list_my_owned_ideas"]

OWNED_GROUP_SIZE: Final = 50
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


async def _evaluations_due(db: AsyncSession, principal: Principal) -> list[WorkEvaluation]:
    """Assigned, not submitted, evaluation open, member/admin, project not archived."""
    me = principal.user_id
    rows = (
        await db.execute(
            select(Idea, Project, Evaluation.status)
            .join(Project, Project.id == Idea.project_id)
            .join(IdeaEvaluator, (IdeaEvaluator.idea_id == Idea.id) & (IdeaEvaluator.user_id == me))
            .join(_roles, (_roles.c.project_id == Idea.project_id) & (_roles.c.user_id == me))
            .outerjoin(
                Evaluation, (Evaluation.idea_id == Idea.id) & (Evaluation.evaluator_id == me)
            )
            .where(
                or_(Evaluation.status.is_(None), Evaluation.status != EvaluationStatus.SUBMITTED),
                Idea.evaluation_closed_at.is_(None),
                Idea.status != IdeaStatus.CLOSED,
                _roles.c.role.in_(list(ASSIGNABLE_ROLES)),
                Project.archived_at.is_(None),
                viewable_ideas(principal),
            )
            .order_by(Idea.evaluation_due_at.asc().nulls_last(), Idea.id)
        )
    ).all()
    owners = await user_refs(db, [idea.owner_id for idea, _, _ in rows])
    now = utcnow()
    return [
        WorkEvaluation(
            idea=idea_ref(idea, project),
            owner=owners.get(idea.owner_id) if idea.owner_id else None,
            due_at=idea.evaluation_due_at,
            overdue=idea.evaluation_due_at is not None and idea.evaluation_due_at < now,
            state="draft" if status is EvaluationStatus.DRAFT else "invited",
        )
        for idea, project, status in rows
    ]


async def get_my_work(db: AsyncSession, principal: Principal) -> Work:
    due = await _evaluations_due(db, principal)

    owned_where = _owned(principal)
    counted = await db.execute(
        select(Idea.status, func.count()).where(*owned_where).group_by(Idea.status)
    )
    owned_counts: dict[IdeaStatus, int] = dict(counted.all())
    groups: list[tuple[IdeaStatus, list[IdeaRow], str | None]] = []
    for status in LIFECYCLE:
        if owned_counts.get(status):
            rows, next_cursor = await fetch_page(
                db,
                principal,
                [*owned_where, Idea.status == status],
                _RECENT_FIRST,
                cursor=None,
                limit=OWNED_GROUP_SIZE,
            )
            groups.append((status, rows, next_cursor))

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
    context = await load_context(db, principal, all_rows)
    summaries = {
        row.idea.id: IdeaSummary(**summary_fields(principal, row, context)) for row in all_rows
    }
    recent = {row.idea.id: row for row in recent_rows}
    latest = await latest_activity(
        db, principal, list(recent), lambda idea_id: idea_facts(recent[idea_id], context)
    )
    now = utcnow()
    return Work(
        counts=WorkCounts(
            evaluations_due=len(due),
            evaluations_overdue=sum(1 for e in due if e.due_at is not None and e.due_at < now),
            owned_open=sum(
                n for status, n in owned_counts.items() if status is not IdeaStatus.CLOSED
            ),
        ),
        evaluations_due=due,
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
