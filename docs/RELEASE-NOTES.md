# Soundings release notes

Soundings is a calm, fast web app where people submit ideas, anonymously too through a
public form. Each idea gets one accountable owner and several evaluators, who score it
blind against a short rubric. Strong ideas become a commercial proposal exported to PDF
or Markdown. It is one container image and one Helm chart, needs only PostgreSQL, sends
mail through any SMTP server and runs air-gapped. Tour: [README](../README.md#a-tour).
Guides: [user](user-guide.md), [operator](operator-guide.md), [MCP](mcp.md).

## 0.2.0

**Released:** 2026-10-10. The product owner's changes after reviewing 0.1.0: Phase 8
(per-project proposal templates and a research step), Phase 8b (the research assigned to
a person, also from outside the project) and Phase 9 (continuous delivery), with their
reviews' fixes. Waiting for the product owner's review.

**Verified on 2026-10-09/10** (the build machine; GitLab's pipeline also on a self-managed
GitLab CE, not GitHub's): every check (8,282 backend tests, 661 unit and 442 page tests
in the SPA, the end-to-end suite in its three modes: 315 tests, 336 with single sign-on
and 355 with the AI agent, none failed), the image `soundings:0.2.0` (525 MB), and on
k3s an upgrade of 0.1.0 with its demo data to 0.2.0 through `scripts/deploy.sh`
(migrations 0011 → 0015, row counts unchanged, the new features working on the migrated
data), then the smoke tests as CI runs them, production mode and two API replicas:
[Phase 8 and 8b summary](phase-summaries/phase-8.md),
[Phase 9 summary](phase-summaries/phase-9.md).

### What's new in 0.2.0

#### Per-project proposal templates (Phase 8)

- Project settings → **Proposal template**: project admins add, remove, rename and
  reorder the sections every proposal in the project has (1–12, each with a title and a
  one-line hint shown in the editor). New and existing projects start from the eight
  sections 0.1.0 had.
- Sections keep a stable key, so renaming or reordering keeps their text, margin threads
  and suggestions. **Removing a section loses nothing**: its text is kept, hidden, under
  "Removed sections", and **Restore** brings it back where it was, with its text.
- One template per project, live: the editor, margin threads, suggestions, "Draft with
  AI", MCP (`get_proposal`, `propose_proposal_section`) and both exports follow it at
  once.

#### The research step (Phase 8)

- Optional per project (Project settings → **Research**): **before evaluation**
  (New → Research → Evaluating …) or **before the proposal** (… Shortlisted → Research →
  Proposal). Off by default; projects without it see nothing new.
- A **checklist** (1–10 items, title, hint, required or not; three defaults: "Not already
  being done elsewhere", "Departments or teams consulted", "Data protection considered")
  answered in plain text on the idea's **Research** panel, with who answered and when.
- **The gate**: an idea can't cross into a status after Research while a required item is
  open (a status change, a board drag, the first evaluator invite, "Ask AI to evaluate",
  starting the proposal). Moving back or closing is never held up. Project and platform
  admins may **Move anyway** (also Invite, Ask, Start anyway), with an optional reason,
  in the audit log and the feed.
- **Similar ideas** (similar titles and summaries in every project you can see, archived
  ones too, never held ideas, no scores) and **Ask AI to research** help with the check.
- The board's **Research column** and cards show "2 open" or "Ready"; the proposal editor
  and both exports end with a **Research and consultation** appendix; public submitters
  never see Research (their tracking page keeps the stage before it).

#### The research assigned to a person, outside researchers (Phase 8b)

- **One researcher per idea** (nobody = the owner does it) with an optional **research
  due date**. The owner, project admins and platform admins ask someone (in a session);
  in a **private** project only admins may ask someone without a role there. The
  researcher can **Hand back**. "Start research" asks who and by when.
- **Asked to research** and **Research reminder** notifications (2 days before and on the
  due date, at the digest hour, while required items are open): in the app and by email,
  with per-type preferences, the digest and unsubscribe links; never score data.
- My work's **Research to do** (overdue first) and the sidebar's Research badge; Research
  cards show the researcher.
- **An outside researcher** (no role in a private project) sees **that one idea** only:
  its overview, comments, the feed's allow-listed events, the checklist and Similar ideas
  among what they could see anyway. Never scores, the evaluation area, the proposal, the
  AI panel or the project (404), through REST, MCP, search, ⌘K, My work and the inbox
  alike. Access ends at the next request when they are unassigned or hand it back, the
  idea is closed or the step turned off, they are deactivated, they leave the private
  project, or the project is made private (its admin is warned first with how many people
  lose access).
- Once an idea is **past Research**, the research is done: a researcher who isn't the
  owner or an admin can no longer change the answers, nobody new can be asked (the panel
  offers Remove), and a required answer can be changed but not cleared.

#### Continuous delivery from self-managed GitLab and GitHub (Phase 9)

- Every **push to main** builds the image (rootless BuildKit, or `docker buildx` on dind),
  scans it (Trivy: `HIGH,CRITICAL` with a fix fail the pipeline; a CycloneDX SBOM), and
  deploys **staging**. A **`vX.Y.Z` tag** checks the versions, rebuilds with that version,
  deploys staging, publishes the release (SBOM, chart) and waits at the **production
  gate**, which deploys the very digest staging ran.
- **GitLab self-managed** reaches the cluster only through the GitLab agent for
  Kubernetes (one agent per environment, namespace-scoped rights, protected refs only; no
  cluster credential in GitLab). **GitHub Actions** deploys from self-hosted runners in
  your network (ARC) whose pods have no rights, with a namespaced kubeconfig per
  environment.
- One script, **`scripts/deploy.sh`** (deploy, rollback, smoke, status), for both CIs and
  people: a render check, `helm upgrade --atomic` by digest, `helm test`, a
  production-safe smoke, and an automatic rollback when any of them fails; migration
  heads recorded on every revision, so a rollback across a migration is refused unless
  forced; one CI per environment.
- Rehearsals: `make k3s-deploy` (the script as a namespaced deployer on a local k3s) and
  `scripts/ci-local/` (a whole self-managed GitLab with its registry, agents and a runner,
  on which the pipeline ran end to end). `.gitlab/CODEOWNERS`, `make check-workflows`
  (actionlint, zizmor, gitlab-ci-local) and `make check-migrations` (expand/contract
  lint) keep the delivery path reviewed.

#### Review fixes

Each phase had security, code and UX reviews (Phase 8b also a guest-access review and an
adversarial check of the follow-ups); every finding was fixed or decided by the lead
([decisions.md](decisions.md), the summaries list each one). The main ones:

- **Phase 8:** a required answer can't be cleared once the idea is past Research;
  blank-looking answers and titles (only invisible characters) are refused; titles that
  Postgres folds together ("Idea", "İdea") are a 422, not a 500; public tracking history
  keeps the step a move happened under; unsaved answers are kept as drafts; focus never
  drops to the page after removing a row; calmer badges and warnings; hints visible, not
  placeholders; 390 px fixes; My work faster (migration 0014's indexes, 10 ideas per owned
  group).
- **Phase 8b:** an AI research run reads only what the idea's guest researcher can
  (`search_ideas`, `get_idea`); a guest's "last activity" comes from their own feed;
  "Asked to research" emails wait 5 minutes when the idea was just passed round, and one
  person's requests email at most 20 people an hour; overdue due dates stay choosable; a
  guest's @mentions list only people on the idea; focus after Hand back and when access
  ends; one feed line per assignment; the researcher's answers lock after Research (D1);
  outsiders leave when a project goes private (D2); nobody new is asked past Research.
- **Phase 9:** 3 high, 8 medium and 12 low findings (who can deploy production, runner
  pods' standing rights, cache poisoning, deploy-only runners, pipeline variables,
  migration labels after a rollback, schema breaks, GitHub's production gate, the air
  gap, run order, concurrent deploys) and 9 defects the live GitLab run found, all fixed
  or documented.
- **Release verification (this release):** the CI k3s job's external-database test
  (`scripts/k3s-test-external-db.sh`) couldn't create its database since Phase 7's
  non-superuser Postgres role, nor reach it through the bundled Postgres's NetworkPolicy;
  one notification test failed between midnight and 08:00 UTC. The re-captured
  screenshots found two lines the research work had missed: the unsubscribe page's
  footer didn't name research, and Admin → Email didn't list the research reminders.

### Known issues in 0.2.0

| Item | Detail |
|---|---|
| **Not verified: GitLab Premium's protected environments and deployment approvals** | The live run used GitLab CE (the Free tier): the gate there was the protected tag's manual job. The Premium setup the operator guide now leads with (protected environments, a required approval, Code Owners) is from GitLab 19.4's documentation and source, not a run. |
| **Not verified: the GitLab-specific changes after the live run** | Cache flags by protected ref, `DEPLOY_RUNNER_TAG`, the 90-minute timeouts, production refusing a `CD_ONLY` pipeline and the `migrations:lint` job were checked with gitlab-ci-local, GitLab's source and linters only. The local GitLab (`scripts/ci-local/`) wasn't run again for 0.2.0: it needs about 12 GB of free disk and the build machine had 7. |
| **Not verified: the Kubernetes executor, cosign, alpine/k8s** | Both build paths ran on GitLab's Docker executor (rootless BuildKit unprivileged, dind privileged); the Kubernetes executor's settings are documented, not run. cosign's image is on ghcr.io, whose blobs can't be fetched here: signing never ran. The default `DEPLOY_IMAGE` (alpine/k8s, 1.3 GB) didn't fit the disk; the live jobs used the `tools` target. |
| **Not verified: GitHub's runners, GHCR, ARC, environments** | No GitHub runner can register here. The workflows lint clean (actionlint, zizmor), and `deploy-env.yml`'s step ran in the cluster as an ARC runner (in-cluster identity) and with `KUBECONFIG_DATA`, but no workflow ran on GitHub: not the image build on GitHub's runners, GHCR, ARC itself, environments with required reviewers or `deploy.yml`'s `gh release download`. |
| **kagent is still verified against its CRDs and Soundings' fake agent only** | As in 0.1.0: no kagent controller or LLM has carried a run; "Ask AI to research" now reads only what a guest researcher could, against the fake. |
| The long CI jobs haven't run in a pipeline | The live GitLab run skipped lint, tests, e2e and the k3s job (`CD_ONLY`) to fit the disk; every command they run passed on the build machine. |
| Guest researchers in no project at all | The demo's two internal projects are visible to everyone, so "a researcher in no project" is tested on the SPA's mock only. Reminders by date are tested with a moved clock (the acceptance test), not by waiting. |
| Accepted from the reviews | A guest's open AI progress stream ends at its next 30 s re-check, not at once; a 404 for a hidden idea and one for a missing idea take different times (keys are sequential anyway); research answers aren't audited (who and when are recorded). |
| Per-pod limits, the 20-people p95, interaction timings at 4x CPU throttling, kagent's cancel, retention, invented sources, the Radix arrow-key case | As in [0.1.0](#known-issues-and-limitations). Unchanged by 0.2.0; `make -C backend test-slow` meets every 150 ms budget one request at a time on a quiet machine (My work for an owner and the board by score had 200 ms during Phase 8 and are back at 150). |
| The image is 525 MB | Ubuntu 24.04 with the PDF libraries; a slimmer final stage is still deferred. |

### Upgrading from 0.1.0

- **Migrations 0012 to 0015** run in one go before the new pods serve (`helm upgrade` or
  `scripts/deploy.sh`), rehearsed on 0.1.0's demo data: row counts unchanged. 0012 gives
  every existing project the eight proposal sections it had and leaves the research step off,
  so nothing changes for anyone until a project admin edits them; 0013 adds two trigram
  indexes for Similar ideas (seconds per 10,000 ideas); 0014 swaps indexes for My work
  and the cards' counts; 0015 adds the research assignment and two notification types
  (anyone who had every type off gets them off too). Downgrading is an emergency only
  (restore a backup if you can): below 0015 every research assignment and due date is
  lost, below 0012 custom template sections, checklists and answers.
- **The image defaults to production** (`SOUNDINGS_ENVIRONMENT=production`, since
  0.1.0): `soundings api` and `worker` refuse the built-in development key unless the
  environment says `development` (the chart's `devLogin=true` does).
- **No new Helm values.** The bundled Postgres's pod no longer carries the version and
  chart labels, so it restarts once on this upgrade (and never again on a deploy).
- **Moving a hand-installed release to continuous delivery**: create `soundings-app`
  and `soundings-break-glass` from the release's generated Secret first, or the secret
  key and break-glass password change ([operator guide, "Upgrades and
  migrations"](operator-guide.md#upgrades-and-migrations-pre-upgrade-hook-argo-cd-presync));
  `scripts/deploy.sh` then takes the release over, and refuses a rollback to the
  hand-installed revision (its migrations are unknown).
- **API (additive)**: proposal templates (`GET/PUT /projects/{slug}/proposal-template`),
  the research step (`GET/PUT /projects/{slug}/research`, `GET /ideas/{idea}/research`,
  answers `PUT/DELETE /ideas/{idea}/research/items/{item_id}`, `GET
  /ideas/{idea}/similar-ideas`), the assignment (`PUT/DELETE
  /ideas/{idea}/research/assignment`, `GET /me/research-to-do`), the `research` status,
  new fields on ideas, summaries, projects and My work, new error codes
  (`research_incomplete`, `research_step_off`, `ideas_in_research`, `unknown_section`,
  `research_answer_required`, `research_finished`, `researcher_not_eligible`,
  `outside_researcher_needs_admin`) and audit actions (`project.proposal_template_replace`,
  `project.research_step_change`, `project.research_checklist_replace`,
  `idea.research_override`, `idea.researcher_change`); MCP's `get_idea` carries the
  research and `research_guest` ([contract-phase8](api/contract-phase8.md),
  [contract-phase8b](api/contract-phase8b.md)). "Research this" is now called "Ask AI to
  research".
- **New checks**: `make check` also runs `check-workflows` and `check-migrations`; new
  migrations (0016 on) must be expand/contract safe, so a failed deploy can roll back.

### Decisions to confirm in 0.2.0

The lead's defaults ("Proposed" or "Decided (lead)" in [decisions.md](decisions.md)),
built that way and easy to change; the product owner already decided the research
step's purpose and shape, outsiders as researchers, S1 (a, b), S8, the GitLab tier and
the scan gate.

**Research step and templates**
1. **"Crossing only"**: the gate guards moves *into* a status after Research; ideas
   already past it (before the step was turned on, or moved on anyway) move freely among
   later statuses, and reopening counts from the status the idea was closed from.
2. Similar ideas include **archived projects**; public tracking shows **the stage before
   Research**; answers are plain text, last write wins, not audited or notified.
3. Template and checklist saves are last write wins; no "Reset to the default eight";
   removed sections and items come back where they were.

**The researcher and guest access**
4. **What a guest researcher sees** (role matrix column R, table L): the idea's overview,
   comments, the feed without its evaluation events, the checklist, Similar ideas among
   what they see anyway; the inbox only status changes, comments, @mentions and the
   research notifications; their @mentions list only people on the idea. In an internal
   project an outsider keeps the non-member view and gains answering, commenting and
   Hand back.
5. **D1**: past Research a researcher who isn't the owner or an admin can't change the
   answers (409 `research_finished`).
6. **D2**: making an internal project private ends the research of everyone without a
   role in it, after a warning.
7. **D3**: "Asked to research" emails wait 5 minutes when the idea asked someone less
   than 5 minutes before; one person's requests email at most 20 people an hour (then
   in-app only); one notification per assignment.
8. **D4**: an owner asked by name stays the researcher when the idea changes owner.
9. **L2**: past Research nobody new can be asked (Remove only; moving the idea back lets
   the owner ask again).

**Continuous delivery**
10. **One CI per environment** (`SOUNDINGS_DEPLOY`; production needs staging in the same
    CI); tags are rebuilt with their version, and production deploys the digest staging
    ran.
11. **The deploy script's refusals**: across a migration head, an older pipeline's or an
    older `X.Y.Z`'s deploy, another CI's release, each unless `DEPLOY_FORCE=1`; *Prevent
    outdated deployment jobs* stays off on GitLab.
12. **Images and signing**: `DEPLOY_IMAGE` defaults to alpine/k8s by digest (the `tools`
    image recommended for production); cosign optional, with a key and no transparency
    log, verified by an admission policy rather than in the CI.
13. **GitHub**: a 30-day namespaced token per environment (`KUBECONFIG_DATA`, renewed
    monthly); on Pro and Team the production gate is one listed person
    (`SOUNDINGS_PRODUCTION_DEPLOYERS`), not two; private Free repositories aren't
    supported for production.
14. The rollback jobs stay `action: access` (protected environments and approvals still
    apply to them), and the deployer's optional kinds (kagent, Gateway API,
    ServiceMonitor) stay in its one ClusterRole.

## 0.1.0

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

### What's in it, by area

#### Ideas, owners and evaluators (Phase 1)

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

#### Sign-in and access (Phase 2)

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

#### Email and notifications (Phase 3)

- Seven notification types, in the app (the bell and the inbox) and by email, chosen
  per type: immediately, in a daily digest, or off. Reminders arrive before and on the
  due date, at a set hour in the instance's time zone.
- A **transactional outbox** sent by the worker, with retries and backoff. An SMTP
  outage delays mail; it never loses it. Admin → Email shows the settings in effect,
  the outbox and a test email.
- Branded HTML and text emails with one-click unsubscribe (RFC 8058) and scoped
  unsubscribe links. **Emails never carry scores.**

#### Proposals, public submission and branding (Phase 4)

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

#### API keys and MCP (Phase 5)

- **Personal API keys** have scopes (`read`, `write`, `evaluate`, `mcp`), an optional
  expiry and an optional restriction to some projects. A key is shown once and can't be
  changed afterwards. It never does more than its owner may do right now, and revoking
  it cuts access at the next call.
- An **MCP server** at `/mcp` offers ten tools over the same services and policy as the
  REST API: search and read ideas (blind), create ideas, comment, evaluate, propose
  proposal text, and more. Every call is audited. Claude Code, Claude Desktop and the
  SDKs connect with a key ([mcp.md](mcp.md)).

#### AI assistance through kagent (Phase 6)

- Platform admins **register kagent agents** (namespace and name, protocol, purposes,
  projects). Each agent gets a service account and one key, shown once with its Secret
  and `RemoteMCPServer` manifests.
- Owners can use **Ask AI to evaluate**, **Research this** and **Draft a section**.
  These start durable runs that the worker sends over A2A, with a deadline, cancel,
  retries and live progress over SSE.
- Agents act through `/mcp`, confined to the idea of their open run and **always
  blind**. An AI evaluation carries a rationale and cited sources per criterion and an
  AI badge. It stays **out of the aggregate until the owner includes it**.

#### Polish and hardening (Phase 7)

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

### Known issues and limitations

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

### Upgrade notes

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

### Decisions to confirm

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
