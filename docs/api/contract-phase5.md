# API contract: Phase 5 (API keys and MCP)

The REST contract, the MCP tool catalogue and the business rules for Phase 5 (SPEC
sections 8 and 13): personal API keys from the user's settings (name, scopes, optional
expiry, optional project restriction; shown once, stored hashed, revocable, last use
shown), the API-key principal for every REST route, Admin settings → API keys, the MCP
server at `/mcp` (streamable HTTP, stateless, API-key auth, nine tools, the same
authorisation as the API, every call audited), and proposal suggestions, which
`propose_proposal_section` creates and the owner accepts or discards in the proposal
editor. It extends [contract-phase1.md](contract-phase1.md) to
[contract-phase4.md](contract-phase4.md), whose conventions all still apply.

Source of truth, in order: the Pydantic schemas in `backend/app/schemas/` (`api_keys`,
`mcp` (the tool catalogue: not part of OpenAPI), the suggestion models in `proposals`),
the route stubs in `backend/app/api/v1/` (`api_keys`, `admin_api_keys`,
`proposal_suggestions`), the models (`app/models/api_key.py`,
`ProposalSuggestion` in `proposal.py`, the new enums `ApiKeyScope`,
`SuggestionStatus`, `SuggestionSource`) with migration `0010`, exported to
`frontend/src/api/generated/openapi.json` / `schema.d.ts` (`make gen-api`). Rules are
named as in [role-matrix.md](../role-matrix.md) (sections 5 and 6 are this phase's
authorisation spec; new condition c20); tables in [erd.md](../erd.md); the design in
[ADR 0013](../adr/0013-api-keys-and-mcp-server.md).

`backend/tests/test_contract_routes.py` pins every method, path and `operation_id` and
keeps a valid request per unimplemented route (`STUBS`, answered with 501
`not_implemented`): delete a stub row when you implement its endpoint.
`tests/authz/test_route_rules.py` names the rule of every operation;
`tests/test_schemas_phase5.py` pins the key format, the request limits and the MCP
catalogue (names, rules, scopes, argument limits, blind-evaluation fields);
`tests/test_domain_schema_phase5.py` the constraints and the downgrade of 0010.

Revised after the contract review of 2026-10-02 (before any builder started): §9 lists
what changed and why.

