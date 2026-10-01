# Test plan: Phase 2 (sign-in and access)

Owner: qa. Source of truth for behaviour: [SPEC.md](../../SPEC.md) sections 7 and 13,
[contract-phase2.md](../api/contract-phase2.md) (business rules §3, error codes §4),
[role-matrix.md](../role-matrix.md) (c11, c17, c18) and
[ADR 0005](../adr/0005-server-side-sessions-oidc-csrf.md). Each row has an ID used in the
test names, so a failing test points back here. Phase 1's plan
([phase-1.md](phase-1.md)) still applies; its suite runs in both modes below.

## Acceptance criterion

> Keycloak users get the right project access from their groups; removing a group
> removes access at next sign-in (managed mapping). (SPEC section 13, Phase 2)

It is tested three times, each adding something the others don't:

| Level | Test | IdP | What it adds |
|---|---|---|---|
| Browser (UI) | `e2e/tests/sso-acceptance.spec.ts` (SA-*) | real Keycloak 26, dev realm | The admin maps groups through the UI and the API; alice, bob, carol, dave and erin click "Sign in with SSO", type their Keycloak password and land with exactly the expected roles (the access list compared whole); bob is removed from `/innovation/members` in Keycloak, keeps access in his running session, signs out through Keycloak and in again and loses the project; manual and additive variants; Keycloak memberships restored after each. |
| HTTP API | `backend/tests/acceptance/test_phase2_acceptance.py` (AC2-API-*) | identity's fake OIDC provider | Everything arranged and checked through the public admin API only (external IDs, groups, mappings, grants, access list, user detail, mapping test, audit viewer); a group-granted *admin* role used and lost; the mapping test's prediction compared with the next real sign-in; offboarding by deactivation. Runs in `make check-backend` without Keycloak. |
| HTTP API + Keycloak | identity's `backend/tests/identity/test_keycloak.py` | real Keycloak (testcontainer) | The code flow with PKCE against Keycloak's own login form; groups and grants arranged in the database; managed, additive and manual variants (§3.13). Not duplicated here. |

## How to run

