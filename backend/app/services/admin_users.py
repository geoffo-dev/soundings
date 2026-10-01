"""Admin settings -> Users (contract-phase2 section 3.4).

Routers check ``platform.manage_users`` first (403 before anything about the user is
looked up); these functions load the user (404), apply the business rules (c17
``cannot_change_self``, 409 ``email_taken`` / ``external_id_taken`` /
``system_account``, c18 ``last_platform_admin``), write the audit entry in the same
transaction and build the response.

Audit entries carry ids, field names, flags and external-ID *kinds*: never emails,
names or external-ID values.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, exists, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.group_mapping import project_roles_for
from app.authz import Resource, Rule, other_platform_admins, require
from app.config import Settings
from app.domain.principal import Principal
from app.errors import ConflictProblem, NotFoundProblem
from app.models.base import utcnow
from app.models.enums import AuthMethod
from app.models.group import Group, GroupMembership
from app.models.user import User, UserExternalId, UserIdentity, UserSession
from app.pagination import InvalidCursorProblem, PageParams, decode_cursor, slice_page
from app.schemas.admin_users import (
    AdminUser,
    AdminUserCreate,
    AdminUserPage,
    AdminUserSummary,
    AdminUserUpdate,
    ExternalId,
    ExternalIdIn,
    ExternalIdsReplace,
    LinkedIdentity,
    UserGroup,
)
from app.schemas.groups import GroupRef
from app.services import audit, sessions
from app.services.users import escape_like

__all__ = [
    "create_user",
    "end_sessions",
    "get_user",
    "list_users",
    "replace_external_ids",
    "unlink_identity",
    "update_user",
    "user_detail",
]

_RULE = Rule.PLATFORM_MANAGE_USERS


class EmailTakenProblem(ConflictProblem):
    def __init__(self) -> None:
        super().__init__("Another user has that email address.", code="email_taken")


class ExternalIdTakenProblem(ConflictProblem):
    def __init__(self) -> None:
        super().__init__("Another user has that external ID.", code="external_id_taken")


class SystemAccountProblem(ConflictProblem):
    def __init__(self, detail: str) -> None:
        super().__init__(detail, code="system_account")


def _is_system(user: User) -> bool:
    """Service accounts and the break-glass admin: only their name and active flag
    change; no email, platform-admin or external-ID changes."""
    return user.is_service_account or user.is_break_glass


def _has_identity() -> Any:
    return exists().where(UserIdentity.user_id == User.id)


# --- Reading -----------------------------------------------------------------------------------
async def get_user(db: AsyncSession, user_id: UUID) -> User:
    """Any account by id (people, service accounts, break-glass), else 404."""
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundProblem("No user with that id.")
    return user


def _summary(user: User, has_identity: bool) -> AdminUserSummary:
    return AdminUserSummary(
        id=user.id,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        email=user.email,
        is_platform_admin=user.is_platform_admin,
        is_active=user.is_active,
        is_service_account=user.is_service_account,
        is_break_glass=user.is_break_glass,
        has_identity=has_identity,
        last_seen_at=user.last_seen_at,
        created_at=user.created_at,
    )


async def list_users(
    db: AsyncSession,
    *,
    q: str | None,
    active: bool | None,
    platform_admin: bool | None,
    has_identity: bool | None,
    page: PageParams,
) -> AdminUserPage:
    """Every account by ``lower(display_name)`` then id (keyset); the filters combine."""
    sort_key = func.lower(User.display_name)
    linked = _has_identity()
    statement: Select[Any] = select(User, sort_key.label("sort_key"), linked.label("linked"))
    if q:
        pattern = f"%{escape_like(q)}%"
        statement = statement.where(
            or_(
                User.display_name.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
            )
        )
    if active is not None:
        statement = statement.where(User.is_active.is_(active))
    if platform_admin is not None:
        statement = statement.where(User.is_platform_admin.is_(platform_admin))
    if has_identity is not None:
        statement = statement.where(linked if has_identity else ~linked)
    if page.cursor:
        after = decode_cursor(page.cursor)
        try:
            position = (str(after["n"]), UUID(str(after["id"])))
        except (KeyError, ValueError) as exc:
            raise InvalidCursorProblem from exc
        statement = statement.where(tuple_(sort_key, User.id) > position)
    rows = (await db.execute(statement.order_by(sort_key, User.id).limit(page.limit + 1))).all()
    items, next_cursor = slice_page(rows, page.limit, lambda row: {"n": row[1], "id": row[0].id})
    return AdminUserPage(
        items=[_summary(user, bool(linked_flag)) for user, _, linked_flag in items],
        next_cursor=next_cursor,
    )


async def _active_session_count(db: AsyncSession, user_id: UUID, settings: Settings) -> int:
    """Sessions that would still be accepted now (not expired, idle or of a sign-in
    method that is no longer available)."""
    now = utcnow()
    rows = await db.execute(
        select(
            UserSession.auth_method,
            UserSession.created_at,
            UserSession.last_seen_at,
            UserSession.expires_at,
        ).where(UserSession.user_id == user_id, UserSession.expires_at > now)
    )
    live = 0
    for method, created_at, last_seen_at, expires_at in rows.all():
        if not sessions.method_available(settings, method):
            continue
        max_age, idle_timeout = sessions.session_limits(settings, method)
        if now < expires_at and now < created_at + max_age and now < last_seen_at + idle_timeout:
            live += 1
    return live


async def user_detail(db: AsyncSession, user: User, settings: Settings) -> AdminUser:
    """Everything an admin needs to see where the user's access comes from."""
    identities = await db.scalars(
        select(UserIdentity)
        .where(UserIdentity.user_id == user.id)
        .order_by(UserIdentity.created_at, UserIdentity.id)
    )
    external_ids = await db.scalars(
        select(UserExternalId)
        .where(UserExternalId.user_id == user.id)
        .order_by(UserExternalId.kind)
    )
    memberships = (
        await db.execute(
            select(Group.id, Group.name, GroupMembership.manual, GroupMembership.synced)
            .join(GroupMembership, GroupMembership.group_id == Group.id)
            .where(GroupMembership.user_id == user.id)
            .order_by(func.lower(Group.name), Group.id)
        )
    ).all()
    linked = [
        LinkedIdentity(
            id=identity.id,
            issuer=identity.issuer,
            subject=identity.subject,
            linked_at=identity.created_at,
            last_login_at=identity.last_login_at,
        )
        for identity in identities
    ]
    project_roles = await project_roles_for(
        db, user_id=user.id, group_ids=[group_id for group_id, *_ in memberships]
    )
    return AdminUser(
        **_summary(user, bool(linked)).model_dump(exclude={"initials"}),
        identities=linked,
        external_ids=[ExternalId(kind=item.kind, value=item.value) for item in external_ids],
        groups=[
            UserGroup(group=GroupRef(id=group_id, name=name), manual=manual, synced=synced)
            for group_id, name, manual, synced in memberships
        ],
        project_roles=project_roles,
        active_session_count=await _active_session_count(db, user.id, settings),
    )


