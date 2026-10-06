"""``POST /mcp`` over HTTP (contract-phase5 sections 3.5 and 4.6, "Transport"): the
guard's checks and their order, the SDK's own refusals, the server metadata and the
published catalogue, and revocation taking effect on the very next request."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from mcp import MCPError
from mcp_types import CallToolResult
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.auth.key_auth import KEY_REQUEST_THROTTLE
from app.auth.throttle import Throttle
from app.mcp.tools import TOOLS
from app.models.activity import AuditLog
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.schemas.mcp import MCP_INSTRUCTIONS, MCP_TOOLS
from tests.conftest import Login
from tests.factories import make_idea
from tests.mcp.conftest import (
    Connect,
    MakeKey,
    Team,
    call,
    data,
    error,
    headers,
    rpc,
)

INITIALIZE = rpc(
    "initialize",
    {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "1"},
    },
)


def problem(response: httpx2.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["cache-control"] == "no-store"
    body: dict[str, Any] = response.json()
    assert body["code"] == code, body
    return body


async def mcp_calls(db: AsyncSession) -> list[AuditLog]:
    rows = await db.scalars(
        select(AuditLog).where(AuditLog.action == "mcp.call").order_by(AuditLog.created_at)
    )
    return list(rows)


@pytest.fixture
async def secret(make_key: MakeKey, team: Team) -> str:
    return await make_key(team.member)


# --- Metadata and catalogue ------------------------------------------------------------
async def test_initialize_names_the_server_and_carries_the_instructions(
    raw: httpx2.AsyncClient, secret: str
) -> None:
    response = await raw.post("/mcp", json=INITIALIZE, headers=headers(secret))

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    assert "mcp-session-id" not in response.headers  # stateless
    result = response.json()["result"]
    assert result["serverInfo"] == {
        "name": "soundings",
        "title": "Soundings",
        "version": __version__,
    }
    assert result["instructions"] == MCP_INSTRUCTIONS
    assert {name for name, value in result["capabilities"].items() if value} == {"tools"}


async def test_tools_list_is_exactly_the_catalogue(connect: Connect, secret: str) -> None:
    async with connect(secret) as client:
        listed = (await client.list_tools()).tools

    assert [tool.name for tool in listed] == [tool.name for tool in MCP_TOOLS]
    for tool, spec in zip(listed, MCP_TOOLS, strict=True):
        assert tool.title == spec.title
        assert tool.description == spec.description
        assert tool.input_schema == spec.input.model_json_schema()
        assert tool.output_schema == spec.output.model_json_schema(mode="serialization")
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is spec.read_only
        assert tool.annotations.destructive_hint is (spec.name == "submit_evaluation")
        assert tool.annotations.idempotent_hint is (
            spec.read_only or spec.name in {"submit_evaluation", "add_research_note"}
        )
        assert tool.annotations.open_world_hint is False


def test_every_catalogue_tool_has_exactly_one_implementation() -> None:
    assert list(TOOLS) == [tool.name for tool in MCP_TOOLS]


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_both_protocol_eras_call_tools(
    connect: Connect, secret: str, team: Team, mode: str
) -> None:
    """The SDK client probes 2026-07-28 (``server/discover``) by default; kagent and
    older clients use the initialize handshake (2025-11-25 and earlier)."""
    async with connect(secret, mode=mode) as client:
        projects = data(await call(client, "list_projects"))["projects"]

    assert [project["slug"] for project in projects] == [team.slug]


async def test_requests_are_logged_and_counted_as_the_mcp_route(
    raw: httpx2.AsyncClient, secret: str, caplog: pytest.LogCaptureFixture
) -> None:
    await raw.post("/mcp", json=INITIALIZE, headers=headers(secret))
    await raw.get("/mcp")

    lines = [r for r in caplog.records if r.name == "soundings.request"]
    assert [(r.method, r.route, r.status) for r in lines] == [  # type: ignore[attr-defined]
        ("POST", "/mcp", 200),
        ("GET", "/mcp", 405),
    ]


async def test_not_audited_initialize_list_and_ping(
    raw: httpx2.AsyncClient, connect: Connect, secret: str, db_session: AsyncSession
) -> None:
    async with connect(secret, mode="legacy") as client:
        await client.list_tools()
    for message in (INITIALIZE, rpc("ping"), rpc("tools/list")):
        response = await raw.post("/mcp", json=message, headers=headers(secret))
        assert response.status_code == 200, response.text

    assert await mcp_calls(db_session) == []


# --- Authentication -------------------------------------------------------------------
async def test_no_key_is_401_with_a_bearer_challenge(raw: httpx2.AsyncClient) -> None:
    response = await raw.post("/mcp", json=INITIALIZE, headers=headers())

    body = problem(response, 401, "unauthorized")
    assert response.headers["www-authenticate"] == 'Bearer realm="soundings"'
    assert "API key" in body["detail"]


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-key",
        "sdg_" + "a" * 12 + "_" + "b" * 39,
        "sdg_" + "a" * 12 + "_" + "b" * 40,  # well-formed, unknown
    ],
)
async def test_unusable_keys_get_the_same_401(raw: httpx2.AsyncClient, token: str) -> None:
    response = await raw.post(
        "/mcp", json=INITIALIZE, headers=headers(Authorization=f"Bearer {token}")
    )

    body = problem(response, 401, "unauthorized")
    assert response.headers["www-authenticate"] == 'Bearer realm="soundings"'
    assert token not in body["detail"] or not token


async def test_a_session_cookie_alone_is_never_accepted(
    login: Login, team: Team, app: FastAPI
) -> None:
    browser = await login(team.member)

    response = await browser.post("/mcp", json=INITIALIZE, headers=headers())

    assert response.status_code == 401, response.text
    assert response.headers["www-authenticate"] == 'Bearer realm="soundings"'


async def test_a_key_without_the_mcp_scope_is_403_and_audited_once_a_minute(
    raw: httpx2.AsyncClient, make_key: MakeKey, team: Team, db_session: AsyncSession
) -> None:
    """c15 whatever the JSON-RPC method; one entry per key a minute (review M2)."""
    secret = await make_key(team.member, ["read", "evaluate"])
    other = await make_key(team.viewer, ["read"])

    listing = await raw.post("/mcp", json=rpc("tools/list"), headers=headers(secret))
    calling = await raw.post(
        "/mcp", json=rpc("tools/call", {"name": "list_projects"}), headers=headers(secret)
    )
    again = await raw.post("/mcp", json=rpc("tools/list"), headers=headers(other))

    for response in (listing, calling, again):
        problem(response, 403, "insufficient_scope")
        assert response.headers["www-authenticate"] == (
            'Bearer error="insufficient_scope", scope="mcp"'
        )
    entries = await mcp_calls(db_session)
    assert [entry.actor_id for entry in entries] == [team.member.id, team.viewer.id]
    for entry in entries:
        assert entry.target_id is None
        assert {k: entry.details[k] for k in ("tool", "rule", "decision", "code", "auth")} == {
            "tool": None,
            "rule": "mcp.connect",
            "decision": "deny",
            "code": "insufficient_scope",
            "auth": "api_key",
        }
        assert entry.details["api_key_id"]


async def test_refusals_of_a_key_without_mcp_count_towards_its_request_budget(
    app: FastAPI, raw: httpx2.AsyncClient, make_key: MakeKey, team: Team, db_session: AsyncSession
) -> None:
    """Review M2: 360 refused requests a minute used to be 360 audit rows; now the key's
    budget (shared with REST) stops them, and each refusal is audited once a minute."""
    name, _, window = KEY_REQUEST_THROTTLE
    app.state.throttles = {name: Throttle(3, window)}
    secret = await make_key(team.member, ["read"])

    responses = [
        await raw.post("/mcp", json=rpc("tools/list", id=n), headers=headers(secret))
        for n in range(6)
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 429, 429, 429]
    problem(responses[-1], 429, "too_many_attempts")
    rest = await raw.get("/api/v1/projects", headers={"Authorization": f"Bearer {secret}"})
    problem(rest, 429, "too_many_attempts")
    entries = await mcp_calls(db_session)
    assert [(e.details["tool"], e.details["rule"], e.details["code"]) for e in entries] == [
        (None, "mcp.connect", "insufficient_scope"),
        (None, None, "too_many_attempts"),
    ]
    assert {entry.details["decision"] for entry in entries} == {"deny"}


async def test_a_key_over_its_request_budget_is_audited_once_a_minute(
    app: FastAPI, raw: httpx2.AsyncClient, secret: str, team: Team, db_session: AsyncSession
) -> None:
    """Review L1: the request budget's 429 at /mcp leaves one entry per key a minute."""
    name, _, window = KEY_REQUEST_THROTTLE
    app.state.throttles = {name: Throttle(1, window)}
    call_once = rpc("tools/call", {"name": "list_projects", "arguments": {}})

    first = await raw.post("/mcp", json=call_once, headers=headers(secret))
    refused = [await raw.post("/mcp", json=call_once, headers=headers(secret)) for _ in range(4)]

    assert first.status_code == 200, first.text
    for response in refused:
        problem(response, 429, "too_many_attempts")
    entries = await mcp_calls(db_session)
    assert [(e.details["tool"], e.details["code"], e.details["decision"]) for e in entries] == [
        ("list_projects", None, "allow"),
        (None, "too_many_attempts", "deny"),
    ]
    assert entries[1].actor_id == team.member.id


