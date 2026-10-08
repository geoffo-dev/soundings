"""Phase 8 acceptance against a live server (QA; docs/test-plans/phase-8.md, AC8-API-*).

The product owner's Phase 8 change (decisions "Phase 8 (product owner, 2026-10-07)",
contract-phase8): **A**, a per-project proposal template, and **B**, an optional research
step with a checklist that gates the statuses after Research.

Like the Phase 5 acceptance, the app runs behind a real **uvicorn** on a free port with
the demo data (``soundings seed``) and the dev login, and everything goes over TCP: people
through the REST API with their session cookie and CSRF header, API keys as bearer tokens
with no cookie, and the official MCP Python SDK client on ``/mcp``. PDFs are rendered by
the real WeasyPrint child process and read back with pypdf. The few database touches are
arrangements the API has no route for (an AI agent's service account and an open run).

* AC8-API-1: a project admin customises the proposal template (add, rename, reorder,
  remove with its text kept, restore); a proposal follows it at once in the editor's
  API, threads and suggestions, the Markdown and PDF exports and through MCP; keys never
  change; API keys can't edit the template.
* AC8-API-2: the research gate: a project admin turns the step on with the default
  checklist; an idea moves New -> Research; moving it on is refused for its owner with
  the open items; every other path past Research is refused too (the status menu and the
  board's drag are one request, the first evaluator invite, reopening an idea closed from
  New, an API key, MCP has no tool that moves an idea, an AI agent's key can't answer);
  the owner answers; then it moves on; a project admin's "Move anyway" is audited and
  marked in the feed; the step can't be switched off while ideas are in Research; the
  exports end with the research appendix; switching the step off hides everything and
  switching it on again brings the answers back.
* AC8-API-3: "Before proposal" in the demo's Sustainability project: starting the
  proposal of a Shortlisted idea with its checklist open is refused (and the status
  change to Proposal); the admin's override passes through ``create_proposal`` with one
  audit entry, and the proposal has the project's "Carbon impact" section.
* AC8-API-4: "Similar ideas" never shows held ideas (held for moderation or for email
  confirmation, not even to a platform admin), ideas of private projects the viewer
  isn't in, ideas outside an API key's projects or the idea itself; archived projects'
  ideas are included; no score data.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import json
import socket
import uuid
import warnings
from collections.abc import AsyncIterator, Iterator
from typing import Any

import altcha
import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from PIL import ImageFile
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.enums import AiRunKind
from app.models.idea import Idea
from app.models.project import Project
from app.proposals import pdf
from app.proposals.pdf import Renderer
from app.seed import run_seed
from tests.acceptance.test_phase5_acceptance import (
    TOOLS as MCP_TOOLS,
)
from tests.acceptance.test_phase5_acceptance import (
    Person,
    audit,
    call,
    data,
    error,
    key_client,
    mcp_client,
    ok,
    score_data,
)
from tests.ai.helpers import make_agent, open_run

with warnings.catch_warnings():
    # WeasyPrint warns at import where HarfBuzz-Subset is missing (it uses fontTools).
    warnings.simplefilter("ignore", DeprecationWarning)
    try:
        from app.proposals import pdf_child  # noqa: F401 - the renderer must load
    except (ImportError, OSError) as missing:  # pragma: no cover - a host without Pango
        pytest.skip(f"WeasyPrint can't load: {missing}", allow_module_level=True)
# Importing WeasyPrint turns on Pillow's LOAD_TRUNCATED_IMAGES for the whole process
# (tests/proposals/test_exports.py): keep the rest of the session strict.
ImageFile.LOAD_TRUNCATED_IMAGES = False

API = "/api/v1"
CUST, TOOLS, GREEN = "customer-innovation", "internal-tools", "sustainability"
DEFAULT_KEYS = [
    "summary",
    "problem",
    "solution",
    "market",
    "cost",
    "benefits",
    "risks",
    "next_steps",
]
REQUIRED = ["Not already being done elsewhere", "Departments or teams consulted"]
OPTIONAL = "Data protection considered"
FOUND = "Searched Soundings and asked the retail ops channel: nobody wraps gifts at the till."
CONSULTED = (
    "Store operations (north region), 3 Oct: fine for the Christmas weeks.\n"
    "Legal (contracts team): no change to the standard terms."
)

# Markdown-looking text in an answer: exported as typed, never as a link or emphasis.
PRIVACY = "No personal data: see [the DPO's note](https://example.com/dpo) *before* launch."


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
    return {
        "base_urls": [f"http://127.0.0.1:{port}"],
        "dev_login_enabled": True,
        # SMTP "configured" (nothing listens there and no worker runs: emails stay
        # queued), so the public form can ask for an email address and hold an idea
        # for its confirmation (AC8-API-4).
        "smtp_host": "127.0.0.1",
        "smtp_port": 9,
        "smtp_security": "none",
        "smtp_from": "soundings@example.com",
        # The cheapest proof of work the settings allow.
        "altcha_cost": 1_000,
    }


class _Server(uvicorn.Server):
    """uvicorn in the test's event loop, without taking over the process's signals."""

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


@pytest.fixture
def renderer(monkeypatch: pytest.MonkeyPatch) -> Iterator[Renderer]:
    """A PDF child process for this test only (stopped afterwards)."""
    child = Renderer()
    monkeypatch.setattr(pdf, "_renderer", child)
    yield child
    child.stop()


NAMES = ("alice", "amara", "bob", "carol", "dave", "erin", "priya", "sven", "zanele")


@pytest.fixture
async def crew(live: str, seeded: None) -> AsyncIterator[dict[str, Person]]:
    """The demo people this module needs, signed in over TCP, by username."""
    clients: list[httpx.AsyncClient] = []
    anonymous = httpx.AsyncClient(base_url=live, trust_env=False)
    clients.append(anonymous)
    users = {u["email"].split("@")[0]: u for u in ok(await anonymous.get(f"{API}/auth/dev/users"))}
    signed_in: dict[str, Person] = {}
    for username in NAMES:
        http = httpx.AsyncClient(base_url=live, trust_env=False, timeout=60)
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


# --- Helpers ----------------------------------------------------------------------------------
async def refused(
    person: Person | httpx.AsyncClient,
    method: str,
    path: str,
    body: Any = None,
    *,
    status: int,
    code: str,
) -> dict[str, Any]:
    http = person.http if isinstance(person, Person) else person
    response = await http.request(method, f"{API}{path}", json=body)
    assert response.status_code == status, f"{method} {path}: {response.text}"
    problem: dict[str, Any] = response.json()
    assert problem["code"] == code, problem
    assert response.headers["content-type"].startswith("application/problem+json")
    return problem


async def new_idea(person: Person, slug: str, title: str, summary: str) -> str:
    created = await person.send(
        "POST", f"/projects/{slug}/ideas", {"title": title, "summary": summary}, 201
    )
    key: str = created["key"]
    return key


async def set_owner(admin: Person, key: str, owner: Person) -> None:
    await admin.send("PUT", f"/ideas/{key}/owner", {"user_id": owner.id})


async def move(person: Person, key: str, status: str, **extra: Any) -> dict[str, Any]:
    idea: dict[str, Any] = await person.send(
        "POST", f"/ideas/{key}/status", {"status": status, **extra}
    )
    return idea


async def items_by_title(person: Person, key: str) -> dict[str, dict[str, Any]]:
    research = await person.get(f"/ideas/{key}/research")
    return {item["title"]: item for item in research["items"]}


async def answer(person: Person, key: str, item_id: str, text: str) -> dict[str, Any]:
    research: dict[str, Any] = await person.send(
        "PUT", f"/ideas/{key}/research/items/{item_id}", {"answer": text}
    )
    return research


async def markdown(person: Person, key: str) -> str:
    response = await person.http.get(f"{API}/ideas/{key}/proposal/markdown")
    assert response.status_code == 200, response.text
    return response.text


async def pdf_text(person: Person, key: str) -> str:
    response = await person.http.get(f"{API}/ideas/{key}/proposal/pdf", timeout=60)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    reader = PdfReader(io.BytesIO(response.content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def item_inputs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A checklist as read (``ResearchChecklistItem``) as a request's items, ids kept."""
    return [{k: item[k] for k in ("id", "title", "hint", "required")} for item in items]


