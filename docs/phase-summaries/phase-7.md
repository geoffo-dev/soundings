# Phase 7 summary: polish and hardening (release 0.1.0)

**Status:** closed on 2026-10-07, waiting for the product owner's review. This is release
**0.1.0**: [RELEASE-NOTES.md](../RELEASE-NOTES.md).
**Scope (SPEC section 13):** "UX pass (empty states, loading, keyboard, mobile),
accessibility audit, performance check (10k ideas feels instant), security review,
operator and user guides." Phase 7 added no feature: four reviews ran against the
running app, their findings were fixed (tests first on the server), and the docs were
checked against the app.
**Acceptance:** the reviews' findings are fixed, declined or deferred by the lead
([decisions.md](../decisions.md), Phase 7 sections); every check passes; one command
installs it ([below](#one-command-install-the-operator-guides-quick-start));
the performance budgets are met one request at a time and missed in the places listed
under [Known issues](#known-issues-and-deferred-items).

Commits: `fd32366` (the performance kit), `a31c8a0` and `b5923e4` (the review fixes),
plus this close-out (final verification, My work's owned-group preview, docs, the README
tour, the release notes).

## What was built

| Area | What | Where |
|---|---|---|
| Security review (OWASP ASVS L2) | The image defaults to production and refuses the development key (M1); ALTCHA cost and expiry bounds (L3); 120 writes a minute per person, 429 `rate_limited` (L4); `soundings anonymise-user` and what is stored about users (L5); a non-superuser Postgres app role (L6); dev ports on 127.0.0.1 (L7); the API's map for signed-in callers in production (N1); break-glass credentials only while SSO is off (N2); metrics port policy (N3); account-kind traits in the policy (N4); bounded SSO callback (N6); `make k3s-install PROD=1` (L10); a CI audit job (L2); trusted proxies and `ingressFrom` explained, NOTES warns (L1) | `backend/app/`, `deploy/helm/`, `.github/workflows/ci.yml`, `docs/operator-guide.md`; tests `tests/auth/test_session_write_limit.py`, `tests/admin/test_anonymise.py`, `tests/public/test_altcha.py`, `tests/api/test_platform_http.py`, `tests/authz/test_principal_traits.py`, `tests/identity/test_sso_flow.py`, `test_cli.py` |
| Accessibility audit (WCAG 2.2 AA) | A switch for single-key shortcuts (2.1.4); one highlight ring and a 3:1 control colour (1.4.11); focus never hidden by sticky bars, moved to the h1 after navigation (2.4.11, 2.4.7); Undo messages 10 s and paused on hover or focus (2.2.1); Move up / Move down for rubric criteria (2.5.7); names that contain their visible labels (2.5.3); tagged PDFs; one landmark per email; axe best-practice rules next to WCAG in both test helpers | `frontend/src/`, `backend/app/proposals/`, `app/templates/email/`; `frontend/tests/a11y-phase7.spec.ts`, `e2e/tests/a11y-phase7.spec.ts`, `tokens.test.ts` |
| UX review | Settings is personal and **Admin** is for platform admins; four project settings tabs; one API keys page with presets; AI from the header's menu only; the idea's blue button follows its status; a first-run welcome and a first admin for new projects (B1); pickers open on the current value; a phone-first project header; one layout for public messages; a progress bar and board skeleton; many minors and polish | `frontend/src/features/` ([decisions](../decisions.md#2026-10-07--phase-7-fixes-frontend)) |
| Performance (10k ideas) | The kit (`e2e/perf/`, `backend/tests/perf/`); `GET /me/work/counts`, 50 evaluations due a page, `pending_moderation_count` (contract C1, C2); one statement for owned groups; short searches and tag counts; no parallel query workers; keep-alive after the response; Brotli/gzip twins and gzip JSON; first-load JS 1,026 → 636 kB; memoised list rows and hover tooltips; the idea page out of the first load and preloaded when idle; ⌘K's list a frame later; **My work shows 10 ideas per owned group** (this close-out) | [contract-phase7.md](../api/contract-phase7.md), [performance.md](../test-plans/performance.md) |
| Docs | The [README](../../README.md) as the front door with a 12-step tour; [RELEASE-NOTES.md](../RELEASE-NOTES.md); the [user guide](../user-guide.md) and [operator guide](../operator-guide.md) checked against the app (Admin names, the quick start's image step, upgrades); [mcp.md](../mcp.md), the Helm README and NOTES; CLAUDE.md; decisions | `README.md`, `docs/` |

## Acceptance evidence (final verification, 2026-10-07)

All on the working tree handed to the lead, on this shared 4-CPU machine.

### Checks

| Check | Result |
|---|---|
| `make -C backend check` | pass: ruff, ruff format, mypy --strict, pytest **6,336 passed**, 1 skipped, 6 deselected (slow); 32 min. After this close-out's template change the notification tests again: 95 passed |
| `make -C backend test-slow` | pass on an idle machine: 6 passed (the 10k-idea budgets and `tests/perf`), 160 s |
| `npm --prefix frontend run check` | pass: tsc, eslint + prettier, vitest **589 tests**, build |
| `npm --prefix frontend run test:pw` | pass: **387 passed**, 205 skipped (screenshot specs), 22.7 min under load (average 10-15), the new owned-group test included |
| `npm --prefix e2e test` (dev login, break-glass, worker, Mailpit) | pass: **248 passed**, 63 skipped, 11.3 min, the PDF specs on pdfjs-dist 6.4.299 |
| `E2E_SSO=1 npm --prefix e2e test` | pass: **269 passed**, 42 skipped, 12.0 min |
| `E2E_AI=1 npm --prefix e2e test` | pass: **285 passed**, 26 skipped, 13.8 min |
| `npm --prefix e2e run check`, `make check-helm`, `make check-scripts` | pass |
| `make check-fake-agent` | pass after fixing a flaky test (a cancel raced a2a-sdk's task store, −32001): 38 passed |
| `make gen-api` | no diff |
| `make image IMAGE=soundings:0.1.0` | pass, **524 MB**; the build renders a PDF |
| Performance kit | [performance.md §9](../test-plans/performance.md#9-final-verification-2026-10-07) |
| k3s | below |

### One command install: the operator guide's quick start

On a fresh local k3s (`K3S_NAME=p7-final-k3s`, `make k3s-up`), the image imported
(`make k3s-load IMAGE=soundings:0.1.0`), then exactly the guide's command with a local
base URL:

```sh
helm install soundings ./deploy/helm -n soundings --create-namespace \
  --set 'baseUrls[0]=http://localhost:18081' --set ingress.enabled=true
helm test soundings -n soundings
```

Deployed in 32 s (with `--wait`): the chart's default image is `soundings:0.1.0`
(appVersion), bundled Postgres, a generated signing key and break-glass password,
NetworkPolicies, production mode. NOTES printed the URL, the break-glass command and the
SSO steps, and warned that `networkPolicy.ingressFrom` is empty. `helm test` passed, then
`PROD=1 scripts/k3s-smoke.sh`: the API's map 401 anonymously, `/metrics` only on its own
port, 413 for 2 MiB, no dev login, break-glass with the Secret's 24-character password,
`__Host-` cookies (Secure, HttpOnly, SameSite=Lax), the production startup log, no
password in the logs.

### Upgrade and every smoke

The same release was upgraded to the CI configuration (`SSO=1 SMTP=1 MCP=1 AI=1`: dev
login and demo data, Keycloak, Mailpit, the fake agent as `kagent/kagent-controller`,
kagent v0.10.2's CRDs with a dry run of every manifest) and smoked through Traefik
(`scripts/k3s-smoke.sh` with `SSO=1 SMTP=1 MCP=1 AI=1`, 140 s, 119 checks): the standard
smoke, the public form with a solved ALTCHA and the PDF and Markdown export, SSO through
Keycloak (groups to project access, removal at the next sign-in), email with Mailpit
down then up (queued, delivered once), MCP through the ingress (ten tools, blind, revoke
→ 401) plus the official SDK in a pod in `kagent` and pods in other namespaces dropped by
the NetworkPolicy, the AI smoke against the fake (register, key once, Test connection,
a pending evaluator's stream without score data, left out then included, research,
draft, a cancelled slow run), every kagent manifest against the CRDs, and `helm test`.
Then `helm upgrade` to two API replicas: the same smoke passed again (137 s). No full key
or `Bearer sdg_` header in the API, worker or fake agent logs. `make k3s-down`.

Upgrading a quick-start release with `dev/k3s-values.yaml` first failed: that file sets a
1 GiB Postgres volume and Kubernetes refuses to change a StatefulSet's volume template.
Keeping the installed size (`--set postgresql.persistence.size=8Gi`) upgraded cleanly;
the Helm README and the operator guide now say these settings are fixed after install.

### My work and opening an idea (lead decisions 3 and 4)

My work now shows 10 ideas per owned group with "Show N more" (50 at a time, from the
response first, then the group's cursor; no contract change). For Alice (186 open ideas
owned) at 4x throttling: data shown 3.2-3.6 → 2.5-2.8 s, TBT 2.0 → 1.2-1.4 s, DOM
3,560 → about 1,870 nodes. Opening an idea from the list: the slower first frame (200-216
ms against 152-176 ms without it) comes from the idle preload of the idea route, which
lets the page paint in the click's frame and show about 250 ms sooner; kept.

## Review findings and outcomes

| Review | Findings | Outcome |
|---|---|---|
| Security (ASVS L2) | M1, L1-L10, N1-N6 | Fixed, except N5 (a slimmer image) deferred, L8 (search limits) declined, L9 (pdfjs-dist 6) done in this close-out |
| Accessibility (WCAG 2.2 AA) | 10 majors, minors | Fixed, except the Help item (3.2.6) declined, Radix menus outside landmarks rejected, a Radix radio-group key timing deferred |
| UX | B1, M1-M7, m1-m12, p1-p5 | Fixed; one save model everywhere declined (m11) |
| Performance | B1-B9 | Fixed, except B5 (two workers per pod) declined; misses listed below |

Each decision with its reason: [decisions.md](../decisions.md) ("Phase 7 fixes: backend
and platform", "Phase 7 fixes: frontend", "Phase 7 final verification").

### This close-out

- `frontend/src/features/work/owned-ideas.tsx`: 10 per owned group, "Show N more"
  (`frontend/tests/my-work.spec.ts`: 10 → 60 → 110 on the 10,000-idea mock).
- `e2e/package.json`: pdfjs-dist 6.4.299; `e2e/tests/support/pdf.ts` without
  `isEvalSupported`.
- Screenshot specs that the Phase 7 UI changes broke: phase 1 (board cards named
  "Title (KEY)"), phase 4 (the Public form tab panel, the phone's one-line review notice),
  phase 5 (Everyone's keys); a new `e2e/screenshots/tour.spec.ts` (`screenshots:tour`).
- The test email said "from Settings → Email": now "Admin → Email".
- `dev/fake-agent/tests/test_work.py`: the cancel tests wait for the task first.
- Docs: README, release notes, this summary, performance.md §9, decisions, CLAUDE.md,
  the guides' admin page names, the operator guide's image step and upgrade note, the
  Helm README's volume note, NOTES ("Admin > …").

## Known issues and deferred items

The release notes list them for operators:
[RELEASE-NOTES.md, Known issues](../RELEASE-NOTES.md#known-issues-and-limitations).
In short: kagent is verified against its CRDs and a fake agent only; the CI pipelines
haven't run on real runners; at 20 people on one API pod reads are p95 206-255 ms
(budget 150); sort, filter, ⌘K, opening an idea and the evaluate sheet take 160-592 ms
to their first frame at 4x throttling (budget 100) and list scrolling drops frames;
throttles are per pod; AI runs and the audit log are kept indefinitely; the image is
524 MB; no licence yet.

## Simplifications (SPEC section 15, item 3)

Phase 7 removed places and choices rather than adding settings: Settings for you and
Admin for platform admins, four project settings tabs, one API keys page with presets,
AI asked from one menu, the review queue in two places, agents' accounts only under AI
agents, My work previews, and a shortcut switch instead of removing shortcuts. Declined:
two workers per pod, a Help item, a minimum search length, one save model everywhere.
The list with reasons: [decisions.md](../decisions.md#phase-7-simplifications-spec-section-15-item-3).

Questions for the product owner: the 21 "Decisions to confirm" in the
[release notes](../RELEASE-NOTES.md#decisions-to-confirm), in one pass.

## Screenshot index

Real stack, freshly seeded demo data, the worker, Mailpit, Keycloak and the fake agent
where a set needs them; 1440 × 900 light and dark, 390 × 844 light. Every set was
re-captured in this close-out and **every PNG read**; no stale files remained (each set's
files were all rewritten): phase 1 (42), phase 2 (39, an SSO run then a break-glass run),
phase 3 (33 + 56 emails), phase 4 (36 + 4 PDF + 6 emails), phase 5 (21), phase 6 (33),
and the new **tour** (31).

The tour, in story order ([`docs/screenshots/tour/`](../screenshots/tour/); the README
shows the 1440 light ones):

| # | Screen | Light | Dark | Phone |
|---|---|---|---|---|
| 1 | Sign in: SSO and the development sign-in | [1440](../screenshots/tour/01-sign-in-1440-light.png) | | [390](../screenshots/tour/01-sign-in-390-light.png) |
| 2 | My work: evaluations due, ideas owned by status | [1440](../screenshots/tour/02-my-work-1440-light.png) | [1440](../screenshots/tour/02-my-work-1440-dark.png) | [390](../screenshots/tour/02-my-work-390-light.png) |
| 3 | Board, with the public form's review notice | [1440](../screenshots/tour/03-board-1440-light.png) | [1440](../screenshots/tour/03-board-1440-dark.png) | [390](../screenshots/tour/03-board-390-light.png) |
| 4 | Idea page CUST-12 (owner) | [1440](../screenshots/tour/04-idea-page-1440-light.png) | [1440](../screenshots/tour/04-idea-page-1440-dark.png) | [390](../screenshots/tour/04-idea-page-390-light.png) |
| 5 | Evaluate sheet, a saved draft (TOOLS-9) | [1440](../screenshots/tour/05-evaluate-sheet-1440-light.png) | | [390](../screenshots/tour/05-evaluate-sheet-390-light.png) |
| 6 | After submitting: everyone's scores (TOOLS-6) | [1440](../screenshots/tour/06-evaluate-reveal-1440-light.png) | [1440](../screenshots/tour/06-evaluate-reveal-1440-dark.png) | [390](../screenshots/tour/06-evaluate-reveal-390-light.png) |
| 7 | Proposal editor CUST-6 with a margin thread | [1440](../screenshots/tour/07-proposal-1440-light.png) | [1440](../screenshots/tour/07-proposal-1440-dark.png) | |
| 8 | The exported PDF's first page ([PDF](../screenshots/tour/08-proposal.pdf)) | [page 1](../screenshots/tour/08-proposal-pdf.png) | | |
| 9 | Public form | [1440](../screenshots/tour/09-public-form-1440-light.png) | | [390](../screenshots/tour/09-public-form-390-light.png) |
| 10 | Notifications inbox; an invitation email | [1440](../screenshots/tour/10-notifications-1440-light.png), [email](../screenshots/tour/10-email-1440-light.png) | | [390](../screenshots/tour/10-notifications-390-light.png), [email](../screenshots/tour/10-email-390-light.png) |
| 11 | Admin → Users | [1440](../screenshots/tour/11-admin-1440-light.png) | [1440](../screenshots/tour/11-admin-1440-dark.png) | |
| 12 | An AI evaluation, not in the score (the fake agent) | [1440](../screenshots/tour/12-ai-evaluation-1440-light.png) | [1440](../screenshots/tour/12-ai-evaluation-1440-dark.png) | [390](../screenshots/tour/12-ai-evaluation-390-light.png) |
