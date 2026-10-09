# kagent integration

Soundings uses [kagent](https://kagent.dev) for its two AI jobs (SPEC.md section 9): an
**AI evaluator** ("Ask AI to evaluate": a cited evaluation, shown with an AI badge and
left out of the aggregate unless the idea's owner includes it) and a **research and
drafting assistant** ("Ask AI to research": a cited research note in the activity feed;
"Draft section": proposal text the owner accepts or discards). The worker starts each run
at kagent's controller over A2A; the agent does the work through Soundings' MCP server
(`/mcp`) as its own service account. Contract: `docs/api/contract-phase6.md`; design: ADR
0014.

## How it fits together

```
person ──"Ask AI to evaluate"──► Soundings API ──run row + job──► worker (ai pool)
                                                                      │ A2A message/stream (0.3) or
                                                                      │ SendStreamingMessage (1.0)
                                                                      ▼
            kagent controller  http://kagent-controller.kagent:8083/api/a2a/<namespace>/<name>/
                                                                      │ proxies to the agent pod
                                                                      ▼
            kagent Agent <namespace>/<name> ──MCP, Bearer <its key>──► Soundings /mcp
              get_rubric, get_idea, submit_evaluation / add_research_note / propose_proposal_section
```

- **URLs are built, never given:** `SOUNDINGS_KAGENT_URL` (Helm `kagent.controllerUrl`) +
  a fixed path per protocol + the agent's namespace and name (DNS labels). Nothing in the
  UI, a message or an agent card can make Soundings call another host. Runs don't read the
  card; Test connection shows it.
- **One key per agent**, created when a platform admin registers the agent (Admin settings
  > AI agents), shown once with a Secret manifest. It works **only on `/mcp` and only
  during the agent's runs** (c22): **every call names its run** (`run_id`, which the
  run's message gives the model, as do the example agents' system messages) and reaches
  only that run's idea, writing only the run's result. So two runs of one agent open at
  once can't reach each other, a task that outlives its run (kagent's Python runtime
  can't cancel) can't act through a newer one, and outside a run the key does nothing:
  someone talking to the agent directly in kagent's UI can't use it for anything else.
  Agents never see other evaluators' scores, and their own only in an evaluate run
  (rule 9).
- **Results come back through MCP**, matched to the run by the server: A2A text and
  artifacts are ignored. The run's message holds the run id, kind, idea key, section and
  the agent's name: no URL, key or idea text.

## Files here

| File | What |
|---|---|
| `agents.yaml` | The two agents by hand for kagent 0.10 (`kagent.dev/v1alpha2`) in namespace `soundings`: a `ModelConfig`, and for `idea-evaluator` and `idea-researcher` each a placeholder key Secret (the manifest registration shows replaces it), a `RemoteMCPServer` reading it and a Declarative, streaming `Agent` with its tools, skills and standing rules |
| `fake-agent-byo.yaml` | Soundings' deterministic fake agent (`dev/fake-agent`) as a `type: BYO` Agent: for a test cluster with kagent but no model, so kagent's real controller carries Soundings' runs |
| `remote-mcp-server.yaml` | Phase 5: a shared `RemoteMCPServer` in kagent's namespace with one key (a person's key for their own kagent agents; an AI agent's key only works in its runs) |
| Helm `kagent.*`, `ai.*` | `deploy/helm/README.md` "AI assistance (kagent)": `features.ai`, `kagent.controllerUrl`, the token Secret, `kagent.agentNamespaces`, `ai.runTimeout` / `.maxConcurrentRuns` / `.defaultProtocol`, NetworkPolicies, and `kagent.examples` rendering the same two agents (`<fullname>-evaluator`, `<fullname>-researcher`) with one `RemoteMCPServer` each |

## Set it up (kagent 0.10.x)

```sh
# 1. Soundings with AI on (the chart admits kagent's namespace and its agent pods to /mcp)
helm upgrade soundings ./deploy/helm -n soundings --reuse-values \
  --set features.ai=true --set kagent.enabled=true
# 2. A ModelConfig in the release namespace (or use an existing one)
kubectl -n soundings create secret generic anthropic-api-key --from-literal=api-key=...
# 3. In Soundings: Admin settings > AI agents > Register agent, e.g. "Idea evaluator",
#    namespace soundings, name soundings-evaluator, purpose Evaluate, its projects. Copy
#    the Secret manifest it shows once and apply it:
kubectl apply -f -        # paste: Secret soundings-agent-soundings-evaluator
# 4. The agents: with the chart's examples (their RemoteMCPServers read exactly that Secret)
helm upgrade soundings ./deploy/helm -n soundings --reuse-values \
  --set kagent.examples=true --set kagent.agents.modelConfig=soundings-model
#    or by hand: edit and apply deploy/kagent/agents.yaml (names idea-evaluator/-researcher)
# 5. Back in Soundings: Test connection (the card, A2A versions, skills), then on an idea
#    "Ask AI to evaluate". Rotate key / Disable live on the same page.
```

- **Namespaces:** agents may be registered only in `kagent.agentNamespaces` (default: the
  release namespace, so nobody can point a run at kagent's built-in agents). Outside the
  chart, `SOUNDINGS_AI_AGENT_NAMESPACES` defaults to `soundings` (never "any"). kagent's agent
  pods call `/mcp` from their own namespace: with `networkPolicy.ingressFrom` set, the
  chart admits pods labelled `app.kubernetes.io/managed-by: kagent` there.
- **Egress:** with `networkPolicy.egress.enabled`, the api (Test connection) and the worker
  (runs) may reach kagent's controller port (`networkPolicy.egress.kagent.to` narrows the
  peers).
- **kagent's auth:** its default `--auth-mode=unsecure` trusts any caller; for
  `trusted-proxy`, put a bearer token in a Secret and set `kagent.existingTokenSecret`.
  Keep kagent's UI and A2A endpoint inside the cluster: whoever can message an agent while
  one of its runs is open could steer that run (contract-phase6 section 3.1 "Reach").
- **Protocols:** `kagent_v0_10` (A2A 0.3 at `/api/a2a/<ns>/<name>/`, the default and what
  kagent-adk 0.10.2 speaks) or `kagent_v1_0` (A2A 1.0 at `/agents/<ns>/<name>` with
  `A2A-Version: 1.0`, for kagent 1.0, unreleased), per agent.
- **Cancel:** kagent's Python runtime can't cancel (it answers an error); the Go runtime,
  which the CRD defaults to, can. Soundings ends the run either way, and the agent's key
  stops working on it at once.
- **What kagent keeps:** kagent stores each run's session (the message and every tool
  result: the idea's text, its comments, the rubric) under its caller `X-User-Id:
  soundings`, in its own database. Soundings' idea deletion, submitter erasure and
  retention don't reach it: set kagent's own retention, or clear those sessions, to match
  (assumed from kagent's design; no live controller here).

## What is verified (2026-10-06)

| Check | How | Result |
|---|---|---|
| Every manifest here and the chart's `kagent.examples` resources against kagent **v0.10.2**'s CRDs (`agents.kagent.dev` v1alpha2 storage, `remotemcpservers.kagent.dev` v1alpha2, `modelconfigs.kagent.dev` v1alpha2; OpenAPI schemas and CEL rules) | `make k3s-kagent-crds`: the CRD files of git tag `v0.10.2` (commit 68df64f, `helm/kagent-crds/templates`, what the kagent-crds chart packages) applied to k3s v1.31, then `kubectl apply --dry-run=server` of each file and of `helm template --set kagent.examples=true` | accepted (again at the final verification, with the system messages that ask for `run_id`); the API server defaulted `runtime: go` on the Agents and `terminateOnClose: true` on the RemoteMCPServers; a `secretKeyRef` header and an Agent without `declarative` are refused (so the schema really applied) |
| The chart's example Agents and RemoteMCPServers created for real (they're only CRs without a controller) | `make k3s-install AI=1` with the CRDs installed (adds `kagent.examples`) | created, listed by `make k3s-smoke AI=1` |
| The A2A loop: Test connection, runs streamed and cancelled, results through `/mcp`, SSE to a pending evaluator | Soundings' **fake agent** (`dev/fake-agent`) in kagent's place: `scripts/ai-smoke.sh` against the e2e stack (`E2E_AI=1`; A2A 0.3 and 1.0), `make demo DEMO_AI=1`, and in k3s as `kagent/kagent-controller:8083` with the default `controllerUrl`, through Traefik, behind the chart's NetworkPolicies (agent pods admitted by label, others dropped; the worker's egress only to DNS, Postgres and 8083), with one and two API replicas (`make k3s-smoke AI=1`, also with `MCP=1`) | pass (2026-10-06; integration repeated `make k3s-install AI=1 MCP=1` + `k3s-smoke AI=1 MCP=1` with the real `make image`; the final verification ran it as CI, `SSO=1 SMTP=1 MCP=1 AI=1`, on one and then two API replicas, after the `run_id` change) |
| The fake agent's 0.3 wire format | a2a-sdk **0.3.23**'s own client (kagent-adk 0.10.2's A2A library) against it: card, stream, `tasks/get`, `tasks/cancel` | pass |
| kagent's MCP client (go-sdk v1.6.1) against `/mcp` | Phase 5 | pass |

**Not verified:** a live kagent controller and an LLM. kagent's 0.10.2 chart can't be
pulled here (`oci://ghcr.io/kagent-dev/kagent/helm/...`: the manifest answers, the blob
host `pkg-containers.githubusercontent.com` is refused by this network), so the
controller's proxying to agent pods, its task store for `tasks/get`, its translation of
1.0 requests to the 0.3 pods, header resolution of `RemoteMCPServer` `headersFrom` and an
Agent's tool-level `headersFrom`, and a model following the run message are known from
kagent's source and docs only. `fake-agent-byo.yaml` is the way to check the controller
part on a cluster that has kagent. kagent **1.0** (pre-release) moves to
`api.kagent.dev/v1alpha3` and new Agent kinds: these manifests are for 0.10.x.

Inspect what is installed before changing anything (SPEC.md section 9):

```sh
kubectl get crd | grep kagent           # agents.kagent.dev: 0.10; agents.api.kagent.dev: 1.0
kubectl explain agents.spec.declarative --api-version=kagent.dev/v1alpha2
kubectl -n soundings get agents,rmcps
```
