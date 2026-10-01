"""Demo data for development and demos: ``soundings seed [--reset] [--force]``.

Twelve people (``alice`` is the platform admin), three projects and 45 ideas in every
status, with owners, blind evaluations, comments and votes spread over the last few
weeks. The content is in :mod:`app.seed.content`; :mod:`app.seed.runner` plays it
through the application services.
"""

from __future__ import annotations

from app.config import DatabaseSettings
from app.db import create_sessionmaker, session_scope
from app.seed.runner import (
    SeedRefused,
    SeedReport,
    check_allowed,
    check_reset_allowed,
    seed_demo_data,
    wipe_app_data,
)

__all__ = [
    "SeedRefused",
    "SeedReport",
    "check_allowed",
    "check_reset_allowed",
    "run_seed",
    "seed_demo_data",
    "wipe_app_data",
]


async def run_seed(
    settings: DatabaseSettings, *, reset: bool = False, force: bool = False
) -> SeedReport:
    """Seed the configured database in one transaction (``soundings seed``); raises
    :class:`SeedRefused` for a ``reset`` that :func:`check_reset_allowed` refuses."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        settings.sqlalchemy_url, connect_args={"application_name": "soundings-seed"}
    )
    try:
        async with session_scope(create_sessionmaker(engine)) as db:
            return await seed_demo_data(db, reset=reset, force=force)
    finally:
        await engine.dispose()
