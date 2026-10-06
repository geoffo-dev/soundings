"""The ``run_ai`` job and the sweep (contract-phase6 sections 3.3 and 3.4).

One job per run, on the ``ai`` queue (the worker's own pool of
``SOUNDINGS_AI_MAX_CONCURRENT_RUNS``, so runs never hold up email or the schedules):

1. **Prepare** (one transaction): the run must still be ``queued`` (a duplicate job, or a
   run cancelled or timed out meanwhile, does nothing); AI must be on (else ``failed``
   ``ai_disabled``) and the agent must pass c10 (else ``failed`` ``agent_unavailable``);
   then *start* (``queued`` -> ``running``, compare-and-set) and the ``started`` event.
2. **Talk A2A** under the deadline (``started_at + timeout_seconds``): always
   ``message/stream`` to the **built** URL (never the card's); task states become events
   and the outcome (the contract's table); the stream silent for 120 s or cut off with a
   task id switches to polling ``tasks/get`` (``historyLength: 1``), never resending;
   before a task exists, connection failures and 502-504 are retried after 5 s and 15 s.
3. **Watch** at the same time: every 2 s the run row is re-read (the heartbeat written
   every 15 s). A cancel request -> ``tasks/cancel`` (best effort, 5 s) and ``cancelled``;
   the run gone (its idea deleted) or ended by someone else -> ``tasks/cancel`` and stop.
4. **Finish** (:func:`app.ai.transitions.finish`): ``succeeded`` when the agent recorded
   its result through MCP, whatever the task's final state; ``cancelled`` after a cancel
   request; else the outcome (``failed`` / ``timed_out`` with Soundings' sentence).

The deadline sends ``tasks/cancel`` and ends ``timed_out``. A worker that is stopped
(SIGTERM) cancels the job at once: it sends ``tasks/cancel`` and ends the run ``failed``
``worker_lost`` in its handler; nothing is resumed. Nothing here ever reads agent text:
results arrive through MCP and are attached by the server.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import agents as agent_service
from app.ai.a2a import (
    INTERRUPTED_STATES,
    A2AClient,
    A2AProtocolError,
    A2AUnreachable,
    StreamInterrupted,
    TaskEvent,
)
from app.ai.transitions import add_event, finish, start
from app.config import Settings
from app.db import SessionMaker, session_scope
from app.domain.idea_keys import format_key
from app.models.ai import AiAgent, AiRun
from app.models.base import utcnow
from app.models.enums import (
    AiAgentProtocol,
    AiRunError,
    AiRunEventType,
    AiRunKind,
    AiRunStatus,
    ProposalSectionKey,
)
from app.models.idea import Idea
from app.models.project import Project
from app.schemas.ai import (
    AI_RUN_CONNECT_RETRIES,
    AI_RUN_HEARTBEAT,
    AI_RUN_POLL_INTERVAL,
    AI_RUN_QUEUE_TIMEOUT,
    AI_RUN_STALE_AFTER,
    run_message,
)

__all__ = ["AiRuntime", "Outcome", "SweepResult", "execute_run", "sweep_runs"]

logger = logging.getLogger("soundings.ai")

CANCEL_POLL: Final = 2.0
"""Seconds between the watcher's reads of the run row (a cancel request is seen within
about this long)."""


@dataclass(slots=True)
class AiRuntime:
    """What the AI jobs need: settings, sessions, the network (``transport`` replaces it
    in tests), a clock and the timings (tests shorten them)."""

    settings: Settings
    sessionmaker: SessionMaker
    transport: httpx.AsyncBaseTransport | None = None
    clock: Callable[[], datetime] = utcnow
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    cancel_poll: float = CANCEL_POLL
    heartbeat: float = AI_RUN_HEARTBEAT.total_seconds()
    poll_interval: float = AI_RUN_POLL_INTERVAL.total_seconds()
    retry_waits: tuple[float, ...] = tuple(wait.total_seconds() for wait in AI_RUN_CONNECT_RETRIES)
    timeout_for: Callable[[int], float] = float
    """A run's ``timeout_seconds`` as the deadline in seconds (tests make it short)."""


