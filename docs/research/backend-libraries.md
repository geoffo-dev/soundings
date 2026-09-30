# Research R1: backend library facts (verified 2026-09-30)

> Phase 0 research by a researcher subagent, lightly edited by the lead. Everything
> here was run, not just read, unless it says **Not verified**. Re-check versions
> before relying on them in a later phase; ADRs 0002, 0003 and 0005 build on this.

All seven topics were tested in a scratch project outside the repo. Topics 1, 2, 3, 5,
6 and 7 were verified end to end. Topic 4 (WeasyPrint) ran on the host only: the Debian
apt mirror is blocked in the build environment, so the Pango libraries could not be
installed in a `python:3.12-slim` container. Topic 1 has one behaviour change that
affects our code: `mcp` 2.x renamed `FastMCP`.

Versions (PyPI latest, checked 2026-09-30; installed together in a Python 3.12 venv):

| Library | Version | Library | Version |
|---|---|---|---|
| mcp | 2.2.0 | testcontainers | 4.15.0 |
| procrastinate | 3.10.0 | altcha (PyPI) | 2.1.0 |
| authlib | 1.8.0 (now uses joserfc) | altcha widget (npm) | 3.2.4 |
| weasyprint | 70.0 | psycopg | 3.3.6 |
| aiosmtplib | 5.1.3 | sqlalchemy | 2.1.1 |
| fastapi | 0.142.2 | starlette | 1.7.0 |
| pytest-asyncio | 1.4.0 | | |

---

## 1. mcp 2.2.0: MCP server over streamable HTTP, stateless, inside FastAPI

**Breaking changes in v2**

- **Renames:**
  - `from mcp.server.fastmcp import FastMCP` now raises `ModuleNotFoundError`. Use
    `from mcp.server.mcpserver import MCPServer, Context`.
  - The client function `streamablehttp_client` is now
    `streamable_http_client(url, http_client=httpx2.AsyncClient(...))`. It no longer
    takes `headers=`; put the headers on the client. The SDK uses **httpx2**, not httpx.
- **Transport settings moved:** `stateless_http`, `json_response`, `host`, the path and
  `transport_security` now go to `streamable_http_app()` or `run()`, not the constructor.

**Verified results**

- A valid key calls tools and returns the principal. A key without the `mcp` scope gets
  403 `insufficient_scope`. A wrong or missing key gets 401 with
  `WWW-Authenticate: Bearer`.
- Both ways of reading the principal work inside a tool.
- The v2 `Client`, the v2 `ClientSession`, the **mcp 1.30 client** (it negotiated
  protocol 2025-11-25) and raw curl JSON-RPC all work.

```python
import contextlib, hashlib
from fastapi import FastAPI
from starlette.requests import Request
from mcp.server.mcpserver import MCPServer, Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.transport_security import TransportSecuritySettings

class ApiKeyVerifier:                       # satisfies the TokenVerifier Protocol
    async def verify_token(self, token: str) -> AccessToken | None:
        row = await lookup_key(hashlib.sha256(token.encode()).hexdigest())  # our DB lookup
        if row is None: return None          # -> 401
        return AccessToken(token=token, client_id=str(row.key_id), subject=str(row.user_id),
                           scopes=row.scopes, expires_at=row.expires_epoch)  # the SDK enforces expires_at

mcp = MCPServer("soundings", token_verifier=ApiKeyVerifier(),
    auth=AuthSettings(issuer_url="https://soundings.example",  # required field, unused here
                      resource_server_url=None,                 # None: no PRM route, no warning
                      required_scopes=["mcp"]))                 # else 403 insufficient_scope

@mcp.tool()
async def get_idea(idea_id: int, ctx: Context) -> dict:
    tok = get_access_token()                       # contextvar: tok.subject = user id, tok.client_id = key id
    req = ctx.request_context.request              # starlette Request (IP/headers for the audit log)
    assert isinstance(req, Request)                # also req.scope["user"].access_token
    raise ToolError("Idea not found")              # message reaches the client; other exceptions become a generic "Error executing tool x"

mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))  # or allowed_hosts=[...]
manager = mcp.session_manager                       # exists only after streamable_http_app()

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with manager.run():                       # REQUIRED: a mounted sub-app's lifespan never runs
        yield
app = FastAPI(lifespan=lifespan)
app.add_route("/mcp", mcp_app, methods=["POST"], include_in_schema=False)
```

