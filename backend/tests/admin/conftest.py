"""Fixtures for the admin (users, groups, audit, SSO) and project group-grant tests.

``people``: a platform admin (``admin``), a second platform admin (``other_admin``),
plain people and a private project (``project``, ``tools``) where ``lead`` is the
admin. ``api(user)`` signs a user in (dev login) and returns a small client helper.
Builders (``make_group``, ``add_to_group``, ``grant``, ``link_identity``,
``add_external_id``, ``make_session``) commit, like ``tests/factories.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import hash_token, new_token
from app.models.activity import AuditLog
from app.models.base import utcnow
from app.models.enums import AuthMethod, GroupSyncMode, ProjectRole
from app.models.group import Group, GroupIdpValue, GroupMembership, ProjectGroupGrant
from app.models.project import Project
from app.models.user import User, UserExternalId, UserIdentity, UserSession
from app.schemas.groups import normalise_idp_value
from tests.conftest import Login
from tests.factories import make_project, make_user

API = "/api/v1"
ISSUER = "https://idp.example.com/realms/acme"


def assert_problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    body: dict[str, Any] = response.json()
    assert body["code"] == code, body
    return body


def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


class Api:
    """A signed-in client with short helpers (paths are relative to ``/api/v1``)."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def get(self, path: str, **params: Any) -> httpx.Response:
        return await self.http.get(API + path, params=params)

    async def post(self, path: str, body: Any = None) -> httpx.Response:
        return await self.http.post(API + path, json=body)

    async def put(self, path: str, body: Any = None) -> httpx.Response:
        return await self.http.put(API + path, json=body)

    async def patch(self, path: str, body: Any = None) -> httpx.Response:
        return await self.http.patch(API + path, json=body)

    async def delete(self, path: str) -> httpx.Response:
        return await self.http.delete(API + path)


AsUser = Callable[[User], Awaitable[Api]]


@pytest.fixture
def api(login: Login) -> AsUser:
    async def sign_in(user: User) -> Api:
        return Api(await login(user))

    return sign_in


@dataclass
class People:
    admin: User
    other_admin: User
    lead: User
    bob: User
    carol: User
    retired: User
    project: Project

    @property
    def slug(self) -> str:
        return self.project.slug


@pytest.fixture
async def people(db_session: AsyncSession) -> People:
    admin = await make_user(db_session, "Alice Anders", platform_admin=True)
    other_admin = await make_user(db_session, "Zed Admin", platform_admin=True)
    lead = await make_user(db_session, "Lena Lead")
    bob = await make_user(db_session, "Bob Brown")
    carol = await make_user(db_session, "Carol Chen")
    retired = await make_user(db_session, "Rita Retired", active=False)
    project = await make_project(
        db_session,
        slug="internal-tools",
        key="TOOLS",
        name="Internal Tools",
        members={lead: ProjectRole.ADMIN, bob: ProjectRole.MEMBER},
    )
    return People(admin, other_admin, lead, bob, carol, retired, project)


# --- Builders -------------------------------------------------------------------------------
async def make_group(
    db: AsyncSession,
    name: str,
    *,
    idp_values: Iterable[str] = (),
    sync_mode: GroupSyncMode = GroupSyncMode.MANAGED,
    description: str = "",
) -> Group:
    group = Group(id=uuid4(), name=name, description=description, sync_mode=sync_mode)
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


@dataclass(frozen=True)
class StartedSession:
    row: UserSession
    token: str
    csrf_token: str


async def make_session(
    db: AsyncSession, user: User, method: AuthMethod = AuthMethod.SSO
) -> StartedSession:
    """A live session row (as if the user had signed in elsewhere), with its cookie
    token and CSRF token."""
    now = utcnow()
    token, csrf_token = new_token(), new_token()
    session = UserSession(
        id=uuid4(),
        token_hash=hash_token(token),
        user_id=user.id,
        csrf_token=csrf_token,
        auth_method=method,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=4),
    )
    db.add(session)
    await db.commit()
    return StartedSession(session, token, csrf_token)


async def session_count(db: AsyncSession, user_id: UUID) -> int:
    await db.commit()  # end the transaction (objects stay loaded): see the API's writes
    return len(list(await db.scalars(select(UserSession.id).where(UserSession.user_id == user_id))))


async def audit_entries(db: AsyncSession, action: str | None = None) -> list[AuditLog]:
    await db.commit()  # end the transaction (objects stay loaded): see the API's writes
    statement = select(AuditLog).order_by(AuditLog.created_at, AuditLog.id)
    if action is not None:
        statement = statement.where(AuditLog.action == action)
    return list(await db.scalars(statement))
