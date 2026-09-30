# Build Brief: Ideas Pipeline (v2 — simplified)

> Working name: **ideas-pipeline** (rename freely). This file is the source of truth for the build.
> Claude Code: read the whole document, then follow "How to work" at the end.

## 1. The product in one paragraph

A simple, good-looking app where people submit ideas (including anonymously), each idea gets an **owner** who is accountable for moving it forward, and **multiple evaluators** score it independently against a short rubric. Strong ideas become a commercial proposal. AI agents in kagent can act as an extra evaluator or research assistant. It runs on Kubernetes, installs with one Helm command, and sends email through any SMTP server.

**Guiding principle: simple beats configurable.** When in doubt, pick a sensible default and don't build a settings screen for it. Every feature should be usable without reading docs.

### Non-goals
- Configurable workflow engines, custom fields, per-project stage designers.
- Webhooks, duplicate detection, file attachments (possible later, not now).
- Multi-organisation tenancy (one instance = one organisation; projects separate work).
- Our own LLM integration — all AI goes through kagent.

## 2. Core concepts

**Project** — a space for ideas (e.g. "Customer Innovation", "Internal Tools"). Has members, a short evaluation rubric, optional public submission, and optional branding.

**Idea** — title, summary, description (Markdown), tags, status, **owner**, **evaluators**.

**Status** — fixed, small, obvious:
`New → Evaluating → Shortlisted → Proposal → Closed (Accepted | Rejected | Parked)`
Admins may rename labels; they can't add or remove stages.

**Owner** — one person per idea. Assigned by a project admin, or a member can volunteer ("I'll own this") if the project allows it. The owner:
- invites evaluators and sets an evaluation due date
- moves the idea between statuses
- writes the proposal
- is the named contact on the idea

**Evaluators** — any number per idea, chosen by the owner or admin from project members. Each evaluator:
- scores each rubric criterion 1–5 with an optional short comment, plus an overall recommendation (Go / Maybe / No)
- evaluates **blind**: they can't see others' scores until they've submitted their own (avoids anchoring)
- can edit their evaluation until the owner closes evaluation

**Rubric** — per project, 3–6 criteria with a name, one-line description and weight. Ships with a sensible default: Value, Feasibility, Effort (inverted), Strategic fit, Risk (inverted). Admins can edit but it stays short.

**Aggregate score** — weighted mean across submitted evaluations, shown with the number of evaluations and a "high disagreement" flag when the spread between evaluators is large (e.g. ≥2 points on any criterion). Ranking is simply "sort by aggregate score" with filters.

**Proposal** — once Shortlisted, the owner creates a proposal from a fixed, sensible template (Summary, Problem, Solution, Market & users, Cost & effort, Benefits/revenue, Risks, Next steps / the ask). Evaluators and members can comment. Export to PDF and Markdown.

## 3. Roles (kept deliberately small)

| Role | Scope | Can |
|---|---|---|
| Platform admin | Instance | Everything: users, groups, SSO, SMTP, branding, all projects |
| Project admin | Project | Settings, rubric, members, assign owners, override anything in the project |
| Member | Project | Submit, comment, vote, be owner or evaluator |
| Viewer | Project | Read only |
| Public | — | Submit to projects with public submission on; track own submission via private link |

Owner and evaluator are **per-idea assignments**, not roles. Project membership can be granted to users or to groups.

Project visibility: `private` (members only) or `internal` (any signed-in user can view; only members can act).

## 4. Tech stack

| Concern | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, `uv` |
| Database | PostgreSQL 16 — the only stateful dependency |
| Background jobs | `procrastinate` (Postgres-backed) for email and agent runs — no Redis |
| Frontend | React + TypeScript + Vite, TanStack Router/Query, Tailwind, shadcn/ui (Radix), lucide icons, `cmdk` |
| Auth | Authlib (OIDC), server-side sessions |
| Email | `aiosmtplib`, Jinja2 templates (HTML + plain text) |
| MCP | Official `mcp` Python SDK, streamable HTTP, stateless mode |
| PDF export | WeasyPrint with bundled fonts |
| Packaging | One container image (api + worker entrypoints), one Helm chart |
| Tests | pytest + testcontainers, Playwright for key UI flows |

