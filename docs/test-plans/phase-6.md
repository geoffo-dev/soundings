# Test plan: Phase 6 (kagent AI assistance)

Owner: qa. Source of truth for behaviour: [SPEC.md](../../SPEC.md) sections 9 and 13,
[contract-phase6.md](../api/contract-phase6.md) (agents §3.1, URL building and SSRF §3.2,
runs §3.3, A2A §3.4, authorisation and c22 §3.5, SSE §3.6, AI evaluations §3.7, research
notes §3.8, drafts §3.9, audit §3.10, the fake agent §3.12, minimum tests §3.13,
acceptance §3.14, screens §3.15), [role-matrix.md](../role-matrix.md) (section J, §3
rules 1, 9 and 10, c10, c22) and [ADR 0014](../adr/0014-kagent-a2a-integration.md). Each
row has an ID used in the test names, so a failing test points back here. The Phase 1–5
plans ([phase-1.md](phase-1.md) … [phase-5.md](phase-5.md)) still apply; their suites run
in every mode next to the Phase 6 specs.

## What is verified against what

There is no kagent installation and no LLM here. Everything Soundings does is real; two
things stand in for kagent:

| Part | Verified against | How |
|---|---|---|
| kagent **v0.10.2 CRDs** (`agents.kagent.dev` v1alpha2, `remotemcpservers`, `modelconfigs`): our example `Agent`, `RemoteMCPServer`, `ModelConfig` and Secret manifests and the chart's `kagent-agents.yaml` | **real kagent** (its CRDs from git tag v0.10.2 in k3s v1.31; server-side dry run and real create/read/delete) | platform: `scripts/k3s-kagent-crds.sh`, `make k3s-install AI=1`; see `deploy/kagent/README.md` "What is verified" |
| kagent's controller: the A2A proxy at `/api/a2a/{ns}/{name}/` (port 8083), its task store, `X-User-Id` sessions, 1.0 translation | **not verified** (no controller runs here: the chart's blobs come from a host this network refuses) | the fake agent serves the same layout; contract §8 |
| The agents' A2A server (0.3 `message/stream`, `tasks/get`, `tasks/cancel`; 1.0 `SendStreamingMessage`, …), streaming order, `final`, error codes | **a2a-sdk 1.2.1's server** (the fake agent, `dev/fake-agent`) and a2a-sdk 0.3.23's client (kagent-adk 0.10.2's library) against it | platform's fake-agent tests; every run below |
| The agent's MCP calls into Soundings (`/mcp`, its service-account key, c22, rule 9, result matching) | **the fake agent**, calling Soundings' real `/mcp` over TCP with the key the admin API showed once | AC6-API-*, every e2e spec below |
| Soundings' worker, A2A client, run lifecycle, SSE, the UI | **real** (procrastinate pools, httpx over TCP, uvicorn, Chromium) | everything below |
| An LLM following the run message (tools in order, real sources, no scores in notes) | **not verified**: the fake is deterministic; the server enforces what matters regardless | — |

So: "the whole loop except the LLM and kagent's controller" is exercised for real; the
fake proves our client against a2a-sdk's server, not against kagent's controller.

## Acceptance criterion

> "Ask AI to evaluate" produces a badged, cited evaluation excluded from the aggregate by
> default. (SPEC section 13, Phase 6; contract-phase6 §3.14)

It is tested at two levels, each adding something the other can't:

