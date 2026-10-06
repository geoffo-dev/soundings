"""Personal API keys: create, list and revoke (Settings -> API keys and Admin settings
-> API keys; contract-phase5 sections 2, 3.1 and 3.7).

* :func:`create_my_key` (``api_key.manage_own``, session only, c20): the key is shown
  once; only its lookup id and hash are stored. At most
  :data:`~app.schemas.api_keys.MAX_API_KEYS_PER_USER` keys that aren't revoked, names
  unique per owner (any case), counted under a lock on the owner's ``users`` row, which
  also serialises the create with the owner's deactivation.
* :func:`issue_key`: the same for any owner (Phase 6: a platform admin creating an
  agent's key); tests use it for service accounts.
* :func:`list_my_keys`, :func:`revoke_my_key`; :func:`list_admin_keys`,
  :func:`revoke_admin_key` (``api_key.manage_any``).
* :func:`revoke_all_for_user`: deactivation revokes every key of the user, each audited
  ``api_key.revoke`` with ``reason: deactivated``.
* States and refusal reasons are in :mod:`app.api_keys.state`; authentication in
  :mod:`app.api_keys.verify`.

Revoked keys keep their row (audit entries name them) and are never listed. Audit
details carry ids, the public ``prefix``, scopes and dates: never the key or its hash.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, exists, false, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_keys.state import key_state, state_clause
from app.api_keys.tokens import hash_key, key_prefix, lookup_id_query, new_key
from app.auth.sources import UnauthorizedProblem
from app.authz import Resource, Rule, can, require, visible_projects
from app.domain.principal import Principal
from app.errors import ConflictProblem, NotFoundProblem, ProblemError
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.enums import ApiKeyScope, AuthMethod
from app.models.project import Project
from app.models.user import User
from app.pagination import InvalidCursorProblem, PageParams, decode_cursor, slice_page
from app.schemas import api_keys as schemas
from app.schemas.api_keys import MAX_API_KEYS_PER_USER, ApiKeyCreate, ApiKeyState
from app.schemas.projects import ProjectRef
from app.schemas.users import UserRef
from app.services import audit
from app.services.users import escape_like

__all__ = [
    "LOOKUP_ID_ATTEMPTS",
    "ApiKeyNameTakenProblem",
    "InvalidProjectProblem",
    "TooManyApiKeysProblem",
    "create_my_key",
    "issue_key",
    "list_admin_keys",
    "list_my_keys",
    "revoke_admin_key",
    "revoke_all_for_user",
    "revoke_my_key",
]

LOOKUP_ID_ATTEMPTS: Final = 3
"""A lookup-id collision (62^12 ids) is retried with a new id this many times."""


# --- Problems ------------------------------------------------------------------------------
class TooManyApiKeysProblem(ConflictProblem):
    def __init__(self) -> None:
        super().__init__(
            f"You have {MAX_API_KEYS_PER_USER} API keys. Revoke keys you no longer use.",
            code="too_many_api_keys",
        )


class ApiKeyNameTakenProblem(ConflictProblem):
    def __init__(self) -> None:
        super().__init__("You already have an API key with this name.", code="api_key_name_taken")


class InvalidProjectProblem(ProblemError):
    def __init__(self) -> None:
        super().__init__(
            422,
            "invalid_project",
            detail="A key can only be restricted to projects you can view.",
        )


def _key_not_found() -> ProblemError:
    return NotFoundProblem("Not found.")


# --- Responses -----------------------------------------------------------------------------
async def _project_refs(db: AsyncSession, ids: Iterable[UUID]) -> dict[UUID, ProjectRef]:
    """The projects that still exist among ``ids``, by id."""
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return {}
    return {
        project.id: ProjectRef(id=project.id, slug=project.slug, key=project.key, name=project.name)
        for project in await db.scalars(select(Project).where(Project.id.in_(wanted)))
    }


async def _viewable(db: AsyncSession, owner: User, ids: Iterable[UUID]) -> set[UUID]:
    """Which of ``ids`` the owner can view now (``project.view``, as the key would)."""
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return set()
    return set(
        await db.scalars(
            select(Project.id).where(
                Project.id.in_(wanted), visible_projects(Principal(user=owner))
            )
        )
    )


def _restricted_to(key: ApiKey, projects: dict[UUID, ProjectRef]) -> list[ProjectRef]:
    """The key's restricted projects that still exist, by name."""
    found = [projects[project_id] for project_id in key.project_ids or () if project_id in projects]
    return sorted(found, key=lambda ref: (ref.name.lower(), str(ref.id)))


