"""The HTTP surface: kagent v0.10.2's controller layout (research R2 section 1) for any
agent that has a key, plus the test endpoints.

* ``POST /api/a2a/{namespace}/{name}/`` (with or without the trailing slash): A2A
  JSON-RPC. ``A2A-Version`` missing or ``0.3``: the 0.3 methods (``message/send``,
  ``message/stream``, ``tasks/get``, ``tasks/cancel``, ...); ``1.0``: the 1.0 methods
  (``SendMessage``, ``SendStreamingMessage``, ``GetTask``, ``CancelTask``, ...); any
  other value: 400, as kagent answers.
* ``POST /agents/{namespace}/{name}``: kagent 1.0's layout (pre-release), ``A2A-Version:
  1.0`` required (else 400).
* ``GET <either>/.well-known/agent-card.json``: a kagent-like card (name with ``_``,
  JSON-RPC interfaces for 0.3 and 1.0 plus the 0.3 ``url`` fields, streaming on, push
  notifications off, one skill per purpose).
* ``GET /_fake/observations[/{run_id}]``, ``DELETE /_fake/observations``: what the
  agent saw (``observations.py``); ``GET /healthz``.

An agent is served only while it has a key (``FAKE_AGENT_KEYS`` or a file in
``FAKE_AGENT_KEYS_DIR``); others get 404, like an Agent that doesn't exist.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.server.routes.jsonrpc_dispatcher import JsonRpcDispatcher
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fake_agent.agent import FakeAgentExecutor
from fake_agent.config import LABEL, Settings
from fake_agent.observations import Observations

log = logging.getLogger("fake_agent")

V0_10 = "kagent_v0_10"
V1_0 = "kagent_v1_0"
BYO = "byo"
"""A ``type: BYO`` Agent's own pod: one agent at ``/`` (the controller proxies to it)."""
_VERSION = re.compile(r"(\d+)\.(\d+)(\.\d+)?")
_A2A_ERRORS_0_3 = {
    "Task not found": -32001,
    "Task cannot be canceled": -32002,
    "Push Notification is not supported": -32003,
    "This operation is not supported": -32004,
    "Incompatible content types": -32005,
    "Invalid agent response": -32006,
}
"""a2a-sdk 1.2.1's v0.3 adapter answers every A2A error as -32603 with the error's
message; A2A 0.3 servers (a2a-sdk 0.3.x in kagent-adk, a2a-go in kagent's controller)
answer these codes. Any other -32603 (an agent that can't cancel) stays as it is."""


DROPPED_AFTER = 2
"""``-drops``: the stream ends after this many events (the task and its first update)."""


async def _first(events: AsyncIterable[Any], count: int) -> AsyncIterator[Any]:
    """The first ``count`` items, then the end of the stream (the task carries on)."""
    iterator = aiter(events)
    try:
        for _ in range(count):
            yield await anext(iterator)
    except StopAsyncIteration:
        return
    finally:
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            await aclose()


def _with_0_3_error_codes(response: Response) -> Response:
    if not isinstance(response, JSONResponse):
        return response  # a stream
    try:
        body = json.loads(bytes(response.body))
    except ValueError:
        return response
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("code") == -32603:
        code = _A2A_ERRORS_0_3.get(str(error.get("message")))
        if code is not None:
            error["code"] = code
            return JSONResponse(body, status_code=response.status_code)
    return response


@dataclass
class _Agent:
    executor: FakeAgentExecutor
    handler: DefaultRequestHandler
    dispatcher: JsonRpcDispatcher


def _a2a_path(layout: str, namespace: str, name: str) -> str:
    if layout == V0_10:
        return f"/api/a2a/{namespace}/{name}/"
    if layout == BYO:
        return "/"
    return f"/agents/{namespace}/{name}"


