"""``mcp.call`` audit entries (contract-phase5 sections 3.6 and 4.6): one per
``tools/call`` for every outcome, written even when the call rolls back; writes keep
their own entries; nothing secret or personal in entries or logs; the 90-day cleanup."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import uuid4

import httpx2
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_keys.tokens import hash_key
from app.api_keys.verify import verify_api_key
from app.auth.key_auth import KEY_WRITE_THROTTLE
from app.auth.throttle import Throttle
from app.config import Settings
from app.mcp import dispatcher, tools
from app.mcp.audit import delete_expired_calls
from app.mcp.context import McpRequest
from app.models.activity import AuditLog, Comment
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.enums import IdeaStatus
from app.models.idea import Idea
from app.models.project import Project
from app.notifications.schedule import run_schedule
from app.schemas.mcp import McpTool, tool_by_name
from tests.factories import add_evaluator, make_idea
from tests.mcp.conftest import (
    AsAgent,
    Connect,
    MakeKey,
    Team,
    call,
    full_scores,
    headers,
    rpc,
)

SECRET_TEXT = "Zebra-7731-personal-detail"


def key_of(team: Team, idea: Idea) -> str:
    return f"{team.project.key}-{idea.number}"


async def entries(db: AsyncSession) -> list[AuditLog]:
    rows = await db.scalars(
        select(AuditLog)
        .where(AuditLog.action == "mcp.call")
        .order_by(AuditLog.created_at, AuditLog.id)
    )
    return list(rows)


def summary(entry: AuditLog) -> tuple[Any, ...]:
    d = entry.details
    return (d["tool"], d["rule"], d["decision"], d["code"])


async def test_a_successful_call_is_one_entry_about_its_idea(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    agent = await as_agent(team.member, ["read", "mcp"])

    await agent.ok("get_idea", idea=key_of(team, idea))
    await agent.ok("list_projects")

    first, second = await entries(db_session)
    assert summary(first) == ("get_idea", "idea.view", "allow", None)
    assert first.actor_id == team.member.id
    assert (first.target_type, first.target_id, first.project_id) == (
        "idea",
        idea.id,
        team.project.id,
    )
    key_id = await db_session.scalar(select(ApiKey.id))
    assert first.details["auth"] == "api_key"
    assert first.details["api_key_id"] == str(key_id)
    assert "auth_method" not in first.details
    assert summary(second) == ("list_projects", "project.view", "allow", None)
    assert second.target_id is None


async def test_every_outcome_is_audited_once(
    app: FastAPI,
    as_agent: AsAgent,
    team: Team,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    idea = await make_idea(db_session, team.project, status=IdeaStatus.EVALUATING)
    evaluator = team.evaluators[0]
    await add_evaluator(db_session, idea, evaluator)
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(evaluation_closed_at=func.now())
    )
    await db_session.commit()
    ref = key_of(team, idea)
    reader = await as_agent(team.outsider, ["read", "mcp"])
    evaluating = await as_agent(evaluator, ["read", "evaluate", "mcp"])
    read_only = await as_agent(team.member, ["read", "mcp"])

    async def crash(ctx: tools.ToolContext, args: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setitem(tools.TOOLS, "get_rubric", crash)

    assert await reader.fails("no_such_tool") == "unknown_tool"
    assert await reader.fails("get_idea", idea="?") == "validation_error"
    assert await reader.fails("get_idea", idea=ref) == "not_found"  # outsider, private
    assert await read_only.fails("add_comment", idea=ref, body_md="x") == "insufficient_scope"
    closed = await evaluating.fails(
        "submit_evaluation", idea=ref, scores=full_scores(team), recommendation="go"
    )
    assert closed == "evaluation_closed"
    assert await read_only.fails("get_rubric", project=team.slug) == "internal_error"

    logged = await entries(db_session)
    assert [summary(e) for e in logged] == [
        ("unknown", None, "deny", "unknown_tool"),
        ("get_idea", "idea.view", "deny", "validation_error"),
        ("get_idea", "idea.view", "deny", "not_found"),
        ("add_comment", "comment.create", "deny", "insufficient_scope"),
        ("submit_evaluation", "evaluation.submit_own", "allow", "evaluation_closed"),
        ("get_rubric", "project.view", "allow", "internal_error"),
    ]
    # The idea exists, so a denial names it too; the crash had found nothing yet but the
    # project is named by its argument.
    assert [e.target_id for e in logged] == [None, None, idea.id, idea.id, idea.id, team.project.id]


async def test_a_validator_that_crashes_is_audited_as_an_internal_error(
    as_agent: AsAgent, team: Team, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review L1: an input model raising anything but ``ValidationError`` used to escape
    the dispatcher (and its entry)."""

    class Exploding(BaseModel):
        project: str | None = None

        @field_validator("project")
        @classmethod
        def _boom(cls, value: str | None) -> str | None:
            raise TypeError("a bug in a validator")

    real = tool_by_name

    def patched(name: str) -> McpTool | None:
        tool = real(name)
        return replace(tool, input=Exploding) if tool and name == "get_rubric" else tool

    monkeypatch.setattr(dispatcher, "tool_by_name", patched)
    agent = await as_agent(team.member, ["read", "mcp"])

    assert await agent.fails("get_rubric", project=team.slug) == "internal_error"

    logged = await entries(db_session)
    assert [summary(e) for e in logged] == [
        ("get_rubric", "project.view", "deny", "internal_error")
    ]
    assert logged[0].target_id == team.project.id


