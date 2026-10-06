# Test plan: Phase 5 (API keys and MCP)

Owner: qa. Source of truth for behaviour: [SPEC.md](../../SPEC.md) sections 8 and 13,
[contract-phase5.md](../api/contract-phase5.md) (key lifecycle §3.1, authentication §3.2,
scopes and restriction §3.3, suggestions §3.4, the `/mcp` transport §3.5, audit §3.6,
minimum tests §3.8 and §4.6, acceptance §3.9, screens §3.10, tools §4),
[role-matrix.md](../role-matrix.md) (§5 API keys, §6 MCP tools, §3 blind evaluation, c15,
c20, c21) and [ADR 0013](../adr/0013-api-keys-and-mcp-server.md). Each row has an ID used
in the test names, so a failing test points back here. The Phase 1–4 plans
([phase-1.md](phase-1.md) … [phase-4.md](phase-4.md)) still apply; their suites run in
every mode next to the Phase 5 specs.

## Acceptance criterion

> An MCP client with a key can search ideas and submit an evaluation only in permitted
> projects; revoking the key cuts access immediately.
> (SPEC section 13, Phase 5; contract-phase5 §3.9)

It is tested at three levels, each adding something the others can't:

| Level | Test | What it adds |
|---|---|---|
| Browser, real stack | `e2e/tests/api-keys.spec.ts` (AC5-01) | Carol creates "Claude Desktop" **in Settings → API keys** (the "Evaluate with an assistant" preset, "Only these projects", 30 days); the secret is shown once (`Cache-Control: no-store`), **copied with the Copy button and read back from the clipboard**, and after Done it is nowhere: not on the page, in the URL, in local or session storage, in cookies or in `GET /me/api-keys`; the new row has focus and says "Never used". The test then uses the key as a script and an MCP client would (bearer only, no cookie, no CSRF header): REST lists only that project and answers 404 for the other one and its idea; `/mcp` `initialize` (stateless: no `Mcp-Session-Id`), the nine tools, `list_projects`, blind `search_ideas awaiting_my_evaluation`, blind `get_idea`, `get_rubric`, `submit_evaluation`, then the aggregate; the other project's idea `not_found` (although she may evaluate it in the app), `create_idea` `insufficient_scope`. The page then shows the key as used; the audit log's API and **the audit viewer's sentences** ("Carol Chen’s key called submit_evaluation on …", "… get_idea on …: denied (not found)", "Carol Chen submitted an evaluation of …"); Carol revokes it in the UI (the confirm names the prefix) and the **very next** `tools/call` and REST call get the one 401 with `WWW-Authenticate: Bearer realm="soundings"`. Fresh projects of its own, so it runs in parallel with everything else. |
| HTTP over TCP, live server, the official MCP SDK | `backend/tests/acceptance/test_phase5_acceptance.py` (AC5-API-1) | The app behind a real **uvicorn** on a free port with the **demo data**, every request over TCP: Carol (dev login) is invited on a new CUST idea that Bob and Farah already scored and on a new TOOLS idea; she creates the key through `POST /me/api-keys` (`read` added to `evaluate`, `prefix` = the key's first 16 characters, the secret never in the list); the **`mcp` 2.x SDK client** (`Client` + `streamable_http_client`) checks the server name and instructions, exactly nine tools, `list_projects` (CUST only, `can_create_ideas` false), `search_ideas` (only CUST's 22 visible ideas; nothing for the TOOLS title), blind `get_idea` (every score field walked, not chosen), a **draft first** (`submit: false`, still blind), `evaluation_incomplete`, then the submission and the two other evaluations and the aggregate; outside the key `not_found` for `get_idea`, `submit_evaluation`, `get_rubric` and `search_ideas project=`; `create_idea` and `add_comment` `insufficient_scope`; `unknown_tool`; the same key on REST narrowed alike (and 403 on the key routes); Carol's session still sees Internal Tools. The audit log read **through the admin API** has exactly one `mcp.call` per call, in order, with decision, code, `api_key_id`, `auth: api_key` and the idea as target (also when denied), plus `evaluation.submit` through the key; none of it holds the key or an argument. Revoked through `DELETE /me/api-keys/{id}`: the **open SDK client's next call** fails, a new connection fails, raw JSON-RPC and REST are 401 with the bearer challenge, the list is empty, a second revoke is 204, the audit has the key's create and revoke. **No log record of the whole story holds the key or the evaluation's text.** The module takes about 50 s (two demo seeds). Runs in `make check-backend`. |
| HTTP, ASGI, factories (backend's) | `backend/tests/mcp/test_flow.py` | The same six steps with factories and a key written to the database (backend's own test, kept as the fast unit-level version). |

