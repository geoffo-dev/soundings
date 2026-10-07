# ADR 0015: Per-project proposal templates and an optional research step

- Status: Proposed · Date: 2026-10-07 · Supersedes SPEC section 2's fixed proposal
  template and fixed lifecycle where they differ ([decisions](../decisions.md#phase-8-product-owner-2026-10-07))

## Context

The product owner asked (after 0.1.0) for (A) a proposal template each project edits like
its rubric, and (B) an optional Research stage, before evaluation or before the proposal,
whose checklist must be answered before an idea moves past it. Sections were named by
eight fixed keys everywhere (proposals, threads, Phase 5 suggestions, Phase 6 drafts) and
the lifecycle was one fixed enum.

## Decision

1. **Templates are rows** (`proposal_template_sections`), 1–12 active per project, seeded
   with the eight defaults. Keys are stable slugs, unique per project. Section rows,
   threads, suggestions and runs keep a **key column without a foreign key**: keys are
   immutable and a referenced section is archived, never deleted (under the project's
   `FOR UPDATE` lock), so a key always resolves; no copied `project_id`, no backfill. The
   template is live; removed sections keep their text and threads, hidden, until restored.
2. **The lifecycle is the project's**: `IdeaStatus` gains `research`, placed by
   `projects.research_step`; `app.schemas.research.lifecycle(step)` is the one definition
   of a project's statuses, `IdeaStatus` order the canonical cross-project order. The step
   can't change while ideas are in Research.
3. **The gate is a domain rule, the override a policy rule**: one pure definition
   (`crosses_gate`, with a closed idea counted from the status it was closed from, and
   `starts_evaluation`) picks the guarded requests; one check in the services
   (`ideas.change_status`, which `create_proposal` uses for its move, and one research
   helper for invites and AI evaluation; no bypass) refuses them (409
   `research_incomplete`) while a required item is unanswered, under the idea's lock.
   `idea.research_override` (admins, session only) lets a flagged request through, audited.
4. **Answers are plain-text records** with first author and last editor, not activity
   events; checklist items archive like rubric criteria. MCP stays at ten tools.
5. **Research is internal**: public tracking reports it as the status before it in the
   project's lifecycle (`public_status`), and submitters hear about a move only when that
   reported status changes. Agents' instructions name a section by key, never by its
   (admin-written) title.

## Consequences

- Clients treat section keys as data; the generated `ProposalSectionKey` type is gone.
- Every path that moves an idea forward must use the gate's one check (the demo seed
  too: it answers checklists or turns the step on after moving its ideas).
- Downgrading 0012 loses custom sections' text and research data; ideas in Research go
  back to the stage before it.
- Still no per-project stage designer: one optional stage at two fixed places.
