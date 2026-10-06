"""What the agent does through MCP for each kind, and the test behaviours."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import pytest

from fake_agent.agent import RATIONALE_MARKER, SOURCE_BASE
from fake_agent.config import Settings
from tests.conftest import KEY, Agent, rpc, run_message, state_of, stream
from tests.fake_mcp import CRITERIA, IDEA


def wait_for(predicate: Any, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.05)


@pytest.mark.parametrize("protocol", ["0.3", "1.0"])
def test_evaluate_reads_then_submits_a_cited_evaluation(agent: Agent, protocol: str) -> None:
    run_id, body = run_message("evaluate", protocol=protocol)
    events = stream(agent.http, agent.url(), body, protocol=protocol)
    assert state_of(events[-1]) in ("completed", "TASK_STATE_COMPLETED")
    assert agent.mcp.tools() == ["get_rubric", "get_idea", "submit_evaluation"]
    call = agent.mcp.calls[0]
    assert call["authorization"] == f"Bearer {KEY}"
    assert call["protocol"] == "2025-11-25"
    submitted = agent.mcp.arguments("submit_evaluation")
    assert submitted["idea"] == IDEA
    # Every call names the run (c22: Soundings binds it to that run's idea).
    assert {call["arguments"].get("run_id") for call in agent.mcp.calls if call["tool"]} == {run_id}
    assert submitted["submit"] is True
    assert submitted["recommendation"] in ("go", "maybe", "no")
    assert submitted["comment"]
    assert [score["criterion_id"] for score in submitted["scores"]] == [c["id"] for c in CRITERIA]
    assert [score["score"] for score in submitted["scores"]] == [3, 4, 5]
    for score, criterion in zip(submitted["scores"], CRITERIA, strict=True):
        assert score["comment"].startswith(RATIONALE_MARKER)
        assert criterion["name"] in score["comment"]
        assert IDEA in score["comment"]
        assert len(score["comment"]) <= 1000
        assert len(score["sources"]) == 2
        for source in score["sources"]:
            assert source["url"].startswith(SOURCE_BASE + "/")
            assert source["url"].isascii()
            assert 1 <= len(source["title"]) <= 200
    seen = agent.observations(run_id)
    assert seen["kind"] == "evaluate"
    assert seen["final_state"] == "completed"
    assert [c["tool"] for c in seen["tool_calls"]] == agent.mcp.tools()


def test_research_writes_a_cited_note(agent: Agent) -> None:
    agent.mcp.open_kind = "research"
    _run_id, body = run_message("research")
    events = stream(agent.http, agent.url(), body)
    assert state_of(events[-1]) == "completed"
    assert agent.mcp.tools() == ["get_idea", "add_research_note"]
    note = agent.mcp.arguments("add_research_note")
    assert note["idea"] == IDEA
    assert 1 <= len(note["body_md"]) <= 20_000
    assert len(note["sources"]) == 3
    assert "score" not in note["body_md"].lower()


def test_draft_section_suggests_text_for_that_section(agent: Agent) -> None:
    agent.mcp.open_kind = "draft_section"
    agent.mcp.open_section = "risks"
    _run_id, body = run_message("draft_section", section_key="risks")
    events = stream(agent.http, agent.url(), body)
    assert state_of(events[-1]) == "completed"
    assert agent.mcp.tools() == ["get_idea", "get_proposal", "propose_proposal_section"]
    suggestion = agent.mcp.arguments("propose_proposal_section")
    assert suggestion["section_key"] == "risks"
    assert suggestion["base_version"] == 3
    assert suggestion["body_md"].startswith("Known risks.")


def test_a_refused_tool_ends_the_task_completed_without_a_result(agent: Agent) -> None:
    agent.mcp.run_open = False
    run_id, body = run_message("evaluate")
    events = stream(agent.http, agent.url(), body)
    assert state_of(events[-1]) == "completed"
    assert agent.mcp.tools() == ["get_rubric"]
    assert agent.observations(run_id)["tool_calls"][0]["error_code"] == "ai_run_not_active"


def test_mcp_unreachable_fails_the_task(agent: Agent) -> None:
    agent.mcp.status = 401
    _, body = run_message("evaluate")
    events = stream(agent.http, agent.url(), body)
    assert state_of(events[-1]) == "failed"


def test_slow_works_until_cancelled(agent: Agent) -> None:
    url = agent.url("idea-evaluator-slow")
    run_id, body = run_message()
    events, done = agent.background_stream(url, body)
    task_id = agent.task_id(run_id)
    time.sleep(0.4)  # a few "still working" updates
    answer = rpc(agent.http, url, "tasks/cancel", {"id": task_id})
    assert answer["result"]["status"]["state"] == "canceled"
    assert done.wait(5)
    working = [e for e in events if state_of(e) == "working"]
    assert len(working) >= 3
    seen = agent.observations(run_id)
    assert seen["cancel_requests"] == 1
    assert seen["final_state"] == "canceled"
    assert agent.mcp.tools() == ["get_idea"]
    after = rpc(agent.http, url, "tasks/get", {"id": task_id, "historyLength": 1})
    assert after["result"]["status"]["state"] == "canceled"


def test_cancel_through_1_0(agent: Agent) -> None:
    url = agent.url("idea-evaluator-slow", layout="v1_0")
    run_id, body = run_message(protocol="1.0")
    _events, done = agent.background_stream(url, body, protocol="1.0")
    task_id = agent.task_id(run_id)
    answer = rpc(agent.http, url, "CancelTask", {"id": task_id}, protocol="1.0")
    assert answer["result"]["status"]["state"] == "TASK_STATE_CANCELED"
    assert done.wait(5)


def test_no_cancel_answers_an_internal_error_like_kagent_adk(agent: Agent) -> None:
    url = agent.url("idea-evaluator-no-cancel")
    run_id, body = run_message()
    agent.background_stream(url, body)
    task_id = agent.task_id(run_id)
    answer = rpc(agent.http, url, "tasks/cancel", {"id": task_id})
    assert answer["error"]["code"] == -32603
    assert agent.observations(run_id)["cancel_requests"] == 1


def test_lingers_records_its_result_then_keeps_working(agent: Agent) -> None:
    url = agent.url("idea-evaluator-lingers")
    run_id, body = run_message()
    agent.background_stream(url, body)
    wait_for(lambda: "submit_evaluation" in agent.mcp.tools())
    time.sleep(0.3)
    assert agent.observations(run_id)["final_state"] is None
    task_id = agent.observations(run_id)["task_id"]
    rpc(agent.http, url, "tasks/cancel", {"id": task_id})
    wait_for(lambda: agent.observations(run_id)["final_state"] == "canceled")


@pytest.mark.parametrize(
    ("name", "state", "tools"),
    [
        ("idea-evaluator-fails", "failed", ["get_idea"]),
        ("idea-evaluator-silent", "completed", []),
        ("idea-evaluator-asks", "input-required", ["get_idea"]),
        ("idea-evaluator-rejects", "rejected", []),
    ],
)
def test_outcomes(agent: Agent, name: str, state: str, tools: list[str]) -> None:
    _run_id, body = run_message()
    events = stream(agent.http, agent.url(name), body)
    assert state_of(events[-1]) == state
    assert agent.mcp.tools() == tools


def test_blind_probe_records_what_rule_9_shows(agent: Agent) -> None:
    run_id, body = run_message()
    stream(agent.http, agent.url("idea-evaluator-blind-probe"), body)
    seen = agent.observations(run_id)
    probes = {(probe["tool"], probe["phase"]): probe for probe in seen["blind"]}
    assert set(probes) == {
        ("get_idea", "before"),
        ("search_ideas", "before"),
        ("get_idea", "after"),
        ("search_ideas", "after"),
    }
    for probe in probes.values():
        assert probe["score_hidden"] is True
        assert probe["score"] is None
    assert probes[("get_idea", "after")]["evaluations"] == 0
    assert probes[("get_idea", "after")]["aggregate"] is None
    assert probes[("search_ideas", "before")]["found"] is True
    assert "submit_evaluation" in agent.mcp.tools()


def test_strays_try_what_c22_refuses_then_work(agent: Agent) -> None:
    run_id, body = run_message("evaluate")
    events = stream(agent.http, agent.url("idea-evaluator-strays"), body)
    assert state_of(events[-1]) == "completed"
    strays = agent.observations(run_id)["strays"]
    assert strays["add_comment"] == "forbidden"
    assert strays["create_idea"] == "forbidden"
    assert strays["get_idea_next"] == "ai_run_not_active"
    assert strays["propose_other_section"] == "ai_run_not_active"
    assert strays["add_research_note"] == "ai_run_not_active"
    assert strays["list_projects"] == "customer-innovation"
    assert strays["search_ideas"] == IDEA
    assert agent.mcp.tools()[-1] == "submit_evaluation"


def test_late_writes_after_its_run_ended(agent: Agent) -> None:
    url = agent.url("idea-evaluator-late")
    run_id, body = run_message("evaluate")
    agent.background_stream(url, body)
    task_id = agent.task_id(run_id)
    agent.mcp.run_open = False  # Soundings ended the run (cancel, deadline, worker lost)
    rpc(agent.http, url, "tasks/cancel", {"id": task_id})
    wait_for(lambda: agent.observations(run_id)["late"] is not None)
    late = agent.observations(run_id)["late"]
    assert late["tool"] == "submit_evaluation"
    assert late["error_code"] == "ai_run_not_active"
    # It names the run that ended, so a newer run on the same idea can't take it.
    assert agent.mcp.arguments("submit_evaluation")["run_id"] == run_id


def test_keys_from_a_directory_are_read_per_request(
    make_agent: Any, settings: Settings, tmp_path: Path
) -> None:
    agent = make_agent(settings, keys={}, keys_dir=tmp_path)
    card = agent.url() + ".well-known/agent-card.json"
    assert agent.http.get(card).status_code == 404
    (tmp_path / "soundings.idea-evaluator").write_text(f"Bearer {KEY}\n")
    assert agent.http.get(card).status_code == 200
    _, body = run_message()
    stream(agent.http, agent.url(), body)
    assert agent.mcp.calls[0]["authorization"] == f"Bearer {KEY}"
    (tmp_path / "soundings.idea-evaluator").write_text("not a key")
    assert agent.http.get(card).status_code == 404


def test_the_key_is_never_logged(agent: Agent, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    _, body = run_message()
    stream(agent.http, agent.url(), body)
    assert KEY not in caplog.text
    assert "sdg_" not in caplog.text


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_AGENT_KEYS", f"soundings/a=Bearer {KEY}, team/b={KEY}")
    monkeypatch.setenv("FAKE_AGENT_BEHAVIOURS", "soundings/a=slow")
    monkeypatch.setenv("FAKE_AGENT_MCP_URL", "http://soundings.soundings.svc:80/mcp")
    monkeypatch.setenv("FAKE_AGENT_STEP_DELAY", "0")
    settings = Settings.from_env()
    assert settings.key_for("soundings", "a") == KEY
    assert settings.key_for("team", "b") == KEY
    assert settings.key_for("team", "c") is None
    assert settings.behaviour_for("soundings", "a") == "slow"
    assert settings.behaviour_for("team", "b-blind-probe") == "blind-probe"
    assert settings.behaviour_for("team", "probe") == "normal"
    assert settings.step_delay == 0
    for bad in ("soundings/a=nokey", "Soundings/a=" + KEY, "a=" + KEY):
        monkeypatch.setenv("FAKE_AGENT_KEYS", bad)
        with pytest.raises(ValueError, match="FAKE_AGENT_KEYS"):
            Settings.from_env()
    monkeypatch.setenv("FAKE_AGENT_KEYS", "")
    monkeypatch.setenv("FAKE_AGENT_MCP_URL", "http://user:pw@host/mcp")
    with pytest.raises(ValueError, match="FAKE_AGENT_MCP_URL"):
        Settings.from_env()


def test_drops_ends_the_stream_early_and_the_task_finishes(agent: Agent) -> None:
    """``-drops``: the stream ends after two events; ``tasks/get`` shows the outcome."""
    url = agent.url("idea-evaluator-drops")
    run_id, body = run_message()
    events = stream(agent.http, url, body)
    assert len(events) == 2
    assert state_of(events[-1]) == "working"
    task_id = agent.task_id(run_id)
    wait_for(lambda: agent.observations(run_id)["final_state"] == "completed", timeout=10)
    answer = rpc(agent.http, url, "tasks/get", {"id": task_id, "historyLength": 1})
    assert answer["result"]["status"]["state"] == "completed"
    assert agent.mcp.tools() == ["get_rubric", "get_idea", "submit_evaluation"]
