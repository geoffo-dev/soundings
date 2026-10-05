"""Helpers for tests that need API keys (identity's, and the MCP and acceptance tests).

``world`` (a fixture; import it into a test module to use it there): three projects
and the people around them.

* ``cust`` (private, ``CUST``): ``lead`` admin, ``carol`` member, ``vic`` viewer,
  ``bot`` (a service account) member.
* ``tools`` (internal, ``TOOLS``): ``lead`` admin, ``carol`` member.
* ``secret`` (private, ``SEC``): ``lead`` admin only.
* ``platform``: a platform admin without project roles; ``outsider``: nobody special.

``make_key`` creates a key through the service layer (as Phase 6 will for service
accounts) and returns the full key string; ``key_client`` is a client that sends it as
``Authorization: Bearer``. A **person's** key works only while they have used the app
within 30 days (``users.last_seen_at``), so ``make_key`` marks the owner as seen now
unless ``seen=False``; service accounts are exempt.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_keys.service import issue_key
from app.domain.principal import Principal
from app.models.activity import AuditLog
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.enums import ApiKeyScope, AuthMethod, ProjectRole, ProjectVisibility
from app.models.project import Project
from app.models.user import User
from app.schemas.api_keys import ApiKeyCreate
from tests.factories import make_project, make_user

API = "/api/v1"
ALL_SCOPES = ("read", "write", "evaluate", "mcp")


async def mark_seen(db: AsyncSession, user: User, at: datetime | None = None) -> None:
    """Set ``users.last_seen_at`` (as a session request would)."""
    await db.execute(update(User).where(User.id == user.id).values(last_seen_at=at or utcnow()))
    await db.commit()


async def make_key(
    db: AsyncSession,
    owner: User,
    *,
    scopes: Iterable[str] = ALL_SCOPES,
    project_ids: Iterable[UUID] | None = None,
    expires_at: datetime | None = None,
    name: str | None = None,
    method: AuthMethod = AuthMethod.DEV_LOGIN,
    creator: User | None = None,
    seen: bool = True,
) -> str:
    """A new key of ``owner`` (the full key string). ``expires_at`` is written after
    creation, so a past expiry is possible here (the API refuses one)."""
    if seen and not owner.is_service_account:
        await mark_seen(db, owner)
    body = ApiKeyCreate(
        name=name or f"Key {utcnow().timestamp()}",
        scopes=[ApiKeyScope(scope) for scope in scopes],
        project_ids=None if project_ids is None else list(project_ids),
    )
    row, secret = await issue_key(
        db,
        owner=owner,
        creator=Principal(user=creator or owner, auth_method=method),
        created_auth_method=method,
        body=body,
    )
    if expires_at is not None:
        row.expires_at = expires_at
    await db.commit()
    return secret


async def key_row(db: AsyncSession, key: str) -> ApiKey:
    """The stored row of a key (by its lookup id), fresh from the database."""
    row = await db.scalar(
        select(ApiKey)
        .where(ApiKey.lookup_id == key[4:16])
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


def key_client(app: FastAPI, key: str | None = None, **headers: str) -> httpx.AsyncClient:
    """A client without cookies that sends ``key`` as a bearer token (close it)."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    sent = dict(headers)
    if key is not None:
        sent["Authorization"] = f"Bearer {key}"
    return httpx.AsyncClient(transport=transport, base_url="http://testserver", headers=sent)


async def audit_rows(db: AsyncSession, action: str) -> list[AuditLog]:
    rows = await db.scalars(
        select(AuditLog)
        .where(AuditLog.action == action)
        .order_by(AuditLog.created_at, AuditLog.id)
        .execution_options(populate_existing=True)
    )
    return list(rows)


def problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json", response.headers
    body: dict[str, Any] = response.json()
    assert body["code"] == code, body
    return body


@dataclass
class World:
    cust: Project
    tools: Project
    secret: Project
    lead: User
    carol: User
    vic: User
    bot: User
    platform: User
    outsider: User


@pytest.fixture
async def world(db_session: AsyncSession) -> World:
    lead = await make_user(db_session, "Lena Lead")
    carol = await make_user(db_session, "Carol Chen")
    vic = await make_user(db_session, "Vic Viewer")
    bot = await make_user(db_session, "Research Agent", service_account=True)
    platform = await make_user(db_session, "Pat Platform", platform_admin=True)
    outsider = await make_user(db_session, "Otto Outsider")
    cust = await make_project(
        db_session,
        slug="customer-innovation",
        key="CUST",
        name="Customer Innovation",
        members={
            lead: ProjectRole.ADMIN,
            carol: ProjectRole.MEMBER,
            vic: ProjectRole.VIEWER,
            bot: ProjectRole.MEMBER,
        },
    )
    tools = await make_project(
        db_session,
        slug="internal-tools",
        key="TOOLS",
        name="Internal Tools",
        visibility=ProjectVisibility.INTERNAL,
        members={lead: ProjectRole.ADMIN, carol: ProjectRole.MEMBER},
    )
    secret = await make_project(
        db_session, slug="secret", key="SEC", name="Secret", members={lead: ProjectRole.ADMIN}
    )
    return World(
        cust=cust,
        tools=tools,
        secret=secret,
        lead=lead,
        carol=carol,
        vic=vic,
        bot=bot,
        platform=platform,
        outsider=outsider,
    )
