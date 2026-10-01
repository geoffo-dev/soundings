"""Demo data for development and demos: ``soundings seed [--reset] [--force]``.

Twelve people (``alice`` is the platform admin; alice, bob and carol have the
``employee_no`` external IDs of the dev Keycloak realm), three projects, five groups
mapped to the realm's groups and granted project roles, and 45 ideas in every status,
with owners, blind evaluations, comments and votes spread over the last few weeks.
Phase 4 adds branding (a global email footer; Customer Innovation's colours, font, logo
and favicon), Customer Innovation's public form, and three ideas sent through it (one
approved, two waiting for review). The content is in :mod:`app.seed.content` and
:mod:`app.seed.public`; :mod:`app.seed.runner` plays it through the application
services.
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
