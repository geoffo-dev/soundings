from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette

from fake_agent.app import create_app
from fake_agent.config import Settings
from tests.fake_mcp import IDEA, FakeMcp

KEY = "sdg_TESTLOOKUP_0123456789abcdefghij"
AGENTS = (
    "idea-evaluator",
    "idea-evaluator-slow",
    "idea-evaluator-lingers",
    "idea-evaluator-fails",
    "idea-evaluator-silent",
    "idea-evaluator-asks",
    "idea-evaluator-rejects",
    "idea-evaluator-blind-probe",
    "idea-evaluator-strays",
    "idea-evaluator-late",
    "idea-evaluator-no-cancel",
    "idea-evaluator-unavailable",
    "idea-evaluator-drops",
)


class Server:
    """An ASGI app served by uvicorn on a free port in a thread (real sockets, so
    streams that never end and cancels during a stream behave as they do in a pod)."""

    def __init__(self, app: Starlette) -> None:
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> str:
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.02)
        port = self._server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    def __exit__(self, *exc: object) -> None:
        self._server.should_exit = True
        self._thread.join(10)


@pytest.fixture
def mcp() -> Iterator[tuple[FakeMcp, str]]:
    fake = FakeMcp()
    with Server(fake.app()) as url:
        yield fake, url + "/mcp"


@pytest.fixture
def settings(mcp: tuple[FakeMcp, str]) -> Settings:
    return Settings(
        mcp_url=mcp[1],
        keys={f"soundings/{name}": KEY for name in AGENTS},
        step_delay=0.01,
        slow_interval=0.1,
        late_delay=0.2,
        mcp_timeout=5,
    )


@dataclass
class Agent:
    base: str
    mcp: FakeMcp
    http: httpx.Client

    def url(self, name: str = "idea-evaluator", layout: str = "v0_10") -> str:
        if layout == "v0_10":
            return f"{self.base}/api/a2a/soundings/{name}/"
        return f"{self.base}/agents/soundings/{name}"

    def observations(self, run_id: str) -> dict[str, Any]:
        response = self.http.get(f"{self.base}/_fake/observations/{run_id}")
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    def observations_safe(self, run_id: str) -> dict[str, Any]:
        response = self.http.get(f"{self.base}/_fake/observations/{run_id}")
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    def background_stream(
        self, url: str, body: dict[str, Any], protocol: str = "0.3"
    ) -> tuple[list[dict[str, Any]], threading.Event]:
        """Listen to a stream in a thread: (events so far, set when it ended)."""
        events: list[dict[str, Any]] = []
        done = threading.Event()

        def listen() -> None:
            try:
                with httpx.Client(timeout=30, trust_env=False) as client:
                    events.extend(stream(client, url, body, protocol=protocol))
            finally:
                done.set()

        threading.Thread(target=listen, daemon=True).start()
        return events, done

    def task_id(self, run_id: str, timeout: float = 5.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task_id = self.observations_safe(run_id).get("task_id")
            if isinstance(task_id, str):
                return task_id
            time.sleep(0.05)
        raise AssertionError("the run's task never started")


@pytest.fixture
def agent(settings: Settings, mcp: tuple[FakeMcp, str]) -> Iterator[Agent]:
    with Server(create_app(settings)) as base, httpx.Client(timeout=10, trust_env=False) as http:
        yield Agent(base=base, mcp=mcp[0], http=http)


@pytest.fixture
def make_agent(mcp: tuple[FakeMcp, str]) -> Iterator[Any]:
    """An agent server with changed settings (``make_agent(required_token="t")``)."""
    servers: list[Server] = []
    clients: list[httpx.Client] = []

    def make(base_settings: Settings, **changes: Any) -> Agent:
        server = Server(create_app(replace(base_settings, **changes)))
        servers.append(server)
        client = httpx.Client(timeout=10, trust_env=False)
        clients.append(client)
        return Agent(base=server.__enter__(), mcp=mcp[0], http=client)

    yield make
    for client in clients:
        client.close()
    for server in servers:
        server.__exit__(None, None, None)


def run_message(
    kind: str = "evaluate",
    *,
    run_id: str | None = None,
    idea: str = IDEA,
    section_key: object = None,
    protocol: str = "0.3",
) -> tuple[str, dict[str, Any]]:
    """A run's message as Soundings builds it (contract-phase6 section 3.4)."""
    run_id = run_id or str(uuid.uuid4())
    metadata = {
        "soundings": {"run_id": run_id, "kind": kind, "idea": idea, "section_key": section_key}
    }
    text = f"Soundings AI run {run_id} ({kind}) for idea {idea}."
    if protocol == "0.3":
        message: dict[str, Any] = {
            "kind": "message",
            "messageId": run_id,
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "metadata": metadata,
        }
        method = "message/stream"
    else:
        message = {
            "messageId": run_id,
            "role": "ROLE_USER",
            "parts": [{"text": text}],
            "metadata": metadata,
        }
        method = "SendStreamingMessage"
    return run_id, {
        "jsonrpc": "2.0",
        "id": f"{run_id}-1",
        "method": method,
        "params": {"message": message, "configuration": {"acceptedOutputModes": ["text/plain"]}},
    }


def headers(protocol: str = "0.3", **extra: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "A2A-Version": protocol,
        "X-User-Id": "soundings",
        **extra,
    }


def stream(
    client: httpx.Client,
    url: str,
    body: dict[str, Any],
    *,
    protocol: str = "0.3",
    until: int | None = None,
) -> list[dict[str, Any]]:
    """The ``result``s (or ``error``s) of an SSE stream; stops after ``until`` events."""
    events: list[dict[str, Any]] = []
    with client.stream("POST", url, json=body, headers=headers(protocol)) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = json.loads(line[5:])
            events.append(payload.get("result", payload))
            if until is not None and len(events) >= until:
                break
    return events


def rpc(
    client: httpx.Client, url: str, method: str, params: dict[str, Any], protocol: str = "0.3"
) -> dict[str, Any]:
    response = client.post(
        url,
        json={"jsonrpc": "2.0", "id": "r1", "method": method, "params": params},
        headers={**headers(protocol), "Accept": "application/json"},
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def state_of(event: dict[str, Any]) -> str | None:
    """The task state in a 0.3 or 1.0 stream result."""
    for key in ("statusUpdate", "task"):
        if key in event:
            event = event[key]
    status = event.get("status") or {}
    state = status.get("state")
    return state if isinstance(state, str) else None
