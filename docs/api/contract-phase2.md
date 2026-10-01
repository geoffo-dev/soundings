# API contract: Phase 2 (sign-in and access)

The REST contract for Phase 2 (SPEC sections 7 and 13): OIDC sign-in, users with
external IDs, pre-created users, groups mapped to IdP groups, project roles via groups,
the break-glass admin and the audit log viewer. It extends
[contract-phase1.md](contract-phase1.md), whose conventions (section 1) all still
apply. Source of truth, in order: the Pydantic schemas in `backend/app/schemas/`
(`auth`, `admin_users`, `groups`, `audit`, `sso`) and the route stubs in
`backend/app/api/v1/` (`auth_sso`, `admin_users`, `admin_groups`, `admin_audit`,
`admin_sso`, `groups`, `project_groups`), exported to
`frontend/src/api/generated/openapi.json` / `schema.d.ts` (`make gen-api`). Rules are
named as in [role-matrix.md](../role-matrix.md); tables in [erd.md](../erd.md);
sessions and CSRF in [ADR 0005](../adr/0005-server-side-sessions-oidc-csrf.md).

`backend/tests/test_contract_routes.py` pins every method, path and `operation_id`
(`CONTRACT`) and keeps a valid request per unimplemented route (`STUBS`, answered with
501 `not_implemented`): delete a stub row when you implement its endpoint.
`tests/authz/test_route_rules.py` names the rule of every operation.

**Who builds what (suggested):** identity: sections 3.1–3.3, 3.5, 3.6, 3.8, 3.9, 3.12
(sign-in, matching, claim extraction, sync, break-glass, sessions and cookies, the
mapping test) and the rule changes in `app/authz`; backend: 3.4, 3.7, 3.10, 3.11 (admin
users and groups CRUD, group grants and access lists, the SSO view, the audit viewer);
frontend: the sign-in page, account menu sign-out, Admin settings (Users, Groups, SSO,
Audit log) and the project Members tab; qa: section 3.13 as e2e against Keycloak.

## 1. Conventions (new in Phase 2)

