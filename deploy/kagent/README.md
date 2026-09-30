# kagent integration (placeholder: Phase 6)

Soundings uses [kagent](https://kagent.dev) for its two AI jobs (SPEC.md section 9). Nothing
here is installed yet; the Helm values `features.ai`, `kagent.enabled`,
`kagent.namespace` and `kagent.examples` exist so the shape of the configuration is
settled, and are ignored until Phase 6.

## What Phase 6 adds

1. **Example `Agent` manifests** (optional Helm templates, off by default via
   `kagent.examples`):
   - `soundings-evaluator`: reads an idea through Soundings' MCP tools (`get_idea`,
     `get_rubric`) and submits a scored, cited evaluation (`submit_evaluation`).
     Shown with an "AI" badge and excluded from the aggregate score by default.
   - `soundings-researcher`: writes a cited research note on an idea and drafts
     proposal sections (`propose_proposal_section`) for the owner to accept or discard.
2. **MCP server registration**: a kagent tool-server resource pointing at
   `http://<release>-soundings.<namespace>.svc/mcp` (streamable HTTP, stateless), with a
   scoped Soundings API key (service account, `mcp` scope) read from a Secret.
3. **Worker to kagent over A2A**: the worker starts agent runs through the agent's A2A
   endpoint (URL from `kagent.namespace` and the registered agent name), streams progress
   to the UI over SSE, and handles timeout and cancel.
4. **NetworkPolicy additions**: when `networkPolicy.enabled`, allow the kagent namespace
   to reach the API port (MCP) and document the worker's egress to kagent.

## Before writing any of it

The kagent CRDs and A2A API change between releases. Inspect the installed version and
code against what is actually there (SPEC.md section 9):

```sh
kubectl get crd | grep kagent
kubectl explain agents.kagent.dev.spec --recursive | head -50
kubectl -n kagent get agents
# the agent card (A2A) of an installed agent, via port-forward to the kagent controller
```

Record the version, CRD group/version and the A2A endpoint shape in `docs/` before
depending on them.
