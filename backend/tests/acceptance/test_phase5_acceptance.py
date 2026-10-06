"""Phase 5 acceptance against a live server (QA; docs/test-plans/phase-5.md, AC5-API-*).

SPEC section 13, Phase 5: *an MCP client with a key can search ideas and submit an
evaluation only in permitted projects; revoking the key cuts access immediately*
(contract-phase5 section 3.9).

Unlike the backend's own ``tests/mcp/test_flow.py`` (the SDK client over an in-process
ASGI transport, factories, the key written straight to the database), this runs the app
behind a real **uvicorn** on a free port and talks to it only over TCP, as Claude
Desktop or a kagent agent would:

* the demo data (``soundings seed``) and the dev login, people signing in through the
  REST API with their session cookie and CSRF header;
* Carol's key created and revoked through ``/api/v1/me/api-keys`` in her session (shown
  once, ``Cache-Control: no-store``, never listed again);
* the official MCP Python SDK client (``mcp`` 2.x, streamable HTTP) on ``/mcp``;
* the audit read back through Admin settings -> Audit log's API as Alice;
* every log record of the story checked for the key and for tool arguments.

* AC5-API-1: the acceptance story, steps 1-6 of contract 3.9, with the evaluation saved
  as a draft first, REST with the same key, and the next call after revoking.
* AC5-API-2: a pending evaluator's key (Alice: platform admin, Customer Innovation admin,
  still owing evaluations in the seed) gets no score data from ``search_ideas`` or
  ``get_idea``, in both protocol handshakes, while the owner's key does.
* AC5-API-3: deactivating a user revokes their keys for good (contract section 2):
  reactivated, the key stays dead.
* AC5-API-4: an AI agent's key (a service account, contract 3.7) evaluates blind through
  MCP, suggests with ``source: ai`` and never volunteers as owner (c21); its evaluation
  is left out of the aggregate, it can't be made an owner (c4) or a project admin.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import socket
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import httpx2
import pytest
import uvicorn
from fastapi import FastAPI
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult, TextContent
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_keys.service import issue_key
from app.config import Settings
from app.domain.principal import Principal
from app.models.enums import ApiKeyScope, AuthMethod, ProjectRole
from app.models.user import User
from app.schemas.api_keys import API_KEY_PATTERN, ApiKeyCreate
from app.schemas.mcp import MCP_INSTRUCTIONS, MCP_SERVER_NAME
from app.seed import run_seed
from tests.factories import make_project, make_user

API = "/api/v1"
TOOLS = {
    "list_projects",
    "search_ideas",
    "get_idea",
    "get_rubric",
    "get_proposal",
    "create_idea",
    "add_comment",
    "submit_evaluation",
    "propose_proposal_section",
}
CUST, TOOLS_PROJECT = "customer-innovation", "internal-tools"
# Text only the tool arguments carry: it must never reach a log record or the audit.
DRAFT_COMMENT = "Draft thoughts on the lockers, not ready yet."
FINAL_COMMENT = "Worth a pilot in two stores; ask Finance about the rent."
CUST_TITLE = "Parcel lockers in every store"
TOOLS_TITLE = "Self-service laptop swap desk"


# --- A live server ------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def port() -> int:
    return _free_port()


@pytest.fixture
def settings_overrides(port: int) -> dict[str, Any]:
    # The live server's own URL is the base URL (the trusted-host check, `url` fields).
    return {"base_urls": [f"http://127.0.0.1:{port}"], "dev_login_enabled": True}


class _Server(uvicorn.Server):
    """uvicorn in the test's event loop, without taking over the process's signals."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


@pytest.fixture
async def live(app: FastAPI, port: int) -> AsyncIterator[str]:
    """The app (lifespan already running) behind uvicorn on 127.0.0.1:<port>."""
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
        await asyncio.wait_for(task, timeout=10)


@pytest.fixture
async def seeded(settings: Settings, app: FastAPI) -> None:
    report = await run_seed(settings)
    assert report.skipped is None
    assert (report.projects, report.ideas) == (3, 48)


