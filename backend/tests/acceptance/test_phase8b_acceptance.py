"""Phase 8b acceptance against a live server (QA; docs/test-plans/phase-8b.md, AC8B-API-*).

The product owner's Phase 8b change (decisions "Phase 8b (product owner, 2026-10-08)",
contract-phase8b): **C**, an idea's research assigned to one person, its researcher, who
may be outside the idea's project. A researcher without a role in a **private** project is
the idea's **guest** (role matrix column R, table L): that one idea, its feed without the
evaluation events, comments and the research checklist; never score data, the evaluation,
the proposal, the AI panel or anything of the project.

The app runs behind a real **uvicorn** on a free port with the demo data (``soundings
seed``) and the dev login; people use the REST API over TCP with their session cookie and
CSRF header, API keys are bearer tokens with no cookie, MCP is the official Python SDK
client. Email goes through a **real Mailpit** (the Phase 3 acceptance's fixtures: a
container, or ``SOUNDINGS_TEST_MAILPIT_SMTP``/``_URL`` as in CI), sent by the worker's own
job code; the hourly schedule is driven with a moved clock, so the reminders fire without
waiting days. The few database touches are arrangements the API has no route for (an AI
agent's service account, its open runs and its evaluator seat).

* AC8B-API-1: a project admin who owns a private project's idea (with two submitted
  evaluations and an AI evaluation) asks Nora, a new account in no project at all, to
  research it with a due date. Refusals first (c25 for a plain owner, c23, keys). Nora
  gets "Asked to research" through Mailpit (the guest line, the Research link, no score
  data), opens the idea and reaches exactly what table L allows: every idea route is
  probed (view, rule, hidden), every project route is 404, lists show the idea and
  nothing else of the project, MCP with her key never more than REST. The research
  reminder fires two days before at the digest hour (not the day before, not twice) and
  stops once she has answered; the gate then lets the owner move the idea (never her).
  Reassigning ends her access on the next request (REST and MCP, search, My work, the
  inbox); the next researcher hands it back; deactivation clears an assignment for good.
* AC8B-API-2: the AI event stream. A guest researcher can't open one (404); a member
  researcher's open stream ends at the next re-check once they lose their role in the
  private project, which also ends the assignment (``left_project``).
* AC8B-API-3: the demo story: bob is TOOLS-12's guest researcher (due in 3 days, asked by
  dave), amara researches GREEN-6, alice's GREEN-5 is overdue; the team sees "not in this
  project"; a plain owner may not name an outsider; a key restricted to bob's own projects
  never reaches TOOLS-12; My work's owned groups hold their first 10 ideas (D).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from procrastinate import App
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import sse
from app.config import Settings
from app.db import session_scope
from app.email import delivery
from app.email.delivery import Runtime
from app.models.base import utcnow
from app.models.enums import AiRunKind, EmailStatus, EmailType
from app.models.idea import Idea
from app.models.notification import OutboundEmail
from app.models.project import Project
from app.notifications.fanout import RESEARCHER_EMAIL_HOLD
from app.notifications.schedule import send_research_reminders
from app.schemas.activity import EVALUATION_ACTIVITY_TYPES, RESEARCH_GUEST_ACTIVITY_TYPES
from app.schemas.notifications import RESEARCH_GUEST_NOTIFICATION_TYPES
from app.seed import run_seed
from tests.acceptance import test_phase3_acceptance as phase3
from tests.acceptance.test_phase3_acceptance import (
    SCORE_NUMBER,
    SCORE_WORDS,
    Clock,
    MailpitInbox,
    Smtp,
    run_worker_once,
    visible_text,
)
from tests.acceptance.test_phase5_acceptance import (
    call,
    data,
    error,
    key_client,
    mcp_client,
    score_data,
)
from tests.ai.helpers import make_agent, open_run
from tests.factories import add_evaluator

API = "/api/v1"
ZONE = "Europe/London"
TOOLS, CUST, GREEN = "internal-tools", "customer-innovation", "sustainability"
TITLE = "Badge reader for the bike shed"
SUMMARY = "Open the bike shed with the staff badge instead of a shared key."
REQUIRED = ["Not already being done elsewhere", "Departments or teams consulted"]
OPTIONAL = "Data protection considered"
# The email's line for a guest researcher (contract-phase8b section 6.2, review S2). It
# names what a guest never sees, so the score-word check below leaves it out.
GUEST_LINE = (
    "You'll see this idea, its comments and activity and its research checklist, not its "
    "scores, evaluations or proposal."
)
# The Phase 3 acceptance's Mailpit (a container, or CI's) and worker fixtures, by name.
mailpit = phase3.mailpit
smtp = phase3.smtp
inbox = phase3.inbox
jobs = phase3.jobs
clock = phase3.clock
runtime = phase3.runtime
NAMES = ("alice", "bob", "carol", "dave", "erin", "farah", "kenji", "sven", "amara")


# --- A live server ------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def port() -> int:
    return _free_port()


@pytest.fixture
def settings_overrides(port: int, smtp: Smtp) -> dict[str, Any]:
    return {
        # The live server's own URL: the trusted-host check and every link in an email.
        "base_urls": [f"http://127.0.0.1:{port}"],
        "dev_login_enabled": True,
        "smtp_host": smtp.host,
        "smtp_port": smtp.port,
        "smtp_security": "none",
        "smtp_from": "soundings@example.com",
        "smtp_from_name": "Soundings",
        "smtp_timeout": 3,
        "timezone": ZONE,
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


# --- People -----------------------------------------------------------------------------
def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, f"{response.request.url}: {response.text}"
    return response.json() if response.content else None


@dataclass
class Person:
    """One person signed in with the dev login over TCP (cookie + CSRF header)."""

    http: httpx.AsyncClient
    id: str
    name: str
    email: str

    async def get(self, path: str) -> Any:
        return ok(await self.http.get(f"{API}{path}"))

    async def send(self, method: str, path: str, body: Any = None, status: int = 200) -> Any:
        return ok(await self.http.request(method, f"{API}{path}", json=body), status)

    async def status(self, method: str, path: str, body: Any = None) -> int:
        return (await self.http.request(method, f"{API}{path}", json=body)).status_code


class Crew(dict[str, Person]):
    """The demo people this module needs plus Nora, a new account in no project."""

    def __init__(self, live: str) -> None:
        super().__init__()
        self.live = live
        self.clients: list[httpx.AsyncClient] = []

    async def sign_in(self, user_id: str, name: str, email: str) -> Person:
        http = httpx.AsyncClient(base_url=self.live, trust_env=False, timeout=60)
        self.clients.append(http)
        ok(await http.post(f"{API}/auth/dev/login", json={"user_id": user_id}))
        http.headers["X-CSRF-Token"] = http.cookies["soundings_csrf"]
        return Person(http, user_id, name, email)


@pytest.fixture
async def crew(live: str, seeded: None) -> AsyncIterator[Crew]:
    people = Crew(live)
    anonymous = httpx.AsyncClient(base_url=live, trust_env=False)
    people.clients.append(anonymous)
    users = {u["email"].split("@")[0]: u for u in ok(await anonymous.get(f"{API}/auth/dev/users"))}
    try:
        for username in NAMES:
            user = users[username]
            people[username] = await people.sign_in(user["id"], user["display_name"], user["email"])
        # Nora: anyone with a Soundings account may research, even someone in no project.
        email = f"nora.{uuid.uuid4().hex[:6]}@example.com"
        created = await people["alice"].send(
            "POST", "/admin/users", {"email": email, "display_name": "Nora Quinn"}, 201
        )
        people["nora"] = await people.sign_in(created["id"], "Nora Quinn", email)
        yield people
    finally:
        for http in people.clients:
            await http.aclose()


# --- Helpers ----------------------------------------------------------------------------
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
    return problem


async def audit(alice: Person, **filters: str) -> list[dict[str, Any]]:
    query = "&".join(f"{name}={value}" for name, value in {"limit": "100", **filters}.items())
    page = await alice.get(f"/admin/audit?{query}")
    items: list[dict[str, Any]] = page["items"]
    return items


async def researcher_changes(alice: Person, idea_id: str) -> list[dict[str, Any]]:
    entries = await audit(alice, action="idea.researcher_change")
    return [entry for entry in entries if entry["target_id"] == idea_id]


async def assign(
    person: Person, key: str, researcher: Person | None, due: datetime | None
) -> dict[str, Any]:
    research: dict[str, Any] = await person.send(
        "PUT",
        f"/ideas/{key}/research/assignment",
        {
            "researcher_id": researcher.id if researcher else None,
            "due_at": due.isoformat() if due else None,
        },
    )
    return research


async def items_by_title(person: Person, key: str) -> dict[str, dict[str, Any]]:
    research = await person.get(f"/ideas/{key}/research")
    return {item["title"]: item for item in research["items"]}


async def answer(person: Person, key: str, item_id: str, text: str) -> dict[str, Any]:
    research: dict[str, Any] = await person.send(
        "PUT", f"/ideas/{key}/research/items/{item_id}", {"answer": text}
    )
    return research


async def feed(person: Person, key: str) -> list[dict[str, Any]]:
    page = await person.get(f"/ideas/{key}/activity?limit=100")
    items: list[dict[str, Any]] = page["items"]
    return items


async def inbox_items(person: Person) -> list[dict[str, Any]]:
    page = await person.get("/me/notifications?limit=100")
    items: list[dict[str, Any]] = page["items"]
    return items


def idea_keys(value: Any) -> set[str]:
    """Every idea key (``ABC-12``) anywhere in a JSON value."""
    found: set[str] = set()
    if isinstance(value, dict):
        for name, item in value.items():
            if name == "key" and isinstance(item, str) and "-" in item:
                found.add(item)
            else:
                found |= idea_keys(item)
    elif isinstance(value, list):
        for item in value:
            found |= idea_keys(item)
    return found


def project_slugs(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for name, item in value.items():
            if name == "slug" and isinstance(item, str):
                found.add(item)
            else:
                found |= project_slugs(item)
    elif isinstance(value, list):
        for item in value:
            found |= project_slugs(item)
    return found


def day(moment: datetime) -> str:
    local = moment.astimezone(ZoneInfo(ZONE))
    return f"{local:%a} {local.day} {local:%b}"


def at_digest_hour(local_day: datetime, settings: Settings, minute: int = 30) -> datetime:
    """``minute`` past the digest hour on that local day, in UTC."""
    zone = ZoneInfo(ZONE)
    moment = datetime.combine(local_day.date(), datetime.min.time(), tzinfo=zone).replace(
        hour=settings.digest_hour, minute=minute
    )
    return moment.astimezone(UTC)


async def remind(app: FastAPI, settings: Settings, now: datetime) -> int:
    """The hourly schedule's research reminders at ``now`` (the job's first step, in its
    own session as ``run_schedule`` opens it; the rest of the job, such as deleting
    sessions that would have expired by then, isn't run)."""
    async with session_scope(app.state.sessionmaker, settings=settings) as db:
        return await send_research_reminders(db, settings, now)


