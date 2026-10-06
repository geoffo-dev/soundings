"""A small A2A JSON-RPC client for kagent's controller (contract-phase6 sections 3.2 and
3.4).

Hand-written on httpx (no a2a-sdk: its client discovers the transport from the agent
card, which must never decide where Soundings sends requests; research R2 section 2) and
speaking both layouts a registered agent may use:

* ``kagent_v0_10``: A2A 0.3 at ``{kagent}/api/a2a/{namespace}/{name}/`` (kagent 0.10.x
  and its Python runtime, kagent-adk, which speaks 0.3 only): ``message/stream``,
  ``tasks/get``, ``tasks/cancel``; ``A2A-Version: 0.3``.
* ``kagent_v1_0``: A2A 1.0 at ``{kagent}/agents/{namespace}/{name}``:
  ``SendStreamingMessage``, ``GetTask``, ``CancelTask``; ``A2A-Version: 1.0``.

**SSRF.** The only URLs requested are :func:`app.schemas.ai.agent_a2a_url` and
:func:`~app.schemas.ai.agent_card_url` (the configured controller origin, a fixed path,
two DNS labels). A 3xx is an :class:`A2AProtocolError`, never followed. The httpx client
ignores the environment (``trust_env=False``: no ``HTTP(S)_PROXY``, ``NO_PROXY`` or
``.netrc``, so the controller token never goes through a proxy), keeps no cookies and
verifies TLS with ``SSL_CERT_FILE`` when set (else the system bundle). Bodies are capped:
the card at 64 KiB, a JSON-RPC response at 1 MiB, one SSE event at 1 MiB.

**Agent text is never kept.** Status messages and artifacts are reduced to what the run
needs (ids, the task state, ``final``); errors carry Soundings' code, an HTTP status or
a JSON-RPC error number, never a body. Logs are the caller's: run id, agent id, status,
exception class.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from itertools import count
from typing import Any, Final, Literal
from urllib.request import Request

import httpx

from app.config import Settings
from app.models.enums import AiAgentProtocol, AiRunError
from app.schemas.ai import (
    A2A_HISTORY_LENGTH,
    A2A_ID_MAX_LENGTH,
    A2A_VERSION,
    AI_CARD_MAX_BYTES,
    AI_CARD_TIMEOUT,
    AI_RUN_CANCEL_TIMEOUT,
    AI_RUN_STREAM_IDLE,
    KAGENT_USER_ID,
    AiRunMessage,
    agent_a2a_url,
    agent_card_url,
)

__all__ = [
    "CONNECT_TIMEOUT",
    "INTERRUPTED_STATES",
    "JSON_RPC_MAX_BYTES",
    "SSE_EVENT_MAX_BYTES",
    "TERMINAL_STATES",
    "A2AClient",
    "A2AError",
    "A2AProtocolError",
    "A2AUnreachable",
    "StreamInterrupted",
    "TaskEvent",
    "http_client",
    "ssl_context",
]

CONNECT_TIMEOUT: Final = 10.0
"""Seconds to connect to the controller (and to write a request)."""
JSON_RPC_MAX_BYTES: Final = 1024 * 1024
SSE_EVENT_MAX_BYTES: Final = 1024 * 1024
RETRYABLE_STATUSES: Final = frozenset({502, 503, 504})
"""Gateway answers worth one more try while no task exists (contract section 3.4)."""

TERMINAL_STATES: Final = frozenset({"completed", "failed", "canceled", "rejected"})
INTERRUPTED_STATES: Final = frozenset({"input-required", "auth-required"})
_KNOWN_STATES: Final = frozenset(
    {"submitted", "working", "unknown"} | TERMINAL_STATES | INTERRUPTED_STATES
)
_V1_STATES: Final = {
    "TASK_STATE_SUBMITTED": "submitted",
    "TASK_STATE_WORKING": "working",
    "TASK_STATE_INPUT_REQUIRED": "input-required",
    "TASK_STATE_AUTH_REQUIRED": "auth-required",
    "TASK_STATE_COMPLETED": "completed",
    "TASK_STATE_CANCELED": "canceled",
    "TASK_STATE_FAILED": "failed",
    "TASK_STATE_REJECTED": "rejected",
    "TASK_STATE_UNSPECIFIED": "unknown",
}
"""A2A 1.0 state names as their 0.3 equivalents (the runner speaks 0.3 names)."""

_METHODS: Final[dict[AiAgentProtocol, dict[str, str]]] = {
    AiAgentProtocol.KAGENT_V0_10: {
        "stream": "message/stream",
        "get": "tasks/get",
        "cancel": "tasks/cancel",
    },
    AiAgentProtocol.KAGENT_V1_0: {
        "stream": "SendStreamingMessage",
        "get": "GetTask",
        "cancel": "CancelTask",
    },
}


# --- Errors --------------------------------------------------------------------------------
class A2AError(Exception):
    """A failed exchange with the controller: Soundings' error code, the HTTP status
    when one came back, and whether sending again (before a task exists) may help.
    ``str()`` is Soundings' own words: never a response body."""

    code: AiRunError = AiRunError.AGENT_PROTOCOL_ERROR

    def __init__(
        self, reason: str, *, http_status: int | None = None, retryable: bool = False
    ) -> None:
        super().__init__(reason)
        self.http_status = http_status
        self.retryable = retryable


