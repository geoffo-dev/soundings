"""Run Alembic programmatically (used by ``soundings migrate`` and the tests).

Alembic owns the whole schema, including procrastinate's tables: see
``app/migrations/procrastinate/README.md``. The scripts ship inside the ``app``
package (``app/migrations``), so an installed wheel migrates without the source tree;
``alembic`` run from ``backend/`` uses the same directory (``pyproject.toml``).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

logger = logging.getLogger(__name__)


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


def wait_for_database(dsn: str, *, timeout: float, interval: float = 1.0) -> bool:
    """Poll until the database accepts a connection and answers ``SELECT 1``.

    Returns ``False`` once ``timeout`` seconds have passed without success. Logs the
    error type only (connection errors can contain the host and user name).
    """
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        remaining = deadline - time.monotonic()
        try:
            with psycopg.connect(dsn, connect_timeout=max(1, min(5, int(remaining)))) as conn:
                conn.execute("SELECT 1")
        except psycopg.Error as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.error(
                    "database not reachable",
                    extra={"attempts": attempt, "error_type": type(exc).__name__},
                )
                return False
            logger.info(
                "waiting for the database",
                extra={"attempt": attempt, "error_type": type(exc).__name__},
            )
            time.sleep(min(interval, remaining))
            continue
        logger.info("database is ready", extra={"attempts": attempt})
        return True