def assert_no_score_data_in_email(*parts: str) -> None:
    """No score words or 1-decimal numbers, outside the guest line (which names them)."""
    for part in parts:
        text = part.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'").replace(GUEST_LINE, "")
        assert not SCORE_WORDS.search(text), SCORE_WORDS.search(text)
        assert not SCORE_NUMBER.search(text), SCORE_NUMBER.search(text)


async def emails_to(db: AsyncSession, user_id: str, type_: str) -> list[OutboundEmail]:
    rows = await db.scalars(
        select(OutboundEmail)
        .where(OutboundEmail.recipient_user_id == uuid.UUID(user_id))
        .order_by(OutboundEmail.created_at)
        .execution_options(populate_existing=True)
    )
    await db.commit()
    return [row for row in rows if row.type.value == type_]


async def send_queued(
    db: AsyncSession, runtime: Runtime, clock: Clock, user_id: str, type_: str, at: datetime
) -> int:
    """Delivers this person's queued emails of this type as the worker would at ``at``."""
    sent = 0
    clock.now = at
    for row in await emails_to(db, user_id, type_):
        if row.status == EmailStatus.QUEUED:
            assert await delivery.send_email(runtime, row.id) == "sent"
            sent += 1
    clock.now = None
    return sent


async def make_key(person: Person, scopes: list[str], projects: list[str] | None) -> str:
    created = await person.send(
        "POST",
        "/me/api-keys",
        {
            "name": f"p8b {uuid.uuid4().hex[:6]}",
            "scopes": scopes,
            "project_ids": projects,
        },
        201,
    )
    secret: str = created["secret"]
    return secret


async def rubric_ids(person: Person, slug: str) -> list[str]:
    project = await person.get(f"/projects/{slug}")
    return [criterion["id"] for criterion in project["rubric"]]


async def evaluate(person: Person, key: str, criteria: list[str], score: int) -> None:
    await person.send(
        "PUT",
        f"/ideas/{key}/evaluations/me",
        {
            "scores": [{"criterion_id": c, "score": score} for c in criteria],
            "recommendation": "go",
            "comment": "Private rationale of a person",
            "submit": True,
        },
    )


@dataclass
class World:
    """A TOOLS idea owned by Dave (project admin) with score data on it, in Research."""

    key: str
    idea_id: str
    tools_id: str
    agent_id: str
    agent_user_id: str
    evaluation_id: str
    research_run: str
    note_id: str
    other_tools_title: str


