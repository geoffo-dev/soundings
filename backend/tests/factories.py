"""Test data builders: users, projects, members, ideas, evaluators and evaluations.

Each builder adds rows through the given session and commits, so the API (which uses
its own sessions) sees them. Example::

    ada = await make_user(db_session, "Ada Lovelace", platform_admin=True)
    project = await make_project(db_session, members={ada: ProjectRole.ADMIN})
    idea = await make_idea(db_session, project, submitted_by=ada)
    await add_evaluator(db_session, idea, bob, state=EvaluatorState.SUBMITTED,
                        scores={"Value": 4}, recommendation=Recommendation.GO)
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.rubric_defaults import default_rubric_criteria
from app.models.base import utcnow
from app.models.enums import (
    EvaluationStatus,
    EvaluatorState,
    IdeaStatus,
    ProjectRole,
    ProjectVisibility,
    Recommendation,
    Resolution,
)
from app.models.evaluation import Evaluation, EvaluationScore
from app.models.idea import Idea, IdeaEvaluator, IdeaTag
from app.models.project import Project, ProjectMember, RubricCriterion, Tag
from app.models.user import User

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


async def make_user(
    db: AsyncSession,
    name: str | None = None,
    *,
    email: str | None = None,
    platform_admin: bool = False,
    active: bool = True,
    service_account: bool = False,
) -> User:
    n = _n()
    name = name or f"User {n}"
    user = User(
        id=uuid4(),
        email=email or f"{name.split()[0].lower()}{n}@example.com",
        display_name=name,
        is_platform_admin=platform_admin,
        is_active=active,
        is_service_account=service_account,
    )
    db.add(user)
    await db.commit()
    return user


async def make_project(
    db: AsyncSession,
    *,
    slug: str | None = None,
    key: str | None = None,
    name: str | None = None,
    visibility: ProjectVisibility = ProjectVisibility.PRIVATE,
    members: Mapping[User, ProjectRole] | None = None,
    archived: bool = False,
    allow_volunteer_owners: bool = True,
) -> Project:
    n = _n()
    project = Project(
        id=uuid4(),
        slug=slug or f"project-{n}",
        key=key or f"P{n}",
        name=name or f"Project {n}",
        description="",
        visibility=visibility,
        allow_volunteer_owners=allow_volunteer_owners,
        archived_at=utcnow() if archived else None,
    )
    db.add(project)
    db.add_all(default_rubric_criteria(project.id))
    for user, role in (members or {}).items():
        db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    await db.commit()
    return project


async def add_member(db: AsyncSession, project: Project, user: User, role: ProjectRole) -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    await db.commit()


async def criteria(db: AsyncSession, project: Project) -> list[RubricCriterion]:
    """Active criteria in order."""
    rows = await db.scalars(
        select(RubricCriterion)
        .where(RubricCriterion.project_id == project.id, RubricCriterion.archived_at.is_(None))
        .order_by(RubricCriterion.position)
    )
    return list(rows)


async def make_idea(
    db: AsyncSession,
    project: Project,
    *,
    title: str | None = None,
    summary: str = "A short summary.",
    status: IdeaStatus = IdeaStatus.NEW,
    resolution: Resolution | None = None,
    owner: User | None = None,
    submitted_by: User | None = None,
    tags: Iterable[str] = (),
    last_activity_at: datetime | None = None,
) -> Idea:
    number = await db.scalar(
        update(Project)
        .where(Project.id == project.id)
        .values(next_idea_number=Project.next_idea_number + 1)
        .returning(Project.next_idea_number - 1)
    )
    assert number is not None
    idea = Idea(
        id=uuid4(),
        project_id=project.id,
        number=number,
        title=title or f"Idea {number}",
        summary=summary,
        status=status,
        resolution=resolution
        if resolution or status is not IdeaStatus.CLOSED
        else Resolution.PARKED,
        owner_id=owner.id if owner else None,
        submitted_by_id=submitted_by.id if submitted_by else None,
        last_activity_at=last_activity_at or utcnow(),
    )
    db.add(idea)
    for name in tags:
        tag = await db.scalar(select(Tag).where(Tag.project_id == project.id, Tag.name == name))
        if tag is None:
            tag = Tag(id=uuid4(), project_id=project.id, name=name)
            db.add(tag)
            await db.flush()
        db.add(IdeaTag(idea_id=idea.id, tag_id=tag.id))
    await db.commit()
    return idea


async def add_evaluator(
    db: AsyncSession,
    idea: Idea,
    user: User,
    *,
    state: EvaluatorState = EvaluatorState.INVITED,
    scores: Mapping[str, int | None] | None = None,
    recommendation: Recommendation | None = Recommendation.GO,
    include_in_aggregate: bool = True,
) -> None:
    """Assign ``user``; ``draft``/``submitted`` also save an evaluation. ``scores`` maps
    criterion names to scores (default: 3 for every active criterion)."""
    db.add(IdeaEvaluator(idea_id=idea.id, user_id=user.id))
    await db.flush()
    if state is not EvaluatorState.INVITED:
        project = await db.get(Project, idea.project_id)
        assert project is not None
        active = await criteria(db, project)
        values = scores if scores is not None else {c.name: 3 for c in active}
        by_name = {c.name: c for c in active}
        submitted = state is EvaluatorState.SUBMITTED
        evaluation = Evaluation(
            id=uuid4(),
            idea_id=idea.id,
            evaluator_id=user.id,
            status=EvaluationStatus.SUBMITTED if submitted else EvaluationStatus.DRAFT,
            recommendation=recommendation,
            submitted_at=utcnow() if submitted else None,
            include_in_aggregate=include_in_aggregate,
        )
        db.add(evaluation)
        await db.flush()
        for name, score in values.items():
            db.add(
                EvaluationScore(
                    evaluation_id=evaluation.id, criterion_id=by_name[name].id, score=score
                )
            )
    await db.commit()
