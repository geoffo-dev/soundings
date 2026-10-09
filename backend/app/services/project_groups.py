"""Project roles granted to groups, and everyone with access to a project
(contract-phase2 section 3.7).

A user's effective role is the highest of their direct role and the role of every
grant to a group they belong to (manual or synced); every check reads it from the
``project_effective_roles`` view. Grant changes lock the project row (the router's
``load_project(for_update=True)``, as Phase 1 membership changes do) and check c11
(an active, human admin remains) after the change.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, case, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Resource, Rule, admin_count, require
from app.domain.principal import Principal
from app.errors import ConflictProblem, NotFoundProblem, ProblemError
from app.models.enums import ProjectRole
from app.models.group import Group, GroupMembership, ProjectGroupGrant
from app.models.project import Project, ProjectMember, project_effective_roles
from app.models.user import User
from app.pagination import InvalidCursorProblem, PageParams, decode_cursor, slice_page
from app.schemas.groups import (
    GroupRef,
    GroupSearchResult,
    ProjectAccessEntry,
    ProjectAccessPage,
    ProjectGroupGrantAdd,
    ProjectGroupGrantUpdate,
    RoleSource,
)
from app.schemas.groups import ProjectGroupGrant as ProjectGroupGrantOut
from app.schemas.users import UserRef
from app.services import audit, research_assignment
from app.services.admin_groups import member_counts
from app.services.users import escape_like

__all__ = ["add_grant", "list_access", "list_grants", "remove_grant", "update_grant"]

_RULE = Rule.PROJECT_MANAGE_MEMBERS
_roles = project_effective_roles


class GroupNotFoundProblem(ProblemError):
    def __init__(self) -> None:
        super().__init__(422, "group_not_found", detail="No group with that id.")


# --- Grants ------------------------------------------------------------------------------------
def _grant_out(grant: ProjectGroupGrant, group: Group, member_count: int) -> ProjectGroupGrantOut:
    return ProjectGroupGrantOut(
        group=GroupSearchResult(
            id=group.id,
            name=group.name,
            description=group.description,
            member_count=member_count,
        ),
        role=grant.role,
        granted_at=grant.created_at,
    )


async def _one_grant_out(
    db: AsyncSession, grant: ProjectGroupGrant, group: Group
) -> ProjectGroupGrantOut:
    counts = await member_counts(db, [group.id])
    return _grant_out(grant, group, counts[group.id].total)


async def list_grants(db: AsyncSession, project: Project) -> list[ProjectGroupGrantOut]:
    """Groups granted a role here: admins first, then by group name."""
    rows = (
        await db.execute(
            select(ProjectGroupGrant, Group)
            .join(Group, Group.id == ProjectGroupGrant.group_id)
            .where(ProjectGroupGrant.project_id == project.id)
            .order_by(
                case((ProjectGroupGrant.role == ProjectRole.ADMIN, 0), else_=1),
                func.lower(Group.name),
                Group.id,
            )
        )
    ).all()
    counts = await member_counts(db, [group.id for _, group in rows])
    return [_grant_out(grant, group, counts[group.id].total) for grant, group in rows]


async def _grant(
    db: AsyncSession, project: Project, group_id: UUID
) -> tuple[ProjectGroupGrant, Group]:
    row = (
        await db.execute(
            select(ProjectGroupGrant, Group)
            .join(Group, Group.id == ProjectGroupGrant.group_id)
            .where(
                ProjectGroupGrant.project_id == project.id, ProjectGroupGrant.group_id == group_id
            )
        )
    ).first()
    if row is None:
        raise NotFoundProblem("That group has no role in this project.")
    return row[0], row[1]


async def _require_an_admin_left(
    db: AsyncSession, principal: Principal, project: Project, resource: Resource
) -> None:
    """c11 after the change (flushed): an active, human admin remains."""
    await db.flush()
    remaining = await admin_count(db, project.id)
    require(principal, _RULE, resource.replace(admins_after_change=remaining))


async def add_grant(
    db: AsyncSession, principal: Principal, project: Project, body: ProjectGroupGrantAdd
) -> ProjectGroupGrantOut:
    """422 ``group_not_found``; 409 ``already_granted``. Adding can't remove an admin."""
    # FOR KEY SHARE: a concurrent delete_group waits, then its cascade removes the grant.
    group = await db.scalar(
        select(Group).where(Group.id == body.group_id).with_for_update(read=True, key_share=True)
    )
    if group is None:
        raise GroupNotFoundProblem
    if await db.get(ProjectGroupGrant, (project.id, group.id)) is not None:
        raise ConflictProblem(
            "That group already has a role in this project.", code="already_granted"
        )
    grant = ProjectGroupGrant(project_id=project.id, group_id=group.id, role=body.role)
    db.add(grant)
    await db.flush()
    await audit.record(
        db,
        "project.group_grant_add",
        actor=principal,
        target_type="group",
        target_id=group.id,
        project_id=project.id,
        details={"rule": _RULE, "role": body.role},
    )
    return await _one_grant_out(db, grant, group)


