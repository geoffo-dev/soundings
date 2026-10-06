"""Users as the API sees them: people pickers, the dev login list, lookups."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.principal import Principal
from app.models.enums import ProjectRole
from app.models.project import Project, project_effective_roles
from app.models.user import User
from app.pagination import InvalidCursorProblem, PageParams, decode_cursor, slice_page
from app.schemas.auth import CurrentUser
from app.schemas.users import UserPage, UserSearchResult

__all__ = ["active_user", "escape_like", "list_dev_users", "search_users"]

_roles = project_effective_roles


def escape_like(text: str) -> str:
    """``text`` as a literal inside a ``LIKE`` pattern (use with ``escape="\\\\"``)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def active_user(
    db: AsyncSession, user_id: UUID, *, allow_service_accounts: bool = False
) -> User | None:
    """An active user by id (``None`` for unknown, deactivated, the break-glass admin
    or, unless allowed, service accounts): the ``user_not_found`` check. The
    break-glass admin never holds project roles, ownerships or evaluations
    (contract-phase2 section 3.4)."""
    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.is_break_glass:
        return None
    if user.is_service_account and not allow_service_accounts:
        return None
    return user


async def list_dev_users(db: AsyncSession) -> list[CurrentUser]:
    """People who can sign in: platform admins first, then by name (not service
    accounts or the break-glass admin)."""
    users = await db.scalars(
        select(User)
        .where(User.is_active, User.is_service_account.is_(False), User.is_break_glass.is_(False))
        .order_by(User.is_platform_admin.desc(), func.lower(User.display_name), User.id)
    )
    return [CurrentUser.model_validate(user) for user in users]


async def search_users(
    db: AsyncSession,
    *,
    q: str | None,
    project: Project | None,
    page: PageParams,
    co_members_of: Principal | None = None,
) -> UserPage:
    """Active people whose name or email contains ``q``, by display name (never
    service accounts or the break-glass admin).

    With ``project``: only users with an effective role there, ``project_role`` set.
    With ``co_members_of`` (an AI agent's service account): only people with an
    effective role in a project where it has one too, inside its key's projects; an
    agent doesn't need the whole directory.
    """
    sort_key = func.lower(User.display_name)
    statement: Select[Any] = select(User, sort_key.label("sort_key")).where(
        User.is_active, User.is_service_account.is_(False), User.is_break_glass.is_(False)
    )
    if co_members_of is not None:
        own = select(_roles.c.project_id).where(_roles.c.user_id == co_members_of.user_id)
        if co_members_of.project_ids is not None:
            own = own.where(_roles.c.project_id.in_(list(co_members_of.project_ids)))
        statement = statement.where(
            User.id.in_(select(_roles.c.user_id).where(_roles.c.project_id.in_(own)))
        )
    if project is not None:
        statement = statement.join(
            _roles, and_(_roles.c.user_id == User.id, _roles.c.project_id == project.id)
        ).add_columns(_roles.c.role)
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
    items, next_cursor = slice_page(rows, page.limit, lambda row: {"n": row[1], "id": row[0].id})
    return UserPage(
        items=[
            UserSearchResult(
                id=row[0].id,
                display_name=row[0].display_name,
                avatar_url=row[0].avatar_url,
                email=row[0].email,
                project_role=ProjectRole(row[2]) if project is not None else None,
            )
            for row in items
        ],
        next_cursor=next_cursor,
    )