**Who builds what (suggested):** identity: the API-key principal source with its
throttles, the write cap, the dormant-owner and sign-in-method checks (§3.2) in
`app/auth/`, key generation, hashing and the key service in `app/api_keys/` (create,
list, revoke, the admin list, `revoke_all_for_user`), the key routes (`api_keys`,
`admin_api_keys`; the lead assigns them to identity, as Phase 2's admin routes) with
their guard tests, c20, c21, `idea.delete` / `idea.moderate` leaving the `write` scope
and the key-scope rules for routes without a rule of their own (§3.3) in `app/authz/`
(the list filters `visible_projects` / `listed_ideas` already narrow by a key's projects
and `read` scope: tests prove it), the `/mcp` authentication wrapper and Origin check
(§3.5), and the OpenAPI `api_key` bearer scheme in `app/api/deps.py` (with backend);
backend: the `mcp` dependency, the MCP server and tools in `app/mcp/` (the SDK's
low-level `Server`, mounted in `app/main.py`, §4), the `mcp.call` audit in the tool
dispatcher and its 90-day cleanup (§3.6), proposal suggestions (§3.4), deactivation
revoking keys (§3.1), a service account's submission being left out of the aggregate and
service accounts never owning an idea or holding the admin role (§3.7), `get_principal`
never falling back when a principal was stored (§3.2), `/mcp` exempt from the Host check
and `/.well-known` kept from the SPA (§3.5); frontend: Settings → API keys (with "Connect
an MCP client"), Admin settings → API keys, suggestions in the proposal editor, the
audit phrases at integration (§3.6); platform: `/mcp` through the ingress and from
other namespaces (`networkPolicy.ingressFrom`), a `make mcp-smoke` (key → initialize →
search → submit → revoke → 401) in `k3s-smoke` that also calls the Service URL from a
pod in the cluster; qa: §3.8 and the acceptance §3.9 as API and e2e tests.

## 1. Conventions (new in Phase 5)

| Topic | Rule |
|---|---|
| Additive only | New endpoints, schemas and tables only. No existing response model gains a field and no enum the SPA maps exhaustively gains a value: the three new audit actions (`api_key.create`, `api_key.revoke`, `mcp.call`) are **agreed but not yet in `AuditAction`** and land in one integration step with the SPA's phrases (§3.6), as in Phase 4. Permission flags the SPA needs come with the new lists (`ApiKeyList.can_create`, `ProposalSuggestionList.permissions`), not as new fields on old models. |
| Keys are a principal source | A request with `Authorization: Bearer <key>` is authenticated by the API-key source (§3.2), before the session cookie. The resulting principal is the key's owner, **live**, narrowed by the key's scopes and project restriction (role matrix §5); every route and tool goes through the same policy (ADR 0010). Nothing checks "is this a key?" except the policy and the session-only rules. |
| Key management is session only | `api_key.manage_own` and `api_key.manage_any` are session-only rules: a key can't list, create or revoke keys (403 `insufficient_scope`), so a leaked key can't mint another. |
| No CSRF with a key | A request authenticated by a key needs no `X-CSRF-Token`: browsers can't attach an `Authorization` header cross-site without a CORS preflight, which the API never grants. A request with both a key and a session cookie is authenticated by the **key** (the cookie is ignored). |
| MCP is not REST | `/mcp` is JSON-RPC over streamable HTTP, outside `/api/v1` and the OpenAPI document. Its contract is §4 and `app/schemas/mcp.py`. Its HTTP-level errors (before JSON-RPC) are problem+json like the API's. |
| Same authorisation, built once | MCP tools call the same services as the REST endpoints (the policy, `load_idea`, the idea and evaluation builders, `save_my_evaluation`'s service, comments, proposals), so blind evaluation, holds, c-conditions and locking are the API's by construction (§4.2). |
| Privacy | Never log, audit, trace or return a key after creation (only its `prefix` and id), the `Authorization` header, `secret_hash`, or MCP tool arguments (queries, idea text, comments may hold personal data). Audit entries carry ids, rule names, tool names, decisions and codes (§3.6). |
| Order of checks | REST, as before: 401 → 404 → 403 → 422 → 409 (→ 429). A key's restriction is part of 404 and its scopes come first in 403 (role matrix §2). Key routes (§2): 401 → 422 shape → 403 (`insufficient_scope` with a key; c20) → 404 → 422 business (`invalid_project`) → 409. Admin key routes: Phase 2's admin order (401 → 422 shape → 403 → 404). `/mcp`: §3.5. |

## 2. Endpoints

Common errors (401, 403 `csrf_failed`, 422 `validation_error`, 400 `invalid_cursor`) are
not repeated per row. "Session only" = never through an API key (role matrix §5).

### Your API keys (`tags: api-keys`, session only)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /me/api-keys` | `list_my_api_keys` | `api_key.manage_own` | → `ApiKeyList {items: [ApiKey], max_keys, can_create}`; keys that aren't revoked, newest first, not paged (≤ 25) | 403 `insufficient_scope` (a key) |
| `POST /me/api-keys` | `create_my_api_key` | `api_key.manage_own` (c20), `project.view` per restricted project | `ApiKeyCreate {name, scopes, expires_at?, project_ids?}` → 201 `CreatedApiKey {key: ApiKey, secret}` (`read` added to `write` and `evaluate`), `Cache-Control: no-store`; audited `api_key.create` (§3.1) | 403 `insufficient_scope`, `break_glass_account` (c20); 409 `too_many_api_keys`, `api_key_name_taken`; 422 `invalid_project` |
| `DELETE /me/api-keys/{key_id}` | `revoke_my_api_key` | `api_key.manage_own` | → 204; idempotent for a revoked key; audited `api_key.revoke` | 403 `insufficient_scope`; 404 (unknown or someone else's) |

### Admin settings → API keys (`tags: admin`, session only)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /admin/api-keys?q=&user_id=&state=&cursor=&limit=` | `list_admin_api_keys` | `api_key.manage_any` | → `AdminApiKeyPage {items: [AdminApiKey], next_cursor, total}`: keys that aren't revoked, of every user (service accounts included), newest first; `q` matches part of the key name or the owner's name or email (any case), or **exactly** a key's prefix (`sdg_` + lookup id) or lookup id, so a leaked key can be found; `state` `active`, `expired` or `dormant` | 403 |
| `DELETE /admin/api-keys/{key_id}` | `revoke_admin_api_key` | `api_key.manage_any` | → 204; idempotent; audited `api_key.revoke` (target: the owner) | 403; 404 |

### Proposal suggestions (`tags: proposals`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /ideas/{idea}/proposal/suggestions` | `list_proposal_suggestions` | `proposal.view` (flags from `proposal.suggest_section`, `proposal.write`) | → `ProposalSuggestionList {items: [ProposalSuggestion], permissions {can_suggest, can_decide}}`: pending ones, template order then oldest first, not paged (≤ 50) | 404 (also: no proposal) |
| `POST /ideas/{idea}/proposal/suggestions` | `create_proposal_suggestion` | `proposal.suggest_section` (c7) | `ProposalSuggestionCreate {section_key, body_md (verbatim, 1–20,000, not blank), base_version?}` → 201 `ProposalSuggestion` (`source: api`, or `ai` for a service account) (§3.4) | 403; 404 (no proposal); 422 `validation_error` (`base_version` above the section's); 409 `proposal_not_available`, `too_many_suggestions`, `project_archived`, `awaiting_moderation` |
| `POST /ideas/{idea}/proposal/suggestions/{suggestion_id}/accept` | `accept_proposal_suggestion` | `proposal.write` (c7) | `ProposalSuggestionAccept {base_version}` → `AcceptedProposalSuggestion {suggestion, section}` (§3.4) | 403; 404; 409 `proposal_conflict` (`ProposalConflictProblem` with `current`), `suggestion_not_pending`, `proposal_not_available`, `project_archived`, `awaiting_moderation` |
| `POST /ideas/{idea}/proposal/suggestions/{suggestion_id}/discard` | `discard_proposal_suggestion` | `proposal.write` (c7) | no body → `ProposalSuggestion` (`status: discarded`); idempotent for a discarded one; accept's locks (§3.4) | 403; 404; 409 `suggestion_not_pending` (accepted), `proposal_not_available`, `project_archived`, `awaiting_moderation` |

### Unchanged endpoints with new behaviour

- **Every signed-in REST route** accepts `Authorization: Bearer <key>` (§3.2) and answers
  for the key's owner narrowed by the key (§3.3): 403 `insufficient_scope` for a rule the
  key's scopes don't grant or a session-only rule; 404 for a project outside its
  restriction; lists and counts only inside it; 429 `too_many_attempts` past the key's
  request or write rate. Permission flags in responses (`IdeaPermissions`,
  `ProjectPermissions`, `ProposalPermissions`, …) are computed for that principal, so
  they reflect the key (`can_edit` is false for a `read` key, `can_delete` for any key).
- **Routes without a rule of their own** need the `read` scope with a key: `get_me`,
  `get_my_work`, `list_my_owned_ideas`, `global_search`. The inbox and the bell
  (`list_notifications`, `get_notification_summary`, `mark_notification_read`,
  `mark_all_notifications_read`) are **session only** (403 `insufficient_scope`), like
  the preferences already were.
- `update_admin_user` with `is_active: false` also **revokes every key** of that user
  (each audited `api_key.revoke`, `reason: deactivated`, same transaction).
- `end_user_sessions` ("Sign out everywhere") ends sessions only: keys keep working. Its
  confirmation in the SPA says so and links to Admin settings → API keys for that user
  (`?user_id=`); revoking is a separate, deliberate step.
- **Service accounts never own an idea or hold the admin role** (§3.7): `set_idea_owner`
  with a service account → 422 `assignee_not_eligible` (c4); `volunteer_as_owner` by a
  service account's key → 403 `forbidden` (c21); `add_project_member` /
  `update_project_member` with `role: admin` for a service account → 409
  `system_account` (as Phase 2 refuses it the platform-admin flag). Groups never contain
  service accounts (Phase 2), so no grant can make one an admin.
- `/.well-known/*` is the API's, not the SPA's: 404 problem+json (no OAuth metadata;
  keys are issued in the app), so an MCP client probing for OAuth after a 401 gets a
  clean 404 instead of `index.html`.
- `save_my_evaluation` (and MCP `submit_evaluation`) by a **service account**: its first
  submission sets `include_in_aggregate = false` (role matrix §3 rule 10: AI evaluations
  are left out by default; `evaluation.include_ai` changes it in Phase 6). A person's
  evaluation stays included.
- Public routes (`public.*`, `self.unsubscribe`, branding reads) ignore keys and sessions
  alike, as before.

## 3. Business rules

Tests first (lead's quality bar) for: 3.2 (authentication: every refusal, throttles,
revocation and expiry immediacy), 3.3 (every rule × scope × restriction × owner role,
live narrowing, session-only rules), 4.2–4.4 (every tool's authorisation, blind
evaluation and holds), 3.6 (audit completeness). §3.8 lists the minimum cases.

### 3.1 Keys: format, storage and lifecycle

- **Format:** `sdg_` + **lookup id** (12 base62 characters) + `_` + **secret** (40 base62
  characters, about 238 bits), e.g. `sdg_Ab12Cd34Ef56_9xQ…` (57 characters;
  `API_KEY_PATTERN`). Both parts come from `secrets` (CSPRNG). The prefix makes a key
  recognisable to people and to secret scanners (a custom pattern for GitHub push
  protection or gitleaks: `sdg_[A-Za-z0-9]{12}_[A-Za-z0-9]{40}`).
- **Stored:** `lookup_id` in clear (unique; a collision on insert is retried with a new
  one) and `secret_hash` = SHA-256 (hex) of the **whole key string**. A fast hash is
  right here: the secret is random and long, so there is nothing to brute-force, and a
  pepper derived from the secret key would make rotating `SOUNDINGS_SECRET_KEY` revoke
  every key. The key itself is never stored, logged or returned again.
- **Shown once:** `create_my_api_key` answers 201 `CreatedApiKey` whose `secret` is the
  full key, with `Cache-Control: no-store`. The SPA shows it in a dialog with Copy and
  "I've copied it", never puts it in a URL, a toast, localStorage or a draft, and drops
  it when the dialog closes (including `reset()` on the create mutation, so the secret
  leaves React Query's cache). Afterwards the key is shown by `prefix` (`sdg_` + lookup
  id).
- **Name:** 1–80 characters, one line (`SingleLine`), unique per owner among keys that
  aren't revoked, case-insensitively (409 `api_key_name_taken`; checked under the
  owner's `users` row lock with the count below, backed by `uq_api_keys_user_id_name_lower`).
- **Scopes:** 1–4 of `read`, `write`, `evaluate`, `mcp` (role matrix §5), stored distinct
  in canonical order. **`write` and `evaluate` include `read`:** their responses return
  readable data (the changed idea, your saved evaluation, the MCP results), so pretending
  otherwise would mislead; the API adds `read` to such a key when it is created
  (`canonical_scopes`; `ck_api_keys_scopes_include_read` backs it). Otherwise scopes
  don't imply each other (`mcp` only opens `/mcp`). The SPA offers presets: "Read only"
  (`read`), "MCP client" (`read`, `mcp`), "AI evaluator" (`read`, `evaluate`, `mcp`),
  "Full access" (all four); ticking `write` or `evaluate` ticks and locks `read`
  ("Included").
- **Project restriction:** `project_ids` null = every project the owner can access, now
  and later; else 1–50 projects, each one the owner can view **now** (`project.view`;
  otherwise, and for unknown ids, 422 `invalid_project`, without saying which). Stored
  as `uuid[]`; a deleted project's id simply matches nothing, so a restriction never
  widens. Archived projects may be chosen (read-only anyway).
- **Expiry:** `expires_at` null (never) or 1 hour to 366 days ahead, with an offset
  (422 otherwise). From that instant every request with the key is 401; the key stays
  listed as `expired` (it counts towards the limit) until revoked. No renewal: create a
  new key.
- **Immutable:** name, scopes, restriction and expiry can't change; create another key
  and revoke the old one (simple beats configurable; a changed key would surprise
  whoever holds it).
- **Limit:** at most 25 keys per user that aren't revoked (409 `too_many_api_keys`:
  "Revoke keys you no longer use."). Counted under a `FOR NO KEY UPDATE` lock on the
  owner's `users` row, so two parallel creates can't both pass. After taking the lock the
  create re-reads the owner's `is_active`: deactivation updates that row, so the two
  serialize; a deactivation that committed first wins (401, nothing created), and one
  that commits later revokes the new key with the others (its revoke runs after its
  `users` update).
- **Created with a sign-in method:** `created_auth_method` stores the creating session's
  `auth_method`. The key works only while that method is available
  (`app.services.sessions.method_available`), like that method's sessions: a key made in
  a dev-login session stops when dev login is turned off, an SSO-made key while SSO isn't
  configured. (Break-glass sessions can't create keys at all: c20.)
- **Revocation:** sets `revoked_at` and `revoked_by_id` (the owner, an admin, or the
  admin who deactivated the owner); the row stays so audit entries can name the key, and
  is never listed again. **Immediate:** authentication reads the row on every request
  (no cache), so the next request with the key, REST or `/mcp`, is 401; a request
  already past authentication finishes.
- **Owner changes are live:** the key acts with the owner's roles, platform-admin flag
  and group memberships **as they are at each request**; a demoted owner's key loses
  access at once. **Deactivating** the owner revokes all their keys (§2); a key whose
  owner is inactive or is the break-glass account never authenticates anyway.
  Deleting a user (not a feature) deletes their keys.
- **Owners who stop using Soundings** (`API_KEY_OWNER_IDLE_LIMIT`, 30 days): group sync
  and identity-provider removals only take effect at sign-in, and someone who has left
  never signs in again. So a **person's** key authenticates only while the owner's
  `users.last_seen_at` (moved by any session request that keeps a session alive) is
  within 30 days; null counts as never. Past that the key is `dormant`: 401, listed with
  that state, and working again as soon as the owner signs in (which also refreshes their
  groups). Service accounts never sign in and are exempt. Settings → API keys says so
  in one line ("Keys pause when you haven't signed in for 30 days; signing in
  reactivates them").
- **Last used:** `last_used_at` is set on successful authentication when it is null or
  older than one minute (`LAST_USED_THROTTLE`), for REST and `/mcp` alike in the key
  source's **own short transaction**, committed at once (so the key row is never locked
  for the whole request and a revoke never waits behind it). Key use doesn't touch the
  owner's `users.last_seen_at` ("last seen in the app"). No IP address is stored.
- **c20:** the break-glass account can't create keys (403 `break_glass_account`): a key
  would outlive the emergency and keep working after SSO is configured, when break-glass
  sessions stop. Its list is empty with `can_create: false`.
- Not audited: last-used updates and refused authentications (logged, §3.2).

### 3.2 Authenticating with a key (the API-key principal source)

`app.auth.sources.ApiKeySource` is first in `PRINCIPAL_SOURCES`; the session source
follows. For each request:

1. **Header:** the `Authorization` header with scheme `Bearer` (case-insensitive). No
   such header → this source answers `None` (the session source runs). Other schemes
   (`Basic`, set by an ingress, for instance) are ignored too. A bearer token is ours:
   it never falls through to the session.
2. **Format:** the token must match `API_KEY_PATTERN` (≤ 57 characters) → else a
   failure, without a database query.
3. **Lookup:** the row by `lookup_id`, with its owner; then
   `hmac.compare_digest(sha256(token), secret_hash)`. No row or no match → a failure.
4. **Usable:** not revoked; not expired (`expires_at > now()`); owner active and not the
   break-glass account; `created_auth_method` available (§3.1); for a person (not a
   service account), `users.last_seen_at` within `API_KEY_OWNER_IDLE_LIMIT` (§3.1) →
   else a failure. A service account's key is usable (service accounts never sign in;
   keys are their only credential).
5. **Failures and the throttle:** a failure is 401, and counts towards at most 30 failed
   key authentications per client address (IPv6: per /64;
   `app.auth.throttle.client_key`, the trusted-proxy-aware address) per minute, per API
   process (`API_KEY_FAILURES_PER_MINUTE`). Over the limit, for the rest of the minute,
   a **failing** key from that address is answered 429 `too_many_attempts` with
   `Retry-After` instead of 401, while a **valid** key from it still works: one script
   retrying a revoked key behind a shared NAT can't lock out its neighbours. (A
   well-formed key costs one indexed lookup either way; malformed ones none.)
6. **Principal:** `Principal(user, auth="api_key", scopes=frozenset(key.scopes),
   project_ids=None if key.project_ids is None else frozenset(key.project_ids),
   api_key_id=key.id, auth_method=None)`. Never `frozenset(...) or None`: an empty set
   must stay "no project", not become "every project" (the database refuses empty and
   NULL-holding restrictions as well).
7. **Per-key rates:** at most 300 requests per key per minute, REST and `/mcp` together
   (`API_KEY_REQUESTS_PER_MINUTE`), and at most 30 **writes** per key per minute
   (`API_KEY_WRITES_PER_MINUTE`: REST requests with `POST`, `PUT`, `PATCH` or `DELETE`
   and MCP calls of tools that aren't read-only), per API process → 429
   `too_many_attempts` with `Retry-After` (an MCP tool call gets the tool error
   `too_many_attempts`), logged with the key id. The write cap bounds a runaway or
   prompt-injected agent (300 comments with 20 @mentions each a minute otherwise).
8. **Last used** (§3.1, its own short transaction). **No CSRF check.**

The principal the source built is the one routes get: `get_principal`
(`app/api/v1/principal.py`) returns the principal stored on the request whenever there
is one, and builds a plain session principal only when none was stored (tests that
override `get_current_user`). It never falls back to an un-narrowed principal because
the stored one's user differs.

Every 401 from a key is the same problem (`code: unauthorized`, "The API key is
missing, invalid, expired or revoked, or its owner needs to sign in to Soundings
again.") with `WWW-Authenticate: Bearer realm="soundings"`: the response never says
which. Refusals are logged at INFO (`api key refused`, `reason` = `malformed | unknown |
mismatch | revoked | expired | inactive_owner | method_unavailable | dormant_owner`, the
key id when known, never the token); the first throttled refusal of an address in a
minute is a WARNING, later ones in that minute aren't logged. They are not audited (an
unauthenticated flood must not fill the audit log).

OpenAPI declares the scheme next to the session cookie: `HTTPBearer(scheme_name="api_key",
bearerFormat="sdg_…", auto_error=False)` on `get_current_user` (identity/backend, then
`make gen-api`; only `securitySchemes` and each operation's `security` change, not the
TypeScript types).

### 3.3 What a key may do (role matrix §5, exactly)

**Effective permission = the owner's live permission ∩ the key's scopes ∩ the key's
projects.**

- **Rules with a scope** (`app.authz.rules.RULE_SCOPES`): `read` grants `project.view`,
  `idea.view`, `user.search`, `evaluation.view_own`, `evaluation.view_others`,
  `score.view_aggregate`, `proposal.view`, `proposal.export`; `write` grants the idea,
  collaboration, ownership, evaluation-management, proposal and AI rules (`idea.create`,
  `idea.edit_*`, `comment.*`, `idea.vote`, `idea.watch`, the owner rules,
  `evaluator.manage`, `idea.set_due_date`, `evaluation.close`, `evaluation.include_ai`,
  `idea.change_status`, `proposal.*` writes including `proposal.suggest_section`,
  `ai.*`) **but not `idea.delete` or `idea.moderate`**; `evaluate` grants
  `evaluation.submit_own`; `mcp` grants `mcp.connect` only. A key with `write` or
  `evaluate` always has `read` too (§3.1). A rule the scopes don't grant → 403
  `insufficient_scope`, checked after the 404s (a key can't learn whether a hidden idea
  exists from a scope error).
- **The implied view rule** (`project.view` / `idea.view` before an idea or project
  rule, the policy's `_locate`) is the owner's, not a scope check; every key that can
  change something has `read` anyway. Blind masking (`✱`) is computed from the owner,
  not from scopes: a pending evaluator's key never gets score data, whatever its scopes.
- **Session only** (never through a key, 403 `insufficient_scope`): `project.create`,
  `project.manage_members`, `project.edit_rubric`, `project.rename_status_labels`,
  `project.edit_settings`, `public.erase_submitter`, **`idea.delete`** (a hard cascade)
  **and `idea.moderate`** (rejecting deletes; no tool moderates), `platform.*`,
  `api_key.*`, `self.manage_profile`, and the inbox routes (§2). Nothing irreversible
  happens through a key.
- **Routes without a rule:** `get_me`, `get_my_work`, `list_my_owned_ideas`,
  `global_search` need `read` (identity provides `require_key_scope(principal, "read")`
  and `require_session(principal)` in `app/authz/`; the routes call them).
- **Project restriction:** any project-scoped resource outside the key's projects is
  404 (before every other check but 401), the same as a project the owner can't see:
  ideas, proposals, evaluations, members, rubric, exports, `search_users?project=`.
  Lists, boards, counts, search, My work and `list_projects` contain only those projects
  (`app.authz.queries.visible_projects` / `listed_ideas` already add
  `project_id IN (:ids)` when `principal.project_ids` is set, and match nothing without
  `read`). Global rules are unaffected: `search_users` without `project=` finds people
  across the directory as it does for every signed-in person (names and emails, no
  project data); accepted, since the picker and @mentions need it and the restriction is
  about project data.
- **Platform admins' keys** are narrowed like anyone's: a restricted key of a platform
  admin sees only its projects; `platform.*` is session only.
- **Writes through a key** are audited exactly like the same writes in a session (the
  entry's `details.auth = "api_key"` and `details.api_key_id`, as `audit.record`
  already does), and activity and notifications name the owner as the actor. They count
  towards the key's write cap (§3.2).

### 3.4 Proposal suggestions

- **What:** the whole new text of one section. `source` follows the **author**: `ai`
  whenever the author is a service account (shown with an AI badge, whatever the
  channel; Phase 6's "Draft section" arrives this way), else the channel a person used:
  `api` (REST: the SPA or an API client) or `mcp` (an MCP client with their key). Text
  is kept verbatim like section saves (`SectionText`: not stripped, NUL refused),
  1–20,000 characters, not only whitespace.
- **Who:** `proposal.suggest_section` (members and admins, and the owner, while c7
  holds: Shortlisted or in Proposal) creates; `proposal.view` lists (everyone who can
  read the proposal sees what is pending, like margin comments); `proposal.write` (the
  owner and admins, c7) accepts or discards. Viewers and internal non-members: 403 on
  create. Archived project → 409 `project_archived`; an idea held for moderation has no
  proposal (c7 needs Shortlisted), and its writes are 409 `awaiting_moderation` (c19).
- **Needs a proposal:** creating, listing or deciding on an idea without one → 404 (the
  owner starts the proposal first).
- **`base_version`** is the section version the author read (default: the current one;
  above the current one → 422 `validation_error`); `section_changed` in responses is
  true when the section's version is now higher, and the editor says "The section has
  changed since this was suggested".
- **Create** runs under the idea lock (`load_idea(for_update=True)`: project `FOR KEY
  SHARE`, idea `FOR UPDATE`), so it never interleaves with an accept or discard (they
  hold the idea `FOR SHARE`). Under it: **one pending per author per section** (a new
  suggestion from the same author for the same section discards the earlier one,
  `decided_by` = the author, `decided_at` = now, in the same transaction;
  `uq_proposal_suggestions_pending_author_section` backs it), and at most **50 pending**
  per proposal (409 `too_many_suggestions`).
- **Accept:** `base_version` is the section version the decider is looking at. Under the
  locks of a section save (project `FOR KEY SHARE`, idea `FOR SHARE`, contract-phase4
  §3.2), the suggestion row `FOR UPDATE`: not pending → 409 `suggestion_not_pending`;
  then exactly `update_proposal_section`'s save with `body_md` = the suggestion's text
  and that `base_version` (409 `proposal_conflict` with `current`, or a no-op when the
  text is already equal), `updated_by` = the decider; then the suggestion becomes
  `accepted` with `decided_by`/`decided_at`. Other pending suggestions for that section
  stay pending (now `section_changed`).
- **Discard:** the same locks in the same order as accept (project `FOR KEY SHARE`, idea
  `FOR SHARE`, then the suggestion `FOR UPDATE`, re-reading its status), or one
  `UPDATE … SET status = 'discarded' … WHERE id = :id AND status = 'pending'
  RETURNING …`; either way a discard can never overwrite `accepted` after an accept
  changed the section. Status `discarded`, `decided_by`/`decided_at`; idempotent for a
  discarded one; 409 `suggestion_not_pending` for an accepted one.
- No notifications, activity events or audit entries in Phase 5 (the MCP call itself is
  audited, §3.6); no edits (suggest again) and no withdrawing (a new suggestion replaces
  yours; the owner discards). Suggestions carry no score data. Deleting the idea deletes
  them; decided ones are kept with the proposal.
- **The editor:** pending suggestions appear by their section ("2 suggestions") with the
  author (AI badge for `ai`), when, a preview of the proposed text against the current
  text, the `section_changed` note, and Accept / Discard for those who may decide.
  Accepting while the section has unsaved local edits asks first; a conflict shows the
  Phase 4 Reload / Keep mine choice.

### 3.5 The MCP endpoint (transport)

- **One route:** `POST /mcp` (exact path, `app.add_route`, no redirect to `/mcp/`;
  research R1 §1), served by the `mcp` SDK 2.x low-level
  `mcp.server.lowlevel.Server(...).streamable_http_app(stateless_http=True,
  json_response=True, max_request_body_size=1 MiB)` (§4.2) with its session manager's
  `run()` in the app's lifespan. **Stateless:** no `Mcp-Session-Id`, no
  server-to-client messages (no sampling, elicitation or progress), every request
  authenticated on its own, so revocation applies to the very next request. JSON
  responses (`application/json`), `Cache-Control: no-store`.
- **Other methods:** `GET` (no SSE stream), `DELETE` (no sessions), `PUT`, `OPTIONS`… →
  405 with `Allow: POST`. No CORS headers, ever.
- **Authentication:** `Authorization: Bearer <key>` only, through the same API-key
  source and throttles as REST (§3.2), in an ASGI wrapper around the SDK app; the SDK's
  own `RequireAuthMiddleware` / `TokenVerifier` isn't used, so errors are the API's
  problem+json and one code path decides. A session cookie alone is 401: `/mcp` never
  accepts cookies (so no CSRF exposure). The wrapper puts the principal in a context
  variable the tools read.
- **c15 (`mcp.connect`):** a key without the `mcp` scope → 403 `insufficient_scope` with
  `WWW-Authenticate: Bearer error="insufficient_scope", scope="mcp"`. Although
  `initialize` and `tools/list` aren't audited, a request refused by c15 is, whatever its
  JSON-RPC method (one `mcp.call` entry, §3.6).
- **Host:** `/mcp` (exactly `MCP_PATH`) is **exempt** from the app's
  `TrustedHostMiddleware`, like the probes, so Phase 6 agents in the cluster can call
  the Service directly (`http://<fullname>.<namespace>.svc.cluster.local/mcp`: the
  chart's Service, port 80) without that host being one of `SOUNDINGS_BASE_URLS`
  (which must be https in production and drive redirects and email links). What the
  Host check guards is covered here otherwise: every request needs a bearer key, the Origin check below
  stops DNS rebinding from browsers, and `url` fields come from the configured base URL,
  never the `Host` header. The SDK's own check stays off
  (`TransportSecuritySettings(enable_dns_rebinding_protection=False)`).
- **Origin (DNS rebinding):** an `Origin` header, when present, must be the origin of
  one of `SOUNDINGS_BASE_URLS` → else 403 `invalid_origin` before authentication. MCP
  clients outside browsers send none.
- **NetworkPolicy:** when `networkPolicy.ingressFrom` restricts the API to the ingress
  controller (as the values file advises), the operator adds the agents' namespace
  (kagent's) to it; the chart's values and README say so, and `make mcp-smoke` also
  calls the Service URL from a pod inside the cluster.
- **Size:** the app's 1 MiB body limit (413 `content_too_large`) applies first; the SDK
  gets the same limit. One JSON-RPC message per request (arrays are refused by the SDK,
  400). The SDK requires `Accept` to include `application/json` (406) and
  `Content-Type: application/json` (415).
- **Protocol versions:** whatever the pinned SDK supports (mcp 2.2: the `initialize`
  handshake versions 2024-11-05 to 2025-11-25, and 2026-07-28). Phase 6 checks kagent's
  client against them.
- **Order of checks:** body size (413) → method (405) → Origin (403) → key (401, or 429
  for a failing key from an address over the failure limit) → c15 (403) → per-key rate
  (429) → SDK (406, 415, 400) → JSON-RPC method → tool (§4.3, including the write cap).
  No Host check (above).
- **Not audited:** `initialize`, `notifications/initialized`, `tools/list`, `ping` (no
  data is read). Every `tools/call` is, and so is a c15 refusal (§3.6).
- **`/.well-known/*`** answers 404 problem+json from the API (§2): MCP clients that look
  for OAuth metadata after a 401 find none and report the key error.
- **Ingress:** `/mcp` reaches the API like `/api` (the chart routes `/` to the API
  service already); proxies must not buffer or time out short JSON responses (no
  streaming is used).

### 3.6 Audit

New `AuditAction` values, **agreed but not yet in the schema** (a new value breaks the
SPA's typecheck until its phrase exists: `audit-phrases.test.ts`'s exhaustive `Record`,
as in Phases 3 and 4). They land in one integration step: frontend adds the phrases, an
"API keys and MCP" category and the mock entries; identity adds the three values to
`AuditAction` (lead-owned contract, recorded in §8) in the same change; `audit.record`
refuses unknown actions until then, so builders call it only after that step (tests
can patch `AUDIT_ACTIONS`).

| Action | Actor | Target | Details (never keys, hashes, arguments or personal data) |
|---|---|---|---|
| `api_key.create` | the creator (session) | `user`: the key's owner | `rule: api_key.manage_own`, `key_id`, `prefix` (`sdg_` + lookup id: public, so a leaked key can be traced), `scopes`, `restricted` (bool), `project_ids`, `expires_at` |
| `api_key.revoke` | the owner, a platform admin, or the admin who deactivated the owner | `user`: the key's owner | `rule` (`api_key.manage_own` \| `api_key.manage_any` \| `platform.manage_users`), `key_id`, `prefix`, `reason: deactivated` for deactivation |
| `mcp.call` | the key's owner | the idea or project the call was about, when it exists (also for denials); none for lists | `tool` (a catalogue name, or `unknown`), `rule` (the tool's rule; `mcp.connect` for c15), `decision` (`allow` \| `deny`), `code` (null on success, else the tool error code), plus `auth: api_key` and `api_key_id` (added by `audit.record`) |

- **Every `tools/call` is audited**, once, whatever the outcome, by the one tool
  dispatcher (§4.2), so nothing escapes it: unknown tool names (`tool: unknown`, `code:
  unknown_tool`, `decision: deny`), arguments that fail the input model (`code:
  validation_error`, `decision: deny`), the write cap (`code: too_many_attempts`,
  `decision: deny`), policy denials (`decision: deny` with `not_found`, `forbidden` or
  `insufficient_scope`), business failures (`decision: allow` with e.g.
  `evaluation_closed`), crashes (`code: internal_error`) and successes. A c15 refusal at
  HTTP level is one entry with `tool: null`, `rule: mcp.connect`, `decision: deny`,
  `code: insufficient_scope` (audited although `initialize` and `tools/list` aren't).
- **Where it is written:** in the tool's transaction when the call commits; otherwise in
  a separate short transaction after the rollback, so denials and failures are kept.
- **Writes keep their own entries:** a call that submits an evaluation records
  `evaluation.submit` (as REST does) **and** its `mcp.call`.
- **Retention:** the hourly cleanup deletes `mcp.call` entries older than 90 days
  (`MCP_AUDIT_RETENTION`, on `ix_audit_log_action_created_at`); every other entry is
  kept as before. Agents call tools often; their call trail doesn't need to live for
  ever, the changes they made do.
- **The viewer:** filter by actor shows a person's or agent's calls; `details.tool`
  and `decision` are shown in the entry's sentence ("Ada's key called get_idea on
  CUST-12: denied (not found)"). `mcp.call` belongs to the new category.

### 3.7 Service accounts (minimum now; Phase 6 builds the UI)

- A **service account** (`users.is_service_account`) is an AI agent's user. It never
  signs in, has no identities or external IDs, is never notified, and follows every rule
  like a person: it needs a real project role, and it evaluates blind.
- **It never owns an idea and is never an admin**, so it can't accept its own
  suggestions, include its own evaluation in the aggregate, change statuses or manage
  evaluators (SPEC §9: a person stays accountable): `set_idea_owner` refuses it (c4, 422
  `assignee_not_eligible`), it can't volunteer (c21, 403 `forbidden`), and
  `add_project_member` / `update_project_member` refuse `role: admin` for it (409
  `system_account`, as Phase 2 refuses it the platform-admin flag; groups never contain
  service accounts). Phase 5 enforces this now, before any agent exists.
- **Its keys are created by platform admins**, never by itself: Phase 6's Admin → AI
  agents (`platform.manage_agents`) registers an agent, creates its service account and
  one key (scopes `read`, `evaluate`, `mcp`, plus `write` if it drafts sections or
  writes research notes), shows the key once for the operator to put in the Kubernetes
  Secret the kagent `RemoteMCPServer` reads, and offers "Rotate key" (create a new one,
  revoke the old). `api_keys.created_by_id` is that admin and `created_auth_method` the
  admin's session method (an agent key made in a dev-login session stops when dev login
  is turned off); agents' keys are exempt from the owner-idle limit. c20 covers this
  path too: the break-glass account can't create an agent's key (403
  `break_glass_account`). The admin list shows these keys with
  `owner_is_service_account`, and `revoke_admin_api_key` covers them. Until Phase 6
  tests create service accounts and their keys through the service layer.
- **Restrict agent keys to the projects the agent serves.** One agent account shared by
  many projects is a path for prompt injection: text planted in project A can make the
  agent read project B and write it into A (a comment, a suggestion). Phase 6's
  registration sets the key's project restriction to the projects the agent is a member
  of and lets an operator register one agent per project (one service account and key
  each) where projects must not leak into each other; the server instructions tell
  agents never to copy text between projects.
- **Project access:** project admins add the agent as a **member** (or viewer; never
  admin, above; c11 doesn't count service accounts anyway) through the member picker,
  which lists agents from Phase 6.
- **Its evaluations** are left out of the aggregate by default (§2), carry `is_ai`, and
  suggestions it makes have `source: ai` (REST or MCP).
- Deactivating a service account revokes its keys (§3.1).

### 3.8 Minimum tests (tests first)

- **Authentication:** a valid key → the owner; missing, malformed (each `API_KEY_PATTERN`
  variant), unknown lookup id, wrong secret (same lookup id), revoked, expired (one second
  past), inactive owner, break-glass owner, a dev-login key with dev login off, an SSO
  key without SSO, a person whose `last_seen_at` is 30 days and a second old (or null)
  → 401 with the same body and `WWW-Authenticate`; the same dormant key works again
  after its owner signs in; a service account's key works with `last_seen_at` null;
  `Basic` falls through to the session; `Bearer` + session cookie → the key decides (a
  revoked key with a valid cookie is 401); no CSRF needed with a key, still needed with
  the cookie alone; after 30 failures from one address in a minute a failing key → 429
  and a valid key from that address still → 200; the 301st request of one key → 429;
  the 31st write of one key in a minute → 429 (REST) and `too_many_attempts` (MCP),
  while its reads still work; `last_used_at` moves at most once a minute, in its own
  transaction (a revoke doesn't wait for a slow request); revoke then the very next
  request → 401 (REST and `/mcp`); a demoted owner's key loses the rule on the next
  request; a re-promoted owner's key regains it; `get_principal` returns the stored
  key principal (never a widened session principal).
- **Scopes:** for every rule in `RULE_SCOPES`, a key whose only scopes are that rule's
  scope (plus `read`, which `write` and `evaluate` include) is allowed (as the owner
  would be) and a key without that scope gets 403 `insufficient_scope`; creating a key
  with `write` or `evaluate` stores `read` too; every session-only rule (including
  `idea.delete` and `idea.moderate`) is 403 for a key with all four scopes; `get_me`, My
  work, owned ideas, search need `read`; the inbox routes are 403 for any key; key routes
  and admin routes are 403 for any key.
- **Restriction:** a key restricted to project A: B's project, ideas, proposal, export,
  members, rubric → 404; lists, board, search, My work, `list_projects`, counts contain
  only A; `search_users?project=B` → 404; a platform admin's restricted key likewise; a
  key restricted to a project later deleted reaches nothing.
- **Owner roles:** the matrix's columns (PA, PAd, Mem, Vwr, NMi, NMp) × the overlays
  (owner, evaluator) for each scope, through a key, equal the session result narrowed by
  the scope.
- **Key lifecycle:** shown once (no endpoint ever returns `secret` again; the list has
  `prefix` only); name taken (any case) → 409, free again after revoke; the 26th key →
  409 and two parallel creates at 24 → one 409; a create racing the owner's deactivation
  leaves no usable key; `invalid_project` for an unknown project and a private project
  the owner isn't in, alike; expiry bounds; break-glass → 403 `break_glass_account`;
  `created_auth_method` = the session's method; deactivation revokes and audits; admin
  list filters (`state=dormant` included) and `total`; `q` = a prefix or lookup id finds
  exactly that key; admin revoke of a service account's key.
- **Service accounts:** `set_idea_owner` with one → 422 `assignee_not_eligible`;
  `volunteer_as_owner` with its key → 403; `add_project_member` / `update_project_member`
  with `role: admin` → 409 `system_account` (member and viewer work).
- **MCP:** §4.6.
- **Suggestions:** every column for create, list, accept and discard (c7, archived,
  held, no proposal); one pending per author and section (the old one discarded); the
  51st → 409; a `base_version` above the section's → 422; accept with a stale
  `base_version` → 409 `proposal_conflict` with `current`, with equal text → no version
  bump; accept/discard twice; a discard racing an accept never turns `accepted` into
  `discarded`; `source` per author and channel (`api`, `mcp`, and `ai` for a service
  account through REST or MCP).
- **Audit:** each of the three actions with its details (`prefix` included); one
  `mcp.call` per `tools/call` for every outcome above (and none for `tools/list`, one for
  a c15 refusal); a denied call's entry survives the rollback; no entry or log line contains a key, a hash, an `Authorization`
  header or a tool argument; the 90-day cleanup removes only old `mcp.call` entries.

### 3.9 Acceptance (SPEC Phase 5): an MCP client with a key can search ideas and submit an evaluation only in permitted projects; revoking the key cuts access immediately

1. Carol (demo seed: member of Customer Innovation and Internal Tools) is invited to
   evaluate one idea in each project (`CUST-n`, `TOOLS-m`; the test invites her, with
   two other evaluators already submitted on `CUST-n`). In Settings → API keys she
   creates "Claude Desktop" with `read`, `evaluate`, `mcp`, restricted to Customer
   Innovation; the key is shown once.
2. An MCP client (the Python SDK client in the acceptance test; `make mcp-smoke` with
   curl JSON-RPC) connects to `/mcp` with the key: `initialize`, `tools/list` (nine
   tools), `list_projects` (only Customer Innovation), `search_ideas
   awaiting_my_evaluation=true` (`CUST-n` only, `score_hidden: true`, no score).
3. `get_idea CUST-n` shows no other evaluations and no aggregate; `get_rubric`;
   `submit_evaluation` with every criterion → submitted; `get_idea` now shows the two
   other submitted evaluations and the aggregate.
4. `get_idea TOOLS-m` and `submit_evaluation` on `TOOLS-m` → `not_found` (outside the
   restriction), although Carol may evaluate it in the app; `create_idea` in Customer
   Innovation → `insufficient_scope` (no `write`; in Internal Tools it would be
   `not_found`).
5. The audit log shows each call (`mcp.call`, with decisions) and Carol's
   `evaluation.submit` through the key.
6. Carol revokes the key in Settings; the client's next `tools/call` (and a REST call
   with the key) → 401.

### 3.10 Screens (frontend)

Calm and Linear-like (SPEC section 5): design-system components only, loading, empty and
error states, dark mode, keyboard, 390 px.

- **Settings → API keys** (personal settings, next to Notifications): one row per key:
  name, `prefix…` in monospace, scope chips, "All projects" or the project names,
  expiry ("Never", a date, or an "Expired" badge), last used ("Never used" or a relative
  time). Empty state: "No API keys yet. Create one to use the API or connect an MCP
  client." **Create key** (disabled with a reason when `can_create` is false: "You have
  25 keys. Revoke one you no longer use." / not for the break-glass account): name;
  scopes as checkboxes with one-line explanations and the presets of §3.1 (`read` ticked
  and locked, "Included", while `write` or `evaluate` is ticked); expiry (30 days, 90
  days, 1 year, never, or a date); projects ("All projects I can access" or "Only
  these", a multi-select of projects you can view). One muted line under the list: "Keys
  pause when you haven't signed in to Soundings for 30 days; signing in reactivates
  them." Then the **secret dialog**: the full key once, Copy, "Store it somewhere safe:
  you won't see it again", Done (focus returns to the new row; the create mutation is
  `reset()` so the secret leaves the query cache). **Revoke** asks first ("Revoke "Claude Desktop"?
  Anything using it stops working immediately.") because the row disappears; no Undo.
  **Connect an MCP client:** the server URL (`<origin>/mcp`), the header
  (`Authorization: Bearer <your key>`) and a copyable JSON example for clients that take
  an `mcpServers` map with `type: "http"`, `url` and `headers`.
- **Admin settings → API keys:** a table (cards at 390 px) of every key that isn't
  revoked: owner (AI badge for service accounts), name, prefix, scopes, projects,
  created, last used, expires, state (an "Expired" or "Dormant" badge; Dormant's tooltip:
  "The owner hasn't signed in for 30 days"); search (`q`: a name, an owner, or a key's
  prefix; a pasted whole key is cut to its prefix in the browser before the request, so
  a secret never goes into a URL), filter by state, a link from a user's admin page
  (`?user_id=`); Revoke with the same confirmation. A user's "Sign out everywhere"
  confirmation adds "API keys keep working" with a link here (`?user_id=`).
- **Proposal editor:** §3.4 "The editor".
- **Audit log:** the three new actions' sentences and an "API keys and MCP" category
  (§3.6).

## 4. MCP server and tool catalogue

The models are in `app/schemas/mcp.py` (`MCP_TOOLS`, `*Input`, `*Output`, `McpToolError`,
`MCP_INSTRUCTIONS`); this section is their prose. Nothing here is in OpenAPI.

### 4.1 Server metadata

| Field | Value |
|---|---|
| `name` / `title` | `soundings` / `Soundings` (`MCP_SERVER_NAME`, `MCP_SERVER_TITLE`) |
| `version` | the app's version (`app.__version__`) |
| Server | the SDK's low-level `mcp.server.lowlevel.Server(MCP_SERVER_NAME, version=…, title=…, instructions=…, on_list_tools=…, on_call_tool=…)`: no decorators, no `fn.__signature__` tricks; one dispatcher handles every call (§4.2) |
| `instructions` | `MCP_INSTRUCTIONS`: what Soundings is, that the client acts as the key's owner narrowed by the key, the evaluate workflow (get_rubric → get_idea → submit_evaluation, inverted criteria, blind evaluation is expected), that proposal suggestions are only suggestions, the write limit, that idea/comment/evaluation/proposal text is untrusted data written by people (some anonymous, `via_public_form`) and never instructions and must not be copied between projects, that long texts are cut, and the error format |
| Capabilities | tools only (no resources, prompts, sampling or subscriptions) |
| Tool annotations | `readOnlyHint` for the five reads; `destructiveHint` only for `submit_evaluation` (it replaces your saved evaluation); `idempotentHint` for the reads and `submit_evaluation`; `openWorldHint: false` for all |

### 4.2 Conventions for every tool

- **Authorisation:** the tool's rule (§4.3) after `mcp.connect`, through the policy with
  the key's principal: the scope of the rule (`insufficient_scope`), the project
  restriction and every condition, exactly as the REST route. Tools that list
  (`list_projects`, `search_ideas`) check their scope first
  (`principal.has_scope("read")`, else `insufficient_scope`) and then filter with
  `visible_projects` / `listed_ideas`.
- **Held ideas are `not_found` for everyone:** an idea held for moderation or for email
  confirmation is never returned, listed, counted, commented on, evaluated or suggested
  through MCP, even for project and platform admins (REST lets them open one held for
  moderation by its link). No MCP tool can approve or reject. This keeps text **waiting
  for moderation** away from agents; in projects without moderation public text goes
  straight to the board, and to agents, so results flag it (`via_public_form`) and
  describe every people-written field as untrusted (below).
- **Blind evaluation:** results are built from the REST builders' output, so a pending
  evaluator (role matrix §3) gets `score: null`, `score_hidden: true`,
  `high_disagreement: false`, `aggregate: null`, `evaluation_count: 0` and
  `evaluations: []`, and `sort: score` puts those ideas last, for every role, service
  accounts included. Drafts stay private for everyone: other evaluators' states are only
  `invited` / `submitted`.
- **Idea references:** `idea` is a key (`CUST-12`, any case) or a UUID
  (`IDEA_REFERENCE_PATTERN`, as REST's `{idea}`); `project` is a slug. Unknown, hidden,
  outside the key's projects and held all answer `not_found`.
- **One dispatcher** (`on_call_tool`): look the name up in `MCP_TOOLS` (else
  `unknown_tool`), validate `arguments` with the tool's `*Input` model (else
  `validation_error`, the message naming the fields, never their values), check the
  key's write cap for tools that aren't read-only (`too_many_attempts`), run the tool in
  its transaction, turn a `ProblemError` into a tool error and anything else into
  `internal_error` (logged with the traceback), and write exactly one `mcp.call` audit
  entry (§3.6). `tools/list` (`on_list_tools`) returns the catalogue: `inputSchema` =
  `tool.input.model_json_schema()`, `outputSchema` =
  `tool.output.model_json_schema(mode="serialization")`, title, description and
  annotations (§4.1), so the published schemas are the models by construction.
- **Arguments:** each `*Input` model is the tool's whole argument contract. The write
  tools' models **subclass the REST request models** (`CreateIdeaInput(IdeaCreate)`,
  `AddCommentInput(CommentCreate)`, `SubmitEvaluationInput(MyEvaluationIn)`,
  `ProposeProposalSectionInput(ProposalSuggestionCreate)`) and add the idea or project,
  so limits, tag de-duplication (`["A", "a"]` → `["A"]`), verbatim proposal text and
  cross-field rules are REST's; the tool passes the validated model to the REST service
  as its body. Strings are stripped (proposal text excepted) and NUL is refused; unknown
  top-level arguments are ignored (`MCP_INPUT_CONFIG`), nested REST models (score
  entries) still refuse unknown fields. `submit_evaluation`'s `submit` defaults to
  **true** (REST's to false): an agent's evaluation is meant to count.
- **Results:** the `*Output` model as `structuredContent` (snake_case, every field
  present), and the same JSON as one text content block (for clients without structured
  content). `url` fields are `<public base URL>/ideas/<KEY>` (the configured base URL,
  never the `Host` header). **Bounded:** `get_idea` returns at most `COMMENTS_MAX` (20,
  default 10) comments and the latest `MCP_EVALUATIONS_MAX` (25) evaluations with
  `evaluation_count` for all; comment bodies and evaluations' overall comments longer
  than `MCP_TEXT_LIMIT` (2,000 characters) are cut there with `truncated: true` (the
  idea's description, at most 50,000 characters, is returned whole).
- **Untrusted text:** every field people write (`title`, `summary`, `description_md`,
  `tags`, comment and evaluation comments, proposal sections' `body_md`, project
  `description`) carries `UNTRUSTED` in its output-schema description, and the
  descriptions of `search_ideas`, `get_idea` and `get_proposal` say the same; ideas from
  the public form say so in search results too (`via_public_form` on `McpIdeaSummary`).
- **Errors** are tool results with `isError: true`, `content: [{type: "text", text:
  "<code>: <message>"}]` and `structuredContent: {code, message}` (`McpToolError`;
  clients validate `structuredContent` against `outputSchema` only for successful
  results). `code` is the REST problem code for the same failure (map `ProblemError.code`
  and `.detail`), or `unknown_tool` / `internal_error`; the message is the problem's
  `detail`.
- **Transactions:** each `tools/call` is one unit of work (`session_scope(...,
  settings=settings)`, so before-commit hooks fan out notifications with email on),
  committed on success, rolled back on any error. Writes take the same locks as REST
  (`load_idea(for_update=True)` …).
- **Pagination** (`search_ideas`): `limit` 1–50 (default 20), `cursor` = the previous
  page's `next_cursor`, opaque and validated on decode like REST cursors (not bound to
  the other arguments, as REST's aren't: reused with other filters it just continues
  from its position); one that isn't ours → `invalid_cursor`.

### 4.3 The tools

| Tool | Rule | Scope | Arguments (`*Input`) | Result (`*Output`) |
|---|---|---|---|---|
| `list_projects` | `project.view` (as a filter) | `read` | `include_archived` (false) | `projects: [McpProject {id, slug, key, name, description, visibility, my_role, archived, idea_count, can_create_ideas}]` by name |
| `search_ideas` | `idea.view` (as a filter); scores per `score.view_aggregate` | `read` | `query` (1–200: title or summary text, or a key), `project` (slug), `status` (1–5 statuses), `owner` (`me` \| `none`), `awaiting_my_evaluation` (false), `sort` (`IdeaSort`, default `-updated`), `cursor`, `limit` (1–50, 20) | `items: [McpIdeaSummary]` (with `via_public_form`), `next_cursor` |
| `get_idea` | `idea.view`; evaluations per `evaluation.view_others`, aggregate per `score.view_aggregate`, own evaluation per `evaluation.view_own` | `read` | `idea`, `comment_limit` (0–20, 10) | `idea: McpIdeaDetail` (bounded, §4.2) |
| `get_rubric` | `project.view` | `read` | `project` **or** `idea` (exactly one) | `project`, `criteria: [RubricCriterion]`, `score_min: 1`, `score_max: 5`, `recommendations` |
| `get_proposal` | `proposal.view` (`can_suggest` from `proposal.suggest_section`) | `read` | `idea` | `idea: McpIdeaRef`, `proposal: McpProposal \| null`, `can_suggest` |
| `create_idea` | `idea.create` | `write` | `IdeaCreate` (`title` 1–200, one line; `summary` 1–500; `description_md` ≤ 50,000; `tags` ≤ 10, merged in any case) + `project` | `idea: McpIdeaRef` |
| `add_comment` | `comment.create` | `write` | `CommentCreate` (`body_md` 1–10,000; @mention tokens as REST) + `idea` | `idea`, `comment: McpComment` |
| `submit_evaluation` | `evaluation.submit_own` | `evaluate` | `MyEvaluationIn` (`scores: [{criterion_id, score 1–5 \| null, comment ≤ 1,000}]` ≤ 6, each criterion once; `recommendation` `go` \| `maybe` \| `no`; `comment` ≤ 4,000; `submit`, here default **true**) + `idea` | `idea`, `evaluation: McpMyEvaluation` |
| `propose_proposal_section` | `proposal.suggest_section` | `write` | `ProposalSuggestionCreate` (`section_key`; `body_md` verbatim, 1–20,000, not blank; `base_version` ≥ 1, default the current one) + `idea` | `idea`, `suggestion: ProposalSuggestion`, `replaced_suggestion_id` |

Notes per tool:

- **`list_projects`:** projects the owner can view (`project.view`: member, admin,
  internal non-member, platform admin) ∩ the key's projects; archived ones only with
  `include_archived`. `idea_count` counts listed ideas only. `can_create_ideas` =
  `idea.create` for this principal (needs `write`; false in archived projects).
- **`search_ideas`:** across every project the key reaches, or one (`project` outside
  the key's reach → `not_found`). `query` uses REST's `q` semantics (ILIKE on title and
  summary, or an exact key first). `awaiting_my_evaluation`: assigned to the owner, not
  submitted, evaluation open (My work's "Evaluations due" without the due-date order).
  `my_evaluation_state` is the owner's own progress (or null). Default order
  `-updated` (`last_activity_at`), ties by id.
- **`get_idea`:** REST `get_idea` + `list_evaluations` (the latest 25, oldest first
  among them, plus `evaluation_count`) + `get_my_evaluation` + the latest
  `comment_limit` comments that aren't deleted (oldest first among them; @mention tokens
  as stored; bodies over 2,000 characters cut, `truncated`). `submitted_by` is null for
  public ideas and the public submitter's name is **not** returned (minimal personal
  data; `via_public_form` says where it came from). `permissions` are evaluated for the
  principal (key scopes included).
- **`get_rubric`:** the active criteria with `guidance`; `inverted: true` means a high
  score is bad (the aggregate uses 6 − score; evaluators score what they see).
- **`get_proposal`:** the proposal (no margin comments, no score line), or null with
  `can_suggest: false` when none has been started.
- **`create_idea`:** exactly `create_idea` (REST): status New, `submitted_by` = the owner,
  the creator watches it, activity and notifications as in the app; 409
  `project_archived`; 403 for viewers and non-members (`forbidden`).
- **`add_comment`:** exactly `create_comment` (REST), including @mentions (at most 20;
  422 `too_many_mentions`), watching and notifications; 409 `project_archived`; held →
  `not_found`.
- **`submit_evaluation`:** exactly `save_my_evaluation` with the validated arguments as
  its body (contract-phase1 §3.6): the arguments **replace** what was saved; every
  `criterion_id` must be active in the idea's project (`unknown_criterion`); submitting
  needs a score for every active criterion and a recommendation
  (`evaluation_incomplete`, message naming the missing criteria); `submit: false` after
  a submission → `evaluation_already_submitted`; not an assigned evaluator with member or admin →
  `forbidden`; `evaluation_closed`, `idea_closed`, `project_archived`. The first
  submission records `evaluation.submit`, emits `evaluation_submitted`, recomputes the
  aggregate; a service account's is left out of the aggregate (§2). Phase 6 adds
  optional per-criterion `rationale` and `sources` (additive).
- **`propose_proposal_section`:** exactly `create_proposal_suggestion` with `source`
  `mcp` (a person's key) or `ai` (a service account's), §3.4; no proposal →
  `not_found` ("This idea has no proposal yet."); `base_version` above the section's →
  `validation_error`; `proposal_not_available`, `too_many_suggestions`,
  `project_archived`.

### 4.4 Tool error codes

| `code` | When |
|---|---|
| `not_found` | the idea or project doesn't exist, can't be seen by the owner, is outside the key's projects, is held; no proposal (`get_proposal` returns `proposal: null` instead) |
| `forbidden` | the owner's role doesn't allow the rule (a viewer commenting, a non-evaluator submitting) |
| `insufficient_scope` | the key's scopes don't include the tool's scope |
| `validation_error` | the arguments fail the tool's `*Input` model (types, limits, cross-field rules, stripped text now empty; the message names the fields, never values), or a REST 422 `validation_error` (a `base_version` above the section's) |
| `invalid_cursor` | a cursor that isn't one of ours |
| `unknown_criterion`, `evaluation_incomplete`, `too_many_mentions` | as REST 422s |
| `evaluation_closed`, `idea_closed`, `evaluation_already_submitted`, `proposal_not_available`, `too_many_suggestions`, `project_archived` | as REST 409s |
| `too_many_attempts` | the key's write cap (30 a minute) on a tool that isn't read-only |
| `unknown_tool` | a name that isn't in the catalogue |
| `internal_error` | anything unexpected (logged with the traceback; the message says nothing more) |

HTTP-level `/mcp` responses (problem+json): 401 `unauthorized`, 403 `insufficient_scope`
(c15), 403 `invalid_origin`, 405, 413 `content_too_large`, 429 `too_many_attempts`; the
SDK's own 400 / 406 / 415 bodies are JSON-RPC errors.

### 4.5 Auditing calls

See §3.6: one `mcp.call` per `tools/call`, with `tool`, `rule`, `decision`, `code`,
`api_key_id`; target the idea (or project) when it exists; never arguments.

### 4.6 Minimum MCP tests (tests first)

Over HTTP (`httpx.ASGITransport` inside the app's lifespan with the SDK client, research
R1 §1; in-memory clients skip authentication):

- Transport: no key, a cookie only, a revoked key → 401 with `WWW-Authenticate`; a key
  without `mcp` → 403 (audited); a foreign `Origin` → 403 `invalid_origin`; `GET` /
  `DELETE` → 405; 1 MiB + 1 byte → 413; a JSON-RPC batch → 400; a request with a
  cluster-internal `Host` (not a base URL) works; `/.well-known/oauth-protected-resource`
  → 404 problem+json; `tools/list` returns exactly the nine catalogue tools with
  `inputSchema` equal to the `*Input` models and `outputSchema` to the `*Output`
  models; `initialize` returns the name, version and instructions; an unknown tool →
  `unknown_tool`, bad arguments → `validation_error` (both structured, both audited).
- Per tool: the scope (each tool with a key lacking its scope → `insufficient_scope`),
  the rule for each column (PA, PAd, Mem, Vwr, NMi, NMp; owner/evaluator overlays), the
  project restriction (`not_found`), and its 409/422 codes as structured errors.
- Blind evaluation on `search_ideas`, `get_idea` and `submit_evaluation`'s result: a
  pending evaluator (draft and no draft), the same user after submitting, a project
  admin who is a pending evaluator, a viewer and an internal non-member, with two other
  submitted evaluations and one AI evaluation present; `sort: score` puts the hidden
  idea last; a service account evaluates blind.
- Holds: an idea held for moderation and one held for confirmation are `not_found` in
  every tool for every role (platform admin included) and absent from
  `search_ideas` and `idea_count`.
- Writes through MCP behave as REST: notifications fan out (with email on), activity and
  audit entries name the owner; a failed write leaves nothing but its `mcp.call` entry;
  `create_idea` with tags `["A", "a"]` stores one tag; the 31st write in a minute →
  `too_many_attempts`.
- Bounded and labelled results: `get_idea` on an idea with 30 comments of 10,000
  characters and 30 submitted evaluations returns 10 (or `comment_limit`, at most 20)
  comments cut at 2,000 characters with `truncated: true`, 25 evaluations and
  `evaluation_count: 30`; a public idea has `via_public_form: true` in `search_ideas`
  and `get_idea`.

## 5. Error codes

New in Phase 5:

| Status | `code` | When |
|---|---|---|
| 401 | `unauthorized` | also: a key that is missing a part, unknown, wrong, revoked or expired, whose owner is inactive or the break-glass account, whose creating sign-in method is unavailable, or (a person's) whose owner hasn't used the app for 30 days (one message for all, `WWW-Authenticate: Bearer`) |
| 403 | `insufficient_scope` | a key whose scopes don't grant the rule, a session-only rule or route with a key (including `idea.delete`, `idea.moderate`), `/mcp` without the `mcp` scope (c15) |
| 403 | `forbidden` | also: a service account volunteering as owner (c21) |
| 403 | `break_glass_account` | the break-glass account creating a key (c20) |
| 403 | `invalid_origin` | `/mcp` with an `Origin` that isn't one of the base URLs |
| 404 | `not_found` | also: a project or idea outside a key's restriction; another user's key; no proposal (suggestions) |
| 409 | `system_account` | also: `role: admin` for a service account in `add_project_member` / `update_project_member` |
| 422 | `assignee_not_eligible` | also: a service account as an idea's owner (c4) |
| 409 | `too_many_api_keys` | a 26th key that isn't revoked |
| 409 | `api_key_name_taken` | a name one of your keys that isn't revoked already has (any case) |
| 409 | `too_many_suggestions` | a 51st pending suggestion on a proposal |
| 409 | `suggestion_not_pending` | accepting an accepted or discarded suggestion, discarding an accepted one |
| 422 | `invalid_project` | a key restricted to a project you can't view or that doesn't exist |
| 422 | `validation_error` | also: a suggestion's `base_version` above the section's current version |
| 429 | `too_many_attempts` | also: a failing key from an address past 30 failed key authentications in a minute (valid keys still work); 300 requests or 30 writes per key per minute; with `Retry-After` |

## 6. Decisions

Simpler option chosen each time; the lead may revisit (also in
[decisions.md](../decisions.md) and [ADR 0013](../adr/0013-api-keys-and-mcp-server.md)).

| Decision | Why |
|---|---|
| Keys are `sdg_<12-char lookup id>_<40-char secret>`; the lookup id is stored in clear, the whole key as SHA-256; constant-time compare after the lookup. | One indexed lookup per request; a database leak reveals no usable key; the prefix is recognisable to people and scanners; no pepper, so rotating the secret key doesn't revoke every key. |
| Keys are immutable (name, scopes, restriction, expiry); no rename, no renewal. | Fewer endpoints and no surprise for whoever holds a key; create and revoke is the whole lifecycle. |
| `write` and `evaluate` include `read` (added at creation, enforced by a check constraint). | Their responses return readable data anyway; a scope list that says otherwise misleads. |
| Up to 25 keys per user; expiry optional, at most 366 days; names unique among keys that aren't revoked. | Bounded lists without paging; "never" stays possible for service integrations, while dated keys can't be set to expire in 2099. |
| The project restriction is a `uuid[]` on the key (null = all), not a join table. | Authentication reads one row; a deleted project's id matches nothing, so a restriction can only shrink; no cascade could ever turn a restricted key into an unrestricted one. |
| Revoked keys keep their row; revoked keys are never listed. | Audit entries can still name the key; the lists show only keys that do something. |
| Deactivating a user revokes their keys; key use doesn't touch `users.last_seen_at`; no IP address stored. | A reactivated account doesn't silently get old keys back; "last seen" stays about the app; minimal personal data. |
| A person's key pauses (401, `dormant`) while its owner hasn't used the app for 30 days; signing in reactivates it; service accounts are exempt. Chosen over "no never-expiring keys for people, 90 days at most". | IdP removals and group changes only apply at sign-in; this bounds a departed person's keys to about 30 days with stale roles, keeps "never" for people who do use the app, and needs no renewal flow. |
| A key works only while the sign-in method of the session that created it is available (`created_auth_method`). | The same rule as sessions: dev-login keys die with dev login, like c20 for break-glass. |
| The break-glass account can't create keys (c20). | Its sessions stop once SSO is configured; a key would not. |
| Key management is session only; key routes answer 403 `insufficient_scope` to keys. | A leaked key can't mint or protect itself (role matrix §5). |
| Routes without a rule need `read` with a key; the inbox is session only. | Deny by default for every key request; the inbox is a person's reading state, not an integration surface. |
| Failed key authentications are counted per address (30/min); over the limit failing keys get 429 while valid keys still work; refusals are logged, not audited; each key is limited to 300 requests and 30 writes a minute. | Bounds floods, runaway or prompt-injected agents and audit growth with the existing in-process throttle, without locking out valid keys behind a shared NAT. |
| Key routes, `idea.delete` and `idea.moderate` are session only. | Nothing irreversible (a hard delete, a rejection that deletes) happens through a key or an agent. |
| Service accounts never own an idea (c4, c21) and never hold the admin role (409 `system_account`). | An agent with `write` could otherwise volunteer as owner and accept its own suggestions or include its own evaluation (SPEC §9). |
| `/mcp` authenticates with the REST key source in an ASGI wrapper (not the SDK's `TokenVerifier`); errors are problem+json; cookies are never accepted there. | One code path for keys; the same throttles, refusals and principal; no CSRF exposure. |
| Stateless JSON mode, `POST /mcp` only, exempt from the Host check, with an Origin check. | Every request authenticated (revocation is immediate), no long-lived streams; agents reach it by the cluster Service name; DNS rebinding blocked by Origin and the bearer key. |
| The SDK's low-level `Server` with one `tools/call` dispatcher; write tools' arguments subclass the REST request models. | The published schemas are the models; one place validates, rate-limits, maps errors and audits each call exactly once; no drift from REST. |
| MCP tools reuse the REST services; tool errors carry the REST problem code in `structuredContent`. | Same authorisation, blind evaluation and conflict handling by construction; one vocabulary of codes. |
| `get_idea` is bounded (10–20 comments, 25 evaluations, comments cut at 2,000 characters) and every people-written field is labelled untrusted. | Agents' context windows and prompt injection: results stay small, and models are told what is data. |
| Held ideas are `not_found` through MCP for everyone, admins included. | No MCP tool moderates; text waiting for moderation doesn't reach agents (public text in unmoderated projects is flagged, not hidden). |
| MCP cursors are opaque and validated like REST's, not bound to the other arguments. | REST cursors aren't either; a reused cursor can't reveal anything the filters wouldn't. |
| `get_idea` returns no public submitter name; tool arguments are never logged or audited. | Minimal personal data for agents and logs. |
| Every `tools/call` is audited (`mcp.call`) whatever the outcome; those entries expire after 90 days. | SPEC's "every call audited"; agents' trails are useful for months, not for ever; what they changed is audited for good. |
| A suggestion is the whole text of one section; one pending per author per section; accepting is a normal versioned section save; 50 pending at most. | Matches "Draft section" (Phase 6) and the per-section concurrency of Phase 4; no diff format to invent; bounded. |
| Service accounts' keys are created by platform admins (Phase 6, Admin → AI agents), restricted to the projects the agent serves; a service account's evaluations are left out of the aggregate by default from Phase 5; its suggestions are `source: ai` whatever the channel. | Agents never sign in; SPEC section 9's default holds as soon as an agent can submit; restriction limits cross-project leaks through a shared agent. |
| No new settings: limits and retention are constants. | Simple beats configurable. |

## 7. Room for later phases

- **Phase 6 (kagent):** Admin → AI agents creates service accounts and their keys
  (`platform.manage_agents`, §3.7); the agent picker in project members (member only);
  `submit_evaluation` gains optional per-criterion `rationale` and `sources` (additive),
  shown in the Evaluations tab; "Draft section" (`ai.draft_section`) asks the agent, which
  calls `propose_proposal_section` (`source: ai`); notifications for new suggestions (a
  new `NotificationType` landed with the SPA's maps); kagent's MCP client checked
  against the SDK's protocol versions.
- **Later, if needed:** key rotation with an overlap window; per-key IP allow-lists;
  OAuth 2.1 for MCP (the SDK supports it; not needed for keys issued in the app);
  `tools/list` filtered by the key's scopes; MCP resources (the rubric, the proposal
  template); a "last used from" location; authors withdrawing their own pending
  suggestion; restricting a restricted key's `search_users` to its projects' people.

## 8. Changes after the contract

Builders record additive contract changes here (date, change, why), then run
`make gen-api`.

## 9. Contract review (2026-10-02, before building)

Applied from the read-only contract review; the lead may revisit any of them.

| # | Change | Where |
|---|---|---|
| 1 | `/mcp` is exempt from the Host check; NetworkPolicy `ingressFrom` must admit the agents' namespace; `mcp-smoke` also calls the Service URL in the cluster. | §3.5 |
| 2 | Service accounts never own an idea (c4 422; volunteering c21 403) or hold the admin role (409 `system_account`). | §2, §3.7, role matrix §1, §4 |
| 3 | A person's key is `dormant` (401) while its owner hasn't used the app for 30 days (`API_KEY_OWNER_IDLE_LIMIT`, new `ApiKeyState.dormant`). | §3.1, §3.2 |
| 4 | `get_principal` returns the stored principal whenever one exists. | §3.2 |
| 5 | `project_ids=None if … is None else frozenset(…)`; the check refuses NULL elements. | §3.2, migration 0010 |
| 6 | `write` and `evaluate` include `read` (`canonical_scopes`, `ck_api_keys_scopes_include_read`). | §3.1, §3.3, role matrix §5 |
| 7 | `idea.delete` and `idea.moderate` are session only. | §3.3, role matrix §5 |
| 8 | Discard takes accept's locks; create replaces under the idea lock. | §3.4 |
| 9 | `source: ai` whenever the author is a service account. | §3.4, `SuggestionSource` |
| 10 | `get_idea` bounded: `comment_limit` 0–20 (10), 25 evaluations + `evaluation_count`, texts cut at 2,000 with `truncated`. | §4.2, `app/schemas/mcp.py` |
| 11 | People-written output fields say `UNTRUSTED`; `via_public_form` on `McpIdeaSummary`; held-idea wording corrected. | §4.2 |
| 12 | Over the failure limit only failing keys get 429. | §3.2 |
| 13 | `/.well-known/*` → API 404, not the SPA. | §2, §3.5 |
| 14 | Admin `q` finds a key by prefix or lookup id; `prefix` in the key audit details. | §2, §3.6 |
| 15 | Write tools' inputs subclass `IdeaCreate`, `CommentCreate`, `MyEvaluationIn` (`submit`, default true, replaces `draft`), `ProposalSuggestionCreate`. | §4.2, §4.3 |
| 16 | 30 writes per key per minute (`API_KEY_WRITES_PER_MINUTE`). | §3.2 |
| 17 | Agent keys restricted to the projects the agent serves; one agent per project where needed. | §3.7, ADR 0013 |
| 18 | `api_keys.created_auth_method`; a key works only while that method is available; c20 covers agent keys. | §3.1, §3.7, migration 0010 |
| considered | Low-level `Server` with one dispatcher (`unknown_tool`, `validation_error`); cursors not bound; `last_used_at` in its own transaction for REST too; `is_active` re-read after the create lock; `base_version` above current → 422; c15 refusals audited; "Sign out everywhere" says keys keep working; acceptance step 4 in Customer Innovation; the SPA `reset()`s the create mutation. Not taken: authors withdrawing suggestions and narrowing a restricted key's global user search (§7, documented in §3.3). | throughout |