async def arrange(crew: Crew, db: AsyncSession, live: str) -> World:
    dave, carol, kenji = crew["dave"], crew["carol"], crew["kenji"]
    created = await dave.send(
        "POST", f"/projects/{TOOLS}/ideas", {"title": TITLE, "summary": SUMMARY}, 201
    )
    key: str = created["key"]
    await dave.send("PUT", f"/ideas/{key}/owner", {"user_id": dave.id})
    # Score data first: Dave (an admin) moves it on anyway, Carol and Kenji submit...
    await dave.send(
        "POST",
        f"/ideas/{key}/status",
        {"status": "evaluating", "override_research": True, "override_reason": "Arranging"},
    )
    await dave.send("POST", f"/ideas/{key}/evaluators", {"user_ids": [carol.id, kenji.id]})
    criteria = await rubric_ids(dave, TOOLS)
    await evaluate(carol, key, criteria, 5)
    await evaluate(kenji, key, criteria, 2)

    # ... and an AI agent evaluates during its evaluate run, then writes a research note.
    tools = await db.scalar(select(Project).where(Project.slug == TOOLS))
    assert tools is not None
    row = await db.scalar(select(Idea).where(Idea.id == uuid.UUID(created["id"])))
    assert row is not None
    agent = await make_agent(db, [tools], key=True, name="p8b-evaluator")
    await add_evaluator(db, row, agent.user)
    evaluate_run = await open_run(db, agent, row, AiRunKind.EVALUATE)
    research_run = await open_run(db, agent, row, AiRunKind.RESEARCH)
    await db.commit()
    assert agent.key is not None
    async with mcp_client(live, agent.key) as client:
        rubric = data(await call(client, "get_rubric", idea=key, run_id=str(evaluate_run.id)))
        scores = [
            {
                "criterion_id": criterion["id"],
                "score": 4,
                "comment": f"AI RATIONALE {criterion['name']}",
                "sources": [{"title": "A source", "url": "https://example.org/badge"}],
            }
            for criterion in rubric["criteria"]
        ]
        data(
            await call(
                client,
                "submit_evaluation",
                idea=key,
                scores=scores,
                recommendation="maybe",
                comment="AI SUMMARY",
                run_id=str(evaluate_run.id),
            )
        )
        note = data(
            await call(
                client,
                "add_research_note",
                idea=key,
                body_md="Facilities already run badge readers on two doors.",
                run_id=str(research_run.id),
            )
        )
    # Back to Research (never guarded): the checklist is still open.
    await dave.send("POST", f"/ideas/{key}/status", {"status": "research"})
    detail = await dave.get(f"/ideas/{key}")
    assert detail["status"] == "research"
    assert detail["score"] is not None or detail["aggregate"] is not None, detail
    evaluations = (await dave.get(f"/ideas/{key}/evaluations"))["items"]
    assert len(evaluations) == 3, evaluations  # two people and the AI evaluator
    other = await dave.send(
        "POST",
        f"/projects/{TOOLS}/ideas",
        {"title": "Badge printer for visitors", "summary": "Print visitor badges at reception."},
        201,
    )
    return World(
        key=key,
        idea_id=created["id"],
        tools_id=str(tools.id),
        agent_id=str(agent.id),
        agent_user_id=str(agent.user.id),
        evaluation_id=evaluations[0]["id"],
        research_run=str(research_run.id),
        note_id=str(note["note_id"]),
        other_tools_title=other["title"],
    )


GUEST_GRANTS = frozenset({"can_comment", "can_answer_research", "can_hand_back_research"})


def assert_guest_shape(detail: dict[str, Any], granted: frozenset[str] = GUEST_GRANTS) -> None:
    """``get_idea`` for column R (contract-phase8b section 4.4); ``granted``: the
    permission flags that are true (a read-only key: none)."""
    assert detail["score"] is None
    assert detail["aggregate"] is None
    assert detail["score_hidden"] is True
    assert detail["high_disagreement"] is False
    assert detail["evaluators"] == []
    assert detail["evaluator_progress"] == {"submitted": 0, "total": 0}
    assert detail["evaluation_due_at"] is None
    assert detail["evaluation_closed_at"] is None
    assert detail["evaluation_open"] is False
    permissions = detail["permissions"]
    flags = {name for name, value in permissions.items() if value is True}
    assert flags == granted, flags
    assert score_data(detail) == []