**Gotchas (all verified)**

- **Mounting:** `app.mount("/mcp", mcp.streamable_http_app(streamable_http_path="/"))`
  answers `POST /mcp` with a **307 redirect to `/mcp/`**, which breaks POST clients
  behind TLS ingress. Use the exact-path `add_route` above, where the inner path is
  also `/mcp`.
- **Missing lifespan:** without `session_manager.run()`, every request fails with
  "Task group is not initialized".
- **`run()` works only once per manager instance.** A second lifespan on the same app
  raises `RuntimeError`. Build the app in a `create_app()` factory that calls
  `streamable_http_app()` each time (verified with two pytest runs).
- **DNS-rebinding default:** `streamable_http_app()` defaults to `host="127.0.0.1"`,
  which turns DNS-rebinding protection on with a localhost-only allow-list. Real
  hostnames then get 421. Pass `transport_security` explicitly.
- **GET holds connections:** in stateless mode, `GET /mcp` opens an SSE stream that
  stays open forever. Allowing only POST returns 405, and both SDK clients handle that.
- **No server-to-client messages:** stateless or JSON mode has no back-channel, so
  sampling, elicitation and progress raise `NoBackChannelError`.
- **In-process tests skip auth:** with `Client(mcp)` in memory, `get_access_token()`
  returns `None`. To test auth, use `httpx2.AsyncClient(transport=httpx2.ASGITransport(app))`
  inside `app.router.lifespan_context(app)` and pass it as `http_client=`. Pydantic
  argument-validation errors are returned to the client as `isError` text.
- **Client usage:** `Client(streamable_http_client(url, http_client=http))` takes the
  transport **before** it is entered. Passing the entered tuple fails.

**Not verified:** kagent's own MCP client (only the SDK v1 and v2 clients were tested).

## 2. procrastinate 3.10.0 with psycopg 3 and SQLAlchemy async

**Atomic defer on the SQLAlchemy connection: yes, verified.** The job is committed
together with the app row, and a rollback removes both. The API process does **not**
need `app.open_async()` for this.

```python
import procrastinate
from procrastinate import RetryStrategy, JobContext

app = procrastinate.App(connector=procrastinate.PsycopgConnector(
          conninfo="postgresql://u:p@h/db", min_size=1, max_size=4),  # libpq DSN, NOT "postgresql+psycopg://"
      import_paths=["app.worker.tasks"])
# Convert an SQLAlchemy URL: make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)

@app.task(name="send_email", queue="email", pass_context=True,
          retry=RetryStrategy(max_attempts=8, exponential_wait=2, retry_exceptions={ConnectionError, TimeoutError}))
async def send_email(context: JobContext, outbox_id: int) -> None: ...   # context.job.attempts

@app.periodic(cron="*/5 * * * *", periodic_id="sweep")   # optional 6th field = seconds
@app.task(name="sweep_outbox", queue="email", queueing_lock="sweep_outbox")
async def sweep_outbox(timestamp: int) -> None: ...     # periodic tasks receive `timestamp`

# In a request handler, inside the app's transaction:
async with Session() as s, s.begin():
    row = OutboundEmail(...); s.add(row); await s.flush()
    pg = (await (await s.connection()).get_raw_connection()).driver_connection   # psycopg.AsyncConnection
    await send_email.configure(connection=pg).defer_async(outbox_id=row.id)
```

**Worker**

- CLI: `procrastinate --app=app.worker.app worker -q email -c 4`. `--one-shot` exits
  once the queue is empty; `procrastinate --app=... healthchecks` also works.
- Programmatic: `async with app.open_async(): await app.run_worker_async(queues=["email"], concurrency=4)`.
  `wait=False` drains the queue and returns (useful in tests);
  `install_signal_handlers=False` lets you embed it in another program.
- Useful options: `delete_jobs="successful"` and `shutdown_graceful_timeout`.

**Retry and periodic behaviour**

- The wait formula is `wait + linear_wait*attempts + exponential_wait**(attempts+1)`
  seconds, so `exponential_wait=2` gives 2, 4, 8, 16… There is **no cap and no
  jitter**. For a cap, subclass `BaseRetryStrategy.get_retry_decision(exception=, job=)`
  and return `RetryDecision(retry_in={"seconds": n})` or `None`.