def _fields(
    key: ApiKey,
    owner: User,
    projects: dict[UUID, ProjectRef],
    viewable: set[UUID],
    now: datetime,
) -> dict[str, Any]:
    """An ``ApiKey``'s fields: ``projects`` are the existing restricted ones the owner
    can view, ``unavailable_project_count`` the existing ones they can't (UX m1)."""
    existing = _restricted_to(key, projects)
    return {
        "id": key.id,
        "name": key.name,
        "prefix": key_prefix(key.lookup_id),
        "scopes": [ApiKeyScope(scope) for scope in key.scopes],
        "restricted": key.project_ids is not None,
        "projects": [ref for ref in existing if ref.id in viewable],
        "unavailable_project_count": sum(1 for ref in existing if ref.id not in viewable),
        "expires_at": key.expires_at,
        "state": key_state(key, owner, now),
        "created_at": key.created_at,
        "last_used_at": key.last_used_at,
    }


def _user_ref(user: User) -> UserRef:
    return UserRef(id=user.id, display_name=user.display_name, avatar_url=user.avatar_url)


# --- Your keys -----------------------------------------------------------------------------
def _issuing(principal: Principal) -> None:
    """``api_key.manage_own`` for a new key: 403 ``insufficient_scope`` through a key
    (session only), 403 ``break_glass_account`` for the break-glass account (c20)."""
    require(principal, Rule.API_KEY_MANAGE_OWN, Resource(issuing_api_key=True))


async def list_my_keys(db: AsyncSession, principal: Principal) -> schemas.ApiKeyList:
    """Your keys that aren't revoked, newest first, with whether you may create another."""
    require(principal, Rule.API_KEY_MANAGE_OWN)
    rows = list(
        await db.scalars(
            select(ApiKey)
            .where(ApiKey.user_id == principal.user_id, ApiKey.revoked_at.is_(None))
            .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
        )
    )
    restricted = [pid for row in rows for pid in row.project_ids or ()]
    projects = await _project_refs(db, restricted)
    viewable = await _viewable(db, principal.user, projects)
    now = utcnow()
    return schemas.ApiKeyList(
        items=[
            schemas.ApiKey(**_fields(row, principal.user, projects, viewable, now)) for row in rows
        ],
        max_keys=MAX_API_KEYS_PER_USER,
        can_create=len(rows) < MAX_API_KEYS_PER_USER
        and can(principal, Rule.API_KEY_MANAGE_OWN, Resource(issuing_api_key=True)),
    )


async def create_my_key(
    db: AsyncSession, principal: Principal, body: ApiKeyCreate
) -> schemas.CreatedApiKey:
    """``POST /me/api-keys``: 403 (a key; c20) → 422 ``invalid_project`` → 409
    ``too_many_api_keys`` / ``api_key_name_taken``. Audited ``api_key.create``."""
    _issuing(principal)
    if principal.auth_method is None:  # only sessions create keys, and they have one
        raise UnauthorizedProblem
    row, secret = await issue_key(
        db,
        owner=principal.user,
        creator=principal,
        created_auth_method=principal.auth_method,
        body=body,
    )
    projects = await _project_refs(db, row.project_ids or ())
    viewable = await _viewable(db, principal.user, projects)
    return schemas.CreatedApiKey(
        key=schemas.ApiKey(**_fields(row, principal.user, projects, viewable, utcnow())),
        secret=secret,
    )


