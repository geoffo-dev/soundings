# Research R2: kagent, A2A, Claude Code config, frontend versions (2026-09-30)

> Phase 0 research by a researcher subagent, lightly edited by the lead. Tags:
> **[src]** read in upstream source · **[run]** the researcher ran it · **[doc]** quoted
> from code.claude.com on 2026-09-30 · **[inf]** inferred, not tested. There was no
> live kagent install, so the kagent endpoint layout is verified from source only.
> Re-verify against the installed cluster before Phase 6 (SPEC section 9).

Main risks for later phases:

- **kagent is mid-rewrite.** The stable line is v0.10.2, but its main branch changes the
  API group, the Agent spec, the A2A path and the protocol version.
- **TypeScript 7 breaks our lint and codegen tools**, so we pin TypeScript 5.9.x.
- **The `TaskCompleted` hook input doesn't say which files a task touched**, so the
  check script has to infer the area (from `teammate_name` or the working tree).

## 1. kagent (github.com/kagent-dev/kagent)

**Versions [src].**

- Latest stable is **v0.10.2** (tagged 2026-09-21). PyPI `kagent-adk` and `kagent-core`
  are also 0.10.2.
- There are pre-releases v1.0.0-alpha1 to alpha5 (alpha5 is from 2026-09-27), and main
  has moved to that line.
- The 1.0 line breaks things:
  - API group becomes `api.kagent.dev/v1alpha3`.
  - Agent kinds become `Agent`, `AgentTemplate`, `Harness` and `SandboxTemplate`.
    `ToolServer` and `Memory` are removed.
  - A2A moves to `/agents/{ns}/{name}` and requires the `A2A-Version: 1.0` header.
- To tell which is installed: 0.10 has `agents.kagent.dev`; 1.0 has
  `agents.api.kagent.dev`.

**CRDs in v0.10.2 (group `kagent.dev`) [src, and applied to a throwaway k3s].**

| Kind | Versions (* = storage) |
|---|---|
| `Agent` | v1alpha1, v1alpha2* |
| `ModelConfig` (`mc`) | v1alpha1, v1alpha2* |
| `ModelProviderConfig` | v1alpha2 |
| `RemoteMCPServer` (`rmcps`) | v1alpha2 |
| `ToolServer` (`ts`, legacy) | v1alpha1 |
| `Memory` | v1alpha1 |
| `AgentHarness` | v1alpha2 |
| `SandboxAgent` | v1alpha2 |

- `MCPServer` is `kagent.dev/v1alpha1` from the bundled kmcp v0.3.0 subchart. We don't
  need it.
- `RemoteMCPServer` protocol is `SSE` or `STREAMABLE_HTTP` (the default). The default
  timeout is 30s.
