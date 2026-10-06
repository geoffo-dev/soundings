"""The worker's two pools (contract-phase6 section 3.3): AI runs on their own ``ai`` pool
(``SOUNDINGS_AI_MAX_CONCURRENT_RUNS``, first in first out) never hold up the main pool,
and stopping the worker ends a running run ``worker_lost`` at once after a
``tasks/cancel``, through procrastinate's real job handling."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from procrastinate import App, PsycopgConnector
from procrastinate.worker import Worker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.runner import AiRuntime
from app.config import Settings
from app.email.delivery import Runtime
from app.models.enums import AiRunError, AiRunStatus
from app.worker import MAIN_QUEUES, ai_worker_options, procrastinate_app, run_pools, worker_options
from tests.ai.conftest import AsUser, Crew, ok
from tests.ai.fake_kagent import FakeKagent
from tests.ai.helpers import events, make_agent, run_row


@pytest.fixture
async def jobs(settings: Settings) -> AsyncIterator[App]:
    with procrastinate_app.replace_connector(
        PsycopgConnector(conninfo=settings.database_dsn, min_size=1, max_size=6)
    ) as job_app:
        async with job_app.open_async():
            job_app.perform_import_paths()  # type: ignore[no-untyped-call]
            yield job_app


async def _request(api: AsUser, crew: Crew, agent_id: UUID) -> UUID:
    created = ok(
        await (await api(crew.team.owner)).post(
            f"/ideas/{crew.ref}/ai-runs/research", {"agent_id": str(agent_id)}
        ),
        201,
    )
    return UUID(created["id"])


async def _types(db: AsyncSession, run_id: UUID) -> list[str]:
    return [event.type.value for event in await events(db, run_id)]


async def _job_count(db: AsyncSession, task: str) -> int:
    count = await db.scalar(
        text(
            "SELECT count(*) FROM procrastinate_jobs"
            " WHERE task_name = :task AND status IN ('todo', 'doing')"
        ),
        {"task": task},
    )
    await db.commit()
    return int(count or 0)


async def test_runs_wait_for_their_own_pool_and_end_worker_lost_on_stop(
    api: AsUser,
    crew: Crew,
    db_session: AsyncSession,
    ai_runtime: AiRuntime,
    kagent: FakeKagent,
    jobs: App,
    settings: Settings,
) -> None:
    first_agent = await make_agent(db_session, [crew.team.project], key=True, name="first-slow")
    second_agent = await make_agent(db_session, [crew.team.project], key=True, name="second-slow")
    first = await _request(api, crew, first_agent.id)
    second = await _request(api, crew, second_agent.id)
    email = Runtime(settings=settings, sessionmaker=ai_runtime.sessionmaker, jobs=jobs)
    main = Worker(
        app=jobs,
        queues=list(MAIN_QUEUES),
        install_signal_handlers=False,
        **worker_options(concurrency=1, runtime=email, ai_runtime=ai_runtime),
    )
    ai = Worker(
        app=jobs,
        install_signal_handlers=False,
        **ai_worker_options(concurrency=1, runtime=email, ai_runtime=ai_runtime),
    )
    pools = asyncio.create_task(run_pools(main, ai))
    try:
        async with asyncio.timeout(10):
            while "agent_working" not in await _types(db_session, first):  # noqa: ASYNC110
                await asyncio.sleep(0.05)
        # The ai pool is full: the second run waits, queued, first in first out...
        await asyncio.sleep(0.3)
        assert (await run_row(db_session, second)).status is AiRunStatus.QUEUED
        # ...while the main pool keeps working.
        await jobs.configure_task("remove_old_jobs").defer_async(timestamp=1)
        async with asyncio.timeout(10):
            while await _job_count(db_session, "remove_old_jobs"):  # noqa: ASYNC110
                await asyncio.sleep(0.05)
        assert (await run_row(db_session, first)).status is AiRunStatus.RUNNING
    finally:
        main.stop()  # type: ignore[no-untyped-call]
        ai.stop()  # type: ignore[no-untyped-call]
        await asyncio.wait_for(pools, 15)

    stopped = await run_row(db_session, first)
    assert (stopped.status, stopped.error_code) == (AiRunStatus.FAILED, AiRunError.WORKER_LOST)
    assert len(kagent.calls("tasks/cancel")) == 1
    assert (await run_row(db_session, second)).status is AiRunStatus.QUEUED  # not started
