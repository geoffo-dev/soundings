# The fake kagent agent

A small, deterministic stand-in for [kagent](https://kagent.dev) and its agents, so
Soundings' AI assistance (SPEC section 9, contract-phase6) runs end to end where there
is no kagent and no model provider: dev machines, the e2e stack, CI and the local k3s
cluster. It speaks the A2A surface of kagent **v0.10.2**'s controller and, when a run
arrives, really calls Soundings' MCP server with the agent's own service-account key, so
everything Soundings does is exercised for real (the worker's A2A client, streaming,
cancel and deadlines, c22's run scope, blind evaluation, result matching, SSE); only the
model is missing. **It is not kagent**: what it proves and what it doesn't is at the end.

Dev, e2e, CI and k3s only. Never deploy it next to a real Soundings install: it holds keys
in plain files and its `/_fake/observations` endpoint has no authentication.

## Run it

```sh
make -C dev/fake-agent install      # uv sync --locked
make -C dev/fake-agent run          # 0.0.0.0:8083, MCP http://localhost:8000/mcp, keys in dev/.fake-agent-keys
make -C dev/fake-agent check        # ruff, mypy --strict, pytest (~20 s)
make fake-agent-image               # soundings-fake-agent:dev (python:3.12-slim, non-root, read-only friendly)
```

The e2e stack starts it with `E2E_AI=1` (`e2e/scripts/start-stack.sh`), `make k3s-fake-agent`
runs it in k3s as `kagent/kagent-controller:8083`, and `docker compose -f
dev/docker-compose.yml --profile ai up -d` next to `make dev`. `scripts/ai-smoke.sh`
(`make ai-smoke`) registers an agent, hands it its key and runs the Phase 6 acceptance
through it.

## Settings (environment)

| Variable | Default | Meaning |
|---|---|---|
| `FAKE_AGENT_HOST` / `FAKE_AGENT_PORT` | `0.0.0.0` / `8083` | Where it listens (kagent's controller port) |
| `FAKE_AGENT_MCP_URL` | unset | Soundings' `/mcp`, like a kagent `RemoteMCPServer`'s URL. Never taken from a message (Soundings' messages carry no URL) |
| `FAKE_AGENT_KEYS` | empty | `<namespace>/<name>=sdg_...` (or `Bearer sdg_...`), comma-separated |
| `FAKE_AGENT_KEYS_DIR` | unset | A directory of files `<namespace>.<name>` holding `Bearer sdg_...` (a mounted Secret, or what a test writes); re-read on every request |
| `FAKE_AGENT_BEHAVIOURS` | empty | `<namespace>/<name>=<behaviour>` to override the name's suffix |
| `FAKE_AGENT_REQUIRE_TOKEN` | unset | Require `Authorization: Bearer <token>` on A2A requests (kagent's `trusted-proxy` mode; Soundings' `SOUNDINGS_KAGENT_TOKEN`) |
| `FAKE_AGENT_BYO` | unset | `<namespace>/<name>`: also serve that agent at `/` (a kagent `type: BYO` Agent's pod; `deploy/kagent/fake-agent-byo.yaml`) |
| `FAKE_AGENT_STEP_DELAY` / `_SLOW_INTERVAL` / `_LATE_DELAY` / `_MCP_TIMEOUT` | `0.3` / `2` / `3` / `30` s | Pause between steps (visible progress), `-slow`'s status interval, `-late`'s wait, each MCP call |

An agent is served only while it has a key; any other `(namespace, name)` answers 404,
like an Agent that doesn't exist. Keys are never logged or returned.

## The surface (kagent v0.10.2's controller, research R2 section 1)

- `POST /api/a2a/{namespace}/{name}/` (with or without the slash, never a redirect):
  A2A JSON-RPC. `A2A-Version` missing or `0.3`: `message/send`, `message/stream`,
  `tasks/get`, `tasks/cancel`, `tasks/resubscribe`; `1.0`: `SendMessage`,
  `SendStreamingMessage`, `GetTask`, `CancelTask`, ...; anything else 400.
- `POST /agents/{namespace}/{name}`: kagent 1.0's layout (pre-release), `A2A-Version: 1.0`
  required (else 400).
- `GET <either>/.well-known/agent-card.json`: a kagent-like card: the name with `-` as
  `_`, JSON-RPC interfaces for 0.3 and 1.0 plus the 0.3 `url` / `protocolVersion` /
  `preferredTransport`, streaming on, push notifications off, a skill per purpose.
- Built on **a2a-sdk 1.2.1**'s server (`DefaultRequestHandler`, `InMemoryTaskStore`, its
  v0.3 compatibility adapter on the same endpoint): streams are `task` (submitted), then
  `status-update`s (working, `final: false`), an `artifact-update`, and the final
  `status-update` (`final: true` in 0.3; 1.0 wraps results in `task` / `statusUpdate` /
  `artifactUpdate` and has no `final`). The SDK's 0.3 adapter answers every A2A error as
  -32603; the fake maps them back to 0.3's codes (-32001 task not found, -32002 not
  cancelable), as kagent-adk's a2a-sdk 0.3 and kagent's a2a-go answer.
- `GET /_fake/observations[/{run_id}]`, `DELETE /_fake/observations`: what it saw, per
  run (below); `GET /healthz`.

## What a run does

The message's `metadata.soundings` (`run_id`, `kind`, `idea`, `section_key`) says what to
do; the text is for a model and is only checked for what must never be in it (a URL or an
API key: `message_checks`). It initialises an MCP session with its key, then makes these
calls, each with the run's id as `run_id` (as the message tells a model to: Soundings binds
every call of an agent to the run it names, c22; the `-late` write names the run that
ended):

| Kind | Calls | Result |
|---|---|---|
| `evaluate` | `get_rubric`, `get_idea`, `submit_evaluation` (`submit: true`) | each criterion scored by its position (3, 4, 5, 1, 2, ...), a rationale starting `fake-rationale:` that names the criterion and the idea, two sources under `https://example.org/fake-agent/...`; recommendation `maybe`; a summary |
| `research` | `get_idea`, `add_research_note` | a short Markdown note with three sources |
| `draft_section` | `get_idea`, `get_proposal`, `propose_proposal_section` | the section's text plus a marked paragraph, with its `base_version`. The section is found by its key in `get_proposal`'s sections, so a section a project added to its template (`carbon_impact`) works like a built-in one; a key that isn't in the proposal saves nothing, and a key not shaped like Soundings' (`^[a-z][a-z0-9_]{0,39}$`) isn't a run |

A tool error ends the task `completed` with a reply saying so (Soundings: `no_result`); an
unreachable MCP server or a refused key ends it `failed`. `fake-rationale` and
`example.org/fake-agent` are there to be searched for: they must never reach a pending
evaluator, a progress event or an error message.

### Behaviours, by the agent name's suffix (or `FAKE_AGENT_BEHAVIOURS`)

| Suffix | Behaviour |
|---|---|
| (none) | the work above, then `completed` |
| `-slow` | reads the idea, then "Still working" every 2 s until cancelled (Soundings cancels at the deadline too) |
| `-lingers` | does its work (the result is recorded), then keeps working like `-slow` |
| `-fails` | `failed` after its first tool call |
| `-silent` | `completed` without calling a tool (`no_result`) |
| `-asks` | `input-required` after reading the idea |
| `-rejects` | `rejected` at once |
| `-blind-probe` | records what `get_idea` and `search_ideas` show of others' scores before and after its work (`blind`), for every kind (rule 9) |
| `-strays` | first tries `add_comment`, `create_idea`, `get_idea` on the next idea number, `propose_proposal_section` for another section and the other kinds' write tools (on a `research` run also `get_proposal` and `get_rubric`, which a research run may not read), then `list_projects` (`ai_run_not_active` on a `research` run) and `search_ideas`, recording each code (`strays`; c22), then works |
| `-late` | works like `-slow`; after its cancel it waits `FAKE_AGENT_LATE_DELAY` and calls its write tool anyway (`late`: Soundings must answer `ai_run_not_active`) |
| `-no-cancel` | like `-slow`, but `tasks/cancel` is answered -32603, as kagent-adk 0.10.2's Python runtime does (`NotImplementedError`) |
| `-unavailable` | HTTP 503 for every request (card included) |
| `-drops` | its stream ends after the task and its first update; the work goes on, so the client must poll `tasks/get` (`historyLength` is recorded) |

Cancel ends every other agent's task `canceled`.

### Observations (`GET /_fake/observations/{run_id}`)

`a2a_requests` (method, `A2A-Version`, `X-User-Id`, whether an `Authorization` header or a
cookie came, `Accept`, `historyLength` of `tasks/get`, `messageId`, whether a `contextId`
was sent, the configuration's keys), `cancel_requests`, `message_checks`, `tool_calls`
(tool, error code, phase), `blind`, `strays`, `late`, `final_state`. Never keys, tokens,
message text or tool results beyond codes and flags. `e2e/scripts/fake-agent.ts` reads
them from specs; `scripts/k3s-fake-agent.sh observations RUN_ID` in k3s.

## Verified against what

| What | Against | Result |
|---|---|---|
| 0.3 and 1.0 wire shapes, streaming order, `final`, `tasks/get` `historyLength`, cancel, error codes | its own tests (raw JSON-RPC over real sockets) and **a2a-sdk 0.3.23's client** (what kagent-adk 0.10.2 is built on; `compat/a2a_0_3_client.py`, run by the tests in an isolated uv environment): card resolution, a streamed run, `tasks/get`, `tasks/cancel` | pass |
| Soundings' worker, API, SSE and `/mcp` end to end | `scripts/ai-smoke.sh` against the e2e stack (`E2E_AI=1`, both protocols), `make demo DEMO_AI=1`, and k3s (`make k3s-smoke AI=1`: through Traefik, with the chart's NetworkPolicies and egress rules, one and two API replicas); every behaviour above against the real backend (outcomes, retries on 503, the deadline, cancel, a cancel answered -32603, c22 refusals, rule 9, a dropped stream polled with `tasks/get` `historyLength: 1`) | pass (2026-10-06) |
| kagent's controller in front of it (proxying, its task store, its 1.0-to-0.3 translation, `X-User-Id` sessions) | **not verified**: no kagent controller runs here (pulling kagent's 0.10.2 chart from `oci://ghcr.io` fails: its blobs are served from `pkg-containers.githubusercontent.com`, which this network's egress policy refuses, and ghcr's image layers come from there too). `deploy/kagent/fake-agent-byo.yaml` runs the fake as a BYO Agent behind a real controller when you have one |
| An LLM following Soundings' run message | **not verified**: there is no model; Soundings enforces what matters server-side regardless |