async def test_revoking_cuts_the_next_request_mid_session(
    connect: Connect,
    raw: httpx2.AsyncClient,
    secret: str,
    team: Team,
    db_session: AsyncSession,
) -> None:
    async with connect(secret) as client:
        assert data(await call(client, "list_projects"))["projects"]
        await db_session.execute(update(ApiKey).values(revoked_at=utcnow()))
        await db_session.commit()

        with pytest.raises(MCPError):  # the client reports the HTTP 401 as an error
            await client.call_tool("list_projects", {})

    response = await raw.post(
        "/mcp", json=rpc("tools/call", {"name": "list_projects"}), headers=headers(secret)
    )
    problem(response, 401, "unauthorized")
    rest = await raw.get("/api/v1/projects", headers={"Authorization": f"Bearer {secret}"})
    assert rest.status_code == 401


async def test_an_expired_key_is_401(
    raw: httpx2.AsyncClient, make_key: MakeKey, team: Team, db_session: AsyncSession
) -> None:
    secret = await make_key(team.member)
    await db_session.execute(update(ApiKey).values(expires_at=utcnow()))
    await db_session.commit()

    response = await raw.post("/mcp", json=INITIALIZE, headers=headers(secret))

    problem(response, 401, "unauthorized")


async def test_the_key_request_budget_is_shared_with_rest(
    app: FastAPI, raw: httpx2.AsyncClient, secret: str
) -> None:
    name, _, window = KEY_REQUEST_THROTTLE
    app.state.throttles = {name: Throttle(2, window)}

    rest = await raw.get("/api/v1/projects", headers={"Authorization": f"Bearer {secret}"})
    first = await raw.post("/mcp", json=rpc("tools/list"), headers=headers(secret))
    third = await raw.post("/mcp", json=rpc("tools/list"), headers=headers(secret))

    assert rest.status_code == 200, rest.text
    assert first.status_code == 200, first.text
    problem(third, 429, "too_many_attempts")
    assert int(third.headers["retry-after"]) >= 1


