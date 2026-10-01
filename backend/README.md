# Soundings backend

FastAPI + SQLAlchemy 2 (async, psycopg 3) + Alembic + procrastinate, managed with
`uv`. One image serves the REST API, the built SPA and (with another entrypoint)
the background worker.

## Run

```sh
make -C backend install                  # uv sync --locked
export SOUNDINGS_DATABASE_URL=postgresql://soundings:soundings@localhost:5432/soundings
make -C backend migrate                  # soundings migrate
make -C backend dev                      # API + SPA on http://localhost:8000 (PORT=...)
make -C backend worker                   # soundings worker
```

The `soundings` command (`uv run soundings --help`):

| Command | What it does |
|---|---|
| `soundings api [--host --port --workers --reload]` | uvicorn; the app believes `X-Forwarded-For`/`-Proto` only from `SOUNDINGS_TRUSTED_PROXIES`, and only the `SOUNDINGS_TRUSTED_PROXY_HOPS` entries they appended (`app/middleware.py`); also starts the metrics listener (below) |
| `soundings worker [--concurrency N]` | procrastinate worker: sends email from the outbox (pausing while the SMTP server is unreachable), the per-minute outbox sweep (also marks jobs of crashed workers failed), large notification fan-outs, the hourly reminder/digest/cleanup schedule, the daily job cleanup; periodic jobs run before waiting sends; stops gracefully on SIGTERM |
| `soundings migrate` | `alembic upgrade head` (app tables **and** procrastinate schema); idempotent. Reads only the database settings: no `SECRET_KEY` needed |
| `soundings wait-for-db [--timeout N]` | polls until Postgres answers `SELECT 1` (default 60 s); exit 1 on timeout. For init containers and scripts |
| `soundings openapi [--output FILE]` | sorted, deterministic OpenAPI JSON (`make openapi OPENAPI_OUT=...`) |
| `soundings email-preview -o DIR` | every email template rendered with sample data (`<template>.html`, `.txt`, `index.html`); no database, SMTP or settings needed |

Endpoints: `/api/v1/...` (REST), `/api/v1/openapi.json`, `/api/docs` (Swagger UI,
vendored assets), `/healthz` (liveness), `/readyz` (DB check). If
`SOUNDINGS_STATIC_DIR` (default `../frontend/dist`) holds a build, `/assets/*` is
served immutable and every other unknown GET gets `index.html`.

