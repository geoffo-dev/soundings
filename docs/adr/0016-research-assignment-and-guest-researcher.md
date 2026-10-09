# ADR 0016: A researcher per idea, and guest access to one idea through the policy

- Status: Proposed · Date: 2026-10-08 · Extends ADR 0010 and ADR 0015
  ([decisions](../decisions.md#phase-8b-product-owner-2026-10-08), [contract-phase8b](../api/contract-phase8b.md))

## Context

The product owner asked that an idea's research can be assigned to one person, **anyone
with an account**, including people outside the idea's project: research means asking
other departments. Until now every access came from a project role (or an internal
project's visibility); a non-member of a private project got 404 for everything in it.

## Decision

1. **Columns on `ideas`** (`researcher_id`, `research_assigned_at`, `research_due_at`),
   not a table: one researcher per idea, read with the idea everywhere. Null = the owner
   does the research, as before. Deactivation, closing the idea and turning the project's
   step off clear it; any active person may hold it (never an agent or the break-glass
   account). Assigning is **session only**: an API key can remove or hand back, never
   assign, since an assignment opens the idea to someone and would outlive a revoked key.
2. **Guest access is a principal column, R**, in the one policy module: a person without a
   role in a **private** project who is the idea's researcher while the assignment is
   **live** (step on, idea open, project not archived). It applies to idea-scoped rules on
   that idea only; project-scoped rules and other ideas stay NMp (404). R's view is
   `idea.view` without `project.view`: no score data (like rule 9 for agents), no
   evaluation area (nor the feed's evaluation events: the guest feed is an allow-list),
   proposal, AI panel or project. Its cells live in one table (role matrix table L), deny
   by default.
3. **A researcher overlay, +Rsr**, counts without a role (unlike +Own and +Evl): answering,
   commenting and "Hand back" for viewers, internal non-members and R. Internal projects
   get no guest view: assignment adds, never takes away. Answering lasts only while the
   idea still awaits research (c26, the lead's D1, 2026-10-09: past Research the answers
   feed the proposal's appendix, which a guest can't see, so only the owner and admins
   change them there, 409 `research_finished` for the researcher).
4. **A route table for R** (`view` / `rule` / `hidden`, missing = hidden) applied where the
   idea is loaded, so reads that only checked `idea.view` (evaluations, AI runs and their
   stream, the submission panel, proposal reads) are 404 for R by default, and a meta-test
   catches any new idea route or MCP tool without a decision.
5. **Lists stay project-scoped**; a separate SQL helper (`app.authz.queries.researched_ideas`)
   adds a person's live researched ideas **only** to search and ⌘K, MCP `search_ideas`,
   the inbox (with only the types a guest can hold), My work's "Research to do" and
   Similar ideas, so a list nobody decided about never shows a guest's idea. Every SQL
   score mask also requires the idea's project to be viewable, so no list can leak a
   score through a guest's idea.

## Consequences

- Access ends on the next request when the assignment ends or stops being live; nothing is
  cached. Closing the idea or turning the step off ends the assignment itself (removal is
  refused then, so a dormant one would come back on reopening); archiving only suspends
  it. Who may open a private idea to an outsider, and whether leaving the project ends it,
  was decided by the product owner (contract review S1: only project and platform admins
  name an outsider in a private project, c25; losing one's role there ends one's
  assignments, `left_project`); the lead added that making an internal project private
  ends the assignments of researchers without a role there (`made_private`, D2, after a
  warning with `Project.outside_researcher_count`), so only an admin's choice ever makes
  someone R.
- An AI agent's research run writes into the feed R reads, so it reads the idea as R would
  (c22 by run kind: no proposal, rubric or evaluation area; guest review M1).
- Every surface that builds idea data for R must use the policy's decisions (the guest
  shape); the tests are a table over principal kinds × assignment states × every route and
  tool, with score data checked on every path.
- Notifications follow `idea.view`, so a guest gets the idea's notifications and loses
  them with the access; "Asked to research" and research reminders are new types.