# --- Origin, Host, methods, size and the SDK's own checks --------------------------------
async def test_a_foreign_origin_is_refused_before_authentication(
    raw: httpx2.AsyncClient, secret: str
) -> None:
    for origin, key in [("https://evil.example", secret), ("null", None)]:
        response = await raw.post("/mcp", json=INITIALIZE, headers=headers(key, Origin=origin))
        problem(response, 403, "invalid_origin")


@pytest.mark.parametrize("origin", ["http://testserver", "HTTP://TestServer:80"])
async def test_our_own_origin_is_fine(raw: httpx2.AsyncClient, secret: str, origin: str) -> None:
    response = await raw.post("/mcp", json=INITIALIZE, headers=headers(secret, Origin=origin))
    assert response.status_code == 200, response.text


async def test_a_cluster_internal_host_works(raw: httpx2.AsyncClient, secret: str) -> None:
    """Agents call the Service by name (http://<fullname>.<ns>.svc.cluster.local/mcp),
    which is not one of the base URLs: /mcp is exempt from the Host check."""
    host = "soundings.soundings.svc.cluster.local"

    response = await raw.post("/mcp", json=INITIALIZE, headers=headers(secret, Host=host))
    api = await raw.get("/api/v1/projects", headers={"Host": host})

    assert response.status_code == 200, response.text
    assert api.status_code == 400  # the rest of the app still checks it
    assert api.json()["code"] == "invalid_host"


