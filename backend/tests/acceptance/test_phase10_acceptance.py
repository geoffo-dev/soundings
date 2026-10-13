"""Phase 10 acceptance against a live server, the real worker, Mailpit and the fake kagent
agent (QA; docs/test-plans/phase-10.md, AC10-API-*).

The product owner's Phase 10 change (decisions "Phase 10 (product owner, 2026-10-13)",
contract-phase10): once an idea has a proposal, the team runs a **call for bids** on it.
The team enters the bids and uploads their documents; a must-have checklist flags what a
bid lacks and a person rejects it in one click with a reason; assessors assigned **per
section** score every bid **blind**; an **AI assessor** scores every question with quotes
from the documents (checked by the server), left out of the totals until a call manager
includes it; the call is awarded and its evaluation report exported.

Everything is real except the model: the app behind **uvicorn** on a free port, people on
the REST API over TCP with their session cookie and CSRF header (uploads are the raw file
as the body, as the SPA sends them), API keys as bearer tokens, MCP through the official
SDK client; the **worker**'s three pools in this event loop (``email`` + ``notifications``,
the ``ai`` pool that runs ``run_ai``, and the ``bid_documents`` pool whose child process
reads each document's text); email through a **real Mailpit** (the Phase 3 acceptance's
fixtures); **Soundings' fake kagent agent** (``dev/fake-agent``) as the AI assessor,
calling back into the live ``/mcp`` with the key the admin API showed once. The reminder
scan runs with a moved clock, so it fires without waiting days. Documents are the demo's
own files (``app/seed/bids/``).

* AC10-API-1: the story, on a new idea of kenji's in the private Internal Tools (bob, no
  role there, researches it: its guest). kenji opens a call, enters Northwind, Tessellate
  and Quillfield and uploads their documents (Quillfield has no insurance certificate:
  flagged missing at once), confirms the terms, rejects Quillfield in one click with a
  reason, assigns Technical (carol, mateo), Commercial with the price (priya) and Delivery
  (sven) with a due date ("Asked to assess bids" through Mailpit: no scores, prices or
  bidders), closes the call to new bids. The AI assessor scores Tessellate through MCP via
  the fake agent (every quote found; never the pricing document), an ``-invents`` agent
  gives Northwind a quote marked not found; an agent's key in another run reaches nothing
  else (c22). Carol is probed on every surface before and after she submits (blind 3a),
  price visibility per section, a member (farah), a viewer (zanele) and the guest (bob).
  The reminder fires two days before the due date at the digest hour (not twice, not the
  day before); "All bid assessments are in" reaches kenji; the comparison and ranking
  match the contract's math worked out here (the AI out, then in); the award; the report
  (Markdown, and the PDF read back with pypdf) for kenji only.
* AC10-API-2: the demo story (contract section 17): TOOLS-3's "Data platform build" being
  assessed, kenji's comparison (Northwind 84.0, Tessellate 71.2, Quillfield rejected), alice
  owing both Delivery assessments (no ranks for her), prices per section, zanele's summary,
  and a person's API key per scope (session-only routes refused).

The module needs ``uv`` and ``dev/fake-agent`` (synced on first use) and Docker for
Mailpit; ``SOUNDINGS_TEST_FAKE_AGENT=0`` skips it.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import re
import shutil
import uuid
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pypdf
import pytest
from fastapi import FastAPI
from procrastinate import PsycopgConnector
from procrastinate.worker import Worker

from app.ai.runner import AiRuntime
from app.config import Settings
from app.db import session_scope
from app.email import delivery as email_delivery
from app.email.delivery import Runtime
from app.models.enums import EmailStatus
from app.notifications.bids import send_assessment_reminders
from app.seed import run_seed
from app.seed.bids import DOCUMENT_DIR
from app.worker import (
    MAIN_QUEUES,
    ai_worker_options,
    document_worker_options,
    procrastinate_app,
    worker_options,
)
from tests.acceptance import test_phase3_acceptance as phase3
from tests.acceptance import test_phase6_acceptance as phase6
from tests.acceptance.test_phase3_acceptance import SCORE_NUMBER, MailpitInbox, visible_text
from tests.acceptance.test_phase5_acceptance import call, data, error, key_client, mcp_client
from tests.acceptance.test_phase8b_acceptance import (
    Crew,
    Person,
    _free_port,
    _Server,
    audit,
    emails_to,
    feed,
    inbox_items,
    items_by_title,
    ok,
    refused,
)

API = "/api/v1"
ZONE = "Europe/London"
TOOLS = "internal-tools"
NAMESPACE = "soundings"
TITLE = "Self-service sandbox environments"
CALL_TITLE = "Sandbox platform build"
FINAL = {"succeeded", "failed", "cancelled", "timed_out"}
NAMES = ("alice", "bob", "carol", "dave", "farah", "kenji", "mateo", "priya", "sven", "zanele")
# The default template's must-haves (app.schemas.bids.DEFAULT_BID_TEMPLATE).
TENDER, PRICING, INSURANCE, TERMS = (
    "Signed form of tender",
    "Pricing schedule",
    "Insurance certificate",
    "Accepts our standard terms",
)
BIDDERS = ("Northwind Data Ltd", "Tessellate Software", "Quillfield Systems")
PRICES = {"Northwind Data Ltd": "120000.00", "Tessellate Software": "96000.00"}
REJECTION = "No insurance certificate provided."
# "Asked to assess bids" names scores once, in a fixed sentence about blind assessment
# ("section" for one, "sections" for more).
BLIND_LINE = re.compile(
    r"Score your sections? for every bid on the idea's Bids tab\. Your assessment is blind: "
    r"nobody's scores for a bid and section are shown to you until you submit yours\."
)
# Human scores (contract section 8.1's pattern): bid -> section -> assessor -> one score
# per score question, in order.
SCORES: dict[str, dict[str, dict[str, list[int]]]] = {
    "Northwind Data Ltd": {
        "Technical": {"carol": [4, 4], "mateo": [5, 4]},
        "Commercial": {"priya": [4, 4]},
        "Delivery": {"sven": [4, 5]},
    },
    "Tessellate Software": {
        "Technical": {"carol": [4, 3], "mateo": [2, 3]},
        "Commercial": {"priya": [3, 3]},
        "Delivery": {"sven": [3, 4]},
    },
}

mailpit = phase3.mailpit
smtp = phase3.smtp
inbox = phase3.inbox
fake_agent = phase6.fake_agent

pytestmark = pytest.mark.skipif(
    os.environ.get("SOUNDINGS_TEST_FAKE_AGENT") == "0"
    or shutil.which("uv") is None
    or not (phase6.FAKE_AGENT_DIR / "pyproject.toml").is_file(),
    reason="needs uv and dev/fake-agent (SOUNDINGS_TEST_FAKE_AGENT=0 skips it)",
)


# --- The live server, the worker, the people ---------------------------------------------
@pytest.fixture
def port() -> int:
    return _free_port()


@pytest.fixture
def fake_port() -> int:
    return _free_port()


@pytest.fixture
def settings_overrides(port: int, fake_port: int, smtp: phase3.Smtp) -> dict[str, Any]:
    return {
        "base_urls": [f"http://127.0.0.1:{port}"],
        "dev_login_enabled": True,
        "smtp_host": smtp.host,
        "smtp_port": smtp.port,
        "smtp_security": "none",
        "smtp_from": "soundings@example.com",
        "smtp_from_name": "Soundings",
        "smtp_timeout": 3,
        "timezone": ZONE,
        "ai_enabled": True,
        "kagent_url": f"http://127.0.0.1:{fake_port}",
        "ai_run_timeout": phase6.RUN_TIMEOUT,
        "ai_max_concurrent_runs": 8,
        "ai_mcp_url": f"http://127.0.0.1:{port}/mcp",
        # Many writes in one minute from the same people (the arrangement is quick).
        "session_writes_per_minute": 10_000,
    }


@pytest.fixture
async def live(app: FastAPI, port: int) -> AsyncIterator[str]:
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
class Workers:
    """``soundings worker``'s three pools (app/worker.py ``run_worker``) in this loop."""

    app: FastAPI
    settings: Settings
    clock: phase3.Clock = field(default_factory=phase3.Clock)
    runtime: Runtime | None = None
    stack: contextlib.AsyncExitStack = field(default_factory=contextlib.AsyncExitStack)
    pools: list[Worker] = field(default_factory=list)
    tasks: list[asyncio.Task[None]] = field(default_factory=list)

    async def start(self) -> None:
        connector = PsycopgConnector(
            conninfo=self.settings.database_dsn,
            min_size=1,
            max_size=self.settings.ai_max_concurrent_runs + 10,
        )
        jobs = self.stack.enter_context(procrastinate_app.replace_connector(connector))
        await self.stack.enter_async_context(jobs.open_async())
        jobs.perform_import_paths()  # type: ignore[no-untyped-call]
        sessionmaker = self.app.state.sessionmaker
        runtime = Runtime(
            settings=self.settings, sessionmaker=sessionmaker, jobs=jobs, clock=self.clock
        )
        self.runtime = runtime
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
            Worker(
                app=jobs,
                install_signal_handlers=False,
                **document_worker_options(runtime=runtime, ai_runtime=ai_runtime),
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
    report = await run_seed(settings)
    assert report.skipped is None
    assert (report.projects, report.ideas) == (3, 48)


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
        yield people
    finally:
        for http in people.clients:
            await http.aclose()


# --- Helpers ------------------------------------------------------------------------------
def half_up(value: Fraction, places: int) -> float:
    """The API's rounding: half up on the exact value (contract section 8)."""
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return float(exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def mean(values: Iterable[int]) -> Fraction:
    items = list(values)
    return Fraction(sum(items), len(items))


def expected_comparison(
    call_: dict[str, Any],
    human: dict[str, dict[str, dict[str, list[int]]]],
    ai: dict[str, dict[str, int]],
) -> dict[str, dict[str, Any]]:
    """Section scores (0-100) and totals worked out from the template, the human scores and
    the included AI scores (bid -> question id -> score), as contract section 8 says: a
    question's mean of the counted scores; the price question lowest scored price / this
    price x 5; a section's weighted mean x 20; the total the sections' weighted sum."""
    lowest = min(Fraction(Decimal(p)) for p in PRICES.values())
    out: dict[str, dict[str, Any]] = {}
    for bidder, sections in human.items():
        price_score = lowest / Fraction(Decimal(PRICES[bidder])) * 5
        section_scores: list[Fraction] = []
        for section in call_["template"]["sections"]:
            weighted = Fraction(0)
            weights = 0
            score_questions = [q for q in section["questions"] if q["type"] == "score"]
            for question in section["questions"]:
                if question["type"] == "comment":
                    continue
                if question["type"] == "price":
                    value = price_score
                else:
                    index = score_questions.index(question)
                    counted = [scores[index] for scores in sections[section["title"]].values()]
                    if question["id"] in ai.get(bidder, {}):
                        counted.append(ai[bidder][question["id"]])
                    value = mean(counted)
                weighted += value * question["weight"]
                weights += question["weight"]
            section_scores.append(weighted / weights * 20)
        total = sum(
            (
                Fraction(s["weight"], 100) * score
                for s, score in zip(call_["template"]["sections"], section_scores, strict=True)
            ),
            Fraction(0),
        )
        out[bidder] = {
            "sections": [half_up(score, 1) for score in section_scores],
            "total": half_up(total, 1),
            "price_score": half_up(price_score, 2),
        }
    return out


def bid_secrets(text: str) -> list[str]:
    """Bidder names, prices or contact details in ``text`` (never in notifications)."""
    found = [name for name in BIDDERS if name in text]
    found += [p for p in ("120000", "120,000", "96000", "96,000", "84000", "84,000") if p in text]
    found += [e for e in ("northwind-data.example", "tessellate.example") if e in text]
    return found


async def upload(
    person: Person,
    key: str,
    bid_id: str,
    path: Path,
    *,
    must_have_id: str | None = None,
    name: str | None = None,
) -> httpx.Response:
    params = {"filename": name or path.name}
    if must_have_id:
        params["must_have_id"] = must_have_id
    return await person.http.post(
        f"{API}/ideas/{key}/bid-call/bids/{bid_id}/documents",
        params=params,
        content=await asyncio.to_thread(path.read_bytes),
        headers={"Content-Type": "application/octet-stream"},
        timeout=60,
    )


async def wait_run(person: Person, key: str, run_id: str, within: float = 90) -> dict[str, Any]:
    async with asyncio.timeout(within):
        while True:
            run: dict[str, Any] = await person.get(f"/ideas/{key}/ai-runs/{run_id}")
            if run["status"] in FINAL:
                return run
            await asyncio.sleep(0.25)


async def wait_status(person: Person, key: str, run_id: str, status: str) -> None:
    async with asyncio.timeout(30):
        while True:
            run: dict[str, Any] = await person.get(f"/ideas/{key}/ai-runs/{run_id}")
            if run["status"] == status:
                return
            await asyncio.sleep(0.2)


async def mail_to(
    inbox_: MailpitInbox, address: str, subject: re.Pattern[str]
) -> list[dict[str, Any]]:
    return [m for m in await inbox_.to(address) if subject.search(m["Subject"])]


async def wait_mail(
    inbox_: MailpitInbox, address: str, subject: re.Pattern[str], seconds: float = 30
) -> dict[str, Any]:
    async with asyncio.timeout(seconds):
        while True:
            found = await mail_to(inbox_, address, subject)
            if found:
                return await inbox_.message(found[0]["ID"])
            await asyncio.sleep(0.25)


def mail_text(message: dict[str, Any]) -> str:
    return "\n".join([message["Subject"], visible_text(message["HTML"]), message["Text"]])


def no_scores_in_mail(label: str, text: str) -> None:
    """No score numbers, no bid secrets, no score words outside the fixed blind line."""
    plain = BLIND_LINE.sub("", text.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'"))
    assert not SCORE_NUMBER.search(plain), (label, SCORE_NUMBER.search(plain))
    assert not re.search(r"\bscored?\b", plain, re.I), (label, plain)
    assert not bid_secrets(plain), (label, bid_secrets(plain))


async def register_agent(alice: Person, name: str, project_id: str) -> tuple[dict[str, Any], str]:
    created = await alice.send(
        "POST",
        "/admin/ai-agents",
        {
            "display_name": name,
            "description": "Phase 10 acceptance (tests/acceptance/test_phase10_acceptance.py).",
            "namespace": NAMESPACE,
            "name": name,
            "purposes": ["assess_bid"],
            "project_ids": [project_id],
        },
        201,
    )
    return created["agent"], created["key"]["secret"]


def at_digest_hour(day: datetime, settings: Settings, minute: int = 30) -> datetime:
    """``minute`` past the digest hour on ``day``'s local date, in UTC."""
    zone = ZoneInfo(ZONE)
    local = day.astimezone(zone)
    moment = datetime.combine(local.date(), datetime.min.time(), tzinfo=zone).replace(
        hour=settings.digest_hour, minute=minute
    )
    return moment.astimezone(UTC)


async def remind(app: FastAPI, settings: Settings, now: datetime) -> int:
    """The hourly schedule's bid assessment reminders at ``now`` (in its own session)."""
    async with session_scope(app.state.sessionmaker, settings=settings) as db:
        return await send_assessment_reminders(db, settings, now)


def strings(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


# --- AC10-API-1 -----------------------------------------------------------------------------
async def test_ac10_api_1_a_call_for_bids_from_entry_to_award(
    live: str,
    crew: Crew,
    fake_agent: phase6.FakeAgent,
    workers: Workers,
    inbox: MailpitInbox,
    app: FastAPI,
    settings: Settings,
) -> None:
    await workers.start()
    alice, bob, carol, dave = crew["alice"], crew["bob"], crew["carol"], crew["dave"]
    farah, kenji, mateo, priya = crew["farah"], crew["kenji"], crew["mateo"], crew["priya"]
    sven, zanele = crew["sven"], crew["zanele"]
    project = await dave.get(f"/projects/{TOOLS}")
    await dave.send(
        "POST", f"/projects/{TOOLS}/members", {"user_id": farah.id, "role": "member"}, 201
    )

    # --- An idea with a proposal; bob researches it from outside the private project ------
    idea = await kenji.send(
        "POST",
        f"/projects/{TOOLS}/ideas",
        {"title": TITLE, "summary": "Spin up a short-lived copy of a service for testing."},
        201,
    )
    key = idea["key"]
    call_path = f"/ideas/{key}/bid-call"
    await dave.send("PUT", f"/ideas/{key}/owner", {"user_id": kenji.id})
    await dave.send(
        "PUT", f"/ideas/{key}/research/assignment", {"researcher_id": bob.id, "due_at": None}
    )
    for item in (await items_by_title(kenji, key)).values():
        if item["required"]:
            await kenji.send(
                "PUT", f"/ideas/{key}/research/items/{item['item_id']}", {"answer": "Checked."}
            )
    view = await kenji.get(call_path)
    assert view["summary"] is None
    assert view["permissions"]["can_create"] is False
    await refused(
        kenji, "POST", call_path, {"title": CALL_TITLE}, status=409, code="bid_call_not_available"
    )
    await kenji.send("POST", f"/ideas/{key}/status", {"status": "shortlisted"})
    await kenji.send("POST", f"/ideas/{key}/proposal", None, 201)
    detail = await kenji.get(f"/ideas/{key}")
    assert detail["permissions"]["can_create_bid_call"] is True
    assert detail["bid_call"] is None

    # --- The call: a copy of the project's template, a draft, then open ------------------
    await refused(mateo, "POST", call_path, {"title": "Not mine"}, status=403, code="forbidden")
    created = await kenji.send(
        "POST",
        call_path,
        {"title": CALL_TITLE, "description": "Build and run the sandboxes.", "currency": "GBP"},
        201,
    )
    call_ = created["call"]
    assert call_["status"] == "draft"
    assert [(s["title"], s["weight"]) for s in call_["template"]["sections"]] == [
        ("Technical", 40),
        ("Commercial", 40),
        ("Delivery", 20),
    ]
    must = {m["text"]: m for m in call_["template"]["must_haves"]}
    assert list(must) == [TENDER, PRICING, INSURANCE, TERMS]
    assert must[PRICING]["pricing"]
    sections = {s["title"]: s for s in call_["template"]["sections"]}
    await refused(kenji, "POST", call_path, {"title": "Twice"}, status=409, code="bid_call_exists")
    await refused(
        kenji,
        "POST",
        f"{call_path}/status",
        {"status": "open"},
        status=409,
        code="bid_call_deadline_required",
    )
    deadline = datetime.now(UTC) + timedelta(days=3)
    await kenji.send(
        "PUT",
        call_path,
        {
            "title": CALL_TITLE,
            "description": "Build and run the sandboxes.",
            "currency": "GBP",
            "deadline_at": deadline.isoformat(),
            "ai_assessor_id": None,
        },
    )
    assert (await kenji.send("POST", f"{call_path}/status", {"status": "open"}))["call"][
        "status"
    ] == "open"

    # --- Three bids and their documents; the missing certificate is flagged at once -------
    bids: dict[str, str] = {}
    for bidder in BIDDERS:
        body: dict[str, Any] = {"bidder": bidder, "contact_name": "Sam Example"}
        body["price"] = PRICES.get(bidder, "84000.00")
        if bidder == "Northwind Data Ltd":
            body["contact_email"] = "bids@northwind-data.example"
        bids[bidder] = (await kenji.send("POST", f"{call_path}/bids", body, 201))["id"]
    northwind, tessellate, quillfield = (bids[b] for b in BIDDERS)
    files = {
        northwind: ("northwind", True),
        tessellate: ("tessellate", True),
        quillfield: ("quillfield", False),
    }
    documents: dict[str, dict[str, str]] = {}
    for bid_id, (prefix, insured) in files.items():
        documents[bid_id] = {}
        for suffix, mh in (
            ("form-of-tender.pdf", TENDER),
            ("pricing-schedule.pdf", PRICING),
            ("insurance-certificate.pdf", INSURANCE),
            ("technical-proposal.docx", None),
        ):
            if suffix.startswith("insurance") and not insured:
                continue
            response = await upload(
                kenji,
                key,
                bid_id,
                DOCUMENT_DIR / f"{prefix}-{suffix}",
                must_have_id=must[mh]["id"] if mh else None,
            )
            document = ok(response, 201)
            assert document["extraction"]["state"] == "pending"
            assert document["pricing"] is (mh == PRICING)
            documents[bid_id][suffix] = document["id"]
    flagged = await kenji.get(f"{call_path}/bids/{quillfield}")
    results = {r["must_have"]["text"]: r for r in flagged["must_have_results"]}
    assert (results[INSURANCE]["result"], results[INSURANCE]["automatic"]) == ("missing", True)
    assert results[TENDER]["result"] == "met"
    assert results[TERMS]["result"] == "unchecked"
    assert flagged["status"] == "received"
    assert flagged["permissions"]["reject_suggested"] is True
    assert flagged["must_haves"]["missing"] == 1
    # A duplicate, a macro file and a path in the name are refused.
    again = await upload(
        kenji, key, northwind, DOCUMENT_DIR / "northwind-form-of-tender.pdf", name="again.pdf"
    )
    assert (again.status_code, again.json()["code"]) == (409, "duplicate_document")
    sneaky = await upload(
        kenji, key, northwind, DOCUMENT_DIR / "northwind-form-of-tender.pdf", name="../x.pdf"
    )
    assert sneaky.status_code == 422
    member_upload = await upload(
        farah, key, northwind, DOCUMENT_DIR / "tessellate-form-of-tender.pdf"
    )
    assert member_upload.status_code == 403

    # The worker reads every document's text in its child process.
    async with asyncio.timeout(120):
        while True:
            states = [
                d["extraction"]["state"]
                for bid_id in bids.values()
                for d in (await kenji.get(f"{call_path}/bids/{bid_id}"))["documents"]
            ]
            if "pending" not in states:
                break
            await asyncio.sleep(0.5)
    assert set(states) == {"done"}, states
    proposal_text = await kenji.get(
        f"{call_path}/bids/{northwind}/documents/{documents[northwind]['technical-proposal.docx']}/text?page=1"
    )
    assert proposal_text["state"] == "done"
    assert "Northwind" in proposal_text["text"]
    download = await kenji.http.get(
        f"{API}{call_path}/bids/{northwind}/documents/{documents[northwind]['form-of-tender.pdf']}/content"
    )
    assert download.status_code == 200
    assert download.content == (DOCUMENT_DIR / "northwind-form-of-tender.pdf").read_bytes()
    assert download.headers["content-disposition"].startswith("attachment")
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in download.headers["content-security-policy"]
    assert "no-store" in download.headers["cache-control"]

    # --- Must-haves confirmed; Quillfield rejected in one click with a reason ------------
    for bid_id in bids.values():
        await kenji.send(
            "PUT",
            f"{call_path}/bids/{bid_id}/must-haves/{must[TERMS]['id']}",
            {"result": "met", "note": ""},
        )
    assert (await kenji.get(f"{call_path}/bids/{northwind}"))["status"] == "qualified"
    assert (await kenji.get(f"{call_path}/bids/{tessellate}"))["status"] == "qualified"
    assert (await kenji.get(f"{call_path}/bids/{quillfield}"))["status"] == "received"
    rejected = await kenji.send(
        "PUT", f"{call_path}/bids/{quillfield}/rejection", {"reason": REJECTION}
    )
    assert rejected["status"] == "rejected"
    assert rejected["rejection"]["reason"] == REJECTION
    entry = next(
        e
        for e in await audit(alice, action="bid.reject")
        if e["details"].get("bid_id") == quillfield
    )
    assert REJECTION not in strings(entry)

    # --- Assessors per section, with a due date; "Asked to assess bids" by email --------
    # Well after the demo call's due date, so the reminder scan's days never meet its own
    # (TOOLS-3's "on the due date" reminder for alice).
    demo_due = datetime.fromisoformat(
        (await kenji.get("/ideas/TOOLS-3/bid-call"))["call"]["assessment_due_at"]
    )
    due = max(datetime.now(UTC), demo_due) + timedelta(days=6)
    assessors = {"Technical": [carol, mateo], "Commercial": [priya], "Delivery": [sven]}

    def assessor_body(extra: dict[str, list[str]] | None = None) -> dict[str, Any]:
        return {
            "sections": [
                {
                    "section_id": sections[title]["id"],
                    "user_ids": [p.id for p in people] + (extra or {}).get(title, []),
                }
                for title, people in assessors.items()
            ],
            "due_at": due.isoformat(),
        }

    # Bob researches the idea but has no role in the private project: not eligible (c28).
    problem = await refused(
        kenji,
        "PUT",
        f"{call_path}/assessors",
        assessor_body({"Delivery": [bob.id]}),
        status=422,
        code="assessor_not_eligible",
    )
    # It names the person by name, never by id (the SPA shows the message: P10-QA-N2).
    assert problem["errors"][0]["msg"] == f"{bob.name} can't assess bids on this idea"
    assert bob.id not in strings(problem)
    await kenji.send("PUT", f"{call_path}/assessors", assessor_body())
    asked = re.compile(rf'Please assess the bids for "{re.escape(CALL_TITLE)}"')
    for person in (carol, mateo, priya, sven):
        message = await wait_mail(inbox, person.email, asked)
        text = mail_text(message)
        assert CALL_TITLE in text
        assert f"/ideas/{key}?tab=bids" in text
        no_scores_in_mail(f"asked {person.name}", text)
    assert "Commercial" in mail_text(await wait_mail(inbox, priya.email, asked))
    assert await mail_to(inbox, kenji.email, asked) == []  # never the actor
    items = [
        i
        for i in await inbox_items(sven)
        if i["type"] == "assessor_assigned" and i["idea"]["key"] == key
    ]
    assert len(items) == 1
    assert not bid_secrets(strings(items[0]))

    closed = await kenji.send("POST", f"{call_path}/status", {"status": "assessing"})
    assert closed["call"]["status"] == "assessing"
    await refused(
        kenji,
        "POST",
        f"{call_path}/bids",
        {"bidder": "Too late"},
        status=409,
        code="bid_call_not_open",
    )

    # --- The AI assessor through MCP via the fake agent --------------------------------
    agent, secret = await register_agent(alice, f"bids-{uuid.uuid4().hex[:6]}", project["id"])
    fake_agent.give_key(agent["name"], secret)
    inventor, inventor_secret = await register_agent(
        alice, f"bids-{uuid.uuid4().hex[:6]}-invents", project["id"]
    )
    fake_agent.give_key(inventor["name"], inventor_secret)
    slow, slow_secret = await register_agent(
        alice, f"bids-{uuid.uuid4().hex[:6]}-slow", project["id"]
    )
    fake_agent.give_key(slow["name"], slow_secret)
    ask = f"{call_path}/bids/{tessellate}/ai-assessment"
    first = await kenji.send("POST", ask, {"agent_id": agent["id"]}, 201)
    assert (await kenji.send("POST", ask, {"agent_id": agent["id"]}, 200))["id"] == first["id"]
    run = await wait_run(kenji, key, first["id"])
    assert run["status"] == "succeeded", run
    assert run["bid_id"] == tessellate
    assert run["result"]["bid_ai_assessment_id"]
    assert not bid_secrets(strings(run["events"]))
    seen = await fake_agent.observations(first["id"])
    assert seen is not None
    assert seen["assess"] is not None
    assert documents[tessellate]["pricing-schedule.pdf"] not in seen["assess"]["documents_listed"]
    assert seen["message_checks"] == {"has_url": False, "has_api_key": False}
    listed = await kenji.get(f"{call_path}/bids/{tessellate}/ai-assessments")
    (ai_tessellate,) = listed["items"]
    assert ai_tessellate["included"] is False
    assert ai_tessellate["quotes_not_found"] == 0
    assert all(e["found"] for s in ai_tessellate["scores"] for e in s["evidence"])
    score_questions = [
        q["id"]
        for s in call_["template"]["sections"]
        for q in s["questions"]
        if q["type"] == "score"
    ]
    assert sorted(s["question_id"] for s in ai_tessellate["scores"]) == sorted(score_questions)
    # One finding per must-have it was shown: never the pricing one (it can't read it).
    assert len(ai_tessellate["findings"]) == len(must) - 1
    by_must_have = {
        r["must_have"]["text"]: r["ai_findings"]
        for r in (await kenji.get(f"{call_path}/bids/{tessellate}"))["must_have_results"]
    }
    assert by_must_have[PRICING] == []
    assert all(len(by_must_have[text]) == 1 for text in (TENDER, INSURANCE, TERMS))
    # Findings are suggestions: the results stay as people (and documents) decided.
    assert (await kenji.get(f"{call_path}/bids/{tessellate}"))["status"] == "qualified"
    # An invented quote is marked "not found in the document".
    invented = await kenji.send(
        "POST", f"{call_path}/bids/{northwind}/ai-assessment", {"agent_id": inventor["id"]}, 201
    )
    assert (await wait_run(kenji, key, invented["id"]))["status"] == "succeeded"
    (ai_northwind,) = (await kenji.get(f"{call_path}/bids/{northwind}/ai-assessments"))["items"]
    assert ai_northwind["quotes_not_found"] >= 1
    assert any(not e["found"] for s in ai_northwind["scores"] for e in s["evidence"])

    # c22: an agent's key in its run reaches that run's bid and nothing else.
    slow_run = await kenji.send(
        "POST", f"{call_path}/bids/{northwind}/ai-assessment", {"agent_id": slow["id"]}, 201
    )
    await wait_status(kenji, key, slow_run["id"], "running")
    async with mcp_client(live, slow_secret) as agent_mcp:
        mine = data(
            await call(agent_mcp, "get_bid_for_assessment", bid_id=northwind, run_id=slow_run["id"])
        )
        assert mine["bid"]["id"] == northwind
        assert "price" not in strings(mine["bid"]).lower()
        assert documents[northwind]["pricing-schedule.pdf"] not in strings(mine)
        assert (
            error(
                await call(
                    agent_mcp, "get_bid_for_assessment", bid_id=tessellate, run_id=slow_run["id"]
                )
            )
            == "ai_run_not_active"
        )
        assert (
            error(
                await call(
                    agent_mcp, "get_bid_for_assessment", bid_id=northwind, run_id=first["id"]
                )
            )
            == "ai_run_not_active"
        )
        assert (
            error(
                await call(
                    agent_mcp,
                    "get_bid_document_text",
                    bid_id=northwind,
                    document_id=documents[northwind]["pricing-schedule.pdf"],
                    page=1,
                    run_id=slow_run["id"],
                )
            )
            == "not_found"
        )
        assert (
            error(
                await call(
                    agent_mcp,
                    "get_bid_document_text",
                    bid_id=northwind,
                    document_id=documents[tessellate]["technical-proposal.docx"],
                    page=1,
                    run_id=slow_run["id"],
                )
            )
            == "not_found"
        )
        assert (
            error(await call(agent_mcp, "get_idea", idea=key, run_id=slow_run["id"]))
            == "ai_run_not_active"
        )
        assert (
            error(await call(agent_mcp, "search_ideas", query=TITLE, run_id=slow_run["id"]))
            == "ai_run_not_active"
        )
    async with key_client(live, slow_secret) as agent_rest:
        assert (await agent_rest.get(f"{API}{call_path}")).status_code == 403
    await kenji.send("POST", f"/ideas/{key}/ai-runs/{slow_run['id']}/cancel")
    assert (await wait_run(kenji, key, slow_run["id"]))["status"] == "cancelled"

    # --- Blind: probe carol on every surface before she submits Technical ---------------
    technical = sections["Technical"]["id"]
    for bidder, by_section in SCORES.items():
        await mateo.send(
            "PUT",
            f"{call_path}/bids/{bids[bidder]}/sections/{technical}/assessment",
            {
                "answers": answers(sections["Technical"], by_section["Technical"]["mateo"]),
                "submit": True,
            },
        )
    await carol.send(
        "PUT",
        f"{call_path}/bids/{northwind}/sections/{technical}/assessment",
        {"answers": answers(sections["Technical"], [1, 1]), "submit": False},
    )  # a draft changes nothing
    before = await carol.get(f"{call_path}/bids/{northwind}/sections/{technical}/assessments")
    assert before["hidden"] is True
    assert before["assessments"] == []
    assert before["ai"] == []
    assert all(q["mean"] is None and q["count"] == 0 for q in before["questions"])
    assert before["section_score"] is None
    for path in ("comparison", f"bids/{northwind}/ai-assessments", "report/markdown", "report/pdf"):
        assert await carol.status("GET", f"{call_path}/{path}") == 403, path
    await refused(
        carol,
        "GET",
        f"{call_path}/bids/{northwind}/sections/{sections['Delivery']['id']}/assessments",
        status=403,
        code="not_section_assessor",
    )
    assessor_bid = await carol.get(f"{call_path}/bids/{northwind}")
    assert (assessor_bid["price"], assessor_bid["price_hidden"]) == (None, True)
    assert (assessor_bid["contact_email"], assessor_bid["notes"]) in ((None, ""), ("", ""))
    assert documents[northwind]["pricing-schedule.pdf"] not in strings(assessor_bid)
    assert assessor_bid["restricted_document_count"] == 1
    pricing_state = next(
        r for r in assessor_bid["must_have_results"] if r["must_have"]["id"] == must[PRICING]["id"]
    )
    assert pricing_state["document_ids"] == []
    assert pricing_state["restricted_document_count"] == 1
    for tail in ("text?page=1", "content"):
        assert (
            await carol.status(
                "GET",
                f"{call_path}/bids/{northwind}/documents/{documents[northwind]['pricing-schedule.pdf']}/{tail}",
            )
            == 404
        )
    assert await carol.status("GET", f"{call_path}/bids/{quillfield}") == 404
    assert [b["id"] for b in (await carol.get(f"{call_path}/bids"))["items"]] == [
        northwind,
        tessellate,
    ]
    carol_view = await carol.get(call_path)
    assert carol_view["call"]["award_reason"] is None
    assert not carol_view["permissions"]["can_see_prices"]
    work = await carol.get("/me/work")
    (item,) = [w for w in work["bids_to_assess"] if w["idea"]["key"] == key]
    assert item["progress"] == {"submitted": 0, "total": 2}
    assert not bid_secrets(strings(item))
    assert "score" not in strings(item).lower()
    assert (await carol.get("/me/work/counts"))["bid_assessments_due"] >= 2
    for item in await inbox_items(carol):
        assert not bid_secrets(strings(item)), item
    idea_view = await carol.get(f"/ideas/{key}")
    assert set(idea_view["bid_call"]) >= {"title", "status", "bid_count"}
    assert not bid_secrets(strings(idea_view))
    # Assess runs name bids, so an assessor (bid.view_bids) may list them; never a score.
    runs = await carol.get(f"/ideas/{key}/ai-runs")
    assert {r["id"] for r in runs["items"]} >= {first["id"], invented["id"]}
    assert not re.search(r'"score"\s*:\s*\d', strings(runs))
    carol_key = (
        await carol.send(
            "POST", "/me/api-keys", {"name": "ac10 read", "scopes": ["read", "mcp"]}, 201
        )
    )["secret"]
    async with mcp_client(live, carol_key) as carol_mcp:
        for found in (
            data(await call(carol_mcp, "get_idea", idea=key)),
            data(await call(carol_mcp, "search_ideas", query=TITLE)),
        ):
            assert not bid_secrets(strings(found))
            assert "bid_call" not in strings(found)
        assert (
            error(await call(carol_mcp, "get_bid_for_assessment", bid_id=northwind)) == "forbidden"
        )
    # Priya assesses the section with the price: prices and the pricing schedule.
    priya_bid = await priya.get(f"{call_path}/bids/{northwind}")
    assert priya_bid["price"] == "120000.00"
    assert documents[northwind]["pricing-schedule.pdf"] in strings(priya_bid)
    assert (
        await priya.get(
            f"{call_path}/bids/{northwind}/documents/{documents[northwind]['pricing-schedule.pdf']}/text?page=1"
        )
    )["state"] == "done"
    assert (await sven.get(f"{call_path}/bids/{northwind}"))["price"] is None

    # After submitting: carol sees mateo's scores and the AI's for Technical, nothing else.
    for bidder, by_section in SCORES.items():
        submitted = await carol.send(
            "PUT",
            f"{call_path}/bids/{bids[bidder]}/sections/{technical}/assessment",
            {
                "answers": answers(sections["Technical"], by_section["Technical"]["carol"]),
                "submit": True,
            },
        )
        assert submitted["state"] == "submitted"
    after = await carol.get(f"{call_path}/bids/{northwind}/sections/{technical}/assessments")
    assert after["hidden"] is False
    assert {a["assessor"]["id"] for a in after["assessments"]} == {
        carol.id,
        mateo.id,
    }
    assert [a["ai_assessment_id"] for a in after["ai"]] == [ai_northwind["id"]]
    disagreeing = await carol.get(f"{call_path}/bids/{tessellate}/sections/{technical}/assessments")
    assert disagreeing["questions"][0]["disagreement"] is True  # 4 and 2
    assert await carol.status("GET", f"{call_path}/comparison") == 403  # totals stay with managers
    # The template is locked by the first person's submission.
    template = (await kenji.get(call_path))["call"]["template"]
    assert template["locked"] is True

    # --- The reminder fires with a moved clock (sven owes Delivery) ----------------------
    commercial = sections["Commercial"]["id"]
    for bidder, by_section in SCORES.items():
        await priya.send(
            "PUT",
            f"{call_path}/bids/{bids[bidder]}/sections/{commercial}/assessment",
            {
                "answers": answers(sections["Commercial"], by_section["Commercial"]["priya"]),
                "submit": True,
            },
        )
    reminder = re.compile(rf'Reminder: bid assessments for "{re.escape(CALL_TITLE)}" are due')
    two_days_before = at_digest_hour(due - timedelta(days=2), settings)
    assert await remind(app, settings, at_digest_hour(due - timedelta(days=1), settings)) == 0
    assert await remind(app, settings, two_days_before) == 1  # sven only
    assert await remind(app, settings, two_days_before + timedelta(minutes=20)) == 0  # once
    # The reminder's email is due at the moved hour: the worker sends it then (its clock).
    assert workers.runtime is not None
    async with app.state.sessionmaker() as db:
        reminder_rows = await emails_to(db, sven.id, "assessment_reminder")
    assert [row.status for row in reminder_rows] == [EmailStatus.QUEUED]
    workers.clock.now = two_days_before + timedelta(minutes=1)
    assert await email_delivery.send_email(workers.runtime, reminder_rows[0].id) == "sent"
    workers.clock.now = None
    message = await wait_mail(inbox, sven.email, reminder)
    no_scores_in_mail("reminder", mail_text(message))
    for person in (carol, mateo, priya, kenji):
        assert await mail_to(inbox, person.email, reminder) == [], person.name
    reminders = [
        i
        for i in await inbox_items(sven)
        if i["type"] == "assessment_reminder" and i["idea"]["key"] == key
    ]
    assert len(reminders) == 1

    # --- Sven submits the last section: "All bid assessments are in" reaches kenji -------
    delivery = sections["Delivery"]["id"]
    complete = re.compile(rf'All bid assessments are in for "{re.escape(CALL_TITLE)}"')
    for bidder, by_section in SCORES.items():
        await sven.send(
            "PUT",
            f"{call_path}/bids/{bids[bidder]}/sections/{delivery}/assessment",
            {
                "answers": answers(sections["Delivery"], by_section["Delivery"]["sven"]),
                "submit": True,
            },
        )
    no_scores_in_mail("complete", mail_text(await wait_mail(inbox, kenji.email, complete)))
    await asyncio.sleep(1)
    assert len(await mail_to(inbox, kenji.email, complete)) == 1
    for person in (sven, carol, dave):
        assert await mail_to(inbox, person.email, complete) == [], person.name

    # --- The comparison: the contract's math, the AI out and then in --------------------
    numbers = await kenji.get(f"{call_path}/comparison")
    assert numbers["complete"] is True
    assert numbers["ranking_hidden"] is False
    assert numbers["progress"] == {"submitted": 8, "total": 8}
    rows = {r["bid"]["bidder"]: r for r in numbers["rows"]}
    want = expected_comparison(call_, SCORES, {})
    for bidder, expected in want.items():
        row = rows[bidder]
        assert [s["score"] for s in row["sections"]] == expected["sections"], bidder
        assert (row["total"], row["price_score"], row["ai_included"]) == (
            expected["total"],
            expected["price_score"],
            False,
        )
    assert (rows["Northwind Data Ltd"]["rank"], rows["Tessellate Software"]["rank"]) == (1, 2)
    assert rows["Tessellate Software"]["sections"][0]["disagreement"] is True
    assert (rows["Quillfield Systems"]["total"], rows["Quillfield Systems"]["rank"]) == (None, None)
    assert all(s["score"] is None for s in rows["Quillfield Systems"]["sections"])
    assert [r["bid"]["bidder"] for r in numbers["rows"]] == list(BIDDERS)
    ai_scores = {
        "Tessellate Software": {s["question_id"]: s["score"] for s in ai_tessellate["scores"]}
    }
    with_ai = expected_comparison(call_, SCORES, ai_scores)
    await kenji.send(
        "PUT",
        f"{call_path}/bids/{tessellate}/ai-assessments/{ai_tessellate['id']}/include-in-totals",
        {"include": True},
    )
    included = {r["bid"]["bidder"]: r for r in (await kenji.get(f"{call_path}/comparison"))["rows"]}
    assert included["Tessellate Software"]["ai_included"] is True
    assert included["Tessellate Software"]["total"] == with_ai["Tessellate Software"]["total"]
    assert [s["score"] for s in included["Tessellate Software"]["sections"]] == with_ai[
        "Tessellate Software"
    ]["sections"]
    assert included["Northwind Data Ltd"]["total"] == want["Northwind Data Ltd"]["total"]
    await kenji.send(
        "PUT",
        f"{call_path}/bids/{tessellate}/ai-assessments/{ai_tessellate['id']}/include-in-totals",
        {"include": False},
    )
    left_out = {r["bid"]["bidder"]: r for r in (await kenji.get(f"{call_path}/comparison"))["rows"]}
    assert left_out["Tessellate Software"]["total"] == want["Tessellate Software"]["total"]

    # --- Who else sees what: a member, a viewer, the guest researcher -------------------
    for person in (farah, zanele):
        summary = await person.get(call_path)
        assert summary["call"] is None
        assert summary["summary"]["bid_count"] == 3
        assert not bid_secrets(strings(summary)), person.name
        for path in (
            "bids",
            f"bids/{northwind}",
            "comparison",
            "report/pdf",
            f"bids/{northwind}/ai-assessments",
        ):
            assert await person.status("GET", f"{call_path}/{path}") == 403, (person.name, path)
        # The same 403 for a bid that doesn't exist (the call-level rule comes first).
        assert await person.status("GET", f"{call_path}/bids/{uuid.uuid4()}") == 403
        assert first["id"] not in strings(await person.get(f"/ideas/{key}/ai-runs"))
        assert await person.status("GET", f"/ideas/{key}/ai-runs/{first['id']}") == 404
        assert await person.status("GET", f"/ideas/{key}/ai-runs/{first['id']}/events") == 404
        assert not bid_secrets(strings(await person.get(f"/ideas/{key}")))
    guest = await bob.get(f"/ideas/{key}")
    assert guest["bid_call"] is None
    assert guest["permissions"]["can_view_bid_call"] is False
    for path in (
        "",
        "/bids",
        f"/bids/{northwind}",
        "/comparison",
        "/report/markdown",
        f"/bids/{northwind}/sections/{technical}/assessment",
    ):
        assert await bob.status("GET", f"{call_path}{path}") == 404, path
    assert await bob.status("GET", f"/ideas/{key}/ai-runs/{first['id']}") == 404
    assert all(i["type"] != "bid_call_changed" for i in await feed(bob, key))
    assert not bid_secrets(strings(await feed(bob, key)))

    # --- The award: one qualified bid; the same numbers after; read-only ---------------
    await refused(
        kenji, "POST", f"{call_path}/award", {"bid_id": quillfield}, status=409, code="bid_rejected"
    )
    awarded = await kenji.send(
        "POST", f"{call_path}/award", {"bid_id": northwind, "reason": "Best value overall."}
    )
    assert awarded["call"]["status"] == "awarded"
    assert awarded["call"]["awarded_bid"]["id"] == northwind
    statuses = {b["bidder"]: b["status"] for b in (await kenji.get(f"{call_path}/bids"))["items"]}
    assert statuses == {
        "Northwind Data Ltd": "awarded",
        "Tessellate Software": "unsuccessful",
        "Quillfield Systems": "rejected",
    }
    after_award = {
        r["bid"]["bidder"]: r for r in (await kenji.get(f"{call_path}/comparison"))["rows"]
    }
    for bidder, expected in want.items():
        assert after_award[bidder]["total"] == expected["total"]
    assert after_award["Northwind Data Ltd"]["rank"] == 1
    await refused(
        kenji,
        "POST",
        f"{call_path}/bids",
        {"bidder": "After"},
        status=409,
        code="bid_call_finished",
    )
    changes = [i for i in await feed(zanele, key) if i["type"] == "bid_call_changed"]
    assert "awarded" in [c["to_status"] for c in changes]
    assert not bid_secrets(strings(changes))

    # --- The report: Markdown and PDF for a call manager only ---------------------------
    markdown = await kenji.http.get(f"{API}{call_path}/report/markdown")
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    report = markdown.text
    for text in (
        *BIDDERS,
        REJECTION,
        str(want["Northwind Data Ltd"]["total"]),
        "Best value overall.",
    ):
        assert text in report, text
    pdf = await kenji.http.get(f"{API}{call_path}/report/pdf", timeout=60)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")
    assert f"{key}-bid-evaluation.pdf" in pdf.headers["content-disposition"]
    reader = pypdf.PdfReader(io.BytesIO(pdf.content))
    pdf_text = " ".join(" ".join((page.extract_text() or "").split()) for page in reader.pages)
    assert re.search(r"bid evaluation report", pdf_text, re.I)
    for text in (*BIDDERS, REJECTION, CALL_TITLE):
        assert text in pdf_text, text
    for person, status in ((carol, 403), (zanele, 403), (farah, 403), (bob, 404)):
        assert await person.status("GET", f"{call_path}/report/pdf") == status, person.name


def answers(section: dict[str, Any], scores: list[int]) -> list[dict[str, Any]]:
    """An assessment's answers: ``scores`` for the score questions in order, a comment for
    comment questions, nothing for the price question."""
    out: list[dict[str, Any]] = []
    values = iter(scores)
    for question in section["questions"]:
        if question["type"] == "score":
            out.append({"question_id": question["id"], "score": next(values)})
        elif question["type"] == "comment":
            out.append({"question_id": question["id"], "comment": "Looks workable."})
    return out


# --- AC10-API-2 -----------------------------------------------------------------------------
async def test_ac10_api_2_the_demo_call_and_keys_per_scope(live: str, crew: Crew) -> None:
    alice, carol, dave, kenji = crew["alice"], crew["carol"], crew["dave"], crew["kenji"]
    priya, zanele, bob = crew["priya"], crew["zanele"], crew["bob"]
    path = "/ideas/TOOLS-3/bid-call"
    view = await kenji.get(path)
    call_ = view["call"]
    assert (call_["title"], call_["status"]) == ("Data platform build", "assessing")
    assessors = {
        s["title"]: sorted(a["user"]["display_name"].split()[0] for a in s["assessors"])
        for s in call_["template"]["sections"]
    }
    assert assessors == {
        "Technical": ["Carol", "Mateo"],
        "Commercial": ["Priya"],
        "Delivery": ["Alice", "Sven"],
    }
    rows = {r["bid"]["bidder"]: r for r in (await kenji.get(f"{path}/comparison"))["rows"]}
    assert (rows["Northwind Data Ltd"]["rank"], rows["Northwind Data Ltd"]["total"]) == (1, 84.0)
    assert (rows["Tessellate Software"]["rank"], rows["Tessellate Software"]["total"]) == (2, 71.2)
    assert rows["Tessellate Software"]["ai_included"] is False
    assert rows["Quillfield Systems"]["bid"]["status"] == "rejected"
    assert rows["Quillfield Systems"]["total"] is None
    # Alice (a platform admin) owes both Delivery assessments: no ranks at all for her.
    hers = await alice.get(f"{path}/comparison")
    assert hers["ranking_hidden"] is True
    assert all(r["rank"] is None for r in hers["rows"])
    assert all(r["total_hidden"] for r in hers["rows"] if r["bid"]["status"] != "rejected")
    assert (await alice.get("/me/work/counts"))["bid_assessments_due"] == 2
    # Prices: priya (Commercial) yes, carol (Technical) no; zanele the summary; bob nothing.
    bids = {b["bidder"]: b for b in (await priya.get(f"{path}/bids"))["items"]}
    assert bids["Northwind Data Ltd"]["price"] == "120000.00"
    assert all(b["price"] is None for b in (await carol.get(f"{path}/bids"))["items"])
    summary = await zanele.get(path)
    assert summary["call"] is None
    assert summary["summary"]["bid_count"] == 3
    assert await bob.status("GET", path) == 404

    # A person's API key: the person's rights ∩ the key's scopes; session-only routes refused.
    def key_for(person: Person, scopes: list[str]) -> Any:
        return person.send(
            "POST", "/me/api-keys", {"name": f"ac10 {'+'.join(scopes)}", "scopes": scopes}, 201
        )

    northwind = bids["Northwind Data Ltd"]["id"]
    sections = {s["title"]: s for s in call_["template"]["sections"]}
    read = (await key_for(carol, ["read"]))["secret"]
    evaluate = (await key_for(carol, ["evaluate"]))["secret"]
    write = (await key_for(kenji, ["write"]))["secret"]
    mcp_only = (await key_for(kenji, ["mcp"]))["secret"]
    technical = sections["Technical"]["id"]
    body = {"answers": answers(sections["Technical"], [4, 4]), "submit": True}
    async with key_client(live, read) as carol_read:
        assert (await carol_read.get(f"{API}{path}/bids/{northwind}")).status_code == 200
        assert (
            await carol_read.get(f"{API}{path}/bids/{northwind}/sections/{technical}/assessment")
        ).status_code == 200
        response = await carol_read.put(
            f"{API}{path}/bids/{northwind}/sections/{technical}/assessment", json=body
        )
        assert (response.status_code, response.json()["code"]) == (403, "insufficient_scope")
    async with key_client(live, evaluate) as carol_evaluate:
        response = await carol_evaluate.put(
            f"{API}{path}/bids/{northwind}/sections/{technical}/assessment", json=body
        )
        assert response.status_code == 200, response.text
    async with key_client(live, write) as kenji_write:
        assert (await kenji_write.get(f"{API}{path}/comparison")).status_code == 200
        for method, tail, payload in (
            ("PUT", f"/bids/{northwind}/rejection", {"reason": "No."}),
            ("POST", "/award", {"bid_id": northwind}),
            (
                "PUT",
                "/assessors",
                {"sections": [{"section_id": technical, "user_ids": []}], "due_at": None},
            ),
            ("POST", "/cancellation", {}),
        ):
            response = await kenji_write.request(method, f"{API}{path}{tail}", json=payload)
            assert (response.status_code, response.json()["code"]) == (403, "insufficient_scope"), (
                tail
            )
        upload_ = await kenji_write.post(
            f"{API}{path}/bids/{northwind}/documents",
            params={"filename": "x.pdf"},
            content=b"%PDF-1.4\n",
            headers={"Content-Type": "application/octet-stream"},
        )
        assert upload_.status_code == 403
    async with key_client(live, mcp_only) as kenji_mcp:
        assert (await kenji_mcp.get(f"{API}{path}")).status_code == 403
    # Nothing changed for the session: dave (project admin) still sees the story.
    assert (await dave.get(f"{path}/comparison"))["rows"][0]["bid"][
        "bidder"
    ] == "Northwind Data Ltd"