| Topic | Rule |
|---|---|
| Sessions | Every sign-in method (SSO, break-glass, dev login) creates the same Phase 1 server-side session through `app.services.sessions.start_session`, which always rotates. The session row records `auth_method` (`sso`, `break_glass`, `dev_login`) and, for SSO, the ID token (only as `id_token_hint` for sign-out, and only up to 3,072 characters, §3.9). A session works only while its method is available (§3.9). |
| Cookies | Unchanged names over plain HTTP (development): `soundings_session`, `soundings_csrf`, plus the short-lived `soundings_oidc`. **When cookies are `Secure`** (production, any HTTPS request; `app.auth.cookies.cookie_secure`) they are named `__Host-soundings_session`, `__Host-soundings_csrf` and `__Host-soundings_oidc`, all `Path=/`. The server reads only the variant matching `cookie_secure(request)`; the SPA reads the CSRF cookie as `__Host-soundings_csrf` first, then `soundings_csrf`. This closes the Phase 1 review item F10 (cookie tossing from a sibling subdomain). |
| Browser navigations | `GET /auth/login` and `GET /auth/callback` are top-level navigations, and `POST /auth/logout/redirect` is a plain HTML form post: never `fetch` them. They answer with redirects (302/303, `Location`), never JSON. Overlong or unexpected parameter values (a long IdP `error_description` or `code`, a `next` over 2048 characters) are handled by the flow as described below, never a 422; only a NUL character (`%00`, possible only in a crafted URL) is a 422. |
| Public routes | No session needed: `get_auth_config`, `sso_login`, `sso_callback`, `break_glass_login`, `logout_redirect` (plus Phase 1's `list_dev_users`, `dev_login`, `logout`). Everything else is 401 without a session. |
| Admin routes | `/admin/*` need a session of a platform admin. Check order: 401 → 422 `validation_error` (shape) → 403 `forbidden` (not a platform admin; nothing about the resource is revealed) → 404 → 403 specific codes (`cannot_change_self`) → 422 business codes → 409. They are **session only** (role matrix section 5): from Phase 5 an API key gets 403 `insufficient_scope`. |
| Active users | "Active" means `users.is_active`. Deactivated users keep their rows (memberships, roles) but can't sign in, have no sessions and **count nowhere**: not in `member_count`, `list_project_access`, group member counts, or c11. c11 also leaves out service accounts (a project keeps a human admin). Lists for admins (`list_group_members`, `list_admin_users`) still show deactivated users, flagged. |
| Project routes | `/projects/{slug}/groups` and `/projects/{slug}/access` follow the Phase 1 project order: 401 → 422 → 404 (can't view) → 403 → 422 → 409. |
| Privacy | Never log or audit tokens, secrets, cookies, emails, passwords or claim sets. Audit entries hold ids, enum values, field names, the IdP issuer and subject, and group mapping values (organisation config, not personal data). The mapping test's claims are neither stored nor logged. |

## 2. Endpoints

Common errors (401, 403 `csrf_failed`, 422 `validation_error`, 400 `invalid_cursor`) are
not repeated per row.

### Sign-in (`tags: auth`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /auth/config` | `get_auth_config` | public | → `AuthConfig {sso, dev_login, break_glass}` (booleans, §3.1) | |
| `GET /auth/login?next=` | `sso_login` | public | browser navigation → 302 to the IdP (§3.2) | 302 `/login?error=sso_unavailable` or `too_many_attempts` |
| `GET /auth/callback?code=&state=&error=&error_description=&iss=` | `sso_callback` | public | browser navigation from the IdP → 302 to the saved `next` with a new session (§3.2–3.6) | 302 `/login?error=<code>` (§4.2) |
| `POST /auth/break-glass` | `break_glass_login` | public; break-glass available (§3.8) | `BreakGlassLogin {username, password}` → `CurrentUser`; sets the session cookies | 404 unavailable; 401 `invalid_credentials`; 403 `account_disabled`; 429 `too_many_attempts` (with `Retry-After`) |
| `POST /auth/logout/redirect` | `logout_redirect` | public | HTML form post, no body → 303 to the IdP's end-session endpoint or `/login?signed_out=1` (§3.9) | none (always 303) |

`GET /auth/me`, `POST /auth/logout` (204) and the dev login are unchanged
(`CurrentUser.auth_method` is agreed but lands later: §7).

### Admin: users (`tags: admin`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /admin/users?q=&active=&platform_admin=&has_identity=&cursor=&limit=` | `list_admin_users` | `platform.manage_users` | → `AdminUserPage` of `AdminUserSummary`, by display name (§3.4) | 403 |
| `POST /admin/users` | `create_admin_user` | `platform.manage_users` | `AdminUserCreate {email, display_name, is_platform_admin?, external_ids?}` → 201 `AdminUser` | 409 `email_taken`, `external_id_taken` |
| `GET /admin/users/{user_id}` | `get_admin_user` | `platform.manage_users` | → `AdminUser` (identities, external IDs, groups with provenance, project roles with sources) | 404 |
| `PATCH /admin/users/{user_id}` | `update_admin_user` | `platform.manage_users` (c17, c18) | `AdminUserUpdate {display_name?, email?, is_active?, is_platform_admin?}` → `AdminUser` | 404; 403 `cannot_change_self`; 409 `email_taken`, `system_account`, `last_platform_admin` |
| `PUT /admin/users/{user_id}/external-ids` | `replace_user_external_ids` | `platform.manage_users` | `ExternalIdsReplace {external_ids: [{kind, value}] (0..20, one per kind)}` → `AdminUser` | 404; 409 `external_id_taken`, `system_account` |
| `DELETE /admin/users/{user_id}/identities/{identity_id}` | `unlink_user_identity` | `platform.manage_users` | → 204; also ends the user's SSO sessions | 404 (unknown, or not this user's) |
| `DELETE /admin/users/{user_id}/sessions` | `end_user_sessions` | `platform.manage_users` | → 204 (idempotent) | 404 |

### Admin: groups (`tags: admin`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /admin/groups?q=&cursor=&limit=` | `list_admin_groups` | `platform.manage_groups` | → `GroupPage` of `GroupSummary`, by name | 403 |
| `POST /admin/groups` | `create_group` | `platform.manage_groups` | `GroupCreate {name, description?, sync_mode=managed, idp_values=[]}` → 201 `Group` | 409 `group_name_taken` |
| `POST /admin/groups/test-mapping` | `test_group_mapping` | `platform.manage_groups` | `MappingTestRequest {claims: object, user_id?}` → `MappingTestResult` (§3.12) | 422 `user_not_found` |
| `GET /admin/groups/{group_id}` | `get_group` | `platform.manage_groups` | → `Group` (mapping, counts by provenance, project grants) | 404 |
| `PATCH /admin/groups/{group_id}` | `update_group` | `platform.manage_groups` | `GroupUpdate {name?, description?}` → `Group` | 404; 409 `group_name_taken` |
| `DELETE /admin/groups/{group_id}` | `delete_group` | `platform.manage_groups` | → 204; memberships, mapping and grants go with it | 404 |
| `PUT /admin/groups/{group_id}/mapping` | `replace_group_mapping` | `platform.manage_groups` | `GroupMappingUpdate {sync_mode, idp_values (0..50)}` → `Group` | 404 |
| `GET /admin/groups/{group_id}/members?q=&cursor=&limit=` | `list_group_members` | `platform.manage_groups` | → `GroupMemberPage` of `GroupMember {user, email, is_active, manual, synced, joined_at}` by display name (deactivated members included, flagged) | 404 |
| `POST /admin/groups/{group_id}/members` | `add_group_member` | `platform.manage_groups` | `GroupMemberAdd {user_id}` → 201 `GroupMember` (manual) | 404; 409 `already_member`; 422 `user_not_found` |
| `DELETE /admin/groups/{group_id}/members/{user_id}` | `remove_group_member` | `platform.manage_groups` | → 204; removes the membership (manual and synced) | 404 (group, or not a member) |

### Groups and project access (`tags: groups`, `projects`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /groups?q=&limit=` | `search_groups` | `user.search` | → `GroupSearchResult[] {id, name, description, member_count}` by name; `limit` 1–50, default 20 | |
| `GET /projects/{slug}/groups` | `list_project_group_grants` | `project.view` | → `ProjectGroupGrant[] {group, role, granted_at}`, admins first, then by group name | 404 |
| `POST /projects/{slug}/groups` | `add_project_group_grant` | `project.manage_members` | `ProjectGroupGrantAdd {group_id, role=member}` → 201 `ProjectGroupGrant` | 403, 404; 409 `already_granted`; 422 `group_not_found` |
| `PATCH /projects/{slug}/groups/{group_id}` | `update_project_group_grant` | `project.manage_members` (c11) | `ProjectGroupGrantUpdate {role}` → `ProjectGroupGrant` | 403; 404 not granted; 409 `last_admin` |
| `DELETE /projects/{slug}/groups/{group_id}` | `remove_project_group_grant` | `project.manage_members` (c11) | → 204 | 403; 404 not granted; 409 `last_admin` |
| `GET /projects/{slug}/access?q=&role=&cursor=&limit=` | `list_project_access` | `project.view` | → `ProjectAccessPage` of `ProjectAccessEntry {user, email, role, sources}` by display name (§3.7) | 404 |

`GET /projects/{slug}/members` (`list_project_members`) is unchanged: **direct**
members only. The Members tab shows direct members, group grants, and (from
`list_project_access`) everyone with access and why.

### Admin: audit log and SSO (`tags: admin`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /admin/audit?actor_id=&action=&target_type=&target_id=&project_id=&since=&until=&cursor=&limit=` | `list_audit_entries` | `platform.view_audit_log` | → `AuditPage` of `AuditEntry`, newest first (§3.11); `target_type` is `user`, `project`, `idea` or `group` | 403 |
| `GET /admin/sso` | `get_sso_config` | `platform.configure_sso` | → `SsoConfig` (effective settings, secrets masked, redirect URIs per base URL, discovery status, break-glass status) (§3.10) | 403 |

## 3. Business rules

Tests first (SPEC section 15) for 3.3 (login matching), 3.5–3.6 (claim extraction and
group sync), 3.8 (break-glass) and the authz changes in 3.7. Every admin write is
audited in the same transaction (§3.11).

### 3.1 Sign-in methods (`GET /auth/config`)

- `sso` = `settings.sso_configured` (an issuer is set). The button always reads "Sign
  in with SSO" (no setting: simple beats configurable).
- `dev_login` = `SOUNDINGS_DEV_LOGIN_ENABLED` (never in production).
- `break_glass` = `settings.break_glass_available`: enabled, username and password both
  set, **and SSO not configured** (§3.8).
- The sign-in page shows the SSO button first (the one primary action), the dev login
  picker when on, and the break-glass form only when `break_glass` is true. With none
  of them it says sign-in isn't configured and to see the operator guide.

### 3.2 SSO sign-in flow

One OIDC provider per instance, configured by `SOUNDINGS_OIDC_*` (Helm `oidc.*`).
Authorization code flow with PKCE (S256), `state` and `nonce`, all server-side; the
browser only ever holds `state` (in the URL and the `soundings_oidc` cookie). Authlib
1.8 is verified against Keycloak 26 ([research R1 §3](../research/backend-libraries.md));
its Starlette client needs `request.session`, so prefer its lower-level pieces
(`AsyncOAuth2Client` with `code_challenge_method="S256"`, and its/joserfc's JWT
validation) over `SessionMiddleware`, and keep the attempt in `oidc_login_attempts`.

**`GET /auth/login?next=`**

1. SSO not configured → 302 `/login?error=sso_unavailable`.
2. **Origin.** `base = settings.base_url_for_host(Host)`. When the request's `Host`
   (with port) is not exactly the host of one of `SOUNDINGS_BASE_URLS` (localhost
   outside production, say), 302 to `<first base URL>/api/v1/auth/login?next=…` first,
   so the whole flow (cookie included) runs on a configured origin. The redirect URI is
   always `base + "/api/v1/auth/callback"`, built from configuration, never from the
   raw `Host`: each public host signs in on itself (multi-domain).
3. **`next`** is kept only if it is a same-origin SPA path: starts with `/`, not `//`
   or `/\`, no `\`, no control or whitespace characters, at most 2048 characters, and
   not under `/api/`. Anything else becomes `/` (no error): open-redirect protection.
4. **Throttle** (this endpoint is public and writes a row): at most **60 starts per
   client IP per minute** (IPv6 addresses counted per /64; the client IP is uvicorn's,
   which honours `trustedProxies`), per process, with the same limiter as break-glass
   (§3.8) → 302 `/login?error=too_many_attempts`. And at most **10,000 live**
   (unexpired) attempts in the table → 302 `/login?error=sso_unavailable` and a
   warning in the log (no audit entry, nothing written). 60 a minute leaves room for an
   office behind one NAT address; one address can hold at most about 600 live rows.
5. Provider metadata from `<issuer>/.well-known/openid-configuration` (cache it for
   about an hour; its `issuer` must equal `SOUNDINGS_OIDC_ISSUER` exactly). Unreachable
   or invalid → 302 `/login?error=sso_unavailable`. **Cache a failed fetch for 30
   seconds** too, so an unreachable IdP is neither hammered nor slow for every request.
   The same cached result feeds `SsoConfig.discovery` (§3.10).
6. `state` and `nonce` = 256-bit random (`secrets.token_urlsafe(32)`), `code_verifier`
   = `secrets.token_urlsafe(64)`, challenge `BASE64URL(SHA256(verifier))`.
7. Insert an `oidc_login_attempts` row: `state_hash` = SHA-256 of `state`, `nonce`,
   `code_verifier`, `redirect_uri`, `next_path`, `expires_at = now + 10 minutes`.
   Delete expired attempts in the same transaction (no job needed).
8. Set the `soundings_oidc` cookie (§1 for the `__Host-` name) = `state`: HttpOnly,
   `SameSite=Lax` (sent on the IdP's top-level redirect back), `Path=/`,
   `Max-Age=600`, `Secure` per `cookie_secure`.
9. 302 to `authorization_endpoint` with `response_type=code`, `client_id`,
   `redirect_uri`, `scope` (space-joined `SOUNDINGS_OIDC_SCOPES`, `openid` always
   first), `state`, `nonce`, `code_challenge`, `code_challenge_method=S256`.

**`GET /auth/callback`**

Every outcome clears the `soundings_oidc` cookie. Every failure is a 302 to
`/login?error=<code>` (codes in §4.2; append `&next=<next>` when the attempt was found
and `next` isn't `/`) and an audit entry (`session.sign_in_denied`, §3.11), except the
first two, which have no attempt to speak of. IdP-supplied text (`error_description`)
is never shown or logged. Query values have no length limits in the schema: an overlong
`state` simply matches no attempt (`login_expired`), an overlong `code` fails at the
token endpoint (`sso_failed`).

**Transactions:** never hold a database transaction open across the token request
(up to 10 s). Step 2 deletes the attempt and commits; steps 3–7 use no transaction;
steps 8–10 (matching, sync, session, audit) run in one new transaction. Denials and
their audit entries commit on their own.

1. SSO not configured → `sso_unavailable`.
2. **State.** `state` query parameter and the cookie both present and equal (constant
   time), and a row with `state_hash = sha256(state)` exists → else `login_expired`.
   **Delete the row now** (single use, committed even if a later step fails); then
   `expires_at <= now` → `login_expired`. The cookie binds the attempt to the browser
   that started it: a callback URL handed to someone else fails (login CSRF).
3. `iss` present and not equal to the issuer (RFC 9207, mix-up defence) → `sso_failed`.
4. `error=access_denied` → `login_cancelled`; any other `error` → `sso_failed`;
   no `code` → `sso_failed`.
5. **Token request** to `token_endpoint` (10 s timeout): `grant_type=authorization_code`,
   `code`, the stored `redirect_uri` and `code_verifier`; client authentication
   `client_secret_basic` when a secret is set (`client_secret_post` if the metadata
   only supports that), else `client_id` in the body (public client). Any error →
   `sso_failed`.
6. **ID token** (`id_token` in the response; missing → `sso_failed`): signature against
   the provider's JWKS (re-fetch once for an unknown `kid`), asymmetric algorithms only
   (RS/PS/ES/EdDSA; `none` and HMAC refused); `iss` = issuer; `aud` contains
   `client_id` and, with several audiences, `azp` = `client_id`; `exp` in the future and
   `iat` not in the future (60 s leeway); `nonce` = the stored nonce; `sub` a non-empty
   string of at most 255 characters. Any failure → `sso_failed`.
7. **Claims** are the validated ID token's claims only (no userinfo call: Keycloak,
   Entra ID and Google all put `sub`, `email`, `email_verified`, `name` and groups in
   the ID token when configured; §3.13). **Group overage:** when group sync is on, the
   configured groups claim is absent, and the claims have a `_claim_names` object with
   that claim name as a key (Entra ID sends this instead of the groups when a user is in
   more than 200), deny `sso_failed` (reason `groups_overage`) before matching, so
   nothing is linked and no membership is removed. Fix it in Entra ID ("groups assigned
   to the application", or app roles).
8. **Login matching** (§3.3) → a user, or a denial.
9. **Group sync** (§3.6), same transaction.
10. **Session:** `start_session(auth_method="sso")` with the raw ID token stored on the
    row when it is at most 3,072 characters (else none: §3.9), rotating any session the
    browser had; set the cookies; `user_identities.last_login_at = now`. Audit
    `session.sign_in` `{method: "sso", session_id, identity_id, matched_by}`.
11. 302 to the attempt's `next_path`.

### 3.3 Login matching

Inputs: `issuer` = the ID token's `iss`, `subject` = `sub`, and the claims. A user is
**eligible** when `is_active`, not `is_service_account` and not `is_break_glass`. The
steps run in order; the first that identifies a user decides, and **the outcome is
final** (a later step never runs after an earlier one found someone). Deny by default.

**What matching trusts (a hard requirement for operators; the operator guide and
`SsoConfig.external_id_claim` repeat it).** Steps 2 and 3 link an existing account to
whoever presents the claim, so their claims must be ones the person can't choose:

- **The external-ID claim must come from an attribute only IdP admins can set.** If
  users can edit it, anyone can type a colleague's employee number and sign in as that
  pre-created user, including a pre-created **platform admin** (§3.8 bootstrap).
  Keycloak: the attribute is declared in the realm's user profile with edit permission
  `admin` only (as `employee_no` in the dev realm), and "Unmanaged attributes" is not
  `Enabled` (otherwise users can add any attribute in the account console); a
  hard-coded or role-based mapper is fine too. Entra ID: `oid` (immutable object id) or
  `employeeid` (directory-managed); never `upn`, `preferred_username`, `email` or an
  extension attribute users can write. Google: leave it unset (`sub` is the identity).
- **Email matching trusts the IdP's `email_verified`.** Keep
  `SOUNDINGS_OIDC_MATCH_VERIFIED_EMAIL` on only for an IdP that verifies addresses and
  clears the flag when a user changes theirs (Keycloak does; Entra ID sends no
  `email_verified`, so email matching never applies there: pre-create users with the
  `oid` external ID instead).

| Step | Runs when | Finds | Then |
|---|---|---|---|
| 1. Identity | always | the user linked to `(issuer, subject)` | not eligible → deny `account_disabled`; else sign in (`matched_by: identity`) |
| 2. External ID | `SOUNDINGS_OIDC_EXTERNAL_ID_CLAIM` set and the claim usable | the user with an external ID of kind `SOUNDINGS_OIDC_EXTERNAL_ID_KIND` whose value equals the claim, case-insensitively | not eligible → `account_disabled`; already linked to another subject at this issuer → `identity_conflict`; else link and sign in (`external_id`) |
| 3. Verified email | `SOUNDINGS_OIDC_MATCH_VERIFIED_EMAIL` (default true) and the email is verified | the user whose email equals the claim, case-insensitively | not eligible → `account_disabled`; already linked at this issuer → `identity_conflict`; external-ID matching is configured and the user has an external ID of that kind → `identity_conflict` (whatever the token carries: such a user is linked **only by step 2**); else link and sign in (`email`) |
| 4. Auto-create | `SOUNDINGS_OIDC_AUTO_CREATE_USERS` (default false) and the email is verified | nobody: creates a user | §"Auto-create" below (`created`) |
| 5. Deny | otherwise | | `no_account` |

Exact semantics:

- **Claim paths** (external ID, display name, groups) resolve as in §3.5: the whole
  configured string as a top-level claim name first, else a dotted path.
- **External-ID claim usable:** a string (trimmed, 1–200 characters) or an integer
  (as its decimal string). Anything else (missing, null, empty, list, object, boolean)
  counts as absent: step 2 is skipped.
- **Verified email** means: an `email` claim that is a string of at most 320
  characters containing `@`, not under the reserved `.invalid` domain (§3.8), **and**
  an `email_verified` claim that is JSON `true` or the string `"true"` (any case). A
  missing `email_verified` is *not* verified (Entra ID sends none: use the external-ID
  claim there). An email that is present but not verified skips steps 3 and 4; if
  nothing else matches, the denial's audit `reason` is `email_not_verified`.
- **Already linked** means the user has a `user_identities` row for this `issuer`
  (with another `subject`, since step 1 didn't find it): one IdP account per user per
  issuer. An admin resolves it by unlinking the old identity (§3.4), e.g. after the
  person's IdP account was recreated.
- **Linking** inserts `user_identities (user_id, issuer, subject)` and audits
  `user.identity_link {identity_id, matched_by, issuer}`. Insert it inside a SAVEPOINT
  (`session.begin_nested()`): on a unique violation (the same person's first sign-in in
  two tabs at once) roll back to it and run matching once more (step 1 then finds the
  identity) without losing the transaction.
- **Auto-create** needs a **verified** email, exactly as step 3 (a missing or false
  `email_verified` → deny `no_account`, reason `email_not_verified`: on Entra ID,
  pre-create users with the `oid` external ID instead). If **any** user already has that
  email (including deactivated, service and break-glass accounts) → deny
  `identity_conflict` (reason `email_taken`): never a second account for one address.
  Otherwise create the user: `email` from the claim; `display_name` from the `name`
  claim (trimmed, cut to 100 characters), falling back to `preferred_username`, then
  the email's local part (fixed, no setting); not a platform admin; active. Link the
  identity; audit `user.create {source: "sso"}` (actor: the new user). The new account
  gets access only through groups (§3.6), or later from admins.
- **Profile fields are not synced:** after the first sign-in, name and email are
  Soundings' own (admins edit them); claims never overwrite them.
- **Service accounts and the break-glass admin are never matched** at any step (they
  are not eligible): a match on one of them denies.
- **Denials** audit `session.sign_in_denied {method: "sso", reason, issuer, subject}`
  with **`actor_id` null** and `target_type: user`, `target_id` = the identified user
  when there is one (never the actor: the attempt may be someone else's). `reason` is
  one of `account_disabled`, `already_linked`, `external_id_mismatch` (the token's value
  differs from the user's), `external_id_missing` (the token has none but the user has
  one), `email_taken`, `email_not_verified`, `groups_overage` (§3.2 step 7),
  `no_match`; the redirect carries only the coarse code (§4.2).

Worked examples (claim `employee_no`, email matching on, auto-create off):

| Token | Soundings has | Result |
|---|---|---|
| `sub=k-1`, linked to Bob | Bob active | Bob (identity) |
| `sub=k-9`, `employee_no=E1002`, `email=bob@…` verified | Bob pre-created with `employee_no=e1002`, no identity | Bob (external ID), identity `k-9` linked |
| `sub=k-9`, `employee_no=E1002` | Bob already linked to `k-1` at this issuer | `identity_conflict` (already_linked) |
| `sub=k-7`, no `employee_no`, `email=Erin@Example.com`, `email_verified=true` | Erin `erin@example.com`, no identity, no external ID | Erin (email) |
| `sub=k-7`, `employee_no=E9`, `email=erin@…` verified | nobody has `E9`; Erin has `employee_no=E5` | `identity_conflict` (external_id_mismatch) |
| `sub=k-7`, no `employee_no`, `email=erin@…` verified | Erin has `employee_no=E5`, no identity | `identity_conflict` (external_id_missing) |
| `sub=k-7`, `email=erin@…`, `email_verified=false` | Erin, no identity | `no_account` (email_not_verified) |
| `sub=k-3`, `email=dave@…` verified | Dave deactivated | `account_disabled` |
| `sub=k-5`, `email=new@…` verified | nobody | `no_account` (no_match) |
| `sub=k-5`, `email=new@…`, no `email_verified`; **auto-create on** | nobody | `no_account` (email_not_verified) |
| `sub=k-5`, `email=new@…` verified, `name=Nia Lee`; **auto-create on** | nobody | Nia Lee created (created), no roles |

### 3.4 Users (Admin settings → Users)

- **List:** every account (people, service accounts, the break-glass admin), by
  `lower(display_name)` then `id`, keyset-paged. `q` = name or email contains
  (case-insensitive); `active`, `platform_admin`, `has_identity` filter when given.
  `has_identity=false` lists pre-created users who never signed in with SSO.
- **Pre-create** (`create_admin_user`): an ordinary active user without an identity.
  Email unique case-insensitively (409 `email_taken`); addresses under `.invalid` are
  reserved for system accounts (422 `validation_error`, also on update); each external
  ID `(kind, value)` unique case-insensitively across users (409 `external_id_taken`);
  kinds match `^[a-z][a-z0-9_]{0,39}$`, values 1–200 characters, one per kind. Audit
  `user.create {source: "admin", rule, is_platform_admin, external_id_kinds}`.
  Pre-create **platform admins** with an external ID (from an admin-only attribute,
  §3.3) where the IdP supports it, rather than relying on email.
- **Detail** (`AdminUser`): `identities` (issuer, subject, linked, last login),
  `external_ids` by kind, `groups` with `manual`/`synced` by group name, `project_roles`
  for every project where the user has an effective role, with its `sources` (direct
  first, then each granting group by name), and `active_session_count`.
- **Update** (PATCH, null = unchanged): email unique (409 `email_taken`). **c17:** you
  can't change your own `is_active` or `is_platform_admin` (403 `cannot_change_self`,
  only when the value would change), so no admin locks themselves out or leaves the
  instance without a platform admin by accident. **c18:** taking the platform-admin
  flag from an active platform admin, or deactivating one, needs another active
  platform admin (not the break-glass account) to remain, else 409
  `last_platform_admin`. Lock first, then count: `SELECT id FROM users WHERE
  is_platform_admin AND is_active ORDER BY id FOR NO KEY UPDATE`, so two admins
  demoting each other at the same moment can't both succeed. **System accounts** (service
  accounts, the break-glass admin): only `display_name` and `is_active` change; `email`
  or `is_platform_admin` → 409 `system_account`. **Deactivating** ends all the user's
  sessions in the same transaction; the user can't sign in by any method until
  reactivated. Audit `user.update {rule, fields, is_active?, is_platform_admin?,
  sessions_ended?}` (the flags' new values, only when they changed).
- **External IDs** (`replace_user_external_ids`): replaces the set; 409
  `external_id_taken`; 409 `system_account` for service and break-glass accounts (an
  external ID on the break-glass admin would let an SSO account take it over). Audit
  `user.external_ids_replace {rule, kinds}` (kinds only, never values).
- **Unlink identity:** deletes the `user_identities` row (404 unless it is this user's)
  and, in the same transaction, the user's SSO sessions (`auth_method = 'sso'`): the
  IdP account they came from is no longer trusted. The next SSO sign-in matches by
  external ID or email again. Audit `user.identity_unlink {rule, identity_id, issuer,
  sessions_ended}`.
- **End sessions:** deletes all the user's sessions (including your own, if it is you);
  204 even if there were none. Audit `user.sessions_end {rule, count}`. Group changes
  then apply at their next sign-in.
- **Offboarding = deactivate.** Sync runs only at sign-in, so someone removed from the
  IdP keeps a running session until it ends (12 hours idle, 7 days at most) and keeps
  their synced memberships for as long as they never sign in again. Deactivating ends
  their sessions at once, and deactivated users count nowhere (§1 "Active users").
  The operator guide says so.
- **People pickers** (`search_users`, `list_dev_users`) and project membership,
  ownership, evaluation and group membership never include or accept the break-glass
  admin (422 `user_not_found`, like service accounts).

### 3.5 Groups and the groups claim

- **Groups** have a name (1–80, unique case-insensitively, 409 `group_name_taken`), a
  description (≤ 500), a `sync_mode` (`managed` default, or `additive`) and 0–50 IdP
  values. A group with no values is "not mapped".
- **Normalisation** (one function, `app.schemas.groups.normalise_idp_value`, for the
  stored mapping *and* the claim): trim whitespace, strip `/` at both ends, trim again,
  lower-case. `"/Innovation/Admins"` → `innovation/admins`, so a Keycloak full path
  (`full.path=true`) matches a mapping typed with or without the leading slash. Inner
  segments stay: `admins` does **not** match `/innovation/admins` (no accidental match
  between same-named subgroups), and a subgroup never inherits its parent's mapping
  (`/innovation` does not match a member of `/innovation/admins`: Keycloak's full-path
  claim lists only the groups a user is directly in, so map each subgroup you need).
  Lower-casing makes IdP groups that differ only in case (`/Ops`, `/ops`) the same
  value. Entra ID object ids and Keycloak role names are just strings. A value that is
  empty once normalised is a 422 in a mapping and ignored in a claim. Mappings are
  stored normalised, de-duplicated and sorted; a value may map to several groups.
- **Extraction** of the claim `SOUNDINGS_OIDC_GROUPS_CLAIM` (default `groups`; empty =
  no group sync at all):
  1. **Path:** if the claims have a top-level key equal to the whole configured string,
     use it (claim names may contain dots, e.g. `https://example.com/groups`);
     otherwise split on `.` and walk nested objects (`realm_access.roles`). A missing
     segment or a non-object on the way → claim absent.
  2. **Value:** a list → its elements; a string → one element; absent or `null` → no
     values; anything else → no values (counted as 1 ignored).
  3. **Elements:** strings are normalised; non-strings and values empty after
     normalisation are ignored (counted). Only the first 1,000 elements are considered.
     The result is de-duplicated.
  4. **Absent = empty**, deliberately (fail closed): a token without the claim removes
     every *synced* membership of managed groups. Keycloak omits the claim when a user
     is in no groups. The one exception is Entra ID's group overage, which denies the
     sign-in instead (§3.2 step 7).
- **Matching:** a group matches when one of its stored values equals one of the
  extracted values exactly. No wildcards or prefixes.

### 3.6 Group sync at sign-in

Runs at every successful **SSO** sign-in (never break-glass or dev login), in the
sign-in transaction, after matching, when a groups claim is configured.

**Locking.** Sync locks the user row (`SELECT … FROM users WHERE id = :user_id FOR NO
KEY UPDATE`: it doesn't block foreign-key checks on other tables) before reading the
user's memberships, so two sign-ins of one user serialise.
**`add_group_member` and `remove_group_member` take the same user-row lock** before
reading or writing the membership, so an admin's manual add can't be lost to a sync
deleting the synced-only row at the same moment (and vice versa). Sync reads the
matched groups `FOR KEY SHARE`, so a concurrent `delete_group` can't fail the sign-in
with a foreign-key error: a delete that comes first leaves nothing to match; one that
comes second waits, and its cascade removes the new membership.

With `V` = the extracted values and `M` = the groups that match `V`:

| User's membership of group *g* before | *g* ∈ M | *g* ∉ M, managed | *g* ∉ M, additive |
|---|---|---|---|
| none | add `synced` (row `manual=false, synced=true`) | — | — |
| manual only | set `synced=true` (keeps `manual`) | — | — |
| synced only | keep | **delete the row** | keep |
| manual and synced | keep | set `synced=false` (stays a manual member) | keep |

- **Manual memberships are never touched by sync:** `manual` is only ever set by
  `add_group_member` and cleared by `remove_group_member` (which removes the whole row).
- **Managed:** after sync, the user's synced memberships of managed groups are
  *exactly* the managed groups in `M`. A managed group whose mapping was emptied matches
  nothing, so its synced memberships go at each member's next sign-in.
- **Additive:** sync only adds; removing an additive synced membership takes an admin
  (`remove_group_member`). It comes back at the next sign-in while the IdP still sends a
  mapped value: that is what additive means.
- Mapping changes (`replace_group_mapping`) change no memberships; they apply to each
  user at their next sign-in. To cut access *now*, remove the user from the group (or
  deactivate the user): roles are evaluated live, so access ends on their next request.
- Audit `user.groups_sync {added_group_ids, removed_group_ids, claim_found}` (actor and
  target: the user) only when something changed. *Added* = `synced` went from false to
  true (a new row, or the flag set on a manual member); *removed* = `synced` went from
  true to false (the row deleted, or the flag cleared on a manual member who stays).
  `claim_found` (whether the token had the groups claim at all) makes a misconfigured
  claim that wipes every managed membership easy to spot in the log.
- **Offboarding:** sync only runs at sign-in; deactivate people who leave (§3.4).
- **Acceptance (SPEC):** a user whose IdP group grants a project role through a managed
  mapping has that role after sign-in; remove them from the IdP group and, at their
  next sign-in, the synced membership and the project access are gone.

### 3.7 Project roles via groups

- **Effective role** (view `project_effective_roles`, migration 0003) = the highest
  (`admin > member > viewer`) of the direct role and the role of every grant to a group
  the user belongs to (manual or synced). Every role check already reads the view, so
  c4, c11, `list_projects`, `search_users?project=`, My work and the whole authz policy
  count group roles with no further change. Role matrix §1: "group membership, both
  (highest wins)" gets table-driven tests now.
- **Grants:** `add_project_group_grant` (group must exist: 422 `group_not_found`;
  already granted: 409 `already_granted`; default role `member`); `update_…` and
  `remove_…` are 404 when the group has no grant here and check **c11** against the
  view after the change (lock the project row as Phase 1 membership changes do; 409
  `last_admin`). Audit `project.group_grant_add {rule, role}`, `…_update {rule,
  from_role, role}`, `…_remove {rule, from_role}` with `target_type: group`.
- **c11 counts group admins**, also for Phase 1's direct-member endpoints: removing the
  last *direct* admin is fine when a group grants admin. It counts only **active,
  non-service** users with the effective role `admin` (join `users`: `is_active AND NOT
  is_service_account`), so a group whose only admins are deactivated doesn't satisfy
  it. Platform-level group changes (deleting a group, removing a group member, sync)
  are **not** blocked by c11: platform admins can always repair a project.
- **`list_project_group_grants`**: anyone who can view the project (like the members
  list); admins first, then by group name; `group.member_count` included.
- **`list_project_access`**: every *active* user with an effective role, by
  `lower(display_name)` then `id` (keyset), with `role` (effective) and `sources` (direct
  first, then groups by name). `q` = name or email contains; `role` filters the
  effective role. Visible to anyone who can view the project (members are, already).
  It lists roles, so it leaves out platform admins without a role here (they can see
  and manage every project) and, for internal projects, the signed-in users who can
  view it without one: the Members tab says so in one line under the list.
- **`ProjectSummary.member_count`** now counts *active* users with an effective role
  (direct or via groups; the same people `list_project_access` lists), not direct
  members: a project shared with a 200-person group doesn't say "1 member". No schema
  change.
- **Group member counts** (`member_count`, `manual_member_count`,
  `synced_member_count`) count active members only, like `member_count` above.
- **`search_groups`**: rule `user.search` (any signed-in user, like the people
  picker), name contains `q` case-insensitively, by name, at most `limit`. Group names,
  descriptions and counts are directory data at the level `user.search` already shows
  everyone (names and emails); kept open so a project admin's picker needs no platform
  rights.

### 3.8 Break-glass admin

- **Available** (`settings.break_glass_available`) only when
  `SOUNDINGS_BREAK_GLASS_ENABLED` is true, `SOUNDINGS_BREAK_GLASS_USERNAME` and
  `_PASSWORD` are both set (from the chart's Secret), **and SSO is not configured**.
  SPEC: "off once SSO is configured". For an SSO outage the operator unsets
  `oidc.issuer` (`helm upgrade`), which brings it back; that takes cluster access, the
  right bar for a break-glass account. Unavailable → `POST /auth/break-glass` is 404 and
  `AuthConfig.break_glass` is false.
- **Sessions follow availability** (§3.9): break-glass sessions stop working as soon as
  break-glass is not available, so configuring SSO ends them at their next request.
  They are also short: at most **8 hours**, and **1 hour** without a request (fixed;
  the shorter of these and the session settings applies).
- **Throttle first:** at most 5 failed attempts per client IP (uvicorn's client
  address, which honours `trustedProxies`; IPv6 addresses counted per /64) per 15
  minutes, per process; beyond that 429 `too_many_attempts` with `Retry-After` (seconds
  until the oldest counted failure leaves the window), without checking credentials.
  Only the first 429 per address per window is audited (`session.sign_in_denied`,
  reason `too_many_attempts`), so a flood can't fill the audit log. No global cap: it
  would let anyone lock the emergency door, and production passwords (at least 16
  characters, settings refuse to start otherwise; the chart generates 24 random ones)
  can't be guessed at 5 tries per address per 15 minutes.
- **Credentials:** compare SHA-256 digests in constant time,
  `hmac.compare_digest(sha256(submitted), sha256(configured))` for the username and
  for the password (UTF-8 bytes; digests have a fixed length, so timing reveals
  neither length), always both, so timing doesn't say which was wrong; no trimming.
  Wrong → 401 `invalid_credentials` and audit `session.sign_in_denied {method:
  "break_glass", reason: "invalid_credentials"}` with no actor and no target. The
  submitted username is never recorded or logged.
- **The account** is the single `users` row with `is_break_glass = true` (a partial
  unique index allows one; look it up by that flag), created at the first successful
  sign-in: email `break-glass@soundings.invalid` (`app.models.user.BREAK_GLASS_EMAIL`),
  display name "Break-glass admin", platform admin, active (audit `user.create
  {source: "break_glass"}`). Addresses under `.invalid` are reserved for system
  accounts: admins can't set one (§3.4) and SSO never matches or creates one (§3.3), so
  the address can't be taken first. Each sign-in re-asserts `is_platform_admin = true`.
  Deactivated → 403 `account_disabled` (audited with reason `account_disabled`, no
  actor, the account as target).
- **Sign-in:** `start_session(auth_method="break_glass")`, cookies as any sign-in,
  response `CurrentUser`. The SPA shows a persistent "Signed in with the break-glass
  account" banner in break-glass sessions: it recognises them by the account's fixed,
  reserved email (`break-glass@soundings.invalid`; only break-glass sign-in can reach
  that account) until `CurrentUser.auth_method` lands (§7). Audit `session.sign_in
  {method: "break_glass", session_id}`.
- **Every use is audited:** every audit entry records the acting session's method as
  `details.auth_method` (`sso`, `break_glass`, `dev_login`; §3.11), so all actions
  taken in a break-glass session are visible as such.
- Never matched by SSO login matching, never in pickers, can't hold external IDs,
  project roles or group memberships (§3.3, §3.4); it doesn't need them as a platform
  admin. It doesn't count as the remaining platform admin for c18 (§3.4).
- **Bootstrap order** (operator guide, chart `NOTES.txt`): install without
  `oidc.issuer`; sign in as the break-glass admin; pre-create the real platform admins
  (external ID from an admin-only attribute, §3.3, and/or email; `is_platform_admin`)
  and, if wanted, groups and mappings; then set `oidc.issuer`. Break-glass turns off
  and the pre-created admins are linked at their first SSO sign-in. SSO users are
  never platform admins by default.

### 3.9 Sessions, sign-out and cookies

- **Session creation** for every method goes through `start_session`, which gains a
  required `auth_method` and an optional `id_token` (SSO). The model's Python default
  (`dev_login`) only keeps Phase 1 callers working until then; there is no server
  default.
- **Sessions follow their method's availability**, checked on every request (a
  session that fails is treated as signed out: 401): `sso` sessions need
  `settings.sso_configured`, `break_glass` sessions need
  `settings.break_glass_available` (and the 8-hour / 1-hour limits, §3.8), `dev_login`
  sessions need `SOUNDINGS_DEV_LOGIN_ENABLED`. The issuer itself isn't checked: after
  moving to another IdP (a new `oidc.issuer`), sessions from the old one last until
  they expire (at most 7 days) unless an admin ends them; the people are the same, and
  their groups re-sync at the next sign-in.
- **The ID token is stored only up to 3,072 characters.** A larger one (many groups in
  the token, e.g. Entra ID) isn't stored at all: as `id_token_hint` it would push the
  303 `Location` past common proxy header limits (ingress-nginx buffers 4 KB by
  default) and sign-out would fail with a 502.
- **`POST /auth/logout`** is unchanged: 204, ends the session, clears the cookies, no
  IdP round trip. API clients and scripts keep using it.
- **`POST /auth/logout/redirect`** (the SPA's "Sign out": a `<form method="post">`,
  which also works without JavaScript; clear local drafts first):
  - **Cross-origin posts end nothing:** when `Sec-Fetch-Site` is present and not
    `same-origin`, or `Origin` is present and is not the origin of one of
    `SOUNDINGS_BASE_URLS`, it changes nothing and redirects (303) to `/`. (SameSite=Lax
    alone doesn't stop a form post from a sibling subdomain, which is same-site.)
  - Otherwise it ends the session if there is one (audit `session.sign_out
    {session_id, method}`), clears the cookies, then 303:
    - to the provider's `end_session_endpoint` with `client_id`,
      `post_logout_redirect_uri = base_url_for_host(Host) + "/login?signed_out=1"` and,
      when one is stored, `id_token_hint` (the stored ID token), when the ended session
      was an SSO session, SSO is configured and the metadata has an
      `end_session_endpoint` (without the hint, Keycloak asks the user to confirm the
      sign-out);
    - otherwise (and whenever the metadata can't be fetched) to `/login?signed_out=1`.
  - No CSRF token: the session cookie is `SameSite=Lax`, so a cross-site form post
    arrives without it and ends nothing; the origin check above covers same-site
    origins. CSP `form-action` is deliberately unset (it would block the redirect to
    the IdP; `app/middleware.py`).
- The ID token lives only on the session row and goes with it. It reaches the browser
  only inside the 303 `Location` to the IdP that issued it (the standard RP-initiated
  logout request); JavaScript never sees it.
- Signing in again at the IdP after `signed_out=1` shows the IdP's login (Keycloak's
  SSO session ended with the hint, or after the user confirmed).

### 3.10 SSO settings view (`GET /admin/sso`)

Read-only: SSO is configured by Helm values (`oidc.*`, `breakGlass.*`) and environment,
one provider per instance, no editing screen. `SsoConfig` maps the settings one to one;
secrets are never returned, only `client_secret_set` and
`break_glass.credentials_set`; the break-glass username is not shown either.
`redirect_uris` has one entry per `SOUNDINGS_BASE_URLS` value, in order, with the
`redirect_uri` (`<base>/api/v1/auth/callback`) and `post_logout_redirect_uri`
(`<base>/login?signed_out=1`) to register on the IdP client. `groups_claim`,
`external_id_claim` and `external_id_kind` are `null` when unset.

`discovery` (null when SSO is off) diagnoses `sso_unavailable` without shell access:
`status` `ok`, `unreachable` (network error, timeout, HTTP error), `invalid` (not JSON,
or no `authorization_endpoint`, `token_endpoint` or `jwks_uri`) or `issuer_mismatch`
(its `issuer` isn't exactly `SOUNDINGS_OIDC_ISSUER`, e.g. a trailing slash);
`end_session_supported`; `checked_at`. It reuses sign-in's cached fetch (§3.2 step 5),
fetching now only when nothing is cached; no error text from the IdP is returned. The
page also shows the external-ID trust warning next to `external_id_claim` (§3.3).

### 3.11 Audit log

Append-only `audit_log` rows in the same transaction as the change. The closed set of
actions is `app.schemas.audit.AuditAction`; `app.services.audit.AUDIT_ACTIONS` must be
exactly that set. `details` holds ids, enum values, field names, and the keys below;
admin actions also carry `rule`. Every entry written for a signed-in principal also
carries `details.auth_method` (the session's method) and, from Phase 5, `api_key_id`.

The actor is the signed-in user, except for `session.sign_in_denied`, whose actor is
always null (the target is the matched user, if any: a failed attempt is never pinned
on the account it tried). `target_type` is `user`, `project`, `idea` or `group`
(`app.schemas.audit.AuditTargetType`).

| Action | Target | `details` (besides `rule`, `auth_method`) |
|---|---|---|
| `session.sign_in` | user | `method` (`sso`, `break_glass`, `dev_login`), `session_id`; SSO: `identity_id`, `matched_by` (`identity`, `external_id`, `email`, `created`) |
| `session.sign_in_denied` | user, or none (no actor) | `method`, `reason` (§3.3: `account_disabled`, `already_linked`, `external_id_mismatch`, `external_id_missing`, `email_taken`, `email_not_verified`, `groups_overage`, `no_match`; §3.2 failures: `login_expired`, `login_cancelled`, `sso_failed`; §3.8: `invalid_credentials`, `account_disabled`, `too_many_attempts`); SSO: `issuer`, `subject` when known |
| `session.sign_out` | user | `session_id`, `method` |
| `user.create` | user | `source` (`admin`, `sso`, `break_glass`), `is_platform_admin`, `external_id_kinds` |
| `user.update` | user | `fields`, and `is_active` / `is_platform_admin` / `sessions_ended` when changed |
| `user.external_ids_replace` | user | `kinds` |
| `user.identity_link` | user | `identity_id`, `matched_by`, `issuer` |
| `user.identity_unlink` | user | `identity_id`, `issuer`, `sessions_ended` |
| `user.sessions_end` | user | `count` |
| `user.groups_sync` | user | `added_group_ids`, `removed_group_ids`, `claim_found` (§3.6) |
| `group.create` | group | `sync_mode`, `idp_values` |
| `group.update` | group | `fields` |
| `group.delete` | group | `member_count`, `project_ids` |
| `group.mapping_replace` | group | `from_sync_mode`, `sync_mode`, `from_idp_values`, `idp_values` (only when something changed) |
| `group.member_add` | group | `user_id` |
| `group.member_remove` | group | `user_id`, `manual`, `synced` (what it was) |
| `project.group_grant_add` / `_update` / `_remove` | group (+ `project_id`) | `role`, `from_role` |
| Phase 1, unchanged | | `project.create`, `project.update`, `project.member_add/_update/_remove`, `project.rubric_replace`, `idea.delete`, `idea.owner_change`, `idea.status_change`, `evaluator.add`, `evaluator.remove`, `evaluation.submit` |

SPEC's list (sign-ins, assignments, evaluations, status changes, admin changes) is
covered by `session.*`, `idea.owner_change` / `evaluator.*`, `evaluation.submit`,
`idea.status_change` and the `user.*`, `group.*`, `project.*` actions.

**Viewer (`list_audit_entries`)**: newest first by `(created_at, id)` (keyset cursor).
Filters combine with AND; repeated `action` values with OR: `actor_id`, `action`,
`target_type` + `target_id` (either alone too), `project_id`, `since` (inclusive),
`until` (exclusive; both need a UTC offset). Each entry resolves, where the thing still
exists: `actor` (`UserRef`), `target_label` (user's display name, project name, idea key
`CUST-12`, group name) and `project` (`ProjectRef`); otherwise those are `null` and the
ids remain. Resolve in a few batched queries per page, not per row. Indexes:
`(created_at, id)`, `(actor_id, created_at)`, `(action, created_at)`, `(project_id,
created_at)`, `(target_type, target_id)`. Entries are kept indefinitely in Phase 2.

### 3.12 Test mapping (`POST /admin/groups/test-mapping`)

The "test mapping" box: the admin pastes a claim set (e.g. a decoded ID token) and
optionally picks a user. It runs **the same extraction and matching code as sign-in**
(§3.5) and the sync rules (§3.6) without writing anything:

- `groups_claim`: the configured path, `null` when group sync is off (then
  `claim_found` false, `values` and `groups` empty).
- `claim_found`, `values` (normalised, de-duplicated, sorted) and `ignored_count`.
- `groups`, by name, each with its `sync_mode`, `matched_values` and whether the user
  is a `manual` member (who stays a member either way):
  - every group that matches: `effect` `add`, or `keep` when the user is already a
    synced member;
  - with a user, every group they are a **synced** member of that no longer matches
    (`matched_values` empty): `remove` for a managed group, `keep` for an additive one
    (additive sync never removes, so the admin sees why the membership stays).
  Without `user_id` the effects are for a user with no memberships (only `add`).
  There is no "no change" value: groups the claims don't touch are not listed.
- `project_roles`: the effective roles the user would have after that sync: their
  direct roles (with a user), plus grants of their manual groups and of the synced
  groups that result; sources as in `AdminUser`.
- `user_id` must be an existing user (422 `user_not_found`). Not audited (read-only);
  the claims are not stored or logged.

### 3.13 Keycloak for the acceptance test

The dev realm (`dev/keycloak/realm-soundings.json`, [dev/README.md](../../dev/README.md))
is already set up for this:

- Client `soundings`: confidential (secret `soundings-dev-secret`), standard flow only,
  PKCE S256 required; valid redirect and post-logout redirect URIs `<origin>/*` for
  `http://localhost:8000`, `:5173`, `http://127.0.0.1:8000`, the e2e stack
  `http://localhost:8100` and `http://127.0.0.1:8100`, and the k3s ingress
  `http://localhost:18081`. Production clients should list the exact URIs from
  `GET /admin/sso` instead of wildcards.
- Mapper "groups": Group Membership, claim `groups`, **full group path on**, in the ID
  token. Mapper "employee_no": user attribute → claim `employee_no`, in the ID token.
- Users alice, bob, carol (with `employee_no` E1001–E1003), dave, erin; password
  `password`; all `email_verified`. Groups `/innovation/admins`, `/innovation/members`,
  `/tools/members`, `/viewers`. Every user has a fixed id, so `sub` survives a
  re-import. Added for the e2e error cases (platform build): `grace` (`employee_no`
  E2001, matches only a user pre-created with it), `mallory` (unverified email naming
  the seeded Farah: `no_account`), `kenji` (in no group: the token has no groups
  claim) and `nia` (verified email, no account).
- Issuer must be the same for the browser and the backend: run the API on the host
  against `http://localhost:8080/realms/soundings`, or set `KC_HOSTNAME` when the API
  runs in a container. Agents on other ports register their callback through
  Keycloak's admin REST API in their own Keycloak container instead of editing the
  shared realm file.

App settings: `SOUNDINGS_OIDC_ISSUER=http://localhost:8080/realms/soundings`,
`SOUNDINGS_OIDC_CLIENT_ID=soundings`, `SOUNDINGS_OIDC_CLIENT_SECRET=soundings-dev-secret`,
`SOUNDINGS_OIDC_GROUPS_CLAIM=groups`, `SOUNDINGS_OIDC_EXTERNAL_ID_CLAIM=employee_no`,
`SOUNDINGS_BASE_URLS` including the origin you browse.

Acceptance scenario. The demo seed's first five people share the Keycloak users'
emails (since the backend build the seed also gives alice, bob and carol `employee_no`
E1001–E1003, so step 0.1 changes nothing on a fresh seed), and every Keycloak member of
`/tools/members` (alice, carol, dave) is already a **direct** member of TOOLS, so
removing the group could never take TOOLS away. The scenario therefore sets up its own
state (dev login stays on next to SSO, so Alice can do this through the API):

0. **Setup**, as platform admin Alice:
   1. Give Carol the external ID `employee_no = E1003` (`PUT
      /admin/users/{carol}/external-ids`). Her first SSO sign-in then links by external
      ID; having one, she can't be linked by email (§3.3).
   2. Create a **private** project for the test (any unused key and name; make them
      unique per run when the stack isn't reseeded) with Alice as its first admin.
      Carol has no direct role in it. Don't reuse TOOLS: Carol is a direct member
      there, and other e2e specs rely on the seed's memberships.
1. Create managed groups mapped to `/innovation/admins` (grant CUST admin),
   `/innovation/members` (CUST member), `/tools/members` (grant the test project
   `member`) and `/viewers` (GREEN viewer); run-unique names when not reseeded.
2. Carol signs in with Keycloak: she is linked by external ID (`session.sign_in`
   with `matched_by: external_id`; on a re-run without reseeding she is already linked
   and matches by `identity`), is a synced member of the tools group
   (`user.groups_sync`), and the test project is in her project list with role
   `member`, whose source in `list_project_access` is the group.
3. In Keycloak (admin REST API), remove carol from `/tools/members`. Her running
   session keeps access until she signs in again.
4. Carol signs out (`POST /auth/logout/redirect`) and in again: the synced membership
   is gone (`user.groups_sync` lists the group in `removed_group_ids`), the test project
   answers 404 and has left her list. (A private project, because CUST and GREEN are
   internal: any signed-in user can still *view* them.)
5. Variants: the same with an **additive** mapping keeps the membership; a **manual**
   membership of the same group survives sync; the mapping test for Carol with claims
   without `/tools/members` shows the tools group as `remove` (managed) or `keep` with
   empty `matched_values` (additive).
6. **Clean up:** add carol back to `/tools/members` in Keycloak.

## 4. Error codes

### 4.1 Problem codes (new in Phase 2)

| Status | `code` | When |
|---|---|---|
| 401 | `invalid_credentials` | break-glass username or password wrong (one answer for both) |
| 403 | `account_disabled` | the break-glass account is deactivated |
| 403 | `cannot_change_self` | changing your own `is_active` or `is_platform_admin` (c17) |
| 404 | `not_found` | break-glass unavailable; unknown user, group, identity or grant; not a member of the group |
| 409 | `email_taken` | creating or updating a user with an email another user has |
| 409 | `external_id_taken` | an external ID `(kind, value)` another user has |
| 409 | `group_name_taken` | group names are unique case-insensitively |
| 409 | `already_member` | adding a manual group member who already is one (Phase 1 code reused) |
| 409 | `already_granted` | granting a role to a group that already has one in the project |
| 409 | `last_admin` | a group grant change would leave the project without an active admin (c11) |
| 409 | `last_platform_admin` | demoting or deactivating the last active platform admin other than the break-glass account (c18) |
| 409 | `system_account` | email, platform-admin flag or external IDs of a service or break-glass account |
| 422 | `user_not_found` | unknown, inactive, service or break-glass user as a group member; unknown user in the mapping test |
| 422 | `group_not_found` | granting an unknown group |
| 422 | `validation_error` | also: a user email under the reserved `.invalid` domain (§3.4) |
| 429 | `too_many_attempts` | break-glass throttle (§3.8), with `Retry-After` |

### 4.2 Sign-in redirect codes (`/login?error=<code>`)

`app.schemas.auth.LoginErrorCode`; the sign-in page shows one calm sentence per code and
the SSO button again. Details are in the audit log only.

| `error` | When | Message idea |
|---|---|---|
| `sso_unavailable` | SSO not configured, the IdP's metadata can't be fetched, or too many sign-ins in progress | "Single sign-on isn't available right now." |
| `too_many_attempts` | more than 60 sign-in starts from this client IP in a minute (§3.2) | "Too many sign-in attempts from your network. Wait a minute and try again." |
| `login_expired` | state missing, mismatched, used or expired | "That sign-in took too long or was already used. Try again." |
| `login_cancelled` | IdP `error=access_denied` | "Sign-in was cancelled." |
| `sso_failed` | other IdP error, token exchange or ID token invalid, Entra ID group overage | "We couldn't verify your sign-in. Try again or contact an admin." |
| `no_account` | no match and no auto-create (or the email isn't verified) | "You don't have a Soundings account yet. Ask an admin to add you." |
| `account_disabled` | matched user deactivated, or a service or break-glass account | "Your account is deactivated." |
| `identity_conflict` | already linked to another IdP account, external ID mismatch or missing, email taken | "Your account needs an admin to finish linking it." |

`/login?signed_out=1` after `logout_redirect`: "You're signed out."

## 5. Decisions

Simpler option chosen each time; the lead may revisit (also logged in
[decisions.md](../decisions.md#2026-10-01--phase-2-contract)).

| Decision | Why |
|---|---|
| Login attempts live in `oidc_login_attempts` (hashed `state`, nonce, PKCE verifier, `redirect_uri`, `next`, 10-minute expiry, single use); the HttpOnly `soundings_oidc` cookie holds only `state`, binding the attempt to the browser. | The browser never holds the verifier or nonce (ADR 0005); no signed-cookie machinery (`itsdangerous`); expired rows are swept at the next login. |
| Claims come from the ID token only; no userinfo call. | One validated source; the providers we document put everything we need in the ID token. |
| Matching steps decide on the first user found; a match on an ineligible or already-linked user denies instead of falling through. | Falling through could link or create a second account for a deactivated or conflicting person. |
| Email matching and auto-create both require `email_verified` true; missing counts as unverified. Auto-create never reuses an existing address. A user with an external ID of the configured kind is linked only by that external ID, never by email. | Linking an existing account is account takeover if the email is wrong; an unverified address (Entra ID's `email`) can name anyone; an admin who set an external ID chose the stronger proof. |
| The external-ID claim must come from an attribute only IdP admins can set (operator requirement, repeated in the guide and on the SSO page). | A user-editable claim lets anyone sign in as a pre-created user, platform admins included. |
| One identity per user per issuer (`uq_user_identities_user_id_issuer`); conflicts are resolved by an admin unlinking. | Two IdP accounts silently sharing one Soundings user is a security smell. |
| External IDs: one value per kind per user; matched case-insensitively; admin-managed only (sign-in never records them). | Matches how employee numbers work; the claim never rewrites admin data. |
| Profile fields are not synced from claims after the first sign-in. | Admin edits stick; no surprise renames. |
| IdP values are normalised (trim, strip `/` at both ends, lower-case); inner path segments kept. | Keycloak full paths match with or without the slash; `admins` can't match `/innovation/admins`. |
| A missing groups claim means "no groups" (managed memberships removed). | Fail closed; Keycloak omits the claim for users in no groups, and the acceptance test relies on removal. |
| One membership row per (group, user) with `manual` and `synced` flags; admin "remove" deletes the row whatever its provenance. | Provenance stays visible; additive memberships can still be removed by an admin; sync never clears `manual`. |
| Mapping changes apply at each user's next sign-in, not retroactively. | Sync needs the user's claims, which only exist at sign-in; "remove member" is the immediate lever. |
| c11 isn't enforced for platform-level group changes (delete group, remove member, sync). | Sync must follow the IdP; platform admins can always repair a project. |
| `list_project_members` stays direct-only; a new `list_project_access` lists everyone with access and why; `member_count` counts effective roles. | No breaking change to `Member`; the Members tab can explain group access. |
| Group grants are listed to anyone who can view the project; `search_groups` uses `user.search` (not limited to admins, as the review suggested). | Same visibility as members; group names and counts are directory data like the people picker's names and emails; project admins need a group picker without platform rights. |
| No new rule names: `platform.manage_users`, `platform.manage_groups`, `platform.configure_sso` (now read-only), `platform.view_audit_log`, `project.manage_members`, `user.search` cover Phase 2; sign-in routes are public. | The role matrix already had them; the policy and its table-driven tests don't change shape. |
| Break-glass is available only while SSO is not configured; its sessions die when that changes and last at most 8 hours (1 hour idle); throttled per IP (IPv6 per /64) with `Retry-After`, no global cap; digests compared in constant time; production needs a 16+ character password; every action in its sessions is audited as such. | SPEC "off once SSO is configured"; an outage procedure (unset the issuer) needs cluster access; a global cap would let anyone lock the emergency door. |
| SSO and dev-login sessions likewise need their method to be configured; unlinking an identity ends the user's SSO sessions. | One rule for every method; an unlinked IdP account is no longer trusted. |
| `GET /auth/login` is throttled (60 starts per IP per minute, at most 10,000 live attempts) and caches a failed metadata fetch for 30 s. | It is public and writes a row; NAT'd offices still fit. |
| The ID token is stored only up to 3,072 characters; sign-out without it sends `client_id` + `post_logout_redirect_uri`. | A large token in the 303 `Location` breaks proxies (502 on sign-out). |
| Entra ID group overage (`_claim_names`) denies the sign-in (`sso_failed`, reason `groups_overage`). | Otherwise the missing claim would silently remove every managed membership. |
| c11 and every count (`member_count`, access list, group counts) consider active users only; c11 also leaves out service accounts. c18 keeps one active platform admin besides the break-glass account. | A deactivated admin can't administer; a project keeps a human admin; two admins demoting each other can't leave none. |
| Fixed texts instead of settings: no `SOUNDINGS_OIDC_DISPLAY_NAME_CLAIM` (always `name` → `preferred_username` → email local part) or `_BUTTON_LABEL` ("Sign in with SSO"). `_EXTERNAL_ID_KIND` defaults to the claim path's last segment. | Simple beats configurable; the documented IdPs all send `name`. |
| `.invalid` email addresses are reserved for system accounts (admin input 422; never matched or created by SSO). | The break-glass account's address can't be taken first. |
| Sign-out with the IdP is a new `POST /auth/logout/redirect` (form post → 303); `POST /auth/logout` stays 204. | No breaking change; the ID token never reaches JavaScript; SameSite=Lax protects the POST. |
| `__Host-` cookie names whenever cookies are Secure (Phase 1 review F10, deferred to now). | Blocks cookie tossing from sibling subdomains (session fixation, login CSRF) without breaking plain-http development. |
| No admin UI for SSO settings; `GET /admin/sso` shows the effective config and the URIs to register. | One provider per instance, configured with the deployment (simple beats configurable). |
| Audit details may include the IdP `issuer`/`subject` and group mapping values, never emails, names, tokens or claims. | Enough to debug a denied sign-in; no personal data. |

## 6. Room for later phases

- **Phase 3:** notifications to group-derived members work through the view; a
  "you were added to a project" email is not planned.
- **Phase 5:** API keys never reach `/admin/*` (session only); the audit viewer
  shows `api_key_id`.
- **Later, if needed:** Entra ID group overage (`_claim_names` with more than 200
  groups) is denied, not resolved through Microsoft Graph: configure "groups assigned
  to the application" in Entra. Back-channel logout, SCIM provisioning, several IdPs
  and an audit retention setting are out of scope. The sign-in throttles are per
  process (with several API replicas the limits multiply).

## 7. Changes after the contract

Builders record additive contract changes here (date, change, why), then run
`make gen-api`.

**2026-10-01, contract review** (applied before any Phase 2 endpoint was built;
regenerated `openapi.json` / `schema.d.ts` carry the schema changes):

- **Schemas:** `AuthConfig.sso` is a boolean (`SsoSignIn` and its `label` removed: the
  button text is fixed). `SsoConfig` loses `display_name_claim` and `button_label` and
  gains `discovery: SsoDiscovery | null` (§3.10). `MappingEffect` is `add | keep |
  remove` (`none` removed; additive groups that stop matching are `keep` with empty
  `matched_values`, §3.12). `GroupMember.since` → `joined_at` (as Phase 1's
  `Member.joined_at`). Schema `UserIdentity` → `LinkedIdentity` (the model keeps its
  name). `list_admin_groups` returns `GroupPage` (`cursor`, `limit`). `AuditEntry.
  target_type` and the `target_type` filter are `AuditTargetType` (`user | project |
  idea | group`). `LoginErrorCode` gains `too_many_attempts`. User emails under
  `.invalid` are a 422. Callback and `next` query parameters have no length limits
  (the flow handles them).
- **Settings:** `SOUNDINGS_OIDC_DISPLAY_NAME_CLAIM` and `_BUTTON_LABEL` removed;
  `_EXTERNAL_ID_KIND` defaults to the claim path's last dotted segment; the issuer is at
  most 512 characters; production with an issuer requires every base URL to be https.
- **Rules:** external-ID trust requirement (§3.3); a user with an external ID of the
  configured kind is never linked by email; auto-create needs a verified email; denied
  sign-ins have no actor; group overage denies; login-start throttle and live-attempt
  cap; ID token stored only up to 3,072 characters; SSO sessions need SSO configured;
  unlinking ends SSO sessions; cross-origin sign-out posts end nothing; break-glass
  hardening (IPv6 /64, `Retry-After`, 429 audited once per window, digest comparison,
  8 h / 1 h sessions); c11 and all counts consider active users only; c18
  `last_platform_admin`; group-member writes take sync's user-row lock;
  `user.groups_sync` defines added/removed and records `claim_found`; acceptance
  scenario (§3.13) no longer depends on Carol's direct TOOLS membership.
- **Migration 0003:** downgrade deletes SSO and break-glass sessions; upgrade re-marks
  an existing `break-glass@soundings.invalid` row as the break-glass account.
- **Agreed, not yet in the schema: `CurrentUser.auth_method: AuthMethod | null`**
  (required and nullable like every response field; `sso`, `break_glass`, `dev_login`;
  null only in `list_dev_users`, which has no session). Adding any field to
  `CurrentUser` breaks Phase 1 code its owners must update in the same change
  (`tests/auth/test_sessions.py` compares the dev-login JSON exactly;
  `frontend/src/mocks/domain.ts` builds `CurrentUser` literals), so the lead lands it
  with identity's session work (`start_session(auth_method=…)`) and frontend's mocks.
  Until then the break-glass banner keys on the reserved account email (§3.8).

**2026-10-01, identity build:**

- **`CurrentUser.auth_method` landed** as agreed above: `AuthMethod | null`, required in
  the schema, `sso` / `break_glass` / `dev_login` for `get_me`, `dev_login` and
  `break_glass_login`, null only in `list_dev_users`. The break-glass banner can key on
  it instead of the reserved email. Also new in the schema: the `AuthMethod` enum.
- Descriptions only: `get_me`, `dev_login`, `logout`, `get_auth_config` and the
  `session` security scheme (SSO and the `__Host-` cookie names).
- No other schema change. Behaviour as specified, with two readings made explicit:
  a callback whose `state` matches no attempt (missing, mismatched, unknown, used) is
  `login_expired` **without** an audit entry (nothing to speak of, and anonymous
  requests can't fill the log), while a found-but-expired attempt is audited as
  `login_expired`; a callback that can't fetch the provider metadata redirects with
  `sso_unavailable` and audits reason `sso_failed`.

**2026-10-01, integration:**

- No schema change (`make gen-api` leaves no diff). §3.13 now lists the realm users
  and e2e redirect URIs added by the platform build, and the seed's external IDs.
- Audit view wording only: `user.groups_sync` reads "now a synced member of …" /
  "no longer a synced member of …", since *added* includes a manual member whose
  membership only became synced (§3.6).
- Implementation note on §3.2: the OIDC client is httpx + `joserfc`
  (`app/auth/oidc.py`); the unused Authlib dependency was removed and `joserfc` is now
  a direct dependency.

**2026-10-01, security review fixes (backend, platform):**

- **Descriptions only** in the schema: `sso_login` and `sso_callback` now say the attempt
  is sealed into the `soundings_oidc` cookie (`make gen-api`: two descriptions change).
- **§3.2 (review H1): sign-in attempts are stateless.** `GET /auth/login` stores
  nothing: state, nonce, PKCE verifier, redirect URI, `next` and expiry are sealed
  (AES-256-GCM, key derived from `SOUNDINGS_SECRET_KEY` by HKDF, `app/auth/sealing.py`)
  into the HttpOnly `soundings_oidc` cookie (same name, attributes and 10 minutes). The
  10,000-live-attempts cap and `oidc_login_attempts` are gone (migration 0004), so no
  number of unfinished sign-ins locks anyone out. The callback opens the cookie and
  compares `state` (constant time); a missing, forged, changed or other-key cookie is
  `login_expired` without an audit entry, an expired one is audited `login_expired`.
  Replaying a callback after sign-in: without the (cleared) cookie `login_expired`; with
  a kept copy the IdP refuses the used code → `sso_failed` (audited). A sealed attempt
  over 3,800 characters (only a very long non-ASCII `next`) is sealed again with `next`
  = `/`. The 60-starts-per-minute throttle stays.
- **§3.2 step 3 (review N1):** `next` is also refused (→ `/`) when its path part
  (before `?`/`#`) contains `//` or a `.`/`..` segment (`%2e` counts as a dot), and
  `/api?…` counts as under `/api`. Same rule for the SPA's `safeNextPath`.
- **§3.2 step 5 (review L5):** in production every discovery endpoint
  (`authorization_endpoint`, `token_endpoint`, `jwks_uri`, `end_session_endpoint` when
  present) must be https, else discovery is `invalid` (`sso_unavailable`).
- **§3.2 step 6 (review L1):** the JWKS is fetched again when an hour old (and, as
  before, once for an unknown `kid`), so a key the IdP withdrew stops working.
- **§3.9 (review L4):** the stored ID token is sealed the same way (purpose-separated
  key); sign-out unseals it for `id_token_hint`. Migration 0004 removes plain-text ID
  tokens (those sessions sign out at the IdP without a hint).
- **Client address (review M1; §3.2 step 4, §3.8):** the app resolves
  `X-Forwarded-For` itself (`app.middleware.ProxyHeadersMiddleware`; uvicorn's proxy
  headers are off): only from `SOUNDINGS_TRUSTED_PROXIES` peers, and only the
  `SOUNDINGS_TRUSTED_PROXY_HOPS` (default 1; chart `trustedProxyHops`) rightmost
  entries, stopping at the first entry that isn't a trusted proxy; a non-IP entry ends
  the walk; a non-IP client shares the throttle key `unknown`. `trustedProxies` must be
  IPs, CIDRs or `*`. The chart turns `networkPolicy.enabled` on by default and its
  NOTES ask for `networkPolicy.ingressFrom`.
- **Tracing (review L2):** spans keep query parameter names only
  (`code=REDACTED&state=REDACTED`).
- **Reserved emails (review N2):** `.invalid` with a trailing dot is reserved too
  (`app.schemas.admin_users.is_reserved_email`, also used for the IdP `email` claim);
  no OpenAPI change.
