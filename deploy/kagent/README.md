# kagent integration

Soundings uses [kagent](https://kagent.dev) for its two AI jobs (SPEC.md section 9): an
AI evaluator and a research and drafting assistant. Agents work through Soundings' MCP
server at `/mcp` (Phase 5) with a service account's API key, under the same
authorisation as people: blind evaluation, the key's project restriction and scopes,
every call audited. Phase 6 adds the agents themselves, their UI and the worker starting
runs over A2A.

## What is here (Phase 5)

| File | What |
|---|---|
| `remote-mcp-server.yaml` | A Secret with the agents' key and a `RemoteMCPServer` in kagent's namespace pointing at the release's Service, to apply by hand (`kubectl apply -f`) |
| Helm `kagent.*` values | `kagent.enabled` admits kagent's namespace to the API through the chart's NetworkPolicy (when `networkPolicy.ingressFrom` restricts it); `kagent.examples` also renders the same `RemoteMCPServer` (`<fullname>-mcp`) in the release namespace, with `kagent.mcp.keySecret` / `.keySecretKey` / `.timeout`. Both off by default. |

```sh
# With the chart: an existing Secret holding the whole header value
kubectl -n soundings create secret generic soundings-agent-key \
  --from-literal=authorization="Bearer sdg_..."
helm upgrade soundings ./deploy/helm -n soundings --reuse-values \
  --set kagent.enabled=true --set kagent.examples=true \
  --set kagent.mcp.keySecret=soundings-agent-key
kubectl -n soundings get rmcps        # kagent's controller lists the tools into its status
```

Agents in the release namespace reference it as `soundings-mcp` (`kind:
RemoteMCPServer`, `apiGroup: kagent.dev`); agents in `kagent.namespace` add `namespace:
<release namespace>` (the chart sets `allowedNamespaces` for that namespace). The header
is always read from the RemoteMCPServer's own namespace.

### The agents' key

- **A service account's key, created by a platform admin** (Phase 6: Admin → AI agents;
  until then through the service layer). Scopes `read`, `evaluate`, `mcp`, plus `write`
  for proposal suggestions and comments. **Restrict it to the projects the agents
  serve** (contract-phase5 section 3.7: text planted in one project must not lead an
  agent to read another and copy it back). Service accounts' keys never pause for
  inactivity; revoking the key (or deactivating the account) cuts the agents off at
  their next call.
- **kagent sends the Secret's value as is**, so it must be `Bearer sdg_...`, not the bare
  key. `valueFrom` takes `{type: Secret, name, key}`; the `secretKeyRef` form is rejected
  by the CRD.
- The key never goes in Helm values: it is shown once in Soundings, and only the
  operator's Secret holds it.

### Network

- The URL is the Service (`http://<fullname>.<namespace>.svc.cluster.local:<port>/mcp`),
  not a public base URL: `/mcp` is exempt from the app's Host check, so in-cluster
  callers need not be listed in `baseUrls`. An `Origin` header, if a client sends one,
  must still be a base URL's origin.
- With `networkPolicy.ingressFrom` set, `kagent.enabled` adds kagent's namespace (the
  controller lists tools from there; agents created there call them). **Agents in any
  other namespace need their namespace in `networkPolicy.ingressFrom`.** kagent 0.10
  labels agent pods `app.kubernetes.io/managed-by: kagent` (from its source), if you
  prefer a narrower `podSelector` peer.
- `/mcp` answers short JSON responses: no SSE stream, so nothing to tune for buffering;
  kagent's `timeout` (30 s) bounds each call.
- Phase 6: with `networkPolicy.egress.enabled`, the worker will also need egress to
  kagent's controller (A2A, port 8083: `networkPolicy.egress.extra`).

## What is verified (2026-10-02)

| Check | How | Result |
|---|---|---|
| The chart's `RemoteMCPServer` and `remote-mcp-server.yaml` against kagent **v0.10.2**'s CRD (`remotemcpservers.kagent.dev`, `v1alpha2`, OpenAPI schema and CEL rules) | CRD from `helm/kagent-crds` at the v0.10.2 tag applied to k3s; `helm upgrade --set kagent.examples=true` and `kubectl apply --dry-run=server` | accepted; defaults applied (`terminateOnClose: true`) |
| kagent's MCP client library against `/mcp` | `github.com/modelcontextprotocol/go-sdk` **v1.6.1** (what kagent v0.10.2's `go.mod` pins), `StreamableClientTransport` with a header-adding `RoundTripper` as in kagent's `go/adk/pkg/mcp/registry.go` | initialize (protocol `2025-11-25`), its `GET` for a standalone SSE stream gets 405 and is skipped as the SDK intends, `tools/list` (9), `tools/call` results and tool errors, `DELETE` on close gets 405 (ignored) |
| An in-cluster agent with a Secret-held header | `make k3s-smoke MCP=1`: a pod in namespace `kagent` with the official Python SDK and `Authorization` from a Secret holding `Bearer sdg_...`, calling the Service URL; a pod in another namespace | tools listed and called; 401 right after the key is revoked; the other namespace's connections are dropped by the NetworkPolicy |

**Not verified:** a live kagent install (controller reconciling the `RemoteMCPServer`:
the `Accepted` condition and `status.discoveredTools`; an `Agent` calling the tools;
header resolution for cross-namespace references). The research notes
(`docs/research/kagent-a2a-claude-code-frontend.md`) describe the 0.10 controller and
A2A from source. kagent's **1.0** line (pre-releases) moves to `api.kagent.dev/v1alpha3`
and changes the Agent kinds; these manifests are for 0.10.x.

## Phase 6

1. **Example `Agent` manifests** (Helm templates under `kagent.examples`):
   `soundings-evaluator` (`get_rubric`, `get_idea`, then `submit_evaluation`; shown with
   an "AI" badge, left out of the aggregate by default) and `soundings-researcher`
   (research notes, `propose_proposal_section` for the owner to accept or discard).
2. **Worker to kagent over A2A**: runs started at the agent's A2A endpoint, progress to
   the UI, timeout and cancel; egress rules for it.
3. Admin → AI agents: the service account and its key, "Rotate key".

Before writing them, inspect the installed kagent version against what is actually
there (SPEC.md section 9):

```sh
kubectl get crd | grep kagent
kubectl explain agents.kagent.dev.spec --recursive | head -50
kubectl -n kagent get agents,rmcps
```
