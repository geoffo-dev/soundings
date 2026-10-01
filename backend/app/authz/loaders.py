"""Build :class:`~app.authz.policy.Resource` facts from the database.

Roles come only from the ``project_effective_roles`` view: the highest of the direct
role and every group grant (manual or synced membership), so group roles count
everywhere with no further change. Typical router use::

    project, resource = await load_project(db, principal, slug)  # 404 unless viewable
    require(principal, Rule.PROJECT_EDIT_SETTINGS, resource)    # 403

    resource = await idea_resource(db, principal, idea, project)
    require(principal, Rule.IDEA_CHANGE_STATUS, resource)
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.policy import IdeaFacts, ProjectFacts, Resource, not_found, require, require_view
from app.authz.rules import Rule
from app.domain.principal import Principal
from app.models.enums import EvaluationStatus, EvaluatorState, ProjectRole
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaEvaluator
from app.models.project import Project, project_effective_roles
from app.models.user import User

__all__ = [
    "admin_count",
    "effective_role_of",
    "effective_roles_of",
    "evaluator_state",
    "idea_resource",
    "load_project",
    "other_platform_admins",
    "project_resource",
]

_roles = project_effective_roles


async def effective_role_of(
    db: AsyncSession, user_id: UUID, project_id: UUID
) -> ProjectRole | None:
    role: ProjectRole | None = await db.scalar(
        select(_roles.c.role).where(_roles.c.project_id == project_id, _roles.c.user_id == user_id)
    )
    return role


async def effective_roles_of(
    db: AsyncSession, project_id: UUID, user_ids: Iterable[UUID]
) -> dict[UUID, ProjectRole | None]:
    """Effective roles of several users (c4: owner/evaluator eligibility)."""
    wanted = list(dict.fromkeys(user_ids))
    rows = await db.execute(
        select(_roles.c.user_id, _roles.c.role).where(
            _roles.c.project_id == project_id, _roles.c.user_id.in_(wanted)
        )
    )
    found: dict[UUID, ProjectRole] = dict(rows.all())
    return {user_id: found.get(user_id) for user_id in wanted}


async def admin_count(db: AsyncSession, project_id: UUID) -> int:
    """c11: the project's admins (effective role, direct or through a group) who are
    active and not service accounts. Count it after applying a change."""
    count = await db.scalar(
        select(func.count())
        .select_from(_roles)
        .join(User, User.id == _roles.c.user_id)
        .where(
            _roles.c.project_id == project_id,
            _roles.c.role == ProjectRole.ADMIN,
            User.is_active,
            User.is_service_account.is_(False),
        )
    )
    return int(count or 0)


async def other_platform_admins(db: AsyncSession, user_id: UUID) -> int:
    """c18: active platform admins other than ``user_id`` and the break-glass account.

    Locks every active platform admin's row first (``FOR NO KEY UPDATE``, in id order),
    then counts, so two admins demoting each other at the same moment can't both
    succeed: the second waits and then counts the first change."""
    locked = await db.execute(
        select(User.id, User.is_break_glass)
        .where(User.is_platform_admin, User.is_active)
        .order_by(User.id)
        .with_for_update(key_share=True)
    )
    return sum(1 for found, break_glass in locked.all() if found != user_id and not break_glass)


async def evaluator_state(db: AsyncSession, idea_id: UUID, user_id: UUID) -> EvaluatorState | None:
    """The user's evaluator assignment on the idea: ``None`` if not assigned."""
    row = (
        await db.execute(
            select(IdeaEvaluator.user_id, Evaluation.status)
            .outerjoin(
                Evaluation,
                (Evaluation.idea_id == IdeaEvaluator.idea_id)
                & (Evaluation.evaluator_id == IdeaEvaluator.user_id),
            )
            .where(IdeaEvaluator.idea_id == idea_id, IdeaEvaluator.user_id == user_id)
        )
    ).first()
    if row is None:
        return None
    status: EvaluationStatus | None = row[1]
    if status is None:
        return EvaluatorState.INVITED
    return EvaluatorState(status.value)


async def project_resource(
    db: AsyncSession, principal: Principal | None, project: Project
) -> Resource:
    role = None if principal is None else await effective_role_of(db, principal.user_id, project.id)
    return Resource(project=ProjectFacts.of(project), role=role)


async def idea_resource(
    db: AsyncSession, principal: Principal | None, idea: Idea, project: Project
) -> Resource:
    """Facts for an idea: its project, the principal's role and evaluator state."""
    if idea.project_id != project.id:
        raise ValueError("the idea belongs to another project")
    role = None
    my_evaluation = None
    if principal is not None:
        role = await effective_role_of(db, principal.user_id, project.id)
        my_evaluation = await evaluator_state(db, idea.id, principal.user_id)
    return Resource(
        project=ProjectFacts.of(project), role=role, idea=IdeaFacts.of(idea, my_evaluation)
    )


async def load_project(
    db: AsyncSession,
    principal: Principal | None,
    slug: str,
    rule: Rule | None = Rule.PROJECT_VIEW,
    *,
    for_update: bool = False,
) -> tuple[Project, Resource]:
    """The project by slug with the principal's facts, after ``require(rule)``:
    404 when missing or not viewable, then the rule's 403/409. ``rule=None`` checks
    only that the principal may view it (no API-key scope)."""
    statement = select(Project).where(Project.slug == slug)
    if for_update:
        statement = statement.with_for_update()
    project = await db.scalar(statement)
    if project is None:
        raise not_found()
    resource = await project_resource(db, principal, project)
    if rule is None:
        require_view(principal, resource)
    else:
        require(principal, rule, resource)
    return project, resource
