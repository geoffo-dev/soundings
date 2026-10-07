"""Phase 6 acceptance against a live server, the real worker and the fake kagent agent
(QA; docs/test-plans/phase-6.md, AC6-API-*).

SPEC section 13, Phase 6: *"Ask AI to evaluate" produces a badged, cited evaluation
excluded from the aggregate by default* (contract-phase6 section 3.14).

Everything is real except the model: the app behind **uvicorn** on a free port (TCP), the
**worker**'s two procrastinate pools (``email`` + ``notifications``, and the ``ai`` pool
that runs ``run_ai``) in this event loop with their default timings, the worker's own
A2A client talking over TCP to **Soundings' fake kagent agent** (``dev/fake-agent``, an
a2a-sdk 1.2.1 server in kagent v0.10.2's controller layout, started here as a
subprocess with ``uv run``), and that agent calling back into the live ``/mcp`` with the
service-account key the admin API showed once. Nothing here talks to a real kagent
controller or an LLM: the fake stands in for both (contract-phase6 section 8).

* AC6-API-1: the acceptance story on the demo data (steps 1-8 of contract 3.14): Alice
  registers "Idea evaluator", the key is shown once and handed to the agent, Test
  connection; CUST-12 (Bob and Carol submitted, Farah and Mateo pending): Alice asks the
  AI to evaluate (201, then 200 with the same run, also when two requests race); Farah,
  a pending evaluator, watches the run's event stream from the start while it runs
  (queued -> ... -> Done, Soundings' sentences only, nothing of the evaluation), replays
  it with ``Last-Event-ID`` and ``?after=``, gets 204 after the end; the run succeeds with
  its evaluation: AI, a rationale and two sources per criterion, left out of the
  aggregate (unchanged); Alice includes it (n 3) and leaves it out again; research note
  and a section draft (accepted); the agent's key outside a run; the audit entries; no
  log line (ours or the fake's) holds the key.
* AC6-API-2: how runs end, on factory data, all at once: cancel while queued (never sent),
  cancel while running (``tasks/cancel``, the assignment taken back), the deadline
  (``timed_out`` after 30 s with ``tasks/cancel``), a late write after the end refused,
  a cancel answered -32603 still ending cancelled, no result / input required / agent
  failed, rule 9 through the agent's own ``get_idea`` and ``search_ideas`` before and
  after it submits (``-blind-probe``), c22 through its own stray calls (``-strays``),
  and the same run over A2A 1.0 (``kagent_v1_0``, the optional protocol).

The module needs ``uv`` and ``dev/fake-agent`` (synced on first use); without them, or
with ``SOUNDINGS_TEST_FAKE_AGENT=0``, it is skipped. It takes about a minute (one demo
seed; AC6-API-2 waits for a 30-second deadline).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from procrastinate import PsycopgConnector
from procrastinate.worker import Worker
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.runner import AiRuntime
from app.config import Settings
from app.email.delivery import Runtime
from app.models.enums import EvaluatorState, IdeaStatus, ProjectRole
from app.models.idea import Idea
from app.models.project import Project
from app.models.user import User
from app.schemas.api_keys import API_KEY_PATTERN
from app.worker import MAIN_QUEUES, ai_worker_options, procrastinate_app, worker_options
from tests.acceptance.test_phase5_acceptance import (
    API,
    Person,
    _free_port,
    _Server,
    audit,
    call,
    data,
    error,
    key_client,
    mcp_client,
    ok,
    score_data,
    sign_in,
)
from tests.factories import add_evaluator, make_idea, make_project, make_user

REPO = Path(__file__).resolve().parents[3]
FAKE_AGENT_DIR = REPO / "dev" / "fake-agent"
CUST = "customer-innovation"
NAMESPACE = "soundings"
RUN_TIMEOUT = timedelta(seconds=30)  # the shortest SOUNDINGS_AI_RUN_TIMEOUT allows
FINAL = {"succeeded", "failed", "cancelled", "timed_out"}

# What the fake agent writes, so it can be searched for: never in front of a pending
# evaluator, in a progress event, an error message or a log line.
AGENT_TEXT = re.compile(r"fake-rationale|example\.org/fake-agent|Fake source|fake agent", re.I)

# Contract 3.14 step 4: the steps of an evaluate run, as Soundings words them.
EVALUATE_STEPS = [
    ("queued", "Waiting to start"),
    ("started", "Sending the request to the agent"),
    ("agent_accepted", "The agent started"),
    ("agent_working", "The agent is working"),
    ("tool_called", "Read the rubric"),
    ("tool_called", "Read the idea"),
    ("tool_called", "Saved its evaluation"),
    ("result_recorded", "Evaluation submitted"),
    ("succeeded", "Done"),
]
WORKING: Final = ("agent_working", "The agent is working")


def evaluate_steps_match(steps: list[tuple[str, str]]) -> bool:
    """``EVALUATE_STEPS``, except that "The agent is working" may land among the tool
    calls: the worker records it from the A2A stream while the API records the agent's
    MCP calls, and on a loaded machine the agent's first call can commit first. It still
    comes once, after "The agent started" and before "Evaluation submitted"."""
    if steps.count(WORKING) != 1:
        return False
    without = [step for step in steps if step != WORKING]
    position = steps.index(WORKING)
    return (
        without == [step for step in EVALUATE_STEPS if step != WORKING]
        and steps.index(("agent_accepted", "The agent started")) < position
        and position < steps.index(("result_recorded", "Evaluation submitted"))
    )


pytestmark = pytest.mark.skipif(
    os.environ.get("SOUNDINGS_TEST_FAKE_AGENT") == "0"
    or shutil.which("uv") is None
    or not (FAKE_AGENT_DIR / "pyproject.toml").is_file(),
    reason="needs uv and dev/fake-agent (SOUNDINGS_TEST_FAKE_AGENT=0 skips it)",
)


# --- The live server, the fake agent and the worker -----------------------------------------
@pytest.fixture
def port() -> int:
    return _free_port()


@pytest.fixture
def fake_port() -> int:
    return _free_port()


@pytest.fixture
def settings_overrides(port: int, fake_port: int) -> dict[str, Any]:
    return {
        "base_urls": [f"http://127.0.0.1:{port}"],
        "dev_login_enabled": True,
        "ai_enabled": True,
        # The only host Soundings calls for AI: the fake, as kagent's controller.
        "kagent_url": f"http://127.0.0.1:{fake_port}",
        "ai_run_timeout": RUN_TIMEOUT,
        "ai_max_concurrent_runs": 12,
        "ai_mcp_url": f"http://127.0.0.1:{port}/mcp",
    }


@pytest.fixture
async def live(app: FastAPI, port: int) -> AsyncIterator[str]:
    """The app (lifespan already running) behind uvicorn on 127.0.0.1:<port>."""
    import uvicorn

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, lifespan="off", log_level="warning", access_log=False
    )
    server = _Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        if task.done():
            task.result()
        await asyncio.sleep(0.025)
    assert server.started, "uvicorn did not start"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)


@dataclass
class FakeAgent:
    """The fake kagent agent in a subprocess: its keys directory (what an operator's
    Secret would be), its log and its observations (``GET /_fake/observations/{run}``)."""

    url: str
    keys_dir: Path
    log: Path
    http: httpx.AsyncClient

    def give_key(self, name: str, secret: str) -> None:
        path = self.keys_dir / f"{NAMESPACE}.{name}"
        path.write_text(f"Bearer {secret}\n")
        path.chmod(0o600)

    async def observations(self, run_id: str) -> dict[str, Any] | None:
        response = await self.http.get(f"/_fake/observations/{run_id}")
        if response.status_code == 404:
            return None
        found: dict[str, Any] = ok(response)
        return found

    async def wait_for(
        self, run_id: str, ready: Callable[[dict[str, Any]], bool], within: float = 30
    ) -> dict[str, Any]:
        seen: dict[str, Any] | None = None
        async with asyncio.timeout(within):
            while True:
                seen = await self.observations(run_id)
                if seen is not None and ready(seen):
                    return seen
                await asyncio.sleep(0.2)


@pytest.fixture
async def fake_agent(port: int, fake_port: int, tmp_path: Path) -> AsyncIterator[FakeAgent]:
    keys = tmp_path / "fake-agent-keys"
    keys.mkdir(mode=0o700)
    log = tmp_path / "fake-agent.log"
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH")}
    env.update(
        FAKE_AGENT_HOST="127.0.0.1",
        FAKE_AGENT_PORT=str(fake_port),
        # Like a kagent RemoteMCPServer's URL: the agent's own setting, never a message's.
        FAKE_AGENT_MCP_URL=f"http://127.0.0.1:{port}/mcp",
        FAKE_AGENT_KEYS_DIR=str(keys),
        FAKE_AGENT_STEP_DELAY="0.2",
        FAKE_AGENT_SLOW_INTERVAL="0.5",
        FAKE_AGENT_LATE_DELAY="1",
        FAKE_AGENT_LOG_LEVEL="INFO",
    )
    with log.open("wb") as out:
        process = subprocess.Popen(  # noqa: S603, ASYNC220 - a fixed command line, started once
            ["uv", "run", "--quiet", "--project", str(FAKE_AGENT_DIR), "fake-agent"],  # noqa: S607
            cwd=FAKE_AGENT_DIR,
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    url = f"http://127.0.0.1:{fake_port}"
    http = httpx.AsyncClient(base_url=url, trust_env=False, timeout=10)
    try:
        for _ in range(240):  # the first `uv run` may sync the environment
            if process.poll() is not None:
                pytest.fail(f"the fake agent exited: {log.read_text()[-2000:]}")
            with contextlib.suppress(httpx.HTTPError):
                if (await http.get("/healthz")).status_code == 200:
                    break
            await asyncio.sleep(0.25)
        else:
            pytest.fail(f"the fake agent did not start: {log.read_text()[-2000:]}")
        yield FakeAgent(url=url, keys_dir=keys, log=log, http=http)
    finally:
        await http.aclose()
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


@dataclass
class Workers:
    """``soundings worker``'s two pools in this event loop (app/worker.py ``run_worker``
    with its defaults: heartbeats, the cancel watch, retries), started when a test says."""

    app: FastAPI
    settings: Settings
    stack: contextlib.AsyncExitStack = field(default_factory=contextlib.AsyncExitStack)
    pools: list[Worker] = field(default_factory=list)
    tasks: list[asyncio.Task[None]] = field(default_factory=list)

    async def start(self) -> None:
        assert not self.pools, "the worker is already running"
        connector = PsycopgConnector(
            conninfo=self.settings.database_dsn,
            min_size=1,
            max_size=self.settings.ai_max_concurrent_runs + 8,
        )
        jobs = self.stack.enter_context(procrastinate_app.replace_connector(connector))
        await self.stack.enter_async_context(jobs.open_async())
        jobs.perform_import_paths()  # type: ignore[no-untyped-call]
        sessionmaker = self.app.state.sessionmaker
        runtime = Runtime(settings=self.settings, sessionmaker=sessionmaker, jobs=jobs)
        # The default runtime: the real A2A client (httpx over TCP) to SOUNDINGS_KAGENT_URL.
        ai_runtime = AiRuntime(settings=self.settings, sessionmaker=sessionmaker)
        self.pools = [
            Worker(
                app=jobs,
                queues=list(MAIN_QUEUES),
                install_signal_handlers=False,
                **worker_options(concurrency=2, runtime=runtime, ai_runtime=ai_runtime),
            ),
            Worker(
                app=jobs,
                install_signal_handlers=False,
                **ai_worker_options(
                    concurrency=self.settings.ai_max_concurrent_runs,
                    runtime=runtime,
                    ai_runtime=ai_runtime,
                ),
            ),
        ]
        self.tasks = [asyncio.create_task(pool.run()) for pool in self.pools]  # type: ignore[no-untyped-call]

    async def stop(self) -> None:
        for pool in self.pools:
            pool.stop()  # type: ignore[no-untyped-call]
        if self.tasks:
            await asyncio.wait_for(asyncio.gather(*self.tasks, return_exceptions=True), 30)
        await self.stack.aclose()


@pytest.fixture
async def workers(app: FastAPI, settings: Settings) -> AsyncIterator[Workers]:
    running = Workers(app=app, settings=settings)
    try:
        yield running
    finally:
        await running.stop()


@pytest.fixture
async def seeded(settings: Settings, app: FastAPI) -> None:
    from app.seed import run_seed

    report = await run_seed(settings)
    assert report.skipped is None
    assert (report.projects, report.ideas) == (3, 48)


@pytest.fixture
async def people(live: str, seeded: None) -> AsyncIterator[dict[str, Person]]:
    """Alice, Bob, Carol, Farah and Mateo from the demo data, signed in, by username."""
    clients: list[httpx.AsyncClient] = []
    anonymous = httpx.AsyncClient(base_url=live, trust_env=False)
    clients.append(anonymous)
    users = {u["email"].split("@")[0]: u for u in ok(await anonymous.get(f"{API}/auth/dev/users"))}
    signed_in: dict[str, Person] = {}
    for username in ("alice", "bob", "carol", "farah", "mateo"):
        http = httpx.AsyncClient(base_url=live, trust_env=False, timeout=30)
        clients.append(http)
        user = users[username]
        ok(await http.post(f"{API}/auth/dev/login", json={"user_id": user["id"]}))
        http.headers["X-CSRF-Token"] = http.cookies["soundings_csrf"]
        signed_in[username] = Person(http, user["id"], user["display_name"])
    try:
        yield signed_in
    finally:
        for http in clients:
            await http.aclose()


# --- Runs and their event stream ------------------------------------------------------------
@dataclass
class Stream:
    status: int
    headers: httpx.Headers
    raw: str
    retry: int | None
    ids: list[int]
    events: list[dict[str, Any]]

    @property
    def steps(self) -> list[tuple[str, str]]:
        return [(event["type"], event["message"]) for event in self.events]


async def read_stream(
    person: Person,
    idea: str,
    run_id: str,
    *,
    last_event_id: str | None = None,
    after: int | None = None,
    within: float = 90,
) -> Stream:
    """``GET .../events`` as ``person`` until the server ends it (after the final event)."""
    headers = {"Accept": "text/event-stream"}
    if last_event_id is not None:
        headers["Last-Event-ID"] = last_event_id
    params = {"after": str(after)} if after is not None else None
    url = f"{API}/ideas/{idea}/ai-runs/{run_id}/events"
    async with (
        asyncio.timeout(within),
        person.http.stream(
            "GET", url, headers=headers, params=params, timeout=httpx.Timeout(within)
        ) as response,
    ):
        raw = "".join([chunk async for chunk in response.aiter_text()])
    retry: int | None = None
    ids: list[int] = []
    events: list[dict[str, Any]] = []
    for block in raw.split("\n\n"):
        for line in block.splitlines():
            name, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if name == "retry":
                retry = int(value)
            elif name == "id":
                ids.append(int(value))
            elif name == "data":
                events.append(json.loads(value))
    return Stream(response.status_code, response.headers, raw, retry, ids, events)


async def wait_run(person: Person, idea: str, run_id: str, within: float = 60) -> dict[str, Any]:
    async with asyncio.timeout(within):
        while True:
            run: dict[str, Any] = await person.get(f"/ideas/{idea}/ai-runs/{run_id}")
            if run["status"] in FINAL:
                return run
            await asyncio.sleep(0.25)


async def wait_event(person: Person, idea: str, run_id: str, event_type: str) -> None:
    async with asyncio.timeout(30):
        while True:
            run = await person.get(f"/ideas/{idea}/ai-runs/{run_id}")
            if any(event["type"] == event_type for event in run["events"]):
                return
            assert run["status"] not in FINAL, run
            await asyncio.sleep(0.2)


def agent_text(text: str) -> list[str]:
    return AGENT_TEXT.findall(text)


async def register(
    admin: Person,
    name: str,
    purposes: list[str],
    project_ids: list[str],
    *,
    display_name: str | None = None,
    protocol: str | None = None,
) -> tuple[dict[str, Any], str, httpx.Response]:
    body: dict[str, Any] = {
        "display_name": display_name or name,
        "description": "Phase 6 acceptance (tests/acceptance/test_phase6_acceptance.py).",
        "namespace": NAMESPACE,
        "name": name,
        "purposes": purposes,
        "project_ids": project_ids,
    }
    if protocol:
        body["protocol"] = protocol
    response = await admin.http.post(f"{API}/admin/ai-agents", json=body)
    created: dict[str, Any] = ok(response, 201)
    return created, created["key"]["secret"], response


def run_request(
    person: Person, idea: str, kind: str, agent_id: str, section: str | None = None
) -> Awaitable[httpx.Response]:
    path = {"evaluate": "evaluation", "research": "research", "draft_section": "section-draft"}
    body: dict[str, Any] = {"agent_id": agent_id}
    if section:
        body["section_key"] = section
    return person.http.post(f"{API}/ideas/{idea}/ai-runs/{path[kind]}", json=body)


# --- AC6-API-1 ------------------------------------------------------------------------------
async def test_ac6_api_1_ask_ai_to_evaluate_gives_a_badged_cited_evaluation_left_out(
    live: str,
    people: dict[str, Person],
    fake_agent: FakeAgent,
    workers: Workers,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="soundings")
    caplog.set_level(logging.INFO)
    alice, bob, farah, mateo = (people[n] for n in ("alice", "bob", "farah", "mateo"))
    cust = await alice.get(f"/projects/{CUST}")
    criteria = {c["id"]: c["name"] for c in cust["rubric"]}

    # 1. Alice registers "Idea evaluator" (soundings/idea-evaluator, evaluate and research)
    #    for Customer Innovation: the key once, with its Secret; the operator (this test)
    #    gives it to the agent; Test connection is ok.
    created, secret, response = await register(
        alice,
        "idea-evaluator",
        ["evaluate", "research"],
        [cust["id"]],
        display_name="Idea evaluator",
    )
    assert response.headers["cache-control"] == "no-store"
    assert re.fullmatch(API_KEY_PATTERN, secret)
    agent = created["agent"]
    agent_id, agent_user = agent["id"], agent["service_account"]["id"]
    assert agent["a2a_url"] == f"{fake_agent.url}/api/a2a/{NAMESPACE}/idea-evaluator/"
    assert agent["card_url"] == agent["a2a_url"] + ".well-known/agent-card.json"
    assert agent["protocol"] == "kagent_v0_10"
    assert (agent["enabled"], agent["display_name"]) == (True, "Idea evaluator")
    assert agent["service_account"]["display_name"] == "Idea evaluator"
    assert [(p["slug"], p["role"]) for p in agent["projects"]] == [(CUST, "member")]
    key = created["key"]["key"]
    assert sorted(key["scopes"]) == ["evaluate", "mcp", "read", "write"]
    assert key["prefix"] == secret[:16]
    manifest = created["secret_manifest"]
    assert f'authorization: "Bearer {secret}"' in manifest
    assert "name: soundings-agent-idea-evaluator" in manifest
    assert f"namespace: {NAMESPACE}" in manifest
    listed = await alice.http.get(f"{API}/admin/ai-agents")
    assert secret not in listed.text
    assert secret[16:] not in listed.text
    assert [a["id"] for a in ok(listed)["items"]] == [agent_id]
    fake_agent.give_key("idea-evaluator", secret)
    tested = await alice.send("POST", f"/admin/ai-agents/{agent_id}/test")
    assert (tested["ok"], tested["http_status"], tested["error_code"]) == (True, 200, None)
    assert tested["url"] == agent["card_url"]
    assert tested["card"]["streaming"] is True
    assert {"0.3", "1.0"} <= set(tested["card"]["protocol_versions"])

    # 2. CUST-12: Bob and Carol submitted, Farah and Mateo still owe theirs.
    before = await alice.get("/ideas/CUST-12")
    assert {e["user"]["display_name"]: e["state"] for e in before["evaluators"]} == {
        "Bob Brown": "submitted",
        "Carol Chen": "submitted",
        "Farah Haddad": "invited",
        "Mateo Rodríguez": "invited",
    }
    aggregate_before = before["aggregate"]
    assert aggregate_before["count"] == 2
    seen_by_farah = await farah.get("/ideas/CUST-12")
    assert seen_by_farah["score_hidden"] is True
    assert seen_by_farah["aggregate"] is None
    runs = await alice.get("/ideas/CUST-12/ai-runs")
    assert runs["ai_enabled"] is True
    assert [a["id"] for a in runs["agents"]] == [agent_id]
    assert runs["permissions"]["can_request_evaluation"] is True
    assert runs["permissions"]["can_include_ai"] is True

    # 3. Alice asks the AI to evaluate: 201 (two racing clicks: one run), the agent is an
    #    invited evaluator with the AI badge, and a third click returns the same run (200).
    first, second = await asyncio.gather(
        run_request(alice, "CUST-12", "evaluate", agent_id),
        run_request(alice, "CUST-12", "evaluate", agent_id),
    )
    assert sorted((first.status_code, second.status_code)) == [200, 201], (first, second)
    run = ok(first, first.status_code)
    run_id = run["id"]
    assert ok(second, second.status_code)["id"] == run_id
    assert (run["status"], run["kind"], run["agent"]["id"]) == ("queued", "evaluate", agent_id)
    assert run["requested_by"]["id"] == alice.id
    again = ok(await run_request(alice, "CUST-12", "evaluate", agent_id), 200)
    assert (again["id"], again["status"]) == (run_id, "queued")
    rows = {e["user"]["id"]: e for e in (await alice.get("/ideas/CUST-12"))["evaluators"]}
    assert (rows[agent_user]["is_ai"], rows[agent_user]["state"]) == (True, "invited")
    assert not any(row["is_ai"] for user, row in rows.items() if user != agent_user)

    #    Farah opens the run's event stream while it waits; then the worker starts it.
    watching = asyncio.create_task(read_stream(farah, "CUST-12", run_id))
    await asyncio.sleep(1.5)  # the stream is open and has replayed "Waiting to start"
    assert not watching.done()
    await workers.start()
    stream = await watching

    # 4. queued -> started -> the agent started -> Read the rubric -> Read the idea -> Saved
    #    its evaluation -> Evaluation submitted -> Done; nothing of the evaluation in it.
    assert stream.status == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert stream.headers["cache-control"] == "no-cache"
    assert stream.headers["x-accel-buffering"] == "no"
    assert stream.raw.startswith("retry: 3000\n")
    assert evaluate_steps_match(stream.steps), stream.steps
    assert stream.ids == [e["seq"] for e in stream.events] == list(range(1, 10))
    assert [e["final"] for e in stream.events] == [False] * 8 + [True]
    assert agent_text(stream.raw) == []
    assert not re.search(r'"(score|scores|recommendation|comment|sources|rationale)"', stream.raw)

    # 5. The run succeeded with its evaluation; the agent's row says submitted.
    done = await alice.get(f"/ideas/CUST-12/ai-runs/{run_id}")
    assert (done["status"], done["error"], done["cancel_requested"]) == ("succeeded", None, False)
    evaluation_id = done["result"]["evaluation_id"]
    assert evaluation_id is not None
    done_steps = [(e["type"], e["message"]) for e in done["events"]]
    assert done_steps == stream.steps, (done_steps, stream.steps)  # one log, in seq order
    assert done["event_count"] == 9
    assert done["can_cancel"] is False
    #    Reconnecting: after the end 204; replays from Last-Event-ID or ?after= (the header
    #    wins).
    ended = await farah.http.get(
        f"{API}/ideas/CUST-12/ai-runs/{run_id}/events", headers={"Last-Event-ID": "9"}
    )
    assert ended.status_code == 204
    assert (await read_stream(farah, "CUST-12", run_id, last_event_id="5")).ids == [6, 7, 8, 9]
    assert (await read_stream(farah, "CUST-12", run_id, after=7)).ids == [8, 9]
    both = await read_stream(farah, "CUST-12", run_id, last_event_id="8", after=2)
    assert both.ids == [9]

    rows = {e["user"]["id"]: e for e in (await alice.get("/ideas/CUST-12"))["evaluators"]}
    assert (rows[agent_user]["is_ai"], rows[agent_user]["state"]) == (True, "submitted")
    owner_view = await alice.get("/ideas/CUST-12")
    assert owner_view["aggregate"] == aggregate_before  # left out: nothing changed
    evaluations = (await alice.get("/ideas/CUST-12/evaluations"))["items"]
    ai_evaluations = [e for e in evaluations if e["is_ai"]]
    assert [e["id"] for e in ai_evaluations] == [evaluation_id]
    ai = ai_evaluations[0]
    assert (ai["evaluator"]["id"], ai["include_in_aggregate"]) == (agent_user, False)
    assert ai["recommendation"] == "maybe"
    assert ai["comment"].startswith("fake-rationale: summary for CUST-12")
    assert {s["criterion_id"] for s in ai["scores"]} == set(criteria)
    for score in ai["scores"]:
        name = criteria[score["criterion_id"]]
        assert 1 <= score["score"] <= 5
        assert score["comment"].startswith(f"fake-rationale: {name} for CUST-12"), score
        assert len(score["sources"]) == 2, score
        for source in score["sources"]:
            assert source["url"].startswith("https://example.org/fake-agent/cust-12/")
            assert source["host"] == "example.org"
            assert source["title"]
    for person in (e for e in evaluations if not e["is_ai"]):
        assert person["include_in_aggregate"] is True
        assert all(score["sources"] == [] for score in person["scores"])  # people never cite

    #    The pending evaluators still see nothing: not in the idea, the evaluations, the
    #    runs, the run and its events, or the feed.
    for pending in (farah, mateo):
        idea = await pending.get("/ideas/CUST-12")
        assert (idea["score_hidden"], idea["aggregate"]) == (True, None)
        assert score_data(idea) == []  # nothing that reveals scores, anywhere in it
        hidden = await pending.get("/ideas/CUST-12/evaluations")
        assert hidden == {"items": [], "score_hidden": True}
        for path in (
            "/ideas/CUST-12",
            "/ideas/CUST-12/evaluations",
            "/ideas/CUST-12/ai-runs",
            f"/ideas/CUST-12/ai-runs/{run_id}",
            "/ideas/CUST-12/activity",
        ):
            text = (await pending.http.get(f"{API}{path}")).text
            assert agent_text(text) == [], path
        rows = {e["user"]["id"]: e for e in idea["evaluators"]}
        assert (rows[agent_user]["is_ai"], rows[agent_user]["state"]) == (True, "submitted")
        assert rows[agent_user]["submitted_at"] is not None

    # 6. Alice includes it: the aggregate and n change; leaves it out again: back.
    toggle = f"/ideas/CUST-12/evaluations/{evaluation_id}/include-in-aggregate"
    included = await alice.send("PUT", toggle, {"include": True})
    assert (included["id"], included["include_in_aggregate"]) == (evaluation_id, True)
    assert (await alice.send("PUT", toggle, {"include": True}))["include_in_aggregate"] is True
    counted = (await alice.get("/ideas/CUST-12"))["aggregate"]
    assert counted["count"] == 3
    assert counted["overall"] != aggregate_before["overall"]
    by_name = {c["name"]: c for c in counted["criteria"]}
    value_before = next(c for c in aggregate_before["criteria"] if c["name"] == "Value")
    ai_value = next(s["score"] for s in ai["scores"] if criteria[s["criterion_id"]] == "Value")
    assert by_name["Value"]["count"] == 3
    assert by_name["Value"]["mean"] == pytest.approx(
        (value_before["mean"] * 2 + ai_value) / 3, abs=0.051
    )
    assert counted["recommendations"]["maybe"] == aggregate_before["recommendations"]["maybe"] + 1
    excluded = await alice.send("PUT", toggle, {"include": False})
    assert excluded["include_in_aggregate"] is False
    assert (await alice.get("/ideas/CUST-12"))["aggregate"] == aggregate_before
    #    Only the owner and admins decide; a pending evaluator gets 404 (it holds scores); a
    #    person's evaluation isn't AI.
    refused = await bob.http.put(f"{API}{toggle}", json={"include": True})
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    hidden = await farah.http.put(f"{API}{toggle}", json={"include": True})
    assert hidden.status_code == 404
    bobs = next(e for e in evaluations if e["evaluator"]["id"] == bob.id)
    person = await alice.http.put(
        f"{API}/ideas/CUST-12/evaluations/{bobs['id']}/include-in-aggregate",
        json={"include": True},
    )
    assert (person.status_code, person.json()["code"]) == (409, "not_ai_evaluation")
    assert (await alice.get("/ideas/CUST-12"))["aggregate"] == aggregate_before

    # 7. "Research this": a research note with sources in the feed.
    research = ok(await run_request(alice, "CUST-12", "research", agent_id), 201)
    researched = await wait_run(alice, "CUST-12", research["id"])
    assert researched["status"] == "succeeded", researched
    assert [e["message"] for e in researched["events"]][-4:] == [
        "Read the idea",
        "Wrote the research note",
        "Research note saved",
        "Done",
    ]
    note_id = researched["result"]["note_id"]
    note = await alice.get(f"/ideas/CUST-12/research-notes/{note_id}")
    assert (note["id"], note["run_id"], note["agent"]["id"]) == (note_id, research["id"], agent_id)
    assert note["body_md"].strip()
    assert note["deleted"] is False
    assert len(note["sources"]) == 3
    assert all(s["url"].startswith("https://") and s["host"] for s in note["sources"])
    assert note["can_delete"] is True  # Alice owns CUST-12 (ai.delete_note)
    feed = (await farah.get("/ideas/CUST-12/activity"))["items"]
    in_feed = [item for item in feed if item["type"] == "ai_research_note"]
    assert [item["note"]["id"] for item in in_feed] == [note_id]
    assert in_feed[0]["actor"]["id"] == agent_user
    assert in_feed[0]["note"]["can_delete"] is False  # Farah is an evaluator, not the owner

    #    "Draft section" on the Risks section of CUST-6's proposal (Alice's, in Proposal):
    #    the admin adds the purpose (the same key: no new Secret), the agent suggests, the
    #    owner accepts.
    updated = await alice.send(
        "PATCH",
        f"/admin/ai-agents/{agent_id}",
        {"purposes": ["evaluate", "research", "draft_section"]},
    )
    assert updated["key"]["id"] == key["id"]
    assert updated["purposes"] == ["evaluate", "research", "draft_section"]
    if (await alice.get("/ideas/CUST-6/proposal"))["proposal"] is None:
        await alice.send("POST", "/ideas/CUST-6/proposal", None, 201)
    proposal = (await alice.get("/ideas/CUST-6/proposal"))["proposal"]
    risks = next(s for s in proposal["sections"] if s["key"] == "risks")
    drafting = ok(await run_request(alice, "CUST-6", "draft_section", agent_id, "risks"), 201)
    assert drafting["section_key"] == "risks"
    drafted = await wait_run(alice, "CUST-6", drafting["id"])
    assert drafted["status"] == "succeeded", drafted
    suggestion_id = drafted["result"]["suggestion_id"]
    suggestions = (await alice.get("/ideas/CUST-6/proposal/suggestions"))["items"]
    suggestion = next(s for s in suggestions if s["id"] == suggestion_id)
    assert (suggestion["source"], suggestion["section_key"]) == ("ai", "risks")
    assert suggestion["author"]["id"] == agent_user
    accepted = await alice.send(
        "POST",
        f"/ideas/CUST-6/proposal/suggestions/{suggestion_id}/accept",
        {"base_version": risks["version"]},
    )
    assert accepted["section"]["body_md"] == suggestion["body_md"]

    # 8. With no run open, the agent's key lists nothing on /mcp and gets 403 on REST.
    async with key_client(live, secret) as rest:
        for method, path in (
            ("GET", "/projects"),
            ("GET", "/ideas/CUST-12"),
            ("POST", "/ideas/CUST-12/ai-runs/evaluation"),
        ):
            denied = await rest.request(method, f"{API}{path}", json={"agent_id": agent_id})
            assert (denied.status_code, denied.json()["code"]) == (403, "insufficient_scope")
    async with mcp_client(live, secret) as client:
        assert data(await call(client, "list_projects"))["projects"] == []
        assert data(await call(client, "search_ideas", query="checkout"))["items"] == []
        assert error(await call(client, "get_idea", idea="CUST-12")) == "ai_run_not_active"
        assert error(await call(client, "get_rubric", project=CUST)) == "ai_run_not_active"
        assert (
            error(
                await call(
                    client,
                    "add_research_note",
                    idea="CUST-12",
                    body_md="Planted later.",
                    sources=[],
                )
            )
            == "ai_run_not_active"
        )
        assert (
            error(
                await call(
                    client,
                    "add_comment",
                    idea="CUST-12",
                    body_md="Not an agent's to write.",
                )
            )
            == "forbidden"  # c22: never an agent's tool, run or no run
        )

    # 9. The audit, read back as an admin: who registered, asked, included, and the agent's
    #    calls under its own key; no secret anywhere.
    def one(entries: list[dict[str, Any]]) -> dict[str, Any]:
        assert len(entries) == 1, entries
        return entries[0]

    registered = one(await audit(alice, action="ai_agent.register"))
    assert (registered["actor_id"], registered["target_type"], registered["target_id"]) == (
        alice.id,
        "user",
        agent_user,
    )
    assert registered["details"]["rule"] == "platform.manage_agents"
    assert registered["details"]["agent_id"] == agent_id
    assert (registered["details"]["namespace"], registered["details"]["name"]) == (
        NAMESPACE,
        "idea-evaluator",
    )
    assert registered["details"]["project_ids"] == [cust["id"]]
    issued = one(
        [e for e in await audit(alice, action="api_key.create") if e["target_id"] == agent_user]
    )
    assert (issued["actor_id"], issued["details"]["key_id"]) == (alice.id, key["id"])
    assert issued["details"]["rule"] == "platform.manage_agents"
    assert issued["details"]["restricted"] is True
    assert any(
        e["target_id"] == agent_user for e in await audit(alice, action="project.member_add")
    )
    changed = one(await audit(alice, action="ai_agent.update"))
    assert "purposes" in changed["details"]["changed"]
    requested = await audit(alice, action="ai_run.request")
    assert sorted(e["details"]["kind"] for e in requested) == [
        "draft_section",
        "evaluate",
        "research",
    ]  # the idempotent 200s are not audited again
    assert {e["details"]["run_id"] for e in requested} == {
        run_id,
        research["id"],
        drafting["id"],
    }
    assert all(e["actor_id"] == alice.id for e in requested)
    added = one(
        [e for e in await audit(alice, action="evaluator.add") if e["target_id"] == agent_user]
    )
    assert (added["actor_id"], added["details"]["idea_id"]) == (alice.id, before["id"])
    assert added["details"]["rule"] == "ai.request_evaluation"
    submitted = [
        e for e in await audit(alice, action="evaluation.submit") if e["actor_id"] == agent_user
    ]
    assert [e["target_label"] for e in submitted] == ["CUST-12"]
    assert submitted[0]["details"]["api_key_id"] == key["id"]
    assert submitted[0]["details"]["evaluation_id"] == evaluation_id
    toggled = await audit(alice, action="evaluation.include_ai")
    # Newest first; the repeated include changed nothing and is not recorded again.
    assert [e["details"]["include"] for e in toggled] == [False, True]
    assert all(e["actor_id"] == alice.id for e in toggled)
    assert all(e["details"]["evaluation_id"] == evaluation_id for e in toggled)
    calls = [e for e in await audit(alice, action="mcp.call") if e["actor_id"] == agent_user]
    tools = [e["details"].get("tool") for e in reversed(calls)]
    assert tools[:3] == ["get_rubric", "get_idea", "submit_evaluation"], tools
    assert "add_research_note" in tools
    assert "propose_proposal_section" in tools
    assert {e["details"].get("auth") for e in calls} == {"api_key"}
    assert {e["details"]["api_key_id"] for e in calls} == {key["id"]}
    denied_calls = [e for e in calls if e["details"].get("decision") != "allow"]
    assert {e["details"].get("code") for e in denied_calls} >= {"ai_run_not_active"}
    everything = json.dumps(await audit(alice))
    assert secret not in everything
    assert secret[16:] not in everything

    # No log record of the story, ours or the agent's, holds the key or the agent's text.
    for record in caplog.records:
        line = f"{record.getMessage()} {record.__dict__}"
        assert secret[16:] not in line, record
        assert agent_text(line) == [], record
    assert secret[16:] not in fake_agent.log.read_text()


# --- AC6-API-2 ------------------------------------------------------------------------------
@dataclass
class World:
    """A private project with an admin (Ada), the ideas' owner (Olga), a pending person
    evaluator (Pat) and two who submitted (Sam, Tia), all signed in over TCP."""

    db: AsyncSession
    project_id: str
    slug: str
    key: str
    ada: Person
    olga: Person
    pat: Person
    sam_user: User
    tia_user: User

    async def idea(self, title: str, *, scored: bool = False, pat: bool = True) -> str:
        olga_user = await self.db.get(User, UUID(self.olga.id))
        project = await self.db.get(Project, UUID(self.project_id))
        assert project is not None
        idea: Idea = await make_idea(
            self.db, project, title=title, owner=olga_user, status=IdeaStatus.EVALUATING
        )
        if scored:
            for user, score in ((self.sam_user, 4), (self.tia_user, 2)):
                await add_evaluator(
                    self.db,
                    idea,
                    user,
                    state=EvaluatorState.SUBMITTED,
                    scores=_scores(score),
                )
        if pat:
            pat_user = await self.db.get(User, UUID(self.pat.id))
            assert pat_user is not None
            await add_evaluator(self.db, idea, pat_user)
        await self.db.commit()
        return f"{self.key}-{idea.number}"


def _scores(score: int) -> dict[str, int]:
    return dict.fromkeys(("Value", "Feasibility", "Effort", "Strategic fit", "Risk"), score)


@pytest.fixture
async def world(live: str, db_session: AsyncSession) -> AsyncIterator[World]:
    ada_user = await make_user(db_session, "Ada Admin", platform_admin=True)
    olga_user = await make_user(db_session, "Olga Owner")
    pat_user = await make_user(db_session, "Pat Pending")
    sam_user = await make_user(db_session, "Sam Scorer")
    tia_user = await make_user(db_session, "Tia Scorer")
    project = await make_project(
        db_session,
        slug="ai-runs",
        key="AIR",
        name="AI runs",
        members={
            ada_user: ProjectRole.ADMIN,
            olga_user: ProjectRole.MEMBER,
            pat_user: ProjectRole.MEMBER,
            sam_user: ProjectRole.MEMBER,
            tia_user: ProjectRole.MEMBER,
        },
    )
    ada = await sign_in(live, ada_user)
    olga = await sign_in(live, olga_user)
    pat = await sign_in(live, pat_user)
    for person in (ada, olga, pat):
        person.http.timeout = httpx.Timeout(30)
    try:
        yield World(
            db=db_session,
            project_id=str(project.id),
            slug=project.slug,
            key=project.key,
            ada=ada,
            olga=olga,
            pat=pat,
            sam_user=sam_user,
            tia_user=tia_user,
        )
    finally:
        for person in (ada, olga, pat):
            await person.http.aclose()


async def test_ac6_api_2_runs_end_cleanly_and_agents_stay_in_their_run(
    world: World, fake_agent: FakeAgent, workers: Workers
) -> None:
    ada, olga, pat = world.ada, world.olga, world.pat

    async def agent(name: str, purposes: list[str], protocol: str | None = None) -> dict[str, Any]:
        created, secret, _ = await register(
            ada, name, purposes, [world.project_id], protocol=protocol
        )
        fake_agent.give_key(name, secret)
        return dict(created["agent"])

    normal = await agent("acc-agent", ["evaluate"])
    slow = await agent("acc-slow", ["evaluate", "research"])
    late = await agent("acc-late", ["evaluate"])
    no_cancel = await agent("acc-no-cancel", ["evaluate"])
    silent = await agent("acc-silent", ["research"])
    asks = await agent("acc-asks", ["evaluate"])
    fails = await agent("acc-fails", ["research"])
    probe = await agent("acc-blind-probe", ["evaluate", "research"])
    strays = await agent("acc-strays", ["evaluate"])
    modern = await agent("acc-modern", ["evaluate"], protocol="kagent_v1_0")
    assert modern["a2a_url"] == f"{fake_agent.url}/agents/{NAMESPACE}/acc-modern"

    queued_idea = await world.idea("Cancelled before it starts")
    cancel_idea = await world.idea("Cancelled while it works")
    deadline_idea = await world.idea("Out of time")
    late_idea = await world.idea("A late write")
    no_cancel_idea = await world.idea("A cancel the agent can't do")
    outcome_idea = await world.idea("Agents that end without a result")
    probe_idea = await world.idea("Two people scored this", scored=True)
    stray_idea = await world.idea("An agent that strays", scored=True)
    neighbour = await world.idea("The idea next door")  # stray_idea's number + 1
    modern_idea = await world.idea("Over A2A 1.0")

    async def ask(idea: str, kind: str, who: dict[str, Any]) -> str:
        created = ok(await run_request(olga, idea, kind, who["id"]), 201)
        return str(created["id"])

    # Cancel while queued (the worker isn't running yet): cancelled at once, never sent.
    queued = await ask(queued_idea, "evaluate", normal)
    cancelled = await olga.send("POST", f"/ideas/{queued_idea}/ai-runs/{queued}/cancel")
    assert (cancelled["status"], cancelled["can_cancel"]) == ("cancelled", False)
    never_started = await olga.get(f"/ideas/{queued_idea}/ai-runs/{queued}")
    assert [e["type"] for e in never_started["events"]] == ["queued", "cancelled"]
    assert never_started["started_at"] is None
    finished = await olga.http.post(f"{API}/ideas/{queued_idea}/ai-runs/{queued}/cancel")
    assert (finished.status_code, finished.json()["code"]) == (409, "ai_run_finished")

    runs: dict[str, tuple[str, str]] = {
        "slow": (cancel_idea, await ask(cancel_idea, "evaluate", slow)),
        "deadline": (deadline_idea, await ask(deadline_idea, "research", slow)),
        "late": (late_idea, await ask(late_idea, "evaluate", late)),
        "no_cancel": (no_cancel_idea, await ask(no_cancel_idea, "evaluate", no_cancel)),
        "silent": (outcome_idea, await ask(outcome_idea, "research", silent)),
        "asks": (outcome_idea, await ask(outcome_idea, "evaluate", asks)),
        "fails": (neighbour, await ask(neighbour, "research", fails)),
        "probe_evaluate": (probe_idea, await ask(probe_idea, "evaluate", probe)),
        "strays": (stray_idea, await ask(stray_idea, "evaluate", strays)),
        "modern": (modern_idea, await ask(modern_idea, "evaluate", modern)),
    }
    # Pat (pending on the slow run's idea) watches it.
    watching = asyncio.create_task(read_stream(pat, cancel_idea, runs["slow"][1]))
    await workers.start()

    # Cancel while running: "Cancelling", tasks/cancel, cancelled; the assignment it made
    # is taken back.
    idea, run_id = runs["slow"]
    await wait_event(olga, idea, run_id, "tool_called")  # it read the idea and works on
    requested = await olga.send("POST", f"/ideas/{idea}/ai-runs/{run_id}/cancel")
    assert (requested["status"], requested["cancel_requested"]) in (
        ("running", True),
        ("cancelled", False),  # the worker already stopped it: nothing left to cancel
    )
    ended = await wait_run(olga, idea, run_id)
    assert (ended["status"], ended["error"]) == ("cancelled", None)
    assert [e["type"] for e in ended["events"]][-2:] == ["cancel_requested", "cancelled"]
    seen = await fake_agent.wait_for(run_id, lambda r: r["final_state"] is not None)
    assert seen["cancel_requests"] >= 1
    assert seen["final_state"] == "canceled"
    evaluators = (await olga.get(f"/ideas/{idea}"))["evaluators"]
    assert [e["user"]["display_name"] for e in evaluators] == ["Pat Pending"]
    stream = await watching
    assert stream.steps[-2:] == [("cancel_requested", "Cancelling"), ("cancelled", "Cancelled")]
    assert agent_text(stream.raw) == []
    removed = [
        e
        for e in await audit(ada, action="evaluator.remove")
        if e["details"].get("run_id") == run_id
    ]
    assert len(removed) == 1
    assert (removed[0]["actor_id"], removed[0]["details"]["reason"]) == (None, "ai_run_ended")
    cancels = [e for e in await audit(ada, action="ai_run.cancel") if e["actor_id"] == olga.id]
    assert {e["details"]["run_id"] for e in cancels} >= {queued, run_id}

    # A cancel the agent answers with -32603 (kagent-adk 0.10.2) still ends cancelled.
    idea, run_id = runs["no_cancel"]
    await wait_event(olga, idea, run_id, "tool_called")
    await olga.send("POST", f"/ideas/{idea}/ai-runs/{run_id}/cancel")
    assert (await wait_run(olga, idea, run_id))["status"] == "cancelled"
    assert (await fake_agent.observations(run_id) or {})["cancel_requests"] >= 1

    # A write after the end (the agent ignores the cancel): refused, nothing recorded.
    idea, run_id = runs["late"]
    await wait_event(olga, idea, run_id, "tool_called")
    await olga.send("POST", f"/ideas/{idea}/ai-runs/{run_id}/cancel")
    over = await wait_run(olga, idea, run_id)
    assert (over["status"], over["result"]["evaluation_id"]) == ("cancelled", None)
    seen = await fake_agent.wait_for(run_id, lambda r: r["late"] is not None)
    assert seen["late"]["tool"] == "submit_evaluation"
    assert seen["late"]["error_code"] == "ai_run_not_active"
    late_evaluations = (await olga.get(f"/ideas/{idea}/evaluations"))["items"]
    assert late_evaluations == []

    # Agents that end without a result: Soundings' sentence, no agent words.
    expected = {
        "silent": ("no_result", "The agent finished without saving a result."),
        "asks": ("agent_needs_input", "The agent asked for input, which a run can't give."),
        "fails": ("agent_failed", "The agent stopped with an error."),
    }
    for name, (code, message) in expected.items():
        idea, run_id = runs[name]
        failed = await wait_run(olga, idea, run_id)
        assert failed["status"] == "failed", (name, failed)
        assert failed["error"]["code"] == code, (name, failed["error"])
        assert failed["error"]["message"].startswith(message), (name, failed["error"])
        assert failed["events"][-1]["type"] == "failed"
        assert failed["events"][-1]["message"] == failed["error"]["message"]
    #    The evaluate run that assigned the agent took the assignment back.
    names = [
        e["user"]["display_name"] for e in (await olga.get(f"/ideas/{outcome_idea}"))["evaluators"]
    ]
    assert names == ["Pat Pending"]

    # Rule 9: the agent never sees others' scores, before or after it submits.
    idea, run_id = runs["probe_evaluate"]
    assert (await wait_run(olga, idea, run_id))["status"] == "succeeded"
    research_probe = await ask(idea, "research", probe)
    assert (await wait_run(olga, idea, research_probe))["status"] == "succeeded"
    for probed in (run_id, research_probe):
        blind = (await fake_agent.observations(probed) or {})["blind"]
        assert {(b["tool"], b["phase"]) for b in blind} == {
            ("get_idea", "before"),
            ("get_idea", "after"),
            ("search_ideas", "before"),
            ("search_ideas", "after"),
        }, blind
        for view in blind:
            assert view["score_hidden"] is True, view
            assert view.get("score") is None, view
            assert view.get("aggregate") is None, view
            assert view.get("evaluations", 0) == 0, view
            assert view.get("evaluation_count", 0) in (0, None), view
            assert view.get("high_disagreement") in (False, None), view
            if view["tool"] == "search_ideas":
                assert (view["found"], view["keys"]) == (True, [idea]), view
    after_submit = next(
        b
        for b in (await fake_agent.observations(run_id) or {})["blind"]
        if b["tool"] == "get_idea" and b["phase"] == "after"
    )
    assert after_submit["my_evaluation_state"] == "submitted"
    #    Its evaluation is left out: Sam's 4 and Tia's 2 still make the aggregate.
    aggregate = (await olga.get(f"/ideas/{idea}"))["aggregate"]
    assert aggregate["count"] == 2

    # c22: what a steered agent tries during its run on one idea is refused; then it works.
    idea, run_id = runs["strays"]
    assert (await wait_run(olga, idea, run_id))["status"] == "succeeded"
    tried = (await fake_agent.observations(run_id) or {})["strays"]
    assert tried == {
        "add_comment": "forbidden",
        "create_idea": "forbidden",
        "get_idea_next": "ai_run_not_active",
        "propose_other_section": "ai_run_not_active",
        "add_research_note": "ai_run_not_active",
        "list_projects": world.slug,
        "search_ideas": idea,
    }, tried
    assert [
        c["body_md"]
        for c in (await olga.get(f"/ideas/{idea}/activity"))["items"]
        if c["type"] == "comment"
    ] == []

    # The optional protocol: the same run over A2A 1.0 (kagent 1.0's layout).
    idea, run_id = runs["modern"]
    assert (await wait_run(olga, idea, run_id))["status"] == "succeeded"
    seen = await fake_agent.observations(run_id) or {}
    first_request = seen["a2a_requests"][0]
    assert (first_request["layout"], first_request["method"], first_request["a2a_version"]) == (
        "kagent_v1_0",
        "SendStreamingMessage",
        "1.0",
    )
    assert [c["tool"] for c in seen["tool_calls"]] == [
        "get_rubric",
        "get_idea",
        "submit_evaluation",
    ]

    # The deadline: tasks/cancel, timed_out (30 s after it started).
    idea, run_id = runs["deadline"]
    out_of_time = await wait_run(olga, idea, run_id, within=75)
    assert out_of_time["status"] == "timed_out", out_of_time
    assert out_of_time["error"]["code"] == "timed_out"
    assert out_of_time["error"]["message"] == "The agent didn't finish in time."
    assert (await fake_agent.observations(run_id) or {})["cancel_requests"] >= 1

    # What Soundings sent, every run: the built URL's layout, X-User-Id, no credentials,
    # no cookie, no context, the run id as message id, nothing secret in the message.
    assert await fake_agent.observations(queued) is None  # cancelled before it was sent
    for _, run_id in runs.values():
        seen = await fake_agent.observations(run_id) or {}
        assert seen["message_id"] == run_id
        assert seen["message_checks"] == {"has_url": False, "has_api_key": False}
        for request in seen["a2a_requests"]:
            assert request["x_user_id"] == "soundings"
            assert (request["authorization"], request["cookie"]) == ("none", False)
            assert request["context_id_sent"] is False
            assert request["history_length"] in (None, 1)
    # The fake never logged a key.
    assert not re.search(r"sdg_[A-Za-z0-9_]{8,}", fake_agent.log.read_text())
