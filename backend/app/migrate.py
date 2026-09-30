"""Run Alembic programmatically (used by ``soundings migrate`` and the tests).

Alembic owns the whole schema, including procrastinate's tables: see
``migrations/procrastinate/README.md``. The scripts live in ``backend/migrations``
next to this package, so the image must keep that layout.
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

from app.config import BACKEND_DIR

MIGRATIONS_DIR = BACKEND_DIR / "migrations"


def alembic_config(database_url: URL | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if database_url is not None:
        # Passed as an attribute, not an ini option, so '%' in passwords is safe.
        config.attributes["database_url"] = database_url
    return config


def upgrade_database(database_url: URL, revision: str = "head") -> None:
    """Apply migrations up to ``revision``. Idempotent; safe to run on every deploy."""
    command.upgrade(alembic_config(database_url), revision)
