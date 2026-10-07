# Soundings 0.1.0 release notes

**Released:** 2026-10-07 (the end of Phase 7, SPEC section 13). It is the first release:
Phases 0–7 complete, waiting for the product owner's review.

Soundings is a calm, fast web app where people submit ideas, anonymously too through a
public form. Each idea gets one accountable owner and several evaluators, who score it
blind against a short rubric. Strong ideas become a commercial proposal exported to PDF
or Markdown. kagent agents can act as an extra evaluator or research assistant. It is
one container image and one Helm chart, needs only PostgreSQL, sends mail through any
SMTP server and runs air-gapped. Tour: [README](../README.md#a-tour). Guides:
[user](user-guide.md), [operator](operator-guide.md), [MCP](mcp.md).

**Verified on 2026-10-07** (the build machine, not yet a real CI runner): every check
(6,336 backend tests, 589 unit and 387 page tests in the SPA, the end-to-end suite in its
three modes), the image `soundings:0.1.0`, and on k3s the operator guide's one-command
`helm install`, `helm test`, an upgrade with SSO, SMTP, MCP and AI, then two API
replicas, with every smoke test passing:
[Phase 7 summary](phase-summaries/phase-7.md#acceptance-evidence-final-verification-2026-10-07).

## What's in it, by area

### Ideas, owners and evaluators (Phase 1)

- **Projects**, private or internal, with members by person or by group (admin,
  member, viewer). The rubric has 3–6 weighted criteria (some inverted, such as Effort
  and Risk). The status labels can be renamed, but the five statuses are fixed: New,
  Evaluating, Shortlisted, Proposal, Closed (Accepted, Rejected or Parked).
- **Ideas** have a title, a summary, a Markdown description, tags, comments with
  @mentions, votes and watching. Each idea has one **owner**, assigned by an admin or
  volunteered for ("I'll own this"). The owner invites **evaluators** with a due date,
  moves the idea between statuses, and closes or reopens evaluation.
- **Blind evaluation.** Evaluators score each criterion 1–5 with an optional comment
  and recommend Go, Maybe or No. Until they submit they see no score data anywhere:
  not in the app, emails, search, exports, the API, MCP or AI run progress. The
  **aggregate** is the weighted mean, with the number of evaluations and a "high
  disagreement" flag (a spread of 2 or more points on any criterion).
- **Screens:** My work, the board and the list (sort by score, filters, search), the
  idea page, the evaluate sheet, the command palette (⌘K) and keyboard shortcuts (`?`).
  Every screen has dark mode and works at 390 px.

### Sign-in and access (Phase 2)

- **Single sign-on** with OIDC (code flow with PKCE): Keycloak, Microsoft Entra ID,
  Google. Accounts are matched by an external ID claim, then by a verified email, or
  optionally created at first sign-in. Pre-created users are linked at their first
  sign-in.
- **Groups and IdP mappings**: managed mappings follow the directory at each sign-in,
  additive ones only add. Projects grant roles to groups.
- A **break-glass admin** works only while SSO is not configured. A **development login**
  exists only in development mode.
- Sessions last 24 hours at most and end after 12 hours idle. `__Host-` cookies are
  used in production. The **audit log** records sign-ins, admin and access changes,
  assignments and evaluations.

### Email and notifications (Phase 3)

- Seven notification types, in the app (the bell and the inbox) and by email, chosen
  per type: immediately, in a daily digest, or off. Reminders arrive before and on the
  due date, at a set hour in the instance's time zone.
- A **transactional outbox** sent by the worker, with retries and backoff. An SMTP
  outage delays mail; it never loses it. Admin → Email shows the settings in effect,
  the outbox and a test email.
- Branded HTML and text emails with one-click unsubscribe (RFC 8058) and scoped
  unsubscribe links. **Emails never carry scores.**

### Proposals, public submission and branding (Phase 4)

- **Proposals** follow a fixed eight-section template, saved per section with conflict
  detection. Comments sit in the margin, suggestions are accepted or discarded, and the
  proposal exports to **Markdown or a branded, tagged PDF**. The PDF uses bundled fonts
  and renders in a time-limited child process that fetches nothing.
- **Public form** at `/<project>/submit`, with a honeypot, an ALTCHA proof of work,
  per-address and per-project limits, optional email confirmation and moderation (on by
  default). Submitters get a private tracking link (the token stays after `#`), status
  emails and "Delete my details". Admins can erase a submitter's details, and retention
  rules run hourly.
- **Branding**: a global profile and per-project overrides (colours, four bundled
  fonts, a PNG or SVG logo, a favicon, an email footer). They apply to the app, public
  pages, emails and PDFs.

### API keys and MCP (Phase 5)

- **Personal API keys** have scopes (`read`, `write`, `evaluate`, `mcp`), an optional
  expiry and an optional restriction to some projects. A key is shown once and can't be
  changed afterwards. It never does more than its owner may do right now, and revoking
  it cuts access at the next call.
- An **MCP server** at `/mcp` offers ten tools over the same services and policy as the
  REST API: search and read ideas (blind), create ideas, comment, evaluate, propose
  proposal text, and more. Every call is audited. Claude Code, Claude Desktop and the
  SDKs connect with a key ([mcp.md](mcp.md)).

### AI assistance through kagent (Phase 6)

- Platform admins **register kagent agents** (namespace and name, protocol, purposes,
  projects). Each agent gets a service account and one key, shown once with its Secret
  and `RemoteMCPServer` manifests.
- Owners can use **Ask AI to evaluate**, **Research this** and **Draft a section**.
  These start durable runs that the worker sends over A2A, with a deadline, cancel,
  retries and live progress over SSE.
- Agents act through `/mcp`, confined to the idea of their open run and **always
  blind**. An AI evaluation carries a rationale and cited sources per criterion and an
  AI badge. It stays **out of the aggregate until the owner includes it**.

### Polish and hardening (Phase 7)

- **Accessibility (WCAG 2.2 AA audit):**
  - a switch to turn off single-key shortcuts;
  - one highlight ring and a 3:1 control colour;
  - focus never hidden under sticky bars, and moved to the page heading after
    navigation;
  - Undo messages last 10 s and pause while you are on them;
  - rubric criteria can be moved without dragging;
  - tagged PDFs and email landmarks.
  - axe checks (WCAG and best-practice rules) cover the main screens on the mock and on
    the real stack.
- **UX:**
  - **Settings** is about you; platform admins get **Admin**;
  - four project settings tabs;
  - one API keys page;
  - the idea's main button follows its status;
  - a first-run welcome;
  - pickers open on the current value;
  - a phone-first project header;
  - one layout for public messages;
  - many smaller fixes ([decisions](decisions.md#2026-10-07--phase-7-fixes-frontend)).
- **Performance with 10,000 ideas** ([performance.md](test-plans/performance.md)):
  - the sidebar's counts come from their own endpoint;
  - My work pages its evaluations due and shows 10 ideas per owned group;
  - faster short searches and tag counts;
  - first-load JavaScript cut from 1,026 kB to 636 kB;
  - Brotli and gzip for the SPA, and gzip for JSON;
  - smoother list scrolling.
- **Security (OWASP ASVS L2 review):**
  - the image starts in production mode and refuses the development key;
  - ALTCHA bounds;
  - a 120-a-minute write limit per person;
  - the bundled Postgres app role is not a superuser;
  - API docs only for signed-in callers in production;
  - bounded SSO callback parameters;
  - NetworkPolicy guidance for trusted proxies;
  - a CI audit job (pip-audit, npm audit, Trivy);
  - `soundings anonymise-user` for leavers, with a table of what is stored about users.
- **Docs:** the [user guide](user-guide.md), the [operator guide](operator-guide.md)
  and this README, all checked against the running app.

## Known issues and limitations

| Item | Detail |
|---|---|
| **kagent is verified against its CRDs and a fake agent only** | No kagent controller or LLM has carried a run. The A2A client, the MCP side and the manifests are tested against Soundings' fake agent (`dev/fake-agent`, a2a-sdk 1.2.1 at kagent v0.10.2's paths) and a server-side dry run of every manifest against kagent v0.10.2's real CRDs. On a cluster with kagent, start with `deploy/kagent/fake-agent-byo.yaml` ([deploy/kagent/README.md](../deploy/kagent/README.md)). |
| **The CI pipelines haven't run** | `.github/workflows/ci.yml` and `.gitlab-ci.yml` were written and every command they run passed on the build machine, but neither pipeline has run on a real runner. Trivy (the image scan) couldn't run here at all. |
| 20 people at once on one API pod: reads at p95 206–255 ms (budget 150 ms) | Medians are well inside the budget. The tail is overlapping requests sharing one event loop per pod. Scale with `api.replicas`. Two workers per pod was declined: it doubles memory. |
| Some interactions take longer than 100 ms at 4x CPU throttling (budget 100 ms) | Input to the next frame on a 10,000-idea list: sort 200 ms, filter 160 ms, opening ⌘K 272 ms, opening an idea from the list 208 ms, the evaluate sheet 592 ms; list scrolling drops 70 % of frames. Opening an idea paints the page in the click's frame on purpose: the page shows about 250 ms sooner than when the click only starts a download. Numbers: [performance.md §8–9](test-plans/performance.md#9-final-verification-2026-10-07). |
| Throttles and stream caps are per API pod's memory | With N replicas, a client gets up to N times as much: sign-in, public form, key failures, writes, SSE streams. |
| kagent's Python runtime can't cancel a task | Soundings ends the run anyway and refuses its late writes. kagent keeps what agents read in its own session store, outside Soundings' retention. |
| AI runs, their events and the audit log (except `mcp.call`, 90 days) are kept indefinitely | Back up and prune with your own policy. |
| Agent-cited sources may be invented | They are shown as "Cited by AI, not checked", with their host. |
| Radix radio groups: an arrow key whose key-up arrives with its key-down moves focus without selecting | Normal typing works (low priority in the audit). |
| The image is 524 MB (Ubuntu 24.04 with the PDF libraries) | A slimmer final stage was deferred (security review N5). Rebuild regularly for Ubuntu's security fixes. |
| No in-app help, no started proposal in the demo seed, no licence chosen yet | |
| Out of scope (SPEC non-goals) | Workflow engines, custom fields, webhooks, duplicate detection, attachments, multi-tenancy, a built-in LLM. |

## Upgrade notes

0.1.0 is the first release, so no upgrade path is supported yet. `helm upgrade` runs
the database migrations before new pods serve, and later releases will keep that path.
If you ran a build from before Phase 7, these changes affect you:

- **The image defaults to production** (`SOUNDINGS_ENVIRONMENT=production`).
  `soundings api` and `worker` refuse to start with the built-in development key when
  the environment isn't set. Development setups must set
  `SOUNDINGS_ENVIRONMENT=development`. The chart's `devLogin=true` does this for you.
- **The bundled Postgres:** a fresh volume gets a non-superuser app role. An existing
  volume keeps its roles. To harden one, dump, reinstall with a new volume and restore
  ([operator guide](operator-guide.md#bundled-postgres-vs-external-or-cloudnativepg-database)).
- **New limits:** a signed-in person may make 120 changes a minute per API pod
  (`SOUNDINGS_SESSION_WRITES_PER_MINUTE`). In production, `/api/docs` and the OpenAPI
  document need a session or a key with `read`.
- **NetworkPolicy:** the metrics port admits only `networkPolicy.metricsFrom`. Set
  `networkPolicy.ingressFrom` to your ingress controller's namespace: NOTES warns while
  it is empty.
- **Moved pages:**
  - the admin pages are under **Admin** in the sidebar (old `/settings/...` links still
    work);
  - **All API keys** is now **Settings → API keys → Everyone's keys** (the old address
    redirects);
  - project settings have four tabs (old `?tab=statuses` and `?tab=branding` links open
    the right section).
- **API (additive):** `GET /me/work/counts`, `GET /me/evaluations-due`,
  `ProjectSummary.pending_moderation_count`. `GET /me/work` now lists the first 50
  evaluations due, with `evaluations_due_next_cursor`
  ([contract-phase7.md](api/contract-phase7.md)).

## Decisions to confirm

The calls below were made without the product owner. Each one is the lead's default
("Proposed" in [decisions.md](decisions.md)), built that way and easy to change. Please
confirm or overrule them in one pass.

**Product and access**
1. Only **platform admins create projects**, and they name the first project admin.
2. **Members may volunteer** to own ideas (`allow_volunteer_owners`, default on per
   project). **Evaluators must be project members** (member or admin role).
3. Evaluations are **due 7 days** after the first invite (per project). Reminders go out
   **2 days before and on the due date** (an operator setting, not in the UI).
4. **Only the owner and admins** can ask AI to evaluate, research or draft.
5. "Anonymous" submission means **the public form**. The internal form always records
   the submitter.
6. Submitters may edit their idea only while it is **New**. Owners and admins can edit
   until it is closed.
7. **No classification markings** on ideas or exported proposals.
8. The product name **Soundings**, deep ocean blue `#1d5fa8` and Inter. Wordmark only;
   admins upload a logo.

**Email and notifications**

9. **Defaults:** status changes and new comments arrive in the **daily digest**;
   everything else is emailed immediately. The digest goes out at 08:00 in the instance
   time zone (default UTC).
10. Every email's footer has an **"Unsubscribe from all email"** link. A type's own
    link turns off only that type.
11. Mail older than 3 days (digests: 2) is cancelled rather than sent late. Outbox rows
    are kept 30 days (failed: 90), notifications 90 days.

**Public form and branding**

12. **Moderation is on by default** for a new public form. Email confirmation is off.
    Rejecting deletes the idea, and approving or rejecting sends no email.
13. Contact details of closed public ideas are erased after **180 days idle**.
    Unconfirmed addresses are dropped after 3 days.
14. A project override with its own logo and no app name uses **the project's name as
    the public wordmark** (form, emails, PDF).
15. Emails carry **no logo** (no remote images): the app name is the wordmark.

**Sign-in and keys**

16. Break-glass works **only while SSO is not configured**. In an SSO outage, the
    operator unsets `oidc.issuer`.
17. **Profile fields aren't synced** from the IdP after the first sign-in, and an
    Entra ID group overage denies the sign-in.
18. A person's API key **pauses after 30 days** without a sign-in. A user has at most
    25 keys, and keys can't be edited.
19. The **audit log is kept indefinitely** (except MCP calls, 90 days).

**Declined or deferred in Phase 7** (reasons in [decisions.md](decisions.md))

20. Declined:
    - two uvicorn workers per pod (scale with replicas);
    - one save model everywhere: forms whose fields belong together keep a Save button,
      while preferences and documents save as you go;
    - a Help item in the account menu;
    - a minimum search length and hiding emails in `GET /users`.
21. Deferred:
    - a slimmer image without apt, dpkg, perl and bash;
    - the Radix radio-group arrow-key edge case.