# --- REST clients ---------------------------------------------------------------------------
def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, f"{response.request.url}: {response.text}"
    return response.json() if response.content else None


@dataclass
class Person:
    """One person signed in with the dev login over TCP (cookie + CSRF header)."""

    http: httpx.AsyncClient
    id: str
    name: str

    async def get(self, path: str) -> Any:
        return ok(await self.http.get(f"{API}{path}"))

    async def send(self, method: str, path: str, body: Any = None, status: int = 200) -> Any:
        return ok(await self.http.request(method, f"{API}{path}", json=body), status)


@pytest.fixture
async def people(live: str, seeded: None) -> AsyncIterator[dict[str, Person]]:
    """Alice, Bob, Carol, Dave and Farah from the demo data, signed in, by username."""
    clients: list[httpx.AsyncClient] = []
    anonymous = httpx.AsyncClient(base_url=live, trust_env=False)
    clients.append(anonymous)
    users = {u["email"].split("@")[0]: u for u in ok(await anonymous.get(f"{API}/auth/dev/users"))}

    signed_in: dict[str, Person] = {}
    for username in ("alice", "bob", "carol", "dave", "farah"):
        http = httpx.AsyncClient(base_url=live, trust_env=False)
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


def key_client(live: str, secret: str) -> httpx.AsyncClient:
    """A REST client that authenticates with the key only (no cookies at all)."""
    return httpx.AsyncClient(
        base_url=live, trust_env=False, headers={"Authorization": f"Bearer {secret}"}
    )


# --- MCP ------------------------------------------------------------------------------------
@contextlib.asynccontextmanager
async def mcp_client(live: str, secret: str, *, mode: str = "auto") -> AsyncIterator[Client]:
    """The official SDK client on ``<live>/mcp`` over real HTTP, with the key."""
    headers = {"Authorization": f"Bearer {secret}"}
    async with httpx2.AsyncClient(headers=headers, trust_env=False, timeout=30) as http:
        client = Client(streamable_http_client(f"{live}/mcp", http_client=http), mode=mode)
        async with client:
            yield client


def text_blocks(result: CallToolResult) -> list[str]:
    return [block.text for block in result.content if isinstance(block, TextContent)]


async def call(client: Client, tool: str, **arguments: Any) -> CallToolResult:
    result = await client.call_tool(tool, arguments)
    assert isinstance(result, CallToolResult)
    # Structured content and the text block carry the same JSON (contract 4.2).
    texts = text_blocks(result)
    if not result.is_error:
        assert [json.loads(text) for text in texts] == [result.structured_content]
    return result


def leaves(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for inner in exc.exceptions for leaf in leaves(inner)]
    return [exc]


async def refused(live: str, secret: str) -> bool:
    """Whether connecting with ``secret`` fails (the SDK raises out of its task group)."""
    try:
        async with mcp_client(live, secret) as client:
            await client.list_tools()
    except (MCPError, httpx2.HTTPError, ExceptionGroup) as exc:
        return all(isinstance(leaf, MCPError | httpx2.HTTPError) for leaf in leaves(exc))
    return False