# --- AC8B-API-1 -------------------------------------------------------------------------------
async def test_ac8b_api_1_an_outside_researcher_sees_one_idea_and_nothing_else(
    live: str,
    app: FastAPI,
    settings: Settings,
    crew: Crew,
    db_session: AsyncSession,
    jobs: App,
    runtime: Runtime,
    clock: Clock,
    inbox: MailpitInbox,
) -> None:
    alice, dave, sven, erin = crew["alice"], crew["dave"], crew["sven"], crew["erin"]
    farah, nora = crew["farah"], crew["nora"]
    world = await arrange(crew, db_session, live)
    key = world.key

    # Before anyone is assigned the owner does the research: Dave's My work lists it.
    work = await dave.get("/me/work")
    [mine] = [item for item in work["research_to_do"] if item["idea"]["key"] == key]
    assert mine["as_owner"] is True
    assert mine["progress"]["required_open"] == 2
    assert (await nora.get("/me/work"))["research_to_do"] == []
    # In no project: she sees the internal ones (as everyone does), never Internal Tools.
    assert TOOLS not in project_slugs(await nora.get("/projects"))

    # --- Refusals --------------------------------------------------------------------------
    zone = ZoneInfo(ZONE)
    local_due = (datetime.now(zone) + timedelta(days=5)).replace(
        hour=17, minute=0, second=0, microsecond=0
    )
    due = local_due.astimezone(UTC)
    # c25: a plain owner (Sven owns TOOLS-12) may not open a private idea to an outsider.
    await refused(
        sven,
        "PUT",
        "/ideas/TOOLS-12/research/assignment",
        {"researcher_id": erin.id, "due_at": None},
        status=403,
        code="outside_researcher_needs_admin",
    )
    # c23: never a service account (the AI agent) or an unknown account.
    for nobody in (world.agent_user_id, str(uuid.uuid4())):
        await refused(
            dave,
            "PUT",
            f"/ideas/{key}/research/assignment",
            {"researcher_id": nobody, "due_at": None},
            status=422,
            code="researcher_not_eligible",
        )
    # Assigning is session only (review M3): Dave's write key is refused before anything.
    async with key_client(live, await make_key(dave, ["write"], None)) as dave_key:
        await refused(
            dave_key,
            "PUT",
            f"/ideas/{key}/research/assignment",
            {"researcher_id": nora.id, "due_at": None},
            status=403,
            code="insufficient_scope",
        )
    # Nora can't name herself (she can't even see the idea yet).
    assert await nora.status("GET", f"/ideas/{key}") == 404

    # --- Dave asks Nora to research it, due in five days -----------------------------------
    research = await assign(dave, key, nora, due)
    assignment = research["assignment"]
    assert assignment["researcher"]["id"] == nora.id
    assert assignment["researcher_in_project"] is False
    assert datetime.fromisoformat(assignment["due_at"]) == due
    assert research["permissions"]["can_assign"] is True
    assert research["permissions"]["can_assign_outside_researcher"] is True
    [entry] = await researcher_changes(alice, world.idea_id)
    assert entry["details"]["reason"] == "assigned"
    assert entry["details"]["to_user_id"] == nora.id
    assert entry["details"]["outside_project"] is True
    types = [item["type"] for item in await feed(dave, key)]
    assert types.count("researcher_changed") == 1
    assert types.count("research_due_date_changed") == 1
    # The same state again changes nothing: no event, audit entry or notification.
    await assign(dave, key, nora, due)
    assert len(await researcher_changes(alice, world.idea_id)) == 1
    assert [item["type"] for item in await feed(dave, key)].count("researcher_changed") == 1
    # Dave's My work hands it to Nora.
    assert key not in idea_keys((await dave.get("/me/work"))["research_to_do"])

    # --- "Asked to research" through Mailpit -----------------------------------------------
    await run_worker_once(jobs, runtime)
    [summary] = await inbox.wait_for(nora.email)
    message = await inbox.message(summary["ID"])
    assert message["Subject"] == f'[{key}] Please research "{TITLE}" by {day(due)}'
    html, plain = visible_text(message["HTML"]), message["Text"]
    research_link = f"{live}/ideas/{key}?research=1"
    assert research_link in plain
    assert f'href="{research_link}"' in message["HTML"].replace("&amp;", "&")
    assert GUEST_LINE in plain
    assert GUEST_LINE in html.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")
    assert "Dave Davies asked you to do the research" in plain
    assert "Internal Tools" in plain
    assert f"You're researching {key}." in plain
    assert f"{live}/p/{TOOLS}" not in plain + message["HTML"]  # no project link
    assert "AI RATIONALE" not in plain + html
    assert "Private rationale" not in plain + html
    assert_no_score_data_in_email(message["Subject"], html, plain)

    # --- What Nora reaches: the idea, as its guest -----------------------------------------
    detail = await nora.get(f"/ideas/{key}")
    assert_guest_shape(detail)
    assert detail["title"] == TITLE
    assert detail["owner"]["id"] == dave.id
    assert detail["researcher"]["id"] == nora.id
    assert datetime.fromisoformat(detail["research_due_at"]) == due
    assert detail["project"]["name"] == "Internal Tools"
    assert detail["watching"] is True  # a new researcher watches the idea
    nora_research = await nora.get(f"/ideas/{key}/research")
    assert nora_research["permissions"] == {
        "can_answer": True,
        "can_override": False,
        "can_assign": False,
        "can_assign_outside_researcher": False,
        "can_hand_back": True,
    }
    assert nora_research["blocking"] is True
    assert nora_research["gate_status_label"] == "Evaluating"
    activity = await feed(nora, key)
    activity_types = {item["type"] for item in activity}
    assert activity_types <= set(RESEARCH_GUEST_ACTIVITY_TYPES), activity_types
    assert not activity_types & set(EVALUATION_ACTIVITY_TYPES)
    assert {"researcher_changed", "ai_research_note", "status_changed"} <= activity_types
    assert score_data(activity) == []
    assert "AI RATIONALE" not in json.dumps(activity)
    similar = await nora.get(f"/ideas/{key}/similar-ideas")
    assert idea_keys(similar) - {key} == set(), similar  # nothing else of the project
    assert score_data(similar) == []
    note = await nora.get(f"/ideas/{key}/research-notes/{world.note_id}")
    assert score_data(note) == []

    # Every idea route (role matrix table L): view, rule (with R's cells) or hidden (404).
    items = await items_by_title(nora, key)
    optional = items[OPTIONAL]["item_id"]
    dave_comment = await dave.send(
        "POST", f"/ideas/{key}/comments", {"body_md": "Facilities said yes in principle."}, 201
    )
    run, fake = world.research_run, str(uuid.uuid4())
    hand_back = ("remove_researcher", "DELETE", f"/ideas/{key}/research/assignment", None)
    probes: list[tuple[str, str, str, Any, set[int]]] = [
        # view
        ("get_idea", "GET", f"/ideas/{key}", None, {200}),
        ("list_idea_activity", "GET", f"/ideas/{key}/activity", None, {200}),
        ("unwatch_idea", "DELETE", f"/ideas/{key}/watch", None, {200}),
        ("watch_idea", "PUT", f"/ideas/{key}/watch", None, {200}),
        ("get_idea_research", "GET", f"/ideas/{key}/research", None, {200}),
        ("list_similar_ideas", "GET", f"/ideas/{key}/similar-ideas", None, {200}),
        ("get_research_note", "GET", f"/ideas/{key}/research-notes/{world.note_id}", None, {200}),
        # rule: the researcher overlay grants commenting and answering ...
        ("create_comment", "POST", f"/ideas/{key}/comments", {"body_md": "On it."}, {201}),
        (
            "answer_research_item",
            "PUT",
            f"/ideas/{key}/research/items/{optional}",
            {"answer": "No personal data beyond the badge number."},
            {200},
        ),
        ("clear_research_item", "DELETE", f"/ideas/{key}/research/items/{optional}", None, {200}),
        # ... and nothing else (403: R sees the idea).
        ("update_idea", "PATCH", f"/ideas/{key}", {"title": "Mine now"}, {403}),
        ("delete_idea", "DELETE", f"/ideas/{key}", None, {403}),
        ("change_idea_status", "POST", f"/ideas/{key}/status", {"status": "evaluating"}, {403}),
        ("set_idea_owner", "PUT", f"/ideas/{key}/owner", {"user_id": nora.id}, {403}),
        ("volunteer_as_owner", "POST", f"/ideas/{key}/volunteer", None, {403}),
        ("vote_idea", "PUT", f"/ideas/{key}/vote", None, {403}),
        ("unvote_idea", "DELETE", f"/ideas/{key}/vote", None, {403}),
        (
            "set_research_assignment",
            "PUT",
            f"/ideas/{key}/research/assignment",
            {"researcher_id": nora.id, "due_at": None},
            {403},
        ),
        (
            "delete_research_note",
            "DELETE",
            f"/ideas/{key}/research-notes/{world.note_id}",
            None,
            {403},
        ),
        # hidden: the evaluation area
        ("list_evaluations", "GET", f"/ideas/{key}/evaluations", None, {404}),
        ("get_my_evaluation", "GET", f"/ideas/{key}/evaluations/me", None, {404}),
        (
            "save_my_evaluation",
            "PUT",
            f"/ideas/{key}/evaluations/me",
            {"scores": [], "recommendation": None, "comment": "", "submit": False},
            {404},
        ),
        (
            "set_evaluation_inclusion",
            "PUT",
            f"/ideas/{key}/evaluations/{world.evaluation_id}/include-in-aggregate",
            {"include": True},
            {404},
        ),
        ("add_evaluators", "POST", f"/ideas/{key}/evaluators", {"user_ids": [nora.id]}, {404}),
        ("remove_evaluator", "DELETE", f"/ideas/{key}/evaluators/{crew['carol'].id}", None, {404}),
        (
            "set_evaluation_due_date",
            "PUT",
            f"/ideas/{key}/evaluation/due-date",
            {"due_at": due.isoformat()},
            {404},
        ),
        ("close_evaluation", "POST", f"/ideas/{key}/evaluation/close", None, {404}),
        ("reopen_evaluation", "POST", f"/ideas/{key}/evaluation/reopen", None, {404}),
        # hidden: the proposal, its exports, threads and suggestions
        ("get_proposal", "GET", f"/ideas/{key}/proposal", None, {404}),
        ("create_proposal", "POST", f"/ideas/{key}/proposal", None, {404}),
        ("export_proposal_markdown", "GET", f"/ideas/{key}/proposal/markdown", None, {404}),
        ("export_proposal_pdf", "GET", f"/ideas/{key}/proposal/pdf", None, {404}),
        (
            "update_proposal_section",
            "PUT",
            f"/ideas/{key}/proposal/sections/summary",
            {"body_md": "Mine", "base_version": 1},
            {404},
        ),
        ("list_proposal_suggestions", "GET", f"/ideas/{key}/proposal/suggestions", None, {404}),
        (
            "create_proposal_suggestion",
            "POST",
            f"/ideas/{key}/proposal/suggestions",
            {"section_key": "summary", "body_md": "Mine"},
            {404},
        ),
        (
            "accept_proposal_suggestion",
            "POST",
            f"/ideas/{key}/proposal/suggestions/{fake}/accept",
            {"base_version": 1},
            {404},
        ),
        (
            "discard_proposal_suggestion",
            "POST",
            f"/ideas/{key}/proposal/suggestions/{fake}/discard",
            None,
            {404},
        ),
        ("list_proposal_threads", "GET", f"/ideas/{key}/proposal/threads", None, {404}),
        (
            "create_proposal_thread",
            "POST",
            f"/ideas/{key}/proposal/threads",
            {"section_key": "summary", "body_md": "Hm"},
            {404},
        ),
        (
            "reply_to_proposal_thread",
            "POST",
            f"/ideas/{key}/proposal/threads/{fake}/comments",
            {"body_md": "Hm"},
            {404},
        ),
        (
            "delete_proposal_comment",
            "DELETE",
            f"/ideas/{key}/proposal/threads/{fake}/comments/{fake}",
            None,
            {404},
        ),
        (
            "resolve_proposal_thread",
            "PUT",
            f"/ideas/{key}/proposal/threads/{fake}/resolved",
            None,
            {404},
        ),
        (
            "reopen_proposal_thread",
            "DELETE",
            f"/ideas/{key}/proposal/threads/{fake}/resolved",
            None,
            {404},
        ),
        # hidden: the submission panel
        ("get_idea_submission", "GET", f"/ideas/{key}/submission", None, {404}),
        ("approve_submission", "POST", f"/ideas/{key}/submission/approve", None, {404}),
        ("reject_submission", "POST", f"/ideas/{key}/submission/reject", None, {404}),
        ("erase_submitter", "POST", f"/ideas/{key}/submission/erase", None, {404}),
        # hidden: the AI panel and its stream
        ("list_idea_ai_runs", "GET", f"/ideas/{key}/ai-runs", None, {404}),
        (
            "request_ai_evaluation",
            "POST",
            f"/ideas/{key}/ai-runs/evaluation",
            {"agent_id": world.agent_id},
            {404},
        ),
        (
            "request_ai_research",
            "POST",
            f"/ideas/{key}/ai-runs/research",
            {"agent_id": world.agent_id},
            {404},
        ),
        (
            "request_ai_section_draft",
            "POST",
            f"/ideas/{key}/ai-runs/section-draft",
            {"agent_id": world.agent_id, "section_key": "summary"},
            {404},
        ),
        ("get_ai_run", "GET", f"/ideas/{key}/ai-runs/{run}", None, {404}),
        ("cancel_ai_run", "POST", f"/ideas/{key}/ai-runs/{run}/cancel", None, {404}),
        ("stream_ai_run_events", "GET", f"/ideas/{key}/ai-runs/{run}/events", None, {404}),
    ]
    outcomes = {}
    for operation, method, path, body, wanted in probes:
        response = await nora.http.request(method, f"{API}{path}", json=body)
        outcomes[operation] = response.status_code
        assert response.status_code in wanted, f"{operation}: {response.text}"
        if response.content and response.headers["content-type"].startswith("application/json"):
            assert score_data(response.json()) == [], operation
    # The table covers every idea route of the API (hand back is the story's end).
    spec = app.openapi()
    idea_operations = {
        op["operationId"]
        for path, methods in spec["paths"].items()
        if "{idea}" in path
        for op in methods.values()
        if isinstance(op, dict) and "operationId" in op
    }
    assert idea_operations == set(outcomes) | {hand_back[0]}, idea_operations ^ set(outcomes)
    # Her own comment she edits and deletes; Dave's she can't touch.
    mine_now = await nora.send("POST", f"/ideas/{key}/comments", {"body_md": "Draft"}, 201)
    await nora.send(
        "PATCH", f"/comments/{mine_now['comment']['id']}", {"body_md": "Checked with Facilities."}
    )
    await nora.send("DELETE", f"/comments/{mine_now['comment']['id']}", status=204)
    assert (
        await nora.status(
            "PATCH", f"/comments/{dave_comment['comment']['id']}", {"body_md": "Changed"}
        )
        == 403
    )
    assert await nora.status("DELETE", f"/comments/{dave_comment['comment']['id']}") == 403

    # Every project route is 404 (project.view), creating an idea there too.
    project_gets = [
        path.removeprefix(API).replace("{slug}", TOOLS)
        for path, methods in spec["paths"].items()
        if path.startswith(f"{API}/projects/{{slug}}") and "get" in methods and path.count("{") == 1
    ]
    assert len(project_gets) >= 10, project_gets
    for path in project_gets:
        assert await nora.status("GET", path) == 404, path
    assert (
        await nora.status("POST", f"/projects/{TOOLS}/ideas", {"title": "x y", "summary": "z"})
        == 404
    )
    assert await nora.status("GET", f"/users?project={TOOLS}") == 404
    assert await nora.status("GET", f"/users?project={TOOLS}&include_non_members=true") == 404
    directory = await nora.get("/users?q=dave")
    assert any(person["id"] == dave.id for person in directory["items"])

    # Lists: the idea and nothing else of the project.
    projects = await nora.get("/projects")
    assert TOOLS not in project_slugs(projects)
    found = await nora.get(f"/search?q={TITLE.split()[0]}")
    assert key in idea_keys(found["ideas"])
    assert found["projects"] == []
    assert score_data(found) == []
    other = await nora.get("/search?q=printer")  # another TOOLS idea: never
    assert idea_keys(other) == set(), other
    assert "TOOLS-12" not in idea_keys(await nora.get("/search?q=TOOLS-12"))
    work = await nora.get("/me/work")
    [todo] = work["research_to_do"]
    assert todo["idea"]["key"] == key
    assert todo["can_view_project"] is False
    assert todo["as_owner"] is False
    assert todo["overdue"] is False
    assert datetime.fromisoformat(todo["due_at"]) == due
    assert todo["progress"]["required_open"] == 2
    assert (work["counts"]["research_to_do"], work["counts"]["research_overdue"]) == (1, 0)
    assert work["evaluations_due"] == []
    assert work["owned"] == [] or all(group["ideas"] == [] for group in work["owned"])
    assert key not in idea_keys(work["recent"])
    assert score_data(work) == []
    counts = await nora.get("/me/work/counts")
    assert (counts["research_to_do"], counts["research_overdue"]) == (1, 0)
    assert idea_keys((await nora.get("/me/research-to-do"))["items"]) >= {key}
    assert idea_keys(await nora.get("/me/owned-ideas")) == set()
    notifications = await inbox_items(nora)
    # "Asked to research", and Dave's comment (a new researcher watches the idea).
    assert sorted(item["type"] for item in notifications) == ["comment", "researcher_assigned"]
    [asked] = [item for item in notifications if item["type"] == "researcher_assigned"]
    assert asked["actor"]["id"] == dave.id
    assert datetime.fromisoformat(asked["due_at"]) == due
    assert score_data(notifications) == []

    # --- MCP and keys: never more than REST ------------------------------------------------
    # A key can be restricted only to projects she can view (none of TOOLS).
    await refused(
        nora,
        "POST",
        "/me/api-keys",
        {"name": "tools only", "scopes": ["read"], "project_ids": [world.tools_id]},
        status=422,
        code="invalid_project",
    )
    secret = await make_key(nora, ["write", "mcp"], None)
    async with key_client(live, secret) as nora_key:
        assert_guest_shape(ok(await nora_key.get(f"{API}/ideas/{key}")))
        assert (await nora_key.get(f"{API}/ideas/{key}/evaluations")).status_code == 404
        assert (await nora_key.get(f"{API}/projects/{TOOLS}")).status_code == 404
        await refused(
            nora_key,
            "PUT",
            f"/ideas/{key}/research/assignment",
            {"researcher_id": nora.id, "due_at": None},
            status=403,
            code="insufficient_scope",
        )
        ok(
            await nora_key.put(
                f"{API}/ideas/{key}/research/items/{optional}",
                json={"answer": "Only the badge number, kept 30 days."},
            )
        )
    async with mcp_client(live, secret) as client:
        seen = data(await call(client, "get_idea", idea=key))["idea"]
        assert seen["research_guest"] is True
        assert seen["research"]["researcher"]["display_name"] == "Nora Quinn"
        assert datetime.fromisoformat(seen["research"]["due_at"]) == due
        assert seen["has_proposal"] is False
        assert score_data(seen) == []
        assert "AI RATIONALE" not in json.dumps(seen)
        searched = data(await call(client, "search_ideas", query=TITLE.split()[0]))
        assert idea_keys(searched) == {key}
        assert score_data(searched) == []
        assert error(await call(client, "search_ideas", project=TOOLS)) == "not_found"
        assert TOOLS not in project_slugs(data(await call(client, "list_projects")))
        assert error(await call(client, "get_rubric", project=TOOLS)) == "not_found"
        assert error(await call(client, "get_rubric", idea=key)) == "not_found"
        assert error(await call(client, "get_proposal", idea=key)) == "not_found"
        assert (
            error(
                await call(
                    client,
                    "submit_evaluation",
                    idea=key,
                    scores=[],
                    recommendation="go",
                    submit=False,
                )
            )
            == "not_found"
        )
        assert (
            error(
                await call(
                    client,
                    "propose_proposal_section",
                    idea=key,
                    section_key="summary",
                    body_md="Mine",
                )
            )
            == "not_found"
        )
        assert (
            error(await call(client, "create_idea", project=TOOLS, title="A b", summary="C"))
            == "not_found"
        )
        assert (
            error(await call(client, "add_research_note", idea=key, body_md="Note")) == "forbidden"
        )
        added = data(await call(client, "add_comment", idea=key, body_md="Asked Legal too."))
        assert added["idea"]["key"] == key

    # --- The research reminder: two days before at the digest hour, once -------------------
    for days_before in (3, 1):  # not a reminder day (SOUNDINGS_REMINDER_DAYS = 2, 0)
        await remind(app, settings, at_digest_hour(local_due - timedelta(days_before), settings))
        assert await emails_to(db_session, nora.id, "research_reminder") == []
    fire = at_digest_hour(local_due - timedelta(days=2), settings)
    # An hour early: not yet.
    await remind(app, settings, fire - timedelta(hours=1))
    assert await emails_to(db_session, nora.id, "research_reminder") == []
    await remind(app, settings, fire)
    await remind(app, settings, fire + timedelta(minutes=20))  # the same hour: nothing new
    [reminder_row] = await emails_to(db_session, nora.id, "research_reminder")
    assert await send_queued(db_session, runtime, clock, nora.id, "research_reminder", fire) == 1
    reminders = [item for item in await inbox_items(nora) if item["type"] == "research_reminder"]
    assert [(r["days_before"], r["as_owner"]) for r in reminders] == [(2, False)]
    mail = await inbox.wait_for(nora.email, count=2)
    [reminder] = [m for m in mail if "Reminder" in m["Subject"]]
    reminder_message = await inbox.message(reminder["ID"])
    assert reminder_message["Subject"] == (
        f'[{key}] Reminder: research for "{TITLE}" is due {day(due)}'
    )
    reminder_text = reminder_message["Text"]
    assert "2 required items to answer" in reminder_text
    assert research_link in reminder_text
    assert f"You're researching {key}." in reminder_text
    assert_no_score_data_in_email(
        reminder_message["Subject"], visible_text(reminder_message["HTML"]), reminder_text
    )
    assert reminder_row.status == EmailStatus.QUEUED  # as read before sending

    # --- Nora answers; the gate lets the owner move it, never her ---------------------------
    for title in REQUIRED:
        research = await answer(nora, key, items[title]["item_id"], f"{title}: done (Nora).")
    assert research["progress"]["required_open"] == 0
    assert research["blocking"] is False
    answered = await items_by_title(dave, key)
    assert {answered[title]["answer"]["answered_by"]["id"] for title in REQUIRED} == {nora.id}
    await refused(
        nora,
        "POST",
        f"/ideas/{key}/status",
        {"status": "evaluating"},
        status=403,
        code="forbidden",
    )
    await refused(
        nora,
        "POST",
        f"/ideas/{key}/status",
        {"status": "evaluating", "override_research": True},
        status=403,
        code="forbidden",
    )
    overrides_before = len(await audit(alice, action="idea.research_override"))
    moved = await dave.send("POST", f"/ideas/{key}/status", {"status": "evaluating"})
    assert moved["status"] == "evaluating"
    assert len(await audit(alice, action="idea.research_override")) == overrides_before
    # Past Research: nothing to do any more, and no reminder on the due date.
    work = await nora.get("/me/work")
    assert work["research_to_do"] == []
    assert (work["counts"]["research_to_do"], work["counts"]["research_overdue"]) == (0, 0)
    await remind(app, settings, at_digest_hour(local_due, settings))
    assert len(await emails_to(db_session, nora.id, "research_reminder")) == 1
    # M1: a required answer can't be cleared past Research, for the researcher too.
    await refused(
        nora,
        "DELETE",
        f"/ideas/{key}/research/items/{items[REQUIRED[0]]['item_id']}",
        status=409,
        code="research_answer_required",
    )
    # She still sees it (assigned, open, the step on), and her inbox has the move.
    assert_guest_shape(await nora.get(f"/ideas/{key}"))
    mention = f"@[Nora Quinn](user:{nora.id})"
    await dave.send(
        "POST", f"/ideas/{key}/comments", {"body_md": f"{mention} thanks, great work"}, 201
    )
    nora_types = [item["type"] for item in await inbox_items(nora)]
    assert {"researcher_assigned", "research_reminder", "status_changed", "mention"} <= set(
        nora_types
    ), nora_types
    assert set(nora_types) <= set(RESEARCH_GUEST_NOTIFICATION_TYPES), nora_types

    # --- Dave reassigns to Farah: Nora's access ends on her next request --------------------
    await assign(dave, key, farah, due)
    for path in (
        f"/ideas/{key}",
        f"/ideas/{key}/research",
        f"/ideas/{key}/activity",
        f"/ideas/{key}/similar-ideas",
        f"/ideas/{key}/research-notes/{world.note_id}",
    ):
        assert await nora.status("GET", path) == 404, path
    assert await nora.status("POST", f"/ideas/{key}/comments", {"body_md": "Still here?"}) == 404
    assert await nora.status("PUT", f"/ideas/{key}/research/items/{optional}", {"answer": "x"}) == (
        404
    )
    assert await nora.status("DELETE", f"/ideas/{key}/research/assignment") == 404
    assert key not in idea_keys(await nora.get(f"/search?q={TITLE.split()[0]}"))
    assert (await nora.get("/me/work"))["research_to_do"] == []
    assert key not in idea_keys(await inbox_items(nora))
    summary_now = await nora.get("/me/notifications/summary")
    assert score_data(summary_now) == []
    async with mcp_client(live, secret) as client:
        assert error(await call(client, "get_idea", idea=key)) == "not_found"
        assert idea_keys(data(await call(client, "search_ideas", query=TITLE.split()[0]))) == set()
    # Her answers stay, with her name on them.
    answered = await items_by_title(dave, key)
    assert answered[REQUIRED[1]]["answer"]["answered_by"]["display_name"] == "Nora Quinn"

    # Farah (no role in TOOLS) is asked by email too, as a guest: Nora was asked minutes ago,
    # so Farah's email waits RESEARCHER_EMAIL_HOLD (review M1); time passes, then it goes.
    farah_row = await db_session.scalar(
        select(OutboundEmail)
        .where(
            OutboundEmail.recipient_user_id == uuid.UUID(farah.id),
            OutboundEmail.type == EmailType.RESEARCHER_ASSIGNED,
        )
        .execution_options(populate_existing=True)
    )
    assert farah_row is not None
    assert farah_row.next_attempt_at is not None
    assert farah_row.next_attempt_at > utcnow() + RESEARCHER_EMAIL_HOLD - timedelta(minutes=1)
    await db_session.execute(
        text("UPDATE outbound_email SET next_attempt_at = now() WHERE id = :id"),
        {"id": farah_row.id},
    )
    await db_session.execute(
        text(
            "UPDATE procrastinate_jobs SET scheduled_at = now()"
            " WHERE task_name = 'send_email' AND args->>'email_id' = :id"
        ),
        {"id": str(farah_row.id)},
    )
    await db_session.commit()
    await run_worker_once(jobs, runtime)
    farah_mail = [
        m for m in await inbox.wait_for(farah.email) if m["Subject"].startswith(f"[{key}]")
    ]
    assert [m["Subject"] for m in farah_mail] == [
        f'[{key}] Please research "{TITLE}" by {day(due)}'
    ]
    assert_guest_shape(await farah.get(f"/ideas/{key}"))

    # --- Farah hands it back; asked again, her inbox holds the live request only (L2) ------
    await farah.send("DELETE", f"/ideas/{key}/research/assignment", status=204)
    assert await farah.status("GET", f"/ideas/{key}") == 404
    after = await dave.get(f"/ideas/{key}/research")
    assert after["assignment"]["researcher"] is None
    assert datetime.fromisoformat(after["assignment"]["due_at"]) == due  # the date stays
    handed = [item for item in await feed(dave, key) if item["type"] == "researcher_changed"]
    assert handed[0]["handed_back"] is True, handed[0]
    await assign(dave, key, farah, due)
    farah_asks = [
        item
        for item in await inbox_items(farah)
        if item["type"] == "researcher_assigned" and item["idea"]["key"] == key
    ]
    assert len(farah_asks) == 1

    # --- Deactivation clears the assignment for good -----------------------------------------
    await alice.send("PATCH", f"/admin/users/{farah.id}", {"is_active": False})
    cleared = await dave.get(f"/ideas/{key}/research")
    assert cleared["assignment"]["researcher"] is None
    assert datetime.fromisoformat(cleared["assignment"]["due_at"]) == due
    await refused(
        dave,
        "PUT",
        f"/ideas/{key}/research/assignment",
        {"researcher_id": farah.id, "due_at": None},
        status=422,
        code="researcher_not_eligible",
    )
    await alice.send("PATCH", f"/admin/users/{farah.id}", {"is_active": True})
    farah_again = await crew.sign_in(farah.id, farah.name, farah.email)
    assert await farah_again.status("GET", f"/ideas/{key}") == 404
    assert (await dave.get(f"/ideas/{key}/research"))["assignment"]["researcher"] is None
    reasons = [
        entry["details"]["reason"] for entry in await researcher_changes(alice, world.idea_id)
    ]
    assert sorted(reasons) == sorted(
        ["assigned", "assigned", "handed_back", "assigned", "deactivated"]
    ), reasons
    # Answers written by former researchers stay.
    final = await items_by_title(dave, key)
    assert {final[title]["answer"]["answered_by"]["id"] for title in REQUIRED} == {nora.id}


