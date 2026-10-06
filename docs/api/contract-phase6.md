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
[contract-phase5.md](contract-phase5.md), whose conventions all still apply. Revised
after the adversarial contract review (§10): agents act only inside their runs (c22,
run scope), never see others' score data (role matrix §3 rule 9), and AI runs have a
worker queue of their own.

Source of truth, in order: the Pydantic schemas in `backend/app/schemas/ai.py` (agents,
runs, events, citations, research notes, the A2A message `run_message`, the URL builder
`agent_a2a_url`, the fixed event and error messages), the MCP additions in
`backend/app/schemas/mcp.py` (`McpScoreIn.sources`, `McpScoreEntry.sources`,
`ADD_RESEARCH_NOTE`, the run-scope note in `MCP_INSTRUCTIONS`), `AiResearchNoteActivity`
in `activity.py`, the route stubs in
`backend/app/api/v1/admin_ai_agents.py` and `ai_runs.py`, the models
(`app/models/ai.py`: `AiAgent`, `AiAgentProject`, `AiRun`, `AiRunEvent`;
`EvaluationScore.sources`; the enums `AiRunKind`, `AiRunStatus`, `AiAgentProtocol`,
`AiRunEventType`, `AiRunError`) with migration `0011` (and its downgrade), the settings in
`app/config.py` (`ai_*`, `kagent_*`), exported to `frontend/src/api/generated/`
(`make gen-api`). Rules are named as in [role-matrix.md](../role-matrix.md) (section J
is this phase's authorisation spec; new condition c22); tables in [erd.md](../erd.md);
the design in [ADR 0014](../adr/0014-kagent-a2a-integration.md); what is known about
kagent in [research R2](../research/kagent-a2a-claude-code-frontend.md) and §8 below.

`backend/tests/test_contract_routes.py` pins every method, path and `operation_id` and
keeps a valid request per unimplemented route (`STUBS`, answered 501): delete a row when
you implement it. `tests/authz/test_route_rules.py` names each operation's rules;
`app/authz/keys.py` classifies each for API keys; `tests/test_schemas_phase6.py` pins the
URL builder, the run message, key scopes, the run scope's tools (`AGENT_RUN_WRITE_TOOLS`,
`AGENT_READ_TOOLS`), the fixed event and error messages, citations, permission reasons,
the MCP additions and blind safety by construction; `tests/test_config_ai.py` the
settings; `tests/test_domain_schema_phase6.py` the constraints and the downgrade of 0011.

**Who builds what (suggested):** backend: the agent registry and its service account,
memberships and key (§3.1, with identity's key service), the run service and the
procrastinate job (`run_ai` on the `ai` queue with its own worker pool, §3.3–3.4) with
an A2A client, the SSE endpoint (§3.6), result matching in `save_my_evaluation`,
`create_proposal_suggestion` and the new MCP tool `add_research_note` (§4), **c22 in the
MCP tools** (the run scope: targets, list filtering, the one write tool), **rule 9's
masks** for service accounts in `get_idea`, `search_ideas` and the queries, the include
toggle and research notes (§3.7–3.8), the `tool_called` events from the MCP dispatcher,
the sweep (stale and queued runs), shutdown handling, audit calls at integration (§5);
identity: agents' keys refused on REST (403 `insufficient_scope`), c22 in the policy
(a service-account principal is confined to its open runs), agent keys exempt from
immutability (scopes and restriction follow the agent, §3.1), the session-only gate for
the admin routes (already classified), guard tests; frontend: Admin settings → AI
agents, the idea page's AI actions (disabled with `AiBlockedReason`) and run panel (SSE
with polling fallback), AI badges, the Evaluations tab's AI card (rationale, sources
"Cited by AI, not checked", "Not in score" and the toggle), research notes in the feed
(integration; http/https links only), "Draft with AI" in the proposal editor, MSW mocks
for the 16 new operations; platform: the **fake A2A agent** (§3.12; its own image and dev
process; its MCP URL from its own configuration), the optional Helm templates and values
(§3.11: NetworkPolicy ingress from agent pods, `agentNamespaces` defaulting to the
release namespace), the worker's (and API's) egress to kagent, kagent's v0.10.2 CRDs in
k3s for server-side dry runs of the example manifests, `make ai-smoke`; qa: §3.13 and the
acceptance §3.14 as API and e2e tests against the fake agent.

## 1. Conventions (new in Phase 6)

| Topic | Rule |
|---|---|
| Additive only | New endpoints, schemas, tables and enums only. Three things the SPA maps exhaustively land in **one integration step** with the SPA (§5), as in Phases 4 and 5: the `ai_research_note` activity item, `EvaluationScore.sources`, and five `AuditAction` values. They are agreed and modelled now (`AiResearchNoteActivity`, `Citation`, §5), not yet wired. The MCP tool `add_research_note` is defined (`ADD_RESEARCH_NOTE`) and joins `MCP_TOOLS` with its handler. Permission flags the SPA needs come with the new lists (`AiRunList.permissions`), not as new fields on old models. |
| URLs are built, never given | No request field, setting other than `SOUNDINGS_KAGENT_URL`, database column or agent card decides where Soundings sends A2A requests: `agent_a2a_url(kagent_url, protocol, namespace, name)` with DNS-1123 labels (§3.2). No redirects are followed. |
| AI text is untrusted | Everything an agent writes (evaluation comments and rationale, sources, research notes, suggestions, the agent card) is data: rendered as sanitised Markdown (the app's `Markdown`: raw HTML dropped; for agent text **http/https links only**, no `mailto:`) with an **AI** label; links `rel="noopener noreferrer nofollow"`, new tab, with the host shown (ASCII: punycode for international names). Sources are labelled "Cited by AI, not checked". Agent text is never shown in progress, errors, emails or audit. |
| Agents act only inside a run | **c22, run scope** (§3.5): an agent's key works on `/mcp` only (REST: 403 `insufficient_scope`), on the idea of one of its `running` runs that nobody asked to cancel, and writes only through that run kind's tool. Outside a run the key does nothing: cancel, timeout and `worker_lost` are final. |
| No secrets in prompts | The A2A message holds references and instructions only (`run_message`): run id, kind, idea key, section, the agent's display name. Never a key, token, URL, idea text or personal data. The agent's MCP key lives only in the operator's Kubernetes Secret (or the fake agent's environment); Soundings shows it once. The agent reaches Soundings only through the MCP server its operator configured, never a URL from a message. |
| Blind safety | Runs, events, run lists and permissions hold **no score data** (by construction: `tests/test_schemas_phase6.py`); everyone who may view the idea may watch, pending evaluators included (role matrix §3 rule 1). **Agents never see other evaluators' score data, before or after submitting** (rule 9), so nothing an agent writes (a note, a suggestion, a rationale) can carry it to a pending evaluator, and people's evaluation comments never reach an LLM provider. |
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
| `PATCH /admin/ai-agents/{agent_id}` | `update_ai_agent` | `AiAgentUpdate {display_name?, description?, protocol?, purposes?, project_ids?, enabled?}` (at least one; no nulls) → `AiAgent`; audited `ai_agent.update` (+ `ai_run.cancel` for runs it cancels, `api_key.revoke` when disabling) | 403; 404; 422 `invalid_project` |
| `POST /admin/ai-agents/{agent_id}/key` | `rotate_ai_agent_key` | no body → 201 `RotatedAiAgentKey {agent, key: CreatedApiKey, secret_manifest, revoked_key_id}`, `Cache-Control: no-store`; audited `api_key.create` + `api_key.revoke` (rule `platform.manage_agents`) | 403 (`break_glass_account`, c20); 404 |
| `POST /admin/ai-agents/{agent_id}/test` | `test_ai_agent` | no body → `AiAgentTest {ok, url, http_status, duration_ms, card, error_code, error_message}` (always 200; §3.2); not audited | 403; 404; 429 (10/min per admin) |

