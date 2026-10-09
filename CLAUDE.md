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
| `README.md` | The front door: what Soundings is, the tour (`docs/screenshots/tour/`), quick start, architecture |
| `docs/RELEASE-NOTES.md` | 0.1.0: what is in it, known issues, upgrade notes, decisions to confirm |
| `SPEC.md` | The product brief and source of truth (read-only) |
| `docs/ownership.md` | Which paths you may edit; how to ask other owners for changes |
| `docs/role-matrix.md` | Every permission rule by stable name, and the exact blind-evaluation rules |
| `docs/adr/` | Architecture decisions (stack, jobs, image, sessions, scoring, authz…) |
| `docs/decisions.md` | Product decisions and simplifications, incl. SPEC section 16 answers |
| `docs/api/contract-phase*.md`, `docs/erd.md` | The current API contract and data model |
| `docs/wireframes/` | Low-fi wireframes of the seven screens (`index.html` shows all) |
| `docs/research/` | Verified library, kagent, A2A and Claude Code facts (with caveats) |
| `docs/mcp.md` | Connecting MCP clients (Claude Code, Claude Desktop, SDKs) with a key; the ten tools; safety; how Soundings' own AI agents use it (c22) |
| `deploy/kagent/README.md` | kagent integration: how a run flows, the manifests, what is verified against real kagent vs the fake agent |
| `docs/phase-summaries/` | What each phase built, its evidence, review outcomes and known issues |

## Repository layout

```
backend/          FastAPI app (app/), Alembic (app/migrations/, ships in the wheel),
                  tests/ — uv, Python 3.12; app/seed/ is the demo story (`soundings seed`)
  app/schemas/      API contract (lead)          app/authz/ app/auth/ app/api_keys/ (identity)
  app/mcp/            the MCP server at /mcp: guard (Origin, key, c15, rate), SDK server,
                      one tools/call dispatcher (audit), the ten tools over the REST services
  app/notifications/  fan-out, preferences, digests, reminders, mentions, inbox, unsubscribe
  app/email/          outbox, worker tasks, SMTP, rendering; app/templates/email/ (Jinja2)
  app/proposals/      sections, margin threads, suggestions, Markdown, exports; PDF child process
                      (pdf.py, pdf_child.py), app/templates/pdf/, app/assets/fonts/ (woff2);
                      template.py (Phase 8: each project's sections, archive/restore by key)
  app/services/research.py  the research step (Phase 8): settings, checklist, answers, the
                      gate (`research_incomplete`, "Move anyway"), card progress, Similar ideas
  app/services/research_assignment.py  the researcher (Phase 8b): assign/remove/hand back, the
                      automatic clears (close, step off, deactivation, `left_project`)
  app/authz/guest.py  the guest researcher's route table `RESEARCH_GUEST_ACCESS` (Phase 8b)
  app/public/         public form, ALTCHA flow, tracking, confirmation, erasure, retention
  app/services/branding.py brand_assets.py moderation.py  branding (cached), images, queue
  app/ai/             AI runs (Phase 6): registry (agents.py), runs.py, runner.py + tasks.py (the
                      worker's `ai` queue), a2a.py (hand-written A2A 0.3/1.0 client), scope.py (c22),
                      results.py, notes.py, transitions.py (compare-and-set + events), sse.py
frontend/         React 19 + TS SPA and design system — npm, Vite 8, Tailwind 4
  src/api/generated/  openapi.json + schema.d.ts (lead, generated)
  src/components/ui/  design system; /design shows it (dev only)
deploy/helm/      Helm chart          deploy/kagent/  example kagent 0.10 manifests (agents, BYO fake)
deploy/environments/  CD values per environment (staging, production; no secrets), cluster-setup.yaml
                  (namespaces, the soundings-deployer ClusterRole), k3s.values.yaml (rehearsal overlay)
deploy/ci/        GitHub ARC: runner values, arc-rbac.yaml (no runner rights; soundings-ci-deployer
                  per environment), deploy-runner.Dockerfile (ARC runner and `tools` deploy images)
deploy/gitlab-agent/  the GitLab agents' RBAC and chart values; .gitlab/agents/soundings-<env>/ their
                  ci_access (this project, the environment, protected refs)
dev/              docker-compose: Postgres 16, Keycloak 26 (realm export), Mailpit, the fake agent
                  (profile `ai`); k3s/ (Mailpit, Keycloak, fake-agent manifests), k3s-*-values.yaml
  fake-agent/       Soundings' deterministic fake kagent agent (a2a-sdk 1.2.1 server; calls /mcp
                      back with the agent's key; own uv project, Makefile, Dockerfile; dev/CI/k3s only)
e2e/              Playwright e2e against the real stack + review screenshots (qa)
scripts/          check-task.sh (TaskCompleted gate), k3s-*.sh helpers, *-smoke.sh, deploy.sh and
                  deploy-smoke.sh (CD, both CIs), lib/ (k3s-deploy.sh, ci-kubeconfig.sh,
                  check-gitlab-ci.sh, check-migrations.py)
  ci-local/         a throwaway self-managed GitLab CE (registry, KAS) + runner + k3s + agents that
                      runs .gitlab-ci.yml for real (README.md); values/ for its environments
docs/             ADRs, role matrix, ownership, wireframes, guides (user, operator, mcp), research,
                  test-plans/phase-N.md (qa), screenshots/phase-N/ (real-stack review
                  screenshots, light/dark/390 px; the frontend's mock ones in mock/;
                  phase-3/emails/: every email template, light/dark, desktop/390 px),
                  phase-summaries/phase-N.md (lead), user-guide.md, operator-guide.md
.claude/          settings.json (team env, permissions, hook), agents/ (8 agent types)
Dockerfile        one image: API + built SPA; `worker` and `migrate` subcommands
Makefile          root tasks (below)
```

## Commands

Root (`make` or `make help` lists them; all verified to exist on 2026-09-30):