- Verified: a job failed twice, then succeeded with `attempts=3`.
- Every worker runs the periodic deferrer. Duplicates are prevented by
  `UNIQUE(task_name, periodic_id, defer_timestamp)`; periodic dispatch was verified
  with a single worker only.

**Schema and Alembic**

- `schema.sql` is **not idempotent**: a second `schema --apply` fails with "type
  procrastinate_job_status already exists". procrastinate keeps no migration log.
- The repo's approach is correct. `backend/app/migrations/procrastinate/schema-3.10.0.sql`
  is **byte-identical** to the 3.10.0 package's `schema.sql`, and
  `exec_driver_sql(sql, execution_options={"no_parameters": True})` applied it cleanly
  through SQLAlchemy and psycopg; the `%` characters in `RAISE` are safe.
- The newest bundled migration is `03.04.00_50_post_…`; 3.5 to 3.10 made no schema
  changes.

**Recommended outbox pattern** (adopted in [ADR 0003](../adr/0003-background-jobs-procrastinate-and-email-outbox.md))

- `outbound_email` holds the truth: status, attempts, `next_attempt_at`, `last_error`.
- Insert the row and defer `send_email(outbox_id)` on the same connection.
- The task locks the row (`SELECT … FOR UPDATE`), sends only if it is still pending,
  and records the result. The `Message-ID` is fixed once at insert.
- A periodic `sweep_outbox` re-defers stale pending rows as a safety net. The admin
  "retry" button resets the row and defers a new job.
- **Do not** combine `queueing_lock` with an in-transaction defer (not run; follows
  from Postgres rules). A lock conflict raises a unique violation, which aborts the
  whole app transaction unless it is wrapped in `s.begin_nested()`.

**For tests:** `procrastinate.testing.InMemoryConnector` with `app.replace_connector(...)`.

## 3. Authlib 1.8.0 OIDC with Starlette/FastAPI (verified against Keycloak 26.0)

**Verified results**

- The authorize URL carries `code_challenge_method=S256`, `nonce` and `state`.
- Login worked on both hosts, `127.0.0.1` and `localhost`.
- Claims were validated, and `groups` came through as `['/innovation/leads']`.
- Replaying the callback fails with `mismatching_state` (400).
- Logout redirected to Keycloak's end-session endpoint, which bounced back to
  `post_logout_redirect_uri?state=…`.
- A disallowed Host header gets 400.

```python
from authlib.integrations.starlette_client import OAuth, OAuthError
from starlette.middleware.sessions import SessionMiddleware   # needs `itsdangerous` (not in backend deps yet)

class DbStateCache:   # async get(key) / set(key, value, expires) / delete(key); in prod a DB table with expiry
    ...
oauth = OAuth(cache=DbStateCache())   # with a cache the cookie holds only {"exp":…}; nonce/code_verifier stay server-side
oauth.register("oidc", client_id=..., client_secret=...,
    server_metadata_url=f"{issuer}/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256", "timeout": 10})
    # custom CA: client_kwargs["verify"] = ssl.create_default_context(cafile=...)  (used for metadata, token and JWKS)

# Login-flow-only cookie: authlib needs request.session. This is NOT the app session.
app.add_middleware(SessionMiddleware, secret_key=..., session_cookie="soundings_oidc",
                   max_age=600, path="/api/v1/auth", same_site="lax", https_only=True)

def public_base(request):            # multi-host: derive from Host, check the allow-list
    host = request.headers.get("host", "")
    if host not in settings.public_hosts: raise HTTPException(400)
    return f"{request.url.scheme}://{host}"   # uvicorn --proxy-headers --forwarded-allow-ips=<ingress>

@app.get("/api/v1/auth/login")
async def login(request): return await oauth.oidc.authorize_redirect(request, public_base(request) + "/api/v1/auth/callback")

@app.get("/api/v1/auth/callback")
async def callback(request):
    token = await oauth.oidc.authorize_access_token(request)  # checks state, sends code_verifier, validates id_token
    claims = token["userinfo"]                                # validated ID-token claims
    ui = await oauth.oidc.userinfo(token=token)               # optional userinfo call
    # create a server-side session row (opaque random id in an HttpOnly cookie); keep id_token server-side for logout

@app.post("/api/v1/auth/logout")   # CSRF-protected
async def logout(request):
    resp = await oauth.oidc.logout_redirect(request, post_logout_redirect_uri=base + "/", id_token_hint=sess.id_token)
    resp.status_code = 303; ...
```

