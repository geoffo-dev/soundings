# Soundings: notes for Claude Code sessions

Living notes. Keep them current: when you learn a command, convention or gotcha that
the next session needs, add it here (lead-owned; teammates send additions to the lead).

## What Soundings is

Soundings (working name "ideas-pipeline" in SPEC.md) is a calm, fast web app where
people submit ideas, including anonymously through a public form. Each idea gets one
accountable **owner** and several **evaluators**, who score it **blind** against a
short rubric. Scores roll up into a weighted aggregate with a disagreement flag, and
strong ideas become a commercial proposal exported to PDF or Markdown. kagent agents
can act as an extra evaluator or research assistant through our MCP server. It is
one container image and one Helm chart, needs only PostgreSQL, sends mail through any
SMTP server, and runs air-gapped. Guiding rule: **simple beats configurable**.

## Read first

| File | Why |
|---|---|
| `SPEC.md` | The product brief and source of truth (read-only) |
| `docs/ownership.md` | Which paths you may edit; how to ask other owners for changes |
| `docs/role-matrix.md` | Every permission rule by stable name, and the exact blind-evaluation rules |
| `docs/adr/` | Architecture decisions (stack, jobs, image, sessions, scoring, authz…) |
| `docs/decisions.md` | Product decisions and simplifications, incl. SPEC section 16 answers |
| `docs/api/contract-phase*.md`, `docs/erd.md` | The current API contract and data model |
| `docs/wireframes/` | Low-fi wireframes of the seven screens (`index.html` shows all) |
| `docs/research/` | Verified library, kagent, A2A and Claude Code facts (with caveats) |
| `docs/phase-summaries/` | What each phase built, its evidence, review outcomes and known issues |

## Repository layout

```
backend/          FastAPI app (app/), Alembic (app/migrations/, ships in the wheel),
                  tests/ — uv, Python 3.12; app/seed/ is the demo story (`soundings seed`)
  app/schemas/      API contract (lead)          app/authz/ app/auth/ app/api_keys/ (identity)
frontend/         React 19 + TS SPA and design system — npm, Vite 8, Tailwind 4
  src/api/generated/  openapi.json + schema.d.ts (lead, generated)
  src/components/ui/  design system; /design shows it (dev only)
deploy/helm/      Helm chart          deploy/kagent/  example agent manifests
dev/              docker-compose: Postgres 16, Keycloak 26 (realm export), Mailpit
e2e/              Playwright e2e against the real stack + review screenshots (qa)
scripts/          check-task.sh (TaskCompleted gate), k3s-*.sh helpers
docs/             ADRs, role matrix, ownership, wireframes, guides, research,
                  test-plans/phase-N.md (qa), screenshots/phase-N/ (real-stack review
                  screenshots, light/dark/390 px; the frontend's mock ones in mock/),
                  phase-summaries/phase-N.md (lead), user-guide.md, operator-guide.md
.claude/          settings.json (team env, permissions, hook), agents/ (8 agent types)
Dockerfile        one image: API + built SPA; `worker` and `migrate` subcommands
Makefile          root tasks (below)
```

## Commands

Root (`make` or `make help` lists them; all verified to exist on 2026-09-30):

