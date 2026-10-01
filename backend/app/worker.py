"""Background jobs with procrastinate (Postgres-backed; no Redis).

Tasks are defined in the modules listed in :data:`TASK_MODULES` (``app.email.tasks``:
``send_email``, ``sweep_outbox``, ``notification_schedule``, ``remove_old_jobs``).
Request code defers jobs **on the request's own connection**, atomically with its
writes (``app.email.outbox.defer_send``); the API process also opens a small
job-queue pool in its lifespan. The worker runs with ``soundings worker``; the
procrastinate schema is created by ``soundings migrate`` (see
app/migrations/procrastinate/README.md).

Finished jobs are deleted as they complete (``delete_jobs="successful"``) and the
daily ``remove_old_jobs`` clears failed, cancelled and aborted jobs after a week, so
the per-minute sweep doesn't grow the job table (contract-phase3 section 3.9).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from procrastinate import App, PsycopgConnector
from psycopg_pool import AsyncConnectionPool

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

TASK_MODULES: list[str] = [
    "app.email.tasks",
]

SHUTDOWN_GRACE_SECONDS = 25
"""Finish within Kubernetes' default 30 s termination grace period."""


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


def worker_options(*, concurrency: int, runtime: Any) -> dict[str, Any]:
    """``run_worker_async`` options (also used by the tests)."""
    from app.email.tasks import RUNTIME_KEY

    return {
        "concurrency": concurrency,
        "name": "soundings-worker",
        "delete_jobs": "successful",
        "additional_context": {RUNTIME_KEY: runtime},
        "shutdown_graceful_timeout": SHUTDOWN_GRACE_SECONDS,
    }


async def run_worker(settings: Settings, *, concurrency: int | None = None) -> None:
    """Run the worker until SIGINT/SIGTERM (graceful shutdown built in): the email
    sender, the outbox sweep and the notification schedule."""
    from app.db import create_engine, create_sessionmaker
    from app.email.delivery import Runtime

    concurrency = concurrency or settings.worker_concurrency
    connector = create_connector(settings, max_size=concurrency + 2)
    engine = create_engine(settings, application_name="soundings-worker")
    try:
        with procrastinate_app.replace_connector(connector) as app:
            async with app.open_async():
                runtime = Runtime(
                    settings=settings, sessionmaker=create_sessionmaker(engine), jobs=app
                )
                logger.info(
                    "worker started",
                    extra={"concurrency": concurrency, "email": settings.smtp_configured},
                )
                await app.run_worker_async(
                    **worker_options(concurrency=concurrency, runtime=runtime)
                )
    finally:
        await engine.dispose()
        logger.info("worker stopped")
