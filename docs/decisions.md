# Decisions log

A running log of product decisions and simplifications, newest section last. Anything
that shapes the architecture also gets an ADR ([adr/](adr/README.md)); this file is for
the smaller calls that would otherwise live only in a chat. Guiding rule from SPEC:
**simple beats configurable**. Status: **Decided**, or **Proposed** (the lead's default,
awaiting the product owner; build it this way unless told otherwise).

## 2026-09-30 · Phase 0

### Answers to SPEC section 16 (Decided, [ADR 0009](adr/0009-product-name-and-open-questions.md))

| Question | Answer |
|---|---|
| Product name, logo, colours | **Soundings**. Calm neutral greys, one accent (deep ocean blue `#1d5fa8`), Inter bundled. Wordmark only; admins upload a logo. |
| Can members volunteer to own ideas? | Yes, when the project allows it: `allow_volunteer_owners`, default `true`. |
| Who can be an evaluator? | Project members with role `member` or `admin` only (direct or via group). |
| Evaluation window and reminders | Due 7 days after the first invite (per-project `default_evaluation_days`). Reminders 2 days before and on the due date, fixed. |
| Classification markings | None. |

### Things we chose not to build (SPEC non-goals, Decided)

- Configurable workflow engines, custom fields, per-project stage designers. The five
  statuses are fixed; admins may only rename labels.
- Webhooks, duplicate detection, file attachments (possible later, not now).
- Multi-organisation tenancy: one instance is one organisation; projects separate work.
- Our own LLM integration: all AI goes through kagent (A2A + our MCP server).
- Classification markings (section 16 answer).
- Configurable reminder schedules, digest times or notification types beyond the
  per-type immediate / daily digest / off preference.

### Simplifications and defaults set while writing the role matrix

| Decision | Status | Why |
|---|---|---|
| Only platform admins create projects (and name the first project admin). | Proposed | One organisation per instance; keeps project sprawl in check. Easy to widen later. |
| "Anonymous" submission means the public form (`/{project}/submit`), which signed-in users can use too. The internal form always records the submitter. | Proposed | Avoids a second anonymity concept with its own visibility rules. |
| Submitters may edit their idea only while it is `new`; the owner and admins can edit until it is closed (admins always). | Decided | Evaluators score what they read; edits after that go through the accountable owner. |
| Blind evaluation is never lifted by a role, and closing evaluation doesn't lift it for evaluators who never submitted. | Decided | One rule, no exceptions, easy to test ([role matrix §3](role-matrix.md#3-blind-evaluation-exact-visibility-rules)). |
| Emails never contain scores, for anyone. | Decided | Removes a whole class of blind-evaluation leaks; emails link to the app. |
| Other people's evaluator progress is shown as submitted / not submitted; "draft" is visible only to its author. | Decided | Draft status carries no useful signal for others. |
| Admin actions (members, rubric, settings, platform, API keys) are session-only, never available to API keys. | Decided | Keys are for automation and agents; admin changes stay in the audited UI. |
| Owner/evaluator assignment needs a real project role; being platform admin is not enough. | Decided | Keeps assignment lists meaningful; platform admins add themselves as members first. |
| Only the owner and admins can trigger AI evaluation, research and drafting. | Proposed | AI runs cost money and write into the idea; the accountable owner decides. |
| Members (not viewers) can suggest proposal section text; the owner accepts or discards it. | Decided | Same mechanism as AI drafting, so no extra concept. |
| Viewers and internal non-members can watch ideas and export proposals. | Decided | Both are reads; watching only affects their own notifications. |
| Denials: 404 when you may not know the resource exists, 403 when you can see it but not act, 409/422 for state and input conditions. | Decided | Private projects don't leak; clients get a stable `code`. |

### Engineering choices made with the Phase 0 research

