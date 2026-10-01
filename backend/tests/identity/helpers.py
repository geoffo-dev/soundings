"""Builders for identity tests: linked identities, external IDs, groups, mappings,
memberships and group grants. Each commits, like ``tests/factories.py``."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.enums import GroupSyncMode, ProjectRole
from app.models.group import Group, GroupIdpValue, GroupMembership, ProjectGroupGrant
from app.models.project import Project
from app.models.user import User, UserExternalId, UserIdentity
from app.schemas.groups import normalise_idp_value

ISSUER = "https://idp.example.com/realms/acme"


async def link_identity(
    db: AsyncSession, user: User, subject: str, *, issuer: str = ISSUER
) -> UserIdentity:
    identity = UserIdentity(id=uuid4(), user_id=user.id, issuer=issuer, subject=subject)
    db.add(identity)
    await db.commit()
    return identity


async def add_external_id(db: AsyncSession, user: User, kind: str, value: str) -> None:
    db.add(UserExternalId(user_id=user.id, kind=kind, value=value))
    await db.commit()


async def make_group(
    db: AsyncSession,
    name: str,
    *,
    idp_values: Iterable[str] = (),
    sync_mode: GroupSyncMode = GroupSyncMode.MANAGED,
) -> Group:
    group = Group(id=uuid4(), name=name, description="", sync_mode=sync_mode)
    db.add(group)
    await db.flush()
    for value in sorted({normalise_idp_value(value) for value in idp_values}):
        db.add(GroupIdpValue(group_id=group.id, value=value))
    await db.commit()
    return group


async def add_to_group(
    db: AsyncSession, group: Group, user: User, *, manual: bool = True, synced: bool = False
) -> None:
    db.add(GroupMembership(group_id=group.id, user_id=user.id, manual=manual, synced=synced))
    await db.commit()


async def grant(db: AsyncSession, project: Project, group: Group, role: ProjectRole) -> None:
    db.add(ProjectGroupGrant(project_id=project.id, group_id=group.id, role=role))
    await db.commit()


async def memberships(db: AsyncSession, user: User) -> dict[UUID, tuple[bool, bool]]:
    """``{group_id: (manual, synced)}`` as the database has it now."""
    rows = await db.execute(
        select(GroupMembership.group_id, GroupMembership.manual, GroupMembership.synced)
        .where(GroupMembership.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    return {group_id: (manual, synced) for group_id, manual, synced in rows.all()}


async def audit_entries(db: AsyncSession, *actions: str) -> list[AuditLog]:
    statement = select(AuditLog).order_by(AuditLog.created_at, AuditLog.id)
    if actions:
        statement = statement.where(AuditLog.action.in_(actions))
    return list(await db.scalars(statement.execution_options(populate_existing=True)))
