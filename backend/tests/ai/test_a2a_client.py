"""The A2A client (contract-phase6 sections 3.2 and 3.4): SSRF, headers, wire shapes for
A2A 0.3 and 1.0, caps, errors. No database: a mock transport stands in for kagent."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.ai.a2a import (
    A2AClient,
    A2AProtocolError,
    A2AUnreachable,
    StreamInterrupted,
    TaskEvent,
    http_client,
    parse_result_v03,
    parse_result_v10,
)
from app.ai.agents import card_summary
from app.models.enums import AiAgentProtocol, AiRunKind
from app.schemas.ai import run_message
from tests.ai.fake_kagent import FakeKagent
from tests.conftest import make_settings

KAGENT = "http://kagent-controller.kagent:8083"
V03, V10 = AiAgentProtocol.KAGENT_V0_10, AiAgentProtocol.KAGENT_V1_0


def _settings(**overrides: Any) -> Any:
    return make_settings(kagent_url=KAGENT, **overrides)


def _message() -> Any:
    return run_message(
        AiRunKind.RESEARCH, run_id=uuid4(), idea_key="CUST-12", agent_name="Researcher"
    )


async def _events(client: A2AClient) -> list[TaskEvent]:
    found = []
    async with client.stream(_message(), "run-1") as events:
        async for event in events:
            found.append(event)
    return found


# --- URLs and headers ------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("protocol", "url", "version"),
    [
        (V03, f"{KAGENT}/api/a2a/soundings/researcher-silent/", "0.3"),
        (V10, f"{KAGENT}/agents/soundings/researcher-silent", "1.0"),
    ],
)
async def test_only_the_built_url_is_requested_with_exactly_these_headers(
    protocol: AiAgentProtocol, url: str, version: str
) -> None:
    kagent = FakeKagent()
    client = A2AClient(
        _settings(kagent_token="controller-token"),
        protocol,
        "soundings",
        "researcher-silent",
        transport=kagent.transport,
    )

    events = await _events(client)
    task_id = events[0].task_id
    assert task_id is not None
    await client.get_task(task_id)
    await client.cancel_task(task_id)
    await client.fetch_card()

    assert kagent.urls == {url, url.rstrip("/") + "/.well-known/agent-card.json"}
    stream, get, cancel, card = kagent.requests
    assert stream.method == get.method == cancel.method == "POST"
    for recorded in (stream, get, cancel):
        assert recorded.headers["a2a-version"] == version
        assert recorded.headers["x-user-id"] == "soundings"
        assert recorded.headers["authorization"] == "Bearer controller-token"
        assert recorded.headers["content-type"] == "application/json"
        assert "cookie" not in recorded.headers
    assert stream.headers["accept"] == "text/event-stream"
    assert get.headers["accept"] == "application/json"
    assert card.method == "GET"
    assert card.headers["a2a-version"] == version
    # The card's own URLs (evil.example) never decide anything.
    assert not [r for r in kagent.requests if "evil.example" in r.url]


async def test_no_token_no_authorization_header() -> None:
    kagent = FakeKagent()
    client = A2AClient(_settings(), V03, "soundings", "a-silent", transport=kagent.transport)

    await _events(client)

    assert "authorization" not in kagent.requests[0].headers


async def test_the_message_is_sent_as_a2a_03_and_10() -> None:
    for protocol, method in ((V03, "message/stream"), (V10, "SendStreamingMessage")):
        kagent = FakeKagent()
        client = A2AClient(
            _settings(), protocol, "soundings", "x-silent", transport=kagent.transport
        )
        message = _message()
        async with client.stream(message, "the-run-id") as events:
            async for _ in events:
                pass
        body = kagent.requests[0].body
        assert body["jsonrpc"] == "2.0"
        assert body["method"] == method
        params = body["params"]
        assert params["configuration"] == {"acceptedOutputModes": ["text/plain"]}
        sent = params["message"]
        assert sent["messageId"] == "the-run-id"
        assert "contextId" not in sent
        assert sent["metadata"] == message.metadata
        if protocol is V03:
            assert (sent["kind"], sent["role"]) == ("message", "user")
            assert sent["parts"] == [{"kind": "text", "text": message.text}]
        else:
            assert sent["role"] == "ROLE_USER"
            assert sent["parts"] == [{"text": message.text}]
        for forbidden in ("blocking", "returnImmediately", "historyLength"):
            assert forbidden not in json.dumps(params["configuration"])


async def test_polling_asks_for_one_history_entry() -> None:
    kagent = FakeKagent()
    client = A2AClient(_settings(), V10, "soundings", "x-silent", transport=kagent.transport)
    task_id = (await _events(client))[0].task_id
    assert task_id is not None

    task = await client.get_task(task_id)

    assert kagent.calls("GetTask")[0].body["params"] == {"id": task_id, "historyLength": 1}
    assert task.state == "completed"


# --- Streams: states and shapes -------------------------------------------------------------
@pytest.mark.parametrize("protocol", [V03, V10])
async def test_stream_events_carry_ids_and_states_only(protocol: AiAgentProtocol) -> None:
    kagent = FakeKagent()
    client = A2AClient(_settings(), protocol, "soundings", "x-fails", transport=kagent.transport)

    events = await _events(client)

    assert [event.state for event in events] == ["submitted", "working", "failed"]
    assert events[0].task_id == events[-1].task_id
    assert events[-1].final
    assert all("SECRET" not in repr(event) for event in events)


def test_a2a_10_states_read_as_03_names() -> None:
    event = parse_result_v10(
        {"statusUpdate": {"taskId": "t", "status": {"state": "TASK_STATE_INPUT_REQUIRED"}}}
    )
    assert (event.kind, event.state, event.task_id) == ("status", "input-required", "t")
    unknown = parse_result_v03(
        {"kind": "status-update", "taskId": "t", "status": {"state": "dreaming"}}
    )
    assert unknown.state is None
    assert unknown.raw_state == "dreaming"


@pytest.mark.parametrize(
    "result",
    [
        {"kind": "task", "id": "x" * 201, "status": {"state": "working"}},
        {"kind": "task", "id": 7, "status": {"state": "working"}},
        {"kind": "status-update", "taskId": "t", "contextId": "c" * 201},
        {"kind": "task", "id": "t", "status": "working"},
        {"kind": "surprise"},
        ["not", "an", "object"],
    ],
)
def test_malformed_results_are_protocol_errors(result: Any) -> None:
    with pytest.raises(A2AProtocolError):
        parse_result_v03(result)


# --- SSRF and the HTTP client -----------------------------------------------------------------
async def test_a_redirect_is_never_followed() -> None:
    kagent = FakeKagent()
    client = A2AClient(_settings(), V03, "soundings", "x-redirect", transport=kagent.transport)

    with pytest.raises(A2AProtocolError) as stream_error:
        await _events(client)
    with pytest.raises(A2AProtocolError) as card_error:
        await client.fetch_card()

    assert stream_error.value.http_status == card_error.value.http_status == 302
    assert all("169.254" not in r.url for r in kagent.requests)
    assert len(kagent.requests) == 2


def test_the_client_ignores_proxies_and_netrc_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:3128")

    client = http_client(read_timeout=1)

    assert client._trust_env is False
    assert client._mounts == {}
    assert client.follow_redirects is False


async def test_a_proxy_in_the_environment_is_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real request (no mock transport) to a closed local port: with the proxy used it
    would fail differently (the proxy is unresolvable); without, it is refused."""
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    client = A2AClient(make_settings(kagent_url="http://127.0.0.1:9"), V03, "soundings", "agent")

    with pytest.raises(A2AUnreachable) as error:
        await client.fetch_card()

    assert isinstance(error.value.__cause__, httpx.ConnectError)
    assert "proxy.invalid" not in str(error.value.__cause__)