def headings(text: str, level: str = "## ") -> list[str]:
    return [line[len(level) :] for line in text.splitlines() if line.startswith(level)]


def in_order(text: str, parts: list[str]) -> bool:
    """Whether every part occurs in ``text``, in this order."""
    at = 0
    for part in parts:
        found = text.find(part, at)
        if found < 0:
            return False
        at = found + len(part)
    return True


def flat(text: str) -> str:
    """PDF text with line wraps and hyphenation joined, for substring checks."""
    return " ".join(text.split())


async def make_key(person: Person, scopes: list[str], projects: list[str]) -> str:
    ids = [(await person.get(f"/projects/{slug}"))["id"] for slug in projects]
    created = await person.send(
        "POST",
        "/me/api-keys",
        {"name": f"p8 {uuid.uuid4().hex[:6]}", "scopes": scopes, "project_ids": ids},
        201,
    )
    secret: str = created["secret"]
    return secret


# --- AC8-API-1: the proposal template ---------------------------------------------------------
@pytest.mark.usefixtures("renderer")
async def test_ac8_api_1_a_project_admin_customises_the_proposal_template(
    live: str, crew: dict[str, Person]
) -> None:
    alice, bob, carol, priya = (crew[n] for n in ("alice", "bob", "carol", "priya"))

    # Bob owns a Customer Innovation idea and starts its proposal (no research step here).
    key = await new_idea(
        bob, CUST, "Gift cards in the app", "Sell and redeem gift cards in the mobile app."
    )
    await set_owner(alice, key, bob)
    await move(bob, key, "shortlisted")
    view = await bob.send("POST", f"/ideas/{key}/proposal", None, 201)
    sections = view["proposal"]["sections"]
    assert [s["key"] for s in sections] == DEFAULT_KEYS
    texts = {k: f"{k.replace('_', ' ').capitalize()} text for {key}." for k in DEFAULT_KEYS}
    for section in sections:
        await bob.send(
            "PUT",
            f"/ideas/{key}/proposal/sections/{section['key']}",
            {"body_md": texts[section["key"]], "base_version": section["version"]},
        )

    # The template as the project admin sees it: the default eight, with counts.
    before = await priya.get(f"/projects/{CUST}/proposal-template")
    assert [s["key"] for s in before["sections"]] == DEFAULT_KEYS
    assert before["removed_sections"] == []
    counts = {s["key"]: s["proposal_count"] for s in before["sections"]}
    assert counts["cost"] >= 1
    titles = {s["key"]: (s["title"], s["hint"]) for s in before["sections"]}

    # Priya (project admin, not a platform admin): Risks moves up to second, Market &
    # users is renamed Customers, Cost & effort is removed (it has text), and "Pilot plan"
    # is added at the end.
    def keep(k: str, title: str | None = None, hint: str | None = None) -> dict[str, Any]:
        return {
            "key": k,
            "title": title or titles[k][0],
            "hint": titles[k][1] if hint is None else hint,
        }

    wanted = [
        keep("summary"),
        keep("risks"),
        keep("problem"),
        keep("solution"),
        keep("market", "Customers", "Who buys it, and why they would switch."),
        keep("benefits"),
        keep("next_steps"),
        {"title": "Pilot plan", "hint": "Where we try it first, for how long."},
    ]
    template = await priya.send("PUT", f"/projects/{CUST}/proposal-template", {"sections": wanted})
    new_keys = ["summary", "risks", "problem", "solution", "market", "benefits", "next_steps"]
    assert [s["key"] for s in template["sections"]] == [*new_keys, "pilot_plan"]
    assert [s["position"] for s in template["sections"]] == list(range(8))
    assert template["sections"][4]["title"] == "Customers"
    assert template["sections"][7]["proposal_count"] == 0
    assert [(r["key"], r["title"], r["proposal_count"]) for r in template["removed_sections"]] == [
        ("cost", titles["cost"][0], counts["cost"])
    ]
    cust_id = (await priya.get(f"/projects/{CUST}"))["id"]
    [entry] = await audit(alice, action="project.proposal_template_replace", project_id=cust_id)
    assert entry["actor"]["id"] == priya.id
    assert entry["target_id"] == cust_id
    details = entry["details"]
    assert details["added"] == ["pilot_plan"]
    assert details["archived"] == ["cost"]
    assert details["renamed"] == ["market"]
    assert details["reordered"] is True
    # Never titles or hints in the audit.
    assert "Customers" not in json.dumps(entry)
    assert "Pilot plan" not in json.dumps(entry)

    # The proposal follows at once: the new order, the renamed section's text kept, the
    # new one empty, the removed one hidden.
    proposal = (await bob.get(f"/ideas/{key}/proposal"))["proposal"]
    shown = proposal["sections"]
    assert [s["key"] for s in shown] == [*new_keys, "pilot_plan"]
    by_key = {s["key"]: s for s in shown}
    assert by_key["market"]["title"] == "Customers"
    assert by_key["market"]["prompt"] == "Who buys it, and why they would switch."
    assert by_key["market"]["body_md"] == texts["market"]
    assert (by_key["pilot_plan"]["body_md"], by_key["pilot_plan"]["version"]) == ("", 1)
    assert texts["cost"] not in json.dumps(proposal)
    # A removed key is a clean 4xx everywhere: the section path 404, threads and
    # suggestions 422 unknown_section; an unknown key the same.
    for gone in ("cost", "budget"):
        await refused(
            bob,
            "PUT",
            f"/ideas/{key}/proposal/sections/{gone}",
            {"body_md": "x", "base_version": 1},
            status=404,
            code="not_found",
        )
        await refused(
            bob,
            "POST",
            f"/ideas/{key}/proposal/threads",
            {"section_key": gone, "body_md": "Where does this number come from?"},
            status=422,
            code="unknown_section",
        )
        await refused(
            carol,
            "POST",
            f"/ideas/{key}/proposal/suggestions",
            {"section_key": gone, "body_md": "A better paragraph."},
            status=422,
            code="unknown_section",
        )
    pilot = "Two flagship stores for the Christmas weeks."
    await bob.send(
        "PUT",
        f"/ideas/{key}/proposal/sections/pilot_plan",
        {"body_md": pilot, "base_version": 1},
    )
    thread = await bob.send(
        "POST",
        f"/ideas/{key}/proposal/threads",
        {"section_key": "pilot_plan", "body_md": "Which stores?"},
        201,
    )
    assert thread["section_key"] == "pilot_plan"

    # Markdown: the template's sections in order, no removed section, no appendix (the
    # project has no research step).
    md = await markdown(bob, key)
    assert headings(md) == [
        titles["summary"][0],
        titles["risks"][0],
        titles["problem"][0],
        titles["solution"][0],
        "Customers",
        titles["benefits"][0],
        titles["next_steps"][0],
        "Pilot plan",
    ]
    assert pilot in md
    assert texts["market"] in md
    assert texts["cost"] not in md
    assert titles["cost"][0] not in md
    assert "Research and consultation" not in md

    # The PDF says the same.
    text = flat(await pdf_text(bob, key))
    assert in_order(text, ["Customers", texts["market"], "Pilot plan", pilot])
    assert in_order(text, [texts["summary"], texts["risks"], texts["problem"]])
    assert texts["cost"] not in text
    assert titles["cost"][0] not in text
    assert "Research and consultation" not in text

    # MCP follows the template too: get_proposal lists the active sections (the keys an
    # agent addresses), propose_proposal_section refuses a removed key.
    secret = await make_key(carol, ["write", "mcp"], [CUST])
    async with mcp_client(live, secret) as client:
        got = data(await call(client, "get_proposal", idea=key))
        assert [s["key"] for s in got["proposal"]["sections"]] == [*new_keys, "pilot_plan"]
        assert got["proposal"]["sections"][4]["title"] == "Customers"
        assert got["can_suggest"] is True
        assert (
            error(
                await call(
                    client,
                    "propose_proposal_section",
                    idea=key,
                    section_key="cost",
                    body_md="Cheaper than it looks.",
                )
            )
            == "unknown_section"
        )
        suggested = data(
            await call(
                client,
                "propose_proposal_section",
                idea=key,
                section_key="pilot_plan",
                body_md="Two flagship stores and one small store, for six weeks.",
            )
        )
        assert suggested["suggestion"]["section_key"] == "pilot_plan"
    # An API key never edits the template (session only), even a write key of an admin.
    admin_secret = await make_key(priya, ["write"], [CUST])
    async with key_client(live, admin_secret) as admin_key:
        await refused(
            admin_key,
            "PUT",
            f"/projects/{CUST}/proposal-template",
            {"sections": wanted},
            status=403,
            code="insufficient_scope",
        )
        assert (await admin_key.get(f"{API}/projects/{CUST}/proposal-template")).status_code == 200
    # A member can read the template but not change it.
    await refused(
        bob,
        "PUT",
        f"/projects/{CUST}/proposal-template",
        {"sections": wanted},
        status=403,
        code="forbidden",
    )

    # Restore: putting the key back brings the section and its text back; renaming keeps
    # the key (and the text) of the new section.
    restored = await priya.send(
        "PUT",
        f"/projects/{CUST}/proposal-template",
        {
            "sections": [
                *wanted[:7],
                {"key": "pilot_plan", "title": "Trial plan", "hint": "Where we try it first."},
                keep("cost"),
            ]
        },
    )
    assert [s["key"] for s in restored["sections"]] == [*new_keys, "pilot_plan", "cost"]
    assert restored["removed_sections"] == []
    back = {s["key"]: s for s in (await bob.get(f"/ideas/{key}/proposal"))["proposal"]["sections"]}
    assert back["cost"]["body_md"] == texts["cost"]
    assert back["cost"]["version"] == 2  # the version it had, not a new row
    assert (back["pilot_plan"]["title"], back["pilot_plan"]["body_md"]) == ("Trial plan", pilot)
    md = await markdown(bob, key)
    assert headings(md)[-2:] == ["Trial plan", titles["cost"][0]]
    assert texts["cost"] in md
    # The thread on the renamed section is still there, under its key.
    threads = (await bob.get(f"/ideas/{key}/proposal/threads"))["items"]
    assert [t["section_key"] for t in threads] == ["pilot_plan"]
    # 1-12 sections: none is refused.
    await refused(
        priya,
        "PUT",
        f"/projects/{CUST}/proposal-template",
        {"sections": []},
        status=422,
        code="validation_error",
    )


