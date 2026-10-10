# Phase 8 and 8b summary: proposal templates, the research step and its researcher (release 0.2.0)

**Status:** built on 2026-10-07 to 2026-10-09, verified for release **0.2.0** on
2026-10-10, waiting for the product owner's review ([RELEASE-NOTES.md](../RELEASE-NOTES.md)).
**Scope (the product owner's changes after 0.1.0):** Phase 8: per-project proposal
templates and an optional research step with a checklist and a gate
([decisions](../decisions.md#phase-8-product-owner-2026-10-07) A and B); Phase 8b: the
research assigned to one person, also from outside the project, with a due date and
reminders ([decisions](../decisions.md#phase-8b-product-owner-2026-10-08) C), and the
Phase 8 review follow-ups (D). Contracts: [contract-phase8.md](../api/contract-phase8.md),
[contract-phase8b.md](../api/contract-phase8b.md); architecture:
[ADR 0015](../adr/0015-proposal-templates-and-research-step.md),
[ADR 0016](../adr/0016-research-assignment-and-guest-researcher.md); rules:
[role matrix](../role-matrix.md) table K, column R and table L; test plans:
[phase-8.md](../test-plans/phase-8.md), [phase-8b.md](../test-plans/phase-8b.md).

Commits: Phase 8 `4fe94d7` (contract), `e0ddb5b` (build and QA), `6afa0fb`
(integration), `f6700f7` (review fixes); Phase 8b `21169fd` (contract), `fdf9822`
(build, QA, integration), `28a1d72` (review fixes), `bb777b3` (the lead's follow-up
decisions D1-D5), `0473232` (the adversarial check's fixes); plus the 0.2.0 release
verification.

## What was built

### Phase 8: proposal templates and the research step

| Area | What | Where |
|---|---|---|
| Proposal templates | Project settings → Proposal template: 1-12 sections (title, hint), add, remove, rename, reorder; stable keys (the eight built-in ones, slugs for new ones); removing archives (text kept) and Restore puts the section back where it was; every proposal, thread, suggestion, "Draft with AI", MCP and both exports follow the template live; migration 0012 gives existing projects the eight | `app/proposals/template.py`, `app/domain/template_defaults.py`, `features/project/settings/` |
| The research step | Off / Before evaluation / Before proposal per project; the Research status and column (`lifecycle(step)`); a checklist of 1-10 items (title, hint, required) with three defaults; plain-text answers with who and when; switching refused while ideas are in Research (409 `ideas_in_research`) | `app/services/research.py`, `app/schemas/research.py`, `features/research/` |
| The gate | Crossings into a status after Research with a required item open are 409 `research_incomplete` (status change, board drag, the first evaluator invite, "Ask AI to evaluate", starting the proposal, reopening counted from where it was closed); "Move anyway" (and Invite, Ask, Start anyway) for project and platform admins, audited `idea.research_override` with a reason | `ideas.change_status`, `features/research/research-gate-dialog.tsx` |
| Help with the check | "Similar ideas" (trigram GiST indexes, migration 0013: the 20 nearest titles and summaries, ≥ 0.3, top 5, never held ideas, no scores); "Ask AI to research"; answers shown to evaluators; the "Research and consultation" appendix in the editor and both exports | `research.similar_ideas`, `app/proposals/markdown.py`, `pdf.py` |
| Public tracking | Research reported as the status before it (`public_status`), no submitter email for moves it hides, the step recorded on each move (review L3) | `app/public/reported.py` |
| Demo | Internal Tools before evaluation with a six-section template (TOOLS-11 complete, finds CUST-14; TOOLS-12 one required item open; TOOLS-3's proposal with the appendix); Sustainability before the proposal with "Carbon impact" (GREEN-4's proposal); Customer Innovation unchanged | `app/seed/research.py` |

### Phase 8b: the researcher and guest researchers

| Area | What | Where |
|---|---|---|
| The assignment | One researcher per idea (`ideas.researcher_id`, `research_assigned_at`, `research_due_at`, migration 0015; nobody = the owner); `PUT/DELETE /ideas/{idea}/research/assignment` (session only to assign; a `write` key may hand back); the owner, project and platform admins assign (c25: in a private project only admins name someone without a role there); never an agent, break-glass or a deactivated account; cleared by closing, the step off, deactivation, leaving a private project (`left_project`) and making the project private (`made_private`, after a warning); past Research the researcher can't change answers (c26) and nobody new is asked (409 `research_finished`) | `app/services/research_assignment.py`, `app/authz/policy.py` |
| Guest researchers (column R) | Someone without a role in a private project sees that one idea through the deny-by-default `RESEARCH_GUEST_ACCESS` table: overview, comments, the feed's allow-list, the checklist, Similar ideas among what they see anyway; never score data, the evaluation area, the proposal, the AI panel or the project (404); search, ⌘K, My work, the inbox and MCP show that idea only; access ends at the next request; an AI research run reads only what the guest could | `app/authz/guest.py`, `app/authz/queries.py`, `app/ai/scope.py` |
| Notifications | "Asked to research" (one per assignment, held 5 minutes when the idea was just passed round, at most 20 people an hour per requester) and "Research reminder" (2 days before and on the day at the digest hour while research is to do); preferences, digest, unsubscribe, two email templates | `app/notifications/fanout.py`, `schedule.py`, `app/templates/email/` |
| Screens | The Research panel's "Research: <name> · due <date>", the picker (members first, then "Not in this project"), "Start research" with who and when, Hand back, Remove past Research, My work's "Research to do", the sidebar's Research badge, Research cards with the researcher, the guest's idea page and shell | `features/research/research-assignment.tsx`, `features/work/research-to-do.tsx` |
| Follow-ups (D) | Owned groups send 10 ideas (both p95 budgets back to 150 ms); removed template sections and checklist items keep their position; "Ask AI to research" everywhere | `app/services/work.py`, `template.py`, `research.py` |

## Acceptance evidence

### The product owner's stories, through the HTTP API

`backend/tests/acceptance/test_phase8_acceptance.py` (a real uvicorn, the demo data, dev
login, API keys, the official MCP client, the real WeasyPrint child read back with pypdf):
**AC8-API-1** a project admin customises the template (keys, restore, Markdown and PDF,
MCP, `unknown_section`); **AC8-API-2** the gate on every path, "Move anyway", keys and
agents, the appendix, the step off and on again; **AC8-API-3** "Before proposal" (GREEN);
**AC8-API-4** Similar ideas never shows held or private ideas. **AC8-MIG**: 0.1.0's data
up to 0013, down to 0011 and up again with no row changed.

`backend/tests/acceptance/test_phase8b_acceptance.py` (also a real Mailpit and the
reminders with a moved clock): **AC8B-API-1** an outside researcher sees one idea and
nothing else (every idea route of the OpenAPI document probed, every project GET, keys,
MCP, the email, the reminder, the gate, reassignment, Hand back, deactivation, D1);
**AC8B-API-2** the AI event stream ends when the watcher becomes a guest; **AC8B-API-3**
the demo story, internal projects.

Rules, tests first: `tests/proposals/test_template.py`, `tests/research/` (settings,
answers, `test_gate.py`, `test_similar.py`, `test_assignment.py`,
`test_assignment_past_research.py`, `test_guest_access.py`, `test_role_loss.py`,
`test_research_to_do.py`, `test_lead_decisions.py`, `test_review_fixes.py`,
`test_guest_review_fixes.py`), `tests/authz/test_researcher_access.py` (its meta-test fails
for an idea route or MCP tool without a guest row), `tests/notifications/
test_research_notifications.py`, `test_research_reminders.py` (the worked example, DST,
every stop condition), `tests/ai/test_scope.py`, `tests/ai/test_research_gate.py`,
`tests/mcp/test_research.py`, `tests/public/test_research_public.py`.

### In the browser, real stack

`e2e/tests/research.spec.ts` RS-01…RS-10 (RS-09 `@ai`), `templates.spec.ts`
TPL-01…TPL-05 (TPL-05 `@ai`), `a11y-phase8.spec.ts` A11Y8 / MO8,
`research-assignment.spec.ts` RA-01…RA-14, `a11y-phase8b.spec.ts` A11Y8B / MO8B / K8B-01;
on the SPA's mock `frontend/tests/research.spec.ts`, `proposal-template.spec.ts`,
`research-assignment.spec.ts`.

### Final verification for 0.2.0 (2026-10-10)

On the build machine, with the version at 0.2.0 (`scripts/deploy.sh check-release
v0.2.0` passes):

| Check | Result |
|---|---|
| Backend: ruff, mypy --strict (457 files), pytest | 8,282 tests; one failed between 00:00 and 08:00 UTC (`test_preferences_digest_and_off` assumed the digest hour had passed): fixed with digest hour 0, its file re-run green; `make -C backend test-slow` green at 150 ms on a quiet machine |
| Frontend: `npm run check` (tsc, eslint, prettier, vitest, build), `test:pw` | 661 unit tests; 442 page tests on the mock (205 screenshot specs skipped), none failed |
| End to end against the real stack | 315 passed (default), 336 (`E2E_SSO=1`), 355 (`E2E_AI=1`), none failed; `npm --prefix e2e run check` |
| Helm, scripts, fake agent, workflows, migrations | `make check-helm check-scripts check-fake-agent check-workflows check-migrations` green; `make gen-api` changes only the version |
| Image | `make image IMAGE=soundings:0.2.0`: 525 MB, reports 0.2.0, migration head 0015 |
| Upgrade with data, through the CD script | 0.1.0's image (`git archive 0046a9a`) and chart with its demo data in `soundings-staging` on k3s, then `make k3s-deploy ENV=staging IMAGE=soundings:0.2.0` (`scripts/deploy.sh` as the namespaced deployer): migrations 0011 → 0012 → 0013 → 0014 → 0015 in the migrate Job, the row counts of nine tables (48 ideas among them) the same before and after, each project with the eight sections and the step off. On the migrated data, signed in with break-glass: a 0.1.0 proposal kept its text and margin thread through renaming, removing, adding and restoring sections, and both exports followed the template; the research step before evaluation, an idea into Research, the gate's 409 `research_incomplete` with `can_override`, an outsider (bob) asked to research (`outside_project` audited), answers then Evaluating, 409 `research_finished` past Research, closing clears the researcher (audited `closed`), Similar ideas across projects. A rollback to 0.1.0's revision was refused (its migrations unknown, the new revision at 0015) |
| Upgrade as CI | 0.1.0 with demo data in namespace `soundings`, then `make k3s-install SSO=1 SMTP=1 MCP=1 AI=1 IMAGE=soundings:0.2.0` and `k3s-smoke` with the same flags (119 checks), a guest researcher by hand (bob on TOOLS-13: the idea 200; its project, list, evaluations, proposal and another idea 404; Research to do lists it; Hand back → 404), `PROD=1` install and smoke, two API replicas and the smoke again, the external-database test (`scripts/k3s-test-external-db.sh`, fixed: see below) |

Fixed in this verification: `scripts/k3s-test-external-db.sh` (Phase 7's non-superuser
app role can't create databases, so the bootstrap superuser does; the bundled Postgres's
NetworkPolicy now has a temporary rule for the second namespace), the notification test
above, and from the re-captured screenshots the unsubscribe page's footer (it didn't name
research) and Admin → Email (it didn't list the research reminders); the image was rebuilt
after the last two.

## Review findings and outcomes

### Phase 8 (security and code review, UX review)

| Finding | Outcome |
|---|---|
| M1 answers cleared after passing the gate | Fixed: past Research a required answer can be edited, not cleared (409 `research_answer_required`) |
| L1 "Idea" + "İdea" gave a 500 | Fixed: uniqueness checked with Postgres `lower()` first (`require_unique_lower`), a 422 |
| L2 blank-looking answers and titles | Fixed: `VisibleText` / `VisibleLine` (a letter, digit, punctuation mark or symbol must be left) |
| L3 tracking history rewritten when the step moves | Fixed: each move into or out of Research records the step |
| L4 Undo of a backward move refused | Rejected (crossing only; the SPA offers no Undo the gate would refuse) |
| N1 audit wording; N2 the suggestions list had no limit | Fixed (the override phrase per operation; 200 at most) |
| My work over budget at 10k ideas | Indexes (0014), fewer statements, then 10 ideas per owned group (Phase 8b D): back at 150 ms |
| UX M1 unsaved answers lost; M2 focus dropped to the page; M3 a permanent warning | Fixed (drafts per user, focus to the neighbouring row, one muted line) |
| UX m1-m7, p1-p7, S1, S2 | Fixed (badges "2 open" / "Ready", visible hints, Escape keeps a draft, 390 px tabs, one name for "Ask AI to research", the appendix in the outline and the phone picker, …); p1 restore position completed in Phase 8b (D) |
| UX S3 "Start research" as the primary action | Adopted in Phase 8b ("Start research" asks who and by when) |

### Phase 8b (code review, guest-access review, UX review)

| Finding | Outcome |
|---|---|
| Guest M1 an AI research note as a side channel | Fixed: research runs read only `search_ideas` and `get_idea`, in the guest's shape |
| Guest L1 `last_activity_at` timed hidden events | Fixed: a guest's comes from their own feed (`visible_last_activity`, `Sort(guests=True)`) |
| Code M1 "Asked to research" spam; L2 dedupe swallowed a real reassignment | Fixed: the 5-minute hold and the 20-an-hour cap; one notification per assignment (D3) |
| Code N1-N4 | Fixed: due dates in UTC, the rule before the user lock, `handed_back` audit reason, the reminder scan in SQL (14 statements to 1) |
| Code L1 / guest L4 making a project private kept outsiders | Fixed by the lead's D2: their research ends after a warning (`outside_researcher_count`) |
| Design point / guest L2 the researcher edits answers after Research | Fixed by D1 (c26, 409 `research_finished`) |
| Guest N2 404 timing; N5 a stream lasts until the 30 s re-check | Rejected (as since Phase 1; by design) |
| UX M1 an overdue date blocked the dialogs; M2 a guest's @mention listed the directory; M3 focus lost | Fixed (`pickerMin`, `MentionOptions.only`, focus to Change or the h1) |
| UX m1-m10, p1-p7, S2 | Fixed (one feed line per assignment, the picker's two groups, the guest's comment line, …); S1 decided as D4 (an owner asked by name stays the researcher) |
| Adversarial check of D1, D2 and the research-run reads | L1 (a research run's `list_projects` showed the private project): fixed; L2 (an outsider could still be asked past Research): fixed, 409 `research_finished`, Remove only; N1 (the private warning's count from page load): fixed; N2 (an unsaved answer hidden once read only): fixed, Copy and Discard |

Every decision with its reason: [decisions.md](../decisions.md) (Phase 8 and 8b sections,
"Phase 8b review leftovers", "Phase 8b adversarial check"); the API changes:
contract-phase8 §10, contract-phase8b §17.

## Known issues and deferred items

- **"Crossing only"**, guest access, D1-D4 and L2 are the lead's calls for the product
  owner to confirm ([release notes](../RELEASE-NOTES.md#decisions-to-confirm-in-020)).
- AI research runs are verified against Soundings' fake agent only (no kagent or LLM).
- A guest researcher **in no project at all** is tested on the SPA's mock only (the demo's
  internal projects are visible to everyone); reminders by date with a moved clock.
- Accepted: a guest's AI progress stream ends at its next 30 s re-check; research answers
  aren't audited (who and when are recorded).

## Screenshot index

Real stack, 1440 px light and dark and 390 px light, from freshly seeded data:

- **Phase 8** ([`docs/screenshots/phase-8/`](../screenshots/phase-8/)): `settings-research`,
  `settings-proposal-template`, `board-research-column`, `idea-research-open-item`,
  `idea-research-similar-ideas`, `research-gate-dialog`, `proposal-custom-template`,
  `proposal-research-appendix`; `pdf/`: TOOLS-3 (the six-section template, the research
  appendix) and GREEN-4 ("Carbon impact"), each as the PDF and its pages.
- **Phase 8b** ([`docs/screenshots/phase-8b/`](../screenshots/phase-8b/)):
  `assign-picker-outsider`, `start-research-dialog`, `research-panel-researcher-due`,
  `guest-researcher-idea`, `my-work-research-to-do-overdue`, and the follow-ups
  `research-read-only-past-research` (D1), `remove-researcher-past-research` (L2: Remove
  only) and `make-private-confirm` (D2); `emails/`: "Asked to research" as Mailpit
  received it (desktop light and dark, 390 px).
- **Emails** ([`docs/screenshots/phase-3/emails/`](../screenshots/phase-3/emails/)):
  `researcher_assigned` and `research_reminder` with every other template.
- **Tour** ([`docs/screenshots/tour/`](../screenshots/tour/)): 07 and 08 now show TOOLS-3's
  own template and its PDF with the research appendix; 13 `research-column`, 14
  `research-checklist`, 15 `research-gate`, 16 `outside-researcher`, 17
  `proposal-template`.
- Every other real-stack set (phases 1-6) was re-captured for 0.2.0 and read; the mock
  sets are in each phase's `mock/`.