**AC5-API-2** (same module): a **pending evaluator's key gets no score data**: Alice, platform
admin and admin of Customer Innovation, still owes evaluations in the seed (CUST-11 among
them). Through her key, in **both protocol handshakes** (the SDK's `auto` 2026-07-28 probe and
`legacy` initialize), `search_ideas awaiting_my_evaluation`, `get_idea` on each of those ideas
(20 comments) and `search_ideas query=<key>` carry no score, aggregate, evaluations,
`evaluation_count`, disagreement or `score_hidden: false` anywhere outside her own
`my_evaluation`; other evaluators' rows say only invited or submitted; `sort: -score` lists
every visible score first, in order, and her hidden ideas after. Bob's key, the owner of
CUST-11, gets its aggregate, evaluations and high-disagreement flag.

**AC5-API-3** (same module): **deactivating a user revokes their keys for good** (contract §2):
after deactivation the key is 401 (an inactive owner never authenticates), and after
**reactivation it must still be 401**, with an `api_key.revoke` entry `reason: deactivated`
and nothing listed (fixed at integration, see "Defects found by these tests").

**AC5-API-4** (same module, contract §3.7): an **AI agent's key** (a service account, member
of its project, its key issued by a platform admin through `issue_key` as Phase 6's Admin →
AI agents will) gets no score data before it submits, submits through MCP, suggests a
section with `source: ai`, and can't volunteer as owner (c21, 403 `forbidden`); its
evaluation is left out of the aggregate (`include_in_aggregate: false`), it can't be made an
idea's owner (c4, 422 `assignee_not_eligible`) and it can't be made a project admin (409
`system_account`). The last three were expected failures until integration fixed them.

The rules behind it are unit-tested by their owners (tests first): `backend/tests/api_keys/`,
`tests/auth/test_api_key_source.py` and `tests/authz/test_key_*.py` (identity: format,
lifecycle, guards, every refusal reason, throttles, last use, every rule × column × 15 scope
sets × 4 restriction kinds), `backend/tests/mcp/` (backend: transport, tools, blind,
audit, flow; about 130) and `tests/proposals/test_suggestions.py` (backend: about 30), and the
SPA's page tests in `frontend/tests/` (MSW: `api-keys`, `admin-api-keys`,
`proposal-suggestions`). The tables below map each rule to them; the e2e suite covers what
only a browser, a real network client and the whole stack can show.

## How to run

| What | Command | Needs |
|---|---|---|
| API acceptance (part of `make check-backend`) | `cd backend && uv run pytest tests/acceptance/test_phase5_acceptance.py` | Docker (Postgres testcontainer) or `TEST_DATABASE_URL` |
| E2E (Phases 1–5), dev login | `npm --prefix e2e test` | Docker (Postgres, Mailpit), `uv`, Node 22, Chromium |
| E2E with SSO | `E2E_SSO=1 npm --prefix e2e test` | + Keycloak 26 |
| Only the Phase 5 specs | `npx --prefix e2e playwright test api-keys admin-api-keys suggestions a11y-phase5 --project=e2e` | |
| Screenshots | `npm --prefix e2e run screenshots:phase5` → `docs/screenshots/phase-5/` | fresh demo data (the local stack reseeds) |
| The curl version of the acceptance | `make mcp-smoke` (platform: `scripts/mcp-smoke.sh`) | an app with the demo data and dev login |

