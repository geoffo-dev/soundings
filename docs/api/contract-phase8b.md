# API contract: Phase 8b (assign the research to a person)

Phase 8b is a change the product owner asked for on 2026-10-08 after seeing Phase 8
([decisions.md](../decisions.md#phase-8b-product-owner-2026-10-08); SPEC.md is
read-only). An idea's research can be **assigned to one person**, its **researcher**:
anyone with a Soundings account, a member of the idea's project or not, notified, listed
in their My work, with an optional research due date and reminders like evaluations. A
researcher without a role in a **private** project sees **that one idea** as its
**guest** (role matrix column R), never its scores, evaluation or proposal. It also
carries the lead's decisions on the Phase 8 review follow-ups (section 12) and the
contract review's fixes (section 18). Everything in
[contract-phase1.md](contract-phase1.md) to [contract-phase8.md](contract-phase8.md)
still applies unless a section below changes it.

Source of truth, in order: the Pydantic schemas (the Phase 8b parts of
`backend/app/schemas/research.py`, `ideas.py`, `work.py`, `notifications.py`,
`activity.py`, `audit.py`, `mcp.py`, `proposals.py`, `base.py`), the route stubs
(`backend/app/api/v1/research.py`: `set_research_assignment`, `remove_researcher`;
`work.py`: `list_my_research_to_do`; `users.py`: `include_non_members`), the models and
migration 0015 (`backend/app/models/idea.py`, `enums.py`;
`migrations/versions/20261008_0015_research_assignment.py`), exported to
`frontend/src/api/generated/` (`make gen-api`). Rules are named as in
[role-matrix.md](../role-matrix.md) (new: column **R**, overlay **+Rsr**, **table L**,
`idea.assign_researcher`, `idea.release_researcher`, c23, c24; `idea.answer_research`
widened). Decision record: [ADR 0016](../adr/0016-research-assignment-and-guest-researcher.md).
`backend/tests/test_contract_routes.py` pins the three new operations
(`PHASE8B_OPERATIONS`, `STUBS`, section 15); `tests/test_schemas_phase8b.py` the request,
`research_to_do` and the defaults; `tests/test_domain_schema_phase8b.py` the columns, types
and the migration.

## 1. What changes, in one table

| Area | Change |
|---|---|
| Data | `ideas.researcher_id` (users, null = nobody: the owner does the research), `ideas.research_assigned_at`, `ideas.research_due_at`; two notification types. Migration **0015**. |
| Who assigns | `idea.assign_researcher`: the idea's owner, project admins, platform admins (c5; c23 for the person named); **in a session only** (an API key can remove, never assign: §4.7). The researcher hands it back with `idea.release_researcher`. Only while the project's research step is on and the idea open; **closing the idea or turning the step off ends the assignment** (§3.7). |
| Who can be researcher | Any **active person**: never a service account (AI agent), the break-glass account or a deactivated user (422 `researcher_not_eligible`). Deactivation clears the assignment (so an account `soundings anonymise-user` handles, always deactivated first, holds none). |
| Researcher access | Members and internal non-members keep their view and gain answering, commenting and "Hand back" on that idea (**+Rsr**). A person without a role in a **private** project gets **column R** for that idea only: overview, feed (without the evaluation events) and comments, the research panel, Similar ideas; never scores, the evaluation, the proposal, the AI panel or anything of the project. Ends when unassigned, deactivated, the idea deleted or closed, or the step turned off; suspended while the project is archived. |
| Answering | `idea.answer_research` widens to the researcher (+Rsr) while the idea still awaits research (c26, §17: past Research 409 `research_finished` for them). The gate and "Move anyway" are unchanged (a researcher can't override). |
| Notifications | "Asked to research" (`researcher_assigned`) and "Research reminder" (`research_reminder`): inbox, email per preference (default immediate), digest, unsubscribe; never score data. |
| My work | "Research to do" (the researcher's, else the owner's ideas still awaiting research with a required item open), `WorkCounts.research_to_do` / `research_overdue`, `GET /me/research-to-do`. Owned groups hold their first **10** ideas (D). |
| UI | "Research: <name> · due <date>" on the idea, a person picker over everyone active (people outside the project marked), "Hand back", the "Start research" dialog, the researcher's avatar on Research cards, a working shell for a guest with no projects. |
| MCP | `get_idea.research` gains `researcher` (untrusted name) and `due_at`; `research_guest` on the idea. Never more than REST. |
| Phase 8 follow-ups | Removed template sections and checklist items gain `position`; decisions recorded (M1, L3, L4, the 200 ms / best-of-3 rule); the performance re-measure. |
| Contract review | Section 18: score data and the evaluation events kept from guests on every path (lists, the feed), assigning session only, closing or turning the step off ends the assignment, the inbox and the recipients narrowed, and smaller fixes. |

## 2. Endpoints

### 2.1 New

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `PUT /ideas/{idea}/research/assignment` | `set_research_assignment` | `idea.assign_researcher` (c5, c23); **session only** | `ResearchAssignmentUpdate {researcher_id: uuid \| null, due_at: DueAt \| null}` (both required) → `IdeaResearch` | 403 (also `insufficient_scope` for any API key); 404; 422 `validation_error`, `researcher_not_eligible`; 409 `project_archived`, `awaiting_moderation`, `idea_closed`, `research_step_off` |
| `DELETE /ideas/{idea}/research/assignment` | `remove_researcher` | `idea.assign_researcher` (owner, admins) or `idea.release_researcher` (the researcher: "Hand back") | → 204 (idempotent) | 403; 404; 409 as above |
| `GET /me/research-to-do?cursor=&limit=` | `list_my_research_to_do` | signed in; contents by `idea.view` (guest access included) | → `WorkResearchPage {items: WorkResearch[], next_cursor}` | 400 (cursor) |

API keys (identity classifies them, section 15): `set_research_assignment` is
**`session`** (review M3: an assignment can open a private idea to an account and would
outlive a leaked, later revoked key; like `project.manage_members`); `remove_researcher`
follows its rules (`write` scope: removing or handing back only takes access away);
`list_my_research_to_do` is a `read` route like `get_my_work`. An AI agent's key is
refused on all three (c22: REST is never an agent's).

### 2.2 Changed

| Operation | Change |
|---|---|
| `search_users` | `include_non_members` (bool, default false), with `project`: **every active person**, members with their `project_role`, everyone else `project_role: null` ("Not in this project"). It needs `project.view` on the project, like `project` alone. The researcher picker. Nothing new leaks: the directory without `project` already lists every active person to every signed-in person, and the members' roles are `project.view` data. Service accounts and the break-glass account never appear, as before. 501 until backend builds it. |
| `get_idea` (`IdeaDetail`) | `researcher` (also on every `IdeaSummary`), `research_due_at`, `permissions.can_assign_researcher`, `can_hand_back_research`, `can_view_project`; the guest shape for R (§4.4). |
| `get_idea_research` (`IdeaResearch`) | `assignment: ResearchAssignment`, `gate_status_label`, `permissions.can_assign`, `can_hand_back`. |
| `get_my_work`, `get_my_work_counts` | `Work.research_to_do` (first 50; `WorkResearch.can_view_project`) + `research_to_do_next_cursor`; `WorkCounts.research_to_do`, `research_overdue`; owned groups' `ideas` = the first **10** (§12). |
| `answer_research_item`, `clear_research_item` | Also the researcher (§5). |
| `list_notifications`, preferences, unsubscribe | Two types (§6); for an idea seen only as its guest researcher, only `RESEARCH_GUEST_NOTIFICATION_TYPES` (§4.5, review S5). |
| `list_idea_activity` | Two event types (§3.6); `StatusChangedActivity.from_label` / `to_label` (the project's labels, so no project read is needed); a guest researcher gets only `RESEARCH_GUEST_ACTIVITY_TYPES` (§4.4, review M2). |
| `get_proposal_template`, `get_research_settings` | `RemovedTemplateSection.position`, `RemovedResearchItem.position` (§12). |
| Every idea route | Column R's outcome (role matrix table L): `view`, `rule` or 404. |

## 3. The research assignment

### 3.1 Data

- `ideas.researcher_id` (FK `users`, `ON DELETE SET NULL`): one researcher per idea, or
  null = **nobody assigned: the idea's owner does the research**, exactly as in Phase 8
  (every existing idea). Columns, not a table: one researcher per idea, read with the
  idea everywhere (cards, the idea page, My work), no join.
- `ideas.research_assigned_at`: when the current researcher was asked (null with nobody;
  the reminders' "already told" check, §6.3).
- `ideas.research_due_at`: the optional research due date, a timestamp like
  `evaluation_due_at` (requests use `DueAt`: an offset, at most a year back and five years
  ahead; the SPA shows it in the instance time zone, `SOUNDINGS_TIMEZONE`, like evaluation
  due dates, and sends the end of the chosen local day). Independent of the researcher:
  kept when the researcher changes or hands it back (it then applies to the owner).
- Indexes: `ix_ideas_researcher_id_status` (`researcher_id, status` where a researcher is
  set: "Research to do", the count, guest access in lists, deactivation) and
  `ix_ideas_research_due_at_open` (`research_due_at` of open ideas: the reminder scan).
- While the project's step is off the columns are kept but **mean nothing**: no access,
  no reminders, no My work, `IdeaSummary.researcher` and `research_due_at` null in
  responses, `IdeaResearch.assignment` empty. Turning the step on again brings them back.

### 3.2 Who may be the researcher (c23)

Any **active person**: `users.is_active`, not `is_service_account`, not `is_break_glass`
(the same set `search_users` returns). A member of the project or not; platform admins
too; **the idea's owner too** (an explicit assignment: the owner is told and it stays
theirs if the idea changes owner; nobody assigned is the implicit owner). Anyone else,
or an unknown id: **422 `researcher_not_eligible`** ("Only an active person can do the
research."). Being an evaluator of the same idea changes nothing (blind rules still
apply to them as an evaluator).

### 3.3 `set_research_assignment`

Order of checks: 401 → **any API key: 403 `insufficient_scope`** (the route is
`session` in `ROUTE_KEY_ACCESS`, checked before the route runs, so it reveals nothing;
review M3) → 422 shape (the body; an idea key that isn't one) → 404 (`idea.view`; R sees
the idea, so R gets 403 next) → 403 (`idea.assign_researcher`) → 422
`researcher_not_eligible` (c23, only when `researcher_id` names someone new) →
409 `project_archived`, `awaiting_moderation` (c19), `idea_closed` (c5) → 409
`research_step_off` (the project's step is off; a domain rule, as for answers) → 409
`research_finished` (a researcher other than the current one, once the idea is past
Research; §17, adversarial check L2) → apply.

Apply, in the request's transaction, with the idea loaded `load_idea(for_update=True)`
(project `FOR KEY SHARE`, then the idea `FOR UPDATE`) and, **when the researcher changes
to a person, that person's `users` row locked `FOR SHARE`** and c23 re-checked on it (so a
deactivation committing meanwhile either clears the new assignment or makes this request
422; §3.5):

1. **Researcher** (when `researcher_id` differs from the current one): set
   `researcher_id` and `research_assigned_at = now()` (both null for nobody). A new
   researcher **watches** the idea (`idea_watchers`, `ON CONFLICT DO NOTHING`; they may
   unwatch). Emit `researcher_changed {from_researcher_id, to_researcher_id,
   handed_back: false}`. Audit `idea.researcher_change` (§13).
2. **Due date** (when `due_at` differs): set `research_due_at`; emit
   `research_due_date_changed {from_due_at, to_due_at}` (no notification, no audit:
   reminders follow the current date, like evaluation due dates).
3. Return `IdeaResearch` as the caller sees it.

**Idempotent:** the same researcher and date change nothing (no event, notification or
audit entry). **Last write wins** (the complete state: two people changing it at once,
the later request's state stands, like the proposal template). Asking someone is allowed
while the idea **awaits research** (in Research or a status before it, also New before
evaluation); **past Research nobody new is asked** (409 `research_finished`: since D1 they
could only read the idea; §17, adversarial check L2), while removing the researcher and
keeping the same one (a due-date change) still work. The fan-out sends "Asked to
research" to a new researcher who isn't the actor (§6.2).

### 3.4 `remove_researcher` ("Remove" and "Hand back")

Order of checks: 401 → 422 (idea) → 404 → 403: `idea.assign_researcher` (the owner,
admins) **or** `idea.release_researcher` (the researcher while the assignment is live:
+Rsr), the denial that got furthest when neither passes (`require_any`) → 409
`project_archived`, `awaiting_moderation`, `idea_closed` (the assign rule's c5) → 409
`research_step_off` → apply: nobody is assigned (`researcher_id`,
`research_assigned_at` null), **the due date is kept**, emit `researcher_changed
{…, to_researcher_id: null, handed_back: <the actor was the researcher>}`, audit
`idea.researcher_change` (`reason: handed_back` or `removed`). **204**, also when nobody
was assigned (no event). A guest researcher's access ends with the request; the SPA then
leaves the idea page (§10). API keys: `write` (removing only takes access away). A closed
idea or a project without the step never has a researcher (closing and turning the step
off clear it, §3.5), so the 409s there only answer a request with nothing to remove. In an
archived project the assignment is kept but suspended (not live, c24): the researcher has
no +Rsr (their "Hand back" is 403, 404 for R), and the owner and admins get 409
`project_archived` like every idea write; after unarchiving they can remove it.

### 3.5 What ends an assignment by itself: deactivation, closing, the step turned off

Three events clear the assignment without anyone removing it, the same way: in the
request's transaction, `researcher_id` and `research_assigned_at` set null, **the due date
kept**, one `idea.researcher_change` audit entry per idea (`reason` below, actor: whoever
made the change), **no activity event and no notification** (the status change or the
settings change explains it; deactivation emits nothing on ideas, as for owners). Answers
stay (`answered_by` names their author). Nothing restores it later (reactivating,
reopening or turning the step on again: the owner does the research until someone assigns
it again).

| Event | Clears | `reason` |
|---|---|---|
| **Deactivating a user** (`update_admin_user {is_active: false}`, after the user row update, as it ends sessions and revokes keys) | every assignment they hold | `deactivated` |
| **Closing the idea** (`change_idea_status` to Closed, any resolution; review S8) | that idea's | `closed` |
| **Turning the project's research step off** (`replace_research_settings` with `step: off`; moving the step keeps them) | every assignment in the project | `step_off` |
| **Losing one's role in a private project** (§17: the product owner's answer to review S1 (b)) | that person's assignments in the project | `left_project` |
| **Making an internal project private** (`update_project {visibility: private}`; §17, the lead's D2) | the project's assignments whose researcher has no role in it | `made_private` |

- **`soundings anonymise-user`** runs on deactivated accounts only, so the account holds no
  assignment by then (review C3: nothing to clear; a test pins it). Its answers stay under
  the placeholder name.
- **Why closing and the step end it** (review S8, product owner to confirm): removal is
  refused on a closed idea and with the step off (the product owner's rule), so a dormant
  assignment would come back with its guest access on reopening or turning the step on,
  without anyone deciding it. An archived project only suspends it (c24): archiving is a
  reversible freeze of the whole project, members included.
- **Lock order** (review S4; no deadlock, no inactive researcher):
  - **Deactivation** updates the `users` row first, then reads the projects of the ideas
    the user researches and locks them `FOR KEY SHARE` **ordered by id**, then the ideas
    `FOR UPDATE` **ordered by id**, then clears them (the project-then-idea order of every
    idea write, so it can't deadlock with `replace_rubric`, which takes the project
    `FOR UPDATE` before its ideas).
  - **Closing** already holds the idea (`load_idea(for_update=True)`); **the step off**
    already holds the project `FOR UPDATE` and then updates its ideas.
  - **An assignment** locks the project and the idea, then the new researcher's `users`
    row `FOR SHARE` (only when the researcher changes to them). So a deactivation either
    commits first (the assignment sees an inactive user: 422) or waits for the assignment
    and then clears it.
- The policy never relies on this alone: a deactivated person can't sign in or use a key,
  and every recipient check drops inactive users (§6).

### 3.6 Feed events

| Type | Payload (stored) | API (`ActivityItem`) | Feed sentence (SPA) |
|---|---|---|---|
| `researcher_changed` | `{from_researcher_id, to_researcher_id, handed_back}` | `ResearcherChangedActivity {from_researcher, to_researcher, handed_back}` | "asked Bob Brown to research" / "asked Bob Brown instead of Ann to research" / "removed Bob Brown as researcher" / "handed the research back" |
| `research_due_date_changed` | `{from_due_at, to_due_at}` | `ResearchDueDateChangedActivity` | "set the research due date to Fri 9 Oct" / "removed the research due date" |

No score data; visible to everyone who can view the idea (R too: both are in
`RESEARCH_GUEST_ACTIVITY_TYPES`, §4.4). They join
`ACTIVITY_TYPES` and `app.services.activity.PAYLOAD_KEYS` together when backend emits
them (an import-time guard ties the two; until then `PHASE8B_ACTIVITY_TYPES`).

### 3.7 What else changes the assignment's meaning

| Event | Effect |
|---|---|
| The researcher joins the project | They hold a role: their column (Mem, Vwr, PAd) + Rsr instead of R. |
| A member researcher loses their role in a private project (an admin removes them or a group grant, a group membership or the group goes, a sign-in group sync) | **Cleared** (§17, the product owner's answer to review S1 (b)): audited `left_project`, answers kept, no feed event or notification; they never become R through it. |
| The project's visibility changes | Private → internal: R becomes NMi + Rsr. Internal → private: a researcher without a role there is **cleared** (§17, the lead's D2: audited `made_private`, answers kept, no feed event or notification), so nobody becomes R by it; project admins see how many people that is first (`Project.outside_researcher_count`). |
| The owner changes | Nothing (an explicit researcher stays; with nobody assigned the new owner does the research). |
| The idea is closed, or the project's step turned off | Cleared (§3.5, review S8): nobody is assigned; reopening or turning the step on again doesn't bring it back. |
| The project is archived | Suspended, not live (c24): no R access (404), no +Rsr, no reminders, not in My work; unarchiving brings it back (archiving freezes the whole project). |
| The idea is deleted | Gone, with its notifications (cascade). |
| The researcher is deactivated | Cleared (§3.5). |

## 4. Researcher access: the security design

The full table is [role matrix table L](../role-matrix.md#l-researcher-access-phase-8b)
(every rule's R and +Rsr cell, every route and MCP tool's R outcome). This section
explains it and fixes the shapes.

### 4.1 One policy module, a column and an overlay

- **Column R** (role matrix section 1): an active person with no effective role in a
  **private** project who is **the idea's researcher while the assignment is live**
  (c24). The policy's column function returns R only for **idea-scoped** rules on **that
  idea** (it reads `IdeaFacts.researcher_id` and the live facts: the project's step, the
  idea's status, the project's archived flag); for project-scoped rules and every other
  idea it returns NMp as before. R's cells deny by default: anything not granted in table
  L is 403 (R can see the idea) or 404 (part of the idea R may not know exists).
- **Overlay +Rsr**: unlike +Own and +Evl it counts **without** a role, in every column
  (Vwr, NMi, R; for Mem, PAd, PA it adds only "Hand back" and, for members, answering),
  while the assignment is live.
- Nothing outside `app/authz/` branches on "is this a guest": services ask the policy
  (`can(…, Rule.PROJECT_VIEW …)` for `can_view_project`, `evaluation.view_own` for the
  evaluation area and the feed's evaluation events, `proposal.view` for anything about the
  proposal, the ✱ rules for score data), its SQL forms in `app.authz.queries` for lists
  (§4.5), and the route table below.

### 4.2 Live (c24)

Live = assigned, the project's research step on, the idea not closed, the project not
archived. Not live: R doesn't apply (the person is NMp: 404) and +Rsr grants nothing.
Closing the idea and turning the step off **clear** the assignment (§3.5, review S8), so
in practice only an archived project leaves an assignment that isn't live; unarchiving
brings the access back with it. The policy still checks all three facts (defence in depth:
a closed idea or a project without the step never grants R, whatever the data says).

### 4.3 Internal and private projects

| The researcher in the project | Their view of the researched idea | What the assignment adds |
|---|---|---|
| PA, PAd, Mem | Their column's | Answering (Mem), "Hand back" |
| Vwr | Viewer's (scores, proposal read) | Answering, commenting, "Hand back" |
| no role, **internal** project (NMi) | NMi's (the board with scores, the proposal) | Answering, commenting, "Hand back" |
| no role, **private** project | **R**: the guest view (§4.4) | (R includes them) |

Assignment adds and never takes away: an internal non-member could already see the board
with scores, so being researcher there grants no guest view, only the three actions.

### 4.4 The guest shape (R)

`get_idea` for R returns `IdeaDetail` with:

| Field | For R |
|---|---|
| `title`, `summary`, `description_md`, `tags`, `status`, `resolution`, `status_label`, `owner`, `submitted_by`, `via_public_form`, `vote_count`, `has_voted`, `comment_count`, `created_at`, `last_activity_at`, `watching`, `research`, `researcher`, `research_due_at`, `project` (`ProjectRef`: name and key, shown as text) | as for anyone |
| `score`, `aggregate` | null |
| `score_hidden` | true |
| `high_disagreement` | false |
| `evaluators` | `[]` |
| `evaluator_progress` | `{submitted: 0, total: 0}` |
| `evaluation_due_at`, `evaluation_closed_at` | null |
| `evaluation_open` | false |
| `held_for` | null (a held idea has no researcher) |
| `permissions` | `can_comment`, `can_hand_back_research` true while live, `can_answer_research` while live and the idea is in Research or a status before it (c26, §17); `can_view_project` **false**; every other flag false (`can_vote`, `can_change_status`, `can_assign_researcher` …) |

Every `IdeaSummary` (and MCP `McpIdeaSummary`) built for R (MCP `search_ideas`, the only
list that returns summaries of a guest's idea, §4.5) has the same score and evaluation
fields, from the SQL forms of the same rules (review M1): `score_visible` also requires
the idea's project to be one the caller can view, and `evaluator_progress` and
`my_evaluation` come only with `evaluation.view_own` (its SQL form: the project is one the
caller can view). MCP `get_idea` / `search_ideas` give `has_proposal: false` and no
proposal permission without `proposal.view`. `get_idea_research` is the same for R as for
anyone (it holds no score data) with `permissions {can_answer: true (until Research ends, c26), can_override: false,
can_assign: false, can_hand_back: true}` and `gate_status_label` (R can't read the
project's labels).

**The feed for R** (review M2): `list_idea_activity` returns to a caller without
`evaluation.view_own` on the idea only the types in
`app.schemas.activity.RESEARCH_GUEST_ACTIVITY_TYPES` — comments, `idea_created`,
`idea_edited`, `status_changed`, `owner_changed`, `ai_research_note`,
`researcher_changed`, `research_due_date_changed` — an **allow-list**, so a type added
later stays hidden from guests until someone adds it. The evaluation events
(`EVALUATION_ACTIVITY_TYPES`: `evaluator_added`, `evaluator_removed`,
`evaluation_submitted` (AI agents' too), `evaluation_closed`, `evaluation_reopened`,
`due_date_changed`) would rebuild the evaluation area (who evaluates, who submitted, the
window), so R never gets them; the filter is in the query (cursors page over the filtered
feed). `tests/test_schemas_phase8b.py` checks the two sets split every type. Every other
caller gets the whole feed. `StatusChangedActivity.from_label` / `to_label` carry the
project's labels (review C6), so a guest's sentences match the idea's `status_label`.

### 4.5 Lists: search, ⌘K, My work, the inbox, Similar ideas

`app.authz.queries.listed_ideas` / `viewable_ideas` **don't change** (review C1): every
list, board, count, tag list, My work's owned groups and `recent`, `list_my_owned_ideas`
and `list_projects`' counts stay project-scoped, so a list nobody thought about never
shows a guest's idea. A new helper, **`researched_ideas(principal)`**, is the `WHERE`
over `ideas` for the ideas a **person** researches with the assignment live
(`researcher_id = :me`, the step on, not closed, the project not archived, not held,
inside a key's projects, the key with `read`; never a service account): one index range
on `ix_ideas_researcher_id_status`. **Only these lists** use `listed_ideas(p) OR
researched_ideas(p)`:

- `global_search` / ⌘K: the idea (`IdeaRef`, no scores); never its project (projects
  follow `project.view`) or its other ideas.
- MCP `search_ideas`: the idea, with the guest shape's fields (§4.4: `score_hidden`, no
  progress or evaluation state, `has_proposal: false`).
- My work's "Research to do" and its counts (§7; the researcher's branch is
  `researched_ideas` itself).
- The inbox (`list_notifications`, `get_notification_summary`,
  `mark_all_notifications_read`): notifications about an idea in `listed_ideas` as
  before; about an idea **only** in `researched_ideas`, only the types in
  `RESEARCH_GUEST_NOTIFICATION_TYPES` (status changes, comments, mentions, "Asked to
  research", research reminders; review S5), so an evaluator's or owner's older items
  stay hidden from a former member who is now its guest. Access ending hides them at
  once; their emails are cancelled at send time by the same check (§6.1).
- "Similar ideas" (from any idea): the candidates are `listed_ideas OR researched_ideas`
  (filtered before the limit), so a guest's other researched ideas may appear; the
  private project's other ideas never.

The score masks in lists (`score_visible`, `visible_aggregate_score`,
`visible_high_disagreement`) also require `Idea.project_id` to be in the caller's
viewable projects (review M1; one more hashed subplan, no extra statement), so even a list
that let a guest's idea through could never show its score or sort by it; the
`tests/authz/test_queries.py` equivalence test gains guest rows (R, NMi + Rsr, a stale
owner). Boards and lists of the project are `project.view` (404 for R).

### 4.6 When access ends

Unassigned (removed, handed back, reassigned), the idea deleted or closed, the step
turned off (both clear the assignment, §3.5), the project archived (suspends it), or the
researcher deactivated: **the next request is 404** for everything of the idea (nothing is cached server side: every request
re-evaluates the policy; API responses are `Cache-Control: no-store`). R can't open an
AI event stream (the AI routes are 404 for R), so no stream outlives the access; the SPA
drops the idea's cached queries on a 404 and leaves the page. Notifications already in
the inbox disappear from it; queued emails about the idea are cancelled at send time
(`idea.view` re-check, contract-phase3 §3.9).

### 4.7 API keys and MCP

- **Key ∩ person ∩ policy**, as always: a guest researcher's unrestricted key with `read`
  reads the idea as R (`write`: answers, comments, hands back). A key restricted to
  projects names, when it is made, projects its owner can view then (`create_my_api_key`):
  a key made after they lost (or before they had) a role in the private project can't
  name it, so it never reaches the idea (404); a key made **while they were a member**
  still lists that project, and then reaches the idea only as R does (the person's
  live column decides; the key never adds anything). Review C2: the tests cover both.
- **Assigning is session only** (review M3): `set_research_assignment` is `session` in
  `ROUTE_KEY_ACCESS` (403 `insufficient_scope` for every key, before the route), because an
  assignment can open a private idea to any account and would outlive a leaked key that is
  later revoked. `remove_researcher` takes a `write` key (it only takes access away).
- **MCP:** `get_idea` (the guest shape, `research_guest: true`), `search_ideas` (the idea,
  `score_hidden`), `add_comment` (+Rsr, `write`); `get_rubric`, `get_proposal`,
  `create_idea`, `propose_proposal_section`, `submit_evaluation` → `not_found`;
  `list_projects` leaves the project out. `McpResearch` gains `researcher` (`McpUser`,
  the display name untrusted) and `due_at` for everyone. MCP never reaches beyond REST.
- **Agents' research runs read as the guest would** (Phase 8b guest review M1; role matrix
  c22): their note lands in the feed R reads, so a research run's agent reads only
  `search_ideas` and `get_idea` (in the guest shape, `research_guest: true`; both name the
  idea's project); `get_rubric`, `get_proposal` and (adversarial check L1, §17)
  `list_projects` are `ai_run_not_active` there. Evaluate and drafting runs read as before
  (drafting is the research assistant's only proposal read).
- **Agents** never assign (REST is refused to them, c22; they are never owners or admins)
  and are never assigned (c23).

### 4.8 Implementation notes (identity and backend)

- `IdeaFacts` gains `researcher_id`; the column function (`_column`) returns R as defined
  above; `authorize` adds the +Rsr grant without the role requirement of the other
  overlays; c23 is `Resource.researcher_eligible` (unset fails); c24 is computed from the
  facts (no request input).
- **Route table** (deny by default): a mapping from every idea-scoped operation and MCP
  tool to `view` / `rule` / `hidden` for R (table L), e.g. `app.authz.guest`, applied
  where the idea is loaded (`ideas.load_idea` knows the operation from the route, as the
  key gate does); a missing row is `hidden`, and a meta-test fails for an idea route or
  tool without one. It is the safety net for reads that check only `idea.view` today (the
  evaluations list, AI runs and their stream, the submission panel, proposal reads).
- The evaluation area of `IdeaDetail` (evaluators, progress, evaluation dates;
  `ideas.idea_detail` builds evaluators and dates today without asking) is built only when
  `evaluation.view_own` allows it (every column that views an idea holds it; R doesn't),
  and score fields follow the ✱ rules (404 for R = hidden).
- **Every read outside the policy today** (review M1), with its fix: `queries.score_visible`
  (and so `visible_aggregate_score`, `visible_high_disagreement`, `sort=score`) adds
  `Idea.project_id IN (viewable projects)`; a new SQL form of `evaluation.view_own` (e.g.
  `queries.evaluation_visible`, the same project condition) gates
  `summaries.summary_fields`' `evaluator_progress` and the row's `my_evaluation` state
  (else `{0, 0}` and none); MCP `get_idea`'s `has_proposal` (a raw `find_proposal`) and
  `can_suggest_proposal_section` need `proposal.view`; `feed.list_activity` filters by
  `RESEARCH_GUEST_ACTIVITY_TYPES` without `evaluation.view_own` (§4.4); the inbox by
  `RESEARCH_GUEST_NOTIFICATION_TYPES` for guest-only ideas (§4.5). Identity owns the SQL
  forms and their equivalence tests; backend the call sites.
- `can_view_project` = `can(principal, Rule.PROJECT_VIEW, project resource)`; also on
  `WorkResearch` (review S7), so My work links the project only when it may. Search and
  inbox rows carry no flag: the SPA links a project there only when it is in
  `list_projects` (the sidebar's list), else shows its name as text.
- The SSE stream's 30-second re-check uses the same route table (`hidden` for R), so a
  member researcher removed from a private project mid-stream loses the stream too.

## 5. Answering, the gate and the checklist

- `idea.answer_research` = the owner (member or admin), **the researcher (+Rsr, any
  column, guest included, while live)**, project admins and platform admins; c5; idea
  write; `research_step_off`. `ResearchPermissions.can_answer` / `IdeaPermissions.can_answer_research`
  follow.
- **Phase 8's M1 rule stays** for the owner and admins: once the idea is past Research a
  required item's answer can be edited but not cleared (409 `research_answer_required`).
- **Past Research the researcher stops** (§17, the lead's D1, condition c26): a researcher
  who isn't the owner (with a member or admin role) or a project or platform admin
  answers, edits and clears only while the idea is in Research or a status before it;
  afterwards every answer, edit or clear of theirs is **409 `research_finished`** (session
  or key) and `can_answer_research` / `can_answer` are false for them. The SPA shows them
  the answers read only, with one line saying why.
- **The gate and "Move anyway" are unchanged.** A researcher can't override
  (`idea.research_override` stays project and platform admins', session only) and can't
  move the idea (`idea.change_status` is the owner's and admins'): when the checklist is
  complete the owner moves it on. A guest researcher sees `blocking` and the gate status
  label on the panel.
- Answers record `answered_by` / `updated_by` as before (the researcher's name, guests'
  included); the exports' appendix prints them.

## 6. Notifications and reminders

### 6.1 Types

| Type | Trigger | Candidate recipients | Type condition (at creation and at send) | Payload | `dedupe_key` |
|---|---|---|---|---|---|
| `researcher_assigned` ("Asked to research") | `researcher_changed` with a new researcher | the new researcher (not when they are the actor) | *R* is the idea's researcher now and the assignment is live (c24) | `{due_at, assigned_at}` (the research due date after the request, may be null; `research_assigned_at` of this assignment: the inbox, the digest and the send-time check keep only the live one) | `researcher_assigned:<event id>`: one per assignment (§17: replaces review S6's once per idea, person and day, which swallowed a real re-assignment) |
| `research_reminder` | the hourly reminder scan (§6.3), no event | the researcher, or the owner while nobody is assigned | *R* does the research, may answer it (`idea.answer_research`, review S3) and it is still to do (`research_to_do`, §7) with a due date; the due date is still `due_at`; *now* < `due_at` | `{due_at, days_before, as_owner}` | `research_reminder:<idea id>:<local due date>:<days_before>` |

Both: in-app inbox items, email per the recipient's preference (default **immediate**,
`DEFAULT_MODES`), `digest` puts them in the daily digest, `off` stops the email; per-type
unsubscribe links (`UnsubscribeScope`), the footer's "all" link, `List-Unsubscribe`;
`NotificationPreferencesUpdate` gains both keys; the preference page lists them after
the Phase 3 types. **Migration 0015** gives `off` rows for both to anyone who had every
earlier type off, so "Unsubscribe from all email" stays all. The fan-out rules of
contract-phase3 §3.3 hold: the actor, inactive users, service accounts and the
break-glass account never get anything; recipients pass `idea.view` now (a guest through
column R); one notification per person per event. **Never score data.**

Phase 3's types, for a researcher (review S3 and S5):

- **`evaluations_complete`** ("All N evaluations are in") also needs the recipient to hold
  `evaluation.view_own` on the idea, at creation and at send: an owner who lost their role
  in a private project and is its guest researcher (R) doesn't get it (the count of
  evaluations is the evaluation area). Nothing changes for anyone else (every other column
  that views the idea holds it).
- `evaluator_invited` and `evaluation_reminder` already need `evaluation.submit_own` (a
  role, c6); `owner_assigned` needs an owner, who has a role when assigned (c4).
- The inbox and the send-time re-check use the same functions, so an item or email of a
  type R can't hold (`RESEARCH_GUEST_NOTIFICATION_TYPES`) is hidden or cancelled for a
  guest (§4.5).

### 6.2 "Asked to research"

- From the fan-out of `set_research_assignment` (its `researcher_changed` event, after
  the request's last write, so `due_at` is the final one). **Throttled** (§17, the lead's
  D3): when the idea asked someone less than 5 minutes before, the email waits 5 minutes
  (`RESEARCHER_EMAIL_HOLD`; the send-time check cancels it if that assignment is over), and
  one person's requests email at most 20 people per rolling hour (`RESEARCHER_EMAIL_CAP`;
  beyond: in-app only, like mentions). Assigning yourself notifies
  nobody; reassigning to someone else notifies the new researcher only; removal and hand
  back notify nobody.
- Inbox: `ResearcherAssignedNotification {due_at}` ("Alice asked you to research TOOLS-12
  · due Fri 9 Oct"). Link `/ideas/<KEY>?research=1` (opens the idea at its Research
  panel; after sign-in the `next` parameter keeps the query).
- Email: subject `[TOOLS-12] Please research "<title>" by Fri 9 Oct` (the research due
  date when the email is sent; none: without "by …"); body: who asked, the idea's key,
  title and project name, the due date, one button "Open the research checklist", and for
  a **guest researcher** (no role in a **private** project: column R; review S2) one line
  "You'll see this idea, its comments and activity and its research checklist, not its
  scores, evaluations or proposal." (nothing for a researcher with a role, or without one
  in an internal project, who sees more). Footer: "You're researching TOOLS-12".
- The idea's watchers aren't told (the feed line says it); the owner isn't either.

### 6.3 Research reminders

- The same hourly `notification_schedule` job as evaluation reminders scans open ideas
  with a research due date (`ix_ideas_research_due_at_open`) in projects with the step on,
  not archived, not held, whose research is still to do (`research_to_do`: not past
  Research and a required item open). The recipient is the researcher, or the owner while
  nobody is assigned; they must be an active person passing `idea.view` and
  `idea.answer_research` (review S3: so not an owner who lost their role, internal
  projects included) and the type condition (one function for the scan and the send-time
  re-check).
- **Timing exactly as contract-phase3 §3.7:** for due time *D* (local date *d* in
  `SOUNDINGS_TIMEZONE`) and each *n* in `SOUNDINGS_REMINDER_DAYS` (2 and 0), the reminder
  fires at local date *d − n*, `SOUNDINGS_DIGEST_HOUR`:00, **only on its own local day**
  (missed days aren't caught up), only while *now* < *D*, and — for an assigned researcher
  — only when `fire(n) > research_assigned_at` ("Asked to research" already gave the date).
  No such check for the owner. A changed due date gives new keys; a changed time on the
  same date doesn't repeat them; DST is computed in the zone.
- **Stops** as soon as the research isn't to do any more: every required item answered,
  the idea moved past Research or closed, the step turned off, the due date cleared or
  passed, the researcher changed (the new one gets their own reminders, with their own
  `research_assigned_at`), the project archived, or the recipient may no longer answer it
  (an owner who lost their role). A reminder queued for email is cancelled at send time
  when any of these happened.
- Inbox: `ResearchReminderNotification {due_at, days_before, as_owner}` ("Research for
  TOOLS-12 is due Fri 9 Oct · 2 required items open" is the SPA's wording from the idea's
  current progress; the payload holds no counts). Email subject
  `[TOOLS-12] Reminder: research for "<title>" is due Fri 9 Oct` / `… is due today, Fri 9
  Oct`; footer "You're researching TOOLS-12" or "You own TOOLS-12".
- Worked example (Europe/London, hour 08:00, days 2,0): bob is asked Mon 09:00, due Fri
  17:00 → Wed 08:00 and Fri 08:00. Asked Thu 10:00 for the same date → Fri only. Bob
  answers the last required item Thu → nothing on Fri. Bob hands back Wed 10:00 → the
  owner gets Fri 08:00 (as owner). Nobody assigned and no due date → no reminders (My work
  still lists the idea when it is in Research or the status before it).

### 6.4 Other notifications for the researcher

- The researcher gets `status_changed` for the idea **always** while assigned and live
  (like the owner and evaluators: they have a job on it), and `comment` as a watcher
  (assignment adds the watch; they may unwatch). Closing the idea clears the assignment
  in the same transaction, before the fan-out runs, so the move to Closed reaches a former
  researcher only as a watcher who can still view the idea (never a guest).
- **@mentions** notify people with a role in the project **and the idea's live
  researcher** (guest or not). Members' mention pickers (`search_users?project=`) list
  members; the SPA adds the idea's researcher to them. A guest researcher's own picker
  uses the people directory (`search_users` without `project`, which they may call like
  everyone); mentioning someone who can't view the idea still notifies nobody.
- Emails to a guest researcher name the project (as text) and link only to the idea.

### 6.5 Templates and the digest

- Branded HTML and plain-text templates for both types in `app/templates/email/`, the
  same layout and rules as contract-phase3 §3.11 (escaped text only, no score data, no
  other people's addresses); `soundings email-preview` renders both with sample data
  (one for a guest researcher).
- Digest lines: "Alice asked you to research it (due Fri 9 Oct)", "Research due Fri 9
  Oct" (grouped under the idea as usual).

## 7. My work: "Research to do"

- **Who:** the person doing the research and **able to answer it** (review S3:
  `idea.answer_research`): the idea's researcher while the assignment is live
  (`researched_ideas`, §4.5), or, while nobody is assigned, its owner while the owner
  overlay counts (effective role member or admin; or a platform admin). An owner who lost
  their role, or who is only a viewer now, has nothing here (nor reminders).
- **What** (`app.schemas.research.research_to_do`, one definition for the list, the
  counts and the reminders): the project's step is on and not archived, the idea isn't
  held, it **awaits research** (`awaits_research`: open and not past Research: in
  Research or a status before it) and has **a required item open**; and either you are
  its **researcher** (any status that awaits research), or you **own** it with nobody
  assigned and it is **in Research or the status right before it**
  (`shows_research_progress`), **or a research due date is set**. (So an owner's whole
  pipeline before a "Before proposal" step isn't listed, but a date someone set always
  is.)
- **Order:** overdue first, then soonest due, no due date last (`research_due_at`
  ascending, nulls last), then the idea's id: the keyset `(research_due_at, id)` over
  columns that don't move while paging, exactly like evaluations due (review C3; no
  `last_activity_at`). `overdue` = `research_due_at < now()`.
- **Item** (`WorkResearch`): `idea` (`IdeaRef`), `can_view_project` (review S7: false for a
  guest: show the project as text), `owner`, `as_owner`, `due_at`, `overdue`, `progress`
  (`ResearchProgress`: "2 open" is `required_open`). No score data.
- `Work.research_to_do` holds the first **50** (`RESEARCH_TO_DO_PAGE`),
  `research_to_do_next_cursor` pages on with `GET /me/research-to-do?cursor=`;
  `WorkCounts.research_to_do` (all) and `research_overdue` (the sidebar badge adds them to
  the evaluations', the SPA decides how).
- **Why a cursor route** (review C3 suggested cutting it): with the step "Before
  evaluation" every New idea an owner owns with a required item open is research to do,
  so a busy owner can have hundreds; "Show all" pages like evaluations due.
- **Cheap** (review C4): `get_my_work` gains at most **two** statements (the first 50: the
  researcher's ideas by `ix_ideas_researcher_id_status`, the owner's by
  `ix_ideas_owner_id_status_last_activity_at`, required-open per idea by one grouped
  subquery like `IdeaSummary.research`; and **both counts in one aggregate**, `count(*)`
  and `count(*) FILTER (WHERE research_due_at < now())`), `get_my_work_counts` **one**.
  The Phase 7/8 statement budgets of `tests/perf` grow by those numbers for `my work` and
  the counts route; the p95 budgets hold (§12).

## 8. Changed shapes (field by field)

| Schema | Change |
|---|---|
| `ResearchAssignment` (new) | `researcher: UserRef \| null`, `researcher_in_project`, `assigned_at`, `due_at`, `overdue`. |
| `ResearchAssignmentUpdate` (new) | `researcher_id: uuid \| null`, `due_at: DueAt \| null`, both required; unknown fields 422. |
| `IdeaResearch` | + `assignment`, + `gate_status_label`. |
| `ResearchPermissions` | + `can_assign`, + `can_hand_back`; `can_answer` includes the researcher. |
| `IdeaSummary` (so `IdeaDetail`) | + `researcher: UserRef \| null` (null while the step is off). |
| `IdeaDetail` | + `research_due_at`. |
| `IdeaPermissions` | + `can_assign_researcher`, + `can_hand_back_research`, + `can_view_project` (false only for R). |
| `Work` | + `research_to_do: WorkResearch[]`, + `research_to_do_next_cursor`. |
| `WorkCounts` | + `research_to_do`, + `research_overdue`. |
| `WorkResearch`, `WorkResearchPage` (new) | §7 (`WorkResearch.can_view_project`, review S7). |
| `WorkOwnedGroup.ideas` | the first **10** (description; was 50). |
| `NotificationType`, `NotificationItem` | + `researcher_assigned` (`ResearcherAssignedNotification {due_at}`), + `research_reminder` (`ResearchReminderNotification {due_at, days_before, as_owner}`), after `mention`. |
| `NotificationPreferencesUpdate`, `UnsubscribeScope` | + both types. |
| `ActivityItem` | + `ResearcherChangedActivity`, + `ResearchDueDateChangedActivity`; `StatusChangedActivity` + `from_label`, `to_label` (`str \| null`, the project's labels when read; review C6). |
| `app.schemas.activity` (constants) | + `EVALUATION_ACTIVITY_TYPES`, + `RESEARCH_GUEST_ACTIVITY_TYPES` (the guest's feed allow-list, review M2). |
| `app.schemas.notifications` (constant) | + `RESEARCH_GUEST_NOTIFICATION_TYPES` (the guest's inbox, review S5). |
| `AuditAction` | + `idea.researcher_change`. |
| `RemovedTemplateSection`, `RemovedResearchItem` | + `position` (§12). |
| `search_users` | + `include_non_members` query parameter. |
| MCP `McpResearch` | + `researcher: McpUser \| null` (untrusted name), + `due_at`. |
| MCP `McpIdeaDetail` | + `research_guest`. |
| `DueAt` | moved to `app.schemas.base` (re-exported by `app.schemas.ideas`); returns the value in UTC (§17, review N1; the API shape is unchanged). |
| `Project` | + `outside_researcher_count` (§17, the lead's D2: project and platform admins; null for everyone else). |
| `ideas` (model, migration 0015) | + `ck_ideas_researcher_assigned_at`: `researcher_id IS NULL OR research_assigned_at IS NOT NULL` (review C5). |

New response fields have server defaults (nobody, false, `can_view_project` true, empty
lists, 0, null labels) so the backend keeps building them until it fills them in; the OpenAPI document
still marks them required (generated types have no optional response fields).

## 9. Minimum tests (tests first)

- **Researcher access as a table** (identity, `tests/authz`): role matrix table L, every
  rule × {R in a private project, NMi + Rsr in an internal one, Vwr + Rsr, Mem + Rsr, PAd,
  PA} × the assignment state {assigned, never assigned, unassigned, reassigned to someone
  else, handed back, idea closed (cleared) then reopened (still nobody), step off
  (cleared) then on, project archived then unarchived (suspended, then back), researcher
  deactivated, a member researcher removed from the project} × session and API keys (each
  scope alone; unrestricted, restricted to another project, restricted to this project
  by a key made while a member; review C2). Every idea route and MCP tool of the table
  with its R outcome (`view` allowed, `rule` 403 or allowed, `hidden` 404), and the
  meta-test that each has a row. `tests/authz/test_queries.py`'s equivalence test with
  guest rows (R, NMi + Rsr, a stale owner who is R) for `listed_ideas`,
  `researched_ideas`, `score_visible` and `evaluation_visible` (review M1).
- **No score data for R through any path:** idea detail and MCP `search_ideas` summaries
  (score, progress, `my_evaluation`, `has_proposal`), `sort=score` and the disagreement
  filter wherever a guest's idea could appear, `list_evaluations` / `get_my_evaluation`
  404, **the feed** (none of the six evaluation event types for R, an AI agent's
  `evaluation_submitted` included; review M2), notifications and their emails (each type;
  no `evaluations_complete` for a stale owner who is R; review S3), the inbox (older
  evaluator and owner items hidden; review S5), the digest, search and ⌘K, My work (never
  in owned groups or `list_my_owned_ideas`; review C1), Similar ideas, SSE (404), exports
  (404), MCP `get_idea` / `search_ideas`; with two submitted evaluations and an AI
  evaluation on the idea.
- **Access ends at once:** after removal, hand back, reassignment, deactivation, deletion,
  close, step off and archive, the very next request (REST and MCP) is 404 and the inbox
  drops the idea's notifications; a queued email is cancelled at send time.
- **Assign rules:** `idea.assign_researcher` for every column and overlay (a demoted owner
  can't; c5; archived; c19; `research_step_off`), **every API key 403 `insufficient_scope`
  on `set_research_assignment`, whatever its scopes, and a `write` key may remove or hand
  back** (review M3), c23 for a service account, the break-glass account, a deactivated and
  an unknown user (422), the owner and a non-member allowed; idempotency (no event, audit
  or notification on a repeat); the watch; the events; the audit entries and their
  `reason`; the remove/hand-back route for the owner, admins, the researcher (live and
  not), others (403/404); closing the idea and turning the step off clear the assignment
  (audited `closed` / `step_off`, no event or notification, the due date kept, nothing
  back on reopen or step on; review S8); concurrency: an assignment and a deactivation of
  the same person serialise (never an inactive researcher), and deactivation against
  `replace_rubric` on the same project doesn't deadlock (`tests/ideas/test_lock_order.py`,
  review S4).
- **Answering:** the researcher in every column answers and clears while the idea is in
  Research or a status before it, and past Research gets 409 `research_finished` (§17, the
  lead's D1; the owner and admins keep M1: edit, never clear, a required answer); can't
  override; can't move the idea.
- **Notifications:** "Asked to research" to the new researcher only (not the actor, not on
  removal; once per idea, person and local day however often they are assigned, review
  S6), its email (the guest line only for column R, review S2; link; no score data),
  preferences, digest line, unsubscribe scope; migration 0015's `off` rows for all-off
  users; mentions of a guest researcher notify them.
- **Reminders:** each row of the worked example in §6.3 in the instance time zone (Europe/
  London, across a DST change), the owner when nobody is assigned, every stop condition
  (also an owner who lost their role, internal projects included; review S3), dedupe,
  `fire(n) > research_assigned_at`.
- **My work:** each row of `TO_DO_CASES` (`tests/test_schemas_phase8b.py`) through the API,
  the order (overdue, soonest, none, then id), counts equal the list, paging, guest ideas
  included (with `can_view_project: false`), an owner who can't answer never, archived
  projects and held ideas never; statement budgets (`tests/perf`: +2 for `my work`, +1 for
  the counts).
- **Anonymisation:** `soundings anonymise-user` on a former researcher: no assignment left
  (deactivation cleared it), answers kept under the placeholder name (review C3).
- **Migration:** `tests/test_domain_schema_phase8b.py` and the up/down/up with demo data.

## 10. What the SPA shows

- **Idea sidebar and Research panel:** "Research: Bob Brown · due Fri 9 Oct" (nobody:
  "Research: Sven Lindqvist (owner)"; no date: no "· due"; overdue in the warning tone
  with "overdue" in text; a researcher without a role in the project carries a quiet
  "not in this project" for everyone who sees the line, from
  `ResearchAssignment.researcher_in_project`, so the team sees who outside it reads the
  idea). Owners and admins (`can_assign_researcher`) get "Change" (a small dialog: a
  person picker and a due date) and "Remove"; the researcher
  (`can_hand_back_research`) gets "Hand back" (a confirm, then the page reloads the idea;
  a guest goes to My work with a toast "You handed the research back").
- **The person picker** searches every active person
  (`search_users?project=<slug>&include_non_members=true`); people outside the project
  carry a quiet "Not in this project" marker, and choosing one shows one line: "They'll
  see this idea, its comments and activity and its research checklist, not scores,
  evaluations or the proposal." (in a private project, review S2; in an internal one:
  "They'll be able to answer the checklist and comment.").
  Default (nobody): "You (owner)" when the owner opens it.
- **"Start research"** (the primary action in the status before Research, lead decision on
  Phase 8 review item S3) opens a small dialog: who does the research (default: the owner)
  and an optional due date, then sends `set_research_assignment` (only when someone or a
  date was chosen) and moves the idea into Research (`change_idea_status`).
- **Cards in the Research column** show the researcher's avatar (with their name in the
  card's accessible name: "… researched by Bob Brown").
- **A guest researcher** (`can_view_project` false): the project's name as text in the
  breadcrumb (no link), no evaluation area, no Evaluations or Proposal tab, no AI menu, no
  status menu, no tags editor; one quiet line "You can see this idea because you're
  researching it." With no projects at all the shell works: My work (Research to do), the
  inbox, search, settings; the sidebar's project list says "No projects" without an error
  and no project route is ever called.
- **My work:** "Research to do" above "Ideas you own" (only when there is any): idea,
  project (a link only when `can_view_project`, else text), "2 open", due date (overdue
  first, in the warning tone), "as owner" for the owner's; "Show all" pages with the
  cursor. The sidebar badge counts research to do. Search and inbox rows link a project
  only when it is in `list_projects` (§4.8).
- **The feed:** status sentences use `from_label` / `to_label` when present (the project's
  labels, also for a guest; review C6).
- **Inbox and preferences:** the two types' phrases ("asked you to research", "Research
  due Fri 9 Oct"), Settings → Notifications lists "Asked to research" and "Research
  reminders".
- **Audit log:** `idea.researcher_change` (§13).
- Loading, empty and error states, dark mode, keyboard, 390 px and WCAG 2.2 AA as
  everywhere (`highlight-ring` in the picker's list, focus back on the trigger after the
  dialog closes).

## 11. Demo data (backend's seed)

Through the same services a person uses; keep `dev/README.md`'s who's who coherent
(platform):

- **bob** (a member of CUST and GREEN, **not** of the private Internal Tools) is
  `TOOLS-12`'s researcher, due in 3 days, asked by sven (the owner): bob sees TOOLS-12 as
  a guest, has it in My work and an "Asked to research" in his inbox, and may answer the
  open required item.
- **amara** is `GREEN-6`'s researcher (she owns it; asked by alice, so the assignment is
  explicit and her inbox has "Asked to research").
- **One overdue assignment** for the My work screenshot, e.g. alice (a GREEN member)
  researching `GREEN-5` with a due date 2 days ago.
- Nothing else changes; TOOLS-11 keeps its owner doing the research (nobody assigned).

## 12. Phase 8 review follow-ups (D)

- **My work owned groups:** `WorkOwnedGroup.ideas` holds the first **10** ideas
  (`OWNED_GROUP_PREVIEW`; was 50); `count` and `next_cursor` unchanged. This replaces
  contract-phase1 §3.10's "the first 50 ideas". Then re-measure: if an owner's My work
  and the score-sorted board meet **150 ms** under the best-of-3 rule, their budgets go
  back to 150; otherwise they stay at 200 and the machine's baseline is recorded in
  `docs/test-plans/performance.md` (backend).
- **Removed template sections and checklist items** carry `position` (0-based, where they
  were when removed: archiving keeps the row's last position). Restore puts them back at
  that position (at the end when the list is shorter now). Additive.
- Recorded in [decisions.md](../decisions.md): Phase 8 review M1 (a required answer can't
  be cleared past Research; role matrix §K), L3 (tracking history records the step of
  each move), L4 (no "came from" exception; the SPA offers no Undo the gate would refuse),
  and the 200 ms / best-of-3 rule.

## 13. Audit actions

| Action | When | Target, details | SPA |
|---|---|---|---|
| `idea.researcher_change` | the researcher was assigned, changed, removed or handed back, or cleared by deactivating them, closing the idea or turning the project's step off (§3.5) | idea (project set); `from_user_id`, `to_user_id`, `reason` (`assigned`, `removed`, `handed_back`, `deactivated`, `closed`, `step_off`, `left_project`, `made_private` (§17)), `outside_project` (the new researcher has no role in the project), `rule` | "asked {user} to research {idea}" (with "outside the project" when `outside_project`), "removed {user} as researcher of {idea}", "{user} handed back the research of {idea}", "{user} was removed as researcher of {idea} (account deactivated)", "… (idea closed)", "… (research step turned off)", "… (left the project)", "… (project made private)"; category Ideas |

It needs, in the SPA's same change: its phrase, its category, the mock list and the
exhaustive `Record` in `audit-phrases.test.ts`. The research due date isn't audited (the
feed records it, like evaluation due dates).

## 14. Error codes (new)

| Code | Status | When |
|---|---|---|
| `researcher_not_eligible` | 422 | `set_research_assignment` names a service account, the break-glass account, a deactivated or unknown user (c23). |
| `research_finished` | 409 | `answer_research_item` / `clear_research_item` by a researcher who isn't the owner or an admin once the idea is past Research (c26, §17: the lead's D1); `set_research_assignment` naming a researcher other than the current one once the idea is past Research (§3.3, §17: adversarial check L2). |
| `outside_researcher_needs_admin` | 403 | `set_research_assignment` by the idea's owner (not a project or platform admin) names someone without a role in a **private** project (c25, §17). |

`research_step_off`, `idea_closed`, `project_archived`, `awaiting_moderation` keep their
meanings on the two new writes.

## 15. Contract mechanics

- **`PHASE8B_OPERATIONS`** in `backend/tests/test_contract_routes.py` pins the three new
  operations (routes, ids, 501 stubs in `STUBS`, request validation) apart from
  `CONTRACT` until identity adds their `ROUTE_KEY_ACCESS` rows (`app/authz/keys.py`),
  `ROUTE_RULES` and the research-guest rows, and moves them into `CONTRACT` in the same
  change (the meta-tests index those tables by every `CONTRACT` operation). Expected key
  classification: `set_research_assignment`: **`session`** (review M3);
  `remove_researcher`: `policy`; `list_my_research_to_do`: `read`.
- `search_users?include_non_members=true` answers 501 until backend builds it (the route
  checks the flag); without it the route is unchanged.
- The role matrix's new rows (`idea.assign_researcher`, `idea.release_researcher`) fail
  `tests/authz/test_policy_matrix.py` until the policy follows (by design: the document
  comes first). Table L is parsed by its own test (identity), not by that one.
- New enum members make the exhaustive `match` statements over `NotificationType` in
  `app/notifications/access.py`, `app/notifications/inbox.py` and `app/email/content.py`
  fail `mypy` until backend adds their branches (by design: every type must be handled).
- `PHASE8B_ACTIVITY_TYPES` joins `ACTIVITY_TYPES` with backend's `PAYLOAD_KEYS` (§3.6);
  `EVALUATION_ACTIVITY_TYPES` and `RESEARCH_GUEST_ACTIVITY_TYPES` already count them
  (`tests/test_schemas_phase8b.py` fails for a feed type in neither).
- Frontend: the generated types gain the fields above; `tsc` lists every exhaustive
  `Record` over the new enums and every fixture missing a new required field (the
  frontend builder's list).

## 16. Decisions

The product owner's decisions (C) and the lead's follow-ups (D) are in
[decisions.md](../decisions.md) ("Phase 8b (product owner, 2026-10-08)" and "Phase 8b
contract"); the security design in [ADR 0016](../adr/0016-research-assignment-and-guest-researcher.md).

## 17. Changes after the contract

Builders record additive changes here (date, what, why), as in earlier phases.

### 2026-10-08 · The product owner's answers to review S1 and S8 (backend)

The product owner answered the review's open questions ([decisions](../decisions.md#phase-8b-product-owner-answers-2026-10-08)):

- **S1 (a), accepted: in a private project only project and platform admins name someone
  outside it.** New condition **c25** on the owner overlay of `idea.assign_researcher`
  (role matrix: `+ (c5, c23, c25)`): when the idea's owner, who isn't a project or
  platform admin, names a person **without a role in a private project**,
  `set_research_assignment` answers **403 `outside_researcher_needs_admin`** ("Only a
  project admin can ask someone outside this project to research it."). The owner may
  still name anyone with a role there, themselves included; internal projects are
  unchanged (the owner names anyone). Check order: after the rule's 403, before c23's
  422 (403s come first): an owner naming an unknown id or a service account outside the
  project hears 403, with a role there 422. The person's role is read **after their user
  row is locked `FOR SHARE`** (§3.3), so a removal from the project that commits
  meanwhile is seen. New permission flags (additive, default false):
  `IdeaPermissions.can_assign_outside_researcher` and
  `ResearchPermissions.can_assign_outside_researcher`: with the assign flag in an
  internal project; in a private project only for project and platform admins. The SPA's
  picker offers people outside the project only when it is true (with
  `include_non_members=true`; otherwise it lists members).
- **S1 (b), accepted: losing one's role in a private project ends one's research
  assignments there**, like §3.5's automatic clears: `researcher_id` and
  `research_assigned_at` null, the due date and answers kept, audited
  `idea.researcher_change` with `reason: left_project` (actor: whoever made the change;
  none for a sign-in sync, whose audit actor is the user), no feed event or notification.
  "Losing" = an effective role before the change and none after it, in a project that is
  private; someone who never had a role there (an outsider an admin named) is untouched.
  Every path that can take a role away compares before and after, in its transaction:
  removing a direct member (`remove_project_member`), removing a group grant
  (`remove_project_group_grant`), removing someone from a group
  (`remove_group_member`), deleting a group (`delete_group`), and the sign-in group sync
  (managed mappings; a changed mapping applies at the next sign-in). Changing a role
  (admin, member, viewer) keeps a role, so nothing ends; deactivation already clears
  everything (`deactivated`). Locks: the project paths hold the project `FOR UPDATE`
  (an assignment holds it `FOR KEY SHARE`, so the two serialise), and deleting a group
  locks its granted projects `FOR UPDATE` in id order the same way; a group membership
  change and the sync lock the user row (`group_sync.lock_user`), which the assignment's
  `FOR SHARE` on the new researcher waits for; then the cleared ideas' projects
  `FOR KEY SHARE` and the ideas `FOR UPDATE`, each in id order. A project made
  private later (internal → private) ended nothing at first (nobody lost a role); the
  lead's D2 (below) changed that.
- **S8, accepted as built:** closing the idea or turning the research step off clears the
  assignment (audited `closed` / `step_off`, the due date kept); reopening doesn't bring
  it back; archiving only suspends it (§3.5, §3.7).

### 2026-10-09 · Review fixes and the lead's decisions on the leftovers (backend, frontend)

The Phase 8b code, guest-access and UX reviews' fixes changed behaviour without a schema
change; the lead then decided what they left open
([decisions](../decisions.md#phase-8b-review-leftovers-lead-2026-10-09), D1-D5):

- **"Asked to research" (code review M1, L2; D3):** `dedupe_key`
  `researcher_assigned:<event id>` (one per assignment) and payload `{due_at,
  assigned_at}` (§6.1); the inbox, the digest and the send-time check keep only the live
  assignment's request. The email waits `RESEARCHER_EMAIL_HOLD` (5 minutes) when the idea
  asked someone less than 5 minutes before; one person's requests email at most
  `RESEARCHER_EMAIL_CAP` (20) people per rolling hour, beyond that in-app only (§6.2).
- **Research runs read as the guest would (guest review M1):** c22's reads depend on the
  run kind; a research run reads `list_projects`, `search_ideas` and `get_idea` in the
  guest shape, `get_rubric` / `get_proposal` are `ai_run_not_active` (§4.7; role matrix
  c22; [mcp.md](../mcp.md)). The guest's `last_activity_at` is the newest event of the
  guest feed (guest review L1).
- **Due dates in UTC (code review N1):** stored, answered and put in the feed in UTC; since
  D5 `DueAt` itself returns UTC (the API shape is unchanged).
- **`project.update` audit details** gained `outside_researchers` when a change makes the
  project private (code review L1): first the number of outside researchers who kept their
  idea; since D2 the number of research assignments the change ended.
- **D1, research finished (guest review L2, code review C1):** past Research, a researcher
  who isn't the idea's owner (with a member or admin role) or a project or platform admin
  can't answer, edit or clear: **409 `research_finished`** (new condition **c26** on the
  +Rsr overlay of `idea.answer_research`, role matrix table L; sessions and keys alike),
  and `IdeaPermissions.can_answer_research` / `ResearchPermissions.can_answer` are false
  for them (§5). The owner and admins keep Phase 8's M1 rule. Check order unchanged: 404
  (the item) → 403 → 409 (`project_archived`, `awaiting_moderation`, `research_finished`)
  → `research_step_off` → `research_answer_required`.
- **D2, made private (code review L1, guest review L4):** `update_project` changing
  `visibility` from internal to private ends, in its transaction (the project is held
  `FOR UPDATE`; the ideas are locked `FOR UPDATE` in id order by the same clear as §3.5),
  every assignment of the project whose researcher has no role there: audited
  `idea.researcher_change` with `reason: made_private` (actor: the admin), answers and the
  due date kept, no feed event or notification (§3.5, §3.7, §13). New field, additive:
  **`Project.outside_researcher_count`** (`get_project`, `update_project`; project and
  platform admins, `project.edit_settings`; null for everyone else): the people researching
  an open idea there without a role. The SPA's visibility change asks first ("N people
  researching ideas here aren't in the project and will lose access") when N > 0. "No
  role" is role-based as in c25 and S1 (b), so a platform admin without a role counts too.
- **D4:** an explicitly assigned owner stays the researcher when the idea changes owner
  (§3.7, unchanged).
- `make gen-api` (additive only): `Project.outside_researcher_count`; descriptions of
  `answer_research_item`, `clear_research_item`, `update_project`,
  `IdeaPermissions.can_answer_research` and `ResearchPermissions.can_answer`. MCP
  `McpIdeaDetail.research_guest`'s description now names the research runs and the masked
  values (`score` and `aggregate` null, `evaluator_progress` 0/0, `has_proposal` false).

### 2026-10-09 · The adversarial check of D1, D2 and the research-run reads (backend, frontend)

No schema change; descriptions only (`make gen-api`: `set_research_assignment`,
`IdeaPermissions.can_assign_researcher`, `ResearchPermissions.can_assign`; MCP
`McpIdeaDetail.research_guest`).

- **L1, research runs and `list_projects`:** a research run's `list_projects` returned the
  project's description, idea count and the agent's role, which a guest of a private
  project can't read (404). It is now `ai_run_not_active` in a research run
  (`app.ai.scope.RUN_READ_TOOLS`); `get_idea` and `search_ideas` name the project (id,
  slug, key, name). Evaluate and drafting runs list the run's project as before (§4.7).
- **L2, nobody new past Research:** after D1 a researcher named past Research could only
  read the idea (and was told "Please research"). `set_research_assignment` naming a
  researcher **other than the current one** once the idea is past Research is **409
  `research_finished`** (after the 403s, the 422 and the other 409s; for owners and admins
  alike, whoever is named). Removing (`researcher_id: null` or `remove_researcher`),
  handing back and keeping the same researcher (a due-date change) still work; moving the
  idea back to Research lets the owner ask again. `can_assign` / `can_assign_researcher`
  are unchanged (they cover Remove); the SPA shows **Remove** instead of Change past
  Research (a confirmation that says why), and nothing while only the owner does it.
- **N1, the "Make this project private?" count:** the SPA reads the project again on Save
  before deciding whether to warn, so an outsider asked while the settings page was open
  is counted.
- **N2, an unsaved answer past Research:** an answer typed but not saved when the answers
  turn read only (the idea moved on) stays visible under its item, with Copy and Discard
  (Undo), and comes back from the browser's drafts like before.

## 18. Contract review (2026-10-08)

An adversarial review of this contract (read-only, with the migration run on demo data)
found three must-fix gaps, eight should-fix items and eight to consider. Each, and what
changed:

| Item | Finding | What changed |
|---|---|---|
| **M1** (must) | Scores reached a guest through SQL lists: `listed_ideas` was to gain the guest branch, while `score_visible` only checks "not a pending evaluator" and summaries always fill `evaluator_progress` (MCP `search_ideas`, a stale owner's owned lists, `sort=score`); `idea_detail` builds evaluators without asking; MCP `has_proposal` reads the proposal directly. | `score_visible` also requires the idea's project to be viewable; progress and `my_evaluation` follow `evaluation.view_own` (its SQL form); `has_proposal` needs `proposal.view`; the evaluation area of `IdeaDetail` only with `evaluation.view_own`; `test_queries.py` gains guest rows (§4.4, §4.5, §4.8, §9; role matrix rule 11). |
| **M2** (must) | The feed rebuilt the hidden evaluation area: table L gave R "the whole feed", which carries evaluator and evaluation events (AI agents' included). | An allow-list, `RESEARCH_GUEST_ACTIVITY_TYPES`, for callers without `evaluation.view_own`; the six `EVALUATION_ACTIVITY_TYPES` never reach R; a schema test makes every new type pick a side (§4.4; table L; rule 11). |
| **M3** (must) | A leaked `write` key of an owner or platform admin could assign the attacker's account on every private idea, and that access outlived revoking the key. | `set_research_assignment` is **session only** (`session` in `ROUTE_KEY_ACCESS`); `remove_researcher` keeps `write` (§2.1, §3.3, §4.7, §15; role matrix §5). |
| **S1** (should; product owner) | Any member can volunteer as owner of an unowned idea and open it to any account; a member removed from a private project (by an admin or a group sync) keeps guest access to the idea they research. | **Not changed: the product owner's rules stand** (anyone may be assigned by the owner; access ends when unassigned, deleted or deactivated). Recorded as an open question with two costed options in [decisions.md](../decisions.md) ("Phase 8b contract review"); meanwhile everyone who sees the idea sees "not in this project" next to an outside researcher (§10), the feed records every assignment and the audit marks `outside_project`. |
| **S2** (should) | The picker line left out comments and activity; the email's guest line was wrong for internal projects. | Both lines say "this idea, its comments and activity and its research checklist, not scores, evaluations or the proposal"; the email line only for column R (§6.2, §10). |
| **S3** (should) | A stale owner who is R would get "All N evaluations are in"; "Research to do" and reminders didn't require being able to answer. | `evaluations_complete` needs `evaluation.view_own`; "Research to do" and reminders need `idea.answer_research` (so not an owner who lost their role, internal projects included) (§6.1, §6.3, §7). |
| **S4** (should) | Deactivation updated idea rows without locking their projects first (deadlock with `replace_rubric`). | Deactivation locks the projects `FOR KEY SHARE`, then the ideas `FOR UPDATE`, both ordered by id; a lock-order test (§3.5, §9). |
| **S5** (should) | The inbox filters by idea only, so a former evaluator or owner turned guest still saw old evaluation items. | For an idea seen only as its guest: only `RESEARCH_GUEST_NOTIFICATION_TYPES` (§4.5, §6.1). |
| **S6** (should) | "Asked to research" deduplicated per event: assigning and removing repeatedly could email anyone in the directory. | `dedupe_key` `researcher_assigned:<idea id>:<local date>`: once per idea, person and day (§6.1). |
| **S7** (should) | My work, search and inbox rows didn't say whether the project may be linked. | `WorkResearch.can_view_project`; search and inbox link a project only when it is in `list_projects` (§4.8, §7, §10). |
| **S8** (should; product owner to confirm) | Closing the idea or turning the step off hid the guest, but reopening restored the access silently, and removal was refused meanwhile. | **Closing the idea and turning the step off clear the assignment** (audited `closed` / `step_off`, no event or notification, the due date kept; nothing comes back on reopening); an archived project only suspends it. The product owner's "removal only while open" still holds (§3.4, §3.5, §3.7, §4.2). |
| C1 (consider) | Widening `listed_ideas` opens every list, present and future. | Adopted: `listed_ideas` unchanged; `researched_ideas()` only in search, MCP search, the inbox, My work's research and Similar ideas (§4.5). |
| C2 (consider) | "A project-restricted key never reaches the idea" is false for a key made while a member. | Wording fixed (it reaches the idea only as R does; key ∩ person); tests cover both (§4.7, §9). |
| C3 (consider) | Cuts: the cursor route; anonymise clearing; `last_activity_at` in the keyset. | Order `(research_due_at nulls last, id)` and anonymise clearing dropped (a test pins that nothing is left); **the cursor route stays**: before evaluation, every New idea an owner owns with a required item open is research to do, so the list can be long (§3.5, §7). |
| C4 (consider) | Count both research numbers in one statement. | Adopted: +2 statements for `get_my_work`, +1 for the counts (§7). |
| C5 (consider) | A `CHECK` tying `researcher_id` to `research_assigned_at`. | Adopted one way (`researcher_id IS NULL OR research_assigned_at IS NOT NULL`): `ON DELETE SET NULL` clears `researcher_id` alone, and SQLAlchemy can't render Postgres's column list for it; migration 0015, test (§8). |
| C6 (consider) | A guest can't read status labels: feed lines fell back to the defaults. | `StatusChangedActivity.from_label` / `to_label` (nullable: null = the default label) (§2.2, §4.4, §10). |
| C7 (consider) | Lost updates of the full-state PUT; no feed line on deactivation; an ex-guest keeps the automatic watch. | Documented: last write wins (§3.3); automatic clears emit no feed event (the sidebar shows the current state; the audit has it); the watch stays (watchers who can't view get nothing). |
| C8 (consider) | "Research this" left in deploy READMEs, `values.yaml`, `app/ai/notes.py`, the Phase 6 acceptance test and the Phase 6 screenshot spec (which expects the old menu item). | Outside the contract's paths: requests to platform, backend and qa (the lead's report). |
