# Test plan: Phase 8 (per-project proposal templates and the research step)

Owner: qa. Source of truth for behaviour: the product owner's decisions in
[decisions.md](../decisions.md) ("Phase 8 (product owner, 2026-10-07)", superseding SPEC's
fixed template and fixed lifecycle where they differ), [contract-phase8.md](../api/contract-phase8.md)
(templates §2, the research step §3: lifecycle §3.2, settings §3.3, answers §3.4, the gate
§3.5, reads §3.6, Similar ideas §3.7, the exports' appendix §3.8, public tracking §3.9,
MCP §3.11, AI §3.12, screens §2.7 and §3.13, demo data §3.14, minimum tests §6),
[role-matrix.md](../role-matrix.md) (`project.edit_proposal_template`,
`project.edit_research`, table K `idea.answer_research`, `idea.research_override`, c7
widened, c22) and [ADR 0015](../adr/0015-proposal-templates-and-research-step.md). Each row
has an ID used in the test names, so a failing test points back here. The Phase 1–7 plans
still apply; their suites run in every mode next to the Phase 8 specs.

## What the product owner asked for, and where it is tested

| Requirement (decisions, Phase 8) | Acceptance (HTTP, live server) | Browser (real stack) | Rules (owners' unit tests) |
|---|---|---|---|
| **A.** Project admins add, remove, rename and reorder proposal sections (1–12; title 1–60, hint ≤ 200); keys stable, slugs for new ones | AC8-API-1 | TPL-01, TPL-02 | `tests/proposals/test_template.py`, `tests/test_schemas_phase8.py` |
| Removing archives (text kept, hidden); "Removed sections" restores it with its text | AC8-API-1 | TPL-01 | `tests/proposals/test_template.py` |
| Live: the editor, threads, suggestions, PDF, Markdown, "Draft with AI" and MCP follow the template; a removed or unknown key is a clean 4xx / tool error | AC8-API-1 | TPL-01, TPL-03, TPL-03b, TPL-04, TPL-05 | `tests/proposals/test_template.py`, `tests/mcp/test_research.py`, `tests/ai/test_research_gate.py` |
| The migration carries existing proposals, threads, suggestions and AI runs over without loss (up/down/up on Phase 7 demo data) | AC8-MIG | — | `tests/test_domain_schema_phase8.py`, `tests/test_domain_schema.py` |
| **B.** Research step Off / Before evaluation / Before proposal; a Research column at that position; switching refused while ideas are in Research (409 with the count) | AC8-API-2, AC8-API-3 | RS-01, RS-07, RS-06 (off) | `tests/research/test_settings.py` |
| A per-project checklist (1–10 items, title, hint, Required), the default three offered when the step is turned on; removing archives | AC8-API-2 | RS-01 | `tests/research/test_settings.py` |
| Free-text answers (1–2,000), who and when, edit and clear by the same people; invisible-only text isn't an answer | AC8-API-2 | RS-03 | `tests/research/test_answers.py` |
| **The gate**: no move past Research with a required item open (status change, board drag, first evaluator invite, "Ask AI to evaluate", starting a proposal, reopening from Closed); back and to Closed never blocked; all-optional never blocks | AC8-API-2, AC8-API-3 | RS-02, RS-06, RS-08, RS-09 | `tests/research/test_gate.py` (31), `tests/ai/test_research_gate.py` |
| "Move anyway" for project and platform admins only (audited, optional reason); never for owners or any API key | AC8-API-2, AC8-API-3 | RS-04, RS-06, RS-09 | `tests/research/test_gate.py`, `tests/authz/test_policy_matrix.py` |
| Who answers: owner, project admins, platform admins; everyone who can view reads (pending evaluators too); answering is a write-scope key operation; agents' keys never answer (c22) | AC8-API-2 | RS-03 | `tests/research/test_answers.py`, `tests/authz/test_key_scopes.py`, `tests/authz/test_route_rules.py` |
| Similar ideas: pg_trgm, top 5, across the projects the viewer can see (archived ones too), **never held ideas**, never other people's private projects, a key's projects only; no score data | AC8-API-4 | RS-05 | `tests/research/test_similar.py` (incl. the full-scan check) |
| "Ask AI to research" on the panel; research answers shown to evaluators; the exports end with "Research and consultation" while the step is on | AC8-API-2 | RS-03, TPL-04 | `tests/proposals/test_research_appendix.py` |
| Public tracking never shows Research (the status before it); no submitter email for moves it hides | — | RS-10 | `tests/public/test_research_public.py` |
| Demo seed: TOOLS before evaluation with a custom template and two ideas in Research (complete / one open); GREEN before the proposal with Carbon impact; CUST defaults | AC8-API-3 (GREEN) | RS-05 (TOOLS-11), RS-08, TPL-04 | `tests/test_seed.py` |
| Calm UI: loading, empty and error states, dark mode, keyboard, 390 px, WCAG 2.2 AA | — | A11Y8-*, MO8-01, RS-02 (keyboard drag, focus back on the card), RS-03 (focus stays on the field) | `frontend/tests/research.spec.ts`, `frontend/tests/proposal-template.spec.ts` (MSW mock) |

## Acceptance through the HTTP API (`backend/tests/acceptance/test_phase8_acceptance.py`)

The app behind a real **uvicorn** on a free port with the **demo data** (`soundings seed`),
people signed in with the dev login (session cookie and CSRF header), API keys as bearer
tokens with no cookie, the official **MCP Python SDK** client on `/mcp`, PDFs rendered by
the real WeasyPrint child and read back with pypdf. About 2 minutes for the four tests.

| ID | Story | What it checks |
|---|---|---|
| AC8-API-1 | A project admin customises the proposal template | Bob's Customer Innovation idea gets a proposal (8 default sections, each written). Priya (project admin, not a platform admin) moves Risks up, renames Market & users → **Customers**, removes **Cost & effort** (it has text) and adds **Pilot plan**: keys `summary, risks, problem, solution, market, benefits, next_steps, pilot_plan` (renamed keeps `market`, the new one is a slug), positions 0–7, `removed_sections = [cost]` with its `proposal_count`; one `project.proposal_template_replace` audit entry (`added`, `archived`, `renamed`, `reordered`; no titles or hints). The proposal follows at once: order, title and hint (`prompt`), the renamed section's text kept, the new one empty at version 1, the removed one's text nowhere. A removed or unknown key: `PUT /sections/{key}` 404, threads and suggestions 422 `unknown_section`. **Markdown** headings exactly the template's, no removed section, no appendix (step off); **PDF** text in the same order without the removed section. **MCP** (Carol's write+mcp key): `get_proposal` lists the active keys and titles, `propose_proposal_section` on `cost` is the tool error `unknown_section`, on `pilot_plan` a suggestion. An admin's write key can't replace the template (403 `insufficient_scope`), a member's session can't (403). **Restore**: putting `cost` back brings its text back at its old version; renaming Pilot plan → Trial plan keeps the key, text and thread; an empty template is 422. |
| AC8-API-2 | The research gate, every path | Priya turns the step on "Before evaluation" with the offered default checklist (a member is 403): lifecycle of six, the board's six columns, `project.research_step_change {off → before_evaluation}` and `project.research_checklist_replace` audited. Bob's idea: progress 0/3 with 2 required open while New; New → **Research** (never guarded), its card shows the progress. **Refused** for the owner: Research → Evaluating 409 `research_incomplete` with exactly the two required titles, `can_override: false`, the contract's detail; "Move anyway" 403 `forbidden`; Shortlisted and Proposal refused too (the board drag is the same request); the first evaluator invite refused for the owner and for an admin (who gets `can_override: true`); `invite_blocked_by_research`; straight from New refused, and **New → Closed → Evaluating** refused (closed from New). **API keys**: Bob's write key refused the same way; no key may override, not even a platform admin's (403 `insufficient_scope`); a read key can read the checklist but answering is 403 `insufficient_scope`; the write key answers the first item. **MCP**: the ten tools only (none moves an idea or answers), `get_idea.research` with the step, items, answers and `required_open`, `search_ideas` with `status: [research]`. An **AI agent's key** during its own research run: REST answer 403 `insufficient_scope`; `get_idea` with its `run_id` reads the checklist. Carol (member) and Erin (viewer) read it but answering is 403; a zero-width + bidi-only answer is 422. Bob answers the second item, edits it (first author and time kept), progress 2/3, `blocking: false`; then it moves on with no audit entry; clearing an answer afterwards never moves it back and its card shows no progress past Research. **Move anyway**: Priya moves another idea on with a reason → `idea.research_override {operation: change_idea_status, research → evaluating, open_items: 2, reason}` and the feed's `research_overridden: true`; Alice "invites anyway" (`add_evaluators`, new → new); the flag with nothing open adds no entry. The step can't be switched off or moved while an idea is in Research (409 `ideas_in_research`, `idea_count: 1`); moving it back is never guarded. The exports end with **Research and consultation** (Markdown: answered items in order, "Answered by Bob Brown", line breaks as hard breaks, `[`, `]` and `*` escaped, no HTML; PDF: the same text). Switched **off**: lifecycle of five, no Research column, `research_step_off` for the status and answers, `research: null`, no appendix, the checklist kept; **on again** with the same ids: every answer back. |
| AC8-API-3 | "Before proposal" (the demo's Sustainability) | GREEN's lifecycle has Research between Shortlisted and Proposal. **GREEN-6** (Shortlisted, checklist started; Amara owns it and is the admin): `start_blocked_by_research`, starting the proposal and the status change to Proposal are 409 `research_incomplete` (`can_override: true`); into Research is free, on from there refused; Zanele (member, not owner) is 403 with or without the override. "Start anyway" passes through `create_proposal`'s move: one `idea.research_override {create_proposal, research → proposal}`, `research_overridden` in the feed, and the proposal has GREEN's nine sections with `carbon_impact` after `benefits`. GREEN-4's seeded proposal: Carbon impact and the appendix last. |
| AC8-API-4 | Similar ideas never shows held or private ideas | The demo holds "Repair café in the flagship store" for moderation; another near-identical idea arrives through the **public form with a real ALTCHA** and is held for **email verification**. Bob's Customer Innovation idea "Repair café in the flagship store on Saturdays": for Alice (platform admin), Bob, Carol and Dave, never a held idea (either kind), never the idea itself, ≤ 5, similarity ≥ 0.3 and sorted, no score data; an **archived** project's idea is included for all. Dave's Internal Tools (private) idea: shown to Carol and Dave (members), never to Bob; Carol's key restricted to Customer Innovation doesn't see it. Approving the moderated idea makes it findable. |

**AC8-MIG — the migration on Phase 7 demo data (run by QA on 2026-10-08; repeatable):**
`git archive 0046a9a backend` (release 0.1.0); with that code `soundings migrate` and
`soundings seed` into a scratch Postgres (`p8-qa-mig`), then, through the Phase 7 API,
proposals on two Customer Innovation ideas with all eight sections written, three margin
threads with replies, three suggestions and an AI draft run each (the 0.1.0 seed has no
proposals). Snapshot every `proposal_sections` (key, text md5, version, author, time),
`proposal_threads`, `proposal_comments`, `proposal_suggestions`, `ai_runs`, `ideas` and
`proposals` row. **Up** to 0013 with the current tree: every row identical, eight
template rows per project in the default order, step off; the Phase 8 app reads them
(sections, threads, suggestions, Markdown, `proposal_count`). Then Phase 8 data (Cost &
effort removed while it has text, a new section written, Sustainability's step on, an idea
in Research with an answer). **Down** to 0011: every Phase 7 row identical again (the
removed section's text back, the new section's rows gone, the idea back in New). **Up**
again: identical. Result: no loss in either direction.

## Browser, real stack (`e2e/tests/`)

Specs that change a template or a step use a project of their own (`tests/support/research.ts`
`researchTeam`, `setResearchStep`, `answerItem`, `answerRequired`, `proposalTemplate`,
`setProposalTemplate`, `similarIdeas`); RS-08, TPL-04 and the a11y screens read the
seeded Internal Tools and Sustainability story without changing it.

| ID | Spec | What it checks |
|---|---|---|
| RS-01 | `research.spec.ts` | An admin turns the step on in Project settings → Research: Off checked, "Before evaluation" fills in the default checklist (3 items), Save → toast; the API has the step and items (two required); lifecycle of six; `project.research_step_change` audited; the board's Research column sits between New and Evaluating. A member reads the step and checklist with no Save. |
| RS-07 | `research.spec.ts` | While an idea is in Research the settings say "Move the 1 idea in Research to another status first", the step's radios are disabled, the API answers 409 `ideas_in_research` (`idea_count: 1`), "Show them" opens the board filtered on Research. |
| RS-02 | `research.spec.ts` | Board cards show "Research 0 of 3 answered, 2 required items open" (in Research and in New, the status before it). The owner's keyboard drag to Evaluating is refused: the dialog "Finish the research first" names the idea and target, lists the two open items, offers no "anyway"; Escape → focus back on the card in Research, status unchanged. "Open research" → the idea page at `#research` with the first open item focused. The list filters on Research. |
| RS-04 | `research.spec.ts` | An admin's drag: "Move anyway…" → reason (focused) → "Move anyway": the card in Evaluating, the toast, the audit entry with the reason, the feed "to Evaluating without finishing research". |
| RS-03 | `research.spec.ts` | The owner on the idea page: "0 of 3 answered · 2 required items left before Evaluating", "Finish research" focuses the first item (hint as placeholder), Save answer keeps focus, "Research complete", "Answered by Bob Brown", the API agrees, "Start evaluation" moves it with no audit entry. Members and viewers read answers and "Not answered yet" with no fields or Clear; a member's API answer is 403. Clear has Undo. |
| RS-05 | `research.spec.ts` | Similar ideas finds a near-identical Customer Innovation idea and never the seeded held "Repair café in the flagship store" (API and panel); the empty state for a unique title; the seeded TOOLS-11 finds CUST-14. |
| RS-06 | `research.spec.ts` | "Before proposal": the owner (member) sees "Finish the research checklist first" and "Open research" instead of "Start proposal"; an admin's "Start proposal" → the dialog → "Start anyway" → the editor, status Proposal, `create_proposal` audited. "Before evaluation": the owner sees "Finish the research checklist before inviting evaluators" (the API refuses his invite, `can_override: false`); an admin keeps "Invite evaluators", is warned in the dialog, invites → the gate → "Invite anyway" → an evaluator, `add_evaluators` audited. Turning the step off removes the column and the panel and keeps the answers. |
| RS-08 | `research.spec.ts` | The demo story as Sven: TOOLS-11 "3 of 3 answered, complete", TOOLS-12 "1 of 3 answered, 1 required item open", no badge past Research; dragging TOOLS-12 is refused naming "Departments or teams consulted". |
| RS-09 `@ai` | `research.spec.ts` | "Ask AI to evaluate" (the first evaluator) before evaluation: the owner's API request is 409 `research_incomplete`, the AI menu says "Finish the research checklist first"; an admin asks → the dialog → "Ask anyway" → the run starts; `request_ai_evaluation` audited (new → new, 2 open). Runs with `E2E_AI=1`. |
| RS-10 | `research.spec.ts` | A public submission in a "Before proposal" project moved Evaluating → Shortlisted → Research: tracking reads Shortlisted, no Research in the history or on the page. "Before evaluation": New → Research reads New (with the team), and Evaluating → Research reads New again; no Research row in the history. |
| TPL-01 | `templates.spec.ts` | Project settings → Proposal: rename Market & users → Customers, Move Risks up (menu), Add section (focused) with a hint, Remove Cost & effort (asks: "Its text in 1 proposal is kept"), Save → toast, "Removed sections" with "Text in 1 proposal"; keys stable and the new one a slug; the owner's editor follows (headings, outline order, the hint as placeholder, the renamed section's text, no removed section); **Markdown and PDF downloads** follow; Restore → nine sections (the restored one focused), Save, its text back in the editor. |
| TPL-02 | `templates.spec.ts` | A member reads the template ("Only project admins can change them.") with no fields; the API refuses a member's save. |
| TPL-03 | `templates.spec.ts` | Text typed into a section removed meanwhile: the autosave's 404 keeps it ("Your text for Risks") **and the editor says it was removed** (P8-QA-F1, fixed at integration; the mark is gone). |
| TPL-03b | `templates.spec.ts` | After a reload the kept text is there, "“Risks” was removed from the template", the section gone. |
| TPL-04 | `templates.spec.ts` | TOOLS-3 (Kenji): outline Summary, Problem, Solution, Effort & rollout, Risks, The ask; The ask's hint; the appendix region with the seeded consultation and "Answered by Kenji Watanabe". GREEN-4 (Zanele): Carbon impact written. |
| TPL-05 `@ai` | `templates.spec.ts` | "Draft with AI" against the fake agent in a project whose template removed Cost & effort and added Pilot plan: a draft for the removed (`cost`) or an unknown key is 422 `unknown_section` before any run; a draft for `pilot_plan` ends as that section's suggestion (P8-QA-P1, fixed at integration; the mark is gone). |
| A11Y8-* | `a11y-phase8.spec.ts` | axe WCAG 2.2 AA (serious/critical none), light and dark: Research settings (locked, checklist), Proposal settings with a removed section, the TOOLS board, the gate dialog, TOOLS-12's answerable panel, TOOLS-11's complete panel with Similar ideas, TOOLS-3's editor with the appendix; axe best-practice rules on the screens without overlays (light). |
| MO8-01 | `a11y-phase8.spec.ts` | The same screens at 390 px without sideways scrolling. |

## How to run

| What | Command | Needs |
|---|---|---|
| API acceptance (part of `make check-backend`) | `cd backend && uv run pytest tests/acceptance/test_phase8_acceptance.py` (about 2 min) | Docker (Postgres testcontainer); Pango for the PDF (it skips without WeasyPrint) |
| Phase 8 browser specs | `npx --prefix e2e playwright test research templates a11y-phase8 --project=e2e` | the local stack (or `E2E_BASE_URL` with the demo data) |
| With AI (RS-09) | `E2E_AI=1 npx --prefix e2e playwright test --grep @ai --project=e2e` | the fake agent (8183) |
| Everything | `npm --prefix e2e test`, `E2E_SSO=1 …`, `E2E_AI=1 …` | |
| Screenshots | `npm --prefix e2e run screenshots:phase8` → `docs/screenshots/phase-8/` (+ `pdf/`) | fresh demo data (the local stack reseeds on start); read-only |

## Results (2026-10-08, QA)

| Run | Result |
|---|---|
| `test_phase8_acceptance.py` | 4 passed (79 s); ruff, format and mypy clean |
| AC8-MIG (0.1.0 data, up/down/up) | no loss in either direction |
| e2e, default mode, every suite (local stack, fresh seed) | 284 passed, 64 skipped (the `@ai`/`@sso` specs), 0 failed (12.1 min); TPL-03 is the pinned expected failure |
| e2e, `E2E_AI=1`, `--grep "@ai\|RS-\|TPL-\|A11Y8\|MO8"` | 77 passed, 1 failed: RS-02's keyboard drag raced the drag library (no "Picked up" yet); the drags now wait for its announcements, and RS-02 passed 3 of 3 after. TPL-05's second test is the pinned expected failure |
| e2e, `E2E_SSO=1`, `--grep "@sso\|RS-\|TPL-"` | 46 passed, 3 skipped (`@ai`), 0 failed |
| `npm --prefix e2e run check` | tsc and prettier clean |
| `npm --prefix e2e run screenshots:phase8` | 25 passed: `docs/screenshots/phase-8/` (8 screens × 1440 light, 1440 dark, 390 light) and `pdf/` |

### Integration (2026-10-08)

| Run | Result |
|---|---|
| `make -C backend check` | ruff, format, mypy (435 files) clean; 6,938 passed, 1 skipped (no 501 stubs left) |
| `make -C backend test-slow` | statement budgets and N+1 checks pass; p95: only "me.work (owner)" over 150 ms (156-214 ms over three runs; 0.1.0's code, `git archive 0046a9a`, 162 ms on the same machine), board by score 130-160 ms |
| `npm --prefix frontend run check` / `test:pw` | 626 vitest; 403 passed + 2 timing failures under load (the palette's My work heading; the appendix behind the lazy editor), both green on rerun, the second given 10 s |
| e2e default / `E2E_AI=1` / `E2E_SSO=1` (full suites) | 286 / 326 / 307 passed, 0 failed (TPL-03 and TPL-05 without their marks) |
| `make check-fake-agent`, `check-helm`, `check-scripts`, `gen-api` | pass; no API diff |
| `make image` | 524 MB |
| k3s (`p8-int-k3s`) | 0.1.0 with demo data, upgraded to the Phase 8 image (0011 → 0013), smoke; then `SSO=1 SMTP=1 MCP=1 AI=1` install and every smoke; the gate, `ideas_in_research` and answers live through the ingress on the migrated data |

No earlier spec needed a change for the new demo story (the Internal Tools ideas that moved
through Research and the custom templates touch no earlier assertion). The only edit to
shared e2e support: `ProposalSectionKey` is now `string` in `tests/support/api.ts` (the
contract dropped the enum).

### Defects and nits found

| ID | Owner | What | Reproduce |
|---|---|---|---|
| P8-QA-F1 | frontend | After a section is removed from the template while someone types in it, the autosave's 404 keeps the text but the proposal isn't refetched: the removed section stays in the editor and the kept-text callout reads "“Risks” **is back in the template** … copy it into the section above" (`removed-sections.tsx` decides "back" from the stale `activeKeys`). The contract (§2.7) wants "This section was removed from the template…". A reload shows it right. | Open a proposal as its owner; as an admin remove an empty section through Settings → Proposal (or the API); type in that section in the first tab; wait 2 s. `e2e/tests/templates.spec.ts` TPL-03 (pinned `test.fail`). |
| P8-QA-P1 | platform | The fake kagent agent drafts only the eight built-in section keys (`dev/fake-agent/fake_agent/agent.py` `SECTION_KEYS`, checked in `_run_from`): a "Draft with AI" run for a section a project added (`carbon_impact`, `pilot_plan`) ends `failed`. It should accept any key matching `^[a-z][a-z0-9_]{0,39}$` (the backend asked for the same). | `E2E_AI=1`: `e2e/tests/templates.spec.ts` TPL-05 (pinned), or Draft with AI on GREEN-4's Carbon impact. |
| P8-QA-N1 | frontend | The proposal editor's "Research and consultation" appendix isn't in the Outline, and its lines run under the comments margin (full width) where the sections stop at the text column. | `/ideas/TOOLS-3?tab=proposal` at 1440 px. |
| P8-QA-N2 | frontend | Research settings at 390 px: the stage preview wraps so a line starts with "→" ("→ ● Closed"). | `/p/internal-tools/settings?tab=research` at 390 px. |
| P8-QA-N3 | backend (seed) | GREEN-4's seeded proposal has amounts without a currency ("2,400 crates at 18 each", "roughly 40,000 a year"). | GREEN-4's PDF or Markdown. |

All five were fixed at integration (2026-10-08): F1 (`save-store.ts` asks the editor to
re-read the proposal after a 404; a restored section is editable again with the kept text
beside it; two vitest cases), P1 (`dev/fake-agent` takes any key of Soundings' shape and
finds the section in `get_proposal`; three fake-agent tests), N1 (the outline links the
appendix, which keeps to the text column; TPL-04 expects the link), N2 (each stage keeps
its arrow after it), N3 (£ amounts). TPL-03 and TPL-05 pass without their marks.