def agent_card(base_url: str, namespace: str, name: str, layout: str) -> AgentCard:
    """What kagent's controller serves for an agent (research R2: name with ``_``,
    ``supportedInterfaces`` for 0.3 and 1.0, the 0.3 ``url`` / ``protocolVersion`` /
    ``preferredTransport`` fields added by the SDK)."""
    url = base_url.rstrip("/") + _a2a_path(layout, namespace, name)
    versions = ("1.0", "0.3") if layout == V1_0 else ("0.3", "1.0")
    return AgentCard(
        name=name.replace("-", "_"),
        description=(
            f"Soundings' fake agent {namespace}/{name}: deterministic, calls Soundings' MCP "
            "tools with its own key. Not kagent."
        ),
        version="0.10.2-fake",
        supported_interfaces=[
            AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version=version)
            for version in versions
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id="evaluate-idea",
                name="Evaluate idea",
                description="Scores a Soundings idea against its rubric, with sources.",
                tags=["soundings"],
            ),
            AgentSkill(
                id="research-idea",
                name="Research idea",
                description="Writes a cited research note on a Soundings idea.",
                tags=["soundings"],
            ),
            AgentSkill(
                id="draft-section",
                name="Draft proposal section",
                description="Suggests text for one section of a Soundings proposal.",
                tags=["soundings"],
            ),
        ],
    )


def _version_ok(layout: str, header: str | None) -> bool:
    if header is None or header.strip() == "":
        return layout != V1_0
    match = _VERSION.fullmatch(header.strip())
    if match is None:
        return False
    major_minor = f"{match.group(1)}.{match.group(2)}"
    return major_minor == "1.0" if layout == V1_0 else major_minor in ("0.3", "1.0")


def _authorization_kind(header: str | None) -> str:
    if header is None:
        return "none"
    return "bearer" if header.lower().startswith("bearer ") else "other"


def _run_id_of(params: dict[str, Any]) -> str | None:
    message = params.get("message")
    if not isinstance(message, dict):
        return None
    metadata = message.get("metadata")
    soundings = metadata.get("soundings") if isinstance(metadata, dict) else None
    run_id = soundings.get("run_id") if isinstance(soundings, dict) else None
    return run_id if isinstance(run_id, str) else None