def data(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    found: dict[str, Any] = result.structured_content
    return found


def error(result: CallToolResult) -> str:
    assert result.is_error, result.structured_content
    code: str = result.structured_content["code"]
    texts = text_blocks(result)
    assert texts, result.content
    assert texts[0].startswith(f"{code}: "), texts
    return code


def score_data(value: Any, path: str = "") -> list[str]:
    """Paths of everything in an MCP result that would reveal score data, outside the
    caller's own evaluation (``my_evaluation``): a non-null ``score`` / ``aggregate`` /
    ``overall``, ``score_hidden: false``, a true ``high_disagreement``, any evaluation
    or a non-zero ``evaluation_count``."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}"
            if key == "my_evaluation":
                continue
            revealing = (
                (key in {"score", "aggregate", "overall"} and item is not None)
                or (key == "score_hidden" and item is not True)
                or (key == "high_disagreement" and item is not False)
                or (key == "evaluations" and bool(item))
                or (key == "evaluation_count" and item != 0)
            )
            if revealing:
                found.append(here)
            else:
                found.extend(score_data(item, here))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(score_data(item, f"{path}[{index}]"))
    return found


async def rubric_ids(person: Person, slug: str) -> list[str]:
    project = await person.get(f"/projects/{slug}")
    return [criterion["id"] for criterion in project["rubric"]]


async def evaluate(person: Person, key: str, slug: str, score: int) -> None:
    scores = [{"criterion_id": c, "score": score} for c in await rubric_ids(person, slug)]
    await person.send(
        "PUT",
        f"/ideas/{key}/evaluations/me",
        {"scores": scores, "recommendation": "go", "comment": "", "submit": True},
    )


async def audit(alice: Person, **filters: str) -> list[dict[str, Any]]:
    query = "&".join(f"{name}={value}" for name, value in {"limit": "100", **filters}.items())
    page = await alice.get(f"/admin/audit?{query}")
    items: list[dict[str, Any]] = page["items"]
    return items


# --- AC5-API-1 ------------------------------------------------------------------------------
async def test_ac5_api_1_an_mcp_key_searches_and_evaluates_only_where_it_reaches(
    live: str, people: dict[str, Person], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="soundings")
    caplog.set_level(logging.INFO)
    alice, bob, carol, dave, farah = (people[n] for n in ("alice", "bob", "carol", "dave", "farah"))

    # 1. Carol is invited to evaluate one idea in each of her projects; on CUST-n two
    #    other evaluators have already submitted.
    cust = await alice.send(
        "POST",
        f"/projects/{CUST}/ideas",
        {"title": CUST_TITLE, "summary": "Customers collect orders from lockers by the door."},
        201,
    )
    cust_key = cust["key"]
    await alice.send("PUT", f"/ideas/{cust_key}/owner", {"user_id": alice.id})
    await alice.send("POST", f"/ideas/{cust_key}/status", {"status": "evaluating"})
    await alice.send(
        "POST", f"/ideas/{cust_key}/evaluators", {"user_ids": [bob.id, farah.id, carol.id]}
    )
    await evaluate(bob, cust_key, CUST, 4)
    await evaluate(farah, cust_key, CUST, 2)
    tools = await dave.send(
        "POST",
        f"/projects/{TOOLS_PROJECT}/ideas",
        {"title": TOOLS_TITLE, "summary": "Swap a broken laptop at a desk in ten minutes."},
        201,
    )
    tools_key = tools["key"]
    await dave.send("PUT", f"/ideas/{tools_key}/owner", {"user_id": dave.id})
    await dave.send("POST", f"/ideas/{tools_key}/status", {"status": "evaluating"})
    await dave.send("POST", f"/ideas/{tools_key}/evaluators", {"user_ids": [carol.id]})
    # In the app Carol may evaluate both.
    for key in (cust_key, tools_key):
        assert (await carol.get(f"/ideas/{key}"))["permissions"]["can_evaluate"] is True

    #    In Settings -> API keys she creates "Claude Desktop": read, evaluate, mcp, only
    #    Customer Innovation. The secret is in this response and nowhere else.
    cust_id = (await carol.get(f"/projects/{CUST}"))["id"]
    response = await carol.http.post(
        f"{API}/me/api-keys",
        json={
            "name": "Claude Desktop",
            "scopes": ["evaluate", "mcp"],
            "project_ids": [cust_id],
            "expires_at": None,
        },
    )
    created = ok(response, 201)
    assert response.headers["cache-control"] == "no-store"
    secret: str = created["secret"]
    key_id: str = created["key"]["id"]
    assert re.fullmatch(API_KEY_PATTERN, secret)
    assert created["key"]["prefix"] == secret[:16]
    assert created["key"]["scopes"] == ["read", "evaluate", "mcp"]  # read included
    assert created["key"]["restricted"] is True
    assert [p["slug"] for p in created["key"]["projects"]] == [CUST]
    listed = await carol.http.get(f"{API}/me/api-keys")
    assert secret not in listed.text
    assert secret[17:] not in listed.text
    assert [k["id"] for k in ok(listed)["items"]] == [key_id]

    # 2. The MCP client connects with the key: nine tools, only Customer Innovation,
    #    only CUST-n awaits her, blind.
    async with mcp_client(live, secret) as client:
        assert client.server_info is not None
        assert client.server_info.name == MCP_SERVER_NAME
        assert client.instructions == MCP_INSTRUCTIONS
        listed_tools = (await client.list_tools()).tools
        assert {tool.name for tool in listed_tools} == TOOLS
        assert len(listed_tools) == 9

        projects = data(await call(client, "list_projects"))["projects"]
        assert [(p["slug"], p["my_role"]) for p in projects] == [(CUST, "member")]
        assert projects[0]["can_create_ideas"] is False  # no write scope

        awaiting = data(await call(client, "search_ideas", awaiting_my_evaluation=True))
        assert [(i["key"], i["score_hidden"], i["score"]) for i in awaiting["items"]] == [
            (cust_key, True, None)
        ]
        everything = data(await call(client, "search_ideas", limit=50))
        assert everything["next_cursor"] is None
        assert len(everything["items"]) == 22  # the seed's 21 CUST ideas and CUST-n
        assert {i["project"]["slug"] for i in everything["items"]} == {CUST}
        assert data(await call(client, "search_ideas", query=TOOLS_TITLE))["items"] == []

        # 3. Blind until she submits: no other evaluations, no aggregate. A draft first.
        before = data(await call(client, "get_idea", idea=cust_key))["idea"]
        assert score_data(before) == []
        assert before["my_evaluation"]["state"] == "invited"
        assert before["permissions"]["can_evaluate"] is True
        assert before["permissions"]["can_comment"] is False
        rubric = data(await call(client, "get_rubric", idea=cust_key))
        criteria = [criterion["id"] for criterion in rubric["criteria"]]
        assert len(criteria) == 5
        draft = data(
            await call(
                client,
                "submit_evaluation",
                idea=cust_key,
                scores=[{"criterion_id": criteria[0], "score": 3}],
                comment=DRAFT_COMMENT,
                submit=False,
            )
        )
        assert draft["evaluation"]["state"] == "draft"
        still_blind = data(await call(client, "get_idea", idea=cust_key))["idea"]
        assert score_data(still_blind) == []
        assert still_blind["my_evaluation"]["comment"] == DRAFT_COMMENT
        # Submitting without every criterion is refused (as REST's 422).
        incomplete = await call(
            client,
            "submit_evaluation",
            idea=cust_key,
            scores=[{"criterion_id": criteria[0], "score": 3}],
            recommendation="go",
        )
        assert error(incomplete) == "evaluation_incomplete"
        submitted = data(
            await call(
                client,
                "submit_evaluation",
                idea=cust_key,
                scores=[{"criterion_id": c, "score": 5} for c in criteria],
                recommendation="go",
                comment=FINAL_COMMENT,
            )
        )
        assert submitted["evaluation"]["state"] == "submitted"
        after = data(await call(client, "get_idea", idea=cust_key))["idea"]
        assert after["evaluation_count"] == 2  # other people's
        assert {e["evaluator"]["display_name"] for e in after["evaluations"]} == {
            bob.name,
            farah.name,
        }
        assert after["aggregate"]["count"] == 3
        assert after["score_hidden"] is False

        # 4. Outside the restriction: not found, although Carol may evaluate it in the
        #    app; without write: insufficient_scope.
        assert error(await call(client, "get_idea", idea=tools_key)) == "not_found"
        outside = await call(
            client,
            "submit_evaluation",
            idea=tools_key,
            scores=[{"criterion_id": c, "score": 4} for c in criteria],
            recommendation="go",
        )
        assert error(outside) == "not_found"
        assert error(await call(client, "get_rubric", project=TOOLS_PROJECT)) == "not_found"
        assert error(await call(client, "search_ideas", project=TOOLS_PROJECT)) == "not_found"
        created_idea = await call(
            client, "create_idea", project=CUST, title="Robots", summary="Robots everywhere."
        )
        assert error(created_idea) == "insufficient_scope"
        commented = await call(client, "add_comment", idea=cust_key, body_md="Nice.")
        assert error(commented) == "insufficient_scope"
        assert error(await call(client, "no_such_tool")) == "unknown_tool"

        # The same key over REST: the same narrowing.
        async with key_client(live, secret) as rest:
            assert [p["slug"] for p in ok(await rest.get(f"{API}/projects"))] == [CUST]
            assert (await rest.get(f"{API}/projects/{TOOLS_PROJECT}")).status_code == 404
            assert (await rest.get(f"{API}/ideas/{tools_key}")).status_code == 404
            mine = ok(await rest.get(f"{API}/ideas/{cust_key}/evaluations/me"))
            assert mine["state"] == "submitted"
            denied = await rest.post(
                f"{API}/projects/{CUST}/ideas", json={"title": "x", "summary": "y"}
            )
            assert (denied.status_code, denied.json()["code"]) == (403, "insufficient_scope")
            keys = await rest.get(f"{API}/me/api-keys")  # key management: session only
            assert (keys.status_code, keys.json()["code"]) == (403, "insufficient_scope")
        # Nobody else is narrowed: in her session Carol still sees Internal Tools.
        assert (await carol.get(f"/ideas/{tools_key}"))["key"] == tools_key

        # 5. The audit log shows each call with its decision, and her evaluation through
        #    the key.
        calls = list(reversed(await audit(alice, action="mcp.call", actor_id=carol.id)))
        assert [(c["details"]["tool"], c["details"]["decision"]) for c in calls] == [
            ("list_projects", "allow"),
            ("search_ideas", "allow"),
            ("search_ideas", "allow"),
            ("search_ideas", "allow"),
            ("get_idea", "allow"),
            ("get_rubric", "allow"),
            ("submit_evaluation", "allow"),
            ("get_idea", "allow"),
            ("submit_evaluation", "allow"),
            ("submit_evaluation", "allow"),
            ("get_idea", "allow"),
            ("get_idea", "deny"),
            ("submit_evaluation", "deny"),
            ("get_rubric", "deny"),
            ("search_ideas", "deny"),
            ("create_idea", "deny"),
            ("add_comment", "deny"),
            ("unknown", "deny"),
        ]
        codes = [c["details"]["code"] for c in calls]
        assert codes[8:] == [
            "evaluation_incomplete",
            None,
            None,
            "not_found",
            "not_found",
            "not_found",
            "not_found",
            "insufficient_scope",
            "insufficient_scope",
            "unknown_tool",
        ]
        assert {c["details"]["api_key_id"] for c in calls} == {key_id}
        assert {c["details"]["auth"] for c in calls} == {"api_key"}
        # The idea a call was about is its target, also for a denial.
        assert calls[4]["target_label"] == cust_key
        assert calls[12]["target_label"] == tools_key
        # (The seed's own evaluations by Carol are in the log too, from her session.)
        evaluation = [
            entry
            for entry in await audit(alice, action="evaluation.submit", actor_id=carol.id)
            if entry["target_label"] == cust_key
        ]
        assert [(e["details"]["auth"], e["details"]["api_key_id"]) for e in evaluation] == [
            ("api_key", key_id)
        ]
        audit_text = json.dumps(calls + evaluation)
        for private in (secret, secret[17:], DRAFT_COMMENT, FINAL_COMMENT, "Robots"):
            assert private not in audit_text

        # 6. Carol revokes the key in Settings: the client's very next call fails.
        await carol.send("DELETE", f"/me/api-keys/{key_id}", status=204)
        with pytest.raises(MCPError):
            await client.call_tool("list_projects", {})

    # A new connection, a raw JSON-RPC request and REST with the key: all 401.
    assert await refused(live, secret)
    async with httpx.AsyncClient(base_url=live, trust_env=False) as raw:
        rpc = await raw.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "Authorization": f"Bearer {secret}",
                "Accept": "application/json, text/event-stream",
            },
        )
        assert rpc.status_code == 401
        assert rpc.headers["www-authenticate"] == 'Bearer realm="soundings"'
        assert rpc.headers["content-type"].startswith("application/problem+json")
    async with key_client(live, secret) as rest:
        assert (await rest.get(f"{API}/auth/me")).status_code == 401
    assert ok(await carol.http.get(f"{API}/me/api-keys"))["items"] == []
    # Revoking a revoked key is idempotent; the audit has the key's whole life.
    await carol.send("DELETE", f"/me/api-keys/{key_id}", status=204)
    lifecycle = await audit(alice, actor_id=carol.id, target_id=carol.id)
    lifecycle = [e for e in lifecycle if e["action"].startswith("api_key.")]
    assert [(e["action"], e["details"]["key_id"]) for e in reversed(lifecycle)] == [
        ("api_key.create", key_id),
        ("api_key.revoke", key_id),
    ]
    assert lifecycle[-1]["details"]["prefix"] == created["key"]["prefix"]
    assert lifecycle[-1]["details"]["restricted"] is True
    # The evaluation she submitted through the key counts, as any other.
    alice_view = await alice.get(f"/ideas/{cust_key}")
    assert alice_view["aggregate"]["count"] == 3

    # Nothing logged the key or the arguments of a tool call.
    logged = "\n".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    for private in (secret, secret[17:], DRAFT_COMMENT, FINAL_COMMENT):
        assert private not in logged


# --- AC5-API-2 ------------------------------------------------------------------------------
async def test_ac5_api_2_a_pending_evaluators_key_gets_no_scores(
    live: str, people: dict[str, Person]
) -> None:
    alice, bob = people["alice"], people["bob"]

    async def new_key(person: Person, name: str) -> str:
        created = await person.send(
            "POST", "/me/api-keys", {"name": name, "scopes": ["read", "mcp"]}, 201
        )
        secret: str = created["secret"]
        return secret

    alice_secret = await new_key(alice, "Blind check")
    bob_secret = await new_key(bob, "Owner check")

    # Both handshakes: the 2026-07-28 probe ("auto") and the older initialize ("legacy").
    for mode in ("auto", "legacy"):
        async with mcp_client(live, alice_secret, mode=mode) as client:
            # Alice is a platform admin and admin of Customer Innovation, and still owes
            # evaluations in the seed (CUST-11 among them): none of them shows a score.
            awaiting = data(await call(client, "search_ideas", awaiting_my_evaluation=True))
            keys = [item["key"] for item in awaiting["items"]]
            assert "CUST-11" in keys, mode
            assert score_data(awaiting) == []
            for key in keys:
                detail = data(await call(client, "get_idea", idea=key, comment_limit=20))["idea"]
                assert score_data(detail) == [], key
                assert detail["my_evaluation"]["state"] in {"invited", "draft"}
                # Other evaluators' drafts stay private: only invited or submitted (her
                # own row may say draft).
                others = {e["state"] for e in detail["evaluators"] if e["user"]["id"] != alice.id}
                assert others <= {"invited", "submitted"}, key
                found = data(await call(client, "search_ideas", query=key))["items"]
                assert [(i["key"], i["score"], i["score_hidden"]) for i in found] == [
                    (key, None, True)
                ]
            # Sorted by score, every visible score comes first; the hidden ones go last.
            ranked = data(
                await call(client, "search_ideas", project=CUST, sort="-score", limit=50)
            )["items"]
            scored = [item for item in ranked if item["score"] is not None]
            overall = [item["score"]["overall"] for item in scored]
            assert overall == sorted(overall, reverse=True)
            assert ranked[: len(scored)] == scored
            tail = {item["key"] for item in ranked[len(scored) :]}
            assert {k for k in keys if k.startswith("CUST-")} <= tail

        # The owner's key on the same idea: the aggregate and the evaluations.
        async with mcp_client(live, bob_secret, mode=mode) as client:
            owned = data(await call(client, "get_idea", idea="CUST-11"))["idea"]
            assert owned["owner"]["display_name"] == bob.name
            assert owned["aggregate"] is not None
            assert owned["evaluation_count"] > 0
            assert owned["high_disagreement"] is True  # the seed's documented disagreement


# --- AC5-API-3 ------------------------------------------------------------------------------
async def sign_in(live: str, user: User) -> Person:
    http = httpx.AsyncClient(base_url=live, trust_env=False)
    ok(await http.post(f"{API}/auth/dev/login", json={"user_id": str(user.id)}))
    http.headers["X-CSRF-Token"] = http.cookies["soundings_csrf"]
    return Person(http, str(user.id), user.display_name)


async def test_ac5_api_3_deactivating_the_owner_revokes_their_keys(
    live: str, db_session: AsyncSession
) -> None:
    admin = await sign_in(live, await make_user(db_session, "Ada Admin", platform_admin=True))
    ben = await sign_in(live, await make_user(db_session, "Ben Script"))
    try:
        created = await ben.send(
            "POST", "/me/api-keys", {"name": "Report script", "scopes": ["read"]}, 201
        )
        async with key_client(live, created["secret"]) as rest:
            assert (await rest.get(f"{API}/auth/me")).status_code == 200
            await admin.send("PATCH", f"/admin/users/{ben.id}", {"is_active": False})
            assert (await rest.get(f"{API}/auth/me")).status_code == 401
            # Reactivated, the key stays revoked: it never comes back by itself.
            await admin.send("PATCH", f"/admin/users/{ben.id}", {"is_active": True})
            assert (await rest.get(f"{API}/auth/me")).status_code == 401
        revoked = await audit(admin, action="api_key.revoke", target_id=ben.id)
        assert [(e["details"]["key_id"], e["details"].get("reason")) for e in revoked] == [
            (created["key"]["id"], "deactivated")
        ]
        assert (await admin.get(f"/admin/api-keys?user_id={ben.id}"))["items"] == []
    finally:
        await admin.http.aclose()
        await ben.http.aclose()


# --- AC5-API-4 ------------------------------------------------------------------------------
@dataclass
class AgentWorld:
    """A project with an admin (Ada), an owner (Olga), a person evaluator (Pat) and an AI
    agent (a service account, member), and the agent's key (read, write, evaluate, mcp)
    issued by Ada as Phase 6's Admin -> AI agents will."""

    ada: Person
    olga: Person
    pat: Person
    agent: User
    agent_secret: str
    slug: str
    criteria: list[str]


@pytest.fixture
async def agent_world(live: str, db_session: AsyncSession) -> AsyncIterator[AgentWorld]:
    ada_user = await make_user(db_session, "Ada Admin", platform_admin=True)
    olga_user = await make_user(db_session, "Olga Owner")
    pat_user = await make_user(db_session, "Pat Person")
    agent = await make_user(db_session, "Research agent", service_account=True)
    project = await make_project(
        db_session,
        slug="agents",
        key="AGT",
        name="Agents",
        members={
            ada_user: ProjectRole.ADMIN,
            olga_user: ProjectRole.MEMBER,
            pat_user: ProjectRole.MEMBER,
            agent: ProjectRole.MEMBER,
        },
    )
    _, secret = await issue_key(
        db_session,
        owner=agent,
        creator=Principal(user=ada_user, auth_method=AuthMethod.DEV_LOGIN),
        created_auth_method=AuthMethod.DEV_LOGIN,
        body=ApiKeyCreate(
            name="kagent research-agent",
            scopes=[ApiKeyScope.READ, ApiKeyScope.WRITE, ApiKeyScope.EVALUATE, ApiKeyScope.MCP],
            project_ids=[project.id],
        ),
    )
    await db_session.commit()
    ada = await sign_in(live, ada_user)
    olga = await sign_in(live, olga_user)
    pat = await sign_in(live, pat_user)
    try:
        rubric = (await ada.get(f"/projects/{project.slug}"))["rubric"]
        yield AgentWorld(ada, olga, pat, agent, secret, project.slug, [c["id"] for c in rubric])
    finally:
        for person in (ada, olga, pat):
            await person.http.aclose()


async def evaluating_idea(world: AgentWorld, *evaluators: str) -> str:
    idea = await world.olga.send(
        "POST",
        f"/projects/{world.slug}/ideas",
        {"title": "Summarise support tickets", "summary": "A weekly digest of themes."},
        201,
    )
    key: str = idea["key"]
    await world.ada.send("PUT", f"/ideas/{key}/owner", {"user_id": world.olga.id})
    await world.olga.send("POST", f"/ideas/{key}/status", {"status": "evaluating"})
    await world.olga.send("POST", f"/ideas/{key}/evaluators", {"user_ids": list(evaluators)})
    return key


async def test_ac5_api_4_an_agents_key_works_like_a_member_and_evaluates_blind(
    live: str, agent_world: AgentWorld
) -> None:
    world = agent_world
    key = await evaluating_idea(world, world.pat.id, str(world.agent.id))
    await evaluate_with(world.pat, key, world.criteria, 4)
    async with mcp_client(live, world.agent_secret) as client:
        before = data(await call(client, "get_idea", idea=key))["idea"]
        assert score_data(before) == []  # blind like anyone else
        submitted = data(
            await call(
                client,
                "submit_evaluation",
                idea=key,
                scores=[
                    {"criterion_id": c, "score": 2, "comment": "From the tickets."}
                    for c in world.criteria
                ],
                recommendation="maybe",
                comment="Themes repeat weekly.",
            )
        )
        assert submitted["evaluation"]["state"] == "submitted"
        # A suggestion by an agent is `ai`, whatever the channel.
        await world.olga.send("POST", f"/ideas/{key}/status", {"status": "shortlisted"})
        await world.olga.send("POST", f"/ideas/{key}/proposal", None, 201)
        proposed = data(
            await call(
                client,
                "propose_proposal_section",
                idea=key,
                section_key="summary",
                body_md="A weekly digest of support themes for product teams.",
            )
        )
        assert proposed["suggestion"]["source"] == "ai"
    # c21: an agent never volunteers as owner (the project allows volunteers).
    async with key_client(live, world.agent_secret) as rest:
        other = await world.olga.send(
            "POST", f"/projects/{world.slug}/ideas", {"title": "Unowned", "summary": "x"}, 201
        )
        volunteered = await rest.post(f"{API}/ideas/{other['key']}/volunteer")
        assert (volunteered.status_code, volunteered.json()["code"]) == (403, "forbidden")


async def evaluate_with(person: Person, key: str, criteria: list[str], score: int) -> None:
    scores = [{"criterion_id": c, "score": score} for c in criteria]
    await person.send(
        "PUT",
        f"/ideas/{key}/evaluations/me",
        {"scores": scores, "recommendation": "go", "comment": "", "submit": True},
    )


async def test_ac5_api_4_an_agents_evaluation_is_left_out_of_the_aggregate(
    live: str, agent_world: AgentWorld
) -> None:
    world = agent_world
    key = await evaluating_idea(world, world.pat.id, str(world.agent.id))
    await evaluate_with(world.pat, key, world.criteria, 4)
    async with mcp_client(live, world.agent_secret) as client:
        data(
            await call(
                client,
                "submit_evaluation",
                idea=key,
                scores=[{"criterion_id": c, "score": 1} for c in world.criteria],
                recommendation="no",
            )
        )
    idea = await world.olga.get(f"/ideas/{key}")
    assert idea["aggregate"]["count"] == 1  # Pat's only
    evaluations = (await world.olga.get(f"/ideas/{key}/evaluations"))["items"]
    by_ai = [e for e in evaluations if e["evaluator"]["id"] == str(world.agent.id)]
    assert [e["include_in_aggregate"] for e in by_ai] == [False]


async def test_ac5_api_4_an_agent_can_not_be_made_an_ideas_owner(
    live: str, agent_world: AgentWorld
) -> None:
    world = agent_world
    key = await evaluating_idea(world, world.pat.id)
    response = await world.ada.http.put(
        f"{API}/ideas/{key}/owner", json={"user_id": str(world.agent.id)}
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "assignee_not_eligible"


async def test_ac5_api_4_an_agent_can_not_be_a_project_admin(
    live: str, agent_world: AgentWorld
) -> None:
    world = agent_world
    response = await world.ada.http.patch(
        f"{API}/projects/{world.slug}/members/{world.agent.id}", json={"role": "admin"}
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "system_account"