| Target | What it does |
|---|---|
| `make check` | Every check: `check-backend check-frontend check-helm check-scripts check-fake-agent check-workflows` |
| `make check-backend` | `make -C backend check`: ruff, mypy --strict, pytest (needs Docker) |
| `make check-frontend` | `npm --prefix frontend run check`: tsc, eslint + prettier, vitest, build |
| `make check-helm` | `helm lint --strict` + `helm template` for defaults and `deploy/helm/ci/*-values.yaml`, via the helm container; then `scripts/deploy.sh template` renders `deploy/environments/{staging,production}.values.yaml` |
| `make check-scripts` | `bash -n` + shellcheck (when available) on `scripts/` |
| `make check-fake-agent` | `make -C dev/fake-agent check`: ruff, mypy --strict, pytest (~25 s; includes a2a-sdk 0.3.23's own client in an isolated uv env) |
| `make check-workflows` | actionlint 1.7.12 (`ACTIONLINT_IMAGE`, by digest, with shellcheck) and zizmor 1.30.1 (`uvx`, `--offline`; `.github/zizmor.yml`) on `.github/workflows/`, then `scripts/lib/check-gitlab-ci.sh`: gitlab-ci-local 4.75.1 (`npx`) validates `.gitlab-ci.yml` against GitLab's schema and checks which delivery jobs main, a branch, a `vX.Y.Z` tag, `IMAGE_BUILDER=dind` and signing get (a throwaway repo; ~1 min) |
| `scripts/check-task.sh [area…]` | The TaskCompleted gate by hand: `backend frontend helm e2e scripts fake-agent` (e2e = `npm --prefix e2e run check`); no args = areas with uncommitted changes, `CHECK_TASK_ALL=1` = all |
| `make dev-up` / `dev-down` / `dev-logs` | Dev services via `docker compose -f dev/docker-compose.yml` |
| `make dev` | Prints how to run API, worker and SPA against the dev services |
| `make seed` | Migrate + load the demo data into `SOUNDINGS_DATABASE_URL` (default: the dev compose DB); a no-op once there are projects, `RESET=1` wipes app data first. Who's who: `dev/README.md` |
| `make image` | Build `soundings:dev` (`IMAGE=`, `IMAGE_BUILD_ARGS=`, `BUILD_CA=`): Ubuntu 24.04 base with Ubuntu's Python 3.12 and Pango, so PDF export works (the build fails if WeasyPrint can't render). Internal mirror: `IMAGE_BUILD_ARGS="--build-arg UBUNTU_MIRROR=http://…/ubuntu"`; `RUNTIME_APT_PACKAGES` only adds packages |
| `make demo` / `demo-down` | Build the image and run it with Postgres, the worker, Mailpit (inbox http://localhost:8026), dev login and demo data on http://localhost:8000 (`DEMO_PORT=`, `DEMO_MAILPIT_PORT=`, `DEMO_NAME=` container prefix, `DEMO_RESET=1`, `DEMO_SMTP=0` in-app only, `DEMO_TIMEZONE=`, `DEMO_PUBLIC_PER_IP=` public submissions per address and hour; `DEMO_AI=1` also builds and runs the fake agent on :8027 with AI on, keys in `dev/.fake-agent-keys`; containers run read-only with a `/tmp` tmpfs and no capabilities; `scripts/demo.sh`) / remove it all |
| `make k3s-up` / `k3s-load` / `k3s-install` / `k3s-smoke` / `k3s-down` | Local k3s in Docker (`K3S_NAME`, default `soundings-k3s`), import image, `helm upgrade --install` with `dev/k3s-values.yaml` (dev login + demo seed Job), smoke test through the ingress (incl. dev login + CSRF + My work, a break-glass sign-in when available, and `public-smoke`) and `helm test`. `make k3s-install IMAGE=soundings:<tag>` loads and deploys that image (the values file alone says `soundings:dev`). `k3s-up.sh` lowers the kubelet's disk eviction to 1 GiB free (`K3S_EVICTION_HARD`; the percentage defaults evicted every pod here); `dev/k3s/public-ratelimit.yaml` puts a Traefik rate limit in front of `/api/v1/public` |
| `make k3s-mailpit` · `k3s-install SMTP=1` · `k3s-smoke SMTP=1` | Mailpit in the cluster (`scripts/k3s-mailpit.sh up\|scale 0\|1\|down`; SMTP `mailpit.mailpit.svc.cluster.local:1025`, inbox http://mailpit.localhost:18081), install with `dev/k3s-smtp-values.yaml` (SMTP, time zone, egress policies), then `scripts/email-smoke.sh` through the ingress (invite → email with the evaluate link; Mailpit scaled to 0 → queued → delivered once). `SSO=1 SMTP=1` combines both (CI) |
| `make k3s-keycloak` · `k3s-install SSO=1` · `k3s-smoke SSO=1` | Keycloak with the dev realm in the cluster (`scripts/k3s-keycloak.sh up\|down`; issuer `http://keycloak.localhost:18081/realms/soundings` for browser and pods; creates Secret `soundings-oidc`), then install with `dev/k3s-sso-values.yaml` and run `scripts/sso-smoke.sh` through the ingress |
| `make sso-smoke` | `scripts/sso-smoke.sh $(SSO_BASE_URL)` (default :8000, the `make dev` API with `dev/.env`): alice signs in through Keycloak with curl, then the Phase 2 acceptance (managed group → private project; removed in Keycloak → 404 at next sign-in); needs `jq`, cleans up |
| `make email-smoke` | `scripts/email-smoke.sh $(EMAIL_BASE_URL)` (default :8000) against an app with dev login, the worker and Mailpit (`MAILPIT_URL`, default :8025; `MAILPIT_CONTAINER`, default the dev compose one; `MAILPIT_OUTAGE=0` skips the outage step); needs `jq` |
| `make mcp-smoke` | `scripts/mcp-smoke.sh $(MCP_BASE_URL)` (default :8000): curl JSON-RPC at `/mcp` with the demo data and dev login: 405/401/`/.well-known` 404 anonymously, then carol's key (read, evaluate, mcp; Customer Innovation only), `tools/list` (the ten tools), SPEC's nine tools called, blind `search_ideas` / `get_idea`, `submit_evaluation`, `not_found` outside the key's projects, `insufficient_scope`, a foreign `Origin`, the audit entries, revoke → 401 at the next call and on REST; creates and deletes a test idea; needs `jq`. `MCP_CLIENT_HOOK` runs another client with the key (k3s) |
| `make k3s-install MCP=1` · `k3s-smoke MCP=1` | `dev/k3s-mcp-values.yaml` (`kagent.enabled`; the API admits only Traefik and the `kagent` namespace), then `mcp-smoke` through the ingress plus `scripts/k3s-mcp-client.sh`: the official Python SDK in a pod in namespace `kagent` with its key from a Secret (`Bearer sdg_…`) calling the Service URL, and a pod in another namespace refused by the NetworkPolicy. CI runs `SSO=1 SMTP=1 MCP=1` |
| `make ai-smoke` | `scripts/ai-smoke.sh $(AI_BASE_URL)` (default :8000) against an app with AI on, dev login, the worker and the fake agent (`AI_FAKE_URL`, default :8083; `AI_FAKE_KEYS_DIR`, default `dev/.fake-agent-keys`): register an agent (key once), hand the fake its key, Test connection, "Ask AI to evaluate" watched over SSE by a pending evaluator (no score data, 204 after the end), the AI evaluation out of the aggregate then included, research note, section draft, a cancelled `-slow` run, the agent's key refused on REST and outside runs; `AI_PROTOCOL=kagent_v1_0` runs it over A2A 1.0; needs `jq` |
| `make fake-agent-image` · `make k3s-fake-agent` · `make k3s-kagent-crds` · `k3s-install AI=1` · `k3s-smoke AI=1` | The fake agent's image (`FAKE_AGENT_IMAGE`, default `soundings-fake-agent:dev`); the fake in k3s as `kagent/kagent-controller:8083` (so the default `controllerUrl` works); kagent v0.10.2's CRDs (from the git tag, cloned into `.k3s/`) plus a server-side dry run of every kagent manifest; install with `dev/k3s-ai-values.yaml` (AI on, `kagent.examples` when the CRDs exist) and run `ai-smoke` through the ingress. CI's k3s job runs `SSO=1 SMTP=1 MCP=1 AI=1` |
| `make public-smoke` | `scripts/public-smoke.sh $(PUBLIC_BASE_URL)` (default :8000): anonymously the public form, branding, logo headers, 404 and 415; with dev login a real ALTCHA submission (replay refused), tracking, approve, shortlist, proposal, PDF and Markdown export, then deletes the idea. `ALTCHA_PYTHON` names a Python with `altcha` (default the backend venv). `k3s-smoke` runs it too |
| `make k3s-install PROD=1` · `k3s-smoke PROD=1` | Production mode on the local k3s (`dev/k3s-prod-values.yaml`: no dev login or demo data, break-glass sign-in): the smoke checks `__Host-` cookies, the OpenAPI document and Swagger UI 401 anonymously and 200 signed in, `/metrics` off the app port, the production startup log, no password in the logs; skips the public-form smoke (no demo data). Not with `SSO=1` |
| `make openapi` | Export the backend's OpenAPI to `frontend/src/api/generated/openapi.json` |
| `make gen-api` | `openapi` + regenerate `schema.d.ts` (openapi-typescript) |
| `make e2e` | Playwright e2e in `e2e/` against `E2E_BASE_URL` (default http://localhost:8000, i.e. `make demo`); CI runs it against the built image with the demo data |
| `make deploy` · `deploy-rollback` · `deploy-smoke` · `deploy-status` (`ENV=staging\|production`) | `scripts/deploy.sh <action> $(ENV)` against the current kubeconfig context (needs helm 3.16+, kubectl, curl): deploy = `IMAGE_REPOSITORY` + `IMAGE_DIGEST` + `IMAGE_TAG`, values `deploy/environments/<env>.values.yaml`, `--atomic --wait`, `helm test`, the cluster checks and `scripts/deploy-smoke.sh <url>` (read-only, anonymous; also by hand), rollback on failure; rollback = `ROLLBACK_REVISION` (default the one before), refused across a migration head unless `DEPLOY_FORCE=1`; `DRY_RUN=1`; `scripts/deploy.sh check-release vX.Y.Z` (the tag = pyproject/uv.lock/Chart.yaml versions). Operator guide "Continuous delivery", ADR 0017 |
| `make deploy-tools-image` · `make deploy-runner-image` | `deploy/ci/deploy-runner.Dockerfile`: `--target tools` (alpine/helm + kubectl: `DEPLOY_TOOLS_IMAGE`, default `soundings-deploy-tools:dev`) or the ARC runner (`ghcr.io/actions/actions-runner` + helm + kubectl: `DEPLOY_RUNNER_IMAGE`; its ghcr base can't be pulled here, `--build-context` it to test) |
| `scripts/ci-local/ci-local.sh up` · `push [branch]` · `bump X.Y.Z` · `tag vX.Y.Z` · `wait <pipeline>` · `play <pipeline> <job> [K=V]` · `probe` · `github <env> deploy\|rollback [K=V]` · `guard` · `down [--images]` | The GitLab pipeline for real (`scripts/ci-local/README.md`): GitLab CE 19.4.1 on https with its registry and KAS (~4.5 GB RAM, the image 5.4 GB of disk), a Docker-executor runner (`runner-mode rootless\|privileged`; also tagged `soundings-deploy`), k3s with both agents from `deploy/gitlab-agent/`; `push` snapshots the working tree (`CI_LOCAL_PATHS` = HEAD + only those paths; `CD_ONLY=1` skips the long checks, and production then refuses), `probe` shows what CI jobs reach through each agent, `github` runs `deploy-env.yml`'s step in a rights-free pod with `KUBECONFIG_DATA`. `CI_LOCAL_PREFIX`/`CI_LOCAL_PORT` (five ports), `CI_LOCAL_MIRROR`, `CI_LOCAL_BUILDKIT_DIR` (not a tmpfs), `CI_LOCAL_DEPLOY_TOOLS=1`; `guard` stops the runner when disk or memory run low |
| `make k3s-deploy` (`ACTION=deploy\|rollback\|smoke\|status ENV=staging IMAGE=soundings:dev`) | CD rehearsal on the local k3s (`scripts/lib/k3s-deploy.sh`): applies `deploy/environments/cluster-setup.yaml`, binds SA `ci-deployers/soundings-<env>` in `soundings-<env>` only, creates the Secrets, imports `IMAGE` (also named by digest, so the kubelet finds it), reads its migration head, and runs `scripts/deploy.sh` as that SA in `DEPLOY_TOOLS_IMAGE` with `<env>.values.yaml` + `k3s.values.yaml`, smoke on localhost:`K3S_HTTP_PORT`. `IMAGE_DIGEST=` rehearses an unpullable image; pass the old image again before a rollback (the kubelet deletes unused images when the disk is >85 % full) |

Backend (`make -C backend <target>`): `install` (uv sync --locked), `check`, `lint`,
`typecheck`, `test`, `test-slow` (10k-idea performance checks, excluded from `test`;
includes `tests/perf`), `test-perf` (only the Phase 7 kit `tests/perf`: N+1, statements
per request, p95 one at a time, ~90 s),
`fmt`, `dev` (API on :8000 with reload; also serves the SPA from `frontend/dist` once
built), `worker` (sends email, runs the outbox sweep, the hourly reminder/digest
schedule and job cleanup; needed for any email; `dev` and `worker` set
`SOUNDINGS_ENVIRONMENT=development` unless you did: `soundings api`/`worker` refuse to
start with it unset and the built-in key), `migrate`, `revision m="..."` (backend
owner only), `openapi`, `vendor-swagger` (refresh the bundled Swagger UI).
`tests/acceptance/test_phase3_acceptance.py` sends through a real Mailpit (testcontainer,
about 10 s; `SOUNDINGS_TEST_MAILPIT=0` skips, `SOUNDINGS_TEST_MAILPIT_SMTP=host:port` +
`_URL` reuse one, as CI does); `test_phase4_acceptance.py` (about 7 s) solves a real
ALTCHA, sends through Mailpit the same way and renders the PDF with the real WeasyPrint
child, read back with `pypdf` (a dev dependency). PDF tests need Pango on the host (it
is installed here; CI installs it or runs on the Ubuntu image), else they skip.
`test_phase5_acceptance.py` (about 50 s) runs the app behind a real uvicorn with the demo
data and drives the contract §3.9 story with the official `mcp` client over TCP.
`test_phase6_acceptance.py` (about a minute) runs the app on uvicorn, the worker's two
procrastinate pools in the same event loop, and the real `dev/fake-agent` as a subprocess
(`uv run --project dev/fake-agent`, synced on first use) calling back into `/mcp`: it needs
`uv`; `SOUNDINGS_TEST_FAKE_AGENT=0` skips it. AI tests (`tests/ai/`) use
`helpers.py` (`make_agent(db, …, user=…)` registers an agent with its service account and
key through the service layer, `open_run(db, agent, idea, kind)` puts a run in `running`
so its key may act, `run_row`, `events`), the `crew`, `kagent` (`fake_kagent.py`: an A2A
server on `httpx.MockTransport`) and `ai_runtime` fixtures; `app.ai.runner.AiRuntime`
holds the timing seams (deadline, heartbeat, poll, retries, clock, `transport`) and
`app.state.ai_transport` replaces the network for Test connection. Agents' keys are
MCP-only (REST: 403), so tests of agents go through `/mcp` with an open run that each
call names: `mcp_as(key).for_run(run)` passes its `run_id` (`tests/mcp/conftest.py`).
Research tests (Phase 8, `tests/research/conftest.py`): `set_step(db, project, step)` turns
the step on with the default checklist (straight in the database), `answer(db, idea, item,
user)` / `answer_required(db, idea, items, user)` write answers, `open_titles(body)` reads a
409's open items; `test_phase8_acceptance.py` (about 80 s) plays the Phase 8 stories
through the API (`tests/proposals/test_template.py` for templates, `tests/ai/
test_research_gate.py`, `tests/mcp/test_research.py`, `tests/public/test_research_public.py`).
Phase 8b (the researcher): `tests/research/conftest.py` also has `assign(client, key, user,
due_at)` (the PUT), `researcher_audit`, `feed_types` and the MCP fixtures (`as_agent`,
`connect`, `make_key`); `tests/factories.py` `set_researcher` writes an assignment straight
in the database. The guest's table tests are `tests/research/test_guest_access.py` (every
idea route as the guest and as a stranger, every project GET) and
`tests/authz/test_researcher_access.py` (its meta-test fails for an idea route or MCP tool
without a `RESEARCH_GUEST_ACCESS` row); `test_role_loss.py` (S1 b on every role path),
`test_research_to_do.py`, `tests/notifications/test_research_reminders.py` (the worked
example, DST, every stop condition). `test_phase8b_acceptance.py` (about 75 s, Mailpit like
Phase 3's) probes every `{idea}` operation of the OpenAPI document as a guest and drives the
reminders with a moved clock.
API-key tests use `tests/api_keys/helpers.py` (`world`, `make_key` through the service
layer, also for service accounts; `key_client`; a person's key needs `last_seen_at`, which
`make_key` sets); MCP tests (`tests/mcp/conftest.py`) run the SDK client over
`httpx2.ASGITransport` inside the app's lifespan: `Client(streamable_http_client(url,
http_client=…), mode="auto" | "legacy")` (both handshakes). `tests/identity/test_keycloak.py`
runs a real Keycloak 26 testcontainer (about 45 s of `test`): `SOUNDINGS_TEST_KEYCLOAK=0`
skips it, `SOUNDINGS_TEST_KEYCLOAK_URL=<url>` reuses a running Keycloak with the dev
realm (CI loads it with `dev/keycloak/import_realm.py`). The other SSO tests use the fake
IdP in `tests/identity/fake_idp.py`. The `soundings` CLI (`uv run soundings
<cmd>` in `backend/`, the image's entrypoint): `api`, `worker`, `migrate`,
`wait-for-db --timeout N`, `seed [--reset] [--force]` (refuses production without
`--force`), `anonymise-user <email>` (a deactivated person's personal data, UK GDPR;
operator guide "What is stored about users"), `openapi`, `email-preview -o DIR` (every email template with sample data as
`.html` + `.txt` and an `index.html`; no database or SMTP needed; for reviewing
templates in browsers and mail clients).

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
Phase 3 mock knob: `soundings-mock-email` = `off` (no SMTP) or `failing` (a dead
server); the mock's pretend worker "sends" queued mail after 1.5 s. Phase 3 mock
screenshots: `SCREENSHOTS=1 npx playwright test notifications-screenshots` →
`docs/screenshots/phase-3/mock/`. Phase 4 mock: `soundings-mock-public=off` turns public
submission off; fixtures CUST-3 (a proposal with threads), CUST-4 (ready to start),
GREEN-9…12 (public submissions); the mock ALTCHA checks replay only (test the real
widget against the backend). Phase 4 mock screenshots: `SCREENSHOTS=1 npx playwright
test proposal-screenshots public-screenshots` → `docs/screenshots/phase-4/mock/`. Phase 5
mock: fixtures in `src/mocks/phase5-fixtures.ts` (Alice's three keys, Mateo's dormant key,
the Research agent's key, four pending suggestions on CUST-3; `frontend/README.md`);
⌘K has "API keys" (everyone) and "All API keys" (platform admins). Phase 5 mock
screenshots: `SCREENSHOTS=1 npx playwright test api-keys-screenshots` →
`docs/screenshots/phase-5/mock/`. Phase 6 mock (`src/mocks/ai.ts`, `phase6-fixtures.ts`,
`frontend/README.md`): Idea evaluator, the Research agent and a disabled Market scout;
CUST-7 has an AI evaluation left out of the score (Alice pending), CUST-4 a research note
and a timed-out run, CUST-2 none (ask away); a pretend worker walks new runs through the
real steps and streams them as SSE. Knobs: `soundings-mock-ai=off`,
`soundings-mock-ai-outcome` = `fail|timeout|no_result|unreachable|slow|queued`,
`soundings-mock-ai-pace` (ms per step); agents named `*-down`/`*-broken` fail Test
connection. Phase 6 mock screenshots: `SCREENSHOTS=1 npx playwright test ai-screenshots` →
`docs/screenshots/phase-6/mock/`. Phase 8b mock (`src/mocks/phase8b-fixtures.ts`,
`frontend/README.md`): Ivan (no role anywhere) researches TOOL-7 as its guest, Kofi TOOL-10,
Alice's GREEN-3 is overdue, GREEN-1 has nobody assigned but a due date;
`soundings-mock-projects=private` makes every project private, so Ivan has no projects.

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
**Email (Phase 3):** the stack also runs `soundings worker` and Mailpit
`<prefix>mailpit` (SMTP 127.0.0.1:`E2E_MAILPIT_SMTP_PORT` 1125, inbox and API
`E2E_MAILPIT_PORT` 8125, emptied on every start, messages survive `docker stop`/`start`),
instance time zone `E2E_TIMEZONE` (Europe/London); `node e2e/scripts/mailpit.ts
list|show|clear|stop|start`. `E2E_SMTP=0` runs without SMTP (email specs skip; the
banner/"not set up" specs PR-05, AE-04 run). Against `E2E_BASE_URL` set `E2E_MAILPIT_URL`
and, for the outage specs, `E2E_MAILPIT_CONTAINER`. Specs that stop Mailpit are tagged
`@smtp-outage` and run last in their own Playwright project `smtp-outage` (one worker,
depends on `e2e`): any failure in `e2e` skips them; rerun with `npx --prefix e2e
playwright test --project=smtp-outage --no-deps`, and add `--project=e2e` to run one
file's other tests without the outage ones. Email specs create run-unique people
(`tests/support/email.ts` `newPeople`) and always filter mail by recipient and `since`.
`npm --prefix e2e run screenshots` writes `docs/screenshots/phase-1/`,
`screenshots:phase2` `docs/screenshots/phase-2/` (an SSO run, then a break-glass run)
and `screenshots:phase3` `docs/screenshots/phase-3/` + `emails/` (an SMTP run, then
`E2E_SMTP=0`), all from freshly seeded data (the local stack reseeds on start);
**Public submission and branding (Phase 4):** the stack allows `E2E_PUBLIC_PER_IP`
(default 1000) public submissions per address and hour and takes `E2E_ALTCHA_COST`
(unset: the app's 5,000); changing either restarts the API. Every spec submits from
127.0.0.1, which the stack trusts as its proxy, so a spec that exhausts a per-address
throttle claims its own address with `X-Forwarded-For` (`tests/support/public.ts`
`Visitor`, which also solves ALTCHA in Node); against `E2E_BASE_URL` that spec (PA-05)
skips unless `E2E_TRUSTS_FORWARDED=1`, and the per-address limit spec (PA-06) needs
`E2E_PUBLIC_PER_IP` ≤ 20. Specs that change the global branding are tagged `@serial` and
run in the `serial` project (after `e2e`, one at a time; `smtp-outage` now depends on
it; `--project=serial --no-deps` reruns them; rerun `smtp-outage` in a separate command:
naming both with `--no-deps` runs them side by side, so the outage specs stop Mailpit
under the serial ones) and restore the profile in `finally`. PDFs
are read with `tests/support/pdf.ts` (`pdfjs-dist`, an e2e dev dependency: text,
metadata, colours, embedded fonts, page renders; there is no poppler here). The demo seed
has 48 ideas (CUST-21 approved from the public form, CUST-22/23 in the moderation
queue), so the Phase 1 list counts are 21 CUST ideas, 6 needing evaluators. Phase 8
(contract-phase8 §3.14, `app/seed/research.py`): Internal Tools (13 ideas) has the research
step before evaluation, the default checklist and a six-section template; TOOLS-11
(complete; "Similar ideas" finds CUST-14) and TOOLS-12 (one required item open) are in
Research, TOOLS-3's proposal ends with the research appendix. Sustainability (12 ideas)
has it before the proposal and a "Carbon impact" section (GREEN-4's proposal); GREEN-6
(Shortlisted) is partly answered, GREEN-5 not yet. Customer Innovation is unchanged (step off). So a New
TOOLS idea needs its checklist answered (or an admin's "Move anyway") before Evaluating or
its first evaluator. Phase 8b (`app/seed/research.py` `ASSIGNMENTS`): bob, not in the private
Internal Tools, researches TOOLS-12 as its guest (due in 3 days, asked by dave); amara, its
owner, researches GREEN-6 explicitly (asked by alice); alice's GREEN-5 is overdue (asked by
sven); TOOLS-11 has nobody (its owner does it).
`screenshots:phase4` writes `docs/screenshots/phase-4/` (12 screens × 1440 light/dark and
390), `pdf/` (the exported PDF and its pages) and `emails/` (as Mailpit received them).
**API keys and MCP (Phase 5):** specs use keys only through `tests/support/mcp.ts`
(`KeyClient`: `Authorization: Bearer`, no cookie or CSRF; `rest()` for `/api/v1`, `rpc()` /
`call()` / `ok()` / `fails()` for `/mcp`; each client claims its own address with
`X-Forwarded-For`, since refused keys count 30 a minute per address) and make keys with
`api.createApiKey(...)`, revoking them when they end (25 per user). Specs that end
someone's sessions or deactivate them create that person (`newPerson`).
`screenshots:phase5` writes `docs/screenshots/phase-5/` (7 screens × 1440 light/dark and
390; the shown key is revoked at once).
**AI (Phase 6):** `E2E_AI=1` also starts the fake agent (`uv run`, no container) on
127.0.0.1:`E2E_FAKE_AGENT_PORT` (8183) as the API's kagent controller, turns AI on with
`E2E_AI_RUN_TIMEOUT` (PT1M) and after every seed registers "Idea evaluator"
(`soundings/idea-evaluator`, `E2E_AI_AGENT`; `E2E_AI_PROVISION=0` skips) through the API,
writing its key to `E2E_FAKE_AGENT_KEYS_DIR` (default `<state dir>/fake-agent-keys`). AI
specs are tagged `@ai` and skip without it (`-- --grep @ai` runs only them, as CI's
`e2e-ai` job). They use `tests/support/ai.ts` (`aiTeam(alice)`: a project of their own
with its **own idea owner**, because each person may ask for 20 runs an hour;
`registerAgent`, `requestRun`, `waitRun`, `retireAgents`) and `e2e/scripts/fake-agent.ts`
(`FakeAgent.giveKey()`, `.waitFor()`, observations; against `E2E_BASE_URL` set
`E2E_FAKE_AGENT_URL` and `E2E_FAKE_AGENT_KEYS_DIR`, relative paths from the repo root).
The fake's behaviour follows the agent name's suffix (`-slow -fails -silent -asks -rejects
-blind-probe -strays -late -no-cancel -unavailable -drops -lingers`; `dev/fake-agent/README.md`).
`screenshots:phase6` (E2E_AI=1) writes `docs/screenshots/phase-6/` (11 screens × 1440
light/dark and 390 light). `screenshots:tour` (E2E_SSO=1 E2E_AI=1) writes the README's
product tour, `docs/screenshots/tour/` (`NN-<screen>-<variant>.png`: 12 screens at 1440
light, most also dark or 390, the PDF's first page and an email). Contract rules not built yet are pinned as
expected failures (`test.fail(true, …)` in Playwright, `@pytest.mark.xfail(strict=True)`
in pytest), which fail loudly once fixed: then delete the mark.
**Templates and research (Phase 8):** specs use `tests/support/research.ts`
(`researchTeam(alice, name, step, members)`: a private project with the step on and the
default checklist; `setResearchStep`, `answerItem`, `answerRequired`, `ideaResearch`,
`proposalTemplate` / `setProposalTemplate`, `similarIdeas`; `CHECKLIST`, `DEFAULT_SECTIONS`):
RS-01…RS-10 (`research.spec.ts`; RS-09 `@ai`), TPL-01…TPL-05 (`templates.spec.ts`;
TPL-05 `@ai`, the fake drafts any section key), A11Y8/MO8 (`a11y-phase8.spec.ts`). Keyboard
drags wait for the drag library's announcements ("Picked up"). Board cards in a project
with the step show "n/m" research badges; outlines list "Research and consultation" after
the sections when the appendix shows. `screenshots:phase8` writes
`docs/screenshots/phase-8/` (8 screens × 1440 light/dark and 390 light) and `pdf/`
(TOOLS-3 and GREEN-4).
**The researcher (Phase 8b):** specs use `tests/support/research.ts` `assignResearcher(api,
key, user | null, dueAt)` (a session: keys can't assign), `removeResearcher` (also Hand back),
`researchToDo`, `PRIVATE_PROJECT_LINE`, `GUEST_EMAIL_LINE`; RA-01…RA-11
(`research-assignment.spec.ts`), A11Y8B/MO8B/K8B (`a11y-phase8b.spec.ts`). Specs that assign
use their own private project and `newPeople`; every run makes another "Nora Quinn", so
pick a new person's picker row by their unique email. RA-03/06/07 read the seeded story
(bob, TOOLS-12; alice's GREEN-5 overdue) without changing it. `screenshots:phase8b` writes
`docs/screenshots/phase-8b/` (5 screens × 1440 light/dark and 390 light) and `emails/`.
`npm --prefix e2e run check` = tsc + prettier. Test plans and case IDs:
`docs/test-plans/phase-1.md` … `phase-8.md` (Phase 7: `performance.md`).

Wireframes: edit `docs/wireframes/0*.md`, then `python3 docs/wireframes/build_index.py`.

**Performance kit (Phase 7, `e2e/perf/README.md`, results in
`docs/test-plans/performance.md`):** `e2e/perf/stack.sh up|seed|stats|restart-api|down`
(`npm --prefix e2e run perf:stack`) starts the e2e stack with the large data set
(`backend/tests/perf/seed_large.py`: 10k ideas in Big Ideas, Pat Pending
`perf01@example.com` owes 1,000 evaluations) on :8320, Postgres `p7-perf-pg` on 55436,
prefix `p7-perf-` (`PERF_PORT`, `PERF_PG_PORT`, `PERF_PREFIX`, `PERF_STATE_DIR`
override; the SPA gets the image's `.br`/`.gz` twins, `PERF_PRECOMPRESS=0` serves it raw); then `uv run python -m tests.perf.load` in `backend/` (20 people, `--isolated
N`, `--think 0`), `npm --prefix e2e run perf` (browser timings, 4x CPU throttling) and
`npm --prefix e2e run perf:bundle` (first-load JavaScript). e2e's `tsc` covers `perf/`.
Timings in `tests/perf` freeze the test process's heap first (`frozen_heap`), as the API
does after startup; without it one full garbage collection over earlier tests' objects
lands on a single sample (a 400 ms "board -score" outlier in a full `-m slow` run).
Phase 8 added "board (research step)" (Internal Tools) and "similar ideas (12k ideas)"
timings and the statement budgets `list`/`board (research step)` 8, `idea.research` 6,
`idea.similar` 6 (`STATEMENT_BUDGET`); `seed_large` gives Internal Tools research data.
Phase 8b: a read over its p95 budget is measured again, up to three rounds, and judged by
its best (`best_p95`); every budget is 150 ms again (owned groups send 10 ideas);
`me.work` 11 and `me.work.counts` 4 statements. Timings taken while another agent drives
browsers or builds images measure the machine, not the code: rerun on a quiet machine.
Before/after comparisons: run the old commit's `backend/app` (`git archive`) with the
backend venv on another port against the same database (section 8 of the test plan).

Ports: Postgres 5432, Keycloak 8080, Mailpit 8025 (SMTP 1025), API 8000 (and
`/metrics` on 9090 unless `--reload`), Vite 5173, Playwright 5174, fake agent 8083, e2e
stack 8100 (Postgres 55433, Keycloak 8180, Mailpit 8125 / SMTP 1125, fake agent 8183),
perf stack 8320 (Postgres 55436),
`make demo` Mailpit 8026 and fake agent 8027, k3s API 16443, k3s ingress 18081. Dev logins, the demo
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

**Email in development** (`dev/README.md` "Email: Mailpit and the worker"): `dev/.env.example`
points the backend at the compose Mailpit (`SOUNDINGS_SMTP_HOST=localhost`, port 1025,
`security=none`) with `SOUNDINGS_TIMEZONE`; run `make -C backend worker` next to the
API and read mail at http://localhost:8025. Without `SOUNDINGS_SMTP_HOST` the app is
in-app only and platform admins see the "Email isn't set up" banner. Templates:
`uv run soundings email-preview -o /tmp/emails` and open `index.html`.

**AI in development** (`dev/README.md` "AI: the fake kagent"): `dev/.env.example` turns AI
on and points `SOUNDINGS_KAGENT_URL` at :8083; run the worker (runs need it) and `make -C
dev/fake-agent run`, then `make ai-smoke`, or register an agent in Admin settings → AI
agents and write its key to `dev/.fake-agent-keys/<namespace>.<name>` as `Bearer sdg_…`
(the fake re-reads it per request; without a key the agent is 404). What the fake saw of a
run: `curl -s localhost:8083/_fake/observations/<run id>`. There is no kagent or LLM here.

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
  `RequestModel` (rejects NUL, Unicode tag characters U+E0000–E007F and unknown fields;
  `SingleLine` refuses tag characters too); text that must show something uses
  `VisibleText` (free text: research answers) or `VisibleLine` (one-line titles, with
  `SingleLine`) from `app/schemas/base.py`; a list of titles under a unique `lower(...)`
  index is checked with `app/services/sql.py` `require_unique_lower` (422 when two collide
  under Postgres `lower()`, which isn't Python's `casefold`); cursors are validated on
  decode (`app/pagination.py`). Malformed input is a 4xx, never a 500.
- **Demo data:** `soundings seed --reset` needs `--force` once anyone who is not a demo
  person has an account; it refuses production without `--force`.
- **Email and notifications** (contract-phase3 §3, ADR 0003 amended): services call
  `app.services.activity.emit`; a **before-commit hook** (`app/db.py`) runs the fan-out
  once, after the request's last write, in its transaction: in-app notification rows,
  plus an `outbound_email` row and its `send_email` job (deferred on the same
  connection) for immediate email. Jobs or CLI code that emit activity must open their
  session with `session_scope(..., settings=settings)`, or their notifications are
  recorded with email off. Content is rendered at send time, after re-checking access,
  preference and age. Recipients pass the policy (`idea.view`, `evaluation.submit_own`);
  the actor, inactive, service and break-glass users never get anything. Emails and
  inbox items **never carry score data** (role matrix §3 rules 1 and 8). One plain
  ASCII recipient per email (`MAIL_ADDRESS_PATTERN`). Logs carry outbox ids, types,
  attempts and error classes; never addresses, subjects, bodies, tokens, SMTP
  credentials or server replies. One-line names that reach subjects (idea titles,
  display names) use `SingleLine` (`app/schemas/base.py`: no CR/LF or other control
  characters, U+2028/U+2029, bidi controls or Unicode tag characters). Unsubscribe tokens are scoped: a type's
  or the digest's link turns off only that; `all=true` needs a token scoped to `all`
  (the footer's "Unsubscribe from all email" link; else 403 `insufficient_scope`, c14).
  SMTP credentials reach worker pods only (the API gets `SOUNDINGS_SMTP_*_SET`).
  Events for more than 500 people fan out in a `notify_event` job; periodic jobs
  outrank sends; a worker pauses sending after 5 connection failures in a row.
- **Tests first** for authz, login matching and group sync, blind-evaluation
  visibility, API-key scoping and the email outbox.
- **Frontend:** only design-system components and tokens (no hex values, no arbitrary
  Tailwind values); loading, empty and error states, dark mode, keyboard, 390 px for
  every screen; API only through `src/api/client.ts`. Dialogs and sheets restore focus
  themselves (`components/ui/return-focus.ts`; `onCloseAutoFocus` only picks a
  replacement when the opener is gone); a busy `Button loading` stays focusable
  (`aria-disabled` + `aria-busy`), so `lib/focus.ts` `focusWhenRendered` keeps trying
  while a closing dialog's focus trap pulls focus back to it;
  server-filtered cmdk lists use `useTopResult` so Enter picks the visible top row, and
  pass empty/loading/error messages as `CommandList empty` (outside the listbox).
  Sheets open focused on themselves; closing one opened from a list row returns focus
  to that row (`lib/return-to-row.ts`). Phase 2 design-system pieces: `PasswordInput`,
  `ButtonShortcut` / `ariaKeys` (`kbd.tsx`; hints only from `sm` with a fine pointer),
  `Table cardFields="inline"` (one muted line per phone card), `FilterMenu`; toasts
  move above a side sheet's footer while it is open.
  Unsent drafts go through `lib/drafts.ts` (`draftKey(userId, name)`), which clears them
  on sign-out, 401 and user switch. Phase 3: the bell (`features/notifications/`) polls
  `get_notification_summary` every minute while visible (the poll doesn't keep the
  session alive); inbox `/notifications` (`g i`), Settings → Notifications, public
  `/unsubscribe?token=` (its fetch must keep `Accept: application/json`, or the API
  answers 303), Admin → Email (`features/admin/email/`); mentions are
  `@[Name](user:<id>)` tokens (`lib/mentions.ts`), shown as chips (only for text that
  is exactly a canonical token), never links; comment boxes show "@Name" with a tint
  (`features/idea/mention-highlights.tsx`) while the stored text keeps the tokens.
  "Mark all read" is a deferred commit: it waits for its Undo toast (`api/undo.ts`),
  like comment delete (so is discarding a proposal suggestion). Theme utilities for features: `mention-tint`,
  `max-h-popover-tall`, `avatar-tint`, `scrollbar-none` (`styles/theme.css`). Phase 5:
  rows that scroll sideways (`TabsList`, the settings row) fade the edge with more
  (`useScrollFade` in `components/ui/scroll-fade.ts` + `scroll-fade-x`); `CodeSnippet`
  wraps long lines; the secret dialog never puts the key in a toast, URL, storage or
  draft and `reset()`s the create mutation after closing. Phase 7: **Settings** is
  personal (Account, Notifications, API keys); platform admins get **Admin** in the
  sidebar (its sections listed under it; `/admin` lists them on phones) while the admin
  pages keep their `/settings/…` addresses (`features/admin/settings-frame.tsx`
  `ADMIN_PAGES`); "Everyone's keys" is `/settings/api-keys?everyone=1`. Public pages'
  messages (form off, broken links, confirmation, unsubscribe) use `PublicMessage`
  (`features/public/public-layout.tsx`). Tokens: `highlight-ring` marks the highlighted
  or selected item of every list (`data-[highlighted]:highlight-ring`), `accent-control`
  colours radios, switches, scores and selected tabs (3:1, `tokens.test.ts`).
  Single-key shortcuts can be switched off (`lib/shortcut-preference.ts`; `useShortcut`
  respects it). Tooltips on list rows mount on hover or focus (`HoverTooltip` in
  `components/ui/tooltip.tsx`). After a navigation that left focus nowhere,
  `components/layout/route-focus.ts` focuses the new page's h1; `NavigationProgress` shows
  a bar after 300 ms of a pending navigation. Board cards are named "Title (KEY)", so
  e2e and Playwright locators match `/\(KEY\)$/`, never `/^KEY/` (which now matches
  nothing, and a `toHaveCount(0)` on it passes without testing anything). Both test
  helpers have `bestPracticeViolations` (axe best-practice rules) next to the WCAG check
  (`frontend/tests/support.ts`, `e2e/tests/support/fixtures.ts`). My work shows the first
  50 evaluations due and 10 ideas per owned group, each with "Show more".
- **Proposals** (contract-phase4 §3.1–3.4): one Markdown text per fixed template section,
  saved per section with `base_version` (409 `proposal_conflict` carries `current`); a
  save locks the project `FOR KEY SHARE` then the idea `FOR SHARE`. Section Markdown is
  rendered by `app/proposals/markdown.py` exactly as the SPA's `Markdown` does (raw HTML
  dropped, images as links, http/https/mailto links only, headings one level down but
  never above h3 through the parser, tables capped; the PDF also prints each link's URL
  and bounds the layout at 5,000 boxes, `box_cost`). PDFs
  render in a `spawn`ed child process (`app/proposals/pdf.py`; 20 s limit, one render at
  a time, a warm child of about 190 MB per API process, its own temporary folder deleted
  when it goes; memory capped at half the container's, an allow-listed environment):
  any script that renders a PDF needs an `if __name__ == "__main__":` guard
  (`pdf_child.render_document(ExportDocument(...))` renders one in-process for a quick
  look; e2e's `renderPdfPages` turns pages into PNGs with pdf.js, no poppler here). WeasyPrint gets a fetcher that answers only `data:` logos and
  `soundings-font:<font>-<weight>[-italic][-ext]` names (`app/proposals/fonts.py`,
  `app/assets/fonts/README.md`); only validated hex colours and fixed font families reach
  its CSS. Importing WeasyPrint turns on Pillow's `LOAD_TRUNCATED_IMAGES` for the whole
  process (only the child imports it in production). The SPA lazy-loads the editor.
- **Public submission** (contract-phase4 §3.5–3.9): public routes are under
  `/api/v1/public/`, writes must be JSON (415), throttles use the trusted-proxy client
  address (`app.auth.throttle.client_key`), and they never return private data, scores,
  people or the idea's current text (tracking shows the title and summary *as
  submitted*). Tokens travel only after `#` (`/track#…`, `/<slug>/verify#…`; the old
  `/verify#…` still works) and in bodies, never in URLs the server sees, logs or audit. Held ideas (`ideas.held_for`) appear in
  no list or count for anyone: lists use `listed_ideas`; ideas held for confirmation are
  404 even for admins; writes on ideas held for moderation are 409
  `awaiting_moderation` (c19, watching too). The honeypot is checked last. Submitter
  emails carry fixed text and the project's branding (the confirmation email has no
  tracking link; status emails have "Stop these emails" in the footer,
  `EmailContent.stop_url`); the per-address confirmation limit counts
  `confirmation_email_sends` (keyed hash, survives erasure); erasure
  (`app/public/erasure.py`) also deletes the idea's submitter outbox rows. Whatever
  releases a hold sets `public_submissions.reached_team_at` (tracking's "With the
  team").
- **Branding** (contract-phase4 §3.10–3.11, ADR 0012): resolve with
  `app.services.branding` (`effective_branding`, `email_branding_for`, `logo_image`;
  cached 5 s per process, cleared on save, so other replicas lag up to 5 s). Colours are
  `#rrggbb`, fonts one of four `BrandFont` keys; logos and favicons are PNG (re-encoded)
  or allow-listed SVG (re-serialised), served with `nosniff` and a sandboxing CSP and
  shown only through `<img>` / `<link rel=icon>`; in dark mode the SPA puts logos on a
  light plate (`logo-plate`), and a public header shows the logo alone. A project
  override with its own logo and no app name resolves its app name to the project's
  name (UX M3; `resolve` and the settings preview). The signed-in app always uses the
  global branding; its UI text stays Inter (the brand font is `font-brand`: titles,
  wordmark, public pages).
- **API keys and MCP** (contract-phase5, role matrix §5–6, ADR 0013): `ApiKeySource` is
  the first principal source; a bearer token never falls back to the cookie and needs no
  CSRF. Effective permission = the owner's live permission ∩ scopes ∩ projects, through
  the same policy; every operation is classified for keys in
  `app.authz.keys.ROUTE_KEY_ACCESS` (deny by default; a new route needs a row);
  `require_view` needs `read`. Key management, admin, settings, the inbox, `idea.delete`
  and `idea.moderate` are session only. `get_principal` returns the stored principal
  as is. Deactivation revokes keys (`api_keys.service.revoke_all_for_user`). Service
  accounts never own an idea (c4, c21) or hold the admin role (409 `system_account`),
  and their first submission is left out of the aggregate. `/mcp` (`app/mcp/`) reuses the
  REST services for every tool; the one dispatcher validates, applies the write cap,
  runs one transaction and writes exactly one `mcp.call` audit entry per `tools/call`
  (never arguments; deleted after 90 days by the hourly schedule). Held ideas are
  `not_found` through MCP for everyone. Never log or return a key after creation, the
  `Authorization` header or tool arguments. The key check and `last_used_at` run in one
  short transaction before the request's session (`app/api_keys/verify.py`); each tool
  re-reads the key and owner in its own transaction (tool error `unauthorized`). At
  `/mcp`: key → rate → c15; c15 and budget refusals are audited once per key a minute.
  Write tools' inputs forbid unknown arguments (`MCP_WRITE_INPUT_CONFIG`), read tools'
  ignore them; every result string goes through `app/mcp/text.py` (no invisible
  characters). A service account with no role is a private non-member everywhere
  (internal projects too), and its `search_users` finds only co-members. Key responses
  carry `unavailable_project_count` (and admin `projects[].owner_can_view`).
- **AI assistance** (contract-phase6, role matrix section J, ADR 0014): runs are rows
  (`ai_runs`, `ai_run_events`) executed by `run_ai` on the worker's own `ai` queue and
  pool (`SOUNDINGS_AI_MAX_CONCURRENT_RUNS`; email and the schedules never wait behind
  them); state changes are compare-and-set (`app/ai/transitions.py`, lock order project →
  idea → run), a run has a hard deadline (`tasks/cancel`, then `timed_out`), cancel is
  cooperative, a stopping worker ends its runs `worker_lost`; one active run per idea +
  agent + kind (+ section) by a partial unique index (repeat = 200 with that run); 20
  requests per person an hour. The A2A URL is only ever `agent_a2a_url(kagent_url,
  protocol, namespace, name)`: no URL field, no redirects, card URLs ignored,
  `trust_env=False`. The A2A message (`run_message`) holds references and instructions,
  never keys, URLs or idea text; A2A text and artifacts are ignored: results come back
  through MCP as the agent's service account and are matched to the run. **c22**: an
  agent's key is MCP-only (REST 403 `insufficient_scope`); every call names its open run
  (`run_id`, required for agents, ignored for people; `app/ai/scope.py`), checked before
  any idea is looked up (another idea, existing or not: `ai_run_not_active`), and reaches
  only that run's idea, writing only through the run kind's tool (`AGENT_RUN_WRITE_TOOLS`).
  **Rule 9**: service accounts are always blind (`queries.score_visible`, the policy) and
  see their own evaluation only in their evaluate run. An agent's text loses bidi and
  zero-width characters before it is stored. Agents register only in
  `SOUNDINGS_AI_AGENT_NAMESPACES` (default `soundings`, never empty); the break-glass
  account can't widen an agent; deleting a research note is audited `ai_note.delete`.
  AI evaluations are excluded from aggregates until `set_evaluation_inclusion`; a changed
  re-submission resets it. Run events and lists carry no score data and only Soundings'
  fixed sentences (never agent text). SSE (`app/ai/sse.py`): one poller per run per
  process, `Last-Event-ID` replay, 204 after the final event, 5 streams per person and
  100 per API process, a re-check every 30 s; the SPA falls back to polling `get_ai_run`.
  The SPA shows one run row per agent and kind (`features/ai/run-card.tsx`; steps behind
  "Steps", older runs under "History"), words errors by `error.code` (`runErrorWords`)
  and keeps the server's sentence under Steps. Agent text in the SPA
  is `<Markdown untrusted>` (http/https links only, `rel="noopener noreferrer nofollow"`,
  host shown), with `AiBadge` wherever an agent's work appears (evaluator rows, cards,
  comparison columns, notes, suggestions, feed lines).