async def test_a_cancelled_call_is_audited(
    app: FastAPI,
    make_key: MakeKey,
    team: Team,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review L1: a call cancelled while its tool runs (the client went away) is rolled
    back and still leaves its entry, written from a task of its own."""
    started = asyncio.Event()

    async def hang(ctx: tools.ToolContext, args: Any) -> Any:
        ctx.target.project(team.project.id)
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setitem(tools.TOOLS, "get_rubric", hang)
    secret = await make_key(team.member)
    check = await verify_api_key(app.state.sessionmaker, secret, settings=app.state.settings)
    assert check.principal is not None
    request = McpRequest(app=app, principal=check.principal)

    running = asyncio.create_task(
        dispatcher.call_tool(request, "get_rubric", {"project": team.slug})
    )
    await asyncio.wait_for(started.wait(), 5)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    for _ in range(50):
        logged = await entries(db_session)
        if logged:
            break
        await asyncio.sleep(0.1)
    assert [summary(e) for e in logged] == [("get_rubric", "project.view", "allow", "cancelled")]
    assert logged[0].target_id == team.project.id
    assert logged[0].actor_id == team.member.id


async def test_a_denied_write_leaves_only_its_entry(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    viewer = await as_agent(team.viewer, ["read", "write", "mcp"])
    member = await as_agent(team.member, ["read", "write", "mcp"])
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=func.now())
    )
    await db_session.commit()

    assert await viewer.fails("add_comment", idea=key_of(team, idea), body_md="Hi") == ("forbidden")
    assert await member.fails("create_idea", project=team.slug, title="x", summary="y") == (
        "project_archived"
    )

    assert await db_session.scalar(select(func.count()).select_from(Comment)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Idea)) == 1
    assert [summary(e) for e in await entries(db_session)] == [
        ("add_comment", "comment.create", "deny", "forbidden"),
        ("create_idea", "idea.create", "allow", "project_archived"),
    ]
    others = await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action != "mcp.call")
    )
    assert others == 0


async def test_writes_keep_their_own_entries(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    evaluator = team.evaluators[0]
    idea = await make_idea(db_session, team.project, status=IdeaStatus.EVALUATING)
    await add_evaluator(db_session, idea, evaluator)
    agent = await as_agent(evaluator, ["read", "evaluate", "mcp"])

    await agent.ok(
        "submit_evaluation", idea=key_of(team, idea), scores=full_scores(team), recommendation="go"
    )

    actions = list(await db_session.scalars(select(AuditLog.action).order_by(AuditLog.created_at)))
    assert sorted(actions) == ["evaluation.submit", "mcp.call"]
    submit = await db_session.scalar(select(AuditLog).where(AuditLog.action == "evaluation.submit"))
    assert submit is not None
    assert submit.actor_id == evaluator.id
    assert submit.details["auth"] == "api_key"


async def test_the_write_cap_refuses_writes_but_not_reads(
    app: FastAPI, as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    name, _, window = KEY_WRITE_THROTTLE
    app.state.throttles = {name: Throttle(1, window)}
    agent = await as_agent(team.member, ["read", "write", "mcp"])

    first = await agent.ok("add_comment", idea=key_of(team, idea), body_md="One")
    second = await agent.fails("add_comment", idea=key_of(team, idea), body_md="Two")
    read = await agent.ok("get_idea", idea=key_of(team, idea))

    assert first["comment"]["body_md"] == "One"
    assert second == "too_many_attempts"
    assert [c["body_md"] for c in read["idea"]["comments"]] == ["One"]
    assert [summary(e) for e in await entries(db_session)] == [
        ("add_comment", "comment.create", "allow", None),
        ("add_comment", "comment.create", "deny", "too_many_attempts"),
        ("get_idea", "idea.view", "allow", None),
    ]


async def test_no_entry_or_log_line_holds_a_key_or_an_argument(
    make_key: MakeKey,
    connect: Connect,
    raw: httpx2.AsyncClient,
    team: Team,
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    idea = await make_idea(db_session, team.project)
    secret = await make_key(team.member)
    revoked = await make_key(team.member)
    await db_session.execute(
        update(ApiKey).where(ApiKey.lookup_id == revoked[4:16]).values(revoked_at=utcnow())
    )
    await db_session.commit()
    caplog.set_level(logging.DEBUG)

    async with connect(secret) as client:
        await call(client, "search_ideas", query=SECRET_TEXT)
        await call(client, "add_comment", idea=key_of(team, idea), body_md=SECRET_TEXT)
        await call(client, "get_idea", idea=key_of(team, idea), comment_limit=SECRET_TEXT)
        await call(client, "no_such_tool", text=SECRET_TEXT)
    refused = await raw.post(
        "/mcp", json=rpc("tools/call", {"name": "list_projects"}), headers=headers(revoked)
    )

    assert refused.status_code == 401
    assert "api key refused" in caplog.text  # the refusal is logged, without the key
    logged = await entries(db_session)
    assert len(logged) == 4
    stored = json.dumps([entry.details for entry in logged])
    lines = "\n".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    for key in (secret, revoked):
        for text in (key, key[17:], hash_key(key), f"Bearer {key}"):
            assert text not in stored
            assert text not in lines
    assert SECRET_TEXT not in stored
    assert SECRET_TEXT not in lines


async def test_the_cleanup_removes_only_old_mcp_call_entries(
    as_agent: AsAgent, team: Team, db_session: AsyncSession
) -> None:
    agent = await as_agent(team.member, ["read", "mcp"])
    await agent.ok("list_projects")
    now = utcnow()
    old = now - timedelta(days=91)
    db_session.add_all(
        [
            AuditLog(id=uuid4(), action="mcp.call", details={}, created_at=old),
            AuditLog(id=uuid4(), action="evaluation.submit", details={}, created_at=old),
            AuditLog(
                id=uuid4(), action="mcp.call", details={}, created_at=now - timedelta(days=89)
            ),
        ]
    )
    await db_session.commit()

    await delete_expired_calls(db_session, now)
    await db_session.commit()

    left = list(await db_session.execute(select(AuditLog.action, AuditLog.created_at)))
    assert sorted(action for action, _ in left) == ["evaluation.submit", "mcp.call", "mcp.call"]
    assert all(created > old for action, created in left if action == "mcp.call")


async def test_the_hourly_schedule_runs_the_mcp_call_cleanup(
    app: FastAPI, settings: Settings, db_session: AsyncSession
) -> None:
    now = utcnow()
    db_session.add_all(
        [
            AuditLog(
                id=uuid4(), action="mcp.call", details={}, created_at=now - timedelta(days=91)
            ),
            AuditLog(id=uuid4(), action="mcp.call", details={}, created_at=now - timedelta(days=1)),
        ]
    )
    await db_session.commit()

    await run_schedule(app.state.sessionmaker, settings, now)

    left = list(await db_session.scalars(select(AuditLog.created_at)))
    assert len(left) == 1
    assert left[0] > now - timedelta(days=2)