def create_app(settings: Settings | None = None) -> Starlette:
    settings = settings or Settings.from_env()
    observations = Observations(settings.max_observations)
    agents: dict[tuple[str, str], _Agent] = {}

    def served(namespace: str, name: str) -> bool:
        return bool(
            LABEL.fullmatch(namespace)
            and LABEL.fullmatch(name)
            and settings.key_for(namespace, name) is not None
        )

    def agent_for(namespace: str, name: str, base_url: str) -> _Agent:
        agent = agents.get((namespace, name))
        if agent is None:
            executor = FakeAgentExecutor(
                namespace=namespace, name=name, settings=settings, observations=observations
            )
            handler = DefaultRequestHandler(
                agent_executor=executor,
                task_store=InMemoryTaskStore(),
                agent_card=agent_card(base_url, namespace, name, V0_10),
            )
            dispatcher = JsonRpcDispatcher(request_handler=handler, enable_v0_3_compat=True)
            agent = _Agent(executor=executor, handler=handler, dispatcher=dispatcher)
            agents[(namespace, name)] = agent
        return agent

    def refused(request: Request, layout: str) -> Response | None:
        namespace = request.path_params["namespace"]
        name = request.path_params["name"]
        if settings.required_token is not None:
            expected = f"Bearer {settings.required_token}"
            if request.headers.get("authorization") != expected:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not served(namespace, name):
            return JSONResponse({"error": "agent not found"}, status_code=404)
        if settings.behaviour_for(namespace, name) == "unavailable":
            return JSONResponse({"error": "agent unavailable"}, status_code=503)
        if not _version_ok(layout, request.headers.get("a2a-version")):
            return JSONResponse({"error": "unsupported A2A-Version"}, status_code=400)
        return None

    async def a2a(request: Request, layout: str) -> Response:
        problem = refused(request, layout)
        if problem is not None:
            return problem
        namespace = request.path_params["namespace"]
        name = request.path_params["name"]
        raw = await request.body()  # cached: the dispatcher reads the same body
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        method = body.get("method") if isinstance(body, dict) else None
        params = body.get("params") if isinstance(body, dict) else None
        params = params if isinstance(params, dict) else {}
        run_id = _run_id_of(params)
        if run_id is None and isinstance(params.get("id"), str):
            run_id = observations.run_for_task(params["id"])
        sent = params.get("message")
        message: dict[str, Any] = sent if isinstance(sent, dict) else {}
        configuration = params.get("configuration")
        observations.a2a_request(
            run_id,
            {
                "agent": f"{namespace}/{name}",
                "layout": layout,
                "method": method if isinstance(method, str) else None,
                "a2a_version": request.headers.get("a2a-version"),
                "x_user_id": request.headers.get("x-user-id"),
                "authorization": _authorization_kind(request.headers.get("authorization")),
                "cookie": "cookie" in request.headers,
                "accept": request.headers.get("accept"),
                "history_length": params.get("historyLength"),
                "task_id": params.get("id") if isinstance(params.get("id"), str) else None,
                "message_id": message.get("messageId"),
                "context_id_sent": "contextId" in message,
                "configuration": sorted(configuration) if isinstance(configuration, dict) else None,
            },
        )
        agent = agent_for(namespace, name, str(request.base_url))
        response = await agent.dispatcher.handle_requests(request)
        if (
            method in ("message/stream", "SendStreamingMessage")
            and settings.behaviour_for(namespace, name) == "drops"
            and isinstance(response, EventSourceResponse)
        ):
            response.body_iterator = _first(response.body_iterator, DROPPED_AFTER)
        if isinstance(method, str) and "/" in method:  # a 0.3 method name
            return _with_0_3_error_codes(response)
        return response

    async def a2a_v0_10(request: Request) -> Response:
        return await a2a(request, V0_10)

    async def a2a_v1_0(request: Request) -> Response:
        return await a2a(request, V1_0)

    async def card(request: Request, layout: str) -> Response:
        namespace = request.path_params["namespace"]
        name = request.path_params["name"]
        if (
            settings.required_token is not None
            and request.headers.get("authorization") != f"Bearer {settings.required_token}"
        ):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not served(namespace, name):
            return JSONResponse({"error": "agent not found"}, status_code=404)
        if settings.behaviour_for(namespace, name) == "unavailable":
            return JSONResponse({"error": "agent unavailable"}, status_code=503)
        base = str(request.base_url)
        return JSONResponse(agent_card_to_dict(agent_card(base, namespace, name, layout)))

    async def card_v0_10(request: Request) -> Response:
        return await card(request, V0_10)

    async def card_v1_0(request: Request) -> Response:
        return await card(request, V1_0)

    async def list_observations(request: Request) -> Response:
        if request.method == "DELETE":
            observations.clear()
            return Response(status_code=204)
        run_id = request.query_params.get("run_id")
        runs = observations.all()
        if run_id:
            runs = [run for run in runs if run["run_id"] == run_id]
        return JSONResponse({"runs": runs})

    async def get_observation(request: Request) -> Response:
        run = observations.get(request.path_params["run_id"])
        if run is None:
            return JSONResponse({"error": "no such run"}, status_code=404)
        return JSONResponse(run)

    async def healthz(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        yield
        for agent in agents.values():
            await agent.handler.aclose()

    def as_byo(handler: Any, layout: str, agent: tuple[str, str]) -> Any:
        namespace, name = agent

        async def endpoint(request: Request) -> Response:
            request.scope["path_params"] = {"namespace": namespace, "name": name}
            return await handler(request, layout)  # type: ignore[no-any-return]

        return endpoint

    card_path = ".well-known/agent-card.json"
    byo_routes = []
    if settings.byo is not None:
        byo_routes = [
            Route(f"/{card_path}", as_byo(card, BYO, settings.byo)),
            Route("/", as_byo(a2a, BYO, settings.byo), methods=["POST"]),
        ]
    routes = [
        *byo_routes,
        Route("/healthz", healthz),
        Route("/_fake/observations", list_observations, methods=["GET", "DELETE"]),
        Route("/_fake/observations/{run_id}", get_observation),
        Route(f"/api/a2a/{{namespace}}/{{name}}/{card_path}", card_v0_10),
        Route("/api/a2a/{namespace}/{name}/", a2a_v0_10, methods=["POST"]),
        Route("/api/a2a/{namespace}/{name}", a2a_v0_10, methods=["POST"]),
        Route(f"/agents/{{namespace}}/{{name}}/{card_path}", card_v1_0),
        Route("/agents/{namespace}/{name}", a2a_v1_0, methods=["POST"]),
        Route("/agents/{namespace}/{name}/", a2a_v1_0, methods=["POST"]),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    # Exact paths only: a client must never be redirected (Soundings refuses redirects).
    app.router.redirect_slashes = False
    app.state.observations = observations
    app.state.settings = settings
    return app