**ID-token checks.** `parse_id_token` validates the signature (JWKS, re-fetched when the
`kid` is unknown), `iss` (from the provider metadata), `aud` (the `client_id`),
`exp`/`iat` (default leeway 120 s), `nonce` and `at_hash`. Algorithms come from
`id_token_signing_alg_values_supported`.

**Gotchas**

- **Without `cache=`,** authlib stores `nonce`, `code_verifier` and `redirect_uri` in
  the signed but **readable** session cookie.
- **Metadata is cached forever** in the process.
- **`validate_logout_response`** only works if the post-logout URL is under the login
  cookie's path.
- **Every public host's callback URL** must be registered on the IdP client
  (`redirectUris`, `post.logout.redirect.uris`).
- **Stable issuer:** set Keycloak `KC_HOSTNAME` so the issuer is the same whether the
  browser or the backend fetches it.
- **Scripted Keycloak logins:** Keycloak sets `Secure` cookies even over
  `http://127.0.0.1`. Browsers accept them, but httpx will not resend them, which
  matters for any scripted login test.

**Not verified:** Entra ID and Google.

## 4. WeasyPrint 70.0

**Base image and system libraries**

- `python:3.12-slim` is **Debian 13 (trixie)** with Python 3.12.14. It ships none of
  glib, pango, harfbuzz or fontconfig, and has no `/usr/share/fonts`. Verified:
  `import weasyprint` fails there with `OSError: cannot load library 'libgobject-2.0-0'`.
- WeasyPrint `dlopen`s these (read from `weasyprint/text/ffi.py`):
  - required: gobject-2.0, pango-1.0, harfbuzz, fontconfig, pangoft2-1.0
  - optional: harfbuzz-subset (a DeprecationWarning, plus slower fontTools subsetting,
    if missing)
  - optional: harfbuzz-vector (not in trixie)
- The Dockerfile's list `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b
  libharfbuzz-subset0 libfontconfig1` matches that list. glib comes in as a dependency,
  as `libglib2.0-0t64` on trixie.
- **Not verified in a container:** `deb.debian.org`, `packages.debian.org` and
  `sources.debian.org` all return 403 through the build environment's egress proxy. The
  package names were checked against Ubuntu 24.04, which went through the same t64
  rename.
- **Import lazily:** do `import weasyprint` inside the export function so the API still
  starts if the libraries are missing.

**Bundled fonts and a local-only fetcher.** Verified: Inter woff2 files from npm
`@fontsource/inter` 5.3.0 are embedded and subset as `Inter`, `Inter-Semi-Bold` and
`Inter-Bold`. An `https` stylesheet, a `169.254.169.254` image and `file:///etc/passwd`
were all blocked, and the PDF still rendered.

```python
from pathlib import Path; from urllib.parse import urlsplit; from urllib.request import url2pathname
from weasyprint import CSS, HTML
from weasyprint.text.fonts import FontConfiguration
from weasyprint.urls import URLFetcher

class LocalOnlyFetcher(URLFetcher):      # v70 API: subclass URLFetcher; fetch() must return URLFetcherResponse
    def __init__(self, root: Path):
        super().__init__(allowed_protocols={"file", "data"}, allow_redirects=False, timeout=2)
        self.root = root.resolve()
    def fetch(self, url, headers=None):
        p = urlsplit(url)
        if p.scheme == "file" and not Path(url2pathname(p.path)).resolve().is_relative_to(self.root):
            raise ValueError("blocked")          # stops local file reads as well as SSRF
        return super().fetch(url, headers)

FONT_CSS = '@font-face{font-family:Inter;font-weight:400;src:url(fonts/inter-latin-400-normal.woff2) format("woff2")} ...'
fc = FontConfiguration()                         # one per render
css = CSS(string=FONT_CSS, base_url=f"{ASSETS}/", font_config=fc, url_fetcher=fetcher)
pdf = HTML(string=html, base_url=f"{ASSETS}/", url_fetcher=fetcher).write_pdf(stylesheets=[css], font_config=fc)
```

**Gotchas**

- **v70 fetcher API:** the old "function returning a dict" `url_fetcher` no longer
  works; there is an `assert isinstance(resource, URLFetcherResponse)`.