async def issue_key(
    db: AsyncSession,
    *,
    owner: User,
    creator: Principal,
    created_auth_method: AuthMethod,
    body: ApiKeyCreate,
) -> tuple[ApiKey, str]:
    """Create a key for ``owner`` and return it with the full key string (show it once,
    never store or log it). The caller has authorised ``creator`` (``api_key.manage_own``
    for their own key; Phase 6: ``platform.manage_agents`` for an agent's).

    Every restricted project must be one the **owner** can view now (else 422
    ``invalid_project``, without saying which). Under a ``FOR NO KEY UPDATE`` lock on
    the owner's row (deactivation updates that row, so the two serialise): the owner
    must still be active (401 otherwise: nothing is created), hold fewer than 25 keys
    that aren't revoked (409 ``too_many_api_keys``) and no such key of the same name in
    any case (409 ``api_key_name_taken``)."""
    if body.project_ids is not None:
        wanted = set(body.project_ids)
        viewable = set(
            await db.scalars(
                select(Project.id).where(
                    Project.id.in_(wanted), visible_projects(Principal(user=owner))
                )
            )
        )
        if viewable != wanted:
            raise InvalidProjectProblem

    active = await db.scalar(
        select(User.is_active).where(User.id == owner.id).with_for_update(key_share=True)
    )
    if not active or owner.is_break_glass:
        raise UnauthorizedProblem
    unrevoked = (ApiKey.user_id == owner.id, ApiKey.revoked_at.is_(None))
    count = await db.scalar(select(func.count()).select_from(ApiKey).where(*unrevoked))
    if (count or 0) >= MAX_API_KEYS_PER_USER:
        raise TooManyApiKeysProblem
    taken = await db.scalar(
        select(exists().where(*unrevoked, func.lower(ApiKey.name) == body.name.lower()))
    )
    if taken:
        raise ApiKeyNameTakenProblem

    now = utcnow()
    for attempt in range(LOOKUP_ID_ATTEMPTS):
        lookup_id, secret = new_key()
        row = ApiKey(
            id=uuid4(),
            user_id=owner.id,
            name=body.name,
            lookup_id=lookup_id,
            secret_hash=hash_key(secret),
            scopes=[scope.value for scope in body.scopes],
            project_ids=None if body.project_ids is None else list(body.project_ids),
            expires_at=body.expires_at,
            created_by_id=creator.user_id,
            created_auth_method=created_auth_method,
            created_at=now,
        )
        try:
            async with db.begin_nested():
                db.add(row)
        except IntegrityError:
            if attempt == LOOKUP_ID_ATTEMPTS - 1:
                raise
            continue
        break
    await audit.record(
        db,
        "api_key.create",
        actor=creator,
        target_type="user",
        target_id=owner.id,
        details={
            "rule": Rule.API_KEY_MANAGE_OWN,
            "key_id": row.id,
            "prefix": key_prefix(row.lookup_id),
            "scopes": list(row.scopes),
            "restricted": row.project_ids is not None,
            "project_ids": row.project_ids,
            "expires_at": row.expires_at,
        },
    )
    return row, secret


async def _revoke(
    db: AsyncSession,
    key: ApiKey,
    *,
    actor: Principal,
    rule: Rule,
    reason: str | None = None,
) -> None:
    key.revoked_at = utcnow()
    key.revoked_by_id = actor.user_id
    details: dict[str, Any] = {"rule": rule, "key_id": key.id, "prefix": key_prefix(key.lookup_id)}
    if reason is not None:
        details["reason"] = reason
    await audit.record(
        db,
        "api_key.revoke",
        actor=actor,
        target_type="user",
        target_id=key.user_id,
        details=details,
    )


async def revoke_my_key(db: AsyncSession, principal: Principal, key_id: UUID) -> None:
    """``DELETE /me/api-keys/{key_id}``: 403 through a key, 404 for someone else's or an
    unknown key, nothing for one already revoked. The next request with it is 401."""
    require(principal, Rule.API_KEY_MANAGE_OWN)
    key = await db.scalar(
        select(ApiKey)
        .where(ApiKey.id == key_id, ApiKey.user_id == principal.user_id)
        .with_for_update()
    )
    if key is None:
        raise _key_not_found()
    if key.revoked_at is None:
        await _revoke(db, key, actor=principal, rule=Rule.API_KEY_MANAGE_OWN)


# --- Every user's keys (platform admins) ------------------------------------------------
def _admin_filters(
    *,
    q: str | None,
    user_id: UUID | None,
    state: ApiKeyState | None,
    now: datetime,
) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = [ApiKey.revoked_at.is_(None)]
    if q:
        pattern = f"%{escape_like(q)}%"
        lookup_id = lookup_id_query(q)
        clauses.append(
            or_(
                ApiKey.name.ilike(pattern, escape="\\"),
                User.display_name.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
                ApiKey.lookup_id == lookup_id if lookup_id is not None else false(),
            )
        )
    if user_id is not None:
        clauses.append(ApiKey.user_id == user_id)
    if state is not None:
        clauses.append(state_clause(state, now))
    return clauses


