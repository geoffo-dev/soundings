"""Fixtures for the MCP tests (contract-phase5 sections 3.5, 3.6 and 4.6).

Everything goes over HTTP into the real app (``httpx2.ASGITransport`` inside the app's
lifespan, research R1 section 1): in-memory MCP clients skip the guard, so they would
test nothing about keys.

* ``team`` (tests/ideas/conftest.py): "Customer Innovation" (``CUST``) with a person in
  every role. ``make_key(user, scopes, projects=None)`` stores an API key for ``user``
  straight in the database (the key service and its routes are identity's) and returns
  the secret.
* ``connect(secret, mode=...)``: an entered SDK ``Client`` on ``/mcp`` with the key;
  ``mode="legacy"`` forces the initialize handshake, the default probes 2026-07-28.
* ``raw``: an ``httpx2`` client on the app for hand-made JSON-RPC (``rpc(...)``).
* ``call(client, tool, **arguments)``: ``tools/call``; ``data`` the structured content
  of a success, ``error`` the code of a tool error.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_keys.tokens import hash_key, new_key
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.enums import AuthMethod
from app.models.project import Project
from app.models.user import User
from tests.ideas.conftest import (  # noqa: F401 - fixtures
    API,
    Api,
    AsUser,
    Team,
    api,
    assert_problem,
    full_scores,
    ok,
    team,
)

__all__ = [
    "ALL_SCOPES",
    "BASE",
    "MCP_URL",
    "Agent",
    "AsAgent",
    "AsUser",
    "Connect",
    "MakeKey",
    "Team",
    "assert_problem",
    "call",
    "data",
    "error",
    "full_scores",
    "ok",
    "rpc",
]

BASE = "http://testserver"
MCP_URL = f"{BASE}/mcp"
ALL_SCOPES = ("read", "write", "evaluate", "mcp")

MakeKey = Callable[..., Awaitable[str]]
Connect = Callable[..., AbstractAsyncContextManager[Client]]


@pytest.fixture
def make_key(db_session: AsyncSession) -> MakeKey:
    async def make(
        user: User,
        scopes: Iterable[str] = ALL_SCOPES,
        projects: Iterable[Project] | None = None,
        *,
        expires_at: datetime | None = None,
        name: str | None = None,
    ) -> str:
        lookup_id, secret = new_key()
        wanted = set(scopes)
        db_session.add(
            ApiKey(
                id=uuid4(),
                user_id=user.id,
                name=name or f"Key {lookup_id}",
                lookup_id=lookup_id,
                secret_hash=hash_key(secret),
                scopes=[s for s in ALL_SCOPES if s in wanted],
                project_ids=None if projects is None else [p.id for p in projects],
                expires_at=expires_at,
                created_by_id=user.id,
                created_auth_method=AuthMethod.DEV_LOGIN,
            )
        )
        if not user.is_service_account:
            # A person's key works while they use the app (contract-phase5 section 3.1).
            await db_session.execute(
                update(User).where(User.id == user.id).values(last_seen_at=utcnow())
            )
        await db_session.commit()
        return secret

    return make


@pytest.fixture
async def raw(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url=BASE) as http:
        yield http


@pytest.fixture
def connect(app: FastAPI) -> Connect:
    @asynccontextmanager
    async def open_client(secret: str, *, mode: str = "auto") -> AsyncIterator[Client]:
        transport = httpx2.ASGITransport(app=app)
        headers = {"Authorization": f"Bearer {secret}"}
        async with httpx2.AsyncClient(transport=transport, headers=headers) as http:
            client = Client(streamable_http_client(MCP_URL, http_client=http), mode=mode)
            async with client:
                yield client

    return open_client


class Agent:
    """An MCP client identity: a key's secret; ``await agent.call(tool, **arguments)``
    opens a client (SDK, streamable HTTP), calls the tool once and closes it."""

    def __init__(self, connect: Connect, secret: str) -> None:
        self.connect = connect
        self.secret = secret

    async def call(self, tool: str, **arguments: Any) -> CallToolResult:
        async with self.connect(self.secret) as client:
            return await call(client, tool, **arguments)

    async def ok(self, tool: str, **arguments: Any) -> dict[str, Any]:
        return data(await self.call(tool, **arguments))

    async def fails(self, tool: str, **arguments: Any) -> str:
        return error(await self.call(tool, **arguments))


AsAgent = Callable[..., Awaitable[Agent]]


@pytest.fixture
def as_agent(make_key: MakeKey, connect: Connect) -> AsAgent:
    """``await as_agent(user, scopes=..., projects=...)``: an :class:`Agent` with a new key."""

    async def make(
        user: User, scopes: Iterable[str] = ALL_SCOPES, projects: Iterable[Project] | None = None
    ) -> Agent:
        return Agent(connect, await make_key(user, scopes, projects))

    return make


def rpc(method: str, params: dict[str, Any] | None = None, *, id: int = 1) -> dict[str, Any]:  # noqa: A002
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        message["params"] = params
    return message


JSON_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def headers(secret: str | None = None, **extra: str) -> dict[str, str]:
    found = dict(JSON_HEADERS)
    if secret is not None:
        found["Authorization"] = f"Bearer {secret}"
    found.update(extra)
    return found


async def call(client: Client, tool: str, **arguments: Any) -> CallToolResult:
    result = await client.call_tool(tool, arguments)
    assert isinstance(result, CallToolResult)
    return result


def data(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    found: dict[str, Any] = result.structured_content
    return found


def error(result: CallToolResult) -> str:
    assert result.is_error, result.structured_content
    code: str = result.structured_content["code"]
    text = result.content[0]
    assert getattr(text, "text", "").startswith(f"{code}: ")
    return code


def uuid(value: Any) -> UUID:
    return UUID(str(value))