def _transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_oversized_card_response_and_stream_event_are_protocol_errors() -> None:
    big = "x" * (65 * 1024)

    def card(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": big})

    client = A2AClient(_settings(), V03, "soundings", "a", transport=_transport(card))
    with pytest.raises(A2AProtocolError):
        await client.fetch_card()

    def rpc(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b'{"jsonrpc":"2.0","result":"' + b"x" * (1024 * 1024 + 1) + b'"}'
        )

    client = A2AClient(_settings(), V03, "soundings", "a", transport=_transport(rpc))
    with pytest.raises(A2AProtocolError):
        await client.get_task("t")

    async def body() -> AsyncIterator[bytes]:
        yield b"data: " + b"x" * (512 * 1024) + b"\n"
        yield b"data: " + b"x" * (600 * 1024) + b"\n\n"

    def stream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())

    client = A2AClient(_settings(), V03, "soundings", "a", transport=_transport(stream))
    with pytest.raises(A2AProtocolError):
        await _events(client)


async def test_a_declared_oversized_body_is_refused_unread() -> None:
    def card(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": str(10**8)}, content=b"{}")

    client = A2AClient(_settings(), V03, "soundings", "a", transport=_transport(card))
    with pytest.raises(A2AProtocolError):
        await client.fetch_card()


@pytest.mark.parametrize(
    ("status", "retryable"), [(404, False), (500, False), (502, True), (503, True), (504, True)]
)
async def test_http_errors_are_unreachable_with_the_status(status: int, retryable: bool) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="<html>body never kept</html>")

    client = A2AClient(_settings(), V03, "soundings", "a", transport=_transport(answer))
    with pytest.raises(A2AUnreachable) as error:
        await _events(client)

    assert error.value.http_status == status
    assert error.value.retryable is retryable
    assert "never kept" not in str(error.value)