class A2AUnreachable(A2AError):
    """No connection, or the controller answered 4xx/5xx (an unknown agent is 404)."""

    code = AiRunError.AGENT_UNREACHABLE


class A2AProtocolError(A2AError):
    """Not the A2A we speak: a redirect, a JSON-RPC error, malformed or oversized JSON,
    an unexpected content type, an unknown result, an over-long id."""

    code = AiRunError.AGENT_PROTOCOL_ERROR


class StreamInterrupted(Exception):
    """The stream ended without a terminal state, was cut off, or stayed silent for
    :data:`~app.schemas.ai.AI_RUN_STREAM_IDLE`: poll ``tasks/get`` if a task exists."""


# --- Events --------------------------------------------------------------------------------
TaskEventKind = Literal["task", "status", "artifact", "message"]


@dataclass(frozen=True, slots=True)
class TaskEvent:
    """What the runner keeps of one A2A result: the task and context ids, the task state
    (an A2A 0.3 name; ``raw_state`` as sent, for an unknown one) and 0.3's ``final``."""

    kind: TaskEventKind
    task_id: str | None = None
    context_id: str | None = None
    state: str | None = None
    raw_state: str | None = None
    final: bool = False

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES


# --- The HTTP client --------------------------------------------------------------------
class _NoCookies(http.cookiejar.DefaultCookiePolicy):
    """Never store or send a cookie: the controller gets the same request every time."""

    def set_ok(self, cookie: http.cookiejar.Cookie, request: Request) -> bool:
        return False

    def return_ok(self, cookie: http.cookiejar.Cookie, request: Request) -> bool:
        return False


def ssl_context() -> ssl.SSLContext:
    """TLS verification for the controller: ``SSL_CERT_FILE`` when set (this sandbox's
    proxy CA, an operator's private CA), else the system's bundle."""
    cafile = os.environ.get("SSL_CERT_FILE") or None
    return ssl.create_default_context(cafile=cafile)


def http_client(
    *, transport: httpx.AsyncBaseTransport | None = None, read_timeout: float
) -> httpx.AsyncClient:
    """The one way Soundings builds an HTTP client for A2A: no redirects, nothing from the
    environment, no cookies, explicit TLS. ``transport`` replaces the network in tests."""
    return httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,
        trust_env=False,
        verify=ssl_context() if transport is None else True,
        cookies=http.cookiejar.CookieJar(policy=_NoCookies()),
        timeout=httpx.Timeout(
            connect=CONNECT_TIMEOUT, read=read_timeout, write=CONNECT_TIMEOUT, pool=CONNECT_TIMEOUT
        ),
    )


async def _read_capped(response: httpx.Response, limit: int) -> bytes:
    """The body, refusing more than ``limit`` bytes (whatever ``Content-Length`` says)."""
    declared = response.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise A2AProtocolError("response too large", http_status=response.status_code)
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > limit:
            raise A2AProtocolError("response too large", http_status=response.status_code)
    return bytes(body)


