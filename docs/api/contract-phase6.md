# API contract: Phase 6 (kagent AI assistance)

The REST contract, the A2A interaction, the MCP additions and the business rules for
Phase 6 (SPEC sections 9 and 13): **the AI evaluator** ("Ask AI to evaluate": the worker
asks a registered kagent agent over A2A; the agent reads the idea through Soundings' MCP
tools and submits an evaluation with a rationale and cited sources per criterion; it
appears with an AI badge and is **left out of the aggregate by default**, the owner can
include it) and **the research and drafting assistant** ("Research this" writes a cited
research note into the activity feed; "Draft section" suggests proposal text the owner
accepts or discards, Phase 5's suggestions). Admin settings → AI agents registers agents
(kagent namespace and name, purposes, projects) with their service accounts and scoped
keys; runs are durable records with live progress over SSE, a hard deadline and cancel.
It extends [contract-phase1.md](contract-phase1.md) to
[contract-phase5.md](contract-phase5.md), whose conventions all still apply.

Source of truth, in order: the Pydantic schemas in `backend/app/schemas/ai.py` (agents,
runs, events, citations, research notes, the A2A message `run_message`, the URL builder
`agent_a2a_url`, the fixed event and error messages), the MCP additions in
`backend/app/schemas/mcp.py` (`McpScoreIn.sources`, `McpScoreEntry.sources`,
`ADD_RESEARCH_NOTE`), `AiResearchNoteActivity` in `activity.py`, the route stubs in
`backend/app/api/v1/admin_ai_agents.py` and `ai_runs.py`, the models
(`app/models/ai.py`: `AiAgent`, `AiAgentProject`, `AiRun`, `AiRunEvent`;
`EvaluationScore.sources`; the enums `AiRunKind`, `AiRunStatus`, `AiAgentProtocol`,
`AiRunEventType`, `AiRunError`) with migration `0011`, the settings in
`app/config.py` (`ai_*`, `kagent_*`), exported to `frontend/src/api/generated/`
(`make gen-api`). Rules are named as in [role-matrix.md](../role-matrix.md) (section J
is this phase's authorisation spec; new condition c22); tables in [erd.md](../erd.md);
the design in [ADR 0014](../adr/0014-kagent-a2a-integration.md); what is known about
kagent in [research R2](../research/kagent-a2a-claude-code-frontend.md) and §8 below.

`backend/tests/test_contract_routes.py` pins every method, path and `operation_id` and
keeps a valid request per unimplemented route (`STUBS`, answered 501): delete a row when
you implement it. `tests/authz/test_route_rules.py` names each operation's rules;
`app/authz/keys.py` classifies each for API keys; `tests/test_schemas_phase6.py` pins the
URL builder, the run message, key scopes, citations, the MCP additions and blind safety
by construction; `tests/test_config_ai.py` the settings; `tests/test_domain_schema_phase6.py`
the constraints and the downgrade of 0011.

**Who builds what (suggested):** backend: the agent registry and its service account,
memberships and key (§3.1, with identity's key service), the run service and the
procrastinate job (`run_ai`, §3.3–3.4) with an A2A client, the SSE endpoint (§3.6),
result matching in `save_my_evaluation`, `create_proposal_suggestion` and the new MCP
tool `add_research_note` (§4), the include toggle and research notes (§3.7–3.8), the
`tool_called` events from the MCP dispatcher, the sweep (stale and queued runs), audit
calls at integration (§5); identity: a disabled agent's key refused (401) in the key
source, agent keys exempt from immutability (scopes and restriction follow the agent,
§3.1), c22 in the policy, the session-only gate for the admin routes (already
classified), guard tests; frontend: Admin settings → AI agents, the idea page's AI
actions and run panel (SSE with polling fallback), AI badges, the Evaluations tab's AI
card (rationale, sources, "Not in score" and the toggle), research notes in the feed
(integration), "Draft with AI" in the proposal editor, MSW mocks for the 16 new
operations; platform: the **fake A2A agent** (§3.12; its own image and dev process),
the optional Helm templates and values (§3.11), the worker's (and API's) egress to
kagent, kagent's v0.10.2 CRDs in k3s for server-side dry runs of the example manifests,
`make ai-smoke`; qa: §3.13 and the acceptance §3.14 as API and e2e tests against the
fake agent.

## 1. Conventions (new in Phase 6)

| Topic | Rule |
|---|---|
| Additive only | New endpoints, schemas, tables and enums only. Three things the SPA maps exhaustively land in **one integration step** with the SPA (§5), as in Phases 4 and 5: the `ai_research_note` activity item, `EvaluationScore.sources`, and five `AuditAction` values. They are agreed and modelled now (`AiResearchNoteActivity`, `Citation`, §5), not yet wired. The MCP tool `add_research_note` is defined (`ADD_RESEARCH_NOTE`) and joins `MCP_TOOLS` with its handler. Permission flags the SPA needs come with the new lists (`AiRunList.permissions`), not as new fields on old models. |
| URLs are built, never given | No request field, setting other than `SOUNDINGS_KAGENT_URL`, database column or agent card decides where Soundings sends A2A requests: `agent_a2a_url(kagent_url, protocol, namespace, name)` with DNS-1123 labels (§3.2). No redirects are followed. |
| AI text is untrusted | Everything an agent writes (evaluation comments and rationale, sources, research notes, suggestions, the agent card) is data: rendered as sanitised Markdown (the app's `Markdown`: raw HTML dropped, http/https/mailto links only) with an **AI** label; links `rel="noopener noreferrer nofollow"`, new tab, with the host shown. Agent text is never shown in progress, errors, emails or audit. |
| No secrets in prompts | The A2A message holds references and instructions only (`run_message`): run id, kind, idea key, section, the MCP URL hint, the agent's display name. Never a key, token, idea text or personal data. The agent's MCP key lives only in the operator's Kubernetes Secret (or the fake agent's environment); Soundings shows it once. |
| Blind safety | Runs, events, run lists and permissions hold **no score data** (by construction: `tests/test_schemas_phase6.py`); everyone who may view the idea may watch, pending evaluators included (role matrix §3 rule 1). The agent evaluates blind like a person (rule 9). |
| Order of checks | REST, as before: 401 → 404 → 403 → 422 → 409 → 429. Admin routes: Phase 2's admin order (401 → 422 shape → 403 → 404 → 422 business → 409). The SSE route answers its errors as problem+json before any stream byte. |
| Durable runs | A run is a row (`ai_runs`) from request to a final status; the worker executes it (procrastinate job `run_ai`); its events are rows (`ai_run_events`) replayed to any client. Nothing lives only in a process. |

## 2. Endpoints

Common errors (401, 403 `csrf_failed`, 422 `validation_error`, 400 `invalid_cursor`) are
not repeated. "Session only" = never through an API key (role matrix §5).

### Admin settings → AI agents (`tags: admin`, session only, `platform.manage_agents`)

| Method & path | operation_id | Request → response | Errors |
|---|---|---|---|
| `GET /admin/ai-agents` | `list_ai_agents` | → `AiAgentList {items: [AiAgent], settings: AiSettingsInEffect, max_agents, can_register}` (by display name, disabled ones too; not paged, ≤ 50) | 403 |
| `POST /admin/ai-agents` | `register_ai_agent` | `AiAgentCreate {display_name, description?, namespace, name, protocol?, purposes, project_ids}` → 201 `CreatedAiAgent {agent, key: CreatedApiKey, secret_manifest}`, `Cache-Control: no-store`; audited `ai_agent.register` + `api_key.create` (§3.1) | 403 `forbidden`, `break_glass_account` (c20); 409 `agent_taken`, `too_many_agents`; 422 `invalid_project`, `namespace_not_allowed` |
| `GET /admin/ai-agents/{agent_id}` | `get_ai_agent` | → `AiAgent` | 403; 404 |
| `PATCH /admin/ai-agents/{agent_id}` | `update_ai_agent` | `AiAgentUpdate {display_name?, description?, protocol?, purposes?, project_ids?, enabled?}` (at least one; no nulls) → `AiAgent`; audited `ai_agent.update` | 403; 404; 422 `invalid_project` |
| `POST /admin/ai-agents/{agent_id}/key` | `rotate_ai_agent_key` | no body → 201 `RotatedAiAgentKey {agent, key: CreatedApiKey, secret_manifest, revoked_key_id}`, `Cache-Control: no-store`; audited `api_key.create` + `api_key.revoke` (rule `platform.manage_agents`) | 403 (`break_glass_account`, c20); 404 |
| `POST /admin/ai-agents/{agent_id}/test` | `test_ai_agent` | no body → `AiAgentTest {ok, url, http_status, duration_ms, card, error_code, error_message}` (always 200; §3.2); not audited | 403; 404; 429 (10/min per admin) |

### AI runs, the include toggle and research notes (`tags: ai`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /ideas/{idea}/ai-runs?kind=&limit=` | `list_idea_ai_runs` | `idea.view` (flags from the AI rules, c10) | → `AiRunList {items: [AiRun] newest first (limit 1–50, 20), ai_enabled, agents: [AiAgentRef], permissions: AiPermissions}` | 404 |
| `POST /ideas/{idea}/ai-runs/evaluation` | `request_ai_evaluation` | `ai.request_evaluation` (c6, c10) | `AiRunRequest {agent_id}` → 201 `AiRun` (new) or **200** `AiRun` (the active one, §3.3); assigns the agent as evaluator if needed; audited `ai_run.request` | 403; 404; 409 `evaluation_closed`, `idea_closed`, `ai_unavailable`, `project_archived`, `awaiting_moderation`; 429 |
| `POST /ideas/{idea}/ai-runs/research` | `request_ai_research` | `ai.research` (c5, c10) | `AiRunRequest` → 201 / 200 `AiRun` | 403; 404; 409 `idea_closed`, `ai_unavailable`, …; 429 |
| `POST /ideas/{idea}/ai-runs/section-draft` | `request_ai_section_draft` | `ai.draft_section` (c7, c10) | `AiSectionDraftRequest {agent_id, section_key}` → 201 / 200 `AiRun` | 403; 404 (also: no proposal); 409 `proposal_not_available`, `ai_unavailable`, …; 429 |
| `GET /ideas/{idea}/ai-runs/{run_id}` | `get_ai_run` | `idea.view` | → `AiRunDetail` (the run + every event, oldest first): the polling fallback | 404 |
| `POST /ideas/{idea}/ai-runs/{run_id}/cancel` | `cancel_ai_run` | `ai.cancel_run` | no body → `AiRun` (`cancelled`, or `cancel_requested: true` while the worker stops it); idempotent while active; audited `ai_run.cancel` | 403; 404; 409 `ai_run_finished` |
| `GET /ideas/{idea}/ai-runs/{run_id}/events` | `stream_ai_run_events` | `idea.view` | `Last-Event-ID` header or `?after=` → `text/event-stream` of `AiRunEvent`, or 204 (§3.6) | 404; 429 (5 streams per person) |
| `PUT /ideas/{idea}/evaluations/{evaluation_id}/include-in-aggregate` | `set_evaluation_inclusion` | `evaluation.include_ai` (+ the evaluation visible: `evaluation.view_others`) | `EvaluationInclusionUpdate {include}` → `Evaluation`; idempotent; audited `evaluation.include_ai` (§3.7) | 403; 404 (a draft, another idea's, or any while you are a pending evaluator); 409 `not_ai_evaluation`, `project_archived`, `awaiting_moderation` |
| `GET /ideas/{idea}/research-notes/{note_id}` | `get_research_note` | `idea.view` | → `ResearchNote` (§3.8) | 404 |
| `DELETE /ideas/{idea}/research-notes/{note_id}` | `delete_research_note` | `comment.delete_any` | → 204; idempotent; clears the text and sources (the feed shows "deleted a research note") | 403; 404; 409 `project_archived` |

API keys: the admin routes are session only (403 `insufficient_scope`); the run requests,
cancel, the toggle and note delete need `write` (`ai.*`, `evaluation.include_ai`,
`comment.*` are `write` rules); the reads need `read`. An agent's own key can't request
runs: `ai.*` need the owner or an admin, which a service account never is (no
recursion).

### Unchanged endpoints with new behaviour

- **Evaluations by an AI evaluator** (`save_my_evaluation` through MCP
  `submit_evaluation` with the agent's key): each score may carry `sources` (§4); a
  submission needs a non-empty `comment` (its rationale) for every scored criterion
  (422 `evaluation_incomplete` naming them); the first submission is left out of the
  aggregate (Phase 5); a re-submission keeps the current inclusion; if the agent has a
  running evaluate run on the idea, the evaluation becomes its result (§3.4). REST
  `MyEvaluationIn` takes no sources (people never cite).
- **Suggestions by an agent** (`propose_proposal_section`, `source: ai`): with a running
  draft run for that idea and section, the suggestion becomes its result.
- **`list_evaluations` / `get_idea`**: unchanged until integration, when
  `EvaluationScore` gains `sources` (§5). `IdeaEvaluator.is_ai` and `Evaluation.is_ai` /
  `include_in_aggregate` already exist; the aggregate (`n`, means, disagreement)
  counts included evaluations only.
- **The key source:** a key whose owner is an agent's service account works only while
  the agent is **enabled** (else 401, the one message for all refusals); agents' keys are
  never dormant (Phase 5).
- **`add_project_member` / `remove_project_member`** with an agent's service account
  work as in Phase 5 (member or viewer, never admin, 409 `system_account`): a project
  admin may remove an agent from their project (then c10 fails there) and add it back.
  `search_users` still never lists service accounts; agents are added to projects in
  Admin settings → AI agents.
- **`update_admin_user`** deactivating an agent's service account revokes its key
  (Phase 5); the agent then shows `key: null` and c10 fails until an admin reactivates
  it and rotates the key.
- **`delete_idea`** cascades to its runs; the worker finds the run gone, stops and
  cancels the A2A task (best effort).
- **MCP:** every tool call by an agent's service account during one of its running runs
  adds a `tool_called` event to that run (§3.4); `tools/list` gains `add_research_note`
  with its handler (§4).

## 3. Business rules

Tests first (lead's quality bar) for: §3.5 (each rule and c10/c22 for every column and
kind; agents can't request), §3.7 (excluded by default, the toggle's rules and blind
404), §3.3–3.4 (timeout, cancel, idempotency: one active run per idea + agent + kind +
section, under concurrent requests), §3.6 (SSE authorisation, re-checks, blind safety),
§3.2 (SSRF: only the built URL is ever requested; no redirects; card URLs ignored).
§3.13 lists the minimum cases.

### 3.1 Agents, their service accounts and keys

- **Registering** (`register_ai_agent`, one transaction): validates the body (labels,
  purposes, 1–50 distinct project ids), refuses the break-glass account (c20, 403
  `break_glass_account`: it would create a key), a namespace outside
  `SOUNDINGS_AI_AGENT_NAMESPACES` when that is set (422 `namespace_not_allowed`), an
  unknown project (422 `invalid_project`), a taken `(namespace, name)` (409
  `agent_taken`), a 51st agent (409 `too_many_agents`). Then it creates:
  - the **service account**: a `users` row with `is_service_account = true`,
    `display_name` = the agent's, `email` = `service_account_email(agent_id)`
    (`agent-<id>@soundings.invalid`: never mailed, never matched by SSO);
  - its **direct `member` role** in each project (`project_members`; audited
    `project.member_add` with `rule: platform.manage_agents`); a project where it
    already has a role keeps it;
  - its **one API key**: name `agent_key_name(namespace, name)`, scopes
    `agent_key_scopes(purposes)` (`read` + `mcp`, `evaluate` for `evaluate`, `write`
    for `research` or `draft_section`), `project_ids` = the agent's projects, no expiry,
    `created_by_id` = the admin, `created_auth_method` = the admin's session method
    (Phase 5 §3.7); audited `api_key.create` (rule `platform.manage_agents`);
  - the `ai_agents` and `ai_agent_projects` rows; audited `ai_agent.register` (details:
    `agent_id`, `namespace`, `name`, `protocol`, `purposes`, `project_ids`).

  The response carries the key **once** (`key.secret`) and `secret_manifest`
  (`agent_secret_manifest`): a Secret `soundings-agent-<name>` in the agent's namespace
  with `authorization: "Bearer sdg_…"`, which kagent's `RemoteMCPServer`
  `headersFrom` sends as is.
- **Agent keys follow the agent.** Unlike a person's key (immutable, Phase 5), an agent's
  active key is managed by the server: `update_ai_agent` changing `purposes` updates its
  `scopes`, changing `project_ids` updates its restriction and the memberships (adds a
  `member` role in new projects; removes the agent's **direct** role from dropped
  projects), in the same transaction, so the operator never re-deploys a Secret for
  that. Rotating (`rotate_ai_agent_key`) creates a new key and revokes the old one in
  one transaction (the agent fails until its Secret is updated: no overlap window).
  Revoking it in Admin settings → API keys leaves `key: null` until a rotation.
- **Disabling** (`enabled: false`): no new run (c10), every queued or running run gets a
  cancel request (by the admin) and ends `cancelled`, and its key is refused (401) until
  it is enabled again (same key). Agents are never deleted (their evaluations, notes,
  suggestions and runs keep their author).
- **Changing the display name** renames the service account too (what people see next
  to its work). Namespace and name never change (register another agent).
- **One agent per project where projects must not leak:** an agent serving several
  projects can be steered by text in one to read another (contract-phase5 §3.7); the
  admin page says so next to the projects field.
- **Settings in effect** (`AiSettingsInEffect`) are read-only (Helm values): enabled,
  the controller URL, whether a token is set (never the token), the default protocol,
  timeout, concurrency, allowed namespaces, the MCP URL agents are told.

### 3.2 Settings and URL building (SSRF)

| Setting (`SOUNDINGS_…`) | Default | Meaning |
|---|---|---|
| `AI_ENABLED` | `false` | The chart's `features.ai`. Off: c10 fails (409 `ai_unavailable`), queued runs fail `ai_disabled` when the worker reaches them, the idea page hides AI actions (`AiRunList.ai_enabled`); agents can still be registered. |
| `KAGENT_URL` | `http://kagent-controller.kagent:8083` | kagent's controller (A2A on 8083). An absolute http(s) **origin**: no path, query, fragment or credentials (refused at start-up); normalised to lower case without a trailing slash. The only host Soundings calls for AI. |
| `KAGENT_TOKEN` | unset | Optional bearer token for the controller (its `trusted-proxy` auth mode): `Authorization: Bearer <token>` on every A2A request; one token, no spaces. Never logged or returned (`kagent_token_set` only). API and worker. |
| `AI_DEFAULT_PROTOCOL` | `kagent_v0_10` | The protocol of a new agent when none is chosen. |
| `AI_RUN_TIMEOUT` | `PT5M` | How long a started run may take (30 s – 1 h; ISO 8601 or seconds), copied to `ai_runs.timeout_seconds` when requested. |
| `AI_MAX_CONCURRENT_RUNS` | `4` | Runs `running` at once across all workers (1–50); the rest wait `queued`, oldest first. |
| `AI_AGENT_NAMESPACES` | empty (any) | Comma-separated namespaces agents may be registered in. |
| `AI_MCP_URL` | the first base URL + `/mcp` | The MCP URL agents are told (the chart sets the Service URL). A hint in the message and the admin page; agents' real MCP endpoint is their `RemoteMCPServer`. |

- **The A2A URL** is `agent_a2a_url(kagent_url, protocol, namespace, name)`:
  `kagent_v0_10` → `{kagent_url}/api/a2a/{namespace}/{name}/` (trailing slash, as kagent
  advertises it); `kagent_v1_0` → `{kagent_url}/agents/{namespace}/{name}`. The card is
  `agent_card_url(…)` = that URL + `/.well-known/agent-card.json`. `namespace` and
  `name` must match `KUBERNETES_LABEL_PATTERN` (`^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$`),
  checked by the request model, the database and the builder: no `/`, `.`, `:`, `@`,
  `?`, `#`, `%` or upper case can reach the URL, so the host, port and path prefix are
  always the configured controller's.
- **The agent card never redirects transport.** Its `url`, `supportedInterfaces[].url`
  and `additionalInterfaces` are read for display only (`AiAgentCard` has no URL
  field); every request goes to the built URL. With a2a-sdk, construct the client from
  the fetched card **after replacing its URLs with the built one** (or use a hand-written
  JSON-RPC client); research R2 §2 shows `create_from_url` follows the card.
- **HTTP client rules** (API for the card test, worker for runs): `follow_redirects =
  False` (a 3xx is `agent_protocol_error`); TLS verified with the system bundle
  (`SSL_CERT_FILE`); no cookies; response bodies capped (card 64 KiB; a JSON-RPC response
  1 MiB; one SSE event 1 MiB) else `agent_protocol_error`; timeouts §3.4. Errors are
  logged with the run id, agent id, HTTP status and exception class, never bodies,
  headers or the token.
- **Test connection** (`test_ai_agent`) fetches the card (5 s, no redirects, ≤ 64 KiB,
  the token if set) and returns what it says (strings cut to 200 characters, at most 20
  skills) or `ok: false` with `agent_unreachable` / `agent_protocol_error` and
  Soundings' message. 10 per admin per minute.

### 3.3 Runs: lifecycle, statuses and A2A states

```
requested ──► queued ──► running ──► succeeded
                │           ├──────► failed      (error_code)
                │           ├──────► timed_out   (timed_out)
                │           └──────► cancelled   (cancel requested, or the agent's task canceled)
                ├──► cancelled (cancel while queued)
                ├──► timed_out (queue_timeout: 30 min without starting)
                └──► failed    (ai_disabled / agent_unavailable at start)
```

- **Requesting** (one transaction, under the idea lock `load_idea(for_update=True)`):
  the rule and its conditions (§3.5), c10 for that agent and kind, the per-person limit
  (20 requests an hour; 429 `too_many_attempts` with `Retry-After`), then
  **idempotency**: an active run (`queued`/`running`) for the same idea, agent, kind and
  section is returned with **200**, unchanged (and doesn't count towards the limit);
  else a new `queued` run (`timeout_seconds` from the setting), its first event
  `queued`, its `run_ai` job deferred on the same connection (visible at commit), audit
  `ai_run.request`, **201**. `uq_ai_runs_active` makes the check race-free: an
  `IntegrityError` on insert re-reads and returns the active run (200).
  `request_ai_evaluation` also assigns the agent's service account as an evaluator when
  it isn't one (audited `evaluator.add`, activity `evaluator_added`, actor the requester;
  no notification: service accounts are never notified).
- **Starting** (the job): at most `AI_MAX_CONCURRENT_RUNS` runs are `running`
  (counted in the database under a transaction-level advisory lock; a job that finds no
  slot re-defers itself 5 s later); oldest first. The worker re-checks AI enabled (else
  `failed` `ai_disabled`) and c10 for the agent (else `failed` `agent_unavailable`),
  sets `running`, `started_at`, `heartbeat_at`, event `started`, then talks A2A (§3.4).
  The idea's state conditions (c5/c6/c7) are **not** re-checked: the agent's MCP calls
  enforce them (a closed evaluation makes `submit_evaluation` fail, the run ends
  `no_result`).
- **While running:** every `AI_RUN_HEARTBEAT` (15 s) and between stream events the
  worker writes `heartbeat_at` and re-reads `cancel_requested_at`; past
  `started_at + timeout_seconds` it times out (§3.4).
- **Final:** `finished_at` set, the final event (`succeeded`, `failed`, `cancelled`,
  `timed_out`); `failed` and `timed_out` carry `error_code` + `error_message`
  (`AI_RUN_ERROR_MESSAGES`, optionally with `(HTTP 503)` or the A2A state name). A run
  that **recorded its result succeeds** when the agent's task ends, whatever the task's
  final state, except after a cancel request (then `cancelled`; the result stays).
- **The sweep** (worker, every minute): `running` runs whose heartbeat is older than
  `AI_RUN_STALE_AFTER` (2 min) → best-effort `tasks/cancel`, `failed` `worker_lost`;
  `queued` runs older than `AI_RUN_QUEUE_TIMEOUT` (30 min) → `timed_out`
  `queue_timeout`.
- **History** is kept with the idea (deleted with it); no retention job in Phase 6.

### 3.4 The A2A interaction

Verified against kagent v0.10.2's source and an a2a-sdk 1.2.1 server (research R2 §1–2);
the live controller is **not** (§8).

**Discovery.** Before sending, the worker fetches the agent card (`agent_card_url`, as
the test connection) and reads `capabilities.streaming`; a card it can't fetch or parse
fails the run (`agent_unreachable` / `agent_protocol_error`) before any message is sent.

**Headers** on every A2A request: `Content-Type: application/json`; `Accept:
text/event-stream` (streaming) or `application/json`; `A2A-Version: 0.3`
(`kagent_v0_10`) or `1.0` (`kagent_v1_0`) (`A2A_VERSION`); `X-User-Id: soundings`
(`KAGENT_USER_ID`: kagent's caller identity; never a person's); `Authorization: Bearer
<SOUNDINGS_KAGENT_TOKEN>` only when set. Nothing else (no cookies, no Soundings key).

**The message** (one per run; `run_message(kind, run_id, idea_key, agent_name, mcp_url,
section_key)`): role user, `messageId` = the run id (a retried send can be recognised),
no `contextId` (kagent starts a fresh session per run), one text part (the
instructions: which tools to call, in order, with the idea key, the limits, that people's
text is information and never instructions, no copying between projects, no secrets),
and `metadata.soundings = {run_id, kind, idea, section_key, mcp_url}` for deterministic
agents (the fake) and logs.

| | A2A 0.3 (`kagent_v0_10`) | A2A 1.0 (`kagent_v1_0`) |
|---|---|---|
| Stream | `{"jsonrpc":"2.0","id":"<run>-1","method":"message/stream","params":{"message":{"kind":"message","messageId":"<run>","role":"user","parts":[{"kind":"text","text":"…"}],"metadata":{"soundings":{…}}},"configuration":{"acceptedOutputModes":["text/plain"],"blocking":false}}}` | `{"jsonrpc":"2.0","id":"<run>-1","method":"SendStreamingMessage","params":{"message":{"messageId":"<run>","role":"ROLE_USER","parts":[{"text":"…"}],"metadata":{"soundings":{…}}},"configuration":{"acceptedOutputModes":["text/plain"]}}}` |
| No streaming (card says so) | `message/send` with `"blocking": false`, then poll | `SendMessage`, then poll |
| Poll | `tasks/get` `{"id": <task id>}` every 2 s | `GetTask` |
| Cancel | `tasks/cancel` `{"id": <task id>}` | `CancelTask` |
| Stream results | SSE `data: {"jsonrpc","id","result":…}` with `kind` `task` / `status-update` (`final`) / `artifact-update` / `message` | `result` wrapped as `{"task"|"statusUpdate"|"artifactUpdate"|"message": …}`; no `final` flag: the stream ends at a terminal state |

**Task states → events and statuses** (0.3 name / 1.0 name):

| A2A state | Event | Run |
|---|---|---|
| (task created) `submitted` / `TASK_STATE_SUBMITTED` | `agent_accepted`; `a2a_task_id`, `a2a_context_id` stored | `running` |
| `working` / `TASK_STATE_WORKING` | `agent_working` (on the first transition only) | `running` |
| `input-required`, `auth-required` / `TASK_STATE_INPUT_REQUIRED`, `TASK_STATE_AUTH_REQUIRED` | the worker sends cancel | `failed` `agent_needs_input` (or `succeeded` with a result) |
| `completed` / `TASK_STATE_COMPLETED` | — | `succeeded` if the result was recorded, else `failed` `no_result` |
| `failed` / `TASK_STATE_FAILED` | — | `failed` `agent_failed` (or `succeeded` with a result) |
| `canceled` / `TASK_STATE_CANCELED` | — | `cancelled` after our cancel request, else `failed` `agent_failed` (or `succeeded` with a result) |
| `rejected` / `TASK_STATE_REJECTED` | — | `failed` `agent_rejected` |
| anything else, a JSON-RPC error, malformed JSON | — | `failed` `agent_protocol_error` |
| a direct `message` reply (no task) | — | treated as `completed` |

Status messages' text and artifacts are **ignored** (logged by size only): results come
through MCP, and agent text never reaches progress events.

**Timeouts.** Connect 10 s; card 5 s; the stream may be silent for up to
`AI_RUN_STREAM_IDLE` (120 s), then the worker switches to polling `tasks/get` (the
message is never resent); a dropped stream with a task id also switches to polling. The
**deadline** is `started_at + timeout_seconds` (`asyncio.timeout` around everything):
then `tasks/cancel` (10 s, best effort: kagent's Python runtime answers
`TaskNotCancelable` -32002, which is fine) and `timed_out` `timed_out` (or `succeeded`
when the result is already recorded).

**Cancel.** `cancel_ai_run` on a queued run finishes it `cancelled` at once (event
`cancelled`); on a running one it sets `cancel_requested_at`/`_by_id` (event
`cancel_requested`); the worker sees it within about 2 seconds of the next stream event
or poll (at most the heartbeat), sends `tasks/cancel` (when there is a task id), stops
listening and finishes `cancelled`. After a cancel request no result is attached and
`add_research_note` is refused.

**Retries.** Only before a task exists: connection refused / DNS / reset and HTTP
502–504 are retried after 5 s and 15 s (`AI_RUN_CONNECT_RETRIES`, event `retrying`),
within the deadline; then `agent_unreachable`. HTTP 4xx (an unknown agent is 404) and
other 5xx fail at once (`agent_unreachable` with the status). Once a task id is known
nothing is resent. The procrastinate job itself is not retried (the run row is the
state); a crashed worker is the sweep's (`worker_lost`).

**Results are matched to the run by the server**, never by parsing agent text:

| Kind | The agent calls (as its service account) | Attached when | Run field |
|---|---|---|---|
| `evaluate` | `submit_evaluation` with `submit: true` (a draft doesn't count) | the agent has a `running`, not cancel-requested evaluate run on that idea | `evaluation_id`; event `result_recorded` "Evaluation submitted" |
| `research` | `add_research_note` (required: such a run, c22) | its `running` research run on that idea | `activity_event_id`; "Research note saved" (a second call replaces the note) |
| `draft_section` | `propose_proposal_section` for the run's section | its `running` draft run for that idea and section | `suggestion_id` (the latest); "Suggestion saved" |

In the same transaction as the write. Work the agent does outside a run (an evaluation
it submits later, a suggestion for another section) stays ordinary data, attached to
nothing. **`tool_called` events:** the MCP dispatcher, for a call by an agent's service
account, adds `AI_TOOL_MESSAGES[tool]` (with `: <code>` when the call failed) to the
agent's running run on the tool's idea, or, for tools without an idea, to its only
running run; in a separate short transaction (like the audit entry); never arguments or
results; at most `AI_RUN_EVENTS_MAX` (200) events per run (later `tool_called` /
`agent_working` events are dropped, the final event is always written).

### 3.5 Authorisation (role matrix section J)

| Rule | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own |
|---|---|---|---|---|---|---|---|---|
| `ai.request_evaluation` | Y (c6, c10) | Y (c6, c10) | 403 | 403 | 403 | 404 | 401 | + (c6, c10) |
| `ai.research` | Y (c5, c10) | Y (c5, c10) | 403 | 403 | 403 | 404 | 401 | + (c5, c10) |
| `ai.draft_section` | Y (c7, c10) | Y (c7, c10) | 403 | 403 | 403 | 404 | 401 | + (c7, c10) |
| `ai.cancel_run` | Y | Y | 403 | 403 | 403 | 404 | 401 | + |
| `evaluation.include_ai` | Y | Y | 403 | 403 | 403 | 404 | 401 | + |

- **c10, exactly** (409 `ai_unavailable`): `SOUNDINGS_AI_ENABLED` is on **and** the named
  agent exists, is `enabled`, has the kind among its `purposes`, serves the idea's
  project (`ai_agent_projects`), its service account is active with effective role
  **member** there (a viewer can't evaluate, comment or suggest), and it has an active
  key (not revoked or expired). An unknown `agent_id` is the same 409 (the body is
  about the run, not a resource you may not know). `AiRunList.agents` lists exactly the
  agents that pass c10 for some kind on this idea; the flags in `permissions` are the
  rule (with c5/c6/c7, archived, held) **and** c10 for an agent with that purpose.
- **Who:** the idea's owner (while member or admin) and project/platform admins.
  Members, viewers and internal non-members get 403; private non-members 404. Service
  accounts never own and are never admins, so **agents can't start runs**.
- **Holds and archive:** the request rules are idea writes: 409 `project_archived`, and
  for an idea held for moderation 409 `awaiting_moderation` (c19); `ai.cancel_run` works
  in archived projects (it only stops work). Held for confirmation: 404.
- **`evaluation.include_ai`** also needs the evaluation to be visible to you under
  section 3 (a pending evaluator, admin or owner, gets 404: the response holds scores),
  submitted (a draft is 404), on this idea, and an AI evaluation (409
  `not_ai_evaluation`).
- **c22** (new; MCP `add_research_note`): the principal is an AI agent's service account
  (people: `forbidden`) whose agent has a `running`, not cancel-requested research run
  on the idea (else `ai_run_not_active`).
- **Keys:** as in §2; a key restricted away from the project gets 404 as everywhere.

### 3.6 Live progress: SSE

`GET /ideas/{idea}/ai-runs/{run_id}/events` (one endpoint per run), `idea.view`.

- **Before the stream:** 401 / 404 (unknown run, another idea's, hidden idea) / 429 (more
  than `AI_SSE_STREAMS_PER_USER` (5) open streams per person per API process) as
  problem+json; 422 for a malformed `after` or `Last-Event-ID` (EventSource only sends
  back the ids the stream set).
- **The stream** (`200 text/event-stream; charset=utf-8`, `Cache-Control: no-cache`,
  `X-Accel-Buffering: no`, never compressed): first `retry: 3000`; then every event with
  `seq` > `Last-Event-ID` (or `?after=`; the header wins; neither = from the start) as

  ```
  id: 7
  data: {"seq":7,"type":"tool_called","message":"Read the idea","created_at":"2026-10-06T09:14:03.120Z","final":false}

  ```

  (no `event:` field, so `EventSource.onmessage` gets them all); then new events as
  they are written (the API checks the table at least once a second; Postgres
  `LISTEN/NOTIFY` may wake it sooner); `: keep-alive` comments every 15 s. After the
  event with `final: true` the server closes the stream; the client closes its
  EventSource and refetches the run (`get_ai_run`). A reconnect after the final event
  with nothing new gets **204** (EventSource stops reconnecting). The server also ends a
  stream after 10 minutes (the browser reconnects with `Last-Event-ID`).
- **Re-checks:** every 30 s the stream re-reads the principal (session still valid, or
  the key) and `idea.view`; if either fails it ends without a final event, and the
  reconnect gets the 401 / 404. A stream doesn't keep a session alive (like the bell).
- **Blind safety:** events are `AiRunEvent` only: Soundings' fixed sentences
  (`AI_RUN_EVENT_MESSAGES`), tool names (`AI_TOOL_MESSAGES`), error sentences
  (`AI_RUN_ERROR_MESSAGES`); never agent text, scores, recommendations, rationale,
  sources or comments. A pending human evaluator watching an AI evaluation run learns
  only what the feed already says ("submitted an evaluation").
- **Fallback:** where EventSource fails (proxy, error event), the SPA polls
  `get_ai_run` every 2–3 s while the run is active (`AiRunDetail.events`).
- **Through the ingress:** Traefik streams as is; nginx needs `X-Accel-Buffering: no`
  (sent) and a read timeout above 15 s (keep-alives).

### 3.7 AI evaluations: badge, rationale, sources, the aggregate

- **Left out by default:** the agent's first submission sets `include_in_aggregate =
  false` (Phase 5); `evaluation.include_ai` (`set_evaluation_inclusion`) includes it
  (it then counts like a person's: weights, `n`, per-criterion means, the disagreement
  flag) or leaves it out again; re-submissions keep the current choice. Visibility is
  unchanged by inclusion (role matrix §3 rules 4, 5 and 10).
- **AI badge** wherever its work appears: the evaluator row (`IdeaEvaluator.is_ai`), the
  evaluation (`Evaluation.is_ai`, with "Not in score" while excluded and, for
  `can_include_ai`, an "Include in score" switch), suggestions (`source: ai`), research
  notes (always AI), the run panel.
- **Rationale and sources:** an AI evaluator's per-criterion `comment` is its rationale
  (required, ≤ 1,000 characters; the SPA labels it "Rationale"); `sources` (≤ 5 per
  criterion, `Citation {title, url, host}`) are shown under it as plain links (§1). The
  overall `comment` is its summary. Sources reach REST at integration (§5).
- **Evaluator progress and "all evaluations are in"** count the AI evaluator like any
  assigned evaluator (it is in the list); remove it to stop waiting for it.
- **The agent is blind** until it submits (its `get_idea` shows `score_hidden`), and its
  evaluation is visible to others only per section 3, like a person's.

### 3.8 Research notes

- One per run (`add_research_note`; calling again replaces the text), stored as an
  `activity_events` row of type `ai_research_note` (actor: the service account; payload
  `{run_id, agent_id, body_md, sources: [{title, url}]}`); Markdown 1–20,000 characters;
  0–20 sources. In the feed at integration (`AiResearchNoteActivity {…, note:
  ResearchNote}`), and now through `get_research_note`.
- Rendered sanitised with an AI label ("Research note by Idea evaluator · AI"); sources
  as a numbered list of plain links. No notifications or emails (the requester watches
  the run; the note is in the feed). Not score data; the instructions forbid scores and
  go/no in notes (an agent could still write them: accepted, documented risk).
- **Deleting** (`comment.delete_any`: project and platform admins) clears the text and
  sources (`deleted: true`), keeps the item ("deleted a research note"); idempotent.

### 3.9 Section drafts

`request_ai_section_draft` needs a proposal (404 otherwise) and c7. The agent reads
`get_idea` and `get_proposal` and calls `propose_proposal_section` (Phase 5, `source:
ai`, replacing its earlier pending suggestion for the section); the owner accepts or
discards it in the editor as any suggestion. One active draft run per idea, agent and
section; drafts of different sections run side by side.

### 3.10 Audit

New `AuditAction` values, **agreed but not yet in the schema** (integration step §5;
`audit.record` refuses unknown actions until then, tests can patch `AUDIT_ACTIONS`):

| Action | Actor | Target | Details (never keys, prompts, agent text or URLs with tokens) |
|---|---|---|---|
| `ai_agent.register` | the admin | `user`: the service account | `rule: platform.manage_agents`, `agent_id`, `namespace`, `name`, `protocol`, `purposes`, `project_ids` |
| `ai_agent.update` | the admin | `user`: the service account | `rule`, `agent_id`, `changed` (field names), `enabled` when it changed |
| `ai_run.request` | the requester | `idea` | `rule` (`ai.request_evaluation` \| `ai.research` \| `ai.draft_section`), `run_id`, `agent_id`, `kind`, `section_key` (an idempotent 200 isn't audited again) |
| `ai_run.cancel` | the canceller (or the admin who disabled the agent) | `idea` | `rule: ai.cancel_run` (or `platform.manage_agents`), `run_id`, `agent_id`, `status` when cancelled |
| `evaluation.include_ai` | the owner or admin | `idea` | `rule`, `evaluation_id`, `evaluator_id`, `include` |

Existing actions cover the rest: `api_key.create` / `api_key.revoke` (rule
`platform.manage_agents`), `project.member_add` / `project.member_remove` for the agent's
memberships, `evaluator.add` when "Ask AI" assigns it, `evaluation.submit` and
`mcp.call` for the agent's calls. Run outcomes are the run rows themselves.

### 3.11 Helm values (platform; off by default)

Names are the contract with the environment variables; platform owns the chart.

| Value | Env | Default | Notes |
|---|---|---|---|
| `features.ai` | `SOUNDINGS_AI_ENABLED` | `false` | exists |
| `kagent.enabled` | — | `false` | exists: admits kagent's namespace to `/mcp` (NetworkPolicy); Phase 6: also the api and worker **egress** to `kagent.controllerUrl`'s port when `networkPolicy.egress.enabled` |
| `kagent.namespace` | — | `kagent` | exists |
| `kagent.controllerUrl` | `SOUNDINGS_KAGENT_URL` | `http://kagent-controller.<kagent.namespace>:8083` | new |
| `kagent.existingTokenSecret` / `.tokenSecretKey` | `SOUNDINGS_KAGENT_TOKEN` | `""` / `token` | new; api and worker |
| `kagent.agentNamespaces` | `SOUNDINGS_AI_AGENT_NAMESPACES` | `[]` | new |
| `ai.runTimeout` | `SOUNDINGS_AI_RUN_TIMEOUT` | `PT5M` | new |
| `ai.maxConcurrentRuns` | `SOUNDINGS_AI_MAX_CONCURRENT_RUNS` | `4` | new |
| `ai.defaultProtocol` | `SOUNDINGS_AI_DEFAULT_PROTOCOL` | `kagent_v0_10` | new |
| `ai.mcpUrl` | `SOUNDINGS_AI_MCP_URL` | the release's Service URL + `/mcp` | new; the chart sets it |
| `kagent.examples` | — | `false` | exists (the `RemoteMCPServer`); Phase 6 adds, under `kagent.examples` + `kagent.agents.*`, example `Agent` resources (kagent 0.10, `kagent.dev/v1alpha2`, `type: Declarative`): `soundings-evaluator` (tools `get_rubric`, `get_idea`, `submit_evaluation`) and `soundings-researcher` (`get_idea`, `get_proposal`, `add_research_note`, `propose_proposal_section`), each with `a2aConfig.skills`, `stream: true`, the system message from `run_message`'s rules, `kagent.agents.modelConfig` (an existing `ModelConfig`; required with the agents) and its own key (`kagent.agents.<agent>.keySecret`, the Secret registration returned) |

The chart never holds a key or token in values (existing Secrets only). Server-side dry
run (`kubectl apply --dry-run=server`) of the rendered examples against kagent
**v0.10.2**'s CRDs in k3s is the platform check; `values.schema.json` covers the new
values (`controllerUrl` an http(s) origin, the timeout an ISO 8601 duration or seconds).

### 3.12 The fake A2A agent (platform; dev, e2e, CI and k3s)

There is no kagent installation or LLM here, so the loop is exercised with a small,
**deterministic** agent (Python, a2a-sdk server) that speaks what kagent exposes and
really calls Soundings' `/mcp`:

- **Endpoints** (behind one base URL, which `SOUNDINGS_KAGENT_URL` points at): for every
  `(namespace, name)` it serves, `POST /api/a2a/{ns}/{name}/` (A2A 0.3 methods; missing
  or `A2A-Version: 0.3`) and `POST /agents/{ns}/{name}` (1.0 methods; requires
  `A2A-Version: 1.0`, else 400), each with its `/.well-known/agent-card.json` (a
  kagent-like card: name with `_`, `supportedInterfaces` for 0.3 and 1.0,
  `capabilities.streaming: true`, a skill per purpose). `message/stream`,
  `message/send`, `tasks/get`, `tasks/cancel` (and the 1.0 names); task states
  submitted → working → completed, with status updates.
- **Work:** reads `metadata.soundings` (`kind`, `idea`, `section_key`) and calls `/mcp`
  with the key for that agent from its environment (e.g. `FAKE_AGENT_KEYS` mapping
  `namespace/name` → `sdg_…`, or a mounted Secret per agent): `evaluate` → `get_rubric`,
  `get_idea`, `submit_evaluation` (every criterion: a score derived from the criterion's
  position, a rationale naming the criterion and the idea, two sources on
  `https://example.org/…`, a recommendation and summary); `research` → `get_idea`,
  `add_research_note` (a short Markdown note with three sources); `draft_section` →
  `get_idea`, `get_proposal`, `propose_proposal_section` for the section.
- **Behaviours by agent name suffix** (for tests): `-slow` keeps working (status updates
  every 2 s) until cancelled or the deadline; `-fails` ends `failed` after its first
  tool call; `-silent` completes without calling a tool (`no_result`); `-asks` goes
  `input-required`; `-rejects` ends `rejected`; `-blind-probe` calls `get_idea` and
  records whether `score_hidden` was true before it submits. Cancel works for every
  agent (the task ends `canceled`).
- It logs run ids and tool names only, never keys. It is **not kagent**: §8 says what it
  proves and what it doesn't.

### 3.13 Minimum tests (tests first)

- **Authorisation:** each run request, cancel, the toggle and note delete for every
  column (PA, PAd, Mem, Vwr, NMi, NMp, Pub) and the owner overlay (also demoted), each
  condition (c5, c6, c7, c10 for each of its parts: AI off, agent disabled, wrong
  purpose, project not served, service account a viewer or removed, key revoked,
  unknown agent; c19, archived, held for confirmation → 404); a service account's key
  requesting a run → 403; keys: `read` only → 403 `insufficient_scope` on requests;
  admin routes refuse keys and non-admins; c20 on register and rotate.
- **Idempotency:** two concurrent requests for the same idea, agent and kind → one run
  (201 and 200, same id); the same after it finished → a new run; different sections →
  two runs; the per-person limit (21st request in an hour → 429; a 200 doesn't count).
- **Exclusion:** an AI evaluation submitted through MCP is `include_in_aggregate: false`
  and the aggregate and `n` are unchanged; include → they change; exclude → back;
  re-submission keeps the choice; the toggle on a person's evaluation → 409; a pending
  evaluator (also an admin or the owner) → 404.
- **Timeout and cancel** (with the fake agent's `-slow`): the run ends `timed_out` at the
  deadline and the fake saw `tasks/cancel`; cancel while queued → `cancelled` without a
  message sent; cancel while running → `cancel_requested` then `cancelled`, the fake saw
  `tasks/cancel`; a result recorded before the deadline → `succeeded`; `-silent` →
  `no_result`; `-asks` → `agent_needs_input`; `-fails` → `agent_failed`; kagent down →
  retries then `agent_unreachable`; the sweep (`worker_lost`, `queue_timeout`);
  concurrency (`AI_MAX_CONCURRENT_RUNS=1`: the second run waits queued).
- **SSRF:** with a mock transport, the only URLs requested are the built card and A2A
  URLs (for both protocols); a card whose `url` / `supportedInterfaces` point elsewhere
  changes nothing; a 302 from the controller → `agent_protocol_error` without following;
  oversized card or response → `agent_protocol_error`; bad labels never reach the
  builder (422) or the database (check constraints).
- **SSE:** 401 without a session; 404 for a hidden idea, another idea's run, a private
  non-member; replay after `Last-Event-ID` and `?after=`; live events; the stream closes
  after the final event; 204 on reconnect after it; removing the watcher's access
  mid-stream ends it within 30 s; a pending human evaluator streaming an AI evaluation
  run receives no score, recommendation, rationale, source or comment text (the fake's
  rationale strings and URLs never appear in the stream or in `get_ai_run`).
- **Results:** each kind's result attached (and only to its run); work outside a run not
  attached; `add_research_note` refused for people (`forbidden`) and without a running
  research run (`ai_run_not_active`); a second note replaces the first; `tool_called`
  events with tool names only; the 200-event cap.
- **Agents:** registration creates the service account, memberships, key (scopes per
  purpose, restriction = projects) and shows the key once; updating purposes and
  projects updates the same key and memberships; disabling cancels runs and the key
  gets 401; rotation revokes the old key; the A2A URL in the response is the built one.

### 3.14 Acceptance (SPEC Phase 6): "Ask AI to evaluate" produces a badged, cited evaluation excluded from the aggregate by default

Against the real stack with the fake agent (`kagent_v0_10`; once more with
`kagent_v1_0`):

1. A platform admin registers "Idea evaluator" (`soundings/idea-evaluator`, purposes
   evaluate and research) for Customer Innovation; the key is shown once; the operator
   (the test) gives it to the fake agent. Test connection is ok.
2. CUST-12 has two submitted human evaluations; note its aggregate and `n`. A third
   evaluator (a pending person) opens the idea and the run's event stream.
3. The owner clicks "Ask AI to evaluate": 201, the evaluator list shows "Idea evaluator ·
   AI · Invited"; a second click returns the same run (200).
4. The stream shows queued → started → the agent started → Read the rubric → Read the
   idea → Saved its evaluation → Evaluation submitted → Done; the pending evaluator's
   stream holds no score data.
5. The run is `succeeded` with `result.evaluation_id`; the evaluator row says Submitted
   with the AI badge; the Evaluations tab (owner) shows the AI evaluation with a
   rationale and sources for every criterion and "Not in score"; the aggregate and `n`
   are unchanged; the pending evaluator still sees nothing (`score_hidden`).
6. The owner includes it: the aggregate and `n` change; excludes it: back.
7. "Research this" adds a research note with sources to the feed; "Draft section" on
   the Risks section of CUST-4's proposal adds an AI suggestion the owner accepts.

### 3.15 Screens (frontend)

- **Admin settings → AI agents:** the settings in effect (a banner when `features.ai` is
  off); agents with their kagent name, purposes, projects (with "removed" where the
  service account lost its role), key prefix and last use, enabled; "Register agent"
  (a sheet: display name, description, namespace, name, protocol, purposes, projects,
  the one-agent-per-project hint); the key reveal **once** with copy buttons for the key
  and the Secret manifest and the "you won't see it again" warning (Phase 5's pattern);
  Test connection (card name, versions, streaming, skills, or the error); Rotate key
  (confirm: "the agent stops until its Secret is updated"); Disable / Enable (confirm).
- **Idea page:** for the owner and admins, an "AI" menu in the primary actions with "Ask
  AI to evaluate" and "Research this" (one agent: direct; several: pick one), disabled
  with a reason when `permissions` say no; a calm run panel (who asked, the agent,
  live steps, elapsed time and the deadline, Cancel) that streams with SSE and falls
  back to polling; recent runs collapsed with their outcome and error sentence.
- **Evaluators list and Evaluations tab:** the AI badge; the run's state on the AI
  evaluator's row while active; the AI evaluation card: "Rationale" per criterion, its
  sources as links with hosts, "Not in score" chip and the "Include in score" switch
  (`can_include_ai`), a line explaining the default.
- **Activity feed** (integration): research notes with the AI label, sanitised
  Markdown, numbered sources, "Delete" for admins.
- **Proposal editor:** "Draft with AI" per section (owner and admins, c7), progress in
  place, and the suggestion appearing with its AI badge (Phase 5's cards).
- Loading, empty and error states, keyboard, dark mode and 390 px as everywhere.

## 4. MCP additions

The models are in `app/schemas/mcp.py`; nothing here is in OpenAPI.

| Change | Contract |
|---|---|
| `submit_evaluation` scores | `McpScoreIn(MyScoreIn)` adds `sources: [CitationIn]` (0–5; `title` one line 1–200, `url` http(s) ≤ 2,048 without credentials, spaces or control characters). **Service accounts only:** a person's key sending any source → `validation_error` ("Only AI evaluators cite sources."). A service account's submission needs a comment (rationale) on every scored criterion → `evaluation_incomplete`. |
| `McpScoreEntry` | adds `sources: [McpCitation {title, url}]` (marked `UNTRUSTED`; empty for people) in `get_idea` and `submit_evaluation` results. |
| `add_research_note` (new, `ADD_RESEARCH_NOTE`) | Rule `comment.create` + c22, scope `write`; not read-only, idempotent. Input `AddResearchNoteInput {idea, body_md (1–20,000), sources (0–20)}` (unknown arguments refused); output `AddResearchNoteOutput {idea, note_id, replaced}`. Errors: `forbidden` (a person, or an agent without the member role), `ai_run_not_active` (no running research run on the idea for this agent, or it is being cancelled), `not_found`, `validation_error`, `project_archived`, `idea_closed`. Audited `mcp.call` like every tool. |
| Instructions | `MCP_INSTRUCTIONS`' evaluate bullet now mentions rationale and sources; `RESEARCH_NOTE_INSTRUCTION` is appended when the tool lands. |
| Catalogue | `MCP_TOOLS` stays nine until backend adds the handler (`app.mcp.tools.TOOLS`) and appends `ADD_RESEARCH_NOTE` to `MCP_TOOLS` (a lead-approved one-line change in `app/schemas/mcp.py`) in the same change, updating `tests/mcp` and `tests/test_schemas_phase5.py`'s `SPEC_TOOLS` (ten). |
| Run events | Each call by an agent's service account during a running run adds a `tool_called` event (§3.4). |

## 5. Integration step (agreed, lands with the SPA)

One change, by backend with frontend, recorded in §10:

1. `ActivityItem` gains `AiResearchNoteActivity` (`type: "ai_research_note"`, `note:
   ResearchNote`); `ACTIVITY_TYPES` and the payload keys gain it; the SPA's
   `describeActivity` says "wrote a research note" / "deleted a research note".
2. `EvaluationScore` gains `sources: list[Citation]` (empty for people).
3. `AuditAction` gains `ai_agent.register`, `ai_agent.update`, `ai_run.request`,
   `ai_run.cancel`, `evaluation.include_ai` (with the SPA's phrases, an "AI" category and
   mock entries; `audit-phrases.test.ts`'s exhaustive `Record`).
4. `MCP_TOOLS` gains `add_research_note` (§4), with its handler.

## 6. Error codes

New in Phase 6:

| Status | `code` | When |
|---|---|---|
| 409 | `ai_unavailable` | c10 (§3.5): AI off, or the agent isn't usable for this idea and kind |
| 409 | `agent_taken` | registering a namespace and name already registered |
| 409 | `too_many_agents` | a 51st agent |
| 409 | `ai_run_finished` | cancelling a run that already ended |
| 409 | `not_ai_evaluation` | the include toggle on a person's evaluation |
| 422 | `namespace_not_allowed` | a namespace outside `SOUNDINGS_AI_AGENT_NAMESPACES` |
| 422 | `invalid_project` | also: registering or updating an agent with an unknown project |
| 403 | `break_glass_account` | also: registering an agent or rotating its key (c20) |
| 429 | `too_many_attempts` | also: 20 run requests per person per hour; 10 tests per admin per minute; 5 open event streams per person |
| MCP | `ai_run_not_active` | `add_research_note` without a running research run (c22) |
| MCP | `forbidden` | also: `add_research_note` by a person |

Run outcomes are not HTTP errors: `AiRunError` values in `AiRun.error.code` (§3.3).

## 7. Decisions

Simpler option chosen each time; the lead may revisit (also in
[decisions.md](../decisions.md) and [ADR 0014](../adr/0014-kagent-a2a-integration.md)).

| Decision | Why |
|---|---|
| The A2A URL is built from one configured controller origin, a fixed path per protocol and two DNS labels; no URL field anywhere; card URLs ignored; no redirects. | SSRF can't be configured in: the only reachable host is the operator's controller. |
| One `protocol` per agent: `kagent_v0_10` (A2A 0.3 at `/api/a2a/{ns}/{name}/`) or `kagent_v1_0` (A2A 1.0 at `/agents/{ns}/{name}`), default from settings. | kagent's stable line and its 1.0 rewrite differ in both path and protocol; one choice per agent covers a mixed or migrating cluster without negotiation logic. |
| Results come back through MCP tools as the agent's service account and are attached to the run by the server; A2A text and artifacts are ignored. | kagent 0.10 has no output schema; authorisation, blind evaluation, limits and audit then apply to agents exactly as to people; no parsing of model output. |
| Rationale = the per-criterion comment (required for agents); sources a JSONB column on `evaluation_scores` (≤ 5). | One evaluation shape for people and agents; no sibling table; the existing evaluate UI shows it. |
| Research notes are `activity_events` rows (`ai_research_note`, payload body + sources), one per run, deletable by admins; a dedicated MCP tool that needs a running research run. | No new table; the feed is where SPEC puts them; a note can't be planted outside a requested run. |
| One agent row = one service account = one key; scopes from purposes; restriction = its projects; the server keeps the key's scopes and restriction in step with the agent. | Least privilege per purpose; adding a project never requires re-deploying a Secret; immutability stays the rule for people's keys. |
| Agents join projects as members through Admin settings → AI agents; project admins may remove them; pickers never list agents. | A platform admin decides an agent's reach (prompt-injection blast radius); project admins keep a veto. |
| Disabling an agent cancels its runs and refuses its key until re-enabled. | One switch stops an agent completely without losing its key or history. |
| Runs are rows with events; the worker runs them with a database-counted concurrency limit, a heartbeat and a sweep; no job retries. | Durable, observable, restart-safe; no state in a process; nothing is sent twice. |
| One active run per idea + agent + kind (+ section), enforced by a partial unique index; a repeated request returns the active run (200). | Double clicks and races are harmless; the button is idempotent. |
| Progress over SSE from the API, read from `ai_run_events`; polling `get_ai_run` as the fallback; events are fixed sentences and tool names. | Works through any replica and the ingress; blind-safe by construction; no agent text in the UI. |
| Excluded from the aggregate by default; the owner and admins include per evaluation. | SPEC section 9. |
| Constants for limits (20 runs/hour/person, 50 agents, 200 events, 5 streams, timings); settings only for what operators must choose. | Simple beats configurable. |
| No new notification types in Phase 6. | The requester watches the run; results land in the feed, the evaluators list and the editor; existing notifications (evaluation submitted, all in) still fire. |

## 8. Verified vs assumed (kagent)

| | Status | Source |
|---|---|---|
| kagent v0.10.2 CRDs (`agents.kagent.dev` v1alpha2 storage, `remotemcpservers.kagent.dev`, `modelconfigs.kagent.dev`), the minimal `Agent` / `RemoteMCPServer` / `ModelConfig` manifests, `headersFrom.valueFrom {type, name, key}` | **verified** (applied to k3s; server-side dry run) | research R2 §1, Phase 5 |
| kagent's MCP client (go-sdk v1.6.1) against `/mcp` | **verified** (the library kagent pins) | Phase 5 |
| A2A endpoint layout `/api/a2a/{ns}/{name}/` on the controller (port 8083), card at `.well-known/agent-card.json`, `A2A-Version` selecting 0.3 or 1.0 method names (other values 400), `X-User-Id`, `contextId` = session | from **source** (v0.10.2), not a live controller | research R2 §1 |
| A2A 0.3 and 1.0 wire shapes, streaming order, `final` (0.3 only), cancel, error codes −32001/−32002/−32004 | **verified** against an a2a-sdk 1.2.1 server with a kagent-identical card; kagent's a2a-go v2.3.1 checked in source | research R2 §1–2 |
| The fake agent end to end through Soundings (message, stream, MCP calls, results, cancel, timeout) | to be **verified** this phase (platform, qa) | §3.12 |
| The controller proxying to agent pods, `tasks/get` from kagent's database, streaming through the controller, its behaviour on a duplicate `messageId` | **assumed** (source reading only) | — |
| kagent 1.0: path `/agents/{ns}/{name}`, card under it, `A2A-Version: 1.0` required | **assumed** from the pre-release's main branch (alpha5); re-check when 1.0 ships | research R2 §1 |
| The Python runtime can't cancel (`NotImplementedError`; the Go runtime can) | from source; handled (cancel is best effort) | research R2 §1 |
| An `Agent`'s tool-level `headersFrom` overriding the server's header (one `RemoteMCPServer`, a key per agent) | **assumed** from a source comment; the examples default to one `RemoteMCPServer` per agent key until a dry run (and ideally a live controller) proves it | research R2 §1 |
| An LLM following `run_message`'s instructions (calling the tools in order, citing sources, no scores in notes) | **assumed**; no LLM here. The server enforces everything that matters (rules, blind evaluation, limits, c22, result matching) regardless | — |
| Optional, if the platform agent can: kagent's 0.10.2 chart from `oci://ghcr.io/kagent-dev/kagent/helm/kagent` in k3s with the fake agent as a `type: BYO` Agent (check `kubectl explain agents.spec.byo`), so the real controller's A2A proxy carries a run | **open** | — |

## 9. Room for later phases

- Notifications when a run finishes; a run history page per agent; retention for old
  runs and events.
- A "focus" question for "Research this"; follow-up messages in the same A2A context;
  push notifications instead of streaming.
- Key rotation with an overlap window; per-agent rate limits; a cost budget per agent.
- Re-checking an agent card's skills against its purposes at registration.

## 10. Changes after the contract

Builders record additive contract changes here (date, change, why), then run
`make gen-api`.

| Date | Change | Why |
|---|---|---|
