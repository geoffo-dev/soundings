"""Live progress over SSE (contract-phase6 section 3.6), through a real uvicorn (the ASGI
test transport buffers whole responses): authorisation, replay after Last-Event-ID or
``after``, live events, the close after the final event, 204 on a reconnect after it,
the per-person limit, the re-check, keep-alives, and blind safety with a real AI
evaluation run (a pending evaluator's stream holds no score, rationale or source)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import transitions
from app.ai.runner import AiRuntime, execute_run
from app.ai.sse import RunEventHub, event_stream
from app.db import session_scope
from app.models.enums import AiRunEventType, AiRunKind, AiRunStatus, EvaluatorState
from app.models.user import User
from tests.ai.conftest import Crew
from tests.ai.helpers import open_run
from tests.factories import add_evaluator, make_idea

API = "/api/v1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def port() -> int:
    return _free_port()


@pytest.fixture
def settings_overrides(port: int) -> dict[str, Any]:
    return {
        "base_urls": [f"http://127.0.0.1:{port}"],
        "dev_login_enabled": True,
        "ai_enabled": True,
    }


class _Server(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


@pytest.fixture
async def live(app: FastAPI, port: int) -> AsyncIterator[str]:
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, lifespan="off", log_level="warning", access_log=False
    )
    server = _Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.025)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)


async def _person(base: str, user: User) -> httpx.AsyncClient:
    http = httpx.AsyncClient(base_url=base, timeout=10)
    signed = await http.post(f"{API}/auth/dev/login", json={"user_id": str(user.id)})
    assert signed.status_code == 200, signed.text
    return http


def _parse(raw: str) -> list[dict[str, Any]]:
    """The stream as messages: {"id", "data"} (data parsed), plus comments and retry."""
    messages = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        message: dict[str, Any] = {}
        for line in block.split("\n"):
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "":
                message["comment"] = value
            elif field == "data":
                message["data"] = json.loads(value)
            else:
                message[field] = value
        messages.append(message)
    return messages


async def _finished_run(crew: Crew, db: AsyncSession, app: FastAPI) -> UUID:
    run = await open_run(db, crew.agent, crew.idea, AiRunKind.RESEARCH, status=AiRunStatus.QUEUED)
    async with session_scope(app.state.sessionmaker) as session:
        await transitions.add_event(session, run.id, AiRunEventType.QUEUED)
        await transitions.add_event(session, run.id, AiRunEventType.CANCEL_REQUESTED)
        await transitions.finish(
            session, run.id, from_status=AiRunStatus.QUEUED, status=AiRunStatus.CANCELLED
        )
    return run.id


# --- Before the stream ------------------------------------------------------------------------
async def test_problems_come_before_any_stream_byte(
    live: str, crew: Crew, db_session: AsyncSession
) -> None:
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    other = await make_idea(db_session, crew.team.project)
    url = f"{API}/ideas/{crew.ref}/ai-runs/{run.id}/events"
    async with httpx.AsyncClient(base_url=live) as anonymous:
        unauthenticated = await anonymous.get(url)
    outsider = await _person(live, crew.team.outsider)
    owner = await _person(live, crew.team.owner)

    hidden = await outsider.get(url)
    elsewhere = await owner.get(f"{API}/ideas/CUST-{other.number}/ai-runs/{run.id}/events")
    malformed = await owner.get(url, headers={"Last-Event-ID": "x"})

    for response, status in (
        (unauthenticated, 401),
        (hidden, 404),
        (elsewhere, 404),
        (malformed, 422),
    ):
        assert response.status_code == status, response.text
        assert response.headers["content-type"] == "application/problem+json"
    await outsider.aclose()
    await owner.aclose()


# --- Replay, close, 204 -------------------------------------------------------------------------
async def test_replay_after_last_event_id_or_after_then_close(
    live: str, crew: Crew, db_session: AsyncSession, app: FastAPI
) -> None:
    run_id = await _finished_run(crew, db_session, app)
    viewer = await _person(live, crew.team.viewer)
    url = f"{API}/ideas/{crew.ref}/ai-runs/{run_id}/events"

    everything = await viewer.get(url)
    after_one = await viewer.get(url, params={"after": 1})
    header_wins = await viewer.get(url, params={"after": 0}, headers={"Last-Event-ID": "2"})
    nothing_new = await viewer.get(url, headers={"Last-Event-ID": "3"})

    assert everything.status_code == 200
    assert everything.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert everything.headers["cache-control"] == "no-cache"
    assert everything.headers["x-accel-buffering"] == "no"
    assert "content-encoding" not in everything.headers
    messages = _parse(everything.text)
    assert messages[0] == {"retry": "3000"}
    assert [(m["id"], m["data"]["type"]) for m in messages[1:]] == [
        ("1", "queued"),
        ("2", "cancel_requested"),
        ("3", "cancelled"),
    ]
    assert messages[-1]["data"]["final"] is True
    assert "event" not in str([m.keys() for m in messages])
    assert [m["id"] for m in _parse(after_one.text)[1:]] == ["2", "3"]
    assert [m["id"] for m in _parse(header_wins.text)[1:]] == ["3"]
    assert nothing_new.status_code == 204
    await viewer.aclose()


async def test_live_events_arrive_and_the_stream_ends_after_the_final_one(
    live: str, crew: Crew, db_session: AsyncSession, app: FastAPI
) -> None:
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    viewer = await _person(live, crew.team.viewer)
    maker = app.state.sessionmaker
    seen: list[dict[str, Any]] = []

    async def write_later() -> None:
        await asyncio.sleep(0.3)
        async with session_scope(maker) as db:
            await transitions.add_event(db, run.id, AiRunEventType.AGENT_WORKING)
        await asyncio.sleep(0.3)
        async with session_scope(maker) as db:
            await transitions.finish(
                db, run.id, from_status=AiRunStatus.RUNNING, status=AiRunStatus.CANCELLED
            )

    writer = asyncio.create_task(write_later())
    async with (
        asyncio.timeout(10),
        viewer.stream("GET", f"{API}/ideas/{crew.ref}/ai-runs/{run.id}/events") as response,
    ):
        assert response.status_code == 200
        raw = ""
        async for chunk in response.aiter_text():
            raw += chunk
    await writer

    seen = [m for m in _parse(raw) if "data" in m]
    assert [m["data"]["type"] for m in seen] == ["agent_working", "cancelled"]
    assert seen[-1]["data"]["final"] is True
    await viewer.aclose()


async def test_five_open_streams_per_person(
    live: str, crew: Crew, db_session: AsyncSession, app: FastAPI
) -> None:
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    viewer = await _person(live, crew.team.viewer)
    url = f"{API}/ideas/{crew.ref}/ai-runs/{run.id}/events"
    async with contextlib.AsyncExitStack() as stack:
        for _ in range(5):
            response = await stack.enter_async_context(viewer.stream("GET", url))
            assert response.status_code == 200
        refused = await viewer.get(url)
        other = await _person(live, crew.team.owner)
        allowed = await stack.enter_async_context(other.stream("GET", url))

        assert refused.status_code == 429
        assert refused.json()["code"] == "too_many_attempts"
        assert allowed.status_code == 200
    await asyncio.sleep(0.2)
    from app.ai.sse import get_hub

    hub = get_hub(app)
    async with asyncio.timeout(5):
        while hub.open_streams(crew.team.viewer.id):  # noqa: ASYNC110 - the server's tasks
            await asyncio.sleep(0.05)
    await viewer.aclose()
    await other.aclose()


# --- The generator: keep-alives, re-check, max duration ------------------------------------------
async def test_keep_alives_and_the_recheck(
    app: FastAPI, crew: Crew, db_session: AsyncSession
) -> None:
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    hub = RunEventHub(app.state.sessionmaker, interval=0.05)
    checks: list[bool] = []

    async def recheck() -> bool:
        checks.append(True)
        return len(checks) < 2  # access removed at the second re-check

    chunks = [
        chunk
        async for chunk in event_stream(
            hub,
            app.state.sessionmaker,
            run.id,
            0,
            recheck,
            heartbeat=0.05,
            recheck_every=0.2,
            max_duration=5,
        )
    ]

    assert chunks[0] == b"retry: 3000\n\n"
    assert b": keep-alive\n\n" in chunks
    assert len(checks) == 2  # it ended at the failed re-check, without a final event
    await hub.close()


async def test_a_stream_ends_after_its_maximum_duration(
    app: FastAPI, crew: Crew, db_session: AsyncSession
) -> None:
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    hub = RunEventHub(app.state.sessionmaker, interval=0.05)

    async def recheck() -> bool:
        return True

    async with asyncio.timeout(5):
        chunks = [
            chunk
            async for chunk in event_stream(
                hub,
                app.state.sessionmaker,
                run.id,
                0,
                recheck,
                heartbeat=1,
                recheck_every=1,
                max_duration=0.3,
            )
        ]

    assert chunks == [b"retry: 3000\n\n"]
    await hub.close()


async def test_the_recheck_follows_the_session_and_idea_view(
    live: str, app: FastAPI, crew: Crew, db_session: AsyncSession
) -> None:
    """``still_allowed``: the session (not kept alive) and idea.view, as at connect."""
    from fastapi import Request

    from app.ai.sse import still_allowed
    from app.domain.principal import Principal
    from app.models.project import ProjectMember

    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    viewer = await _person(live, crew.team.viewer)
    cookie = viewer.cookies["soundings_session"]
    scope = {
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "query_string": b"",
        "server": ("127.0.0.1", 80),
        "headers": [(b"cookie", f"soundings_session={cookie}".encode())],
        "app": app,
    }
    request = Request(scope)
    principal = Principal(user=crew.team.viewer)

    assert await still_allowed(app, request, principal, crew.idea.id, run.id) is True
    member = await db_session.get(ProjectMember, (crew.team.project.id, crew.team.viewer.id))
    assert member is not None
    await db_session.delete(member)
    await db_session.commit()
    assert await still_allowed(app, request, principal, crew.idea.id, run.id) is False
    await viewer.aclose()


# --- Blind safety ---------------------------------------------------------------------------------
async def test_a_pending_evaluator_watching_an_ai_evaluation_learns_no_score_data(
    live: str, api: Any, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime
) -> None:
    pending = crew.team.evaluators[2]
    await add_evaluator(db_session, crew.idea, pending)
    for evaluator in crew.team.evaluators[:2]:
        await add_evaluator(db_session, crew.idea, evaluator, state=EvaluatorState.SUBMITTED)
    owner = await _person(live, crew.team.owner)
    owner.headers["X-CSRF-Token"] = owner.cookies["soundings_csrf"]
    created = await owner.post(
        f"{API}/ideas/{crew.ref}/ai-runs/evaluation", json={"agent_id": str(crew.agent.id)}
    )
    assert created.status_code == 201, created.text
    run_id = UUID(created.json()["id"])
    watcher = await _person(live, pending)

    async def watch() -> str:
        raw = ""
        async with watcher.stream(
            "GET", f"{API}/ideas/{crew.ref}/ai-runs/{run_id}/events"
        ) as response:
            assert response.status_code == 200
            async for chunk in response.aiter_text():
                raw += chunk
        return raw

    watching = asyncio.create_task(watch())
    await asyncio.sleep(0.2)
    await execute_run(ai_runtime, run_id)
    raw = await asyncio.wait_for(watching, 10)
    detail = (await watcher.get(f"{API}/ideas/{crew.ref}/ai-runs/{run_id}")).json()
    idea = (await watcher.get(f"{API}/ideas/{crew.ref}")).json()

    messages = [m["data"]["message"] for m in _parse(raw) if "data" in m]
    assert messages[-1] == "Done"
    assert "Evaluation submitted" in messages
    for text in (raw, json.dumps(detail)):
        for leak in ("RATIONALE", "SUMMARY", "example.org", "maybe", "score", "SECRET"):
            assert leak not in text, leak
    assert idea["score_hidden"] is True
    assert idea["aggregate"] is None
    await owner.aclose()
    await watcher.aclose()


def test_streams_are_capped_per_process_too() -> None:
    """L6: besides 5 per person, at most ``STREAMS_PER_PROCESS`` open streams per API
    process (each on another run adds a poller reading once a second); the count is
    released as streams close."""
    from typing import Any, cast
    from uuid import uuid4

    import pytest

    from app.ai.sse import STREAMS_PER_PROCESS, RunEventHub, TooManyStreamsProblem

    assert 20 <= STREAMS_PER_PROCESS <= 200
    hub = RunEventHub(cast(Any, None), max_streams=3)  # never polls here
    people = [uuid4() for _ in range(4)]
    for person in people[:3]:
        hub.open_stream(person)
    with pytest.raises(TooManyStreamsProblem) as refused:
        hub.open_stream(people[3])
    assert (refused.value.status, refused.value.code) == (429, "too_many_attempts")
    hub.close_stream(people[0])
    hub.open_stream(people[3])
    assert hub.total_streams() == 3