async def _sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """The ``data`` of each server-sent event (multi-line data joined with ``\\n``);
    comments and other fields are skipped. One event (or one unfinished line) over
    :data:`SSE_EVENT_MAX_BYTES` is an :class:`A2AProtocolError`."""
    buffer = bytearray()
    parts: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        buffer += chunk
        while True:
            end = buffer.find(b"\n")
            if end < 0:
                if len(buffer) > SSE_EVENT_MAX_BYTES:
                    raise A2AProtocolError("stream event too large")
                break
            line = bytes(buffer[:end]).rstrip(b"\r")
            del buffer[: end + 1]
            if not line:
                if parts:
                    try:
                        yield b"\n".join(parts).decode("utf-8")
                    except UnicodeDecodeError as error:
                        raise A2AProtocolError("stream event is not UTF-8") from error
                    parts, size = [], 0
                continue
            if line.startswith(b":"):
                continue  # a comment (keep-alive)
            field, _, value = line.partition(b":")
            if field != b"data":
                continue  # event, id, retry: not used
            value = value.removeprefix(b" ")
            size += len(value) + 1
            if size > SSE_EVENT_MAX_BYTES:
                raise A2AProtocolError("stream event too large")
            parts.append(value)


# --- Parsing ---------------------------------------------------------------------------------
def _identifier(value: object, what: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise A2AProtocolError(f"{what} is not a string")
    if len(value) > A2A_ID_MAX_LENGTH:
        raise A2AProtocolError(f"{what} is longer than {A2A_ID_MAX_LENGTH} characters")
    return value


def _state(status: object) -> tuple[str | None, str | None]:
    """``(0.3 state name or None for an unknown one, the raw value)``."""
    if status is None:
        return None, None
    if not isinstance(status, dict):
        raise A2AProtocolError("task status is not an object")
    raw = status.get("state")
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        raise A2AProtocolError("task state is not a string")
    state = _V1_STATES.get(raw, raw)
    return (state if state in _KNOWN_STATES else None), raw[:64]


def _task(data: dict[str, Any], kind: TaskEventKind, *, final: bool = False) -> TaskEvent:
    task_id = data.get("id") if kind == "task" else data.get("taskId")
    state, raw = _state(data.get("status"))
    return TaskEvent(
        kind=kind,
        task_id=_identifier(task_id, "task id"),
        context_id=_identifier(data.get("contextId"), "context id"),
        state=state,
        raw_state=raw,
        final=final or (state in TERMINAL_STATES),
    )


def parse_result_v03(result: object) -> TaskEvent:
    """One A2A 0.3 result (``kind`` task, status-update, artifact-update or message)."""
    if not isinstance(result, dict):
        raise A2AProtocolError("result is not an object")
    match result.get("kind"):
        case "task":
            return _task(result, "task")
        case "status-update":
            return _task(result, "status", final=result.get("final") is True)
        case "artifact-update":
            return TaskEvent(
                kind="artifact",
                task_id=_identifier(result.get("taskId"), "task id"),
                context_id=_identifier(result.get("contextId"), "context id"),
            )
        case "message":
            return TaskEvent(
                kind="message",
                task_id=_identifier(result.get("taskId"), "task id"),
                context_id=_identifier(result.get("contextId"), "context id"),
            )
    raise A2AProtocolError("unknown result kind")


def parse_result_v10(result: object) -> TaskEvent:
    """One A2A 1.0 result: ``{"task"|"statusUpdate"|"artifactUpdate"|"message": ...}``,
    or a bare task (``GetTask`` / ``CancelTask``)."""
    if not isinstance(result, dict):
        raise A2AProtocolError("result is not an object")
    for key, kind in (
        ("task", "task"),
        ("statusUpdate", "status"),
        ("artifactUpdate", "artifact"),
        ("message", "message"),
    ):
        inner = result.get(key)
        if isinstance(inner, dict):
            if kind == "task":
                return _task(inner, "task")
            if kind == "status":
                return _task(inner, "status")
            return TaskEvent(
                kind=kind,  # type: ignore[arg-type]
                task_id=_identifier(inner.get("taskId"), "task id"),
                context_id=_identifier(inner.get("contextId"), "context id"),
            )
    if "id" in result and "status" in result:
        return _task(result, "task")
    raise A2AProtocolError("unknown result")


def _rpc_result(payload: object) -> object:
    """The ``result`` of a JSON-RPC response; an ``error`` (or anything else) is an
    :class:`A2AProtocolError` naming only the numeric code."""
    if not isinstance(payload, dict):
        raise A2AProtocolError("not a JSON-RPC response")
    error = payload.get("error")
    if error is not None:
        code = error.get("code") if isinstance(error, dict) else None
        number = code if isinstance(code, int) and not isinstance(code, bool) else None
        raise A2AProtocolError(f"JSON-RPC error {number}")
    if "result" not in payload:
        raise A2AProtocolError("not a JSON-RPC response")
    return payload["result"]


def _json(body: bytes | str) -> object:
    try:
        return json.loads(body)
    except (ValueError, RecursionError) as error:
        raise A2AProtocolError("malformed JSON") from error


def _check_status(response: httpx.Response) -> None:
    status = response.status_code
    if 300 <= status < 400:
        raise A2AProtocolError("redirect refused", http_status=status)
    if status >= 400:
        raise A2AUnreachable(
            "agent answered an error", http_status=status, retryable=status in RETRYABLE_STATUSES
        )


# --- The client ---------------------------------------------------------------------------
class A2AClient:
    """One registered agent's A2A endpoint. Create one per run (or test connection)."""

    def __init__(
        self,
        settings: Settings,
        protocol: AiAgentProtocol,
        namespace: str,
        name: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        request_prefix: str = "soundings",
    ) -> None:
        self.protocol = protocol
        self.url = agent_a2a_url(settings.kagent_url, protocol, namespace, name)
        self.card_url = agent_card_url(settings.kagent_url, protocol, namespace, name)
        token = settings.kagent_token.get_secret_value() if settings.kagent_token else None
        self._token = token
        self._transport = transport
        self._prefix = request_prefix
        self._ids = count(1)
        self._parse = (
            parse_result_v10 if protocol is AiAgentProtocol.KAGENT_V1_0 else parse_result_v03
        )

    def headers(self, accept: str) -> dict[str, str]:
        """Exactly these, on every request (contract section 3.4)."""
        found = {
            "Content-Type": "application/json",
            "Accept": accept,
            "A2A-Version": A2A_VERSION[self.protocol],
            "X-User-Id": KAGENT_USER_ID,
        }
        if self._token:
            found["Authorization"] = f"Bearer {self._token}"
        return found

    def _request(self, method: str, params: dict[str, Any]) -> bytes:
        body = {
            "jsonrpc": "2.0",
            "id": f"{self._prefix}-{next(self._ids)}",
            "method": _METHODS[self.protocol][method],
            "params": params,
        }
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def message_params(self, message: AiRunMessage, message_id: str) -> dict[str, Any]:
        """The run's one message: no ``contextId`` (a fresh kagent session), no
        ``blocking`` / ``returnImmediately`` (streams don't block)."""
        configuration = {"acceptedOutputModes": ["text/plain"]}
        if self.protocol is AiAgentProtocol.KAGENT_V1_0:
            return {
                "message": {
                    "messageId": message_id,
                    "role": "ROLE_USER",
                    "parts": [{"text": message.text}],
                    "metadata": message.metadata,
                },
                "configuration": configuration,
            }
        return {
            "message": {
                "kind": "message",
                "messageId": message_id,
                "role": "user",
                "parts": [{"kind": "text", "text": message.text}],
                "metadata": message.metadata,
            },
            "configuration": configuration,
        }

    @asynccontextmanager
    async def stream(
        self, message: AiRunMessage, message_id: str
    ) -> AsyncIterator[AsyncIterator[TaskEvent]]:
        """``message/stream`` (``SendStreamingMessage``): the task's events as they come.

        Raises :class:`A2AUnreachable` (``retryable`` for connection failures and 502-504)
        or :class:`A2AProtocolError` before the first event, and inside the iteration
        :class:`StreamInterrupted` when the stream is cut off or silent for
        :data:`~app.schemas.ai.AI_RUN_STREAM_IDLE` (``ReadTimeout``)."""
        content = self._request("stream", self.message_params(message, message_id))
        async with http_client(
            transport=self._transport, read_timeout=AI_RUN_STREAM_IDLE.total_seconds()
        ) as http:
            try:
                request = http.build_request(
                    "POST", self.url, content=content, headers=self.headers("text/event-stream")
                )
                response = await http.send(request, stream=True)
            except httpx.TimeoutException as error:
                raise A2AUnreachable("timed out", retryable=True) from error
            except httpx.TransportError as error:
                raise A2AUnreachable("connection failed", retryable=True) from error
            try:
                _check_status(response)
                yield self._events(response)
            finally:
                await response.aclose()

    async def _events(self, response: httpx.Response) -> AsyncIterator[TaskEvent]:
        media = response.headers.get("content-type", "").split(";")[0].strip().lower()
        try:
            if media == "application/json":
                # A server that answers a stream request with one JSON-RPC response (an
                # error, typically: an agent that can't stream).
                payload = _json(await _read_capped(response, JSON_RPC_MAX_BYTES))
                yield self._parse(_rpc_result(payload))
                return
            if media != "text/event-stream":
                raise A2AProtocolError("unexpected content type", http_status=response.status_code)
            async for data in _sse_data(response):
                yield self._parse(_rpc_result(_json(data)))
        except httpx.TimeoutException as error:
            raise StreamInterrupted("stream silent") from error
        except httpx.TransportError as error:
            raise StreamInterrupted("stream cut off") from error

    async def _call(self, method: str, params: dict[str, Any], *, read_seconds: float) -> object:
        """One JSON-RPC request and its ``result``."""
        content = self._request(method, params)
        async with http_client(transport=self._transport, read_timeout=read_seconds) as http:
            try:
                request = http.build_request(
                    "POST", self.url, content=content, headers=self.headers("application/json")
                )
                response = await http.send(request, stream=True)
            except httpx.TimeoutException as error:
                raise A2AUnreachable("timed out", retryable=True) from error
            except httpx.TransportError as error:
                raise A2AUnreachable("connection failed", retryable=True) from error
            try:
                _check_status(response)
                try:
                    body = await _read_capped(response, JSON_RPC_MAX_BYTES)
                except httpx.TimeoutException as error:
                    raise A2AUnreachable("timed out", retryable=True) from error
                except httpx.TransportError as error:
                    raise A2AUnreachable("connection failed", retryable=True) from error
            finally:
                await response.aclose()
        return _rpc_result(_json(body))

    async def get_task(self, task_id: str) -> TaskEvent:
        """``tasks/get`` (``GetTask``) with ``historyLength: 1``: kagent's tasks carry their
        whole tool-call history, and a2a-sdk 0.3 reads 0 as "all of it"."""
        result = await self._call(
            "get",
            {"id": task_id, "historyLength": A2A_HISTORY_LENGTH},
            read_seconds=CONNECT_TIMEOUT,
        )
        event = self._parse(result)
        if event.kind != "task":
            raise A2AProtocolError("tasks/get did not return a task")
        return event

    async def cancel_task(self, task_id: str) -> bool:
        """``tasks/cancel`` (``CancelTask``), best effort: any answer is fine (kagent-adk
        0.10.2 can't cancel and answers -32603). ``True`` when the controller answered at
        all within :data:`~app.schemas.ai.AI_RUN_CANCEL_TIMEOUT`."""
        try:
            await self._call(
                "cancel", {"id": task_id}, read_seconds=AI_RUN_CANCEL_TIMEOUT.total_seconds()
            )
        except A2AProtocolError:
            return True  # an answer, just not a task
        except A2AUnreachable as error:
            return error.http_status is not None
        return True

    async def fetch_card(self) -> tuple[int, object]:
        """``GET`` the card URL (5 seconds, at most 64 KiB, no redirects): ``(status,
        JSON)``. Raises :class:`A2AUnreachable` / :class:`A2AProtocolError`."""
        seconds = AI_CARD_TIMEOUT.total_seconds()
        headers = self.headers("application/json")
        headers.pop("Content-Type")
        async with http_client(transport=self._transport, read_timeout=seconds) as http:
            try:
                response = await http.send(
                    http.build_request("GET", self.card_url, headers=headers), stream=True
                )
            except httpx.TransportError as error:
                raise A2AUnreachable("connection failed") from error
            try:
                _check_status(response)
                try:
                    body = await _read_capped(response, AI_CARD_MAX_BYTES)
                except httpx.TransportError as error:
                    raise A2AUnreachable("connection failed") from error
            finally:
                await response.aclose()
        return response.status_code, _json(body)