# --- Checks ------------------------------------------------------------------------------------
async def _check_email_free(db: AsyncSession, email: str, *, except_user: UUID | None) -> None:
    statement = select(User.id).where(func.lower(User.email) == email.lower())
    if except_user is not None:
        statement = statement.where(User.id != except_user)
    if await db.scalar(statement.limit(1)) is not None:
        raise EmailTakenProblem


async def _check_external_ids_free(
    db: AsyncSession, external_ids: Sequence[ExternalIdIn], *, except_user: UUID | None
) -> None:
    if not external_ids:
        return
    statement = select(UserExternalId.user_id).where(
        or_(
            *(
                and_(
                    UserExternalId.kind == item.kind,
                    func.lower(UserExternalId.value) == item.value.lower(),
                )
                for item in external_ids
            )
        )
    )
    if except_user is not None:
        statement = statement.where(UserExternalId.user_id != except_user)
    if await db.scalar(statement.limit(1)) is not None:
        raise ExternalIdTakenProblem


def _constraint(exc: IntegrityError) -> str:
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""


async def _flush_unique(db: AsyncSession) -> None:
    """Flush; a unique violation that a concurrent write won is the matching 409."""
    try:
        await db.flush()
    except IntegrityError as exc:
        if "external_ids" in _constraint(exc):
            raise ExternalIdTakenProblem from exc
        if "email" in _constraint(exc):
            raise EmailTakenProblem from exc
        raise


# --- Writing -----------------------------------------------------------------------------------
async def create_user(db: AsyncSession, principal: Principal, body: AdminUserCreate) -> User:
    """Pre-create an active user without an identity (linked at their first SSO
    sign-in by external ID or verified email)."""
    await _check_email_free(db, body.email, except_user=None)
    await _check_external_ids_free(db, body.external_ids, except_user=None)
    user = User(
        email=body.email,
        display_name=body.display_name,
        is_platform_admin=body.is_platform_admin,
        is_active=True,
    )
    db.add(user)
    await _flush_unique(db)
    db.add_all(
        UserExternalId(user_id=user.id, kind=item.kind, value=item.value)
        for item in body.external_ids
    )
    await _flush_unique(db)
    await audit.record(
        db,
        "user.create",
        actor=principal,
        target_type="user",
        target_id=user.id,
        details={
            "rule": _RULE,
            "source": "admin",
            "is_platform_admin": body.is_platform_admin,
            "external_id_kinds": sorted(item.kind for item in body.external_ids),
        },
    )
    return user


