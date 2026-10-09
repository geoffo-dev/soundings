# Test plan: Phase 8b (the research assigned to a person)

Owner: qa. Source of truth for behaviour: the product owner's decisions in
[decisions.md](../decisions.md) ("Phase 8b (product owner, 2026-10-08)" and the answers to
the contract review's S1 and S8), [contract-phase8b.md](../api/contract-phase8b.md) (the
assignment §3, researcher access §4, answering §5, notifications and reminders §6, My work
§7, shapes §8, minimum tests §9, the SPA §10, demo data §11, the Phase 8 follow-ups §12,
audit §13, errors §14, the review §18), [role-matrix.md](../role-matrix.md) (column **R**,
overlay **+Rsr**, table L, `idea.assign_researcher`, `idea.release_researcher`,
`idea.answer_research` widened, c23–c25) and
[ADR 0016](../adr/0016-research-assignment-and-guest-researcher.md). Each row has an ID
used in the test names, so a failing test points back here. The Phase 1–8 plans still
apply; their suites run in every mode next to the Phase 8b specs.

## What the product owner asked for, and where it is tested

| Requirement (decisions, Phase 8b) | Acceptance (HTTP, live server) | Browser (real stack) | Rules (owners' unit tests) |
|---|---|---|---|
| **One researcher per idea**, optional, with a research due date (DueAt, the instance time zone); nobody assigned = the owner does the research | AC8B-API-1, AC8B-API-3 | RA-01, RA-05, RA-07 | `tests/test_domain_schema_phase8b.py`, `tests/test_schemas_phase8b.py`, `tests/research/test_assignment.py` |
| **Who assigns**: the owner, project and platform admins, in a session only (any key 403 `insufficient_scope`); in a private project only admins name an outsider (c25, 403 `outside_researcher_needs_admin`); the researcher hands back; 409 `research_step_off`, `idea_closed`, `project_archived`, `awaiting_moderation`; idempotent; audited `idea.researcher_change` with its `reason` and `outside_project` | AC8B-API-1, AC8B-API-3 | RA-01, RA-02, RA-04, RA-05 | `tests/research/test_assignment.py` (38), `tests/authz/test_researcher_access.py`, `tests/authz/test_key_scopes.py`, `tests/authz/test_route_rules.py`, `frontend/src/features/admin/audit/audit-phrases.test.ts` |
| **Who can be researcher**: any active person; never a service account (AI agent), the break-glass account, a deactivated or unknown account (422 `researcher_not_eligible`) | AC8B-API-1 | — | `tests/research/test_assignment.py`, `tests/research/test_picker_and_leavers.py` |
| **What ends an assignment by itself**: deactivation, closing, the step turned off, losing one's role in a private project (`left_project`); answers kept, the due date kept, nothing restored later; lock order | AC8B-API-1 (deactivation), AC8B-API-2 (`left_project`) | — | `tests/research/test_assignment.py`, `tests/research/test_role_loss.py` (10), `tests/research/test_assignment_locks.py` (4), `tests/research/test_picker_and_leavers.py` (anonymise keeps answers) |
| **Researcher access (column R)**: that one idea only — overview, the feed without the evaluation events, comments, the checklist, Similar ideas among ideas they see anyway; never score data, the evaluation area, the proposal and its exports, the AI panel, the submission panel, the project (board, list, members, settings, public form, moderation), other ideas; the project by name only | AC8B-API-1 (every idea route, every project route, lists, MCP), AC8B-API-3 | RA-01, RA-03, RA-04, MO8B-02 | `tests/research/test_guest_access.py` (153), `tests/authz/test_researcher_access.py`, `tests/authz/test_research_guest_queries.py`, `tests/authz/test_queries.py`, the route table's meta-test (`app/authz/guest.py`, in `tests/authz/test_researcher_access.py`) |
| **Access ends at once** (unassigned, reassigned, handed back, deactivated, deleted, closed, step off; archived suspends): the next request is 404, REST and MCP, search, My work and the inbox drop the idea; an open AI event stream ends at its next re-check | AC8B-API-1, AC8B-API-2 | RA-04 | `tests/research/test_guest_access.py` (7 ways), `tests/ai/test_sse.py` (`test_the_recheck_ends_a_stream_once_its_watcher_is_only_a_guest`) |
| **API keys and MCP**: key ∩ person ∩ policy; a key restricted to projects can't name a private project its owner can't view (422 `invalid_project`) and a key restricted elsewhere never reaches the idea; MCP `get_idea` guest shape with `research_guest`, `research.researcher` and `due_at`, `has_proposal: false`; `search_ideas` the idea only; `get_rubric` / `get_proposal` / `submit_evaluation` / `propose_proposal_section` / `create_idea` `not_found`; `add_comment` allowed; agents never assign or are assigned | AC8B-API-1, AC8B-API-3 | — | `tests/research/test_guest_access.py` (keys, MCP), `tests/mcp/` |
| **Answering**: `idea.answer_research` widens to the researcher (guest included); the gate and "Move anyway" unchanged (a researcher can't move or override); M1: a required answer can't be cleared past Research | AC8B-API-1 | RA-04 | `tests/research/test_answers.py`, `tests/research/test_gate.py` |
| **Notifications**: "Asked to research" (to the new researcher when someone else assigns; once per idea, person and local day; the guest line only for column R; the Research link; no score data) and "Research reminder" (2 days before and on the day at the digest hour, only while research is to do, stops once answered, past Research, closed, step off, unassigned; to the owner when nobody is assigned); preferences, digest, unsubscribe; recipients pass the policy | AC8B-API-1 (Mailpit, the fake clock) | RA-01, RA-08 | `tests/notifications/test_research_notifications.py` (11), `tests/notifications/test_research_reminders.py` (22: the worked example, DST, every stop condition) |
| **My work**: "Research to do" for the researcher, else the owner; overdue first, then soonest, then none; "N open"; `WorkCounts.research_to_do` / `research_overdue`; never in owned groups for a guest; owned groups hold their first 10 (D) | AC8B-API-1, AC8B-API-3 | RA-01, RA-03, RA-07 | `tests/research/test_research_to_do.py` (23), `tests/ideas/test_work.py`, `tests/perf` budgets |
| **UI**: "Research: <name> · due <date>" (outsiders marked "not in this project"), Change / Remove (Undo) / Hand back, the person picker (outsiders marked, the one line), "Start research" dialog, the researcher's avatar on Research cards, the guest's idea page without dead tabs, a working shell | — | RA-01…RA-07, A11Y8B-*, MO8B-*, K8B-01 | `frontend/tests/research-assignment.spec.ts` (16, MSW mock; also the no-project shell) |
| **Demo seed**: bob researches TOOLS-12 as its guest (due in 3 days, asked by dave); amara researches GREEN-6 (asked by alice); alice's GREEN-5 is overdue; TOOLS-11 nobody | AC8B-API-3 | RA-03, RA-06, RA-07 | `tests/test_seed.py` |
| **D. Phase 8 follow-ups**: removed template sections and checklist items keep their position, so Restore puts them back there | — | RA-09 | `tests/proposals/test_template.py`, `tests/research/test_settings.py` |
| Calm UI: loading, empty and error states, dark mode, keyboard, 390 px, WCAG 2.2 AA | — | A11Y8B-*, MO8B-01, MO8B-02, K8B-01, RA-01 (focus back on Change) | `frontend/tests/research-assignment.spec.ts` |

## Acceptance through the HTTP API (`backend/tests/acceptance/test_phase8b_acceptance.py`)

The app behind a real **uvicorn** on a free port with the **demo data**, people signed in
with the dev login over TCP (session cookie, CSRF header), API keys as bearer tokens with no
cookie, the official **MCP Python SDK** client on `/mcp`, email through a **real Mailpit**
(the Phase 3 acceptance's fixtures: a container, or `SOUNDINGS_TEST_MAILPIT_SMTP` / `_URL`
as CI provides) sent by the worker's own job code, the research reminders driven by
`send_research_reminders` with a moved clock (the hourly job's first step; the rest of the
job, which would delete sessions "expired" by then, isn't run). About 75 s for the three.

| ID | Story | What it checks |
|---|---|---|
| AC8B-API-1 | An outside researcher sees one idea and nothing else | **Arranged**: a TOOLS (private) idea Dave owns (a project admin), moved on anyway, evaluated by Carol (5) and Kenji (2) and by an AI agent during its evaluate run (rationale per criterion), a research note from the agent's research run, then back in Research (2 required items open). Dave's My work lists it (`as_owner`). **Refusals**: Sven (plain owner of TOOLS-12) naming Erin, an outsider → 403 `outside_researcher_needs_admin`; Dave naming the agent's service account or an unknown id → 422 `researcher_not_eligible`; Dave's write key → 403 `insufficient_scope`. **Assigned**: Dave asks **Nora**, a new account in no project, due in 5 days at 17:00 London: `researcher_in_project: false`, the due date, one `idea.researcher_change {reason: assigned, outside_project: true}`, one `researcher_changed` and one `research_due_date_changed` event; the same request again adds nothing; Dave's My work no longer lists it. **Email** (Mailpit): subject `[KEY] Please research "…" by <day>`, the Research link `?research=1` in text and HTML, the guest line, "Dave Davies asked you to do the research", the project's name, "You're researching KEY.", no project link, no rationale, no score words or numbers. **Nora's view**: the guest shape (score, aggregate, evaluators, progress, evaluation dates empty; only `can_comment`, `can_answer_research`, `can_hand_back_research`); research permissions (answer, hand back; no override, no assign); the feed only `RESEARCH_GUEST_ACTIVITY_TYPES`, none of the evaluation events; Similar ideas nothing else of the project; the research note. **Every idea route** of the OpenAPI document probed (the table must cover them all): view 200, the overlay's comment and answer allowed, every other rule 403, the evaluation area, the proposal and its exports, threads, suggestions, the submission panel and the AI panel and its stream 404; her own comment edited and deleted, Dave's 403. **Every project GET** 404, creating an idea there 404, `search_users?project=` 404 (with `include_non_members` too), the directory works. **Lists**: no TOOLS in `list_projects`; search finds the idea, no project, no other TOOLS idea; My work's `research_to_do` (`can_view_project: false`, the due date, 2 open), counts 1/0, nothing in evaluations due, owned groups or recent; the inbox "Asked to research" (Dave, the due date) and Dave's comment (she watches). **Keys and MCP**: a key restricted to TOOLS → 422 `invalid_project`; her unrestricted write+mcp key reads the guest shape, answers, is 404 on evaluations and the project and 403 `insufficient_scope` on assigning; MCP `get_idea` (`research_guest`, the researcher's name, the due date, `has_proposal: false`, no score data), `search_ideas` only the idea, `search_ideas project=` / `get_rubric` (project or idea) / `get_proposal` / `submit_evaluation` / `propose_proposal_section` / `create_idea` `not_found`, `add_research_note` `forbidden`, `add_comment` works. **Reminder**: none 3 days or 1 day before, none an hour early; at the digest hour two days before, one (and still one 20 minutes later); sent through Mailpit: `[KEY] Reminder: research for "…" is due <day>`, "2 required items to answer", the link, no score data; her inbox `days_before: 2`, `as_owner: false`. **Answering and the gate**: Nora answers both required items (`answered_by` her); her move and her "Move anyway" 403; Dave moves it to Evaluating with no override entry; her My work and counts empty; no reminder on the due day; clearing a required answer now 409 `research_answer_required`; Dave's @mention reaches her; her inbox types are only `RESEARCH_GUEST_NOTIFICATION_TYPES`. **Reassigned** to Farah: Nora's next requests (idea, research, feed, Similar ideas, the note, comment, answer, hand back) 404, search, My work and the inbox drop it, MCP `get_idea` `not_found` and `search_ideas` empty; her answers stay under her name; Farah is emailed. **Hand back**: Farah's 204, then 404; nobody assigned, the due date kept, `handed_back: true` in the feed; asked again the same day, no second "Asked to research" (S6). **Deactivation** clears it (due date kept); naming a deactivated account 422; reactivated, nothing comes back (404). Audit reasons: assigned ×3, handed_back, deactivated. |
| AC8B-API-2 | The AI event stream | The guest can't open a stream on the idea's research run (404). Reassigned to Carol (a TOOLS member): Nora is 404 at once; Carol's stream opens (`retry: 3000`); Dave removes Carol from TOOLS: the stream ends at the next re-check (half a second here), Carol's idea and stream are 404, nobody is assigned, one `left_project` audit entry. |
| AC8B-API-3 | The demo story | Bob sees TOOLS-12 as its guest (due in 2–4 days), TOOLS is 404 (project, board, TOOLS-11), his My work lists TOOLS-12 (`can_view_project: false`, 1 open) and his inbox "Asked to research" from Dave. Sven sees bob "not in this project", may assign but not name outsiders (403 `outside_researcher_needs_admin` for Erin); Dave may. The picker (`include_non_members`) lists bob with `project_role: null`. TOOLS-11 nobody. Bob's key restricted to Customer Innovation: REST 404 and MCP `not_found` on TOOLS-12; his unrestricted read key reads the guest shape with no permission flags. Amara researches GREEN-6 (asked by alice); alice's first research to do is GREEN-5, overdue; every owned group of alice's holds at most 10 ideas with `next_cursor` exactly when there are more (D). **Internal projects**: Sven (a plain owner) names Dave, who has no role in Sustainability: allowed (c25 is for private projects), `researcher_in_project: false`, Dave keeps the internal non-member's view (`can_view_project`, the board 200) and gains commenting, answering and handing back (no status change); his "Asked to research" has no guest line (review S2). |

## Browser, real stack (`e2e/tests/`)

Specs that assign use a private project of their own (`tests/support/research.ts`
`researchTeam`, `assignResearcher`, `removeResearcher`, `researchToDo`) and new people
(`newPeople`: their own inbox and mailbox); RA-03, RA-06, RA-07 and the a11y screens read
the seeded story without changing it.

| ID | Spec | What it checks |
|---|---|---|
| RA-01 | `research-assignment.spec.ts` | An admin opens "Change researcher or due date" on a private project's idea (owner Carol): "Search everyone…", Nora (a new person) found by email and marked "Not in this project", "Chosen: Nora Quinn · Not in this project" with the private-project line, "In a week", Save → toast, the line "Nora Quinn · not in this project · due …", focus back on Change, the feed sentence; the API agrees. Her email (when SMTP is on): the guest line, the `?research=1` link, no score data. In Nora's browser: My work's row (project as text, "2 open"), no project in the sidebar, "Answer" opens the idea with the first open item focused, the guest line, the breadcrumb as text, no tabs; the project URL is "doesn't exist". |
| RA-02 | `research-assignment.spec.ts` | "Remove Nora Quinn as researcher" → toast "… is no longer researching KEY", the line "Carol Chen (owner)", Undo → Nora again (API too). |
| RA-03 | `research-assignment.spec.ts` | bob on TOOLS-12 (seeded): the guest line, breadcrumb text, no tabs, no evaluators or score, no AI menu, no status menu, no 1-decimal number on the page; "Research: You · not in this project · due …", Hand back, no Change; "Answer the checklist"; the feed "Dave Davies asked Bob Brown to research"; axe clean (WCAG and best practice). No Internal Tools in the sidebar, "Research, N to do"; ⌘K finds TOOLS-12, never the project; `/p/internal-tools` and TOOLS-11 "don't exist"; the API's evaluations, proposal, export, AI runs, project and board 404; My work's row (project text, "1 open", "Due …"). |
| RA-04 | `research-assignment.spec.ts` | A guest (Nora) answers with "Answer the checklist" (focus on the item, Ctrl+Enter, "Answered by Nora Quinn", focus stays), then "Hand back" → the confirmation "You'll no longer see KEY" → My work with the toast, the idea gone from it; Back → "This idea doesn't exist…", no title; the owner does it again; her answer keeps her name. |
| RA-05 | `research-assignment.spec.ts` | "Start research" as the plain owner of a private project's New idea: "KEY moves to Research.", "Chosen: You (owner)", "Search the project's people…", "Only a project admin can ask someone outside this project.", Erin not found among the project's people; Kenji (member) chosen, "In 2 weeks", axe clean; Start research → one toast (the status change's), status Research, the line "Kenji Watanabe"; the API (status, researcher, due date); Kenji's inbox has one "Asked to research" and his My work the idea. |
| RA-06 | `research-assignment.spec.ts` | The TOOLS board as Dave: TOOLS-12's card has the avatar "Researched by Bob Brown" and it in its description (name stays "Title (KEY)"); TOOLS-11 (nobody assigned) none; axe clean. |
| RA-07 | `research-assignment.spec.ts` | alice's My work: "Research to do" first row GREEN-5 "Overdue N days", "2 open", the project linked; the sidebar "Research, N to do, N overdue"; axe clean; Answer → GREEN-5 with the first item focused. |
| RA-08 | `research-assignment.spec.ts` | Settings → Notifications has 9 types, "Asked to research" and "Research reminders" immediate by default; "Asked to research" Off (saved) → an assignment reaches the inbox but sends no email (the outbox settles; Mailpit has none); the inbox page words it "Alice Anders asked you to research"; Immediate again → the next assignment is emailed (`[KEY] Please research "…"` without "by", the guest line). |
| RA-09 | `research-assignment.spec.ts` | Removing an answered checklist item and a written template section (Solution) archives them; after a reload, Restore puts each back at its old position (item 2, section 3). |
| RA-10 | `research-assignment.spec.ts` | A guest has the idea page open; the owner reassigns; her next save is refused (404) and the page leaves the idea ("This idea doesn't exist…", no title), nothing saved, the idea 404 through the API (contract §4.6/§10; P8B-QA-F1, fixed in the integration: a write refused with 404 re-checks the idea on screen). |
| RA-11 | `research-assignment.spec.ts` | Mentions (contract §6.4): on TOOLS-12 Sven's @-picker offers Bob Brown (the researcher, not a member); Bob's own picker (the directory) offers Sven. Nothing is posted. |
| A11Y8B-* | `a11y-phase8b.spec.ts` | axe WCAG 2.2 AA (serious, critical), light and dark: the guest's idea page, My work with an overdue research item, the Research panel with an outside researcher, the board's Research column with the avatar, the assign dialog with an outsider chosen, the "Start research" dialog; best practice on the screens without overlays (light). |
| MO8B-01 | `a11y-phase8b.spec.ts` | The same six screens at 390 px without sideways scrolling; the dialogs keep Save / Start research in view. |
| MO8B-02 | `a11y-phase8b.spec.ts` | The guest's Details sheet at 390 px: Research, no Evaluators, no Score. |
| K8B-01 | `a11y-phase8b.spec.ts` | The assign dialog with the keyboard only: Enter on Change, the search focused, type, the top row selected, Enter chooses (a member: no guest line), Escape → focus back on Change, nothing saved. |

**Updated for the changed story** (not new behaviour): `preferences.spec.ts` PR-01 (9 rows;
the two research types immediate by default), `a11y-phase3.spec.ts` (9 rows),
`screenshots/phase-3.spec.ts` (9 rows), `screenshots/phase-6.spec.ts` ("Ask AI to
research", contract C8), `moderation-leaks.spec.ts` ML-02 (`IdeaPermissions.can_view_project`
is true for an admin: not an action, left out of the "only delete" check) and
`templates.spec.ts` TPL-01 (Restore puts Cost & effort back at its old place, fifth, not at
the end: D).

**Not testable on the real stack, covered elsewhere:** a guest researcher **in no project at
all** (the demo's two internal projects are visible to everyone): the MSW mock's
`soundings-mock-projects=private` knob in `frontend/tests/research-assignment.spec.ts`
("the shell works … no project route is called"). Reminders by date: the acceptance test and
`tests/notifications/test_research_reminders.py` (the e2e suite can't move the clock).

## Screenshots (`npm --prefix e2e run screenshots:phase8b`)

`docs/screenshots/phase-8b/`: `assign-picker-outsider`, `start-research-dialog`,
`research-panel-researcher-due`, `guest-researcher-idea`, `my-work-research-to-do-overdue`
(each `-1440-light`, `-1440-dark`, `-390-light`) and `emails/asked-to-research-`
(`desktop-light`, `desktop-dark`, `390-light`, as Mailpit received it).

## Defects and nits found (2026-10-09, real stack)

| ID | Owner | Severity | What | Reproduce |
|---|---|---|---|---|
| P8B-QA-F1 | frontend | minor (no new data leaks: every request is 404) | After the researcher is changed while a guest has the idea page open, a write that comes back 404 (answer, comment) shows "This no longer exists. It may have been deleted." under the field, but the page keeps the idea's title, checklist and "Research: You", and the sidebar's "Research 1"; the contract says the SPA drops the idea's cached queries on a 404 and leaves the page. | RA-10: as an admin assign a new person to a private idea; sign in as them and open it; reassign through the API; type an answer and Ctrl+Enter. |
| P8B-QA-N1 | frontend | nit | "Start research" / "Who does the research" for an owner who is also the explicit researcher (GREEN-6, amara): "Chosen: You (owner)" is right, but the list's highlight starts on the next row (Alice Anders), so Enter would pick Alice. | Sign in as amara, GREEN-6, "Start research". |
| P8B-QA-N2 | frontend | nit | At 390 px the assign dialog's "No due date" wraps alone onto a second row under the three quick dates. | `assign-picker-outsider-390-light.png`. |
| P8B-QA-N3 | backend (identity) | doc | `app/authz/guest.py`'s docstring names `tests/authz/test_guest_routes.py`; the meta-test lives in `tests/authz/test_researcher_access.py` (`test_every_idea_route_and_mcp_tool_has_a_guest_row`). | — |

**Integration (2026-10-09): all four fixed.** F1: any write refused with 404 re-checks the
idea on screen (`frontend/src/api/query.ts`), so the page shows "doesn't exist", drops the
idea's queries and refreshes My work's counts; RA-10's mark removed, `src/api/query.test.ts`.
N1: the person picker starts its highlight on the chosen owner row (`PeopleList
beforeChosen`; the mock test "QA N1"). N2: "No due date" sits beside the date field (the
390 px mock test checks they share a row). N3: the docstring names the right test.
The integration's walkthrough of the real stack found one more: the owner of a private
idea (sven on TOOLS-12) opened "Change" and, since his picker lists only the project's
people, bob (the outsider dave asked) had no row, so the highlight started on Alice and
Enter would have replaced bob. Fixed: the kept outsider has a row of their own, chosen and
highlighted (the mock test "may pick only the project's people").