| What | Command | Needs |
|---|---|---|
| API acceptance (part of `make check-backend`) | `cd backend && uv run pytest tests/acceptance` | Docker (testcontainers) or `TEST_DATABASE_URL` |
| E2E with SSO (Phase 1 + 2) | `E2E_SSO=1 npm --prefix e2e test` | Docker (Postgres + Keycloak 26), `uv`, Node 22, Chromium |
| E2E without SSO (dev login + break-glass) | `npm --prefix e2e test` | as Phase 1 |
| Only the SSO specs (what CI's SSO jobs run) | `E2E_SSO=1 npm --prefix e2e test -- --grep @sso` | |
| Screenshots | `npm --prefix e2e run screenshots:phase2` → `docs/screenshots/phase-2/` | a run with SSO, then one without (break-glass page) |

**The stack** (`e2e/scripts/start-stack.sh`, platform's SSO mode): `E2E_SSO=1` adds
Keycloak `<E2E_PREFIX>kc` on `E2E_KC_PORT` (8180) with a fresh dev realm on every start,
and runs the API with SSO (issuer `http://localhost:8180/realms/soundings`, groups and
`employee_no` claims) next to the dev login, so tests arrange data as Alice through the
API. Without `E2E_SSO` the API has the dev login and the break-glass admin
(`admin` / `e2e-break-glass-password`). QA ran it with `E2E_PREFIX=p2-qa-`.

**Modes.** Specs that need Keycloak are tagged `@sso` and skip themselves when
`GET /auth/config` says `sso: false` (the plain CI e2e jobs); BG-02 skips unless
break-glass is available (no SSO). Everything else runs in both modes, so both the plain
and the SSO run are complete for what they can test.

**Data.** Everything that changes data uses run-unique names (groups, projects, IdP
values like `/e2e/<run>/…`); Keycloak memberships are changed through
`e2e/scripts/keycloak.ts` and restored in `finally`. Some SSO specs need a **fresh seed
and realm** (identities link once; grace's E2001 and nia's address are unique): the local
stack gives both on start. Keep-stack reruns hit a reseed problem, see
[Known issues](#known-issues).

Keycloak users (dev realm, `dev/README.md`) and who uses them:

| User | Used by | Why |
|---|---|---|
| alice, bob, carol, erin | SA-* | the acceptance (their Keycloak groups are changed and restored there only) |
| dave | SA-02, AG-04, AD-05, SI-* | sign-ins that change nothing in Keycloak |
| grace | AU-04 | only her `employee_no` E2001 can match: pre-created by the admin |
| mallory | LE-01, AD-05 | unverified email naming seeded Farah: always refused |
| nia | LE-02, LE-03 | verified, no account; then pre-created and deactivated |
| kenji | LE-04 | no `employee_no` in Keycloak; given one in Soundings (removed afterwards) |

## Test cases

Status: ✅ passes, ❌ fails (a product bug, owner in brackets; see
[Known issues](#known-issues)). Rule-level tests by other owners are named where they
are the better place for a rule.

### SA: acceptance in the browser (`sso-acceptance.spec.ts`, @sso, serial)

| ID | Case | Status |
|---|---|---|
| SA-01 | The admin creates a managed group mapped to `/tools/members` in Settings → Groups (UI) and gives it Member in a private project's Members tab (UI, Group switch); three more groups and grants through the API (`/innovation/admins` → admin, `/innovation/members` → member, `/viewers` additive → viewer). Before any sign-in only the project's direct admin has access. | ✅ |
| SA-02 | alice, bob, carol, dave, erin sign in through Keycloak's form: each project is in the sidebar and opens, or answers "doesn't exist or you don't have access"; erin is a viewer (no New idea); alice (platform admin) is shown "via Innovation admins …". `list_project_access` for both projects equals the expected group-derived roles exactly. First sign-ins linked alice, bob, carol by `employee_no` and dave, erin by verified email (`user.identity_link.matched_by`). | ✅ |
| SA-03 | The mapping test with real synced memberships: dave without `/tools/members` → the managed tools group `remove`, Viewers `add`, the tools project gone from `project_roles`; erin with no groups claim → the additive group `keep` with empty `matched_values`. | ✅ |
| SA-04 | **The acceptance.** bob is removed from `/innovation/members` in Keycloak; his running session keeps the project (sync runs at sign-in only); he signs out (through Keycloak, `/login?signed_out=1`) and in again: the project is gone from the sidebar and answers 404, he left the group, `user.groups_sync` lists it in `removed_group_ids` with `claim_found: false` (no Keycloak groups → no claim). Put back in the group, his next sign-in restores the access. | ✅ |
| SA-05 | carol is also a manual member of the tools group; removed from `/tools/members` in Keycloak she stays a member (`manual: true, synced: false`) and keeps the project; the sync entry lists the group as removed (the flag cleared). | ✅ |
| SA-06 | erin, removed from `/viewers` in Keycloak, keeps her additive membership (`synced: true`) and her viewer role. | ✅ |

### AC2-API: acceptance through the API (`test_phase2_acceptance.py`)

| ID | Case | Status |
|---|---|---|
| AC2-API-01…02 | External ID set through `PUT /admin/users/{id}/external-ids`; groups, mappings and grants through `/admin/groups` and `/projects/{slug}/groups`; Carol's sign-in (next kept) links by external ID, shows the user's *stored* name (claims don't rename), syncs both groups, gives the private project with the group as source (access list and `AdminUser.project_roles`); the audit viewer returns `user.identity_link`, `session.sign_in` and `user.groups_sync` with the expected details and no email or claimed name. | ✅ |
| AC2-API-03 | The mapping test predicts `keep`/`remove` and the resulting roles without changing anything; the next real sign-in does exactly that. | ✅ |
| AC2-API-04 | Removed from the IdP group: the running session keeps access; after sign-out and sign-in, 404, gone from `list_projects` and the access list, `removed_group_ids` = the group. | ✅ |
| AC2-API-05 | No groups claim at all removes the remaining managed memberships (`claim_found: false`). | ✅ |
| AC2-API-06 | Offboarding: deactivating through `PATCH /admin/users` ends the session at once; the next SSO sign-in is `account_disabled`, audited with no actor and the user as target. | ✅ |
| AC2-API-07 | Additive mapping (changed with `PUT …/mapping`): the membership stays without the value; an admin removal takes it away at once; the next sign-in with the value brings it back. | ✅ |
| AC2-API-08…09 | A manual member (added with `POST …/members`) who is also synced keeps the manual membership and the group's admin role after sync clears `synced`. | ✅ |
| AC2-API-10 | A group-granted admin can manage the project's members; removed from the group by an admin, the next request is 404 (roles are evaluated live); `group.member_remove` records `manual`, `synced` and `auth_method`. | ✅ |

### SI: the SSO flow in the browser (`sso-sign-in.spec.ts`, @sso)

| ID | Case | Status |
|---|---|---|
| SI-01 | A deep link (`/p/customer-innovation?view=list`) → `/login?next=…` → Keycloak → back on that page. | ✅ |
| SI-02 | Unsafe `next` (`//evil.example/x`, `/api/v1/auth/me`, `https://evil.example/`) lands on My work. Unit-level: identity's `test_next_must_be_a_same_origin_spa_path`. | ✅ |
| SI-03 | After an SSO sign-in the browser holds only `soundings_session` (HttpOnly, SameSite=Lax) and `soundings_csrf`; the `soundings_oidc` cookie is gone; no JWT in any cookie, localStorage, sessionStorage or `/auth/me`. | ✅ |
| SI-04 | Sign out ends the Keycloak session too: the next "Sign in with SSO" asks for the password; `/auth/me` is 401. | ✅ |
| SI-05 | Multi-domain: from `http://127.0.0.1:8100` the authorization request carries `redirect_uri=http://127.0.0.1:8100/api/v1/auth/callback` and the user lands back on that host; the session is that host's only. (Local stack only: two base URLs.) Unconfigured hosts: identity's `test_an_unconfigured_host_goes_to_the_first_base_url_first`. | ✅ |

### LE / BG: sign-in errors and break-glass (`login-errors.spec.ts`)

Each refusal: `/login?error=<code>`, one calm sentence (never the code or IdP text), the
SSO button again, `GET /auth/me` 401, a `session.sign_in_denied` entry with no actor.

| ID | Case | Status |
|---|---|---|
| LE-01 | mallory (unverified email that names seeded Farah) → `no_account`; `next=/work` kept in the URL and on the SSO link; audit reason `email_not_verified`, no actor, no target, no address; Farah not linked. | ✅ |
| LE-02 | nia (verified, no account, auto-create off) → `no_account`, reason `no_match`; nobody created. | ✅ |
| LE-03 | nia pre-created and deactivated → `account_disabled` (target: her account); reactivated, she signs in and is linked by verified email. | ✅ |
| LE-04 | kenji has an external ID in Soundings but none in his token → `identity_conflict` (reason `external_id_missing`): never linked by email alone. | ✅ |
| LE-05 | Keycloak answers `error=access_denied` to a real attempt → `login_cancelled` (a calm status, not an alert); audited. | ✅ |
| LE-06 | A real attempt answered with a bogus code and an HTML `error_description` → `sso_failed`; the IdP text is never shown. | ✅ |
| LE-07 | A forged callback → `login_expired`; a real attempt answered twice → the second is `login_expired` (single use). | ✅ |
| LE-08 | An unknown `error` value (`<script>…`) → a generic message; the value is never echoed. (Both modes.) | ✅ |
| BG-01 | With SSO configured: `auth/config.break_glass` false, no break-glass form, `POST /auth/break-glass` 404 even with the configured credentials. (@sso) | ✅ |
| BG-02 | Without SSO: a wrong password → "That username and password don't match" (audited: no actor, no username, no password); the right one → the "Signed in with the break-glass account" banner, "Break-glass admin" account, `session.sign_in {method: break_glass}`; the banner's Sign out → `/login?signed_out=1`. Throttle (5 failures → 429 + `Retry-After`) is identity's `test_five_failures_then_429_without_checking_credentials` (not run in e2e: it would lock the stack's break-glass for 15 minutes). | ✅ (no-SSO run) |

### AU: Admin settings → Users (`admin-users.spec.ts`)

| ID | Case | Status |
|---|---|---|
| AU-01 | List, search (`?q=`), Platform admins filter (`?admins=1`), settings section row. | ✅ |
| AU-02 | Deactivate from the sheet (confirm, "signed out everywhere"): the person's live session is 401 at once and dev login refuses them; reactivate lets them back. | ✅ |
| AU-03 | c17 in the UI: your own Platform admin switch is disabled, no Deactivate; a non-admin gets the plain 404 page and the API 403, and sees no section row. | ✅ |
| AU-04 | Pre-create Grace in "Add user" (employee_no suggested as the kind, value typed in lower case); her first Keycloak sign-in links the pre-created account (`matched_by: external_id`, Keycloak issuer) under its own name, and the seeded "Tools team" (→ `/tools/members`) gives her Internal Tools; the sheet shows the linked account, "Tools team · Synced" and "via Tools team"; Unlink ends her SSO session (401, back to /login) and her next sign-in links again. (@sso) | ✅ |

Rule-level: backend's `tests/admin/test_admin_users.py` (409s, c18, system accounts,
external-ID replace), identity's `tests/authz/test_group_roles.py` (c18 concurrency).

### AG: Admin settings → Groups and project roles via groups (`admin-groups.spec.ts`)

| ID | Case | Status |
|---|---|---|
| AG-01 | New group with ` /Leadership/<RUN>/Board/ ` → previewed and stored as `leadership/<run>/board`, additive; then a second value and managed, saved once (`group.mapping_replace` with `from_sync_mode`); the list shows "Managed:" and the value. | ✅ |
| AG-02 | "Test mapping" (Groups list sheet): invalid JSON message; claims with a mixed-case full path, an unmapped value, `42` and `/` → "Found 2 values", "2 entries were ignored", only this group "Joins", the granted project under "Project roles after signing in"; nothing stored or audited. | ✅ |
| AG-03 | Add Kenji by hand (Manual badge), remove with Undo; give the group Viewer in a project's Members tab; "Everyone with access" shows "via <group>"; Kenji (dev login) sees the project, and gets 404 once removed from the group. | ✅ |
| AG-04 | dave signs in with Keycloak into a managed and an additive group on `/tools/members`; his synced row has no Remove button; the group page's test box for Dave without `/tools/members` says Leaves (managed, "This group") and Stays (additive). (@sso) | ✅ |

Rule-level: identity's `tests/identity/test_group_sync.py` (every cell of the sync table,
both modes), `test_claims.py` (extraction, normalisation, overage),
`test_mapping_preview.py`; backend's `tests/admin/test_admin_groups.py`,
`test_project_groups.py` (c11 with group admins).

### AD: audit log (`audit.spec.ts`)

| ID | Case | Status |
|---|---|---|
| AD-01 | A dev-login sign-in appears for the person ("Bob Brown signed in with the development login", Who filter in the URL). | ✅ |
| AD-02 | Admin changes on a group (create with mapping, rename, member add, mapping change, project grant) appear as sentences with the member's name resolved, under "About · <group>"; Details shows the raw fields; every entry has `auth_method: dev_login`. | ✅ |
| AD-03 | SPEC's list in a project: owner assignment, status change, evaluator invitation, evaluation submit, by the right actors; no emails in the entries. | ✅ |
| AD-04 | Non-admins: API 403, page 404. | ✅ |
| AD-05 | An SSO sign-in ("Dave Davies signed in with SSO…") and a denied one ("An SSO sign-in was denied: the email isn't verified") appear; the Denied filter shows no sign-ins. (@sso) | ✅ |

Rule-level: backend's `tests/admin/test_audit_viewer.py` (filters, cursor, resolution),
identity's `test_nothing_personal_reaches_the_audit_log_or_logs`.

### A11Y2 / MO2: accessibility and phones (`a11y-phase2.spec.ts`)

axe (WCAG 2.2 AA rules; bar: zero serious/critical) in light and dark on: login with an
error, login after signing out, Users, user detail sheet, Add user (with inline errors),
Groups, group detail with a test-mapping result, Sign-in (SSO), Audit log with Details
open, project Members with groups (Group switch on) — 10 screens × 2 themes. MO2-01: the
same screens at 390 px have no sideways scrolling.

| ID | Case | Status |
|---|---|---|
| A11Y2-light | All screens, light | ✅ |
| A11Y2-dark | All screens, dark | ✅ |
| MO2-01 | All screens at 390 px | ✅ |

### P1: the Phase 1 suite in both modes

All Phase 1 specs (dev login) pass with SSO on and off. Two test-side changes: KB-11
types "sign out" instead of "sign", because platform admins now also have "Sign-in (SSO)"
in the palette (a new admin command, not a regression); and `switchUserInUi` waits for
the app shell before signing out (it raced a page still loading and went to /login while
signed in, which bounced back to My work: AC-01…07 failed once in the SSO run).

| Run (fresh stack, 2026-10-01) | Result |
|---|---|
| `E2E_SSO=1 npm --prefix e2e test` | 124 passed, 1 skipped (BG-02: needs SSO off) |
| `npm --prefix e2e test` (no SSO, break-glass on) | 103 passed, 22 skipped (the @sso specs) |
| `cd backend && uv run pytest tests/acceptance` | 4 passed (2 Phase 1, 2 Phase 2) |

### SS: screenshots

`e2e/screenshots/phase-2.spec.ts` (`npm --prefix e2e run screenshots:phase2`): 12
screens × (1440 light, 1440 dark, 390 light) = 36 PNGs in `docs/screenshots/phase-2/`,
from the real app after real Keycloak sign-ins (alice, bob, carol, dave, erin linked and
synced; mallory and nia refused). Alice signs in once (through Keycloak) and every shot
reuses her cookies, so the audit log shows that story. Screens: `login-sso`,
`login-error`, `login-break-glass` (second run, SSO off), `settings-users`,
`settings-user-detail`, `settings-user-sign-in` (linked account, external IDs,
sessions), `settings-add-user`, `settings-groups`, `settings-group-detail` (Tools team
with a test-mapping result for Carol), `settings-sso`, `settings-audit`,
`project-members-groups` (group grant and everyone with access). The frontend's mock
screenshots stay in `docs/screenshots/phase-2/mock/`.

## Known issues

No product failures: every acceptance and rule test above passes against the real stack.
Every issue below was fixed during integration (2026-10-01) except the two noted as by design.

| ID | Owner | Issue | Reproduce |
|---|---|---|---|
| K-1 | platform (`e2e/scripts/start-stack.sh`, `reseed.sh`) | A kept stack can't be reseeded once a run created people who aren't demo people (AU-02, AU-04, LE-03 do): `soundings seed --reset` refuses without `--force`, and the failure is swallowed (`quietly … \| grep … \|\| true` calls `die` in a pipeline subshell), so the run carries on with stale data and "reseeded" in the log; the realm *is* reset. SSO specs that need a fresh seed then fail (AU-04: 409 `external_id_taken` for E2001). Fresh starts (default, CI) are unaffected. Fix: `seed --reset --force` (the e2e database is disposable, on tmpfs) and fail when it fails. **Fixed in integration** (`stack-env.sh: seed_demo_data`): a kept SSO stack reran 124 passed / 1 skipped; a failing seed now stops the start. | `E2E_SSO=1 E2E_KEEP_STACK=1 npm --prefix e2e test` twice: the second start prints "Refusing to --reset …", "error: failed: uv run --quiet soundings seed --reset", then "reseeded, not restarted". |

## Screenshot review (2026-10-01)

All 36 read one by one (real app, Keycloak sign-ins). Nothing is broken; polish items:

| Screen | Problem | Owner |
|---|---|---|
| settings-add-user-390, settings-user-sign-in-390 | The external-ID Kind field is too narrow on a phone: "employee_no" is clipped. **Fixed in integration:** Kind and ID share the row equally. | frontend-admin |
| settings-*-390 | The settings section row scrolls sideways with no cue: "Audit log" is cut to "Audit l…" at the edge. **Fixed in integration:** on phones the tab reads "SSO" (same accessible name) and the row fits. | frontend-admin |
| settings-sso (all) | "Client secret: Set (from the Kubernetes Secret)" also when it comes from an environment variable (dev, e2e, compose). "Set" alone, or "from the deployment's secret", would be true everywhere. **Fixed in integration:** "Set (never shown)". | frontend-admin |
| settings-audit (all) | "Sign-in sync for Erin Evans: joined Viewers" when Erin was already a manual member: the sync only marked the membership as synced (`added_group_ids` per §3.6). "now synced: Viewers" would be exact. **Fixed in integration:** "now a synced member of Viewers" / "no longer a synced member of …". | frontend-admin |
| settings-user-detail, settings-user-sign-in | The sheet opens with a focus ring on its Close button (initial focus). Expected for keyboard use; noted only because it is the first thing the eye lands on. | frontend (design system) |
| login-sso, login-error | The SSO button carries its focus ring on arrival (focused on purpose so Enter signs in). By design. | — |