| Decision | Status | Reference |
|---|---|---|
| psycopg 3 is the only Postgres driver (no asyncpg), shared by SQLAlchemy and procrastinate. | Decided | [ADR 0002](adr/0002-backend-stack.md) |
| Email outbox table + in-transaction job defer; capped exponential retry. | Decided | [ADR 0003](adr/0003-background-jobs-procrastinate-and-email-outbox.md) |
| Target kagent **v0.10.2** (`kagent.dev/v1alpha2`); talk A2A through `a2a-sdk` (1.0 with 0.3 fallback); re-verify against the installed cluster in Phase 6. | Decided | [research R2](research/kagent-a2a-claude-code-frontend.md) |
| MCP server uses `mcp` 2.x (`MCPServer`), stateless JSON mode, exact-path route at `/mcp`, POST only. | Decided | [research R1](research/backend-libraries.md) |
| Pin TypeScript 5.9.x (7.x breaks typescript-eslint and openapi-typescript); MSW 2.15 rather than the 2-day-old 3.0; Playwright 1.56.1 to match the pre-installed Chromium. | Decided | research R2 |
| Proposal editor: one native `<textarea>` per template section with Write/Preview, no editor library. | Decided | research R2 (CodeMirror +172 KB, md-editor +361 KB gzip) |
| Components are hand-written on the unified `radix-ui` package; no shadcn CLI. | Decided | [ADR 0007](adr/0007-hand-built-design-system-on-radix.md) |
| SPEC's "security-reviewer" is the `code-reviewer` agent type (it covers OWASP ASVS L2). | Decided | [ownership.md](ownership.md) |
| ALTCHA: Python `altcha` 2.x with the `altcha@3` widget, random mode, cost ~5,000; store used challenge signatures until expiry (no built-in replay protection). | Decided | research R1 |

## 2026-09-30 · Phase 1

Calls made while building ideas, owners and evaluators. The contract
([contract-phase1.md](api/contract-phase1.md)) is unchanged by all of them.

### Product and API behaviour

| Decision | Status | Why |
|---|---|---|
| The first project admin is the platform admin who creates the project (no admin picker in the dialog); they can hand over in Members. | Proposed | One less field; the contract's `admin_user_id` stays for the API. |
| "New project" shows for platform admins (`CurrentUser.is_platform_admin`). The contract gets no `CurrentUser.permissions.can_create_projects` in Phase 1: `project.create` is exactly "platform admin" in the role matrix, so the flag would only repeat `is_platform_admin`. Add it when another rule can grant project creation. | Proposed | Everything else in the SPA follows the API's `permissions`; this one rule is the role itself. |
| Ideas live at `/ideas/{KEY}` (not `/p/{project}/ideas/{key}` as in wireframe 03): keys are unique across projects and the URL survives a project rename. | Decided | Shorter links, one route. |
| `MyEvaluation.editable` means "you could save now": assigned with a member/admin role, evaluation open, project not archived. | Decided | The sheet needs one flag for read-only. |
| `aggregate.criteria` leaves out active criteria that have no scores yet (no mean, min or max to show), so it can be shorter than the rubric. | Decided | No invented numbers. |
| An unknown or deactivated user as owner or evaluator gets 422 `assignee_not_eligible`, not `user_not_found`. | Decided | One code for "can't be assigned". |
| `cannot_remove_self` (403) applies to people who may manage evaluators; a plain member removing anyone gets 403 `forbidden`. Any 403 on an idea edit is `not_submitter`; a non-author editing or deleting a comment gets `not_author`. | Decided | Matches the contract's error rows. |
| Due dates are stored and returned in UTC; the SPA shows them in local time. Evaluators invited together keep the request's order. | Decided | |
| Editing a submitted evaluation is explicit ("Edit my evaluation" → "Save changes"), not autosaved, so it isn't marked "edited" on every keystroke. Drafts autosave (800 ms, on close, when the tab is hidden). | Decided | `edited_at` must mean a deliberate change. |
| The evaluate sheet says "Draft saved just now", "3 minutes ago" or "3 days ago" (relative up to a week, then a date); the ticking time isn't re-announced to screen readers. | Decided | A bare time from two days ago read as today (integration); the UX review (m3) preferred relative wording. |
| Command palette: what you see highlighted is what Enter opens. Late search results never move the highlight off a current item or one you moved to; it only follows the best match while it rests on results for an earlier query. | Decided | Results arriving mid-keystroke opened the wrong idea (KB-06). |
| cmdk's Ctrl+N/P/J/K list bindings are on for macOS only: elsewhere Ctrl+K is the palette shortcut, which cmdk swallowed as "move up" (KB-07). | Decided | One shortcut, one meaning. |
| On the Evaluations tab the aggregate card shows only below `lg`, where the sidebar (and its Score section) is folded away. | Decided | It appeared twice side by side. |
| Phones: filters scroll sideways (no bottom sheet), board columns snap-scroll (no status tabs), the list scrolls inside its panel, the comparison table pins its Mean column. Project settings are General, Members, Rubric and Status labels; Public form and Branding arrive in Phase 4. Comments are flat, without @mentions, until Phase 3. | Decided | Simple beats configurable; the wireframes' extras wait for their phase. |
| Muted text (`text-muted`) is at least 4.5:1 on every canvas and under the quiet fills (`bg-subtle`, `bg-subtle-hover`: chips, input add-ons, selected rows) in both themes; `styles/tokens.test.ts` checks it. Light `#63636d`, dark `#9e9ea8`. | Decided | Dark muted text on a selected palette row was 3.75:1; fixing the token fixes every such pairing, not just the two axe found. |
| Service accounts can be project members (Phase 6 needs this) but can't be a project's first admin, sign in, or appear in user search. | Decided | Agents act through API keys only. |

