"""Baseline: procrastinate job-queue schema (procrastinate 3.10.0).

No application tables yet. Creates procrastinate's tables, types and functions from
the SQL vendored at ``migrations/procrastinate/schema-3.10.0.sql``, which already
includes procrastinate's migrations up to ``03.04.00_50``.

Revision ID: 0001
Revises:
Create Date: 2026-09-30
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROCRASTINATE_SQL = Path(__file__).resolve().parents[1] / "procrastinate"


def run_sql_file(name: str) -> None:
    """Execute a multi-statement SQL file verbatim (no bind-parameter processing)."""
    sql = (PROCRASTINATE_SQL / name).read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def upgrade() -> None:
    run_sql_file("schema-3.10.0.sql")


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        """
        DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers,
            procrastinate_jobs, procrastinate_workers CASCADE;
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT p.oid::regprocedure AS signature FROM pg_proc p
                WHERE p.proname LIKE 'procrastinate\\_%'
                  AND p.pronamespace = current_schema()::regnamespace
            LOOP
                EXECUTE 'DROP ROUTINE IF EXISTS ' || r.signature || ' CASCADE';
            END LOOP;
        END $$;
        DROP TYPE IF EXISTS procrastinate_job_status, procrastinate_job_event_type,
            procrastinate_job_to_defer_v1 CASCADE;
        """,
        execution_options={"no_parameters": True},
    )