# --- AC8B-API-2: the AI event stream --------------------------------------------------------
async def test_ac8b_api_2_a_researcher_who_loses_access_loses_the_event_stream(
    live: str,
    crew: Crew,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alice, dave, carol, nora = crew["alice"], crew["dave"], crew["carol"], crew["nora"]
    # The stream re-checks every 30 s; half a second here, so the test doesn't wait.
    kwdefaults = sse.event_stream.__kwdefaults__
    assert kwdefaults is not None
    monkeypatch.setitem(kwdefaults, "recheck_every", 0.5)
    created = await dave.send(
        "POST", f"/projects/{TOOLS}/ideas", {"title": "Shared parcel locker", "summary": "S"}, 201
    )
    key = created["key"]
    await dave.send("PUT", f"/ideas/{key}/owner", {"user_id": dave.id})
    await dave.send("POST", f"/ideas/{key}/status", {"status": "research"})
    tools = await db_session.scalar(select(Project).where(Project.slug == TOOLS))
    row = await db_session.scalar(select(Idea).where(Idea.id == uuid.UUID(created["id"])))
    assert tools is not None
    assert row is not None
    agent = await make_agent(db_session, [tools], name="p8b-researcher")
    run = await open_run(db_session, agent, row, AiRunKind.RESEARCH)
    await db_session.commit()
    events = f"{API}/ideas/{key}/ai-runs/{run.id}/events"

    # A guest researcher can't open a stream at all.
    await assign(dave, key, nora, None)
    assert (await nora.http.get(events)).status_code == 404
    assert (await nora.http.get(f"{API}/ideas/{key}")).status_code == 200

    # A member researcher (Carol) watches the run ...
    await assign(dave, key, carol, None)
    assert (await nora.http.get(f"{API}/ideas/{key}")).status_code == 404  # reassigned
    async with carol.http.stream("GET", events, headers={"Accept": "text/event-stream"}) as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        lines = stream.aiter_lines()
        assert await asyncio.wait_for(anext(lines), 5) == "retry: 3000"
        # ... and loses her role in the private project: the assignment ends with it
        # (S1 b), and the stream ends at the next re-check.
        await dave.send("DELETE", f"/projects/{TOOLS}/members/{carol.id}", status=204)

        async def drain() -> None:
            async for _ in lines:
                pass

        await asyncio.wait_for(drain(), 10)
    assert (await carol.http.get(f"{API}/ideas/{key}")).status_code == 404
    assert (await carol.http.get(events)).status_code == 404
    research = await dave.get(f"/ideas/{key}/research")
    assert research["assignment"]["researcher"] is None
    reasons = [
        entry["details"]["reason"] for entry in await researcher_changes(alice, created["id"])
    ]
    assert reasons.count("left_project") == 1, reasons


# --- AC8B-API-3: the demo story ---------------------------------------------------------------
async def test_ac8b_api_3_the_demo_story(
    live: str, crew: Crew, jobs: App, runtime: Runtime, inbox: MailpitInbox
) -> None:
    alice, amara, bob, dave = crew["alice"], crew["amara"], crew["bob"], crew["dave"]
    sven, erin = crew["sven"], crew["erin"]

    # Bob researches TOOLS-12 as its guest, due in about three days, asked by dave.
    detail = await bob.get("/ideas/TOOLS-12")
    assert_guest_shape(detail)
    assert detail["status"] == "research"
    assert detail["researcher"]["id"] == bob.id
    due = datetime.fromisoformat(detail["research_due_at"])
    assert timedelta(days=2) < due - datetime.now(UTC) < timedelta(days=4), due
    assert await bob.status("GET", f"/projects/{TOOLS}") == 404
    assert await bob.status("GET", f"/projects/{TOOLS}/board") == 404
    assert await bob.status("GET", "/ideas/TOOLS-11") == 404  # another idea of the project
    work = await bob.get("/me/work")
    [todo] = [item for item in work["research_to_do"] if item["idea"]["key"] == "TOOLS-12"]
    assert todo["can_view_project"] is False
    assert todo["progress"]["required_open"] == 1
    assert work["counts"]["research_to_do"] >= 1
    asked = [
        item
        for item in await inbox_items(bob)
        if item["type"] == "researcher_assigned" and item["idea"]["key"] == "TOOLS-12"
    ]
    assert [item["actor"]["id"] for item in asked] == [dave.id]

    # The team sees who outside the project reads it; only admins may name outsiders.
    sven_view = await sven.get("/ideas/TOOLS-12/research")
    assert sven_view["assignment"]["researcher"]["id"] == bob.id
    assert sven_view["assignment"]["researcher_in_project"] is False
    assert sven_view["permissions"]["can_assign"] is True
    assert sven_view["permissions"]["can_assign_outside_researcher"] is False
    assert (await dave.get("/ideas/TOOLS-12/research"))["permissions"][
        "can_assign_outside_researcher"
    ] is True
    await refused(
        sven,
        "PUT",
        "/ideas/TOOLS-12/research/assignment",
        {"researcher_id": erin.id, "due_at": None},
        status=403,
        code="outside_researcher_needs_admin",
    )
    picker = await dave.get(f"/users?project={TOOLS}&include_non_members=true&q=bob")
    [bob_row] = [row for row in picker["items"] if row["id"] == bob.id]
    assert bob_row["project_role"] is None
    # TOOLS-11 keeps its owner doing the research.
    assert (await dave.get("/ideas/TOOLS-11/research"))["assignment"]["researcher"] is None

    # A key restricted to bob's own projects never reaches TOOLS-12; an unrestricted one
    # reaches it only as the guest.
    cust = await bob.get(f"/projects/{CUST}")
    restricted = await make_key(bob, ["read", "mcp"], [cust["id"]])
    async with key_client(live, restricted) as narrow:
        assert (await narrow.get(f"{API}/ideas/TOOLS-12")).status_code == 404
    async with mcp_client(live, restricted) as client:
        assert error(await call(client, "get_idea", idea="TOOLS-12")) == "not_found"
    unrestricted = await make_key(bob, ["read"], None)
    async with key_client(live, unrestricted) as wide:
        assert_guest_shape(ok(await wide.get(f"{API}/ideas/TOOLS-12")), granted=frozenset())

    # Amara researches GREEN-6 (asked by alice); alice's GREEN-5 is overdue.
    green6 = await amara.get("/ideas/GREEN-6/research")
    assert green6["assignment"]["researcher"]["id"] == amara.id
    assert [
        item["actor"]["id"]
        for item in await inbox_items(amara)
        if item["type"] == "researcher_assigned" and item["idea"]["key"] == "GREEN-6"
    ] == [alice.id]
    alice_work = await alice.get("/me/work")
    first = alice_work["research_to_do"][0]
    assert first["idea"]["key"] == "GREEN-5"
    assert first["overdue"] is True
    assert alice_work["counts"]["research_overdue"] >= 1
    # D: owned groups hold their first 10 ideas; count and the cursor say the rest.
    for group in alice_work["owned"]:
        assert len(group["ideas"]) <= 10
        assert group["count"] >= len(group["ideas"])
        assert (group["next_cursor"] is not None) == (group["count"] > len(group["ideas"]))
    # GREEN is internal: a non-member there would be NMi, not a guest; bob, a member, sees
    # GREEN-6 with the normal member view (scores included where they are visible).
    assert (await bob.get("/ideas/GREEN-6"))["permissions"]["can_view_project"] is True

    # An internal project: an outsider researching there is NMi + Rsr, not a guest. A plain
    # owner may name them (c25 is for private projects), they keep the internal
    # non-member's view and gain answering, commenting and handing back, and their email
    # has no guest line (review S2).
    created = await sven.send(
        "POST",
        f"/projects/{GREEN}/ideas",
        {"title": "Rainwater for the car wash", "summary": "Collect rainwater from the roof."},
        201,
    )
    key = created["key"]
    await amara.send("PUT", f"/ideas/{key}/owner", {"user_id": sven.id})
    research = await assign(sven, key, dave, None)
    assert research["assignment"]["researcher"]["id"] == dave.id
    assert research["assignment"]["researcher_in_project"] is False
    seen = await dave.get(f"/ideas/{key}")
    assert seen["permissions"]["can_view_project"] is True
    granted = {name for name, value in seen["permissions"].items() if value is True}
    assert {"can_comment", "can_answer_research", "can_hand_back_research"} <= granted
    assert "can_change_status" not in granted
    assert await dave.status("GET", f"/projects/{GREEN}/board") == 200
    assert (await dave.get(f"/ideas/{key}/research"))["permissions"]["can_answer"] is True
    await run_worker_once(jobs, runtime)
    mail = [m for m in await inbox.wait_for(dave.email) if m["Subject"].startswith(f"[{key}]")]
    assert [m["Subject"] for m in mail] == [f'[{key}] Please research "{created["title"]}"']
    text = (await inbox.message(mail[0]["ID"]))["Text"]
    assert GUEST_LINE not in text
    assert f"You're researching {key}." in text