# --- AC8-API-2: the research gate --------------------------------------------------------------
@pytest.mark.usefixtures("renderer")
async def test_ac8_api_2_the_research_step_gates_every_path_past_research(
    live: str, crew: dict[str, Person], db_session: AsyncSession
) -> None:
    alice, bob, carol, erin, priya = (crew[n] for n in ("alice", "bob", "carol", "erin", "priya"))

    # 1. Priya (project admin of Customer Innovation) turns the step on "Before
    #    evaluation" with the default checklist it offers.
    settings = await priya.get(f"/projects/{CUST}/research")
    assert (settings["step"], settings["items"], settings["ideas_in_research"]) == ("off", [], 0)
    defaults = settings["default_items"]
    assert [(d["title"], d["required"]) for d in defaults] == [
        (REQUIRED[0], True),
        (REQUIRED[1], True),
        (OPTIONAL, False),
    ]
    await refused(
        bob,
        "PUT",
        f"/projects/{CUST}/research",
        {"step": "before_evaluation", "items": defaults},
        status=403,
        code="forbidden",
    )
    on = await priya.send(
        "PUT", f"/projects/{CUST}/research", {"step": "before_evaluation", "items": defaults}
    )
    assert on["step"] == "before_evaluation"
    assert [i["title"] for i in on["items"]] == [*REQUIRED, OPTIONAL]
    project = await bob.get(f"/projects/{CUST}")
    lifecycle = ["new", "research", "evaluating", "shortlisted", "proposal", "closed"]
    assert project["lifecycle"] == lifecycle
    assert project["research_step"] == "before_evaluation"
    board = await bob.get(f"/projects/{CUST}/board")
    assert [c["status"] for c in board["columns"]] == lifecycle
    cust_id: str = project["id"]
    step_changes = await audit(alice, action="project.research_step_change", project_id=cust_id)
    assert [(e["details"]["from"], e["details"]["to"]) for e in step_changes] == [
        ("off", "before_evaluation")
    ]
    [checklist] = await audit(
        alice, action="project.research_checklist_replace", project_id=cust_id
    )
    assert checklist["details"]["added"] == 3

    # 2. Bob owns a new idea and moves it New -> Research (never guarded); its card
    #    shows the progress.
    key = await new_idea(
        bob, CUST, "Gift wrapping at the till", "Wrap presents at the till in December."
    )
    await set_owner(alice, key, bob)
    assert (await bob.get(f"/ideas/{key}"))["research"] == {
        "answered": 0,
        "total": 3,
        "required_open": 2,
    }
    idea = await move(bob, key, "research")
    assert idea["status"] == "research"
    assert idea["permissions"]["can_answer_research"] is True
    board = await bob.get(f"/projects/{CUST}/board")
    column = next(c for c in board["columns"] if c["status"] == "research")
    [card] = [i for i in column["items"] if i["key"] == key]
    assert card["research"] == {"answered": 0, "total": 3, "required_open": 2}

    # 3. Moving on is refused for the owner, with the open required items, and he can't
    #    "Move anyway" (only admins).
    problem = await refused(
        bob,
        "POST",
        f"/ideas/{key}/status",
        {"status": "evaluating"},
        status=409,
        code="research_incomplete",
    )
    assert [i["title"] for i in problem["open_items"]] == REQUIRED
    assert problem["can_override"] is False
    assert problem["detail"] == "Finish the research checklist first: 2 required items are open."
    await refused(
        bob,
        "POST",
        f"/ideas/{key}/status",
        {"status": "evaluating", "override_research": True},
        status=403,
        code="forbidden",
    )
    # Every status past Research is guarded (the board's drag is the same request).
    for gated in ("shortlisted", "proposal"):
        await refused(
            bob,
            "POST",
            f"/ideas/{key}/status",
            {"status": gated},
            status=409,
            code="research_incomplete",
        )
    # The first evaluator invite would start evaluation: guarded, for an admin too
    # (who is told they may override).
    invite = {"user_ids": [carol.id]}
    await refused(
        bob, "POST", f"/ideas/{key}/evaluators", invite, status=409, code="research_incomplete"
    )
    admin_problem = await refused(
        priya, "POST", f"/ideas/{key}/evaluators", invite, status=409, code="research_incomplete"
    )
    assert admin_problem["can_override"] is True
    assert (await bob.get(f"/ideas/{key}"))["permissions"]["invite_blocked_by_research"] is True
    # Straight from New, and reopening an idea closed from New: guarded too.
    other = await new_idea(bob, CUST, "Late-night click and collect", "Collect orders until 10pm.")
    await set_owner(alice, other, bob)
    await refused(
        bob,
        "POST",
        f"/ideas/{other}/status",
        {"status": "evaluating"},
        status=409,
        code="research_incomplete",
    )
    await move(bob, other, "closed", resolution="parked")
    await refused(
        bob,
        "POST",
        f"/ideas/{other}/status",
        {"status": "evaluating"},
        status=409,
        code="research_incomplete",
    )
    # An API key: a write key's status change is refused the same way, and no key may
    # override, not even a platform admin's.
    bob_secret = await make_key(bob, ["write", "mcp"], [CUST])
    alice_secret = await make_key(alice, ["write"], [CUST])
    read_secret = await make_key(bob, ["read"], [CUST])
    async with (
        key_client(live, bob_secret) as bob_key,
        key_client(live, alice_secret) as alice_key,
        key_client(live, read_secret) as read_key,
    ):
        keyed = await refused(
            bob_key,
            "POST",
            f"/ideas/{key}/status",
            {"status": "evaluating"},
            status=409,
            code="research_incomplete",
        )
        assert keyed["can_override"] is False
        for keyed_client in (bob_key, alice_key):
            await refused(
                keyed_client,
                "POST",
                f"/ideas/{key}/status",
                {"status": "evaluating", "override_research": True},
                status=403,
                code="insufficient_scope",
            )
        # Reading needs read; answering is a write-scope operation.
        assert (await read_key.get(f"{API}/ideas/{key}/research")).status_code == 200
        item_id = (await items_by_title(bob, key))[REQUIRED[0]]["item_id"]
        await refused(
            read_key,
            "PUT",
            f"/ideas/{key}/research/items/{item_id}",
            {"answer": FOUND},
            status=403,
            code="insufficient_scope",
        )
        answered = await bob_key.put(
            f"{API}/ideas/{key}/research/items/{item_id}", json={"answer": FOUND}
        )
        assert answered.status_code == 200, answered.text
        assert answered.json()["progress"] == {"answered": 1, "total": 3, "required_open": 1}
    # MCP: get_idea shows the checklist (read only); no tool moves an idea or answers.
    async with mcp_client(live, bob_secret) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        assert tools == MCP_TOOLS
        research = data(await call(client, "get_idea", idea=key))["idea"]["research"]
        assert research["step"] == "before_evaluation"
        assert research["required_open"] == 1
        assert [(i["title"], i["answer"]) for i in research["items"]] == [
            (REQUIRED[0], FOUND),
            (REQUIRED[1], None),
            (OPTIONAL, None),
        ]
        found = data(await call(client, "search_ideas", query="Gift wrapping", status=["research"]))
        assert [i["key"] for i in found["items"]] == [key]
    # An AI agent's key (c22) never answers, even during its own research run.
    cust = await db_session.scalar(select(Project).where(Project.slug == CUST))
    assert cust is not None
    agent = await make_agent(db_session, [cust], key=True, name="p8-researcher")
    assert agent.key is not None
    row = await db_session.scalar(
        select(Idea).where(Idea.project_id == cust.id, Idea.title == "Gift wrapping at the till")
    )
    assert row is not None
    run = await open_run(db_session, agent, row, AiRunKind.RESEARCH)
    await db_session.commit()
    async with key_client(live, agent.key) as agent_key:
        second = (await items_by_title(bob, key))[REQUIRED[1]]["item_id"]
        await refused(
            agent_key,
            "PUT",
            f"/ideas/{key}/research/items/{second}",
            {"answer": "The agent says so."},
            status=403,
            code="insufficient_scope",
        )
    async with mcp_client(live, agent.key) as client:
        seen = data(await call(client, "get_idea", idea=key, run_id=str(run.id)))["idea"]
        assert seen["research"]["required_open"] == 1  # read only, nothing changed
    # Members who aren't the owner, and viewers, read the checklist but can't answer.
    for reader in (carol, erin):
        read = await reader.get(f"/ideas/{key}/research")
        assert read["permissions"] == {"can_answer": False, "can_override": False}
        await refused(
            reader,
            "PUT",
            f"/ideas/{key}/research/items/{second}",
            {"answer": "Me too."},
            status=403,
            code="forbidden",
        )
    # An invisible-only answer is no answer.
    await refused(
        bob,
        "PUT",
        f"/ideas/{key}/research/items/{second}",
        {"answer": "\u200b\u202e "},
        status=422,
        code="validation_error",
    )
    assert (await bob.get(f"/ideas/{key}"))["status"] == "research"

    # 4. The owner answers the second required item, then edits it: the first answer's
    #    author and time are kept.
    first = await answer(bob, key, second, "Store operations: fine.")
    first_answer = next(i for i in first["items"] if i["item_id"] == second)["answer"]
    edited = await answer(bob, key, second, CONSULTED)
    item = next(i for i in edited["items"] if i["item_id"] == second)["answer"]
    assert item["answer"] == CONSULTED
    assert item["answered_by"]["id"] == bob.id
    assert item["answered_at"] == first_answer["answered_at"]
    assert item["updated_at"] >= first_answer["updated_at"]
    assert edited["progress"] == {"answered": 2, "total": 3, "required_open": 0}
    assert edited["blocking"] is False

    # 5. Now it moves on, with no override and no audit entry.
    assert (await move(bob, key, "evaluating"))["status"] == "evaluating"
    assert await audit(alice, action="idea.research_override", project_id=cust_id) == []
    # Clearing an answer afterwards never moves it back; the card shows no progress
    # past Research.
    cleared = await bob.send("DELETE", f"/ideas/{key}/research/items/{second}")
    assert cleared["progress"]["required_open"] == 1
    assert cleared["blocking"] is False
    after = await bob.get(f"/ideas/{key}")
    assert (after["status"], after["research"]) == ("evaluating", None)
    await answer(bob, key, second, CONSULTED)

    # 6. "Move anyway": a project admin moves another idea on with its checklist open;
    #    audited with the reason, and the feed marks the move.
    rushed = await new_idea(bob, CUST, "Gift wrap station kiosks", "Self-service wrapping kiosks.")
    await set_owner(alice, rushed, bob)
    await move(bob, rushed, "research")
    moved = await move(
        priya,
        rushed,
        "evaluating",
        override_research=True,
        override_reason="Legal agreed on a call; notes to follow",
    )
    assert moved["status"] == "evaluating"
    [entry] = await audit(alice, action="idea.research_override", project_id=cust_id)
    assert entry["actor"]["id"] == priya.id
    assert (entry["target_type"], entry["target_id"]) == ("idea", moved["id"])
    assert {
        k: entry["details"][k]
        for k in ("operation", "from_status", "to_status", "open_items", "reason")
    } == {
        "operation": "change_idea_status",
        "from_status": "research",
        "to_status": "evaluating",
        "open_items": 2,
        "reason": "Legal agreed on a call; notes to follow",
    }
    feed = (await bob.get(f"/ideas/{rushed}/activity?limit=5"))["items"]
    change = next(i for i in feed if i["type"] == "status_changed")
    assert (change["to_status"], change["research_overridden"]) == ("evaluating", True)
    # The first invite with "Invite anyway" (a platform admin this time): audited too.
    waiting = await new_idea(bob, CUST, "Gift receipts by email", "Email a gift receipt.")
    await set_owner(alice, waiting, bob)
    await alice.send(
        "POST",
        f"/ideas/{waiting}/evaluators",
        {"user_ids": [carol.id], "override_research": True},
    )
    entries = await audit(alice, action="idea.research_override", project_id=cust_id)
    assert [
        (e["details"]["operation"], e["details"]["from_status"], e["details"]["to_status"])
        for e in entries
    ] == [
        ("add_evaluators", "new", "new"),
        ("change_idea_status", "research", "evaluating"),
    ]
    # The flag changes nothing when nothing blocks: no audit entry.
    await move(priya, key, "shortlisted", override_research=True)
    assert len(await audit(alice, action="idea.research_override", project_id=cust_id)) == 2

    # 7. The step can't move or switch off while an idea is in Research.
    parked = await new_idea(bob, CUST, "Gift bags for loyalty members", "A bag at checkout.")
    await set_owner(alice, parked, bob)
    await move(bob, parked, "research")
    conflict = await refused(
        priya,
        "PUT",
        f"/projects/{CUST}/research",
        {"step": "off"},
        status=409,
        code="ideas_in_research",
    )
    assert conflict["idea_count"] == 1
    await refused(
        priya,
        "PUT",
        f"/projects/{CUST}/research",
        {"step": "before_proposal", "items": item_inputs(on["items"])},
        status=409,
        code="ideas_in_research",
    )
    assert (await priya.get(f"/projects/{CUST}/research"))["ideas_in_research"] == 1
    await move(bob, parked, "new")  # moving back is never guarded

    optional_id = (await items_by_title(bob, key))[OPTIONAL]["item_id"]
    await answer(bob, key, optional_id, PRIVACY)

    # 8. The exports end with "Research and consultation" while the step is on.
    view = await bob.send("POST", f"/ideas/{key}/proposal", None, 201)
    assert view["proposal"] is not None
    md = await markdown(bob, key)
    assert headings(md)[-1] == "Research and consultation"
    appendix = md.split("## Research and consultation", 1)[1]
    assert headings(appendix, "### ") == [*REQUIRED, OPTIONAL]
    assert "Answered by Bob Brown" in appendix
    # Plain text as typed: line breaks are hard breaks, Markdown syntax is escaped.
    assert f"{CONSULTED.splitlines()[0]}\\\n{CONSULTED.splitlines()[1]}" in appendix
    assert "see \\[the DPO's note\\](https://example.com/dpo) \\*before\\* launch" in appendix
    assert "<a " not in md
    text = flat(await pdf_text(bob, key))
    assert in_order(text, ["Research and consultation", REQUIRED[0], FOUND, REQUIRED[1]])
    assert "Answered by Bob Brown" in text
    # Evaluators (pending ones too) read the answers on the idea page.
    assert (await carol.get(f"/ideas/{rushed}/research"))["items"][0]["title"] == REQUIRED[0]

    # 9. Switched off: no Research anywhere in the project, answers and checklist kept.
    off = await priya.send("PUT", f"/projects/{CUST}/research", {"step": "off", "items": []})
    assert off["step"] == "off"
    assert [i["title"] for i in off["items"]] == [*REQUIRED, OPTIONAL]
    assert (await bob.get(f"/projects/{CUST}"))["lifecycle"] == [
        "new",
        "evaluating",
        "shortlisted",
        "proposal",
        "closed",
    ]
    assert "research" not in [
        c["status"] for c in (await bob.get(f"/projects/{CUST}/board"))["columns"]
    ]
    await refused(
        bob,
        "POST",
        f"/ideas/{parked}/status",
        {"status": "research"},
        status=409,
        code="research_step_off",
    )
    await refused(
        bob,
        "PUT",
        f"/ideas/{parked}/research/items/{second}",
        {"answer": "x"},
        status=409,
        code="research_step_off",
    )
    assert (await bob.get(f"/ideas/{parked}"))["research"] is None
    assert "Research and consultation" not in await markdown(bob, key)
    # On again with the same items: the answers come back.
    again = await priya.send(
        "PUT",
        f"/projects/{CUST}/research",
        {"step": "before_evaluation", "items": item_inputs(off["items"])},
    )
    assert [i["id"] for i in again["items"]] == [i["id"] for i in on["items"]]
    back = await bob.get(f"/ideas/{key}/research")
    assert [i["answer"]["answer"] if i["answer"] else None for i in back["items"]] == [
        FOUND,
        CONSULTED,
        PRIVACY,
    ]