**Keys in e2e.** `e2e/tests/support/mcp.ts` (`KeyClient`) is a client that only has a key:
`Authorization: Bearer`, no cookies, no CSRF header, REST through `rest()` and `/mcp`
JSON-RPC through `rpc()` / `call()` / `ok()` / `fails()` with the headers a streamable HTTP
client sends (`Accept: application/json, text/event-stream`, `MCP-Protocol-Version`).
Every client claims an address of its own with `X-Forwarded-For` (the stack trusts loopback
as its proxy, as Phase 4's `Visitor`): refused keys count towards 30 a minute **per
address** (§3.2), and the whole run shares 127.0.0.1. `expectRefusedKey` checks the one 401
(problem+json `unauthorized`, `WWW-Authenticate: Bearer realm="soundings"`). Keys made by
specs have run-unique names and are revoked when the spec ends (the limit is 25 per user;
the stack reseeds on every run anyway). People whose sessions a spec ends or who it
deactivates are created by that spec (`newPerson` in `admin-api-keys.spec.ts`), so no other
spec loses Bob's or Carol's session.

**Expected failures.** Tests for contract rules that aren't built yet are marked so they
pass while the defect stands and **fail as soon as it is fixed** (then remove the mark):
`test.fail(true, …)` in Playwright, `@pytest.mark.xfail(strict=True)` in pytest. None are
left: AK-04, AAK-04, AC5-API-3 and three of AC5-API-4 were, until integration fixed their
defects (below).

## Key rules and where they are tested

### Keys: format, storage, lifecycle (contract §3.1)

| Rule | Unit (identity) | E2E / acceptance |
|---|---|---|
| `sdg_` + 12 + `_` + 40 base62; only SHA-256 of the whole key stored; constant-time compare | `test_tokens.py` (5), `test_a_new_key_is_shown_once_and_stored_hashed` | AC5-01, AC5-API-1 (pattern, prefix = first 16 characters) |
| Shown once with `Cache-Control: no-store`; never listed, logged or audited again | `test_a_new_key_is_shown_once_and_stored_hashed`, `test_creation_is_audited_without_the_key`, `tests/mcp/test_audit.py::test_no_entry_or_log_line_holds_a_key_or_an_argument` | AC5-01 (page, URL, storage, cookies, list, clipboard), AC5-API-1 (list, audit, every log record), screenshots (the shown key is revoked at once) |
| `write` / `evaluate` include `read` | `test_write_and_evaluate_include_read` | AC5-API-1 (`["evaluate","mcp"]` → `read, evaluate, mcp`), AC5-01 (the preset; "Included") |
| Names unique per owner in any case, free again after revoking | `test_names_are_unique_in_any_case_until_revoked` | AK-01 (the 409 on the field, focus back on Name; the same name in upper case after revoking) |
| 25 keys; two parallel creates at 24 → one 409 | `test_at_most_25_keys_that_are_not_revoked`, `test_two_parallel_creates_at_24_keys_leave_one_409` | (unit only) |
| Restriction: projects you can view now; unknown or private → `invalid_project` alike | `test_restrictions_must_be_projects_you_can_view`, `…archived_project_may_be_chosen` | AC5-01, AC5-API-1 (restricted keys made through the UI and the API) |
| Expiry 1 h–366 days; expired → 401 at once | `test_revoked_and_expired_keys_are_refused_on_the_next_request`, `tests/mcp/test_transport.py::test_an_expired_key_is_401` | AC5-01 ("30 days" in the UI: "Stops working on …"); the hour can't pass in e2e |
| Revocation is immediate (REST and `/mcp`), idempotent | `test_revoking_through_the_api_cuts_access_at_once`, `tests/mcp/test_transport.py::test_revoking_cuts_the_next_request_mid_session` | AC5-01 (UI revoke → next call), AC5-API-1 (open SDK client, new connection, raw JSON-RPC, REST; second revoke 204), AAK-02 (an admin's revoke) |
| Deactivation revokes every key (audited `reason: deactivated`); a reactivated account doesn't get them back | `test_deactivating_revokes_every_key` (service), `tests/api_keys/test_service_accounts.py::test_deactivating_a_user_revokes_their_keys_for_good` (HTTP) | AC5-API-3, AAK-04 |
| "Sign out everywhere" ends sessions only; keys keep working | — | AAK-03 (the confirm says so; the person's session 401, their key 200) |
| c20: the break-glass account can't create keys | `test_the_break_glass_account_cannot_create_keys`, `test_c20_…` | AK-05 (signed in as break-glass: "Create key" disabled with the reason; the API 403 `break_glass_account`; skips with SSO, where break-glass is off) |
| `created_auth_method`: a dev-login key stops when dev login is off; SSO keys without SSO | `test_a_dev_login_key_stops_when_dev_login_is_off`, `test_an_sso_key_stops_while_sso_is_not_configured` | (unit only: needs a restart with other settings) |
| Dormant after 30 days without signing in; signing in resumes | `test_a_persons_key_pauses_after_30_days_without_signing_in` | (unit only) |
| Last used, at most once a minute, own transaction | `test_last_used_moves_at_most_once_a_minute`, `…saved_even_when_the_request_fails`, `test_refused_keys_are_not_marked_used` | AC5-01 ("Never used" → a time after the client's calls) |

### Authenticating with a key (§3.2)

| Rule | Unit (identity / backend) | E2E / acceptance |
|---|---|---|
| Every refusal is the same 401 with `WWW-Authenticate: Bearer realm="soundings"` | `test_unknown_and_wrong_keys_are_refused`, `test_malformed_keys_are_refused_without_a_query`, `tests/mcp/test_transport.py::test_unusable_keys_get_the_same_401` | AK-03 (none, malformed: REST and `/mcp`), AC5-01, AC5-API-1, AAK-02 |
| No CSRF with a key; a key decides over a cookie; a cookie alone never opens `/mcp` | `test_no_csrf_token_with_a_key_but_still_with_a_cookie`, `test_a_key_decides_over_a_session_cookie`, `test_a_session_cookie_alone_is_never_accepted` | AK-02 (a write with the key alone; a revoked key + Carol's valid cookie → 401; the cookie alone on `/mcp` → 401) |
| 30 failures per address a minute → 429 for failing keys only | `test_failing_keys_from_one_address_are_throttled_but_valid_keys_still_work`, `test_failures_are_counted_per_address` | (unit; the e2e clients claim their own addresses so the run never trips it) |
| 300 requests and 30 writes per key a minute | `test_each_key_has_a_request_rate`, `test_each_key_has_a_write_cap_but_reads_still_work`, `tests/mcp/test_audit.py::test_the_write_cap_refuses_writes_but_not_reads` | (unit only) |
| Live owner: a demoted owner's key loses the rule on the next request | `test_a_demoted_owner_loses_the_right_on_the_next_request`, `test_a_platform_admins_key_follows_the_flag` | (unit only) |

### What a key may do (§3.3, role matrix §5)

| Rule | Unit (identity) | E2E / acceptance |
|---|---|---|
| Effective permission = owner ∩ scopes ∩ projects, for every rule × column × scope set × restriction | `tests/authz/test_key_scopes.py` (9; 15 scope sets × 4 restrictions; checked to bite) | AC5-01, AC5-API-1, AK-02 |
| Scopes: a rule the key's scopes don't grant → 403 `insufficient_scope`, after the 404s | `test_scopes_grant_exactly_the_documented_rules`, `test_rule_routes_refuse_a_key_without_the_rules_scope` | AK-02 (a read key commenting), AC5-01 / AC5-API-1 (`create_idea`, `add_comment`) |
| Session only: deleting and moderating ideas, key management, admin routes, the inbox and preferences | `test_session_only_rules_refuse_a_key_with_every_scope`, `test_session_only_routes_refuse_a_key_with_every_scope`, `test_deleting_and_moderating_ideas_need_a_session` | AK-02 (a key with all four scopes: delete, key routes, inbox, summary, preferences → 403), AAK-05 (Alice's full key on admin routes → 403), AC5-API-1 |
| Permission flags reflect the key (`can_delete` false for any key) | `test_permission_flags_are_computed_for_the_key` | AK-02, AC5-API-1 (`can_comment` false without `write`) |
| Restriction: everything outside is 404; lists contain only the key's projects; a platform admin's key too | `tests/authz/test_key_narrowing.py` (11) | AC5-01, AC5-API-1 (REST and MCP) |
| Writes through a key are audited with `auth: api_key` and `api_key_id`; activity names the owner | `test_writes_through_a_key_are_audited_with_the_key` | AC5-API-1 (`evaluation.submit`), AK-02 (`create_idea` by MCP and REST: submitted by Carol, the idea's page) |

### The MCP server (§3.5, §4)

| Rule | Unit (backend, `tests/mcp/`) | E2E / acceptance |
|---|---|---|
| `initialize`: name, instructions; stateless (no session id); nine tools with schemas | `test_initialize_names_the_server_and_carries_the_instructions`, `test_tools_list_is_exactly_the_catalogue`, `test_both_protocol_eras_call_tools` | AC5-01 (raw JSON-RPC), AC5-API-1 / -2 (SDK, both handshakes) |
| `POST` only (405 `Allow: POST`); foreign `Origin` 403 `invalid_origin`; own origin fine; `no-store`; no CORS | `test_only_post_is_served`, `test_a_foreign_origin_is_refused_before_authentication`, `test_our_own_origin_is_fine` | AK-03 |
| c15: a key without `mcp` → 403 with `error="insufficient_scope"`, audited | `test_a_key_without_the_mcp_scope_is_403_and_audited` | AK-02 (a read key on `tools/list`) |
| `/.well-known/*` → the API's 404 problem, not the SPA | `test_well_known_oauth_metadata_is_a_clean_404` (no SPA build in tests) | **AK-04: fails today** on the real stack (the SPA answers) |
| Tools reuse REST: blind evaluation, holds, c-conditions, errors as tool results with the REST code | `test_tools.py` (29), `test_blind.py` (7) | AC5-01, AC5-API-1 (draft, `evaluation_incomplete`, submit, `not_found`, `insufficient_scope`, `unknown_tool`), AC5-API-2 |
| Blind: a pending evaluator (admin too) gets no score data; `sort: score` puts hidden ideas last | `test_a_pending_evaluators_key_gets_no_score_data`, `test_a_project_admin_who_owes_an_evaluation_is_blind_too`, `test_sort_by_score_puts_the_hidden_idea_last` | AC5-API-2 (the seed's platform admin, every payload walked), AC5-01, AC5-API-1 |
| Held ideas are `not_found` in every tool, for everyone | `test_held_ideas_are_not_found_through_any_tool` | (unit; the seed's held CUST-22/23 are absent from AC5-API-1's 22 CUST ideas) |
| Results: structured content and the same JSON as text; `url` from the base URL | `test_results_are_structured_and_the_same_json_as_text` | AC5-API-1 (every call), AK-02 (`url` = `<base>/ideas/<key>`) |
| `create_idea` merges tags in any case | `test_create_idea_is_rest_create_idea` | AK-02 (`["MCP","mcp"]` → `["MCP"]`) |

### Service accounts (§3.7)

| Rule | Unit | Acceptance |
|---|---|---|
| An agent evaluates blind and suggests as `ai` | `tests/mcp/test_blind.py::test_a_service_account_evaluates_blind`, `tests/mcp/test_tools.py::test_an_agents_suggestion_is_ai` | AC5-API-4 (live server, MCP) |
| c21: never volunteers as owner | `tests/authz/test_key_scopes.py::test_c21_…`, `test_key_narrowing.py::test_a_service_account_never_volunteers_as_owner` | AC5-API-4 |
| Left out of the aggregate; never an owner (c4) or a project admin | `test_c4_refuses_a_service_account_as_owner_but_not_as_evaluator` (policy), `tests/api_keys/test_service_accounts.py` (HTTP: owner 422, admin 409 on add and update, member and viewer work, the agent's evaluation left out while a person's through a key stays in) | AC5-API-4 |

### Audit (§3.6)

| Rule | Unit | E2E / acceptance |
|---|---|---|
| One `mcp.call` per `tools/call` whatever the outcome; none for `initialize` / `tools/list`; one for a c15 refusal | `tests/mcp/test_audit.py::test_every_outcome_is_audited_once`, `test_not_audited_initialize_list_and_ping` | AC5-API-1 (18 calls → exactly 18 entries, in order, codes), AC5-01 (9 calls → 9 entries) |
| `api_key.create` / `api_key.revoke` with the prefix, never the key | `test_creation_is_audited_without_the_key`, `test_admins_revoke_any_key` | AC5-API-1, AC5-01, AAK-02 (`rule: api_key.manage_any`, the actor) |
| The viewer's sentences and the "API keys and MCP" category | (frontend `audit-phrases.test.ts`) | AC5-01 (the sentences on the real stack), AAK-02 ("Alice Anders revoked API key sdg_… of Bob Brown" under `?action=api_keys`), screenshots |
| 90-day cleanup of `mcp.call` | `test_the_cleanup_removes_only_old_mcp_call_entries`, `test_the_hourly_schedule_runs_the_mcp_call_cleanup` | (unit) |

### Settings → API keys and Admin settings → API keys (§3.10)

| ID | What | Spec |
|---|---|---|
| AK-01 | A name you already use (any case) is refused on the field; free again after revoking | `api-keys.spec.ts` |
| AK-02 | A key alone: writes without CSRF, scopes, session-only routes, the key over the cookie, a cookie alone on `/mcp`, MCP `create_idea` as Carol | `api-keys.spec.ts` |
| AK-03 | `/mcp`: other methods 405, foreign origin 403, own origin 200 + `no-store` + no CORS, no key and a malformed key 401 | `api-keys.spec.ts` |
| AK-04 | `/.well-known/oauth-*` → 404 problem+json | `api-keys.spec.ts` |
| AK-05 | c20 for the break-glass account (UI and API) | `api-keys.spec.ts` |
| AAK-01 | Everyone's keys with owner, prefix, scopes, projects, last use; a pasted whole key (with "Bearer ") is cut to its prefix in the box and the URL, never in a request; the API finds exactly that key by prefix or lookup id, nothing for a near miss; the owner links to their admin page | `admin-api-keys.spec.ts` |
| AAK-02 | Revoking someone's key: the confirm names owner, key and prefix; toast; it stops at once (REST and MCP); audited and shown in the viewer; idempotent | `admin-api-keys.spec.ts` |
| AAK-03 | "Sign out everywhere" says keys keep working, ends the session, leaves the key; the sheet's "API keys" link filters by owner | `admin-api-keys.spec.ts` |
| AAK-04 | Deactivating revokes keys for good | `admin-api-keys.spec.ts` |
| AAK-05 | Non-admins get the 404 page and 403; an admin's key gets 403 on admin and key routes | `admin-api-keys.spec.ts` |

### Proposal suggestions (§3.4, `propose_proposal_section`)

| ID | What | Unit (backend) | Spec |
|---|---|---|---|
| SG-01 | An MCP suggestion (`source: mcp`, `base_version` = the section's) reaches the owner's editor: "1 suggestion" by the section and in the bar, the author, "via MCP", Removed/Added, the suggested text as Markdown; Accept → toast, the card goes, the textbox has the text, saved as the next version by Bob, nothing pending, the client's `get_proposal` sees it | `test_propose_proposal_section_creates_a_pending_suggestion`, `test_accepting_saves_the_text_as_a_versioned_section_save`, `test_source_follows_the_author` | `suggestions.spec.ts` |
| SG-02 | Discard hides it at once, focus moves to the section's text, Undo toast; the request goes when the toast closes; the text is unchanged; the client may suggest again | `test_deciding_twice` | `suggestions.spec.ts` |
| SG-03 | One pending per author and section (`replaced_suggestion_id`); a section saved since says "The section has changed since this was suggested"; accepting then replaces it; `base_version` above the section's → `validation_error` | `test_a_new_suggestion_from_the_same_author_replaces_the_pending_one`, `test_a_base_version_above_the_section_is_a_validation_error` | `suggestions.spec.ts` |
| SG-04 | Members and viewers see suggestions without Accept/Discard; a viewer's key can't suggest (`forbidden`); a member's session can't discard (403, `can_decide` false) | `test_viewers_and_outsiders_may_not_suggest`, `test_only_the_owner_and_admins_decide` | `suggestions.spec.ts` |
| — | Agents' suggestions (`source: ai`, the AI badge) | `test_an_agents_suggestion_is_ai` | frontend `proposal-suggestions.spec.ts` (mock); no service-account key can be made in the app before Phase 6 |

### Accessibility, phones, keyboard

| ID | What | Spec |
|---|---|---|
| A11Y5 | axe (WCAG 2.2 AA), light and dark: Settings → API keys, the create dialog filled in, the key shown once, the revoke confirm, Admin settings → API keys and its revoke confirm, the proposal editor with an MCP suggestion (changes and suggested text) | `a11y-phase5.spec.ts` |
| MO5-01 | The same screens at 390 px: no sideways scrolling; dialogs fill the screen | `a11y-phase5.spec.ts` |
| K5-01 | Create a key with the keyboard only (Enter on "Create key", type, ⌘/Ctrl+Enter, focus on "Copy key", Escape → focus on the new row) | `a11y-phase5.spec.ts` |

### After the security and UX reviews (2026-10-06)

| Rule | Unit / API tests | e2e |
|---|---|---|
| The key check holds no pool connection of the request (H1) | `tests/api_keys/test_connections.py` (4, a pool of 1 + 1) | — |
| A key revoked, expired, deactivated or demoted while a tool call waits changes nothing (M1) | `tests/mcp/test_held_requests.py` (5) | — |
| Refusals at `/mcp` count towards the key's budget and are audited once a minute (M2, L1) | `test_transport.py::test_a_key_without_the_mcp_scope_is_403_and_audited_once_a_minute`, `::test_refusals_of_a_key_without_mcp_count_towards_its_request_budget`, `::test_a_key_over_its_request_budget_is_audited_once_a_minute`; `test_audit.py::test_a_validator_that_crashes_is_audited_as_an_internal_error`, `::test_a_cancelled_call_is_audited` | — |
| A service account without a role is a private non-member everywhere (M3) | `tests/authz/test_service_account_access.py` (232) | — |
| No invisible characters in tool results (M4, output) | `tests/mcp/test_hidden_text.py` | — |
| Tag characters refused in every request body, one-line names and tool arguments; stripped from IdP names (M4, input) | `tests/ideas/test_input_robustness.py::test_request_models_reject_tag_characters_anywhere`, `::test_one_line_names_reject_every_tag_character`, `::test_tag_characters_in_any_text_are_a_422`; `test_hidden_text.py::test_tool_arguments_with_tag_characters_are_a_validation_error`; `tests/identity/test_claims.py::test_display_name` | — |
| Write tools refuse unknown arguments; read tools ignore them (L2) | `tests/test_schemas_phase5.py::test_write_arguments_refuse_unknown_ones`, `::test_read_arguments_ignore_extras_strip_and_refuse_nul_and_tag_characters`; `tests/mcp/test_tools.py::test_a_misspelt_write_argument_is_refused_not_ignored` | — |
| People-written output fields are marked `UNTRUSTED` (nit 2) | `test_schemas_phase5.py::test_people_written_text_is_marked_untrusted` | — |
| An agent's people search finds only co-members, inside its key's projects (L4) | `tests/api_keys/test_service_accounts.py::test_an_agent_finds_only_people_who_share_a_project_with_it`, `::test_an_agents_people_search_stays_inside_its_keys_projects`, `::test_an_agent_without_a_project_finds_nobody` | — |
| Lost project access: counted for the owner, marked for admins (UX m1) | `tests/api_keys/test_lifecycle.py::test_listed_projects_are_the_ones_that_still_exist_and_you_can_view`, `::test_unavailable_projects_are_counted_for_the_owner_and_marked_for_admins`; `frontend/src/features/api-keys/key-parts.test.tsx` | AAK-06 (`admin-api-keys.spec.ts`) |

## Defects found by these tests

All six were fixed at integration (2026-10-06); their expected-failure marks are gone and
the tests pass. Unit tests for each: `tests/api_keys/test_service_accounts.py`,
`tests/test_spa.py`, `tests/mcp/test_audit.py`.

| Owner | Defect | Contract | Test (was an expected failure) | Reproduce |
|---|---|---|---|---|
| backend | Deactivating a user doesn't revoke their keys: after reactivation the key works again (`admin_users.update_user` doesn't call identity's `revoke_all_for_user`) | §2, §3.1 | AC5-API-3, AAK-04 | Create a key as Ben (dev login), deactivate Ben as Alice (`PATCH /admin/users/{id} {"is_active": false}`), reactivate him, `GET /api/v1/auth/me` with the key → 200 (want 401); no `api_key.revoke` entry |
| backend | `/.well-known/oauth-protected-resource` (and every `/.well-known/*`) is the SPA's `index.html` with 200 on a stack that serves the SPA; `make mcp-smoke` and `k3s-smoke MCP=1` fail on it too | §2, §3.5 | AK-04 | `curl -i http://localhost:8100/.well-known/oauth-protected-resource` → `200 text/html` (want 404 problem+json); add `/.well-known` to `BACKEND_PATH_PREFIXES` in `app/spa.py` |
| backend | Old `mcp.call` entries are never deleted (`delete_expired_calls` isn't in the hourly schedule) | §3.6 | — (unit-tested function, not wired) | `grep delete_expired_calls backend/app/notifications/schedule.py` → nothing |
| backend | A service account's submitted evaluation counts in the aggregate (`include_in_aggregate` is always true in `services/evaluations.py`) | §2, §3.7, role matrix §3 rule 10 | AC5-API-4 (aggregate) | An agent key (`issue_key` for a `is_service_account` user, member) submits through MCP next to one person: the aggregate's `count` is 2 (want 1) |
| backend | A service account can be made an idea's owner (`set_idea_owner` 200; c4 needs `assignee_service_account` in the policy's `Resource`) | §2, §3.7 | AC5-API-4 (owner) | `PUT /ideas/{key}/owner {"user_id": <agent>}` as the project admin → 200 with the agent as owner (want 422 `assignee_not_eligible`) |
| backend | A service account can be made a project admin (`update_project_member` 200) | §2, §3.7 | AC5-API-4 (admin) | `PATCH /projects/{slug}/members/{agent} {"role": "admin"}` → 200 (want 409 `system_account`); `add_project_member` likewise per the contract |

## Screenshots

`npm --prefix e2e run screenshots:phase5` writes `docs/screenshots/phase-5/`
`<screen>-<1440-light|1440-dark|390-light>.png` from freshly seeded data: `api-keys`
(Carol's three keys, one used by an MCP client a moment before, one restricted to a private
project she has since left: "+1 project you can no longer open"), `api-keys-connect-mcp` (the
"For developers and AI assistants" section, opened), `api-keys-create-dialog`
("Evaluate with an assistant", 30 days, one project), `api-keys-secret-reveal` (the key is revoked as soon as
it is on screen), `admin-api-keys` (Alice: five keys of three people; the project Carol left struck through), `proposal-pending-suggestions`
(CUST-6 with Carol's MCP suggestion for Summary and Bob's REST one for Risks) and
`audit-api-keys-and-mcp` (the "API keys and MCP" category).