- **Glyph coverage:** use `latin-ext` subsets or a fallback font, otherwise missing
  glyphs render as boxes since the image has no system fonts.
- **Fontconfig cache:** with a read-only root filesystem, point `XDG_CACHE_HOME` at an
  `emptyDir` (**not verified**).

**Performance** (host, fontTools subsetting): a 12-page A4 proposal takes about
0.45–0.5 s and produces a 19 KiB PDF. Rendering is CPU-bound and holds the GIL: 8
renders on 4 threads took 9.3 s, versus about 3.6 s one after another. Run it off the
event loop (`anyio.to_thread.run_sync`) behind `Semaphore(1)`, or in the worker.

## 5. aiosmtplib 5.1.3 (verified against Mailpit v1.31.3)

All three modes were verified with auth and a custom CA, and each message was read back
through Mailpit's API: subject, To, text part, HTML part and Reply-To.

```python
ctx = ssl.create_default_context(cafile=ca_file) if security != "none" else None  # cafile=None -> system trust
await aiosmtplib.send(msg, hostname=host, port=port,
    use_tls=security == "tls",            # implicit TLS (465)
    start_tls=security == "starttls",     # MUST be an explicit False for "none" (the default None means "opportunistic")
    tls_context=ctx, username=user, password=pw, timeout=conn_timeout)   # default timeout is 60 s
# msg = EmailMessage(); set_content(text); add_alternative(html, subtype="html"); set Message-ID, Reply-To, List-Unsubscribe
# Mailpit: GET /api/v1/messages -> {"total", "messages":[{"ID","Subject","To":[{"Address"}]}]};
#          GET /api/v1/message/{ID} -> {"Text","HTML","ReplyTo",...}
```

**Errors seen (verified)**

- Wrong password: `SMTPAuthenticationError(535)`.
- Implicit TLS without the private CA: `SMTPConnectError(... CERTIFICATE_VERIFY_FAILED)`.
- Plain connection to a require-STARTTLS server: `SMTPSenderRefused(530)`.
- Unreachable host with `timeout=2`: `SMTPConnectTimeoutError`.
- **STARTTLS certificate failure raises a bare `ssl.SSLCertVerificationError`, not an
  `SMTPException`.** This happens with the default `start_tls=None`. Catch
  `(aiosmtplib.SMTPException, OSError)`.

**Deciding when to retry**

- Retry: `SMTPConnectError`, `SMTPTimeoutError`, `SMTPServerDisconnected`, other
  `OSError`s, and `SMTPResponseException` with a 4xx `.code`.
- Treat as permanent: 5xx codes, `SMTPRecipientsRefused`, `SMTPAuthenticationError`.

**Mailpit flags used**

- STARTTLS mode: `--smtp-tls-cert/--smtp-tls-key` with `--smtp-require-starttls`.
- Implicit-TLS mode: the same cert flags with `--smtp-require-tls`.
- Plain mode: `--smtp-auth-file` with `--smtp-auth-allow-insecure`.
- `--disable-version-check` stops the call to GitHub.

## 6. testcontainers 4.15.0, SQLAlchemy 2.1 async with psycopg 3, pytest-asyncio 1.4

Verified: 4 tests passed in about 3.6 s, including container start.

```ini
# pytest.ini / pyproject [tool.pytest.ini_options]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = session
asyncio_default_test_loop_scope = session
```

```python
os.environ.setdefault("RYUK_CONTAINER_IMAGE", "testcontainers/ryuk:0.11.0")  # TC default is 0.8.1 (not pre-pulled)
from testcontainers.community.postgres import PostgresContainer   # testcontainers.postgres is deprecated (warns)

@pytest.fixture(scope="session")
def pg_url():
    if url := os.environ.get("TEST_DATABASE_URL"): yield url; return
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()        # postgresql+psycopg://test:test@host:port/test

@pytest_asyncio.fixture(scope="session")
async def engine(pg_url):
    eng = create_async_engine(pg_url, poolclass=NullPool)   # "postgresql+psycopg" is async under create_async_engine
    ...; yield eng; await eng.dispose()

@pytest_asyncio.fixture
async def session(engine):      # rolled back per test; app code may still call commit()
    async with engine.connect() as conn:
        trans = await conn.begin()
        s = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try: yield s
        finally: await s.close(); await trans.rollback()
```

**Notes**

