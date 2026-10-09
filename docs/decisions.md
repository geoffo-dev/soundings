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
| `GET /me/work` stays **uncapped** in Phase 1 (review F9): `counts.evaluations_due` is still the length of the list. | Superseded (Phase 7, C1) | p95 118 ms with 1,000 evaluations due among 10k ideas, inside the 150 ms budget. Phase 7's performance check found the sidebar fetching it on every load (up to 513 kB): My work now lists the first 50 (the count is the total), `GET /me/evaluations-due` pages on, and `GET /me/work/counts` serves the badges ([contract-phase7.md](api/contract-phase7.md)). |
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

## 2026-10-01 · Phase 3 build and integration

Calls made while building and integrating email and notifications. Contract changes
are listed in [contract-phase3.md §7](api/contract-phase3.md#7-changes-after-the-contract);
the known issues QA found (K3-1 to K3-5) are fixed below.

### Email, the outbox and the worker

| Decision | Status | Why |
|---|---|---|
| The fan-out runs from a **before-commit hook** (`app/db.py`) over the events `activity.emit` queued on the session: once, after the request's last write, in its transaction. Jobs and CLI code that emit activity open their session with `session_scope(…, settings=)`, or their notifications are recorded with email off. | Decided | An invitation carries the due date the same request set; a rollback drops notification, email and job together. |
| Both MIME parts are quoted-printable and headers are folded at 998 characters, so `List-Unsubscribe` stays a plain URL. | Decided | Found live: folding at 78 turned it into encoded words that mail clients can't use. |
| The plain-text part has a blank line before the action link and an RFC 3676 `-- ` before the footer. | Decided | Integration review of the text emails: the link ran into the paragraph, and clients now dim the footer and leave it out of replies. |
| HTML emails add a fixed 600 px table for Outlook for Windows only (`<!--[if mso]>`), `mso-padding-alt` on the button, and digest bullets in their own cell. | Decided | Word-based Outlook ignores `max-width` and link padding; long digest lines now hang under the text instead of under the bullet. |
| `last_error` gains "connection failed" (DNS, unreachable network), transient like "connection refused". | Decided | A stopped Mailpit reached by container name (`make demo`) fails name resolution, not the connection. |
| A deactivated recipient's queued email is cancelled at send time ("Not sent: no longer applies"). | Decided | Deactivated users are never notified; the same rule at send time. |
| `remove_old_jobs` is our own daily periodic task calling procrastinate's job manager; the data cleanup runs in the hourly schedule's run that falls in the digest hour, so a day the worker is down at that hour skips it (the next day catches up). | Superseded (review: the cleanup runs every hour) | procrastinate's builtin can't take the `timestamp` a periodic task receives; one cleanup a day is enough. |
| The worker counts `soundings_emails_*` metrics but serves no metrics port yet; operators watch the banner, the outbox and the logs. | Proposed | A worker metrics listener and ServiceMonitor are a small follow-up (platform). |
| Idea titles and display names reject line breaks and other control characters (422, `SingleLine`); names from SSO claims are collapsed to one line. | Decided | QA K3-1: headers were already safe, but CR/LF reached plain-text emails and the UI. |
| The seed fans each story step out to the inbox only (no outbox rows), backdated with the step; notifications older than 3 days are read; bob and carol have non-default email preferences. | Decided | A fresh demo shows a lived-in inbox without mailing anyone. |

### Screens

| Decision | Status | Why |
|---|---|---|
| The Settings section row shows for everyone (Account · Notifications), the admin pages after a divider; on phones it scrolls the current section into view. | Decided | Preferences belong in Settings; QA K3-2 (on Email or Audit log the active tab was off-screen at 390 px). |
| The bell polls every minute while the tab is visible and on focus; desktop opens a 28rem popover, phones a full-height sheet; `g i` opens the inbox page. In the popover and on phones the time sits on the sentence line, so titles keep their room, and a due date never breaks across lines. | Decided | QA K3-4: titles were cut to about 20 characters and "due Sat, 3 / Oct" wrapped. |
| The "Some emails aren't going out" banner says "See why in the outbox and retry any that failed", not "Soundings keeps retrying". | Decided | QA K3-3: a failed email (a test email has one attempt) isn't retried until an admin does. |
| Mentions are inserted from a picker as `@[Name](user:<id>)` and shown as name chips, never links; the picker also filters on the client, so Enter can't pick a stale match. | Decided | Unambiguous, can't impersonate; Enter picks what is visible (Phase 1 picker rule). |
| The `email-preview` sample of `status_changed` shows the new status in the idea card. | Decided | QA K3-5: the sample read "Moved to Shortlisted" over "Status: Evaluating" (real emails were right). |

### Testing and operations

| Decision | Status | Why |
|---|---|---|
| The local e2e stack, `make demo`, GitHub and GitLab CI run `soundings worker` with Mailpit as the SMTP server; `E2E_SMTP=0` / `DEMO_SMTP=0` run in-app only. `make demo`'s Mailpit is on 8026, the e2e stack's on 8125 (SMTP 1125). CI pins `axllent/mailpit:v1.31.3`. | Decided | The acceptance needs a real worker and SMTP server; ports don't clash with the dev Mailpit. |
| Specs that stop Mailpit are tagged `@smtp-outage` and run in their own Playwright project after every other spec, one at a time; they skip where Mailpit can't be stopped (GitLab services). Any `e2e` failure skips them (`--project=smtp-outage --no-deps` reruns them). | Decided | While Mailpit is down no other spec may wait for mail. |
| Digests and reminders are tested end to end in `backend/tests/acceptance/test_phase3_acceptance.py` with a moved clock and a real Mailpit, not in the browser. | Decided | E2E can't move the clock; the API test covers the schedule through real SMTP. |
| Mailpit's chaos mode (`MP_ENABLE_CHAOS`) isn't used yet. | Proposed | Optional QA request; stopping the container already covers the acceptance where it can run. |
| e2e AU-03 checks that a non-admin's Settings row lists exactly Account and Notifications. | Decided | Its old `toHaveCount(0)` passed only because it looked before the row rendered. |

## 2026-10-01 · Phase 3 review and final verification

Calls made on the security and UX reviews' findings and in the final verification
([phase-summaries/phase-3.md](phase-summaries/phase-3.md#review-findings-and-outcomes)
has every finding and its tests). Contract changes are additive and listed in
[contract-phase3.md §7](api/contract-phase3.md#7-changes-after-the-contract).

### Security and email

| Decision | Status | Why |
|---|---|---|
| **Unsubscribe links are scoped (L8):** a type's or the digest's link (and `List-Unsubscribe`) turns off only that; `all=true` is accepted only with a token scoped to `all`, which every email carries in a separate footer link, "Unsubscribe from all email" (else 403 `insufficient_scope`, a second check of c14). The SPA page offers no "all" button for other links. | Decided | A forwarded email (or one read over someone's shoulder) could silence every email its recipient gets; one more footer link keeps "stop everything" one click away. |
| **No token versioning or expiry** for unsubscribe links: links in old emails keep working until the secret key changes. | Decided (trade-off) | A per-user version would need a column, a migration and a "reset my links" flow for a narrow risk (someone holding an old email can only turn email *off*, which the owner sees in their preferences and can undo); mail sits in inboxes for months and must still unsubscribe. |
| One-line names (`SingleLine`) also reject U+2028 / U+2029 and the bidi controls U+202A–U+202E, U+2066–U+2069, U+061C; the marks U+200E / U+200F stay allowed. SSO names turn separators into spaces and drop those controls. | Decided | Input hygiene: emails were already safe (template values are one line without bidi controls), but such names could still reorder or break lines in the UI and in other clients of the API. |
| Comment excerpts read at most 2,000 characters with linear-time patterns. | Decided | Review H1: crafted comments stalled inbox and `/auth/me` requests for seconds. |
| Periodic jobs (priority 100) and `notify_event` (50) run before sends; a worker pauses sending after 5 connection failures in a row (30 s doubling to 5 min) without using attempts; test emails are always tried. | Decided | Review M1: a blackholed server let a backlog of 10-second timeouts delay the sweep, reminders and digests. |
| Mention-email cap counted under a per-author advisory lock; mention tokens rewritten until stable (nested tokens count toward the 20); the project-role rule re-checked at send time. | Decided | Reviews M2, L1 and a nit. |
| Template values are one line without C1 or bidi controls; a subject with `=?` is RFC 2047-encoded as a whole; Message-IDs use address literals for IP base URLs; branding colours must be hex. | Decided | Reviews L2, L3 and nits. |
| SMTP credentials go to worker pods only (`SOUNDINGS_SMTP_*_SET` tells the API); `smtp.existingSecret` needs both keys; the chart refuses it with `security: none` unless `devLogin`; a CA bundle must hold a certificate. | Decided | Reviews L4, L5: the API never sends mail. |
| Events for more than 500 people fan out in a `notify_event` job deferred in the request's transaction; smaller ones in the request at a constant number of statements. | Decided | Review L6: one UPDATE per person made big status changes slow requests. In-app items of such events appear once the worker runs. |
| The minute sweep fails jobs of workers without a heartbeat for 2 minutes; the data cleanup runs every hour; migration 0006 indexes it. | Decided | Review L7 and nits. |
| Retrying a test email counts toward the admin's 5-per-10-minutes limit. | Decided | Review L9: Retry was a way around the limit. Test emails stay retryable. |

### Screens

| Decision | Status | Why |
|---|---|---|
| Retry keeps the outbox filter and moves focus to the row's status with a "Queued again" toast; the default filter (failed plus queued when there are failures) is set once when the page opens. | Decided | UX M1. Deviation: the contract's UI default was "failed" only. |
| "Mark all read" waits for its Undo toast before telling the server (no "mark unread" endpoint), and the button keeps focus (`aria-disabled`). | Decided | UX M2. |
| The comment box shows "@Name" with a light tint while the stored text keeps the tokens; typing inside a name makes it plain text, Backspace after it removes the whole mention. Chips render only for text that is exactly a canonical token. | Decided | UX M3, security L1 (SPA). |
| Admin → Email reads status, outbox, test email, server, schedule; the banner links to `#outbox`. | Decided | UX M4. |
| The app and the email footers use the same type names ("evaluation requests"…). | Decided | UX m2. |
| Dates in emails stay in the instance's format, not the viewer's browser language. | Rejected (UX p4) | Emails can't know the reader's locale; the app's format follows the browser. |
| Undo on the "You're unsubscribed" page. | Deferred | Needs a public re-subscribe endpoint; people can sign in to their preferences. |

## 2026-10-01 · Phase 4 contract

Calls made while writing the proposals, public submission and branding contract
([contract-phase4.md](api/contract-phase4.md), section 5 has the full list with
reasons). Status **Proposed** = the lead's default; build it this way unless told
otherwise.

### Proposals

| Decision | Status | Why |
|---|---|---|
| One Markdown text per fixed template section, each with its own `version`; a save sends `base_version` and gets 409 `proposal_conflict` if that section changed since; identical text is a no-op. | Proposed | Autosave per section; different sections never collide; wireframe 05's Reload / Keep mine without silent overwrites. |
| No proposal status. Starting a proposal (owner or admins, c7) moves a Shortlisted idea to Proposal as an ordinary status change; outside Shortlisted and Proposal it is read-only but readable, commentable and exportable. Summary starts as the idea's summary. | Proposed | One lifecycle; the board shows where the work is. |
| Margin threads per section with flat replies, resolve and reopen (anyone who may comment; a reply reopens), delete only (no edit); deleting is `comment.edit_own` / `comment.delete_any`. No notifications or @mentions for them in Phase 4. | Proposed | Wireframe 05; no new `NotificationType` (it breaks the SPA's exhaustive maps and mocks); a later phase can add one. |
| Exports: two `GET`s (Markdown, PDF), 10 per user per minute, one PDF render per process at a time in a child process killed after 20 s (503 `export_busy`, also after 30 s waiting); at most 2,000 table cells render as tables (the rest as source); the aggregate line only for people who may see scores; never comments; PDFs in the project's effective branding with a local-only fetcher (`data:` and named bundled fonts only); Markdown rendered as the SPA renders it (raw HTML dropped, images as links, headings demoted through the parser). | Proposed | Role matrix E; no SSRF or local-file reads by construction; a hostile proposal can't stall exports or the event loop (measured in the contract review); the editor preview is the PDF; downloads work as plain links. |

### Public submission

| Decision | Status | Why |
|---|---|---|
| A public idea is an ordinary idea (`submitted_by_id` null) plus a `public_submissions` row (optional name and email, confirmation, opt-in, tracking token hashed and sealed). No IP address or user agent is stored; rate limits are in memory per IP (10 an hour) and in the database per project (100 an hour). No tags on the public form. | Proposed | One idea model; minimal personal data (UK GDPR); the per-project limit holds across replicas. |
| `ideas.held_for` (`email_verification`, `moderation`): held ideas are listed and counted nowhere, for anyone; admins work through a moderation queue (oldest first, a count on the board). Ideas held for verification are invisible even to admins and deleted after 3 days. Idea writes on a moderation-held idea are 409 `awaiting_moderation` (new c19) until approved. Moderation is on by default for a new form; verification off. | Proposed | Linear-style triage: no unreviewed posts on boards or in search, no notifications about ideas people can't see. Safe defaults for an open form. |
| Reject deletes the idea (spam, abuse, off-topic); a genuine but unwanted idea is approved and later closed as Rejected. Approve and reject send no email. | Proposed | Nothing personal kept from spam; the submitter of a real idea sees an honest status. |
| Email confirmation exists for every project with email: only confirmed addresses get status emails; the project setting also holds the idea until confirmed. The confirmation email is fixed text (no title or name: "Confirm your idea for <project>"). Confirmation tokens are signed (no table), valid 3 days, confirmed on a click (never on page load), and work while the instance switch is on even if the project's form was turned off. At most 3 confirmation emails a day per address (lower-cased, `+tag` folded, counted in the outbox, silent) and per submission. Without SMTP the form asks for no address (and drops `wants_updates`). | Proposed | The form can't be used to mail strangers anything but a short fixed note; mail scanners can't confirm; one less table. |
| Tokens never travel in URLs the server sees: links carry them after `#` (`/track#…`, `/verify#…`) and the SPA posts them in the body; tracking tokens are stored hashed (lookup) and sealed (for links in later emails), shown once. | Proposed | Ingress logs, traces (which carry URL paths) and `Referer` can't leak them; a database leak alone reveals none. |
| The honeypot is checked after every other check (ALTCHA and its replay row included), accepts any value, is described neutrally and uses a DOM name autofill won't fill; it answers 201 with a lookalike receipt and keeps nothing else. ALTCHA's HMAC key is derived from the secret key, challenges are bound to their form (`data.project`), solved challenges are remembered until they expire (replays fail). Public writes must be `application/json` (415 otherwise). | Proposed | Bots learn nothing from status, timing or proof of work; real ideas aren't lost to autofill; nothing extra to configure; other sites can't post through visitors' browsers. |
| Erasing a submitter clears name, address, confirmation, opt-in, the copy of what they sent and the tracking link and deletes the idea's submitter emails (which must name their idea); the idea stays. Admins erase from the idea page; the submitter erases from their tracking page ("Delete my details"). The form shows a fixed privacy notice. Retention: unconfirmed addresses go after 3 days, contact details of closed ideas idle for 180 days are erased automatically. | Proposed | UK GDPR erasure (without having to contact anyone), transparency and storage limitation without a settings screen. |
| The tracking page and status emails show the title and summary as submitted (a copy in `public_submissions`), never the idea's current text. | Proposed | Nothing the team writes or edits reaches the public. |
| Public form settings and moderation have their own endpoints (`/projects/{slug}/public-form`, `/moderation`, `/ideas/{idea}/submission…`) rather than new `Project` / `IdeaSummary` fields; contract-phase1's "`ProjectUpdate` gains those settings" is superseded. | Proposed | Additive contract: Phase 1–3 mocks and tests keep compiling. |
| New projects can't take the app's own top-level paths as slugs (`RESERVED_SLUGS`: `settings`, `track`, `verify`, `ideas`, `api`, …); an older project with one can't turn its form on. | Proposed | SPEC puts the public form at `/{slug}/submit`, in the app's URL space. |
| An instance switch `SOUNDINGS_PUBLIC_SUBMISSION_ENABLED` (chart `features.publicSubmission`, default on) turns every public form and link off. | Proposed | SPEC section 11's feature toggle; one place to stop intake in an incident. |

### Branding

| Decision | Status | Why |
|---|---|---|
| Global profile plus optional project overrides, every field "inherit" when empty. The signed-in app always uses the global branding; project overrides apply to the project's public pages, submitter emails and exported proposals. | Proposed | One consistent product for staff; projects still face the public in their own colours. |
| Colours hex only (`#rrggbb`), fonts from a bundled set of four (Inter, IBM Plex Sans, Source Serif 4, Atkinson Hyperlegible; OFL), app name one line (≤ 40), email footer plain text (≤ 500, ≤ 5 lines); checked in the API and the database. | Proposed | CSS injection impossible by type; air-gapped fonts for the SPA (`@fontsource`) and PDFs (bundled `woff2`). |
| Logos and favicons are PNG or SVG raw-body uploads stored in the database (no ICO or WebP): PNGs re-encoded with Pillow, SVGs parsed with expat (no DTD), allow-listed (no `use`, no reference chains, 2,000 elements, depth 32, a 10,000-element reference budget) and re-serialised, served with `nosniff`, a sandboxing CSP and immutable caching by id, shown only through `<img>`; no delete endpoint (unreferenced images expire after 24 hours) ([ADR 0012](adr/0012-branding-and-uploaded-images.md)). | Proposed | No object storage or multipart dependency; metadata and polyglots stripped; no rendering bombs (measured at 18–73 s in the review); SVG XSS blocked twice; cache busting for free. |
| Live preview is client-side only; `GET /branding` is public (the sign-in page needs it). | Proposed | No preview endpoint; branding isn't secret. |

### Platform and contract mechanics

| Decision | Status | Why |
|---|---|---|
| The runtime image moves to `ubuntu:24.04` with Ubuntu's Python 3.12, Pango/HarfBuzz, `tzdata` and DejaVu as a glyph fallback ([ADR 0011](adr/0011-ubuntu-runtime-image-and-weasyprint.md)). | Proposed | WeasyPrint's libraries install from Ubuntu's archive, which is reachable; Debian's isn't. |
| New `AuditAction` values `submission.approve`, `submission.reject`, `submission.erase`, `branding.update` are agreed but land at integration with the SPA's phrases; project branding and form changes use `project.update`. | Proposed | Adding enum values breaks the frontend typecheck until the phrases exist (Phase 3 precedent). |
| `outbound_email.idea_id` is set exactly for the two submitter types (`ck_outbound_email_idea_iff_submission_type`; `NewEmail.idea_id`); Phase 3's plumbing test now passes an idea. | Proposed | Erasure deletes submitter emails by idea and must not miss one. |
| Section text is the one request string that isn't whitespace-trimmed; a section save locks the idea `FOR SHARE`; 409 `proposal_conflict` carries the current section. | Proposed | Markdown indentation and autosave keep what was typed; saves to different sections don't block each other but can't race a status change; "Keep mine" can't race a refetch. |
| While an idea is held for moderation every permission flag but `can_delete` is false; `IdeaDetail.held_for` / `via_public_form` land at integration with the audit actions. | Proposed | The SPA shows a read-only page with Approve / Reject; no new required response fields before the SPA's mocks have them. |
| Declined from the contract review: idea numbers assigned on approval, the submitter's name for members only, a branding `updated_at` precondition, cutting the upload quota or the resend endpoint, bulk reject (later). | Proposed | Reasons in [contract-phase4 §7](api/contract-phase4.md#7-changes-after-the-contract). |

## 2026-10-02 · Phase 4 build and integration

Calls made while building and integrating proposals, public submission and branding.
Contract changes are listed in [contract-phase4.md §7](api/contract-phase4.md#7-changes-after-the-contract);
QA's known issues K4-1 to K4-5 and the PDF nits are fixed below.

### Proposals and export

| Decision | Status | Why |
|---|---|---|
| The editor is one auto-growing native textarea per section with Write / Preview, a four-button toolbar and an outline; no editor dependency. Each section autosaves 800 ms after typing stops, one request at a time; a conflict shows both versions with **Use theirs** / **Keep mine**. Written sections open in Preview on phones. The Proposal tab widens the idea page (`max-w-7xl`) and folds the sidebar into the Details sheet. | Decided | docs/research recommendation and wireframe 05; editing long text is not a phone task. |
| Margin comments reuse the Phase 3 composer without the mention picker, notify nobody and are not audited; exports are not audited. | Decided | Contract §3.1, §3.3, §3.14: no new `NotificationType` or `AuditAction` this phase. |
| PDFs render in a warm `spawn`ed child per API process (exits after 5 minutes idle), with its own temporary folder that the API deletes when the child goes. | Decided | First export 2.7 s, then 0.7 s; a killed render must not leave WeasyPrint's font folder in a pod's `/tmp` (platform's finding). |
| Fonts: `@fontsource` 5.3.0 `woff2`, latin and latin-ext as separate CSS families, plus 400 italics and IBM Plex Mono; URLs `soundings-font:<font>-<weight>[-italic][-ext]`. | Decided | One family per subset kept PDF text extraction intact; code and emphasis render in the bundled fonts too. |
| The PDF cover: a text-less band in the primary colour, the logo (or the app name), "Proposal", the title and the details table; tables print at the body size. | Decided | QA: the cover named the project three times and table cells were smaller than the text. |
| While a smooth scroll to a section runs (outline, `j`/`k`), the scroll spy waits for it to end (`scrollend`, or 1 s), so the current section stays the one asked for. | Decided | Integration: under load, `j` right after an outline jump stepped from a section scrolled past (a flaky page test). |
| The SPA loads the proposal editor with the tab (`React.lazy`) and React in a chunk of its own. | Decided | Phase 4 pushed the entry chunk from 499 kB to 575 kB (Vite's 500 kB warning); now 310 kB + 219 kB React, which stays cached across releases. |
| No proposal in the demo seed; the screenshot run and the smoke tests start one through the API. | Proposed | Seeding one would change Phase 1–3 expectations late in the phase; worth doing with the next seed change. |

### Public submission and moderation

| Decision | Status | Why |
|---|---|---|
| The SPA uses altcha@3's solver library and its PBKDF2 worker, bundled as a same-origin file, with its own accessible status line instead of `<altcha-widget>`. No WebAssembly, so the CSP is unchanged. | Decided | The widget's styles and strings don't fit the design system; verified under the production CSP and at 6× CPU throttling (0.15–0.65 s). |
| `viewable_ideas` now equals `listed_ideas` (no held idea in any list for anyone); single ideas go through the policy (c12). c19 also blocks watching. | Decided | Every caller of `viewable_ideas` was a list; an admin opens a held idea by link or from the queue. |
| Tracking and confirmation routes count their per-IP throttle before the token lookup. | Decided | Unknown tokens are rate-limited too. |
| Approve and Reject in the queue wait for their Undo toast; the board shows "N ideas waiting for review" per project; Watch is hidden on a held idea. | Decided | Reject deletes the idea; a misclick must be recoverable. |
| A public idea's first activity reads "A visitor sent it through the public form". | Decided | QA K4-5: "Someone submitted the idea" read like a deleted account. |
| The form's Send button is 44 px tall on phones, like its fields. | Decided | QA K4-4. |
| Demo seed: Customer Innovation has a branding override (SVG logo and favicon uploaded through the same checks), a moderated public form with an intro and three public ideas (CUST-21 approved, CUST-22/23 waiting); the global profile has an email footer. 48 ideas in all. | Decided | Screenshots, e2e and `make public-smoke` need a live form; existing demo keys stay the same. |

### Branding

| Decision | Status | Why |
|---|---|---|
| One resolver, `app.services.branding`, cached 5 s per process and engine, cleared on save and again at commit; public pages, `GET /branding`, emails and PDFs all use it. | Decided | Two resolvers had been built in parallel; other replicas follow a save within 5 s. |
| Emails carry no logo: the app name is the wordmark, with the primary colour, a contrast-checked text colour and the footer. | Decided | Contract §3.8 / §3.10: no remote resources or images in emails. |
| In dark mode the SPA shows uploaded logos on a light plate (`logo-plate`), and a public page's header shows the logo alone (the app name only for screen readers) when one is set. | Decided | QA K4-2: dark lettering vanished on dark backgrounds and logo plus "Soundings" read as two brands; emails and PDFs are always light, so logos are designed for light. |
| `<main>` is the positioning context of the app shell (`relative`). | Decided | QA K4-1 / K4-3: absolutely positioned `sr-only` text and hidden inputs inside the scroller made the whole document scroll, so moving around the proposal editor scrolled the shell off-screen. One fix for every page. |

### Platform and testing

| Decision | Status | Why |
|---|---|---|
| The image is built on `ubuntu:24.04` with Ubuntu's Python 3.12 (ADR 0011, now Accepted): 504 MB (+43 MB over the same dependencies on Debian). `RUNTIME_APT_PACKAGES` only adds packages; `UBUNTU_MIRROR` / `UBUNTU_IMAGE` replace the Debian arguments; the build fails if WeasyPrint can't render. | Decided | PDF export works in the shipped image; verified in a hardened container, `make demo` and k3s. |
| Chart: `features.publicSubmission` now reaches the app (`SOUNDINGS_PUBLIC_SUBMISSION_ENABLED`; it set an unused variable before); session durations given in seconds become `PT<n>S`; new `publicSubmission.*` and `branding.maxUploadBytes` values; optional `ingress.publicApi.annotations` for an edge rate limit on `/api/v1/public`. | Decided | Two pre-existing chart bugs; edge limits apply to anonymous traffic only. |
| `scripts/public-smoke.sh` (`make public-smoke`, also in `k3s-smoke`) runs the acceptance through HTTP; `make demo` containers run read-only with a `/tmp` tmpfs and no capabilities; k3s's kubelet evicts at 1 GiB free (`K3S_EVICTION_HARD`). | Decided | The demo behaves like a cluster pod; the percentage defaults evicted every pod on this machine. |
| e2e: specs that change the global branding run in a `serial` project; per-address throttle specs claim their own address with `X-Forwarded-For` (the stack trusts loopback), and skip against `E2E_BASE_URL` unless `E2E_TRUSTS_FORWARDED=1`; the stack allows 1,000 public submissions per address per hour (`E2E_PUBLIC_PER_IP`); PDFs are read with `pdfjs-dist` (no poppler). | Decided | Every spec submits from 127.0.0.1; global branding is shared state. |

## 2026-10-02 · Phase 4 review and final verification

What the security and UX reviews changed, and the lead's calls on the UX findings no
fixer owned. Details and tests: [phase-summaries/phase-4.md](phase-summaries/phase-4.md#review-findings-and-outcomes);
contract changes in [contract-phase4.md §7](api/contract-phase4.md#7-changes-after-the-contract).

### Security

| Decision | Status | Why |
|---|---|---|
| PDF layout is bounded before WeasyPrint starts: at most 5,000 layout boxes per document (a section over it is cut with a note pointing to the Markdown export), a zero-width break opportunity every 32 characters of an unbroken run, text over 1,000 characters printed in pieces. No PDF cache. | Decided | Review H1: ordinary-looking text took 9–25 s and up to 250 MB per section. A shared cache can't work: each PDF names its exporter and date. The 10-per-minute export limit stays. |
| The renderer limits its own memory to half the container's limit (at most 1 GiB), is replaced after growing past it, and starts with an allow-listed environment; the chart's API memory limit is 1Gi. | Decided | Review H1 / N4: a runaway render fails with a 500 instead of an OOM-killed pod; no secrets in the child. |
| The confirmation-email limit (3 per address per day) counts `confirmation_email_sends` by a keyed hash of the canonical address (case, `+tag`, Gmail dots, Yahoo keywords folded); nothing but the 24-hour cleanup deletes those rows. | Decided | Review M1 / L1: erasure and rejection deleted the outbox rows the limit counted. |
| The confirmation email carries no tracking link; the `/verify` page shows no submitted text (`EmailVerified.title` stays in the schema, unused). | Decided | Review L2: anyone can type anyone's address; the recipient must not land on our page reading a stranger's words. |
| Loading a form, its challenge and the submission share a per-address limit of 120 a minute, counted before the form is looked up. | Decided | Review L3: unknown slugs were free to enumerate. 120 (not 60) keeps the existing 30-a-minute challenge limit the tighter one for one address. |
| Setuid/setgid bits are stripped in the image; the ALTCHA check runs off the event loop; the SPA's Markdown keeps only http, https and mailto links, like the PDF. | Decided | Review N1, N2, N3. |

### UX: lead decisions (final verification)

| Decision | Status | Why |
|---|---|---|
| Confirmation links are `<base>/<slug>/verify#<token>`; `/verify#<token>` keeps working. | Decided | UX M1: the confirmation page now shows the project's branding before the click (the slug isn't secret). |
| One identity per audience: a project override with its own logo and no app name resolves its app name to the project's name (emails, PDF running header and creator, public pages' title and screen-reader name, the settings preview). | Decided | UX M3: the logo on the form and "Soundings" or the instance name in the inbox read as two senders. Done in the resolver, so every surface follows. |
| Proposal headings move one level down, never above h3 (`#`, `##` → h3, `###` → h4 …), in the PDF, the Markdown export and the editor preview alike; every PDF heading level is semibold with its own size; links print in the primary colour with their URL in brackets; a short proposal's contents go on the cover; empty sections are marked in the contents. | Decided | UX M4, m4, m5: `###` printed exactly like body text; a whole contents page fronted a two-page body; paper can't be clicked. |
| The confirmation email's text part has the Confirm link right after the first paragraph; status emails put "Stop these emails" in the footer. | Decided | UX p6. |
| `TrackedSubmission.reached_team_at` (additive; `public_submissions.reached_team_at`, migration 0009) dates the tracking page's "With the team" step. | Decided | UX m3. A stored time rather than one derived from the audit log: verification releases weren't recorded anywhere. |
| No proposal in the demo seed (UX p7). | Proposed | Still deferred: seeding one changes Phase 1–3 expectations; the screenshot run and the smokes start one through the API. |

### UX: fixed by the frontend

Focus follows every proposal and moderation action (M6); "Close evaluation" is no
longer a primary action while a proposal is written, and the phone's sticky bar hides
while typing (M7); "Review n" in the sidebar and "Waiting for review" in My work for
admins (M5); the branding email preview is the real layout (M2) and opens in a sheet on
phones (m1); an invalid colour says so (m2); the brand font is for titles, the wordmark
and public pages, while UI text stays Inter (m9); a softer dark logo plate (m8); plain
excerpts of resolved threads (m6); the send error sits by the button (m7); form copy,
receipt at 390 px with Share, conflict labels ("Use Carol's version" / "Keep your
version"), one Markdown hint, queue polish, a one-line verified ALTCHA status (p1–p5,
p8).

## 2026-10-02 · Phase 5 contract

Calls made while writing the API keys and MCP contract
([contract-phase5.md](api/contract-phase5.md), section 6 has the full list with reasons;
[ADR 0013](adr/0013-api-keys-and-mcp-server.md)). Status **Proposed** = the lead's
default; build it this way unless told otherwise. Revised the same day after the
contract review, before building ([contract-phase5 §9](api/contract-phase5.md#9-contract-review-2026-10-02-before-building)).

### API keys

| Decision | Status | Why |
|---|---|---|
| Keys are `sdg_<12-char lookup id>_<40-char secret>` (base62); only the lookup id and the SHA-256 of the whole key are stored; constant-time compare; shown once (201 with `Cache-Control: no-store`), then by prefix only. | Proposed | One indexed lookup; a database leak reveals no key; recognisable to scanners; rotating the secret key doesn't revoke keys. |
| A key has a name (unique per owner until revoked), 1–4 scopes (`write` and `evaluate` include `read`), an optional expiry (1 hour to 366 days) and an optional restriction to 1–50 projects (a `uuid[]`, null = all); none of it can change later; at most 25 keys per user that aren't revoked; no rename, no renewal. | Proposed | Simple lifecycle (create, revoke); bounded lists; a restriction can only shrink when projects disappear; write responses return readable data anyway. |
| A person's key pauses (401, state `dormant`) while its owner hasn't used the app for 30 days; signing in reactivates it; service accounts are exempt. A key works only while the sign-in method that created it is available (`created_auth_method`). | Proposed | IdP removals and group sync apply at sign-in only; keys must not outlive a departure (sessions end in 24 hours) or the dev-login switch. Preferred over capping people's keys at 90 days: tighter, and "never" stays usable. |
| Effective permission = the owner's live permission ∩ scopes ∩ projects; authentication re-reads the key every request (no cache); revocation, expiry and demotion apply to the next request; deactivating a user revokes their keys. | Proposed | SPEC: "never exceeds its owner's live permissions"; "revoking cuts access immediately". |
| Key management, admin pages, settings, the inbox, `idea.delete` and `idea.moderate` are session only; routes without a rule (me, My work, search) need `read`; a key plus a cookie is decided by the key; no CSRF with a key. | Proposed | A leaked key can't mint keys or change access, and nothing irreversible happens through a key; deny by default; browsers can't send `Authorization` cross-site. |
| The break-glass account can't create keys (new condition c20, 403 `break_glass_account`; not written in the matrix cells). | Proposed | A key would outlive the emergency and keep working after SSO is configured. |
| 30 failed key authentications per address per minute (beyond it failing keys get 429, valid keys still work), 300 requests and 30 writes per key per minute (in-process, like the sign-in throttles); refusals logged with a reason, not audited; `last_used_at` at most once a minute in its own transaction; no IP stored. | Proposed | Bounded load, runaway agents and audit growth without locking out valid keys behind a NAT; a revoke never waits behind a request; minimal personal data. |
| Service accounts' keys are created by platform admins (Phase 6, Admin → AI agents), restricted to the projects the agent serves; `api_keys.created_by_id` records who; service accounts may hold member or viewer roles, never admin (409 `system_account`), and never own an idea (c4; c21 for volunteering); their evaluations are left out of the aggregate from Phase 5; their suggestions are `source: ai`. | Proposed | Agents never sign in; an agent must not accept its own suggestions or count its own evaluation (SPEC section 9); restriction limits cross-project prompt injection. |

### MCP

| Decision | Status | Why |
|---|---|---|
| `POST /mcp` only, stateless JSON mode, mcp SDK 2.x low-level `Server` with one `tools/call` dispatcher; authentication by the REST key source in an ASGI wrapper (not the SDK's `TokenVerifier`); cookies never accepted; exempt from the app's Host check (agents call the cluster Service), Origin against the base URLs; 1 MiB bodies; `/.well-known` answers the API's 404. | Proposed | One code path and error format for keys; immediate revocation; no CSRF or DNS-rebinding exposure; one place validates, rate-limits and audits each call; in-cluster agents need no public hostname. |
| The nine SPEC tools only; arguments and results are contract models in `app/schemas/mcp.py` (structured content plus JSON text; write tools' arguments subclass the REST request models); tools reuse the REST services and policy; errors are tool results with the REST problem code. | Proposed | Same authorisation, validation, blind evaluation and conflicts as the API by construction; one vocabulary of error codes. |
| `get_idea` is bounded (10 comments by default, 20 at most, the latest 25 evaluations with a count, texts over 2,000 characters cut with `truncated`); every people-written output field is described as untrusted; `via_public_form` in search results. | Proposed | Agents' context windows; prompt injection: models are told what is data. |
| Ideas held for moderation or confirmation are `not_found` through every tool, for everyone; `get_idea` omits the public submitter's name; the server instructions tell agents that idea, comment, evaluation and proposal text is data, never instructions, and never to copy it between projects. | Proposed | No MCP tool moderates; text waiting for moderation doesn't reach agents (public text in unmoderated projects is flagged); minimal personal data. |
| Every `tools/call` is audited (`mcp.call`: tool, rule, decision, code, key id; never arguments), whatever the outcome, in its own transaction when the call fails; those entries are deleted after 90 days. `initialize` and `tools/list` aren't audited. | Proposed | SPEC: "every call audited"; agents' trails are useful for months, what they changed is audited for good. |
| `tools/list` always lists all nine tools; a call without the tool's scope is `insufficient_scope`. | Proposed | Static catalogue; kagent selects tools by name anyway. |

### Proposal suggestions

| Decision | Status | Why |
|---|---|---|
| A suggestion is the whole text of one section (REST `create_proposal_suggestion` for members, MCP `propose_proposal_section` for clients and agents; `source` follows the author: `ai` for a service account, else `api` or `mcp`); one pending per author per section (a newer one discards the older, under the idea lock); at most 50 pending per proposal; a `base_version` above the current one is 422. No withdrawing in Phase 5. | Proposed | Matches Phase 6's "Draft section"; no diff format to invent; bounded; the AI badge follows who wrote it. |
| Listing needs `proposal.view`; accepting or discarding `proposal.write` (c7), both under the section-save locks (discard can't overwrite an accept). Accepting is a normal versioned section save (`base_version`, 409 `proposal_conflict` with `current`). No notifications or activity in Phase 5. | Proposed | Same concurrency as Phase 4; no new `NotificationType` (it breaks the SPA's exhaustive maps). |

### Contract mechanics

| Decision | Status | Why |
|---|---|---|
| New `AuditAction` values `api_key.create`, `api_key.revoke`, `mcp.call` are agreed but land at integration with the SPA's phrases (target type `user` for key events: no new target type). | Proposed | Adding enum values breaks the frontend typecheck until the phrases exist (Phases 3 and 4 precedent). |
| No new settings: every limit and the `mcp.call` retention are constants. | Proposed | Simple beats configurable. |
| The contract commit adds the new operations to the meta-test tables owned by identity and backend (`test_route_rules.py`, the guard tests' exclusions, `DOMAIN_TABLES`), as the Phase 4 contract did. | Proposed | Otherwise `make check-backend` fails on routes and tables that exist only as stubs. |

## 2026-10-06 · Phase 5 build and integration

Calls made while building and integrating API keys, the MCP server and proposal
suggestions. Contract changes are listed in
[contract-phase5.md §8](api/contract-phase5.md#8-changes-after-the-contract); QA's six
defects ([test-plans/phase-5.md](test-plans/phase-5.md#defects-found-by-these-tests)) are
fixed below and their expected-failure marks removed.

### API keys

| Decision | Status | Why |
|---|---|---|
| Every operation is classified for keys (`app.authz.keys.ROUTE_KEY_ACCESS`: `policy`, `read`, `session`, `public`; unclassified is refused), and `get_current_user` refuses a key on a session route, or a read route without `read`, with 403 `insufficient_scope` before the route's own 404 or 422. | Decided | Deny by default for every new route; the answer doesn't depend on the resource, so nothing leaks (contract §8). |
| `require_view` (loading an idea or project to read it) needs `read` with a key; the moderation queue, `get_idea_submission` and the public-form and branding settings are session only too. | Decided | An `mcp`-only key read ideas over REST before (found by `test_key_routes.py`); moderation and settings aren't integration surfaces. |
| Deactivating a user revokes every key in the same transaction (`revoke_all_for_user`, each audited `reason: deactivated`), after the `users` update is flushed. | Decided | Integration fix (QA AC5-API-3, AAK-04): a reactivated account got its old keys back. The flush orders it after a racing create's lock. |
| `get_principal` returns whatever principal was stored, even when the route's user object is another instance. | Decided | Contract §3.2: a key's narrowed principal must never become a session one. |
| The audit filter takes up to 64 actions. | Decided | 42 actions now; a filter on all of them was 422. |

### MCP

| Decision | Status | Why |
|---|---|---|
| One guard in front of the SDK (`app/mcp/guard.py`: method, Origin, key, c15 with one audit entry, the key's rate, Content-Type), on identity's `key_auth`; 415 comes from the guard as problem+json. | Decided | One code path for keys; the SDK answers a wrong Content-Type with a plain-text 400. |
| The SDK's session manager runs its task group in a task of its own; its loggers are held at WARNING. | Decided | pytest-asyncio enters and leaves the lifespan in different tasks; it logs every request at INFO and may log raw messages at DEBUG (tool arguments must never reach logs). |
| `get_idea`'s `evaluation_count` and `evaluations` are other people's; yours is `my_evaluation`. Tool error messages name the failing fields, never their values. | Decided | The schema's wording; arguments may hold personal data. |
| `mcp.call` `decision`: refusals before or by authorisation (401/403/404/429, bad arguments, unknown tool, the write cap) are `deny`; business 409/422s and crashes are `allow`. | Decided | "Was the caller allowed to try" is what an auditor asks; the code says what happened. |
| The hourly schedule (`run_schedule`) deletes `mcp.call` entries older than 90 days. | Decided | Integration fix: `delete_expired_calls` existed but nothing called it. |
| `/.well-known/*` is a backend path: the SPA never answers it. | Decided | Integration fix (QA AK-04): it returned `index.html` 200 on a stack with the SPA, which broke `mcp-smoke`. |

### Service accounts and suggestions

| Decision | Status | Why |
|---|---|---|
| A service account's **first** submission sets `include_in_aggregate = false`; later edits keep whatever it is (Phase 6's `evaluation.include_ai` changes it). A person's evaluation through a key stays included. | Decided | Integration fix (QA AC5-API-4): an agent's evaluation counted in the aggregate. |
| `set_idea_owner` passes `assignee_service_account` to the policy (c4, 422 `assignee_not_eligible`); `add_project_member` and `update_project_member` refuse `role: admin` for a service account (409 `system_account`, "AI agents can be members or viewers, not admins"). The SPA shows the server's detail for `system_account`. | Decided | Integration fix (QA AC5-API-4); one code, two contexts, so the detail says which. |
| No notification for a new suggestion in Phase 5. | Decided | Contract §3.4 and §7: a new `NotificationType` needs the SPA's maps (Phase 6). |
| Discarding waits for its Undo toast (about 6 s) before the request, like comment delete; Undo after Accept saves the previous text again as a new version (the suggestion stays accepted). | Decided | A misclick is recoverable; an MCP client may see the suggestion pending for those seconds. |
| No in-app "Suggest" button; `can_suggest` is unused by the SPA. | Proposed | Suggestions come from the API, MCP clients and (Phase 6) agents; people edit sections directly. |

### Screens

| Decision | Status | Why |
|---|---|---|
| A key with all four scopes shows one "Full access" chip (the preset's name; the scopes in screen-reader text); admin columns widened so three chips and two project names fit; the owner's name truncates before the key's prefix. | Decided | QA: four chips wrapped to two lines, and "Customer Innovation, Internal Tools" took three; the prefix finds a leaked key. |
| Code blocks (the MCP config, commands) wrap long lines softly instead of scrolling sideways; copying still gets the text as written. | Decided | QA: `"Authorization": "Bearer sdg_…"` ran out of the dialog with no sign it scrolled. |
| Rows that scroll sideways (tabs, the settings row) fade the edge they can still scroll towards; on phones the settings row runs to the screen's edges. | Decided | QA: at 390 px the admin's settings row was cut at both edges with no hint. |
| A blank line in a suggestion's diff is a short gap in its band's colour, with no "+" or "−". | Decided | QA: an empty "+" row read like a missing line. |
| "Connect an MCP client" and the secret dialog add a **Claude Desktop** example through `mcp-remote@0.14.3` with `--header-file`; the `mcpServers` example is described for `.mcp.json` and editor assistants. | Decided | Claude Desktop's custom connectors only sign in with OAuth (platform verified `mcp-remote`); the old text promised Claude Desktop would take the HTTP config. |

### Platform and testing

| Decision | Status | Why |
|---|---|---|
| `kagent.enabled` adds kagent's namespace to the API's NetworkPolicy (when `networkPolicy.ingressFrom` is set); `ingress.mcp.annotations` adds an Ingress for `/mcp` only, with a Prefix path. | Decided | The contract had the operator add the namespace by hand; on Traefik 2.11 an Exact `/mcp` path lost to `/`. |
| The kagent example renders only a `RemoteMCPServer` (kagent 0.10, `v1alpha2`), reading the whole `Bearer sdg_…` header from an existing Secret; Agents come in Phase 6. | Decided | Checked against kagent 0.10.2's CRD; a live kagent install isn't verified yet. |
| `make mcp-smoke` and `k3s-smoke MCP=1` (an SDK client in another namespace with a Secret-held key) run the acceptance; CI's k3s job runs `SSO=1 SMTP=1 MCP=1`. | Decided | The acceptance through the ingress and the Service, as kagent will call it. |
| Tests for contract rules that aren't built yet are expected failures (`test.fail(true, …)`, strict `xfail`) that fail once fixed. | Decided | QA's convention: the suites stay green while a defect is open, and the fix can't go unnoticed. |

## 2026-10-06 · Phase 5 review and final verification

What the security and UX reviews changed, and the lead's calls on the findings the fixers
left open. Details and tests:
[phase-summaries/phase-5.md](phase-summaries/phase-5.md#review-findings-and-outcomes);
contract changes in [contract-phase5.md §8](api/contract-phase5.md#8-changes-after-the-contract).

### Security

| Decision | Status | Why |
|---|---|---|
| The key check and the `last_used_at` update run in one short transaction that closes before the request's own session opens; `/mcp` holds no session at the door. | Decided | Review H1: parallel requests with fresh keys held two pool connections each and stalled the pool (15 s, then 500). |
| Each MCP tool call reads the key and its owner again inside its own transaction; a key revoked or expired, or an owner deactivated, dormant or demoted meanwhile, is the tool error `unauthorized` (audited as a denial). | Decided | Review M1: a request let in before a revoke still created an idea. |
| At `/mcp` the key's request budget comes before the `mcp`-scope check, so refusals count; a scope refusal and a budget refusal are audited at most once per key per minute; cancelled calls (`cancelled`) and crashing validators (`internal_error`) are audited; the SDK's 415/406/400 aren't (no tool call). | Decided | Review M2, L1: a key without `mcp` could hammer `/mcp` and fill the audit log for free. |
| A service account with no role in a project is a private non-member there (404), internal projects included; lists leave those projects out; a key can't be restricted to them. | Decided | Review M3: an agent added to one project could read every internal one. |
| MCP results lose every invisible character (Unicode tag characters, variation selectors beyond VS15/VS16, zero-width, other format, bidi and control characters; ZWJ, ZWNJ and line breaks stay), and error messages cut field names to 40 characters. | Decided | Review M4, output side: tag characters spell instructions a model reads and a person never sees ("ASCII smuggling"). |
| Request bodies (every `RequestModel` string, `SingleLine` included) and MCP arguments refuse Unicode tag characters (U+E0000–U+E007F, 422 / `validation_error`); sign-in strips them from IdP display names. Subdivision flag emoji (England, Scotland, Wales) are refused with them. | Decided (lead) | Review M4, input side: stop hidden text at the door, so stored text is clean for agents, exports and emails alike; the flags are the only legitimate use and not worth a special case. |
| The four MCP write tools refuse unknown arguments (`extra="forbid"`, `validation_error`); the read tools keep ignoring them. | Decided (lead) | Review L2: `sumbit: false` was ignored and the evaluation submitted (the default). Reads can't do harm by ignoring an extra. |
| `display_name`, `status_label`, rubric criteria's name, description and guidance, and a suggestion's `body_md` say `UNTRUSTED` in the MCP output schemas (`McpRubricCriterion`, `McpProposalSuggestion`). | Decided (lead) | Review nit 2: people write those too. |
| A service account's people search (`GET /users`) finds only people with a role in a project where it has one, inside its key's projects; people's keys and sessions still search the directory. | Decided (lead) | Review L4: an agent needs its projects' people for @mentions, not the whole directory. |
| Bound SQL parameters never appear in database errors (`hide_parameters=True`); a suggestion's checks run 404 → 403 → 422 → 409. | Decided | Review nits. |
| A proxy that adds its own `Authorization: Bearer` header breaks sign-in (every bearer is read as a key): documented in the Helm README and the operator guide, not worked around. | Decided | Review L3: a fall-through to the cookie would make a bad key silently act as the browser's user. |

### UX: lead decisions (final verification)

| Decision | Status | Why |
|---|---|---|
| Presets "Read with an assistant" (`read`, `mcp`) and "Evaluate with an assistant" (`read`, `evaluate`, `mcp`: "…they count as yours"); the `mcp` scope is labelled "AI assistants (MCP)". | Decided | UX M4: "AI evaluator" read as SPEC §9's agent, whose evaluations are left out of the aggregate; a person's assistant submits as them. |
| The idea's Proposal tab shows the number of pending suggestions to people who may decide (owner, project admins, while c7 holds); no notification in Phase 5. | Decided | UX M5: an assistant's suggestion sat unseen unless someone opened the tab; a notification needs a new `NotificationType` and the SPA's maps (Phase 6). |
| `ApiKey.unavailable_project_count` and `AdminApiKey.projects[].owner_can_view` (additive): the owner sees "+N project(s) you can no longer open", the admin view strikes those projects through. | Decided | UX m1: the owner's list dropped a project the owner had lost while the admin list still named it, with nothing saying why. |

### UX: fixed by the frontend

A plain-words "Can" column in Settings → API keys and a live "This key can …" line in
the create dialog (M3); "Treat it like a password" and "I've copied it", with one
reminder if nothing containing the key was copied (m3); expiry within a week in a
warning tone, expired keys last with Remove (m2); a single break-glass empty state (m9);
State-menu rows that wrap with descriptions (M1) and owner names that no longer
collapse in the admin table (M2); word-level highlights in suggestion diffs (m5), who
decides on each card (m6), focus to the next pending suggestion after a decision (m7),
pending autosaves sent before Accept (m8), distinct names per card (m4); the developer
section folded behind "For developers and AI assistants", "via assistant", "check the
facts" on AI cards, monospace prefixes and tool names in the audit log, a nudge towards
"Only these projects" when assistants may use every project (p1–p9). A partly typed key
in the admin search is cut to its prefix before it reaches the URL (code-review nit).

## 2026-10-06 · Phase 6 contract

Calls made while writing the kagent contract
([contract-phase6.md](api/contract-phase6.md), section 7 has the full list with reasons;
[ADR 0014](adr/0014-kagent-a2a-integration.md)). Status **Proposed** = the lead's
default; build it this way unless told otherwise. No kagent installation or LLM exists
here: builders use a deterministic fake A2A agent (contract-phase6 §3.12), and §8 there
says what is verified against real kagent and what is assumed. Revised the same day after
the adversarial contract review (contract-phase6 §10 lists every finding and what was
done; italic notes below say what changed).

### Agents and keys

| Decision | Status | Why |
|---|---|---|
| A platform admin registers an agent by kagent namespace and name (DNS labels), protocol (`kagent_v0_10` or `kagent_v1_0`, default from settings), purposes (evaluate, research, draft_section) and 1–50 projects; registering creates its service account (`agent-<id>@soundings.invalid`), a direct member role in each project and one key (scopes from purposes, restricted to the projects, no expiry), shown once with a Kubernetes Secret manifest. | Proposed | One form does everything an operator needs; least privilege per purpose; the platform admin decides an agent's reach (prompt-injection blast radius). |
| The server keeps an agent key's scopes and restriction in step with the agent's purposes and projects (an exception to Phase 5's immutable keys, for agents only; narrowing cancels the runs it no longer covers); rotation replaces the key (no overlap); disabling **revokes** the key and cancels its runs (enabling again needs a rotation); agents are never deleted. *Contract review S6, S7: disabling first only refused the key (401); C3 (scopes worked out at use time) declined: c22 confines agents, the key's own scopes stay a second fence.* | Proposed | Adding a project never requires re-deploying a Secret; one switch stops an agent and a downgrade can't revive its key; history keeps its author. |
| **c22, run scope:** an agent's key works on `/mcp` only (REST 403 `insufficient_scope`), on the idea of one of its `running` runs nobody asked to cancel, writing only through the run kind's tool (`create_idea`, `add_comment` never). *Contract review M1; replaces the "one agent per project" advice.* | Proposed | Otherwise the key is a full project member outside runs: anyone who can message the agent in kagent (unauthenticated by default) or text planted in any idea could drive it, and cancel or timeout wouldn't stop late writes. Per-run keys are impossible (Soundings has no Kubernetes API access) and unnecessary once the key is inert outside runs. |
| **Agents never see others' score data**, before or after submitting (role matrix §3 rule 9). *Contract review M2: first only "blind until it submits".* | Proposed | Agent-written notes and suggestions are read by pending evaluators; people's evaluation comments shouldn't reach an LLM provider. |
| Project admins may remove an agent from their project (c10 then fails there) and add it back; people pickers never list agents. | Proposed | A project keeps a veto without a second way to grant agents access. |

### Runs and A2A

| Decision | Status | Why |
|---|---|---|
| The A2A URL is built from `SOUNDINGS_KAGENT_URL` (an origin, validated at start-up) + the protocol's fixed path + namespace and name; no URL field anywhere; card URLs ignored; redirects never followed; an optional namespace allow-list. | Proposed | SSRF can't be configured in through the UI, the API or a malicious card. |
| One A2A message per run with references and instructions only (`run_message`; idea text is read by the agent through MCP, labelled untrusted; **no URL**: agents use the MCP server their operator configured); always `message/stream` (no card fetch per run), polling `tasks/get` with `historyLength: 1` when the stream drops; `X-User-Id: soundings`; an optional controller token; the HTTP client ignores proxy settings (`trust_env=False`). *Contract review S3, S10, S12, C2.* | Proposed | No secrets, URLs or people's text in prompts; works with kagent 0.10's Go and Python runtimes (kagent-adk 0.10.2 speaks A2A 0.3 only); a polled kagent task stays small. |
| Results come back through MCP as the agent's service account (`submit_evaluation`, the new `add_research_note`, `propose_proposal_section`) and the server attaches them to the run; A2A text and artifacts are ignored. | Proposed | kagent 0.10 has no output schema; the same rules, blind evaluation, limits and audit as for people; no parsing of model output. |
| Runs are rows (`ai_runs`, `ai_run_events`) executed by a procrastinate job on its own `ai` queue with a pool of `AI_MAX_CONCURRENT_RUNS` (4) per worker process, compare-and-set transitions (lock order project → idea → run), a per-run deadline (5 minutes from start), a 15-second heartbeat, a minute sweep (`worker_lost`, 30-minute queue limit, also enforced on the next request), cooperative cancel (`tasks/cancel`, any answer accepted) and `worker_lost` at shutdown; no job retries or resuming; connection retries only before a task exists. *Contract review M3, S1, S2, C8: first a database-counted limit in the shared pool.* | Proposed | Durable and restart-safe; AI runs never hold up email or the schedules; nothing is sent twice; timeouts and cancels end cleanly even when kagent's Python runtime can't cancel. |
| One active run per idea + agent + kind (+ section) by a partial unique index; a repeated request returns it (200); 20 requests per person per hour. | Proposed | Double clicks and races are harmless; bounded cost. |

### Evaluations, notes, progress

| Decision | Status | Why |
|---|---|---|
| An AI evaluator's rationale is its per-criterion comment (required); its sources are a JSONB column on `evaluation_scores` (≤ 5 per criterion, `{title, url}`, http(s) without credentials); people never cite. | Proposed | One evaluation shape; no sibling table; the evaluate UI already shows comments. |
| AI evaluations stay out of the aggregate until the owner or an admin includes each one (`set_evaluation_inclusion`); a re-submission with a changed score or recommendation is left out again; the toggle is 404 for a pending evaluator (the response has scores) and 409 on a person's evaluation. An evaluate run that assigned the agent and ends without its evaluation removes the assignment. *Contract review S5, S6.* | Proposed | SPEC section 9; an included score never changes unseen; "all evaluations are in" never waits for an agent that won't submit. |
| Cited sources are stored as plain ASCII (punycode host, %-encoded rest; invisible characters refused), shown with their host under "Cited by AI, not checked"; agent Markdown links are http/https only. *Contract review S9, C5.* | Proposed | No look-alike hosts or hidden text in links; agents without a web tool may invent sources. |
| Research notes are `ai_research_note` activity events (body + sources in the payload), one per run, readable alone and deletable by admins (`comment.delete_any`); a new MCP tool that requires a running research run (c22). *Contract review C4 (let the owner delete too) left to the lead: it needs a new policy rule.* | Proposed | No new table; a note can't be planted outside a requested run; harmful output can be removed. |
| Live progress is SSE from the API (one stream per run, `Last-Event-ID` replay, keep-alives, re-checks every 30 s, 204 when over; one poller per run per process) with `get_ai_run` polling as fallback; events are Soundings' fixed sentences for known MCP tools only, and error messages add at most an HTTP status or a known A2A state name. The idea page's AI actions say why they are unavailable (`AiBlockedReason`). *Contract review S4, S14, C2.* | Proposed | Works across replicas and through the ingress; blind-safe by construction (a test walks every run model for score-like fields); no agent words reach pending evaluators. |
| No new notification types; no run retention job in Phase 6. | Proposed | The requester watches; results appear where people look; simple. |

### Contract mechanics

| Decision | Status | Why |
|---|---|---|
| The `ai_research_note` activity item, `EvaluationScore.sources`, five `AuditAction` values and the tenth MCP tool are agreed and modelled now but land in one integration step with the SPA (contract-phase6 §5). | Proposed | They break the SPA's exhaustive maps and mocks, or need their handler (Phases 3–5 precedent). |
| The contract adds the new operations to identity's and backend's meta-test tables (`ROUTE_KEY_ACCESS`, `test_route_rules.py`, the guard tests' exclusions, `DOMAIN_TABLES`). | Proposed | Otherwise `make check-backend` fails on stub routes and new tables (Phase 5 precedent). |

## 2026-10-06 · Phase 6 build and integration

Calls made while building and integrating AI assistance. Contract changes are listed in
[contract-phase6.md §10](api/contract-phase6.md#10-changes-after-the-contract) ("Builders'
changes"); what is verified against kagent and what only against the fake agent is in
[contract-phase6.md §8](api/contract-phase6.md#8-verified-vs-assumed-kagent) and
[`deploy/kagent/README.md`](../deploy/kagent/README.md#what-is-verified-2026-10-06). The
test plan, with every case ID: [test-plans/phase-6.md](test-plans/phase-6.md).

### Runs, A2A and the worker

| Decision | Status | Why |
|---|---|---|
| The A2A client is hand-written on httpx (0.3 `message/stream`, `tasks/get`, `tasks/cancel`; 1.0 `SendStreamingMessage`, `GetTask`, `CancelTask` with `A2A-Version: 1.0`): SSE parsing capped at 1 MiB per event, cards at 64 KiB, no redirects, no cookies, `trust_env=False`, an explicit SSL context; card URLs are never followed. | Decided | No new backend dependency (a2a-sdk would bring its own HTTP stack and server pieces for four calls); every limit is ours. |
| The worker runs two procrastinate pools in one process: `email` + `notifications` (`worker_concurrency`) and `ai` (`SOUNDINGS_AI_MAX_CONCURRENT_RUNS`); one signal handler stops both; the database pool is concurrency + AI runs + 4. `sweep_ai_runs` is a periodic job on `notifications`. | Decided | Contract review M3: email and the schedules never wait behind a five-minute AI run. |
| State changes are compare-and-set with an event log of at most 200 events per run, the final one included; nothing but the final event once a run has ended. A `tool_called` event of a write tool goes to the open run of that tool's kind on the idea; `result_recorded` is written after the tool's transaction. | Decided | Races between the worker, cancel, the sweep and the agent's own calls resolve to one outcome; the stream reads "Saved its evaluation" then "Evaluation submitted". |
| A worker that receives SIGTERM ends its runs `worker_lost` at once and sends `tasks/cancel` (verified: 0.15 s, one cancel at the fake). | Decided | Contract review S2: no resuming, nothing sent twice. |
| `AiRun.cancel_requested` is true only while the run is active. | Decided (integration) | QA nit: a queued run cancelled at once answered "Cancelling" on a cancelled run. |

### Agents, keys and rules

| Decision | Status | Why |
|---|---|---|
| New rule `ai.delete_note` (the idea's owner, project admins, platform admins) for research notes, instead of `comment.delete_any`. | Decided (lead) | Contract review C4: the owner who asked for a note should be able to remove a harmful one. |
| On REST an agent's key gets 403 `insufficient_scope` (c22) before Phase 5's c21 answers; on MCP every tool checks c22 and writes go only through the run kind's tool. Service accounts are blind everywhere (rule 9, in the policy and `queries.score_visible`). | Decided | One refusal for every REST route; agents never carry scores to pending evaluators. |
| Sources are accepted only from AI evaluators; an agent's submission needs a rationale (comment) for every scored criterion; a re-submission that changes a score or the recommendation resets "include in score". | Decided | Contract §3.7. |
| `rotate_ai_agent_key` answers 409 `ai_unavailable` while the agent's service account is deactivated; an agent key's project restriction skips the "owner can view" check (c10 decides per project). | Decided | A key can't be issued to an inactive owner; an agent may be a viewer in a project for a while. |
| Helm: the switch is `SOUNDINGS_AI_ENABLED` (the chart had `SOUNDINGS_FEATURE_AI`, which the app never read); `kagent.mcp.keySecret` is optional because each example agent has its own `RemoteMCPServer` reading the Secret registration shows; the worker's egress gets kagent's controller port. | Decided | One key per agent; the shared Phase 5 `RemoteMCPServer` is for a person's key. |

### Screens

| Decision | Status | Why |
|---|---|---|
| The AI menu is hidden, not disabled, when AI is off or the person may not ask; an action that can't be done now is disabled with its reason in plain words. | Decided | Members and viewers have nothing to ask; the owner learns why. |
| One label for the evaluate action everywhere (menu, evaluators list, ⌘K): "Ask AI to evaluate again" once every agent offered has submitted. | Decided (integration) | QA: the menu and the list said different things for the same agent. |
| The AI badge is on every activity line by or about an agent ("Idea evaluator [AI] submitted an evaluation", "Alice invited Idea evaluator [AI] to evaluate"), from data the page has (the idea's AI evaluators, the runs' agents): no `is_ai` on `UserRef`. The comparison table heads an agent's column with its full name. | Decided (integration) | Contract §1: AI work labelled wherever it appears; "Idea" (the first word) read as a person. |
| The register sheet's URL preview shows `{namespace}` / `{name}` for anything the API would refuse; the key dialog opens focused on itself (Radix focused the copy icon, whose tooltip covered the header); "Draft with AI" reads "Draft" on phones; the admin list refetches on every visit, after a run is asked for or ends, and every 30 s while an agent has runs in progress. | Decided (integration) | QA's visual list. |
| A deleted research note reads "wrote a research note, since deleted"; the admin page has no per-agent run history (no endpoint): it shows active runs and links to the audit log filtered to AI. | Decided | Simple; the audit log already has every run request and cancel. |

### Platform and testing

| Decision | Status | Why |
|---|---|---|
| Soundings' fake agent (`dev/fake-agent`, a2a-sdk 1.2.1's server) stands in for kagent's controller in dev, e2e, CI and k3s: kagent v0.10.2's paths (and 1.0's), a card, streaming, `tasks/get`, `tasks/cancel`, a real MCP session with the agent's own key, behaviours by name suffix, observations without keys or text. | Decided | No kagent or LLM here; everything but the model and kagent's proxy is exercised for real. |
| kagent's CRDs come from its v0.10.2 git tag (`make k3s-kagent-crds`), not its chart. | Decided | ghcr's blob host is refused on this network; the CRDs are the files the kagent-crds chart packages. |
| The e2e stack (`E2E_AI=1`) registers "Idea evaluator" after every seed; AI specs are `@ai`, each with its own project, idea owner and agents. | Decided | 20 run requests per person an hour: one shared owner hit the limit in the first full run. |
| The backend acceptance runs the real fake agent as a subprocess (`uv`); `SOUNDINGS_TEST_FAKE_AGENT=0` skips it. CI's backend job has uv, so it runs there. | Decided | The whole loop over TCP in `make check-backend`. |
| AAK-03 waits for "Sign out everywhere"'s confirmation to close before asserting the sheet's button is gone. | Decided (integration) | While the confirmation is open the sheet is outside the accessibility tree, so the check passed before the sessions ended and `/auth/me` still answered 200 under load. |

## 2026-10-06 · Phase 6 review and final verification

What the security and UX reviews changed, and the lead's calls on what the fixers left
open. Details and tests:
[phase-summaries/phase-6.md](phase-summaries/phase-6.md#review-findings-and-outcomes);
contract changes in [contract-phase6.md §10](api/contract-phase6.md#10-changes-after-the-contract).

### Security

| Decision | Status | Why |
|---|---|---|
| Every MCP tool takes an optional `run_id`; for an agent it is required and binds the call to that open run's idea, checked before any idea is looked up (another idea, existing or not, is `ai_run_not_active`; `create_idea` / `add_comment` are `forbidden` before any lookup). People's calls ignore it. | Decided (lead accepted, H1 option 2) | Review H1: two runs of one agent open at once could reach each other's ideas (a private project's included). "One run per agent at a time" was rejected: kagent-adk 0.10.2 can't cancel, so a task outliving its run would act through the next one, and a killed worker's job would hold the agent's lock. Also fixes N1 (an agent could tell which ideas exist). |
| An agent sees its own evaluation (`my_evaluation`) only in its evaluate run. | Decided | Review M1: a research note or draft could carry the agent's scores to a pending evaluator. |
| An agent's note, comment and rationales lose bidi controls and zero-width characters before they are validated and stored; the SPA isolates agent hosts and link text (`<bdi dir="ltr">`) and strips the same characters on display. | Decided | Review M2: hidden text in model output could reorder what people read. |
| `ai_agent.update` records the new purposes, projects and key scopes; deleting a research note is audited as `ai_note.delete` (ids only). | Decided (lead: the new action) | Review L4. |
| The break-glass account can't widen an agent (add a purpose or project): 403 `break_glass_account`; narrowing, renaming and disabling still work. | Decided | Review L5, c20: widening changes what a key can do. |
| At most 100 open SSE streams per API process (then 429 and the SPA polls); `tasks/cancel` and the card fetch are bounded as a whole at 5 s; the sweep ends lost runs first, then cancels them side by side. | Decided | Review L6, L7. |
| `SOUNDINGS_AI_AGENT_NAMESPACES` defaults to `soundings` and must list at least one namespace. | Decided | Review L8: "any" let an admin register kagent's built-in agents. |
| kagent's session store keeps what agents read, outside Soundings' deletion, erasure and retention: documented in the operator guide and `deploy/kagent/README.md`, not worked around. | Decided | Review N2: it is kagent's database. |

### UX

| Decision | Status | Why |
|---|---|---|
| The SPA words a run's error by `error.code` in plain words with a next step ("The agent didn't finish within 1 minute. Try again: it may have been busy."); the server's fixed sentence appears only under **Steps**. The server keeps its "(state X)" suffix, which appears only there. | Decided (lead) | UX M4: errors read like protocol output; the server sentence stays useful for operators. |
| One row per agent and kind with its latest run; who asked and every step behind "Steps"; older runs under "History (N)"; only the latest row offers "Try again"; draft runs stay in the proposal editor. | Decided | UX M3: the cards were noisy and piled up. |
| "1 AI evaluation not counted · Review" under the score; the comparison table mutes the AI column and labels Mean "counted". | Decided | UX M2: an excluded AI evaluation wasn't visibly left out. |
| **Declined:** a "would be 3.6 with AI" preview of the aggregate including AI evaluations. | Declined (lead) | Simple beats configurable: it would copy the weighted-aggregate maths into the SPA or add another server field; including the evaluation (with Undo) shows the real number. |
| Focus stays where the person put it when a run ends (only a lost focus moves to the row); busy buttons are `aria-disabled` + `aria-busy` instead of `disabled`, so they keep focus; a dialog opened while a menu closes returns focus to the menu's button. | Decided | UX B1, M1. |
| The admin page's "Namespaces" shows the list in effect (never "Any"). | Decided (lead) | It can no longer be empty. |
| `focusWhenRendered` keeps trying while focus is held by a closing dialog or sheet that doesn't contain its target. | Decided (final verification) | Since busy buttons stay focusable, a closing confirm's focus trap pulled focus back to its button, so focus after a revoke flaked in `admin-api-keys.spec.ts`. |

## 2026-10-06 · Phase 7 fixes: backend and platform

What the Phase 7 security, accessibility and performance reviews changed on the server,
in the image and the chart, and the lead's calls. Contract changes:
[contract-phase7.md](api/contract-phase7.md); measurements:
[test-plans/performance.md](test-plans/performance.md).

### Contract

| Decision | Status | Why |
|---|---|---|
| `GET /me/work/counts` (the sidebar's badges, two aggregate queries); `GET /me/work` lists the first 50 evaluations due with `evaluations_due_next_cursor`; `GET /me/evaluations-due` pages through the rest (C1). | Decided (lead) | Perf B1: the sidebar fetched all of My work on every page load. Supersedes F9. MCP results are unchanged. |
| `ProjectSummary.pending_moderation_count` (null unless you may moderate) (C2). | Decided (lead) | Perf B7: one moderation request per project on every load. |
| `total` stays on every list page. | Kept | It is a required `int` in the contract; making it nullable isn't additive (lead: only if the schema allowed null). |

### Security

| Decision | Status | Why |
|---|---|---|
| The image sets `SOUNDINGS_ENVIRONMENT=production`; dev compose, the e2e and perf stacks, `make demo`, the chart's `devLogin`, both CIs say `development` explicitly. `soundings api` / `worker` refuse to start when the environment is unset and the key is the built-in development one. | Decided (lead) | Review M1: the image fell back to development mode with a public signing key (forged `all` unsubscribe links and cheap, lasting ALTCHA challenges). The CLI refusal covers installs from the wheel; the Settings model stays usable for tests and tools. |
| ALTCHA refuses a signed challenge whose cost is below `SOUNDINGS_ALTCHA_COST` or whose expiry is beyond `SOUNDINGS_ALTCHA_EXPIRY` (plus 1 minute of clock skew). | Decided | Review L3: a leaked key could mint challenges with cost 1 lasting 8 years. |
| 120 writes a minute per signed-in person per API process (`SOUNDINGS_SESSION_WRITES_PER_MINUTE`), then 429 `rate_limited` with `Retry-After`; refused writes aren't counted; CSRF is checked first; sign-out is never limited. The e2e and perf stacks and CI's demo raise it to 100,000. | Decided (lead: 120, `rate_limited`) | Review L4: 40 comments with 11 mentions each in 2 s made 400 inbox rows. One setting, because the e2e suite sets its data up through the API as a handful of people. |
| `soundings anonymise-user <email>` (CLI only, deactivated accounts only): placeholder name and undeliverable address, identities, external ids, sessions, inbox, preferences and outbox deleted, keys revoked, @mention labels renamed (idea comments and proposal margin comments); work and audit entries stay; one `user.anonymise` entry (no actor, counts only). Expired sessions are deleted hourly. The operator guide lists what is stored about users and for how long. | Decided (lead) | Review L5: no erasure procedure for leavers; expired session rows waited for the next sign-in. |
| **Declined:** a minimum `q` length and emails for admins or co-members only in `GET /users`. | Declined (lead) | Review L8: an internal directory with emails for signed-in staff is intended. |
| The bundled Postgres: bootstrap superuser `postgres` (its own generated password) and a non-superuser app role that owns the database and its `public` schema; migrations, procrastinate and `pg_trgm` work (verified on a fresh volume; `COPY ... PROGRAM` refused). Older volumes keep their roles (documented). | Decided | Review L6: the app's role was a superuser, so any SQL injection would have been command execution. |
| `/api/docs` and `/api/v1/openapi.json` need a session or a person's key with `read` in production (401 / 403); open in development. | Decided (lead) | Review N1: anonymously they mapped the admin surface. |
| The API's metrics port admits only `networkPolicy.metricsFrom` peers and the release's pods (empty: nobody else). | Decided (lead) | Review N3. |
| Break-glass credentials reach the API pods only while `oidc.issuer` is empty (the Secret keeps the password for an outage). | Decided | Review N2. |
| `trustedProxies` and `networkPolicy.ingressFrom` stay two settings; `production-values.yaml` sets `ingressFrom`; NOTES warns when `ingressFrom` is empty (or policies are off) while `trustedProxies` covers private ranges; the operator guide explains it. | Decided (lead) | Review L1: any pod could choose its own throttle address. Deriving one from the other isn't possible (selectors vs address ranges). |
| Account-kind decisions live in the policy module as named traits (`is_agent`, `sees_email_trouble`, `may_cite_sources`, `counted_by_default`, `writes_as_ai`, `searches_co_members_only`; role matrix §1a). | Decided (lead) | Review N4 (ADR 0010). |
| The SSO callback's parameters are bounded (code 4 KiB, state 512, error 256, iss 2 KiB): past that the sign-in fails as `sso_failed` (a redirect and a denial, nothing sent to the IdP), not a 422. | Decided | Review N6; keeps the existing behaviour that IdP errors end on the sign-in page. |
| Dev compose publishes Postgres, Keycloak, Mailpit and the fake agent on 127.0.0.1 (`SOUNDINGS_DEV_BIND_ADDRESS`). | Decided | Review L7. |
| `make k3s-install PROD=1` / `k3s-smoke PROD=1`: production mode on the local k3s (no dev login or demo data; break-glass sign-in; `__Host-` cookies; the API's map for signed-in callers only; `/metrics` off the app port; the startup log; no password in the logs). | Decided (lead) | Review L10: no live install ran in production mode. |
| GitHub CI gains an `audit` job: pip-audit (backend runtime with otel, the fake agent), `npm audit --omit=dev`, Trivy on the built image (as GitLab: HIGH/CRITICAL with a fix fails). | Decided (lead) | Review L2. Validated here: pip-audit and npm audit clean; Trivy can't run in this sandbox. |
| **Deferred:** a final image stage without apt, dpkg, perl and bash. | Deferred (lead, after 0.1.0) | Review N5: stripping Ubuntu's base is fragile and WeasyPrint needs its libraries. |
| **Kept:** SVG logos (hardened and tested in Phase 4) and the per-agent A2A protocol (agents migrate one by one). | Kept (lead) | Simplifications the security review proposed. |

### Performance

| Decision | Status | Why |
|---|---|---|
| Static files ship with Brotli and gzip twins made at image build (`scripts/precompress-assets.mjs`; 1.76 MB of JS/CSS to 0.49 MB), served by `spa.py` with `Content-Encoding` and `Vary`; `index.html` is gzipped in memory. | Decided (lead) | Perf B4. |
| `GET` JSON of 1 KB or more is gzipped when accepted, except what the endpoint itself marked `no-store` (keys shown once), event streams and files. | Decided (lead) | Perf B4 (the board was 213 kB); BREACH: secrets are only in explicit `no-store` bodies, and CSRF and session tokens are cookies. Ingress compression is optional (operator guide). |
| Every database connection runs `SET max_parallel_workers_per_gather = 0`. | Decided | Perf B6: sorts over a 10k-idea project (score, title, votes) spent most of their time starting parallel workers (45-70 ms; 28-39 ms without), and under load the workers took the requests' CPU. |
| One- and two-letter searches match titles only, most recently active first. | Decided | Perf B6: pg_trgm can't narrow them; 98 ms to 25 ms (a miss: 92 to 49 ms). |
| Tag counts are a semi-join over the project's viewable ideas (`count(*)`). | Decided | Perf B6: 127 ms to 29 ms for a pending evaluator. |
| `GET /ideas/{key}` uses the facts it loaded (no re-read after a plain read) and one query for "watching" and "via the public form": 14 statements to 10-11. | Decided | Perf B6. |
| My work reads its owned groups in one statement (the board's `LATERAL` page per status, `pages_by_status`) and the first 50 evaluations due with their total and overdue counts as window aggregates, selecting only the columns an item shows. Same response. | Decided | Perf B1 follow-up: an owner of 225 ideas (five groups) still took 141 / 166 ms (p50 / p95) after C1; 108 / 122 ms after (A/B in-process on the 10k data set, identical bodies). |
| The session keep-alive runs after the response in a short transaction of its own, guarded in SQL (`SessionTouchMiddleware`). | Decided (lead) | Perf B8: a screen's parallel requests queued on the user's row lock until each committed. It also survives a request that fails. |
| **Declined:** two uvicorn workers per pod by default. | Declined (lead) | Perf B5: each process also keeps a warm PDF child; scale with replicas, and send fewer requests per screen (C1, C2). |

### Accessibility

| Decision | Status | Why |
|---|---|---|
| Exported PDFs are tagged (`pdf_tags`: headings, paragraphs, lists, tables, links), keeping the 20 s and box bounds. | Decided (lead) | Audit minor: the export had no structure tree. About 50% larger. |
| Every email is one `role="article"` landmark (`aria-roledescription="email"`, named by its subject); the layout tables stay presentational. | Decided (lead) | Audit minor: emails had no landmark. |
| **Deferred:** pdfjs-dist 6 in e2e (GHSA-hq66-cqwq-w95j). | Superseded (final verification: bumped) | Review L9: 6.x removed `PDFDocumentProxy.destroy()` (`e2e/tests/support/pdf.ts` now destroys the loading task, which works on 5 and 6) and the `isEvalSupported` option, which `readPdf` still passes (a type error on 6). With that one line dropped, 6.4.299 reads, colour-checks and renders the exported proposal exactly as 5.6.205 (checked 2026-10-07 in a scratch copy). Bump with `npm --prefix e2e install pdfjs-dist@6.4.299 --save-exact` in the same change. Test-only, reading the app's own PDFs. |


## 2026-10-07 · Phase 7 fixes: frontend

What the Phase 7 UX, accessibility and performance reviews changed in the SPA, and the
lead's calls. Every item was checked against the app first; the regression tests are
named in the frontend's `tests/a11y-phase7.spec.ts`, `tests/project-list.spec.ts` and
e2e `tests/a11y-phase7.spec.ts`.

### Simplifications

| Decision | Status | Why |
|---|---|---|
| **Settings** is about you (Account, Notifications, API keys); platform admins get **Admin** in the sidebar, its sections listed under it on an admin page and as a list at `/admin` (phones). The admin pages keep their `/settings/…` addresses. | Decided (lead) | UX M5: eleven tabs mixed personal and admin pages; on phones they scrolled sideways with shortened labels. |
| Project settings: four tabs. Status labels are a section of **General**, Branding a section of **Public form**; `?tab=statuses` and `?tab=branding` open the tab that holds them, at the section. | Decided (lead) | UX simplification: Branding only changes how the project faces outward (the form, submitter emails, PDFs). |
| **API keys** and **All API keys** are one page: platform admins switch between "Your keys" and "Everyone's keys" (`?everyone=1`); `/settings/all-api-keys` redirects with its filters. | Decided (lead) | UX simplification. |
| The create-key dialog offers the presets; the scope checkboxes are behind **Custom**. | Decided (lead) | UX simplification: presets and checkboxes side by side asked the same question twice. |
| AI is asked from the header's **AI** menu only (now with **Draft a section…**); the sidebar's "Ask AI to evaluate" is gone. The AI runs panel shows a row while a run works or after it stopped short (failed, timed out), plus runs seen finishing on the page; the rest fold under **History**. | Decided (lead) | UX simplification and m4: AI appeared in five places; a finished run's result is already in the feed and the Evaluations tab. |
| "Waiting for review" is the sidebar's count and the board's notice (one line on phones); My work no longer has the section. | Decided (lead) | UX simplification: three places for one queue. |
| The Users list leaves out AI agents' service accounts (they live in Admin → AI agents) and shows "Platform admin" / "Break-glass" by the name, Active or Deactivated as the status. | Decided (lead) | UX m3. |
| **Declined:** one Save model everywhere. Forms whose fields are checked together (project settings, rubric, branding) keep an explicit Save; single preferences and documents (notification preferences, proposals) save as you go. | Declined (lead) | UX m11; the rule is in the user guide. |

### UX

| Decision | Status | Why |
|---|---|---|
| The break-glass admin picks the project's **First admin** in New project; with nobody to pick, the dialog points to Admin → Users. | Decided (lead) | UX B1: the only account on a fresh install hit "No active user with that id". The API already took `admin_user_id`. |
| My work with no projects is a welcome: platform admins get **Create a project** (and `N` opens New project while there is none), others "Ask an admin for access". Empty sections are one line; viewers don't get "Ideas I own". | Decided (lead) | UX M3, m6. |
| The idea header's blue button follows the status: Evaluate (you owe a score), Assign owner / I'll own this, Invite evaluators, Close evaluation, Change status, Start proposal, Open proposal; none when there is nothing to do. | Decided (lead) | UX M6. |
| The status and owner pickers open on the current value; "Remove owner" is last. | Decided (lead) | UX M2: Enter straight away removed the owner or moved the idea back to New. |
| A new search, filter or sort starts the list at the top. | Decided | UX M4. Cause: the router's scroll restoration put the old offset back after the replace navigation; the page navigates with `resetScroll: false` and the list resets its virtualizer. |
| Phones: the project header keeps its actions beside the title, the description on one line, the view toggle as icons and the review notice as a one-line link. | Decided (lead) | UX M7: the first idea sat below the fold. |
| The receipt and `/track` say the tracking link isn't emailed (only a confirmation link is). | Decided (lead) | UX M1. |
| Public messages (form off or failing, broken tracking, confirmation and unsubscribe links) share one layout (`PublicMessage`); the unsubscribe page uses the public pages' frame. | Decided (lead) | UX m5. |
| Minors: idea keys never wrap (m1); "No proposal was written for this idea" on closed ideas (m2); one page width on every idea tab (m7); a thin progress bar after 300 ms of navigation and a board-shaped skeleton (m8); "1.2K" counts in collapsed board columns (m9); one button style per My work row (m10); the dark-mode logo plate grows around the logo (m12). | Decided (lead) | UX review. |
| Polish: the score hint once per sheet, and even scores worded by level and their neighbours (p1); "Saved" once, in the editor bar (p2); no breadcrumb on not-found pages, a chevron for audit details, narrower key columns (p4); full-width group pages, Details beside the idea facts on phones, the inbox dot at the row's start (p5). | Decided (lead) | UX review. The duplicated private-link sentence (p3) is in the demo seed's form introduction (`backend/app/seed/public.py`), not the page. |

### Accessibility

| Decision | Status | Why |
|---|---|---|
| A "Single-key shortcuts" switch in the `?` sheet, kept per person in the browser; off, keys without a modifier do nothing and their hints go. Every shortcut stays. | Decided (lead) | Audit major 1 (2.1.4). Dropping `[`, `v`, `f`, `1`–`3` declined. |
| One 2px ring (`highlight-ring`, the focus colour) marks the highlighted or selected item of every list (menus, selects, ⌘K, pickers, "Close as…"); a dark `--accent-control` token for radios, switches, checkboxes, scores and selected tabs; the neutral segmented control's selection has a border and semibold text. `tokens.test.ts` checks 3:1. | Decided (lead) | Audit majors 7–8 (1.4.11). |
| Focus is never hidden: the page scrolls fields clear of a sticky Save bar or the proposal's bar, the list's header sits above its rows, the card layout's sort buttons leave the Tab order, a focused board column scrolls into view on phones. Tab panels show the ring. | Decided | Audit majors 2–6 (2.4.11, 2.4.7). |
| Undo messages last 10 s and wait while the pointer or focus is on them; `Alt`+`T` is in the `?` sheet; the toast region is "Messages". | Decided (lead) | Audit major 9 (2.2.1), minor (two "Notifications"). |
| Rubric criteria have **Move up** / **Move down** in a row menu. | Decided | Audit major 10 (2.5.7). |
| "Continue" (a draft) is named "Continue evaluating KEY: title"; key hints are hidden from names and given as `aria-keyshortcuts`; board cards are named by their title and key, the rest as their description. | Decided | Audit 2.5.3 and minors. |
| After a navigation that left focus nowhere, focus moves to the new page's h1; titles name the project settings tab and project, and "Idea not found". | Decided | Audit minors. |
| **Declined:** a Help item in the account menu (3.2.6). | Declined (lead) | There is no in-app help to be consistent with. |
| **Rejected:** Radix menus outside landmarks (axe best-practice `region`). | Rejected | Menus are portalled, transient overlays opened from a control in a landmark; moving them inside one breaks their stacking. |
| **Deferred:** an arrow key whose keyup arrives with its keydown moves focus in a radio group without selecting. | Deferred | Radix moves focus in a timeout; normal typing works. Low priority in the audit. |

### Performance

| Decision | Status | Why |
|---|---|---|
| The sidebar's badges come from `GET /me/work/counts`; My work lists the first 50 evaluations due with **Show more** (100 at a time, `GET /me/evaluations-due`); the sidebar's review counts come from `pending_moderation_count` (no request per project). | Decided (lead) | Perf B1, B7 (contract-phase7 C1, C2). |
| List rows are memoised, the virtualizer re-renders without `flushSync`, table rows have a fixed height (cards are measured), and row tooltips mount on hover or focus (`HoverTooltip`). | Decided | Perf B2: 112 long tasks over 80 wheel ticks. |
| The idea route's loading and not-found states live in `idea-page-states.tsx`, so first visits don't download the idea page, AI and Markdown; the idea route's chunk (with the evaluate sheet) is fetched when the browser is idle. | Decided | Perf B3, B9. |
| ⌘K's first frame is the dialog and its input; the results mount in the next (deferred) render. | Decided | Perf B9: a 247 ms task on open. Sort and filter got the memoised rows above; anything further waits for the perf rerun's numbers. |

## 2026-10-07 · Phase 7 final verification

The lead's decisions at the close of Phase 7 and what the final verification changed.
Checks and evidence: [phase-summaries/phase-7.md](phase-summaries/phase-7.md); numbers:
[performance.md §9](test-plans/performance.md#9-final-verification-2026-10-07).

| Decision | Status | Why |
|---|---|---|
| My work shows the first **10 ideas of each owned group**, then "Show N more" 50 at a time: first from the ideas the response already holds (up to 50 a group), then through the group's `next_cursor` (`GET /me/owned-ideas`). No contract change. | Decided (lead) | Perf §8.3: an owner of 186 open ideas still rendered them all (TBT 2.0 s). Measured: data shown 3.2-3.6 s → 2.5-2.8 s, TBT 2.0 → 1.2-1.4 s, DOM 3,560 → about 1,870 nodes. |
| Opening an idea from the list keeps the idle preload of the idea route (B9), although its first frame is slower than without it (200-216 ms against 152-176 ms at 4x throttling). | Kept (lead: fix only if cheap) | Cause: with the chunk loaded, the router paints the idea page in the click's own frame (unmounting the list too); without it the first frame paints nothing new and the page shows about 250 ms later. The router's store renders synchronously, so no cheap change gives both. Known issue in the release notes. |
| Sort and filter, opening ⌘K, the evaluate sheet and reads at 20 people at once stay over budget. | Known issues (lead) | No cheap fix left after the Phase 7 fixes; numbers in the release notes and performance.md §9. |
| pdfjs-dist 6.4.299 in e2e (GHSA-hq66-cqwq-w95j), dropping `isEvalSupported` from `readPdf`. | Decided (lead) | Review L9. The PDF specs (BR-04, AC4-01, the public acceptance) pass on it in every e2e mode. |
| The README is the front door: what Soundings is, a 12-step tour from real screenshots (`docs/screenshots/tour/`, `npm --prefix e2e run screenshots:tour` with `E2E_SSO=1 E2E_AI=1`), quick start, documentation, architecture. [RELEASE-NOTES.md](RELEASE-NOTES.md) (0.1.0) lists what is in it, known issues, upgrade notes and the decisions to confirm. | Decided (lead) | The tour's email picture names its run-unique test project "Customer Care" (CARE-1); everything else is the screen as captured. |
| Guides, Helm NOTES and READMEs name the admin pages **Admin → …** (Users, Groups, Sign-in (SSO), Email, Branding, AI agents, Audit log) and the project's **Project settings → Public form**; the test email says "from Admin → Email". | Decided | They still said "Settings → …" from before the Settings/Admin split. |
| The fake agent's cancel tests wait until the task exists (`tasks/get` / `GetTask`) before cancelling. | Decided | A cancel could race a2a-sdk's task store and get −32001 (a flaky `make check-fake-agent`). Test-only. |

### Phase 7 simplifications (SPEC section 15, item 3)

Phase 7 added no feature; it removed places and choices. In one list (details above in
"Phase 7 fixes: frontend" and "backend and platform"):

1. **Settings is about you, Admin is for platform admins:** eleven tabs became three
   personal pages and an Admin section.
2. **Project settings: four tabs** (statuses inside General, branding inside Public form).
3. **One API keys page** ("Your keys" / "Everyone's keys") and **presets** in front of
   the scope checkboxes.
4. **AI is asked from one place** (the idea's AI menu); finished runs fold under History.
5. **The review queue in two places** (the sidebar count and the board's notice), not three.
6. **AI agents' accounts only under AI agents**, not in Users.
7. **My work previews** (50 evaluations due, 10 ideas per group) instead of everything.
8. **One switch for single-key shortcuts** instead of removing shortcuts.
9. **Declined to add:** two workers per pod (scale with replicas), a Help item, a
   minimum search length; **declined to change:** one save model everywhere.

## Phase 8 (product owner, 2026-10-07)

The product owner's change after reviewing 0.1.0. SPEC.md is read-only, so it is recorded
here; where it differs it **supersedes** SPEC section 2's "fixed, sensible template" for
proposals and its fixed lifecycle ("they can't add or remove stages"), and the Phase 0
non-goal line "The five statuses are fixed" (now: five, or six with the research step;
still no per-project stage designer). Contract: [contract-phase8.md](api/contract-phase8.md);
architecture: [ADR 0015](adr/0015-proposal-templates-and-research-step.md).

### A. Per-project proposal template (Decided, product owner)

| Decision | Why |
|---|---|
| Each project edits its proposal template like the rubric: project admins add, remove, rename and reorder sections; each has a title (1–60) and a one-line hint shown in the editor (≤ 200); 1–12 sections. New projects and every existing project start from today's eight. | Teams write different proposals (an internal tool needs "Effort & rollout", not "Market & users"). |
| Each section has a stable key: the eight keep `summary` … `next_steps`; new ones get a slug key, unique per project, immutable. Renaming keeps the key. | REST, MCP and AI drafts keep addressing sections by key. |
| Removing a section archives it: its text is kept but hidden from the editor and the exports; "Removed sections" in settings restores it with its text. | Nobody loses writing by tidying the template. |
| One template per project, live: every proposal in the project follows it at once (editor, margin threads, suggestions, "Draft with AI", MCP `get_proposal` / `propose_proposal_section`, PDF and Markdown). A removed or unknown key is a clean 4xx / tool error. | One place to change; no per-proposal drift. |
| No per-idea templates and no global template library: new projects start from the built-in defaults. | Simple beats configurable. |

### B. The research step (Decided, product owner)

| Decision | Why |
|---|---|
| Purpose: before the team invests in an idea, check it isn't already being done elsewhere in the company and that the right departments or teams were consulted. | Avoid duplicated work and late surprises from Legal, Security, IT. |
| Project setting "Research step": Off (default for every existing and new project), Before evaluation, Before proposal. When on, the lifecycle gains a Research status and board column at that position (New → Research → Evaluating → … or … → Shortlisted → Research → Proposal → Closed). `IdeaStatus` gains `research`, renameable per project. Cross-project views use one canonical order with Research after New. While Off there is no Research column or status anywhere in the project. | One optional stage, two sensible places; projects that don't want it see nothing new. |
| Switching the step off or moving it is refused while any idea of the project is in Research (409 with the count; the UI says to move those ideas first). | No idea is ever left in a status its project doesn't have. |
| A per-project research checklist, edited like the rubric (add, remove, rename, reorder; 1–10 items): title (1–80), hint (≤ 200, what to write), Required (default on). Completing an item is a free-text answer (1–2,000); for consultations a free-text box naming the department or team and what they said, not a user picker. Who answered and when is recorded; answers can be edited or cleared by the same people; removing an item archives it (answers kept, hidden, restorable). | The answer is the record people read later; consultations are with teams, not accounts. |
| Default checklist offered when the step is turned on: "Not already being done elsewhere" (required; search Soundings and ask around, note what you found), "Departments or teams consulted" (required; who you spoke to and what they said), "Data protection considered" (optional). | A useful start that teams can change. |
| The gate: an idea can't move to any status after Research (status change, board drag, the evaluator invite or anything else that would start evaluation before an evaluation step, starting a proposal before a proposal step) while a required item is unanswered: 409 `research_incomplete` with the open items. Project and platform admins may "Move anyway" (a request flag, audited, the reason optional). Moving back, or to Closed, is never blocked. An all-optional checklist is a guide that never blocks. Changing the checklist never moves ideas. | The step means something, with an escape hatch for the people accountable. |
| Who: the idea's owner and project admins (and platform admins) answer; everyone who can view the idea reads the checklist and answers (no score data; pending evaluators see them). API keys: answering is a write-scope operation; agents' keys never answer. | The owner does the research; evaluators benefit from it. |
| Help on the Research panel: "Similar ideas" (similar titles and summaries across every project the viewer can see, pg_trgm similarity, top 5, held ideas never shown) and the existing "Ask AI to research". Answers are shown to evaluators on the idea page, and proposal exports end with a "Research and consultation" appendix listing each answered item while the step is on. | Make the check easy to do and visible where decisions are made. |
| Public tracking shows Research as "With the team". Status-change notifications and emails cover Research like other statuses (no new notification types; never score data). | Submitters don't need the internal stage; members get the usual updates. |
| Demo: Internal Tools uses "Before evaluation" with the default checklist and a custom template (Summary, Problem, Solution, Effort & rollout, Risks, The ask), two ideas in Research (one complete, one partly answered); Sustainability uses "Before proposal" with a "Carbon impact" section added; Customer Innovation keeps the defaults with the step Off. | Show both positions and both features in the demo story. |

## 2026-10-07 · Phase 8 contract

Calls made while writing the Phase 8 contract ([contract-phase8.md](api/contract-phase8.md),
[ADR 0015](adr/0015-proposal-templates-and-research-step.md)). Status **Proposed** = the
lead's default; build it this way unless told otherwise.

### Templates

| Decision | Status | Why |
|---|---|---|
| Section rows, threads, suggestions and AI runs keep naming a section by **key** (`varchar(40)`, format `CHECK`), with **no foreign key** to the template; a removed section is archived when anything refers to its key (text in a proposal, a thread, a suggestion, an AI run), else deleted with its empty rows, all under the project's `FOR UPDATE` lock. | Proposed | Keys are immutable and a referenced key is never deleted, so they always resolve; no copied `project_id` on four tables, no backfill, historic rows untouched, a plain downgrade. Matches the rubric's archive-or-delete rule. |
| New keys come from the title (`section_key_for`: ASCII slug, `_2`, `_3` on a clash with any key the project has, removed ones included); the API never takes a key for a new section. | Proposed | Deterministic, readable in MCP and runs, no key field in the UI. |
| Restoring a section is putting its key back in `replace_proposal_template` (no restore endpoint); the replace also creates the section rows proposals lack. | Proposed | One endpoint, like the rubric; every proposal always has a row per active section. |
| No template tool in MCP: `get_proposal`'s sections carry the keys whenever a suggestion is possible. | Proposed | Keep the tool list at ten. |
| Threads, suggestions and an active draft run of a removed section are kept and hidden (404 by id); a running draft for it ends `no_result`. | Proposed | Nothing is lost; restoring brings them back; no cancel cascade to build. |

### Research

| Decision | Status | Why |
|---|---|---|
| The gate guards **crossings**: a status change into a status after Research from one that isn't; an idea's **first** evaluator (or "Ask AI to evaluate") before an evaluation step; starting a proposal before a proposal step. Ideas already past Research move freely among later statuses even when the checklist changes later. **To confirm with the product owner**: this reads "cannot move to any status after Research" as "cannot cross into one". | Proposed (to confirm with the PO) | "Changing the checklist never moves ideas" and turning the step on mid-flight shouldn't freeze ideas already evaluating. |
| **Reopening counts from the status the idea was closed from** (the latest `status_changed` into Closed, read under the idea lock; none recorded counts as New): reopening an idea that was past Research is never guarded, one closed from New or Research is (review must-fix 2). | Proposed | Undo of a Close must work for every idea past Research (ideas that passed before the step was turned on, ideas moved on with "Move anyway"), and owners can't override; New → Closed → Evaluating must not skip the check. |
| One choke point: `ideas.change_status` (also `create_proposal`'s move, with the override passed through) and one research-service helper for invites and "Ask AI to evaluate"; **no bypass**, the demo seed answers or turns the step on after moving its ideas. | Proposed | Every path that moves an idea forward uses the same check; nothing can skip it by accident. |
| c7 also allows Research while the step is before proposal, so "Start proposal" is the Research column's next step (gated). | Proposed | One click from finished research to a proposal. |
| The override is a request flag on the four guarded requests (`override_research`, optional one-line `override_reason`), needs `idea.research_override` (project and platform admins, **session only**) whenever it is true, is audited `idea.research_override` with the reason, and marks the status change `research_overridden`. Owners can't override. | Proposed | An explicit, accountable choice by the people who own the process; visible in the feed and the audit log. |
| One settings resource for the step and the checklist (`GET/PUT /projects/{slug}/research`), audited as two actions (step change, checklist replace); the default checklist comes from the server (`default_items`) and is created only on Save. | Proposed | One form, one save; one definition of the defaults. |
| Answers are plain text (not Markdown), last write wins, first author and last editor recorded, not activity events, not audited, not notified. | Proposed | Short records; calm feed; the panel shows who and when. |
| Status `research` while the step is off is 409 `research_step_off` (also for answers); the API never stores an idea in Research outside a research step. | Proposed | "No Research anywhere" holds by construction. |
| "Similar ideas": `pg_trgm` similarity ≥ 0.3 on title or summary, top 5, every project the viewer can see **archived included**, any status, never held ideas or the idea itself, owner shown, no scores. | Proposed | An archived project's idea is evidence it was tried; the owner is whom to ask. |
| Public tracking reports Research as **the status before it** in the project's lifecycle (`new` before evaluation, `shortlisted` before the proposal: `public_status`) and leaves moves that change nothing reported out of the history and the submitter emails (review must-fix 1). | Proposed | "With the team" without a new public status, and a "Before proposal" idea never drops back to "New" for the submitter. |
| Answers lose invisible characters (zero-width, bidi controls: the MCP `HIDDEN` set) and need one visible character. | Proposed | A lone zero-width space must not count as an answer and pass the gate. |
| Turning the step off ignores `items`: the checklist and answers are kept as they are. | Proposed | `{step: off, items: []}` must not delete a checklist the team will want back. |
| Cards show research progress only for an idea in Research or in the status before it; `blocking` is false for a closed idea; no per-card override flag (the 409 says whether you may move anyway); invites get a `invite_blocked_by_research` warning flag like "Start proposal" and "Ask AI to evaluate". | Proposed | Calm cards: no "0/3" on ideas past the gate or closed; one policy call per page, not per row. |
| c1 is unchanged: the submitter may edit their idea only while it is New; moving it into Research ends that, like moving it to Evaluating. | Proposed | Research answers ("not already done elsewhere") are about the text as it stood; the team has taken the idea up. |
| An AI draft's run message names the section by **key only**; the agent reads the title and hint in `get_proposal`, untrusted. | Proposed | Section titles are project admins' text, which ADR 0014 keeps out of agents' instructions. |
| No "Reset to the default eight" in the template editor; Removed sections restores. | Proposed | A deleted default's key can't be given back; simple beats configurable. |
| Template and checklist saves are last write wins, like the rubric. | Proposed | Rare, admin-only edits of a short list. |
| Project settings gains one tab, **Workflow** (Research step, Proposal template). | Proposed | Five tabs rather than six; both settings shape how ideas flow. |

### Contract mechanics

| Decision | Status | Why |
|---|---|---|
| The eight new operations are pinned in `PHASE8_OPERATIONS` (test_contract_routes), apart from `CONTRACT`, until identity adds their `ROUTE_KEY_ACCESS` rows and `ROUTE_RULES` and moves them into `CONTRACT`; meanwhile keys are refused on them. | Proposed | The meta-tests index identity's tables by every `CONTRACT` operation, so adding them earlier stops the whole backend suite at collection. This phase's contract owns no identity paths. |
| New response fields have server defaults in the schemas (`research_step = off`, `lifecycle` = the five, `research = null`, permission flags false) so the backend keeps building them until it implements Phase 8; the OpenAPI document still marks them required. | Proposed | Builders work in parallel on a compiling backend. |

## 2026-10-08 · Phase 8 build and integration

What the builders decided while building Phase 8, and the integration's fixes. The
backend's API-level choices are B1–B7 in
[contract-phase8 §10](api/contract-phase8.md#10-changes-after-the-contract); no API shape
changed after the contract review.

### Screens

| Decision | Status | Why |
|---|---|---|
| Project settings has **two** new tabs, **Research** (`?tab=research`) and **Proposal** (`?tab=proposal-template`), not one "Workflow" tab: six tabs for project admins (General · Members · Rubric · Research · Proposal · Public form), five for members. Supersedes the contract's Proposed "Workflow". | Decided (lead, integration) | Each is a long editor of its own (radio cards with the stages, a checklist with Removed items; a template with Removed sections); one tab meant scrolling past one to reach the other. |
| "Move anyway" is worded for the action it overrides: **Move**, **Invite**, **Ask** or **Start anyway**, each after an optional one-line reason. | Decided | The admin confirms what will happen, not an abstract override. |
| Admins keep Invite and "Ask AI to evaluate" while research is open, with a note (the 409's dialog offers the override); owners who aren't admins get **Open research** instead. | Decided | No dead buttons for the people who may override; a clear next step for everyone else. |
| The list's status filter keeps a chosen status the project no longer has (its research step was turned off). | Decided | A shared link still says what it filters on; it simply matches nothing. |
| A board with six columns (the research step) fits beside the sidebar at 1440 px: columns shrink to 176 px (were 192), and a card's footer wraps its counts under the badges instead of clipping them. | Decided (integration) | At 1440 px the Closed column was cut off and footers with a research badge ran past the card's edge. |
| The proposal editor's outline ends with a **Research and consultation** link while the appendix shows, and the appendix keeps to the text column. | Decided (integration, QA N1) | It is part of the document the exports print; it ran under the margin. |
| Text typed into a section removed meanwhile: after the save's 404 the editor reads the proposal again, so the section leaves the editor and the kept text says it was removed; if an admin restores the section, it is editable again and the kept text stays, saying it is back. | Decided (integration, QA P8-QA-F1) | Until a reload the removed section stayed in the editor and the kept text claimed it was "back in the template". |
| An idea's Proposal tab tells viewers the owner can start the proposal "once the research checklist is done" while required items are open before the proposal. | Decided (integration) | "Can start it now" was untrue there. |

### Platform and demo

| Decision | Status | Why |
|---|---|---|
| Soundings' fake agent drafts any section key of Soundings' shape (`^[a-z][a-z0-9_]{0,39}$`) and finds the section in `get_proposal`, as a real agent would; a key not in the proposal saves nothing. | Decided (integration, QA P8-QA-P1) | It accepted only the eight built-in keys, so "Draft with AI" for a project's own section (`carbon_impact`) failed against it. |
| The demo's amounts carry a currency (GREEN-4: "£18 each", "£40,000 a year"). | Decided (QA N3) | Bare numbers in an exported proposal read as a mistake. |

## Phase 8b (product owner, 2026-10-08)

The product owner's change after seeing Phase 8, and the lead's decisions on the Phase 8
review follow-ups. SPEC.md is read-only, so it is recorded here. Contract:
[contract-phase8b.md](api/contract-phase8b.md); security design:
[ADR 0016](adr/0016-research-assignment-and-guest-researcher.md), role matrix table L.

### C. Assign the research to a person (Decided, product owner)

| Decision | Why |
|---|---|
| One researcher per idea, optional; nobody assigned = the idea's owner does the research (as in Phase 8). An optional research due date, stored and shown like evaluation due dates (the instance time zone). | Research often means asking other departments; someone other than the owner may be best placed, with a date to aim for. |
| Anyone with a Soundings account may be the researcher, including people who aren't members of the idea's project; never a service account (AI agent), the break-glass account or a deactivated person. Deactivation and `soundings anonymise-user` clear the assignment without losing answers already written. | The researcher is often in another team; accounts that aren't people can't do research. |
| The idea's owner, project admins and platform admins assign, change or remove the researcher and set the due date; the researcher may hand it back. Only while the project's research step is on and the idea isn't closed; allowed in any open status. Assignment changes are audited like owner assignment. | The people accountable for the idea decide who researches it. |
| Assigning notifies the researcher ("Asked to research", with the due date and a link to the idea's Research panel), lists the work in their My work ("Research to do") and sends reminders 2 days before the due date and on the day, at the usual reminder hour, while the idea is in or before Research with a required item open; to the owner when nobody is assigned but a due date is set. Per-type email preferences (default immediate), digest and unsubscribe like the other types; never score data. | Like evaluations: people see what they owe and are reminded in time. |
| A researcher outside a private project sees that one idea only: title, summary, description, tags, status, owner, the feed and comments (they comment and @mention, and can be mentioned), the research checklist (they answer it) and Similar ideas limited to ideas they could see anyway; never score data, the evaluation, the proposal, other ideas of the project, the board, members, settings, moderation, the public form or "Ask AI". The project shows by name only. Access ends the moment they are unassigned, the idea is deleted or they are deactivated. A member keeps the normal member view; the role adds answering. | Ask another department for input without opening the project to them. |
| `idea.answer_research` widens to the researcher; the research gate and "Move anyway" are unchanged (a researcher can't override). | The researcher does the work; the accountable people still decide to skip it. |
| The idea's sidebar and Research panel say "Research: <name> · due <date>" ("Research: <owner> (owner)" with nobody); a person picker over all active people marks those outside the project; "Hand back" for the researcher; "Start research" opens a small dialog (who, default the owner; optional due date) and moves the idea into Research; Research cards show the researcher's avatar; a guest with no projects gets a working app shell. | Calm, one place to see and change who does it. |
| Demo: bob (not a member of the private Internal Tools) researches TOOLS-12, due in 3 days; amara researches GREEN-6; one overdue research assignment for the My work screenshot. | Show guest access, an explicit assignment and an overdue item. |

### D. Phase 8 review follow-ups (Decided, lead)

| Decision | Why |
|---|---|
| **M1:** once an idea is past Research, a required checklist item's answer can be edited but not cleared (409 `research_answer_required`); optional items, and ideas in Research or before it, clear as before. Role matrix §K records the exception. | "Answer, move on, clear" left an idea in Proposal at 0/3 with no trace (answers aren't audited). |
| **L3:** a `status_changed` event into or out of Research records the project's step at the time (`research_step`, an optional payload key never shown in the feed); public tracking and submitter emails read Research with that step. | Changing the step later rewrote a submitter's history (a status the idea never had). |
| **L4:** no "came from" exception to crossing-only: moving an idea back into Research and then forward again is a crossing like any other, guarded by the checklist; the SPA offers no Undo the gate would refuse (or offers it through the gate dialog). | An exception would let any idea once moved back be pushed forward again with the checklist open, at any time later. |
| **Performance rule:** a read over its p95 budget is measured again, up to three rounds, and judged by its best (`best_p95`); the owner's My work and the score-sorted board have a 200 ms budget on this shared VM (0.1.0's code misses 150 ms here too). Phase 8b: owned groups return their first 10 ideas (was 50); if both reads then meet 150 ms by the best-of-3 rule their budgets go back to 150, else they stay at 200 and `docs/test-plans/performance.md` records the machine's baseline. **Outcome (2026-10-09, backend):** on a quiet machine both met 150 ms in their first round (my work (owner) 80.2 / 84.0 ms, board -score 102.3 / 107.3 ms; performance.md §11), so both budgets are back at 150 ms. | One request's time spreads widely on this VM; the fix that matters is sending fewer cards. |
| Removed template sections and checklist items carry their former `position`, so Restore puts them back where they were. | Restored items landed at the end. |
| "Research this" is called "Ask AI to research" everywhere (role matrix, MCP guide, operator guide, scripts' comments; not the 0.1.0 release notes, which are historic). | One name, the SPA's. |

## 2026-10-08 · Phase 8b contract

Calls made while writing the Phase 8b contract ([contract-phase8b.md](api/contract-phase8b.md),
[ADR 0016](adr/0016-research-assignment-and-guest-researcher.md)). Status **Proposed** = the
lead's default; build it this way unless told otherwise.

| Decision | Status | Why |
|---|---|---|
| Columns on `ideas` (`researcher_id`, `research_assigned_at`, `research_due_at`), not a table; migration 0015. | Proposed | One researcher per idea, read with the idea on every card and page; no join, no second lock. |
| One `PUT /ideas/{idea}/research/assignment {researcher_id, due_at}` (the complete state, idempotent, last write wins; **session only**, contract review M3) and one `DELETE` for both "Remove" (owner, admins: `idea.assign_researcher`) and "Hand back" (the researcher: `idea.release_researcher`, like `idea.release_owner`; a `write` key may); the due date stays when the researcher goes. | Proposed | One dialog, one request; hand back mirrors stepping down as owner; the date is the idea's. |
| The owner may be assigned explicitly (they are told, and it stays theirs if the idea changes owner); nobody assigned is the implicit owner. | Proposed | No special case; lets an admin ask the owner by a date (the demo's GREEN-6). |
| The researcher picker is `search_users?project=&include_non_members=true` (members carry `project_role`, others null = "Not in this project"), not a new endpoint. | Proposed | It shows nothing beyond the directory every signed-in person already searches and the members `project.view` shows. |
| Guest access is a policy **column R** (no role, private project, the idea's live researcher) with its own cells (role matrix table L) and a **+Rsr overlay** that counts without a role; reads that check only `idea.view` today go through a deny-by-default route table (`view` / `rule` / `hidden`). | Proposed | One policy module, deny by default, testable as a table; new routes are hidden from guests until someone decides. |
| R's view is `idea.view` without `project.view`: no evaluator list, progress or evaluation due date either (the evaluation area follows `evaluation.view_own`, which R lacks), no AI panel (its runs include evaluate and draft runs), no submission panel. The feed comes without its evaluation events (an allow-list, contract review M2). | Proposed | "Never evaluations" read strictly; the feed is what the product owner listed, minus what would rebuild the evaluation area. |
| Internal projects: a researcher without a role there is NMi + Rsr, not R (they keep the board with scores and the proposal NMi sees, and gain answering, commenting and Hand back). | Proposed | Assignment adds, never takes away; hiding on the idea what the board shows would be incoherent. |
| Access holds while the assignment is **live**: the step on, the idea not closed, the project not archived. Closing the idea or turning the step off **clears** the assignment (contract review S8); archiving only suspends it. | Proposed (S8: product owner to confirm) | Removing the researcher is refused on closed ideas and with the step off (the product owner's rule), so a dormant assignment would otherwise bring a guest's access back on reopening without anyone deciding it. |
| Deactivation clears the assignment (audited `idea.researcher_change`, `reason: deactivated`; no feed event, no notification); the assignment locks the new researcher's user row `FOR SHARE`, deactivation updates the user first, then locks the ideas' projects `FOR KEY SHARE` and the ideas `FOR UPDATE`, each ordered by id (contract review S4). `soundings anonymise-user` has nothing left to clear (deactivated first). | Proposed | The researcher is always an active person; no inactive researcher can slip in by a race; the project-then-idea lock order of every idea write. |
| "Research to do" lists, for the researcher, every idea still awaiting research (not past Research, a required item open); for the owner with nobody assigned, only ideas in Research or the status before it, or with a research due date; only for someone who may answer it (contract review S3). Ordered by due date (nulls last), then id, with a cursor route. Reminders use the same rule and need a due date. | Proposed | Before a "Before proposal" step an owner's whole pipeline would otherwise count as research to do; before evaluation it can still be long, so it pages like evaluations due. |
| The researcher gets `status_changed` always while assigned and watches the idea on assignment; @mentions notify the idea's researcher besides people with a role; a guest's mention picker is the people directory. | Proposed | They have a job on the idea; mentioning them is how the team asks; no member list reaches a guest. |
| Migration 0015 gives `off` rows for the two new types to anyone who had every earlier type off. | Proposed | "Unsubscribe from all email" must stay all. |
| No feed or audit entry for the research due date; feed events `researcher_changed` and `research_due_date_changed`; audit `idea.researcher_change` with `reason` and `outside_project`. | Proposed | Like evaluation due dates and owner changes. |
| The three operations are pinned in `PHASE8B_OPERATIONS` apart from `CONTRACT` until identity classifies them for keys and rules; the two feed types stay out of `ACTIVITY_TYPES` (`PHASE8B_ACTIVITY_TYPES`) until backend adds their payload keys. | Proposed | The meta-tests and an import-time guard index those tables; adding them earlier would stop the backend suite. |

## Phase 8b contract review (2026-10-08)

An adversarial review of the Phase 8b contract; every item and its outcome is in
[contract-phase8b §18](api/contract-phase8b.md#18-contract-review-2026-10-08). The calls:

| Decision | Status | Why |
|---|---|---|
| Lists stay project-scoped (`listed_ideas` unchanged); a guest's idea joins only search, MCP `search_ideas`, the inbox, My work's "Research to do" and "Similar ideas" through `researched_ideas()`. Every SQL score mask also requires the idea's project to be viewable; summaries' evaluation fields follow `evaluation.view_own`; MCP `has_proposal` follows `proposal.view`. | Decided (review M1, C1) | Widening every list leaked scores through summaries, owned lists and `sort=score`; a new list should stay closed to guests until someone decides. |
| A guest's feed is an allow-list (`RESEARCH_GUEST_ACTIVITY_TYPES`) without the six evaluation events. | Decided (review M2) | Evaluators added and removed, evaluations submitted (AI agents' too), closed, reopened and the evaluation due date rebuild the evaluation area R must not see. |
| Assigning the researcher is session only; removing or handing back takes a `write` key. | Decided (review M3) | An assignment can open a private idea to any account and would outlive a leaked key after it is revoked; removal only takes access away. |
| **Who may open a private idea to someone outside it, and whether removal from the project ends a guest's access.** As built: the product owner's rules (the idea's owner, project admins and platform admins name anyone; access ends when unassigned, the idea deleted, the researcher deactivated, and now when the idea is closed or the step turned off). Options for the product owner: **(a)** in a private project only project or platform admins may name someone without a role there (an owner who is a member names members; a condition and a permission flag, small); **(b)** losing one's role in a private project (an admin's removal, a group mapping, an IdP group sync) clears one's assignments there, audited, and project admins are told about outside assignments (every role-changing path must compare before and after, larger). Meanwhile everyone who sees the idea sees "not in this project" beside such a researcher, the feed records every assignment and the audit marks `outside_project`. | **Decided** (review S1: the product owner chose (a) and (b) on 2026-10-08; see below) | Any member may volunteer to own an unowned idea and then open it to any account; a member removed from the project (also by a group sync) keeps guest access to the idea they research. Both follow the product owner's stated rules, so they decide whether to narrow them. |
| Closing an idea or turning its project's research step off ends the research assignment (nobody assigned, audited `closed` / `step_off`, no event or notification, the due date kept); reopening or turning the step on again doesn't bring it back; an archived project only suspends it. | **Decided** (review S8: confirmed by the product owner on 2026-10-08) | The product owner refused removal on closed ideas and with the step off, so a dormant assignment would otherwise silently restore a guest's access on reopening. "Access ends on close" wasn't on their list. |
| `evaluations_complete` needs `evaluation.view_own`; "Research to do" and research reminders need `idea.answer_research`; the inbox shows a guest only `RESEARCH_GUEST_NOTIFICATION_TYPES` about the idea; "Asked to research" at most once per idea, person and local day. | Decided (review S3, S5, S6) | A stale owner who is a guest must not learn about evaluations; an owner who lost their role can't do the research; older evaluator items must not resurface; assigning and removing someone again and again mustn't flood them. |
| `WorkResearch.can_view_project`; search and inbox rows link a project only when it is in `list_projects`. `StatusChangedActivity.from_label` / `to_label`. | Decided (review S7, C6) | A guest's links must not lead to 404 pages; a guest can't read the project's status labels. |
| "Research to do" keeps its cursor route; ordered by due date (nulls last) then id; both counts in one statement; `ck_ideas_researcher_assigned_at` one way; last write wins for the assignment; automatic clears emit no feed event; the watch stays after unassignment. | Decided (review C3, C4, C5, C7) | Owners before evaluation can have many New ideas to research; stable keysets; fewer statements; the reminders rely on `research_assigned_at`; simple beats configurable. |

## Phase 8b (product owner answers, 2026-10-08)

The product owner's answers to the Phase 8b contract review's open questions, recorded by
the backend builder ([contract-phase8b §17](api/contract-phase8b.md#17-changes-after-the-contract)).

| Decision | Status | Why |
|---|---|---|
| **S1 (a):** in a **private** project only project admins and platform admins may name someone without a role there as researcher; the idea's owner names anyone with a role there, themselves included (403 `outside_researcher_needs_admin` otherwise; condition c25; flags `can_assign_outside_researcher` on `IdeaPermissions` and `ResearchPermissions`, so the picker offers outsiders only to admins). Internal projects unchanged: the owner names anyone. | Decided (product owner) | Opening a private idea to another department is the project admins' decision; any member may volunteer to own an idea, so the owner alone shouldn't. |
| **S1 (b):** losing one's role in a private project (an admin removes the member, a group grant, the person from a group or the group itself, or a sign-in group sync does) ends one's research assignments there: nobody assigned, audited `reason: left_project`, answers and the due date kept, no feed event or notification. Changing between roles ends nothing. | Decided (product owner) | Leaving the project must end access to its ideas; the guest view is for people an admin chose to ask from outside. |
| Making a project private (internal → private) ends no assignment: nobody lost a role, and outsiders an internal project's owner had named stay (the "not in this project" marker and the audit show them). | **Superseded** by the lead's D2 (2026-10-09, [below](#phase-8b-review-leftovers-lead-2026-10-09)): their assignments end, after a warning | The admin changing visibility can remove them in one click; ending them silently would surprise the owner. |
| **S8:** closing the idea or turning the research step off clears the assignment (audited `closed` / `step_off`, the due date kept); reopening doesn't bring it back; archiving only suspends it. | Decided (product owner) | Confirmed as built. |


## 2026-10-09 · Phase 8b build and integration

What the builders and the integration decided while building Phase 8b. API-level changes
after the contract are in [contract-phase8b §17](api/contract-phase8b.md#17-changes-after-the-contract).

| Decision | Status | Why |
|---|---|---|
| A board card keeps its accessible name "Title (KEY)"; "Researched by <name>" is the card's description (and the avatar's label), not part of the name the contract proposed. | Decided (frontend, accepted at integration) | e2e and Playwright locators match cards by `/\(KEY\)$/`; the researcher is still announced with the card. |
| "Start research" shows one toast, the status change's own (with Undo), not a second one for the assignment. | Decided (frontend) | One action, one message; the dialog already said who does it. |
| Any write refused with 404 re-checks the idea on screen (the query client invalidates idea details), so the page shows "doesn't exist", drops the idea's queries and refreshes My work's counts. | Decided (integration, QA P8B-QA-F1) | A guest researcher reassigned while the page was open kept reading the stale idea after her save was refused; the contract says access ends at once. One rule for every write, not a hook per mutation. |
| The researcher picker starts its highlight on the current choice, the owner row included; "No due date" sits beside the date field. | Decided (integration, QA N1, N2) | Enter straight away must change nothing; on a phone the clear button wrapped onto a row of its own. |
| An owner whose picker lists only the project's people (a private project) sees the outsider an admin asked as a row of its own above the members ("Not in this project"), chosen and highlighted, so they can keep them and change only the due date. | Decided (integration, real-stack walkthrough) | The outsider wasn't in the owner's list, so the highlight started on the first member and Enter replaced the researcher. |
| The owner may keep an outside researcher an admin named and change only the due date: c25 applies only when the researcher changes. | Decided (backend, confirmed at integration with a test) | The dialog sends the complete state, so the same researcher comes back with every due-date change. |

## Phase 8b review leftovers (lead, 2026-10-09)

The lead's decisions on what the Phase 8b reviews (code, guest access, UX) left open,
built after the review fixes; API changes are in
[contract-phase8b §17](api/contract-phase8b.md#17-changes-after-the-contract).

| Decision | Status | Why |
|---|---|---|
| **D1:** past Research, a researcher who isn't the idea's owner or an admin can no longer change the answers: they answer, edit and clear only while the idea is in Research or a status before it (and not closed). Afterwards `answer_research_item` / `clear_research_item` are **409 `research_finished`** for them (condition **c26** on the +Rsr overlay of `idea.answer_research`; sessions and API keys alike) and `IdeaPermissions.can_answer_research` / `ResearchPermissions.can_answer` are false; the SPA shows the answers read only with one line saying why. The owner (with a member or admin role) and project and platform admins keep Phase 8's rule (M1: past Research a required answer is edited, never cleared). | Decided (lead; guest review L2, code review C1) | Past Research the answers feed the proposal's "Research and consultation" appendix, which a guest can't see, and answer edits aren't audited. |
| **D2:** when a project goes from internal to private, the research assignments of researchers without a role in it end at once: nobody assigned, audited `idea.researcher_change` with `reason: made_private` (actor: the admin), answers and the due date kept, no feed event or notification, like leaving a private project (S1 b). The admin is warned first: `Project.outside_researcher_count` (additive; project and platform admins, null for everyone else) counts those people, and the visibility change asks "N people researching ideas here aren't in the project and will lose access" when N > 0. The `project.update` audit entry's `outside_researchers` says how many assignments ended. "No role" is role-based as in c25 and S1 (b): a platform admin without a role there counts too. | Decided (lead; code review L1, guest review L4; supersedes backend's "ends no assignment") | Otherwise an owner's choice in an internal project (where c25 lets them name anyone) became a guest's access to a private one, which only an admin may grant (c25). |
| **D3:** "Asked to research" emails wait **5 minutes** when the idea asked someone less than 5 minutes before (`RESEARCHER_EMAIL_HOLD`; the send-time check cancels a request that is no longer live, so passing an idea round quickly emails only the first person and the one finally asked), one person's requests email at most **20** people per rolling hour (`RESEARCHER_EMAIL_CAP`; beyond: in-app only, like mentions), and notifications are deduplicated **per assignment** (`researcher_assigned:<event id>`, payload `{due_at, assigned_at}`), replacing the contract's once per idea, person and day (review S6). | Decided (lead, accepting the review fixes; code review M1, L2) | One a day swallowed a real re-assignment's notice; the hold and the cap stop the directory being emailed at the write rate. |
| **D4:** an explicitly assigned owner stays the researcher when the idea changes owner (contract §3.7: "the owner changes: nothing"); with nobody assigned the new owner does the research. | Decided (lead; kept as the contract says) | An explicit assignment is a person asked by name, not a role; the assigner can change it in one step. |
| **D5:** docs the review fixers asked for: contract-phase8b §6.1 (dedupe key per event, payload `{due_at, assigned_at}`) and §17 (the `outside_researchers` audit detail, then D2); the role matrix's c22 reads by run kind (a research run reads as its guest researcher would; among the research assistant's runs only drafting reads the proposal); docs/mcp.md (what research runs read; masked guest values: `score` null, `evaluator_progress` 0/0, `has_proposal` false); MCP `research_guest`'s description; `DueAt` returns UTC at the schema level (the root of code review N1; the API shape is unchanged); the kagent idea-researcher's system message says `get_proposal` works only in drafting runs (both manifests); the composer's line for a guest reader uses `assignment.researcher_in_project` (guest review L3). | Decided (lead) | One place for each rule; agents and MCP clients told what the masked values mean. |

## Phase 8b adversarial check (2026-10-09)

An adversarial check of D1, D2 and the research-run reads found two low findings and two
nits; all four are fixed
([contract-phase8b §17](api/contract-phase8b.md#2026-10-09--the-adversarial-check-of-d1-d2-and-the-research-run-reads-backend-frontend)).

| Decision | Status | Why |
|---|---|---|
| **L1:** a research run can't call `list_projects` (`ai_run_not_active`, like `get_rubric` and `get_proposal`); `get_idea` and `search_ideas` already name the idea's project. Evaluate and drafting runs list the run's project as before. | Decided (fix) | It returned a private project's description, idea count and the agent's role, which the guest researcher reading the note can't see (404); the run must read no more than its guest. |
| **L2:** past Research nobody new is asked: `set_research_assignment` naming a researcher other than the current one is 409 `research_finished`, for owners and admins alike; removing, handing back and keeping the same researcher still work; moving the idea back to Research lets the owner ask again. The SPA shows **Remove** instead of Change past Research (a confirmation that says why), and nothing while only the owner does it. | Decided (fix; chosen over documenting a "read-only consultation") | After D1 such a researcher could only read the idea, so the assignment would just open a private idea to someone and email them "Please research" for work they can't do. Simple beats configurable: one rule, no new flag (`can_assign` still covers Remove). |
| **N1:** "Make this project private?" counts the outside researchers again on Save (the project is read afresh) instead of using the count from when the page loaded. | Decided (fix) | An outsider asked while the settings page was open was otherwise dropped without the warning. |
| **N2:** an answer typed but not saved when the answers turn read only (the idea moved on) stays under its item with Copy and Discard (with Undo), and comes back from the browser's drafts on the next visit. | Decided (fix) | The draft was kept but nothing showed it, so the text was lost to the person who wrote it. |

## Phase 9 (product owner, 2026-10-09)

Continuous delivery, asked for by the product owner; the lead's build decisions follow
in the same table. How it works: [operator guide, "Continuous delivery"](operator-guide.md#continuous-delivery-phase-9),
[ADR 0017](adr/0017-continuous-delivery.md); research: [gitlab-cd](research/gitlab-cd.md),
[github-cd](research/github-cd.md).

| Decision | Status | Why |
|---|---|---|
| GitLab is self-managed and on-prem with runners inside the network; images and packages come from internal mirrors; nothing needs the internet at run time (every image a variable or pinned by digest, mirrors for packages, the runner helper image). | Decided (product owner) | The organisation's network. |
| The pipeline reaches the cluster only through the GitLab agent for Kubernetes (CI/CD workflow, `ci_access`); no kubeconfig or cluster credential in GitLab. One agent per environment, its ServiceAccount bound to the `soundings-deployer` ClusterRole (namespaced rules) in its namespace only, `rbac.create=false`, no impersonation; `ci_access` names this project, the environment and protected refs only (both agents, since the live run's F2). | Decided (product owner; lead: namespace RBAC over impersonation) | Least privilege that works on GitLab Free; impersonation is Premium and needs a cluster-wide `impersonate` right. |
| Every push to main builds, pushes and deploys staging; a `vX.Y.Z` tag rebuilds (version label), deploys that image to staging, publishes the release and waits at the production gate, which deploys the digest staging ran. | Decided (product owner; lead: rebuild on tags) | The production image has passed staging; the tag's image carries its version. |
| Production gate: GitLab Free a manual job (`allow_failure: false`) on a protected `v*` tag; Premium adds a protected environment with approvals (same YAML). GitHub: the `production` environment's required reviewers (public repositories, Enterprise), or `SOUNDINGS_PRODUCTION_GATE=manual`, the `deploy` workflow run on the tag (private Pro/Team, which have no reviewers); private Free repositories have no environments and aren't supported for production. | Decided (product owner, lead) | GitLab Free has no deployment approvals; GitHub's reviewers need Enterprise for private repositories. |
| GitHub gets the same flow after its checks, in `ci.yml` (staging waits for this commit's checks), deploy jobs on self-hosted runners in the network (ARC) whose pods have no cluster rights; each environment deploys with a namespaced token of `soundings-ci-deployer` in its environment's secret `KUBECONFIG_DATA` (`scripts/lib/ci-kubeconfig.sh`, renewed monthly; the `staging` environment allows `main` and `v*.*.*`); ARC-only (Enterprise) and API-server OIDC documented as alternatives. Push runs no longer cancel each other (pull requests still do); each deploy has its own non-cancelling group. | Decided (product owner, lead; review H2: the staging runner's own rights removed) | The cluster is on-prem; a runner label is not access control below Enterprise (any branch's workflow could deploy staging and read its Secrets); a cancelled helm upgrade leaves the release stuck. |
| Each environment is deployed by one CI at a time: `SOUNDINGS_DEPLOY` lists the environments a CI deploys (empty: checks only); production requires staging in the same CI. The deploy script refuses a release the other CI made unless `DEPLOY_FORCE=1`. | Decided (lead) | Their locks can't see each other and both would upgrade the same release. |
| One shared script, `scripts/deploy.sh deploy\|rollback\|smoke\|status\|template <env>` (+ `check-release`): render check, `helm upgrade --install --atomic --wait --cleanup-on-fail`, image by digest, values from `deploy/environments/<env>.values.yaml` (no secrets) plus CI variables, `helm test`, then the production-safe smoke (`scripts/deploy-smoke.sh`: health, readiness, the SPA and its script, anonymous API 401, `/mcp` 401 with a Bearer challenge, no public `/metrics`; plus every pod on the digest and the app's version for X.Y.Z tags); a failed test or smoke rolls back to the previous revision. No `--create-namespace`. | Decided (product owner, lead) | One behaviour for both CIs and people; a failure leaves the previous release serving. |
| Migrations and rollback: migrations stay compatible with the previous release (expand, then contract in a later release). Each revision carries Helm labels `soundings.io/migration-head` and `soundings.io/deployed-by`; a manual rollback to a revision with another migration head, and a deploy of an image with an older head than the database's, are refused unless `DEPLOY_FORCE=1`. The head is read from the checkout's `backend/app/migrations` (`MIGRATION_HEAD` overrides). A revision that restores older content (Helm's `--atomic`, the script's or a manual rollback) is relabelled with the database's head, the newer of the two, unless the migration Job failed. | Decided (lead; review M3) | Helm's rollback restores pods, not the schema, and copies the target's labels: without the relabel, older deploys and rollbacks two releases back were no longer refused. |
| Image tags: every GitLab pipeline pushes `ci-<pipeline id>` for its tests; main also `sha-<8 hex>` (both CIs: GitLab's short SHA length), tags `X.Y.Z` and `X.Y`, all one digest in one push; no `latest`. Immutability is the registry's (GitLab Ultimate immutable tags, protected container tags, Harbor rules); deploys pin digests, so a moved tag never moves an environment. | Decided (build) | A fast-forward merge would otherwise rebuild and re-point `sha-*`; the build jobs have no registry client to refuse an existing tag. |
| The app reports `backend/pyproject.toml`'s version (package metadata), not the image's `VERSION` build argument: a tag pipeline's `release:check` / `release-check` requires `pyproject.toml`, `uv.lock` and `Chart.yaml` (`version`, `appVersion`) to say X.Y.Z, so a release commit bumps them. | Decided (build); a build-time version would need a backend change (request to the backend owner) | "The app's reported version follows the tag" without touching `backend/`. |
| Scan gate before any deploy: Trivy 0.75.0 by digest, `SCAN_SEVERITY` default `HIGH,CRITICAL` with a fix (0.1.0's gate, kept; `CRITICAL` is the product owner's minimum), on the pushed digest; a CycloneDX SBOM from Trivy attached to the release with the packaged chart. cosign with a key, no transparency log, optional (`COSIGN_PRIVATE_KEY`). | Decided (product owner; build: kept the stricter default) | Everything that exists stays; keyless signing needs the internet. |
| Image builds: rootless BuildKit (`moby/buildkit:v0.33.1-rootless`) on unprivileged Kubernetes runners by default, `docker buildx` on dind with `IMAGE_BUILDER=dind`; kaniko removed (archived). The CA (`CI_BUILD_CA`, one name in both CIs) and the mirror build args keep working. | Decided (product owner, lead) | Kubernetes runners aren't privileged; kaniko is unmaintained. |
| Supply chain: every action pinned by commit SHA at its latest release (checkout 7.0.1, setup-python 7.0.0, setup-node 7.1.0, upload-artifact 7.0.2, download-artifact 8.0.2), `persist-credentials: false`, least-privilege permissions per job, no third-party actions (Trivy, cosign, helm from digest-pinned images; buildx in plain shell); Dependabot for `github-actions` and `docker` with a 7-day cooldown; `make check-workflows` (actionlint 1.7.12, zizmor 1.30.1, gitlab-ci-local 4.75.1) in `make check`. | Decided (lead) | The March 2026 trivy-action compromise re-pointed tags; digests and SHAs were safe. |
| Deploy images: GitLab's `DEPLOY_IMAGE` defaults to `alpine/k8s:1.31.13` by digest (helm 3.19.0, kubectl, bash, curl); `deploy/ci/deploy-runner.Dockerfile` builds the ARC runner (the official runner image plus helm 3.16.2 and kubectl 1.31.14, copied from digest-pinned images) and a small `tools` image as the alternative. Local tooling keeps helm 3.16.2. | Decided (build) | A public image works out of the box from a mirror; the script runs on both helm versions (rehearsed). |
| The bundled Postgres's pod template no longer carries the version and chart labels. | Decided (build; chart change for the lead to confirm) | With CD every deploy changed them, restarting the database on each push to main. |
| **Review fixes (2026-10-09).** Who can deploy production through GitLab: the agent can't tell `main` from a tag (`protected_branches_only` admits every protected ref), so on Free whoever may merge into a protected branch can reach production. Free: *Allowed to merge* and *push* on every protected branch = the people allowed to create `v*` tags; Premium: protect the environments (GitLab drops other users' jobs for them, any action: verified in 19.4's source) and Code Owners for the delivery files; the agents' configuration preferably in a project the platform team owns (`KUBE_AGENT_PROJECT`). A separate production deploy project is documented, not built. | Decided (lead, review H1; product owner to confirm the Free merge rule) | The claim "only tag creators can deploy" was wrong; no YAML can fix it, only who may write to protected refs. |
| The registry layer cache never feeds a release image: GitLab's protected refs build from scratch and write `cache:buildkit`, other pipelines only read it; GitHub builds without a cache. | Decided (lead, review H3) | Any job token (any Developer's branch) can write the cache repository; a planted layer would pass the scan. A cold build costs about 1.5 minutes. |
| Deploy jobs run only on a protected runner tagged `DEPLOY_RUNNER_TAG` (`soundings-deploy`), not shared with merge-request or privileged jobs; GitHub's build job keeps its registry login in `RUNNER_TEMP` and removes its builder. | Decided (lead, review M1, L6) | A runner host taken over through another job would see later deploys' kubeconfigs. |
| Pipeline variables override every gate: keep GitLab's *Minimum role to use pipeline variables* at Maintainer (the self-managed default; 19.4 also checks it for variables typed when playing a manual job). `deploy:production` refuses a `CD_ONLY` pipeline; `SCAN_SEVERITY` must include CRITICAL in both CIs. | Decided (lead, review M2) | Defaults that hold even when someone sets a variable by mistake. |
| The deploy script: the restored release's smoke failing is a distinct, loud failure ("may be down"); the smoke reads the app's tables (`GET /api/v1/branding`); the migration Job's deadline must be below `HELM_TIMEOUT` (the environments set 480 s); a version tag whose app version can't be read fails (keep `logLevel` INFO); a deploy waits for one in progress (3 × `HELM_TIMEOUT` from its start, then stale); a deploy from an older CI run than the running revision's (label `soundings.io/pipeline`), or of an older `X.Y.Z`, is refused; deploy jobs time out after 90 minutes; Helm's "another operation in progress" is reported as such. | Decided (lead, review M4, L2-L4, L10, nits) | Rehearsed on k3s (test plan CD-17 to CD-24). |
| *Prevent outdated deployment jobs* stays off on GitLab; the script's run-order check replaces it in both CIs. GitHub's deploy queues: `main`'s staging deploys replace each other, a release's staging deploy and the rollbacks queue apart. | Decided (lead, review L2, L3) | GitLab orders deployments by pipeline creation: a `main` deploy during a tag pipeline would fail the tag's staging deploy and the release would never reach the gate; GitHub keeps one pending job per group. |
| New migrations are linted for expand/contract (`scripts/lib/check-migrations.py`: drops, renames, new types, NOT NULL in `upgrade()`; `# contract-ok: <reason>` to accept), from 0016 on, in GitLab's `migrations:lint`, GitHub's `helm` job and `make check-migrations`. | Decided (lead, review M4) | The rule that makes automatic rollback safe was only written down. |
| GitHub's manual production gate (Pro/Team): only logins in `SOUNDINGS_PRODUCTION_DEPLOYERS` (an admin-only variable), only from an immutable release, only an image of this CI's repository with the tag's version; the same list for production rollbacks. "Someone approves" is one person there, not two. Deploy jobs get `CI_BUILD_CA` passed explicitly; production waits for the release in both CIs. | Decided (lead, review M5-M7, nit) | Write access could otherwise deploy any release or swap the release's `image.env`. |
| Air gap, stated exactly: release-path images by digest (node, docker, dind and helm newly pinned; GitHub's build uses the same Ubuntu and Node pins), test-only images by tag; mirrors for the k3s job (`ALPINE_MIRROR`, `K3S_REGISTRY_MIRROR`, `KAGENT_GIT_URL` checked against `KAGENT_COMMIT`); the fake agent's job no longer installs `make` from Debian; Trivy without version checks or telemetry, with the CA and the Java DB mirror on GitHub too. GitHub's own check jobs run on GitHub's runners by design. | Decided (lead, review M8, L5) | The guide claimed more than the pipeline did. |
| Kept, with reasons: rollback jobs stay `action: access` (a GitLab deployment would record the pipeline's commit while an older revision runs; protected environments and approvals apply to them anyway); `DEPLOY_IMAGE` stays `alpine/k8s` by digest, with the `tools` target recommended for production (a default the site must build first would fail out of the box; the target's base is the same community helm image); GitHub keeps a 30-day namespaced token (API-server OIDC needs the issuer's keys, i.e. GHES inside the network); cosign is verified by an admission policy, not by the deploy (whoever controls the CI could skip a CI-side check); unfixed CRITICALs are reported, not gated, by default (`SCAN_IGNORE_UNFIXED=false` gates them); the deployer's optional kinds (kagent, Gateway API, ServiceMonitor) stay in its one ClusterRole (without their CRDs the rights do nothing). | Decided (lead, review L1, L9, L11, L12, nits; product owner to confirm the unfixed-CRITICAL default) | Each alternative costs more than the risk it removes, or moves the check to where it can't be bypassed. |
