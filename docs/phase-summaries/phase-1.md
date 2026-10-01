# Phase 1 summary: ideas, owners, evaluators

**Status:** closed on 2026-10-01, waiting for the product owner's review before Phase 2.
**Scope (SPEC section 13):** projects, members, ideas, statuses, owner assignment,
evaluator invites, blind evaluations, rubric, aggregate score, disagreement flag,
comments, My work, Board/List, idea page, evaluate sheet, command palette, dev-only
login. **Acceptance:** create a project, submit an idea, assign an owner, have three
evaluators score it blind, see the aggregate and ranking. Met: see
[Acceptance evidence](#acceptance-evidence).

Commits: `c702ea4`, `9aaa3e5` (build), `0e7af04`, `5d3070c` (integration), `a8552f3`
(review fixes), plus this close-out (final verification, docs).

## What was built

| Area | What | Where |
|---|---|---|
| Contract | 43 REST operations under `/api/v1`, RFC 9457 problems with stable codes, cursor pagination, `permissions` objects computed by the policy | [contract-phase1.md](../api/contract-phase1.md), `backend/app/schemas/`, `frontend/src/api/generated/` |
| Identity | Server-side sessions (12 h idle, 7 days max, hashed tokens, rotation on sign-in), CSRF header, dev login, host check against `baseUrls` | `backend/app/auth/`, `app/middleware.py`, [ADR 0005](../adr/0005-server-side-sessions-oidc-csrf.md) |
| Authorisation | One deny-by-default policy, rules named as in the role matrix, used by routes and list queries alike | `backend/app/authz/`, [role-matrix.md](../role-matrix.md), [ADR 0010](../adr/0010-central-authorisation-policy.md) |
| Projects | Create (platform admins), members and roles, rubric (3–6 weighted, invertible criteria with guidance), status label renames, visibility, volunteering, evaluation window, archive | `app/services/projects.py`; SPA `features/project/settings/` |
| Ideas | Keys (`CUST-12`), five fixed statuses with resolutions, edit rules, tags, votes, watching, flat Markdown comments, activity feed, Undo | `app/services/ideas.py`, `features/idea/` |
| Owners and evaluators | Assign, volunteer, step down; invite several at once; first invite sets the default due date; remove with deferred Undo; close/reopen evaluation | `app/services/evaluations.py`, `features/idea/` |
| Blind evaluation and scoring | Per-viewer masking on every surface (pages, lists, board, sort, filters, search, cursors); weighted aggregate with inverted criteria, half-up rounding, disagreement flag (spread ≥ 2), cached and recomputed on rubric change | `app/domain/scoring.py`, [ADR 0006](../adr/0006-blind-evaluation-and-aggregate-scoring.md) |
| Screens | Login, My work, project Board and List (filters in the URL, keyboard card moves), idea page, evaluate sheet with reveal, Evaluations tab, New idea, command palette (⌘K), `?` sheet, project settings, personal Settings, in-app 404 | `frontend/src/features/`, `components/ui/` |
| Demo and ops | `soundings seed` (12 people, 3 projects, 45 ideas), `make demo`, Helm `demo.seed` hook, `/metrics` on its own port, 1 MiB body limit, k3s install/upgrade/smoke scripts | `app/seed/`, `scripts/`, `deploy/helm/` |
| Tests | Backend 2,762 (+ 10k-idea performance), frontend 204 unit + 105 page tests, e2e 70 against the real stack | `backend/tests/`, `frontend/src/**/*.test.ts*`, `frontend/tests/`, `e2e/tests/` |
| Docs | User guide (Phase 1 sections, keyboard shortcuts), operator guide (demo, Helm, hosts, sessions, metrics), decisions log, test plan | `docs/` |

## Acceptance evidence

All run on 2026-10-01 in the final verification, on the working tree that was committed.

| Criterion | Evidence (test names) |
|---|---|
| Create a project → submit an idea → assign an owner → three evaluators score blind → aggregate and ranking, through the API | `backend/tests/acceptance/test_phase1_acceptance.py::test_phase_1_acceptance_through_the_api` (AC-API-01…07: weighted rubric with an inverted criterion, aggregate against the contract formula, every JSON payload walked for score data while an evaluator is pending, `sort=score` cursors decoded, ranking for a viewer and a non-member); `backend/tests/ideas/test_acceptance.py::test_phase_1_acceptance` |
| The same story clicked and typed in the browser, switching people through the login page | `e2e/tests/acceptance.spec.ts` "AC-01…07: project → idea → owner → three blind evaluations → aggregate and ranking" (owner sees 3.7 / 5 · 3 evaluations, High disagreement; list ranks 3.7, 3.0, unscored), "AC-08: a member volunteers…" |
| Blind evaluation never leaks | `backend/tests/ideas/test_blind.py::test_every_surface` (every surface × drafting, admin-owner, viewer, internal non-member, platform admin), `::test_closing_evaluation_does_not_lift_the_blind`, `::test_demoted_pending_evaluators_stay_blind`, `::test_pending_admin_cannot_remove_themselves_to_peek`; `test_phase1_acceptance.py::test_a_pending_admin_evaluator_stays_blind_and_cannot_remove_themselves`; e2e `blind-leaks.spec.ts` BL-01…11 (wire-level capture of every API response) |
| Scoring and ranking | `backend/tests/domain/test_scoring.py` (`test_contract_worked_example`, `test_inverted_criteria_count_six_minus_the_score`, `test_rounds_half_up_from_unrounded_means`, `test_high_disagreement`); e2e `list.spec.ts` LF-04 |
| Authorisation | `backend/tests/authz/test_policy_matrix.py`, `test_policy_rules.py`, `test_queries.py`, `test_route_rules.py`; `tests/ideas/test_route_guards.py` |
| Status rules | `backend/tests/ideas/test_status_owner.py`; e2e `board.spec.ts` ST-01…04 |
| "10k ideas feels instant" (early check) | `backend/tests/ideas/test_performance.py::test_list_and_board_at_10k_ideas`: list, board, My work (an evaluator with 1,000 due) and search p95 < 150 ms |
| Works on Kubernetes | k3s v1.31 with the Restricted Pod Security Standard: `make k3s-install` (dev login + demo seed) → `make k3s-smoke` (health, SPA, OpenAPI, metrics only on 9090, 413 for 2 MiB both ways, dev login + CSRF + My work, `helm test`) → `helm upgrade` with a changed value (pods rolled, seed hook a no-op) → smoke again → `make k3s-down` |

### Checks (final verification, 2026-10-01)

| Check | Result |
|---|---|
| `make -C backend check` | pass: ruff, ruff format, mypy --strict (142 files), pytest 2,762 passed, 1 skipped (no 501 stubs left), 1 deselected (slow) |
| `make -C backend test-slow` | pass (10k-idea performance) |
| `npm --prefix frontend run check` | pass: tsc, eslint + prettier, vitest 32 files / 204 tests, build |
| `npm --prefix frontend run test:pw` | pass: 105 passed, 37 skipped (mock screenshot specs, run with `SCREENSHOTS=1`) |
| `npm --prefix e2e test` | pass: 70 passed, real stack from cold |
| `npm --prefix e2e run check` | pass |
| `make check-helm`, `make check-scripts` | pass (shellcheck through its container) |
| `make gen-api` | no diff |
| Image | `make image IMAGE_BUILD_ARGS="--build-arg RUNTIME_APT_PACKAGES="` (no Debian mirror in this sandbox) |

## Review findings and outcomes

Two reviews ran at the end of the build: `code-reviewer` (code, security, OWASP ASVS L2)
and `ux-reviewer` (Linear-grade UX, WCAG 2.2 AA). Backend fixes were test-first: every
reproducible finding got a test that failed before its fix. Frontend fixes came with new
unit and page tests, mirrored against the real stack in e2e KB-08…13.

### Code and security

| # | Finding | Outcome | Tests |
|---|---|---|---|
| F1 (high) | Unbounded request bodies: a 200 MB anonymous POST took the API to 690 MB | Fixed: 413 `content_too_large` above 1 MiB before auth, chunked bodies cut off; chart docs and production example | `tests/api/test_request_limits.py`; `scripts/k3s-smoke.sh` (through Traefik) |
| F2 (medium) | Rubric replacement racing an evaluation save: deadlock (500), stale cached aggregate, FK violation | Fixed: one lock order, project (`FOR KEY SHARE`) then idea | `tests/ideas/test_lock_order.py` (5) |
| F3 | NUL bytes in bodies, `q`, `tag` or cursors could give a 500 | Fixed: 422, or 400 `invalid_cursor` | `tests/ideas/test_input_robustness.py` (incl. a sweep of every string parameter in the OpenAPI document) |
| F4 | Forged cursors with out-of-range values could give a 500 | Fixed: 400 `invalid_cursor` | `test_list_board.py::test_cursor_values_out_of_range_are_invalid`, `::test_activity_cursor_out_of_range_is_invalid` |
| F5 | Due dates had no bounds (far past or future values reached the database) | Fixed: a year ago to five years ahead, else 422; the SPA pickers stop at five years | `test_evaluations.py::test_due_dates_outside_a_sane_window_are_a_422`; `due-date.test.ts` |
| F6 | Unsent drafts readable by the next person on the browser | Fixed: per-user drafts, cleared on sign-out, 401, user switch | `lib/drafts.test.ts`, `features/auth/session.test.ts`; e2e KB-13 |
| F7 | `?next=` accepted `\` and other origins (open redirect) | Fixed: `safeNextPath` | `frontend/tests/auth.spec.ts` |
| F8 | `seed --reset` would wipe a real database in development mode | Fixed: needs `--force` once a non-demo person has an account | `test_seed.py::test_reset_needs_force_unless_everyone_is_a_demo_person` |
| — | Saving an evaluation checked 409 before 422 | Fixed: 403 → 422 → 409 | `test_save_checks_422_before_409` |
| F9 | `GET /me/work` returns every evaluation due, uncapped | **Kept for Phase 1**: p95 118 ms with 1,000 due among 10k ideas; revisit with real data | `test_performance.py` now covers My work and search |
| F10 | Cookies without the `__Host-` prefix | **Deferred to Phase 2** (needs `Secure`, breaks http://localhost; sign-in is reworked then) | — |

### UX and accessibility

| # | Finding | Outcome |
|---|---|---|
| M1 | Focus fell to `<body>` after dialogs, sheets and inline edits | Fixed once in `components/ui/return-focus.ts` (opener, menu button, or `#main` after navigation); e2e KB-08 |
| M2 | Pickers didn't highlight the typed match; in the owner picker Enter **removed the owner** | Fixed: `useTopResult` in all four pickers, "Remove owner" hidden while searching; e2e KB-09 |
| M3 | ⌘/Ctrl+Enter in Invite toggled a row instead of submitting | Fixed in the `Command` wrapper; e2e KB-10 |
| M4 | Palette buried commands and projects under weak idea matches | Fixed: commands and projects first, groups by best match; e2e KB-11 |
| M5 | Leaving settings lost edits silently | Fixed: confirm on links, Back and tab close; sticky save bar; e2e KB-12 |
| M6 | Unnamed popovers, messages inside the listbox | Fixed (`CommandList empty`), axe clean |
| m1–m13 | Error copy, viewer copy, draft time, settings page, in-shell 404, empty project, filter toolbar, sort options, ←/→ board columns, evaluate-sheet preview, skeleton announcements, live regions, modal menus | Fixed (m11 differently: the label is announced after 300 ms instead of `aria-busy`) |
| p1–p8 | Polish | Fixed, except p5/p6 partly (see Known issues) |

The integration before the reviews fixed the QA hand-over's four failing tests (KB-06
late palette results, KB-07 Ctrl+K after a jump, two contrast failures fixed at the
`--fg-muted` token with a contrast test) and the screenshot review items
([test plan](../test-plans/phase-1.md#screenshot-review-2026-09-30)).

### Final verification (this close-out)

- **Phone palette rows** cut the idea title while showing the hint: the hint now takes
  only the room the title leaves (`components/ui/command-palette.tsx`).
- **Due-date pickers** offered dates the API refuses: `max` is five years ahead
  (`features/idea/due-date.ts`, both pickers, new `due-date.test.ts`).
- **e2e mirror of the keyboard flows** (KB-08…13, `e2e/tests/keyboard-flow.spec.ts`).
- Docs: this summary, user and operator guides, decisions, contract error table (400
  `invalid_host`, 413 `content_too_large`) and the F9 decision, CLAUDE.md conventions.

## Known issues and deferred items

| Item | Why / when |
|---|---|
| `/me/work` uncapped (F9) | Within budget at 1,000 due; revisit (cap 100, count = total) if real data says otherwise. |
| No `__Host-` cookie prefix (F10) | Phase 2, with OIDC sign-in. |
| Drafts are cleared on a 401, so an expired session loses an unsent draft | Deliberate: security over convenience on shared machines. |
| A due date typed by hand beyond five years and sent with ⌘↵ (bypassing the picker's `max`) gets a 422 error toast | Edge case; the picker itself stops at five years. |
| UX polish deferred to Phase 7: smaller empty-section cards, a scroll hint on the phone filter row (needs a gradient token), uneven meta-row wrapping on phones, the evaluate sheet header's height | Polish, not defects. |
| Filter chips wrap to a second line at 1440 px with three or more active filters | Kept: a filter bar may wrap. |
| The Proposal tab is a placeholder; comments have no @mentions; only the dev login | By plan: Phases 4, 3 and 2. |
| Traefik (k3s's default ingress) has no body limit at the edge | The app enforces 1 MiB itself; the chart README shows the optional Middleware. |
| Image builds here skip the runtime apt packages (no Debian mirror), so PDF export libraries are missing | Sandbox only; matters from Phase 4. The GitLab pipeline was not run in this sandbox. |
| The frontend's mock screenshots (`docs/screenshots/phase-1/mock/`) are not committed | Regenerate with `npm --prefix frontend run screenshots`; the real-stack set below is the review set. |
| `docs/screenshots/phase-0/` is no longer produced by any spec | Kept as the Phase 0 review record. |
| SPEC.md still says `backend/migrations/` (it is `backend/app/migrations/`) | SPEC is read-only. |

## Simplifications proposed (SPEC section 15, item 3)

Each avoided a new settings screen or concept; all are in [decisions.md](../decisions.md).

1. **Five fixed statuses, renamable labels only**: no workflow designer.
2. **Only platform admins create projects**, and the creator is the first admin (no admin
   picker, no `can_create_projects` flag until another rule grants creation).
3. **Status changes have no side effects** (no automatic transitions or due dates);
   Undo is the inverse call. Only the first invite sets the default due date.
4. **Undo without undo endpoints**: inverse calls, or DELETEs held back while the toast
   shows.
5. **No tag management screen**: tags are free text and only tags in use are listed.
6. **Phones reuse the desktop screens**: filters scroll sideways (no bottom sheet), board
   columns snap-scroll (no status tabs).
7. **Personal settings are three sections** (account, theme, projects you manage);
   notification preferences join in Phase 3 rather than a placeholder now.
8. **Close/reopen evaluation stay two buttons** (two POSTs), not an "evaluation state"
   setting.

Question for the product owner: keep "only platform admins create projects" (row 2), or
let project admins create projects too?

## Screenshot index

Real app, freshly seeded demo data, `npm --prefix e2e run screenshots`; 1440 × 900 light
and dark, 390 × 844 light. All 42 were read after the final capture.

| Screen | Light | Dark | Phone |
|---|---|---|---|
| Sign in (dev login) | [1440](../screenshots/phase-1/login-1440-light.png) | [1440](../screenshots/phase-1/login-1440-dark.png) | [390](../screenshots/phase-1/login-390-light.png) |
| My work | [1440](../screenshots/phase-1/my-work-1440-light.png) | [1440](../screenshots/phase-1/my-work-1440-dark.png) | [390](../screenshots/phase-1/my-work-390-light.png) |
| Project board | [1440](../screenshots/phase-1/project-board-1440-light.png) | [1440](../screenshots/phase-1/project-board-1440-dark.png) | [390](../screenshots/phase-1/project-board-390-light.png) |
| Project list (filtered, by score) | [1440](../screenshots/phase-1/project-list-1440-light.png) | [1440](../screenshots/phase-1/project-list-1440-dark.png) | [390](../screenshots/phase-1/project-list-390-light.png) |
| Idea page (owner, with scores) | [1440](../screenshots/phase-1/idea-page-1440-light.png) | [1440](../screenshots/phase-1/idea-page-1440-dark.png) | [390](../screenshots/phase-1/idea-page-390-light.png) |
| Idea page (pending evaluator, blind) | [1440](../screenshots/phase-1/idea-page-blind-1440-light.png) | [1440](../screenshots/phase-1/idea-page-blind-1440-dark.png) | [390](../screenshots/phase-1/idea-page-blind-390-light.png) |
| Evaluate sheet (draft) | [1440](../screenshots/phase-1/evaluate-sheet-1440-light.png) | [1440](../screenshots/phase-1/evaluate-sheet-1440-dark.png) | [390](../screenshots/phase-1/evaluate-sheet-390-light.png) |
| Evaluate sheet (reveal after submitting) | [1440](../screenshots/phase-1/evaluate-sheet-revealed-1440-light.png) | [1440](../screenshots/phase-1/evaluate-sheet-revealed-1440-dark.png) | [390](../screenshots/phase-1/evaluate-sheet-revealed-390-light.png) |
| Evaluations tab | [1440](../screenshots/phase-1/evaluations-tab-1440-light.png) | [1440](../screenshots/phase-1/evaluations-tab-1440-dark.png) | [390](../screenshots/phase-1/evaluations-tab-390-light.png) |
| New idea | [1440](../screenshots/phase-1/submit-idea-1440-light.png) | [1440](../screenshots/phase-1/submit-idea-1440-dark.png) | [390](../screenshots/phase-1/submit-idea-390-light.png) |
| Command palette | [1440](../screenshots/phase-1/command-palette-1440-light.png) | [1440](../screenshots/phase-1/command-palette-1440-dark.png) | [390](../screenshots/phase-1/command-palette-390-light.png) |
| Project settings: general | [1440](../screenshots/phase-1/project-settings-1440-light.png) | [1440](../screenshots/phase-1/project-settings-1440-dark.png) | [390](../screenshots/phase-1/project-settings-390-light.png) |
| Project settings: rubric | [1440](../screenshots/phase-1/project-settings-rubric-1440-light.png) | [1440](../screenshots/phase-1/project-settings-rubric-1440-dark.png) | [390](../screenshots/phase-1/project-settings-rubric-390-light.png) |
| Keyboard shortcuts (`?`) | [1440](../screenshots/phase-1/shortcut-sheet-1440-light.png) | [1440](../screenshots/phase-1/shortcut-sheet-1440-dark.png) | [390](../screenshots/phase-1/shortcut-sheet-390-light.png) |
