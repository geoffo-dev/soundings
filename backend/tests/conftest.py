"""Shared fixtures.

* ``database_url`` (session): a migrated, disposable Postgres. Uses
  ``TEST_DATABASE_URL`` if set (the database is wiped between tests!), otherwise a
  ``postgres:16-alpine`` testcontainer.
* ``settings``: hermetic ``Settings`` (ignores ``SOUNDINGS_*`` env vars). Override
  per test with ``@pytest.mark.settings(field=value)`` or per module by
  redefining the ``settings_overrides`` fixture.
* ``app`` / ``client``: a fresh app (lifespan running) and an ``httpx.AsyncClient``
  bound to it via ASGITransport.
* After every test that used the database, all tables except ``alembic_version``
  are truncated.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from psycopg import sql
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.main import create_app
from app.migrate import upgrade_database

POSTGRES_IMAGE = "postgres:16-alpine"
CONTAINER_PREFIX = os.environ.get("SOUNDINGS_TEST_CONTAINER_PREFIX", "soundings-test-")
PRESERVED_TABLES = ("alembic_version",)


class HermeticSettings(Settings):
    """Settings built only from explicit arguments, never from the environment."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def make_settings(**overrides: Any) -> Settings:
    return HermeticSettings(**overrides)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """SQLAlchemy URL of a migrated test database (shared by the whole session)."""
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        yield _migrate(external)
        return

    # Ryuk (testcontainers' reaper) 0.11 is the version pre-pulled in dev/CI images.
    os.environ.setdefault("RYUK_CONTAINER_IMAGE", "testcontainers/ryuk:0.11.0")
    from testcontainers.community.postgres import PostgresContainer

    container = (
        PostgresContainer(POSTGRES_IMAGE, driver="psycopg")
        .with_name(f"{CONTAINER_PREFIX}pg-{uuid.uuid4().hex[:8]}")
        # Durability is irrelevant for tests; this makes TRUNCATE/DDL much faster.
        .with_command("postgres -c fsync=off -c synchronous_commit=off -c full_page_writes=off")
    )
    with container:
        yield _migrate(container.get_connection_url())


def _migrate(url: str) -> str:
    settings = make_settings(database_url=url)
    upgrade_database(settings.sqlalchemy_url)
    return settings.database_url


@pytest.fixture(scope="session")
def truncate_tables(database_url: str) -> Iterator[Callable[[], None]]:
    """Callable that empties every table except ``alembic_version``."""
    dsn = make_settings(database_url=database_url).database_dsn
    with psycopg.connect(dsn, autocommit=True) as connection:
        rows = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
            " AND tablename <> ALL(%s) ORDER BY tablename",
            [list(PRESERVED_TABLES)],
        ).fetchall()
        tables = [row[0] for row in rows]
        statement = sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
            sql.SQL(", ").join(sql.Identifier(table) for table in tables)
        )

        def truncate() -> None:
            if tables:
                connection.execute(statement)

        yield truncate


@pytest.fixture(autouse=True)
def _isolate_database(request: pytest.FixtureRequest) -> Iterator[None]:
    truncate: Callable[[], None] | None = None
    if "database_url" in request.fixturenames:
        truncate = request.getfixturevalue("truncate_tables")
    yield
    if truncate is not None:
        truncate()


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    """Redefine in a test module to change settings for all its tests."""
    return {}


@pytest.fixture
def settings(
    request: pytest.FixtureRequest,
    database_url: str,
    tmp_path: Path,
    settings_overrides: dict[str, Any],
) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": database_url,
        "static_dir": tmp_path / "no-frontend-build",
    }
    values.update(settings_overrides)
    marker = request.node.get_closest_marker("settings")
    if marker is not None:
        values.update(marker.kwargs)
    return make_settings(**values)


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


@pytest.fixture
async def db_session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    """A session on the test database for arranging/asserting data (commit explicitly)."""
    async with app.state.sessionmaker() as session:
        yield session