async def list_admin_keys(
    db: AsyncSession,
    principal: Principal,
    *,
    q: str | None,
    user_id: UUID | None,
    state: ApiKeyState | None,
    page: PageParams,
) -> schemas.AdminApiKeyPage:
    """Keys that aren't revoked, of every user, newest first (keyset on
    ``created_at, id``), with ``total`` for the filters."""
    require(principal, Rule.API_KEY_MANAGE_ANY)
    now = utcnow()
    clauses = _admin_filters(q=q, user_id=user_id, state=state, now=now)
    total = await db.scalar(
        select(func.count())
        .select_from(ApiKey)
        .join(User, User.id == ApiKey.user_id)
        .where(*clauses)
    )
    statement = select(ApiKey, User).join(User, User.id == ApiKey.user_id).where(*clauses)
    if page.cursor:
        after = decode_cursor(page.cursor)
        try:
            position = (datetime.fromisoformat(str(after["c"])), UUID(str(after["id"])))
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidCursorProblem from exc
        if position[0].tzinfo is None:
            raise InvalidCursorProblem
        statement = statement.where(tuple_(ApiKey.created_at, ApiKey.id) < position)
    rows: list[tuple[ApiKey, User]] = [
        (key, owner)
        for key, owner in await db.execute(
            statement.order_by(ApiKey.created_at.desc(), ApiKey.id.desc()).limit(page.limit + 1)
        )
    ]
    items, next_cursor = slice_page(
        rows, page.limit, lambda row: {"c": row[0].created_at, "id": row[0].id}
    )
    projects = await _project_refs(db, (pid for key, _ in items for pid in key.project_ids or ()))
    viewable: dict[UUID, set[UUID]] = {}
    for key, owner in items:
        if key.project_ids and owner.id not in viewable:
            owned = {pid for k, o in items if o.id == owner.id for pid in k.project_ids or ()}
            viewable[owner.id] = await _viewable(db, owner, (p for p in owned if p in projects))
    creators = await _users_by_id(db, (key.created_by_id for key, _ in items))
    return schemas.AdminApiKeyPage(
        items=[
            schemas.AdminApiKey(
                **(
                    _fields(key, owner, projects, viewable.get(owner.id, set()), now)
                    | {
                        "projects": [
                            schemas.AdminApiKeyProject(
                                **ref.model_dump(),
                                owner_can_view=ref.id in viewable.get(owner.id, set()),
                            )
                            for ref in _restricted_to(key, projects)
                        ]
                    }
                ),
                owner=_user_ref(owner),
                owner_email=owner.email,
                owner_is_service_account=owner.is_service_account,
                created_by=(
                    _user_ref(creators[key.created_by_id])
                    if key.created_by_id in creators
                    else None
                ),
            )
            for key, owner in items
        ],
        next_cursor=next_cursor,
        total=int(total or 0),
    )


async def _users_by_id(db: AsyncSession, ids: Iterable[UUID | None]) -> dict[UUID, User]:
    wanted = {user_id for user_id in ids if user_id is not None}
    if not wanted:
        return {}
    return {user.id: user for user in await db.scalars(select(User).where(User.id.in_(wanted)))}


async def revoke_admin_key(db: AsyncSession, principal: Principal, key_id: UUID) -> None:
    """``DELETE /admin/api-keys/{key_id}``: 403 before 404 (admin order); nothing for a
    key already revoked. Audited with the owner as target."""
    require(principal, Rule.API_KEY_MANAGE_ANY)
    key = await db.scalar(select(ApiKey).where(ApiKey.id == key_id).with_for_update())
    if key is None:
        raise _key_not_found()
    if key.revoked_at is None:
        await _revoke(db, key, actor=principal, rule=Rule.API_KEY_MANAGE_ANY)


async def revoke_all_for_user(
    db: AsyncSession,
    user_id: UUID,
    *,
    actor: Principal,
    rule: Rule = Rule.PLATFORM_MANAGE_USERS,
    reason: str = "deactivated",
) -> int:
    """Revoke every key of ``user_id`` that isn't revoked (deactivation: call it in the
    same transaction, after changing ``users.is_active``). Flushes first, so the
    ``users`` update (and its row lock) comes before the keys are read: a create that
    held the lock has committed and its key is revoked here too. Returns how many."""
    await db.flush()
    keys = list(
        await db.scalars(
            select(ApiKey)
            .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
            .order_by(ApiKey.created_at, ApiKey.id)
            .with_for_update()
        )
    )
    for key in keys:
        await _revoke(db, key, actor=actor, rule=rule, reason=reason)
    return len(keys)
