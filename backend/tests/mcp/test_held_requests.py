"""A tool runs with the key as it is when the tool runs (security review M1).

The guard authenticates ``/mcp`` on the headers; the SDK reads the body afterwards. A
client that holds its body back (uvicorn has no body-read timeout) used to keep the
principal of that moment: a key revoked meanwhile still created an idea. The dispatcher
now re-checks the key and rebuilds its principal inside the tool's own transaction, so
a revoked or expired key, a deactivated owner or a lost platform-admin flag applies to
every call that runs after it.

The requests here go straight to the ASGI app with a ``receive`` that hands over the
first bytes of the body and then waits; once the SDK asks for the rest (the guard has
let the request in by then), the test changes the key or its owner and releases it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.idea import Idea
from app.models.user import User
from tests.factories import make_idea
from tests.mcp.conftest import MakeKey, Team, rpc

Change = Callable[[], Awaitable[None]]


async def held_call(
    app: FastAPI, secret: str, tool: str, arguments: dict[str, Any], change: Change
) -> dict[str, Any]:
    """``tools/call`` with its body held back until ``change`` has run; the JSON-RPC
    ``result``."""
    body = json.dumps(rpc("tools/call", {"name": tool, "arguments": arguments})).encode()
    chunks = [body[:10], body[10:]]
    reading, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def receive() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"type": "http.request", "body": chunks[0], "more_body": True}
        if calls == 2:
            reading.set()  # the SDK is reading the body: the guard has admitted us
            await release.wait()
            return {"type": "http.request", "body": chunks[1], "more_body": False}
        await asyncio.Event().wait()  # never a disconnect while the call runs
        raise AssertionError("unreachable")

    sent: list[dict[str, Any]] = []

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(dict(message))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"authorization", f"Bearer {secret}".encode()),
            (b"content-type", b"application/json"),
            (b"accept", b"application/json, text/event-stream"),
            (b"mcp-protocol-version", b"2025-11-25"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 5555),
        "server": ("testserver", 80),
    }
    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.wait_for(reading.wait(), 10)
    await change()
    release.set()
    await asyncio.wait_for(task, 10)

    start = next(message for message in sent if message["type"] == "http.response.start")
    assert start["status"] == 200, sent
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    result: dict[str, Any] = json.loads(payload)["result"]
    return result


def tool_error(result: dict[str, Any]) -> str:
    assert result["isError"] is True, result
    code: str = result["structuredContent"]["code"]
    return code


async def last_call(db: AsyncSession) -> dict[str, Any]:
    entry = await db.scalar(
        select(AuditLog)
        .where(AuditLog.action == "mcp.call")
        .order_by(AuditLog.created_at.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    assert entry is not None
    return {k: entry.details[k] for k in ("tool", "decision", "code")}


async def ideas_titled(db: AsyncSession, title: str) -> int:
    found = await db.scalar(select(func.count()).select_from(Idea).where(Idea.title == title))
    return int(found or 0)


async def test_a_key_revoked_while_the_body_is_held_changes_nothing(
    app: FastAPI, make_key: MakeKey, team: Team, db_session: AsyncSession
) -> None:
    secret = await make_key(team.member)

    async def revoke() -> None:
        await db_session.execute(update(ApiKey).values(revoked_at=utcnow()))
        await db_session.commit()

    result = await held_call(
        app,
        secret,
        "create_idea",
        {"project": team.slug, "title": "Written after the revoke", "summary": "No."},
        revoke,
    )

    assert tool_error(result) == "unauthorized"
    assert await ideas_titled(db_session, "Written after the revoke") == 0
    assert await last_call(db_session) == {
        "tool": "create_idea",
        "decision": "deny",
        "code": "unauthorized",
    }


async def test_a_key_that_expires_while_the_body_is_held_changes_nothing(
    app: FastAPI, make_key: MakeKey, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, title="Commented on")
    secret = await make_key(team.member)

    async def expire() -> None:
        await db_session.execute(update(ApiKey).values(expires_at=utcnow()))
        await db_session.commit()

    result = await held_call(
        app, secret, "add_comment", {"idea": str(idea.id), "body_md": "Too late."}, expire
    )

    assert tool_error(result) == "unauthorized"


async def test_an_owner_deactivated_while_the_body_is_held_changes_nothing(
    app: FastAPI, make_key: MakeKey, team: Team, db_session: AsyncSession
) -> None:
    secret = await make_key(team.member)

    async def deactivate() -> None:
        # Only the flag: the service would also revoke the keys (another path to 401).
        await db_session.execute(
            update(User).where(User.id == team.member.id).values(is_active=False)
        )
        await db_session.commit()

    result = await held_call(
        app,
        secret,
        "create_idea",
        {"project": team.slug, "title": "Written by a leaver", "summary": "No."},
        deactivate,
    )

    assert tool_error(result) == "unauthorized"
    assert await ideas_titled(db_session, "Written by a leaver") == 0


async def test_a_platform_admin_demoted_while_the_body_is_held_sees_nothing(
    app: FastAPI, make_key: MakeKey, team: Team, db_session: AsyncSession
) -> None:
    """The platform admin has no role in the (private) project: only the flag let them in."""
    idea = await make_idea(db_session, team.project, title="Private plan")
    secret = await make_key(team.platform)

    async def demote() -> None:
        await db_session.execute(
            update(User).where(User.id == team.platform.id).values(is_platform_admin=False)
        )
        await db_session.commit()

    result = await held_call(app, secret, "get_idea", {"idea": str(idea.id)}, demote)

    assert tool_error(result) == "not_found"
    assert await last_call(db_session) == {
        "tool": "get_idea",
        "decision": "deny",
        "code": "not_found",
    }


async def test_nothing_changed_while_the_body_is_held_still_works(
    app: FastAPI, make_key: MakeKey, team: Team, db_session: AsyncSession
) -> None:
    secret = await make_key(team.member)

    async def nothing() -> None:
        return None

    result = await held_call(
        app,
        secret,
        "create_idea",
        {"project": team.slug, "title": "Written slowly", "summary": "Fine."},
        nothing,
    )

    assert result["isError"] is False, result
    assert await ideas_titled(db_session, "Written slowly") == 1
