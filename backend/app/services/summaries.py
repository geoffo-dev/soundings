"""``IdeaSummary`` rows for the list, the board, My work and the idea page.

Page queries select each idea with its :func:`summary_columns`: whether the viewer may
see its score (the policy's ``score.view_aggregate`` in SQL, false for a pending
evaluator), its tag ids, evaluator progress, the viewer's own evaluator state,
comment count and vote. They are correlated subqueries, so Postgres evaluates them
only for the page's rows, through the per-idea indexes, in the same round trip.
:func:`build_summaries` then loads the owners' and tags' names for the whole page
(and the projects and roles when a page spans projects).

Blind evaluation (contract section 3.7): where the score is not visible,
``score`` is null, ``score_hidden`` true and ``high_disagreement`` false.

Phase 8b (review M1): the evaluation area (``evaluator_progress``, the viewer's own
evaluator state) follows ``evaluation.view_own`` (:func:`app.authz.evaluation_visible`),
so a guest researcher's idea shows ``0/0`` and no state; ``researcher`` is the idea's
researcher while the project's research step is on.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Row, String, exists, func, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.authz import (
    IdeaFacts,
    ProjectFacts,
    Resource,
    evaluation_visible,
    idea_summary_permissions,
    score_visible,
    visible_last_activity,
)
from app.domain.idea_keys import format_key
from app.domain.labels import status_label
from app.domain.principal import Principal
from app.models.activity import Comment
from app.models.enums import (
    EvaluationStatus,
    EvaluatorState,
    IdeaStatus,
    ProjectRole,
    ResearchStep,
    Resolution,
)
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaEvaluator, IdeaTag, IdeaVote
from app.models.project import Project, Tag, project_effective_roles
from app.models.user import User
from app.schemas.ideas import (
    AggregateScoreSummary,
    EvaluatorProgress,
    IdeaSummary,
    IdeaSummaryPermissions,
)
from app.schemas.projects import ProjectRef
from app.schemas.research import ResearchProgress
from app.schemas.users import UserRef
from app.services import research
from app.services.refs import project_ref
from app.services.sql import any_of

__all__ = [
    "IDEA_COLUMNS",
    "IdeaData",
    "IdeaRow",
    "SummaryContext",
    "build_summaries",
    "idea_facts",
    "idea_row",
    "load_context",
    "roles_in",
    "summary_columns",
    "summary_fields",
    "user_refs",
]

_roles = project_effective_roles


@dataclass(frozen=True, slots=True)
class IdeaData:
    """The idea columns a summary shows. Pages select these (:data:`IDEA_COLUMNS`)
    rather than ORM entities: hundreds of cards per request stay cheap to load."""

    id: UUID
    project_id: UUID
    number: int
    title: str
    summary: str
    status: IdeaStatus
    resolution: Resolution | None
    owner_id: UUID | None
    submitted_by_id: UUID | None
    evaluation_closed_at: datetime | None
    aggregate_score: Decimal | None
    aggregate_count: int
    high_disagreement: bool
    vote_count: int
    created_at: datetime
    last_activity_at: datetime
    researcher_id: UUID | None = None  # Phase 8b

    @classmethod
    def of(cls, source: Any) -> IdeaData:
        """From an ``Idea`` or a row selected with :data:`IDEA_COLUMNS`."""
        return cls(**{name: getattr(source, name) for name in _IDEA_FIELDS})

    @classmethod
    def of_row(cls, row: Row[Any]) -> IdeaData:
        """From a row that starts with :data:`IDEA_COLUMNS`, in their order (the page
        queries): positional, which is several times cheaper than a lookup by name per
        field on hundreds of cards (Phase 8 review: My work)."""
        return cls(*row[:_IDEA_FIELD_COUNT])


_IDEA_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(IdeaData))
_IDEA_FIELD_COUNT = len(_IDEA_FIELDS)
IDEA_COLUMNS: tuple[InstrumentedAttribute[Any], ...] = tuple(
    getattr(Idea, name) for name in _IDEA_FIELDS
)
"""``SELECT`` these for :meth:`IdeaData.of` (named after the attributes)."""


@dataclass(frozen=True, slots=True)
class IdeaRow:
    """An idea and its summary columns, as the viewer may see it."""

    idea: IdeaData
    score_visible: bool
    evaluation_visible: bool = True
    """Phase 8b: ``evaluation.view_own`` (progress and your own state; never a guest's)."""
    tag_ids: Sequence[UUID] = ()
    evaluators: int = 0
    submitted: int = 0
    my_state: EvaluatorState | None = None
    comment_count: int = 0
    has_voted: bool = False
    activity_at: datetime | None = None
    """Phase 8b guest review L1: ``last_activity_at`` as the viewer may see it
    (:func:`app.authz.visible_last_activity`); ``None``: the column itself."""

    @classmethod
    def of(
        cls,
        idea: IdeaData,
        row: Row[Any],
        *,
        score_visible: bool | None = None,
        evaluation_visible: bool | None = None,
    ) -> IdeaRow:
        """From a row selected with :func:`summary_columns`."""
        evaluation = bool(
            row.evaluation_visible if evaluation_visible is None else evaluation_visible
        )
        return cls(
            idea=idea,
            score_visible=bool(row.score_visible if score_visible is None else score_visible),
            evaluation_visible=evaluation,
            tag_ids=row.tag_ids or (),
            evaluators=row.evaluators,
            submitted=row.submitted,
            my_state=EvaluatorState(row.my_state) if row.my_state and evaluation else None,
            comment_count=row.comment_count,
            has_voted=bool(row.has_voted),
            activity_at=row.activity_at,
        )


def summary_columns(
    principal: Principal, idea_id: ColumnElement[UUID] | Any = Idea.id
) -> list[ColumnElement[Any]]:
    """Labelled columns that :meth:`IdeaRow.of` reads, correlated to ``idea_id`` (the
    ``ideas.id`` of the enclosing query, or a subquery's id column)."""
    me = principal.user_id
    # Ids only (an index-only scan); names are resolved once per page, and sorted.
    tag_ids = select(func.array_agg(IdeaTag.tag_id)).where(IdeaTag.idea_id == idea_id)
    evaluators = (
        select(func.count())
        .select_from(IdeaEvaluator)
        .where(IdeaEvaluator.idea_id == idea_id)
        .scalar_subquery()
    )
    submitted = (
        select(func.count())
        .select_from(Evaluation)
        .where(Evaluation.idea_id == idea_id, Evaluation.status == EvaluationStatus.SUBMITTED)
        .scalar_subquery()
    )
    my_state = (
        select(func.coalesce(type_coerce(Evaluation.status, String), EvaluatorState.INVITED.value))
        .select_from(IdeaEvaluator)
        .outerjoin(
            Evaluation,
            (Evaluation.idea_id == IdeaEvaluator.idea_id)
            & (Evaluation.evaluator_id == IdeaEvaluator.user_id),
        )
        .where(IdeaEvaluator.idea_id == idea_id, IdeaEvaluator.user_id == me)
        .scalar_subquery()
    )
    comments = (
        select(func.count())
        .select_from(Comment)
        .where(Comment.idea_id == idea_id, Comment.deleted_at.is_(None))
        .scalar_subquery()
    )
    voted = exists().where(IdeaVote.idea_id == idea_id, IdeaVote.user_id == me)
    return [
        score_visible(principal, idea_id).label("score_visible"),
        evaluation_visible(principal).label("evaluation_visible"),
        tag_ids.scalar_subquery().label("tag_ids"),
        evaluators.label("evaluators"),
        submitted.label("submitted"),
        my_state.label("my_state"),
        comments.label("comment_count"),
        voted.label("has_voted"),
        visible_last_activity(principal).label("activity_at"),
    ]


async def idea_row(
    db: AsyncSession,
    principal: Principal,
    idea: Idea,
    *,
    score_visible: bool,
    evaluation_visible: bool = True,
) -> IdeaRow:
    """One idea's summary columns (the idea page); visibility comes from the policy."""
    row = (
        await db.execute(select(*summary_columns(principal)[2:]).where(Idea.id == idea.id))
    ).one()
    return IdeaRow.of(
        IdeaData.of(idea),
        row,
        score_visible=score_visible,
        evaluation_visible=evaluation_visible,
    )


async def user_refs(db: AsyncSession, user_ids: Iterable[UUID | None]) -> dict[UUID, UserRef]:
    wanted = {user_id for user_id in user_ids if user_id is not None}
    if not wanted:
        return {}
    users = await db.scalars(select(User).where(any_of(User.id, wanted)))
    return {user.id: UserRef.model_validate(user) for user in users}


async def roles_in(
    db: AsyncSession, principal: Principal, project_ids: Iterable[UUID]
) -> dict[UUID, ProjectRole]:
    """The principal's effective role per project (projects without one are absent)."""
    rows = await db.execute(
        select(_roles.c.project_id, _roles.c.role).where(
            _roles.c.user_id == principal.user_id, any_of(_roles.c.project_id, project_ids)
        )
    )
    return {project_id: ProjectRole(role) for project_id, role in rows}


@dataclass(slots=True)
class SummaryContext:
    """What summaries need besides their rows: projects, your roles, the owners."""

    principal: Principal
    projects: Mapping[UUID, Project]
    roles: Mapping[UUID, ProjectRole]
    users: Mapping[UUID, UserRef]
    tags: Mapping[UUID, str]
    research: Mapping[UUID, ResearchProgress] = field(default_factory=dict)
    """Phase 8: ``IdeaSummary.research`` of the ideas that show it."""
    project_refs: dict[UUID, ProjectRef] = field(default_factory=dict)
    project_facts: dict[UUID, ProjectFacts] = field(default_factory=dict)
    _permissions: dict[tuple[Any, ...], IdeaSummaryPermissions] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for project in self.projects.values():
            self.project_refs[project.id] = project_ref(project)
            self.project_facts[project.id] = ProjectFacts.of(project)

    def permissions(self, row: IdeaRow) -> IdeaSummaryPermissions:
        """``idea_summary_permissions``, decided once per distinct set of facts.

        The policy compares an idea's owner and submitter only with the principal, so
        ideas that agree on the key below get the same decision.
        """
        idea, me = row.idea, self.principal.user_id
        key = (
            idea.project_id,
            idea.status,
            idea.owner_id is None,
            idea.owner_id == me,
            idea.submitted_by_id == me,
            idea.evaluation_closed_at is not None,
            row.my_state,
        )
        found = self._permissions.get(key)
        if found is None:
            found = idea_summary_permissions(self.principal, idea_facts(row, self))
            self._permissions[key] = found
        return found


async def load_context(
    db: AsyncSession,
    principal: Principal,
    rows: Sequence[IdeaRow],
    *,
    projects: Mapping[UUID, Project] | None = None,
    roles: Mapping[UUID, ProjectRole] | None = None,
    extra_users: Iterable[UUID | None] = (),
) -> SummaryContext:
    """Projects, your roles, and the names of the page's owners and tags."""
    project_ids = {row.idea.project_id for row in rows}
    if projects is None or not project_ids <= set(projects):
        if roles is None:
            # The projects and your role in each in one statement (Phase 8 review: My work).
            found_roles = await db.execute(
                select(Project, _roles.c.role)
                .outerjoin(
                    _roles,
                    (_roles.c.project_id == Project.id) & (_roles.c.user_id == principal.user_id),
                )
                .where(any_of(Project.id, project_ids))
            )
            pairs = found_roles.all()
            projects = {project.id: project for project, _ in pairs}
            roles = {project.id: ProjectRole(role) for project, role in pairs if role is not None}
        else:
            found = await db.scalars(select(Project).where(any_of(Project.id, project_ids)))
            projects = {project.id: project for project in found}
    if roles is None:
        roles = await roles_in(db, principal, project_ids)
    users = await user_refs(
        db,
        [
            *(row.idea.owner_id for row in rows),
            *(row.idea.researcher_id for row in rows),  # Phase 8b
            *extra_users,
        ],
    )
    tag_ids = {tag_id for row in rows for tag_id in row.tag_ids}
    tags: dict[UUID, str] = {}
    if tag_ids:
        found_tags = await db.execute(select(Tag.id, Tag.name).where(any_of(Tag.id, tag_ids)))
        tags = dict(found_tags.all())
    # Phase 8: the checklist's progress, one grouped statement for the page (none when no
    # idea on it is in Research or the status before it in a project with the step on).
    progress = await research.progress_by_idea(
        db,
        ((row.idea.id, row.idea.project_id, row.idea.status) for row in rows),
        {project.id: project.research_step for project in projects.values()},
    )
    return SummaryContext(
        principal=principal,
        projects=projects,
        roles=roles,
        users=users,
        tags=tags,
        research=progress,
    )


def idea_facts(row: IdeaRow, context: SummaryContext) -> Resource:
    idea = row.idea
    return Resource(
        project=context.project_facts[idea.project_id],
        role=context.roles.get(idea.project_id),
        idea=IdeaFacts(
            id=idea.id,
            status=idea.status,
            owner_id=idea.owner_id,
            submitted_by_id=idea.submitted_by_id,
            evaluation_closed=idea.evaluation_closed_at is not None,
            my_evaluation=row.my_state,
            researcher_id=idea.researcher_id,
        ),
    )


def summary_fields(principal: Principal, row: IdeaRow, context: SummaryContext) -> dict[str, Any]:
    """The ``IdeaSummary`` fields of one idea, for ``IdeaSummary`` or ``IdeaDetail``."""
    idea = row.idea
    project = context.projects[idea.project_id]
    visible = row.score_visible
    score = None
    if visible and idea.aggregate_score is not None and idea.aggregate_count > 0:
        score = AggregateScoreSummary(
            overall=float(idea.aggregate_score), count=idea.aggregate_count
        )
    return {
        "id": idea.id,
        "key": format_key(project.key, idea.number),
        "number": idea.number,
        "project": context.project_refs[project.id],
        "title": idea.title,
        "status": idea.status,
        "resolution": idea.resolution,
        "status_label": status_label(project.status_labels, idea.status, idea.resolution),
        "summary": idea.summary,
        "owner": context.users.get(idea.owner_id) if idea.owner_id else None,
        "tags": sorted(
            (context.tags[tag_id] for tag_id in row.tag_ids if tag_id in context.tags),
            key=lambda name: (name.casefold(), name),
        ),
        "evaluator_progress": (
            EvaluatorProgress(submitted=row.submitted, total=row.evaluators)
            if row.evaluation_visible
            else EvaluatorProgress(submitted=0, total=0)
        ),
        "score": score,
        "score_hidden": not visible,
        "high_disagreement": visible and idea.high_disagreement,
        "vote_count": idea.vote_count,
        "has_voted": row.has_voted,
        "comment_count": row.comment_count,
        "created_at": idea.created_at,
        "last_activity_at": row.activity_at or idea.last_activity_at,
        "permissions": context.permissions(row),
        "research": context.research.get(idea.id),
        # Phase 8b: who does the research, while the project has the step.
        "researcher": (
            context.users.get(idea.researcher_id)
            if idea.researcher_id and project.research_step is not ResearchStep.OFF
            else None
        ),
    }


async def build_summaries(
    db: AsyncSession,
    principal: Principal,
    rows: Sequence[IdeaRow],
    *,
    projects: Mapping[UUID, Project] | None = None,
    roles: Mapping[UUID, ProjectRole] | None = None,
) -> list[IdeaSummary]:
    if not rows:
        return []
    context = await load_context(db, principal, rows, projects=projects, roles=roles)
    return [IdeaSummary(**summary_fields(principal, row, context)) for row in rows]
