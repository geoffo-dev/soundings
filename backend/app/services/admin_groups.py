"""Admin settings -> Groups, and the group picker (contract-phase2 sections 3.5-3.7).

Groups have a name (unique case-insensitively), a description, a ``sync_mode`` and
their IdP values (stored normalised: the schema's validator applies
``normalise_idp_value``). Members carry their provenance: ``manual`` (only these
functions set and clear it) and ``synced`` (only sign-in sync sets it,
:mod:`app.auth.group_sync`).

Manual membership writes take the same user-row lock as sync
(:func:`app.auth.group_sync.lock_user`), so an admin's add can't be lost to a sync
deleting the synced-only row at the same moment, and vice versa.

Counts (``member_count`` and the per-provenance counts) consider active users only;
member lists for admins show deactivated members too, flagged.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Select, delete, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.group_sync import lock_user
from app.authz import Rule
from app.domain.principal import Principal
from app.errors import ConflictProblem, NotFoundProblem, ProblemError
from app.models.base import utcnow
from app.models.enums import ProjectRole
from app.models.group import Group, GroupIdpValue, GroupMembership, ProjectGroupGrant
from app.models.project import Project
from app.models.user import User
from app.pagination import InvalidCursorProblem, PageParams, decode_cursor, slice_page
from app.schemas.groups import Group as GroupOut
from app.schemas.groups import (
    GroupCreate,
    GroupMappingUpdate,
    GroupMember,
    GroupMemberAdd,
    GroupMemberPage,
    GroupPage,
    GroupProjectGrant,
    GroupSearchResult,
    GroupSummary,
    GroupUpdate,
)
from app.schemas.projects import ProjectRef
from app.schemas.users import UserRef
from app.services import audit
from app.services.users import escape_like

__all__ = [
    "MemberCounts",
    "add_member",
    "create_group",
    "delete_group",
    "get_group",
    "group_detail",
    "list_groups",
    "list_members",
    "member_counts",
    "remove_member",
    "replace_mapping",
    "search_groups",
    "update_group",
]

_RULE = Rule.PLATFORM_MANAGE_GROUPS


class GroupNameTakenProblem(ConflictProblem):
    def __init__(self) -> None:
        super().__init__("Another group has that name.", code="group_name_taken")


class UserNotFoundProblem(ProblemError):
    def __init__(self) -> None:
        super().__init__(422, "user_not_found", detail="No active person with that id.")


# --- Counts and values -------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MemberCounts:
    """Active members of one group: all, manual, synced (a member can be both)."""

    total: int = 0
    manual: int = 0
    synced: int = 0


async def member_counts(db: AsyncSession, group_ids: Collection[UUID]) -> dict[UUID, MemberCounts]:
    """Active members per group (deactivated users count nowhere), in one query."""
    if not group_ids:
        return {}
    rows = await db.execute(
        select(
            GroupMembership.group_id,
            func.count(),
            func.count().filter(GroupMembership.manual),
            func.count().filter(GroupMembership.synced),
        )
        .join(User, User.id == GroupMembership.user_id)
        .where(GroupMembership.group_id.in_(list(group_ids)), User.is_active)
        .group_by(GroupMembership.group_id)
    )
    counts = {group_id: MemberCounts() for group_id in group_ids}
    for group_id, total, manual, synced in rows.all():
        counts[group_id] = MemberCounts(int(total), int(manual), int(synced))
    return counts


async def _idp_values(db: AsyncSession, group_ids: Collection[UUID]) -> dict[UUID, list[str]]:
    values: dict[UUID, list[str]] = defaultdict(list)
    if group_ids:
        rows = await db.execute(
            select(GroupIdpValue.group_id, GroupIdpValue.value)
            .where(GroupIdpValue.group_id.in_(list(group_ids)))
            .order_by(GroupIdpValue.group_id, GroupIdpValue.value)
        )
        for group_id, value in rows.all():
            values[group_id].append(value)
    return values


async def _project_counts(db: AsyncSession, group_ids: Collection[UUID]) -> dict[UUID, int]:
    if not group_ids:
        return {}
    rows = await db.execute(
        select(ProjectGroupGrant.group_id, func.count())
        .where(ProjectGroupGrant.group_id.in_(list(group_ids)))
        .group_by(ProjectGroupGrant.group_id)
    )
    return {group_id: int(count) for group_id, count in rows.all()}


async def _summaries(
    db: AsyncSession, groups: list[Group], counts: Mapping[UUID, MemberCounts] | None = None
) -> list[GroupSummary]:
    ids = [group.id for group in groups]
    counts = counts if counts is not None else await member_counts(db, ids)
    values = await _idp_values(db, ids)
    projects = await _project_counts(db, ids)
    return [
        GroupSummary(
            id=group.id,
            name=group.name,
            description=group.description,
            member_count=counts[group.id].total,
            sync_mode=group.sync_mode,
            idp_values=values.get(group.id, []),
            project_count=projects.get(group.id, 0),
            created_at=group.created_at,
            updated_at=group.updated_at,
        )
        for group in groups
    ]


# --- Reading -----------------------------------------------------------------------------------
async def get_group(
    db: AsyncSession, group_id: UUID, *, for_update: bool = False, key_share: bool = False
) -> Group:
    """The group, else 404. ``for_update``: lock it for a change of the group itself
    (rename, mapping, delete). ``key_share``: keep it from being deleted while a
    membership or grant that references it is written (``delete_group`` then waits,
    and its cascade removes the new row)."""
    statement = select(Group).where(Group.id == group_id)
    if for_update:
        statement = statement.with_for_update()
    elif key_share:
        statement = statement.with_for_update(read=True, key_share=True)
    group = await db.scalar(statement)
    if group is None:
        raise NotFoundProblem("No group with that id.")
    return group


def _name_contains(q: str | None) -> Any:
    return Group.name.ilike(f"%{escape_like(q)}%", escape="\\") if q else None


async def list_groups(db: AsyncSession, *, q: str | None, page: PageParams) -> GroupPage:
    """Every group by ``lower(name)`` then id (keyset), with mapping and counts."""
    sort_key = func.lower(Group.name)
    statement: Select[Any] = select(Group, sort_key.label("sort_key"))
    contains = _name_contains(q)
    if contains is not None:
        statement = statement.where(contains)
    if page.cursor:
        after = decode_cursor(page.cursor)
        try:
            position = (str(after["n"]), UUID(str(after["id"])))
        except (KeyError, ValueError) as exc:
            raise InvalidCursorProblem from exc
        statement = statement.where(tuple_(sort_key, Group.id) > position)
    rows = (await db.execute(statement.order_by(sort_key, Group.id).limit(page.limit + 1))).all()
    items, next_cursor = slice_page(rows, page.limit, lambda row: {"n": row[1], "id": row[0].id})
    return GroupPage(
        items=await _summaries(db, [group for group, _ in items]), next_cursor=next_cursor
    )


async def search_groups(db: AsyncSession, *, q: str | None, limit: int) -> list[GroupSearchResult]:
    """The group picker: name contains ``q``, by name, at most ``limit``."""
    statement = select(Group).order_by(func.lower(Group.name), Group.id).limit(limit)
    contains = _name_contains(q)
    if contains is not None:
        statement = statement.where(contains)
    groups = list(await db.scalars(statement))
    counts = await member_counts(db, [group.id for group in groups])
    return [
        GroupSearchResult(
            id=group.id,
            name=group.name,
            description=group.description,
            member_count=counts[group.id].total,
        )
        for group in groups
    ]


async def group_detail(db: AsyncSession, group: Group) -> GroupOut:
    """The group with its counts by provenance and project grants (by project name)."""
    all_counts = await member_counts(db, [group.id])
    [summary] = await _summaries(db, [group], all_counts)
    counts = all_counts[group.id]
    grants = await db.execute(
        select(Project, ProjectGroupGrant.role)
        .join(ProjectGroupGrant, ProjectGroupGrant.project_id == Project.id)
        .where(ProjectGroupGrant.group_id == group.id)
        .order_by(func.lower(Project.name), Project.id)
    )
    return GroupOut(
        **summary.model_dump(),
        manual_member_count=counts.manual,
        synced_member_count=counts.synced,
        project_grants=[
            GroupProjectGrant(project=ProjectRef.model_validate(project), role=ProjectRole(role))
            for project, role in grants.all()
        ],
    )


# --- Groups ------------------------------------------------------------------------------------
async def _check_name_free(db: AsyncSession, name: str, *, except_group: UUID | None) -> None:
    statement = select(Group.id).where(func.lower(Group.name) == name.lower())
    if except_group is not None:
        statement = statement.where(Group.id != except_group)
    if await db.scalar(statement.limit(1)) is not None:
        raise GroupNameTakenProblem


async def _flush_name(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as exc:  # a concurrent create or rename took the name
        raise GroupNameTakenProblem from exc


async def create_group(db: AsyncSession, principal: Principal, body: GroupCreate) -> GroupOut:
    await _check_name_free(db, body.name, except_group=None)
    group = Group(name=body.name, description=body.description, sync_mode=body.sync_mode)
    db.add(group)
    await _flush_name(db)
    db.add_all(GroupIdpValue(group_id=group.id, value=value) for value in body.idp_values)
    await db.flush()
    await audit.record(
        db,
        "group.create",
        actor=principal,
        target_type="group",
        target_id=group.id,
        details={"rule": _RULE, "sync_mode": body.sync_mode, "idp_values": body.idp_values},
    )
    return await group_detail(db, group)


async def update_group(
    db: AsyncSession, principal: Principal, group: Group, body: GroupUpdate
) -> GroupOut:
    """Rename or describe (null = unchanged). The mapping has its own endpoint."""
    fields: list[str] = []
    if body.name is not None and body.name != group.name:
        await _check_name_free(db, body.name, except_group=group.id)
        group.name = body.name
        fields.append("name")
    if body.description is not None and body.description != group.description:
        group.description = body.description
        fields.append("description")
    if fields:
        await _flush_name(db)
        await audit.record(
            db,
            "group.update",
            actor=principal,
            target_type="group",
            target_id=group.id,
            details={"rule": _RULE, "fields": fields},
        )
    return await group_detail(db, group)


async def delete_group(db: AsyncSession, principal: Principal, group: Group) -> None:
    """Delete the group; its memberships, mapping and project grants go with it
    (``ON DELETE CASCADE``), so access through it ends at once. Not blocked by c11:
    platform admins can always repair a project."""
    members = await db.scalar(
        select(func.count())
        .select_from(GroupMembership)
        .where(GroupMembership.group_id == group.id)
    )
    project_ids = list(
        await db.scalars(
            select(ProjectGroupGrant.project_id)
            .where(ProjectGroupGrant.group_id == group.id)
            .order_by(ProjectGroupGrant.project_id)
        )
    )
    group_id = group.id
    await db.execute(delete(Group).where(Group.id == group_id))
    db.expunge(group)
    await audit.record(
        db,
        "group.delete",
        actor=principal,
        target_type="group",
        target_id=group_id,
        details={"rule": _RULE, "member_count": int(members or 0), "project_ids": project_ids},
    )


async def replace_mapping(
    db: AsyncSession, principal: Principal, group: Group, body: GroupMappingUpdate
) -> GroupOut:
    """Make the mapping exactly ``body``. Memberships don't change now: the mapping
    applies to each user at their next sign-in."""
    before = (await _idp_values(db, [group.id])).get(group.id, [])
    before_mode = group.sync_mode
    wanted = list(body.idp_values)  # normalised, de-duplicated, sorted by the schema
    if wanted != before:
        await db.execute(
            delete(GroupIdpValue).where(
                GroupIdpValue.group_id == group.id, GroupIdpValue.value.not_in(wanted)
            )
        )
        db.add_all(
            GroupIdpValue(group_id=group.id, value=value) for value in wanted if value not in before
        )
    if body.sync_mode != before_mode:
        group.sync_mode = body.sync_mode
    if wanted != before or body.sync_mode != before_mode:
        group.updated_at = utcnow()
        await db.flush()
        await audit.record(
            db,
            "group.mapping_replace",
            actor=principal,
            target_type="group",
            target_id=group.id,
            details={
                "rule": _RULE,
                "from_sync_mode": before_mode,
                "sync_mode": body.sync_mode,
                "from_idp_values": before,
                "idp_values": wanted,
            },
        )
    return await group_detail(db, group)


# --- Members -----------------------------------------------------------------------------------
def _member_out(membership: GroupMembership, user: User) -> GroupMember:
    return GroupMember(
        user=UserRef.model_validate(user),
        email=user.email,
        is_active=user.is_active,
        manual=membership.manual,
        synced=membership.synced,
        joined_at=membership.created_at,
    )


async def list_members(
    db: AsyncSession, group: Group, *, q: str | None, page: PageParams
) -> GroupMemberPage:
    """Members by ``lower(display_name)`` then id (keyset), deactivated ones included."""
    sort_key = func.lower(User.display_name)
    statement: Select[Any] = (
        select(GroupMembership, User, sort_key.label("sort_key"))
        .join(User, User.id == GroupMembership.user_id)
        .where(GroupMembership.group_id == group.id)
    )
    if q:
        pattern = f"%{escape_like(q)}%"
        statement = statement.where(
            or_(
                User.display_name.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
            )
        )
    if page.cursor:
        after = decode_cursor(page.cursor)
        try:
            position = (str(after["n"]), UUID(str(after["id"])))
        except (KeyError, ValueError) as exc:
            raise InvalidCursorProblem from exc
        statement = statement.where(tuple_(sort_key, User.id) > position)
    rows = (await db.execute(statement.order_by(sort_key, User.id).limit(page.limit + 1))).all()
    items, next_cursor = slice_page(rows, page.limit, lambda row: {"n": row[2], "id": row[1].id})
    return GroupMemberPage(
        items=[_member_out(membership, user) for membership, user, _ in items],
        next_cursor=next_cursor,
    )


async def add_member(
    db: AsyncSession, principal: Principal, group: Group, body: GroupMemberAdd
) -> GroupMember:
    """Add a manual member, or mark a synced member manual too (sync never removes a
    manual membership). 422 ``user_not_found`` for unknown, deactivated, service and
    break-glass accounts; 409 ``already_member`` when already manual."""
    user = await db.get(User, body.user_id)
    if user is None or not user.is_active or user.is_service_account or user.is_break_glass:
        raise UserNotFoundProblem
    await lock_user(db, user.id)  # the same lock as sign-in sync
    membership = await db.scalar(
        select(GroupMembership)
        .where(GroupMembership.group_id == group.id, GroupMembership.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    if membership is not None and membership.manual:
        raise ConflictProblem("Already a manual member of this group.", code="already_member")
    if membership is None:
        membership = GroupMembership(group_id=group.id, user_id=user.id, manual=True, synced=False)
        db.add(membership)
    else:
        membership.manual = True
    await db.flush()
    await audit.record(
        db,
        "group.member_add",
        actor=principal,
        target_type="group",
        target_id=group.id,
        details={"rule": _RULE, "user_id": user.id},
    )
    return _member_out(membership, user)


async def remove_member(
    db: AsyncSession, principal: Principal, group: Group, user_id: UUID
) -> None:
    """Remove the membership whatever its provenance (manual and synced). A synced
    member comes back at their next sign-in while the IdP still sends a mapped value.
    Not blocked by c11. 404 when the user is not a member."""
    await lock_user(db, user_id)  # the same lock as sign-in sync
    membership = await db.scalar(
        select(GroupMembership)
        .where(GroupMembership.group_id == group.id, GroupMembership.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if membership is None:
        raise NotFoundProblem("Not a member of this group.")
    was: Mapping[str, Any] = {"manual": membership.manual, "synced": membership.synced}
    await db.delete(membership)
    await db.flush()
    await audit.record(
        db,
        "group.member_remove",
        actor=principal,
        target_type="group",
        target_id=group.id,
        details={"rule": _RULE, "user_id": user_id, **was},
    )
