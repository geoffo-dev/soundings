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
| Sessions end after **12 hours idle or 24 hours** in total (`SOUNDINGS_SESSION_IDLE_TIMEOUT`, `SOUNDINGS_SESSION_MAX_AGE`; chart `sessions.idleTimeout`, `sessions.maxAge`; *7 days in Phase 1, shortened in Phase 2: review L3, below*). The cookie is HttpOnly and SameSite=Lax; `Secure` is set except on plain-http requests outside production (`SOUNDINGS_COOKIE_SECURE` overrides it, through the chart's `extraEnv`; `false` is refused in production). Only a SHA-256 hash of the token is stored; signing in always rotates it. | Decided | A working day without re-login; IdP removals and group changes apply within a day. |
| CSRF: a header compared in constant time with the session's token; 403 `csrf_failed`. Logout is exempt (always 204; SameSite=Lax already blocks cross-site posts). | Decided | |
| Requests for a host not in `SOUNDINGS_BASE_URLS` get 400 `invalid_host` (localhost is allowed outside production; `/healthz` and `/readyz` are exempt). Every public host must be listed in the chart's `baseUrls`, and in-cluster callers use one of them. | Decided | Host-header attacks; links in emails need the canonical host. |
| `/metrics` has its own port (9090, `SOUNDINGS_METRICS_PORT`; chart `metrics.port`) and is never served through the ingress. | Decided | Metrics aren't public. |
| Audit action names (ids only in the entries): `idea.delete`, `idea.owner_change`, `idea.status_change`, `evaluator.add`, `evaluator.remove`, `evaluation.submit`, plus the project and member actions. Since Phase 2 the closed set is `app.schemas.audit.AuditAction` (sign-in, user, group and access actions, and `evaluation.close` / `evaluation.reopen`). | Decided | The Phase 2 audit view is built on them. |
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

## 2026-10-01 · Phase 2 contract

Calls made while writing the sign-in and access contract
([contract-phase2.md](api/contract-phase2.md), section 5 has the full list with
reasons). Status **Proposed** = the lead's default; build it this way unless told
otherwise.

### Sign-in

| Decision | Status | Why |
|---|---|---|
| One OIDC provider per instance, configured only by Helm values / `SOUNDINGS_OIDC_*`; Admin settings → SSO is read-only (effective values, secrets masked, the redirect URIs to register per base URL). | Decided | SPEC "simple beats configurable"; the IdP client is set up with the deployment anyway. |
| New settings beyond the chart's: `SOUNDINGS_OIDC_EXTERNAL_ID_KIND` (defaults to the claim path's last segment), `_MATCH_VERIFIED_EMAIL` (true), `_AUTO_CREATE_USERS` (false). No display-name claim or button-label settings (fixed: `name` → `preferred_username` → email local part; "Sign in with SSO"). Production refuses a non-https issuer, and with SSO configured non-https base URLs. | Proposed | Each maps to a SPEC sentence (login matching, auto-create "if enabled"); defaults are the safe choice; the cut ones were configurable for its own sake (contract review). |
| Login state (state, nonce, PKCE verifier, redirect URI, `next`, 10 minutes) is sealed into the HttpOnly `soundings_oidc` cookie (AES-256-GCM, key derived from the secret key); nothing is stored until the callback. *First a server-side `oidc_login_attempts` table; changed by review H1 (below).* Claims come from the validated ID token; no userinfo call. | Decided | ADR 0005 amendment: no table that anyone could fill; the browser can't read or change the attempt; one validated source of claims. |
| Login matching stops at the first user found: a deactivated, service, break-glass or already-linked match denies rather than falling through. Email matching and auto-create (off by default) need `email_verified` true (missing = unverified); auto-create refuses an address any account already has; a user with an external ID of the configured kind is linked only by it. One identity per user per issuer; admins unlink to re-match (which also ends their SSO sessions). | Decided | Account takeover and duplicate accounts are the failure modes that matter. |
| The external-ID claim must come from an attribute only IdP admins can set (Keycloak: user-profile edit `admin`, unmanaged attributes not enabled; Entra ID: `oid` or `employeeid`). The operator guide, the setting's description and the SSO page say so. | Decided | Otherwise anyone can claim a pre-created account, platform admins included (contract review must-fix). |
| Denied sign-ins are audited with no actor; the matched user is the target. | Decided | A failed attempt must not be pinned on the account it tried. |
| `GET /auth/login` is throttled per client IP (60/minute, IPv6 per /64; the client IP comes from trusted proxies only, review M1); failed IdP metadata fetches are cached for 30 s. *The 10,000-live-attempts cap went with the attempts table (review H1).* | Decided | Public endpoint; the limit still fits an office behind one NAT address; no global cap anyone could exhaust. |
| Every session needs its sign-in method to be available (SSO configured, break-glass available, dev login on). Break-glass sessions last at most 8 hours (1 hour idle). Sign-out posts from another origin end nothing. | Proposed | One rule for every method; the emergency account shouldn't stay signed in all week; SameSite doesn't cover sibling subdomains. |
| The ID token is kept for `id_token_hint` only up to 3,072 characters; otherwise sign-out sends `client_id` and Keycloak asks to confirm. | Decided | Header limits on proxies (ingress-nginx 4 KB) would turn sign-out into a 502. |
| Entra ID group overage (groups claim replaced by `_claim_names`) denies the sign-in. | Proposed | Silently treating it as "no groups" would remove every managed membership. |
| Offboarding = deactivate. Sync only runs at sign-in, so IdP removal alone leaves a running session (up to 24 hours since review L3; 7 days before) and the memberships of people who never come back. | Decided | Documented in the operator guide; deactivation ends sessions at once and deactivated users count nowhere. |
| Profile fields (name, email) are not synced from claims after the first sign-in. | Proposed | Admin edits stick; nothing changes behind an admin's back. |
| Sign-out with the IdP is a new form-post endpoint (`POST /auth/logout/redirect` → 303 to the end-session endpoint with `id_token_hint`); `POST /auth/logout` stays 204. | Decided | No breaking change for API clients; the ID token never reaches JavaScript. |
| Cookies are named `__Host-soundings_*` whenever they are Secure (production, HTTPS); plain names on http development. Closes Phase 1 review item F10. | Proposed | Stops cookie tossing from sibling subdomains without breaking local development. |
| Break-glass works only while SSO is not configured, and its sessions stop working once that changes. For an SSO outage, the operator unsets `oidc.issuer` (helm upgrade) to bring it back. Throttled to 5 failures per IP (IPv6 per /64) per 15 minutes with `Retry-After`; no global cap; credentials compared as SHA-256 digests in constant time; production needs a 16+ character password; every action in its sessions is audited as `auth_method: break_glass`. Its address `break-glass@soundings.invalid` is reserved: `.invalid` emails can't be given to users. | Proposed | SPEC "off once SSO is configured"; the chart README's "and SSO outages" now means "by unsetting the issuer", which needs cluster access; a global cap would let anyone lock the emergency door. |
| `CurrentUser.auth_method` is agreed (persistent break-glass banner) but lands with identity's and frontend's Phase 2 work, because adding a field breaks Phase 1 tests and mocks they own. Meanwhile the SPA recognises the break-glass account by its reserved email. | Proposed | Keeps every check green at hand-off. |

