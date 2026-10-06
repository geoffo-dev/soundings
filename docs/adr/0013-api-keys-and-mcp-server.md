# ADR 0013: API keys as a principal source, and an MCP server built on the REST services

- Status: Accepted (built and verified in Phase 5 integration, 2026-10-06) · Date: 2026-10-02

## Context

SPEC section 8 asks for personal API keys (scopes `read`, `write`, `evaluate`, `mcp`;
optional expiry and project restriction; shown once, stored hashed, revocable, last use
shown; never more than the owner's live permissions) and an MCP server at `/mcp`
(streamable HTTP, stateless, API-key auth, nine tools, same authorisation as the API,
every call audited). Phase 6 agents will use it with service-account keys. The policy
(ADR 0010) and `Principal` were built for this in Phase 1 (`auth = "api_key"`, scopes,
project restriction); the `mcp` SDK 2.x was verified in research R1 §1.

## Decision

- **Keys** are `sdg_<12-char lookup id>_<40-char secret>` (base62, CSPRNG). Only the
  lookup id and the SHA-256 of the whole key are stored; authentication is one indexed
  lookup plus a constant-time compare. No pepper: rotating the secret key must not revoke
  every key, and a 238-bit random secret needs no slow hash. Keys are immutable, at most
  25 per user, optionally expiring within 366 days, restricted by a `uuid[]` of projects
  (null = all). `write` and `evaluate` include `read`. Revoked rows stay for the audit
  trail; deactivating the owner revokes.
- **Keys don't outlive what ended the owner's access.** Group sync and identity-provider
  removals apply at sign-in, and sessions end within 24 hours, so a key follows its
  owner's sign-ins: a person's key pauses (401, `dormant`) while they haven't used the
  app for 30 days and works again when they sign in; a key works only while the sign-in
  method that created it is available (`created_auth_method`, like sessions); the
  break-glass account creates none (c20). Service accounts never sign in and are exempt
  from the 30 days.
- **A principal source**, first in `PRINCIPAL_SOURCES`: `Authorization: Bearer` builds
  `Principal(auth="api_key", scopes, project_ids, api_key_id)` for the owner, re-read on
  every request (no cache), so revocation, expiry and demotion apply to the next
  request. The policy does the narrowing (scope → 403 `insufficient_scope`, restriction
  → 404); key management, admin and settings rules, `idea.delete` and `idea.moderate`
  stay session only (nothing irreversible through a key); requests with a key skip
  CSRF. Failures are counted per address (over the limit only failing keys get 429), and
  every key is rate-limited (300 requests and 30 writes a minute).
- **MCP is a thin adapter over the REST services.** `POST /mcp` only, stateless JSON
  mode on the SDK's low-level `Server` (`streamable_http_app(stateless_http=True,
  json_response=True)`, `app.add_route`, the session manager in the app's lifespan). An
  ASGI wrapper authenticates with the same key source (so errors are problem+json and
  there is one code path), enforces c15 and an Origin allow-list, and hands the
  principal to the tools. `/mcp` is exempt from the app's Host check so agents can call
  the cluster Service (the bearer key and Origin check cover what Host guards). One
  dispatcher handles every `tools/call`: it validates the arguments with the tool's
  contract model (the write tools' models are the REST request models), applies the
  write cap, authorises the rule through the policy, calls the service the REST
  endpoint uses, returns a contract model as structured content (bounded: latest
  comments and evaluations, long texts cut, people-written fields labelled untrusted),
  maps failures to tool results carrying the REST problem code, and audits the call as
  `mcp.call` exactly once (entries expire after 90 days). Held ideas are never visible
  through MCP.
- **Agents and prompt injection.** An agent's service account never owns an idea or
  holds the admin role (it can't accept its own suggestions or count its own
  evaluation). Its key is restricted to the projects it serves, and where projects must
  not leak into each other an operator registers one agent per project: text planted in
  one project could otherwise steer a shared agent to read another and write it back.
- **Suggestions** (`proposal_suggestions`) are the one new domain object:
  `propose_proposal_section` (and a REST twin) stores the whole text of one section;
  the owner accepts it as a normal versioned section save or discards it.

## Consequences

- Blind evaluation, holds, conditions and locks in MCP come from the REST services by
  construction; tests check the outputs rather than re-implement the rules.
- One more credential to protect: keys are never logged, traced, returned twice or put
  in URLs; secret scanners can match the `sdg_` pattern.
- Statelessness means no server-to-client MCP messages (sampling, progress); agents
  don't need them for these tools.
- The audit log grows with agent traffic; the 90-day expiry of `mcp.call` bounds it.
- People who use only keys must sign in to the app once a month; Settings → API keys
  says so. In exchange a departed person's keys stop within about 30 days without an
  admin noticing.
- Phase 6 adds agent registration (service accounts and their keys) without changing
  authentication, the policy or the tools' authorisation.

## Amendment (2026-10-06, after the security and UX reviews)

- The key check (and `last_used_at`) runs in one short transaction that closes before
  the request's session opens, and every MCP tool call checks the key and its owner
  again inside its own transaction: no pool lock-up under parallel keys, and a revoke
  stops even a call already let in (tool error `unauthorized`).
- Text that reaches agents is cleaned at both ends: request bodies refuse Unicode tag
  characters, MCP results lose every invisible character, and every people-written
  output field (names and labels included) is marked untrusted. Write tools refuse
  unknown arguments.
- A service account without a role is a private non-member everywhere, and its people
  search covers only its projects' people: an agent sees what it was added to, nothing
  more.