- **Hardening (Phase 7, contract-phase7, decisions Phase 7):** the image defaults to
  `SOUNDINGS_ENVIRONMENT=production` (everything that runs it for development says so);
  session writes are limited to 120 a minute per person (429 `rate_limited`; the e2e and
  perf stacks raise `SOUNDINGS_SESSION_WRITES_PER_MINUTE`); the session keep-alive runs
  after the response in its own transaction (`app.middleware.SessionTouchMiddleware`);
  `GET` JSON of 1 KB+ is gzipped unless the endpoint set `no-store` itself (a body with a
  secret must: BREACH) and the image ships `.br`/`.gz` twins of the SPA
  (`scripts/precompress-assets.mjs`); connections run without parallel query workers;
  OpenAPI and Swagger UI need a caller in production; account-kind decisions are policy
  traits (`app.authz.is_agent` …, role matrix §1a); PDFs are tagged; emails are one
  `role="article"` landmark; the bundled Postgres's app role is not a superuser.
- **Proposal templates** (contract-phase8 §2, ADR 0015, `app/proposals/template.py`): a
  section is always addressed by its **key** (`varchar(40)`, `^[a-z][a-z0-9_]{0,39}$`, no
  foreign key; the eight built-in keys `summary` … `next_steps` stay even when renamed); a
  new section's key comes from its title (`section_key_for`: slug, `_2` on a clash with any
  key the project ever had) and never changes; the API never takes a key for a new
  section. `replace_proposal_template` (project `FOR UPDATE`, audited, last write wins)
  archives a removed key that anything refers to (text, thread, suggestion, AI run), else
  deletes it; putting the key back restores it with its text. Proposals, threads,
  suggestions, exports, "Draft with AI" and MCP list only active sections in template
  order; a removed or unknown key is 422 `unknown_section` (after the 403s, before the
  409s). New projects get `app/domain/template_defaults.py`. Never assume eight sections
  (the fake agent reads them from `get_proposal`).