@pytest.mark.parametrize("method", ["GET", "DELETE", "PUT", "PATCH", "OPTIONS"])
async def test_only_post_is_served(raw: httpx2.AsyncClient, secret: str, method: str) -> None:
    response = await raw.request(method, "/mcp", headers=headers(secret))

    problem(response, 405, "method_not_allowed")
    assert response.headers["allow"] == "POST"
    assert "access-control-allow-origin" not in response.headers


async def test_bodies_over_one_mebibyte_are_413(raw: httpx2.AsyncClient, secret: str) -> None:
    body = (
        b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":"' + b"a" * (1024 * 1024) + b'"}}'
    )

    declared = await raw.post("/mcp", content=body, headers=headers(secret))

    async def chunks() -> AsyncIterator[bytes]:
        for start in range(0, len(body), 64 * 1024):
            yield body[start : start + 64 * 1024]

    streamed = await raw.post("/mcp", content=chunks(), headers=headers(secret))

    assert declared.status_code == 413
    assert declared.json()["code"] == "content_too_large"
    assert streamed.status_code == 413


async def test_a_json_rpc_batch_is_refused(raw: httpx2.AsyncClient, secret: str) -> None:
    response = await raw.post(
        "/mcp", json=[rpc("ping", id=1), rpc("ping", id=2)], headers=headers(secret)
    )
    assert response.status_code == 400, response.text


async def test_the_sdk_checks_accept_and_content_type(raw: httpx2.AsyncClient, secret: str) -> None:
    accept = await raw.post("/mcp", json=INITIALIZE, headers=headers(secret, Accept="text/html"))
    content_type = await raw.post(
        "/mcp",
        content=b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
        headers=headers(secret, **{"Content-Type": "text/plain"}),
    )

    assert accept.status_code == 406
    assert content_type.status_code == 415


async def test_well_known_oauth_metadata_is_a_clean_404(raw: httpx2.AsyncClient) -> None:
    """MCP clients probe for OAuth metadata after a 401: they find none."""
    for path in (
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
    ):
        response = await raw.get(path)
        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"


# --- Tool errors at the protocol edge ------------------------------------------------------
async def test_an_unknown_tool_and_bad_arguments_are_structured_tool_errors(
    connect: Connect, secret: str, db_session: AsyncSession, team: Team
) -> None:
    idea = await make_idea(db_session, team.project)
    async with connect(secret) as client:
        unknown = await call(client, "delete_everything")
        invalid = await call(client, "get_idea", idea="not a key", comment_limit=99)
        both = await call(client, "get_rubric", project=team.slug, idea=f"CUST-{idea.number}")

    assert error(unknown) == "unknown_tool"
    assert error(invalid) == "validation_error"
    message = invalid.structured_content["message"]
    assert "idea (string_pattern_mismatch)" in message
    assert "comment_limit (less_than_equal)" in message
    assert "not a key" not in message  # field names, never values
    assert error(both) == "validation_error"
    assert "give either project or idea" in both.structured_content["message"]
    entries = await mcp_calls(db_session)
    assert [(e.details["tool"], e.details["code"], e.details["decision"]) for e in entries] == [
        ("unknown", "unknown_tool", "deny"),
        ("get_idea", "validation_error", "deny"),
        ("get_rubric", "validation_error", "deny"),
    ]
    assert entries[1].details["rule"] == "idea.view"
    assert entries[1].target_id is None  # "not a key" names nothing
    assert entries[2].target_id == idea.id  # it exists


async def test_a_call_the_sdk_refuses_is_still_audited(
    raw: httpx2.AsyncClient, secret: str, db_session: AsyncSession
) -> None:
    response = await raw.post(
        "/mcp",
        json=rpc("tools/call", {"name": "get_idea", "arguments": ["CUST-1"]}),
        headers=headers(secret),
    )

    assert response.status_code in (200, 400), response.text
    assert "error" in response.json()
    [entry] = await mcp_calls(db_session)
    assert entry.details["tool"] == "get_idea"
    assert entry.details["code"] == "validation_error"
    assert entry.details["decision"] == "deny"


async def test_results_are_structured_and_the_same_json_as_text(
    connect: Connect, secret: str
) -> None:
    async with connect(secret) as client:
        result: CallToolResult = await call(client, "list_projects")

    import json

    assert json.loads(result.content[0].text) == result.structured_content  # type: ignore[union-attr]
