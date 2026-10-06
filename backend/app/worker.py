"""Background jobs with procrastinate (Postgres-backed; no Redis).

Tasks are defined in the modules listed in :data:`TASK_MODULES` (``app.email.tasks``:
``send_email``, ``notify_event``, ``sweep_outbox``, ``notification_schedule``,
``remove_old_jobs``).
Request code defers jobs **on the request's own connection**, atomically with its
writes (``app.email.outbox.defer_send``); the API process also opens a small
job-queue pool in its lifespan. The worker runs with ``soundings worker``; the
procrastinate schema is created by ``soundings migrate`` (see
app/migrations/procrastinate/README.md).

Finished jobs are deleted as they complete (``delete_jobs="successful"``) and the
daily ``remove_old_jobs`` clears failed, cancelled and aborted jobs after a week, so
the per-minute sweep doesn't grow the job table (contract-phase3 section 3.9).

**Two pools in one process** (contract-phase6 section 3.3): the main pool
(:data:`MAIN_QUEUES`, ``SOUNDINGS_WORKER_CONCURRENCY`` jobs: email, notifications, the
schedules and the AI sweep) and the AI pool (the ``ai`` queue,
``SOUNDINGS_AI_MAX_CONCURRENT_RUNS`` jobs: ``run_ai``), so runs that take minutes never
hold up email. procrastinate's own signal handlers are off in both (two workers' handlers
would replace each other); one handler of ours stops both. The main pool keeps its
25-second grace; the AI pool doesn't wait: its jobs are cancelled at once and end their
runs ``worker_lost`` (after a best-effort ``tasks/cancel``) well inside Kubernetes'
30-second grace period.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

from procrastinate import App, PsycopgConnector
from procrastinate.worker import Worker
from psycopg_pool import AsyncConnectionPool

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

TASK_MODULES: list[str] = [
    "app.email.tasks",
    "app.ai.tasks",
]

SHUTDOWN_GRACE_SECONDS = 25
"""Finish within Kubernetes' default 30 s termination grace period."""
MAIN_QUEUES: Final = ("email", "notifications")
"""The main pool's queues: everything but ``ai`` (the AI pool's)."""
AI_QUEUES: Final = ("ai",)


def create_connector(settings: Settings, *, max_size: int) -> PsycopgConnector:
    """A procrastinate connector on the same database as SQLAlchemy."""
    return PsycopgConnector(
        conninfo=settings.database_dsn,
        min_size=1,
        max_size=max_size,
        kwargs={"application_name": "soundings-worker"},
    )


# Module-level so ``@procrastinate_app.task`` works at import time. No connection is
# made until the app is opened.
procrastinate_app = App(
    connector=create_connector(get_settings(), max_size=get_settings().worker_concurrency + 2),
    import_paths=TASK_MODULES,
)


@asynccontextmanager
async def open_job_queue(settings: Settings) -> AsyncIterator[App]:
    """Open procrastinate for *deferring* jobs from the API process.

    Uses a small, lazily-connecting pool so the API still starts (and reports
    not-ready) while the database is unavailable.
    """
    pool: AsyncConnectionPool = AsyncConnectionPool(
        settings.database_dsn,
        min_size=0,
        max_size=2,
        open=False,
        kwargs={"application_name": "soundings-api-jobs"},
        check=AsyncConnectionPool.check_connection,
        name="soundings-api-jobs",
    )
    await pool.open(wait=False)
    try:
        with procrastinate_app.replace_connector(PsycopgConnector()) as app:
            await app.open_async(pool)
            try:
                yield app
            finally:
                await app.close_async()
    finally:
        await pool.close()


def _context(runtime: Any, ai_runtime: Any | None) -> dict[str, Any]:
    from app.ai.runner import AiRuntime
    from app.ai.tasks import AI_RUNTIME_KEY
    from app.email.tasks import RUNTIME_KEY

    if ai_runtime is None:
        ai_runtime = AiRuntime(settings=runtime.settings, sessionmaker=runtime.sessionmaker)
    return {RUNTIME_KEY: runtime, AI_RUNTIME_KEY: ai_runtime}