Everything bundled — no CDN fonts/scripts, no telemetry — so it runs air-gapped.

## 5. UI and UX — this is a headline requirement

The bar: it should feel like Linear or Height — calm, fast, obvious. Not an enterprise form-fest.

### Principles
- **Few screens, each doing one thing well.** Most work happens on the idea page and in "My work".
- **Fast:** optimistic updates, skeleton loaders not spinners, no full page reloads, lists virtualised.
- **Keyboard friendly:** `⌘K` command palette (jump to idea/project, create idea, assign), `N` new idea, `E` evaluate, `?` shortcut sheet.
- **Clear hierarchy:** generous whitespace, one primary action per view, restrained colour (status and score only), consistent 4/8px spacing scale, Inter (bundled) or branding font.
- **Light and dark mode**, following system by default.
- **Responsive:** evaluating and submitting must work well on a phone.
- **Friendly empty states** that tell you what to do next.
- **Accessible:** WCAG 2.2 AA, full keyboard navigation, visible focus, proper labels.
- **Inline editing** rather than separate edit pages. Toasts with Undo for destructive-ish actions.

### Screens
1. **My work** (home) — three sections: *Evaluations due* (with due dates), *Ideas I own* (grouped by status), *Recently updated in my projects*. Counts in the sidebar.
2. **Project** — toggle between **Board** (columns by status, drag to move if you're owner/admin) and **List** (sortable table: title, owner avatar, evaluator progress e.g. "3/4", score, status, updated). Filters as chips: status, owner, tag, "needs evaluators", "high disagreement".
3. **Idea page** — single page. Left: title, summary, description, then an activity feed (comments + events). Right sidebar: status, owner, evaluators with progress ticks, due date, aggregate score with per-criterion bars, tags. Tabs only for *Overview / Evaluations / Proposal*.
4. **Evaluate** — a side sheet from the idea page: one row per criterion with 1–5 segmented control and hover guidance, optional comment, overall recommendation, Submit. After submitting, the other scores reveal with a subtle animation.
5. **Proposal editor** — clean Markdown editor with section outline, comment threads in the margin, Export button.
6. **Submit idea** — a short, friendly form (title, summary, description, tags). The public version is branded and even simpler.
7. **Settings** — project settings (members, rubric, public submission, branding); admin settings (users, groups, SSO, SMTP, branding, API keys, agents). Plain forms, sensible defaults, no sprawl.

Claude Code: build a small internal design system first (tokens, typography scale, buttons, inputs, badges, avatars, sheet, command palette, empty state, skeleton) and use it everywhere. Add a `/design` dev-only page showing all components.

## 6. Email (SMTP)

- Works with any SMTP server: host, port, security mode (`none` | `starttls` | `tls`), optional username/password, from address/name, optional reply-to, optional custom CA bundle, connection timeout.
- Configured via Helm values; credentials from a K8s Secret (`existingSecret` supported). Admin UI shows the effective config (password masked) and a **Send test email** button.
- **Transactional outbox:** emails are written to an `outbound_email` table in the same DB transaction as the event, then sent by the worker with retries and exponential backoff. Failed sends visible in admin with retry button. No email is ever lost because SMTP was briefly down.
- Branded HTML + plain-text templates, rendered from Jinja2, with a footer and working unsubscribe/preferences link.
- Per-user preferences: immediate / daily digest / off, per notification type.
- Notification types:
  - You've been made owner of an idea
  - You've been asked to evaluate an idea (with due date and a one-click link to the evaluate sheet)
  - Evaluation reminder (configurable, e.g. 2 days before due and on the due date)
  - All evaluations are in (to owner)
  - Status changed (to owner, evaluators, watchers, and public submitter if they opted in)
  - New comment / @mention
  - Public submitter: confirmation with tracking link, optional email verification
- If SMTP isn't configured the app still works; notifications are in-app only and admin sees a banner.
- Dev: Mailpit in docker-compose.

## 7. Identity and access

Keep the capability, keep the UI simple.

- **Sign-in:** OIDC (Keycloak primary test target; Entra ID and Google documented). Server-side code flow + PKCE, HttpOnly session cookie, CSRF protection. The browser never sees IdP tokens. Redirect URIs derived from the configured host the user signed in on (multiple domains supported).
- **Users:** admins can pre-create users and attach **external IDs** (e.g. `employee_no`, `gitlab`) so the right account is linked at first sign-in. Login matching: (issuer, subject) → configured external-ID claim → verified email (if enabled) → auto-create (if enabled) → deny.
- **Groups:** internal groups, each mappable to one or more IdP group values (claim path configurable, Keycloak `/path` normalised). Mapping is **managed** (sync adds and removes) or **additive** (sync only adds). Manual memberships are never touched by sync. A "test mapping" box shows what a pasted claim set would resolve to.
- **Break-glass admin** from a K8s Secret, off once SSO is configured, every use audited.
- **Authorisation** in one central module; deny by default; table-driven tests of the role matrix.
- **Audit log** of sign-ins, assignments, evaluations, status changes, admin changes.

## 8. API, API keys and MCP

- REST API at `/api/v1` with OpenAPI docs (self-hosted assets), cursor pagination, problem+json errors.
- **Personal API keys** from the user's profile: name, scopes (`read`, `write`, `evaluate`, `mcp`), optional expiry, optional project restriction. Shown once, stored hashed, revocable, last-used shown. A key can never exceed its owner's live permissions.
- **MCP server** at `/mcp` (streamable HTTP, stateless). Auth via API key. Tools: `list_projects`, `search_ideas`, `get_idea`, `create_idea`, `add_comment`, `submit_evaluation`, `get_rubric`, `get_proposal`, `propose_proposal_section`. Same authz as the API; every call audited.

## 9. kagent integration (AI assistance)

Keep it to two clear jobs:

1. **AI evaluator** — the owner can click "Ask AI to evaluate". The worker calls a configured kagent agent over A2A; the agent reads the idea via our MCP tools and submits an evaluation with a rationale and cited sources for each criterion. It appears in the evaluators list with an "AI" badge and is **excluded from the aggregate score by default** (the owner can include it).
2. **Research & draft assistant** — on the idea page, "Research this" produces a cited research note in the activity feed; in the proposal editor, "Draft section" proposes text the owner accepts or discards.

Details:
- Agents authenticate back to our MCP server as a service account with a scoped API key.
- Before writing integration code, inspect the installed kagent (`kubectl get crd | grep kagent`, `kubectl explain`, the agent card) and code to the installed version's A2A and CRD APIs.
- Admin UI: register agents (namespace/name, purpose). Optional Helm templates for example `Agent` manifests and the MCP server registration, off by default.
- Show run progress live (SSE) and handle timeout/cancel cleanly.

## 10. Public submission and branding

- Per-project toggle for public submission at `/{project}/submit`. Anti-abuse: honeypot, per-IP rate limit (trusted-proxy aware), ALTCHA proof-of-work challenge (works offline), optional email verification, optional moderation (ideas land in New but hidden until approved).
- Submitter gets a private tracking link and optional email updates. Minimal PII; admins can erase submitter details while keeping the idea (UK GDPR).
- **Branding:** app name, logo, favicon, primary/accent colour, font choice from bundled set, email footer. Global default, optional per-project override. Applied through CSS variables at runtime, live preview in settings.

## 11. Kubernetes and Helm

Goal: `helm install ideas ./deploy/helm -f my-values.yaml` gives a working app.

- One image; two Deployments (`api`, `worker`); DB migrations as a pre-install/pre-upgrade hook Job (also valid as ArgoCD PreSync).
- Postgres: `postgresql.enabled: true` for a simple bundled StatefulSet (dev/small installs) or `externalDatabase.*` / existing Secret for managed or CloudNativePG databases.
- Values cover: image registry/tag override, replicas, resources, ingress (hosts, TLS, class) and optional Gateway API HTTPRoute, OIDC provider bootstrap, SMTP (`smtp.host`, `smtp.port`, `smtp.security`, `smtp.from`, `smtp.existingSecret`), break-glass admin secret, feature toggles (public submission, AI).
- `values.schema.json` validation, `NOTES.txt` with the URL and first-login steps.
- Restricted Pod Security (non-root, read-only root FS, no capabilities), probes, PDB, optional HPA, optional NetworkPolicy, optional ServiceMonitor.
- Prometheus metrics, OTel tracing (optional endpoint), JSON logs without PII.
- Tested on k3s/k3d in CI (install, upgrade, smoke test).

## 12. Repository layout

```
/backend       FastAPI app, domain, authz, email, mcp, worker, alembic, tests
/frontend      React SPA + design system
/deploy/helm   Helm chart
/deploy/kagent example agent manifests
/dev           docker-compose: Postgres, Keycloak (realm export), Mailpit; seed data
/e2e           Playwright acceptance tests + screenshots
/scripts       check-task.sh and dev helpers
/docs          ADRs, role matrix, ownership map, operator guide, user guide
/.claude       settings.json and agents/ (multi-agent build)
CLAUDE.md      living notes for future sessions
```

## 13. Delivery plan

Stop for review after each phase. Each phase ends with passing tests, updated docs, and a working Helm install on local k3s/k3d.

**Phase 0 — Plan & scaffold (stop before Phase 1)**
Multi-agent setup (section 14), ADRs, ERD, role matrix, repo scaffold, docker-compose dev stack, GitLab CI (lint, types, tests, image, Trivy, `helm lint` + k3d install), Helm skeleton, design tokens + `/design` page, `CLAUDE.md`. Include low-fi wireframes (ASCII or simple HTML) of the seven screens for review.

**Phase 1 — Ideas, owners, evaluators**
Projects, members, ideas, statuses, owner assignment, evaluator invites, blind evaluations, rubric, aggregate score, disagreement flag, comments, My work, Board/List, idea page, evaluate sheet, command palette. Dev-only login stub. *Acceptance:* create a project, submit an idea, assign an owner, have three evaluators score it blind, see the aggregate and ranking.

**Phase 2 — Sign-in and access**
OIDC, users, external IDs, pre-created users, groups and mappings, project roles via groups, break-glass admin, audit log, authz matrix tests. *Acceptance:* Keycloak users get the right project access from their groups; removing a group removes access at next sign-in (managed mapping).

**Phase 3 — Email**
SMTP config, outbox + worker, templates, preferences, digests, reminders, test email. *Acceptance:* with Mailpit, assigning an evaluator sends a branded email whose link opens the evaluate sheet; stopping Mailpit then restarting it delivers queued mail.

**Phase 4 — Proposals, public submission, branding**
Proposal editor and PDF/Markdown export, public forms with ALTCHA and tracking links, branding profiles. *Acceptance:* anonymous idea → evaluated → shortlisted → exported branded proposal.

**Phase 5 — API keys and MCP**
*Acceptance:* an MCP client with a key can search ideas and submit an evaluation only in permitted projects; revoking the key cuts access immediately.

**Phase 6 — kagent**
AI evaluator, research notes, proposal drafting, live progress. *Acceptance:* "Ask AI to evaluate" produces a badged, cited evaluation excluded from the aggregate by default.

**Phase 7 — Polish & hardening**
UX pass (empty states, loading, keyboard, mobile), accessibility audit, performance check (10k ideas feels instant), security review, operator and user guides.

## 14. Multi-agent build

The build uses Claude Code **agent teams** (a lead session plus teammates with a shared task list and direct messaging) for parallel phases, and plain **subagents** for focused research and review. Agent teams are experimental: check the current docs (https://code.claude.com/docs/en/agent-teams) and adjust anything below that has changed.

### Setup (done by the lead in Phase 0)
- `.claude/settings.json` (project): set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` under `env`; pre-approve routine commands (`make`, `uv run`, `npm run`, `helm`, `kubectl` against the local k3d context only) so teammate permission prompts don't flood the lead; add a `TaskCompleted` hook that runs `scripts/check-task.sh` and exits 2 with the failure output if lint/type-check/tests for the touched area fail, so a task can't be marked done while red. Verify hook and permission syntax against the current docs.
- `.claude/agents/*.md`: the role definitions in the appendix below. They work both as subagents and as teammate types ("spawn a teammate using the frontend agent type").
- `docs/ownership.md`: the file-ownership map below. Every teammate reads it before starting.

### Contract-first, so work can run in parallel
Before any parallel phase, the lead writes the API contract for that phase: Pydantic request/response schemas in `backend/app/schemas/`, route stubs returning 501, exported `openapi.json`, and a generated TypeScript client in `frontend/src/api/generated/` (e.g. `openapi-typescript`). Frontend builds against MSW mocks from the contract while backend implements it. Contract changes go through the lead only.

### File ownership (prevents overwrites — teammates share one working tree)

| Owner | Paths |
|---|---|
| lead | `docs/`, `CLAUDE.md`, `backend/app/schemas/`, `frontend/src/api/generated/`, `.claude/` |
| backend | `backend/app/**` (except `auth/`, `authz/`, `schemas/`), `backend/migrations/`, matching unit tests |
| identity | `backend/app/auth/`, `backend/app/authz/`, `backend/app/api_keys/`, matching tests |
| frontend | `frontend/**` (except `src/api/generated/`) |
| platform | `deploy/`, `dev/`, `Dockerfile`, `.gitlab-ci.yml` (self-hosted GitLab; GitHub Actions optional), `scripts/` |
| qa | `e2e/`, `backend/tests/acceptance/`, `docs/test-plans/` |

Rules: only **backend** creates Alembic migrations (others message backend with the schema change they need — avoids multiple heads). Teammates don't commit; the **lead** reviews and commits at task boundaries. If you need a change in a path you don't own, message its owner.

### Team per phase (3–5 active teammates max)

| Phase | Mode | Who |
|---|---|---|
| 0 Plan & scaffold | Lead solo + parallel **researcher** subagents verifying MCP SDK, kagent CRDs/A2A, procrastinate, Authlib, WeasyPrint | Sequential foundation work — no team |
| 1 Ideas, owners, evaluators | Team | backend, frontend, platform, qa |
| 2 Sign-in & access | Team | identity, frontend, qa → then **security-reviewer** subagent |
| 3 Email | Team | backend, frontend, platform, qa |
| 4 Proposals, public, branding | Team | backend, frontend, identity (ALTCHA/rate limits), qa |
| 5 API keys & MCP | Team | identity, backend, qa → then **security-reviewer** |
| 6 kagent | Team | backend, platform, frontend, qa |
| 7 Polish & hardening | Review team | security-reviewer, ux-reviewer, qa (performance) — findings to lead, fixes assigned back to builders |

Each phase: lead writes the contract and a task list with dependencies (aim for 5–6 tasks per teammate, each producing a clear deliverable), spawns the team with task-specific context in each spawn prompt, waits for teammates rather than implementing their tasks itself, then runs **code-reviewer** and **ux-reviewer** subagents over the phase before the phase summary.

### Example kick-off (for the human to paste at the start of a phase)
> Enter plan mode. We're starting Phase 1 from SPEC.md. Write the Phase 1 contract and task list, then create an agent team: backend, frontend, platform and qa teammates using those agent types. Enforce docs/ownership.md. Wait for all teammates to finish, run code-reviewer and ux-reviewer, then give me the phase summary with screenshots.

### Appendix: agent definitions (create in `.claude/agents/`)

Use `model: inherit` unless cost pushes you to a smaller model for qa/reviewers. Keep bodies short; project detail lives in SPEC.md and CLAUDE.md, which every agent loads.

```markdown
---
name: backend
description: Implements FastAPI endpoints, domain logic, worker jobs, email outbox and Alembic migrations for ideas-pipeline. Use for server-side features outside auth/authz.
---
You own the paths listed for "backend" in docs/ownership.md. Implement against the schemas in backend/app/schemas/ — never change them; message the lead if the contract is wrong. You are the only agent that writes Alembic migrations. Write tests first for business rules (blind evaluation visibility, aggregate scoring, status transitions, email outbox). Use testcontainers Postgres, not mocks. Mark a task complete only when `make check-backend` passes.
```

```markdown
---
name: identity
description: Implements OIDC sign-in, sessions, user/identity/external-ID matching, group mapping sync, central authorisation, API keys and public-form anti-abuse. Use for anything security-sensitive in the backend.
---
You own backend/app/auth, authz and api_keys. Deny by default. Every permission rule gets a table-driven test mirroring docs/role-matrix.md. Test OIDC flows against the Keycloak in dev/ (realm export), including managed vs additive group sync and multi-domain redirects. Never log tokens, secrets or PII. Request schema changes from the backend agent.
```

```markdown
---
name: frontend
description: Builds the React SPA and design system — screens, components, theming, keyboard shortcuts, accessibility. Use for any UI work.
---
You own frontend/ except src/api/generated. Follow section 5 of SPEC.md: calm, fast, Linear-like. Build and reuse the design-system components on /design; no one-off styling. Use the generated API client and MSW mocks until the backend lands. Every screen needs loading, empty and error states, dark mode, keyboard access and a mobile layout. Add Playwright component or page tests for what you build.
```

```markdown
---
name: platform
description: Owns the Helm chart, container image, docker-compose dev stack, GitLab CI and k3d test cluster. Use for packaging, deployment, SMTP/Keycloak/Mailpit dev services and kagent manifests.
---
You own deploy/, dev/, Dockerfile, .gitlab-ci.yml and scripts/. The chart must install cleanly with `helm install` on k3d with default values and pass `helm lint` and values.schema.json validation. Restricted Pod Security, probes, migration hook Job, bundled-or-external Postgres, SMTP via existingSecret. No image or asset pulled from the public internet at runtime; registry must be overridable.
```

```markdown
---
name: qa
description: Writes and runs acceptance and end-to-end tests against each phase's acceptance criteria, and captures screenshots. Use to verify a phase is actually done.
---
You own e2e/, backend/tests/acceptance and docs/test-plans. Turn each acceptance criterion in SPEC.md into an automated test before builders finish. Run against the k3d Helm install, not only the dev server. Capture light, dark and mobile screenshots of every screen touched this phase. Report failures to the owning teammate by name with reproduction steps; don't fix other agents' code.
```

```markdown
---
name: code-reviewer
description: Read-only security and code-quality review of a phase's changes. Use at the end of each phase and before any release.
tools: Read, Grep, Glob, Bash
---
Do not edit files. Review the diff for the phase against OWASP ASVS L2, the role matrix, secret handling, SQL/HTML injection, SSRF in the A2A/SMTP clients, error handling and test gaps. Also flag complexity that contradicts SPEC.md's "simple beats configurable" rule. Return findings ranked by severity with file:line references and a suggested fix.
```

```markdown
---
name: ux-reviewer
description: Read-only UX and accessibility review using Playwright screenshots and axe checks. Use at the end of each phase with UI changes.
tools: Read, Grep, Glob, Bash
---
Do not edit files. Open the app on the k3d install, run axe accessibility checks, capture screens (light, dark, 390px mobile) and review against section 5 of SPEC.md: hierarchy, spacing consistency, one primary action per view, empty/loading/error states, keyboard flow, copy clarity. Return a ranked list of issues with screenshots and concrete fixes.
```

```markdown
---
name: researcher
description: Read-only research to verify library, SDK and cluster APIs before code depends on them. Use in Phase 0 and whenever an external API is uncertain.
tools: Read, Grep, Glob, Bash, WebFetch, WebSearch
---
Do not edit project files. Answer the specific question asked with version numbers, minimal working examples and links to the source. For kagent, inspect the live cluster (`kubectl get crd`, `kubectl explain`) rather than relying on docs alone. Say clearly what you could not verify.
```

## 15. How to work (instructions for Claude Code)

1. Start in plan mode. Summarise your understanding, list assumptions and questions, then do Phase 0 (including the multi-agent setup in section 14) and stop.
2. From Phase 1 onward, run phases as agent teams per section 14. The lead coordinates, owns the contract and commits; it does not do teammates' tasks.
3. Protect simplicity: if a feature needs a new settings screen or a new concept, question it and propose the simpler option in your phase summary.
4. Treat UI quality as a feature: screenshot key screens with Playwright at the end of each phase (light, dark, mobile) and include them in the summary.
5. Keep `CLAUDE.md` current (commands, conventions, gotchas).
6. Verify external APIs (MCP SDK, kagent, A2A, Authlib) against current docs or the installed cluster before relying on them.
7. Tests first for authz, login matching/group sync, blind-evaluation visibility, API key scoping and the email outbox.
8. Small conventional commits; no secrets in the repo; justify every new dependency.

## 16. Open questions for the product owner

- Product name and default logo/colours?
- Can members volunteer to own ideas, or only admins assign owners?
- Should evaluators be restricted to project members, or can owners invite anyone signed in?
- Default evaluation window (e.g. 7 days) and reminder schedule?
- Any classification markings needed on ideas or exported proposals?