- **Phase 5 [run, v0.10.2 CRD on k3s]:** `RemoteMCPServer.spec` also has
  `allowedNamespaces` (which other namespaces' Agents may reference it) and `tls`, and
  defaults `terminateOnClose: true`; the header is always read from the RemoteMCPServer's
  own namespace. kagent's source labels agent pods `app.kubernetes.io/managed-by:
  kagent`. Its MCP client (`go-sdk` v1.6.1) worked against Soundings' `/mcp`
  (initialize `2025-11-25`, its SSE `GET` gets 405 and is skipped, `DELETE` 405 ignored).
  Keys are `sdg_…`, not the `sk_soundings_…` placeholder below: see
  `deploy/kagent/README.md`.

**Minimal manifest [run].** The API server accepted this with v0.10.2 CRDs and their
validation rules, and defaulted `runtime` to `go`:

```yaml
apiVersion: v1
kind: Secret
metadata: {name: soundings-mcp-key, namespace: soundings}
stringData: {authorization: "Bearer sk_soundings_REPLACE_ME"}   # value is sent as-is
---
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata: {name: soundings-model, namespace: soundings}
spec: {provider: Anthropic, model: claude-sonnet-4-5, apiKeySecret: anthropic-api-key, apiKeySecretKey: api-key}
---
apiVersion: kagent.dev/v1alpha2
kind: RemoteMCPServer
metadata: {name: soundings-mcp, namespace: soundings}
spec:
  description: Soundings MCP server
  protocol: STREAMABLE_HTTP
  url: http://soundings.soundings.svc:8000/mcp
  timeout: 30s
  headersFrom:
    - name: Authorization
      valueFrom: {type: Secret, name: soundings-mcp-key, key: authorization}
---
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata: {name: idea-evaluator, namespace: soundings}
spec:
  type: Declarative
  description: Evaluates a Soundings idea and submits a cited evaluation.
  declarative:
    modelConfig: soundings-model
    stream: true
    systemMessage: "Use get_idea/get_rubric, then call submit_evaluation once with score, rationale and sources per criterion."
    tools:
      - type: McpServer
        mcpServer: {apiGroup: kagent.dev, kind: RemoteMCPServer, name: soundings-mcp,
                    toolNames: [get_idea, get_rubric, search_ideas, submit_evaluation]}
    a2aConfig: {skills: [{id: evaluate-idea, name: Evaluate idea, tags: [soundings]}]}
```

**Gotchas.**

- `valueFrom` takes `{type, name, key}`. The `secretKeyRef` form in kagent's own skill
  doc is rejected with `strict decoding error: unknown field
  "spec.headersFrom[0].valueFrom.secretKeyRef"` [run].
- A tool entry's `headersFrom` overrides the server's headers of the same name.
  `mcpServer.allowedHeaders` passes headers from the A2A request through to MCP calls
  [src comment; not tested].
- The CRD defaults `runtime` to `go`. The Go runtime implements cancel (the task ends
  `canceled`). The Python runtime raises `NotImplementedError` on cancel [src].
- 0.10 has no output schema, so the agent must report through our `submit_evaluation`
  MCP tool, which matches SPEC section 9.
- Agent readiness shows as the `Accepted` and `Ready` conditions.

**How agents are exposed over A2A [src: `httpserver/server.go`, `a2a/a2a_registrar.go`,
`a2a_handler_mux.go`, `utils/a2a_version.go`].**

- **Service:** the controller serves HTTP on port 8083 behind the
  `<release>-controller` Service. The route is `PathPrefix /api/a2a/{namespace}/{name}`
  (sandboxed agents use `/api/a2a-sandboxes/…`).
- **Advertised URL:** `A2A_BASE_URL + /api/a2a/{ns}/{name}/`. The Helm default base is
  `http://{release}-controller.{ns}.svc:8083`, so for us it is
  `http://kagent-controller.kagent.svc:8083/api/a2a/soundings/idea-evaluator/` (note
  the trailing slash).
- **Agent card:** `GET {url}.well-known/agent-card.json`; any path ending in that suffix
  works.
  - The card combines 1.0 and 0.3 fields: `supportedInterfaces` lists JSON-RPC for both
    "0.3" and "1.0", plus the older `url`, `protocolVersion` and `preferredTransport`
    fields.
  - The card name is the agent name with `-` changed to `_`. Streaming is on; push
    notifications are off.
- **Methods:** all calls are `POST {url}`. The `A2A-Version` header picks the method
  names:
  - Missing or `0.3`: `message/send`, `message/stream`, `tasks/get`, `tasks/cancel`,
    `tasks/resubscribe`, and `tasks/list` (served from kagent's store).
  - `1.0`: `SendMessage`, `SendStreamingMessage`, `GetTask`, `CancelTask`,
    `SubscribeToTask`, `ListTasks`.
  - Any other value returns 400.
- **Where calls go:** `GetTask` is answered from kagent's database. Everything else is
  proxied to the agent pod at `http://{agent}.{ns}:8080`.
- **Auth:** the default is `--auth-mode=unsecure`. The caller's identity comes from
  `?user_id=` or the `X-User-Id` header (default `admin@kagent.dev`), and
  `Authorization` is forwarded to the pod. In `trusted-proxy` mode a `Bearer <JWT>` is
  required (claims are parsed, not validated). **Send `X-User-Id` always, and a
  configurable `Authorization`.**
- **Timeouts:** the controller's HTTP server sets none, and `KAGENT_A2A_CLIENT_TIMEOUT`
  (controller to pod) defaults to 0. Long SSE streams are fine, so our worker owns the
  deadline.
- **Sessions:** kagent treats `contextId` as its session id. Leave it out to get a
  fresh session for each run.

**Wire shapes [run].** Captured from an a2a-sdk 1.2.1 server serving a kagent-identical
card. kagent's a2a-go v2.3.1 implements the same spec; its method names and error codes
were checked in source.

- **0.3 request:** `{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"kind":"message","messageId":"m1","role":"user","parts":[{"kind":"text","text":"…"}],"contextId":"(optional)"},"configuration":{"blocking":true}}}`
  - The result is a Task: `{"kind":"task","id","contextId","status":{"state":"completed","timestamp"},"artifacts":[{"artifactId","name","parts":[{"kind":"text","text"}]}],"history":[…]}`.
  - `message/stream` sends SSE lines of the form `data: {"jsonrpc","id","result":…}`.
    Results come in order: `task` (submitted), then `status-update`
    (`"state":"working","final":false`), then `artifact-update` (`append`,
    `lastChunk`), then `status-update` with `"final":true`.
  - `tasks/get` and `tasks/cancel` take params `{"id":…}`.
- **1.0 request:** `{"method":"SendMessage","params":{"message":{"messageId","role":"ROLE_USER","parts":[{"text":"…"}]},"configuration":{}}}`.
  - The result is `{"task":{…,"status":{"state":"TASK_STATE_COMPLETED"}}}` or
    `{"message":…}`.
  - Stream results are wrapped in `{"task"|"statusUpdate"|"artifactUpdate"|"message":…}`.
    There is **no `final` flag**: the stream ends at `COMPLETED`, `FAILED`, `CANCELED`
    or `REJECTED` (or pauses at `INPUT_REQUIRED` / `AUTH_REQUIRED`).
- **Error codes:** -32001 TaskNotFound, -32002 TaskNotCancelable, -32004
  UnsupportedOperation.

**Not verified:** a live kagent install. The chart
`oci://ghcr.io/kagent-dev/kagent/helm/kagent:0.10.2` is pullable (the manifest request
returned 200), and its images default to ghcr.io. k3s will need a `registries.yaml`
entry for ghcr.io that trusts the proxy CA.

## 2. A2A Python client: `a2a-sdk`

- **Package:** `a2a-sdk` **1.2.1** (released on PyPI 2026-09-30), Python >=3.10. Its
  types are protobuf (`a2a.types.a2a_pb2`).
- **Install:** the client needs no extras. Base dependencies are httpx, protobuf,
  pydantic, google-api-core/google-auth, json-rpc and culsans, about **43 MB**. Don't
  add the `postgresql`/`sql` extras, which pull in asyncpg. `[http-server]` is only
  needed as a dev dependency for a fake agent in tests.
- **Protocol version:** it sends `A2A-Version: 1.0` by default and prefers the 1.0
  interface on the card. It falls back to the 0.3 transport automatically, and sets
  `A2A-Version: 0.3` on those requests [run]. That covers kagent 0.10 and 1.0.
- **Tested [run]:** blocking send, get, stream, cancel (the stream then ended
  `TASK_STATE_CANCELED`) and a per-call timeout (raised `A2AClientTimeoutError`).

```python
import asyncio, uuid, httpx
from a2a.client import ClientCallContext, ClientConfig, ClientFactory, A2AClientError, A2AClientTimeoutError
from a2a.types.a2a_pb2 import CancelTaskRequest, GetTaskRequest, Message, Part, Role, SendMessageRequest, TaskState

async def run(agent_url: str, text: str, headers: dict[str, str], total_s: float) -> None:
    http = httpx.AsyncClient(headers=headers,  # e.g. {"X-User-Id": "soundings", "Authorization": "Bearer …"}
                             timeout=httpx.Timeout(10.0, read=120.0))  # read = max gap between SSE events
    client = await ClientFactory(ClientConfig(streaming=True, httpx_client=http)).create_from_url(agent_url)
    msg = Message(role=Role.ROLE_USER, message_id=str(uuid.uuid4()), parts=[Part(text=text)])
    task_id: str | None = None
    try:
        async with asyncio.timeout(total_s):          # overall deadline (httpx timeouts are per phase)
            async for ev in client.send_message(SendMessageRequest(message=msg)):
                kind = ev.WhichOneof("payload")       # task | message | status_update | artifact_update
                if kind == "task": task_id = ev.task.id
                elif kind == "status_update":
                    task_id = ev.status_update.task_id
                    state = TaskState.Name(ev.status_update.status.state)   # push to our SSE
                elif kind == "artifact_update":
                    texts = [p.text for p in ev.artifact_update.artifact.parts]
    except TimeoutError:
        if task_id:  # best effort: the Python runtime can't cancel
            await client.cancel_task(CancelTaskRequest(id=task_id), context=ClientCallContext(timeout=10))
    finally:
        await client.close()                          # also closes the httpx client
```

- **Other calls:** `await client.get_task(GetTaskRequest(id=…))`. Turning streaming off
  (`ClientConfig(streaming=False)`) gives a blocking send that yields a single event.
- **Timeouts:** `ClientCallContext(timeout=s)` becomes `httpx.Timeout(s)` for that one
  call. It is not a total deadline.
- **Auth:** headers can also be set per call with
  `ClientCallContext(service_parameters={"Authorization": …})`.
- **Alternative:** if 43 MB is too much, a hand-written httpx JSON-RPC client of about
  80 lines speaking 1.0 would work, but it loses the 0.3 fallback. **Recommendation:
  a2a-sdk**, because the protocol is changing right now and the same package gives us
  the fake-agent test fixture.

## 3. Claude Code project configuration (docs verified; CLI 2.1.285 installed)

The lead re-read the hooks, settings, permissions, sub-agents and agent-teams pages on
2026-09-30 before writing `.claude/settings.json`; the facts below still hold.

**Settings and env [doc].**

- Settings files are strict JSON; `$schema` is
  `https://json.schemastore.org/claude-code-settings.json`.
- "Agent teams are disabled by default. Enable them by setting the
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` environment variable to `1`, either in your
  shell environment or through settings.json", i.e.
  `"env": {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"}`.
- Project `env` values and `permissions.allow` rules apply only after the workspace
  trust dialog is accepted, or at startup in `-p` mode. `deny` and `ask` rules apply
  right away.

**Permissions [doc].**

- Rules are checked "in order: deny, then ask, then allow". "A `*` in a Bash rule
  matches any text, including spaces".
- "A `*` at the end, with a space before it, also matches the bare command."
- "a rule like `Bash(safe-cmd *)` won't give it permission to run the command
  `safe-cmd && other-cmd`". `timeout`, `nice` and similar wrappers are stripped before
  matching.
- Claude Code "warns at startup about an allow rule with a `*` before the subcommand".
- Environment runners (`docker exec`, `npx`, `devbox run`, …) are **not** stripped: a
  rule like `Bash(docker exec *)` approves whatever follows. Write one rule per runner
  plus inner command, e.g. `Bash(docker exec soundings-k3s kubectl *)`.
- Consequence: don't add an `ask` rule for bare `kubectl`, because ask would beat the
  context-scoped allow.

**`TaskCompleted` hook [doc].**

- The event exists. It runs "when any agent explicitly marks a task as completed
  through the TaskUpdate tool, or when an agent team teammate finishes its turn with
  in-progress tasks". It supports no matcher.
- **Input:** the common fields (`session_id`, `transcript_path`, `cwd`,
  `permission_mode`, `hook_event_name`) plus `task_id`, `task_subject`, and optionally
  `task_description`, `teammate_name` and `team_name` (deprecated).
- **It has no list of touched files.** Either map `teammate_name` to a make target (so
  teammates must be spawned with names that match their agent types) or infer the area
  from the working tree.
- **Exit 2:** "the task is not marked as completed and the stderr message is fed back
  to the model as feedback."
- `{"continue": false, "stopReason": …}` stops a teammate, but is ignored when the
  TaskUpdate tool triggered the event.
- The default command-hook `timeout` is 600 seconds; set it per hook if the checks take
  longer.
- Placeholder: `${CLAUDE_PROJECT_DIR}`. "Prefer exec form" (`args`) whenever a hook
  references a path placeholder.
- `TeammateIdle` (exit 2 keeps the teammate working) and `TaskCreated` (exit 2 rolls
  the task back) work the same way.

The adopted configuration is `.claude/settings.json` in the repo; `CLAUDE.md` explains
it. Helm and kubectl run through Docker here, so they are wrapped in make targets that
`Bash(make *)` covers. `jq` is installed at `/usr/bin/jq`.

**Agent teams [doc].**

- Claude "launches a teammate when it calls the Agent tool with a `name` while agent
  teams are enabled". Named subagents therefore become teammates; researchers should be
  spawned unnamed.
- Other constraints:
  - One team per session.
  - Teammates can't spawn teammates.
  - An in-process teammate can't run background subagents.
  - Teammates start with the lead's permission mode (except `dontAsk`), and their
    permission prompts appear in the lead session.
- **Subagent definitions as teammate types:** yes. "reference a subagent type from the
  project, user, or managed subagent scope", e.g. "Spawn a teammate using the
  security-reviewer agent type". A teammate gets:
  - the definition's `tools` (plus `SendMessage` and the Task tools),
  - its `model`,
  - its body (appended to the prompt for in-process teammates; replaces it for
    split-pane teammates).
  - **`skills` is not applied**, and `mcpServers` only applies to split-pane teammates.

**Subagent frontmatter [doc].**

- "Only `name` and `description` are required."
- Optional fields: `tools`, `disallowedTools`, `model`
  (`sonnet|opus|haiku|fable|<full id>|inherit`), `permissionMode`, `maxTurns`, `skills`,
  `mcpServers`, `hooks`, `memory`, `background`, `omitClaudeMd`, `effort`,
  `isolation: worktree`, `color`, `initialPrompt`, `experimental.cacheTtl`.
- Unknown fields are silently ignored, and names can't contain `:`.

## 4. Frontend versions and React 19 pitfalls

The whole stack below installed with npm 10 without any conflict. `tsc --strict` passed
on smoke code that uses every library, and `vite build` succeeded [run].

| Package | Version | Note |
|---|---|---|
| react, react-dom, @types/react(-dom) | 19.3.0 | |
| vite / @vitejs/plugin-react | 8.3.1 / 6.1.1 | Vite 8 uses Rolldown; plugin-react 6 requires `vite ^8`. `build.rollupOptions` still works. |
| tailwindcss / @tailwindcss/vite | 4.3.3 / 4.3.3 | Configure in CSS: `@import "tailwindcss"; @theme {…}` |
| @tanstack/react-router / router-plugin | 1.170.40 / 1.168.41 | Put `tanstackRouter({target:"react",autoCodeSplitting:true})` before `react()` |
| @tanstack/react-query / react-virtual | 5.104.0 / 3.14.13 | react-hooks 7 warns `incompatible-library` on `useVirtualizer` |
| cmdk / sonner / lucide-react | 1.1.1 / 2.0.8 / 1.49.0 | lucide is now at 1.x |
| radix-ui (unified) | 1.6.7 | `import { Dialog, DropdownMenu } from "radix-ui"`: one version, only used primitives get bundled. Prefer it over separate `@radix-ui/react-*` packages. |
| openapi-typescript / openapi-fetch | 7.13.0 / 0.17.0 | generated a client fine with TS 5.9.3 |
| msw | 3.0.1 | **3.0.0 was 2 days old.** Core imports unchanged (`http`, `HttpResponse`, `msw/browser`, `msw/node`). Safer pin: 2.15.0 (the repo uses it). |
| @playwright/test / @axe-core/playwright | **1.56.1** / 4.13.0 | 1.56.0 and 1.56.1 use chromium-1194 (141.0.7390.37). 1.57 uses 1200; latest 1.63 uses 1243. 1.56.1 plus axe ran against `/opt/pw-browsers` [run]. |
| react-markdown / remark-gfm | 10.1.0 / 4.0.1 | |
| altcha | 3.2.4 | See below |
| @dnd-kit/core / sortable / utilities | 6.3.1 / 10.0.0 / 3.2.2 | Last published Dec 2024 but works on React 19. See below. Avoid `@dnd-kit/react` 0.5 (pre-1.0). |
| @fontsource-variable/inter | 5.3.0 | `import "@fontsource-variable/inter"` bundles the woff2 files; family name is `"Inter Variable"` |
| typescript | **pin 5.9.3** | See pitfalls |
| vitest / jsdom / eslint / typescript-eslint | 5.0.3 / 30.1.1 / 10.11.0 / 8.71.0 | Flat config with `strictTypeChecked` and react-hooks 7.1.1 works |

**altcha:** the widget registers `<altcha-widget>`, and React JSX typing comes from
`import type {} from "altcha/types/react"`. The default algorithm is PBKDF2/SHA-256 and
its only dependency is hash-wasm. It makes no network calls; the altcha.org link is
attribution you can remove with `hideFooter` / `hideLogo`. The server side is PyPI
`altcha` 2.1.0 (`create_challenge` / `verify_solution` use the v2 API that matches
widget 3).

**Drag and drop:** use `KeyboardSensor` with `sortableKeyboardCoordinates` for keyboard
moves; screen-reader announcements are built in and set through
`accessibility.announcements`.

**Pitfalls.**

- **TypeScript 7.0.2 is npm `latest`, but it only exports `version.cjs` and `unstable/*`
  (no compiler API).** `typescript-eslint` needs typescript `>=4.8.4 <6.1.0` and
  `openapi-typescript` needs `^5.x`, and npm reports both conflicts [run]. Pin
  **5.9.3**.
- **Node versions:** jsdom 30 needs Node ^22.22.2, vitest 5 needs ^22.12 and eslint 10
  needs ^22.13. Local Node is 22.22.2 and the `node:22-alpine` image has 22.23.3, so
  both are fine.

**Proposal editor recommendation.** Measured Vite 8 gzip sizes [run]:

- `<textarea>` with a react-markdown preview: about 0 KB extra (react-markdown and
  remark-gfm, about 46 KB gzip, are shared and needed anyway).
- CodeMirror 6 (view, state, commands, lang-markdown): **+172 KB**, because
  lang-markdown statically pulls in the HTML, CSS and JS language modes.
- `@uiw/react-md-editor` 4.1.2: **+361 KB** plus 6 KB of CSS (Prism highlighting and
  its own preview renderer).

**Recommendation: one auto-growing native `<textarea>` per template section, with a
Write/Preview toggle** (react-markdown), a small toolbar that uses `setRangeText`, and
the fixed template sections as the outline. Margin comments attach to a section id. It
needs no new dependency and has the best accessibility (native spellcheck, input
methods, mobile and screen readers). See the
[proposal editor wireframe](../wireframes/05-proposal-editor.md).

- If highlighting is wanted later, lazy-load CodeMirror 6, and turn spellcheck back on:
  CodeMirror sets `spellcheck="false"` and `autocorrect="off"` by default, so override
  them with `EditorView.contentAttributes` [src].
- Avoid `@uiw/react-md-editor`.

## Open items from this research

- **Not verified:** a live kagent end-to-end run, the 1.0-protocol path through a real
  controller, and the `TaskCompleted` hook actually running inside a Claude team
  session.
- Four anonymous Docker volumes left behind by the researcher's throwaway k3s container
  (created 2026-09-30T13:38:57Z) may need removing by hand with `docker volume rm`.
