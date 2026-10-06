"""The HTTP surface: kagent v0.10.2's controller layout, both protocol versions, the card,
version negotiation, unknown agents, the optional controller token."""

from __future__ import annotations

from typing import Any

import pytest

from fake_agent.config import Settings
from tests.conftest import Agent, headers, rpc, run_message, state_of, stream


def test_card_is_kagent_like(agent: Agent) -> None:
    response = agent.http.get(agent.url() + ".well-known/agent-card.json")
    assert response.status_code == 200
    card = response.json()
    assert card["name"] == "idea_evaluator"  # kagent: the agent name with "-" -> "_"
    versions = {i["protocolVersion"] for i in card["supportedInterfaces"]}
    assert versions == {"0.3", "1.0"}
    assert {i["protocolBinding"] for i in card["supportedInterfaces"]} == {"JSONRPC"}
    # The 0.3 fields kagent's card also carries.
    assert card["url"] == agent.url()
    assert card["protocolVersion"] == "0.3"
    assert card["preferredTransport"] == "JSONRPC"
    assert card["capabilities"] == {"streaming": True, "pushNotifications": False}
    assert {skill["id"] for skill in card["skills"]} == {
        "evaluate-idea",
        "research-idea",
        "draft-section",
    }


def test_card_of_the_1_0_layout(agent: Agent) -> None:
    response = agent.http.get(agent.url(layout="v1_0") + "/.well-known/agent-card.json")
    assert response.status_code == 200
    card = response.json()
    assert card["supportedInterfaces"][0] == {
        "url": agent.url(layout="v1_0"),
        "protocolBinding": "JSONRPC",
        "protocolVersion": "1.0",
    }


def test_an_agent_without_a_key_does_not_exist(agent: Agent) -> None:
    card = agent.http.get(f"{agent.base}/api/a2a/soundings/nobody/.well-known/agent-card.json")
    assert card.status_code == 404
    _, body = run_message()
    response = agent.http.post(
        f"{agent.base}/api/a2a/soundings/nobody/", json=body, headers=headers()
    )
    assert response.status_code == 404
    other_namespace = agent.http.post(
        f"{agent.base}/api/a2a/kagent/idea-evaluator/", json=body, headers=headers()
    )
    assert other_namespace.status_code == 404


def test_paths_with_and_without_the_trailing_slash_answer_without_redirects(agent: Agent) -> None:
    _run_id, body = run_message()
    for url in (agent.url(), agent.url().rstrip("/")):
        response = agent.http.post(url, json=body, headers=headers(), follow_redirects=False)
        assert response.status_code == 200
    assert (
        agent.http.post(
            agent.url(layout="v1_0") + "/",
            json=run_message(protocol="1.0")[1],
            headers=headers("1.0"),
        ).status_code
        == 200
    )


def test_a2a_version_selects_the_methods(agent: Agent) -> None:
    # 0.3 methods without the header (kagent: "missing or 0.3").
    _run_id, body = run_message("evaluate")
    events = stream_without_version(agent, body)
    assert state_of(events[-1]) == "completed"
    # 1.0 methods on the same (v0.10) path with A2A-Version: 1.0.
    _, body10 = run_message(protocol="1.0")
    events = stream(agent.http, agent.url(), body10, protocol="1.0")
    assert state_of(events[-1]) == "TASK_STATE_COMPLETED"
    # Any other version: 400, as kagent's controller answers.
    response = agent.http.post(agent.url(), json=body, headers=headers("2.0"))
    assert response.status_code == 400
    response = agent.http.post(agent.url(), json=body, headers=headers("x"))
    assert response.status_code == 400


def stream_without_version(agent: Agent, body: dict[str, Any]) -> list[dict[str, Any]]:
    import json

    events = []
    request_headers = {k: v for k, v in headers().items() if k != "A2A-Version"}
    with agent.http.stream("POST", agent.url(), json=body, headers=request_headers) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:])["result"])
    return events


def test_the_1_0_layout_requires_version_1_0(agent: Agent) -> None:
    _, body = run_message(protocol="1.0")
    no_header = {k: v for k, v in headers("1.0").items() if k != "A2A-Version"}
    assert (
        agent.http.post(agent.url(layout="v1_0"), json=body, headers=no_header).status_code == 400
    )
    assert (
        agent.http.post(agent.url(layout="v1_0"), json=body, headers=headers("0.3")).status_code
        == 400
    )
    events = stream(agent.http, agent.url(layout="v1_0"), body, protocol="1.0")
    assert "task" in events[0]
    assert state_of(events[-1]) == "TASK_STATE_COMPLETED"
    assert all("final" not in event for event in events)  # 1.0 has no final flag


def test_0_3_stream_shape(agent: Agent) -> None:
    _run_id, body = run_message()
    events = stream(agent.http, agent.url(), body)
    kinds = [event["kind"] for event in events]
    assert kinds[0] == "task"
    assert events[0]["status"]["state"] == "submitted"
    assert "artifact-update" in kinds
    assert kinds[-1] == "status-update"
    assert events[-1]["final"] is True
    assert all(
        event.get("final") is False for event in events[1:-1] if event["kind"] == "status-update"
    )
    states = [state_of(event) for event in events if event["kind"] == "status-update"]
    assert states[0] == "working"
    assert states[-1] == "completed"