async def test_connection_failures_are_retryable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = A2AClient(_settings(), V03, "soundings", "a", transport=_transport(refuse))
    with pytest.raises(A2AUnreachable) as error:
        await _events(client)

    assert error.value.retryable is True
    assert error.value.http_status is None


async def test_a_json_rpc_error_is_a_protocol_error_naming_its_number_only() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32004, "message": "AGENT TEXT"}},
        )

    client = A2AClient(_settings(), V03, "soundings", "a", transport=_transport(answer))
    with pytest.raises(A2AProtocolError) as error:
        await _events(client)

    assert str(error.value) == "JSON-RPC error -32004"


async def test_an_unexpected_content_type_is_a_protocol_error() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html/>")

    client = A2AClient(_settings(), V03, "soundings", "a", transport=_transport(answer))
    with pytest.raises(A2AProtocolError):
        await _events(client)


async def test_a_cut_stream_is_interrupted_not_an_error() -> None:
    task = {"kind": "task", "id": "t", "status": {"state": "working"}}
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "result": task})

    async def body() -> AsyncIterator[bytes]:
        yield f"data: {line}\n\n".encode()
        raise httpx.ReadError("cut")

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())

    client = A2AClient(_settings(), V03, "soundings", "a", transport=_transport(answer))
    seen: list[TaskEvent] = []

    async def read() -> None:
        async with client.stream(_message(), "r") as events:
            async for event in events:
                seen.append(event)

    with pytest.raises(StreamInterrupted):
        await read()

    assert [event.task_id for event in seen] == ["t"]


async def test_cancel_accepts_any_answer() -> None:
    kagent = FakeKagent()
    client = A2AClient(_settings(), V03, "soundings", "x-nocancel", transport=kagent.transport)
    task_id = (await _events(client))[0].task_id
    assert task_id is not None

    assert await client.cancel_task(task_id) is True  # -32603 is an answer

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    down = A2AClient(_settings(), V03, "soundings", "a", transport=_transport(refuse))
    assert await down.cancel_task(task_id) is False


# --- The card ---------------------------------------------------------------------------------
async def test_the_card_is_summarised_as_plain_text() -> None:
    kagent = FakeKagent()
    client = A2AClient(_settings(), V03, "soundings", "idea-evaluator", transport=kagent.transport)

    status, card = await client.fetch_card()
    summary = card_summary(card)

    assert status == 200
    assert summary.name == "idea_evaluator"
    assert len(summary.description) == 200
    assert summary.protocol_versions == ["0.3", "1.0", "0.3.0"]
    assert summary.streaming is True
    assert len(summary.skills) == 20
    assert "url" not in summary.model_dump()
    assert "evil.example" not in summary.model_dump_json()