### Groups and access

| Decision | Status | Why |
|---|---|---|
| IdP group values are normalised (trim, strip `/` at both ends, lower-case) on both sides; inner path segments are kept, so `admins` doesn't match `/innovation/admins`. The claim path is a top-level claim name or a dotted path. | Decided | Keycloak full paths work typed with or without the slash; no accidental matches between same-named subgroups. |
| A missing groups claim means "no groups": managed synced memberships are removed. | Decided | Fail closed; Keycloak omits the claim for users in no groups. |
| One membership row per user and group with `manual` and `synced` flags. Sync only sets/clears `synced`; an admin's "remove" deletes the row (so additive memberships can be removed). | Decided | Provenance is visible and manual memberships are never touched by sync. |
| Mapping changes apply at each user's next sign-in; to cut access now, remove the member (roles are evaluated live) or deactivate the user. | Decided | Sync needs the user's claims, which only exist at sign-in. |
| Project members list stays direct-only; new "everyone with access" list with sources (active users; it says platform admins and, on internal projects, every signed-in user can also view); `member_count` counts active users with an effective role; group grants are visible to project viewers like members. | Proposed | No breaking change; the Members tab can explain why someone has access. |
| Group search stays open to every signed-in user (`user.search`), not only admins (review suggestion declined). | Proposed | Group names and counts are directory data like the people picker's names and emails. |
| No new rule names: the existing `platform.*`, `project.manage_members` and `user.search` (now also the group picker) cover Phase 2. New conditions: c17 `cannot_change_self` (own active / platform-admin flags); c16 (Phase 1) now listed in the role matrix. | Decided | The matrix already had the platform rows; tests and policy keep their shape. |
| c11 (last admin) applies to project-level membership and grant changes only; deleting a group, removing a group member and sync are not blocked by it. It counts active, non-service admins only. c18 keeps one active platform admin besides break-glass (409 `last_platform_admin`). | Proposed | Sync must follow the IdP; platform admins can always repair a project; deactivated admins can't administer; two admins demoting each other can't leave none. |
| The audit log keeps everything indefinitely in Phase 2; entries may include the IdP issuer/subject and group mapping values, never emails, names, tokens or claims. | Proposed | Enough to debug a denied sign-in without personal data; retention can come later if needed. |