async def update_user(
    db: AsyncSession, principal: Principal, user: User, body: AdminUserUpdate
) -> None:
    """PATCH semantics (null = unchanged). c17 (403 ``cannot_change_self``) for your
    own active / platform-admin flags, then 409 ``system_account``, ``email_taken``
    and c18 (``last_platform_admin``). Deactivating ends every session of the user."""
    is_active = body.is_active if body.is_active is not None else user.is_active
    is_platform_admin = (
        body.is_platform_admin if body.is_platform_admin is not None else user.is_platform_admin
    )
    access_change = is_active != user.is_active or is_platform_admin != user.is_platform_admin
    if access_change:  # c17 (403) before the state checks (409)
        require(principal, _RULE, Resource(user_to_change=user.id))

    email_change = body.email is not None and body.email != user.email
    if _is_system(user) and (email_change or is_platform_admin != user.is_platform_admin):
        raise SystemAccountProblem(
            "Service and break-glass accounts keep their email and platform-admin role."
        )
    if email_change and body.email is not None:
        await _check_email_free(db, body.email, except_user=user.id)

    takes_admin_away = (
        user.is_platform_admin and user.is_active and not (is_platform_admin and is_active)
    )
    if takes_admin_away:  # c18, counted under a lock on every active platform admin
        remaining = await other_platform_admins(db, user.id)
        require(
            principal,
            _RULE,
            Resource(user_to_change=user.id, platform_admins_after_change=remaining),
        )

    fields: list[str] = []
    details: dict[str, Any] = {"rule": _RULE}
    if body.display_name is not None and body.display_name != user.display_name:
        user.display_name = body.display_name
        fields.append("display_name")
    if email_change and body.email is not None:
        user.email = body.email
        fields.append("email")
    if is_active != user.is_active:
        user.is_active = is_active
        fields.append("is_active")
        details["is_active"] = is_active
        if not is_active:
            details["sessions_ended"] = await sessions.end_user_sessions(db, user.id)
    if is_platform_admin != user.is_platform_admin:
        user.is_platform_admin = is_platform_admin
        fields.append("is_platform_admin")
        details["is_platform_admin"] = is_platform_admin
    if fields:
        await _flush_unique(db)
        details["fields"] = fields
        await audit.record(
            db,
            "user.update",
            actor=principal,
            target_type="user",
            target_id=user.id,
            details=details,
        )


async def replace_external_ids(
    db: AsyncSession, principal: Principal, user: User, body: ExternalIdsReplace
) -> None:
    """Make the user's external IDs exactly ``body`` (one per kind). Unchanged values
    keep their row; the audit entry names the kinds, never the values."""
    if _is_system(user):
        raise SystemAccountProblem("Service and break-glass accounts can't have external IDs.")
    await _check_external_ids_free(db, body.external_ids, except_user=user.id)
    current = {
        item.kind: item
        for item in await db.scalars(
            select(UserExternalId).where(UserExternalId.user_id == user.id)
        )
    }
    wanted = {item.kind: item.value for item in body.external_ids}
    changed = False
    for kind, row in current.items():
        if kind not in wanted:
            await db.delete(row)
            changed = True
        elif row.value != wanted[kind]:
            row.value = wanted[kind]
            changed = True
    await _flush_unique(db)
    added = [
        UserExternalId(user_id=user.id, kind=kind, value=value)
        for kind, value in wanted.items()
        if kind not in current
    ]
    if added:
        db.add_all(added)
        changed = True
        await _flush_unique(db)
    if changed:
        await audit.record(
            db,
            "user.external_ids_replace",
            actor=principal,
            target_type="user",
            target_id=user.id,
            details={"rule": _RULE, "kinds": sorted(wanted)},
        )


async def unlink_identity(
    db: AsyncSession, principal: Principal, user: User, identity_id: UUID
) -> None:
    """Delete one of the user's identities and end their SSO sessions (the IdP account
    they came from is no longer trusted). 404 unless the identity is this user's."""
    identity = await db.get(UserIdentity, identity_id)
    if identity is None or identity.user_id != user.id:
        raise NotFoundProblem("That identity is not linked to this user.")
    issuer = identity.issuer
    await db.delete(identity)
    ended = await sessions.end_user_sessions(db, user.id, auth_method=AuthMethod.SSO)
    await audit.record(
        db,
        "user.identity_unlink",
        actor=principal,
        target_type="user",
        target_id=user.id,
        details={
            "rule": _RULE,
            "identity_id": identity_id,
            "issuer": issuer,
            "sessions_ended": ended,
        },
    )


async def end_sessions(db: AsyncSession, principal: Principal, user: User) -> None:
    """Sign the user out everywhere (yourself too, if it is you). Idempotent."""
    ended = await sessions.end_user_sessions(db, user.id)
    await audit.record(
        db,
        "user.sessions_end",
        actor=principal,
        target_type="user",
        target_id=user.id,
        details={"rule": _RULE, "count": ended},
    )
