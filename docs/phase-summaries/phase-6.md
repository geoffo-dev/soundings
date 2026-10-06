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

@@ACCEPTANCE@@

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

@@FINAL@@

