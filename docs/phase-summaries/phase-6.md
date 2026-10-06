# Phase 6 summary: kagent AI assistance

**Status:** closed on 2026-10-06, waiting for the product owner's review.
**Scope (SPEC sections 9 and 13):** kagent agents registered in Admin settings → AI agents
(namespace/name, protocol, purposes, projects) with a service account and one scoped key;
"Ask AI to evaluate" (the AI evaluator: a cited evaluation with an AI badge, left out of
the aggregate until the owner includes it), "Research this" (a cited research note in the
activity feed) and "Draft with AI" (a proposal suggestion the owner accepts or discards);
durable runs executed by the worker over A2A with a deadline and cooperative cancel,
live progress over SSE; agents act back through Soundings' MCP server; optional Helm
templates for example Agents and their `RemoteMCPServer`s, off by default.
**Acceptance:** "Ask AI to evaluate" produces a badged, cited evaluation excluded from the
aggregate by default. Met against Soundings' fake kagent agent: see
[Acceptance evidence](#acceptance-evidence). **No kagent controller or LLM exists on the
build machine:** see [What is verified against kagent](#what-is-verified-against-kagent-and-what-only-against-the-fake).

Commits: `a381651`, `452e131` (contract and its review), `09a7cbb` (build and
integration), `ef33c57` (security and UX review fixes), plus this close-out (lead
decisions on the reviews, final verification, k3s, screenshots, docs).

## What was built

| Area | What | Where |
|---|---|---|
| Contract | 16 REST operations (6 admin, 10 runs / toggle / notes), the SSE stream, migration 0011 (`ai_agents`, `ai_agent_projects`, `ai_runs`, `ai_run_events`, `evaluation_scores.sources`; the existing `users.is_service_account` and `evaluations.include_in_aggregate` reused), table J (`ai.request_evaluation`, `ai.research`, `ai.draft_section`, `ai.cancel_run`, `evaluation.include_ai`, `ai.delete_note`), c10 and c22, rule 9, six audit actions, the MCP tool `add_research_note` (ten tools) and `run_id` on every tool | [contract-phase6.md](../api/contract-phase6.md) (§10 lists every change after the contract), `backend/app/schemas/ai.py`, `mcp.py`, [ADR 0014](../adr/0014-kagent-a2a-integration.md), [role matrix](../role-matrix.md) section J |
| Agents | Registration (namespace and name as DNS labels inside the allowed namespaces, protocol `kagent_v0_10` or `kagent_v1_0`, purposes, 1–50 projects): a service account, member roles, one server-managed key (scopes from purposes, restricted to the projects) shown once with its Secret and `RemoteMCPServer`; the key follows changes; narrowing cancels runs; rotate; disable revokes; Test connection fetches the card (5 s, 64 KiB, no redirects); c20 (break-glass can't register, rotate or widen) | `app/ai/agents.py`, `app/api/v1/admin_ai_agents.py` |
| Runs | Rows (`ai_runs`, `ai_run_events`, compare-and-set transitions, lock order project → idea → run), one active run per idea + agent + kind (+ section), 20 requests per person an hour; the worker's own `ai` procrastinate pool; the hand-written A2A client (0.3 `message/stream`, `tasks/get`, `tasks/cancel`; 1.0 `SendStreamingMessage`, `GetTask`, `CancelTask` with `A2A-Version: 1.0`; URL only from `agent_a2a_url`, `trust_env=False`, size caps); deadline then `tasks/cancel` and `timed_out`; cooperative cancel; retries only before a task exists; `worker_lost` on shutdown; the sweep | `app/ai/runs.py`, `runner.py`, `tasks.py`, `a2a.py`, `transitions.py` |
| Agents act through MCP | c22: REST refused; every call names its open run (`run_id`) and reaches only that run's idea, checked before any lookup; one write tool per kind; results matched to the run by the server, never by agent text; `tool_called` events in Soundings' words; rule 9 (always blind; own evaluation only in its evaluate run); agent text stripped of bidi and zero-width characters | `app/ai/scope.py`, `results.py`, `notes.py`, `app/mcp/tools.py`, `dispatcher.py` |
| Evaluations, notes, drafts | AI evaluations with a rationale and up to 5 cited sources per criterion, left out of the aggregate until `set_evaluation_inclusion`, reset by a changed re-submission; research notes (one per run, feed item, `ai.delete_note`, audited `ai_note.delete`); drafts as Phase 5 suggestions (`source: ai`) | `app/ai/results.py`, `notes.py`, `app/services/scoring.py` |
| Live progress | SSE per run (`Last-Event-ID` replay, 204 after the final event, 5 streams per person and 100 per process, re-check every 30 s, 10-minute limit), polling fallback | `app/ai/sse.py`, `frontend/src/features/ai/use-run-progress.ts` |
| Screens | Admin settings → AI agents (settings in effect, register sheet with the built URL preview, key shown once with a 3-step dialog, Test connection with "What to check", rotate, disable, change); the idea's AI menu and ⌘K; run rows (one per agent and kind, Steps, History, plain-words errors, Cancel, Try again); the AI evaluation card (rationale, "Cited by AI, not checked", "Include in score"); "1 AI evaluation not counted · Review"; research notes in the feed; "Draft with AI" in the proposal editor; AI badges everywhere; `<Markdown untrusted>` | `frontend/src/features/ai/`, `features/admin/ai-agents/`, `features/idea/`, `features/proposal/` |
| The fake agent | `dev/fake-agent`: a deterministic kagent stand-in on a2a-sdk 1.2.1's server at kagent v0.10.2's paths (and 1.0's), a card, streaming, `tasks/get`, `tasks/cancel`, a real MCP session back into `/mcp` with the agent's key (passing `run_id`), behaviours by name suffix, observations without keys or text; its own uv project, image and tests (38) | `dev/fake-agent/` |
| Platform | Helm `features.ai`, `kagent.*` (controller URL, token Secret, agent namespaces, examples), `ai.*`, NetworkPolicies (agent pods in, controller out); example manifests (`deploy/kagent/agents.yaml`, `fake-agent-byo.yaml`, the chart's `kagent.examples`); `make ai-smoke`, `make demo DEMO_AI=1`, `make k3s-fake-agent`, `make k3s-kagent-crds`, `k3s-install AI=1`, `k3s-smoke AI=1`; the e2e stack's `E2E_AI=1` | `deploy/helm/`, `deploy/kagent/`, `scripts/ai-smoke.sh`, `scripts/k3s-*.sh`, `e2e/scripts/` |
| Docs | Contract, role matrix J, ADR 0014, decisions (Phase 6 contract, build and integration, review and final verification), [mcp.md](../mcp.md) §5, user guide ("AI assistance", "AI agents"), operator guide ("kagent integration"), [`deploy/kagent/README.md`](../../deploy/kagent/README.md), test plan | `docs/`, `deploy/kagent/` |

## Acceptance evidence

All run on 2026-10-06 in the final verification, on the working tree that was committed.
"The fake" is Soundings' fake kagent agent (`dev/fake-agent`), never a real kagent
controller or a model.

| Criterion | Evidence (test names) |
|---|---|
| **"Ask AI to evaluate" produces a badged, cited evaluation excluded from the aggregate by default**, over HTTP | `backend/tests/acceptance/test_phase6_acceptance.py::test_ac6_api_1_ask_ai_to_evaluate_gives_a_badged_cited_evaluation_left_out` (AC6-API-1): the app on uvicorn with the demo data, the worker's two procrastinate pools, the real fake agent as a subprocess calling back into the live `/mcp` with the key the admin API showed once. Alice registers "Idea evaluator" (key once, `no-store`, the Secret, the built URLs); Test connection ok; two racing requests → one 201 and one 200 (the same run); Farah, a pending evaluator, watches the run over SSE from `queued` to Done (nine fixed sentences, replay by `Last-Event-ID` and `?after=`, 204 after the end) and learns no score data anywhere; the evaluation has a rationale and two cited sources per criterion and `include_in_aggregate: false`; the aggregate is unchanged (n 2); include → n 3 and the means move, exclude → identical aggregate; research note and section draft; the key with no open run does nothing; the audit holds every step and no secret; no log record holds the key or the agent's text |
| The same through the browser | `e2e/tests/ai-acceptance.spec.ts` **AC6-01** (`E2E_AI=1`): the owner's AI menu, the run row fed by the SSE request through every step, the agent in the evaluators list with "AI agent", the score line unchanged ("3.0 / 5 · 2 evaluations"), "1 AI evaluation not counted · Review", the AI card ("Not in score", a rationale per criterion, "Sources cited by AI, not checked", links `rel="noopener noreferrer nofollow"` with their host), "Include in score" → "2.9 / 5 · 3 evaluations", off → back; 204 on reconnecting |
| The same on Kubernetes, through Traefik | `make k3s-smoke SSO=1 SMTP=1 MCP=1 AI=1` → `scripts/ai-smoke.sh` against the fake deployed as `kagent/kagent-controller:8083` (register, key once, Test connection, a pending evaluator's SSE stream with no score data, 204 after the end, the evaluation left out (n 1), included (n 2), left out again, research, draft, a cancelled `-slow` run with `tasks/cancel`, the key refused on REST and outside runs), on one and then two API replicas; see [Checks](#checks-final-verification-2026-10-06) |
| Runs end cleanly; agents stay in their run | `test_phase6_acceptance.py::test_ac6_api_2_runs_end_cleanly_and_agents_stay_in_their_run` (AC6-API-2): cancel while queued (nothing sent) and while running (`tasks/cancel`), a cancel answered −32603, a late write refused, the deadline (`timed_out`), `no_result`, `agent_needs_input`, `agent_failed`, a blind probe, a straying agent (`ai_run_not_active`, `forbidden`), A2A 1.0; e2e RUN6-01…03, AD6-02 |
| AI-run authorisation: c10 and the rules (tests first) | `tests/ai/test_runs_api.py::test_who_may_ask`, `::test_c10_each_part`, `::test_c10_ai_off`, `::test_state_conditions`, `::test_holds_and_archive`, `::test_a_persons_key_needs_write`, `::test_an_agents_key_is_refused_on_every_rest_route`, `::test_service_accounts_never_request_runs`, `::test_cancel_rules`, `tests/authz/test_policy_matrix.py`, `test_route_rules.py`, `test_key_scopes.py`; e2e AR6-02, AD6-02, BL6-03, AA6-04 |
| Excluded from aggregates by default | `tests/ai/test_results.py::test_an_ai_evaluation_is_left_out_until_someone_includes_it`, `::test_a_changed_re_submission_leaves_the_aggregate_again`, `::test_the_toggle_refusals`, `::test_a_draft_ai_evaluation_is_404_for_the_toggle`; e2e AC6-01, BL6-02 |
| Timeout and cancel | `tests/ai/test_runner.py::test_the_deadline_cancels_the_task_and_times_out`, `::test_cancel_while_running`, `::test_cancel_while_queued_sends_nothing`, `::test_cancel_and_completion_end_in_exactly_one_final_status`, `::test_stopping_the_worker_ends_the_run_worker_lost`, `::test_the_sweep_ends_lost_and_stale_queued_runs`, `::test_the_sweep_sends_its_cancels_side_by_side_within_one_deadline`, `test_a2a_client.py::test_cancel_accepts_any_answer`, `::test_a_cancel_and_a_card_fetch_end_within_their_deadline`; e2e RUN6-01, RUN6-03 |
| Idempotency: one active run per idea + agent + kind (+ section) | `tests/ai/test_runs_api.py::test_a_repeated_request_returns_the_active_run`, `::test_concurrent_requests_make_one_run`, `::test_a_finished_run_doesnt_block_a_new_one_and_sections_run_side_by_side`, `::test_asking_to_evaluate_assigns_the_agent_once`, `test_runner.py::test_a_duplicate_job_does_nothing`; AC6-API-1 |
| SSE authorisation and blind safety (a pending evaluator watching an AI evaluation run sees no scores) | `tests/ai/test_sse.py::test_a_pending_evaluator_watching_an_ai_evaluation_learns_no_score_data`, `::test_problems_come_before_any_stream_byte`, `::test_the_recheck_follows_the_session_and_idea_view`, `::test_five_open_streams_per_person`, `::test_streams_are_capped_per_process_too`; e2e BL6-01 (every JSON response the page received and the stream, walked) |
| Agents are blind and bound to their run (rule 9, c22) | `tests/ai/test_scope.py` (11, among them `::test_two_open_runs_of_one_agent_never_reach_each_other`, `::test_an_open_run_needs_its_run_id`, `::test_an_agent_never_sees_others_scores`, `::test_an_agent_sees_its_own_scores_only_in_its_evaluate_run`, `::test_an_agent_cant_tell_which_other_ideas_exist`); e2e BL6-02 |
| SSRF: URLs built from the controller origin + namespace/name only | `tests/test_schemas_phase6.py` (the URL builder, DNS labels), `tests/ai/test_a2a_client.py::test_only_the_built_url_is_requested_with_exactly_these_headers`, `::test_a_redirect_is_never_followed`, `::test_the_client_ignores_proxies_and_netrc_from_the_environment`, `::test_a_proxy_in_the_environment_is_not_used`, `::test_oversized_card_response_and_stream_event_are_protocol_errors`, `test_agents.py::test_connection_reads_the_built_card_url_only`, `::test_namespaces_outside_the_allow_list_are_refused`, `::test_by_default_agents_are_registered_in_soundings_only`; e2e AA6-01 (the URL preview) |
| Agents registered by admins with a scoped key (shown once) | `tests/ai/test_agents.py` (17); e2e AA6-01…04 |
| Research notes in the feed; drafts as suggestions | `test_results.py::test_a_research_note_is_written_replaced_read_and_deleted` (audited `ai_note.delete`), `test_runner.py::test_research_and_draft_runs_attach_their_results`; e2e AR6-01/02, AD6-01/02 |

### Checks (final verification, 2026-10-06)

| Check | Result |
|---|---|
| `make -C backend check` | pass: ruff, ruff format (402 files), mypy --strict (399 files), pytest **6,281 passed**, 1 skipped (an empty stub-route parameter set), 1 deselected (slow); Postgres, Mailpit and Keycloak testcontainers, the Phase 6 acceptance with the real fake agent as a subprocess; 26.2 min. After the last backend edit (`ai_note.delete`) `tests/ai` and `tests/test_schemas*.py` again: 523 passed |
| `make -C backend test-slow` | pass on an idle machine (51 s). The first run, straight after another test session, missed one budget: My work (evaluator) p95 153.4 ms against 150 ms; a third run printed 141 ms (evaluator) and 125 ms (owner), the list and board 32–88 ms, search 18–21 ms, the 10k recompute 1.1 s. My work's code is unchanged since Phase 5: see [Known issues](#known-issues-and-deferred-items) |
| `npm --prefix frontend run check` | pass: tsc, eslint + prettier, vitest **73 files / 582 tests**, build |
| `npm --prefix frontend run test:pw` | pass: **360 passed**, 205 skipped (the screenshot specs), 13.1 min |
| `npm --prefix e2e test` (dev login, break-glass, worker, Mailpit) | pass: **232 passed**, 63 skipped (`@sso`, `@ai`, `E2E_SMTP=0`-only), `serial` and `smtp-outage` included, 9.7 min |
| `E2E_SSO=1 npm --prefix e2e test` | pass: **253 passed**, 42 skipped, 10.2 min |
| `E2E_AI=1 npm --prefix e2e test` (+ the fake agent as the controller) | pass: **269 passed**, 26 skipped, 11.8 min; the 37 `@ai` tests among them (AC6-01, AA6-01…04, BL6-01…03, AD6-01/02, AR6-01/02, RUN6-01…03, 20 A11Y6 axe checks, MO6-01 at 390 px, K6-01 keyboard only) |
| `npm --prefix e2e run check`, `make check-helm`, `make check-scripts`, `make check-fake-agent` (38 tests, a2a-sdk 0.3.23's client included) | pass |
| `make gen-api` | no diff |
| `make image` | `soundings:p6-final`, 521 MB (520 MB in Phase 5); the build renders a PDF; in the image (read-only root, no network) `app.ai.a2a`, `app.ai.scope` and `app.mcp.tools` import and `AuditAction("ai_note.delete")` exists |
| k3s (`K3S_NAME=p6-final-k3s`, the `make image` above, as CI: `SSO=1 SMTP=1 MCP=1 AI=1`) | pass, 9 min in all: `make fake-agent-image`, `k3s-up`, `k3s-keycloak`, `k3s-mailpit`, `k3s-fake-agent` (the fake as `kagent/kagent-controller:8083`), **`k3s-kagent-crds`: kagent v0.10.2's CRDs from its git tag and a server-side dry run of every manifest, the `run_id` system messages included (`deploy/kagent/agents.yaml`, `fake-agent-byo.yaml`, `remote-mcp-server.yaml`, the chart's `kagent.examples`), then each created for real and read back**; `k3s-install` (demo seed Job, Restricted PSS, NetworkPolicies); `k3s-smoke`: the standard smoke, public form, ALTCHA and PDF export, SSO through Keycloak, email with Mailpit down and up, MCP through the ingress (ten tools, blind, `not_found` outside, revoke → 401) plus the official Python SDK in a pod in `kagent` and two pods in other namespaces dropped by the NetworkPolicy, then **`ai-smoke` through Traefik against the fake**: register (key once, `no-store`, the Secret applied), Test connection (the built card URL), Ask AI to evaluate (201, then 200 with the same run), Carol (pending) watches the stream's nine steps with no rationale, source, score or recommendation, 204 after the end, the evaluation left out (3.2, n 1), included (2.9, n 2), left out again, the fake saw `message/stream` with no URL or key in the message and called `get_rubric`, `get_idea`, `submit_evaluation`; research note (3 sources), Risks drafted, a `-slow` run cancelled (`tasks/cancel` seen), the agent's key 403 on REST and listing nothing on `/mcp` outside a run; `helm test`. Then **`helm upgrade`** with `logLevel=DEBUG` and `api.replicas=2` → the same smoke passed on two API replicas; the DEBUG logs of both API pods, the worker and the fake hold no full key and no `Bearer sdg_` header; `k3s-down` |

## What is verified against kagent, and what only against the fake

There is **no kagent controller and no LLM** on the build machine (kagent.dev and ghcr's
blob host are blocked, and no model provider is configured). What was checked against
real kagent artefacts:

| | Against | Status |
|---|---|---|
| Every manifest in `deploy/kagent/` and the chart's `kagent.examples` resources (with the review's `run_id` system messages) | kagent **v0.10.2**'s CRDs from its git tag in k3s v1.31 (`make k3s-kagent-crds`: server-side dry run, then created for real by `k3s-install AI=1`) | **verified against real kagent CRDs** (this close-out) |
| kagent's MCP client (go-sdk v1.6.1) against `/mcp` | the library kagent pins | verified (Phase 5) |
| A2A paths, headers, `A2A-Version` selection, task states, the Python runtime's missing cancel | kagent v0.10.2's source and the kagent-adk 0.10.2 / a2a-sdk 0.3.23 wheels | **read from source**, not run |
| The whole loop: register, Test connection, A2A 0.3 and 1.0 streaming, polling, cancel, deadline, worker shutdown, results through `/mcp`, c22 with `run_id`, blind agents, SSE through Traefik, NetworkPolicies | Soundings' **fake agent** standing in for kagent's controller: backend acceptance, `E2E_AI=1` e2e, `make k3s-smoke AI=1` | **verified against the fake only** |
| kagent's controller proxying A2A to agent pods, its task store, `RemoteMCPServer` `headersFrom` at runtime, kagent 1.0's layout, a model following the run message | — | **not verified** (assumed; the server enforces c22, rule 9, limits and result matching regardless) |

To close the gap on a cluster with kagent: apply `deploy/kagent/fake-agent-byo.yaml` (the
fake behind kagent's real controller, no model), register it and run "Ask AI to
evaluate"; then a Declarative agent with a `ModelConfig` (operator guide).

## Review findings and outcomes

Two reviews ran after the build: a security and code review (the A2A client, SSRF, c22,
blind evaluation, SSE, keys) and a UX and accessibility review (the real stack at 1440
light and dark and 390 px). Backend fixes were test-first (each listed test failed before
its fix); frontend fixes came with unit, page and e2e tests. The lead decided what the
fixers left open in this close-out.

### Security and code

| # | Finding | Outcome | Tests |
|---|---|---|---|
| H1 (high) | Two open runs of one agent reached each other's ideas (an evaluate run on a private project's idea and a research run elsewhere) | Fixed, **lead accepted option 2**: every MCP tool takes `run_id`, required for agents; each call is bound to that open run's idea; the run is checked before any lookup | `tests/ai/test_scope.py::test_two_open_runs_of_one_agent_never_reach_each_other`, `::test_an_open_run_needs_its_run_id`, `::test_a_run_that_ended_stays_ended_while_a_newer_one_is_open`, `::test_without_an_open_run_an_agent_can_do_nothing`, `test_results.py::test_an_agents_calls_become_soundings_sentences_on_the_run_they_name`; live replay against the fake |
| M1 | An agent saw its own scores in research and draft runs (a note could repeat them) | Fixed: `my_evaluation` only in its evaluate run | `test_scope.py::test_an_agent_sees_its_own_scores_only_in_its_evaluate_run`, `::test_an_agent_never_sees_others_scores` |
| M2 | Bidi and zero-width characters in agent text | Fixed: stripped before storing (backend); hosts and link text isolated, the same characters stripped on display (SPA) | `test_results.py::test_an_agents_text_is_stored_without_invisible_characters`, `::test_an_agents_draft_is_stored_without_invisible_characters`, `frontend/src/lib/visible-text.test.ts`, `markdown.test.tsx` |
| L1–L3 | AI suggestions rendered as trusted Markdown; untrusted image links without a host; a new key left in the query cache | Fixed (SPA: `<Markdown untrusted>` for `source: ai`, hosts on image links, `gcTime: 0` and `reset()`) | `markdown.test.tsx`, `ai.test.tsx`, `admin-ai-agents.spec.ts` |
| L4 | Audit gaps: an agent's widened purposes and projects, note deletion | Fixed: `ai_agent.update` records the new values and the key's scopes; **lead: new action `ai_note.delete`** | `test_agents.py::test_purposes_and_projects_change_the_same_key_and_memberships`, `test_results.py::test_a_research_note_is_written_replaced_read_and_deleted`, `audit-phrases.test.ts` |
| L5 | The break-glass account could widen an agent | Fixed: 403 `break_glass_account` | `test_agents.py::test_the_break_glass_account_cannot_widen_an_agent` |
| L6 | No overall cap on SSE streams | Fixed: 100 per API process, then 429 and polling | `test_sse.py::test_streams_are_capped_per_process_too` |
| L7 | A slow controller could hold a cancel or card fetch past its timeout; the sweep cancelled one by one | Fixed: 5 s overall each; the sweep cancels side by side | `test_a2a_client.py::test_a_cancel_and_a_card_fetch_end_within_their_deadline`, `test_runner.py::test_the_sweep_sends_its_cancels_side_by_side_within_one_deadline` |
| L8 | Agents could be registered in any namespace by default (kagent's built-in agents too) | Fixed: default `soundings`, at least one | `test_agents.py::test_by_default_agents_are_registered_in_soundings_only`, `test_config_ai.py::test_defaults`, `::test_agent_namespaces_are_kubernetes_names` |
| N1 | An agent could tell which ideas exist (`not_found` vs `ai_run_not_active`) | Fixed by H1's check order | `test_scope.py::test_an_agent_cant_tell_which_other_ideas_exist` |
| N2 | kagent's session store keeps what agents read | Documented (operator guide, `deploy/kagent/README.md`) | — |

### UX and accessibility

| # | Finding | Outcome |
|---|---|---|
| B1 (blocker) | Focus jumped to the run card when a run ended | Fixed: focus moves only if it was in the row and is lost; the outcome is announced |
| M1 a–d | Focus dropped by the include switch, Cancel, a finished draft and the Test connection dialog | Fixed in the design system (`Switch pending`, `Button loading` = `aria-disabled` + `aria-busy`, `return-focus.ts` finds a closing menu's button) and in the editor (focus to the new suggestion or "Try again") |
| M2 | An AI evaluation wasn't visibly left out | Fixed: "1 AI evaluation not counted · Review", the muted AI column, Mean "counted", "not in the score yet" on the run. **Declined (lead):** the "would be 3.6" preview |
| M3 | Run cards noisy and piling up | Fixed: one row per agent and kind, Steps, History (N), "Try again" on the latest only |
| M4 | Errors read like protocol output | Fixed: plain words by `error.code` with a next step; **lead:** the server keeps its "(state X)" suffix, shown only under Steps |
| m1–m10 | Too many AI labels, a redundant toast, overstated time left, a clipped header at 390, weak onboarding after registering, register sheet rough edges, alarming disabled rows, ⌘K ranking, the audit log not naming the agent, eight "Draft with AI" buttons | Fixed (the "Cited by AI, not checked" label stays: the contract fixes it) |
| p1–p6 | "now" vs "just now", a tooltip after a menu closed, a heavy phone button, re-evaluation wording, truncated names, a cancelled-draft alert | Fixed |
| (lead) | The admin page's dead "Any" namespace fallback | Removed |

### Final verification (this close-out)

- **Lead decisions on the reviews**, applied and tested:
  1. **H1 accepted as built** (`run_id` on every tool, required for agents, checked
     before any lookup): contract §3.1, §3.2, §3.4, §3.5, §4 and §10, ADR 0014, role
     matrix c22 and rule 9 (an agent sees its own evaluation only in its evaluate run),
     mcp.md (people's calls ignore `run_id`), the operator guide (the namespace default;
     N2, kagent's session store) and CLAUDE.md now say so.
  2. **L4's remainder:** `AuditAction` `ai_note.delete` (additive, `make gen-api`,
     contract §10): `app/ai/notes.py:delete_note` records it the first time (target the
     idea; `rule`, `note_id`, `run_id`, `agent_id`; never the note's text); the SPA's
     phrase ("deleted a research note by AI agent X on CUST-7"), its category "AI agents
     and runs", the mock's action list and the exhaustive `Record` in
     `audit-phrases.test.ts` in the same change. Tests:
     `test_results.py::test_a_research_note_is_written_replaced_read_and_deleted`,
     `audit-phrases.test.ts`.
  3. The admin page's dead "Any" namespace fallback removed.
  4. **Declined:** the "would be 3.6" preview (decisions.md, with the error-wording and
     "(state X)" decisions).
  5. The test plan's "Stops by" and always-visible steps follow the run-row redesign.
  6. The kagent example system messages (which now ask for `run_id`) dry-run again
     against kagent v0.10.2's CRDs (see the k3s row above).
  7. All three e2e modes and the full `test:pw` on the combined tree (above).
  8. Every screenshot set re-captured; every Phase 6 PNG read (below).
- **Fixed while verifying:** a flaky Phase 5 page test
  (`frontend/tests/admin-api-keys.spec.ts`, "revokes anyone's key …; focus moves to the
  next key"): since review M1b a busy `Button loading` stays focusable, so a closing
  dialog's focus trap pulled focus back to it; `lib/focus.ts` `focusWhenRendered` now
  keeps trying while focus is held by a dialog or sheet that doesn't contain its target
  (`frontend/src/lib/focus.test.ts`, 3 tests). Three over-long paragraphs in the operator
  guide re-wrapped.
- **Docs:** contract §3.1–3.5, §3.10, §4, §10; role matrix c22 and rule 9; ADR 0014
  notes; decisions ("Phase 6 review and final verification"); mcp.md §4–5; user guide
  ("AI assistance", "AI agents", the audit log); operator guide ("kagent integration");
  test plan; dev README; CLAUDE.md.

## Known issues and deferred items

| Item | Why / when |
|---|---|
| **No kagent controller or LLM has carried a run.** The controller's A2A proxy, its task store for `tasks/get`, `RemoteMCPServer` `headersFrom` at runtime, kagent 1.0's layout and a model following the run message are known from kagent's source only | kagent.dev and ghcr's blob host are refused here (re-checked at this close-out: `pkg-containers.githubusercontent.com` → 403). On a cluster with kagent, apply `deploy/kagent/fake-agent-byo.yaml` (the fake behind the real controller), then a Declarative agent with a `ModelConfig` (operator guide) |
| kagent's Python runtime (kagent-adk 0.10.2) can't cancel: after a cancel or the deadline its task may keep working inside kagent | Soundings ends the run anyway and refuses the task's late writes (c22: `ai_run_not_active`; AC6-API-2's `-late` agent) |
| kagent keeps what agents read (its session store), outside Soundings' deletion, erasure and retention | Review N2: documented (operator guide, `deploy/kagent/README.md`); kagent's own retention applies |
| AI runs and their events are kept forever; no notification when a run ends; no per-agent run history page | Contract §9 (later phases); the audit log has every request and cancel |
| SSE stream caps (5 per person, 100 per API process) live in each process's memory | With N replicas a person can open up to 5 × N streams; beyond the cap the SPA polls |
| An agent's text loses bidi controls before it is stored | Review M2: right-to-left text from an agent still shows, laid out by the browser's default bidi rules |
| My work at 10k ideas runs close to its 150 ms p95 budget on this shared 4-CPU machine (141 ms; one of three runs 153 ms) | Unchanged since Phase 5 (`app/services/work.py`); a candidate for the next performance pass |
| Sources an agent cites may be invented | Shown "Cited by AI, not checked" with their host; no link checking (air-gapped) |
| The new CI jobs (`e2e-ai`, the k3s job with `AI=1`) have not run in a real pipeline | Sandbox only; every command they run passed here |

## Simplifications proposed (SPEC section 15, item 3)

Each avoided a settings screen, a dependency or a moving part; all are in
[decisions.md](../decisions.md).

1. **No URL field anywhere:** an agent's address is built from the controller origin in
   the deployment plus its namespace and name, so there is nothing to validate against
   SSRF in the UI.
2. **One server-managed key per agent,** its scopes and projects following the agent's
   purposes and projects (no per-run keys, no new Secret when an agent gains a project);
   c22 makes it inert outside the agent's open runs.
3. **Results come back only through MCP,** as the agent's service account, through the
   same services and rules as people: no parsing of model output, no output schema.
4. **Runs are rows plus an event log,** executed by the existing procrastinate worker in
   a pool of its own: no new queue, broker or retention job.
5. **AI evaluations are left out until someone includes each one:** no project setting
   for "trust this agent", and no preview of the would-be score.
6. **A hand-written A2A client** (four calls on httpx) instead of a2a-sdk in the backend.
7. **SSE from the API reading the database,** with polling as the fallback: no pub/sub,
   WebSockets or sticky sessions.
8. **One fake agent** stands in for kagent in dev, e2e, CI and k3s, with behaviours chosen
   by the agent's name.

Questions for the product owner: should the person who asked be notified when a run
ends (in-app only)? Should an idea's owner be able to include every AI evaluation of a
trusted agent at once, or stay per evaluation?

## Screenshot index

Real app, freshly seeded demo data, the real worker, Mailpit and the fake agent as the
kagent controller (`npm --prefix e2e run screenshots:phase6`, `E2E_AI=1`); 1440 × 900
light and dark, 390 × 844 light. All 33 PNGs were read after this capture. The three
variants of a screen are taken one after another on the same data, so a later variant
shows what an earlier one did (a cancelled "Market researcher" run, "History (1)" or
"(2)", one more disabled "Proposal drafter"). No defect was found. Phases 1–5 were
re-captured too (`screenshots`, `screenshots:phase2`: an SSO run then a break-glass
run, `screenshots:phase3` with `emails/` and an `E2E_SMTP=0` run, `screenshots:phase4`
with `pdf/` and `emails/`, `screenshots:phase5`): 42 + 39 + 89 + 46 + 21 files, every one
rewritten, so no stale files remained. The frontend's mock set,
[`mock/`](../screenshots/phase-6/mock/) (28, `SCREENSHOTS=1 npx playwright test
ai-screenshots` in `frontend/`), was re-captured after the run-row redesign and read too:
ai-menu (1440 light, dark), ai-run-live (1440 and 390, light and dark), ai-runs-history, ai-run-failed, ai-evaluation (1440 and 390, light and dark), ai-pending-evaluator, ai-research-note (light, dark), ai-draft-section (light, dark), ai-agents (1440 and 390, light and dark), ai-agents-register (light, dark), ai-agents-key (light, dark), ai-agents-test, ai-agents-off, audit-ai.

| Screen | Light | Dark | Phone |
|---|---|---|---|
| Idea page CUST-12, the owner's AI menu ("Ask AI to evaluate again", "Research this" with its agent submenu, the note on what agents may do); the run rows under AI runs; Idea evaluator [AI] among the evaluators | [1440](../screenshots/phase-6/ai-menu-1440-light.png) | [1440](../screenshots/phase-6/ai-menu-1440-dark.png) | [390](../screenshots/phase-6/ai-menu-390-light.png) |
| AI runs: "Market researcher" (a `-slow` fake) working on one line (current step, time taken, "under a minute left", Cancel, Steps); Idea evaluator's finished rows ("Research note saved", "Evaluation submitted · not in the score yet"); older runs under "History (N)"; "1 AI evaluation not counted · Review" under the score | [1440](../screenshots/phase-6/run-live-1440-light.png) | [1440](../screenshots/phase-6/run-live-1440-dark.png) | [390](../screenshots/phase-6/run-live-390-light.png) |
| Evaluations tab: Idea evaluator's card ("Not in score", the Include in score switch off, a rationale and two cited sources per criterion with their host, the summary, "Written by an AI agent…") | [1440](../screenshots/phase-6/ai-evaluation-1440-light.png) | [1440](../screenshots/phase-6/ai-evaluation-1440-dark.png) | [390](../screenshots/phase-6/ai-evaluation-390-light.png) |
| The switch on: 3.6 / 5 · 3 evaluations, High disagreement, the AI column in the comparison table (desktop at 1440 × 2100) | [1440](../screenshots/phase-6/ai-evaluation-included-1440-light.png) | [1440](../screenshots/phase-6/ai-evaluation-included-1440-dark.png) | [390](../screenshots/phase-6/ai-evaluation-included-390-light.png) |
| The research note in the activity feed (AI label, headings and lists, "Cited by AI, not checked" with three numbered sources) | [1440](../screenshots/phase-6/research-note-1440-light.png) | [1440](../screenshots/phase-6/research-note-1440-dark.png) | [390](../screenshots/phase-6/research-note-390-light.png) |
| Farah, a pending evaluator, on the same idea: "Hidden until you submit", the AI evaluator Submitted among the others, no score anywhere | [1440](../screenshots/phase-6/pending-evaluator-1440-light.png) | [1440](../screenshots/phase-6/pending-evaluator-1440-dark.png) | [390](../screenshots/phase-6/pending-evaluator-390-light.png) |
| Proposal editor CUST-6, Risks: "Draft with AI" on the current section and Idea evaluator's AI suggestion (Changes, Discard, Accept) | [1440](../screenshots/phase-6/draft-with-ai-1440-light.png) | [1440](../screenshots/phase-6/draft-with-ai-1440-dark.png) | [390](../screenshots/phase-6/draft-with-ai-390-light.png) |
| Settings → AI agents: the agents (namespace/name, protocol, purposes, projects, key prefix and last use, state, runs in progress; a disabled agent's key "Revoked when disabled"), Settings in effect (controller, protocol, run limit, namespaces `soundings`, MCP URL) | [1440](../screenshots/phase-6/admin-agents-1440-light.png) | [1440](../screenshots/phase-6/admin-agents-1440-dark.png) | [390](../screenshots/phase-6/admin-agents-390-light.png) |
| Register agent sheet: display name, description, namespace ("Allowed: soundings") and name, protocol with each layout, "Soundings will call …" built from the controller in effect | [1440](../screenshots/phase-6/admin-register-agent-1440-light.png) | [1440](../screenshots/phase-6/admin-register-agent-1440-dark.png) | [390](../screenshots/phase-6/admin-register-agent-390-light.png) |
| The agent's key, shown once, with its Secret and `RemoteMCPServer` (the agent was disabled as soon as it was on screen: the key opens nothing) | [1440](../screenshots/phase-6/admin-key-reveal-1440-light.png) | [1440](../screenshots/phase-6/admin-key-reveal-1440-dark.png) | [390](../screenshots/phase-6/admin-key-reveal-390-light.png) |
| Test connection: the card URL, HTTP 200, the card's name, description, A2A versions, streaming and skills | [1440](../screenshots/phase-6/admin-test-connection-1440-light.png) | [1440](../screenshots/phase-6/admin-test-connection-1440-dark.png) | [390](../screenshots/phase-6/admin-test-connection-390-light.png) |