@dataclass(frozen=True, slots=True)
class Outcome:
    """How the conversation ended, before the result and the cancel request decide:
    ``status`` / ``error`` as :func:`~app.ai.transitions.finish` takes them. ``gone``: the
    run was deleted or ended elsewhere (nothing to finish)."""

    status: AiRunStatus
    error: AiRunError | None = None
    http_status: int | None = None
    a2a_state: str | None = None
    cancel_task: bool = False
    gone: bool = False


_COMPLETED: Final = Outcome(AiRunStatus.FAILED, AiRunError.NO_RESULT)
_CANCELLED: Final = Outcome(AiRunStatus.CANCELLED)
_TIMED_OUT: Final = Outcome(AiRunStatus.TIMED_OUT, AiRunError.TIMED_OUT)
_WORKER_LOST: Final = Outcome(AiRunStatus.FAILED, AiRunError.WORKER_LOST)
_INTERNAL: Final = Outcome(AiRunStatus.FAILED, AiRunError.INTERNAL_ERROR)
_GONE: Final = Outcome(AiRunStatus.CANCELLED, gone=True)


def _failed(error: AiRunError, **kwargs: object) -> Outcome:
    return Outcome(AiRunStatus.FAILED, error, **kwargs)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class _Run:
    id: UUID
    kind: AiRunKind
    section_key: ProposalSectionKey | None
    idea_key: str
    agent_id: UUID
    agent_name: str
    namespace: str
    name: str
    protocol: AiAgentProtocol
    timeout_seconds: int


@dataclass(slots=True)
class _Conversation:
    task_id: str | None = None
    context_id: str | None = None
    working: bool = False
    events: list[AiRunEventType] = field(default_factory=list)


# --- Small transactions ---------------------------------------------------------------------
async def _event(runtime: AiRuntime, run_id: UUID, type_: AiRunEventType) -> None:
    async with session_scope(runtime.sessionmaker) as db:
        await add_event(db, run_id, type_)


async def _finish(runtime: AiRuntime, run_id: UUID, outcome: Outcome) -> None:
    if outcome.gone:
        return
    try:
        async with session_scope(runtime.sessionmaker, settings=runtime.settings) as db:
            await finish(
                db,
                run_id,
                from_status=AiRunStatus.RUNNING,
                status=outcome.status,
                error=outcome.error,
                http_status=outcome.http_status,
                a2a_state=outcome.a2a_state,
                now=runtime.clock(),
            )
    except Exception:
        # The sweep ends it worker_lost once the heartbeat is stale.
        logger.exception("ai run finish failed", extra={"run_id": str(run_id)})


async def _prepare(runtime: AiRuntime, run_id: UUID) -> _Run | None:
    """Step 1 (see the module docstring): the run to talk about, or ``None``."""
    settings = runtime.settings
    async with session_scope(runtime.sessionmaker, settings=settings) as db:
        row = (
            await db.execute(
                select(AiRun, AiAgent, Idea, Project)
                .join(AiAgent, AiAgent.id == AiRun.agent_id)
                .join(Idea, Idea.id == AiRun.idea_id)
                .join(Project, Project.id == Idea.project_id)
                .where(AiRun.id == run_id)
            )
        ).first()
        if row is None:
            return None  # its idea was deleted
        run, agent, idea, project = row
        if run.status is not AiRunStatus.QUEUED:
            return None  # a duplicate job, or cancelled / timed out meanwhile
        error: AiRunError | None = None
        if not settings.ai_enabled:
            error = AiRunError.AI_DISABLED
        elif await agent_service.usable(db, settings, agent.id, project.id, run.kind) is None:
            error = AiRunError.AGENT_UNAVAILABLE
        if error is not None:
            await finish(
                db,
                run.id,
                from_status=AiRunStatus.QUEUED,
                status=AiRunStatus.FAILED,
                error=error,
                now=runtime.clock(),
            )
            return None
        now = runtime.clock()
        if not await start(db, run.id, now):
            return None
        await add_event(db, run.id, AiRunEventType.STARTED)
        return _Run(
            id=run.id,
            kind=run.kind,
            section_key=run.section_key,
            idea_key=format_key(project.key, idea.number),
            agent_id=agent.id,
            agent_name=agent.display_name,
            namespace=agent.namespace,
            name=agent.name,
            protocol=AiAgentProtocol(agent.protocol),
            timeout_seconds=run.timeout_seconds,
        )


