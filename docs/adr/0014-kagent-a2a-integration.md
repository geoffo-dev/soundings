# ADR 0014: kagent over A2A, with results through MCP and runs as durable records

- Status: Proposed · Date: 2026-10-06

## Context

SPEC section 9: an AI evaluator and a research and drafting assistant in kagent, called
by the worker over A2A, reading and writing Soundings through its MCP server (Phase 5)
as a service account with a scoped key; agents registered in the admin UI by
namespace/name; live progress; clean timeout and cancel. kagent is mid-rewrite: v0.10.2
serves A2A 0.3 and 1.0 method names at `/api/a2a/{ns}/{name}/` (selected by
`A2A-Version`), the 1.0 line moves to `/agents/{ns}/{name}` (research R2 §1). kagent 0.10
has no output schema, its Python runtime can't cancel, and there is no kagent or LLM in
this build environment.

## Decision

- **Addressing is built, never given.** An agent is `(namespace, name, protocol)`; the
  A2A URL is `SOUNDINGS_KAGENT_URL` (one validated origin) + the protocol's fixed path +
  two DNS labels (`agent_a2a_url`). No URL is stored or accepted; agent cards' URLs are
  ignored; redirects are not followed. `protocol` is `kagent_v0_10` (A2A 0.3) or
  `kagent_v1_0` (A2A 1.0) per agent.
- **Agents act through MCP, as people do.** Each agent has one service account and one
  server-managed key (scopes from its purposes, restricted to its projects). The A2A
  message carries only references and instructions; the agent reads the idea with
  `get_idea`/`get_rubric` and records its result with `submit_evaluation` (per-criterion
  rationale and sources), `add_research_note` or `propose_proposal_section`. The server
  attaches the result to the active run; A2A text is ignored. Blind evaluation, holds,
  limits and audit apply unchanged.
- **Runs are rows.** `ai_runs` (status, deadline, heartbeat, cancel request, A2A task id,
  sanitised error, result reference) and `ai_run_events` (numbered, Soundings' own
  sentences) are executed by a procrastinate job with a database-counted concurrency
  limit, a deadline from start, cooperative cancel (`tasks/cancel`, best effort) and a
  sweep for lost workers. One active run per idea, agent, kind and section (partial
  unique index); a repeated request returns it.
- **Progress is SSE from the API**, replayed from `ai_run_events` with `Last-Event-ID`,
  re-authorised every 30 seconds, with polling as the fallback. Events hold no agent
  text and no score data, so anyone who may view the idea may watch.
- **AI evaluations are excluded from the aggregate by default**; the owner or an admin
  includes each one (`evaluation.include_ai`).
- **Tested without kagent** by a deterministic fake A2A agent (a2a-sdk server) that
  serves both layouts and really calls `/mcp`; kagent's v0.10.2 CRDs in k3s check the
  example manifests by server-side dry run.

## Consequences

- An operator can't point Soundings at an arbitrary host, and a compromised or
  misconfigured agent can do only what its member role and key allow, in its projects.
- Model output never needs parsing; a model that ignores instructions fails its run
  (`no_result`) instead of writing something unchecked.
- Supporting kagent 1.0 is one enum value and a path; its exact layout is assumed until a
  release ships (contract-phase6 §8). A live controller (proxying, `tasks/get` from its
  database) is not verified here.
- Without an output schema, rationale quality and citations depend on the model and its
  system message; the server enforces only shape (rationale present, ≤ 5 http(s)
  sources per criterion).