- **The research step** (contract-phase8 §3, role matrix F/K, `app/services/research.py`):
  `IdeaStatus.research` exists in a project only while its step is on (else 409
  `research_step_off`); per-project order is `app.schemas.research.lifecycle(step)`
  (board, status dialog, `Project.lifecycle`), cross-project views use
  `CANONICAL_STATUS_ORDER` (Research after New). Turning the step off or moving it is 409
  `ideas_in_research` (with the count). **The gate** guards crossings only
  (`crosses_gate`; reopening counts from the status the idea was closed from), in one
  place: `ideas.change_status` (also `create_proposal`'s move) plus one research-service
  check for the first evaluator invite and "Ask AI to evaluate"; refused moves are 409
  `research_incomplete` with `open_items` and `can_override`. "Move anyway" is the request
  flag `override_research` (+ optional `override_reason`), rule `idea.research_override`
  (project and platform admins, session only), audited, `research_overridden: true` in the
  status event. Never bypass it (the seed answers first). Answers (`idea.answer_research`:
  the owner and admins; a `write`-scope key; never an agent) are plain text without
  invisible characters, need a visible one, are not audited or notified.
  `IdeaSummary.research` ("2/3") only for an idea in Research or the status before it, in
  one grouped statement per page. "Similar ideas" uses the trigram GiST indexes (0013):
  the 20 nearest titles and summaries, ≥ 0.3, top 5, never held ideas, no scores. Public
  tracking shows the status before Research (`public_status`) and emails the submitter
  only when that changes. The exports end with "Research and consultation" while the step
  is on and an item is answered. SPA: statuses from `Project.lifecycle` (`lib/status.ts`),
  one gate dialog for every guarded action (`features/research/research-gate-dialog.tsx`,
  state in `api/research.ts`); text typed into a section removed meanwhile is kept per
  user (`proposal-removed:<KEY>:<section>` draft) and the editor re-reads the proposal
  after the save's 404.
- **The researcher and guest researchers** (contract-phase8b, role matrix column R and table
  L, ADR 0016, `app/services/research_assignment.py`): one optional researcher per idea
  (`ideas.researcher_id`, `research_due_at`; nobody = the owner does it), set in a session
  only by `idea.assign_researcher` (owner, project and platform admins; c25: in a private
  project only admins name someone without a role there), handed back with
  `idea.release_researcher` (a `write` key may); never a service account, break-glass or
  inactive account (422 `researcher_not_eligible`). Past Research the researcher (not the
  owner or an admin) can't change answers (c26) and nobody new is asked (both 409
  `research_finished`; the SPA offers Remove there); tests that need a researcher past
  Research assign while it is New or in Research, then move it. Closing the idea, turning the step off,
  deactivation and losing one's role in a private project (`left_project`: every path that
  removes project roles calls `research_assignment.roles_before` / `end_after_role_loss`)
  clear it, audited, answers and the due date kept; archiving only suspends it. A
  researcher with no role in a private project is **column R**: that one idea through
  `RESEARCH_GUEST_ACCESS` (`app/authz/guest.py`; deny by default: a new idea route or MCP
  tool needs a row, a meta-test fails otherwise), never score data, the evaluation area,
  the proposal, the AI panel or the project (404); the feed is the allow-list
  `RESEARCH_GUEST_ACTIVITY_TYPES` (a new feed type goes there or in the evaluation set; a
  schema test fails otherwise) and the inbox `RESEARCH_GUEST_NOTIFICATION_TYPES`. Lists
  stay project-scoped (`listed_ideas`); only search, MCP `search_ideas`, the inbox, "Research
  to do" and Similar ideas add `researched_ideas()`. In internal projects an outside
  researcher keeps the non-member view and gains answering, commenting and Hand back. In
  nested `EXISTS` subqueries use `correlate_except` (an uncorrelated `ideas` once counted
  any idea's answer). Notifications `researcher_assigned` ("Asked to research", one per
  assignment) and `research_reminder` (2 days before and on the day at the
  digest hour while research is to do). "Asked to research" emails wait
  `RESEARCHER_EMAIL_HOLD` (5 min, `app/notifications/fanout.py`) when the idea asked
  someone less than 5 minutes before (and at most `RESEARCHER_EMAIL_CAP`, 20, per person
  an hour): a test that reassigns within 5 minutes fast-forwards the outbox row and its
  `send_email` job (`test_phase8b_acceptance.py`). A list that may show a guest's idea
  sorts `updated` with `Sort(token, guests=True)` (`app/services/board.py`: on
  `visible_last_activity`, the guest feed's newest event), as MCP `search_ideas` does;
  project-scoped lists keep the column. SPA: `features/research/research-assignment.tsx`
  (the line, the picker dialog, "Start research", Hand back), `features/work/research-to-
  do.tsx`; `IdeaPermissions.can_view_project` false = the guest's page (Overview only,
  breadcrumb text); any write refused with 404 re-checks the idea on screen
  (`api/query.ts`), so a guest unassigned meanwhile sees "doesn't exist".