### Sessions, hosts and operations

| Decision | Status | Why |
|---|---|---|
| Sessions end after **12 hours idle or 7 days** in total (`SOUNDINGS_SESSION_IDLE_TIMEOUT`, `SOUNDINGS_SESSION_MAX_AGE`; chart `sessions.idleTimeout`, `sessions.maxAge`). The cookie is HttpOnly and SameSite=Lax; `Secure` is set except on plain-http requests outside production (`SOUNDINGS_COOKIE_SECURE` overrides it, through the chart's `extraEnv`; `false` is refused in production). Only a SHA-256 hash of the token is stored; signing in always rotates it. | Decided | A working day without re-login, a week at most. |
| CSRF: a header compared in constant time with the session's token; 403 `csrf_failed`. Logout is exempt (always 204; SameSite=Lax already blocks cross-site posts). | Decided | |
| Requests for a host not in `SOUNDINGS_BASE_URLS` get 400 `invalid_host` (localhost is allowed outside production; `/healthz` and `/readyz` are exempt). Every public host must be listed in the chart's `baseUrls`, and in-cluster callers use one of them. | Decided | Host-header attacks; links in emails need the canonical host. |
| `/metrics` has its own port (9090, `SOUNDINGS_METRICS_PORT`; chart `metrics.port`) and is never served through the ingress. | Decided | Metrics aren't public. |
| Audit action names (ids only in the entries): `idea.delete`, `idea.owner_change`, `idea.status_change`, `evaluator.add`, `evaluator.remove`, `evaluation.submit`, plus the project and member actions in `app/services/audit.py:AUDIT_ACTIONS`. | Proposed | Phase 2 builds the audit view on them. |
| The API process freezes its startup heap (`gc.freeze()`, once per process, in the lifespan): otherwise the first full collection (~80 ms) lands on a random request. | Decided | Board p95 with 10k ideas 151 ms → 75 ms. |
| Demo data (`soundings seed`) is for development only: it refuses `SOUNDINGS_ENVIRONMENT=production` without `--force`, does nothing once the database has projects (so the chart's `demo.seed` hook is safe on upgrades), and `--reset` wipes application data first. The chart refuses `demo.seed` without `devLogin`. The seed reuses existing accounts matched by email and always makes alice a platform admin. | Decided | Realistic screenshots and demos without risking real data. |
| E2E tests run locally against the working tree (Postgres in Docker, a Vite build, `soundings api` on :8100) and in CI against the built image (`make demo`, `E2E_BASE_URL`). | Decided | The same process serves API + SPA either way; local runs don't need an image build. |
| Review screenshots: `docs/screenshots/phase-1/` is the real-stack set (`npm --prefix e2e run screenshots`, seeded data); the frontend's mock-data captures go to `phase-1/mock/`. | Decided | The names overlapped and the mock set overwrote the real one. |

### Phase 1 close: code, security and UX review

What the reviews changed, and the calls made on findings that were not simply fixed.
Details and tests: [phase-summaries/phase-1.md](phase-summaries/phase-1.md#review-findings-and-outcomes).

| Decision | Status | Why |
|---|---|---|
| Request bodies are capped at **1 MiB** by the app (413 `content_too_large`, before authentication; a too-large `Content-Length` is refused unread, chunked bodies are cut off). The chart's production example sets ingress-nginx to the same `1m`. | Decided | A 200 MB anonymous post pushed the API to 690 MB (99 MB with the limit); the limit can't depend on the ingress. |
| Every write to an idea locks its project row (`FOR KEY SHARE`) before the idea row (`load_idea(for_update=True)`); `replace_rubric` locks the project. | Decided | One lock order: no deadlock (500) or stale cached aggregate when a rubric is replaced during an evaluation save. |
| NUL characters in any body, `q` or `tag` are a 422; cursors holding NUL or values their column can't hold are 400 `invalid_cursor`; `due_at` must be between a year ago and five years ahead (422). The SPA's date pickers stop at five years. | Decided | Malformed input is the client's error, never a 500. |
| `soundings seed --reset` needs `--force` as soon as anyone who is not a demo person has an account. | Decided | The reset is a development tool; it must never wipe a real database by default. |
| `GET /me/work` stays **uncapped** in Phase 1 (review F9): `counts.evaluations_due` is still the length of the list. | Decided | p95 118 ms with 1,000 evaluations due among 10k ideas, inside the 150 ms budget. Revisit (cap at 100, count = total) if real data says otherwise. |
| The `__Host-` cookie prefix (review F10) is **deferred to Phase 2** with single sign-on. | Decided | It requires `Secure`, which breaks plain-http localhost development, and the SPA reads `soundings_csrf` by name; Phase 2 reworks sign-in anyway. |
| Unsent drafts (new idea, comments) are stored per user in the browser and cleared on sign-out, on a 401 and when another person signs in on the same browser. A draft is therefore lost when the session expires. | Decided | A shared computer must not show one person's draft to the next; security over convenience. |
| `?next=` after sign-in accepts only same-origin paths (no `//`, `\`, control characters or other origins). | Decided | Open-redirect hardening. |
| Dialogs, sheets and menus return focus to whatever opened them (`components/ui/return-focus.ts`), or to `#main` when they navigated away. | Decided | Keyboard users carry on where they were (review M1). |
| Server-filtered pickers highlight the top result as you type (`useTopResult`), "Remove owner" hides while searching, and `⌘↵` inside a form submits it. Empty/loading/error messages render outside the listbox (`CommandList empty`). | Decided | Type a name, press Enter, get that person (review M2, M3, M6); Enter had removed the owner. |
| The palette ranks commands and projects above idea results and groups by best match; fuzzy threshold 0.1. | Decided | "Settings" and project names were buried under weak idea matches (review M4). |
| Project settings ask before leaving with unsaved edits (in-app links, Back, closing the tab); the save bar sticks while there are changes. | Decided | Edits were lost silently (review M5). |
| The personal Settings page is Account, Appearance and "Projects you manage"; unknown routes show a 404 inside the app shell. | Decided | The old page was a placeholder; a 404 without navigation was a dead end. |
| Kept from the UX review: the full-width first "Evaluate" button on phones; filter chips may wrap at 1440 with three or more active filters. Deferred to Phase 7 polish: smaller empty-section cards, a scroll hint on the phone filter row (needs a gradient token), uneven meta-row wrapping on phones, the evaluate sheet header's height. | Proposed | The first is the page's one primary action, in thumb reach; the rest are polish, not defects. |
