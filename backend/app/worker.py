"""Background jobs with procrastinate (Postgres-backed; no Redis).

Define tasks in feature modules and list those modules in :data:`TASK_MODULES`::

    # app/email/tasks.py
    from app.worker import procrastinate_app

    @procrastinate_app.task(name="send_email", queue="email", retry=5)
    async def send_email(email_id: str) -> None: ...

Defer from API code with ``await send_email.defer_async(email_id=str(email.id))``
(the API process opens a small job-queue pool in its lifespan). The worker runs
with ``soundings worker``; the procrastinate schema is created by ``soundings
migrate`` (see app/migrations/procrastinate/README.md).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from procrastinate import App, PsycopgConnector
from psycopg_pool import AsyncConnectionPool

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

TASK_MODULES: list[str] = [
    # Modules that define @procrastinate_app.task functions, e.g. "app.email.tasks".
]


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


async def run_worker(settings: Settings, *, concurrency: int | None = None) -> None:
    """Run the worker until SIGINT/SIGTERM (graceful shutdown built in)."""
    concurrency = concurrency or settings.worker_concurrency
    connector = create_connector(settings, max_size=concurrency + 2)
    with procrastinate_app.replace_connector(connector) as app:
        async with app.open_async():
            logger.info("worker started", extra={"concurrency": concurrency})
            await app.run_worker_async(
                concurrency=concurrency,
                name="soundings-worker",
                # Finish within Kubernetes' default 30s termination grace period.
                shutdown_graceful_timeout=25,
            )
