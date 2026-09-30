# ADR 0008: Contract-first parallel build with a generated TS client and MSW

- Status: Accepted · Date: 2026-09-30

## Context

From Phase 1, backend, frontend and qa work in parallel (SPEC section 14). If the
frontend waits for real endpoints, it idles; if it guesses shapes, integration breaks.
Hand-maintained TypeScript types drift from Pydantic models.

## Decision

- **The lead writes the contract before a parallel phase:** Pydantic request/response
  models in `backend/app/schemas/`, route stubs that return 501 problem+json, and the
  exported OpenAPI document (`make openapi` →
  `frontend/src/api/generated/openapi.json`, sorted and deterministic).
- **Generated client:** `openapi-typescript` turns the document into
  `frontend/src/api/generated/schema.d.ts` (`make gen-api`); the SPA calls the API only
  through `openapi-fetch` (`src/api/client.ts`), which adds the CSRF header and turns
  problem+json into a typed `ApiError`. Generated files are committed and never edited
  by hand.
- **Mocks:** the frontend runs against MSW handlers (`src/mocks/handlers/`) typed
  against the same schema (`npm run dev:mock`; vitest uses `msw/node`). Mocks must
  return realistic data, including blind-hidden scores and problem+json errors.
- **Contract changes go through the lead only.** A builder who finds the contract wrong
  messages the lead with the proposed change; the lead updates schemas, regenerates,
  and tells affected owners.
- Conventions baked into the contract: snake_case JSON, cursor pagination
  (`items`, `next_cursor`), RFC 9457 errors with a stable `code`, UUID ids plus
  human-friendly idea keys (e.g. `INN-42`).
- CI must fail when the committed `openapi.json` or `schema.d.ts` differs from a fresh
  `make gen-api` (check requested from platform in Phase 1).

## Consequences

- Frontend and backend can finish in either order; integration is "turn mocks off".
- Two generated artefacts to keep in sync; `make gen-api` does both, CI checks it.
- Contract changes serialise through the lead, a deliberate bottleneck.
