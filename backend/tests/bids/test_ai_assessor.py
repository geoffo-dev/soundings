"""The AI assessor (contract-phase10 section 9, role matrix c22 and table M): asking for
assess runs (who, states, the hourly limit, "Assess all"), who sees them, the three MCP
tools bound to the run's bid (never pricing documents, prices or other bids), quote checks,
the assessment and its inclusion, the automatic pre-check, and a run end to end through
the fake kagent."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.runner import AiRuntime, execute_run
from app.bids import assess
from app.bids.extraction import extract_document
from app.config import Settings
from app.models.ai import AiRun
from app.models.base import utcnow
from app.models.bid import Bid, BidAiAssessment, BidCall, BidDocument
from app.models.enums import AiRunKind, AiRunStatus, BidCallStatus
from app.schemas.ai import AI_RUNS_PER_USER_PER_HOUR
from app.schemas.bids import quotes_found
from tests.ai.fake_kagent import FakeKagent
from tests.ai.helpers import Agent, make_agent, run_row
from tests.api_keys.helpers import key_client
from tests.api_keys.helpers import make_key as make_person_key
from tests.bids import files
from tests.bids.conftest import (
    API,
    Api,
    AsUser,
    Crew,
    add_bid,
    assert_problem,
    assign,
    bid_detail,
    call_url,
    must_haves,
    ok,
    open_call,
    start,
    upload,
)
from tests.mcp.conftest import Agent as McpIdentity
from tests.mcp.conftest import Connect, connect, make_key  # noqa: F401 - fixtures

TENDER = "We hereby submit our signed form of tender for the data platform build."
SECURITY = "We hold ISO 27001 certification for every hosting site we operate."
INGEST = "Our platform ingests data from every source in near real time."


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {"ai_enabled": True}


@dataclass
class Scene:
    owner: Api
    view: dict[str, Any]
    call_id: UUID
    bid: dict[str, Any]
    other: dict[str, Any]
    agent: Agent
    documents: dict[str, str]

    @property
    def must(self) -> dict[str, dict[str, Any]]:
        return must_haves(self.view)


@pytest.fixture
async def scene(api: AsUser, crew: Crew, db_session: AsyncSession, app: FastAPI) -> Scene:
    owner = await api(crew.owner)
    view = await start(owner, crew)
    view = await open_call(owner, crew, view)
    await assign(owner, crew, view, {"Technical": [crew.tech1], "Commercial": [crew.commercial]})
    bid = await add_bid(owner, crew, "Northwind Data Ltd", price="120000.00")
    other = await add_bid(owner, crew, "Tessellate Software", price="96000.00")
    view = ok(await owner.get(call_url(crew)))
    must = must_haves(view)
    uploads = {
        "tender": (bid, files.pdf(TENDER), "Tender.pdf", must["Signed form of tender"]["id"]),
        "technical": (bid, files.docx(INGEST, SECURITY), "Technical.docx", None),
        "prices": (
            bid,
            files.xlsx("Total price", "120000"),
            "Prices.xlsx",
            must["Pricing schedule"]["id"],
        ),
        "other": (other, files.pdf("Tessellate's own tender text for the test."), "T.pdf", None),
    }
    documents: dict[str, str] = {}
    for name, (target, data, filename, must_have_id) in uploads.items():
        params = {"must_have_id": must_have_id} if must_have_id else {}
        document = ok(await upload(owner, crew, target["id"], data, filename, **params), 201)
        await extract_document(app.state.sessionmaker, UUID(document["id"]))
        documents[name] = document["id"]
    agent = await make_agent(
        db_session, [crew.project], purposes=[AiRunKind.ASSESS_BID], key=True, name="bid-assessor"
    )
    return Scene(
        owner=owner,
        view=view,
        call_id=UUID(view["call"]["id"]),
        bid=bid,
        other=other,
        agent=agent,
        documents=documents,
    )


def ask_url(crew: Crew, bid_id: str) -> str:
    return call_url(crew, f"/bids/{bid_id}/ai-assessment")


async def assess_run(
    db: AsyncSession,
    scene: Scene,
    crew: Crew,
    bid_id: str | None = None,
    *,
    kind: AiRunKind = AiRunKind.ASSESS_BID,
    status: AiRunStatus = AiRunStatus.RUNNING,
) -> AiRun:
    now = utcnow()
    run = AiRun(
        id=uuid4(),
        idea_id=crew.idea.id,
        agent_id=scene.agent.id,
        kind=kind,
        bid_id=UUID(bid_id or scene.bid["id"]) if kind is AiRunKind.ASSESS_BID else None,
        bid_call_id=scene.call_id if kind is AiRunKind.ASSESS_BID else None,
        requested_by_id=crew.owner.id,
        status=status,
        timeout_seconds=300,
        created_at=now,
        started_at=now if status is AiRunStatus.RUNNING else None,
        heartbeat_at=now if status is AiRunStatus.RUNNING else None,
    )
    db.add(run)
    await db.commit()
    return run


@pytest.fixture
def agent_mcp(scene: Scene, connect: Connect) -> McpIdentity:  # noqa: F811 - the fixture
    assert scene.agent.key is not None
    return McpIdentity(connect, scene.agent.key)


def questions(scene: Scene) -> list[dict[str, Any]]:
    return [
        q
        for section in scene.view["call"]["template"]["sections"]
        for q in section["questions"]
        if q["type"] == "score"
    ]


def submission(scene: Scene, *, score: int = 4, quote: str = SECURITY) -> dict[str, Any]:
    """A complete assessment of ``scene.bid``: every score question and the must-haves the
    AI is shown (pricing ones aren't), quoting the technical response."""
    evidence = [{"document_id": scene.documents["technical"], "quote": quote}]
    return {
        "bid_id": scene.bid["id"],
        "scores": [
            {
                "question_id": q["id"],
                "score": score,
                "rationale": "Clear and complete.",
                "evidence": evidence,
            }
            for q in questions(scene)
        ],
        "findings": [
            {
                "must_have_id": m["id"],
                "finding": "unclear",
                "rationale": "Nothing in the documents says so.",
                "evidence": [],
            }
            for m in scene.view["call"]["template"]["must_haves"]
            if not m["pricing"]
        ],
    }


# --- Asking --------------------------------------------------------------------------------------
async def test_ask_ai_to_assess(scene: Scene, crew: Crew, db_session: AsyncSession) -> None:
    body = {"agent_id": str(scene.agent.id)}
    first = await scene.owner.post(ask_url(crew, scene.bid["id"]), body)
    run = ok(first, 201)
    again = ok(await scene.owner.post(ask_url(crew, scene.bid["id"]), body), 200)

    assert again["id"] == run["id"]
    assert run["kind"] == "assess_bid"
    assert run["bid_id"] == scene.bid["id"]
    assert run["automatic"] is False
    assert run["requested_by"]["id"] == str(crew.owner.id)
    assert run["status"] == "queued"
    jobs = await db_session.scalar(
        text("SELECT count(*) FROM procrastinate_jobs WHERE task_name = 'run_ai'")
    )
    assert jobs == 1
    audit = await db_session.scalar(
        text("SELECT details->>'bid_id' FROM audit_log WHERE action = 'ai_run.request'")
    )
    assert audit == scene.bid["id"]


@pytest.mark.parametrize(
    ("who", "status"),
    [
        ("admin", 201),
        ("platform", 201),
        ("member", 403),
        ("tech1", 403),
        ("commercial", 403),
        ("viewer", 403),
        ("outsider", 404),
    ],
)
async def test_who_may_ask(scene: Scene, crew: Crew, api: AsUser, who: str, status: int) -> None:
    user = await api(getattr(crew, who))
    response = await user.post(ask_url(crew, scene.bid["id"]), {"agent_id": str(scene.agent.id)})
    assert response.status_code == status, response.text


async def test_keys_need_write(
    scene: Scene, crew: Crew, db_session: AsyncSession, app: FastAPI
) -> None:
    read = await make_person_key(db_session, crew.owner, scopes=["read"])
    write = await make_person_key(db_session, crew.owner, scopes=["write"])
    body = {"agent_id": str(scene.agent.id)}
    async with key_client(app, read) as http:
        refused = await http.post(API + ask_url(crew, scene.bid["id"]), json=body)
    async with key_client(app, write) as http:
        asked = await http.post(API + ask_url(crew, scene.bid["id"]), json=body)
    assert_problem(refused, 403, "insufficient_scope")
    assert asked.status_code == 201, asked.text


async def test_states_that_refuse(
    scene: Scene, crew: Crew, db_session: AsyncSession, api: AsUser
) -> None:
    body = {"agent_id": str(scene.agent.id)}
    ok(
        await scene.owner.put(
            call_url(crew, f"/bids/{scene.other['id']}/rejection"), {"reason": "Late."}
        )
    )
    assert_problem(
        await scene.owner.post(ask_url(crew, scene.other["id"]), body), 409, "bid_rejected"
    )
    unknown = {"agent_id": str(uuid4())}
    assert_problem(
        await scene.owner.post(ask_url(crew, scene.bid["id"]), unknown), 409, "ai_unavailable"
    )
    call = await db_session.get(BidCall, scene.call_id)
    assert call is not None
    call.status = BidCallStatus.DRAFT
    await db_session.commit()
    assert_problem(
        await scene.owner.post(ask_url(crew, scene.bid["id"]), body), 409, "bid_call_not_assessable"
    )
    call.status = BidCallStatus.CANCELLED
    call.cancelled_at = utcnow()
    await db_session.commit()
    assert_problem(
        await scene.owner.post(ask_url(crew, scene.bid["id"]), body), 409, "bid_call_finished"
    )


@pytest.mark.settings(ai_enabled=False)
async def test_ai_off_is_ai_unavailable(scene: Scene, crew: Crew) -> None:
    response = await scene.owner.post(
        ask_url(crew, scene.bid["id"]), {"agent_id": str(scene.agent.id)}
    )
    assert_problem(response, 409, "ai_unavailable")


async def _fill_hour(db: AsyncSession, scene: Scene, crew: Crew, count: int) -> None:
    for _ in range(count):
        db.add(
            AiRun(
                id=uuid4(),
                idea_id=crew.idea.id,
                agent_id=scene.agent.id,
                kind=AiRunKind.RESEARCH,
                requested_by_id=crew.owner.id,
                status=AiRunStatus.CANCELLED,
                timeout_seconds=300,
                created_at=utcnow() - timedelta(minutes=10),
                finished_at=utcnow(),
                cancel_requested_at=utcnow(),
            )
        )
    await db.commit()


async def test_the_hourly_limit(scene: Scene, crew: Crew, db_session: AsyncSession) -> None:
    await _fill_hour(db_session, scene, crew, AI_RUNS_PER_USER_PER_HOUR)
    response = await scene.owner.post(
        ask_url(crew, scene.bid["id"]), {"agent_id": str(scene.agent.id)}
    )
    problem = assert_problem(response, 429, "too_many_attempts")
    assert problem
    assert int(response.headers["Retry-After"]) > 0


async def test_assess_all(scene: Scene, crew: Crew, db_session: AsyncSession) -> None:
    third = await add_bid(scene.owner, crew, "Quillfield Systems", price="80000.00")
    ok(
        await scene.owner.put(
            call_url(crew, f"/bids/{third['id']}/rejection"), {"reason": "No insurance."}
        )
    )
    url = call_url(crew, "/ai-assessments")
    body = {"agent_id": str(scene.agent.id)}

    batch = ok(await scene.owner.post(url, body))
    again = ok(await scene.owner.post(url, body))

    assert (batch["created"], batch["skipped"]) == (2, 0)
    assert [run["bid_id"] for run in batch["items"]] == [scene.bid["id"], scene.other["id"]]
    assert (again["created"], again["skipped"]) == (0, 0)
    assert {run["id"] for run in again["items"]} == {run["id"] for run in batch["items"]}


async def test_assess_all_starts_what_fits(
    scene: Scene, crew: Crew, db_session: AsyncSession
) -> None:
    await _fill_hour(db_session, scene, crew, AI_RUNS_PER_USER_PER_HOUR - 1)
    url = call_url(crew, "/ai-assessments")
    body = {"agent_id": str(scene.agent.id)}
    batch = ok(await scene.owner.post(url, body))
    assert (batch["created"], batch["skipped"]) == (1, 1)
    assert [run["bid_id"] for run in batch["items"]] == [scene.bid["id"]]
    await db_session.execute(
        update(AiRun).values(
            status=AiRunStatus.CANCELLED, finished_at=utcnow(), cancel_requested_at=utcnow()
        )
    )
    await db_session.commit()
    assert_problem(await scene.owner.post(url, body), 429, "too_many_attempts")


# --- Who sees assess runs (review S9) -----------------------------------------------------------
async def test_assess_runs_are_only_for_people_who_see_the_bids(
    scene: Scene, crew: Crew, api: AsUser
) -> None:
    run = ok(
        await scene.owner.post(ask_url(crew, scene.bid["id"]), {"agent_id": str(scene.agent.id)}),
        201,
    )
    runs = f"/ideas/{crew.key}/ai-runs"
    member = await api(crew.member)
    technical = await api(crew.tech1)

    assert [r["id"] for r in ok(await scene.owner.get(runs))["items"]] == [run["id"]]
    assert [r["id"] for r in ok(await technical.get(runs))["items"]] == [run["id"]]
    assert ok(await member.get(runs))["items"] == []
    assert ok(await member.get(runs, kind="assess_bid"))["items"] == []
    assert_problem(await member.get(f"{runs}/{run['id']}"), 404, "not_found")
    assert_problem(await member.post(f"{runs}/{run['id']}/cancel"), 404, "not_found")
    stream = await member.http.get(API + f"{runs}/{run['id']}/events")
    assert_problem(stream, 404, "not_found")
    assert ok(await technical.get(f"{runs}/{run['id']}"))["bid_id"] == scene.bid["id"]
    cancelled = ok(await scene.owner.post(f"{runs}/{run['id']}/cancel"))
    assert cancelled["status"] == "cancelled"


# --- MCP: c22 -----------------------------------------------------------------------------------
async def test_the_bid_tools_need_the_runs_bid(
    scene: Scene, crew: Crew, db_session: AsyncSession, agent_mcp: McpIdentity
) -> None:
    run = await assess_run(db_session, scene, crew)
    evaluate = await assess_run(db_session, scene, crew, kind=AiRunKind.EVALUATE)
    tool = "get_bid_for_assessment"

    assert await agent_mcp.fails(tool, bid_id=scene.bid["id"]) == "ai_run_not_active"
    assert await agent_mcp.for_run(run).fails(tool, bid_id=scene.other["id"]) == "ai_run_not_active"
    assert await agent_mcp.for_run(run).fails(tool, bid_id=str(uuid4())) == "ai_run_not_active"
    assert await agent_mcp.for_run(evaluate).fails(tool, bid_id=scene.bid["id"]) == (
        "ai_run_not_active"
    )
    assert await agent_mcp.for_run(run).fails("get_idea", idea=crew.key) == "ai_run_not_active"
    assert await agent_mcp.for_run(run).fails("list_projects") == "ai_run_not_active"
    assert await agent_mcp.for_run(run).fails("search_ideas") == "ai_run_not_active"
    assert await agent_mcp.for_run(run).ok(tool, bid_id=scene.bid["id"])


async def test_people_get_forbidden(
    scene: Scene,
    crew: Crew,
    make_key: Any,  # noqa: F811 - the fixture
    connect: Connect,  # noqa: F811 - the fixture
) -> None:
    secret = await make_key(crew.owner)
    person = McpIdentity(connect, secret)
    for tool, args in (
        ("get_bid_for_assessment", {"bid_id": scene.bid["id"]}),
        (
            "get_bid_document_text",
            {"bid_id": scene.bid["id"], "document_id": scene.documents["technical"]},
        ),
        ("submit_bid_assessment", submission(scene)),
    ):
        assert await person.fails(tool, **args) == "forbidden"


async def test_what_the_agent_reads(
    scene: Scene, crew: Crew, db_session: AsyncSession, agent_mcp: McpIdentity
) -> None:
    run = await assess_run(db_session, scene, crew)
    seen = await agent_mcp.for_run(run).ok("get_bid_for_assessment", bid_id=scene.bid["id"])

    assert seen["bid"] == {
        "id": scene.bid["id"],
        "bidder": "Northwind Data Ltd",
        "received_at": seen["bid"]["received_at"],
    }
    assert [d["id"] for d in seen["documents"]] == [
        scene.documents["tender"],
        scene.documents["technical"],
    ]
    assert {q["id"] for s in seen["call"]["sections"] for q in s["questions"]} == {
        q["id"] for q in questions(scene)
    }
    texts = [m["text"] for m in seen["call"]["must_haves"]]
    assert "Pricing schedule" not in texts
    assert "Signed form of tender" in texts
    tender = next(m for m in seen["call"]["must_haves"] if m["text"] == "Signed form of tender")
    assert tender["document_ids"] == [scene.documents["tender"]]
    flat = str(seen)
    for secret in ("120000", "Prices.xlsx", "price", "Price", "Tessellate", "contact"):
        assert secret not in flat
    assert seen["previous"] is None


async def test_document_pages_for_the_agent(
    scene: Scene, crew: Crew, db_session: AsyncSession, agent_mcp: McpIdentity
) -> None:
    run = agent_mcp.for_run(await assess_run(db_session, scene, crew))
    tool = "get_bid_document_text"
    page = await run.ok(tool, bid_id=scene.bid["id"], document_id=scene.documents["technical"])
    assert page["text"] == f"{INGEST}\n{SECURITY}"
    assert page["page_count"] == 1
    assert await run.fails(tool, bid_id=scene.bid["id"], document_id=scene.documents["prices"]) == (
        "not_found"
    )
    assert await run.fails(tool, bid_id=scene.bid["id"], document_id=scene.documents["other"]) == (
        "not_found"
    )
    assert (
        await run.fails(
            tool, bid_id=scene.bid["id"], document_id=scene.documents["technical"], page=2
        )
        == "not_found"
    )


# --- MCP: the assessment ----------------------------------------------------------------------
async def test_submit_checks_every_quote(
    scene: Scene, crew: Crew, db_session: AsyncSession, agent_mcp: McpIdentity
) -> None:
    run = await assess_run(db_session, scene, crew)
    args = submission(scene)
    # One quote across a line break with odd spacing, one invented.
    args["scores"][0]["evidence"] = [
        {
            "document_id": scene.documents["technical"],
            "quote": "every  source in near\nreal time. We hold ISO 27001",
        }
    ]
    args["scores"][1]["evidence"] = [
        {"document_id": scene.documents["technical"], "quote": "We guarantee 100% uptime forever."}
    ]

    result = await agent_mcp.for_run(run).ok("submit_bid_assessment", **args)

    assert result["replaced"] is False
    assert result["included"] is False
    assert result["quotes_checked"] == len(questions(scene))
    assert result["quotes_not_found"] == 1
    stored = await run_row(db_session, run.id)
    assert stored.bid_ai_assessment_id == UUID(result["ai_assessment_id"])
    listed = ok(await scene.owner.get(call_url(crew, f"/bids/{scene.bid['id']}/ai-assessments")))
    [assessment] = listed["items"]
    assert assessment["included"] is False
    assert assessment["quotes_not_found"] == 1
    found = [e["found"] for score in assessment["scores"] for e in score["evidence"]]
    assert found.count(False) == 1
    # Findings are suggestions: the must-have results don't change.
    detail = await bid_detail(scene.owner, crew, scene.bid["id"])
    terms = next(
        r
        for r in detail["must_have_results"]
        if r["must_have"]["text"] == "Accepts our standard terms"
    )
    assert terms["result"] == "unchecked"
    assert terms["ai_findings"][0]["finding"] == "unclear"


async def test_submit_refuses_what_it_wasnt_given(
    scene: Scene, crew: Crew, db_session: AsyncSession, agent_mcp: McpIdentity
) -> None:
    run = agent_mcp.for_run(await assess_run(db_session, scene, crew))
    tool = "submit_bid_assessment"

    missing = submission(scene)
    missing["scores"] = missing["scores"][1:]
    assert await run.fails(tool, **missing) == "validation_error"

    pricing = submission(scene)
    pricing["findings"].append(
        {
            "must_have_id": scene.must["Pricing schedule"]["id"],
            "finding": "met",
            "rationale": "x",
            "evidence": [{"document_id": scene.documents["tender"], "quote": TENDER}],
        }
    )
    assert await run.fails(tool, **pricing) == "validation_error"

    priced = submission(scene)
    priced["scores"][0]["evidence"] = [
        {"document_id": scene.documents["prices"], "quote": "Total price 120000 for all."}
    ]
    assert await run.fails(tool, **priced) == "validation_error"

    foreign = submission(scene)
    foreign["scores"][0]["evidence"] = [
        {"document_id": scene.documents["other"], "quote": "Tessellate's own tender text"}
    ]
    assert await run.fails(tool, **foreign) == "validation_error"

    unknown_argument = submission(scene) | {"sumbit": True}
    assert await run.fails(tool, **unknown_argument) == "validation_error"
    assert await db_session.scalar(select(func.count()).select_from(BidAiAssessment)) == 0


async def test_inclusion_and_a_changed_resubmission(
    scene: Scene, crew: Crew, db_session: AsyncSession, agent_mcp: McpIdentity
) -> None:
    run = agent_mcp.for_run(await assess_run(db_session, scene, crew))
    first = await run.ok("submit_bid_assessment", **submission(scene, score=4))
    include = call_url(
        crew,
        f"/bids/{scene.bid['id']}/ai-assessments/{first['ai_assessment_id']}/include-in-totals",
    )
    assert ok(await scene.owner.put(include, {"include": True}))["included"] is True

    same = await run.ok("submit_bid_assessment", **submission(scene, score=4))
    assert same["replaced"] is True
    assert same["ai_assessment_id"] == first["ai_assessment_id"]
    assert same["included"] is True  # nothing changed

    changed = await run.ok("submit_bid_assessment", **submission(scene, score=2))
    assert changed["included"] is False  # a changed score is judged again


async def test_hidden_characters_in_agent_text_are_removed(
    scene: Scene, crew: Crew, db_session: AsyncSession, agent_mcp: McpIdentity
) -> None:
    run = agent_mcp.for_run(await assess_run(db_session, scene, crew))
    args = submission(scene, quote="We hold ISO\u00ad 27001 certi\u200bfication for every")
    args["scores"][0]["rationale"] = "Strong\u202e security."
    result = await run.ok("submit_bid_assessment", **args)
    assert result["quotes_not_found"] == 0
    listed = ok(await scene.owner.get(call_url(crew, f"/bids/{scene.bid['id']}/ai-assessments")))
    rationales = [s["rationale"] for s in listed["items"][0]["scores"]]
    assert "Strong security." in rationales


async def test_a_rejected_bids_run_can_no_longer_submit(
    scene: Scene, crew: Crew, db_session: AsyncSession, agent_mcp: McpIdentity
) -> None:
    run = await assess_run(db_session, scene, crew)
    ok(await scene.owner.put(call_url(crew, f"/bids/{scene.bid['id']}/rejection"), {"reason": "x"}))
    stored = await run_row(db_session, run.id)
    assert stored.cancel_requested_at is not None  # the rejection cancelled it
    result = await agent_mcp.for_run(run).fails("submit_bid_assessment", **submission(scene))
    assert result == "ai_run_not_active"


def test_quote_checks_at_the_largest_bid() -> None:
    """Review S2: 420 quotes over 30 documents of 2,000,000 characters each (the most a bid
    can hold), each document normalised once. Measured about 1.2 s on the shared 4-CPU build
    machine (the event loop never waits for it: it runs in a thread, test below)."""
    rng = random.Random(10)  # noqa: S311 - test data
    words = [rng.choice(VOCABULARY) for _ in range(400_000)]
    texts = {uuid4(): " ".join(rng.sample(words, len(words)))[:2_000_000] for _ in range(30)}
    ids = list(texts)
    quotes = [
        (ids[n % 30], " ".join(rng.choice(VOCABULARY) for _ in range(5)) + f" {n}")
        for n in range(420)
    ]
    started = time.perf_counter()
    found = quotes_found(quotes, texts)
    assert time.perf_counter() - started < 3.0
    assert not any(found)


VOCABULARY = [
    *("platform", "data", "security", "delivery", "certified", "ISO", "27001", "team"),
    *("months", "phase", "supplier", "support", "the", "and", "of", "to", "in", "with"),
    *("we", "our", "service", "levels", "schedule", "risk", "plan", "hosting", "cloud"),
    *("backup", "recovery", "staff", "training", "contract", "terms", "quality", "report"),
]


async def test_quote_checks_run_off_the_event_loop(
    scene: Scene,
    crew: Crew,
    db_session: AsyncSession,
    agent_mcp: McpIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import anyio.to_thread

    seen: list[Any] = []
    real = anyio.to_thread.run_sync

    async def spy(function: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(function)
        return await real(function, *args, **kwargs)

    monkeypatch.setattr(anyio.to_thread, "run_sync", spy)
    run = agent_mcp.for_run(await assess_run(db_session, scene, crew))
    await run.ok("submit_bid_assessment", **submission(scene))
    assert quotes_found in seen


# --- The call's AI assessor ---------------------------------------------------------------------
async def _name_assessor(scene: Scene, crew: Crew) -> None:
    call = scene.view["call"]
    body = {
        "title": call["title"],
        "description": call["description"],
        "currency": call["currency"],
        "deadline_at": call["deadline_at"],
        "ai_assessor_id": str(scene.agent.id),
    }
    ok(await scene.owner.put(call_url(crew), body))


async def _quiet(db: AsyncSession) -> None:
    await db.execute(update(BidDocument).values(uploaded_at=utcnow() - timedelta(minutes=6)))
    await db.commit()


async def test_the_automatic_run(
    scene: Scene, crew: Crew, db_session: AsyncSession, app: FastAPI, settings: Settings
) -> None:
    await _name_assessor(scene, crew)
    sessionmaker = app.state.sessionmaker
    # Inside the quiet period after the uploads: nothing yet.
    assert await assess.start_due_automatic_runs(sessionmaker, settings) == 0
    await _quiet(db_session)

    assert await assess.start_due_automatic_runs(sessionmaker, settings) == 2
    assert await assess.start_due_automatic_runs(sessionmaker, settings) == 0  # once per bid

    runs = list(await db_session.scalars(select(AiRun).order_by(AiRun.created_at)))
    assert {run.bid_id for run in runs} == {UUID(scene.bid["id"]), UUID(scene.other["id"])}
    assert all(run.automatic and run.requested_by_id is None for run in runs)
    bids = list(await db_session.scalars(select(Bid).execution_options(populate_existing=True)))
    assert all(bid.auto_ai_run_at is not None for bid in bids)
    # Not audited as a request, and not counted toward anyone's hourly limit.
    requests = await db_session.scalar(
        text("SELECT count(*) FROM audit_log WHERE action = 'ai_run.request'")
    )
    assert requests == 0
    listed = ok(await scene.owner.get(f"/ideas/{crew.key}/ai-runs"))
    assert all(run["automatic"] for run in listed["items"])


async def test_no_automatic_run_while_a_document_is_pending_or_for_a_rejected_bid(
    scene: Scene, crew: Crew, db_session: AsyncSession, app: FastAPI, settings: Settings
) -> None:
    await _name_assessor(scene, crew)
    ok(
        await upload(scene.owner, crew, scene.bid["id"], files.pdf("Late addition"), "Late.pdf"),
        201,
    )
    ok(
        await scene.owner.put(
            call_url(crew, f"/bids/{scene.other['id']}/rejection"), {"reason": "x"}
        )
    )
    await _quiet(db_session)
    assert await assess.start_due_automatic_runs(app.state.sessionmaker, settings) == 0


async def test_no_automatic_run_without_an_assessor_or_in_a_draft(
    scene: Scene, crew: Crew, db_session: AsyncSession, app: FastAPI, settings: Settings
) -> None:
    await _quiet(db_session)
    assert await assess.start_due_automatic_runs(app.state.sessionmaker, settings) == 0
    await _name_assessor(scene, crew)
    await db_session.execute(update(BidCall).values(status=BidCallStatus.DRAFT))
    await db_session.commit()
    assert await assess.start_due_automatic_runs(app.state.sessionmaker, settings) == 0


async def test_naming_the_assessor_queues_a_check(
    scene: Scene, crew: Crew, db_session: AsyncSession
) -> None:
    await _name_assessor(scene, crew)
    jobs = list(
        await db_session.scalars(
            text(
                "SELECT args->>'call_id' FROM procrastinate_jobs"
                " WHERE task_name = 'check_bid_ai_assessor'"
            )
        )
    )
    assert jobs == [str(scene.call_id)]


# --- End to end through the fake kagent ----------------------------------------------------------
async def test_an_assess_run_end_to_end(
    scene: Scene,
    crew: Crew,
    db_session: AsyncSession,
    app: FastAPI,
    settings: Settings,
    agent_mcp: McpIdentity,
) -> None:
    async def work(metadata: dict[str, Any]) -> None:
        run = agent_mcp.for_run(UUID(metadata["run_id"]))
        bid_id = metadata["bid_id"]
        seen = await run.ok("get_bid_for_assessment", bid_id=bid_id)
        for document in seen["documents"]:
            await run.ok("get_bid_document_text", bid_id=bid_id, document_id=document["id"])
        await run.ok("submit_bid_assessment", **submission(scene))

    kagent = FakeKagent(work)
    runtime = AiRuntime(
        settings=settings,
        sessionmaker=app.state.sessionmaker,
        transport=kagent.transport,
        cancel_poll=0.05,
        heartbeat=0.2,
        poll_interval=0.05,
        retry_waits=(0.01, 0.02),
    )
    asked = ok(
        await scene.owner.post(ask_url(crew, scene.bid["id"]), {"agent_id": str(scene.agent.id)}),
        201,
    )

    await execute_run(runtime, UUID(asked["id"]))

    run = await run_row(db_session, UUID(asked["id"]))
    assert run.status is AiRunStatus.SUCCEEDED
    assert run.bid_ai_assessment_id is not None
    detail = ok(await scene.owner.get(f"/ideas/{crew.key}/ai-runs/{asked['id']}"))
    messages = [event["message"] for event in detail["events"]]
    assert "Read the bid" in messages
    assert "Read a bid document" in messages
    assert "Saved its bid assessment" in messages
    assert "Bid assessment saved" in messages
    assert detail["result"]["bid_ai_assessment_id"] == str(run.bid_ai_assessment_id)
    sent = kagent.calls("message/stream") or kagent.calls("SendStreamingMessage")
    assert sent
    assert scene.bid["id"] in str(sent[0].body)
    assert "Northwind" not in str(sent[0].body)


async def test_after_extraction_the_check_waits_for_the_quiet_period(
    scene: Scene, crew: Crew, db_session: AsyncSession, app: FastAPI, settings: Settings
) -> None:
    await _name_assessor(scene, crew)
    await db_session.execute(text("DELETE FROM procrastinate_jobs"))
    await db_session.commit()

    started = await assess.check_after_extraction(
        app.state.sessionmaker, settings, UUID(scene.bid["id"])
    )

    assert started == 0
    scheduled = (
        await db_session.execute(
            text(
                "SELECT args->>'call_id', scheduled_at FROM procrastinate_jobs"
                " WHERE task_name = 'check_bid_ai_assessor'"
            )
        )
    ).all()
    assert [call_id for call_id, _ in scheduled] == [str(scene.call_id)]
    last = await db_session.scalar(
        select(func.max(BidDocument.uploaded_at)).where(BidDocument.bid_id == UUID(scene.bid["id"]))
    )
    assert last is not None
    assert scheduled[0][1] > last + timedelta(minutes=5)
    # Once quiet, the same check starts the run at once.
    await _quiet(db_session)
    assert (
        await assess.check_after_extraction(app.state.sessionmaker, settings, UUID(scene.bid["id"]))
        == 1
    )


async def test_the_bid_tools_need_evaluate(
    scene: Scene,
    crew: Crew,
    db_session: AsyncSession,
    make_key: Any,  # noqa: F811 - the fixture
    connect: Connect,  # noqa: F811 - the fixture
) -> None:
    run = await assess_run(db_session, scene, crew)
    secret = await make_key(scene.agent.user, ["read", "mcp"], [crew.project])
    narrow = McpIdentity(connect, secret).for_run(run)
    assert await narrow.fails("get_bid_for_assessment", bid_id=scene.bid["id"]) == (
        "insufficient_scope"
    )