| Level | Test | What it adds |
|---|---|---|
| HTTP over TCP, live server, real worker, the real fake agent | `backend/tests/acceptance/test_phase6_acceptance.py` **AC6-API-1** | The app behind **uvicorn** on a free port with the **demo data**, the worker's **two procrastinate pools** in the same event loop with their default timings, the worker's real A2A client over TCP to **`dev/fake-agent` started as a subprocess** (`uv run`), which calls back into the live `/mcp` with the key. The contract's steps 1–8: Alice registers "Idea evaluator" (`soundings/idea-evaluator`, evaluate + research) for Customer Innovation: 201, `Cache-Control: no-store`, the key once (pattern, prefix), the Secret manifest (`soundings-agent-idea-evaluator`, `Bearer <key>`), the built A2A and card URLs, the service account a member, scopes `read evaluate mcp write`; the list never holds the key; the key goes to the agent; **Test connection** is ok (card, streaming, 0.3 and 1.0). CUST-12 (Bob and Carol submitted, Farah and Mateo pending; aggregate n=2). **Two racing requests → one 201 and one 200, same run**; a third → 200 queued; the agent is an invited AI evaluator. **Farah opens the event stream while the run is still queued**, then the worker starts: the stream carries exactly *Waiting to start → Sending the request to the agent → The agent started → The agent is working → Read the rubric → Read the idea → Saved its evaluation → Evaluation submitted → Done* (ids 1–9, `retry: 3000`, `no-cache`, `X-Accel-Buffering: no`, only the last `final`), nothing of the evaluation; replay after `Last-Event-ID: 5`, `?after=7`, the header winning over `?after`, **204** after the end. The run `succeeded` with `result.evaluation_id`; the AI evaluation has a rationale and two sources per criterion (`example.org`, host shown), `include_in_aggregate: false`, people's evaluations no sources; the **aggregate is unchanged**; Farah and Mateo get `score_hidden`, `{items: [], score_hidden: true}`, no score field anywhere (walked) and none of the agent's words in the idea, evaluations, runs, run detail or feed. **Include → n 3, the means move (Value = (2×4.0+3)/3), recommendations +1; include again changes nothing; exclude → identical aggregate**; Bob 403, Farah 404, a person's evaluation 409 `not_ai_evaluation`. "Research this" → a note with three sources in the feed, attached to its run (`Read the idea → Wrote the research note → Research note saved → Done`), `can_delete` for the owner only. The admin adds `draft_section` (**the same key**: no new Secret) and "Draft section" on **CUST-6**'s Risks → an `ai` suggestion the owner accepts. With no run open the key gets 403 `insufficient_scope` on REST (also requesting a run), lists nothing on `/mcp`, `ai_run_not_active` for `get_idea`, `get_rubric`, `add_research_note`, `forbidden` for `add_comment`. The audit through the admin API: `ai_agent.register`, `api_key.create` (rule `platform.manage_agents`, restricted), `project.member_add`, `ai_agent.update` (`purposes`), three `ai_run.request` (the 200s not audited), `evaluator.add` (rule `ai.request_evaluation`), the agent's `evaluation.submit` with its key id, `evaluation.include_ai` (include, exclude), the agent's `mcp.call` entries in order with `api_key_id` and the denials; **no secret anywhere in the audit, no log record of ours or the fake's holds the key or the agent's text**. |
| Browser, real stack | `e2e/tests/ai-acceptance.spec.ts` **AC6-01** | Through the UI with a project and an agent of its own: the owner's AI menu ("Research this" offered too), the toast, the agent in the evaluators list with "AI agent"; **the run card fed by the SSE request** (not the polling fallback) through every step to "Evaluation submitted"/Done, no agent text in it, the row's Submitted tick; **the score line unchanged ("3.0 / 5 · 2 evaluations")**; "View the evaluation" → the Evaluations tab with the AI card focused: "AI agent", "Not in score", a rationale for each of five criteria, five source lists ("Sources cited by AI, not checked", ten links, `rel="noopener noreferrer nofollow"`, new tab, `https://example.org/…`, host shown), people's cards in the score; **"Include in score" → toast, "2.9 / 5 · 3 evaluations"; off → back to 3.0 / 2**; stored `include_in_aggregate: false`; reconnecting to the finished stream → 204; the agent's key with no open run: `list_projects` empty, `ai_run_not_active`, REST 403 `insufficient_scope`. |