async def _store_task(runtime: AiRuntime, run: _Run, conv: _Conversation) -> None:
    async with session_scope(runtime.sessionmaker) as db:
        await db.execute(
            update(AiRun)
            .where(AiRun.id == run.id, AiRun.status == AiRunStatus.RUNNING)
            .values(a2a_task_id=conv.task_id, a2a_context_id=conv.context_id)
            .execution_options(synchronize_session=False)
        )
        await add_event(db, run.id, AiRunEventType.AGENT_ACCEPTED)


# --- The conversation ------------------------------------------------------------------------
async def _on_event(
    runtime: AiRuntime, run: _Run, conv: _Conversation, event: TaskEvent
) -> Outcome | None:
    """One A2A result: store the task, write progress, and the outcome at its end."""
    if conv.task_id is None and event.task_id is None and event.kind == "message":
        return _COMPLETED  # a direct reply without a task: done
    if conv.task_id is None and event.task_id is not None:
        conv.task_id, conv.context_id = event.task_id, event.context_id
        await _store_task(runtime, run, conv)
    if event.raw_state is not None and event.state is None:
        return _failed(AiRunError.AGENT_PROTOCOL_ERROR, a2a_state=event.raw_state)
    match event.state:
        case None | "submitted":
            return None
        case "working":
            if not conv.working:
                conv.working = True
                await _event(runtime, run.id, AiRunEventType.AGENT_WORKING)
            return None
        case "completed":
            return _COMPLETED
        case "failed" | "canceled":
            return _failed(AiRunError.AGENT_FAILED, a2a_state=event.state)
        case "rejected":
            return _failed(AiRunError.AGENT_REJECTED, a2a_state=event.state)
        case state if state in INTERRUPTED_STATES:
            return _failed(AiRunError.AGENT_NEEDS_INPUT, a2a_state=state, cancel_task=True)
    return _failed(AiRunError.AGENT_PROTOCOL_ERROR, a2a_state=event.raw_state)


async def _converse(
    runtime: AiRuntime, run: _Run, client: A2AClient, conv: _Conversation
) -> Outcome:
    message = run_message(
        run.kind,
        run_id=run.id,
        idea_key=run.idea_key,
        agent_name=run.agent_name,
        section_key=run.section_key,
    )
    attempt = 0
    while True:
        try:
            async with client.stream(message, str(run.id)) as events:
                async for event in events:
                    outcome = await _on_event(runtime, run, conv, event)
                    if outcome is not None:
                        return outcome
            raise StreamInterrupted("stream ended")
        except A2AUnreachable as error:
            if conv.task_id is None and error.retryable and attempt < len(runtime.retry_waits):
                await _event(runtime, run.id, AiRunEventType.RETRYING)
                await runtime.sleep(runtime.retry_waits[attempt])
                attempt += 1
                continue
            if conv.task_id is None:
                return _failed(AiRunError.AGENT_UNREACHABLE, http_status=error.http_status)
        except StreamInterrupted:
            if conv.task_id is None:
                return _failed(AiRunError.AGENT_PROTOCOL_ERROR)
        except A2AProtocolError as error:
            return _failed(AiRunError.AGENT_PROTOCOL_ERROR, http_status=error.http_status)
        break
    # The stream dropped or stayed silent with a task: poll it (the message is never resent).
    assert conv.task_id is not None  # noqa: S101 - the loop above leaves only with a task
    while True:
        await runtime.sleep(runtime.poll_interval)
        try:
            event = await client.get_task(conv.task_id)
        except A2AUnreachable as error:
            if error.retryable:
                continue
            return _failed(AiRunError.AGENT_UNREACHABLE, http_status=error.http_status)
        except A2AProtocolError as error:
            return _failed(AiRunError.AGENT_PROTOCOL_ERROR, http_status=error.http_status)
        outcome = await _on_event(runtime, run, conv, event)
        if outcome is not None:
            return outcome


