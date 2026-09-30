# ADR 0009: Product name "Soundings" and answers to SPEC section 16

- Status: Accepted · Date: 2026-09-30 · Deciders: product owner (relayed by the lead)

## Context

SPEC.md used the working name "ideas-pipeline" and listed five open questions for the
product owner (section 16). The answers affect names in code, Helm and images, the
data model and the authorisation rules, so they are recorded here.

## Decision

1. **Name:** the product is **Soundings** (taking soundings: measuring depth before
   committing). Package, chart, image, CLI and cookie prefixes use `soundings`.
   Default brand: calm neutral greys with one accent, deep ocean blue `#1d5fa8`,
   Inter (bundled). No default logo beyond a simple wordmark; admins upload their own.
2. **Volunteer owners:** members may volunteer to own an unowned idea when the project
   allows it: project setting `allow_volunteer_owners`, default `true`.
3. **Evaluators** are restricted to project members with role `member` or `admin`
   (direct or via a group). Viewers and non-members cannot be invited.
4. **Evaluation window:** default due date 7 days after the first evaluator is invited
   (`default_evaluation_days = 7` per project). Reminders go 2 days before the due date
   and on the due date, to evaluators who have not submitted.
5. **No classification markings** on ideas or exported proposals.

Also fixed at the same time (engineering, see linked ADRs): one image for API + SPA
with the worker as a second entrypoint (ADR 0004); psycopg 3 only (ADR 0002);
snake_case JSON everywhere (ADR 0008).

## Consequences

- `allow_volunteer_owners` and `default_evaluation_days` are the only new project
  settings; reminder timing is fixed, not configurable (simple beats configurable).
- The role matrix ([../role-matrix.md](../role-matrix.md)) encodes answers 2 and 3.
- Renaming again later means changing prefixes in code, chart and cookies; avoid it.