# --- AC8-API-3: "Before proposal" (the demo's Sustainability project) --------------------------
async def test_ac8_api_3_starting_a_proposal_waits_for_the_research_before_the_proposal(
    live: str, crew: dict[str, Person]
) -> None:
    alice, amara, zanele = (crew[n] for n in ("alice", "amara", "zanele"))
    green = await amara.get(f"/projects/{GREEN}")
    assert green["research_step"] == "before_proposal"
    assert green["lifecycle"] == [
        "new",
        "evaluating",
        "shortlisted",
        "research",
        "proposal",
        "closed",
    ]
    # GREEN-6: Shortlisted (the status before Research here), its checklist started.
    idea = await amara.get("/ideas/GREEN-6")
    assert idea["status"] == "shortlisted"
    assert idea["research"] is not None
    assert idea["research"]["required_open"] >= 1
    view = await amara.get("/ideas/GREEN-6/proposal")
    assert view["permissions"]["start_blocked_by_research"] is True
    problem = await refused(
        amara, "POST", "/ideas/GREEN-6/proposal", None, status=409, code="research_incomplete"
    )
    assert problem["can_override"] is True  # amara is the project's admin
    await refused(
        amara,
        "POST",
        "/ideas/GREEN-6/status",
        {"status": "proposal"},
        status=409,
        code="research_incomplete",
    )
    # Into Research is free; on from there to Proposal is guarded.
    await move(amara, "GREEN-6", "research")
    await refused(
        amara, "POST", "/ideas/GREEN-6/proposal", None, status=409, code="research_incomplete"
    )
    # A member who isn't the owner can't start it anyway (c7) nor override.
    await refused(
        zanele,
        "POST",
        "/ideas/GREEN-6/proposal",
        {"override_research": True},
        status=403,
        code="forbidden",
    )
    # "Start anyway": create_proposal passes the override through its move, one audit
    # entry, and the proposal follows Sustainability's template with Carbon impact.
    started = await amara.send("POST", "/ideas/GREEN-6/proposal", {"override_research": True}, 201)
    keys = [s["key"] for s in started["proposal"]["sections"]]
    assert keys == [
        "summary",
        "problem",
        "solution",
        "market",
        "cost",
        "benefits",
        "carbon_impact",
        "risks",
        "next_steps",
    ]
    assert (await amara.get("/ideas/GREEN-6"))["status"] == "proposal"
    [entry] = await audit(alice, action="idea.research_override", project_id=green["id"])
    assert (
        entry["details"]["operation"],
        entry["details"]["from_status"],
        entry["details"]["to_status"],
    ) == (
        "create_proposal",
        "research",
        "proposal",
    )
    feed = (await amara.get("/ideas/GREEN-6/activity?limit=5"))["items"]
    change = next(i for i in feed if i["type"] == "status_changed")
    assert (change["from_status"], change["to_status"], change["research_overridden"]) == (
        "research",
        "proposal",
        True,
    )
    # GREEN-4's seeded proposal: Carbon impact written, then the research appendix.
    md = await markdown(amara, "GREEN-4")
    names = headings(md)
    assert "Carbon impact" in names
    assert names[-1] == "Research and consultation"


