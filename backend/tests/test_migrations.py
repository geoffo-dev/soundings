from __future__ import annotations

from pathlib import Path

import procrastinate
from alembic import command
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.migrate import MIGRATIONS_DIR, alembic_config
from tests.conftest import make_settings

# The newest procrastinate migration already included in our vendored schema/revisions.
PROCRASTINATE_APPLIED_UP_TO = "03.04.00_50_post_add_retry_failed_job_procedure.sql"


def test_migrations_have_a_single_head() -> None:
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()

    assert len(heads) == 1, f"multiple Alembic heads, merge them: {heads}"


def test_models_match_migrations(database_url: str) -> None:
    """Fails when a model changed without an Alembic revision (`alembic check`)."""
    config = alembic_config(make_settings(database_url=database_url).sqlalchemy_url)

    command.check(config)


def test_procrastinate_upgrade_has_matching_migrations() -> None:
    """Fails when procrastinate is upgraded but its new SQL migrations are not vendored.

    See app/migrations/procrastinate/README.md for how to add them.
    """
    shipped = Path(procrastinate.__file__).parent / "sql" / "migrations"
    newer = sorted(p.name for p in shipped.glob("*.sql") if p.name > PROCRASTINATE_APPLIED_UP_TO)
    vendored = {p.name for p in (MIGRATIONS_DIR / "procrastinate").glob("*.sql")}

    missing = [name for name in newer if name not in vendored]
    assert not missing, f"vendor these procrastinate migrations and add a revision: {missing}"


async def test_api_can_defer_jobs(app: FastAPI, db_session: AsyncSession) -> None:
    job_queue: procrastinate.App = app.state.job_queue

    job_id = await job_queue.configure_task("tests.noop", allow_unknown=True).defer_async(n=1)

    status = await db_session.scalar(
        text("SELECT status::text FROM procrastinate_jobs WHERE id = :id"), {"id": job_id}
    )
    assert status == "todo"


async def test_database_is_clean_between_tests(db_session: AsyncSession) -> None:
    # Runs after test_api_can_defer_jobs: the job it created must be gone.
    count = await db_session.scalar(text("SELECT count(*) FROM procrastinate_jobs"))

    assert count == 0