def test_tasks_get_honours_history_length_and_is_observed(agent: Agent) -> None:
    run_id, body = run_message()
    events = stream(agent.http, agent.url(), body)
    task_id = events[0]["id"]
    answer = rpc(agent.http, agent.url(), "tasks/get", {"id": task_id, "historyLength": 1})
    task = answer["result"]
    assert task["id"] == task_id
    assert task["status"]["state"] == "completed"
    assert len(task.get("history") or []) <= 1
    answer10 = rpc(
        agent.http, agent.url(), "GetTask", {"id": task_id, "historyLength": 1}, protocol="1.0"
    )
    assert answer10["result"]["status"]["state"] == "TASK_STATE_COMPLETED"
    seen = agent.observations(run_id)["a2a_requests"]
    gets = [r for r in seen if r["method"] in ("tasks/get", "GetTask")]
    assert [r["history_length"] for r in gets] == [1, 1]
    assert {r["task_id"] for r in gets} == {task_id}


def test_unknown_task_is_task_not_found(agent: Agent) -> None:
    answer = rpc(agent.http, agent.url(), "tasks/get", {"id": "no-such-task", "historyLength": 1})
    assert answer["error"]["code"] == -32001


def test_what_soundings_sends_is_recorded_without_secrets(agent: Agent) -> None:
    run_id, body = run_message()
    stream(agent.http, agent.url(), body)
    seen = agent.observations(run_id)
    request = seen["a2a_requests"][0]
    assert request["method"] == "message/stream"
    assert request["a2a_version"] == "0.3"
    assert request["x_user_id"] == "soundings"
    assert request["authorization"] == "none"
    assert request["cookie"] is False
    assert request["message_id"] == run_id
    assert request["context_id_sent"] is False
    assert request["configuration"] == ["acceptedOutputModes"]
    assert seen["message_checks"] == {"has_url": False, "has_api_key": False}
    assert "sdg_" not in str(seen)


def test_a_message_with_a_url_or_key_is_flagged(agent: Agent) -> None:
    run_id, body = run_message()
    body["params"]["message"]["parts"][0]["text"] += (
        " Use http://evil.example/mcp with sdg_abcdefghijk"
    )
    stream(agent.http, agent.url(), body)
    assert agent.observations(run_id)["message_checks"] == {"has_url": True, "has_api_key": True}


def test_a_message_that_is_not_a_soundings_run_gets_an_answer_only(agent: Agent) -> None:
    _, body = run_message()
    del body["params"]["message"]["metadata"]
    events = stream(agent.http, agent.url(), body)
    assert state_of(events[-1]) == "completed"
    assert agent.mcp.tools() == []


def test_controller_token(make_agent: Any, settings: Settings) -> None:
    agent = make_agent(settings, required_token="controller-token")
    _, body = run_message()
    card_url = agent.url() + ".well-known/agent-card.json"
    assert agent.http.get(card_url).status_code == 401
    assert agent.http.post(agent.url(), json=body, headers=headers()).status_code == 401
    wrong = headers(Authorization="Bearer nope")
    assert agent.http.post(agent.url(), json=body, headers=wrong).status_code == 401
    ok = agent.http.get(card_url, headers={"Authorization": "Bearer controller-token"})
    assert ok.status_code == 200
    with agent.http.stream(
        "POST", agent.url(), json=body, headers=headers(Authorization="Bearer controller-token")
    ) as response:
        assert response.status_code == 200


def test_unavailable_answers_503(agent: Agent) -> None:
    _, body = run_message()
    url = agent.url("idea-evaluator-unavailable")
    assert agent.http.post(url, json=body, headers=headers()).status_code == 503
    assert agent.http.get(url + ".well-known/agent-card.json").status_code == 503


def test_observations_can_be_listed_and_cleared(agent: Agent) -> None:
    run_id, body = run_message()
    stream(agent.http, agent.url(), body)
    listed = agent.http.get(f"{agent.base}/_fake/observations", params={"run_id": run_id}).json()
    assert [run["run_id"] for run in listed["runs"]] == [run_id]
    assert agent.http.delete(f"{agent.base}/_fake/observations").status_code == 204
    assert agent.http.get(f"{agent.base}/_fake/observations/{run_id}").status_code == 404
    assert agent.http.get(f"{agent.base}/healthz").json() == {"status": "ok"}


def test_a2a_sdk_0_3_client_interoperates(agent: Agent) -> None:
    """a2a-sdk 0.3.23's own client (what kagent-adk 0.10.2 is built on) against the fake:
    card, stream, tasks/get, tasks/cancel. Needs uv and the package index once (cached);
    FAKE_AGENT_COMPAT=0 skips it."""
    import os
    import shutil
    import subprocess
    from pathlib import Path

    if os.environ.get("FAKE_AGENT_COMPAT") == "0" or shutil.which("uv") is None:
        pytest.skip("FAKE_AGENT_COMPAT=0 or no uv")
    script = Path(__file__).parent.parent / "compat" / "a2a_0_3_client.py"
    command = ["uv", "run", "--quiet", "--isolated", "--no-project"]
    command += ["--with", "a2a-sdk==0.3.23", "--with", "httpx", "python", str(script)]
    command += [agent.url(), agent.url("idea-evaluator-slow")]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env={k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok  0.3 tasks/cancel: canceled" in result.stdout


def test_byo_mode_serves_one_agent_at_the_root(make_agent: Any, settings: Settings) -> None:
    """kagent's controller proxies a ``type: BYO`` Agent to its pod's root (port 8080)."""
    agent = make_agent(settings, byo=("soundings", "idea-evaluator"))
    card = agent.http.get(f"{agent.base}/.well-known/agent-card.json").json()
    assert card["name"] == "idea_evaluator"
    assert card["url"] == f"{agent.base}/"
    _, body = run_message()
    events = stream(agent.http, f"{agent.base}/", body)
    assert state_of(events[-1]) == "completed"
    assert agent.mcp.tools() == ["get_rubric", "get_idea", "submit_evaluation"]
