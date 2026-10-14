# Test plan: Phase 10 (bid evaluation)

Owner: qa. Source of truth for behaviour: the product owner's decisions in
[decisions.md](../decisions.md) ("Phase 10 (product owner, 2026-10-13)": P1-P4 and the lead
defaults L1-L13), [contract-phase10.md](../api/contract-phase10.md) (the call §3, the
template §4, bids and must-haves §5, documents §6, assessors and assessing §7, scoring §8,
the AI assessor §9, who sees what §10, notifications and My work §11, feed and audit §12,
the report §13, minimum tests §16, demo data §17, the review §20),
[role-matrix.md](../role-matrix.md) (table M, the overlay **+Asr**, section **3a**, c27-c30)
and [ADR 0018](../adr/0018-bid-evaluation.md). Each row has an ID used in the test names,
so a failing test points back here. The Phase 1-8b plans still apply; their suites run in
every mode next to the Phase 10 specs.

## What the product owner asked for, and where it is tested

| Requirement (decisions, Phase 10) | Acceptance (HTTP, live server) | Browser (real stack) | Rules (owners' unit tests) |
|---|---|---|---|
| **A call for bids** on an idea in Proposal with a proposal (one per idea, c27); lifecycle draft → open (needs a deadline) → assessing → awarded, cancel, reopen while nothing is submitted; read-only after the award | AC10-API-1 | BD-01, BD-07 | `tests/bids/test_lifecycle.py`, `tests/test_schemas_phase10.py`, `scripts/bid-smoke.sh` |
| **The evaluation template**: the project's default (Project settings → Bids: sections, weights summing to 100, questions of three types, must-haves); a call copies it and may edit its copy until the first person's submission; later project changes never touch a call | AC10-API-1 (copy, lock) | BD-01, BD-09 | `tests/bids/test_templates.py`, `tests/test_schemas_phase10.py`, `frontend/src/features/bids/bid-template.test.ts` |
| **Bids entered by the team** (P1): bidder, contact, received (late after the deadline), price for the price question, notes; only while open | AC10-API-1 | BD-02 | `tests/bids/test_bids.py` |
| **Documents** (L7, ADR 0018): raw-body upload by call managers in a session; type by content (PDF, DOCX, XLSX, PPTX, ODT, ODS, TXT, CSV, PNG, JPEG), macro and OLE content refused, 25 MiB, 30 per bid, 500 MiB per call, duplicates 409, safe names; attachment-only download with nosniff, a sandboxing CSP, no-store; text extracted in the worker's child process | AC10-API-1 (PDF + DOCX, duplicate, `../`, a member's upload, download headers, extraction) | BD-02 (drag and drop, keyboard), BD-03 (macro, executable, empty, over 25 MiB) | `tests/bids/test_sniff.py`, `test_documents.py`, `test_extraction.py`, `scripts/bid-smoke.sh` (413 with Content-Length and chunked) |
| **Pricing documents** (contract §6.4): file, text and link only for call managers and the price section's assessors ("present (restricted)" for the rest); the AI never reads them | AC10-API-1 (carol, priya, sven, the agent) | BD-06, BD-13 | `tests/bids/test_documents.py`, `tests/bids/test_access_table.py` |
| **Must-haves** (P2): a required document not uploaded is **flagged at once** (missing, automatic); confirmations decided by a person (met / not met with a note / clear); the AI's findings are suggestions beside the result | AC10-API-1 | BD-04 | `tests/bids/test_bids.py`, `frontend/src/features/bids/must-haves.test.ts` |
| **Reject in one click with a reason**, offered when a must-have is missing or not met; audited (no reason text in the details); **Reinstate** until the award, the rejection kept on record; a rejected bid leaves queues, totals, the price formula and the ranking | AC10-API-1 | BD-04 | `tests/bids/test_bids.py`, `tests/bids/test_scoring.py` |
| **Assessors per section** (P3), with an assessment due date; eligibility (c28: an active person who can see the idea in their own right; never a guest researcher, an agent, break-glass); `cannot_remove_self`, `assessor_has_submitted` | AC10-API-1 (bob refused) | BD-05, BD-07 | `tests/bids/test_assessments.py`, `tests/authz/test_bid_access.py` |
| **Blind** (role matrix 3a): before submitting a section for a bid an assessor sees nobody else's scores for it (human or AI) anywhere; no ranks for a manager who owes one; after submitting, that section's assessments and the AI's scores; totals stay with the managers | AC10-API-1 (carol on every surface, before and after), AC10-API-2 (alice: `ranking_hidden`) | BD-05, BD-14 (P10-QA-F1, fixed) | `tests/bids/test_access_table.py`, `tests/authz/test_bid_access.py`, `tests/bids/test_assessments.py` |
| **Scoring** (L8): question means, the price formula (lowest scored price ÷ this price × 5), weighted sections × 20, the weighted total, half-up rounding, disagreement (2 or more apart), "n of m assessed", ranking with ties; the same numbers after the award | AC10-API-1 (worked out in the test with exact fractions: AI out, then in), AC10-API-2 (84.0 / 71.2) | BD-07 (the worked numbers in the comparison) | `tests/bids/test_scoring.py`, `tests/test_schemas_phase10.py` (contract §8.1) |
| **The AI assessor** (P4, L9): "Ask AI to assess" (201, then 200 with the same run), scores every score question with quotes; every quote checked against the document text ("Not found in the document" for an invented one); left out of the totals until a call manager includes it; c22: the run's bid only, its two read tools and its write tool | AC10-API-1 (the fake agent; `-invents`; a `-slow` agent's key probed: another bid, another run, the pricing document, another bid's document, `get_idea`, `search_ideas`, REST) | BD-13 (@ai) | `tests/bids/test_ai_assessor.py`, `tests/mcp/`, `dev/fake-agent/tests/test_assess.py` |
| **Notifications** (L10): "Asked to assess bids" (the call, the sections, the due date; never the actor), "Bid assessment reminder" (2 days before and on the day at the digest hour, once), "All bid assessments are in" (owner and creator, never the actor); never scores, prices or bidders; inbox items the same | AC10-API-1 (Mailpit, the moved clock) | BD-12 | `tests/notifications/test_bid_notifications.py`, `tests/notifications/test_bid_reminders.py` |
| **My work** "Bids to assess" and the sidebar's Bids count | AC10-API-1 (carol), AC10-API-2 (alice) | BD-08 | `tests/bids/test_work.py`, `tests/perf` budgets |
| **Who sees what** (table M): a member and a viewer see only that a call exists (title, status, deadline, number of bids; the feed's `bid_call_changed`); the same 403 for a real and an unknown bid; assess runs left out / 404; a guest researcher nothing (404, no Bids tab); keys per scope, session-only routes refused | AC10-API-1 (farah, zanele, bob), AC10-API-2 (keys) | BD-10 | `tests/authz/test_bid_access.py`, `tests/research/test_guest_access.py` (meta-test), `tests/bids/test_route_guards.py` |
| **The report** (L11): Markdown and PDF for call managers only; ranking, sections, must-have counts, rejected bids with reasons, assessors, the award | AC10-API-1 (pypdf), AC10-API-2 | BD-11 (pdf.js) | `tests/bids/test_report.py` |
| **Demo seed** (L12): TOOLS-3's "Data platform build" being assessed; Northwind and Tessellate qualified, Quillfield rejected; alice owes both Delivery assessments; an AI assessment of Tessellate left out | AC10-API-2 | BD-06, BD-08, BD-10, BD-11, BD-14, A11Y10-*, the screenshots | `tests/test_seed.py`, `tests/bids/test_seed_documents.py` |
| Calm UI: loading, empty and error states, dark mode, keyboard, 390 px, WCAG 2.2 AA | — | A11Y10-*, MO10-01, MO10-02, K10-01 | `frontend/tests/bids.spec.ts` (MSW mock) |

## Acceptance through the HTTP API (`backend/tests/acceptance/test_phase10_acceptance.py`)

The app behind a real **uvicorn** on a free port with the **demo data**, people signed in
with the dev login over TCP (session cookie, CSRF header), API keys as bearer tokens, the
official **MCP Python SDK** client on `/mcp`; the **worker's three pools** in the test's
event loop (email + notifications, `ai`, and `bid_documents`, whose child process reads each
document's text); email through a **real Mailpit** (the Phase 3 acceptance's fixtures);
**Soundings' fake kagent agent** (`dev/fake-agent`, `uv run`) as the AI assessor, calling
back into `/mcp` with the key registration showed once. The reminder scan
(`send_assessment_reminders`) runs with a moved clock and the email is sent with the
worker's clock moved to the same hour. The documents are the demo's own (`app/seed/bids/`).
About 70 s for the two.

| ID | Story | What it checks |
|---|---|---|
| AC10-API-1 | A call for bids from entry to award | **The idea**: kenji's new idea in the private Internal Tools; dave (project admin) asks bob, who has no role there, to research it (the guest); kenji answers the checklist, shortlists, starts the proposal. Before the proposal `can_create` is false and a call is 409 `bid_call_not_available`; after it `can_create_bid_call`. **The call**: mateo (member) 403; kenji 201 draft with the default copy (Technical 40, Commercial 40, Delivery 20; tender, pricing (pricing), insurance, terms); a second call 409 `bid_call_exists`; opening without a deadline 409 `bid_call_deadline_required`, with one 200 open. **Bids and documents**: Northwind, Tessellate (each with a form of tender, a pricing schedule, an insurance certificate and a Word proposal) and Quillfield (no certificate) entered and uploaded as raw bodies; every upload 201 `pending`, the pricing schedule `pricing: true`; Quillfield's insurance must-have is `missing` and automatic **at once**, `reject_suggested`; a duplicate 409, `../x.pdf` 422, a member's upload 403. The worker extracts all eleven (done); the proposal's text page holds the bidder's name; the download is the same bytes, attachment, nosniff, a sandbox CSP, no-store. **Must-haves and rejection**: terms met → Northwind and Tessellate qualified, Quillfield still received; rejected with "No insurance certificate provided." (audited, the reason not in the details). **Assessors**: adding bob (a guest researcher) 422 `assessor_not_eligible` naming him; Technical carol + mateo, Commercial priya, Delivery sven, due after the demo call's due date; "Asked to assess bids" through Mailpit to all four (the call's title, the `?tab=bids` link, priya's Commercial; no score numbers, bidders, prices; the one fixed sentence about blind assessment aside), none to kenji; one inbox item each without bid data. Closed to new bids; a new bid 409 `bid_call_not_open`. **The AI assessor**: an `assess_bid` agent asked on Tessellate (201, then 200 with the same run) succeeds through the fake agent: events without bid data, every score question scored, every quote found, no finding for the pricing must-have, the fake never listed the pricing schedule, the message has no URL or key; the bid stays qualified. An `-invents` agent on Northwind: a quote "not found". A `-slow` agent's key, while its run is open: its bid 200 (no price, no pricing document), another bid, another run's id, `get_idea`, `search_ideas` `ai_run_not_active`; the pricing schedule and another bid's document `not_found`; REST 403; cancelled. **Blind**: mateo submits Technical for both; carol (a draft only) sees `hidden`, no assessments, no AI, no means, no section score; the comparison, the AI assessments and both reports 403; another section 403 `not_section_assessor`; no price, no contact or notes, the pricing schedule only counted (and 404 for its text and file); Quillfield 404 and out of her list; My work's "Bids to assess" 0 of 2 with nothing else; her inbox, the idea page and MCP `get_idea` / `search_ideas` without bid data; she may list the assess runs, which carry no scores; a person's `get_bid_for_assessment` `forbidden`. Priya (the price section) sees the price and the pricing schedule's text; sven no price. After carol submits: mateo's and her assessments and the AI's Technical scores; Tessellate's first question disagrees (4 and 2); the comparison still 403 for her; the template locked. **Reminder**: priya submits; at the digest hour the day before the due date nothing; two days before, sven only (and not again 20 minutes later); his email (the subject, no score data) and one inbox item; nobody else reminded. **Complete**: sven submits Delivery; "All bid assessments are in" reaches kenji once, not sven, carol or dave. **The comparison**: complete, 8 of 8, every section score, total and price score as worked out in the test with exact fractions and half-up rounding; Northwind 1, Tessellate 2 (disagreement), Quillfield without scores, rows in that order; including Tessellate's AI assessment changes its sections and total to the values worked out with the AI's scores; leaving it out restores them. **Others**: farah (member) and zanele (viewer) get the summary only, 403 for every bid route (also an unknown bid id), the assess runs left out and 404; bob gets `bid_call: null` and 404 everywhere, no `bid_call_changed` in his feed. **Award**: Quillfield 409 `bid_rejected`; Northwind awarded with a reason, Tessellate unsuccessful, the same totals and rank after; a new bid 409 `bid_call_finished`; zanele's feed says "awarded" without bid data. **Report**: Markdown (`text/markdown`: bidders, the reason, the total, the award reason) and PDF read with pypdf ("Bid evaluation report", the bidders, the reason, the call); carol, zanele, farah 403, bob 404. |
| AC10-API-2 | The demo call and keys per scope | TOOLS-3's "Data platform build" being assessed with Technical carol + mateo, Commercial priya, Delivery alice + sven; kenji's comparison Northwind 1st 84.0, Tessellate 2nd 71.2 (its AI assessment not counted), Quillfield rejected without a total; alice's comparison `ranking_hidden`, every rank null, every total hidden, 2 due in her counts; priya sees prices, carol none; zanele the summary; bob 404. **Keys**: carol's `read` key reads the bid and her own assessment and is 403 `insufficient_scope` for saving one; her `evaluate` key saves it; kenji's `write` key reads the comparison and is 403 `insufficient_scope` on reject, award, assessors and cancel (session only) and 403 on uploads; an `mcp`-only key 403 on REST. |

## Browser, real stack (`e2e/tests/`)

Specs that change a call use a private project of their own (`tests/support/bids.ts`:
`bidTeam`, `assessingCall`, `completeBid`, `setAssessors`, `assess`; uploads are raw
bodies); BD-06, BD-08, BD-10, BD-11, BD-14 and the a11y screens read the seeded TOOLS-3
call without changing it. Nobody's seeded My work changes: specs' assessors are people
other than alice, and the projects are archived afterwards.

| ID | Spec | What it checks |
|---|---|---|
| BD-01 | `bids.spec.ts` | The owner (alice) starts a call from the Bids tab ("Start a call for bids", title and what is bought): a Draft with the project's three sections and four must-haves (the API agrees); "Open the call" asks for a deadline first (Call details), then opens it ("Enter a bid" offered). |
| BD-02 | `bids.spec.ts` | "Enter a bid" (bidder, contact, email, price) opens the bid's sheet; the missing insurance certificate is flagged at once; two files dropped on the drop zone (a DataTransfer), one chosen with the keyboard ("Choose files" + Enter → file chooser); each shows "characters of text" once the worker has read it; the text opens as text (Escape closes it); the API has the three documents done. |
| BD-03 | `bids.spec.ts` | A macro-enabled Word file named `.docx` ("macro") and an executable named `.pdf` ("That file type can't be uploaded") are refused with their reasons; Dismiss clears them; an empty file and one over 25 MiB are refused before anything is sent (no request); the bid keeps its three documents. |
| BD-04 | `bids.spec.ts` | "1 missing" in the list; the sheet's warning; terms Not met with a note, Clear, Met; "Reject…" pre-fills "Missing: Insurance certificate."; rejected (toast, status, audit `bid.reject`); "Reinstate" → received, the rejection kept (`reinstated_at`). |
| BD-05 | `bids.spec.ts` | Carol (Technical) in her queue: 0 of 2, no comparison, no Price column; the assessment sheet says the others' scores stay hidden, shows no other assessor, the bid's documents beside it (never the pricing schedule); Submit needs every score ("Pick a score"); a digit picks a score; submitted → "Everyone's scores" with mateo's and the disagreement; the API agrees (not hidden, 2 assessments). |
| BD-06 | `bids.spec.ts` | TOOLS-3: carol sees no prices, not Quillfield, the pricing schedule "restricted" and no file name; priya (Commercial) sees £120,000.00 and the pricing schedule. |
| BD-07 | `bids.spec.ts` | A call scored with contract §8.1's pattern: Northwind 84.0 (86.7 / 80.0 / 86.7, price score 4), Tessellate 70.9 (60.0 / 84.0 / 66.7, price score 5, disagreement), Quillfield (flagged) without a total and out of the price formula; the comparison shows them; "Award…" warns "n assessments are outstanding" (n from the API), offers only the two qualified bids, awards with a reason; read-only (no Award, no Enter a bid); the same numbers after; the feed says so. |
| BD-08 | `bids.spec.ts` | Alice's My work: "Bids to assess" with the call, Delivery, 0 of 2 submitted, no bidder or price; the sidebar's "Bids, 2 to assess"; "Assess" opens the Bids tab on her queue. |
| BD-09 | `bids.spec.ts` | Project settings → Bids: weights adding up to 110 % say so and Save refuses (an alert, nothing saved); 50/30/20 saves ("Bid template saved"); the call started before keeps 40/40/20, a new call takes 50/30/20. |
| BD-10 | `bids.spec.ts` | Zanele (viewer) sees TOOLS-3's call title, status and "3 bids", the line about who sees bids, no bidder, price or reason, no bids or comparison; a guest researcher (bob, outside a private project) gets no Bids tab and 404 for the call (`bid_call: null`). |
| BD-11 | `bids.spec.ts` | Kenji exports the report from "More for this call" → Export the report → PDF (`TOOLS-3-bid-evaluation.pdf`; pdf.js reads "Bid evaluation report", Northwind, the rejection's reason); the Markdown holds 84.0; carol's PDF 403. |
| BD-12 | `bids.spec.ts` | A new person (Nora) made a member and a Delivery assessor gets one "Asked to assess bids" email: the call's title, Delivery, the `?tab=bids` link; no bidder, price or score data; her inbox item without bid data. Skipped without Mailpit. |
| BD-13 | `bids-ai.spec.ts` (@ai) | The idea's owner (a new person) asks "Bid assessor" through the bid sheet's "Ask AI to assess" menu: the run succeeds; its card shows "Found in the document", no "Not found", "Count in the totals" off; the must-haves keep their results with one AI finding each; the fake agent never listed the pricing document; the total unchanged until the switch is on, then counted, then left out again ("The AI's scores now count" / "are left out"); an `-invents` agent's card shows "Not found in the document"; carol's AI assessments 403. |
| BD-14 | `bids.spec.ts` | P10-QA-F1 (fixed at integration, mark removed): alice owes Tessellate's Delivery, so she may not include its AI assessment (contract §9.4: 404); `can_include` is false and the comparison offers no switch. |
| A11Y10 | `a11y-phase10.spec.ts` | axe (WCAG 2.2 AA, serious and critical), light and dark: the Bids tab for kenji, alice (no ranks), carol and zanele; Quillfield's sheet; carol's Northwind sheet; the reject dialog; the award dialog; alice's assessment sheet; Project settings → Bids; My work. axe best-practice rules on the screens without overlays (light). |
| MO10-01 | `a11y-phase10.spec.ts` | The same screens at 390 px: no sideways scrolling, no serious violations. |
| MO10-02 | `a11y-phase10.spec.ts` | On a phone the assessment sheet keeps Submit in reach and offers the bid's documents over it. |
| K10-01 | `a11y-phase10.spec.ts` | The bid list with the keyboard: Enter on a bid opens its sheet focused; Escape puts focus back on the bid. |

Earlier specs changed where the story legitimately changed: `a11y-phase3.spec.ts`,
`preferences.spec.ts` and `research-assignment.spec.ts` (RA-08) count 12 notification types
(9 before: the three bid types); `tests/support/mcp.ts` `TOOL_NAMES` lists 13 tools (the AI
assessor's three, for AC5-01's `tools/list`); `tests/support/ai.ts` `requestRun` excludes
the `assess_bid` kind (asked on a bid, not here; the e2e `tsc` failed on the new kind);
`scripts/fake-agent.ts` documents `-invents`, `-not-met` and the `assess` observation.

## Screenshots (`npm --prefix e2e run screenshots:phase10`)

`docs/screenshots/phase-10/`, each at 1440 light, 1440 dark and 390 light, from the demo
story and one call of its own ("Facilities", archived afterwards): `call-overview` (kenji),
`bid-documents-flagged` (Quillfield without its certificate, not rejected; scrolled to the
missing certificate and the three documents with their extraction state; the warning is in
`reject-dialog`),
`reject-dialog`, `assessment-sheet-document-text` (alice's Delivery with the Word proposal's
text beside it), `comparison-ai-not-counted` (kenji), `award-dialog`,
`project-bids-template` (dave), `my-work-bids-to-assess` (alice), `bids-assessor` (carol),
`bids-viewer-summary` (zanele); `emails/assessor-assigned-*` (desktop light and dark, 390;
with the `.html` and `.txt` Mailpit received); `pdf/TOOLS-3-bid-evaluation.pdf` and its
pages 1 and 2 (`.md` beside it).

## Defects and nits found (2026-10-13, real stack)

See the QA report for reproduction steps and owners. Marked tests pin the defects
(`test.fail`), so they fail loudly once fixed.

Integration (2026-10-13) fixed every row; the last column says how.

| ID | Owner | What |
|---|---|---|
| P10-QA-F1 | backend + frontend | A call manager who owes an assessment of a bid is offered "Count in the totals" for its AI assessment (`BidAiAssessmentList.can_include: true`, the comparison's switch), but the PUT is 404 (contract §9.4); the SPA then says "This no longer exists". BD-14. **Fixed:** `can_include` is false while the manager owes a section of the bid (backend view and mock); BD-14's mark removed. |
| P10-QA-V1 | backend (report) | The report PDF's Ranking table is wider than A4 portrait: the last column ("Assessed") is cut off at the right edge (`pdf/TOOLS-3-bid-evaluation-page-2.png`). **Fixed:** the ranking and the section scores are two tables ("Section scores", at most four sections a table); `test_report.py` checks no text starts past the right margin, at the maximum too. |
| P10-QA-N1 | backend (email) | "Asked to assess bids" says "Score your sections" to someone with one section. **Fixed:** "Score your section" for one. |
| P10-QA-N2 | backend + frontend | `assessor_not_eligible` names the person by id ("User 1f3e… can't assess bids here"); the assessors dialog shows that message as it is. **Fixed:** named by display name ("Nora Quinn can't assess bids on this idea"). |
| P10-QA-N3 | lead (contract) | `BidAiAssessment.findings` don't say which must-have each finding is about (only `BidMustHaveState.ai_findings` does). **Fixed:** `BidAiFindingView.must_have_id` (additive, contract §21). |
| P10-QA-N4 | frontend | Two blue buttons with the Bids tab open ("Open proposal" in the idea header and "Award…" in the call header); Project settings' seven tabs wrap to two rows at 390 px. **Fixed:** the idea header's button is an outline one on the Bids tab; the settings tabs keep wrapping on a phone by design (Phase 8 m6). |
| P10-QA-N5 | frontend | The reject dialog asks "Reject Quillfield Systems’s bid?" (a possessive on a name ending in s; "Reject the bid from Quillfield Systems?" reads for any name). `reject-dialog-*`. **Fixed:** "the bid from X" in every title, toast and label. |
| P10-QA-N6 | frontend | Bid sheet wording: a confirmation must-have says "A confirmation · met per Alice Anders just now" ("confirmed by"); the header repeats "Received" (the status chip, then "Received Tuesday 13 October…"). `bid-documents-flagged-*`. **Fixed:** "confirmed by" / "marked … by"; "Arrived <date>". |
| P10-QA-N7 | frontend | Comparison's section cards: the price question reads "Price … Price" (its text and its type); the "Assessors" blocks don't line up across the three cards (Commercial's, with one assessor, sits lower). `comparison-ai-not-counted-1440-*`. **Fixed:** "From the price"; the cards share rows (subgrid). |
| P10-QA-N8 | frontend | Project settings → Bids: a question's weight field has no visible label or unit (the comparison shows "× 2"); at 390 px question texts are one-line inputs cut off mid-word ("How well does the proposed s"). `project-bids-template-*`. **Fixed:** "×" before the weight ("Weight ×" on a phone); question text wraps. |
| P10-QA-N9 | frontend | My work's "Bids to assess 2" counts assessments (bid × section) above a single call row that says "0 of 2 submitted"; the award dialog's chosen bid looks like the others except for its radio. **Fixed:** rows lead with "N to submit"; the chosen bid has the selected border and tint. |
| P10-QA-N10 | frontend | Bid sheet → Documents: the "Upload as pricing documents" checkbox sits at the left edge while its label and help text are centred under the drop zone, far from it (`bid-documents-flagged-1440-*`). **Fixed:** the label is left-aligned beside its checkbox. |

## Release 0.3.0 verification (2026-10-14)

On the build machine, from the tree at `ececfad` plus the release changes (the SPA's
`X-Filename`, the audit phrases, the version bump, `bids.spec.ts` in order).

| Check | Result |
|---|---|
| `make -C backend check`, `test-slow` | 10,254 passed, 5 skipped; 6 passed (quiet machine) |
| `npm --prefix frontend run check`, `test:pw` | 713 vitest; test:pw 471 passed, 238 skipped (the screenshot specs), none failed on a quiet machine (27.7 min); beside the backend check 14 had hit the 5 s timeout |
| e2e default, `E2E_SSO=1`, `E2E_AI=1` (local stack) | 353, 374, 394 passed; none failed (the first default run: BD-02 503 `upload_busy` beside BD-03, both alice: `bids.spec.ts` now runs in order) |
| e2e against `make demo` (`soundings:0.3.0`, CI's e2e job's settings) | 392 passed, 28 skipped, none failed; then `mcp-smoke`, `ai-smoke`, `bid-smoke` (`BID_AI=1`, 65 checks) passed |
| `npm --prefix e2e run check`, `check-helm`, `check-scripts` (+ shellcheck 0.9.0), `check-workflows`, `check-migrations`, `check-fake-agent` (59), `make gen-api` | pass; `gen-api` changed only `info.version` |
| `make image IMAGE=soundings:0.3.0` | 533 MB, label `org.opencontainers.image.version=0.3.0`; `scripts/deploy.sh check-release v0.3.0` passes |
| k3s upgrade | 0.2.0's chart (`25ad3dd`), image and demo seed in `soundings-staging`, then `scripts/lib/k3s-deploy.sh deploy staging soundings:0.3.0` (the deployer ServiceAccount in the tools image): 0015 → 0016, helm test, `deploy-smoke.sh`, the app reports 0.3.0; eleven tables' row counts unchanged; CUST, GREEN and TOOLS have the default template (40/40/20, four must-haves); on TOOLS-3 a call, a bid, a PDF uploaded with `X-Filename` (201), its text read (558 characters), automatic must-haves; `bid-smoke.sh` (`BID_AI=0`, 54 checks: assessors, blind, comparison 80.8, report, award) on the migrated data; the rollback to revision 1 refused (it crosses 0016) |
| k3s as CI (`SSO=1 SMTP=1 MCP=1 AI=1`, `BID_SLOW_UPLOAD=1`) | every smoke passed: the upload route's own router, a 1.6 MB upload at 20 KiB/s 201 after 78 s through Traefik, the AI assessment (6 quotes found; `-invents` 1 not found), SSO, email, MCP with the in-cluster SDK and the NetworkPolicy, AI, helm test; kagent v0.10.2 CRDs and a dry run of every manifest |
| Two API replicas | the same smoke passed; uploads 201 on both pods (6 and 4), downloads 3 and 3 (matched by `X-Request-Id` in each pod's log) |
| `PROD=1` | install and smoke passed (`__Host-` cookies, break-glass, `/metrics` 404 on the app port, production start-up, no password in the logs) |
| Screenshots | phase-1, 2, 3 (+ emails), 4, 5, 6, 8, 8b, 10 (+ emails, pdf, mock) and the tour re-captured; every changed PNG read; one demo-data nit: "Bid assessor (demo)" says "Removed: can't work there" in Admin → AI agents |
