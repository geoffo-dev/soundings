"""Alembic environment (async, psycopg 3).

The database URL comes from ``config.attributes["database_url"]`` (set by
``app.migrate``) or else from the app settings (``SOUNDINGS_DATABASE_URL``).
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import URL, Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql.schema import SchemaItem

import app.models  # noqa: F401 - registers every model on Base.metadata
from app.config import get_settings
from app.models.base import Base

config = context.config
target_metadata = Base.metadata

# Serialises concurrent `soundings migrate` runs (e.g. two Helm hooks racing).
MIGRATION_LOCK_ID = 7_302_019_411


def _database_url() -> URL:
    url = config.attributes.get("database_url")
    return url if isinstance(url, URL) else get_settings().sqlalchemy_url


def include_name(name: str | None, type_: str, _parent_names: object) -> bool:
    """Keep autogenerate away from tables owned by procrastinate (managed via SQL files)."""
    return not (type_ == "table" and name is not None and name.startswith("procrastinate_"))


def include_object(
    _obj: SchemaItem, name: str | None, type_: str, _reflected: bool, _compare_to: object
) -> bool:
    return include_name(name, type_, None)


def _configure(**kwargs: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_name=include_name,
        include_object=include_object,
        **kwargs,  # type: ignore[arg-type]
    )


def run_migrations_offline() -> None:
    _configure(
        url=_database_url().render_as_string(hide_password=True),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MIGRATION_LOCK_ID})
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