- **Empty extra:** in 4.15 the `[postgres]` extra pulls in nothing; the driver comes
  from our own `psycopg[binary,pool]`.
- **Loop scope:** pytest-asyncio 1.x has no `event_loop` fixture; use `loop_scope=`.
- **Cross-loop pooling:** a session-loop engine with the default pool, used from
  function-loop tests, did **not** fail with psycopg (asyncpg is known to fail there).
  A session loop scope plus `NullPool` is still the safe default.
- **Raw driver connection:** `(await (await s.connection()).get_raw_connection()).driver_connection`
  returns the `psycopg.AsyncConnection` (used in topic 2).

## 7. altcha 2.1.0 (Python) with the altcha@3.2.4 widget

- **Version pairing:** Python `altcha` 2.x switched the main API to **PoW v2**
  (key-derivation based; the widget's default is `PBKDF2/SHA-256`). The v1 API is still
  there as `create_challenge_v1` / `verify_solution_v1`. The npm widget v3 (latest
  3.2.4, one dependency, `hash-wasm`) uses v2 challenges, so pair **Python altcha ≥2
  with npm altcha@3**.
- **Payload delivery:** the widget posts a base64 payload in the form field `altcha`
  (the `name=` attribute). The `challenge=` attribute takes the challenge URL or JSON.
- **CSP and air-gap:** for a strict Content Security Policy, import from
  `altcha/external` and register the workers yourself. Both work air-gapped.

```python
from altcha import create_challenge, verify_solution
ch = create_challenge(algorithm="PBKDF2/SHA-256", cost=5_000, hmac_secret=HMAC_SECRET,
                      expires_at=datetime.now(UTC) + timedelta(minutes=10))
return ch.to_dict()          # GET /api/v1/public/{project}/altcha -> JSON for the widget
                             # {"parameters":{algorithm,cost,keyLength,keyPrefix,nonce,salt,expiresAt},"signature":...}
r = verify_solution(form["altcha"], HMAC_SECRET)   # .verified .expired .invalid_signature .invalid_solution .error
```

**Measured**

- **Random mode** (`keyPrefix "00"`, 1 in 256 odds): about 250 attempts on average;
  Python solves in 0.02–1.4 s; verification re-derives one key in about 3 ms.
- **Deterministic mode** (`counter=` plus `hmac_key_secret`, verification in 0.15 ms):
  the README's example counter range of 5,000–10,000 at cost 5,000 is too heavy. It
  took 18 s in Python, and Node WebCrypto needs 3.2 ms per attempt, about 24 s
  single-threaded.
- **Recommendation:** random mode at cost around 5,000, and tune it with Playwright on
  a phone-class CPU.

**Security**

- A wrong secret gives `invalid_signature`, and expiry is enforced.
- **There is no replay protection:** the same payload verifies twice. Store the
  challenge `signature` (or `nonce`) as used until it expires.
- In the fast path, only the derived key is checked, so a changed counter still passes.
  That is expected; the derived key is the proof of work.

**Not verified:** the widget in a real browser.

---

## Dependencies these recommendations introduce

- **`itsdangerous`:** required by Starlette's `SessionMiddleware`, which Authlib's login
  flow needs.
- **`mcp>=2.2,<3`:** v2 API as above; brings httpx2, sse-starlette and pyjwt.
- **`weasyprint>=70,<71`:** the v70 URL-fetcher API differs from older releases.
- **`altcha>=2.1,<3` and npm `altcha@^3`:** PoW v2 pairing.

## Follow-ups handed to owners

- **backend:** add `itsdangerous`, `mcp`, `weasyprint` and `altcha` when their phase
  starts. Raise the `aiosmtplib` floor to `>=5.1`. Import the PostgresContainer from
  `testcontainers.community.postgres`, and set `RYUK_CONTAINER_IMAGE` to
  `testcontainers/ryuk:0.11.0`.
- **platform (Helm/Dockerfile):** set `XDG_CACHE_HOME` to an `emptyDir` for fontconfig.
  Uvicorn needs `--proxy-headers --forwarded-allow-ips` for the multi-host redirect
  URIs. A `DEBIAN_MIRROR`-style build argument is needed where `deb.debian.org` is
  blocked.
- **platform (dev compose/realm):** register one callback URL per public host, plus
  `post.logout.redirect.uris`, and use the `oidc-group-membership-mapper` with
  `full.path=true`.
