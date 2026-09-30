# ADR 0002: FastAPI + SQLAlchemy 2 async + psycopg 3 + Alembic

- Status: Accepted · Date: 2026-09-30

## Context

SPEC section 4 fixes Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic
and `uv`, with PostgreSQL 16 as the only stateful dependency. It leaves the Postgres
driver open. SQLAlchemy's async mode supports asyncpg and psycopg 3. The job queue
(procrastinate, [ADR 0003](0003-background-jobs-procrastinate-and-email-outbox.md))
ships connectors for psycopg 3 and aiopg, not asyncpg. To defer a job atomically with
the row that caused it, both must share one connection and so one driver.

## Decision

- **psycopg 3** (`psycopg[binary,pool]`, async) is the only Postgres driver, used by
  SQLAlchemy (`postgresql+psycopg://`) and procrastinate (`PsycopgConnector`, plain
  libpq DSN). **No asyncpg** anywhere, including transitive extras (e.g. don't install
  `a2a-sdk[sql]`).
- **FastAPI + Pydantic v2** for the REST API at `/api/v1`, OpenAPI served from the app
  with vendored Swagger UI assets. JSON field names are snake_case.
- **SQLAlchemy 2** typed ORM (`Mapped[...]`), async sessions, one session per request.
  Enums are stored as `VARCHAR` + `CHECK`, not native Postgres enums, so adding a value
  is a plain migration.
- **Alembic** owns the schema, including the vendored procrastinate `schema.sql` applied
  once by a migration. `soundings migrate` runs `alembic upgrade head` and is
  idempotent. Only the backend owner writes migrations.
- Errors are RFC 9457 `application/problem+json` with a stable snake_case `code`.
  Lists use opaque cursor pagination (`items`, `next_cursor`).
- Tooling: `uv` with a committed lockfile, ruff, mypy `--strict`, pytest with
  testcontainers Postgres (no database mocks).

## Consequences

- One pool type and one set of connection settings for API, worker and migrations.
- `get_raw_connection().driver_connection` gives the `psycopg.AsyncConnection` needed
  for in-transaction job deferral (verified, see
  [research R1](../research/backend-libraries.md#2-procrastinate-3100-with-psycopg-3-and-sqlalchemy-async)).
- We give up asyncpg's raw speed; at our scale (10k ideas) it does not matter.
- Test fixtures use a session event-loop scope and `NullPool` to avoid cross-loop
  connection reuse.