| Target | What it does |
|---|---|
| `make check` | Every check: `check-backend check-frontend check-helm check-scripts` |
| `make check-backend` | `make -C backend check`: ruff, mypy --strict, pytest (needs Docker) |
| `make check-frontend` | `npm --prefix frontend run check`: tsc, eslint + prettier, vitest, build |
| `make check-helm` | `helm lint --strict` + `helm template` for defaults and `deploy/helm/ci/*-values.yaml`, via the helm container |
| `make check-scripts` | `bash -n` + shellcheck (when available) on `scripts/` |
| `scripts/check-task.sh [area…]` | The TaskCompleted gate by hand: `backend frontend helm e2e scripts` (e2e = `npm --prefix e2e run check`); no args = areas with uncommitted changes, `CHECK_TASK_ALL=1` = all |
| `make dev-up` / `dev-down` / `dev-logs` | Dev services via `docker compose -f dev/docker-compose.yml` |
| `make dev` | Prints how to run API, worker and SPA against the dev services |
| `make seed` | Migrate + load the demo data into `SOUNDINGS_DATABASE_URL` (default: the dev compose DB); a no-op once there are projects, `RESET=1` wipes app data first. Who's who: `dev/README.md` |
| `make image` | Build `soundings:dev` (`IMAGE=`, `IMAGE_BUILD_ARGS=`, `BUILD_CA=`). This sandbox has no Debian mirror: add `IMAGE_BUILD_ARGS="--build-arg RUNTIME_APT_PACKAGES="` (PDF export then fails) |
| `make demo` / `demo-down` | Build the image and run it with Postgres, dev login and demo data on http://localhost:8000 (`DEMO_PORT=`, `DEMO_NAME=` container prefix, `DEMO_RESET=1`; `scripts/demo.sh`) / remove it all |
| `make k3s-up` / `k3s-load` / `k3s-install` / `k3s-smoke` / `k3s-down` | Local k3s in Docker (`K3S_NAME`, default `soundings-k3s`), import image, `helm upgrade --install` with `dev/k3s-values.yaml` (dev login + demo seed Job), smoke test through the ingress (incl. dev login + CSRF + My work, and a break-glass sign-in when available) and `helm test`. `make k3s-install IMAGE=soundings:<tag>` loads and deploys that image (the values file alone says `soundings:dev`) |
| `make k3s-keycloak` · `k3s-install SSO=1` · `k3s-smoke SSO=1` | Keycloak with the dev realm in the cluster (`scripts/k3s-keycloak.sh up\|down`; issuer `http://keycloak.localhost:18081/realms/soundings` for browser and pods; creates Secret `soundings-oidc`), then install with `dev/k3s-sso-values.yaml` and run `scripts/sso-smoke.sh` through the ingress |
| `make sso-smoke` | `scripts/sso-smoke.sh $(SSO_BASE_URL)` (default :8000, the `make dev` API with `dev/.env`): alice signs in through Keycloak with curl, then the Phase 2 acceptance (managed group → private project; removed in Keycloak → 404 at next sign-in); needs `jq`, cleans up |
| `make openapi` | Export the backend's OpenAPI to `frontend/src/api/generated/openapi.json` |
| `make gen-api` | `openapi` + regenerate `schema.d.ts` (openapi-typescript) |
| `make e2e` | Playwright e2e in `e2e/` against `E2E_BASE_URL` (default http://localhost:8000, i.e. `make demo`); CI runs it against the built image with the demo data |

Backend (`make -C backend <target>`): `install` (uv sync --locked), `check`, `lint`,
`typecheck`, `test`, `test-slow` (10k-idea performance checks, excluded from `test`),
`fmt`, `dev` (API on :8000 with reload; also serves the SPA from `frontend/dist` once
built), `worker`, `migrate`, `revision m="..."` (backend owner only), `openapi`,
`vendor-swagger` (refresh the bundled Swagger UI). `tests/identity/test_keycloak.py`
runs a real Keycloak 26 testcontainer (about 45 s of `test`): `SOUNDINGS_TEST_KEYCLOAK=0`
skips it, `SOUNDINGS_TEST_KEYCLOAK_URL=<url>` reuses a running Keycloak with the dev
realm (CI loads it with `dev/keycloak/import_realm.py`). The other SSO tests use the fake
IdP in `tests/identity/fake_idp.py`. The `soundings` CLI (`uv run soundings
<cmd>` in `backend/`, the image's entrypoint): `api`, `worker`, `migrate`,
`wait-for-db --timeout N`, `seed [--reset] [--force]` (refuses production without
`--force`), `openapi`.

Frontend (`npm --prefix frontend run <script>`, after `npm --prefix frontend ci`):
`dev` (Vite on :5173, proxies `/api`, `/mcp`, `/metrics` to :8000), `dev:mock` (MSW, no
backend), `check`, `typecheck`, `test` (vitest), `test:pw` (Playwright + axe against
dev:mock on :5174; `PW_PORT` overrides; pages start signed in as Alice through
`tests/support.ts`), `screenshots` (every `*screenshots.spec.ts` against the mock, into
`docs/screenshots/phase-1/mock/`; `SCREENSHOT_DIR` overrides), `gen:api`, `build`,
`lint`, `format`. The mock keeps toggles in localStorage (latency, forced failures, the
10k-idea dataset) and adds a dev-only "Switch user" to the account menu. Phase 2 mock
sign-in knobs (localStorage, `frontend/README.md`): `soundings-mock-auth` (`sso`,
`dev_login`, `break_glass`, `none`; default `sso,dev_login`), `soundings-mock-sso-user`,
`-sso-error`, `-sso-discovery`; the mock break-glass login is `break-glass` / `correct
horse battery staple`. Phase 2 mock screenshots: `SCREENSHOTS=1 npx playwright test
admin-screenshots login-screenshots` in `frontend/` → `docs/screenshots/phase-2/mock/`.

E2E (`e2e/`, after `npm --prefix e2e ci`): `npm --prefix e2e test` starts the real stack
from the working tree (Postgres `<E2E_PREFIX>pg` on 55433, migrate, `seed --reset`, a
Vite build into `e2e/.stack/dist`, `soundings api` on :8100 with dev login), runs 60+
specs and stops it. `E2E_BASE_URL=<url>` tests a running app instead (nothing started
or reseeded; it needs the demo data and dev login: `make demo`, CI). `E2E_KEEP_STACK=1`
keeps the stack (the next run only reseeds), `E2E_SKIP_BUILD=1` reuses the SPA build,
`E2E_PORT` / `E2E_PG_PORT` / `E2E_PREFIX` (default `p1-qa-`) / `E2E_WORKERS` (2) /
`E2E_STATE_DIR` (default `e2e/.stack`: SPA build, pid, log; give each parallel stack its
own, with its own ports and prefix).
**SSO mode:** `E2E_SSO=1` also starts Keycloak `<prefix>kc` on `E2E_KC_PORT` (8180) with
a fresh realm on every start and reseed, and points the API at it (dev login stays on;
break-glass is configured but off). Specs that need Keycloak are tagged `@sso` and skip
without it (`-- --grep @sso` runs only them, as CI's SSO jobs do). They use
`tests/support/sso.ts` (`ssoSignInAs(page, 'carol')`, `withoutKeycloakGroup(...)`, which
always restores the membership) on top of `e2e/scripts/keycloak.ts` (Keycloak admin API,
module and CLI). Without SSO the break-glass admin is on (`E2E_BREAK_GLASS_USERNAME` /
`_PASSWORD`, default `admin` / `e2e-break-glass-password`; `E2E_BREAK_GLASS=0` turns it
off). Changing mode restarts the API; `stop-stack.sh` also removes Keycloak.
`npm --prefix e2e run screenshots` writes `docs/screenshots/phase-1/` and
`screenshots:phase2` `docs/screenshots/phase-2/` (an SSO run, then a break-glass run),
both from freshly seeded data (the local stack reseeds on start); `npm --prefix e2e run
check` = tsc + prettier. Test plans and case IDs: `docs/test-plans/phase-1.md`,
`phase-2.md`.

Wireframes: edit `docs/wireframes/0*.md`, then `python3 docs/wireframes/build_index.py`.

Ports: Postgres 5432, Keycloak 8080, Mailpit 8025 (SMTP 1025), API 8000 (and
`/metrics` on 9090 unless `--reload`), Vite 5173, Playwright 5174, e2e stack 8100
(Postgres 55433, Keycloak 8180), k3s API 16443, k3s ingress 18081. Dev logins, the demo
people and groups, and the Keycloak users are in `dev/README.md`.

**SSO in development** (`dev/README.md` has the walkthrough): `make dev-up` (Keycloak
imports `dev/keycloak/realm-soundings.json`), `cp dev/.env.example dev/.env` once and
`set -a; . dev/.env; set +a` in each backend shell, `make seed`, `make -C backend dev`,
`npm --prefix frontend run dev`, then "Sign in with SSO" on http://localhost:5173 as
`alice` / `password` (realm users alice…erin, grace, mallory, kenji, nia; client
`soundings`, secret `soundings-dev-secret`). The realm allows redirect URIs only on
:8000, :5173, :8100 (localhost and 127.0.0.1) and :18081; on other ports register yours
through Keycloak's admin API in your own Keycloak container. Break-glass works only
with `SOUNDINGS_OIDC_ISSUER` unset (`.env.example`: `admin` / `dev-break-glass-password`).

## Conventions

- **Contract first.** The lead writes Pydantic schemas in `backend/app/schemas/`, 501
  route stubs and `docs/api/contract-phaseN.md`, then `make gen-api`. Builders never
  change the contract; they message the lead (ADR 0008).
- **File ownership** per `docs/ownership.md`. Only backend writes migrations. Only the
  lead commits. Never run `git stash/reset/checkout --/clean/restore` in the shared
  tree (settings.json makes these ask).
- **API shape:** `/api/v1`, snake_case JSON, RFC 9457 problem+json with a stable
  `code`, opaque cursor pagination (`items`, `next_cursor`), UUID ids plus idea keys
  like `CUST-12`. Check order: 401 → 404 → 403 → 422 → 409.
- **Database:** psycopg 3 only (SQLAlchemy `postgresql+psycopg://` and procrastinate);
  no asyncpg. Enums are `VARCHAR` + `CHECK`. Tests use testcontainers Postgres, not
  mocks.
- **Authorisation:** one policy module, deny by default, rules named as in the role
  matrix. Routes, MCP tools, jobs and emails call the policy; nothing checks roles
  directly (ADR 0010).
- **Blind evaluation:** pending evaluators see no score data anywhere; emails never
  contain scores (role matrix section 3, ADR 0006).
- **Sign-in and audit:** sessions carry `auth_method` and work only while that method is
  available (24 h max, 12 h idle; break-glass 8 h / 1 h); cookies are
  `__Host-soundings_*` when Secure (ADR 0005 amendment). A sign-in in progress is
  sealed into the `soundings_oidc` cookie (`app/auth/login_attempt.py`; nothing is
  stored), and anything else the server must get back unread uses
  `app/auth/sealing.py` (per-purpose keys from the secret key). The client IP comes
  from `app.middleware.ProxyHeadersMiddleware` (trusted proxies, `trusted_proxy_hops`),
  never from `X-Forwarded-For` directly. Admin, sign-in and assignment changes are
  recorded with `app/services/audit.py:record` (actions = exactly the contract's
  `AuditAction`; a new one needs the SPA's phrase, category, mock list and the
  exhaustive `Record` in `audit-phrases.test.ts` in the same change); denied sign-ins
  have no actor; never log or audit tokens, secrets, cookies, emails or claims.
  Group-membership writes call `group_sync.lock_user` first (the lock sign-in sync
  takes).
- **Locking:** every write to an idea loads it with `load_idea(for_update=True)`, which
  locks the project row (`FOR KEY SHARE`) before the idea row; whole-project writes
  (`replace_rubric`) take the project `FOR UPDATE`. One order, so no deadlocks or stale
  cached aggregates.
- **Input limits:** bodies over 1 MiB get 413 before auth; request models extend
  `RequestModel` (rejects NUL, unknown fields); cursors are validated on decode
  (`app/pagination.py`). Malformed input is a 4xx, never a 500.
- **Demo data:** `soundings seed --reset` needs `--force` once anyone who is not a demo
  person has an account; it refuses production without `--force`.
- **Email:** outbox row + job deferred in the same transaction (ADR 0003).
- **Tests first** for authz, login matching and group sync, blind-evaluation
  visibility, API-key scoping and the email outbox.
- **Frontend:** only design-system components and tokens (no hex values, no arbitrary
  Tailwind values); loading, empty and error states, dark mode, keyboard, 390 px for
  every screen; API only through `src/api/client.ts`. Dialogs and sheets restore focus
  themselves (`components/ui/return-focus.ts`; `onCloseAutoFocus` only picks a
  replacement when the opener is gone);
  server-filtered cmdk lists use `useTopResult` so Enter picks the visible top row, and
  pass empty/loading/error messages as `CommandList empty` (outside the listbox).
  Sheets open focused on themselves; closing one opened from a list row returns focus
  to that row (`lib/return-to-row.ts`). Phase 2 design-system pieces: `PasswordInput`,
  `ButtonShortcut` / `ariaKeys` (`kbd.tsx`; hints only from `sm` with a fine pointer),
  `Table cardFields="inline"` (one muted line per phone card), `FilterMenu`; toasts
  move above a side sheet's footer while it is open.
  Unsent drafts go through `lib/drafts.ts` (`draftKey(userId, name)`), which clears them
  on sign-out, 401 and user switch.
- **Air-gapped:** no CDN assets, web fonts or telemetry; everything is bundled.
- **Dependencies:** one-line justification each, in the owner's report.
- **Commits** (lead): small conventional commits, no secrets.

## Environment gotchas (this build machine)

- **Docker:** if `docker info` fails, start the daemon:
  `(nohup dockerd > /tmp/dockerd.log 2>&1 &)`. Docker Hub pulls go through the
  `mirror.gcr.io` registry mirror (direct Hub pulls may 429). Pre-pulled:
  `postgres:16-alpine`, `python:3.12-slim`, `node:22-alpine`, `alpine/helm:3.16.2`,
  `rancher/k3s:v1.31.4-k3s1`, `keycloak/keycloak:26.0`, `axllent/mailpit`,
  `testcontainers/ryuk:0.11.0`.
- **Blocked hosts:** quay.io, get.helm.sh, GitHub release downloads, ui.shadcn.com,
  kagent.dev, modelcontextprotocol.io, deb.debian.org (so apt in the image build
  fails; see `IMAGE_BUILD_ARGS` in the Makefile). pypi.org, registry.npmjs.org and
  code.claude.com work. To check a library's API, read the installed source.
- **TLS proxy:** outbound HTTPS is intercepted; the CA bundle is
  `/root/.ccr/ca-bundle.crt` (`SSL_CERT_FILE`). `make image` passes it as a BuildKit
  secret (`BUILD_CA`); k3s trusts it via `scripts/k3s-up.sh`.
- **Helm and kubectl** are not installed as binaries. Use the make targets;
  `scripts/lib/k3s-env.sh` defines `helm` (alpine/helm container on the k3s network)
  and `kubectl` (`docker exec -i soundings-k3s kubectl …`). The kubeconfig is in
  `.k3s/soundings-k3s/` (git-ignored). In-cluster pulls need the `registries.yaml`
  mirror that `k3s-up.sh` writes.
- **Playwright:** Chromium is pre-installed at `/opt/pw-browsers`
  (`PLAYWRIGHT_BROWSERS_PATH`). Pin `@playwright/test` to **1.56.1**. Never run
  `playwright install` (denied in settings.json).
- **testcontainers:** set `RYUK_CONTAINER_IMAGE=testcontainers/ryuk:0.11.0` (the
  default 0.8.1 isn't pulled); import `PostgresContainer` from
  `testcontainers.community.postgres`.
- **Local e2e stack:** the API serves `e2e/.stack/dist` and caches `index.html` at
  startup, so after rebuilding the SPA restart the API too (`e2e/scripts/stop-stack.sh`
  then run again); a rebuild under a running API gives a blank page.
- **Shared tree:** the Vite dev server reloads pages whenever anyone saves a file
  (`VITE_NO_HMR=1` turns that off; `test:pw` sets it for the server it starts, not for a
  running one it reuses), and parallel Playwright runs share `test-results/` (pass
  `--output=<dir>`). `pkill -f <pattern>` also matches the calling shell's own
  command line and kills it; stop servers by pid.
- **`ruff format`** also formats Python code blocks in `backend/README.md`.
- **Keycloak:** it marks its cookies `Secure` even on http://localhost, so curl must
  pass cookies by hand (`scripts/lib/keycloak.sh` does). glibc and Node don't resolve
  `*.localhost` here (curl and Chromium do), which matters for k3s's
  `keycloak.localhost`. Browser and API must use the same issuer URL
  (`KC_HOSTNAME_STRICT=false` makes it follow the URL used). The app's OIDC client
  (httpx) trusts only `SSL_CERT_FILE` when that is set, as it is in this sandbox.
  Keycloak 26 ignores `prompt=select_account` (hence `max_age=0` with every prompt) and
  compares `max_age` in whole seconds: a test that switches accounts right after a
  sign-in must wait a second (e2e LE-09).
- **k3s NetworkPolicy** is enforced (kube-router) and on by default in the chart; a new
  pod's address is admitted a moment after it starts, so in-cluster clients started
  fresh (the `helm test` pod) retry. Through Traefik an oversized *chunked* POST may get
  502 instead of the app's 413 (the smoke accepts that and checks 413 in the pod).
- **SSO e2e data:** an identity links to an account once, so some `@sso` specs need a
  fresh seed and realm (the local stack resets both on start; reseeding uses
  `seed --reset --force` and fails loudly). Use run-unique group names
  (`group_name_taken` otherwise).
- **Undo inside sheets:** a toast's Undo can't be clicked while a modal sheet is open
  (the sheet blocks outside clicks), so destructive actions in sheets confirm instead.
- **Library pins that matter:** TypeScript 5.9.x (7.x breaks typescript-eslint and
  openapi-typescript), MSW 2.15, `mcp` 2.x (`MCPServer`, not `FastMCP`), WeasyPrint 70
  (new URL-fetcher API), Python `altcha` 2.x with the `altcha@3` widget. OIDC is httpx +
  `joserfc` (no Authlib: `authlib.jose` is deprecated and its Starlette client isn't used).
- **Shared machine** (4 CPUs, 15 GB): use your assigned ports and container prefix,
  stop what you start, never kill other agents' processes or containers.

## Claude Code multi-agent setup

`.claude/settings.json` (verified against code.claude.com on 2026-09-30 and the
published settings schema):

- `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` enables agent teams. Project `env` and
  `allow` rules apply only after the folder is trusted.
- **allow:** `make`, the `scripts/k3s-*.sh` and `check-task.sh` helpers, `uv sync`,
  `uv run pytest|ruff|mypy|alembic|soundings`, `npm ci`, `npm run` (also with
  `--prefix frontend|e2e`), `npx playwright test|show-report`,
  `docker compose -f dev/docker-compose.yml`, `docker exec [-i] soundings-k3s kubectl`
  (local k3s only), and read-only git. Helm has no direct rule: a wildcard over
  `docker run` flags would also approve `--privileged` or arbitrary mounts, so run it
  through `make check-helm` / `make k3s-install`.
- **ask:** git commands that rewrite the shared working tree, and `docker * prune`.
- **deny:** `playwright install`.
- **TaskCompleted hook** runs `scripts/check-task.sh` (exec form, 20 min timeout) when
  any agent marks a task completed with TaskUpdate, or a teammate stops with tasks in
  progress. Exit 2 keeps the task open and feeds the failing output back to the agent.
  The hook input has no list of touched files, so the script checks every area with
  uncommitted changes (`git status`): in a busy shared tree that can include other
  owners' red areas. Unverified: the hook firing inside a real team session.

Agent types in `.claude/agents/` (all `model: inherit`): `backend`, `identity`,
`frontend`, `platform`, `qa` (builders) and `code-reviewer`, `ux-reviewer`,
`researcher` (read-only). Spawn teammates **named after their type** (e.g. "spawn a
teammate named backend using the backend agent type"). With teams enabled, any
subagent given a name becomes a teammate, so spawn researchers and reviewers
unnamed. Teammates can't spawn teammates; one team per session.

## How to run a phase

1. **Plan** (plan mode): re-read the phase in SPEC section 13, `docs/decisions.md` and
   open requests. List assumptions and questions for the human.
2. **Contract:** write schemas, 501 stubs and `docs/api/contract-phaseN.md`; update
   `docs/role-matrix.md` for new rules and `docs/erd.md`; run `make gen-api`; commit.
3. **Tasks:** 5–6 tasks per teammate, each with a clear deliverable, the paths it
   touches, and dependencies. Acceptance criteria become qa tasks first.
4. **Team:** spawn 3–5 teammates by agent type with task-specific context (ports,
   container prefix, which docs to read). Example kick-off from the human:
   > Enter plan mode. We're starting Phase N from SPEC.md. Write the Phase N contract
   > and task list, then create an agent team: backend, frontend, platform and qa
   > teammates using those agent types. Enforce docs/ownership.md. Wait for all
   > teammates to finish, run code-reviewer and ux-reviewer, then give me the phase
   > summary with screenshots.
5. **Wait**, route cross-owner requests, and don't implement teammates' tasks.
6. **Review:** run `code-reviewer` and `ux-reviewer` subagents; assign fixes back.
7. **Close:** `make check`, a clean `make k3s-install k3s-smoke`, light/dark/mobile
   screenshots, docs updated (this file, decisions, ADRs, guides), lead commits, then
   stop for the human's review.

The same flow works with Claude Code workflows (a script that fans out subagents): the
lead's script supplies each agent's owned paths, ports and prefix; agents report
"Requests for other owners" in their final message instead of messaging peers.

## Status

- **Phase 0** (plan and scaffold): docs, ADRs, role matrix, ownership, wireframes,
  agent setup, backend/frontend/Helm/dev/CI scaffolds.
- **Phase 1** (ideas, owners, evaluators): sessions + dev login, the authz policy,
  projects/members/rubric/labels, ideas, board and list, owners, evaluators, blind
  evaluation, aggregate and ranking, My work, search, ⌘K, settings, the demo seed, e2e
  suite and screenshots (`docs/screenshots/phase-1/`). Code/security and UX reviews
  applied (1 MiB body limit, lock order, input hardening, focus return, pickers, per-user
  drafts). Closed on 2026-10-01 with every check green and a clean k3s install, upgrade
  and smoke: [docs/phase-summaries/phase-1.md](docs/phase-summaries/phase-1.md) (known
  issues and deferred items there). Decisions: `docs/decisions.md` (Phase 1).
- **Phase 2** (sign-in and access): OIDC code flow + PKCE (`app/auth/oidc.py`,
  `api/v1/auth_sso.py`; stateless sealed sign-in cookie), login matching, group
  mappings and sync, break-glass, project roles via groups, admin Users / Groups /
  Sign-in (SSO) / Audit log under `/settings`, "Use a different account"
  (`prompt=select_account`), 24-hour sessions, Keycloak in dev, e2e (`E2E_SSO=1`), k3s
  (NetworkPolicy on by default, Keycloak in the cluster) and CI. Code/security and UX
  reviews applied. Closed on 2026-10-01 with every check green in both e2e modes and a
  clean k3s install (SSO), upgrade and smoke:
  [docs/phase-summaries/phase-2.md](docs/phase-summaries/phase-2.md) (known issues and
  deferred items there). Screenshots: `docs/screenshots/phase-2/` (real stack) and
  `mock/`. Decisions: `docs/decisions.md` (Phase 2). Stop for the human's review before
  Phase 3.