## 2026-10-01 · Phase 2 build and integration

Calls made while building and integrating sign-in and access. The contract changed
only additively (`CurrentUser.auth_method`, [contract-phase2.md §7](api/contract-phase2.md#7-changes-after-the-contract)).

### Sign-in

| Decision | Status | Why |
|---|---|---|
| The OIDC client is httpx + `joserfc` (`app/auth/oidc.py`); the unused Authlib dependency is gone and `joserfc` is a direct one ([ADR 0005 amendment](adr/0005-server-side-sessions-oidc-csrf.md#amendment-phase-2-as-built-2026-10-01)). | Decided | `authlib.jose` is deprecated, and its Starlette client wants a signed-cookie session the design doesn't use. |
| A callback whose `state` matches no attempt is `login_expired` without an audit entry; a found but expired attempt is audited. A callback that can't fetch the provider metadata redirects with `sso_unavailable` and audits reason `sso_failed`. | Decided | Anonymous requests can't fill the log; the operator still sees outages. |
| The sign-in page treats any `next` under `/api/` (also encoded) as unsafe and goes to My work, as the server does. "Your session has ended" is a notice on the sign-in page, not a toast. | Decided | One rule on both sides; the notice survives the redirect. |
| The break-glass banner keys on `CurrentUser.auth_method`; the dev-login list, people pickers and member assignment never offer the break-glass account. | Decided | The reserved email was a stopgap. |
| The chart keeps break-glass credentials in the api pods while SSO is on (the app ignores them), and still requires a client secret (no public clients through the chart). The worker gets neither. | Proposed | Unsetting the issuer in an outage brings back the same account without a second Secret. |

### Admin screens and access

| Decision | Status | Why |
|---|---|---|
| The admin pages live under **Settings** (Account · Users · Groups · Sign-in (SSO) · Audit log), shown to platform admins only; other people get the plain 404 at those URLs. On phones the SSO tab reads "SSO" (same accessible name) so the row fits at 390 px. | Decided | One settings place, like project settings; no admin crumb leaks. |
| Project Members is three lists (People, Groups, Everyone with access) instead of wireframe 07's single mixed list. | Proposed | Clearer once groups have hundreds of members; the access list explains every role's source. |
| Synced group members are read-only, with "Remove until next sign-in" in their menu. | Decided | Otherwise people synced into an additive group could never be removed (§3.6). |
| Revoking platform admin confirms instead of offering Undo. | Decided | A toast's Undo can't be clicked while the user sheet (modal) is open. |
| The audit log says "now a synced member of …" / "no longer a synced member of …" for sign-in sync, not "joined"/"left". | Decided | *Added* includes a manual member whose membership only became synced; "joined" was wrong for them (QA). |
| The SSO page says the client secret is "Set (never shown)", without naming where it came from. | Decided | It may come from an environment variable, not a Kubernetes Secret (QA). |
| Audit details where the contract left a choice: `user.update.sessions_ended` is a count; `user.sessions_end` is recorded even when 0 sessions ended; `group.delete.member_count` counts every membership, deactivated users included; update actions are recorded only when something changed; Phase 1's `details.auth` is still written next to `auth_method`. | Proposed | Each entry says what the admin did, even when it changed nothing visible. |
| The demo seed gives alice, bob and carol `employee_no` E1001–E1003 and adds five groups mapped to the dev realm (dev/README.md); every manual member already holds the granted role directly. | Decided | SSO sign-ins link and sync out of the box, while dev-login access stays as in Phase 1. |

### Testing and operations

| Decision | Status | Why |
|---|---|---|
| The local e2e stack runs Keycloak only with `E2E_SSO=1` (a fresh realm on every start); `@sso` specs skip without it. Break-glass is on without SSO (`admin` / `e2e-break-glass-password`). Reseeding uses `seed --reset --force` and stops the run if it fails. | Decided | Each run gets the data an identity links to once; a swallowed reseed failure had run specs on stale data (QA K-1). |
| `make check-backend` runs the real-Keycloak identity tests in a testcontainer (+45 s); CI provides Keycloak as a service and sets `SOUNDINGS_TEST_KEYCLOAK_URL` so they fail instead of skipping. | Decided | The acceptance is about a real IdP's tokens. |
| The operator guide documents Keycloak, Entra ID (`oid` external ID, groups as object ids, no email matching, overage refused) and Google (no groups, keep auto-create off unless the consent screen is Internal). An IdP behind a private CA is trusted through `SSL_CERT_FILE`. | Decided | The three providers SPEC names, with the settings that matter for each. |

## 2026-10-01 · Phase 2 review and final verification

Calls made on the code/security and UX reviews' findings and in the final verification
([phase-summaries/phase-2.md](phase-summaries/phase-2.md#review-findings-and-outcomes)
has every finding and its tests). Contract changes are additive and listed in
[contract-phase2.md §7](api/contract-phase2.md#7-changes-after-the-contract).

### Security

| Decision | Status | Why |
|---|---|---|
| Sign-in attempts are **stateless**: sealed (AES-256-GCM, HKDF key per purpose from `SOUNDINGS_SECRET_KEY`) into the HttpOnly `soundings_oidc` cookie; `oidc_login_attempts` and its 10,000 cap are gone (migration 0004). Changing the secret key restarts sign-ins in progress. Dependency: `cryptography` (already there through `joserfc`). | Decided | Review H1: anyone could fill the global cap and lock every user out of sign-in. |
| The app resolves the client address itself: `X-Forwarded-For` only from `trustedProxies` peers and only the **`trustedProxyHops`** (default 1) rightmost entries, stopping at the first untrusted one; uvicorn's proxy headers are off. The chart turns **`networkPolicy.enabled` on by default** (API reachable from the ingress once `networkPolicy.ingressFrom` is set, and from the release's pods; Postgres only from the release's pods), and its NOTES ask for `ingressFrom`. | Decided | Review M1: a spoofed leftmost entry gave a fresh throttle key per request, defeating the break-glass and sign-in throttles. |
| Sessions last **24 hours** at most (12 hours idle) by default for every sign-in method; break-glass keeps 8 hours (1 hour idle). | Decided | Review L3: without an admin, an IdP removal or group change took up to 7 days to apply; one sign-in a working day is acceptable. |
| The stored ID token is sealed; migration 0004 clears plain-text ones. Signing keys are refetched hourly; production refuses non-https IdP endpoints; spans keep query parameter names only; `.invalid.` (trailing dot) is reserved too; `next` refuses `//`, `.` and `..` segments (also `%2e`) on both sides. | Decided | Reviews L4, L1, L5, L2, N2, N1. |
| Closing and reopening evaluation are audited (`evaluation.close`, `evaluation.reopen`; target the idea; only when the state changes). | Decided | Review L6: they change who can still score, so they belong with assignments and submissions. |
| c18 keeps counting platform admins who never signed in. | Decided | Review N3: the acting admin always remains (c17), and requiring a linked identity would block the break-glass setup, when no identity can exist yet. |
| Group members stay visible to project admins in the group picker and access list. | Decided | Review N4: accepted in the contract (directory data, like the people picker). |

### Sign-in and admin screens

| Decision | Status | Why |
|---|---|---|
| After `no_account` or `identity_conflict` the sign-in page offers **"Use a different account"**, which starts sign-in with `prompt=select_account` (`GET /auth/login?prompt=login|select_account`, else 422); the server adds `max_age=0`. Entra ID and Google show their account picker; Keycloak 26 ignores `select_account`, and `max_age=0` makes it ask to re-authenticate, with "Restart login" to switch. | Decided | Review M3: signing in again reused the refused account's IdP session; telling people to sign out of the IdP first was a dead end. |
| Sheets open focused on themselves (not their first field); closing the user sheet or leaving a group page returns focus to that row. Toasts move above a side sheet's footer. | Decided | Reviews M1, M2, m7. |
| The group page reads Members, Identity provider, Project roles, Details, Delete; "Test mapping" is a button that opens the shared sheet with the group highlighted. | Decided | Review M4: the page was too tall and the test box sat in the middle. |
| Project Members lists Groups before People; "Everyone with access (n)" is folded, open from the start only when nobody has a direct role, and hidden when no group has a role. Group names link to the group page for platform admins. Showing a group's mapping there needs `sync_mode` / `idp_values` on `ProjectGroupGrant.group` and is deferred. | Proposed | Review M6 (the reviewer's second option, not one merged list) and p7 (partly). |
| Break-glass sign-in without a `next` lands on Settings → Sign-in (SSO); without SSO that page shows a three-step setup checklist instead of the matching rules. | Decided | Reviews m1, m2: the break-glass admin is there to set up SSO. |
| The audit log's When filter offers Today, Last 7 days and Last 30 days (whole local days); refused break-glass attempts read "Break-glass attempt". | Decided | Reviews m8 ("24 h" became "Today", since the filter works in days) and m3. |
| Design-system additions: `PasswordInput` (show/hide), `ButtonShortcut` and `ariaKeys` in `kbd.tsx` (hint only from `sm` with a fine pointer), `Table cardFields="inline"` (phone cards as one muted line), `lib/return-to-row.ts`. | Decided | Reviews p2, p3, p5 and M1, solved once in the design system. |


## 2026-10-01 · Phase 3 contract

Calls made while writing the email and notifications contract
([contract-phase3.md](api/contract-phase3.md), section 5 has the full list with
reasons). Status **Proposed** = the lead's default; build it this way unless told
otherwise.

### Email and the outbox

| Decision | Status | Why |
|---|---|---|
| SMTP is configured only by Helm values / `SOUNDINGS_SMTP_*` (the chart's names); Admin settings → Email is read-only (credentials as "set" flags, not even the username) plus a test email and the outbox with retry (no cancel, after review). | Decided | SPEC section 6; simple beats configurable, like SSO. |
| When SMTP isn't configured, nothing is written to the outbox: notifications are in-app only, platform admins see a banner, test email and retry answer 409 `smtp_not_configured`. | Proposed | Nothing piles up to go out by surprise months later. |
| Emails are rendered at send time from the notification rows; the outbox stores no subject or body. Authorisation (`idea.view` plus the type's condition) is re-checked at send time; failing it cancels the email without contacting SMTP. | Proposed | The content follows what the recipient may see when it is sent; template fixes reach queued mail; no message bodies at rest. |
| The outbox row is the truth; each attempt is a `send_email` job; a worker claims a row (`sending`, 5-minute lease, the attempt must finish within 4 minutes) in a short transaction and records the result in another; a minute-by-minute sweep re-queues expired leases and lost jobs (once per row, only while SMTP is configured); finished jobs are deleted. At-least-once delivery with a fixed Message-ID. | Proposed | Amends ADR 0003's "lock the row while sending": no transaction held across SMTP, in-flight mail is visible, crashes recover by themselves, the job table stays bounded. |
| 12 attempts, backoff 30 s doubling to an hourly cap with jitter (about 5 hours), then `failed`; 4xx, connection and authentication errors retry, other 5xx fail at once, internal errors fail at once; `last_error` is our own phrase plus the SMTP code, never the server's text. Mail older than 3 days (digests 2) is cancelled, not sent late. | Proposed | "Briefly down" and a password rotation are covered; long outages become one admin action ("Retry all failed") while mail is still current; server replies can echo addresses. |
| Test emails go through the outbox with one attempt (5 per admin per 10 minutes); the page polls the row for the result. | Proposed | Tests the real path, worker included, with a quick answer. |
| Outbox rows are kept 30 days after sending or cancelling (failed: 90); notifications 90 days. | Proposed | Support questions are answerable; little personal data at rest. |
| Email HTML is table-based with inline styles, system fonts, no images or remote resources, dark-mode safe, with a plain-text part; `List-Unsubscribe` + `List-Unsubscribe-Post` (RFC 8058) and `Auto-Submitted` on notification mail. | Decided | Renders in common clients, air-gapped, and meets the one-click unsubscribe rules of large mailbox providers. |
| Emails carry the idea key and title, project, names, statuses, due dates and comment excerpts (200 characters); never scores, evaluation content, summaries or descriptions. | Decided | Blind evaluation (role matrix §3 rule 8); mail leaves the system, so it says enough to decide to click. |

### Notifications

| Decision | Status | Why |
|---|---|---|
| One fan-out, in the event's transaction, writes the in-app notification for every recipient and the outbox row for those who want email now. Preferences (immediate / daily digest / off per type) govern email only; the inbox always shows everything. | Proposed | One source of truth; SPEC's preferences are about email; unwatching stops follow-type notifications. |
| Seven types: owner assigned, evaluator invited, evaluation reminder, all evaluations in, status changed, new comment, mention (SPEC's "new comment / @mention" split in two). Defaults: status changes and comments in the digest, everything else immediate. | Proposed | Act-on items arrive now; followed items once a day. |
| Never notified: the actor, deactivated users, service accounts, the break-glass account, anyone without `idea.view`. One notification per person per event. | Decided | Respect authorisation; no noise about your own actions. |
| One instance time zone (`SOUNDINGS_TIMEZONE`, default UTC) and hour (`SOUNDINGS_DIGEST_HOUR`, default 8) for digests and reminders; reminder offsets `SOUNDINGS_REMINDER_DAYS` (default 2,0) are an operator setting. Amends the Phase 0 entry "reminders … fixed" and "no configurable reminder schedules or digest times": still no UI or per-user setting. | Proposed | SPEC asks for configurable reminders; an env value with the decided default is the least configuration that does it. |
| Reminders go out only on their own local day, phrased as a date; never for overdue evaluations, never before the invitation; a new due date reschedules. The digest skips notifications already read in the app and anything older than a week. | Proposed | No bursts or wrong countdowns after an outage or a moved date; overdue items are on My work; no email about what you've seen, never twice. |
| Digest and reminder bookkeeping use `notifications` (dedupe key, `email_mode`, `email_id`) and the outbox's idempotency key; no extra tables. | Proposed | Fewer tables; the same uniqueness makes the jobs idempotent. |
| Unsubscribe tokens are HMAC-signed (key derived from the secret key), not stored, no expiry; GET changes nothing; POST is RFC 8058 one-click; scopes: the email's type, the digest's types, or all. | Proposed | No table; old mail keeps working; link scanners can't unsubscribe anyone. |
| @mentions are `@[Name](user:<id>)` tokens from a picker that reuses `search_users?project=`; labels are rewritten to current names; at most 20 per comment; only people with a role in the project who can view the idea are notified, and at most 50 mention emails per author per hour; no mentions table. | Proposed | Unambiguous, can't impersonate, no new endpoint, can't flood mailboxes. |
| The bell's count is polled (`get_notification_summary`, capped at 100) and the poll doesn't keep the session alive; the SMTP banner flag (and, for admins, "email failing") rides on the same call instead of a new `CurrentUser` field; opening an idea marks its notifications read. | Proposed | No push channel in Phase 3; idle timeouts must still work with a tab open; `CurrentUser` changes break Phase 1–2 tests and mocks. |
| Admin email actions (test, retry) are audited without addresses. The two `AuditAction` values land at integration with frontend's audit phrases (contract-phase3 §7). | Proposed | Audit entries never hold emails; adding enum values breaks the frontend typecheck until the phrases exist. |

### Contract review (2026-10-01)

The Phase 3 contract review (4 must-fix, 10 should-fix, 9 to consider) was applied
before builders started; contract-phase3 §7 lists the schema changes.

| Decision | Status | Why |
|---|---|---|
| Digests collect at most 7 days of items; the daily cleanup turns older pending items off (after pruning outbox rows). | Proposed | Review must-fix 1: a pruned digest row set `email_id` back to null, and its items would have been mailed again 30 days later. |
| Bounded job table: `delete_jobs="successful"`, a daily `remove_old_jobs`, the sweep idle without SMTP and re-deferring each row at most once (`queueing_lock`). | Proposed | Review must-fix 2: procrastinate keeps every job by default. |
| One recipient per email: `MAIL_ADDRESS_PATTERN` for every address, `Address(addr_spec=…)` for `To`, `recipients=[address]` passed to SMTP. | Proposed | Review must-fix 3: `victim@corp.com,postmaster` reached two mailboxes. |
| The summary poll doesn't slide the session's idle timer. | Proposed | Review must-fix 4: an open tab kept sessions (break-glass included) alive for ever. |
| 4-minute attempt deadline under the 5-minute lease; send-time checks for out-of-date mail (3 days, digests 2), past-due reminders and types turned off; the fan-out runs after the request's last write; type conditions through the policy (`evaluation.submit_own`); reminders only on their own day; mentions only to project members, 50 emails per author per hour; `email_trouble` for admins; authentication errors transient, internal errors failed at once; the unsubscribe URL redirects browsers (303). | Proposed | Review should-fix 5-14. |
| No admin cancel; `outbound_email.idea_id` moves to Phase 4; no server details in the test email; SMTP port defaults to 465 for `tls`; unwatching stops only watcher-only notifications; mention length checked after rewriting. | Proposed | Review "consider" items taken. Not taken: a preferences flag for `.invalid` addresses (only system accounts have them, and they are never notified) and a `created_at` index for the 90-day notification cleanup (a daily scan is fine at this scale). |
