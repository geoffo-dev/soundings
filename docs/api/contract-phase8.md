# API contract: Phase 8 (per-project proposal templates and the research step)

Phase 8 is a change the product owner asked for after reviewing 0.1.0
([decisions.md](../decisions.md#phase-8-product-owner-2026-10-07), recorded
there because SPEC.md is read-only). Where they differ it **supersedes** SPEC section 2's
"fixed, sensible template" for proposals and its fixed lifecycle ("they can't add or
remove stages"): a project's proposal template is edited like its rubric, and a project
may add one optional stage, Research, at one of two positions. Everything in
[contract-phase1.md](contract-phase1.md) to [contract-phase7.md](contract-phase7.md)
still applies unless a section below changes it.

Source of truth, in order: the Pydantic schemas (`backend/app/schemas/research.py`, and
the Phase 8 parts of `proposals.py`, `ideas.py`, `projects.py`, `ai.py`, `mcp.py`,
`activity.py`, `audit.py`, `public.py`), the route stubs (`backend/app/api/v1/research.py`,
`proposal_templates.py`, the changed routes in `ideas.py`, `proposals.py`, `ai_runs.py`),
the models and migration 0012 (`backend/app/models/research.py`, `proposal.py`,
`project.py`; `migrations/versions/20261007_0012_templates_and_research.py`), exported to
`frontend/src/api/generated/` (`make gen-api`). Rules are named as in
[role-matrix.md](../role-matrix.md) (new: `project.edit_proposal_template`,
`project.edit_research`, table K `idea.answer_research`, `idea.research_override`; c7
widened). Decision record: [ADR 0015](../adr/0015-proposal-templates-and-research-step.md).
`backend/tests/test_contract_routes.py` pins the eight new operations
(`PHASE8_OPERATIONS`, section 7) and the new request fields;
`tests/test_schemas_phase8.py` the lifecycle, the gate and the key rules;
`tests/test_domain_schema_phase8.py` the tables and the migration's data.

## 1. What changes, in one table

| Area | Change |
|---|---|
| Proposal template | Per project: 1–12 sections (key, title 1–60, hint ≤ 200), edited like the rubric; removing archives (text kept, hidden) when anything refers to the section, else deletes; restore by putting the key back. Live: every proposal follows it at once. New projects and every existing project start from today's eight. |
| Section keys | Stable and immutable; the eight keep `summary` … `next_steps`; new ones get a slug from the title. `ProposalSectionKey` is no longer an API enum: section keys are strings matching `^[a-z][a-z0-9_]{0,39}$`. |
| Lifecycle | `IdeaStatus` gains `research`. Project setting **research step**: `off` (default for every project) \| `before_evaluation` \| `before_proposal`. While on, the lifecycle has six statuses with Research at that position; while off, Research exists nowhere in the project. |
| Research checklist | Per project, 1–10 items (title 1–80, hint ≤ 200, required, default on), edited like the rubric. Each idea answers items with free text (1–2,000). |
| The gate | While a required item is unanswered, an idea can't move past Research (status change or board drag, reopening an idea closed before it got past Research, its first evaluator before an evaluation step, starting its proposal before a proposal step): 409 `research_incomplete`. Admins may "Move anyway" (`override_research`, audited). One check in the services (§3.5). |
| Idea page | A Research panel (checklist and answers, progress, "Similar ideas", the existing "Ask AI to research"). |
| Exports | End with a "Research and consultation" appendix of the answered items while the step is on. |
| MCP | Still ten tools. `get_idea` shows the checklist (untrusted answers); `get_proposal` / `propose_proposal_section` use the project's keys. |
| Public tracking | Research is never shown: it is reported as the status before it in the project's lifecycle (`new` before evaluation, `shortlisted` before the proposal), and moves that change nothing shown are left out of the history and the submitter's emails. |

## 2. Per-project proposal templates

### 2.1 Endpoints

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /projects/{slug}/proposal-template` | `get_proposal_template` | `project.view` | → `ProposalTemplate {sections: ProposalTemplateSection[], removed_sections: RemovedTemplateSection[]}` | 404 |
| `PUT /projects/{slug}/proposal-template` | `replace_proposal_template` | `project.edit_proposal_template` (session only) | `ProposalTemplateUpdate {sections: TemplateSectionIn[1..12]}` → `ProposalTemplate` | 403; 404; 422 `validation_error`, `unknown_section` |

`ProposalTemplateSection {key, title, hint, position, proposal_count}` (proposals of the
project with text in the section: the removal warning's N); `RemovedTemplateSection {key,
title, hint, removed_at, proposal_count}` (proposals with text in it, "Text in 3
proposals"; it may be 0, since a section is also kept for a thread, a suggestion or an AI
run), most recently removed first; `TemplateSectionIn {key?, title, hint=""}`. Both work
in an archived project (project settings stay editable, contract-phase1 §2). Both counts
come from one grouped statement over the project's proposals (no per-section query).

### 2.2 Rules

- **Size:** 1–12 active sections (`MIN_TEMPLATE_SECTIONS`, `MAX_TEMPLATE_SECTIONS`).
  Titles 1–60 characters, one line (`SingleLine`: no line breaks, control, bidi or tag
  characters), unique among the request's sections case-insensitively (422
  `validation_error`; the database's `uq_proposal_template_sections_project_id_title_lower`
  backs it). Hints 0–200 characters, one line. Keys in the request unique.
- **Keys** (`SECTION_KEY_PATTERN` `^[a-z][a-z0-9_]{0,39}$`): unique per project among
  **all** its template rows, removed ones included (`uq_proposal_template_sections_project_id_key`),
  and never change. The built-in eight keep `summary, problem, solution, market, cost,
  benefits, risks, next_steps`. A section added without a key gets
  `section_key_for(title, taken)` (`app/schemas/proposals.py`): NFKD-folded to ASCII,
  lower case, every run of other characters one `_`, trimmed, cut to 36 characters,
  `s_` in front of a leading digit, `section` when nothing is left; if `taken` (every
  key of the project plus those given earlier in the same request) has it, `_2`, `_3`, …
  ("Effort & rollout" → `effort_rollout`, "Coût" → `cout`, "2026 plan" → `s_2026_plan`).
  The SPA never shows keys; REST paths, MCP and AI drafts use them.
- **Renaming** (same key, new title or hint) keeps the section's text, threads,
  suggestions and runs. **Reordering** is the list's order (`position` 0…n−1).

### 2.3 Replacing the template (`replace_proposal_template`)

Order of checks: 401 → 422 `validation_error` (shape) → 404 (`project.view`) → 403
(`project.edit_proposal_template`; any API key: 403 `insufficient_scope`) → 422
`unknown_section` (a `key` the project's template has never had, or has deleted) → apply.
In one transaction, with the **project row locked `FOR UPDATE`** (like `replace_rubric`:
section saves, threads and suggestions lock the project `FOR KEY SHARE`, so they wait and
can't write to a section while it is removed):

1. Each requested section, in order: an existing key (active **or removed**) gets the
   title, hint, `position` = its index and `archived_at = NULL` (a removed section is
   **restored**, its text, threads and suggestions with it); a section without a key is
   inserted with a new key (2.2). Any permutation of titles is valid (apply archives,
   then renames, then inserts; a swap needs a temporary title, since the title index
   isn't deferrable).
2. Each active section left out is **removed**: archived (`archived_at = now()`, the
   row and every proposal's text kept) if anything refers to its key: a
   `proposal_sections` row of a proposal of the project with non-empty `body_md`, a
   `proposal_threads` row, a `proposal_suggestions` row (any status) or an `ai_runs` row
   on an idea of the project; otherwise **deleted**, with its (empty) `proposal_sections`
   rows. A deleted section's key may be given out again later; an archived one's never.
3. Every proposal of the project gets the `proposal_sections` rows it lacks for the
   active sections (version 1, empty; `INSERT … SELECT … ON CONFLICT DO NOTHING`), so a
   proposal always has a row for every active section.
4. Audit `project.proposal_template_replace` (target the project; details: the keys
   `added`, `restored`, `archived`, `deleted`, `renamed`, and `reordered: bool`; never
   titles or hints). Nothing changes → 200, no audit entry.

**Last write wins** (no version or `If-Match`), like `replace_rubric`: two admins saving
at once each replace the whole template; the later one is the template. No activity
events, notifications or `last_activity_at` bumps: a template edit is a project setting. Pending suggestions and threads of a removed section stay stored and
come back with it. An AI draft run already running for a removed section is not
cancelled: its `propose_proposal_section` answers `unknown_section` and the run ends
`failed` (`no_result`).

### 2.4 Everything follows the template, live

| Surface | Behaviour |
|---|---|
| `GET /ideas/{idea}/proposal` (`Proposal.sections`) | Every active section of the project's template in order: `key`, `title` and `prompt` (= the section's hint) from the template, `body_md`, `version`, `updated_*` from the proposal's row. Removed sections and their text are left out. |
| `create_proposal` | Creates a row per active section (a section keyed `summary`, if active, starts as the idea's summary; the rest empty). c7 now also allows Research before a proposal step (§3.5); the research gate guards it. Optional body `ProposalStart {override_research?, override_reason?}`. |
| `update_proposal_section` (`/sections/{section_key}`) | `section_key` is a key (422 for a malformed one); a key the template doesn't have, or a removed section's: **404**. |
| Margin threads | `list_proposal_threads` lists threads on active sections only (template order). `create_proposal_thread` with an unknown or removed `section_key`: **422 `unknown_section`**. Replying, resolving, reopening or deleting a comment in a thread of a removed section: 404 (it is hidden). |
| Suggestions (Phase 5) | `list_proposal_suggestions` lists pending suggestions of active sections only; `create_proposal_suggestion` with an unknown or removed key: 422 `unknown_section`; accepting or discarding a suggestion of a removed section: 404. The cap of 50 pending suggestions per proposal (`MAX_PENDING_SUGGESTIONS`, 409 `too_many_suggestions`) counts active sections only, so hidden ones never block a new suggestion; restoring a section can bring the list a little above 50 (no paging). |
| "Draft with AI" (`request_ai_section_draft`) | `section_key` must be an active section of the idea's project (422 `unknown_section`, checked after the 404s and 403, before the 409s). The run message names the section **by key only** (`run_message(..., section_key=)`): a title is a project admin's text and stays out of an agent's instructions (ADR 0014); the agent reads the title and hint in `get_proposal`, marked untrusted. |
| Exports (Markdown, PDF) | The active sections in template order, as before (`## <title>`, "_Not written yet._" for an empty one); removed sections never. Then the research appendix (§3.8). 12 sections fit the PDF limits (they bound boxes, not sections). |
| MCP `get_proposal` | `proposal.sections` = the active sections (key, title, prompt, body, version): an agent or MCP client learns the keys there, so there is no separate template tool (the tool list stays at ten). `propose_proposal_section` with an unknown or removed key: tool error `unknown_section`. `can_suggest` follows the widened c7. |

### 2.5 Existing data (migration 0012)

Every existing project gets the eight default sections (titles and hints of the fixed
template, positions 0–7). Proposal sections, threads, comments, suggestions and AI runs
are untouched: their keys are exactly those defaults, so they all resolve in their
project's template. `tests/test_domain_schema_phase8.py` pins the carry-over row by row
and the downgrade (custom sections and research data are deleted, ideas in Research go
back to the stage before it, every proposal gets its eight default rows back);
`tests/test_domain_schema.py` runs up/down/up and compares the migrated schema with the
models; the up/down/up was also run on a database holding the Phase 7 demo data (lead
report). Two known effects of the downgrade, accepted because a downgrade is an
emergency path: a status change into or out of Research is rewritten to the stage before
Research, so the feed may show a no-op line such as "Shortlisted → Shortlisted"; and a
pending team email (an `outbound_email` row without an idea: only submitter emails name
one) whose payload names `research` gets `new` whatever the project's step was.

### 2.6 Storage: keys, not foreign keys

`proposal_sections.key`, `proposal_threads.section_key`, `proposal_suggestions.section_key`
and `ai_runs.section_key` become `varchar(40)` with a format `CHECK`
(`ck_<table>_<column>_format`); the eight-key `CHECK` is gone and **there is no foreign key
to `proposal_template_sections`**. Why: (1) keys are immutable and a key anything refers
to is archived, never deleted (step 2 above, under the project lock), so a stored key
always resolves within its idea's project; (2) a composite foreign key would need a copy
of `project_id` on all four tables (proposals reach their project only through ideas)
and a backfill of every row; (3) historic rows stay valid without being rewritten, and
the downgrade is a constraint swap; (4) every write validates the key against the
project's template in the same transaction (the services, with the template read under
the project's `FOR KEY SHARE` lock).

### 2.7 What the SPA shows

- **Project settings** gains one tab, **Workflow**, holding "Research step" (§3.13) and
  "Proposal template" (five tabs; `?tab=research` and `?tab=proposal-template` open it at
  the section). The template editor works like the rubric editor: one row per section
  (title, hint), Move up / Move down (and drag), Remove, "Add section" (disabled at 12;
  Remove disabled on the last one), Save. There is no "Reset to the default eight"
  (review item 6: a deleted default's key can't be given back, and restoring is what
  Removed sections is for). Below, **Removed sections** (only when there are any): title,
  "Text in N proposals" (or "Kept for its comments and suggestions" when
  `proposal_count` is 0), Restore (appends it to the form). Removing a section whose
  `proposal_count` is above 0 asks first: "Its text in N proposals is kept and comes back
  if you restore it." Saves are last write wins (§2.3).
- **Proposal editor:** the outline and sections follow `Proposal.sections`; the
  "Draft with AI" section picker and the suggestion cards use the same list. If a
  section is removed while someone is typing in it, its autosave answers 404: the editor
  keeps the unsaved text as a local draft (`lib/drafts.ts`, keyed by idea and section),
  says "This section was removed from the template. Your text is kept here; copy it, or
  ask an admin to restore the section", and stops saving it; it never drops the text
  silently.
- Loading, empty and error states, keyboard, 390 px and dark mode as everywhere.

## 3. The research step

### 3.1 Endpoints

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /projects/{slug}/research` | `get_research_settings` | `project.view` | → `ResearchSettings {step, items, removed_items, default_items, ideas_in_research}` | 404 |
| `PUT /projects/{slug}/research` | `replace_research_settings` | `project.edit_research` (session only) | `ResearchSettingsUpdate {step, items?: ResearchItemIn[0..10]}` (items ignored while `step` is `off`) → `ResearchSettings` | 403; 404; 422 `validation_error`, `unknown_research_item`; 409 `ideas_in_research` (`IdeasInResearchProblem.idea_count`) |
| `GET /ideas/{idea}/research` | `get_idea_research` | `idea.view` | → `IdeaResearch {step, gate_status, items: IdeaResearchItem[], progress, blocking, permissions}` | 404 |
| `PUT /ideas/{idea}/research/items/{item_id}` | `answer_research_item` | `idea.answer_research` (c5) | `ResearchAnswerIn {answer: 1..2000, ≥ 1 visible character}` → `IdeaResearch` | 403; 404 (item not active in the idea's project); 422; 409 `research_step_off`, `idea_closed`, `project_archived`, `awaiting_moderation` |
| `DELETE /ideas/{idea}/research/items/{item_id}` | `clear_research_item` | `idea.answer_research` (c5) | → `IdeaResearch` (idempotent) | as above |
| `GET /ideas/{idea}/similar-ideas` | `list_similar_ideas` | `idea.view` | → `SimilarIdeas {items: SimilarIdea[≤5]}` | 404 |

API keys: the two `GET`s of an idea and the settings `GET` follow `idea.view` /
`project.view` (`read`); answering and clearing follow `idea.answer_research` (`write`);
`replace_research_settings` is session only. An AI agent's key is refused on all of them
(c22: REST is never an agent's). Until identity classifies them, keys are refused on all
eight new operations (deny by default, §7).

### 3.2 The step and the lifecycle

- `projects.research_step` (`ResearchStep`): `off` (every existing and new project),
  `before_evaluation`, `before_proposal`. `Project` / `ProjectSummary` carry
  `research_step` and `lifecycle: IdeaStatus[]` (the project's statuses in board order:
  `app.schemas.research.lifecycle(step)`):

  | Step | Lifecycle (board columns, status menu, filter chips) |
  |---|---|
  | `off` | New → Evaluating → Shortlisted → Proposal → Closed |
  | `before_evaluation` | New → **Research** → Evaluating → Shortlisted → Proposal → Closed |
  | `before_proposal` | New → Evaluating → Shortlisted → **Research** → Proposal → Closed |

- **Canonical order** (`IdeaStatus` order, `CANONICAL_STATUS_ORDER`): new, research,
  evaluating, shortlisted, proposal, closed. Views across projects use it: My work's
  owned groups (a Research group appears only for ideas in Research), ⌘K, search, MCP.
- **Board** (`get_board`): one column per status of the project's lifecycle, in its
  order (six with the step). `list_ideas?status=research` is valid in any project (no
  rows while the step is off), and the SPA keeps `?status=research` in a project's URL
  (the `ideas_in_research` message links the board filtered on Research). Every place
  that assumed the fixed five is listed in §7.
- **Labels:** `StatusLabels.research` (default "Research") and
  `StatusLabelsUpdate.research`, renameable like the others
  (`project.rename_status_labels`); the SPA shows the Research label field only while
  the step is on.
- **While the step is off** there is no Research status, column or checklist anywhere in
  the project: `change_idea_status` to `research` is 409 **`research_step_off`**
  ("This project has no research step"), `IdeaSummary.research` is null,
  `IdeaResearch` is empty, `IdeaPermissions.can_answer_research` false, answering 409
  `research_step_off`, exports have no appendix, MCP `get_idea.research` is null.
  Answers and the checklist given before are kept (hidden) and come back if the step is
  turned on again.
- An idea is created in New whatever the step. Moving into Research is never guarded;
  the checklist can be answered in any status but Closed (c5).

### 3.3 Settings: the step and the checklist (`replace_research_settings`)

Order of checks: 401 → 422 shape (`ResearchSettingsUpdate`: 0–10 items, titles 1–80 one
line and unique case-insensitively, hints ≤ 200 one line, ids unique, **at least one item
while `step` isn't `off`**) → 404 → 403 → 422 `unknown_research_item` (an `id` that isn't
one of the project's items, active or removed; checked only while `step` is on) → 409 →
apply. In one transaction with the project row locked `FOR UPDATE`:

- **Step:** if `step` differs from the current one and any idea of the project is in
  Research: **409 `ideas_in_research`** with `idea_count` (nothing is applied; the SPA
  says "Move the N ideas in Research to another status first" and links the board
  filtered on Research). Otherwise set it; audit `project.research_step_change`
  `{from, to}`.
- **Checklist** (like `replace_rubric`), **only while `step` is on**: each requested item,
  in order, by `id` (active, or removed: **restored** with its answers) or new;
  `position` = index. Items left out: archived if any idea answered them (answers kept,
  hidden), else deleted. Changing `required`, titles or hints is allowed at any time.
  **Changing the checklist never moves an idea** (an idea already past Research stays
  there; the gate only guards the next crossing). Audit
  `project.research_checklist_replace` (details: counts `added`, `restored`, `archived`,
  `deleted`, `changed`) when anything changed.
- **With `step` `off`, `items` is ignored** (it may be left out; the SPA sends `[]`): turning
  the step off keeps the checklist and every answer exactly as they are, hidden, and
  turning it on again brings them back (review item 7: `{step: off, items: []}` must never
  delete a checklist). The checklist can't be edited while the step is off; the SPA shows
  it only while a position is chosen.
- **Last write wins** (no version), like the rubric and the template.
- `ResearchSettings.default_items` is `DEFAULT_RESEARCH_CHECKLIST`: "Not already being
  done elsewhere" (required; hint "Search Soundings and ask around; note what you
  found."), "Departments or teams consulted" (required; "Who you spoke to and what they
  said."), "Data protection considered" (optional; "Personal data involved, and who you
  checked with."). The SPA offers it when the step is turned on while `items` is empty;
  nothing is created until Save. `ideas_in_research` lets the SPA explain the 409 before
  it happens.

### 3.4 Answers

- **Who:** `idea.answer_research`: the idea's owner (while member or admin), project
  admins and platform admins; c5 (not Closed: 409 `idea_closed`); an idea write (409
  `project_archived`; c19 `awaiting_moderation`). Everyone who passes `idea.view` reads
  the checklist and answers (no score data: pending evaluators see them too; role matrix
  table K).
- **Answer** (`PUT`): free text, 1–2,000 characters after trimming the ends (line breaks
  kept; NUL and tag characters refused), stored and shown as plain text (never Markdown).
  Invisible characters (zero-width, bidi controls and the other format characters of
  `app.schemas.base.INVISIBLE_CHARACTERS`, the same set as MCP's `HIDDEN` for agents'
  text; ZWJ/ZWNJ kept) are **removed** before the length check, and an answer must keep at
  least one visible character (422 `validation_error`): a lone zero-width space or bidi
  control is not an answer and never satisfies the gate (review item 4). The schema
  (`ResearchAnswerIn`) does this; the service stores what it validated.
  The item must be an **active** item of the idea's project (else 404) and the step on
  (else 409 `research_step_off`). Upsert: a first answer records `answered_by` /
  `answered_at` (and `updated_*` the same); a change records `updated_by` / `updated_at`
  (the first answer's author and time are kept); identical text changes nothing. **Last
  write wins** (answers are short; no versioning).
- **Clear** (`DELETE`): deletes the answer (unanswered again); idempotent. Clearing a
  required item never moves the idea back.
- Neither is an activity event, a notification or a `last_activity_at` bump (like section
  saves); neither is audited (the record is the answer's own `answered_*` / `updated_*`).
- **Locking:** both load the idea `FOR UPDATE` (project `FOR KEY SHARE` first, the usual
  order), so a guarded request on the same idea sees the checklist before or after the
  answer, never half of it.
- For consultations the product owner wants a free-text box naming the department or
  team and what they said, not a person picker ("Legal (contracts team), 3 Oct: fine if
  we keep the standard terms"). No item types beyond free text.

### 3.5 The gate

**Definition** (`app.schemas.research`, one definition for services, policy and tests):

- `gated_statuses(step)`: the statuses after Research, Closed excluded —
  `before_evaluation`: Evaluating, Shortlisted, Proposal; `before_proposal`: Proposal.
- `crosses_gate(step, from, to, *, closed_from)`: `to` is gated and `from` isn't. When
  `from` is Closed, the move counts **from `closed_from`**, the status the idea was closed
  from: the `from_status` of the idea's latest `status_changed` event whose `to_status` is
  `closed`, read under the idea's `FOR UPDATE` lock (unknown, i.e. no such event: counts as
  New). So Undo of a Close, and reopening any idea that was already past Research (also one
  moved on with "Move anyway", or one that passed before the step was turned on), is never
  guarded, while New → Closed → Evaluating is (review must-fix 2).
- **`required_open`** = the project's active required items this idea hasn't answered.
  The gate **blocks** a guarded request while `required_open > 0`. A checklist whose
  items are all optional never blocks (the step is a guide).

**Guarded requests** (every other path is unguarded):

| Request | Guarded when | Notes |
|---|---|---|
| `change_idea_status` (status menu, board drag, Undo, keyboard) | `crosses_gate(step, from, to, closed_from=…)`: `to` is a gated status and `from` isn't (New, Research or a status before Research; for a closed idea, the status it was closed from) | Moving among gated statuses, back, to Research or to Closed (any resolution) is never guarded. Reopening a closed idea into a gated status is guarded only when it was closed from New, Research or a status before Research. Same status: no-op, not evaluated. |
| `add_evaluators` | `starts_evaluation(step, status, evaluators)`: step `before_evaluation`, the idea has **no evaluator yet** and isn't past Research (New or Research) | The first invite starts evaluation; once one evaluator exists (or the idea is past Research), later invites aren't guarded. A closed idea answers 409 `evaluation_closed` first. |
| `request_ai_evaluation` ("Ask AI to evaluate") | the same as `add_evaluators` (it assigns the agent as an evaluator) | Checked after c10 (`ai_unavailable`), before 429. `AiPermissions.request_evaluation_blocked_by = research_incomplete` (new `AiBlockedReason`, last in the order). |
| `create_proposal` ("Start proposal") | step `before_proposal` and the idea is Shortlisted or in Research (it moves the idea to Proposal): exactly `crosses_gate(step, status, proposal)` | An idea already in Proposal (moved there with the gate passed) just gets its proposal. `ProposalPermissions.start_blocked_by_research` says so. |

Not guarded: creating ideas, moving into Research, evaluators already assigned saving or
submitting (MCP `submit_evaluation` included), the due date, closing or reopening
evaluation, comments, votes, owners, suggestions and drafts (they need a proposal, whose
start is guarded), public submissions and moderation (they stay in New), template or
checklist changes.

**Where the gate lives** (review item 3): one check, called from three services, no bypass.

- `app.services.ideas.change_status` is the **only** code that changes an idea's status
  (the API, the board, Undo, and `create_proposal`, which calls it for its move). It takes
  `override_research` (and the reason) from the request, computes `closed_from` when the
  idea is closed, and runs the shared check when `crosses_gate(...)`. `create_proposal`
  passes its body's override through and moves a Shortlisted **or Research** idea to
  Proposal with it, so its gate, audit entry and `research_overridden` payload are
  change_status's (one audit entry, not two).
- One helper in the research service (backend names it; e.g.
  `app.services.research.check_gate(db, principal, idea, *, operation, to_status,
  override)`) does the check for every guarded path: count the open required items under
  the idea's lock; none open → pass (no audit, the flag ignored); open and no override →
  409 `research_incomplete`; open and override → audit `idea.research_override` and pass.
  `change_status`, `add_evaluators` and `request_ai_evaluation` (each when its
  "Guarded when" holds) call it. The override's permission (403) is checked earlier, at
  the 403 stage, by the same module.
- **No bypass parameter.** The demo seed calls the same services as a person would; it
  either answers the checklist before moving an idea past Research or turns the step on
  after moving its ideas (§3.14). Moderation approval, public submissions, MCP
  `create_idea` and the downgrade never move an idea past Research.

**Order of checks** in a guarded request: 401 → 422 shape → 404 → 403 (the request's own
rule; then, only if `override_research` is true, `idea.research_override`: 403
`forbidden` without it, 403 `insufficient_scope` for any API key, even when nothing would
block) → 422 business codes → 409 (the request's existing codes: c5/c6/c7,
`project_archived`, `awaiting_moderation`, `proposal_exists`, `research_step_off`; for
`request_ai_evaluation` then c10 `ai_unavailable`) → **409 `research_incomplete`** → (429
for `request_ai_evaluation`). The check runs under the idea's `FOR UPDATE` lock (the
guarded routes already take it), so a concurrent answer or clear is fully before or after.

**The problem** (`ResearchIncompleteProblem`, the 409 schema of all four routes):
`code: research_incomplete`, `detail` "Finish the research checklist first: N required
items are open.", `open_items: [{item_id, title}]` (the open required items in checklist
order), `can_override` (the caller holds `idea.research_override`). The route's other 409
codes leave both fields out.

**Move anyway** (`ResearchOverride`, mixed into `StatusChange`, `EvaluatorsAdd`,
`ProposalStart`, `AiEvaluationRequest`): `override_research: true` (omitted, null or
false = no override) and an optional one-line `override_reason` (1–200, only with the
flag: 422 otherwise). When the gate would block and the override is allowed, the request
goes through and is audited **`idea.research_override`** (target the idea; details
`{operation, from_status, to_status, open_items: <count>, reason?}`), and a status change
it makes (also `create_proposal`'s move) stores `research_overridden: true` in the
`status_changed` payload (`StatusChangedActivity.research_overridden`, default false: the
feed says "without finishing research"). When nothing would block, the flag changes
nothing (no audit). Owners can't override: only project and platform admins, in a session.

### 3.6 Reading an idea's research

- `IdeaSummary.research: ResearchProgress | null` (lists, board cards, My work): `{answered,
  total, required_open}` over active items, set **only while the step is on and the idea
  is in Research or in the status right before it** (`shows_research_progress(step,
  status)`: New before evaluation, Shortlisted before the proposal); null otherwise:
  step off, an idea past Research (e.g. ideas that passed before the step was turned on),
  a closed idea, or one further back (a New idea when Research comes before the proposal).
  Cards show "2/3" only when it is set (review item 9).
- **One statement per page** (review item 11): the backend fills `IdeaSummary.research`
  for a whole page (list, board, My work, search) with one grouped query over the page's
  ideas that need it (`shows_research_progress`), and **skips the query** when no project
  on the page has the step on. The Phase 7 statement budgets
  (`tests/perf/test_perf_large.py` `STATEMENT_BUDGET`) stay as they are for projects with
  the step off and allow at most one more statement where it is on; `seed_large` gets a
  project with the step on (and answered ideas) so the kit measures it.
- `IdeaPermissions.can_answer_research`; `IdeaPermissions.invite_blocked_by_research`
  (inviting now would be refused: `starts_evaluation(...)` and `required_open > 0`; "Invite
  evaluators" and "Ask AI to evaluate" say so up front, review item 15). There is **no
  per-card override flag** (review item 14): a refused drag's 409 carries `can_override`,
  and the idea page has `IdeaResearch.permissions.can_override`.
- `IdeaResearch`: `step`; `gate_status` (the status right after Research:
  `gate_status(step)`); `items` (active items in order, each with `answer: ResearchAnswer
  | null` = `{answer, answered_by, answered_at, updated_by, updated_at}`); `progress`;
  `blocking` (= `required_open > 0`, the step on, and the idea neither in a gated status
  nor **closed**: moving it past Research would be refused now; false for every closed
  idea); `permissions {can_answer, can_override}`.
- Removed items and their answers are never shown (they come back with the item).

### 3.7 "Similar ideas"

`list_similar_ideas`: at most **5** ideas, most similar first, whose `pg_trgm`
`similarity()` with this idea is **≥ 0.3** (the `%` operator's default threshold, served
by the existing trigram indexes on `title` and `summary`): the higher of
`similarity(title, :title)` and `similarity(summary, :summary)`, rounded to 2 places,
ties by `last_activity_at` then id. Candidates: ideas the principal passes `idea.view` on
(`listed_ideas`: **never a held idea**, never this idea, a key's project restriction
applied) in **every project they can view, archived ones included** (an archived
project's idea is still evidence it was tried), any status (a closed one shows its
resolution's label). `SimilarIdea` = `IdeaRef` + `summary`, `owner` (whom to ask),
`last_activity_at`, `similarity`: **no score data**, so blind rules are unaffected. The
panel's other help is the existing "Ask AI to research" (Phase 6 research run; its note
lands in the feed as today).

### 3.8 The exports' appendix

While the project's step is on and at least one active item has an answer, the Markdown
and PDF exports end with **"Research and consultation"** after the template's sections
(`## Research and consultation`, a PDF section listed in the contents): each answered
active item in checklist order as `### <item title>`, its answer as **plain text** (in
Markdown every character that could start Markdown syntax is backslash-escaped and each
line break becomes a hard break, so it reads exactly as typed; in the PDF a paragraph
with line breaks), then "Answered by <name> on <date>" (plus ", updated by <name> on
<date>" when changed by someone else or later; dates in the instance time zone).
Unanswered items, removed items and the step's name aren't printed. Exporters who can't
see scores get the appendix too (no score data).

### 3.9 Public tracking

The tracking page never shows Research. One function decides what the submitter sees,
`app.schemas.research.public_status(step, status)`: Research is reported as **the status
before it in the project's lifecycle** (`status_before_research(step)`: `new` before
evaluation, `shortlisted` before the proposal; `new` while the step is off, for history
rows of an earlier step), with that status's label; every other status as itself (review
must-fix 1: a "Before proposal" project's Shortlisted → Research must not drop the
submitter's page to "New").

- `TrackedSubmission.status` / `status_label`: `public_status(step, idea.status)`.
- `TrackedSubmission.history`: each `status_changed` event since the idea reached the team
  **whose reported status or resolution changes** (`public_status(step, from_status) !=
  public_status(step, to_status)`, or the resolution differs), shown as
  `public_status(step, to_status)`. So New → Research and Research → New (before
  evaluation), Shortlisted → Research and Research → Shortlisted (before the proposal) add
  nothing, Research → Evaluating shows Evaluating, Research → Proposal shows Proposal, and
  moving an Evaluating idea back to Research (before evaluation) shows New, as moving it
  back to New would. The step used is the project's current one (it can't change while
  any idea is in Research; history rows of a step since turned off read as `new`).
- **Submitter status emails** (`submission_status_changed`): the same test decides
  whether one is sent, at send time (the email renders the reported status's label); a
  move that changes nothing reported sends nothing.
- The SPA's `statusMeaning` maps `research` like the status before it if it ever arrives
  (it doesn't; the type allows it).

### 3.10 Notifications and emails

No new notification types. `status_changed` notifications and emails cover moves into
and out of Research like any other status (the project's label), to the owner,
evaluators and watchers; never score data. Answers, checklist and template changes
notify nobody.

### 3.11 MCP

- Still ten tools. `McpIdeaRef.status` and `search_ideas.status` (now up to six values)
  include `research`.
- `get_idea.idea.research: McpResearch | null` (null while the step is off): `{step,
  items: [{item_id, title, hint, required, answer, answered_by, answered_at}],
  required_open}`; titles, hints and answers are marked **untrusted** like other people's
  text. Read only: no tool answers items, and an agent's key never does (c22).
- `get_proposal` / `propose_proposal_section`: §2.4. `MCP_INSTRUCTIONS` mentions both.

### 3.12 AI (Phase 6)

- "Ask AI to evaluate" is guarded like an invite (§3.5) and takes the override;
  `AiPermissions.request_evaluation_blocked_by = research_incomplete` says so up front.
- "Draft with AI" uses the project's section keys (§2.4); c7's widening applies to
  `ai.draft_section`. The run message names the section by key only (review item 10);
  the agent reads its title and hint in `get_proposal` (untrusted).
- "Research this" is unchanged and is offered on the Research panel too.

### 3.13 What the SPA shows

- **Project settings → Workflow → Research step:** a segmented control Off / Before
  evaluation / Before proposal with one line saying where Research goes; when turning it
  on with an empty checklist, the default three items fill the form. The checklist editor
  works like the rubric's (title, hint, Required switch with `accent-control`, Move up /
  down, Remove, Add item up to 10, Removed items with Restore) and is shown only while a
  position is chosen (turning the step off saves `{step: "off", items: []}` and keeps the
  checklist; §3.3). While ideas are in Research, the step control is disabled with "Move
  the N ideas in Research first" (`ideas_in_research`, a link to the board filtered on
  Research, `?status=research`), and a 409 says the same. Saves are last write wins.
- **Board and list:** the columns, status menu and filter chips follow
  `Project.lifecycle` (Research where the step puts it). Cards show the checklist
  progress ("2/3", a quiet badge, the open count as text for screen readers) **only when
  `IdeaSummary.research` is set** (an idea in Research or in the status before it; never
  past Research or closed). A drop into a gated column that the API refuses with
  `research_incomplete` snaps the card back and opens a small dialog listing the open
  items, with "Open research" and, when the 409's `can_override` is true, **Move anyway**
  (optional reason, then the same request with `override_research: true`); the same
  dialog for the status menu, "Start proposal", "Invite evaluators" and "Ask AI to
  evaluate". Before a click, "Start proposal" (`ProposalPermissions.start_blocked_by_research`),
  "Invite evaluators" (`IdeaPermissions.invite_blocked_by_research`) and "Ask AI to
  evaluate" (`request_evaluation_blocked_by`) say "Finish the research checklist first"
  (admins keep the button and get the dialog). Undo of a Close works for an idea that
  was past Research (§3.5).
- **Idea page:** a **Research** panel on the Overview (above the feed, collapsible;
  shown only while the step is on): items in order, each with its hint as the
  placeholder of a plain textarea (owner and admins; everyone else reads the answer or
  "Not answered yet"), "Answered by … · date", Clear; a progress line ("2 of 3 answered ·
  1 required item left before Evaluating", or "Research complete"); then "Similar ideas"
  (up to 5 rows: key, title, project, status, owner; links) with an empty state ("No
  similar ideas found in the projects you can see"), and "Ask AI to research". Evaluators
  see the answers too. Keyboard, focus and 390 px rules as everywhere
  (`highlight-ring`, focus stays on the field after saving).
- **Audit log:** phrases and categories for the four new actions (§5).
- **Public tracking:** no change beyond `statusMeaning` treating `research` like the
  status before it (it never arrives, §3.9; the type allows it).

### 3.14 Demo data (backend's seed)

The seed shows both features in the demo and the README tour (review item 8), through
the same services a person uses (no gate bypass, §3.5):

- **Internal Tools** (`TOOLS`): step `before_evaluation`, the default checklist, and a
  custom template: Summary, Problem, Solution, **Effort & rollout**, Risks, **The ask**
  (keys `summary, problem, solution, effort_rollout, risks, the_ask`; the unused
  defaults are deleted, so there are no removed sections). **Two ideas in Research**:
  one complete (both required items answered, the optional one too), one with one
  required item open (so its card shows "1/3" with one required open and the gate is
  visible). **Every TOOLS idea already past Research** (Evaluating, Shortlisted,
  Proposal) has its required items answered, by its owner, before it was moved on
  (closed ideas may stay unanswered: c5, and no card shows them). The TOOLS idea in
  Proposal **has a proposal** in the custom template with most sections written, so the
  editor, the PDF and the Markdown show the custom sections and the "Research and
  consultation" appendix.
- **Sustainability** (`GREEN`): step `before_proposal`, the default checklist, and a
  **"Carbon impact"** section (key `carbon_impact`, after Benefits / revenue) added to
  the default template. The GREEN idea in Proposal has its checklist answered and **a
  proposal** with Carbon impact written. A GREEN Shortlisted idea may carry a partly
  answered checklist (its card shows the badge: Shortlisted is the status before
  Research here).
- **Customer Innovation**: defaults, step off, nothing new.
- Answers are realistic consultation records ("Legal (contracts team), 3 Oct: fine if
  we keep the standard terms"), written by the idea's owner, with `answered_at` before the
  move past Research. Either answer before moving the idea on, or move the ideas first
  and turn the step on afterwards (the step can be turned on while no idea is in
  Research), then answer and move the two Research ideas in.
- `dev/README.md`'s who's who stays coherent (platform): the owners of the Research ideas
  are members who can answer; the tour (`screenshots:tour`, qa) can show the Research
  panel and the custom template.

## 4. Changed shapes (field by field)

| Schema | Change |
|---|---|
| `IdeaStatus` | + `research` (after `new`). |
| `ResearchStep` (new enum) | `off`, `before_evaluation`, `before_proposal`. |
| `ProjectSummary` (so `Project`) | + `research_step`, + `lifecycle: IdeaStatus[]`. |
| `ProjectPermissions.can_manage` | description: also the template and research settings. |
| `StatusLabels`, `StatusLabelsUpdate` | + `research`. |
| `IdeaSummary` (so `IdeaDetail`) | + `research: ResearchProgress \| null` (set only for an idea in Research or the status before it, §3.6). |
| `IdeaPermissions` | + `can_answer_research`, + `invite_blocked_by_research`. |
| `Board` / `BoardColumn` | columns follow `Project.lifecycle`. |
| `StatusChange`, `EvaluatorsAdd` | + `override_research?: boolean \| null`, `override_reason?: string \| null`. |
| `ProposalStart` (new, optional body of `create_proposal`) | `override_research?`, `override_reason?`. |
| `AiEvaluationRequest` (new body of `request_ai_evaluation`, was `AiRunRequest`) | `agent_id` + the override fields. |
| `ProposalSection.key`, `ProposalThread.section_key`, `ProposalSuggestion.section_key`, `AiRun.section_key` | `string` (was the `ProposalSectionKey` enum). |
| `ProposalThreadCreate.section_key`, `ProposalSuggestionCreate.section_key`, `AiSectionDraftRequest.section_key`, path `{section_key}` | `SectionKey` (pattern, max 40). |
| `ProposalPermissions` | + `start_blocked_by_research`. |
| `ProposalTemplateSection` (new) | includes `proposal_count`. |
| `ResearchSettingsUpdate` (new) | `items` optional (default `[]`), ignored while `step` is `off`. |
| `ResearchAnswerIn` (new) | invisible characters removed; at least one visible character. |
| `TrackedSubmission.status`, `TrackedStatusChange.status` | never `research`: reported as the status before it (§3.9; the type is `IdeaStatus`). |
| `StatusChangedActivity` | + `research_overridden`. |
| `AiBlockedReason` | + `research_incomplete` (last). |
| `McpIdeaDetail` | + `research: McpResearch \| null`. |
| `SearchIdeasInput.status` | up to six values. |
| New | `ProposalTemplate`, `ProposalTemplateSection`, `RemovedTemplateSection`, `ProposalTemplateUpdate`, `TemplateSectionIn`; `ResearchSettings`, `ResearchChecklistItem`, `RemovedResearchItem`, `DefaultChecklistItem`, `ResearchSettingsUpdate`, `ResearchItemIn`, `IdeaResearch`, `IdeaResearchItem`, `ResearchAnswer`, `ResearchAnswerIn`, `ResearchPermissions`, `ResearchProgress`, `ResearchOpenItem`, `ResearchIncompleteProblem`, `IdeasInResearchProblem`, `SimilarIdea`, `SimilarIdeas`; MCP `McpResearch`, `McpResearchItem`. |
| Removed from the API | the `ProposalSectionKey` schema (the Python enum stays, naming the defaults). |

Request fields that default to null are optional in the generated types; response fields
are always present (contract-phase1 §1).

## 5. Audit actions

| Action | When | Target, details | SPA |
|---|---|---|---|
| `project.proposal_template_replace` | the template changed | project; `added`, `restored`, `archived`, `deleted`, `renamed` (keys), `reordered` | phrase "changed the proposal template of {project}", category Projects |
| `project.research_step_change` | the step changed | project; `from`, `to` | "set the research step of {project} to {to}" (Off / Before evaluation / Before proposal), Projects |
| `project.research_checklist_replace` | the checklist changed | project; counts `added`, `restored`, `archived`, `deleted`, `changed` | "changed the research checklist of {project}", Projects |
| `idea.research_override` | an admin moved an idea past Research with required items open | idea (project set); `operation`, `from_status`, `to_status`, `open_items`, `reason?` | "moved {idea} past research without finishing it" (+ the reason), Ideas |

Each needs, in the SPA's same change: its phrase, its category, the mock list and the
exhaustive `Record` in `audit-phrases.test.ts` (CLAUDE.md, audit convention). Answers
aren't audited (§3.4); the override reason is the admin's own one line and is shown in
the audit log only.

## 6. Minimum tests (tests first)

- **Role matrix:** `project.edit_proposal_template`, `project.edit_research`,
  `idea.answer_research`, `idea.research_override` for every column and overlay (a
  demoted owner can't answer; c5; archived and held ideas), through keys (answering needs
  `write`; the three session-only rules refuse every key; agents never answer); c7 with
  Research before a proposal step (start, save, suggest, draft).
- **The gate**, every path for owner, project admin, platform admin and a key: status
  changes (each `GATE_CASES` row of `tests/test_schemas_phase8.py` through the API, the
  board drag being the same request), reopening from Closed (each `REOPEN_CASES` row:
  Undo of a Close of an idea past Research or moved on with the override goes through for
  the owner; New → Closed → Evaluating is refused; `closed_from` read under the lock),
  the first invite and later invites, "Ask AI to evaluate", starting a proposal from
  Shortlisted and from Research (with the override passed through `create_proposal`: one
  audit entry);
  all-optional checklists never block; an answered checklist lets every path through;
  clearing an answer re-arms it; the override: allowed (audited, `research_overridden`
  in the event), refused for owners (403) and keys (403 `insufficient_scope`), ignored
  when nothing blocks (no audit); the 409 lists exactly the open required items;
  concurrency: an answer and a guarded move on the same idea serialise.
- **Step changes:** 409 `ideas_in_research` with the count; turning off hides
  everything and keeps answers **and the checklist** (`{step: off, items: []}` deletes
  nothing; turning it on again with the same ids restores them); `research_step_off` on
  status `research` and on answers.
- **Answers:** a lone zero-width space, bidi control or other invisible character is 422
  and never satisfies the gate; invisible characters are removed from stored answers.
- **Cards:** `IdeaSummary.research` only for ideas in Research or the status before it
  (null past Research, closed, or further back), in one statement per page and none when
  no project on the page has the step on (`tests/perf`); `IdeaResearch.blocking` false
  for a closed idea; `invite_blocked_by_research` for the first invite only.
- **Template rules:** keys stable across renames and reorders; new keys from titles and
  collisions with removed keys; archive vs delete (text, thread, suggestion, AI run each
  keep a section); restore brings text, threads and suggestions back; missing section
  rows created in every proposal; unknown or removed keys: 404 on the section path, 422
  `unknown_section` for threads, suggestions and AI drafts, MCP `unknown_section`;
  exports and `get_proposal` list the active sections only, in order.
- **Migration:** `tests/test_domain_schema_phase8.py` (carry-over, downgrade) and the
  up/down/up with demo data.
- **Similar ideas:** held ideas never (both kinds, for admins too), private projects of
  others never, a key's restriction, archived projects included, the idea itself never,
  the threshold and the limit; no score data for a pending evaluator.
- **Research reads** for every column (404/401), pending evaluators see answers; MCP
  `get_idea.research` for people and agents (read only), null while off.
- **Public:** tracking reports Research as the status before it (New before evaluation,
  **Shortlisted** before the proposal) and leaves moves that change nothing reported out
  of the history; no submitter email for New ↔ Research or Shortlisted ↔ Research (each
  row of `test_submitters_see_a_move_only_when_the_reported_status_changes`).
- **AI drafts:** the run message names the section by key, never its title.
- **Exports:** the appendix only while on and with answers, escaped Markdown, the PDF
  section; removed items never.

## 7. Contract mechanics

- **`PHASE8_OPERATIONS`** in `backend/tests/test_contract_routes.py` pins the eight new
  operations like `CONTRACT` (routes, operation ids, 501 stubs, request validation) but
  is kept apart from `CONTRACT` until identity classifies them for API keys
  (`app/authz/keys.py ROUTE_KEY_ACCESS`, last bullet) and names their rules
  (`tests/authz/test_route_rules.py ROUTE_RULES`), because five meta-tests
  index those tables by every `CONTRACT` operation. Identity moves the rows into
  `CONTRACT` in the same change; backend then adds the new idea routes to its guard
  tests (`tests/ideas/test_route_guards.py` covers every `/ideas` route). Until then keys
  are refused on the new operations (deny by default).
- The role matrix's new rows and the c7 change fail `tests/authz/test_policy_matrix.py`
  until the policy follows (by design: the document comes first).
- Section keys are strings from Phase 8 on: backend code typed on `ProposalSectionKey`
  (template lookups, `.value` on a loaded key) changes with the per-project template.
- Expected classification for keys: `get_proposal_template`, `get_research_settings`,
  `get_idea_research`, `list_similar_ideas`, `answer_research_item`,
  `clear_research_item`: `policy`; `replace_proposal_template`,
  `replace_research_settings`: `session`.
- **Places that assumed the fixed five statuses or the fixed template** (review item 12;
  each owner changes its own):
  - Backend: `app/services/board.py` (`LIFECYCLE = tuple(IdeaStatus)` is now six: the
    board uses `lifecycle(project.research_step)` per project), while `app/services/work.py`
    keeps `CANONICAL_STATUS_ORDER` for My work's groups; `app/public/tracking.py`
    (`_history`, the current status) and `app/public/emails.py` (`_status_label`, whether
    to send) use `public_status` (§3.9); the gate and `closed_from` in
    `app/services/ideas.change_status`, `create_proposal` in `app/proposals/service.py`
    (override through, Research → Proposal), the seed (`app/seed/runner.py`, §3.14);
    `proposal_count` and the suggestion cap (`app/proposals/suggestions.py`) over active
    sections; `seed_large` (tests/perf) with a stepped project.
  - Identity: `app/authz/policy.py` c7 (Research before a proposal step); c1 stays
    "status is `new`": **an idea moved into Research is no longer the submitter's to
    edit**, like one moved to Evaluating (decided, role matrix c1).
  - Frontend: `lib/status.ts` (the order and labels: per project from
    `Project.lifecycle`, canonical across projects), `project-search.ts` (accept
    `?status=research`), `status-dialog.tsx`, `project-filters.tsx`,
    `status-labels-settings.tsx` (the Research label only while the step is on),
    `board-column.tsx`, `track-page.tsx` (`statusMeaning`), `app-commands.tsx` (⌘K status
    commands), and the generated types (no `ProposalSectionKey`).

## 8. Error codes (new)

| Code | Status | When |
|---|---|---|
| `research_incomplete` | 409 | A guarded request while required checklist items are open (§3.5); `ResearchIncompleteProblem` with `open_items`, `can_override`. |
| `research_step_off` | 409 | `change_idea_status` to `research`, or answering / clearing an item, while the project's step is off. |
| `ideas_in_research` | 409 | Changing the research step while ideas are in Research; `IdeasInResearchProblem.idea_count`. |
| `unknown_section` | 422 | A section key the project's template doesn't have (or a removed section's) in a thread, a suggestion, an AI draft or `replace_proposal_template`; MCP tool error with the same code. |
| `unknown_research_item` | 422 | An item id that isn't the project's in `replace_research_settings`. |

A section key in a path that isn't active (`update_proposal_section`) and an item id that
isn't an active item of the idea's project (`answer_research_item`, `clear_research_item`)
are 404 `not_found`.

## 9. Decisions

The product owner's decisions (A and B) and the calls made writing this contract are in
[decisions.md](../decisions.md) ("Phase 8 (product owner, 2026-10-07)" and "Phase 8
contract"); the architecture in [ADR 0015](../adr/0015-proposal-templates-and-research-step.md).

## 10. Changes after the contract

Builders record additive changes here (date, what, why), as in earlier phases.

### 2026-10-07 · contract review (p8-critic), applied before building

| # | Change | Why |
|---|---|---|
| 1 | Public tracking reports Research as the status **before it** in the project's lifecycle (`public_status`, `status_before_research`), not always `new`; history rows and submitter emails only when the reported status or resolution changes (§3.9). | In a "Before proposal" project Shortlisted → Research dropped the submitter's page to "New" and emailed "Your idea is now New". |
| 2 | Reopening a closed idea counts from the status it was **closed from** (`crosses_gate(..., closed_from=)`, from the latest `status_changed` into closed, under the idea lock); unknown counts as New (§3.5). | Undo of a Close failed for every idea past Research without answers (all ideas once a project turned the step on, every overridden idea), and owners can't override. |
| 3 | Where the gate lives: `ideas.change_status` (also `create_proposal`'s move, override passed through, Research → Proposal) plus one research-service helper for invites and "Ask AI to evaluate"; no bypass, the seed follows the services (§3.5, §3.14). | One choke point; the seed would otherwise be refused. |
| 4 | `ResearchAnswerIn` removes invisible characters (`app.schemas.base.INVISIBLE_CHARACTERS` / `visible_text`, = MCP's `HIDDEN`) and needs one visible character. | A lone zero-width space or bidi control passed the gate. |
| 5 | `ProposalTemplateSection.proposal_count`. | The removal warning names N. |
| 6 | "Reset to the default eight" cut (§2.7). | No field for it, and a deleted default's key is `unknown_section`; Removed sections restores. |
| 7 | `ResearchSettingsUpdate.items` optional and **ignored while `step` is `off`** (§3.3). | `{step: off, items: []}` deleted the checklist, against "kept (hidden)". |
| 8 | §3.14 seed: answers for TOOLS ideas past Research, one proposal each in TOOLS (custom template, appendix) and GREEN (Carbon impact). | Otherwise "0/3" on ideas past the gate, and neither feature visible in the demo or the tour. |
| 9 | `IdeaSummary.research` only for an idea in Research or the status before it (`shows_research_progress`); `IdeaResearch.blocking` false for a closed idea. | Badges on ideas past the gate or closed. |
| 10 | `run_message` names a draft's section by **key only**; `section_title` removed (and a key that isn't one is a `ValueError`). | A project admin's title reached an agent's instructions (ADR 0014). |
| 11 | Research progress in one statement per page, none when no project on the page has the step on; `seed_large` gets a stepped project (§3.6). | Phase 7 statement budgets. |
| 12 | The list of places that assumed the fixed five (§7); c1 decided: Research ends the submitter's editing. | So builders change them all. |
| 13 | The editor keeps text typed into a section removed meanwhile as a local draft and says so (§2.7). | Autosave's 404 would lose it. |
| 14 | `IdeaSummaryPermissions.can_override_research` **removed**. | A policy call per row; the 409 carries `can_override`, the idea page `IdeaResearch.permissions.can_override`. |
| 15 | `IdeaPermissions.invite_blocked_by_research`. | Invites now warn like "Start proposal" and "Ask AI to evaluate". |
| 16 | Template and checklist saves documented as last write wins. | Like the rubric. |
| 17 | The pending-suggestion cap counts active sections only; `RemovedTemplateSection.proposal_count` may be 0 (wording in §2.7). | Hidden suggestions shouldn't block new ones. |
| 18 | "Crossing only" stays **Proposed, to confirm with the product owner** (decisions). | It reads "cannot move to any status after Research" as "cannot cross into". |
| 19 | The downgrade's no-op status events and team emails' `new` documented (§2.5). | Known effects of an emergency path. |

### 2026-10-07 · backend build (no API shape changed)

| # | Change | Why |
|---|---|---|
| B1 | Reopening counts from the latest move into Closed **from an open status** (`app.services.ideas._closed_from`): a re-resolution (Closed → Closed) is skipped, so an idea closed from Proposal and re-resolved Accepted → Parked still reopens into Proposal freely. | Read literally, "the latest `status_changed` into closed" would be the Closed → Closed event, whose `from_status` is `closed` (counts as New), and Undo of a re-resolved idea would be refused. |
| B2 | The `idea.research_override` audit entry of an evaluator invite or "Ask AI to evaluate" records the idea's current status as both `from_status` and `to_status` (no status changes there); `operation` says which request it was. | The details' shape is §5's; an invite moves no status. |
| B3 | `status_changed` payloads may carry `research_overridden: true` as the one optional key (`app.services.activity.OPTIONAL_PAYLOAD_KEYS`); absent means false, so every Phase 1–7 event stays valid. | §3.5 "stored in the payload as research_overridden: true (absent = false)". |
| B4 | A 409 with fields of its own (`ResearchIncompleteProblem.open_items` / `can_override`, `IdeasInResearchProblem.idea_count`) is raised as a `ProblemError` with a `model` and `extra` values (`app/errors.py`); the response is the contract's schema. MCP tools get the same `code` and `detail` as a tool error. | One way to raise them from any service, not only from routes. |
| B5 | Submitter status emails are skipped at queue time too (not only at send time) when nothing reported changes, so no outbox row is queued and then cancelled for New ↔ Research. | Admin → Email's outbox would otherwise list cancelled emails for moves the submitter never sees. |
| B6 | My work asks only for the owned groups that have ideas (one statement still): the Research group exists only while you own an idea in Research. | §3.2 "a Research group appears only for ideas in Research". |
| B7 | Migration **0013** adds trigram **GiST** indexes `ix_ideas_title_trgm_gist` and `ix_ideas_summary_trgm_gist`; "Similar ideas" takes the 20 nearest titles and the 20 nearest summaries by `<->` (index order), then ranks them by the larger similarity as shown (2 places, >= 0.3; ties by the latest activity, then id), limit 5. Same results as a full scan (any top-5 idea is among the nearest few by its better column) unless more than 20 ideas tie for fifth place. | `%` on the GIN indexes returns every match unordered: 1.3 s on 12,000 near-identical summaries, 5-16 ms with GiST. |