Signal = Literal["cancel", "gone"]


async def _watch(runtime: AiRuntime, run: _Run) -> Signal:
    """Re-read the run every ``cancel_poll`` seconds (writing the heartbeat every
    ``heartbeat``) until it is cancel-requested or no longer ``running``."""
    last_beat = time.monotonic()
    while True:
        await runtime.sleep(runtime.cancel_poll)
        beat = time.monotonic() - last_beat >= runtime.heartbeat
        async with session_scope(runtime.sessionmaker) as db:
            row = await _beat(db, run.id, runtime.clock()) if beat else await _read(db, run.id)
        if beat:
            last_beat = time.monotonic()
        if row is None or row[0] is not AiRunStatus.RUNNING:
            return "gone"
        if row[1] is not None:
            return "cancel"


async def _beat(db: AsyncSession, run_id: UUID, now: datetime) -> tuple[AiRunStatus, object] | None:
    found = (
        await db.execute(
            update(AiRun)
            .where(AiRun.id == run_id, AiRun.status == AiRunStatus.RUNNING)
            .values(heartbeat_at=now)
            .returning(AiRun.status, AiRun.cancel_requested_at)
            .execution_options(synchronize_session=False)
        )
    ).first()
    return (AiRunStatus(found[0]), found[1]) if found is not None else None


async def _read(db: AsyncSession, run_id: UUID) -> tuple[AiRunStatus, object] | None:
    found = (
        await db.execute(select(AiRun.status, AiRun.cancel_requested_at).where(AiRun.id == run_id))
    ).first()
    return (AiRunStatus(found[0]), found[1]) if found is not None else None


async def _cancel_task(client: A2AClient, conv: _Conversation, run_id: UUID) -> None:
    """``tasks/cancel`` for the run's task, if it has one (best effort, at most 5 s)."""
    if conv.task_id is None:
        return
    try:
        answered = await client.cancel_task(conv.task_id)
    except Exception:  # best effort: the run is final either way
        logger.exception("ai task cancel failed", extra={"run_id": str(run_id)})
        return
    logger.info("ai task cancel sent", extra={"run_id": str(run_id), "answered": answered})


async def _stop(*tasks: asyncio.Task[object]) -> None:
    """Cancel the child tasks and wait for them (their own errors are dropped; a
    cancellation of the caller still propagates)."""
    for task in tasks:
        task.cancel()
    pending = [task for task in tasks if not task.done()]
    if pending:
        await asyncio.wait(pending)
    for task in tasks:
        if not task.cancelled():
            task.exception()  # retrieved, so it is never reported as unhandled


async def _supervise(
    runtime: AiRuntime, run: _Run, client: A2AClient, conv: _Conversation
) -> Outcome:
    """Steps 2 and 3 under the deadline."""
    talk: asyncio.Task[object] = asyncio.create_task(_converse(runtime, run, client, conv))
    watch: asyncio.Task[object] = asyncio.create_task(_watch(runtime, run))
    try:
        async with asyncio.timeout(runtime.timeout_for(run.timeout_seconds)):
            done, _ = await asyncio.wait({talk, watch}, return_when=asyncio.FIRST_COMPLETED)
    except TimeoutError:
        await _stop(talk, watch)
        await _cancel_task(client, conv, run.id)
        return _TIMED_OUT
    except BaseException:
        await _stop(talk, watch)  # the job is being cancelled: stop the children too
        raise
    if talk in done:
        await _stop(watch)
        result = talk.result()
        assert isinstance(result, Outcome)  # noqa: S101 - _converse returns one
        if result.cancel_task:
            await _cancel_task(client, conv, run.id)
        return result
    await _stop(talk)
    signal = watch.result()
    await _cancel_task(client, conv, run.id)
    return _CANCELLED if signal == "cancel" else _GONE


