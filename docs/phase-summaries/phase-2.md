# Phase 2 summary: sign-in and access

**Status:** closed on 2026-10-01, waiting for the product owner's review before Phase 3.
**Scope (SPEC sections 7 and 13):** OIDC sign-in (server-side code flow with PKCE,
HttpOnly session cookie, CSRF, no IdP tokens in the browser, redirect URIs per host),
users with external IDs and pre-created users, login matching, internal groups mapped to
IdP group values (managed or additive), manual memberships that sync never touches, the
"test mapping" box, project roles via groups, the break-glass admin, one central
authorisation module with table-driven tests, and the audit log with an admin viewer.
**Acceptance:** Keycloak users get the right project access from their groups; removing
a group removes access at next sign-in (managed mapping). Met: see
[Acceptance evidence](#acceptance-evidence).

Commits: `e536ae9` (contract), `2903409` (build and integration), `ace0b5e` (review
fixes), plus this close-out (lead decisions L3, L6, M3; final verification; docs).

## What was built

| Area | What | Where |
|---|---|---|
| Contract | 30 new operations (sign-in, admin users, groups, mappings, audit, SSO view, project group grants and access list), stable problem codes, `/login?error=` codes, `AuditAction` | [contract-phase2.md](../api/contract-phase2.md), `backend/app/schemas/`, `frontend/src/api/generated/` |
| SSO sign-in | Authorization code flow with PKCE (S256), `state`, `nonce`, RFC 9207 `iss` check; the attempt sealed (AES-256-GCM) into the HttpOnly `soundings_oidc` cookie, nothing stored until the callback; ID token validated with the provider's keys (refetched hourly), claims from the ID token only; redirect URIs from the configured host (multi-domain); RP-initiated sign-out with a sealed `id_token_hint`; "Use a different account" (`prompt=select_account` + `max_age=0`) | `app/auth/oidc.py`, `login_attempt.py`, `sealing.py`, `api/v1/auth_sso.py`, [ADR 0005](../adr/0005-server-side-sessions-oidc-csrf.md) |
| Login matching | (issuer, subject) → external-ID claim → verified email (if on) → auto-create (if on) → deny; ineligible or conflicting matches deny instead of falling through; one identity per user per issuer | `app/auth/login_matching.py` |
| Groups and sync | Internal groups mapped to normalised IdP values (Keycloak "/path" with or without the slash, configurable claim path); managed (adds and removes) vs additive (adds only); one membership row with `manual` / `synced` flags, so sync never touches manual memberships; Entra ID overage refused; the mapping test predicts the next sign-in | `app/auth/group_mapping.py`, `group_sync.py`, `api/v1/admin_groups.py` |
| Project roles via groups | Group grants per project; the effective role is the highest of direct and group roles (`project_effective_roles` view); "Everyone with access" explains each role's source | `app/authz/`, `api/v1/project_groups.py`, migration 0003 |
| Break-glass admin | From a K8s Secret, only while SSO is not configured; its sessions end when SSO is configured and last 8 h (1 h idle); throttled per client IP with `Retry-After`; every use and every action in its sessions audited | `app/auth/break_glass.py`, chart `breakGlass.*` |
| Sessions and cookies | Every method creates the same server-side session with its `auth_method`, valid only while that method is available; 24 h max, 12 h idle; `__Host-` cookie names when Secure (Phase 1 item F10) | `app/services/sessions.py`, `app/auth/cookies.py` |
| Client address | `X-Forwarded-For` only from trusted proxies and only `trustedProxyHops` entries from the right; the chart's NetworkPolicy is on by default | `app/middleware.py`, `deploy/helm/` |
| Audit log | Sign-ins and denials (no actor), user, group, mapping, membership, grant and project changes, owner and evaluator assignments, evaluation submit / close / reopen, status changes, idea deletion; ids only, never emails, tokens or claims; viewer with filters, cursor paging and per-entry details | `app/services/audit.py`, `audit_viewer.py`, `api/v1/admin_audit.py` |
| Admin screens | Settings → Users (list, add, user sheet with access, groups, linked account, external IDs, sessions), Groups (list, group page, Test mapping sheet), Sign-in (SSO) (effective config read-only, secrets masked, redirect URIs to copy, discovery status, setup checklist without SSO), Audit log; project Members with Groups, People and Everyone with access; sign-in page with SSO, break-glass and dev login | `frontend/src/features/admin/`, `features/auth/`, `features/project/settings/` |
| Platform | Keycloak 26 dev realm (users, groups with full paths, `employee_no`), Helm `oidc.*` / `breakGlass.*` values with schema, Keycloak in k3s (`make k3s-keycloak`), `make sso-smoke`, CI SSO jobs | `dev/keycloak/`, `deploy/helm/`, `scripts/` |
| Tests | Backend 3,342 (incl. 9 against a real Keycloak 26 container), frontend 296 unit + 172 page tests, e2e 103 (dev login) / 125 (SSO) against the real stack | `backend/tests/`, `frontend/`, `e2e/tests/` |
| Docs | Contract, ERD, role matrix, ADR 0005 amendment, decisions, user guide (signing in, members and groups, platform administration), operator guide (Keycloak, Entra ID, Google, login matching, mappings, break-glass, NetworkPolicy and proxies), test plan | `docs/` |

## Acceptance evidence

All run on 2026-10-01 in the final verification, on the working tree that was committed.

| Criterion | Evidence (test names) |
|---|---|
| **Keycloak users get the right project access from their groups; removing a group removes access at next sign-in (managed)**, in the browser | `e2e/tests/sso-acceptance.spec.ts` SA-01…06 against Keycloak 26: groups mapped in the UI and API; alice, bob, carol, dave and erin sign in through Keycloak's form and get exactly the expected roles (`list_project_access` compared whole); SA-04: bob removed from `/innovation/members` in Keycloak keeps access in his running session, signs out and in again and gets 404 for the project, restored when put back; SA-05 manual and SA-06 additive memberships survive |
| The same through the HTTP API | `backend/tests/acceptance/test_phase2_acceptance.py::test_managed_group_gives_and_takes_project_access_at_sign_in`, `::test_additive_and_manual_memberships_and_a_group_granted_admin_role` (AC2-API-01…10) |
| The same against a real Keycloak token | `backend/tests/identity/test_keycloak.py::test_acceptance_removing_the_idp_group_removes_access_at_next_sign_in`, `::test_acceptance_additive_mapping_keeps_the_membership`, `::test_acceptance_manual_membership_survives_sync`, `::test_full_group_paths_match_mappings_typed_without_the_slash` |
| The same on Kubernetes | k3s v1.31, Restricted PSS, Keycloak in the cluster: `make k3s-smoke SSO=1` (`scripts/sso-smoke.sh`): alice's code flow + PKCE through the ingress, carol a member through a managed group, removed from `/tools/members` in Keycloak → 404 at her next sign-in, sign-out at Keycloak, mallory refused |
| Code flow, PKCE, cookies, CSRF, no tokens in the browser | `tests/identity/test_sso_flow.py::test_login_redirects_to_the_idp_with_pkce`, `::test_starting_sign_ins_stores_nothing_and_locks_no_one_out`, `::test_a_forged_or_changed_attempt_cookie_is_refused`, `::test_a_callback_url_works_only_once`, `::test_invalid_id_tokens_are_refused`; `tests/auth/test_session_methods.py`; e2e SI-01…05 (SI-03: no IdP token in storage, HttpOnly session cookie) |
| Redirect URIs per host, several domains | `test_sso_flow.py::test_each_configured_host_signs_in_on_itself`, `::test_an_unconfigured_host_goes_to_the_first_base_url_first`, `::test_an_unconfigured_host_keeps_the_prompt`; e2e SI-05 |
| Login matching (tests first) | `tests/identity/test_login_matching.py::test_login_matching` (table of every step and denial), `::test_concurrent_first_sign_in_links_once`, `::test_external_id_is_matched_case_insensitively`; `test_keycloak.py::test_pre_created_user_links_by_external_id`, `::test_external_id_mismatch_needs_an_admin`; e2e LE-01…04, AU-04 |
| Groups, claim path, managed vs additive, manual untouched (tests first) | `tests/identity/test_claims.py` (16), `test_group_sync.py::test_sync_table`, `::test_missing_claim_removes_managed_synced_memberships`, `::test_manual_membership_keeps_access_when_the_idp_group_goes`, `::test_subgroups_do_not_inherit_a_parent_mapping` |
| Test mapping | `tests/identity/test_mapping_preview.py::test_preview_matches_what_sign_in_does`; e2e SA-03, AG-* |
| Break-glass, off once SSO is configured, every use audited (tests first) | `tests/identity/test_break_glass.py` (15, e.g. `::test_break_glass_session_ends_once_sso_is_configured`, `::test_five_failures_then_429_without_checking_credentials`); `tests/test_proxy_headers.py::test_a_client_behind_the_ingress_cannot_dodge_the_break_glass_throttle`; e2e BG-01, BG-02 |
| One authorisation module, table-driven tests (tests first) | `tests/authz/test_policy_matrix.py` (`::test_matrix_matches_the_role_matrix_document`, `::test_cell`, `::test_condition`), `test_policy_rules.py`, `test_route_rules.py` (the rule of every operation), `test_group_roles.py` |
| Audit log and viewer | `tests/admin/test_audit_viewer.py` (`::test_the_closed_set_is_exactly_the_contract_enum`, `::test_entries_written_by_the_api_record_the_session_method`), `tests/ideas/test_evaluations.py::test_close_and_reopen_are_audited_once_each`; e2e AD-01…05 |
| Final-verification decisions | `test_session_methods.py::test_sessions_last_at_most_a_day_by_default` (L3); `test_sso_flow.py::test_prompt_is_passed_to_the_idp`, `::test_any_other_prompt_is_a_422` and e2e LE-09 against Keycloak (M3); the audit test above (L6) |

### Checks (final verification, 2026-10-01)

| Check | Result |
|---|---|
| `make -C backend check` | pass: ruff, ruff format, mypy --strict (194 files), pytest 3,342 passed, 1 skipped (empty stub list), 1 deselected (slow); the 9 real-Keycloak tests ran |
| `make -C backend test-slow` | pass (10k-idea performance) |
| `npm --prefix frontend run check` | pass: tsc, eslint + prettier, vitest 41 files / 296 tests, build |
| `npm --prefix frontend run test:pw` | pass: 172 passed, 74 skipped (screenshot specs; they pass with `SCREENSHOTS=1`) |
| `npm --prefix e2e test` (dev login, break-glass on) | pass: 103 passed, 23 skipped (`@sso`) |
| `E2E_SSO=1 npm --prefix e2e test` | pass: 125 passed, 1 skipped (BG-02 needs SSO off) |
| `npm --prefix e2e run check`, `make check-helm`, `make check-scripts` | pass (shellcheck 0.11 through its container: clean) |
| `make gen-api` | no diff |
| k3s | `make image` (sandbox: `RUNTIME_APT_PACKAGES=`), `k3s-up`, `k3s-keycloak`, `k3s-install SSO=1` (NetworkPolicy on by default), `k3s-smoke SSO=1` and `k3s-smoke`, `helm upgrade` with changed values (`logLevel`, `networkPolicy.ingressFrom` = kube-system: pods rolled, API reachable only through Traefik and the release's pods, Postgres only from the release) → `k3s-smoke SSO=1` three times, `k3s-down` |

## Review findings and outcomes

Two reviews ran after the build: `code-reviewer` (code, security, OWASP ASVS L2) and
`ux-reviewer` (Linear-grade UX, WCAG 2.2 AA). Backend fixes were test-first (a failing
test before each fix); frontend fixes came with unit and page tests and the e2e specs
they touch.

### Code and security

| # | Finding | Outcome | Tests |
|---|---|---|---|
| H1 (high) | A global cap of 10,000 live sign-in attempts let anyone lock everyone out of SSO | Fixed at the root: sign-in starts are stateless (sealed `soundings_oidc` cookie); table and cap gone (migration 0004) | `test_starting_sign_ins_stores_nothing_and_locks_no_one_out`, `test_a_forged_or_changed_attempt_cookie_is_refused` (6), `test_a_very_long_next_still_fits_in_the_cookie`, `test_0004_stateless_sign_in_drops_attempts_and_plain_id_tokens` |
| M1 | A spoofed `X-Forwarded-For` gave a fresh throttle key per request | Fixed: the app resolves the client itself (trusted proxies, `trustedProxyHops`); NetworkPolicy on by default; verified on k3s | `tests/test_proxy_headers.py` (19-row table, middleware, break-glass flood) |
| L1 | Signing keys cached forever | Fixed: refetched hourly | `test_signing_keys_are_refreshed_hourly` |
| L2 | Traces recorded `code` and `state` | Fixed: query values redacted | `test_spans_never_carry_query_values` |
| L3 | IdP removal took up to 7 days to apply | **Lead decision:** sessions last 24 h (12 h idle) by default | `test_sessions_last_at_most_a_day_by_default`, `test_sessions.py` |
| L4 | ID token stored in plain text | Fixed: sealed at rest | `test_the_id_token_is_sealed_at_rest`, `test_a_legacy_plaintext_id_token_is_not_sent` |
| L5 | IdP endpoints could be http in production | Fixed: discovery `invalid` | `test_production_needs_https_idp_endpoints` (4) |
| L6 | Close/reopen evaluation not audited | **Lead decision, fixed:** `evaluation.close` / `evaluation.reopen` (backend, SPA phrases, category, mock) | `test_close_and_reopen_are_audited_once_each`, `audit-phrases.test.ts` |
| N1 | Dot segments passed the `next` check | Fixed on both sides | `test_next_must_be_a_same_origin_spa_path` (+10), `session.test.ts` |
| N2 | `.invalid.` (trailing dot) beat the reserved-email check | Fixed | `test_reserved_invalid_addresses_are_refused`, `test_email_claim` |
| N3 | c18 counts admins who never signed in | Kept (decisions.md): the acting admin always remains; requiring an identity would block the break-glass setup | — |
| N4 | Group members visible to project admins | Accepted in the contract (directory data) | — |

### UX and accessibility

| # | Finding | Outcome |
|---|---|---|
| M1 | Focus lost when closing the user sheet or leaving a group page | Fixed: focus returns to the row (`lib/return-to-row.ts`) |
| M2 | The user sheet opened with its Name field selected | Fixed: sheets open focused on themselves |
| M3 | No way to sign in with another account after `no_account` | **Lead decision, fixed:** "Use a different account" (`prompt=select_account`; the server adds `max_age=0` because Keycloak ignores `select_account`); e2e LE-09 |
| M4 | Group page too tall, test box in the middle | Fixed: Members first; Test mapping is a sheet |
| M5 | Three headers on every admin page | Fixed: one short line each |
| M6 | Members listed twice on project Members | Fixed with the reviewer's second option: Groups first, "Everyone with access" folded |
| m1–m8 | Break-glass landing, setup checklist without SSO, "Break-glass attempt" label, "SSO not linked" chip, help copy, invalid-JSON focus, toasts above sheet footers, When filter presets | Fixed (m8: "Today" instead of "24 h", since the filter works in days) |
| p1–p8 | Quiet SSO focus ring, `ButtonShortcut`, one-line phone cards, no wrapping in pickers, `PasswordInput`, one column, group links on Members, placeholder | Fixed; p7 partly (showing a group's mapping on Members needs a contract change, deferred) |

The integration before the reviews fixed QA's K-1 (a kept e2e stack swallowed a failed
reseed) and four screenshot polish items ([test plan](../test-plans/phase-2.md#screenshot-review-2026-10-01)).

### Final verification (this close-out)

- **Lead decisions L3, L6, M3** implemented test-first (above); contract changes are
  additive (`LoginPrompt`, the `prompt` parameter, two `AuditAction` values) and recorded
  in [contract-phase2.md §7](../api/contract-phase2.md#7-changes-after-the-contract).
- **Keycloak ignores `prompt=select_account`** (found by the new e2e LE-09): the server
  now also sends `max_age=0`, which makes Keycloak ask to re-authenticate, with "Restart
  login" to switch account.
- **k3s with NetworkPolicy on:** `helm test` failed now and then once `ingressFrom` was
  set, because k3s's policy controller admits a new pod's address a moment after it
  starts; the test pod now retries for up to 30 s (`templates/tests/test-connection.yaml`).
- **Smoke flake:** through Traefik, a chunked 2 MiB POST got 502 instead of 413 about half
  the time (the app stops reading and closes; Traefik sees a reset). The smoke accepts 502
  there and checks the app's own 413 inside the pod (`scripts/k3s-smoke.sh`).
- **Phone cards:** a wrapped inline meta line started with "·"; the separator now trails
  the previous value (`components/ui/table.tsx`).
- Docs: this summary, contract §1, §3.2, §3.9, §3.11, §5, §7, ERD (no attempts table),
  ADR 0005 amendment, decisions, user and operator guides, Helm values/README/schema,
  test plan (LE-09, counts, screenshots), CLAUDE.md.

## Known issues and deferred items

| Item | Why / when |
|---|---|
| Showing a group's mapping on project Members (review p7) | Needs `sync_mode` and `idp_values` on `ProjectGroupGrant.group` (additive contract change); the group name links to the group page for platform admins meanwhile. |
| Keycloak's "Use a different account" page shows the previous username first; the person clicks "Restart login" | Keycloak 26 ignores `select_account`; `max_age=0` is the portable fallback. Entra ID and Google show their account picker. The ID token's `auth_time` is not checked. |
| `networkPolicy.ingressFrom` is empty by default (any pod can reach the API) | The ingress controller's namespace differs per cluster; the NOTES and operator guide ask operators to set it. |
| Through Traefik, a chunked body over 1 MiB can get 502 instead of 413 | Refused either way; the app answers 413 (checked in the pod). A bounded drain before answering would fix it at the cost of reading up to a few MiB per such request. |
| Sign-in throttles are per process | With several API replicas the limits multiply (contract §6). |
| No back-channel logout or SCIM; Entra ID group overage is refused, not resolved through Graph | Out of scope (contract §6); offboarding = deactivate. |
| The audit log is kept indefinitely, with no export | A retention setting can come later if needed. |
| Optional cleanups left: `project-filters.tsx` onto the shared `FilterMenu`; Kofi, Lena and break-glass ids in `frontend/tests/support.ts` `USERS` | Not defects. |
| Image builds here skip the runtime apt packages (no Debian mirror); the GitLab pipeline was not run in this sandbox | Sandbox only. |
| `docs/research/backend-libraries.md` still describes Authlib | Research record; ADR 0005's amendment says what was built. |

## Simplifications proposed (SPEC section 15, item 3)

Each avoided a settings screen or a moving part; all are in [decisions.md](../decisions.md).

1. **One IdP per instance, configured with the deployment**; the SSO page is read-only
   (effective values, masked secrets, URIs to copy). No SSO editing screen.
2. **Fixed texts instead of settings:** "Sign in with SSO", display name from `name` →
   `preferred_username` → email; the external-ID kind defaults to the claim's name.
3. **Sync only at sign-in** (no background sync, SCIM or Graph calls); mapping changes
   apply at the next sign-in, and "remove member" or deactivation act at once.
4. **Stateless sign-in:** the attempt rides in a sealed cookie, so there is no table, no
   sweeper and no cap to tune.
5. **Break-glass only while SSO is off**; in an outage the operator unsets the issuer.
6. **One membership row with `manual` / `synced` flags** instead of separate tables or
   per-member sync settings.
7. **Admin pages are tabs of Settings**, not a separate admin area.
8. **24-hour sessions for every method** instead of per-method lifetimes (break-glass
   excepted).

Questions for the product owner: keep project Members as three lists (Groups, People,
Everyone with access) rather than one merged list? Show each group's IdP mapping on
project Members (needs the p7 contract change)?

## Screenshot index

Real app, freshly seeded demo data, real Keycloak sign-ins (`npm --prefix e2e run
screenshots:phase2`; the break-glass login from a second run with SSO off); 1440 × 900
light and dark, 390 × 844 light. All 39 were read; after the last fix (phone card
separators) the set was captured again and the Users and Groups shots read again. The
frontend's mock set is in [`mock/`](../screenshots/phase-2/mock/).

| Screen | Light | Dark | Phone |
|---|---|---|---|
| Sign in (SSO and dev login) | [1440](../screenshots/phase-2/login-sso-1440-light.png) | [1440](../screenshots/phase-2/login-sso-1440-dark.png) | [390](../screenshots/phase-2/login-sso-390-light.png) |
| Sign in after `no_account` ("Use a different account") | [1440](../screenshots/phase-2/login-error-1440-light.png) | [1440](../screenshots/phase-2/login-error-1440-dark.png) | [390](../screenshots/phase-2/login-error-390-light.png) |
| Sign in: break-glass admin (SSO off) | [1440](../screenshots/phase-2/login-break-glass-1440-light.png) | [1440](../screenshots/phase-2/login-break-glass-1440-dark.png) | [390](../screenshots/phase-2/login-break-glass-390-light.png) |
| Settings → Users | [1440](../screenshots/phase-2/settings-users-1440-light.png) | [1440](../screenshots/phase-2/settings-users-1440-dark.png) | [390](../screenshots/phase-2/settings-users-390-light.png) |
| User sheet: profile, access, groups | [1440](../screenshots/phase-2/settings-user-detail-1440-light.png) | [1440](../screenshots/phase-2/settings-user-detail-1440-dark.png) | [390](../screenshots/phase-2/settings-user-detail-390-light.png) |
| User sheet: linked account, external IDs, sessions | [1440](../screenshots/phase-2/settings-user-sign-in-1440-light.png) | [1440](../screenshots/phase-2/settings-user-sign-in-1440-dark.png) | [390](../screenshots/phase-2/settings-user-sign-in-390-light.png) |
| Add user (pre-created, external ID) | [1440](../screenshots/phase-2/settings-add-user-1440-light.png) | [1440](../screenshots/phase-2/settings-add-user-1440-dark.png) | [390](../screenshots/phase-2/settings-add-user-390-light.png) |
| Settings → Groups | [1440](../screenshots/phase-2/settings-groups-1440-light.png) | [1440](../screenshots/phase-2/settings-groups-1440-dark.png) | [390](../screenshots/phase-2/settings-groups-390-light.png) |
| Group page (members first) | [1440](../screenshots/phase-2/settings-group-detail-1440-light.png) | [1440](../screenshots/phase-2/settings-group-detail-1440-dark.png) | [390](../screenshots/phase-2/settings-group-detail-390-light.png) |
| Test mapping (Carol leaves the managed Tools team) | [1440](../screenshots/phase-2/settings-test-mapping-1440-light.png) | [1440](../screenshots/phase-2/settings-test-mapping-1440-dark.png) | [390](../screenshots/phase-2/settings-test-mapping-390-light.png) |
| Settings → Sign-in (SSO) | [1440](../screenshots/phase-2/settings-sso-1440-light.png) | [1440](../screenshots/phase-2/settings-sso-1440-dark.png) | [390](../screenshots/phase-2/settings-sso-390-light.png) |
| Settings → Audit log | [1440](../screenshots/phase-2/settings-audit-1440-light.png) | [1440](../screenshots/phase-2/settings-audit-1440-dark.png) | [390](../screenshots/phase-2/settings-audit-390-light.png) |
| Project Members: groups, people, everyone with access | [1440](../screenshots/phase-2/project-members-groups-1440-light.png) | [1440](../screenshots/phase-2/project-members-groups-1440-dark.png) | [390](../screenshots/phase-2/project-members-groups-390-light.png) |
