"""Phase 10: assess runs (contract-phase10 section 9): the bid, its documents' text, one
assessment with quotes taken from that text; the suffixes that invent a quote and find a
must-have not met; c22 for the bid tools."""

from __future__ import annotations

import time
from typing import Any

import pytest

from fake_agent.agent import (
    INVENTED_QUOTE,
    RATIONALE_MARKER,
    assessment_arguments,
    passages,
)
from tests.conftest import Agent, rpc, run_message, state_of, stream
from tests.fake_mcp import (
    BID,
    BID_VIEW,
    DOC_PENDING,
    DOC_PHOTO,
    DOC_PRICING,
    DOC_TENDER,
    MUST_HAVES,
    QUESTIONS,
    TEXTS,
    quotes_not_found,
)

ASSESS_TOOLS = ["get_bid_for_assessment", "get_bid_document_text", "get_bid_document_text"]


def _assess(agent: Agent, name: str = "bid-assessor", protocol: str = "0.3") -> str:
    agent.mcp.open_kind = "assess_bid"
    run_id, body = run_message("assess_bid", bid_id=BID, protocol=protocol)
    events = stream(agent.http, agent.url(name), body, protocol=protocol)
    assert state_of(events[-1]) in ("completed", "TASK_STATE_COMPLETED")
    return run_id


@pytest.mark.parametrize("protocol", ["0.3", "1.0"])
def test_assess_reads_the_bid_then_submits_quotes_from_its_text(
    agent: Agent, protocol: str
) -> None:
    run_id = _assess(agent, protocol=protocol)
    assert agent.mcp.tools() == [*ASSESS_TOOLS, "submit_bid_assessment"]
    # Every call names the run and the run's bid (c22).
    for call in agent.mcp.calls:
        assert call["arguments"]["run_id"] == run_id
        assert call["arguments"]["bid_id"] == BID
    pages = [c["arguments"] for c in agent.mcp.calls if c["tool"] == "get_bid_document_text"]
    assert [(p["document_id"], p["page"]) for p in pages] == [(DOC_TENDER, 1), (DOC_TENDER, 2)]
    submitted = agent.mcp.arguments("submit_bid_assessment")
    assert [s["question_id"] for s in submitted["scores"]] == [q["id"] for q in QUESTIONS]
    assert [s["score"] for s in submitted["scores"]] == [3, 4, 5, 1]
    for score in submitted["scores"]:
        assert score["rationale"].startswith(RATIONALE_MARKER)
        assert len(score["rationale"]) <= 1000
        assert len(score["evidence"]) == 1
        assert score["evidence"][0]["document_id"] == DOC_TENDER
        assert 20 <= len(score["evidence"][0]["quote"]) <= 500
        assert "..." not in score["evidence"][0]["quote"]
        assert "…" not in score["evidence"][0]["quote"]
    # Every quote is found in the document's text, as Soundings checks it.
    assert quotes_not_found(submitted) == (6, 0)
    findings = {f["must_have_id"]: f for f in submitted["findings"]}
    assert [f["must_have_id"] for f in submitted["findings"]] == [m["id"] for m in MUST_HAVES]
    tender, insurance, terms = (findings[m["id"]] for m in MUST_HAVES)
    assert tender["finding"] == "met"
    assert tender["evidence"][0]["document_id"] == DOC_TENDER
    assert insurance["finding"] == "not_met"
    assert insurance["evidence"] == []
    assert terms["finding"] == "met"
    assert "standard terms" in terms["evidence"][0]["quote"]
    seen = agent.observations(run_id)
    assert seen["kind"] == "assess_bid"
    assessed = seen["assess"]
    assert assessed["documents_listed"] == [DOC_TENDER, DOC_PHOTO, DOC_PENDING]
    assert assessed["documents_read"] == [DOC_TENDER]
    assert assessed["pages_read"] == 2
    assert (assessed["questions"], assessed["must_haves"], assessed["quotes"]) == (4, 3, 6)
    assert (assessed["quotes_checked"], assessed["quotes_not_found"]) == (6, 0)
    assert assessed["invented"] is False
    assert DOC_PRICING not in str(seen)
    assert seen["final_state"] == "completed"


def test_invents_gives_one_quote_that_is_in_no_document(agent: Agent) -> None:
    run_id = _assess(agent, "bid-assessor-invents")
    submitted = agent.mcp.arguments("submit_bid_assessment")
    quotes = [e["quote"] for s in submitted["scores"] for e in s["evidence"]]
    assert quotes.count(INVENTED_QUOTE) == 1
    assert quotes_not_found(submitted) == (6, 1)
    assessed = agent.observations(run_id)["assess"]
    assert assessed["invented"] is True
    assert assessed["quotes_not_found"] == 1


