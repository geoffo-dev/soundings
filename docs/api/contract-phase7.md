# API contract: Phase 7 (polish and hardening)

Phase 7 (SPEC section 13) adds no feature: it applies the security, accessibility, UX and
performance reviews. These are its **additive** changes to the REST contract; everything
in [contract-phase1.md](contract-phase1.md) to [contract-phase6.md](contract-phase6.md)
still applies. Source of truth: `backend/app/schemas/` (`work.py`, `projects.py`,
`audit.py`), the routes in `backend/app/api/v1/work.py`, exported to
`frontend/src/api/generated/` (`make gen-api`). `backend/tests/test_contract_routes.py`
pins the two new operations; `tests/authz/test_route_rules.py` names their rules and
`app/authz/keys.py` classifies them for API keys (`read`, like `get_my_work`).

## Changes in Phase 7

### C1 · My work: counts alone, the first 50 evaluations due, the rest page by page

Performance review B1: the sidebar fetched the whole `GET /me/work` on every page load
for three numbers (116 ms and up to 513 kB for someone owing 1,000 evaluations), and My
work rendered every evaluation due at once. This supersedes Phase 1 decision F9 ("My work
stays uncapped").

| Operation | Change |
|---|---|
| `GET /api/v1/me/work/counts` (`get_my_work_counts`, new) | Returns `WorkCounts` (`evaluations_due`, `evaluations_overdue`, `owned_open`): the same numbers as `GET /me/work`'s `counts`, from two aggregate queries. The sidebar's badges use this. Rules: signed in, `idea.view` (the same filters as My work). Keys: `read`. |
| `GET /api/v1/me/work` (`get_my_work`) | Same shape plus one field. `evaluations_due` holds **at most the first 50** (`EVALUATIONS_DUE_PAGE`), in the same order (overdue first, then soonest due, no due date last; ties by idea id). `counts.evaluations_due` and `counts.evaluations_overdue` count **all** of them, as owned groups already do. New `evaluations_due_next_cursor: string \| null`: null when the list holds them all. |
| `GET /api/v1/me/evaluations-due?cursor=&limit=` (`list_my_evaluations_due`, new) | `WorkEvaluationPage` (`items: WorkEvaluation[]`, `next_cursor`): every evaluation you owe in My work's order, page by page (`limit` 1-200, default 50). My work's "Show all" passes `cursor=<evaluations_due_next_cursor>` and continues with each page's `next_cursor`. Opaque keyset cursor; a malformed or foreign cursor is 400 `invalid_cursor`. Rules and key access as `get_my_work`. |

MCP tools are unchanged (none of them returns My work).

### C2 · `ProjectSummary.pending_moderation_count`

Performance review B7: platform admins sent one `GET /projects/{slug}/moderation?limit=1`
per project on every load for the sidebar's "waiting for review" counts.

| Field | Meaning |
|---|---|
| `ProjectSummary.pending_moderation_count: integer \| null` (so also `Project`, from `GET /projects/{slug}`) | The number of ideas from the public form held for moderation (the moderation queue's `total`), for people who may moderate the project (`idea.moderate`: project admins and platform admins, archived projects included, as the queue is a read); **null** for everyone else. Ideas held for email confirmation are not counted. `GET /projects` computes it in its one query. |

### Audit: `user.anonymise`

`AuditAction` gains `user.anonymise` (security review L5): written by the CLI command
`soundings anonymise-user <email>` (no API operation), which only works on a deactivated
account. Target: the user; actor: none (an operator at the console); details: what was
removed, as counts (`identities`, `external_ids`, `api_keys`, `sessions`,
`notifications`, `emails`, `mentions`). Never the old name or address. The SPA needs its phrase, category, mock entry and the exhaustive `Record`
in `audit-phrases.test.ts`.

### Writes: 429 `rate_limited` for a signed-in person

Every `POST`, `PUT`, `PATCH` and `DELETE` authenticated by a **session** counts against
120 a minute per person per API process (security review L4;
`SOUNDINGS_SESSION_WRITES_PER_MINUTE`). Past that: **429** problem+json, code
`rate_limited`, `Retry-After` in whole seconds; the refused write is not counted. The
CSRF check comes first (a forged write is 403 `csrf_failed` and not counted); sign-out
(`POST /auth/logout`, `/auth/logout/redirect`) is never limited; reads are not limited.
API keys keep their own limits (contract-phase5 §3.2, `too_many_attempts`). The SPA
words it like other 429s ("Wait a moment and try again").

### The API's map: signed in only in production

`GET /api/v1/openapi.json` and `GET /api/docs` (Swagger UI) need a session or a
person's API key with `read` when `SOUNDINGS_ENVIRONMENT=production` (security review
N1): 401 `unauthorized` without one, 403 `insufficient_scope` for a key without `read`
or an AI agent's key. Outside production they stay open (`make gen-api` exports the
document in-process either way). Swagger UI's own static files stay public.

### Transport: compression

Not a contract change, but clients see it (performance review B4): `GET` responses with
a JSON body of 1 KB or more come gzipped (`Content-Encoding: gzip`, `Vary:
Accept-Encoding`) when the request accepts gzip, except responses the endpoint marks
`Cache-Control: no-store` itself (the two that show a key once), event streams and
files. The SPA's static files come Brotli- or gzip-compressed from the image.
