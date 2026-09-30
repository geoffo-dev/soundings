# ADR 0010: Authorisation in one central policy module, deny by default

- Status: Accepted · Date: 2026-09-30

## Context

SPEC section 7 requires authorisation in one central module, deny by default, with
table-driven tests of the role matrix. Permissions combine a platform flag, a project
role (direct or via groups, highest wins), project visibility, per-idea overlays
(owner, evaluator), blind evaluation, API-key scopes and project restrictions, and the
public tracking link. Scattered `if user.is_admin` checks drift and leak.

## Decision

- `backend/app/authz/` (identity agent) exposes one entry point,
  `authorize(principal, rule, resource) -> Decision`, with `can`/`require` helpers and
  query filters (`visible_projects`, `visible_ideas`) for lists. `require` raises 404
  when the principal cannot *view* the resource and 403 when it can view but not act.
- **Rules have stable names** (`idea.change_status`, `evaluation.view_others`, …)
  defined in [../role-matrix.md](../role-matrix.md). Code, tests, audit entries and
  docs refer to rules by name. A rule missing from the policy table is denied.
- The **principal** is resolved once per request: user (or none), platform-admin flag,
  auth kind (session, API key, tracking token, anonymous), key scopes and project
  restriction. Effective permission = live user permission ∩ key scopes ∩ key project
  restriction, so a key never exceeds its owner.
- Owner and evaluator overlays count only while the user holds `member` or `admin` in
  the project.
- Routes, MCP tools, worker jobs acting for a user, and email rendering all call the
  policy; none inspect roles directly. Blind visibility is part of the policy
  ([ADR 0006](0006-blind-evaluation-and-aggregate-scoring.md)).
- Tests: a parametrised table per rule (principal × resource state → allow/403/404)
  mirroring the matrix, against real Postgres, plus a test that every route and MCP
  tool declares its rule.

## Consequences

- A new feature starts with a named rule and a matrix row; reviewers check both.
- Admin override is explicit in the table, never implicit, and never lifts blind
  evaluation.
- The policy is on the hot path; list endpoints filter in SQL, not per row.