- **Air-gapped:** no CDN assets, web fonts or telemetry; everything is bundled.
- **Dependencies:** one-line justification each, in the owner's report.
- **Commits** (lead): small conventional commits, no secrets.

## Environment gotchas (this build machine)

- **Docker:** if `docker info` fails, start the daemon:
  `(nohup dockerd > /tmp/dockerd.log 2>&1 &)`. Docker Hub pulls go through the
  `mirror.gcr.io` registry mirror (direct Hub pulls may 429). Pre-pulled:
  `postgres:16-alpine`, `python:3.12-slim`, `node:22-alpine`, `alpine/helm:3.16.2`,
  `rancher/k3s:v1.31.4-k3s1`, `keycloak/keycloak:26.0`, `axllent/mailpit`,
  `testcontainers/ryuk:0.11.0`, `ubuntu:24.04` (the image's base).
- **Blocked hosts:** quay.io, get.helm.sh, GitHub release downloads, ui.shadcn.com,
  kagent.dev, modelcontextprotocol.io, deb.debian.org (the image uses Ubuntu's
  archive.ubuntu.com, which works), and ghcr's blob host
  `pkg-containers.githubusercontent.com` (`oci://ghcr.io/...` answers the manifest, so
  kagent's Helm chart and images can't be pulled; `make k3s-kagent-crds` takes the CRDs
  from kagent's git tag instead). The Docker daemon's own proxy setting is stale, so
  `docker pull ghcr.io/...` fails too. pypi.org, registry.npmjs.org and code.claude.com
  work. To check a library's API, read the installed source.
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
  command line and kills it; stop servers by pid. Page tests that wait for an error
  state shown after the client's query retries (about 3 s) need a 10 s timeout: the
  default 5 s flakes while backend tests or image builds load the machine.
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
- **k3s upgrades between values files:** `make k3s-install` on top of a release installed
  another way (the operator guide's one-command quick start) fails with "updates to
  statefulset spec … are forbidden", because `dev/k3s-values.yaml` sets a 1 GiB Postgres
  volume and the default is 8 GiB: run `scripts/k3s-install.sh --set image.repository=…
  --set image.tag=… --set postgresql.persistence.size=8Gi` (the make target sets the
  image from `IMAGE` for you; the script alone keeps `soundings:dev` with `pullPolicy:
  Never`, so pods stick in `ErrImageNeverPull` until `--wait` times out).
- **CD rehearsals:** `GIT_SSL_CAINFO` overrides git's `http.sslCAInfo` (set it, not the
  config, for an internal CA). `kubectl auth can-i create pods/exec` asks about a pod
  named "exec": use `--subresource=exec`. The kubelet deletes imported (unused) images
  when the disk is over 85 % full: import the image again before a rollback to it. A
  bind-mounted script edited while a container runs it breaks that run (bash reads it as
  it goes): edit between runs.
- **k3s NetworkPolicy** is enforced (kube-router) and on by default in the chart; a new
  pod's address is admitted a moment after it starts, so in-cluster clients started
  fresh (the `helm test` pod) retry. Through Traefik an oversized *chunked* POST may get
  502 instead of the app's 413 (the smoke accepts that and checks 413 in the pod).
- **SSO e2e data:** an identity links to an account once, so some `@sso` specs need a
  fresh seed and realm (the local stack resets both on start; reseeding uses
  `seed --reset --force` and fails loudly). Use run-unique group names
  (`group_name_taken` otherwise).
- **Mailpit and the worker:** email goes out only while a worker runs (`make -C backend
  worker`, the e2e stack and `make demo` start one). After an SMTP failure the worker
  retries 30 s, 1 min, 2 min… later, so a test that restarts Mailpit allows about 2.5
  minutes. A worker that reaches Mailpit by container name (`make demo`) reports a
  stopped Mailpit as "connection failed" (DNS), by IP as "connection refused". Mailpit
  refuses to start with both `MP_SMTP_REQUIRE_STARTTLS` and `MP_SMTP_AUTH_ALLOW_INSECURE`.
  Mailpit's inbox is shared by a whole e2e run: filter by recipient and time. aiosmtplib
  tries STARTTLS opportunistically unless told not to: `security=none` passes
  `start_tls=False`.
- **MCP SDK (`mcp` 2.2):** it uses `httpx2` (not `httpx`) for its client; `send_ping`
  raises a DeprecationWarning, which pytest's warnings-as-errors turns into a failure (send
  a raw `ping`); its streamable-HTTP session manager keeps its task group in a task of its
  own (pytest-asyncio enters and leaves the lifespan in different tasks); its loggers are
  held at WARNING (it logs every request at INFO). Claude Desktop needs the `mcp-remote`
  bridge (custom connectors only do OAuth). On k3s's Traefik 2.11 an `Exact` `/mcp`
  Ingress path loses to `/`: use `Prefix`.
- **Undo inside sheets:** a toast's Undo can't be clicked while a modal sheet is open
  (the sheet blocks outside clicks), so destructive actions in sheets confirm instead.
- **Fake agent:** the compose service (profile `ai`) reaches the API on the host, so run
  the API with `SOUNDINGS_HOST=0.0.0.0`; it needs `SOUNDINGS_DEV_FAKE_AGENT_USER`. a2a-sdk
  1.2.1's 0.3 adapter answers every A2A error as −32603: the fake maps them back to 0.3's
  codes (−32001, −32002). There is no kagent controller or LLM here: anything "verified"
  for AI is against the fake unless it says kagent's CRDs.
- **Library pins that matter:** TypeScript 5.9.x (7.x breaks typescript-eslint and
  openapi-typescript), MSW 2.15, `mcp` 2.x (2.2: the low-level `Server`, not `FastMCP`), WeasyPrint 70
  (new URL-fetcher API), Python `altcha` 2.x with the `altcha@3` widget, `a2a-sdk[http-server]`
1.2.1 (the fake agent only; the backend's A2A client is hand-written on httpx). OIDC is httpx +
  `joserfc` (no Authlib: `authlib.jose` is deprecated and its Starlette client isn't used).
- **Shared machine** (4 CPUs, 15 GB): use your assigned ports and container prefix,
  stop what you start, never kill other agents' processes or containers. `make -C backend
  test-slow`'s My work p95 sits near its 150 ms budget here (about 140 ms): run it on an
  idle machine, not straight after another test session. On 2026-10-08 this machine was
  slower: an owner's My work 150-187 ms and the board by score 128-182 ms from run to run,
  for 0.1.0's code too (`git archive 0046a9a`, same venv), so compare against the old
  commit before calling a p95 miss a regression.

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
- **Phase 3** (email and notifications): one fan-out (before-commit hook) writes in-app
  notifications and outbox rows for seven types (made owner, asked to evaluate,
  reminders, all evaluations in, status changed, comment, @mention); transactional
  outbox sent by `soundings worker` (lease, 12 attempts with backoff, sweep, send-time
  re-checks, no score data); per-type preferences (immediate / daily digest / off),
  daily digests and reminders in the instance time zone, signed unsubscribe links (RFC
  8058 one-click), branded table-based HTML + text templates (`soundings
  email-preview`), the bell and inbox (`g i`), Settings → Notifications, the
  unsubscribe page, Admin → Email (settings in effect, test email, outbox with retry),
  admin banners, @mention picker and chips; SMTP via Helm values / `SOUNDINGS_SMTP_*`
  with a Secret and CA bundle; Mailpit in dev, the e2e stack, `make demo`, CI and k3s
  (`SMTP=1`). Integration (2026-10-01): every check green in both e2e modes, QA's
  K3-1…K3-5 fixed; test plan `docs/test-plans/phase-3.md`, screenshots
  `docs/screenshots/phase-3/` (+ `emails/`, `mock/`). Security and UX reviews applied
  (linear excerpts, send breaker and job priorities, mention cap lock, one-line email
  values, worker-only SMTP credentials, `notify_event` for large audiences, scoped
  unsubscribe links with a footer "Unsubscribe from all email", input hygiene for bidi
  and line separators, retry and inbox focus, "@Name" in the composer). Closed on
  2026-10-01 with every check green in both e2e modes and a clean k3s install with
  Mailpit (`SMTP=1`), SMTP outage drill, upgrade and smoke:
  [docs/phase-summaries/phase-3.md](docs/phase-summaries/phase-3.md) (known issues and
  deferred items there). Decisions: `docs/decisions.md` (Phase 3). Stop for the
  human's review before Phase 4.
- **Phase 4** (proposals, public submission, branding): proposals over the fixed
  eight-section template (per-section autosave with `base_version` conflicts, margin
  threads, Markdown and branded PDF export in a time-limited child process with a
  local-only fetcher and bundled fonts); the public form at `/{slug}/submit` (honeypot,
  per-address and per-project limits, ALTCHA with replay protection, JSON-only writes,
  optional email confirmation and moderation, private `/track#` links, `/verify#`
  confirmation on click, submitter emails, "Delete my details", admin erasure and
  retention); held ideas invisible in every list; the moderation queue; global and
  per-project branding (colours, bundled fonts, PNG/SVG logo and favicon stored in the
  database, footer) applied at runtime to the SPA, public pages, emails and PDFs; the
  image on Ubuntu 24.04 (PDF export works in it); `make public-smoke`. Integration
  (2026-10-02): every check green, QA's K4-1…K4-5 and PDF nits fixed. Security review
  (PDF layout and memory bounds, keyed per-address limit, no tracking link in the
  confirmation email, form-lookup throttle, setuid bits, renderer environment) and UX
  review (focus, moderation counts, branding preview, one identity per audience,
  `/<slug>/verify`, PDF hierarchy and links, `reached_team_at`, migrations 0008 and
  0009) applied. Closed on 2026-10-02 with every check green in both e2e modes and a
  clean k3s install with Mailpit, public-form and PDF smoke through the ingress,
  upgrade and smoke: [docs/phase-summaries/phase-4.md](docs/phase-summaries/phase-4.md)
  (known issues and deferred items there). Test plan `docs/test-plans/phase-4.md`,
  screenshots `docs/screenshots/phase-4/` (+ `pdf/`, `emails/`, `mock/`). Decisions:
  `docs/decisions.md` (Phase 4). Stop for the human's review before Phase 5.
- **Phase 5** (API keys and MCP): personal API keys (`sdg_` + lookup id + secret, SHA-256
  stored, shown once; scopes `read`/`write`/`evaluate`/`mcp` with `write`/`evaluate`
  including `read`; optional expiry and project restriction; 25 per user; dormant after 30
  days without sign-in; immutable) as the first principal source, narrowed by the policy
  and the per-operation key table (`app/authz/keys.py`); throttles (30 failures per
  address, 300 requests and 30 writes per key a minute); Settings → API keys (presets, the
  one-time secret with Claude Code / Claude Desktop / `mcpServers` / curl examples,
  revoke) and Settings → All API keys; the MCP server at `/mcp` (`app/mcp/`: stateless
  JSON, Origin check, Host-check exempt, nine tools over the REST services, blind and
  hold filtering, one `mcp.call` audit entry per call, 90-day retention); proposal
  suggestions (`propose_proposal_section`, REST create/list/accept/discard, the editor's
  cards with Accept/Discard); service accounts never own or admin and their evaluations
  stay out of the aggregate; Helm `ingress.mcp`, `kagent.*` (RemoteMCPServer example,
  NetworkPolicy), `make mcp-smoke`, `k3s-smoke MCP=1`. Integration (2026-10-06): QA's six
  defects fixed (deactivation revokes keys, `/.well-known` kept from the SPA, agents'
  evaluations out of the aggregate, no agent owners or admins, `get_principal`, the
  `mcp.call` cleanup scheduled) and the visual nits (wrapping code blocks, faded scroll
  edges on tab rows, a "Full access" chip, admin column widths, blank diff lines); every
  check green in both e2e modes, `make mcp-smoke` against the e2e stack. Guides:
  `docs/mcp.md`, user and operator guides; test plan `docs/test-plans/phase-5.md`,
  screenshots `docs/screenshots/phase-5/` (+ `mock/`); decisions `docs/decisions.md`
  (Phase 5). Security review (pool-safe key check, keys re-checked inside each tool call,
  refusals rate-limited and audited once a minute, service accounts NMp without a role,
  invisible characters stripped from results, `hide_parameters`) and UX review (plain-words
  key access, "I've copied it", expiry warnings, word diffs, focus, State menu, admin
  layout) applied; lead decisions at the close: assistant presets and the Proposal tab's
  suggestion count accepted, `unavailable_project_count` / `owner_can_view`, write tools
  forbid unknown arguments, tag characters refused in request text, more `UNTRUSTED`
  fields, agents search co-members only. Closed on 2026-10-06 with every check green in
  both e2e modes (one Phase 1 page test flaked under load and passed 5 of 5 on rerun) and
  a clean k3s install (`SSO=1 SMTP=1 MCP=1`, as CI), MCP smoke through the ingress and
  the in-cluster SDK client, upgrade to two API replicas and smoke:
  [docs/phase-summaries/phase-5.md](docs/phase-summaries/phase-5.md) (known issues and
  deferred items there). Stop for the human's review before Phase 6.
- **Phase 6** (kagent AI assistance): Admin settings → AI agents registers kagent agents
  (namespace/name, protocol `kagent_v0_10` or `kagent_v1_0`, purposes, projects) with a
  service account and one key (shown once with its Secret and `RemoteMCPServer`; rotate,
  disable revokes, Test connection fetches the card); "Ask AI to evaluate", "Research
  this" and "Draft with AI" start durable runs (`ai_runs`, `ai_run_events`) that the
  worker's own `ai` pool sends over A2A (hand-written httpx client, URL built from
  `SOUNDINGS_KAGENT_URL` + namespace/name only) with a deadline, cooperative cancel
  (`tasks/cancel`), retries before a task exists, the sweep and `worker_lost`; agents act
  back through `/mcp` (ten tools: `add_research_note`), confined by c22 (MCP only, open
  runs only, one write tool per kind) and always blind (rule 9); AI evaluations carry a
  rationale and cited sources per criterion, an AI badge everywhere, and are left out of
  the aggregate until the owner or an admin includes them (a changed re-submission is left
  out again); research notes in the feed (`ai.delete_note`), drafts as Phase 5
  suggestions; live progress over SSE (replay, 204 at the end, polling fallback); Helm
  `features.ai`, `kagent.*`, `ai.*`, example Agents/`RemoteMCPServer`s, NetworkPolicy for
  agent pods and egress to the controller. No kagent controller or LLM here: Soundings'
  fake agent (`dev/fake-agent`) stands in, and the manifests are checked against kagent
  v0.10.2's real CRDs. Integration (2026-10-06): QA's visual list and nits fixed (one
  evaluate label, agent names and AI badges in the comparison and the feed, the URL
  preview, key dialog focus, "Draft" on phones, admin list refresh, `cancel_requested`
  only while active, AAK-03's race, `demo.sh down` removes its key); every check green:
  backend (6260 tests), frontend check + test:pw, e2e in all three modes (default, SSO,
  `E2E_AI=1`), `make image`, `make k3s-install AI=1 MCP=1` + `k3s-smoke AI=1 MCP=1` with
  that image. Guides: user guide "AI assistance" and "AI agents", operator guide "kagent
  integration", `docs/mcp.md` §5; test plan `docs/test-plans/phase-6.md`; screenshots
  `docs/screenshots/phase-6/` (+ `mock/`); decisions `docs/decisions.md` (Phase 6).
  Security review (H1: every MCP tool takes `run_id`, required for agents, binding each
  call to that open run's idea before any lookup, which also fixes N1; M1 an agent's own
  evaluation only in its evaluate run; M2 bidi and zero-width characters stripped from
  agent text and isolated on display; L4 audit incl. `ai_note.delete`; L5 break-glass
  can't widen an agent; L6 100 streams per process; L7 5 s cancel and card deadlines; L8
  `SOUNDINGS_AI_AGENT_NAMESPACES` defaults to `soundings`) and UX review (focus stays put
  when a run ends; busy buttons keep focus; one run row per agent and kind with Steps and
  History; errors worded by `error.code`; "1 AI evaluation not counted · Review") applied;
  lead decisions at the close: H1 option 2 accepted, `ai_note.delete`, the "would be 3.6"
  preview declined. Closed on 2026-10-06 with every check green: backend (6281 tests,
  `test-slow`), frontend check + test:pw, e2e in all three modes (default, SSO,
  `E2E_AI=1`), `make image`, and a clean k3s install as CI (`SSO=1 SMTP=1 MCP=1 AI=1`:
  kagent v0.10.2 CRDs with a dry run of every manifest, the AI smoke through Traefik
  against the fake), upgrade to two API replicas and smoke:
  [docs/phase-summaries/phase-6.md](docs/phase-summaries/phase-6.md) (what is verified
  against real kagent vs the fake, known issues and deferred items there). Stop for the
  human's review.
- **Phase 7** (polish and hardening, release **0.1.0**): no new feature; four reviews
  against the running app and their fixes. Security (OWASP ASVS L2): the image defaults
  to production and refuses the development key, ALTCHA bounds, 120 session writes a
  minute (429 `rate_limited`), `soundings anonymise-user`, a non-superuser bundled Postgres
  role, the API's map for signed-in callers in production, the metrics port policy,
  bounded SSO callback, policy traits for account kinds, `k3s-install PROD=1`, a CI audit
  job. Accessibility (WCAG 2.2 AA): single-key shortcut switch, `highlight-ring` and
  `accent-control`, focus never hidden and moved to the h1, 10 s Undo, rubric Move
  up/down, tagged PDFs, email landmarks. UX: Settings personal and **Admin** for platform
  admins, four project settings tabs, one API keys page, the status-driven blue button,
  first-run welcome, phone-first project header. Performance (the kit in `e2e/perf/`,
  10k ideas): `GET /me/work/counts`, 50 evaluations due a page, `pending_moderation_count`
  (contract-phase7), Brotli/gzip, first-load JS 1,026 → 636 kB, memoised list rows, the
  idea route preloaded when idle, 10 ideas per owned group in My work. Docs: the README
  with the tour (`screenshots:tour`), `docs/RELEASE-NOTES.md`, guides checked against the
  app. Closed on 2026-10-07 with every check green: backend (6,336 tests, `test-slow`),
  frontend check + test:pw, e2e in all three modes (default, SSO, `E2E_AI=1`), fake agent,
  `make image` (524 MB), and on k3s the operator guide's one-command `helm install`
  (production, break-glass, `PROD=1` smoke), then an upgrade as CI (`SSO=1 SMTP=1 MCP=1
  AI=1`) and to two API replicas with every smoke:
  [docs/phase-summaries/phase-7.md](docs/phase-summaries/phase-7.md); performance numbers
  and the remaining misses in `docs/test-plans/performance.md` §8–9 and the release notes'
  known issues; decisions `docs/decisions.md` (Phase 7 sections). Stop for the human's
  review.
- **Phase 8** (product owner's change after 0.1.0; `docs/decisions.md` "Phase 8 (product
  owner, 2026-10-07)", contract-phase8, ADR 0015): **per-project proposal templates** (1-12
  sections with a title and hint, stable keys, archive/restore with text kept; editor,
  threads, suggestions, "Draft with AI", MCP and both exports follow the template live) and
  an optional **research step** per project (Off / Before evaluation / Before proposal; the
  Research status and column; a checklist of free-text answers; the gate with an admin's
  "Move anyway", audited; "Similar ideas" over trigram GiST indexes; the "Research and
  consultation" appendix in the editor and exports; public tracking shows the stage before
  it). Migrations 0012 (templates and research, existing projects keep the eight sections,
  step off) and 0013 (GiST indexes); head 0013. Project settings has six tabs (General ·
  Members · Rubric · Research · Proposal · Public form). Demo: Internal Tools before
  evaluation with a six-section template, Sustainability before the proposal with "Carbon
  impact", Customer Innovation unchanged. Integration (2026-10-08): QA's P8-QA-F1 (the editor
  re-reads the proposal after a removed section's 404), P8-QA-P1 (the fake agent drafts any
  section key) and nits N1-N3 fixed and their marks removed; six board columns fit at 1440
  px with wrapping card footers. Checks: backend (6,938 tests), frontend check (626 vitest)
  + test:pw, e2e in all three modes (default 286, `E2E_AI=1` 326, `E2E_SSO=1` 307 passed,
  none failed), fake agent, Helm, scripts, `make gen-api` (no diff), `make image` (524 MB);
  on k3s an upgrade from 0.1.0's image with demo data (0011 → 0013) and every smoke as CI
  (`SSO=1 SMTP=1 MCP=1 AI=1`). `test-slow`: only an owner's My work p95 misses its 150 ms
  here (156-214 ms; 0.1.0's code 162 ms on the same machine that day). Test plan
  `docs/test-plans/phase-8.md`; screenshots `docs/screenshots/phase-8/` (+ `pdf/`), every
  earlier set re-captured, tour shots 13-14. Stop for the human's review.
- **Phase 8b** (product owner's change after Phase 8; `docs/decisions.md` "Phase 8b (product
  owner, 2026-10-08)", contract-phase8b, ADR 0016, role matrix column R / table L): **one
  researcher per idea** (anyone active, also outside the project; nobody = the owner) with an
  optional research due date; assigned by the owner and admins in a session (in a private
  project only admins name an outsider, c25), handed back by the researcher; cleared by
  closing, the step off, deactivation and leaving a private project (`left_project`);
  "Asked to research" and "Research reminder" notifications (preferences, digest,
  unsubscribe, two email templates); My work's "Research to do" and the sidebar's Research
  badge; "Start research" asks who and by when; Research cards show the researcher. A
  **guest researcher** (no role in a private project) reaches that one idea only, through
  the deny-by-default `RESEARCH_GUEST_ACCESS` table: overview, comments, the feed's
  allow-list, the checklist, Similar ideas among what they see anyway; never score data,
  the evaluation area, the proposal, the AI panel or the project (404); search, ⌘K, My work,
  the inbox and MCP show that idea and nothing else of the project; access ends at the next
  request. Phase 8 follow-ups: owned groups send 10 ideas (both p95 budgets back to 150 ms),
  removed template sections and checklist items keep their position, "Ask AI to research".
  Migration 0015 (head 0015). Integration (2026-10-09): QA's P8B-QA-F1 (any write refused
  with 404 re-checks the idea, so a guest unassigned meanwhile sees "doesn't exist"; RA-10's
  mark removed), N1 (the picker's highlight starts on the chosen owner), N2 ("No due date"
  beside the field), N3, and from the real-stack walkthrough the owner's picker keeping an
  admin-named outsider as its own row. Checks: backend (8,109 tests + `test-slow` at 150
  ms), frontend check (656 vitest) + test:pw (430), e2e in all three modes (default 312,
  `E2E_SSO=1` 333, `E2E_AI=1` 352 passed, none failed), e2e check, fake agent, Helm,
  scripts, `make gen-api` (no diff), `make image` (525 MB). Test plan
  `docs/test-plans/phase-8b.md`; screenshots `docs/screenshots/phase-8b/` (+ `emails/`),
  phase-1, phase-3 (+ the two research emails), phase-8 and the tour re-captured. Stop for
  the human's review.