# --- AC8-API-4: "Similar ideas" ----------------------------------------------------------------
def solve(challenge: dict[str, Any]) -> str:
    """The ALTCHA widget's answer: the solved challenge as base64 JSON."""
    parsed = altcha.Challenge.from_dict(challenge)
    solution = altcha.solve_challenge(parsed)
    assert solution is not None
    return base64.b64encode(
        json.dumps(altcha.Payload(parsed, solution).to_dict()).encode()
    ).decode()


async def test_ac8_api_4_similar_ideas_never_shows_held_or_private_ideas(
    live: str, crew: dict[str, Person]
) -> None:
    alice, bob, carol, dave = (crew[n] for n in ("alice", "bob", "carol", "dave"))
    title = "Repair café in the flagship store"
    summary = "Once a month, volunteers help customers fix small appliances and clothes."
    # The demo's public form holds "Repair café in the flagship store" for moderation.
    queue = await alice.get(f"/projects/{CUST}/moderation")
    held_moderation = [i["key"] for i in queue["items"]]
    assert "Repair café in the flagship store" in [i["title"] for i in queue["items"]]
    # Another arrives through the public form, held until its sender confirms the email.
    await alice.send("PATCH", f"/projects/{CUST}/public-form", {"require_email_verification": True})
    async with httpx.AsyncClient(base_url=live, trust_env=False) as visitor:
        challenge = ok(await visitor.get(f"{API}/public/projects/{CUST}/altcha"))
        receipt = ok(
            await visitor.post(
                f"{API}/public/projects/{CUST}/submissions",
                json={
                    "title": "Repair café in the flagship store every month",
                    "summary": summary,
                    "email": "jo.public@example.com",
                    "altcha": solve(challenge),
                    "website": "",
                },
            ),
            201,
        )
    assert receipt["held_for"] == "email_verification"

    # Bob's idea in Customer Innovation (internal: everyone can view it).
    mine = await new_idea(bob, CUST, f"{title} on Saturdays", summary)
    # Internal Tools is private: Dave (admin) and Carol (member) are in it, Bob isn't.
    private = await new_idea(
        dave, TOOLS, f"{title} for staff laptops", "Fix staff laptops at a monthly repair café."
    )
    # An archived project's idea is still evidence that it was tried.
    old = await alice.send(
        "POST",
        "/projects",
        {
            "name": "Old pilots",
            "slug": f"old-pilots-{uuid.uuid4().hex[:4]}",
            "key": "OLDP",
            "visibility": "internal",
        },
        201,
    )
    archived = await new_idea(alice, old["slug"], f"{title} pilot (2024)", summary)
    await alice.send("PATCH", f"/projects/{old['slug']}", {"archived": True})

    async def similar(person: Person | httpx.AsyncClient) -> list[dict[str, Any]]:
        http = person.http if isinstance(person, Person) else person
        response = await http.get(f"{API}/ideas/{mine}/similar-ideas")
        assert response.status_code == 200, response.text
        items: list[dict[str, Any]] = response.json()["items"]
        return items

    held_titles = {
        "Repair café in the flagship store",
        "Repair café in the flagship store every month",
    }
    for viewer in (alice, bob, carol, dave):
        items = await similar(viewer)
        keys = [i["key"] for i in items]
        assert len(items) <= 5
        assert mine not in keys
        assert not held_titles & {i["title"] for i in items}, (viewer.name, items)
        assert not set(held_moderation) & set(keys)
        assert archived in keys, (viewer.name, items)
        assert all(0.3 <= i["similarity"] <= 1 for i in items)
        assert [i["similarity"] for i in items] == sorted(
            (i["similarity"] for i in items), reverse=True
        )
        assert score_data(items) == []
        assert not {"score", "aggregate", "evaluations"} & set().union(*(i.keys() for i in items))
    # The private project's idea: only for people in it.
    assert private not in [i["key"] for i in await similar(bob)]
    assert private in [i["key"] for i in await similar(carol)]
    assert private in [i["key"] for i in await similar(dave)]
    # A key restricted to Customer Innovation doesn't see Internal Tools, even Carol's.
    secret = await make_key(carol, ["read"], [CUST])
    async with key_client(live, secret) as carol_key:
        assert private not in [i["key"] for i in await similar(carol_key)]
    # Held ideas are 404 even by key, and never listed; approving one makes it findable.
    first_held = next(i["key"] for i in queue["items"] if i["title"] == title)
    await alice.send("POST", f"/ideas/{first_held}/submission/approve")
    approved = [i["key"] for i in await similar(alice)]
    assert first_held in approved