def test_not_met_finds_the_first_must_have_not_met(agent: Agent) -> None:
    run_id = _assess(agent, "bid-assessor-not-met")
    submitted = agent.mcp.arguments("submit_bid_assessment")
    first = submitted["findings"][0]
    assert first["must_have_id"] == MUST_HAVES[0]["id"]
    assert first["finding"] == "not_met"
    assert agent.observations(run_id)["assess"]["findings"][MUST_HAVES[0]["id"]] == "not_met"


def test_assess_without_readable_text_scores_zero_without_quotes() -> None:
    arguments = assessment_arguments(BID, BID_VIEW["call"], [DOC_PHOTO], {})
    assert [s["score"] for s in arguments["scores"]] == [0, 0, 0, 0]
    assert all(s["evidence"] == [] for s in arguments["scores"])
    assert [f["finding"] for f in arguments["findings"]] == ["unclear", "not_met", "unclear"]


def test_a_pricing_only_must_have_is_unclear_not_missing() -> None:
    call = {**BID_VIEW["call"], "must_haves": [{**MUST_HAVES[1], "restricted_document_count": 1}]}
    arguments = assessment_arguments(
        BID, call, [DOC_TENDER], {DOC_TENDER: "".join(TEXTS[DOC_TENDER])}
    )
    assert arguments["findings"][0]["finding"] == "unclear"


def test_passages_are_normalised_substrings_within_bounds() -> None:
    text = "Short.\n" + "word " * 200 + "\nA   sentence   with  gaps here. Another one follows it."
    found = passages(text)
    normalised = " ".join(text.split())
    assert found
    for passage in found:
        assert 20 <= len(passage) <= 300
        assert passage in normalised
    assert "A sentence with gaps here." in found


def test_an_assess_message_without_a_bid_is_not_a_run(agent: Agent) -> None:
    agent.mcp.open_kind = "assess_bid"
    for bid_id in (None, "not-a-uuid", 7):
        _run_id, body = run_message("assess_bid", bid_id=bid_id)
        stream(agent.http, agent.url("bid-assessor"), body)
    assert agent.mcp.tools() == []


def test_strays_in_an_assess_run_are_refused_then_it_works(agent: Agent) -> None:
    agent.mcp.open_kind = "assess_bid"
    run_id, body = run_message("assess_bid", bid_id=BID)
    events = stream(agent.http, agent.url("bid-assessor-strays"), body)
    assert state_of(events[-1]) == "completed"
    strays = agent.observations(run_id)["strays"]
    for attempt in (
        "get_bid_other",
        "get_idea",
        "get_rubric",
        "get_proposal",
        "list_projects",
        "search_ideas",
        "submit_evaluation",
        "add_research_note",
    ):
        assert strays[attempt] == "ai_run_not_active", attempt
    assert strays["add_comment"] == "forbidden"
    assert agent.mcp.tools()[-1] == "submit_bid_assessment"


def test_other_runs_cant_reach_the_bid_tools(agent: Agent) -> None:
    run_id, body = run_message("evaluate")
    stream(agent.http, agent.url("idea-evaluator-strays"), body)
    strays = agent.observations(run_id)["strays"]
    assert strays["get_bid_other"] == "ai_run_not_active"
    assert strays["submit_bid_assessment"] == "ai_run_not_active"


def test_blind_probe_of_a_bid_sees_no_price_or_scores(agent: Agent) -> None:
    run_id = _assess(agent, "bid-assessor-blind-probe")
    probes = {(p["tool"], p["phase"]): p for p in agent.observations(run_id)["blind"]}
    assert set(probes) == {
        ("get_bid_for_assessment", "before"),
        ("get_bid_for_assessment", "after"),
    }
    for probe in probes.values():
        assert probe["keys"] == ["bid", "call", "documents", "previous"]
        assert probe["bid_keys"] == ["bidder", "id", "received_at"]


def test_slow_assess_reads_the_bid_and_works_until_cancelled(agent: Agent) -> None:
    agent.mcp.open_kind = "assess_bid"
    url = agent.url("bid-assessor-slow")
    run_id, body = run_message("assess_bid", bid_id=BID)
    _events, done = agent.background_stream(url, body)
    task_id = agent.task_id(run_id)
    time.sleep(0.3)
    answer: dict[str, Any] = rpc(agent.http, url, "tasks/cancel", {"id": task_id})
    assert answer["result"]["status"]["state"] == "canceled"
    assert done.wait(5)
    assert agent.mcp.tools() == ["get_bid_for_assessment"]
