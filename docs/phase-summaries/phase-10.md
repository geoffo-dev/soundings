# Phase 10 summary: bid evaluation (release 0.3.0)

**Status:** built on 2026-10-13 and 2026-10-14, verified for release **0.3.0** on
2026-10-14, waiting for the product owner's review ([RELEASE-NOTES.md](../RELEASE-NOTES.md)).
**Scope (the product owner's change after 0.2.0, 2026-10-13):** "when a proposal is made,
we'll be able to evaluate any of the bids that come in", in sections of questions, with
uploaded documents and must-have checklists so an incomplete bid is rejected at once,
several human assessors and an AI assessor. The product owner's answers P1-P4 and the
lead's defaults L1-L13: [decisions](../decisions.md#phase-10-product-owner-2026-10-13)
(E, F, G, "Phase 10 build and integration", "Phase 10 review decisions"). Contract:
[contract-phase10.md](../api/contract-phase10.md) (§20 the contract review, §21 the
changes after it); architecture: [ADR 0018](../adr/0018-bid-evaluation.md); rules:
[role matrix](../role-matrix.md) table M, section 3a, c27-c30; test plan:
[phase-10.md](../test-plans/phase-10.md).

Commits: `b51e8dd`, `2884033` (the contract, after a critic's review), `307277f`,
`1e9730e`, `44cec31`, `0ff8884` (backend core, documents, notifications, report, seed;
the frontend's screens), `ca685fb` (platform), `82ee260`, `559a472` (QA), `3712ff5`,
`b82c47e` (integration), `ad072c1`, `152297f`, `ececfad` (the review fixes), plus the
0.3.0 release verification.

## What was built

| Area | What | Where |
|---|---|---|
| The call | One call per idea in Proposal with a proposal (c27): draft → open (a deadline in the instance's time zone; late bids marked) → assessing → awarded \| cancelled, back to open while nothing is submitted; read-only while the idea is closed (409 `idea_closed`); a draft or cancelled call deleted with everything in it (an awarded one by a platform admin, c30); the idea page's **Bids** tab, the Details row, ⌘K | `app/bids/service.py`, `access.py` (load and lock order), `features/bids/bids-tab.tsx`, `call-header.tsx` |
| The template | Each project's default (`bid_templates`, one JSON document; Project settings → **Bids**): 1-8 sections with weights summing to 100, 1-15 questions (score / price / comment), 0-20 must-haves (document / confirmation, `pricing`); migration 0016 gives every project the built-in default; a call copies it into rows and edits its copy until a person's first submission (409 `bid_call_template_locked`) | `app/bids/templates.py`, `app/schemas/bids.py`, `features/bids/bid-template*.ts(x)`, `template-copy-sheet.tsx` |
| Bids and must-haves | Bids entered by the team (P1): bidder, contact, received, price, notes, at most 50 a call; must-haves `missing` (a document with no file, at once), `unchecked`, `met`, `not_met`; **Reject…** in one click with the reason filled in, audited, **Reinstate** until the award (P2); rejected bids leave queues, totals, the price formula and the ranking | `app/bids/service.py`, `views.py`, `features/bids/bid-sheet.tsx`, `must-haves.tsx`, `reject-dialog.tsx` |
| Documents (ADR 0018) | Raw-body upload (the name in `X-Filename` or the query) with its own 25 MiB limit counted as it streams, two uploads per API process and one per person, 120 s and a 16 KiB/s floor after 15 s; the type from the bytes (macro, OLE, encrypted Office files, Excel macro sheets, duplicate ZIP names refused: 415); caps 30 a bid, 500 MiB a call, 5 GiB a project with the text; SHA-256 duplicates 409; stored in PostgreSQL; downloads as attachments (nosniff, a sandboxing CSP, no-store); pricing documents for price viewers only | `app/bids/documents.py`, `sniff.py`, `app/middleware.py`, `features/bids/bid-documents.tsx`, `use-document-uploads.tsx`, `upload-names.ts` |
| Extraction | On the worker's own `bid_documents` pool, one child at a time (`python -I`, an allow-listed environment, stdin/stdout, 30 s, 512 MiB, 2 M characters, three crashes then `internal_error`); `pypdf` for PDF, `zipfile` + expat (no DTDs or entities, zip-bomb caps) for OOXML/ODF, text with fallbacks, no OCR; `active_content` flagged; calls take turns (L6) | `app/bids/extraction.py`, `extract_child.py`, `tasks.py` |
| Assessors and assessments | Assessors per section (P3) with one due date: active people who can view the idea in their own right (c28), never agents or break-glass (422 `assessor_not_eligible`); `cannot_remove_self`, `assessor_has_submitted`; drafts and submissions per (bid, section), edits audited; leaving a private project removes unsubmitted assignments (ACC-5) | `app/bids/service.py`, `role_loss.py`, `features/bids/assessors-dialog.tsx`, `assessment-queue.tsx`, `assessment-sheet.tsx` |
| Blind | Per (bid, section) (`authz.bid_pending`): nobody's scores, the AI's included, until you submit; no ranks while you owe any (`ranking_hidden`); assessors never see totals, ranks, contacts, notes or reasons; the AI's must-have reasons hidden while you owe a section of the bid (ACC-2); a finished call ends it (ACC-4); agents always blind | `app/authz/policy.py`, `app/bids/views.py` |
| Scoring and the award | Exact fractions (`fractions.Fraction`), rounded half up for display; section = weighted mean × 20, total = Σ weight × section; price = lowest qualified ÷ price × 5; disagreement at a spread of 2; ties share a rank ("1="); the comparison (call managers; each section's assessments one click away); **Award…** among qualifying bids with a reason, audited, in the feed | `app/bids/scoring.py`, `features/bids/comparison.tsx`, `section-results.tsx`, `award-dialog.tsx` |
| The AI assessor (P4) | Purpose and run kind `assess_bid`; "Ask AI to assess", "Assess all with AI", one automatic run per bid for a call's AI assessor (documents read, 5 quiet minutes); three MCP tools bound to the run's bid (c22: never other bids, people's scores, the price or pricing documents); every quote (≥ 20 characters) checked whitespace-normalised, off the event loop; left out of totals until a call manager includes it (not while they owe a section of the bid); the fake agent's assess runs (`-invents`, `-not-met`); the bid-assessor Agent example | `app/bids/assess.py`, `app/mcp/bid_tools.py`, `features/bids/bid-ai.tsx`, `quotes.ts`, `dev/fake-agent/`, `deploy/kagent/` |
| Notifications and My work | "Asked to assess bids", "Bid assessment reminder" (2 days before and on the day, at the digest hour), "Bid assessments complete" (the owner and the call's creator): inbox, email, digest, unsubscribe; never scores, prices, bidders or text; a 23:59 due date shown as the day (`format_due`); My work's "Bids to assess", `WorkCounts`, the sidebar badge | `app/notifications/bids.py`, `app/templates/email/`, `app/bids/work.py`, `features/work/` |
| The report | Markdown and PDF through the proposal export path (the PDF child, the shared limit), call managers only; ranking and section scores split so A4 portrait holds them; blind for a manager who owes an assessment | `app/bids/report.py` (an `ExportDocument` for `app/proposals/`) |
| Platform | Helm `ingress.uploads` (a fourth Ingress for the upload path: 26 MiB, 180 s, no buffering), the worker's 1 GiB limit, `kagent.agents.bidAssessor`; k3s's Traefik `readTimeout` 180 s and an uploads router; `scripts/bid-smoke.sh` (`make bid-smoke`, in `k3s-smoke` and GitHub's e2e job); `mcp-smoke` lists 13 tools; `ai-smoke` an assess run | `deploy/helm/`, `scripts/`, `dev/k3s/` |
| Demo | TOOLS-3's "Data platform build" (Internal Tools, private, kenji's) being assessed: Technical carol + mateo, Commercial (price) priya, Delivery sven + alice (alice owes hers); Northwind (strong), Tessellate (cheaper, weaker; a disagreement; an AI assessment left out), Quillfield (no insurance certificate: rejected); small PDF and DOCX documents, extracted at seed time | `app/seed/`, `backend/app/seed/bids/`, `dev/README.md` |

Migration **0016** (expand only; head 0016): 16 tables, four `ai_runs` columns, the run
kind and agent purpose, three notification types; every existing project gets the
default template.

## Acceptance evidence

| What | Evidence |
|---|---|
| The whole call through the API | `tests/acceptance/test_phase10_acceptance.py` **AC10-API-1** (entry to award: the call, bids, eleven uploads extracted by the worker, must-haves and rejection, assessors and their emails through Mailpit, the AI through the real fake agent, blind for carol before and after, the reminder with a moved clock, "complete", the comparison worked out in exact fractions, others' views, the award, the report read back with pypdf) and **AC10-API-2** (the demo call and keys per scope) |
| Access over principal kinds | `tests/bids/test_access_table.py`, `tests/authz/test_bid_access.py` (call manager, assessor before and after submitting, another section's, the price section's, member, viewer, internal non-member, guest researcher, agent in its run / another run / none, keys per scope × every route and tool), `tests/authz/test_researcher_access.py` (the guest table's meta-test), `tests/bids/test_route_guards.py` |
| Uploads | `tests/bids/test_sniff.py`, `test_documents.py` (types by bytes, macros, OLE, encrypted, duplicate names, a lying Content-Length, chunked bodies, 25 MiB + 1, trickling bodies, one upload per person, `X-Filename`, names with folders or control characters), `test_extraction.py` (zip bombs, entities, time and memory limits, active content), `scripts/bid-smoke.sh` |
| Scoring | `tests/bids/test_scoring.py` (`worked_example`: contract §8.1, A 84.7, B 74.0, C rejected; ties; the largest call read once), `tests/test_schemas_phase10.py` |
| The AI assessor | `tests/bids/test_ai_assessor.py` (c22 before any lookup, quotes found / not found, inclusion, a closed idea's run, rejected bids' runs), `tests/mcp/` (13 tools), `test_phase10_acceptance.py` with the real fake agent |
| Lifecycle, lock order, must-haves | `tests/bids/test_lifecycle.py`, `test_bids.py`, `test_templates.py`, `test_assessments.py`, `test_work.py`, `test_report.py` (`assert_fits_the_page` at the maximum) |
| Browser, real stack | `e2e/tests/bids.spec.ts` BD-01 … BD-12, BD-14; `bids-ai.spec.ts` BD-13 (`@ai`); `a11y-phase10.spec.ts` A11Y10, MO10-01, MO10-02, K10-01 |
| SPA | `frontend/tests/bids.spec.ts`, `bids-review.spec.ts` (page tests against the mock), vitest (`features/bids/*.test.ts`, `mocks/phase10.test.ts`, `api/bids-upload.test.ts`, `audit-phrases.test.ts`) |

**Release verification (2026-10-14,** [test plan](../test-plans/phase-10.md#release-030-verification-2026-10-14)**):**
backend `check` (10,254 passed, 5 skipped) and `test-slow`; frontend `check` (713 vitest)
and `test:pw` (471 passed on a quiet machine); e2e default 353, `E2E_SSO=1` 374, `E2E_AI=1` 394 and against
`make demo` with `soundings:0.3.0` 392 passed (none failed), then CI's `mcp-smoke`,
`ai-smoke` and `bid-smoke` (`BID_AI=1`) on that image; e2e check, `check-helm`,
`check-scripts` (shellcheck 0.9 too), `check-workflows`, `check-migrations`,
`check-fake-agent`, `make gen-api` (the version only), `make image` (533 MB, labelled
0.3.0). On k3s: 0.2.0 with its demo data upgraded to 0.3.0 through `scripts/deploy.sh` as
the deployer ServiceAccount (0015 → 0016, row counts unchanged, every project the default
template, a call, bid, upload and extraction on the migrated TOOLS-3, the bid smoke's
assessing, report and award on the migrated data, the rollback across 0016 refused); then
as CI (`SSO=1 SMTP=1 MCP=1 AI=1` with a 78 s slow upload through Traefik and the AI
assessment through the fake agent), two API replicas (each pod served uploads and
downloads) and `PROD=1`. Every real-stack screenshot set and the tour re-captured and read.

## Reviews and outcomes

- **The contract review** (a critic, before any builder started; contract §20): prices in
  documents (pricing documents, M4), assigning assessors (M3), the AI pre-check automatic
  but bounded, scored bids follow the facts (M1), no ranks while you owe (M2), upload
  inspection bounded (M5, S5, S6), active content flagged (S3), extraction caps (S1, S4),
  quote rules (S2), and smaller items: all decided in decisions.md G.
- **QA** (2026-10-13): P10-QA-F1 (the AI inclusion switch offered to a manager who owes the
  bid), V1 (the report's ranking wider than A4) and N1-N10 (wording, alignment, buttons):
  all fixed at integration; the walkthrough found the seeded forms of tender carrying the
  price (fixed: amounts only in the pricing schedules, with a seed test).
- **Security and code review** (no critical or high; 3 medium, 9 low, 6 nits): M1 a closed
  idea's call writable (fixed: 409 `idea_closed`), M2 quadratic scoring (fixed), M3 false
  active-content flags (fixed), L1-L9 (feeder timeout, damaged PDFs, macro sheets and ODF
  events, slow uploads, quote memory, extraction fairness, edit audit, AI rationales,
  rejected bids' runs: fixed), N1-N6 (UTF-16 and offset PDFs, `X-Filename`, `late_changed`,
  perf rounds, chart README: fixed; N3, the request Content-Type, declined as contracted).
- **Access review** (adversarial, live; no critical or high): ACC-1 a pricing must-have's
  note leaked the price (fixed), ACC-2 the AI's finding text (fixed: verdict only while
  owing), ACC-3 rejected bids' runs (fixed), ACC-4 blind for ever after the award (fixed:
  a finished call has no pending assessors), ACC-5 assignments resuming after rejoining
  (fixed: removed on leaving), ACC-6 the bid count (declined).
- **UX and accessibility review** (axe clean on about 40 screen and variant pairs): M1-M6
  (the stuck bid form, uploads not linked to must-haves, prices exposed by default,
  managers unable to read assessments, a stale Bids tab, dates differing between the app,
  emails and the report), m1-m13 and p1-p7: fixed; "one table for Bids, Comparison and
  Rejected" deferred (a reshaping of every bids spec, worth its own change).
- **Release verification** (2026-10-14): the SPA's upload sends the name in `X-Filename`;
  the audit log words an edited assessment, a lateness change and a removal on leaving
  the project, and counts assessors added and removed (always "none" before: the backend
  sends them by section); the image label follows `pyproject.toml`; `e2e/tests/bids.spec.ts`
  runs in order (BD-02 and BD-03 both upload as alice, and the review's one upload per
  person turned the second away with 503 `upload_busy` when they ran side by side).

## Known issues

- **Verified against Soundings' fake agent only**: no kagent controller or LLM has carried
  an assess run; the bid-assessor manifest is validated against kagent v0.10.2's CRDs. How
  a real model scores, quotes exactly and resists instructions hidden in bid documents is
  untested.
- **No antivirus scanning and no OCR** in this phase (operator guide: a scanning proxy on
  the upload path, or scanning backups).
- **No bidder portal** (P1): bids are entered by the team.
- **Database growth**: documents and text live in PostgreSQL (up to 5 GiB a project).
- **The upload route needs ingress settings** (ingress-nginx through `ingress.uploads`;
  Traefik's `readTimeout`); through Traefik an oversized chunked upload may get 502.
- **Deferred from the UX review**: one bids table whose columns grow with the call
  (instead of Bids, Comparison and Rejected); the seven project settings tabs wrap to two
  rows on a phone (Phase 8's decision).
- **Declined**: the bid count includes rejected bids (ACC-6); the first submitted scores
  of an edited assessment aren't kept (L7).
- Reminders by date are tested with a moved clock (the acceptance test), not by waiting.
- **The demo's bid assessor** shows "Removed: can't work there" in Admin → AI agents: the
  seed (`app/seed/bids.py` `_agent`) links the disabled agent to Internal Tools without the
  direct `member` role registration gives its service account (found re-capturing
  `phase-6/admin-agents-*`; left for the backend owner, see the release report).
- **Page tests under load**: with `make -C backend check` running beside it, 14 of
  `test:pw`'s tests hit the 5 s default timeout; all passed again on a quiet machine.
- **k3s image garbage collection**: at 86 % disk the kubelet removed the fake agent's
  imported image during its rollout restart (ErrImageNeverPull); with disk freed and the
  image imported again the smoke passed (the CD-rehearsal gotcha in CLAUDE.md).

## Screenshots

Real stack (`npm --prefix e2e run screenshots:phase10`, re-captured for the release on
2026-10-14), each at 1440 light, 1440 dark and 390 light, in `docs/screenshots/phase-10/`:

| Screen | Files |
|---|---|
| The call as its manager (kenji) | `call-overview-*` |
| A bid missing a must-have, its documents and their reading state | `bid-documents-flagged-*` |
| Rejecting it ("Missing: Insurance certificate.") | `reject-dialog-*` |
| An assessment with the Word proposal's text beside it (alice, Delivery) | `assessment-sheet-document-text-*` |
| The comparison with an AI assessment not counted | `comparison-ai-not-counted-*` |
| The award dialog | `award-dialog-*` |
| Project settings → Bids (dave) | `project-bids-template-*` |
| My work's "Bids to assess" (alice) | `my-work-bids-to-assess-*` |
| An assessor's Bids tab (carol: no prices, no ranks) | `bids-assessor-*` |
| A viewer's summary (zanele) | `bids-viewer-summary-*` |
| "Asked to assess bids" as Mailpit received it | `emails/assessor-assigned-*` (+ `.html`, `.txt`) |
| The evaluation report | `pdf/TOOLS-3-bid-evaluation.pdf`, its pages 1 and 2, the `.md` |

Against the mock (`SCREENSHOTS=1 npx playwright test bids-screenshots` in `frontend/`):
`docs/screenshots/phase-10/mock/` (`bids-draft`, `bids-manager`, `bids-member`,
`bids-assessor`, `bids-ranking-hidden`, `bid-sheet`, `bid-flagged`, `assessment-sheet`,
`award-dialog`, `settings-bids`, `my-work-bids`). The tour's 18-20
(`docs/screenshots/tour/`): the comparison, a bid's must-haves, an assessment. Every
other real-stack set the phase touched (phase-1, phase-3 with its emails, phase-8b) and
the tour were re-captured too; every changed PNG was read, without a defect.