def worker_options(
    *, concurrency: int, runtime: Any, ai_runtime: Any | None = None
) -> dict[str, Any]:
    """The main pool's ``run_worker_async`` options (also used by the tests, which pick
    their ``queues``; :func:`run_worker` gives :data:`MAIN_QUEUES`). ``ai_runtime``
    defaults to one on the email runtime's settings and sessions (the AI sweep runs
    here)."""
    return {
        "concurrency": concurrency,
        "name": "soundings-worker",
        "delete_jobs": "successful",
        "additional_context": _context(runtime, ai_runtime),
        "shutdown_graceful_timeout": SHUTDOWN_GRACE_SECONDS,
    }


def ai_worker_options(
    *, concurrency: int, runtime: Any, ai_runtime: Any | None = None
) -> dict[str, Any]:
    """The AI pool's options: the ``ai`` queue only, no grace on shutdown (its jobs end
    their runs ``worker_lost`` themselves when cancelled)."""
    return {
        "concurrency": concurrency,
        "name": "soundings-ai-worker",
        "queues": list(AI_QUEUES),
        "delete_jobs": "successful",
        "additional_context": _context(runtime, ai_runtime),
        "shutdown_graceful_timeout": 0,
    }


async def run_pools(*workers: Worker) -> None:
    """Run the workers until SIGINT/SIGTERM (or until one of them stops), then stop them
    all and wait for them: one signal handler for every pool, since procrastinate's own
    (``install_signal_handlers``) would replace each other."""
    loop = asyncio.get_running_loop()

    def stop_all() -> None:
        logger.info("worker stopping")
        for worker in workers:
            worker.stop()  # type: ignore[no-untyped-call]

    installed: list[signal.Signals] = []
    for number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(number, stop_all)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - not the main thread
            continue
        installed.append(number)
    runs = [worker.run() for worker in workers]  # type: ignore[no-untyped-call]
    tasks = [asyncio.create_task(run, name=f"pool-{n}") for n, run in enumerate(runs)]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        stop_all()
        await asyncio.gather(*tasks)
    finally:
        for number in installed:
            loop.remove_signal_handler(number)


async def run_worker(settings: Settings, *, concurrency: int | None = None) -> None:
    """Run the worker until SIGINT/SIGTERM: the main pool (the email sender, the outbox
    and AI sweeps, the notification schedule) and the AI pool (``run_ai``)."""
    from app.ai.runner import AiRuntime
    from app.db import create_engine, create_sessionmaker
    from app.email.delivery import Runtime

    concurrency = concurrency or settings.worker_concurrency
    ai_concurrency = settings.ai_max_concurrent_runs
    connector = create_connector(settings, max_size=concurrency + ai_concurrency + 4)
    engine = create_engine(settings, application_name="soundings-worker")
    try:
        with procrastinate_app.replace_connector(connector) as app:
            async with app.open_async():
                sessionmaker = create_sessionmaker(engine)
                runtime = Runtime(settings=settings, sessionmaker=sessionmaker, jobs=app)
                ai_runtime = AiRuntime(settings=settings, sessionmaker=sessionmaker)
                app.perform_import_paths()  # type: ignore[no-untyped-call]
                main = Worker(
                    app=app,
                    install_signal_handlers=False,
                    queues=list(MAIN_QUEUES),
                    **worker_options(
                        concurrency=concurrency, runtime=runtime, ai_runtime=ai_runtime
                    ),
                )
                ai = Worker(
                    app=app,
                    install_signal_handlers=False,
                    **ai_worker_options(
                        concurrency=ai_concurrency, runtime=runtime, ai_runtime=ai_runtime
                    ),
                )
                logger.info(
                    "worker started",
                    extra={
                        "concurrency": concurrency,
                        "ai_concurrency": ai_concurrency,
                        "email": settings.smtp_configured,
                        "ai": settings.ai_enabled,
                    },
                )
                await run_pools(main, ai)
    finally:
        await engine.dispose()
        logger.info("worker stopped")
