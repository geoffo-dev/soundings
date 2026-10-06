# Phase 5 summary: API keys and MCP

**Status:** closed on 2026-10-06, waiting for the product owner's review before Phase 6.
**Scope (SPEC sections 8 and 13):** personal API keys from Settings → API keys (name,
scopes `read` / `write` / `evaluate` / `mcp`, optional expiry, optional project
restriction; shown once, stored hashed, revocable, last use shown; never more than the
owner's live permissions), Settings → All API keys for platform admins, the MCP server at
`/mcp` (streamable HTTP, stateless, API-key auth, the nine SPEC tools, the same
authorisation as the API, every call audited), and proposal suggestions, which
`propose_proposal_section` creates and the owner accepts or discards in the proposal
editor (Phase 6's agents will use them with service-account keys).
**Acceptance:** an MCP client with a key can search ideas and submit an evaluation only in
permitted projects; revoking the key cuts access immediately. Met: see
[Acceptance evidence](#acceptance-evidence).

Commits: `dc80f09` (contract), `fe8f171`, `496ee1b`, `56ea8f3` (build and integration),
`7f1234a` (security and UX review fixes), plus this close-out (lead decisions on the
reviews, final verification, k3s, screenshots, docs).

## What was built

| Area | What | Where |
|---|---|---|
| Contract | 9 REST operations (your keys, all keys, suggestions), the MCP catalogue (9 tools, `*Input` / `*Output` models, error shape, instructions), migration 0010 (`api_keys`, `proposal_suggestions`), three audit actions, c20 / c21, `ApiKey.unavailable_project_count` and `AdminApiKey.projects[].owner_can_view` (additive, this close-out) | [contract-phase5.md](../api/contract-phase5.md) (§8 lists every change after the contract), `backend/app/schemas/api_keys.py`, `mcp.py`, `proposals.py`, [ADR 0013](../adr/0013-api-keys-and-mcp-server.md) |
| Keys | `sdg_` + 12-character lookup id + 40-character secret (CSPRNG, base62), only the lookup id and a SHA-256 stored, constant-time compare, shown once (`no-store`); immutable; 25 per user; `write` / `evaluate` include `read`; expiry 1 h–366 days; restriction to 1–50 projects (`uuid[]`); dormant after 30 days without a sign-in (people only); works only while its creating sign-in method is available; c20 (no break-glass keys); deactivation revokes | `app/api_keys/`, `app/auth/key_auth.py`, `sources.py` |
| Authorisation | The API-key principal source first in `PRINCIPAL_SOURCES` (bearer never falls back to the cookie; no CSRF); effective permission = owner (live) ∩ scopes ∩ projects through the one policy; every operation classified for keys (`ROUTE_KEY_ACCESS`, deny by default); session-only rules (key management, admin, settings, inbox, `idea.delete`, `idea.moderate`); throttles (30 failures per address, 300 requests and 30 writes per key a minute, refusals counted); the key check in its own short transaction; service accounts never own or admin, are private non-members where they have no role, and search only co-members | `app/authz/keys.py`, `rules.py`, `policy.py`, `queries.py`, `app/services/users.py` |
| MCP server | `POST /mcp` (the SDK's low-level `Server`, stateless JSON, 1 MiB); the guard (method → Origin → key → rate → c15 → Content-Type; Host-check exempt; no cookies, no CORS); one dispatcher (unknown tool, argument validation with write tools refusing unknown arguments, the write cap, the key re-checked in the tool's transaction, error mapping, exactly one `mcp.call` audit entry, 90-day retention); nine tools over the REST services (blind evaluation and holds by construction, held ideas `not_found` for everyone, bounded results, untrusted text marked, invisible characters stripped) | `app/mcp/` (`guard.py`, `server.py`, `dispatcher.py`, `tools.py`, `audit.py`, `text.py`) |
| Suggestions | Whole-section suggestions (REST create / list / accept / discard; MCP `propose_proposal_section`; `source` `api`, `mcp` or `ai`); one pending per author and section; 50 per proposal; accept is a versioned section save; the editor's cards with a word-level diff, who decides, Accept / Discard with Undo, focus to the next; the Proposal tab's count for deciders | `app/proposals/suggestions.py`, `features/proposal/suggestions.tsx`, `features/idea/idea-page.tsx` |
| Screens | Settings → API keys (plain-words "Can" column, presets, live "This key can …", the one-time secret with "I've copied it", lost projects counted, expiry warnings, revoke / remove, "For developers and AI assistants" with Claude Code, Claude Desktop through `mcp-remote`, `mcpServers` and curl examples); Settings → All API keys (search by name, owner or a pasted key cut to its prefix, state filter, `?user_id=`, lost projects struck through, revoke); the audit log's "API keys and MCP" category | `frontend/src/features/api-keys/`, `features/admin/audit/` |
| Platform | Helm `ingress.mcp`, `kagent.*` (RemoteMCPServer example, NetworkPolicy for kagent's namespace); `make mcp-smoke`; `k3s-smoke MCP=1` with the official Python SDK in a pod of another namespace and a Secret-held key; CI's k3s job `SSO=1 SMTP=1 MCP=1` | `deploy/helm/`, `deploy/kagent/`, `scripts/mcp-smoke.sh`, `scripts/k3s-mcp-client.sh` |
| Tests | Backend 5,849 (840 in the Phase 5 modules: keys, authz for keys, MCP, suggestions, the API acceptance, schemas; tests first for key scoping, MCP authorisation, blind and hold filtering and audit completeness), frontend 516 unit + 333 page tests, e2e 232 (dev login) / 253 (SSO) against the real stack | `backend/tests/`, `frontend/`, `e2e/tests/` |
| Docs | Contract, role matrix §1, §5, §6, ADR 0013 (accepted, amended), decisions, [mcp.md](../mcp.md) (connecting clients, tools, safety), user guide (keys, assistants, suggestions, All API keys, audit), operator guide (keys, exposing `/mcp`, proxies, limits, audit, checks, kagent), test plan | `docs/` |

## Acceptance evidence

All run on 2026-10-06 in the final verification, on the working tree that was committed.

| Criterion | Evidence (test names) |
|---|---|
| **An MCP client with a key searches ideas and submits an evaluation only in permitted projects; revoking the key cuts access immediately**, in the browser | `e2e/tests/api-keys.spec.ts` AC5-01: Carol creates "Claude Desktop" in Settings → API keys ("Evaluate with an assistant", "Only these projects", 30 days); the key is shown once, copied with Copy and read back from the clipboard, then found nowhere (page, URL, storage, cookies, the list); bearer only (no cookie, no CSRF): REST narrowed to the project (404 outside); `/mcp` `initialize` (no session id), nine tools, `list_projects`, blind `search_ideas awaiting_my_evaluation` and `get_idea`, `get_rubric`, `submit_evaluation`, then the aggregate; the other project's idea `not_found` although she may evaluate it in the app; `create_idea` `insufficient_scope`; the audit viewer's sentences; revoke in the UI → the very next `tools/call` and REST call 401 |
| The same over TCP with the official `mcp` 2.x client and the demo data | `backend/tests/acceptance/test_phase5_acceptance.py::test_ac5_api_1_an_mcp_key_searches_and_evaluates_only_where_it_reaches` (live uvicorn; draft then submit; every score field walked while blind; `not_found` outside the key for `get_idea`, `submit_evaluation`, `get_rubric`, `search_ideas project=`; one `mcp.call` per call read through the admin API; revoke → the open client's next call, a new connection, raw JSON-RPC and REST all 401; no log record holds the key or the evaluation's text); `::test_ac5_api_2_a_pending_evaluators_key_gets_no_scores`, `::test_ac5_api_3_deactivating_the_owner_revokes_their_keys`, `::test_ac5_api_4_*` (an agent's key: member rules, blind, left out of the aggregate, never owner or admin) |
| The same on Kubernetes, through the ingress and the cluster Service | `make k3s-smoke MCP=1`: `scripts/mcp-smoke.sh` through Traefik (key → initialize → nine tools → blind search → submit → `not_found` outside → `insufficient_scope` → foreign Origin 403 → audit → revoke → 401), then `scripts/k3s-mcp-client.sh`: the Python SDK in a pod in namespace `kagent` with its key from a Secret, calling `http://soundings.soundings.svc.cluster.local:80/mcp`, and a pod in another namespace refused by the NetworkPolicy; see [Checks](#checks-final-verification-2026-10-06) |
| Key scoping: every rule × scope × restriction × owner role; live narrowing; session-only rules (tests first) | `tests/authz/test_key_scopes.py` (15 scope sets × 4 restrictions × the matrix's columns, checked to bite), `test_key_narrowing.py` (restriction everywhere, platform admins' keys, deleted projects), `test_key_routes.py` (every operation classified; session-only routes 403 for a key with all four scopes), `tests/api_keys/test_guards.py`; e2e AK-02, AAK-05 |
| Revocation and expiry immediacy; demotion; a request already let in | `tests/api_keys/test_lifecycle.py::test_revoking_through_the_api_cuts_access_at_once`, `tests/mcp/test_transport.py::test_revoking_cuts_the_next_request_mid_session`, `::test_an_expired_key_is_401`, `tests/mcp/test_held_requests.py` (revoked, expired, deactivated, demoted while the body was held: nothing changes), `tests/test_principal.py`; e2e AC5-01, AAK-02, AAK-04 |
| MCP tool authorisation, blind evaluation and moderation holds (c12) | `tests/mcp/test_tools.py` (every tool's scope, each column, the restriction, the REST codes), `test_blind.py::test_a_pending_evaluators_key_gets_no_score_data`, `::test_a_project_admin_who_owes_an_evaluation_is_blind_too`, `::test_sort_by_score_puts_the_hidden_idea_last`, `::test_a_service_account_evaluates_blind`, `::test_held_ideas_are_not_found_through_any_tool`, `tests/authz/test_service_account_access.py` (232) |
| Every call audited (rule, decision, user, key id; no arguments or PII) | `tests/mcp/test_audit.py::test_every_outcome_is_audited_once`, `::test_a_denied_write_leaves_only_its_entry`, `::test_writes_keep_their_own_entries`, `::test_a_validator_that_crashes_is_audited_as_an_internal_error`, `::test_a_cancelled_call_is_audited`, `::test_no_entry_or_log_line_holds_a_key_or_an_argument`, `::test_the_cleanup_removes_only_old_mcp_call_entries`, `::test_the_hourly_schedule_runs_the_mcp_call_cleanup`, `test_transport.py::test_a_key_without_the_mcp_scope_is_403_and_audited_once_a_minute`; e2e AC5-01, AAK-02 |
| Phase 6 readiness: `propose_proposal_section` creates a pending suggestion the owner accepts or discards | `tests/proposals/test_suggestions.py` (every column, c7, archived, held, no proposal, one pending per author, the 51st, `base_version`, conflicts, the discard-accept race, `source` per author and channel), `tests/mcp/test_tools.py::test_an_agents_suggestion_is_ai`; e2e SG-01…04 |
| Final-verification decisions | L2: `test_schemas_phase5.py::test_write_arguments_refuse_unknown_ones`, `tests/mcp/test_tools.py::test_a_misspelt_write_argument_is_refused_not_ignored`; nit 2: `test_schemas_phase5.py::test_people_written_text_is_marked_untrusted`; M4 input: `tests/ideas/test_input_robustness.py::test_request_models_reject_tag_characters_anywhere`, `::test_one_line_names_reject_every_tag_character`, `::test_tag_characters_in_any_text_are_a_422`, `tests/mcp/test_hidden_text.py::test_tool_arguments_with_tag_characters_are_a_validation_error`, `tests/identity/test_claims.py::test_display_name`; L4: `tests/api_keys/test_service_accounts.py::test_an_agent_finds_only_people_who_share_a_project_with_it`, `::test_an_agents_people_search_stays_inside_its_keys_projects`, `::test_an_agent_without_a_project_finds_nobody`; UX m1: `tests/api_keys/test_lifecycle.py::test_unavailable_projects_are_counted_for_the_owner_and_marked_for_admins`, `key-parts.test.tsx`, e2e AAK-06; UX M4 / M5: e2e AC5-01, A11Y5, K5-01, SG-01, `frontend/tests/api-keys.spec.ts`, `proposal-suggestions.spec.ts` |

### Checks (final verification, 2026-10-06)

| Check | Result |
|---|---|
| `make -C backend check` | pass: ruff, ruff format (370 files), mypy --strict (367 files), pytest 5,849 passed, 1 skipped (the empty stub list), 1 deselected (slow); Postgres, Mailpit and Keycloak testcontainers; 16.4 min |
| `make -C backend test-slow` | pass (10k-idea performance, 46 s) |
| `npm --prefix frontend run check` | pass: tsc, eslint + prettier, vitest 64 files / 516 tests, build (after the last change, again) |
| `npm --prefix frontend run test:pw` | 332 passed, 177 skipped (screenshot specs), 1 failed: Phase 1's `project-board.spec.ts` "moves a card with the keyboard" (the announcer missed "Move cancelled" under load); `project-board.spec.ts` `--repeat-each=5`: 60 of 60 passed, so a load flake, untouched by this phase; 11.9 min |
| `npm --prefix e2e test` (dev login, break-glass, worker, Mailpit) | pass: 232 passed, 26 skipped (`@sso`-only, `E2E_SMTP=0`-only, PA-06), `serial` and `smtp-outage` included, 9.3 min; after the last copy change `admin-api-keys.spec.ts` and `api-keys.spec.ts` again (12 passed, AAK-06 included) |
| `E2E_SSO=1 npm --prefix e2e test` | pass: 253 passed, 5 skipped, 9.8 min |
| `npm --prefix e2e run check`, `make check-helm`, `make check-scripts`, shellcheck (container) on `scripts/`, `scripts/lib/`, `e2e/scripts/` | pass |
| `make gen-api` | no diff after the additive m1 fields were generated |
| F811 in `tests/api_keys/test_connections.py` and `tests/authz/test_service_account_access.py` (the TaskCompleted gate) | already fixed in the committed tree: ruff clean (the gate runs `make -C backend check`, above) |
| `make image` | `soundings:p5-final`, 520 MB (507 MB in Phase 4); the build renders a PDF; in the image (read-only root, no network) `app.mcp` imports and the new rules are there (`MCP_WRITE_INPUT_CONFIG` forbids, tag characters detected) |
| k3s | `k3s-up` (`K3S_NAME=p5-final-k3s`), `k3s-keycloak`, `k3s-mailpit`, `k3s-install SSO=1 SMTP=1 MCP=1` (as CI: demo seed Job, Restricted PSS, NetworkPolicy admitting only Traefik and the `kagent` namespace), `k3s-smoke SSO=1 SMTP=1 MCP=1`: the standard smoke, public form, ALTCHA and PDF export, SSO through Keycloak, email with Mailpit down and up, then **MCP through the ingress** (405, 401 problem+json with the bearer challenge, malformed key, `/.well-known` 404; carol's key with `read` added, cookie-only 401; `initialize` stateless at protocol 2025-11-25; nine tools with schemas; `list_projects` only Customer Innovation; blind `search_ideas` / `get_idea`; `get_rubric`; `submit_evaluation`; the aggregate after; TOOLS `not_found`; `create_idea` `insufficient_scope`; foreign Origin 403; a read-only key 403 at c15; carol's `mcp.call` entries (7 allowed, 2 denied, and the c15 refusal); revoke → 401 on `/mcp` and REST), **the official Python SDK in a pod in `kagent`** with its key from a Secret calling `http://soundings.soundings.svc.cluster.local:80/mcp` (initialize, nine tools, search; 401 after the revoke), a pod in another namespace dropped by the NetworkPolicy, and `helm test`; then **`helm upgrade`** with changed values (`logLevel=DEBUG`, `api.replicas=2`; both Deployments rolled) → the same smoke again, passed on two API replicas; the API and worker logs at DEBUG held no full key and no `Authorization` header; `k3s-down` |

## Review findings and outcomes

Two reviews ran after the build: a security review (code, OWASP ASVS L2, the MCP
server's threat model) and a UX and accessibility review (the real stack at 1440 light
and dark and 390 px). Backend fixes were test-first, frontend fixes came with unit, page
and e2e tests. Findings the fixers left open (contract-owned or needing a product call)
were decided by the lead and applied in this close-out.

### Security

| # | Finding | Outcome | Tests |
|---|---|---|---|
| H1 (high) | Parallel requests with fresh keys held two pool connections each: the pool stalled 15 s, then 500 | Fixed: the key check and `last_used_at` run in one short transaction closed before the request's session; `/mcp` holds no session at the door | `tests/api_keys/test_connections.py` (4, pool 1 + 1); live: 12 fresh keys in 0.12 s on a pool of 1 |
| M1 | A request let in before a revoke still ran its tool (an idea was created) | Fixed: each tool call re-reads the key and owner in its transaction; tool error `unauthorized`, audited as a denial | `tests/mcp/test_held_requests.py` (5) |
| M2 | Refusals of a key without `mcp` weren't rate-limited and each filled an audit entry | Fixed: rate before c15, refusals count; audited once per key a minute | `test_transport.py::test_a_key_without_the_mcp_scope_is_403_and_audited_once_a_minute`, `::test_refusals_of_a_key_without_mcp_count_towards_its_request_budget` |
| M3 | A service account read every internal project | Fixed: without a role it is NMp everywhere; lists and restrictions follow | `tests/authz/test_service_account_access.py` (232) |
| M4 | Invisible Unicode (tag characters) reached agents verbatim | Fixed, output: every result string cleaned (`app/mcp/text.py`). **Lead decision, fixed, input:** request bodies, one-line names and tool arguments refuse tag characters (422 / `validation_error`), IdP names are stripped | `tests/mcp/test_hidden_text.py`, `tests/ideas/test_input_robustness.py` (3 new), `test_claims.py` |
| L1 | Some refusals weren't audited (crashing validator, cancellation, the budget's 429) | Fixed: `internal_error`, `cancelled`, `too_many_attempts` once a minute; the SDK's 415/406/400 aren't tool calls (documented) | `test_audit.py` (2 new), `test_transport.py::test_a_key_over_its_request_budget_is_audited_once_a_minute` |
| L2 | A typo'd write argument (`sumbit`) was ignored and the default applied | **Lead decision, fixed:** write tools forbid unknown arguments; read tools keep ignoring them | `test_schemas_phase5.py::test_write_arguments_refuse_unknown_ones`, `test_tools.py::test_a_misspelt_write_argument_is_refused_not_ignored` |
| L3 | A proxy adding its own `Authorization: Bearer` breaks every browser request | Documented (Helm README, operator guide, mcp.md); no fall-through by design | — |
| L4 | Agents' keys could search the whole people directory | **Lead decision, fixed:** a service account finds only co-members, inside its key's projects | `test_service_accounts.py` (3 new) |
| Nits | Long field names echoed; output fields without `UNTRUSTED`; a partly typed key in the admin search URL; bound values in database errors; suggestion check order | Fixed (field names cut to 40 and cleaned; **lead:** `display_name`, `status_label`, criteria's text, suggestion `body_md` marked; the search cuts to the prefix; `hide_parameters=True`; 404 → 403 → 422 → 409) | `test_hidden_text.py::test_error_messages_cut_and_clean_the_callers_own_field_names`, `test_schemas_phase5.py::test_people_written_text_is_marked_untrusted`, `api-keys.test.tsx`, `test_db.py::test_database_errors_never_carry_bound_parameters`, `test_suggestions.py::test_a_base_version_above_the_section_is_422_before_the_409s` |

### UX and accessibility

| # | Finding | Outcome |
|---|---|---|
| M1 | Admin State menu rows overflowed | Fixed in the design system (`FilterMenuOption` descriptions on two lines) |
| M2 | Long owner names collapsed to "R…" in the admin table | Fixed: name and prefix on line 1, owner alone on line 2 with Dormant |
| M3 | A key's risk wasn't said in plain words | Fixed: the "Can" column, "This key can …" in the dialog, "Treat it like a password: anyone who has it can act as you: …"; the `mcp` scope is "AI assistants (MCP)" |
| M4 | "AI evaluator" read as SPEC §9's agent | **Lead decision, accepted:** "Evaluate with an assistant" / "Read with an assistant" ("…they count as yours") |
| M5 | Suggestions sat unseen outside the Proposal tab | **Lead decision, accepted:** a count on the Proposal tab for people who can decide; no notification in Phase 5 |
| m1 | The owner's and the admin's project lists disagreed silently | **Lead decision, fixed:** `unavailable_project_count` ("+1 project you can no longer open") and `owner_can_view` (struck through for admins) |
| m2–m9 | Expiry didn't stand out; the new-key dialog closed without a copy check; identical scroll-area names; line-only diffs; no hint who decides; focus after Undo; a stale unsaved-edits warning; a contradictory break-glass page | Fixed (warning tone within 7 days and expired keys last with Remove; "I've copied it" with one reminder; distinct names; word-level highlights; "Ada decides whether to use it."; focus to the next pending suggestion; Accept saves a waiting autosave first; one empty state) |
| p1–p9 | Placeholder in Name, the developer section always open, "via MCP", AI facts note, audit monospace, agent revoke copy, phone counts, Created in a tooltip, a nudge towards "Only these projects" | Fixed |

### Final verification (this close-out)

- **Lead decisions on the reviews**, test-first where they touch the API:
  - **UX M4 / M5 accepted** as the frontend fixer applied them; contract §3.1 and §3.10,
    the user guide, mcp.md and dev/README follow.
  - **UX m1:** `ApiKey.unavailable_project_count` and `AdminApiKey.projects[]` as
    `AdminApiKeyProject` with `owner_can_view` (additive, `make gen-api`, contract §8);
    `KeyProjects` says "+N project(s) you can no longer open", `AdminKeyProjects` strikes
    them through with a tooltip and screen-reader text; the mock follows.
  - **Review L2:** `MCP_WRITE_INPUT_CONFIG` (`extra="forbid"`) on the four write tools'
    inputs; the read tools keep `extra="ignore"`.
  - **Review nit 2:** `McpUser.display_name`, `McpIdeaRef.status_label`, the new
    `McpRubricCriterion` (name, description, guidance) and `McpProposalSuggestion`
    (`body_md`) carry `UNTRUSTED` in the published output schemas.
  - **Review M4, input side:** `reject_hidden` (NUL and tag characters) on every
    `RequestModel` string and the read tools' arguments; `has_control` (so `SingleLine`)
    includes tag characters; sign-in strips them from IdP display names. The
    output-side tests now plant hidden text in the database, as old data would be.
  - **Review L4:** `search_users(co_members_of=…)` for service accounts.
  - **F811** in the two new backend test modules: already gone in the committed tree
    (`scripts/check-task.sh backend` passes).
- **Stale tests and specs found:** the Phase 5 screenshot spec still chose "AI evaluator"
  and the "Connect an MCP client" region (both renamed by the UX fixes); it now opens "For
  developers and AI assistants" and shows the m1 states (Carol leaves a private "Partner
  pilots" project that a key of hers is restricted to). The MCP tests that sent tag
  characters or an ignored extra argument were rewritten for the new rules.
- **New e2e:** AAK-06 (a project the owner can no longer open: counted in Settings → API
  keys, struck through in All API keys, `owner_can_view` in the API).
- **Docs:** contract §3.1, §3.3–§3.7, §3.10, §4.2, §4.4, §8 (five rows); role matrix §1,
  §5, §6; ADR 0013 amendment; decisions ("Phase 5 review and final verification"); user
  guide; operator guide (re-checks, lost access, agents' keys, the proxy note, text for
  agents, audited refusals); mcp.md; test plan (new tests, screenshots); frontend and dev
  READMEs; CLAUDE.md.

## Known issues and deferred items

| Item | Why / when |
|---|---|
| A real kagent install against `/mcp` is untested | kagent.dev is blocked here; the Go SDK kagent 0.10.2 pins was checked against the server (`deploy/kagent/README.md`). Phase 6. |
| Rate limits are per API pod's memory | Like the sign-in throttles: with N replicas a client gets up to N times as much; they bound floods and runaway agents, not determined attackers. |
| Discarding a suggestion waits for its Undo toast (about 6 s) | An MCP client may see it pending meanwhile. |
| No notification for new suggestions; no in-app "Suggest" button | A new `NotificationType` needs the SPA's maps (Phase 6); people edit sections directly (`can_suggest` unused by the SPA). |
| Subdivision flag emoji (England, Scotland, Wales) are refused in request text | They are built from Unicode tag characters, which now never enter the database (review M4). |
| A person's restricted key still searches the whole people directory | Accepted in the contract (names and emails, no project data; pickers and @mentions need it); agents' keys are limited to co-members since this close-out. |
| Key rotation with an overlap, per-key IP allow-lists, OAuth for MCP, `tools/list` filtered by scopes, MCP resources | Not needed for keys issued in the app (contract §7). |
| The GitLab pipeline was not run in this sandbox | Sandbox only. |

## Simplifications proposed (SPEC section 15, item 3)

Each avoided a settings screen, a dependency or a moving part; all are in
[decisions.md](../decisions.md).

1. **Immutable keys:** create and revoke is the whole lifecycle; no rename, no renewal,
   no scope edits.
2. **A project restriction is a `uuid[]` on the key,** not a join table: it can only
   shrink when projects go.
3. **Dormant keys instead of mandatory expiry:** a person's key pauses after 30 days
   without a sign-in and resumes at the next one.
4. **No new settings:** every limit and the `mcp.call` retention are constants.
5. **Stateless JSON MCP,** `POST /mcp` only: no sessions, streams or server-to-client
   messages to operate.
6. **One dispatcher** over the REST services instead of tool-specific authorisation.
7. **Suggestions are whole-section texts,** accepted as a normal versioned save: no diff
   format, no merge.

Questions for the product owner: is pausing a person's keys after 30 days without a
sign-in acceptable for people who only use scripts? Should a new suggestion notify the
idea's owner in Phase 6 (in-app only, or email too)?

## Screenshot index

Real app, freshly seeded demo data, the real worker and Mailpit (`npm --prefix e2e run
screenshots:phase5`); 1440 × 900 light and dark, 390 × 844 light. Every PNG was read; after the last fix (a shorter lost-access line and a wider Projects column in All API keys) Phase 5 was captured again and the changed screens read again. Phases 1–4 were re-captured too (`screenshots`, `screenshots:phase2`: an SSO run then a break-glass run, `screenshots:phase3` with `emails/`, `screenshots:phase4` with `pdf/` and `emails/`); every file was rewritten, so no stale files remained. The
frontend's mock set is in [`mock/`](../screenshots/phase-5/mock/) (26).

| Screen | Light | Dark | Phone |
|---|---|---|---|
| Settings → API keys (Carol: three keys, the plain-words "Can" column, one used by an MCP client a moment ago, one with "+1 project you can no longer open") | [1440](../screenshots/phase-5/api-keys-1440-light.png) | [1440](../screenshots/phase-5/api-keys-1440-dark.png) | [390](../screenshots/phase-5/api-keys-390-light.png) |
| Settings → API keys, "For developers and AI assistants" opened | [1440](../screenshots/phase-5/api-keys-connect-mcp-1440-light.png) | [1440](../screenshots/phase-5/api-keys-connect-mcp-1440-dark.png) | [390](../screenshots/phase-5/api-keys-connect-mcp-390-light.png) |
| Create key ("Evaluate with an assistant", 30 days, one project; "This key can …") | [1440](../screenshots/phase-5/api-keys-create-dialog-1440-light.png) | [1440](../screenshots/phase-5/api-keys-create-dialog-1440-dark.png) | [390](../screenshots/phase-5/api-keys-create-dialog-390-light.png) |
| The new key, shown once (revoked as soon as it was on screen) | [1440](../screenshots/phase-5/api-keys-secret-reveal-1440-light.png) | [1440](../screenshots/phase-5/api-keys-secret-reveal-1440-dark.png) | [390](../screenshots/phase-5/api-keys-secret-reveal-390-light.png) |
| Settings → All API keys (Alice: everyone's keys; the project Carol left struck through) | [1440](../screenshots/phase-5/admin-api-keys-1440-light.png) | [1440](../screenshots/phase-5/admin-api-keys-1440-dark.png) | [390](../screenshots/phase-5/admin-api-keys-390-light.png) |
| Proposal editor with two pending suggestions (CUST-6: Carol's through MCP, Bob's through the API) | [1440](../screenshots/phase-5/proposal-pending-suggestions-1440-light.png) | [1440](../screenshots/phase-5/proposal-pending-suggestions-1440-dark.png) | [390](../screenshots/phase-5/proposal-pending-suggestions-390-light.png) |
| Audit log, "API keys and MCP" | [1440](../screenshots/phase-5/audit-api-keys-and-mcp-1440-light.png) | [1440](../screenshots/phase-5/audit-api-keys-and-mcp-1440-dark.png) | [390](../screenshots/phase-5/audit-api-keys-and-mcp-390-light.png) |
