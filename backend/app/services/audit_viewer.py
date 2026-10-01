"""The audit log viewer (Admin settings -> Audit log; contract-phase2 section 3.11).

Newest first by ``(created_at, id)`` with a keyset cursor; filters combine with AND,
several ``action`` values with OR. Each page resolves its actors, targets and
projects in a few batched queries (not per row): names of things that still exist,
``null`` otherwise (the ids remain). Entries hold ids, enum values and field names
only (``app.services.audit``), so nothing here adds personal data beyond the names the
contract shows (a user's display name, a project or group name, an idea key).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, get_args
from uuid import UUID

from sqlalchemy import Select, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.group import Group
from app.models.idea import Idea
from app.models.project import Project
from app.models.user import User
from app.pagination import InvalidCursorProblem, PageParams, decode_cursor, slice_page
from app.schemas.audit import AuditAction, AuditEntry, AuditPage, AuditTargetType
from app.schemas.projects import ProjectRef
from app.schemas.users import UserRef

__all__ = ["AuditFilters", "list_entries"]

_TARGET_TYPES: Final = frozenset(get_args(AuditTargetType))


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditFilters:
    actor_id: UUID | None = None
    actions: Collection[AuditAction] | None = None
    target_type: AuditTargetType | None = None
    target_id: UUID | None = None
    project_id: UUID | None = None
    since: datetime | None = None
    """Inclusive."""
    until: datetime | None = None
    """Exclusive."""


def _filtered(filters: AuditFilters) -> Select[Any]:
    statement = select(AuditLog)
    if filters.actor_id is not None:
        statement = statement.where(AuditLog.actor_id == filters.actor_id)
    if filters.actions:
        statement = statement.where(AuditLog.action.in_(sorted({a.value for a in filters.actions})))
    if filters.target_type is not None:
        statement = statement.where(AuditLog.target_type == filters.target_type)
    if filters.target_id is not None:
        statement = statement.where(AuditLog.target_id == filters.target_id)
    if filters.project_id is not None:
        statement = statement.where(AuditLog.project_id == filters.project_id)
    if filters.since is not None:
        statement = statement.where(AuditLog.created_at >= filters.since)
    if filters.until is not None:
        statement = statement.where(AuditLog.created_at < filters.until)
    return statement


async def list_entries(db: AsyncSession, filters: AuditFilters, page: PageParams) -> AuditPage:
    statement = _filtered(filters)
    if page.cursor:
        after = decode_cursor(page.cursor)
        try:
            position = (datetime.fromisoformat(str(after["t"])), UUID(str(after["id"])))
        except (KeyError, ValueError) as exc:
            raise InvalidCursorProblem from exc
        if position[0].tzinfo is None:
            raise InvalidCursorProblem
        statement = statement.where(tuple_(AuditLog.created_at, AuditLog.id) < position)
    rows = list(
        await db.scalars(
            statement.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(page.limit + 1)
        )
    )
    items, next_cursor = slice_page(
        rows, page.limit, lambda entry: {"t": entry.created_at, "id": entry.id}
    )
    resolved = await _resolve(db, items)
    return AuditPage(items=[resolved.entry(item) for item in items], next_cursor=next_cursor)


# --- Resolving ids -------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Resolved:
    users: dict[UUID, User]
    projects: dict[UUID, Project]
    groups: dict[UUID, str]
    ideas: dict[UUID, str]

    def target_label(self, target_type: str | None, target_id: UUID | None) -> str | None:
        if target_id is None:
            return None
        match target_type:
            case "user":
                user = self.users.get(target_id)
                return user.display_name if user is not None else None
            case "project":
                project = self.projects.get(target_id)
                return project.name if project is not None else None
            case "group":
                return self.groups.get(target_id)
            case "idea":
                return self.ideas.get(target_id)
        return None

    def entry(self, item: AuditLog) -> AuditEntry:
        actor = self.users.get(item.actor_id) if item.actor_id is not None else None
        project = self.projects.get(item.project_id) if item.project_id is not None else None
        target_type = item.target_type if item.target_type in _TARGET_TYPES else None
        return AuditEntry(
            id=item.id,
            created_at=item.created_at,
            action=item.action,
            actor_id=item.actor_id,
            actor=UserRef.model_validate(actor) if actor is not None else None,
            target_type=target_type,  # type: ignore[arg-type]  # checked against the Literal
            target_id=item.target_id,
            target_label=self.target_label(target_type, item.target_id),
            project=ProjectRef.model_validate(project) if project is not None else None,
            details=dict(item.details or {}),
        )


async def _resolve(db: AsyncSession, items: list[AuditLog]) -> _Resolved:
    targets: dict[str, set[UUID]] = defaultdict(set)
    for item in items:
        if item.target_id is not None and item.target_type is not None:
            targets[item.target_type].add(item.target_id)
    user_ids = {item.actor_id for item in items if item.actor_id is not None} | targets["user"]
    project_ids = {item.project_id for item in items if item.project_id is not None}
    project_ids |= targets["project"]

    users: dict[UUID, User] = {}
    if user_ids:
        users = {
            user.id: user for user in await db.scalars(select(User).where(User.id.in_(user_ids)))
        }
    ideas: dict[UUID, str] = {}
    if targets["idea"]:
        idea_rows = await db.execute(
            select(Idea.id, Project.key, Idea.number)
            .join(Project, Project.id == Idea.project_id)
            .where(Idea.id.in_(targets["idea"]))
        )
        ideas = {idea_id: f"{key}-{number}" for idea_id, key, number in idea_rows.all()}
    projects: dict[UUID, Project] = {}
    if project_ids:
        projects = {
            project.id: project
            for project in await db.scalars(select(Project).where(Project.id.in_(project_ids)))
        }
    groups: dict[UUID, str] = {}
    if targets["group"]:
        group_rows = await db.execute(
            select(Group.id, Group.name).where(Group.id.in_(targets["group"]))
        )
        groups = dict(group_rows.all())
    return _Resolved(users=users, projects=projects, groups=groups, ideas=ideas)