**Metrics** (Prometheus text) are served on their own port, `SOUNDINGS_METRICS_PORT`
(default `9090`, bound to `SOUNDINGS_HOST`, path `/metrics`), never on the public app
port in production. With `SOUNDINGS_METRICS_PORT=0` there is no separate listener
and, outside production only, `/metrics` is served on the app port; `--reload` does
this automatically (the reloader's child process serves the requests).

**Hosts:** requests whose `Host` is not one of `SOUNDINGS_BASE_URLS` (port ignored)
get `400 invalid_host`, so every public host must be listed; outside production
`localhost`, `127.0.0.1` and `::1` are accepted too. `/healthz` and `/readyz` are
exempt so probes addressing the pod IP work.

**Migrations** ship inside the package (`app/migrations/`), so an installed wheel
can migrate; `alembic` run from `backend/` uses the same directory
(`pyproject.toml` `[tool.alembic]`).

### Settings (`SOUNDINGS_*`)

`DATABASE_URL` (`postgresql://` or `postgresql+psycopg://`), `DATABASE_PASSWORD`
(optional, overrides the URL's password without URL-encoding), `DATABASE_POOL_SIZE`,
`BASE_URLS` (comma-separated external origins; first is the default; also the
trusted hosts), `SECRET_KEY` (32+ chars, required in production for the API and
worker, not for `migrate`/`wait-for-db`), `DEV_LOGIN_ENABLED` (refused in
production), `ENVIRONMENT` (`development`/`test`/`production`), `STATIC_DIR`,
`LOG_LEVEL`, `TRUSTED_PROXIES` (IPs/CIDRs or `*`), `TRUSTED_PROXY_HOPS` (default 1:
how many of them append to `X-Forwarded-For`), `HOST`, `PORT`, `WORKERS`,
`METRICS_PORT` (default 9090; 0 = none), `WORKER_CONCURRENCY`, `OTEL_ENDPOINT`
(OTLP/HTTP base URL; needs the `otel` extra), `SESSION_IDLE_TIMEOUT` (default 12
hours) and `SESSION_MAX_AGE` (default 24 hours; seconds or ISO 8601 such as `PT8H`),
`COOKIE_SECURE` (default: `Secure` except on plain-http requests outside
production; `false` is refused in production). Email (contract-phase3 §3.1):
`SMTP_HOST` (unset: in-app notifications only), `SMTP_PORT` (default 465 with `tls`,
else 587), `SMTP_SECURITY` (`none`/`starttls`/`tls`), `SMTP_USERNAME`,
`SMTP_PASSWORD`, `SMTP_FROM` (required with the host), `SMTP_FROM_NAME`,
`SMTP_REPLY_TO`, `SMTP_CA_BUNDLE` (PEM path), `SMTP_TIMEOUT` (default 10 s),
`TIMEZONE` (default UTC), `DIGEST_HOUR` (default 8), `REMINDER_DAYS` (default `2,0`).
See `app/config.py`.

## Sign-in and authorisation

* **Sessions** (ADR 0005, `app/auth/`, `app/services/sessions.py`): sign-in (dev
  login now, OIDC in Phase 2) stores a `user_sessions` row with the SHA-256 of a
  random token and sets `soundings_session` (HttpOnly, SameSite=Lax) plus the
  readable `soundings_csrf`. Unsafe methods on cookie-authenticated requests must
  send `X-CSRF-Token` (compared in constant time with the session's token) or get
  `403 csrf_failed`. Sign-in rotates the session; sessions end after the idle
  timeout or the absolute maximum; `last_seen_at` is written at most once a minute;
  logout deletes the row and clears both cookies.
* **Principals:** `app/auth/sources.py` tries each principal source in order
  (session cookie now; Phase 5 adds API keys first). Routes take `PrincipalDep`.
* **Authorisation** is only in `app/authz/` (ADR 0010), rules named as in
  `docs/role-matrix.md`:

  ```python
  project, resource = await load_project(db, principal, slug, Rule.PROJECT_EDIT_RUBRIC)
  resource = await idea_resource(db, principal, idea, project)
  require(principal, Rule.IDEA_CHANGE_STATUS, resource)  # raises 404/403/409...
  require_any(principal, (Rule.IDEA_EDIT_OWN, Rule.IDEA_EDIT_ANY), resource)
  can(principal, Rule.SCORE_VIEW_AGGREGATE, resource)  # False when blind
  select(Idea).where(viewable_ideas(principal))  # lists filter in SQL
  visible_aggregate_score(principal)  # masked score column
  ```

  Conditions that depend on the request go into `Resource`: `assignee_roles`
  (c4, from `effective_roles_of`), `evaluator_to_remove` (c16), `admins_after_change`
  (c11, from `admin_count` after flushing the change), `comment_author_id` (c2).
  `idea_permissions()` / `project_permissions()` build the `permissions` objects.

## Services

Routers stay thin: parse, authorise (`app.authz`), call a service in
`app/services/`, return a schema. Services take the request's `AsyncSession` and the
`Principal`, never check roles themselves, and record side effects in the same
transaction: `activity.emit(db, idea, type, actor=principal, payload=...)` (inserts
the feed event, bumps `last_activity_at`; payload keys are checked per type, so no
scores), `audit.record(db, action, actor=principal, ...)` (ids only, no PII), and
`scoring.recompute_aggregates(db, idea_ids=[...])` after evaluation or rubric
changes (raw SQL: refresh loaded `Idea`s afterwards). `refs.idea_ref()` /
`project_ref()` build the shared reference shapes.

Admin settings and access (contract-phase2 sections 3.4, 3.7, 3.10, 3.11):
`admin_users` (pre-create, external IDs, c17/c18, deactivate = end sessions),
`admin_groups` (groups, mapping, manual members under sign-in sync's user-row lock;
counts are active users only), `project_groups` (group grants with c11, everyone with
access and why) and `audit_viewer` (keyset newest first, references resolved per
page). Every admin write is audited with `rule` and the session's `auth_method`; the
closed set of actions is `app.schemas.audit.AuditAction`. The mapping test reuses
`app.auth.group_mapping.preview_group_mapping` (identity), so it runs the sign-in code.

## Test

```sh
make -C backend check    # ruff + mypy --strict + pytest
```

Tests start a `postgres:16-alpine` testcontainer (Docker required; its name starts
with `SOUNDINGS_TEST_CONTAINER_PREFIX`) once per session and apply the migrations.
Set `TEST_DATABASE_URL` to use an existing **throwaway** database instead: every
table is truncated after each test.
Fixtures (`tests/conftest.py`): `client` (httpx against the app, not signed in),
`login` (`await login(user)` returns a client signed in through the dev login, with
the CSRF header set), `app`, `db_session`, `settings`; change settings with
`@pytest.mark.settings(field=value)` or by overriding the `settings_overrides`
fixture in a module. `tests/factories.py` builds users, projects, members, ideas,
evaluators and evaluations. Authorisation tests live in `tests/authz/` (the role
matrix row by row, blind evaluation, SQL filters vs the policy), sessions in
`tests/auth/`, endpoint tests in `tests/api/`.

## Add a router

1. `app/api/v1/<area>.py`: `router = APIRouter(prefix="/<area>", tags=["<area>"])`.
2. Register it in `app/api/v1/__init__.py`: `api_router.include_router(<area>.router)`.
3. Request/response models go in `app/schemas/`; take a DB session with
   `session: SessionDep` (commits after the endpoint returns, rolls back if it raises).
4. Endpoint function names become OpenAPI operationIds: keep them unique.

## Add a migration

1. Add/modify models in `app/models/` (inherit `Base`, `UUIDPrimaryKeyMixin`,
   `TimestampMixin`) and import them in `app/models/__init__.py`.
2. `make -C backend revision m="add ideas"` (runs autogenerate), review the file
   in `app/migrations/versions/`, then `make -C backend migrate`.
3. `tests/test_migrations.py` fails if models and migrations drift or if there
   are multiple heads. Only the backend owner writes migrations.

procrastinate's tables are managed by Alembic too, from vendored SQL: see
`app/migrations/procrastinate/README.md` before upgrading procrastinate.

## Conventions

- **Errors** are RFC 9457 `application/problem+json` with `type`, `title`,
  `status`, `detail`, `instance`, a stable snake_case `code` and `request_id`.
  Raise `app.errors.ProblemError(status, code, detail=...)` (or `NotFoundProblem`,
  `ConflictProblem`, `NotImplementedProblem`); never return error dicts by hand.
  500s never include exception text.
- **Pagination** is cursor-based: `PageParamsDep` (`?cursor=&limit=`), fetch
  `limit + 1` rows with a keyset `WHERE`, `slice_page()`, return `Page[T]`
  (`items`, `next_cursor`). See `app/pagination.py`.
- **JSON** is snake_case; datetimes are timezone-aware UTC.
- **Logs** are JSON on stdout with `request_id`. Never log emails, names,
  tokens, cookies, headers, query strings, raw paths or bodies; log ids and
  route templates. Keep secrets and PII out of URLs (they reach traces and
  proxy logs).
- **Background jobs**: `@procrastinate_app.task` in a module listed in
  `app/worker.py:TASK_MODULES`; defer from the API with `await task.defer_async(...)`,
  on the request's connection when it must commit with the request
  (`app/email/outbox.py:defer_send`).
- **Notifications and email**: services call `app.services.activity.emit`; the
  before-commit hook in `app/db.py` runs the fan-out (`app/notifications/fanout.py`)
  once per transaction. Outside requests open sessions with `session_scope(...,
  settings=settings)`, or notifications are recorded with email off. Emails are
  rendered at send time (`app/email/`, templates in `app/templates/email/`) and never
  contain score data.
- **Metrics**: `soundings_http_requests_total` / `soundings_http_request_duration_seconds`,
  labelled by route template, on the metrics port (above). Run one uvicorn worker per
  pod (or set `PROMETHEUS_MULTIPROC_DIR`). The worker counts
  `soundings_emails_sent_total`, `soundings_email_attempts_failed_total`,
  `soundings_emails_cancelled_total` and `soundings_emails_queued` (not served on a
  port yet).
- **Security headers**: CSP (`script-src 'self'` plus hashes of `index.html`'s
  inline scripts, computed at startup), `nosniff`, `frame-ancestors 'none'`,
  `Referrer-Policy`, HSTS over HTTPS, `Cache-Control: no-store` on `/api/*`.
  Adjust in `app/middleware.py:content_security_policy`.
- **Swagger UI** assets are vendored in `app/static/swagger`
  (`make vendor-swagger SWAGGER_UI_VERSION=x.y.z` to refresh).
