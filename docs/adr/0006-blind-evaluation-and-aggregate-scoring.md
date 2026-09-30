# ADR 0006: Blind evaluation and aggregate scoring

- Status: Accepted · Date: 2026-09-30

## Context

SPEC section 2: evaluators score each rubric criterion 1–5 plus Go/Maybe/No, **blind**
until they submit; the aggregate is a weighted mean with a count and a "high
disagreement" flag; AI evaluations are excluded by default. Score leaks are easy to
miss (a sort order, a board badge, an email, an MCP tool), so the rule must be exact
and enforced in one place.

## Decision

- **Pending evaluator** = a user assigned as evaluator on the idea with no *submitted*
  evaluation for it (none, or only a draft). No role, including platform admin, lifts
  this. A pending evaluator sees no other evaluation data for that idea anywhere (list,
  board, idea page, score sort and filters, API, MCP, exports, emails), only who is
  assigned and who has submitted. After submitting they see every submitted evaluation.
- Anyone else who can view the idea sees submitted evaluations and the aggregate.
  Drafts are visible only to their author. Emails never contain scores.
- Enforcement: rules `evaluation.view_others` and `score.view_aggregate` in the policy
  module ([ADR 0010](0010-central-authorisation-policy.md)). Serializers null the
  fields and set `scores_hidden: true`; score sort treats the idea as unscored and
  score-derived filters never match it. Cached score columns get the same check.
- **Included set:** submitted evaluations with `include_in_aggregate = true`; human
  evaluations always, AI evaluations (`is_ai`) only when the owner or an admin
  includes them (default excluded).
- **Aggregate:** adjusted score `a = score`, or `6 - score` for inverted criteria
  (Effort, Risk). `m_c` = mean of `a` for criterion `c` over the included set.
  Aggregate = `Σ w_c·m_c / Σ w_c` over active criteria with at least one score
  (weights renormalise). Scale 1–5, one decimal, shown with `n`; none when `n = 0`.
- **High disagreement** = any active criterion with ≥ 2 included scores where
  `max - min >= 2` (raw scores; inversion doesn't change the spread).
- Aggregate, count and flag are cached on `idea` and recomputed in the same transaction
  as any evaluation, inclusion or rubric change.

## Consequences

- Blind visibility and scoring get table-driven tests before any UI (SPEC section 15).
- The client must render "Hidden until you submit" for `scores_hidden`, not "no score".
- Ranking is `ORDER BY aggregate_score DESC NULLS LAST` plus the hidden rule.