The rules behind it are unit-tested by their owners (tests first): `backend/tests/ai/`
(backend: 105 test functions, 167 cases, in `test_a2a_client.py`, `test_agents.py`, `test_results.py`,
`test_runner.py`, `test_runs_api.py`, `test_scope.py`, `test_sse.py`,
`test_worker_pools.py`, on an in-process MockTransport kagent), the identity guard tests
(`tests/authz/`, `tests/auth/test_api_key_source.py`), the fake agent's own tests
(`dev/fake-agent/tests/`, 38, including a2a-sdk 0.3.23's client) and the SPA's page tests
against the MSW mock (`frontend/tests/ai.spec.ts`, `admin-ai-agents.spec.ts`). The
tables below map each rule to them; the e2e suite covers what only a browser, a real
worker, a real agent process and the whole stack can show.

## How to run

| What | Command | Needs |
|---|---|---|
| API acceptance (part of `make check-backend`) | `cd backend && uv run pytest tests/acceptance/test_phase6_acceptance.py` (about 60 s: one demo seed, a 30-second deadline) | Docker (Postgres testcontainer) or `TEST_DATABASE_URL`; `uv` and `dev/fake-agent` (synced on first use); `SOUNDINGS_TEST_FAKE_AGENT=0` skips it |
| E2E with AI (all suites) | `E2E_AI=1 npm --prefix e2e test` | the local stack + the fake agent on 8183 (`E2E_FAKE_AGENT_PORT`) |
| Only the Phase 6 specs | `E2E_AI=1 npx --prefix e2e playwright test --grep @ai --project=e2e` (CI's `e2e-ai` job) | |
| E2E without AI / with SSO | `npm --prefix e2e test`, `E2E_SSO=1 npm --prefix e2e test` (the `@ai` specs skip, saying why) | |
| Screenshots | `npm --prefix e2e run screenshots:phase6` → `docs/screenshots/phase-6/` (sets `E2E_AI=1`) | fresh demo data (the local stack reseeds) |
| The curl version of the acceptance | `make ai-smoke` (platform: `scripts/ai-smoke.sh`) | an app with AI on and the fake agent |

**AI specs in e2e** (`e2e/tests/support/ai.ts`). Every spec registers agents of its own
through the admin API (run-unique names; the name's suffix picks the fake's behaviour:
`-slow`, `-lingers`, `-fails`, `-asks`, `-blind-probe`, …) for a project of its own
(`aiTeam`: Alice is its admin, a person created for the team owns the ideas and asks for
the runs, since each person may ask for 20 an hour and the suite asks for about 60; Bob
and Carol score, Farah is pending), and hands the key
to the fake with `FakeAgent.giveKey` (`e2e/scripts/fake-agent.ts`) as an operator applies
the Secret; `retireAgents` disables them at the end (runs stop, keys revoked). So they run
side by side and never touch the stack's own "Idea evaluator". `skipWithoutAi` skips
unless AI is on and the fake answers; specs are tagged `@ai`. Against `E2E_BASE_URL`
(`make demo DEMO_AI=1`, CI's main e2e job) set `E2E_FAKE_AGENT_URL` and
`E2E_FAKE_AGENT_KEYS_DIR`. The run time limit test (RUN6-03) needs a limit of at most two
minutes (the stack's `E2E_AI_RUN_TIMEOUT=PT1M`), else it skips.

## Rules and where they are tested

### Agents, service accounts and keys (§3.1)

| Rule | Unit (backend) | E2E / acceptance |
|---|---|---|
| Registering creates the service account (member of each project), one key (scopes from purposes, restricted to the projects), shown once with the Secret manifest; audited | `test_agents.py::test_registering_creates_the_service_account_membership_and_one_key`, `::test_key_scopes_follow_the_purposes` | AC6-API-1, AA6-01 (the sheet; `no-store`; the dialog with key, Secret and RemoteMCPServer; copied to the clipboard; then nowhere: page, URL, storage, list; the service account `is_service_account` and a member; its key in Admin → API keys) |
| Namespace and name are DNS labels; the A2A URL is built from the controller in effect, never typed | `test_registration_refusals`, `tests/test_schemas_phase6.py` (URL builder) | AA6-01 (`idea.evaluator` refused on the field, the namespace lower-cased as typed, the preview `<controller>/api/a2a/soundings/<name>/`), AC6-API-1 / -2 (`a2a_url`, `card_url`, the 1.0 layout `/agents/{ns}/{name}`) |
| A taken namespace/name → 409 `agent_taken` | `test_registration_refusals` | AA6-01 (said on the field) |
| Purposes and projects change the same key (no new Secret) | `test_purposes_and_projects_change_the_same_key_and_memberships` | AC6-API-1 (`draft_section` added: same key id, then a draft run works) |
| Rotation revokes the old key at once | `test_rotation_revokes_the_old_key_in_the_same_change` | AA6-02 (the confirm, `no-store`, `revoked_key_id`, the old key 401 on `/mcp`, the new one works for a run, "Used …" after reload) |
| Disabling cancels the runs and revokes the key; enabling needs a rotation | `test_disabling_cancels_everything_and_revokes_the_key` | AA6-03 (a working run → cancelled; the key 401; no agent offered: `no_agent`; Enable's toast offers "Rotate key"; `key: null`) |
| Test connection reads the built card URL only; failures are answered | `test_connection_reads_the_built_card_url_only`, `::test_connection_failures_are_answered_not_raised`, `::test_connection_tests_are_limited` | AC6-API-1 (ok, card), AA6-01 (the dialog: card URL, 200, streaming Yes, 0.3), AA6-02 (no key at the fake → "didn’t answer", `Couldn't reach the agent. (HTTP 404)`, "What to check") |
| Session only, platform admins only; c20 | `test_the_break_glass_account_cannot_register_or_rotate`, `tests/authz/test_route_rules.py` | AA6-04 (Bob 403 and no "Register agent"; Alice's own full key 403 `insufficient_scope`) |

### Runs: lifecycle, A2A, timeout and cancel (§3.3–3.4)

| Rule | Unit (backend) | E2E / acceptance |
|---|---|---|
| queued → running → succeeded; the steps as Soundings' sentences | `test_runner.py::test_an_evaluation_run_end_to_end` | AC6-API-1 (the exact nine steps over SSE), AC6-01 |
| Idempotent: one active run per idea + agent + kind (+ section); concurrent requests → 201 + 200 | `test_runs_api.py::test_a_repeated_request_returns_the_active_run`, `::test_concurrent_requests_make_one_run` | AC6-API-1 (racing requests, then a third 200) |
| "Ask AI to evaluate" assigns the agent; a run that ends without its evaluation takes the assignment back (`evaluator_removed`, no actor, `reason: ai_run_ended`) | `test_asking_to_evaluate_assigns_the_agent_once`, `test_runner.py::test_a_failed_evaluation_run_takes_its_assignment_back_and_all_evaluations_are_in` | AC6-API-2 (cancelled and needs-input runs: only Pat left; audit `evaluator.remove` actor null), RUN6-01 (the row goes; the feed says the run ended without an evaluation), RUN6-02 |
| Cancel while queued: cancelled at once, nothing sent; finished → 409 `ai_run_finished` | `test_cancel_while_queued_sends_nothing`, `test_runs_api.py::test_cancel_queued_running_and_finished` | AC6-API-2 (events `queued, cancelled`, never `started_at`, the fake never saw it even after the worker started) |
| Cancel while running: `cancel_requested`, `tasks/cancel`, cancelled | `test_cancel_while_running` | AC6-API-2 (the fake's `cancel_requests ≥ 1`, its task `canceled`; Pat's stream ends "Cancelling → Cancelled"), RUN6-01 (one line while it works: the current step, "Working", "N min left"; the row's Cancel keeps focus while busy, then "Cancelled: nothing was saved." with focus on the row and "Try again"; "Cancelling" under Steps; the fake saw `tasks/cancel`; a second cancel 409), AD6-02 (a draft cancelled in place) |
| A cancel answered −32603 (kagent-adk 0.10.2) still ends cancelled | `test_a2a_client.py::test_cancel_accepts_any_answer` | AC6-API-2 (`-no-cancel`) |
| Nothing after the end: a late write is refused | `test_results.py::test_nothing_is_attached_or_recorded_after_a_cancel_request`, `test_scope.py` | AC6-API-2 (`-late`: its `submit_evaluation` after the cancel → `ai_run_not_active`; no evaluation) |
| The deadline: `tasks/cancel`, `timed_out` | `test_the_deadline_cancels_the_task_and_times_out` | AC6-API-2 (30 s, the fake saw the cancel), RUN6-03 ("N min left" or "under a minute left" on the row while it works, then "The agent didn’t finish within 1 minute." and "Try again: it may have been busy."; the deadline itself is under Steps) |
| Endings without a result: `no_result`, `agent_needs_input`, `agent_failed`; unknown agent (404) → `agent_unreachable` without retries | `test_each_ending`, `test_a2a_client.py::test_http_errors_are_unreachable_with_the_status` | AC6-API-2 (`-silent`, `-asks`, `-fails`: code, Soundings' sentence as the last event), RUN6-02 (the rows: Soundings' plain words by error code with a next step, never "(state …)", the server's sentence under Steps; "Try again" asks again, the failed run moves to "History (1)" and focus follows the new row; a draft agent without its key → `Couldn't reach the agent. (HTTP 404)`, no `retrying` event) |
| What Soundings sends: the built URL's layout, `X-User-Id: soundings`, no credentials or cookie, no `contextId`, `messageId` = run id, nothing secret in the message; `historyLength: 1` when polling | `test_a2a_client.py::test_only_the_built_url_is_requested_with_exactly_these_headers`, `::test_polling_asks_for_one_history_entry` | AC6-API-2 (every run's observations: `x_user_id`, `authorization: none`, `cookie: false`, `context_id_sent: false`, `message_checks` no URL and no key) |
| A2A 1.0 (`kagent_v1_0`, optional) | `test_a_kagent_10_agent`, `test_the_message_is_sent_as_a2a_03_and_10` | AC6-API-2 (`SendStreamingMessage` with `A2A-Version: 1.0` at `/agents/…`, the same three tools, succeeded) |
| Worker pools, shutdown (`worker_lost`), the sweep, 200-event cap | `test_worker_pools.py`, `test_runner.py::test_stopping_the_worker_ends_the_run_worker_lost`, `::test_the_sweep_ends_lost_and_stale_queued_runs`, `::test_a_run_keeps_at_most_200_events_the_final_included` | (unit; platform drove SIGTERM against the fake) |
| Who may ask and cancel (c5/c6/c7, c10 in each part, holds, archive, keys) | `test_runs_api.py` (24) | AR6-02 (Kenji, a member: no AI menu, 403, `research_blocked_by: not_allowed`, `can_cancel` false), BL6-01 (Farah: no Cancel), AD6-02 (`proposal_not_available`; no proposal → 404; Bob `not_allowed`, no "Draft with AI"), AR6-01 (a research-only agent: "Ask AI to evaluate" disabled with "No AI agent serves this project") |

### Live progress: SSE (§3.6)

| Rule | Unit (backend) | E2E / acceptance |
|---|---|---|
| Replay after `Last-Event-ID` / `?after=` (header wins); live events; close after the final one; 204 on reconnect | `test_sse.py::test_replay_after_last_event_id_or_after_then_close`, `::test_live_events_arrive_and_the_stream_ends_after_the_final_one` | AC6-API-1 (a stream opened while queued, live through the worker; every replay form; 204), AC6-01 (the page uses the stream; 204 after) |
| Problems before any stream byte; 5 streams per person; re-checks; 10-minute limit | `::test_problems_come_before_any_stream_byte`, `::test_five_open_streams_per_person`, `::test_the_recheck_follows_the_session_and_idea_view`, `::test_a_stream_ends_after_its_maximum_duration` | (unit) |
| Blind: a pending evaluator's stream holds no score, recommendation, rationale, source or comment | `::test_a_pending_evaluator_watching_an_ai_evaluation_learns_no_score_data` | AC6-API-1 (Farah's stream: no agent text, no score keys), BL6-01 (the replay from the start: "Evaluation submitted" but nothing of it) |

### AI evaluations and the aggregate (§3.7)

| Rule | Unit (backend) | E2E / acceptance |
|---|---|---|
| Left out by default; include / exclude change and restore the aggregate; idempotent | `test_results.py::test_an_ai_evaluation_is_left_out_until_someone_includes_it` | AC6-API-1, AC6-01, BL6-02 (the probe's evaluation left out: n 2) |
| A changed re-submission is left out again | `::test_a_changed_re_submission_leaves_the_aggregate_again` | (unit: the fake submits once) |
| The toggle: owner and admins only; a pending evaluator 404; a person's evaluation 409; a draft 404 | `::test_the_toggle_refusals`, `::test_a_draft_ai_evaluation_is_404_for_the_toggle` | AC6-API-1, BL6-03 (Bob reads "Not counted in the score", no switch, 403; Farah 404) |
| A rationale for every score; sources only from agents, plain ASCII, unsafe URLs refused | `::test_an_ai_evaluator_must_give_a_rationale_for_every_score`, `::test_people_never_cite_sources`, `::test_sources_are_stored_as_plain_ascii`, `::test_unsafe_source_urls_are_refused` | AC6-API-1 (every criterion, `host`), AC6-01 (links `rel`, target, host) |
| The AI badge wherever its work appears | (frontend `ai.spec.ts`) | AC6-01 (evaluator row, card), AR6-01 (note), AD6-01 (suggestion), screenshots |

### Rule 9 and c22: agents stay blind and in their run (§3.5)

| Rule | Unit (backend) | E2E / acceptance |
|---|---|---|
| Rule 9: the agent's `get_idea` / `search_ideas` show `score_hidden`, no score, aggregate, evaluations or disagreement, before and after it submits, on evaluate and research runs; its own evaluation is `my_evaluation` | `test_scope.py::test_an_agent_never_sees_others_scores` | AC6-API-2 and BL6-02 (`-blind-probe` on an idea two people scored: every probe hidden; `my_evaluation_state: submitted` after) |
| c22: without an open run the key does nothing; REST always 403 `insufficient_scope` | `test_scope.py::test_without_an_open_run_an_agent_can_do_nothing`, `test_runs_api.py::test_an_agents_key_is_refused_on_every_rest_route` | AC6-API-1 step 8, AC6-01 |
| c22: during a run only its idea, only its kind's write tool; `add_comment` / `create_idea` forbidden; another idea, another section, another kind's tool → `ai_run_not_active`; lists only the run's project and idea | `::test_an_open_run_reaches_its_idea_only`, `::test_a_draft_run_writes_its_section_only` | AC6-API-2 (`-strays`: the exact codes, `list_projects` = the project, `search_ideas` = the idea, no comment written; then it still succeeds) |
| `add_research_note` never for people; a service account without an agent is refused everything | `::test_people_never_write_research_notes`, `::test_a_service_account_without_an_agent_is_refused_everything` | (unit) |

### Research notes and drafts (§3.8–3.9)

| Rule | Unit (backend) | E2E / acceptance |
|---|---|---|
| A note per run in the feed with the AI label, untrusted Markdown, numbered sources, attached to its run | `test_results.py::test_a_research_note_is_written_replaced_read_and_deleted` | AC6-API-1, AR6-01 (headings and list rendered; three links, `rel`, target, host; "Check the facts…"; the fake called `get_idea`, `add_research_note`), AR6-02 (two runs, two notes) |
| Delete: the owner and admins (`ai.delete_note`), confirmed; the feed keeps a line | same | AR6-01 (Bob: no actions; Alice deletes: toast, the line, `deleted: true`, text and sources gone) |
| Draft: the run's section only, as an `ai` suggestion the owner accepts | `test_runner.py::test_research_and_draft_runs_attach_their_results` | AC6-API-1 (CUST-6 Risks, accepted), AD6-01 (in place; only Risks; `get_idea`, `get_proposal`, `propose_proposal_section`; Accept → the section holds the text), AD6-02 (cancel in place; "Try again") |

### Audit (§3.10)

| Rule | Unit | E2E / acceptance |
|---|---|---|
| `ai_agent.register` / `.update`, `ai_run.request` (not for a 200), `ai_run.cancel`, `evaluation.include_ai` (on change), `evaluator.add` / `.remove`, the agent's `evaluation.submit` and `mcp.call`; never keys | `test_results.py::test_the_call_is_audited_once_as_mcp_call`, `test_agents.py` | AC6-API-1 (each entry's actor, target and details; no secret in the whole log), AC6-API-2 (`ai_run.cancel`, `evaluator.remove` with no actor) |

### Accessibility, phones, keyboard

| ID | What | Spec |
|---|---|---|
| A11Y6 | axe (WCAG 2.2 AA), light and dark: Admin → AI agents, the register sheet filled in, the key shown once, a test result, the idea's AI menu, a live run card, finished runs and a research note, an AI evaluation with its switch, the same idea as a pending evaluator, the proposal editor with a draft in progress and an AI suggestion | `a11y-phase6.spec.ts` |
| MO6-01 | The same screens at 390 px: no sideways scrolling; sheets and dialogs within the screen (inset dialogs keep their 16 px gutter) | `a11y-phase6.spec.ts` |
| K6-01 | "Research this" with the keyboard only (Enter on "AI actions", arrows, Enter; focus back on the button), then Enter on "Read the note" focuses the note | `a11y-phase6.spec.ts` |

## Specs

| ID | What | Spec |
|---|---|---|
| AC6-01 | The acceptance through the UI (above) | `ai-acceptance.spec.ts` |
| BL6-01 | Farah watches a `-lingers` run live (its evaluation already saved): its Steps up to "Evaluation submitted", still Working, no Cancel, no "View the evaluation", no AI actions, no score line; nothing of the evaluation on the page, in **any JSON response the page received** or in the stream; the owner cancels: "Cancelled · its evaluation was submitted", the result stays; after Farah submits she reads it ("Not counted in the score", no switch) | `ai-blind.spec.ts` |
| BL6-02 | Rule 9 through the agent's own calls (`-blind-probe`, evaluate and research) | `ai-blind.spec.ts` |
| BL6-03 | Non-owners can't include (Bob: text, no switch, 403; Farah 404) | `ai-blind.spec.ts` |
| AR6-01/02 | Research notes (above) | `ai-research.spec.ts` |
| RUN6-01/02/03 | Cancel, failures and "Try again", the deadline (above) | `ai-runs.spec.ts` |
| AD6-01/02 | Draft with AI, accepted; cancelled; who and when (above) | `ai-draft.spec.ts` |
| AA6-01…04 | Admin → AI agents (above) | `ai-admin.spec.ts` |
| AC6-API-1/2 | The acceptance and how runs end, over TCP with the real fake agent (above) | `backend/tests/acceptance/test_phase6_acceptance.py` |

Phase 5's `e2e/tests/support/mcp.ts` lists ten tools now (`add_research_note`), so
`api-keys.spec.ts` (AC5-01) checks the Phase 6 catalogue.

## Results (2026-10-06)

| Run | Result |
|---|---|
| `uv run pytest tests/acceptance` (Phases 1–6) | 17 passed (AC6-API-1/2 about 60 s of the 132 s) |
| `E2E_AI=1` full suite (local stack, fake agent) | 264 passed + `serial` 2 + `smtp-outage` 2; 26 skipped (`@sso`); KB-09 failed once under load (passes 5/5 alone; now waits for the save) |
| Default mode (no AI) | 227 passed + 2 + 2; 63 skipped (`@sso`, and the 37 `@ai` tests saying why); PR4-02 failed once under load (passes 3/3; now waits for the save) |
| `E2E_SSO=1` | 253 passed (all projects), 42 skipped (`@ai`, break-glass) |
| The image: `make demo DEMO_AI=1` + `E2E_BASE_URL` (CI's main e2e job; `E2E_FAKE_AGENT_KEYS_DIR=dev/.fake-agent-keys`) | 267 passed, 28 skipped (RUN6-03: the demo's limit is 5 minutes); `--grep @ai` alone 36 + 1 skipped |
| `npm --prefix e2e run check` | tsc + prettier clean |
| `npm --prefix e2e run screenshots:phase6` | 33 screenshots (11 screens × 3) |

The two load flakes were Phase 1 and 4 specs reading the API right after an optimistic
UI update (KB-09 owner, PR4-02 resolve); they now poll. No defect found by these tests
is open; the frontend's question (a run ending without an evaluation records
`evaluator_removed` with no actor, worded as the run ending) is confirmed on the real
stack (RUN6-01, AC6-API-2).

## Deviations from contract §3.14

- **Step 7, the draft:** CUST-4 is *closed* in the real demo data (the "ready to start"
  CUST-4 is the SPA mock's), so c7 refuses it; the acceptance drafts **CUST-6**'s Risks
  (Alice's, in Proposal) instead.
- **Step 1, purposes:** registered with evaluate and research as written; `draft_section`
  is added before step 7 with `update_ai_agent`, which also checks that the key follows
  the agent (same key id, no new Secret).
- **"The agent saw `score_hidden: true` throughout" (step 7):** checked with a
  `-blind-probe` agent on an idea two people scored (AC6-API-2, BL6-02); the acceptance's
  own agent is a plain one, so its stream shows exactly the steps of step 4.

## Observations for owners (not failing tests)

All fixed at integration (2026-10-06; `docs/decisions.md`, "Phase 6 build and
integration", Screens): one evaluate label everywhere, the agent's full name in the
comparison, the AI badge on the agent's feed lines (`frontend/tests/ai.spec.ts`), the
preview shows `{name}` for refused names (`agent-rules.test.ts`), the key dialog opens on
itself, "Draft" on phones, the admin list refetched after runs, and `cancel_requested`
false once a run has ended (`tests/ai/test_runs_api.py`).

| Owner | Observation | Where |
|---|---|---|
| frontend | The AI menu says "Ask AI to evaluate" while the evaluators list says "Ask AI to evaluate again" for the same agent after it submitted | `ai-menu-*.png` |
| frontend | The Evaluations comparison table heads the agent's column "Idea" (the first word of "Idea evaluator") | `ai-evaluation-included-*.png` |
| frontend | Activity lines by or about the agent ("Idea evaluator submitted an evaluation", "invited Idea evaluator") carry no AI label (contract §3.7: the badge wherever its work appears); only the research note has one | `research-note-*.png` |
| frontend | The register sheet's "Soundings will call …" preview shows an invalid name verbatim (`…/soundings/idea.evaluator/`) while the field is in error; the server refuses it anyway | AA6-01 |
| frontend | The key dialog opens with focus on the copy button, whose tooltip ("Copy the agent’s key") covers part of the header, also on phones | `admin-key-reveal-*.png` |
| frontend | At 390 px "Draft with AI" is a bare sparkles icon beside Write/Preview (its label is screen-reader only) | `draft-with-ai-390-light.png` |
| frontend | Admin → AI agents keeps "Not used yet" after the agent's first run until the page is reloaded (the list isn't refetched) | AA6-02 |
| backend | Cancelling a *queued* run answers `cancelled` with `cancel_requested: true` (harmless: the SPA shows "Cancelled") | AC6-API-2 |

## Screenshots

`npm --prefix e2e run screenshots:phase6` writes `docs/screenshots/phase-6/`
`<screen>-<1440-light|1440-dark|390-light>.png` from freshly seeded data: `ai-menu` (CUST-12's
AI menu; "Ask AI to evaluate again" in the evaluators list), `run-live` ("Market
researcher", a `-slow` fake, working: one row with the current step, the time taken and
left, and Cancel; Idea evaluator's finished rows, older runs folded under "History"), `ai-evaluation` (Idea evaluator's card: "Not in score", the switch, a rationale
and sources per criterion), `ai-evaluation-included` (switched on: 3.6 / 5 · 3
evaluations, High disagreement, the AI column in the comparison; desktop at 1440 × 2100 so
the score, the table and the card fit), `research-note` (the note in the feed),
`pending-evaluator` (Farah, blind, the AI evaluator Submitted among the others),
`draft-with-ai` (CUST-6's Risks with Idea evaluator's suggestion), `admin-agents`,
`admin-register-agent`, `admin-key-reveal` (the agent is disabled as soon as its key is on
screen: the key opens nothing) and `admin-test-connection`.