async def update_grant(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    resource: Resource,
    group_id: UUID,
    body: ProjectGroupGrantUpdate,
) -> ProjectGroupGrantOut:
    """404 when the group has no grant here; 409 ``last_admin`` (c11)."""
    grant, group = await _grant(db, project, group_id)
    previous = grant.role
    if body.role != previous:
        grant.role = body.role
        await _require_an_admin_left(db, principal, project, resource)
        await audit.record(
            db,
            "project.group_grant_update",
            actor=principal,
            target_type="group",
            target_id=group.id,
            project_id=project.id,
            details={"rule": _RULE, "from_role": previous, "role": body.role},
        )
    return await _one_grant_out(db, grant, group)


async def remove_grant(
    db: AsyncSession, principal: Principal, project: Project, resource: Resource, group_id: UUID
) -> None:
    """404 when the group has no grant here; 409 ``last_admin`` (c11). Access through
    the group ends at once."""
    grant, group = await _grant(db, project, group_id)
    previous = grant.role
    held = await research_assignment.roles_before(db, project_ids=[project.id])
    await db.delete(grant)
    await _require_an_admin_left(db, principal, project, resource)
    await audit.record(
        db,
        "project.group_grant_remove",
        actor=principal,
        target_type="group",
        target_id=group.id,
        project_id=project.id,
        details={"rule": _RULE, "from_role": previous},
    )
    # Phase 8b (product owner, review S1 b): the group's members who lose their role here
    # stop researching the project's ideas.
    await research_assignment.end_after_role_loss(db, held, actor=principal)


# --- Everyone with access ------------------------------------------------------------------------
async def _sources(
    db: AsyncSession, project: Project, user_ids: list[UUID]
) -> dict[UUID, list[RoleSource]]:
    """Each user's role sources here: direct first, then groups by name."""
    found: dict[UUID, list[RoleSource]] = defaultdict(list)
    if not user_ids:
        return found
    direct = await db.execute(
        select(ProjectMember.user_id, ProjectMember.role).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id.in_(user_ids)
        )
    )
    for user_id, role in direct.all():
        found[user_id].append(RoleSource(kind="direct", role=ProjectRole(role), group=None))
    granted = await db.execute(
        select(GroupMembership.user_id, ProjectGroupGrant.role, Group.id, Group.name)
        .join(ProjectGroupGrant, ProjectGroupGrant.group_id == GroupMembership.group_id)
        .join(Group, Group.id == GroupMembership.group_id)
        .where(ProjectGroupGrant.project_id == project.id, GroupMembership.user_id.in_(user_ids))
        .order_by(func.lower(Group.name), Group.id)
    )
    for user_id, role, group_id, name in granted.all():
        found[user_id].append(
            RoleSource(kind="group", role=ProjectRole(role), group=GroupRef(id=group_id, name=name))
        )
    return found


async def list_access(
    db: AsyncSession,
    project: Project,
    *,
    q: str | None,
    role: ProjectRole | None,
    page: PageParams,
) -> ProjectAccessPage:
    """Every active user with an effective role here, by ``lower(display_name)`` then
    id (keyset), with the role and its sources. Platform admins without a role (and,
    for internal projects, signed-in users without one) are not listed."""
    sort_key = func.lower(User.display_name)
    statement: Select[Any] = (
        select(User, _roles.c.role, sort_key.label("sort_key"))
        .join(_roles, and_(_roles.c.user_id == User.id, _roles.c.project_id == project.id))
        .where(User.is_active)
    )
    if q:
        pattern = f"%{escape_like(q)}%"
        statement = statement.where(
            or_(
                User.display_name.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
            )
        )
    if role is not None:
        statement = statement.where(_roles.c.role == role)
    if page.cursor:
        after = decode_cursor(page.cursor)
        try:
            position = (str(after["n"]), UUID(str(after["id"])))
        except (KeyError, ValueError) as exc:
            raise InvalidCursorProblem from exc
        statement = statement.where(tuple_(sort_key, User.id) > position)
    rows = (await db.execute(statement.order_by(sort_key, User.id).limit(page.limit + 1))).all()
    items, next_cursor = slice_page(rows, page.limit, lambda row: {"n": row[2], "id": row[0].id})
    sources = await _sources(db, project, [user.id for user, _, _ in items])
    return ProjectAccessPage(
        items=[
            ProjectAccessEntry(
                user=UserRef.model_validate(user),
                email=user.email,
                role=ProjectRole(effective),
                sources=sources.get(user.id, []),
            )
            for user, effective, _ in items
        ],
        next_cursor=next_cursor,
    )