### AI runs, the include toggle and research notes (`tags: ai`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /ideas/{idea}/ai-runs?kind=&limit=` | `list_idea_ai_runs` | `idea.view` (flags from the AI rules, c10) | → `AiRunList {items: [AiRun] newest first (limit 1–50, 20), ai_enabled, agents: [AiAgentRef], permissions: AiPermissions}`; each request flag has a `*_blocked_by: AiBlockedReason \| null` (§3.15) | 404 |
| `POST /ideas/{idea}/ai-runs/evaluation` | `request_ai_evaluation` | `ai.request_evaluation` (c6, c10) | `AiRunRequest {agent_id}` → 201 `AiRun` (new) or **200** `AiRun` (the active one, §3.3); assigns the agent as evaluator if needed (`ai_runs.assigned_evaluator`; undone if the run ends without its submitted evaluation); audited `ai_run.request` | 403; 404; 409 `evaluation_closed`, `idea_closed`, `ai_unavailable`, `project_archived`, `awaiting_moderation`; 429 |
| `POST /ideas/{idea}/ai-runs/research` | `request_ai_research` | `ai.research` (c5, c10) | `AiRunRequest` → 201 / 200 `AiRun` | 403; 404; 409 `idea_closed`, `ai_unavailable`, …; 429 |
| `POST /ideas/{idea}/ai-runs/section-draft` | `request_ai_section_draft` | `ai.draft_section` (c7, c10) | `AiSectionDraftRequest {agent_id, section_key}` → 201 / 200 `AiRun` | 403; 404 (also: no proposal); 409 `proposal_not_available`, `ai_unavailable`, …; 429 |
| `GET /ideas/{idea}/ai-runs/{run_id}` | `get_ai_run` | `idea.view` | → `AiRunDetail` (the run + every event, oldest first): the polling fallback | 404 |
| `POST /ideas/{idea}/ai-runs/{run_id}/cancel` | `cancel_ai_run` | `ai.cancel_run` | no body → `AiRun` (`cancelled`, or `cancel_requested: true` while the worker stops it); idempotent while active; audited `ai_run.cancel` | 403; 404; 409 `ai_run_finished` |
| `GET /ideas/{idea}/ai-runs/{run_id}/events` | `stream_ai_run_events` | `idea.view` | `Last-Event-ID` header or `?after=` → `text/event-stream` of `AiRunEvent`, or 204 (§3.6) | 404; 429 (5 streams per person) |
| `PUT /ideas/{idea}/evaluations/{evaluation_id}/include-in-aggregate` | `set_evaluation_inclusion` | `evaluation.include_ai` (+ the evaluation visible: `evaluation.view_others`) | `EvaluationInclusionUpdate {include}` → `Evaluation`; idempotent; audited `evaluation.include_ai` (§3.7) | 403; 404 (a draft, another idea's, or any while you are a pending evaluator); 409 `not_ai_evaluation`, `project_archived`, `awaiting_moderation` |
| `GET /ideas/{idea}/research-notes/{note_id}` | `get_research_note` | `idea.view` | → `ResearchNote` (§3.8) | 404 |
| `DELETE /ideas/{idea}/research-notes/{note_id}` | `delete_research_note` | `ai.delete_note` (§10) | → 204; idempotent; clears the text and sources (the feed shows "deleted a research note") | 403; 404; 409 `project_archived` |

API keys: the admin routes are session only (403 `insufficient_scope`); the run requests,
cancel, the toggle and note delete need `write` (`ai.*`, `evaluation.include_ai`,
`comment.*` are `write` rules); the reads need `read`. **An agent's key gets 403
`insufficient_scope` on every REST route** (c22: MCP only), so it can't request runs,
watch them or read anything over REST (and `ai.*` need the owner or an admin, which a
service account never is: no recursion).

### Unchanged endpoints with new behaviour

- **Evaluations by an AI evaluator** (`save_my_evaluation` through MCP
  `submit_evaluation` with the agent's key, only during its open evaluate run on the
  idea, c22): each score may carry `sources` (§4); a submission needs a non-empty
  `comment` (its rationale) for every scored criterion (`evaluation_incomplete` naming
  them); the first submission is left out of the aggregate (Phase 5); **a re-submission
  that changes any score or the recommendation resets `include_in_aggregate` to false**
  (someone includes it again after reading it; one that changes only text keeps the
  choice); the submitted evaluation becomes the run's result (§3.4). REST
  `MyEvaluationIn` takes no sources (people never cite).
- **Suggestions by an agent** (`propose_proposal_section`, `source: ai`): only during its
  open draft run for that idea and section (c22); the suggestion becomes its result.
- **`list_evaluations` / `get_idea`**: unchanged until integration, when
  `EvaluationScore` gains `sources` (§5). `IdeaEvaluator.is_ai` and `Evaluation.is_ai` /
  `include_in_aggregate` already exist; the aggregate (`n`, means, disagreement)
  counts included evaluations only.
- **The key source and c22:** a key whose owner is a service account works on `/mcp`
  only (REST: 403 `insufficient_scope`, after the key check) and there only within c22
  (§3.5); agents' keys are never dormant (Phase 5). Disabling an agent **revokes** its
  key (401 like any revoked key; no special case in the key source).
- **Agents never see others' score data** (role matrix §3 rule 9): for a service account
  every idea is as for a pending evaluator (`score_hidden: true`, no aggregate, `n`,
  others' evaluations or their comments; sorted and filtered as unscored), before and
  after it submits; it sees its own evaluation (`my_evaluation`). `get_proposal` carries
  no score data already (contract-phase4).
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
- **MCP:** every call of a known tool by an agent's service account on the idea of one
  of its open runs adds a `tool_called` event to that run (§3.4); `tools/list` gains
  `add_research_note` with its handler (§4); `MCP_INSTRUCTIONS` say agents' keys work
  only during a run.

## 3. Business rules

Tests first (lead's quality bar) for: §3.5 (each rule and c10 for every column and kind;
c22 for every tool, REST refused to agents, nothing after cancel, timeout or
`worker_lost`; agents can't request; rule 9 for agents), §3.7 (excluded by default, the
toggle's rules, the reset on a changed re-submission, blind 404), §3.3–3.4 (timeout,
cancel, idempotency: one active run per idea + agent + kind + section, under concurrent
requests; compare-and-set transitions), §3.6 (SSE authorisation, re-checks, blind
safety), §3.2 (SSRF: only the built URL is ever requested; no redirects; no proxy).
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
  that. **Narrowing cancels:** a dropped purpose or project gives each of the agent's
  active runs of that kind, or on ideas in that project, a cancel request by the admin
  (as disabling does; audited `ai_run.cancel`, rule `platform.manage_agents`). The key's
  scopes and restriction are a second fence: c22 is what confines an agent. Rotating
  (`rotate_ai_agent_key`) creates a new key and revokes the old one in one transaction
  (the agent fails until its Secret is updated: no overlap window). Revoking it in Admin
  settings → API keys leaves `key: null` until a rotation.
- **Disabling** (`enabled: false`): no new run (c10), every queued or running run gets a
  cancel request (by the admin) and ends `cancelled`, and **its key is revoked** (audited
  `api_key.revoke`, rule `platform.manage_agents`). Enabling it again leaves `key: null`
  (c10 fails) until an admin rotates the key and the operator updates the Secret. Agents
  are never deleted (their evaluations, notes, suggestions and runs keep their author).
- **Changing the display name** renames the service account too (what people see next
  to its work). Namespace and name never change (register another agent).
- **Reach:** an agent serving several projects can't be steered by text in one idea into
  another: c22 confines every call to the idea of an open run, and rule 9 hides
  others' scores. What remains (documented in the admin guide): while a run on idea X is
  open, whoever can message the agent directly in kagent (its UI and A2A endpoint have no
  authentication by default, `--auth-mode=unsecure`) could make it read X or write its
  one result for X; and an agent with other tools (web fetch) could send out what it read
  of X. Keep kagent's endpoints inside the cluster and give researchers only the tools
  they need.
- **Settings in effect** (`AiSettingsInEffect`) are read-only (Helm values): enabled,
  the controller URL, whether a token is set (never the token), the default protocol,
  timeout, concurrency per worker process, allowed namespaces, the MCP URL to configure
  in the agent's `RemoteMCPServer` (shown to admins, never sent to agents).

### 3.2 Settings and URL building (SSRF)

| Setting (`SOUNDINGS_…`) | Default | Meaning |
|---|---|---|
| `AI_ENABLED` | `false` | The chart's `features.ai`. Off: c10 fails (409 `ai_unavailable`), queued runs fail `ai_disabled` when the worker reaches them, the idea page hides AI actions (`AiRunList.ai_enabled`); agents can still be registered. |
| `KAGENT_URL` | `http://kagent-controller.kagent:8083` | kagent's controller (A2A on 8083). An absolute http(s) **origin**: no path, query, fragment or credentials (refused at start-up); normalised to lower case without a trailing slash. The only host Soundings calls for AI. |
| `KAGENT_TOKEN` | unset | Optional bearer token for the controller (its `trusted-proxy` auth mode): `Authorization: Bearer <token>` on every A2A request; one token, no spaces. Never logged or returned (`kagent_token_set` only). API and worker. |
| `AI_DEFAULT_PROTOCOL` | `kagent_v0_10` | The protocol of a new agent when none is chosen. |
| `AI_RUN_TIMEOUT` | `PT5M` | How long a started run may take (30 s – 1 h; ISO 8601 or seconds), copied to `ai_runs.timeout_seconds` when requested. |
| `AI_MAX_CONCURRENT_RUNS` | `4` | Runs talking to agents at once **per worker process** (1–50): the size of the worker's own pool for the `ai` queue (`AI_RUN_QUEUE`), separate from `WORKER_CONCURRENCY` (email, notifications, schedules), so AI runs never hold those up; the rest wait `queued`, first in, first out. With N worker replicas, N × this. |
| `AI_AGENT_NAMESPACES` | empty (any) | Comma-separated namespaces agents may be registered in. The chart sets the release namespace unless `kagent.agentNamespaces` lists others (§3.11). |
| `AI_MCP_URL` | the first base URL + `/mcp` | The URL to put in an agent's `RemoteMCPServer` (the chart sets the Service URL), shown in Admin settings → AI agents. **Never sent to agents** (not in the message): an agent uses only the MCP server its operator configured. |

- **The A2A URL** is `agent_a2a_url(kagent_url, protocol, namespace, name)`:
  `kagent_v0_10` → `{kagent_url}/api/a2a/{namespace}/{name}/` (trailing slash, as kagent
  advertises it); `kagent_v1_0` → `{kagent_url}/agents/{namespace}/{name}`. The card is
  `agent_card_url(…)` = that URL + `/.well-known/agent-card.json`. `namespace` and
  `name` must match `KUBERNETES_LABEL_PATTERN` (`^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$`),
  checked by the request model, the database and the builder: no `/`, `.`, `:`, `@`,
  `?`, `#`, `%` or upper case can reach the URL, so the host, port and path prefix are
  always the configured controller's.
- **The agent card never redirects transport.** Runs don't read the card at all; the
  test connection reads its `url`, `supportedInterfaces[].url` and
  `additionalInterfaces` for display only (`AiAgentCard` has no URL field); every
  request goes to the built URL. Use a hand-written JSON-RPC client (or a2a-sdk's
  transport constructed **with the built URL**, never from the card); research R2 §2
  shows `create_from_url` follows the card.
- **HTTP client rules** (API for the card test, worker for runs): one `httpx` client with
  `follow_redirects=False` (a 3xx is `agent_protocol_error`), **`trust_env=False`** (no
  `HTTP(S)_PROXY`, `NO_PROXY` or `.netrc` from the environment: the controller token
  never goes through a proxy) and an explicit `ssl.create_default_context(cafile=…)`
  from `SSL_CERT_FILE` when set (else the system bundle); no cookies; response bodies
  capped (card 64 KiB; a JSON-RPC response 1 MiB; one SSE event 1 MiB) else
  `agent_protocol_error`; timeouts §3.4. Errors are logged with the run id, agent id,
  HTTP status and exception class, never bodies, headers or the token.
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
  except a run still `queued` past `AI_RUN_QUEUE_TIMEOUT`, which this request finishes
  `timed_out` `queue_timeout` (so a run never stays queued without a worker) before
  creating a new one; else a new `queued` run (`timeout_seconds` from the setting), its
  first event `queued`, its `run_ai` job deferred on the `ai` queue on the same
  connection (visible at commit), audit `ai_run.request`, **201**. `uq_ai_runs_active`
  makes the check race-free: an `IntegrityError` on insert re-reads and returns the
  active run (200). `request_ai_evaluation` also assigns the agent's service account as
  an evaluator when it isn't one (audited `evaluator.add`, activity `evaluator_added`,
  actor the requester; no notification: service accounts are never notified) and then
  sets the run's `assigned_evaluator`.
- **Transitions are compare-and-set**, each one statement `UPDATE ai_runs SET … WHERE id
  = :id AND status IN (…) [AND …] RETURNING …`; no row means someone else got there first
  (the caller re-reads and acts on what it finds):
  - *start* (the job): `queued` → `running` `WHERE status = 'queued'`, setting
    `started_at`, `heartbeat_at`; a duplicate job, or a run cancelled or timed out
    meanwhile, gets no row and exits;
  - *cancel* (the API): first `queued` → `cancelled` (with `finished_at`); if no row,
    `SET cancel_requested_at = coalesce(cancel_requested_at, now()),
    cancel_requested_by_id = coalesce(…) WHERE status = 'running'`; if still no row the
    run is final: 409 `ai_run_finished`;
  - *finish* (the worker and the sweep): `WHERE status = 'running'`, the final status
    computed **in the same statement** from `cancel_requested_at` and the result
    columns (a cancel request that lands while the agent's task completes can't be
    lost or overwritten);
  - *attach a result* (the agent's MCP write, in the tool's transaction, after it locked
    the project and the idea): `SET evaluation_id = … WHERE agent_id = … AND idea_id = …
    AND kind = … [AND section_key = …] AND status = 'running' AND cancel_requested_at IS
    NULL`.

  **Lock order** for anything that touches both: project (`FOR KEY SHARE`) → idea
  (`FOR UPDATE`) → run, as every idea write (CLAUDE.md "Locking"). Heartbeats and events
  lock only the run row, in their own short transactions; nobody takes the run row before
  the idea.
- **Starting** (the job, from the `ai` queue: its own pool of `AI_MAX_CONCURRENT_RUNS` per
  worker process, so no further concurrency count; first in, first out): the worker
  re-checks AI enabled (else `failed` `ai_disabled`) and c10 for the agent (else
  `failed` `agent_unavailable`), then *start* (above) and event `started`, then talks
  A2A (§3.4). The idea's state conditions (c5/c6/c7) are **not** re-checked: the agent's
  MCP calls enforce them (a closed evaluation makes `submit_evaluation` fail, the run
  ends `no_result`).
- **While running:** every `AI_RUN_HEARTBEAT` (15 s) and between stream events the
  worker writes `heartbeat_at` and re-reads `cancel_requested_at`; past
  `started_at + timeout_seconds` it times out (§3.4).
- **Final:** `finished_at` set, the final event (`succeeded`, `failed`, `cancelled`,
  `timed_out`); `failed` and `timed_out` carry `error_code` + `error_message`, built only
  by `run_error_message` (the code's sentence, optionally `(HTTP 503)` or `(state
  rejected)` with a state name from `A2A_TASK_STATES`; any other agent-supplied value is
  left out). A run that **recorded its result succeeds** when the agent's task ends,
  whatever the task's final state, except after a cancel request (then `cancelled`; the
  result stays).
- **No result, no assignment:** when an evaluate run with `assigned_evaluator` ends in
  any status without the agent's **submitted** evaluation on the idea, the worker (in
  the finishing transaction, project → idea → run) removes that evaluator assignment and
  the agent's draft, if any: activity `evaluator_removed` with no actor (the SPA words it
  as the run ending without an evaluation), audit `evaluator.remove` with no actor
  (`rule: ai.request_evaluation`, `run_id`, `reason: ai_run_ended`). So "all evaluations
  are in" never waits for an agent that won't submit. An assignment that existed before
  the run is never touched.
- **Stopping the worker** (SIGTERM, every `helm upgrade`): the `ai` pool doesn't wait for
  its runs (they may take minutes): each run job is cancelled at once, sends
  `tasks/cancel` when it has a task id (at most `AI_RUN_CANCEL_TIMEOUT`, 5 s) and
  *finishes* `failed` `worker_lost` in its `finally`, well inside Kubernetes' 30-second
  grace period; the email pool keeps its 25-second grace. The two pools run in one
  process with procrastinate's signal handlers off (`install_signal_handlers=False`)
  and one handler of ours stopping both (two workers' handlers would replace each
  other). Runs are not resumed by the next worker (simple; the requester asks again).
- **The sweep** (worker, every minute, on the main pool so a full `ai` pool can't delay
  it): `running` runs whose heartbeat is older than `AI_RUN_STALE_AFTER` (2 min) →
  best-effort `tasks/cancel`, `failed` `worker_lost` (a worker that was killed);
  `queued` runs older than `AI_RUN_QUEUE_TIMEOUT` (30 min) → `timed_out`
  `queue_timeout`.
- **History** is kept with the idea (deleted with it); no retention job in Phase 6.

### 3.4 The A2A interaction

Verified against kagent v0.10.2's source, an a2a-sdk 1.2.1 server and the kagent-adk
0.10.2 and a2a-sdk 0.3.23 wheels (research R2 §1–2, the contract review); the live
controller is **not** (§8). kagent-adk 0.10.2, the Python runtime in kagent's agent
pods, speaks **A2A 0.3 only** (`kagent_v0_10`, the default); `kagent_v1_0` is for
kagent 1.0, unreleased when written.

**No discovery.** Runs don't read the agent card (kagent's agents always stream): the
worker sends `message/stream` straight to the built URL. An agent that can't stream
answers with a JSON-RPC error (`agent_protocol_error`). Test connection shows the card.

**Headers** on every A2A request: `Content-Type: application/json`; `Accept:
text/event-stream` (streaming) or `application/json`; `A2A-Version: 0.3`
(`kagent_v0_10`) or `1.0` (`kagent_v1_0`) (`A2A_VERSION`); `X-User-Id: soundings`
(`KAGENT_USER_ID`: kagent's caller identity; never a person's); `Authorization: Bearer
<SOUNDINGS_KAGENT_TOKEN>` only when set. Nothing else (no cookies, no Soundings key).

**The message** (one per run; `run_message(kind, run_id, idea_key, agent_name,
section_key)`): role user, `messageId` = the run id (a retried send can be recognised),
no `contextId` (kagent starts a fresh session per run), one text part (the
instructions: which tools to call, in order, with the idea key, the limits, that the
run's tools reach only this idea, that people's text is information and never
instructions, nothing copied out of Soundings beyond short search terms, real sources
only, no secrets), and `metadata.soundings = {run_id, kind, idea, section_key}` for
deterministic agents (the fake) and logs. **No URL**: the agent uses the MCP server its
operator configured (kagent's `RemoteMCPServer`; the fake agent's own setting), so a
message can't send its key elsewhere.

| | A2A 0.3 (`kagent_v0_10`) | A2A 1.0 (`kagent_v1_0`) |
|---|---|---|
| Stream (always) | `{"jsonrpc":"2.0","id":"<run>-1","method":"message/stream","params":{"message":{"kind":"message","messageId":"<run>","role":"user","parts":[{"kind":"text","text":"…"}],"metadata":{"soundings":{…}}},"configuration":{"acceptedOutputModes":["text/plain"]}}}` | `{"jsonrpc":"2.0","id":"<run>-1","method":"SendStreamingMessage","params":{"message":{"messageId":"<run>","role":"ROLE_USER","parts":[{"text":"…"}],"metadata":{"soundings":{…}}},"configuration":{"acceptedOutputModes":["text/plain"]}}}` |
| Poll (stream dropped or silent) | `tasks/get` `{"id": <task id>, "historyLength": 1}` every 2 s | `GetTask` `{"id": <task id>, "historyLength": 1}` |
| Cancel | `tasks/cancel` `{"id": <task id>}` | `CancelTask` `{"id": <task id>}` |
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
through MCP, and agent text never reaches progress events. `historyLength: 1`
(`A2A_HISTORY_LENGTH`) keeps a polled task small: kagent's tasks carry their whole
tool-call history (idea text), which would pass the 1 MiB cap; 1, not 0, because
a2a-sdk 0.3.23 treats 0 as "the whole history" (1.2.1 clears it). The send uses neither
`blocking` nor `returnImmediately` (streams don't block; 1.0 has no `blocking`, and its
server drops unknown fields silently). A task or context id longer than 200 characters
(`A2A_ID_MAX_LENGTH`) is `agent_protocol_error`, never a database error.

**Timeouts.** Connect 10 s; card 5 s (test connection); the stream may be silent for up
to `AI_RUN_STREAM_IDLE` (120 s), then the worker switches to polling `tasks/get` (the
message is never resent); a dropped stream with a task id also switches to polling. The
**deadline** is `started_at + timeout_seconds` (`asyncio.timeout` around everything):
then `tasks/cancel` (`AI_RUN_CANCEL_TIMEOUT`, 5 s, best effort) and `timed_out`
`timed_out` (or `succeeded` when the result is already recorded). **Any** answer to a
cancel is fine: kagent-adk 0.10.2's executor raises `NotImplementedError`, which a2a-sdk
0.3 returns as −32603 (internal error); the Go runtime and the fake cancel for real. The
run is final either way, and c22 refuses whatever the agent tries afterwards.

**Cancel.** `cancel_ai_run` on a queued run finishes it `cancelled` at once (event
`cancelled`); on a running one it sets `cancel_requested_at`/`_by_id` (event
`cancel_requested`); the worker sees it within about 2 seconds of the next stream event
or poll (at most the heartbeat), sends `tasks/cancel` (when there is a task id), stops
listening and finishes `cancelled`. From the cancel request on, c22 refuses the agent's
every call on that run (`ai_run_not_active`) and no result is attached.

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

In the same transaction as the write, after the tool has locked the project and the
idea (§3.3's lock order). There is no work outside a run: c22 refuses an agent's write
without an open run of that kind on that idea (and section). **`tool_called` events:**
the MCP dispatcher, for a call of a known tool (`AI_TOOL_MESSAGES`) by an agent's
service account naming an idea, adds `tool_event_message(tool, error_code)` ("Read the
idea", "Commented: forbidden") to the agent's open runs on that idea (the write tools:
to the run they attach to); `list_projects`, `search_ideas` and unknown tools add none
(never a raw tool name); **after the tool's transaction has ended** (committed or rolled
back), in a short transaction of its own: writing it while the tool's transaction holds
the run row would deadlock the call on itself; never arguments or results; at most
`AI_RUN_EVENTS_MAX` (200) events per run, the final included (once a run has 199,
non-final events are dropped).

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
- **c22, run scope** (new; a property of the principal, like c20 and c21, so not written
  in the cells). An **open run** is a run of the principal's agent with status `running`
  and no cancel request. For a **service-account principal** (every service account is
  an agent's; one without an agent row has no runs, so it can do nothing):
  - **REST:** every operation is refused with 403 `insufficient_scope` (agents' keys are
    MCP only), after the key check;
  - **MCP targets:** every tool naming an idea must name the idea of an open run (an
    idea the agent can't see: `not_found` as before; one it can see without an open run:
    `ai_run_not_active`); `get_rubric` by that idea or by its project; `list_projects`
    lists only the projects of its open runs' ideas and `search_ideas` only those ideas
    (both empty without an open run);
  - **MCP writes:** only the open run's kind's tool (`AGENT_RUN_WRITE_TOOLS`): evaluate →
    `submit_evaluation` (draft or submit), research → `add_research_note`, draft_section
    → `propose_proposal_section` with `section_key` = the run's section (another
    section: `ai_run_not_active`); `create_idea`, `add_comment` and any other write tool:
    `forbidden`, always. The read tools are `AGENT_READ_TOOLS`.

  For people, c22 refuses only `add_research_note` (`forbidden`). Check order on `/mcp`:
  key → rate → c15 → arguments → the idea (`not_found`) → c22 → the tool's rule and
  scope. Consequences: cancel, timeout and `worker_lost` are final (the agent can't
  finish later); disabling or narrowing an agent cuts it off at once; text planted in
  one idea can't make the agent read or write another; @mentions (and their emails)
  can't come from agents. The residual risk is a message sent to the agent by someone
  else (kagent's UI or A2A endpoint) while a run on the same idea is open (§3.1 "Reach").
- **Rule 9 (role matrix §3), for agents:** a service account never sees other
  evaluators' score data, before or after it submits: in `get_idea`, `search_ideas` and
  the shared queries it is treated as a pending evaluator on every idea
  (`score_hidden: true`, no aggregate, `n`, others' evaluations or their comments,
  unscored for sorting and filters); its own evaluation stays visible to it.
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
  they are written: **one poller per run per API process** reads `ai_run_events` once a
  second in a short database session of its own (opened and closed per poll: the
  request's `SessionDep` is closed before streaming starts, `app/db.py`) and fans new
  events out to every open stream of that run in the process; no `LISTEN/NOTIFY`;
  `: keep-alive` comments every 15 s. After the
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
  flag) or leaves it out again. **A re-submission that changes any score or the
  recommendation resets it to left out** (in the same transaction; a later run, or an
  agent steered within its run, can't change a counted score unseen; the owner includes
  it again after reading it); one that changes only text keeps the choice. Visibility is
  unchanged by inclusion (role matrix §3 rules 4, 5 and 10).
- **AI badge** wherever its work appears: the evaluator row (`IdeaEvaluator.is_ai`), the
  evaluation (`Evaluation.is_ai`, with "Not in score" while excluded and, for
  `can_include_ai`, an "Include in score" switch), suggestions (`source: ai`), research
  notes (always AI), the run panel.
- **Rationale and sources:** an AI evaluator's per-criterion `comment` is its rationale
  (required, ≤ 1,000 characters; the SPA labels it "Rationale"); `sources` (≤ 5 per
  criterion, `Citation {title, url, host}`) are shown under it as plain links (§1) under
  "Cited by AI, not checked" (an agent without a web tool may invent sources). URLs are
  stored as plain ASCII (`CitationIn.url`: the host in IDNA punycode, other non-ASCII
  %-encoded; spaces, control, zero-width and bidi characters refused), so `host` can't
  show a look-alike. The overall `comment` is its summary. Sources reach REST at
  integration (§5).
- **Evaluator progress and "all evaluations are in"** count the AI evaluator like any
  assigned evaluator (it is in the list); a run that assigned it and ends without its
  submitted evaluation removes the assignment again (§3.3); remove it by hand to stop
  waiting for it otherwise.
- **The agent is blind, always** (rule 9): its `get_idea` shows `score_hidden: true`
  before and after it submits; its evaluation is visible to others only per section 3,
  like a person's.

### 3.8 Research notes

- One per run (`add_research_note`; calling again replaces the text), stored as an
  `activity_events` row of type `ai_research_note` (actor: the service account; payload
  `{run_id, agent_id, body_md, sources: [{title, url}]}`); Markdown 1–20,000 characters;
  0–20 sources. In the feed at integration (`AiResearchNoteActivity {…, note:
  ResearchNote}`), and now through `get_research_note`.
- Rendered sanitised with an AI label ("Research note by Idea evaluator · AI"), links
  http/https only (no `mailto:`); sources as a numbered list of plain links under
  "Cited by AI, not checked" (the example researcher has no web tool, so its sources may
  be invented). No notifications, mentions or emails (the requester watches the run; the
  note is in the feed). Not score data: the agent never sees others' scores or
  evaluation comments (rule 9), so a note can't quote them to a pending evaluator; the
  instructions forbid scores and go/no in notes (the agent's own opinion could still
  appear: accepted, documented risk).
- **Deleting** (`ai.delete_note`: the idea's owner, project and platform admins; §10) clears the text and
  sources (`deleted: true`), keeps the item ("deleted a research note"); idempotent.

### 3.9 Section drafts

`request_ai_section_draft` needs a proposal (404 otherwise) and c7. The agent reads
`get_idea` and `get_proposal` and calls `propose_proposal_section` (Phase 5, `source:
ai`, replacing its earlier pending suggestion for the section) for the run's section
only (c22: another section is `ai_run_not_active`); the owner accepts or discards it in
the editor as any suggestion. One active draft run per idea, agent and section; drafts
of different sections run side by side.

### 3.10 Audit

New `AuditAction` values, **agreed but not yet in the schema** (integration step §5;
`audit.record` refuses unknown actions until then, tests can patch `AUDIT_ACTIONS`):

| Action | Actor | Target | Details (never keys, prompts, agent text or URLs with tokens) |
|---|---|---|---|
| `ai_agent.register` | the admin | `user`: the service account | `rule: platform.manage_agents`, `agent_id`, `namespace`, `name`, `protocol`, `purposes`, `project_ids` |
| `ai_agent.update` | the admin | `user`: the service account | `rule`, `agent_id`, `changed` (field names), `enabled` when it changed |
| `ai_run.request` | the requester | `idea` | `rule` (`ai.request_evaluation` \| `ai.research` \| `ai.draft_section`), `run_id`, `agent_id`, `kind`, `section_key` (an idempotent 200 isn't audited again) |
| `ai_run.cancel` | the canceller (or the admin who disabled or narrowed the agent) | `idea` | `rule: ai.cancel_run` (or `platform.manage_agents`), `run_id`, `agent_id`, `status` when cancelled |
| `evaluation.include_ai` | the owner or admin | `idea` | `rule`, `evaluation_id`, `evaluator_id`, `include` |

Existing actions cover the rest: `api_key.create` / `api_key.revoke` (rule
`platform.manage_agents`; also when disabling revokes the key), `project.member_add` /
`project.member_remove` for the agent's memberships, `evaluator.add` when "Ask AI"
assigns it and `evaluator.remove` (no actor, `reason: ai_run_ended`) when a run without
an evaluation undoes that (§3.3), `evaluation.submit` (with `include_reset: true` when a
changed AI re-submission left the aggregate, §3.7) and `mcp.call` for the agent's calls.
Run outcomes are the run rows themselves.

### 3.11 Helm values (platform; off by default)

Names are the contract with the environment variables; platform owns the chart.

| Value | Env | Default | Notes |
|---|---|---|---|
| `features.ai` | `SOUNDINGS_AI_ENABLED` | `false` | exists |
| `kagent.enabled` | — | `false` | exists: admits kagent's namespace to `/mcp` (NetworkPolicy); Phase 6: **also agent pods** (labelled `app.kubernetes.io/managed-by: kagent`) in each of `kagent.agentNamespaces` (by default the release namespace), since kagent's agents call `/mcp` from their own namespace, not the controller's; and the api and worker **egress** to `kagent.controllerUrl`'s port when `networkPolicy.egress.enabled` |
| `kagent.namespace` | — | `kagent` | exists |
| `kagent.controllerUrl` | `SOUNDINGS_KAGENT_URL` | `http://kagent-controller.<kagent.namespace>:8083` | new |
| `kagent.existingTokenSecret` / `.tokenSecretKey` | `SOUNDINGS_KAGENT_TOKEN` | `""` / `token` | new; api and worker |
| `kagent.agentNamespaces` | `SOUNDINGS_AI_AGENT_NAMESPACES` | `[]` → the release namespace | new; empty renders the release namespace (where the example agents run), so an admin can't point a run at kagent's built-in agents in `kagent` by default; list namespaces to allow more. The app's own default (no variable) stays "any" for development |
| `ai.runTimeout` | `SOUNDINGS_AI_RUN_TIMEOUT` | `PT5M` | new |
| `ai.maxConcurrentRuns` | `SOUNDINGS_AI_MAX_CONCURRENT_RUNS` | `4` | new; per worker pod (the `ai` queue's own pool); the worker's database pool grows by this much |
| `ai.defaultProtocol` | `SOUNDINGS_AI_DEFAULT_PROTOCOL` | `kagent_v0_10` | new |
| `ai.mcpUrl` | `SOUNDINGS_AI_MCP_URL` | the release's Service URL + `/mcp` | new; the chart sets it; shown to admins for the `RemoteMCPServer`, never sent to agents |
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
- **Work:** reads `metadata.soundings` (`kind`, `idea`, `section_key`) and calls **its
  own configured MCP URL** (e.g. `FAKE_AGENT_MCP_URL`, like kagent's `RemoteMCPServer`;
  never a URL from the message, which carries none) with the key for that agent from its
  environment (e.g. `FAKE_AGENT_KEYS` mapping `namespace/name` → `sdg_…`, or a mounted
  Secret per agent): `evaluate` → `get_rubric`,
  `get_idea`, `submit_evaluation` (every criterion: a score derived from the criterion's
  position, a rationale naming the criterion and the idea, two sources on
  `https://example.org/…`, a recommendation and summary); `research` → `get_idea`,
  `add_research_note` (a short Markdown note with three sources); `draft_section` →
  `get_idea`, `get_proposal`, `propose_proposal_section` for the section.
- **Behaviours by agent name suffix** (for tests): `-slow` keeps working (status updates
  every 2 s) until cancelled or the deadline; `-fails` ends `failed` after its first
  tool call; `-silent` completes without calling a tool (`no_result`); `-asks` goes
  `input-required`; `-rejects` ends `rejected`; `-blind-probe` records `score_hidden` and
  whether any other evaluation was visible on every `get_idea`, before and after it
  submits, for every kind (rule 9: always hidden, research runs included); `-strays`
  first tries `add_comment`, `create_idea`, `get_idea` on the next idea number and
  `propose_proposal_section` for another section, recording the error codes (c22:
  `forbidden`, `ai_run_not_active`), then does its work; `-late` ignores cancel and the
  deadline and calls its write tool a few seconds after its run ended, recording the
  error (`ai_run_not_active`). Cancel works for every other agent (the task ends
  `canceled`). Observations are readable by tests (e.g. `GET /_fake/observations`).
- It logs run ids and tool names only, never keys. It is **not kagent**: §8 says what it
  proves and what it doesn't.

### 3.13 Minimum tests (tests first)

- **Authorisation:** each run request, cancel, the toggle and note delete for every
  column (PA, PAd, Mem, Vwr, NMi, NMp, Pub) and the owner overlay (also demoted), each
  condition (c5, c6, c7, c10 for each of its parts: AI off, agent disabled, wrong
  purpose, project not served, service account a viewer or removed, key revoked,
  unknown agent; c19, archived, held for confirmation → 404); a service account's key
  on any REST route (requesting a run included) → 403 `insufficient_scope`; keys:
  `read` only → 403 `insufficient_scope` on requests; admin routes refuse keys and
  non-admins; c20 on register and rotate; `AiPermissions` reasons for each blocked case.
- **c22, run scope** (every MCP tool, with and without an open run): an agent without an
  open run lists no projects or ideas and gets `ai_run_not_active` on every idea; with an
  open run on CUST-12 it reads CUST-12 only (another idea, also in the same project:
  `ai_run_not_active`; `get_rubric` by another project: `ai_run_not_active`); writes only
  through the run kind's tool (`create_idea`, `add_comment`: `forbidden`; the evaluate
  tool during a research run and another section's draft: `ai_run_not_active`);
  everything refused from the cancel request on, after a timeout and after `worker_lost`
  (the fake's `-late` and `-strays`); a service account without an agent row is refused
  everything.
- **Rule 9 for agents:** the agent's `get_idea` and `search_ideas` show `score_hidden:
  true`, no aggregate and no other evaluation, before and after it submits, on evaluate
  and research runs (the fake's `-blind-probe`); its own evaluation is in
  `my_evaluation`.
- **Idempotency:** two concurrent requests for the same idea, agent and kind → one run
  (201 and 200, same id); the same after it finished → a new run; different sections →
  two runs; the per-person limit (21st request in an hour → 429; a 200 doesn't count).
- **Exclusion:** an AI evaluation submitted through MCP is `include_in_aggregate: false`
  and the aggregate and `n` are unchanged; include → they change; exclude → back;
  an included AI evaluation re-submitted with a changed score or recommendation is left
  out again (text-only changes keep it); the toggle on a person's evaluation → 409; a
  pending evaluator (also an admin or the owner) → 404.
- **Timeout and cancel** (with the fake agent's `-slow`): the run ends `timed_out` at the
  deadline and the fake saw `tasks/cancel`; cancel while queued → `cancelled` without a
  message sent; cancel while running → `cancel_requested` then `cancelled`, the fake saw
  `tasks/cancel`; a result recorded before the deadline → `succeeded`; `-silent` →
  `no_result`; `-asks` → `agent_needs_input`; `-fails` → `agent_failed`; kagent down →
  retries then `agent_unreachable`; the sweep (`worker_lost`, `queue_timeout`); a request
  meeting a run queued past the queue timeout finishes it and returns a new one (201);
  concurrency (`AI_MAX_CONCURRENT_RUNS=1`: the second run waits queued, while email and
  `notify_event` jobs still run); stopping the worker mid-run → `worker_lost` at once and
  the fake saw `tasks/cancel`; a cancel answered with −32603 still ends `cancelled`; a
  failed or cancelled evaluate run that assigned the agent removes that assignment (and
  "all evaluations are in" fires if the others are in); concurrent cancel and completion
  end in exactly one final status.
- **SSRF:** with a mock transport, the only URLs requested are the built card (test
  connection) and A2A URLs (for both protocols); a run never fetches the card; a 302
  from the controller → `agent_protocol_error` without following; oversized card,
  response or SSE event → `agent_protocol_error`; with `HTTPS_PROXY` set the client
  doesn't use it (`trust_env=False`); bad labels never reach the builder (422) or the
  database (check constraints); a polled task carries `historyLength: 1`.
- **SSE:** 401 without a session; 404 for a hidden idea, another idea's run, a private
  non-member; replay after `Last-Event-ID` and `?after=`; live events; the stream closes
  after the final event; 204 on reconnect after it; removing the watcher's access
  mid-stream ends it within 30 s; a pending human evaluator streaming an AI evaluation
  run receives no score, recommendation, rationale, source or comment text (the fake's
  rationale strings and URLs never appear in the stream or in `get_ai_run`).
- **Results:** each kind's result attached (and only to its run); `add_research_note`
  refused for people (`forbidden`) and without a running research run
  (`ai_run_not_active`); a second note replaces the first; `tool_called` events with
  Soundings' tool sentences only (an unknown tool name adds none), written after the
  tool's transaction (no self-deadlock when the call attaches a result); error messages
  with an unknown A2A state name leave it out; the 200-event cap, final included.
- **Agents:** registration creates the service account, memberships, key (scopes per
  purpose, restriction = projects) and shows the key once; updating purposes and
  projects updates the same key and memberships and cancels the active runs a dropped
  purpose or project covers; disabling cancels runs and revokes the key (401), enabling
  leaves `key: null` until a rotation; rotation revokes the old key; the A2A URL in the
  response is the built one; the Secret name is never cut.
- **Citations:** an international host is stored and shown in punycode; bidi, zero-width
  and other invisible characters are refused.

### 3.14 Acceptance (SPEC Phase 6): "Ask AI to evaluate" produces a badged, cited evaluation excluded from the aggregate by default

Against the real stack with the fake agent (`kagent_v0_10`, required; once more with
`kagent_v1_0` **optional**: kagent 1.0 is unreleased and kagent-adk 0.10.2 speaks 0.3
only, so the 1.0 run proves our client against a2a-sdk's 1.0 server and the fake, not
against kagent):

1. A platform admin registers "Idea evaluator" (`soundings/idea-evaluator`, purposes
   evaluate and research) for Customer Innovation; the key is shown once; the operator
   (the test) gives it to the fake agent. Test connection is ok.
2. CUST-12 has two submitted human evaluations; note its aggregate and `n`. A third
   evaluator (a pending person) opens the idea.
3. The owner clicks "Ask AI to evaluate": 201, the evaluator list shows "Idea evaluator ·
   AI · Invited"; a second click returns the same run (200). The pending evaluator opens
   the run's event stream (from the start: it replays what it missed).
4. The stream shows queued → started → the agent started → Read the rubric → Read the
   idea → Saved its evaluation → Evaluation submitted → Done; the pending evaluator's
   stream holds no score data.
5. The run is `succeeded` with `result.evaluation_id`; the evaluator row says Submitted
   with the AI badge; the Evaluations tab (owner) shows the AI evaluation with a
   rationale and sources for every criterion and "Not in score"; the aggregate and `n`
   are unchanged; the pending evaluator still sees nothing (`score_hidden`).
6. The owner includes it: the aggregate and `n` change; excludes it: back.
7. "Research this" adds a research note with sources to the feed (the agent saw
   `score_hidden: true` throughout); "Draft section" on the Risks section of CUST-4's
   proposal adds an AI suggestion the owner accepts.
8. With no run open, the agent's key lists nothing on `/mcp` and gets 403 on REST.

### 3.15 Screens (frontend)

- **Admin settings → AI agents:** the settings in effect (a banner when `features.ai` is
  off); agents with their kagent name, purposes, projects (with "removed" where the
  service account lost its role), key prefix and last use, enabled; "Register agent"
  (a sheet: display name, description, namespace, name, protocol, purposes, projects;
  a line that the agent works only on the idea of a run someone asked for); the key
  reveal **once** with copy buttons for the key and the Secret manifest and the "you
  won't see it again" warning (Phase 5's pattern); Test connection (card name, versions,
  streaming, skills, or the error); Rotate key (confirm: "the agent stops until its
  Secret is updated"); Disable (confirm: "its runs stop and its key is revoked; you'll
  rotate the key to enable it again") / Enable (then offer Rotate key).
- **Idea page:** for the owner and admins, an "AI" menu in the primary actions with "Ask
  AI to evaluate" and "Research this" (one agent: direct; several: pick one), disabled
  with the reason `permissions.*_blocked_by` gives (`AiBlockedReason`: "AI assistance is
  off", "No AI agent serves this project", "Evaluation is closed", "Waiting for
  moderation", …); a calm run panel (who asked, the agent,
  live steps, elapsed time and the deadline, Cancel) that streams with SSE and falls
  back to polling; recent runs collapsed with their outcome and error sentence.
- **Evaluators list and Evaluations tab:** the AI badge; the run's state on the AI
  evaluator's row while active; the AI evaluation card: "Rationale" per criterion, its
  sources as links with hosts under "Cited by AI, not checked", "Not in score" chip and
  the "Include in score" switch (`can_include_ai`; disabled with
  `include_ai_blocked_by`), a line explaining the default (and that a changed
  re-submission is left out again).
- **Activity feed** (integration): research notes with the AI label, sanitised
  Markdown (http/https links only), numbered sources under "Cited by AI, not checked",
  "Delete" for admins; `evaluator_removed` without an actor reads as the AI run ending
  without an evaluation ("Idea evaluator's run ended without an evaluation; it was
  taken off the evaluators").
- **Proposal editor:** "Draft with AI" per section (owner and admins, c7; disabled with
  `draft_section_blocked_by`), progress in place, and the suggestion appearing with its
  AI badge (Phase 5's cards).
- Loading, empty and error states, keyboard, dark mode and 390 px as everywhere.

## 4. MCP additions

The models are in `app/schemas/mcp.py`; nothing here is in OpenAPI.

| Change | Contract |
|---|---|
| `submit_evaluation` scores | `McpScoreIn(MyScoreIn)` adds `sources: [CitationIn]` (0–5; `title` one line 1–200, `url` http(s) ≤ 2,048 without credentials, spaces, control, zero-width or bidi characters, stored as plain ASCII with a punycode host). **Service accounts only:** a person's key sending any source → `validation_error` ("Only AI evaluators cite sources."). A service account's submission needs a comment (rationale) on every scored criterion → `evaluation_incomplete`. |
| `McpScoreEntry` | adds `sources: [McpCitation {title, url}]` (marked `UNTRUSTED`; empty for people) in `get_idea` and `submit_evaluation` results. |
| c22 in every tool | For a service-account principal (§3.5): targets limited to the ideas of its open runs (`ai_run_not_active`), `list_projects` / `search_ideas` filtered to them, writes only through `AGENT_RUN_WRITE_TOOLS[run.kind]` (`create_idea`, `add_comment`: `forbidden`). `MCP_INSTRUCTIONS` gain a bullet saying so. |
| Rule 9 in `get_idea` / `search_ideas` | For a service account: `score_hidden: true`, `score` / `aggregate` null, `evaluation_count` 0, `evaluations` empty, `high_disagreement` false, before and after it submits; `my_evaluation` is its own. |
| `add_research_note` (new, `ADD_RESEARCH_NOTE`) | Rule `comment.create` + c22, scope `write`; not read-only, idempotent. Input `AddResearchNoteInput {idea, body_md (1–20,000), sources (0–20)}` (unknown arguments refused); output `AddResearchNoteOutput {idea, note_id, replaced}`. Errors: `forbidden` (a person, or an agent without the member role), `ai_run_not_active` (no running research run on the idea for this agent, or it is being cancelled), `not_found`, `validation_error`, `project_archived`, `idea_closed`. Audited `mcp.call` like every tool. |
| Instructions | `MCP_INSTRUCTIONS`' evaluate bullet now mentions rationale and sources and that agents never see others' scores; a new bullet says agents' keys work only during a run; `RESEARCH_NOTE_INSTRUCTION` is appended when the tool lands. |
| Catalogue | `MCP_TOOLS` stays nine until backend adds the handler (`app.mcp.tools.TOOLS`) and appends `ADD_RESEARCH_NOTE` to `MCP_TOOLS` (a lead-approved one-line change in `app/schemas/mcp.py`) in the same change, updating `tests/mcp` and `tests/test_schemas_phase5.py`'s `SPEC_TOOLS` (ten). |
| Run events | Each call of a known tool by an agent's service account on an open run's idea adds a `tool_called` event (`tool_event_message`, after the tool's transaction; §3.4). |

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
| 403 | `insufficient_scope` | also: any REST route with an agent's key (c22: MCP only) |
| MCP | `ai_run_not_active` | c22: an agent's tool call on an idea without its open run (none, cancel requested, or of another kind or section for a write) |
| MCP | `forbidden` | also: `add_research_note` by a person; `create_idea`, `add_comment` by an agent (c22) |

Run outcomes are not HTTP errors: `AiRunError` values in `AiRun.error.code` (§3.3).

## 7. Decisions

Simpler option chosen each time; the lead may revisit (also in
[decisions.md](../decisions.md) and [ADR 0014](../adr/0014-kagent-a2a-integration.md)).

| Decision | Why |
|---|---|
| The A2A URL is built from one configured controller origin, a fixed path per protocol and two DNS labels; no URL field anywhere; card URLs ignored; no redirects. | SSRF can't be configured in: the only reachable host is the operator's controller. |
| One `protocol` per agent: `kagent_v0_10` (A2A 0.3 at `/api/a2a/{ns}/{name}/`) or `kagent_v1_0` (A2A 1.0 at `/agents/{ns}/{name}`), default from settings. | kagent's stable line and its 1.0 rewrite differ in both path and protocol; one choice per agent covers a mixed or migrating cluster without negotiation logic. |
| Results come back through MCP tools as the agent's service account and are attached to the run by the server; A2A text and artifacts are ignored. | kagent 0.10 has no output schema; authorisation, blind evaluation, limits and audit then apply to agents exactly as to people; no parsing of model output. |
| **c22, run scope:** an agent's key works on `/mcp` only, on the idea of an open run, writing only through the run kind's tool; nothing else, ever. | A long-lived key that is a full member outside runs would let anyone who can message the agent (kagent's UI, `--auth-mode=unsecure`) or text planted in any idea drive it; with the scope, cancel, timeout and `worker_lost` are final and one agent can serve many projects. Per-run keys would need Kubernetes API access Soundings doesn't have, and add nothing once the long-lived key is inert outside runs. |
| **Agents never see others' score data** (rule 9), before or after submitting. | Whatever they write (notes, suggestions, rationale) is read by pending evaluators; and people's evaluation comments shouldn't reach an LLM provider or kagent's session store. |
| Rationale = the per-criterion comment (required for agents); sources a JSONB column on `evaluation_scores` (≤ 5). | One evaluation shape for people and agents; no sibling table; the existing evaluate UI shows it. |
| Research notes are `activity_events` rows (`ai_research_note`, payload body + sources), one per run, deletable by admins; a dedicated MCP tool that needs a running research run. | No new table; the feed is where SPEC puts them; a note can't be planted outside a requested run. |
| One agent row = one service account = one key; scopes from purposes; restriction = its projects; the server keeps the key's scopes and restriction in step with the agent. | Least privilege per purpose; adding a project never requires re-deploying a Secret; immutability stays the rule for people's keys. |
| Agents join projects as members through Admin settings → AI agents; project admins may remove them; pickers never list agents. | A platform admin decides an agent's reach (prompt-injection blast radius); project admins keep a veto. |
| Disabling an agent cancels its runs and **revokes** its key; enabling it again needs a rotation. | One switch stops an agent completely; no special case in the key source, and a downgrade below 0011 can't bring a disabled agent's key back. |
| Runs are rows with events; the worker runs them from their own `ai` queue with a pool of `AI_MAX_CONCURRENT_RUNS` per process, compare-and-set transitions, a heartbeat and a sweep; on shutdown it ends its runs `worker_lost`; no job retries, no resuming. | Durable, observable, restart-safe; AI runs that hold a slot for minutes never delay email or the schedules; first in, first out for free; nothing is sent twice. |
| One active run per idea + agent + kind (+ section), enforced by a partial unique index; a repeated request returns the active run (200). | Double clicks and races are harmless; the button is idempotent. |
| Progress over SSE from the API, read from `ai_run_events` by one poller per run per process; polling `get_ai_run` as the fallback; events are fixed sentences (known tool names only; error messages add an HTTP status or a known A2A state at most). | Works through any replica and the ingress; blind-safe by construction; no agent text in the UI. |
| Runs always stream (`message/stream`), never read the card, poll `tasks/get` with `historyLength: 1` when the stream drops. | kagent's agents always stream; one code path; a polled kagent task would otherwise carry the whole tool-call history. |
| Excluded from the aggregate by default; the owner and admins include per evaluation; a changed AI re-submission is left out again. | SPEC section 9; an included score never changes unseen. |
| An evaluate run that assigned the agent and ends without its evaluation removes the assignment. | "All evaluations are in" never waits for an agent that won't submit. |
| Constants for limits (20 runs/hour/person, 50 agents, 200 events, 5 streams, timings); settings only for what operators must choose. | Simple beats configurable. |
| No new notification types in Phase 6. | The requester watches the run; results land in the feed, the evaluators list and the editor; existing notifications (evaluation submitted, all in) still fire. |

## 8. Verified vs assumed (kagent)

| | Status | Source |
|---|---|---|
| kagent v0.10.2 CRDs (`agents.kagent.dev` v1alpha2 storage, `remotemcpservers.kagent.dev`, `modelconfigs.kagent.dev`), the minimal `Agent` / `RemoteMCPServer` / `ModelConfig` manifests, `headersFrom.valueFrom {type, name, key}` | **verified** (applied to k3s; server-side dry run) | research R2 §1, Phase 5 |
| kagent's MCP client (go-sdk v1.6.1) against `/mcp` | **verified** (the library kagent pins) | Phase 5 |
| A2A endpoint layout `/api/a2a/{ns}/{name}/` on the controller (port 8083), card at `.well-known/agent-card.json`, `A2A-Version` selecting 0.3 or 1.0 method names (other values 400), `X-User-Id`, `contextId` = session | from **source** (v0.10.2), not a live controller | research R2 §1 |
| A2A 0.3 and 1.0 wire shapes, streaming order, `final` (0.3 only), cancel, error codes −32001/−32002/−32004 | **verified** against an a2a-sdk 1.2.1 server with a kagent-identical card; kagent's a2a-go v2.3.1 checked in source | research R2 §1–2 |
| The fake agent end to end through Soundings (message, stream, MCP calls, results, cancel, timeout, worker shutdown, every misbehaviour suffix, A2A 0.3 and 1.0) | **verified against the fake** (2026-10-06): backend acceptance (`test_phase6_acceptance.py`), `E2E_AI=1` e2e, `make ai-smoke`, `make demo DEMO_AI=1`, `make k3s-smoke AI=1` (the fake as `kagent/kagent-controller:8083`, through Traefik and the NetworkPolicies); the fake's 0.3 wire format checked with a2a-sdk 0.3.23's client (kagent-adk 0.10.2's library). Not kagent's controller | §3.12, `deploy/kagent/README.md` |
| The example manifests (`deploy/kagent/*.yaml`, the chart's `kagent.examples`) | **verified** against kagent v0.10.2's CRDs from the git tag (server-side dry run, and created for real) in k3s v1.31; the chart itself can't be pulled here (ghcr blobs blocked) | `make k3s-kagent-crds` |
| The controller proxying to agent pods, `tasks/get` from kagent's database, streaming through the controller, its behaviour on a duplicate `messageId` | **assumed** (source reading only) | — |
| kagent 1.0: path `/agents/{ns}/{name}`, card under it, `A2A-Version: 1.0` required | **assumed** from the pre-release's main branch (alpha5); re-check when 1.0 ships | research R2 §1 |
| The Python runtime can't cancel (`NotImplementedError`, answered −32603; the Go runtime can) | from the kagent-adk 0.10.2 wheel (contract review); handled (any cancel answer is fine) | research R2 §1 |
| kagent-adk 0.10.2 speaks A2A 0.3 only (a2a 0.3 types, `a2a-sdk>=0.3.23`) | from the wheel (contract review) | — |
| a2a-sdk 0.3.23 `tasks/get`: `historyLength` 0 returns the whole history, ≥ 1 the last N; 1.2.1: 0 clears it. 1.0's send configuration has `returnImmediately`, no `blocking`; unknown fields are dropped | **verified** in the wheels' source (0.3.23 here; 1.2.1 by the review) | §3.4 |
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

### Contract review (2026-10-06, before any builder started)

The adversarial review's findings, applied to the schemas, models, migration 0011,
settings, route descriptions and these docs (`make gen-api` rerun):

| Finding | Change |
|---|---|
| M1 agent keys are full members outside runs | c22 is now the **run scope** (§3.5): REST refused to agents, every tool on an open run's idea, writes only through `AGENT_RUN_WRITE_TOOLS`; `AGENT_READ_TOOLS`; `MCP_INSTRUCTIONS` bullet; the "one agent per project" advice replaced by §3.1 "Reach" (residual risk: a direct message to the agent during a live run) |
| M2 notes could carry scores | Role matrix §3 rule 9: agents never see others' score data, before or after submitting (§3.5, §4); fake `-blind-probe` on every kind |
| M3 runs take every worker slot | `AI_RUN_QUEUE` (`ai`) with its own pool of `AI_MAX_CONCURRENT_RUNS` per worker process; the advisory-lock count and the 5-second re-defer are gone |
| S1 races and lock order | Compare-and-set transitions; project → idea → run; `tool_called` after the tool's transaction (§3.3–3.4) |
| S2 deploys kill runs | Shutdown cancels at once (`AI_RUN_CANCEL_TIMEOUT`, 5 s) and ends runs `worker_lost`; message reworded; no resuming (simple) |
| S3 A2A 1.0 send / large tasks | Always stream (no non-streaming branch, no `blocking`/`returnImmediately`); `historyLength: 1` (`A2A_HISTORY_LENGTH`; 0 means "all" in a2a-sdk 0.3.23, verified) |
| S4 agent words in messages | `run_error_message` (states only from `A2A_TASK_STATES`), `tool_event_message` (known tools only) |
| S5 re-submission keeps "include" | A changed score or recommendation resets `include_in_aggregate` (§3.7) |
| S6 narrowing, stale assignments | Dropped purposes/projects cancel runs; `ai_runs.assigned_evaluator` + removal when a run ends without its evaluation (§3.3) |
| S7 downgrade restores keys | Disabling revokes the key (enable → rotate); 0011's downgrade revokes every agent's key and deletes `ai_research_note` rows (tested) |
| S8 missing indexes | Partial indexes on `ai_runs.evaluation_id`, `suggestion_id`, `activity_event_id` |
| S9 look-alike hosts | `CitationIn.url` stored as ASCII (punycode host, %-encoded rest; invisible characters refused); `Citation.host` ASCII; "Cited by AI, not checked" |
| S10 MCP URL in the message | Removed from `run_message` (text and metadata); the fake uses its own configured URL; `AI_MCP_URL` is shown to admins only |
| S11 NetworkPolicy | §3.11: ingress from agent pods in `kagent.agentNamespaces` |
| S12 proxy settings | §3.2: `trust_env=False`, explicit SSL context |
| S13 Secret names | `agent_secret_name` never cuts |
| S14 unexplained disabled actions | `AiBlockedReason` and `AiPermissions.*_blocked_by` |
| C1, C2, C7, C8, C10 | Accepted: 0.3-only kagent-adk and best-effort cancel (§3.4, §8); no card fetch per run, no LISTEN/NOTIFY, one poller per run (§3.4, §3.6); `agentNamespaces` defaults to the release namespace (§3.11); a stale queued run expires on the next request (§3.3); the 1.0 acceptance run is optional (§3.14) |
| C5, C6, C9 | Accepted: http/https links only in agent Markdown; instructions made consistent and the exfiltration risk documented (§3.1); nits: §3.4 reference, distinct purposes in the database and before `max_length`, 200 events including the final, acceptance step order, `note_id` = `activity_event_id`, long task ids |
| C3 key scopes at use time | **Declined**: c22 confines agents; the stored scopes and restriction stay a second fence, kept in step by `update_ai_agent` in one transaction (no extra join in every key check) |
| C4 owners delete notes | **Declined for now**: it needs a new policy rule (identity); admins delete notes (`comment.delete_any`); proposed for the lead with `ai.delete_note` (owner + admins) if wanted |

### Builders' changes

Builders record additive contract changes here (date, change, why), then run
`make gen-api`.

| Date | Change | Why |
|---|---|---|
| 2026-10-06 | **Integration step (§5), done by backend first thing:** `ActivityItem` gains `AiResearchNoteActivity` (`ACTIVITY_TYPES` and `PAYLOAD_KEYS` gain `ai_research_note`); `EvaluationScore` gains `sources: [Citation]` (empty for people); `AuditAction` gains `ai_agent.register`, `ai_agent.update`, `ai_run.request`, `ai_run.cancel`, `evaluation.include_ai`; `MCP_TOOLS` gains `add_research_note` (ten tools; `MCP_INSTRUCTIONS` gains `RESEARCH_NOTE_INSTRUCTION`'s bullet) with its handler. `make gen-api` rerun. | Lead's build notes: the §5 items land in this build, before the frontend's screens |
| 2026-10-06 | New rule **`ai.delete_note`** (role matrix table J: PA Y, PAd Y, Mem/Vwr/NMi 403, NMp 404, Pub 401, `+Own` +; an idea write: archived 409, c19; key scope `write`). `delete_research_note` and `ResearchNote.can_delete` use it instead of `comment.delete_any`, so the idea's owner may delete an AI note too (descriptions changed, no field changed). | Lead's decision on review item C4 |
| 2026-10-06 | `rotate_ai_agent_key` answers **409 `ai_unavailable`** ("reactivate the service account first") when the agent's service account is deactivated (a key can't be issued to an inactive owner; before, the key service's 401 would have reached the admin). No schema change. | Found while building rotation (§2 listed 403 and 404 only) |
| 2026-10-06 | Integration, no schema change: `AiRun.cancel_requested` is true only while the run is active ("Cancelling" until it ends), so a queued run cancelled at once answers `cancel_requested: false` (the mock already did). The SPA labels an agent's feed lines with the AI badge from data it already has (the idea's AI evaluators and the runs' agents), so `UserRef` needs no `is_ai`. | QA nit; QA visual list |
| 2026-10-06 | Implementation notes, no contract change: an agent's key is restricted to the agent's projects whatever role its service account has there now (c10 decides per project), so `issue_key` skips the "owner can view" check for agents' keys; `tool_called` events of a **write** tool go to the agent's open run of that tool's kind on the idea (the run the call attaches to, or would); `result_recorded` is written right after the `tool_called` event, after the tool's transaction, so the stream reads "Saved its evaluation" then "Evaluation submitted"; non-final events are never added to a run that already ended. | Recorded for reviewers |

