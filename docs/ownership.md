# File ownership

Every agent reads this before starting. Agents share **one working tree**, so ownership
is what prevents overwrites: you create and modify files only under the paths you own.
This map adapts SPEC section 14 to the repository as it actually is.

This build orchestrates agents two ways: Claude Code **agent teams** (a lead session
plus named teammates with a shared task list) and **workflows/subagents** launched by
the lead. The rules below are the same in both. The agent types live in
[`.claude/agents/`](../.claude/agents/).

## Map

| Owner | Paths |
|---|---|
| **lead** | `SPEC.md` (read-only; product owner's brief), `CLAUDE.md`, `.claude/`, `.gitignore`, `docs/` (except the qa paths below), `backend/app/schemas/`, `frontend/src/api/generated/` (`openapi.json`, `schema.d.ts`) |
| **backend** | `backend/app/**` except `auth/`, `authz/`, `api_keys/` and `schemas/`; `backend/migrations/`; `backend/tests/**` except the identity and qa test paths; `backend/pyproject.toml`, `backend/uv.lock`, `backend/Makefile`, `backend/README.md` |
| **identity** | `backend/app/auth/`, `backend/app/authz/`, `backend/app/api_keys/`; tests in `backend/tests/auth/`, `backend/tests/authz/`, `backend/tests/api_keys/` |
| **frontend** | `frontend/**` except `frontend/src/api/generated/` |
| **platform** | `deploy/` (Helm chart, kagent examples), `dev/`, `scripts/`, `Dockerfile`, `.dockerignore`, `.gitlab-ci.yml`, `.github/`, the root `Makefile`, `.k3s/` (local state, git-ignored) |
| **qa** | `e2e/`, `backend/tests/acceptance/`, `docs/test-plans/` |
| read-only reviewers | **code-reviewer**, **ux-reviewer** and **researcher** never edit project files; they report to the lead |

Notes on the edges:

- `docs/erd.md` and `docs/api/` are lead-owned; the lead may delegate writing them to a
  contract subagent, which then owns them for that task only.
- Shared test fixtures (`backend/tests/conftest.py`) belong to backend. Identity and qa
  ask backend for fixture changes.
- ORM models (`backend/app/models/`), including users, sessions and API keys, belong
  to backend. Identity asks backend for model and migration changes, then builds on
  them.
- Public-form anti-abuse (honeypot, per-IP rate limits, ALTCHA) is identity's and lives
  in `backend/app/auth/`; the public submission endpoints themselves are backend's.
- Generated files belong to whoever owns the generator's output path:
  `frontend/src/routeTree.gen.ts` is frontend's; `frontend/src/api/generated/*` is the
  lead's (regenerated with `make gen-api`, never edited by hand).
- Anything not listed belongs to the lead until the lead assigns it.

## Rules

1. **Stay in your paths.** No "quick fixes" in someone else's files, not even a typo.
   Send a request instead (below).
2. **Only backend writes Alembic migrations.** Everyone else messages backend with the
   schema change they need. One writer means one migration head.
3. **The lead commits.** Teammates never `git commit`, `push`, switch branches, or run
   anything that rewrites the shared tree: `git stash`, `git reset`, `git checkout --`,
   `git clean`, `git restore`. These would destroy other agents' uncommitted work.
   Read-only git (`status`, `diff`, `log`, `show`) is fine.
4. **Contract changes go through the lead.** `backend/app/schemas/`, `openapi.json`
   and the generated client change only when the lead changes them. If the contract is
   wrong, message the lead with the proposed change; keep building against the current
   contract (or a clearly marked local stub) until it lands.
5. **Dependencies:** the owner of the manifest (`pyproject.toml`, `package.json`, the
   Dockerfile, the chart) adds dependencies, and justifies each in one line in their
   report. No CDN assets, fonts or telemetry: everything is bundled.
6. **A task is done when its checks pass.** The `TaskCompleted` hook runs
   `scripts/check-task.sh`; don't try to bypass it. `make check-backend`,
   `make check-frontend`, `make check-helm` and `make check-scripts` are the per-area
   gates.
7. **Shared machine:** use only the ports and Docker name prefix your task gives you,
   stop every server and container you started before you finish, and never stop
   anything you didn't start.

## Requests between owners

- **In an agent team:** message the owner directly with `SendMessage` (their teammate
  name matches their agent type, e.g. `backend`). Copy the lead if it touches the
  contract, a migration, or blocks you.
- **As a workflow subagent or plain subagent:** you can't message peers. Put the
  request in your final report under **"Requests for other owners"**; the lead routes
  it.
- A good request names the **owner**, the **path**, the **change** (a snippet or
  schema if you can), **why**, and whether it **blocks** you. Example:
  > backend: add `idea.moderation_state` (`pending | approved | rejected`, default
  > `approved`) with a migration. Needed for c12 in docs/role-matrix.md. Blocks the
  > moderation authz tests.
- The receiving owner replies when it's done (or why not). Unanswered blocking
  requests go to the lead.

## Agent types and phases

| Agent type (`.claude/agents/`) | Role | Edits files |
|---|---|---|
| `backend` | FastAPI endpoints, domain, worker, email outbox, migrations | yes |
| `identity` | OIDC, sessions, users and groups sync, authz, API keys, anti-abuse | yes |
| `frontend` | SPA and design system | yes |
| `platform` | Image, Helm, dev stack, CI, k3s | yes |
| `qa` | Acceptance and e2e tests, screenshots | yes (qa paths) |
| `code-reviewer` | Security and code-quality review; SPEC's "security-reviewer" is this type | no |
| `ux-reviewer` | UX and accessibility review with screenshots and axe | no |
| `researcher` | Verify external APIs before code depends on them | no |

Teams per phase follow SPEC section 14 ("Team per phase"): at most 3–5 active
teammates, reviewers at the end of each phase.
