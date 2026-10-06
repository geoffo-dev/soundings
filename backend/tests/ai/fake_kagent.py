"""An in-process stand-in for kagent's controller, for the runner and SSE tests.

``FakeKagent.transport`` is an ``httpx.MockTransport``: the runner's A2A client talks to
it exactly as to ``http://kagent-controller.kagent:8083`` (no network), and every request
is recorded (method, URL, headers, JSON body) so tests can assert what Soundings sent:
only the built URLs, the headers, ``historyLength: 1``, ``tasks/cancel``. It speaks A2A
0.3 at ``/api/a2a/{ns}/{name}/`` and 1.0 at ``/agents/{ns}/{name}`` (``A2A-Version``
checked like kagent: other values 400).

Behaviour by agent name suffix (as the platform's fake agent, contract-phase6 3.12):
``-slow`` keeps working until cancelled; ``-fails`` ends failed; ``-silent`` completes
without working; ``-asks`` goes input-required; ``-rejects`` ends rejected; ``-drops``
closes the stream while working (the runner polls ``tasks/get``); ``-nocancel`` answers
``tasks/cancel`` with -32603 like kagent-adk 0.10.2; ``-redirect`` answers 302;
``-down`` answers 503; ``-unknown`` sends an unknown state; ``-message`` replies with a
direct message (no task). Anything else does the work: ``work(metadata)`` (the test's
MCP calls as the agent), then completes.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx

Work = Callable[[dict[str, Any]], Awaitable[None]]

V03 = "/api/a2a/"
V10 = "/agents/"


@dataclass
class Recorded:
    method: str
    url: str
    headers: dict[str, str]
    body: Any


@dataclass
class Task:
    id: str
    context_id: str
    state: str = "submitted"
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)


class FakeKagent:
    def __init__(self, work: Work | None = None, *, step: float = 0.02) -> None:
        self.work = work
        self.step = step
        self.requests: list[Recorded] = []
        self.tasks: dict[str, Task] = {}
        self.transport = httpx.MockTransport(self._handle)

    # --- what tests read ------------------------------------------------------------------
    def calls(self, method: str) -> list[Recorded]:
        return [
            r for r in self.requests if isinstance(r.body, dict) and r.body.get("method") == method
        ]

    @property
    def urls(self) -> set[str]:
        return {r.url for r in self.requests}

    # --- the controller -------------------------------------------------------------------
    async def _handle(self, request: httpx.Request) -> httpx.Response:
        body: Any = None
        if request.content:
            body = json.loads(request.content)
        self.requests.append(
            Recorded(request.method, str(request.url), dict(request.headers), body)
        )
        path = request.url.path
        v10 = path.startswith(V10)
        version = request.headers.get("a2a-version")
        if v10 and version != "1.0":
            return httpx.Response(400, json={"error": "A2A-Version 1.0 required"})
        if not v10 and version not in (None, "0.3"):
            return httpx.Response(400, json={"error": "unsupported A2A-Version"})
        name = (
            path.rstrip("/").split("/")[-1] if "/.well-known/" not in path else path.split("/")[-3]
        )
        if "-redirect" in name:
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})
        if "-down" in name:
            return httpx.Response(503, text="unavailable")
        if request.method == "GET" and path.endswith("/.well-known/agent-card.json"):
            return httpx.Response(200, json=self.card(name))
        assert isinstance(body, dict)
        method = body["method"]
        if method in ("message/stream", "SendStreamingMessage"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=self._stream(body, name, v10),
            )
        if method in ("tasks/get", "GetTask"):
            task = self.tasks.get(body["params"]["id"])
            if task is None:
                return self._error(body, -32001, "task not found")
            return self._result(body, self._task(task, v10, bare=True))
        if method in ("tasks/cancel", "CancelTask"):
            task = self.tasks.get(body["params"]["id"])
            if task is None:
                return self._error(body, -32001, "task not found")
            if "-nocancel" in name:
                return self._error(body, -32603, "NotImplementedError")
            task.state = "canceled"
            task.cancelled.set()
            return self._result(body, self._task(task, v10, bare=True))
        return self._error(body, -32601, "method not found")

    def card(self, name: str) -> dict[str, Any]:
        return {
            "name": name.replace("-", "_"),
            "description": "A fake kagent agent " + "x" * 300,
            "url": "http://evil.example/somewhere-else/",
            "protocolVersion": "0.3.0",
            "supportedInterfaces": [
                {
                    "url": "http://evil.example/",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "0.3",
                },
                {
                    "url": "http://evil.example/",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "1.0",
                },
            ],
            "capabilities": {"streaming": True, "pushNotifications": False},
            "skills": [{"id": f"skill-{n}", "name": f"Skill {n}"} for n in range(25)],
        }

    # --- JSON-RPC ---------------------------------------------------------------------------
    @staticmethod
    def _result(body: dict[str, Any], result: Any) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id"), "result": result})

    @staticmethod
    def _error(body: dict[str, Any], code: int, message: str) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": code, "message": message},
            },
        )

    @staticmethod
    def _state(state: str, v10: bool) -> str:
        return f"TASK_STATE_{state.upper().replace('-', '_')}" if v10 else state

    def _task(self, task: Task, v10: bool, *, bare: bool = False) -> dict[str, Any]:
        inner: dict[str, Any] = {
            "id": task.id,
            "contextId": task.context_id,
            "status": {"state": self._state(task.state, v10)},
            "history": [{"role": "agent", "parts": [{"text": "SECRET AGENT TEXT"}]}],
        }
        if v10:
            return inner if bare else {"task": inner}
        return {"kind": "task", **inner}

    def _status(self, task: Task, v10: bool, *, final: bool = False) -> dict[str, Any]:
        status = {
            "state": self._state(task.state, v10),
            "message": {"role": "agent", "parts": [{"text": "SECRET STATUS TEXT"}]},
        }
        if v10:
            return {
                "statusUpdate": {"taskId": task.id, "contextId": task.context_id, "status": status}
            }
        return {
            "kind": "status-update",
            "taskId": task.id,
            "contextId": task.context_id,
            "status": status,
            "final": final,
        }

    @staticmethod
    def _sse(body: dict[str, Any], result: Any) -> bytes:
        message = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": result})
        return f"data: {message}\n\n".encode()

    async def _stream(self, body: dict[str, Any], name: str, v10: bool) -> AsyncIterator[bytes]:
        metadata = body["params"]["message"].get("metadata", {}).get("soundings", {})
        if "-message" in name:
            reply: dict[str, Any] = {
                "messageId": "m1",
                "role": "ROLE_AGENT" if v10 else "agent",
                "parts": [],
            }
            yield self._sse(body, {"message": reply} if v10 else {"kind": "message", **reply})
            return
        task = Task(id=f"task-{uuid4().hex}", context_id=f"ctx-{uuid4().hex}")
        self.tasks[task.id] = task
        yield b": keep-alive\n\n"
        yield self._sse(body, self._task(task, v10))
        await asyncio.sleep(self.step)
        if "-silent" in name:
            task.state = "completed"
            yield self._sse(body, self._status(task, v10, final=True))
            return
        if "-unknown" in name:
            task.state = "dreaming"
            yield self._sse(body, self._status(task, v10, final=True))
            return
        task.state = "working"
        yield self._sse(body, self._status(task, v10))
        if "-drops" in name:
            # The stream ends while working; the work goes on (the runner polls).
            asyncio.get_running_loop().create_task(self._finish_later(task, metadata))
            return
        if "-slow" in name:
            while not task.cancelled.is_set():
                await asyncio.sleep(self.step)
                yield self._sse(body, self._status(task, v10))
            yield self._sse(body, self._status(task, v10, final=True))
            return
        if "-donefails" in name:  # records its result, then its task fails
            if self.work is not None:
                await self.work(metadata)
            task.state = "failed"
            yield self._sse(body, self._status(task, v10, final=True))
            return
        for suffix, state in (
            ("-fails", "failed"),
            ("-asks", "input-required"),
            ("-rejects", "rejected"),
        ):
            if suffix in name:
                task.state = state
                yield self._sse(body, self._status(task, v10, final=True))
                return
        if self.work is not None:
            await self.work(metadata)
        task.state = "completed"
        yield self._sse(body, self._status(task, v10, final=True))

    async def _finish_later(self, task: Task, metadata: dict[str, Any]) -> None:
        if self.work is not None:
            await self.work(metadata)
        await asyncio.sleep(self.step)
        task.state = "completed"
