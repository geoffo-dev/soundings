# Test plan: Phase 1 (ideas, owners, evaluators)

Owner: qa. Source of truth for behaviour: [SPEC.md](../../SPEC.md) section 13,
[contract-phase1.md](../api/contract-phase1.md) (business rules §3),
[role-matrix.md](../role-matrix.md) §3 (blind evaluation) and
[ADR 0006](../adr/0006-blind-evaluation-and-aggregate-scoring.md). Each row below has an
ID used in the test names, so a failing test points back here.

## Acceptance criterion

> Create a project, submit an idea, assign an owner, have three evaluators score it
> blind, see the aggregate and ranking. (SPEC section 13, Phase 1)

It is tested twice, against the real stack both times:

| Level | Test | What it adds |
|---|---|---|
| HTTP API | `backend/tests/acceptance/test_phase1_acceptance.py` (AC-API-*) | Weighted rubric with an inverted criterion edited through the API; the aggregate against the contract formula incl. half-up rounding; every JSON payload walked for score data while an evaluator is pending; `sort=score` cursors decoded; ranking in both directions for a viewer and an internal non-member, on list and board. |
| Browser (UI) | `e2e/tests/acceptance.spec.ts` (AC-*) | The same story clicked and typed through the SPA, switching people through the real login page (dev login). |

The backend's own `tests/ideas/test_acceptance.py` covers the same criterion from the
builder's side; the rule-level suites under `backend/tests/` are referenced below where
they are the better place for a rule.

## How to run

| What | Command | Needs |
|---|---|---|
| API acceptance (part of `make check-backend`) | `make -C backend check`, or `cd backend && uv run pytest tests/acceptance` | Docker (testcontainers) or `TEST_DATABASE_URL` |
| E2E, local stack | `npm --prefix e2e ci && npm --prefix e2e test` | Docker, `uv`, Node 22, Chromium in `PLAYWRIGHT_BROWSERS_PATH` |
| E2E against a running app | `E2E_BASE_URL=http://localhost:8000 npm --prefix e2e test` (`make demo && make e2e`) | an app with the demo data and dev login |
| Screenshots | `npm --prefix e2e run screenshots` → `docs/screenshots/phase-1/` | freshly seeded data (the local stack reseeds) |
| One spec / headed | `npx --prefix e2e playwright test tests/board.spec.ts --headed` | |

