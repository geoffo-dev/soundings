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
| `soundings api [--host --port --workers --reload]` | uvicorn with proxy headers trusted from `SOUNDINGS_TRUSTED_PROXIES` |
| `soundings worker [--concurrency N]` | procrastinate worker; stops gracefully on SIGTERM |
| `soundings migrate` | `alembic upgrade head` (app tables **and** procrastinate schema); idempotent |
| `soundings openapi [--output FILE]` | sorted, deterministic OpenAPI JSON (`make openapi OPENAPI_OUT=...`) |

Endpoints: `/api/v1/...` (REST), `/api/v1/openapi.json`, `/api/docs` (Swagger UI,
vendored assets), `/healthz` (liveness), `/readyz` (DB check), `/metrics`
(Prometheus). If `SOUNDINGS_STATIC_DIR` (default `../frontend/dist`) holds a
build, `/assets/*` is served immutable and every other unknown GET gets
`index.html`.

### Settings (`SOUNDINGS_*`)

`DATABASE_URL` (`postgresql://` or `postgresql+psycopg://`), `DATABASE_PASSWORD`
(optional, overrides the URL's password without URL-encoding), `DATABASE_POOL_SIZE`,
`BASE_URLS` (comma-separated external origins; first is the default), `SECRET_KEY`
(32+ chars, required in production), `DEV_LOGIN_ENABLED` (refused in production),
`ENVIRONMENT` (`development`/`test`/`production`), `STATIC_DIR`, `LOG_LEVEL`,
`TRUSTED_PROXIES` (IPs/CIDRs or `*`), `HOST`, `PORT`, `WORKERS`,
`WORKER_CONCURRENCY`, `OTEL_ENDPOINT` (OTLP/HTTP base URL; needs the `otel` extra).
See `app/config.py`.

## Test

```sh
make -C backend check    # ruff + mypy --strict + pytest
```

Tests start a `postgres:16-alpine` testcontainer (Docker required) once per
session and apply the migrations. Set `TEST_DATABASE_URL` to use an existing
**throwaway** database instead: every table is truncated after each test.
Fixtures (`tests/conftest.py`): `client` (httpx against the app), `app`,
`db_session`, `settings`; change settings with `@pytest.mark.settings(field=value)`
or by overriding the `settings_overrides` fixture in a module.

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
   in `migrations/versions/`, then `make -C backend migrate`.
3. `tests/test_migrations.py` fails if models and migrations drift or if there
   are multiple heads. Only the backend owner writes migrations.

procrastinate's tables are managed by Alembic too, from vendored SQL: see
`migrations/procrastinate/README.md` before upgrading procrastinate.

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
  `app/worker.py:TASK_MODULES`; defer from the API with `await task.defer_async(...)`.
- **Metrics**: `soundings_http_requests_total` / `soundings_http_request_duration_seconds`,
  labelled by route template. Run one uvicorn worker per pod (or set
  `PROMETHEUS_MULTIPROC_DIR`).
- **Security headers**: CSP (`script-src 'self'` plus hashes of `index.html`'s
  inline scripts, computed at startup), `nosniff`, `frame-ancestors 'none'`,
  `Referrer-Policy`, HSTS over HTTPS, `Cache-Control: no-store` on `/api/*`.
  Adjust in `app/middleware.py:content_security_policy`.
- **Swagger UI** assets are vendored in `app/static/swagger`
  (`make vendor-swagger SWAGGER_UI_VERSION=x.y.z` to refresh).