async def execute_run(runtime: AiRuntime, run_id: UUID) -> None:
    """The ``run_ai`` job's body (see the module docstring)."""
    run = await _prepare(runtime, run_id)
    if run is None:
        return
    client = A2AClient(
        runtime.settings,
        run.protocol,
        run.namespace,
        run.name,
        transport=runtime.transport,
        request_prefix=str(run.id),
    )
    conv = _Conversation()
    try:
        outcome = await _supervise(runtime, run, client, conv)
    except asyncio.CancelledError:
        # The worker is stopping (procrastinate cancels the job at once): end the run
        # worker_lost, after asking the agent to cancel; never resumed.
        await _cancel_task(client, conv, run.id)
        await _finish(runtime, run.id, _WORKER_LOST)
        logger.warning("ai run stopped with the worker", extra={"run_id": str(run.id)})
        raise
    except Exception:
        logger.exception("ai run failed", extra={"run_id": str(run.id)})
        await _cancel_task(client, conv, run.id)
        outcome = _INTERNAL
    await _finish(runtime, run.id, outcome)


# --- The sweep -------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SweepResult:
    lost: int = 0
    expired: int = 0


async def sweep_runs(runtime: AiRuntime) -> SweepResult:
    """Every minute on the main pool: ``running`` runs whose heartbeat is older than
    :data:`~app.schemas.ai.AI_RUN_STALE_AFTER` (a killed worker) end ``failed``
    ``worker_lost``, then get a best-effort ``tasks/cancel`` (all at once); runs
    ``queued`` longer than :data:`~app.schemas.ai.AI_RUN_QUEUE_TIMEOUT` end ``timed_out``
    ``queue_timeout``."""
    now = runtime.clock()
    stale_before = now - AI_RUN_STALE_AFTER
    async with session_scope(runtime.sessionmaker) as db:
        stale = (
            await db.execute(
                select(AiRun.id, AiRun.a2a_task_id, AiAgent)
                .join(AiAgent, AiAgent.id == AiRun.agent_id)
                .where(
                    AiRun.status == AiRunStatus.RUNNING,
                    or_(
                        AiRun.heartbeat_at < stale_before,
                        AiRun.heartbeat_at.is_(None) & (AiRun.started_at < stale_before),
                    ),
                )
                .order_by(AiRun.created_at)
                .limit(100)
            )
        ).all()
        expired = list(
            await db.scalars(
                select(AiRun.id)
                .where(
                    AiRun.status == AiRunStatus.QUEUED,
                    AiRun.created_at < now - AI_RUN_QUEUE_TIMEOUT,
                )
                .order_by(AiRun.created_at)
                .limit(100)
            )
        )
    lost = 0
    cancels = []
    for run_id, task_id, agent in stale:
        async with session_scope(runtime.sessionmaker, settings=runtime.settings) as db:
            done = await finish(
                db,
                run_id,
                from_status=AiRunStatus.RUNNING,
                status=AiRunStatus.FAILED,
                error=AiRunError.WORKER_LOST,
                now=now,
            )
        lost += done is not None
        if done is not None and task_id is not None:
            client = A2AClient(
                runtime.settings,
                AiAgentProtocol(agent.protocol),
                agent.namespace,
                agent.name,
                transport=runtime.transport,
                request_prefix=str(run_id),
            )
            cancels.append(_cancel_task(client, _Conversation(task_id=task_id), run_id))
    # The runs are over first; then their best-effort tasks/cancel side by side (each
    # bounded by the cancel deadline), so an unreachable controller holds this main-pool
    # job for about one deadline, not one per run (review L7).
    await asyncio.gather(*cancels)
    timed_out = 0
    for run_id in expired:
        async with session_scope(runtime.sessionmaker, settings=runtime.settings) as db:
            done = await finish(
                db,
                run_id,
                from_status=AiRunStatus.QUEUED,
                status=AiRunStatus.TIMED_OUT,
                error=AiRunError.QUEUE_TIMEOUT,
                now=now,
            )
        timed_out += done is not None
    if lost or timed_out:
        logger.warning("ai runs swept", extra={"lost": lost, "expired": timed_out})
    return SweepResult(lost=lost, expired=timed_out)