**The local stack** (`e2e/scripts/start-stack.sh`, run by Playwright's global setup):
Postgres 16 in Docker (`p1-qa-pg`, 127.0.0.1:55433, tmpfs), `soundings migrate`,
`soundings seed --reset`, a Vite build of the SPA into `e2e/.stack/dist`, and
`soundings api` on http://localhost:8100 with the dev login. Global teardown stops it
(`E2E_KEEP_STACK=1` keeps it; the next run only reseeds). Why not the image: CI tests
the image (`make demo` / the GitLab `e2e` job set `E2E_BASE_URL`); locally the working
tree is what changes, and building it takes ~20 s instead of an image build. Both run
one process serving API + SPA, so the code paths are the same.

**Data.** Read-only tests use the seeded story (`backend/app/seed/content.py`). Tests that
change data create their own private project through the API (`createTeamProject`) and
archive it afterwards, so specs run in parallel and repeatedly against one database.
Facts the tests rely on:

| Seeded fact | Used by |
|---|---|
| CUST-11 "WhatsApp order updates": owner Bob; Kenji and Zanele submitted (3.4, high disagreement); Alice (platform + project admin) and Amara pending | BL-01…10, LF-02 |
| TOOLS-9: Alice has a draft (Value 4, Feasibility 3); Dave and Sven submitted | BL-07, screenshots |
| CUST: 20 ideas; CUST-16…20 new without evaluators; Alice owns CUST-2, 6, 8, 12, 17; only CUST-8 and CUST-11 flagged | LF-01…04 |
| TOOLS-6: Alice submitted, evaluation open (reveal) | A11Y, screenshots |

## Test cases

Status: ✅ passes, ❌ fails (a product bug, owner in brackets; see
[Known failures](#known-failures)).

### AC: acceptance (UI and API)

| ID | Case | Test | Status |
|---|---|---|---|
| AC-01 | A platform admin creates a project from the sidebar and adds members in settings | `acceptance.spec.ts` AC-01…07 | ✅ |
| AC-02 | A member submits an idea with `n` from the project page (project preselected, Ctrl/⌘+Enter) | same | ✅ |
| AC-03 | An admin assigns an owner (`a`, picker) | same | ✅ |
| AC-04 | The owner moves it to Evaluating (`s`) and invites three evaluators with a due date 10 days out | same | ✅ |
| AC-05 | Each evaluator: My work lists it; idea page, Evaluations tab and list show the blind state; `e` opens the sheet; score all criteria; submit; the reveal shows the earlier evaluators' scores; the blind lifts on the page; it leaves My work | same | ✅ |
| AC-06 | The owner sees the aggregate (3.7 / 5 · 3 evaluations), High disagreement, bars, all three evaluations; next step is Close evaluation | same | ✅ |
| AC-07 | The list sorted by score ranks 3.7, 3.0, unscored | same | ✅ |
| AC-08 | A member volunteers ("I'll own this") when the project allows it; the offer disappears when it doesn't | `acceptance.spec.ts` AC-08 | ✅ |
| AC-API-01…07 | The criterion through the API (see table above) | `test_phase_1_acceptance_through_the_api` | ✅ |
| AC-API-08 | A pending evaluator who is the project admin stays blind after evaluation closes and gets 403 `cannot_remove_self` | `test_a_pending_admin_evaluator_stays_blind_…` | ✅ |

### BL: blind evaluation (role matrix §3, contract §3.7)

| ID | Case | Test | Status |
|---|---|---|---|
| BL-01 | List: a lock instead of the score, no disagreement flag | `blind-leaks.spec.ts` (Alice and Amara) | ✅ |
| BL-02 | Board card: lock, no score, no flag | same | ✅ |
| BL-03 | Idea page: "Hidden until you submit", no bars, no score text anywhere in `main`; submission progress (2 of 4) still shown; Evaluations tab shows the hidden state and no evaluations | same | ✅ |
| BL-04 | My work: the evaluation is due; no score on any row for the idea | same | ✅ |
| BL-05 | ⌘K search result carries no score | same | ✅ |
| BL-06 | Wire level: no API response the SPA received has score data for the idea (`score`, `aggregate`, `high_disagreement`, `aggregate_score`, evaluation list, private comments) | same (`captureApi` + `expectNoScoreData`) | ✅ |
| BL-07 | A saved draft does not lift the blind | `blind-leaks.spec.ts` BL-07; API: AC-API-05 | ✅ |
| BL-08 | `high_disagreement` filter never matches the hidden idea (list and board) | `blind-leaks.spec.ts` BL-08/09; `list.spec.ts` LF-02; AC-API-05 | ✅ |
| BL-09 | Sort by score treats it as unscored; `sort=score` cursors never encode its score | `blind-leaks.spec.ts` BL-08/09; AC-API-05 (cursors decoded) | ✅ |
| BL-10 | Control: the owner sees the same idea's 3.4 and flag (proves the checks can fail) | `blind-leaks.spec.ts` BL-10 | ✅ |
| BL-11 | Closing evaluation keeps a pending evaluator blind ("Evaluation closed before you submitted") | `blind-leaks.spec.ts` BL-11; AC-API-08 | ✅ |
| BL-12 | Submitting lifts the blind in the next response / at once in the UI | AC-05, MO-01, AC-API-05 | ✅ |
| BL-13 | Every surface × viewer type (drafting, admin-owner, viewer, internal non-member, platform admin, AI present), demoted evaluators, removal releases | backend `tests/ideas/test_blind.py`, `tests/authz/` | ✅ (backend) |

### SC: aggregate and ranking (contract §3.8, §3.9)

| ID | Case | Test | Status |
|---|---|---|---|
| SC-01 | Weighted mean over active criteria, inverted = 6 − s, from unrounded means | AC-API-06 (weights 2/1/1, inverted Effort → 3.3); `tests/domain/test_scoring.py` | ✅ |
| SC-02 | Half-up rounding to 1 decimal (2.25 → 2.3) | AC-API-06; `test_rounds_half_up_from_unrounded_means` | ✅ |
| SC-03 | Per-criterion stats are raw (mean, min, max, spread); recommendations tallied | AC-API-06 | ✅ |
| SC-04 | High disagreement = spread ≥ 2 on a criterion with ≥ 2 scores | AC-06, AC-API-06; `test_high_disagreement` | ✅ |
| SC-05 | Ranking: `-score` and `score`, unscored last in both, same through keyset pages, on list and board | AC-07, LF-04, AC-API-07 | ✅ |
| SC-06 | Rubric replacement recomputes aggregates | backend `test_rubric_changes_recompute_the_aggregate` | ✅ (backend) |

### ST: status transitions (contract §3.3)

| ID | Case | Test | Status |
|---|---|---|---|
| ST-01 | The owner drags a card to another column (mouse) or moves it with the keyboard (Space, arrows, announced) | `board.spec.ts` | ✅ |
| ST-02 | Undo puts it back (inverse call; server state checked) | `board.spec.ts` | ✅ |
| ST-03 | Someone who may not change the status has no drag, and the API refuses (403) | `board.spec.ts` | ✅ |
| ST-04 | Dropping on Closed asks for a resolution | `board.spec.ts` | ✅ |
| ST-05 | Any → any, resolution rules, no side effects, same status is a no-op | backend `tests/ideas/test_status_owner.py` | ✅ (backend) |

### OW / EV: owner, volunteering, evaluator management (contract §3.4, §3.5)

| ID | Case | Test | Status |
|---|---|---|---|
| OW-01 | Admin assigns an owner | AC-03, AC-API-03 | ✅ |
| OW-02 | Member volunteers when allowed; not when switched off | AC-08; backend `test_member_volunteers`, `test_volunteer_conditions` | ✅ |
| EV-01 | Invite several evaluators with a due date | AC-04, AC-API-04 | ✅ |
| EV-02 | First invite sets the default window; later invites leave it; eligibility is all-or-nothing | backend `tests/ideas/test_evaluations.py` | ✅ (backend) |
| EV-03 | Remove (deferred Undo), can't remove self, can't remove a submitted evaluator | AC-API-08; backend `test_remove_rules`; frontend `idea-page.spec.ts` (mock) | ✅ |

### MW: My work (contract §3.10)

| ID | Case | Test | Status |
|---|---|---|---|
| MW-01 | Evaluations due appear with an Evaluate action that opens the sheet | AC-05, MO-01, BL-04 | ✅ |
| MW-02 | After submitting, the evaluation leaves My work | AC-05, MO-01, AC-API-05 | ✅ |
| MW-03 | Order (overdue first), counts, owned groups, recent | backend `tests/ideas/test_work.py` | ✅ (backend) |

### LF: list and board filters (contract §3.9)

| ID | Case | Test | Status |
|---|---|---|---|
| LF-01 | "Needs evaluators" = open ideas without evaluators (UI = API) | `list.spec.ts` | ✅ |
| LF-02 | "High disagreement" = flagged and not hidden from you (Alice: CUST-8; Bob: CUST-8, CUST-11) | `list.spec.ts` | ✅ |
| LF-03 | "Owner: me"; chips combine with AND | `list.spec.ts` | ✅ |
| LF-04 | Sort by score (both directions) matches the API; hidden/unscored last | `list.spec.ts` | ✅ |
| LF-05 | Filters live in the URL; Clear removes them | `list.spec.ts` | ✅ |

### KB: keyboard

| ID | Case | Test | Status |
|---|---|---|---|
| KB-01 | ⌘K / Ctrl+K jumps to an idea by key (exact key first) and by title, and to a project; empty state | `keyboard.spec.ts` | ✅ |
| KB-02 | `n` opens New idea in the project in view; typed-only submit | `keyboard.spec.ts` | ✅ |
| KB-03 | `e` opens the evaluate sheet with focus on the first score; digits score; Esc keeps the draft (server state checked) | `keyboard.spec.ts` | ✅ |
| KB-04 | `?` lists the shortcuts | `keyboard.spec.ts` | ✅ |
| KB-05 | `j`/`k` and Enter in the list | `keyboard.spec.ts` | ✅ |
| KB-06 | ⌘K keeps your selection when search results arrive late | `keyboard.spec.ts`; frontend `command-palette.test.tsx` | ✅ |
| KB-07 | Ctrl/⌘+K straight after a palette jump reopens the palette; typing stays in it (no "s" → Change status on the page behind) | `keyboard.spec.ts` | ✅ |

### MO: phone (390 × 844, touch)

| ID | Case | Test | Status |
|---|---|---|---|
| MO-01 | From My work to a submitted evaluation: full-height sheet, 44 px targets, Submit in view, reveal, score shown, bar gone | `mobile.spec.ts` | ✅ |
| MO-02 | List, board, idea page, rubric settings: no sideways page scroll, no serious axe violations | `mobile.spec.ts` | ✅ |

### A11Y: accessibility (axe, WCAG 2.2 AA rules; bar: zero serious/critical)

Every screen and overlay in light and dark: login, My work, board, list with a filter,
idea page (owner, pending evaluator), Evaluations tab, evaluate sheet, reveal, new idea,
command palette, shortcut sheet, project settings (general, members, rubric, statuses),
create project, not found — `a11y.spec.ts` (18 screens × 2 themes = 36 tests).

| ID | Case | Status |
|---|---|---|
| A11Y-light | All screens, light theme | ✅ |
| A11Y-dark | All screens, dark theme | ✅ |

### SS: screenshots

`e2e/screenshots/phase-1.spec.ts`: 14 screens × (1440 light, 1440 dark, 390 light) into
`docs/screenshots/phase-1/<screen>-<variant>.png`, from the real app and seeded data.

## Known failures

None. The four left failing on purpose in the QA hand-over were fixed in the Phase 1
integration:

| Test | Fix |
|---|---|
| KB-06 | The palette's highlight no longer follows late results once it rests on a current item or one you moved to (`components/ui/command-palette.tsx`; results for an earlier query are marked `pending`). |
| A11Y shortcut sheet (light, dark) | The scrolling list is a focusable, named region; from `sm` the sheet has two columns and doesn't scroll at 900 px. |
| A11Y command palette (dark) | The hint on the highlighted row uses `text-secondary`. |
| A11Y create project dialog (dark) | The "/p/" prefix uses `text-secondary`. |

## Screenshot review (2026-09-30)

Read from `docs/screenshots/phase-1/` (real app, seeded data). The QA hand-over's
findings, and what the integration did with them:

| Screen | Problem | Status |
|---|---|---|
| evaluate-sheet (all) | "Draft saved 18:10" for a draft saved two days earlier. | Fixed: "Draft saved 28 Sept" on other days (`lib/dates.ts formatTime`). |
| evaluations-tab-390 | The scores table is wider than the phone; the Mean column is off-screen. | Fixed: "lower is better" under the name, icon-only recommendations and a pinned Mean column on phones. |
| evaluations-tab-1440 | The aggregate appears twice side by side (tab card and sidebar). | Fixed: the tab's card shows only below `lg`. |
| command-palette-390 | The idea title is cut to ~15 characters while the hint takes half the row. | Fixed: the hint gives way first. |
| command-palette-1440-dark | Muted hint on the selected row: 3.75:1. | Fixed (`text-secondary`). |
| shortcut-sheet | Idea shortcuts below the fold; the list can't be focused. | Fixed: two columns from `sm`, focusable region. |
| project-list-390 | Card rows differ in height (the date wraps on some). | Fixed: tighter gaps on card rows. |
| project-list-1440 | With a filter applied the chips wrap to a second line. | Kept: a filter bar may wrap; it doesn't with the sidebar collapsed. |
| my-work-390 | The first Evaluate is full width, the others compact. | Kept by design: it is the page's one primary action, in thumb reach (`my-work.spec.ts` asserts it). |
