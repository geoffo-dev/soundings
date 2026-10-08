"""The ``run_ai`` job end to end (contract-phase6 sections 3.3 and 3.4) against the
in-process fake controller: the agent really calls ``/mcp`` with its key. Statuses,
events, results, timeout, cancel (queued, running, an agent that can't cancel),
shutdown, retries, polling, every task state, the sweep, compare-and-set races."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import transitions
from app.ai.runner import AiRuntime, execute_run, sweep_runs
from app.db import session_scope
from app.models.activity import ActivityEvent
from app.models.ai import AiAgent, AiRun
from app.models.base import utcnow
from app.models.enums import (
    AiAgentProtocol,
    AiRunError,
    AiRunEventType,
    AiRunKind,
    AiRunStatus,
    EvaluationStatus,
    EvaluatorState,
    IdeaStatus,
    NotificationType,
    SuggestionSource,
)
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaEvaluator
from app.models.notification import Notification
from app.models.proposal import ProposalSuggestion
from app.schemas.activity import AI_RESEARCH_NOTE
from tests.ai.conftest import AsUser, Crew, ok
from tests.ai.fake_kagent import FakeKagent
from tests.ai.helpers import Agent, ago, events, make_agent, open_run, run_row
from tests.factories import add_evaluator, make_idea

PATHS = {"evaluate": "evaluation", "research": "research", "draft_section": "section-draft"}


async def _request(
    api: AsUser,
    crew: Crew,
    kind: str = "evaluate",
    *,
    agent: Agent | None = None,
    ref: str | None = None,
    section: str | None = None,
) -> UUID:
    body: dict[str, Any] = {"agent_id": str((agent or crew.agent).id)}
    if section is not None:
        body["section_key"] = section
    created = ok(
        await (await api(crew.team.owner)).post(
            f"/ideas/{ref or crew.ref}/ai-runs/{PATHS[kind]}", body
        ),
        201,
    )
    return UUID(created["id"])


async def _agent(db: AsyncSession, crew: Crew, name: str, **kwargs: Any) -> Agent:
    return await make_agent(db, [crew.team.project], key=True, name=name, **kwargs)


async def _types(db: AsyncSession, run_id: UUID) -> list[str]:
    return [event.type.value for event in await events(db, run_id)]


async def _messages(db: AsyncSession, run_id: UUID) -> list[str]:
    return [event.message for event in await events(db, run_id)]


async def _until(check: Callable[[], Awaitable[bool]], seconds: float = 5.0) -> None:
    """Poll ``check`` (the database) until it holds."""
    async with asyncio.timeout(seconds):
        while not await check():  # noqa: ASYNC110 - polling another session's writes
            await asyncio.sleep(0.02)


def _working(db: AsyncSession, run_id: UUID) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        return "agent_working" in await _types(db, run_id)

    return check


# --- The happy paths ----------------------------------------------------------------------------
async def test_an_evaluation_run_end_to_end(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime, kagent: FakeKagent
) -> None:
    run_id = await _request(api, crew)

    await execute_run(ai_runtime, run_id)

    run = await run_row(db_session, run_id)
    assert (run.status, run.error_code) == (AiRunStatus.SUCCEEDED, None)
    assert run.evaluation_id is not None
    assert run.a2a_task_id is not None
    assert run.a2a_task_id.startswith("task-")
    assert await _messages(db_session, run_id) == [
        "Waiting to start",
        "Sending the request to the agent",
        "The agent started",
        "The agent is working",
        "Read the rubric",
        "Read the idea",
        "Saved its evaluation",
        "Evaluation submitted",
        "Done",
    ]
    assert [e.seq for e in await events(db_session, run_id)] == list(range(1, 10))
    evaluation = await db_session.get(Evaluation, run.evaluation_id, populate_existing=True)
    assert evaluation is not None
    assert (evaluation.status, evaluation.include_in_aggregate) == (
        EvaluationStatus.SUBMITTED,
        False,
    )
    # The A2A side: one message, to the built URL, naming the run; no URL, key or idea text.
    [sent] = kagent.calls("message/stream")
    assert sent.url == "http://kagent-controller.kagent:8083/api/a2a/soundings/idea-evaluator/"
    message = sent.body["params"]["message"]
    assert message["messageId"] == str(run_id)
    assert message["metadata"]["soundings"] == {
        "run_id": str(run_id),
        "kind": "evaluate",
        "idea": crew.ref,
        "section_key": None,
    }
    text = message["parts"][0]["text"]
    assert crew.ref in text
    assert str(run_id) in text
    assert crew.agent.key is not None
    assert crew.agent.key not in str(sent.body)
    assert "://" not in text
    assert "Parcel lockers" not in text
    assert kagent.calls("tasks/cancel") == []
    assert [r.method for r in kagent.requests] == ["POST"]  # a run never reads the card
    # The run as people see it.
    detail = ok(await (await api(crew.team.viewer)).get(f"/ideas/{crew.ref}/ai-runs/{run_id}"))
    assert detail["result"]["evaluation_id"] == str(run.evaluation_id)
    assert detail["status"] == "succeeded"
    assert detail["deadline_at"] is None
    assert crew.observations == [{"score_hidden": True}]


async def test_research_and_draft_runs_attach_their_results(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime
) -> None:
    idea = await make_idea(
        db_session, crew.team.project, status=IdeaStatus.SHORTLISTED, owner=crew.team.owner
    )
    ref = f"CUST-{idea.number}"
    ok(await (await api(crew.team.owner)).post(f"/ideas/{ref}/proposal"), 201)
    research = await _request(api, crew, "research", ref=ref)
    draft = await _request(api, crew, "draft_section", ref=ref, section="risks")

    await execute_run(ai_runtime, research)
    await execute_run(ai_runtime, draft)

    note_run = await run_row(db_session, research)
    draft_run = await run_row(db_session, draft)
    assert note_run.status is draft_run.status is AiRunStatus.SUCCEEDED
    note = await db_session.get(ActivityEvent, note_run.activity_event_id, populate_existing=True)
    assert note is not None
    assert note.type == AI_RESEARCH_NOTE
    assert note.actor_id == crew.agent.user.id
    assert note.payload["run_id"] == str(research)
    assert len(note.payload["sources"]) == 3
    suggestion = await db_session.get(
        ProposalSuggestion, draft_run.suggestion_id, populate_existing=True
    )
    assert suggestion is not None
    assert (suggestion.source, suggestion.section_key) == (SuggestionSource.AI, "risks")
    assert (await _messages(db_session, research))[-3:] == [
        "Wrote the research note",
        "Research note saved",
        "Done",
    ]
    assert (await _messages(db_session, draft))[-3:] == [
        "Suggested section text",
        "Suggestion saved",
        "Done",
    ]
    feed = ok(await (await api(crew.team.viewer)).get(f"/ideas/{ref}/activity"))
    [item] = [i for i in feed["items"] if i["type"] == "ai_research_note"]
    assert item["note"]["run_id"] == str(research)
    assert item["note"]["agent"]["id"] == str(crew.agent.id)
    assert [s["host"] for s in item["note"]["sources"]] == ["example.org"] * 3
    assert item["note"]["can_delete"] is False  # a viewer
    assert crew.observations == [{"score_hidden": True}]


async def test_a_kagent_10_agent(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime, kagent: FakeKagent
) -> None:
    await db_session.execute(
        update(AiAgent)
        .where(AiAgent.id == crew.agent.id)
        .values(protocol=AiAgentProtocol.KAGENT_V1_0)
    )
    await db_session.commit()
    run_id = await _request(api, crew, "research")

    await execute_run(ai_runtime, run_id)

    assert (await run_row(db_session, run_id)).status is AiRunStatus.SUCCEEDED
    [sent] = kagent.calls("SendStreamingMessage")
    assert sent.url == "http://kagent-controller.kagent:8083/agents/soundings/idea-evaluator"
    assert sent.headers["a2a-version"] == "1.0"


# --- Outcomes by task state ---------------------------------------------------------------------
@pytest.mark.parametrize(
    ("suffix", "status", "error", "message"),
    [
        (
            "silent",
            AiRunStatus.FAILED,
            AiRunError.NO_RESULT,
            "The agent finished without saving a result.",
        ),
        (
            "asks",
            AiRunStatus.FAILED,
            AiRunError.AGENT_NEEDS_INPUT,
            "The agent asked for input, which a run can't give. (state input-required)",
        ),
        (
            "fails",
            AiRunStatus.FAILED,
            AiRunError.AGENT_FAILED,
            "The agent stopped with an error. (state failed)",
        ),
        (
            "rejects",
            AiRunStatus.FAILED,
            AiRunError.AGENT_REJECTED,
            "The agent declined the request. (state rejected)",
        ),
        (
            "unknown",
            AiRunStatus.FAILED,
            AiRunError.AGENT_PROTOCOL_ERROR,
            "The agent's answer couldn't be understood.",
        ),
        (
            "message",
            AiRunStatus.FAILED,
            AiRunError.NO_RESULT,
            "The agent finished without saving a result.",
        ),
        (
            "redirect",
            AiRunStatus.FAILED,
            AiRunError.AGENT_PROTOCOL_ERROR,
            "The agent's answer couldn't be understood. (HTTP 302)",
        ),
        (
            "down",
            AiRunStatus.FAILED,
            AiRunError.AGENT_UNREACHABLE,
            "Couldn't reach the agent. (HTTP 503)",
        ),
    ],
)
async def test_each_ending(
    api: AsUser,
    crew: Crew,
    db_session: AsyncSession,
    ai_runtime: AiRuntime,
    kagent: FakeKagent,
    suffix: str,
    status: AiRunStatus,
    error: AiRunError,
    message: str,
) -> None:
    agent = await _agent(db_session, crew, f"agent-{suffix}")
    run_id = await _request(api, crew, "research", agent=agent)

    await execute_run(ai_runtime, run_id)

    run = await run_row(db_session, run_id)
    assert (run.status, run.error_code, run.error_message) == (status, error, message)
    found = await events(db_session, run_id)
    assert found[-1].type is AiRunEventType.FAILED
    assert found[-1].message == message
    assert "dreaming" not in str([e.message for e in found])
    if suffix == "asks":
        assert len(kagent.calls("tasks/cancel")) == 1
    if suffix == "down":
        assert len(kagent.calls("message/stream")) == 3  # two retries
        assert (await _types(db_session, run_id)).count("retrying") == 2


async def test_a_result_recorded_before_the_task_fails_succeeds(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime, kagent: FakeKagent
) -> None:
    await db_session.execute(
        update(AiAgent).where(AiAgent.id == crew.agent.id).values(name="idea-evaluator-donefails")
    )
    await db_session.commit()
    run_id = await _request(api, crew, "research")

    await execute_run(ai_runtime, run_id)

    run = await run_row(db_session, run_id)
    assert (run.status, run.error_code) == (AiRunStatus.SUCCEEDED, None)
    assert run.activity_event_id is not None


async def test_a_dropped_stream_is_polled_with_one_history_entry(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime, kagent: FakeKagent
) -> None:
    await db_session.execute(
        update(AiAgent).where(AiAgent.id == crew.agent.id).values(name="idea-evaluator-drops")
    )
    await db_session.commit()
    run_id = await _request(api, crew, "research")

    await execute_run(ai_runtime, run_id)

    assert (await run_row(db_session, run_id)).status is AiRunStatus.SUCCEEDED
    polls = kagent.calls("tasks/get")
    assert polls
    assert all(p.body["params"]["historyLength"] == 1 for p in polls)
    assert len(kagent.calls("message/stream")) == 1  # never resent


# --- Deadline, cancel, shutdown -----------------------------------------------------------------
async def test_the_deadline_cancels_the_task_and_times_out(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime, kagent: FakeKagent
) -> None:
    agent = await _agent(db_session, crew, "agent-slow")
    run_id = await _request(api, crew, "research", agent=agent)
    runtime = dataclasses.replace(ai_runtime, timeout_for=lambda seconds: 0.4)

    await execute_run(runtime, run_id)

    run = await run_row(db_session, run_id)
    assert (run.status, run.error_code) == (AiRunStatus.TIMED_OUT, AiRunError.TIMED_OUT)
    assert run.error_message == "The agent didn't finish in time."
    assert len(kagent.calls("tasks/cancel")) == 1
    assert (await events(db_session, run_id))[-1].type is AiRunEventType.TIMED_OUT


@pytest.mark.parametrize("suffix", ["slow", "slow-nocancel"])
async def test_cancel_while_running(
    api: AsUser,
    crew: Crew,
    db_session: AsyncSession,
    ai_runtime: AiRuntime,
    kagent: FakeKagent,
    suffix: str,
) -> None:
    agent = await _agent(db_session, crew, f"agent-{suffix}")
    run_id = await _request(api, crew, "research", agent=agent)
    job = asyncio.create_task(execute_run(ai_runtime, run_id))
    await _until(_working(db_session, run_id))

    cancelling = ok(
        await (await api(crew.team.owner)).post(f"/ideas/{crew.ref}/ai-runs/{run_id}/cancel")
    )
    await asyncio.wait_for(job, 5)

    assert cancelling["cancel_requested"] is True
    run = await run_row(db_session, run_id)
    assert (run.status, run.error_code) == (AiRunStatus.CANCELLED, None)
    assert len(kagent.calls("tasks/cancel")) == 1  # -32603 from a runtime that can't: fine
    types = await _types(db_session, run_id)
    assert types[-2:] == ["cancel_requested", "cancelled"]


async def test_cancel_while_queued_sends_nothing(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime, kagent: FakeKagent
) -> None:
    run_id = await _request(api, crew)
    ok(await (await api(crew.team.owner)).post(f"/ideas/{crew.ref}/ai-runs/{run_id}/cancel"))

    await execute_run(ai_runtime, run_id)  # the job finds it cancelled

    assert (await run_row(db_session, run_id)).status is AiRunStatus.CANCELLED
    assert kagent.requests == []
    assert await _types(db_session, run_id) == ["queued", "cancelled"]
    # It assigned the agent; ending without an evaluation took that back.
    assert (
        await db_session.get(
            IdeaEvaluator, (crew.idea.id, crew.agent.user.id), populate_existing=True
        )
        is None
    )


async def test_stopping_the_worker_ends_the_run_worker_lost(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime, kagent: FakeKagent
) -> None:
    agent = await _agent(db_session, crew, "agent-slow")
    run_id = await _request(api, crew, "research", agent=agent)
    job = asyncio.create_task(execute_run(ai_runtime, run_id))
    await _until(_working(db_session, run_id))

    job.cancel()  # what procrastinate does to the ai pool's jobs on SIGTERM
    with pytest.raises(asyncio.CancelledError):
        await job

    run = await run_row(db_session, run_id)
    assert (run.status, run.error_code) == (AiRunStatus.FAILED, AiRunError.WORKER_LOST)
    assert run.error_message == "The worker running it stopped before it finished."
    assert len(kagent.calls("tasks/cancel")) == 1


async def test_a_deleted_idea_stops_the_run(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime, kagent: FakeKagent
) -> None:
    agent = await _agent(db_session, crew, "agent-slow")
    run_id = await _request(api, crew, "research", agent=agent)
    job = asyncio.create_task(execute_run(ai_runtime, run_id))
    await _until(_working(db_session, run_id))

    response = await (await api(crew.team.admin)).delete(f"/ideas/{crew.ref}")
    assert response.status_code == 204, response.text
    await asyncio.wait_for(job, 5)

    assert await db_session.scalar(select(AiRun).where(AiRun.id == run_id)) is None
    assert len(kagent.calls("tasks/cancel")) == 1


# --- Start-time checks --------------------------------------------------------------------------
async def test_ai_turned_off_before_the_run_starts(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime, kagent: FakeKagent
) -> None:
    run_id = await _request(api, crew)
    off = dataclasses.replace(
        ai_runtime, settings=ai_runtime.settings.model_copy(update={"ai_enabled": False})
    )

    await execute_run(off, run_id)

    run = await run_row(db_session, run_id)
    assert (run.status, run.error_code, run.started_at) == (
        AiRunStatus.FAILED,
        AiRunError.AI_DISABLED,
        None,
    )
    assert kagent.requests == []
    assert (
        await db_session.get(
            IdeaEvaluator, (crew.idea.id, crew.agent.user.id), populate_existing=True
        )
        is None
    )


async def test_an_agent_unavailable_at_start(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime, kagent: FakeKagent
) -> None:
    run_id = await _request(api, crew, "research")
    await db_session.execute(
        update(AiAgent).where(AiAgent.id == crew.agent.id).values(purposes=["evaluate"])
    )
    await db_session.commit()

    await execute_run(ai_runtime, run_id)

    run = await run_row(db_session, run_id)
    assert (run.status, run.error_code) == (AiRunStatus.FAILED, AiRunError.AGENT_UNAVAILABLE)
    assert kagent.requests == []


async def test_a_duplicate_job_does_nothing(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime, kagent: FakeKagent
) -> None:
    run_id = await _request(api, crew, "research")
    await execute_run(ai_runtime, run_id)
    before = await _types(db_session, run_id)

    await execute_run(ai_runtime, run_id)

    assert await _types(db_session, run_id) == before
    assert len(kagent.calls("message/stream")) == 1


# --- No result, no assignment -----------------------------------------------------------------
async def test_a_failed_evaluation_run_takes_its_assignment_back_and_all_evaluations_are_in(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime
) -> None:
    for evaluator in crew.team.evaluators[:2]:
        await add_evaluator(db_session, crew.idea, evaluator, state=EvaluatorState.SUBMITTED)
    agent = await _agent(db_session, crew, "agent-fails")
    run_id = await _request(api, crew, agent=agent)
    assert await db_session.get(IdeaEvaluator, (crew.idea.id, agent.user.id)) is not None

    await execute_run(ai_runtime, run_id)

    assert (await run_row(db_session, run_id)).status is AiRunStatus.FAILED
    db_session.expunge_all()
    assert await db_session.get(IdeaEvaluator, (crew.idea.id, agent.user.id)) is None
    complete = list(
        await db_session.scalars(
            select(Notification).where(
                Notification.type == NotificationType.EVALUATIONS_COMPLETE,
                Notification.user_id == crew.team.owner.id,
            )
        )
    )
    assert len(complete) == 1


# --- Races, the sweep, the event cap ---------------------------------------------------------
async def test_cancel_and_completion_end_in_exactly_one_final_status(
    crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime
) -> None:
    maker = ai_runtime.sessionmaker

    async def complete(run_id: UUID) -> Any:
        async with session_scope(maker) as db:
            return await transitions.finish(
                db,
                run_id,
                from_status=AiRunStatus.RUNNING,
                status=AiRunStatus.FAILED,
                error=AiRunError.NO_RESULT,
            )

    async def cancel(run_id: UUID) -> Any:
        async with session_scope(maker) as db:
            await transitions.lock_idea(db, crew.idea.id)
            return await transitions.cancel(db, run_id, by_id=crew.team.owner.id)

    for _ in range(5):
        run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)

        finished, cancelled = await asyncio.gather(complete(run.id), cancel(run.id))

        found = await events(db_session, run.id)
        finals = [e for e in found if e.type.value in ("succeeded", "failed", "cancelled")]
        assert len(finals) == 1
        final = (await run_row(db_session, run.id)).status
        assert finished is not None
        assert finished.status is final
        # Either the cancel request landed first (the finish then ends it cancelled), or
        # the finish did (the cancel then finds it over): never both, never neither.
        assert (final, cancelled) in (
            (AiRunStatus.CANCELLED, AiRunStatus.RUNNING),
            (AiRunStatus.FAILED, None),
        )


async def test_the_sweep_ends_lost_and_stale_queued_runs(
    crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime, kagent: FakeKagent
) -> None:
    other = await make_idea(db_session, crew.team.project)
    lost = await open_run(
        db_session, crew.agent, crew.idea, AiRunKind.RESEARCH, heartbeat_at=ago(minutes=3)
    )
    await db_session.execute(
        update(AiRun).where(AiRun.id == lost.id).values(a2a_task_id="task-lost")
    )
    alive = await open_run(
        db_session, crew.agent, other, AiRunKind.RESEARCH, heartbeat_at=ago(seconds=10)
    )
    queued = await open_run(
        db_session,
        crew.agent,
        other,
        AiRunKind.EVALUATE,
        status=AiRunStatus.QUEUED,
        created_at=ago(minutes=31),
    )
    fresh = await open_run(
        db_session, crew.agent, crew.idea, AiRunKind.EVALUATE, status=AiRunStatus.QUEUED
    )
    await db_session.commit()

    result = await sweep_runs(ai_runtime)

    assert (result.lost, result.expired) == (1, 1)
    assert (await run_row(db_session, lost.id)).error_code is AiRunError.WORKER_LOST
    assert (await run_row(db_session, alive.id)).status is AiRunStatus.RUNNING
    expired = await run_row(db_session, queued.id)
    assert (expired.status, expired.error_code) == (AiRunStatus.TIMED_OUT, AiRunError.QUEUE_TIMEOUT)
    assert (await run_row(db_session, fresh.id)).status is AiRunStatus.QUEUED
    [cancel] = kagent.calls("tasks/cancel")
    assert cancel.body["params"] == {"id": "task-lost"}


async def test_a_run_keeps_at_most_200_events_the_final_included(
    crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime
) -> None:
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    async with session_scope(ai_runtime.sessionmaker) as db:
        for _ in range(205):
            await transitions.add_event(db, run.id, AiRunEventType.TOOL_CALLED, "Read the idea")
    async with session_scope(ai_runtime.sessionmaker) as db:
        await transitions.finish(
            db, run.id, from_status=AiRunStatus.RUNNING, status=AiRunStatus.CANCELLED
        )
        after_final = await transitions.add_event(
            db, run.id, AiRunEventType.TOOL_CALLED, "Read the idea"
        )

    found = await events(db_session, run.id)
    assert len(found) == 200
    assert found[-1].type is AiRunEventType.CANCELLED
    assert after_final is None  # nothing follows the final event
    assert (await run_row(db_session, run.id)).event_count == 200


async def test_an_evaluate_run_is_matched_by_the_server_not_by_agent_text(
    api: AsUser, crew: Crew, db_session: AsyncSession, ai_runtime: AiRuntime
) -> None:
    """A run's result is the agent's own submitted evaluation on the run's idea, attached
    in the tool's transaction; a draft doesn't count."""
    run_id = await _request(api, crew)
    await execute_run(ai_runtime, run_id)

    run = await run_row(db_session, run_id)
    evaluation = await db_session.get(Evaluation, run.evaluation_id)
    assert evaluation is not None
    assert (evaluation.idea_id, evaluation.evaluator_id) == (crew.idea.id, crew.agent.user.id)
    idea = await db_session.get(Idea, crew.idea.id, populate_existing=True)
    assert idea is not None
    assert idea.aggregate_count in (0, None)
    assert utcnow() >= run.finished_at  # type: ignore[operator]


async def test_the_sweep_sends_its_cancels_side_by_side_within_one_deadline(
    crew: Crew,
    db_session: AsyncSession,
    ai_runtime: AiRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L7: with the controller hanging, the sweep still ends every lost run at once and
    spends at most about one cancel deadline on their ``tasks/cancel`` (sent side by side,
    after the runs ended), not one per run on the main pool."""
    import asyncio
    import time

    import httpx

    from app.ai import a2a

    async def hang(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)
        return httpx.Response(200, json={})

    monkeypatch.setattr(a2a, "CANCEL_DEADLINE", 0.3)
    ai_runtime.transport = httpx.MockTransport(hang)
    lost = []
    for n in range(4):
        idea = await make_idea(db_session, crew.team.project)
        run = await open_run(
            db_session, crew.agent, idea, AiRunKind.RESEARCH, heartbeat_at=ago(minutes=3)
        )
        await db_session.execute(
            update(AiRun).where(AiRun.id == run.id).values(a2a_task_id=f"task-{n}")
        )
        lost.append(run)
    await db_session.commit()

    started = time.monotonic()
    result = await sweep_runs(ai_runtime)
    took = time.monotonic() - started

    assert result.lost == 4
    assert took < 4 * 0.3
    for run in lost:
        assert (await run_row(db_session, run.id)).error_code is AiRunError.WORKER_LOST
