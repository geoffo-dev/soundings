# ADR 0014: kagent over A2A, with results through MCP and runs as durable records

- Status: Proposed · Date: 2026-10-06

## Context

SPEC section 9: an AI evaluator and a research and drafting assistant in kagent, called
by the worker over A2A, reading and writing Soundings through its MCP server (Phase 5)
as a service account with a scoped key; agents registered in the admin UI by
namespace/name; live progress; clean timeout and cancel. kagent is mid-rewrite: v0.10.2
serves A2A 0.3 and 1.0 method names at `/api/a2a/{ns}/{name}/` (selected by
`A2A-Version`), the 1.0 line moves to `/agents/{ns}/{name}` (research R2 §1); its Python
agent runtime (kagent-adk 0.10.2) speaks A2A 0.3 only. kagent 0.10 has no output schema,
its Python runtime can't cancel, its UI and A2A endpoint are unauthenticated by default
(`--auth-mode=unsecure`), and there is no kagent or LLM in this build environment.

## Decision

- **Addressing is built, never given.** An agent is `(namespace, name, protocol)`; the
  A2A URL is `SOUNDINGS_KAGENT_URL` (one validated origin) + the protocol's fixed path +
  two DNS labels (`agent_a2a_url`). No URL is stored or accepted; agent cards' URLs are
  ignored; redirects are not followed. `protocol` is `kagent_v0_10` (A2A 0.3) or
  `kagent_v1_0` (A2A 1.0) per agent.
- **Agents act through MCP, as people do, and only inside their runs.** Each agent has
  one service account and one server-managed key (scopes from its purposes, restricted
  to its projects). The A2A message carries only references and instructions (no URL);
  the agent reads the idea with `get_idea`/`get_rubric` and records its result with
  `submit_evaluation` (per-criterion rationale and sources), `add_research_note` or
  `propose_proposal_section`. The server attaches the result to the active run; A2A
  text is ignored. Blind evaluation, holds, limits and audit apply unchanged, plus two
  agent rules: **c22, run scope** (the key works on `/mcp` only, on the idea of a
  `running` run nobody asked to cancel, writing only through the run kind's tool) and
  **rule 9** (agents never see others' score data, before or after submitting).
- **Runs are rows.** `ai_runs` (status, deadline, heartbeat, cancel request, A2A task id,
  sanitised error, result reference) and `ai_run_events` (numbered, Soundings' own
  sentences) are executed by a procrastinate job on its own `ai` queue and worker pool
  (so email and the schedules never wait for AI), with compare-and-set transitions, a
  deadline from start, cooperative cancel (`tasks/cancel`, best effort), `worker_lost`
  on shutdown and a sweep for lost workers. One active run per idea, agent, kind and
  section (partial unique index); a repeated request returns it.
- **Progress is SSE from the API**, replayed from `ai_run_events` with `Last-Event-ID`,
  re-authorised every 30 seconds, with polling as the fallback. Events hold no agent
  text and no score data, so anyone who may view the idea may watch.
- **AI evaluations are excluded from the aggregate by default**; the owner or an admin
  includes each one (`evaluation.include_ai`).
- **Tested without kagent** by a deterministic fake A2A agent (a2a-sdk server) that
  serves both layouts and really calls `/mcp`; kagent's v0.10.2 CRDs in k3s check the
  example manifests by server-side dry run.

## Consequences

- An operator can't point Soundings at an arbitrary host, and a compromised,
  misconfigured or steered agent can do only its one result on the idea of a run
  someone asked for, while that run is open; cancel, timeout and a lost worker are
  final. The residual risk is someone messaging the agent directly in kagent during a
  live run on the same idea (keep kagent's endpoints inside the cluster).
- Agents' notes and suggestions can't leak others' scores to pending evaluators, and
  people's evaluation comments never reach an LLM provider.
- Model output never needs parsing; a model that ignores instructions fails its run
  (`no_result`) instead of writing something unchecked.
- Supporting kagent 1.0 is one enum value and a path; its exact layout is assumed until a
  release ships (contract-phase6 §8). A live controller (proxying, `tasks/get` from its
  database) is not verified here.
- Without an output schema, rationale quality and citations depend on the model and its
  system message; the server enforces only shape (rationale present, ≤ 5 http(s)
  sources per criterion).

## Notes from the build (2026-10-06)

- The A2A client is hand-written on httpx (no a2a-sdk in the backend): four calls, our
  own size limits, no redirects or proxies. a2a-sdk 1.2.1 is used only by the fake agent.
- The worker runs the `ai` queue in a procrastinate pool of its own next to the email and
  notification pool, in one process; the database pool is sized for both.
- `ai.delete_note` (the idea's owner and admins) replaced `comment.delete_any` for
  research notes. Other build-time calls: [decisions.md](../decisions.md), "Phase 6 build
  and integration"; contract changes: contract-phase6 §10.
- Verified against kagent: the example manifests against v0.10.2's real CRDs. Everything
  else about the loop is verified against the fake agent only (contract-phase6 §8).
