# API contract: Phase 10 (bid evaluation)

Phase 10 is a change the product owner asked for on 2026-10-13
([decisions.md](../decisions.md#phase-10-product-owner-2026-10-13); SPEC.md is read-only):
once an idea has a proposal, the team runs a **call for bids** on it. Bids from suppliers
are **entered by the team** with their **documents**; a **must-have checklist** flags a bid
that lacks something so a person can **reject it in one click**; **human assessors,
assigned per section** of the evaluation, score every bid **blind**; an **AI assessor**
checks the must-haves and scores every question with **quotes from the bid's documents**,
left out of the totals until a person includes it. Everything in
[contract-phase1.md](contract-phase1.md) to [contract-phase8b.md](contract-phase8b.md)
still applies unless a section below changes it.

Source of truth, in order: the Pydantic schemas (`backend/app/schemas/bids.py`,
`bid_refs.py`, and the Phase 10 parts of `ai.py`, `ideas.py`, `work.py`,
`notifications.py`, `activity.py`, `audit.py`, `mcp.py`), the route stubs
(`backend/app/api/v1/bids.py`, 34 operations under the tag `bids`), the models and
migration 0016 (`backend/app/models/bid.py`, `ai.py`, `enums.py`;
`migrations/versions/20261013_0016_bid_evaluation.py`), exported to
`frontend/src/api/generated/` (`make gen-api`). Rules are named as in
[role-matrix.md](../role-matrix.md) (new: **table M**, the overlay **+Asr**, section **3a**,
c27-c30). Decision record: [ADR 0018](../adr/0018-bid-evaluation.md). The contract review
(2026-10-13) changed it before any builder started: section 20 lists every item and what
changed.
`backend/tests/test_contract_routes.py` pins the operations (`PHASE10_OPERATIONS`,
`STUBS`, the invalid-request table), `tests/test_schemas_phase10.py` the template, the
scoring math, quote checks, the MCP tools, key and guest rows and blind safety by
construction, `tests/test_domain_schema_phase10.py` the tables, constraints and the
migration on data.

## 1. What changes, in one table

| Area | Change |
|---|---|
| Data | 16 tables (`bid_templates`, `bid_calls` and its template copy `bid_call_sections` / `bid_call_questions` / `bid_call_must_haves`, `bid_section_assessors`, `bids`, `bid_must_have_results`, `bid_documents` + `bid_document_contents` + `bid_document_texts`, `bid_assessments` + `bid_assessment_answers`, `bid_ai_assessments` + `bid_ai_scores` + `bid_ai_findings`), with composite foreign keys so no row mixes two calls; `ai_runs.bid_id`, `ai_runs.bid_call_id`, `ai_runs.automatic`, `ai_runs.bid_ai_assessment_id`; run kind and agent purpose `assess_bid`; three notification types. Migration **0016** (expand only), head 0016. |
| Project settings | A **Bids** tab: the project's default bid evaluation template (`get_bid_template`, `replace_bid_template`). Every existing project gets the built-in default (section 4.1). |
| Idea page | A **Bids** tab: the call (one per idea), its template copy, assessors, bids, documents, must-haves, assessments, the comparison, the AI assessor, the award, the report. Everyone who can see the idea (not a guest researcher) sees that a call exists and its summary; the rest is for call managers and section assessors. |
| Who | **Call managers** (the idea's owner, project admins, platform admins) run the call; **section assessors** (overlay **+Asr**) score their sections; table M. Documents (upload, pricing mark and link, delete), rejections, reinstating, the award, cancelling, deleting and assigning assessors are **session only**. |
| Blind | An assessor sees nobody else's scores for a bid and section until they have submitted that section for that bid, anywhere (role matrix 3a); while a call manager owes any assessment, the comparison has no ranks. Prices and **pricing documents** only for call managers and the price section's assessors. |
| AI | Agents with the purpose `assess_bid`; one `assess_bid` run per bid ("Ask AI to assess", "Assess all with AI"), plus **one automatic run per bid** when the call names an AI assessor; three MCP tools bound to the run's bid (c22), never pricing documents; every quote checked against the document's text; scores out of the totals until included. |
| Notifications | "Asked to assess bids" (`assessor_assigned`), "Bid assessment reminder" (`assessment_reminder`), "Bid assessments complete" (`assessments_complete`): inbox, email per preference (default immediate), digest, unsubscribe; never scores, prices or bidders. |
| My work | "Bids to assess" (`Work.bids_to_assess`) and `WorkCounts.bid_assessments_due` / `_overdue`. |
| Feed | `bid_call_changed` (started, opened, closed to new bids, reopened, awarded, cancelled): no bid data. |
| Export | The bid evaluation report, Markdown and PDF, for call managers only. |

## 2. Endpoints

All under `/api/v1`. `M` = the call managers' rule, `A` = a section assessor's.

| Operation | Method and path | Rule | Keys (section 5 of the role matrix) |
|---|---|---|---|
| `get_bid_template` | GET `/projects/{slug}/bid-template` | `project.view` | `read` |
| `replace_bid_template` | PUT `/projects/{slug}/bid-template` | `project.edit_bid_template` | session only |
| `get_bid_call` | GET `/ideas/{idea}/bid-call` | `bid.view_call` (+ `bid.view_bids` for the whole call) | `read` |
| `create_bid_call` | POST `/ideas/{idea}/bid-call` | `bid.manage` (c27) | `write` |
| `update_bid_call` | PUT `/ideas/{idea}/bid-call` | `bid.manage` | `write` |
| `delete_bid_call` | DELETE `/ideas/{idea}/bid-call` | `bid.delete_call` (c30) | session only |
| `change_bid_call_status` | POST `/ideas/{idea}/bid-call/status` | `bid.manage` (open, assessing) | `write` |
| `cancel_bid_call` | POST `/ideas/{idea}/bid-call/cancellation` | `bid.decide` | session only |
| `replace_bid_call_template` | PUT `/ideas/{idea}/bid-call/template` | `bid.manage` | `write` |
| `set_bid_assessors` | PUT `/ideas/{idea}/bid-call/assessors` | `bid.manage` (c28) | session only |
| `get_bid_comparison` | GET `/ideas/{idea}/bid-call/comparison` | `bid.view_scores` | `read` |
| `request_ai_bid_assessments` | POST `/ideas/{idea}/bid-call/ai-assessments` | `ai.assess_bid` (c5, c10) | `write` |
| `award_bid_call` | POST `/ideas/{idea}/bid-call/award` | `bid.decide` | session only |
| `export_bid_report_markdown` | GET `/ideas/{idea}/bid-call/report/markdown` | `bid.view_scores` | `read` |
| `export_bid_report_pdf` | GET `/ideas/{idea}/bid-call/report/pdf` | `bid.view_scores` | `read` |
| `list_bids` | GET `/ideas/{idea}/bid-call/bids` | `bid.view_bids` | `read` |
| `create_bid` | POST `/ideas/{idea}/bid-call/bids` | `bid.manage` | `write` |
| `get_bid` | GET `…/bids/{bid_id}` | `bid.view_bids` | `read` |
| `update_bid` | PUT `…/bids/{bid_id}` | `bid.manage` | `write` |
| `delete_bid` | DELETE `…/bids/{bid_id}` | `bid.decide` | session only |
| `reject_bid` | PUT `…/bids/{bid_id}/rejection` | `bid.decide` | session only |
| `reinstate_bid` | DELETE `…/bids/{bid_id}/rejection` | `bid.decide` | session only |
| `decide_must_have` | PUT `…/bids/{bid_id}/must-haves/{must_have_id}` | `bid.manage` | `write` |
| `upload_bid_document` | POST `…/bids/{bid_id}/documents?filename=…&must_have_id=…&pricing=…` | `bid.upload_document` | session only |
| `update_bid_document` | PUT `…/bids/{bid_id}/documents/{document_id}` | `bid.upload_document` | session only |
| `delete_bid_document` | DELETE `…/bids/{bid_id}/documents/{document_id}` | `bid.upload_document` | session only |
| `download_bid_document` | GET `…/documents/{document_id}/content` | `bid.view_bids` | `read` |
| `get_bid_document_text` | GET `…/documents/{document_id}/text?page=1` | `bid.view_bids` | `read` |
| `get_my_bid_assessment` | GET `…/bids/{bid_id}/sections/{section_id}/assessment` | `bid.view_own_assessment` (c29) | `read` |
| `save_my_bid_assessment` | PUT `…/bids/{bid_id}/sections/{section_id}/assessment` | `bid.assess` (c29) | `evaluate` |
| `list_bid_section_assessments` | GET `…/bids/{bid_id}/sections/{section_id}/assessments` | `bid.view_section_scores` | `read` |
| `request_ai_bid_assessment` | POST `…/bids/{bid_id}/ai-assessment` | `ai.assess_bid` (c5, c10) | `write` |
| `list_bid_ai_assessments` | GET `…/bids/{bid_id}/ai-assessments` | `bid.view_scores` | `read` |
| `set_bid_ai_inclusion` | PUT `…/ai-assessments/{ai_assessment_id}/include-in-totals` | `bid.manage` | `write` |

`…` = `/ideas/{idea}/bid-call`. Changed (additive): `get_idea` (`bid_call`, two
permission flags), `get_my_work` / `get_my_work_counts`, the notification routes and
preferences (three types), the audit log (19 actions), AI agents (the purpose
`assess_bid`), AI runs (`bid_id`, `automatic`, `result.bid_ai_assessment_id`, `blocked_by`
reasons; `get_ai_run`, `stream_ai_run_events`, `cancel_ai_run` and `list_idea_ai_runs` of
an assess run need `bid.view_bids`, else 404 / left out). **Every operation returns 501**
until backend builds it.

### 2.1 Order of checks

1. 401.
2. 404: the idea (`idea.view`; a guest researcher at any of it), then `bid.view_call`,
   then the call when the operation needs one (`not_found`).
3. 403: the operation's **call-level** rule (`bid.view_bids`, `bid.manage`, …), a key's
   scope or a session-only route, **before** any bid, section, document or AI assessment
   is looked up, so a member can't tell a real bid id from an unknown one (review C10).
4. 404: a bid, section, question, must-have, document or AI assessment of **another
   call**; a rejected bid for an assessor who isn't a call manager; a pricing document or
   pricing must-have for someone without `bid.view_price`.
5. 403: c29 (`not_section_assessor`), `cannot_remove_self` (section 7.1).
6. Uploads only: an upload slot (503 `upload_busy`), then the body (413
   `content_too_large`, 408 `upload_timeout`), then its type (415).
7. 422: bodies and query parameters (FastAPI validates these before the route runs, so a
   malformed body is 422 even where a later step would refuse); c28.
8. 409: `project_archived`, c19 `awaiting_moderation`, c5 `idea_closed`, then the call's
   state, then the rest.

Writes lock project (`FOR KEY SHARE`) → idea → call (`FOR UPDATE`) → bid → AI run, in that
order; a write that changes many bids (award, the template copy, a price change, cancel)
locks the call and reads the bids under it, then the runs it cancels. **Bid-call writes
never touch the idea's `updated_at` or `last_activity_at`** (members would see when bids
are worked on); only the `bid_call_changed` feed events, which everyone with
`bid.view_call` reads, count as the idea's activity.

## 3. The call for bids

### 3.1 One call per idea (c27, L1)

`create_bid_call` (`BidCallCreate`: `title` 1-120 visible characters, `description` up
to 2,000, `currency` ISO 4217 letters, default `GBP`) needs the idea **in Proposal with
a proposal** (409 `bid_call_not_available`) and no call yet (409 `bid_call_exists`). It
copies the project's template (section 4) and starts as a **draft**. Moving the idea back
out of Proposal later keeps the call; closing the idea makes everything read-only (409
`idea_closed`); deleting the idea deletes the call with all its bids and documents.

```json
POST /api/v1/ideas/TOOLS-3/bid-call
{"title": "Data platform build", "description": "Supply and build the pilot.", "currency": "GBP"}
→ 201 BidCallView
```

`get_bid_call` answers `BidCallView`: `summary` (`BidCallSummary`: id, title, status,
deadline, bid count; null when there is no call) for everyone with `bid.view_call`;
`call` (`BidCall`, the whole call with its template copy, assessors, progress and its AI
assessor) only with `bid.view_bids`; `ai_agents` (the agents that may assess, for the
request buttons and the AI assessor picker); `permissions` (`BidCallPermissions`).
Everyone else sees a summary only, which is also `IdeaDetail.bid_call`.

### 3.2 Lifecycle (L2)

```
draft ──open──▶ open ──close to new bids──▶ assessing ──award──▶ awarded
  │               ▲  │                        │
  │               └──┼── reopen (no assessment submitted yet) ┘
  └──────────────────┴──────── cancel (draft, open, assessing) ──▶ cancelled
```

| Move | Needs | Refusals |
|---|---|---|
| draft → open (`change_bid_call_status`) | a deadline (`update_bid_call`) | 409 `bid_call_deadline_required` |
| open → assessing (`change_bid_call_status`) | | |
| assessing → open (`change_bid_call_status`) | no person's assessment submitted | 409 `assessments_submitted` |
| draft / open / assessing → cancelled (`cancel_bid_call`, `BidCallCancelIn`) | `bid.decide` (session); an optional `reason` (up to 500) | 409 `bid_call_finished` |
| anything else (also → awarded: that is `award_bid_call`) | | 409 `invalid_bid_call_transition` |

- **Deadline** (`deadline_at`, `DueAt`: a date in the instance time zone, the end of that
  day, stored in UTC as Phase 8b's research due dates). Bids received after it are
  `late: true`, never refused (L2). An open call keeps a deadline (409
  `bid_call_deadline_required` when cleared). It changes **only while the call is a draft
  or open** (a changed deadline while assessing: 409 `bid_call_not_open`), so `late` never
  flips after bids are closed.
- **Currency** is a label (no conversion, no formula uses it): it changes until the award.
- **Assessment due date** (`assessment_due_at`): written only with the assessors
  (`set_bid_assessors`); reminders and My work's "overdue".
- **The AI assessor** (`ai_assessor_id`, `update_bid_call`): optional, section 9.1.
- **Bids are entered only while the call is open** (409 `bid_call_not_open`); assessments
  only while it is **assessing** (409 `bid_call_not_assessing`); AI runs while it is open
  or assessing (409 `bid_call_not_assessable`).
- **Awarded and cancelled calls are read-only** (409 `bid_call_finished` for every write),
  except that they may be deleted (below).
- `delete_bid_call` (`bid.delete_call`, session only, c30) deletes a **draft or cancelled**
  call, or, **for platform admins only**, an **awarded** one (the bidders' contact details
  and documents are personal data; retention shouldn't need the idea deleted), with
  everything in it, and frees the idea for a new call. An open or assessing call, or an
  awarded one for anyone else: 409 `bid_call_active`. Audited `bid_call.delete`.
- Cancelling and the award cancel the call's active AI assess runs (section 9.1).
- Each move emits `bid_call_changed` and is audited `bid_call.status_change`.

### 3.3 The award

`award_bid_call` (`BidAwardIn`: `bid_id`, optional `reason` 1-500; session only), while the
call is **assessing** (409 `bid_call_not_assessing`): the bid must be **qualified** (409
`bid_not_qualified`; rejected: 409 `bid_rejected`). It becomes `awarded`, every other bid
that isn't rejected `unsuccessful`, the call `awarded` and read-only, and active AI assess
runs are cancelled. The bids keep their scores, totals and ranks: scoring follows the facts
(not rejected, every must-have met), never the award (section 8). Outstanding
assessments don't block it (the SPA warns: "2 assessments outstanding"). The reason is
kept on the call (`award_reason`) and shown to call managers and in the report. Feed event
(`bid_call_changed` to `awarded`, no bid named); audited `bid_call.award` with the bid's id
and whether a reason was given.

## 4. The evaluation template

### 4.1 The project's default (L3)

`BidTemplate`: `scale` (six labels for scores 0-5, 1-80 characters each), `sections`
(1-8: `title` 1-60, `guidance` up to 500, `weight` 1-100 percent; weights **sum to 100**;
unique titles, compared case-insensitively), each with `questions` (1-15: `text` 1-300,
`guidance` up to 1,000, `type`, `weight` 0-100; **at least one score question**),
`must_haves` (0-20: `text` 1-200, unique; `kind` `document` or `confirmation`; `pricing`,
document must-haves only, section 6.4). At most **one price question** in the whole
template. Titles and must-have texts are unique by Python's `casefold` in the schema and
by Postgres `lower()` in the service (`require_unique_lower`, as Phase 8's templates).

The built-in default (`DEFAULT_BID_TEMPLATE`, written for every existing project by
migration 0016 and for new projects by `create_project`):

| Section (weight) | Questions (type, weight) |
|---|---|
| Technical (40) | How well does the proposed solution meet our requirements? (score, 2) · How well will our data be kept secure and compliant? (score, 1) · What risks do you see in the technical approach? (comment) |
| Commercial (40) | Price (price, 3) · How clear and complete is the pricing? (score, 1) · Are the payment terms and contract conditions acceptable? (score, 1) |
| Delivery (20) | How realistic is the delivery plan and timeline? (score, 2) · How strong is the team and its relevant experience? (score, 1) |

Must-haves: "Signed form of tender" (document), "Pricing schedule" (document,
**pricing**), "Insurance certificate" (document), "Accepts our standard terms"
(confirmation). Prices travel in the pricing schedule, not in the form of tender (review
M4). Scale 0-5: "No response, or unacceptable" ·
"Poor: major gaps" · "Weak: some gaps or doubts" · "Acceptable: meets the requirement" ·
"Good: meets it with some added value" · "Excellent: exceeds it, with clear evidence".

`replace_bid_template` (session only; project and platform admins) replaces the whole
template, last write wins, allowed in an archived project, audited
`project.bid_template_replace`. **Existing calls keep their own copy.**

### 4.2 Question types (L4)

| Type | Scored by | Weight |
|---|---|---|
| `score` | each assessor of the section, 0-5 with the scale's labels | 1-100 (default 1) |
| `price` | Soundings, from each bid's price (section 8.1); assessors don't score it (422 `not_assessable`) | 1-100 (default 1) |
| `comment` | nobody: free text from each assessor | always 0 |

A question's weight counts **within its section**; a section's weight counts in the total.

### 4.3 The call's own copy

`BidCall.template` (`BidCallTemplate`) is relational: every section, question and
must-have has an **id** (ids are stable; they are what assessments, results, assessors and
the AI refer to; Phase 8's string keys aren't needed because nothing outside the call
names them). `replace_bid_call_template` (`BidCallTemplateIn`) sends the complete copy:
items **with an id keep it** (an unknown or other call's id: 422
`unknown_template_item`; an id used twice: 422), items **without one are new**, items
**left out are deleted** with their assessor assignments, results and document links (a
removed must-have's documents stay, **unlinked first**: the composite key from
`bid_documents` is `NO ACTION`). New must-haves get a result for every bid (missing or
unchecked). The same validation as 4.1. Removing a section with submitted assessments
can't happen: the copy is locked by then.

**The lock:** the copy can change only until the **first person's assessment is
submitted** (409 `bid_call_template_locked`; `BidCallTemplate.locked`). AI assessments
don't lock it, but **any change to the copy deletes the call's AI assessments and cancels
its active assess runs** (their questions changed; the AI is asked again). Later changes to
the project template never touch a call.

## 5. Bids and must-haves

### 5.1 Entering bids (P1, L6)

The team enters bids (no bidder accounts or links). `BidIn`: `bidder` (one line, 1-120),
`contact_name` (up to 120), `contact_email` (`x@y`, up to 254; stored as given, **never
emailed by Soundings**), `received_at` (default now; not more than 5 minutes ahead, not
more than a year back; stored in UTC), `price` (a decimal string, > 0, 2 decimals, up to
12 digits before the point; 422 `price_not_asked` when the call has no price question),
`notes` (up to 2,000). At most **50 bids per call** (409 `too_many_bids`). `update_bid`
takes the complete new state (`BidUpdate`) until the award, with **`received_at`
required**: the stored value is always accepted (however old), a changed one is checked as
on create; a changed price changes every scored bid's price score.

```json
POST /api/v1/ideas/TOOLS-3/bid-call/bids
{"bidder": "Northwind Data Ltd", "contact_name": "Ada Price", "contact_email": "ada@northwind.example",
 "received_at": "2026-10-12T15:30:00+01:00", "price": "120000.00", "notes": ""}
→ 201 Bid
```

`delete_bid` (session only) only while the call is a draft or open (409
`bid_call_not_open`; nobody has assessed it yet).

### 5.2 Status

`received` → `qualified` (every must-have **met**; a call without must-haves qualifies
every bid) or back; `rejected` (by a person) and back by "Reinstate"; at the award,
`awarded` or `unsuccessful`. The service keeps `bids.status` equal to
`call_bid_status(rejected, results, awarded)`.

**Scored bids** are the bids `is_scored(rejected, results)` accepts: not rejected and
every must-have met, **whatever the award made them** (review M1: after the award no bid
is `qualified`, yet the report and the comparison still score and rank the awarded and
unsuccessful bids). Before the award that is exactly `qualified`. Only scored bids get a
price score, section scores, a total and a rank; the price formula's lowest price is the
lowest **scored** price.

### 5.3 Must-haves (P2)

One `BidMustHaveState` per bid and must-have: `result` `missing` | `unchecked` | `met` |
`not_met`, `automatic`, who and when, a `note`, the linked `document_ids`, and the AI's
`ai_findings` (suggestions, never the result).

| Kind | No decision | A person decides (`decide_must_have`, `MustHaveDecisionIn`) |
|---|---|---|
| `document` | `missing` without a linked file; **`met` (automatic)** once a file is linked | `not_met` with a note (the file isn't what was asked for); `met` without a file: 409 `document_missing`; `null` clears the decision |
| `confirmation` | `unchecked` | `met` or `not_met` with a note; `null` clears |

When a document must-have loses its **last** linked file (the document is deleted or
unlinked), its result is `missing` again, **a person's `met` included** (it was about that
file); a person's `not_met` stays. A pricing must-have (section 6.4) is decided like any
other, by call managers; without `bid.view_price` its result shows as "present
(restricted)" (`restricted_document_count`), never a file name, and `decide_must_have` on
it is 404.

### 5.4 Reject and reinstate (P2)

`reject_bid` (`BidRejectionIn`: `reason`, 1-500 visible characters; session only): one
click and a reason, **any time before the award**; a new reason replaces the old one. The
SPA offers it prominently when a must-have is `missing` or `not_met`, or an AI assessor
found one `not_met` (a suggestion a person checks; `BidPermissions.reject_suggested`), and
anywhere else from the bid's menu. A rejected bid leaves the assessors' queues (404 for
them), the totals, the price formula and the ranking (the comparison lists it without
scores); its assessments are kept; its active AI assess runs are cancelled. **A rejection
never ends anyone's blindness for the bid** (role matrix 3a: otherwise "reject, read,
reinstate" would get round it). `reinstate_bid` undoes it (idempotent): the bid is
received or qualified again by its must-haves and its assessments count again; the last
rejection stays on record (`BidRejection.reinstated_at`, `reinstated_by`: the reason isn't
lost). Both audited (`bid.reject`, `bid.reinstate`), neither in the feed (bids are not for
everyone).

## 6. Documents (L7, ADR 0018)

### 6.1 Upload

`upload_bid_document` (session only; call managers; before the award) takes **the raw
file as the request body**, the name as `?filename=` (1-200 characters; no `/` or `\`,
no leading dot, no control, bidi or tag characters), optionally `?must_have_id=` (a
`document` must-have of this call, else 422 `invalid_must_have`) and `?pricing=` (section
6.4; default: the must-have's pricing mark, false without one; `false` with a pricing
must-have: 422 `invalid_must_have`). **The request's `Content-Type` is ignored**: the type
comes from the bytes alone (the SPA sends `application/octet-stream`).

In order (review S5): authenticate, the 404s and 403s, then **an upload slot** (at most 2
uploads at once per API process: 503 `upload_busy` with `Retry-After: 5`), then read the
body into **one buffer**, with **no database transaction open**, counted while reading,
within 120 s; then decide the type (off the event loop); then the 422s and the 409s in one
short transaction that inserts the rows.

| Check | Refusal |
|---|---|
| This route alone takes up to **25 MiB** (the global 1 MiB limit stays everywhere else); counted while reading, so a body longer than its `Content-Length` or a chunked one is stopped at the limit | 413 `content_too_large` |
| The whole body within **120 s** (`BID_UPLOAD_READ_TIMEOUT`) | 408 `upload_timeout` |
| Type **from the bytes** (below): PDF, DOCX, XLSX, PPTX, ODT, ODS, plain text (UTF-8 or Windows-1252, no NULs), CSV, PNG, JPEG; anything else, an empty file, an encrypted Office file (an OLE container, not a ZIP), a ZIP with more than 2,000 entries | 415 `unsupported_document_type` |
| Macro-enabled or active Office files and embedded OLE packages, by **entry name** (`BID_REFUSED_ARCHIVE_ENTRY`: `vbaProject.bin`, `vbaData.xml`, `activeX/`, `embeddings/*.bin`, `oleObject*.bin`, nested `.docm` / `.xlsm` / `.pptm` / `.xlsb` and the other macro formats), a `macroEnabled` content type, OpenDocument `Basic/` or `Scripts/` | 415 `macro_document` |
| 30 documents per bid | 409 `too_many_documents` |
| 500 MiB per call: documents' sizes **plus** their extracted text (`text_chars`) | 409 `call_storage_full` |
| 5 GiB per project, counted the same way over all its calls (`BID_PROJECT_STORAGE_MAX_BYTES`) | 409 `project_storage_full` |
| The same file (SHA-256) already on this bid | 409 `duplicate_document` |

**Deciding the type** (review M5: bounded, and never a PDF parser in the API):

- `%PDF-` → PDF (no parsing: an encrypted PDF is accepted and its extraction ends
  `failed` `encrypted`); `\x89PNG\r\n\x1a\n` → PNG; `\xff\xd8\xff` → JPEG.
- `PK\x03\x04` → a ZIP container, inspected **in a thread** (`anyio.to_thread`):
  1. the entry count from the end-of-central-directory record, read from the file's end,
     **before** anything else: more than 2,000 entries is 415;
  2. the central directory's **names only** (never the local headers' or the sizes they
     claim): a name matching `BID_REFUSED_ARCHIVE_ENTRY` is 415 `macro_document`;
  3. at most two entries are decompressed, each with a bounded read:
     `[Content_Types].xml` (up to 256 KiB: bigger is 415) and `mimetype` (up to 64 bytes),
     checked **by substring**, never with an XML parser. OOXML by the main part's content
     type (`…wordprocessingml.document.main+xml` → DOCX, `…spreadsheetml.sheet.main+xml` →
     XLSX, `…presentationml.presentation.main+xml` → PPTX; `macroEnabled` anywhere → 415
     `macro_document`; templates and anything else → 415); OpenDocument by `mimetype`
     (`application/vnd.oasis.opendocument.text` → ODT, `…spreadsheet` → ODS).
- Anything else that decodes as UTF-8, or else Windows-1252, with no NUL byte → text:
  **CSV when the given name ends in `.csv`** (any case), TXT otherwise (the bytes decide it
  is text; the name only picks the label and media type).

The stored name is the given one; the type, media type and extension come from the
sniffed type (`BID_DOCUMENT_TYPES`), never from the name: an extension of the type is
appended when the name lacks one, and **the stem is cut** when the two would pass 200
characters. 201 `BidDocument` with `extraction.state: pending`. Audited
`bid_document.upload` (the file name is not in the audit details: it may name a person;
`pricing` is).

`update_bid_document` (`BidDocumentUpdate`, the complete state: `must_have_id` and
`pricing`; session only, `bid.upload_document`; before the award) links or unlinks the
file and marks it pricing or not; audited `bid_document.update` (what changed).
`delete_bid_document` (session only; before the award) deletes the file, its text and its
link. Unlinking or deleting a must-have's last file makes it `missing` again (section 5.3).

### 6.2 Storage and download

Bytes in `bid_document_contents` (`bytea`, `STORAGE EXTERNAL`: uncompressed out of line,
so 1 MiB range reads don't decompress the whole file), the extracted text in
`bid_document_texts`, metadata in `bid_documents`: lists and the bid page never read the
bytes. Deleting the bid, the call or the idea deletes them (`ON DELETE CASCADE`).
`download_bid_document`: the bytes as stored, **always** `Content-Disposition: attachment`
(an ASCII fallback name and `filename*` in UTF-8), the type's media type,
`X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`,
`Cache-Control: private, no-store`; streamed in 1 MiB chunks from the database. The SPA
never shows a document inline: it shows the extracted text (as text) and offers the
download, with a warning first when `active_content` is set (section 6.3).

### 6.3 Text extraction (the worker)

The worker's `bid_documents` queue extracts each pending document in a **child process**
(as the PDF export does), **one at a time per worker** (`BID_EXTRACTIONS_PER_WORKER`), with
these bounds (review S4):

- **Time**: 30 s wall clock, then killed (`timeout`).
- **Memory**: `RLIMIT_AS` 512 MiB (`BID_EXTRACTION_MEMORY_BYTES`; `memory`), in a worker
  container of **1 GiB** (the chart's worker limit, platform).
- **Isolation**: a `spawn`ed child with an **allow-listed environment** (no database URL,
  secret key or SMTP credentials; the worker holds them), its own empty temporary folder
  (deleted after), the document's bytes on **stdin**, its output (JSON: the text and
  flags) read from stdout **up to a bound** (the text cap's UTF-8 worst case plus a small
  margin; more: `internal_error`).
- **Output**: at most 2,000,000 characters of text (`text_truncated`). The child removes
  NULs and the characters `app.mcp.text.visible_text` hides (soft hyphens, zero-width,
  bidi controls, tag characters) **before** the text is stored (review S1), so REST, MCP
  and the quote checks read the same characters and invisible instructions never reach a
  person or an agent.
- **Archives** (OOXML, ODF; `zipfile`): at most 2,000 entries; an entry is read only up to
  50 MiB and all of them together up to 200 MiB, counting **actual bytes as they stream**
  (never the sizes the archive claims); an entry whose uncompressed size is more than 100
  times its compressed size is refused; nested archives are never opened; XML is read with
  `xml.etree.ElementTree.iterparse`, refusing a `DOCTYPE` (no entity expansion). Any of
  these: `archive_limits`.
- **Formats**: `pypdf` for PDF (BSD-3-Clause; promoted from a dev dependency); OOXML and
  ODF as above; TXT and CSV decoded as UTF-8, else Windows-1252; PNG and JPEG have no text
  (no OCR: `no_text`).
- **Active content** (review S3): the child sets `bid_documents.active_content` when it
  finds a PDF's `/JavaScript`, `/JS`, `/Launch` or `/EmbeddedFile`(s), or an Office file's
  relationship with `TargetMode="External"` (a remote `attachedTemplate`, external links,
  `xl/externalLinks/`) or a DDE field (`DDE`, `DDEAUTO`). The document is kept (files are
  never executed here); the SPA warns before the download.
- **Attempts**: a run that crashes the child or the worker counts in
  `extraction_attempts`; at 3 (`BID_EXTRACTION_MAX_ATTEMPTS`) the document is `failed`
  `internal_error`, so one bad file can't crash-loop the worker.

States: `pending`, `done` (with `chars`, `page_count`), `no_text`, `failed` (`timeout`,
`memory`, `damaged`, `encrypted`, `archive_limits`, `internal_error`). A failed extraction
doesn't refuse the document; the bid page says so.

`get_bid_document_text` pages the text in 20,000-character pages (`page` 1-100; past the
last: 404). **Extracted text is untrusted** (written by the bidder): shown as plain text,
never rendered as Markdown or HTML, passed to agents as evidence, never instructions.

### 6.4 Pricing documents (review M4, lead decision)

A bid document is a **pricing document** when it is marked so (`?pricing=true` at upload,
or `update_bid_document`) or is linked to a **pricing must-have** (`BidCallMustHave.pricing`,
document must-haves only; the default template's "Pricing schedule"), which it must then
stay (422 `invalid_must_have`). A pricing document's **file, extracted text, quotes from
it and its must-have link** are visible only with **`bid.view_price`** (call managers and
the assessors of the section holding the price question):

- everyone else with `bid.view_bids` gets no row for it in `BidDetail.documents`, 404 for
  its download and text, `Bid.restricted_document_count` and
  `BidMustHaveState.restricted_document_count` instead (the must-have shows "present
  (restricted)", no file name);
- **the AI never reads pricing documents**: `get_bid_for_assessment` leaves them and the
  pricing must-haves out, `get_bid_document_text` answers `not_found`, and quotes may cite
  only the documents it was given (`validation_error`); prices are scored by the formula
  anyway;
- **marking** a document pricing (it wasn't) deletes the bid's AI assessments and cancels
  its active assess runs (the AI may have read it: ask again); unmarking opens it to every
  assessor and the AI. Both audited `bid_document.update`.

The SPA says so in one line when a manager uploads into a pricing must-have (for example
"Only call managers and the Commercial assessors can open this file").

## 7. Assessors and assessments (P3)

### 7.1 Assigning (c28)

`set_bid_assessors` (`BidAssessorsUpdate`: every section with its `user_ids`, 0-10 each,
and `due_at`, the call's **only** writer of the assessment due date; the complete state;
session only) on a call that isn't finished. Assessors are **active people who can view
the idea in their own right** (in a private project: a role there, **never** as the idea's
guest researcher, column R; an admin adds people as members first), never a service
account, the break-glass account or a deactivated account (422 `assessor_not_eligible`,
naming the user). c28 is also checked **live** on every request an assessor makes (the
+Asr overlay; review M6): someone who left a private project holds nothing through their
assignment, even while they research the idea. A section of another call or one left
out: 422 `unknown_section`. A person may assess several sections; call managers may
assess too. People added get "Asked to assess bids". Removing people (Phase 1's c16 and
`evaluator_has_submitted`, for sections; review M3):

1. **yourself**, from a section you still owe for any bid of the call (a bid you haven't
   submitted that section for, **rejected bids included**): 403 `cannot_remove_self`.
   Otherwise a pending assessor could step out, read every score, step back in and submit
   an anchored assessment. Another call manager may remove you, or you submit;
2. someone who has **submitted** an assessment of that section (for any bid): 409
   `assessor_has_submitted` (submitted work is never thrown away; their scores count);
3. otherwise the assignment goes, with that person's **drafts** of the section.

Audited `bid_call.assessors_change`.

### 7.2 Assessing

`get_my_bid_assessment` (`bid.view_own_assessment`: a key needs `read`, as
`evaluation.view_own`) / `save_my_bid_assessment` (`bid.assess`: `evaluate`) for one bid
and one section you assess (else 403 `not_section_assessor`; a rejected bid: 404 for an
assessor who isn't a call manager). `MyBidAssessmentIn`: `answers` (`question_id`, `score`
0-5 for score questions, `comment` up to 2,000) and `submit`. Saving without `submit` keeps a **draft**
(private to its author); `submit: true` needs every score question scored (422
`assessment_incomplete`); a question of another section, unknown, or the price question:
422 `unknown_question` / `not_assessable`. Only while the call is **assessing** (409
`bid_call_not_assessing`) and the bid isn't rejected (409 `bid_rejected`); editable after
submitting until the award (`edited_at`). The first person's submission in the call locks
the template (4.3). Audited `bid_assessment.submit` on each first submission.

### 7.3 Blind (role matrix 3a)

For a bid *B* and section *S*, a principal who **assesses *S* and hasn't submitted *S* for
*B*** sees no one else's scores, comments, AI scores or section score for (*B*, *S*), and
neither *B*'s total nor its rank (they would reveal them), through every surface:
`list_bid_section_assessments` answers `hidden: true` and nothing else, the comparison
marks those cells `hidden` and the total `total_hidden`, `list_bid_ai_assessments` leaves
out *S*'s scores (`hidden_section_ids`), the report leaves the bid's scores out for them,
and nothing in My work, notifications, emails, the feed or MCP carries any score. After
submitting *S* for *B* they see (*B*, *S*)'s assessments and the AI's scores for *S*
(`bid.view_section_scores`); totals and the ranking stay with the call managers
(`bid.view_scores`).

Three rules close the ways round it (review M2, M3):

- **No ranking while you owe anything.** If any row of your comparison (or report) has
  `total_hidden`, every row has `rank: null`, `tied: false`, the rows are in the order
  received and `BidComparison.ranking_hidden` is true: the ranks of the others (1, 3)
  would place the hidden bid (2).
- **A rejection never ends blindness.** A pending assessor of (*B*, *S*) stays blind for
  it after *B* is rejected (and if reinstated); the comparison shows no scores for rejected
  bids at all.
- **You can't step out of a section you owe** (`cannot_remove_self`, section 7.1).

## 8. Scoring (L8)

Computed with exact fractions; only what the API returns is rounded, **half up**: scores
on 0-5 to 2 decimals, section scores and totals on 0-100 to 1 decimal.

Everything below is for **scored bids** (section 5.2: not rejected, every must-have met;
`is_scored`), before and after the award alike.

- **A question's score** = the mean of the counted scores: submitted human assessments
  of that section for that bid, plus each **included** AI assessment's score. Drafts never
  count. No counted score: no score.
- **Price score** (the price question) = lowest **scored** price ÷ this bid's price × 5
  (the lowest scored bid gets 5; no cap needed: a scored bid is never below the lowest
  scored price). Rejected bids and bids with a must-have not met don't take part.
- **Section score** (0-5) = the weighted mean of its scored questions (comment questions
  don't count), shown × 20 as 0-100. None while any of its questions has no score.
- **Total** (0-100) = Σ section weight % × section score × 20. None while any section has
  no score. Only scored bids get one.
- **Disagreement**: two counted scores on one question differ by **2 or more**
  (`BidQuestionStats.disagreement`, `BidSectionScore.disagreement`).
- **Progress**: "n of m assessed" (`BidProgress`) for each bid, section and the call.
  Expected = every (assessor, section, bid that isn't rejected) whose assessor is still
  **eligible** (`BidAssessor.can_assess`, c28 live), plus the submitted ones of
  ineligible assessors (their scores still count); submitted = those with a submitted
  assessment (review S10: a deactivated or departed assessor never keeps a call from
  completing). `BidComparison.complete` when nothing expected is outstanding; checked
  after every submission, rejection and assessor change, it sends `assessments_complete`
  once per call.
- **Ranking**: scored bids with a total, by the **rounded** total, highest first.
  Equal rounded totals **share a rank** (competition ranking "1, 2, 2, 4", `tied: true`);
  within a tie the lower price is listed first (no price last), then the earlier
  `received_at`, then the id. Ties are never broken silently: the award is a person's. No
  rank at all while you owe an assessment of any bid (section 7.3, `ranking_hidden`).
- **Comparison order**: ranked bids, then the other bids that aren't rejected by
  `received_at`, then rejected bids (no scores); with `ranking_hidden`, every bid by
  `received_at`.

### 8.1 Worked example (tests: `test_schemas_phase10.py`)

Template: Technical 40 % (Q1 weight 2, Q2 weight 1), Commercial 40 % (Q3 the price,
weight 3; Q4 weight 1), Delivery 20 % (Q5). Technical: carol and mateo; Commercial: priya;
Delivery: sven and alice.

| Bid | Price | Q1 | Q2 | Q3 (price score) | Q4 | Q5 |
|---|---|---|---|---|---|---|
| A, qualified | 120,000 | 4, 5 → 4.5 | 4, 4 → 4 | 96,000 / 120,000 × 5 = **4** | 4 | 4, 5 → 4.5 |
| B, qualified | 96,000 | 4, 2 → 3 (**disagreement**) | 3, 3 → 3 | **5** | 3 | 3, 4 → 3.5 |
| C, rejected (no insurance) | 80,000 | out of everything, including the lowest price | | | | |

After the award to A, A is `awarded` and B `unsuccessful`; both are still scored (every
must-have met), so the report shows the same numbers and ranks.

- A: Technical (2 × 4.5 + 1 × 4) / 3 = 13/3 → **86.7**; Commercial (3 × 4 + 4) / 4 = 4 →
  **80.0**; Delivery 4.5 → **90.0**; total 0.4 × 86.67 + 0.4 × 80 + 0.2 × 90 = 254/3 →
  **84.7**.
- B: Technical 3 → **60.0**; Commercial (3 × 5 + 3) / 4 = 4.5 → **90.0**; Delivery 3.5 →
  **70.0**; total 24 + 36 + 14 → **74.0**.
- Ranking: A 1st (84.7), B 2nd (74.0). Had C not been rejected, the lowest price would be
  80,000 and A's price score 3.33.
- The AI assessed B (Q1 3, Q2 4, Q4 4, Q5 3), left out: nothing changes. **Included**:
  Q1 (4 + 2 + 3) / 3 = 3, Q2 (3 + 3 + 4) / 3 = 10/3, Q4 (3 + 4) / 2 = 3.5, Q5 (3 + 4 + 3)
  / 3 = 10/3; Technical (6 + 10/3) / 3 → **62.2**, Commercial (15 + 3.5) / 4 → **92.5**,
  Delivery → **66.7**; total → **75.2**. Q1 still disagrees (4 and 2).
- Rounding: 86.45 shows as **86.5** (half up, on the exact value).

## 9. The AI assessor (P4, L9)

### 9.1 Agents and runs

An agent registered with the purpose **`assess_bid`** (Admin settings → AI agents; its key
gets `read`, `evaluate`, `mcp`) may be asked by call managers (`ai.assess_bid`: c5, c10)
while the call is **open or assessing** (409 `bid_call_not_assessable`) for a bid that
isn't rejected (409 `bid_rejected`): `request_ai_bid_assessment` ("Ask AI to assess", 201
the run, 200 the active one) or `request_ai_bid_assessments` ("Assess all with AI": one
run per bid that isn't rejected; `AiRunBatch` with `created` and `skipped`). Each new run
counts toward the person's **20 AI requests an hour**: the batch starts what fits, bids in
the order received, and reports the rest as `skipped`; 429 `too_many_attempts` only when
none fits (review C6). One active run per idea, agent, kind and **bid**
(`uq_ai_runs_active`). Runs are ordinary AI runs (`ai_runs.kind = assess_bid`, `bid_id`,
`bid_call_id`), with their events, deadline, cancel and SSE; `AiRun.bid_id` names the bid
(nothing else of it). The run message (`run_message`) carries the run id, the idea's key
and the bid's id, never bid data, prices or document text. `IdeaPermissions` /
`BidCallPermissions.request_ai_blocked_by` gains `bid_call_state` and `bid_rejected`.

**The call's AI assessor** (lead decision on P2's "pre-checked by the AI"; automatic but
bounded). A call manager may name one agent on the call (`update_bid_call`
`ai_assessor_id`: an agent passing c10 for `assess_bid` on the idea, else 409
`ai_unavailable`; an unchanged value isn't checked again; audited in `bid_call.update`).
While one is set and AI is on, **each bid gets one automatic assess run** (`automatic:
true`, `requested_by` null, not counted toward anyone's 20 an hour, not audited as a
request) once all of these hold:

- the call is open or assessing and the bid isn't rejected;
- the bid has at least one document and none is `pending` extraction (done, no text or
  failed);
- nothing was uploaded to the bid for 5 minutes (`BID_AUTO_AI_QUIET`, so a batch of
  uploads is read together; lead default, to confirm);
- the agent still passes c10, and the bid has no automatic run yet (`bids.auto_ai_run_at`
  is null; it is set when the run is created and never reset: a later document change
  doesn't run it again).

The worker checks after each extraction finishes (deferring the check to the end of the
quiet period), and when the AI assessor is set or the call opens or closes to new bids.
Further runs are manual and counted as above. Its findings stay suggestions a person
confirms; its scores stay out of the totals until included (section 9.4).

**Cancelled runs** (review S8): rejecting a bid, marking one of its documents pricing,
changing the call's template copy, the award and cancelling the call cancel the affected
active assess runs (`cancel_requested`; the worker sends `tasks/cancel`), in the lock
order project → idea → call → bid → run; deleting a bid or the call deletes its runs.
`submit_bid_assessment` from a run that is still running then refuses (`bid_rejected`,
`bid_call_finished`, `bid_call_not_assessable`).

**Who sees assess runs** (review S9): `list_idea_ai_runs` lists an idea's `assess_bid`
runs, and `get_ai_run`, `stream_ai_run_events` and `cancel_ai_run` answer for one, only to
principals with `bid.view_bids` (they name bids); everyone else: left out, or 404 (as if
the run didn't exist). A guest researcher gets 404 there anyway.

### 9.2 MCP (c22)

Three tools join the catalogue with their handlers (`PHASE10_MCP_TOOLS`; rule
`bid.ai_assess`, scope `evaluate`, granted only through c22: people get `forbidden`):

| Tool | Reads or writes |
|---|---|
| `get_bid_for_assessment` (`bid_id`, `run_id`) | the call (title, description, scale, sections with their **score** questions, the must-haves **except pricing ones**, with `restricted_document_count`), the bid (id, bidder, received), its documents **except pricing ones**, with their extraction state, and the agent's own earlier assessment of this bid (`previous`). **Never** other bids, people's scores, the price, pricing documents, the contact or the notes. |
| `get_bid_document_text` (`bid_id`, `document_id`, `page`, `run_id`) | one 20,000-character page of a document's extracted text (a pricing document or another bid's: `not_found`) |
| `submit_bid_assessment` (`bid_id`, `scores`, `findings`, `run_id`) | for **every score question** a `score` 0-5, a `rationale` (1-1,000) and up to 3 `evidence` quotes (`document_id` + `quote`, 20-500 characters, one passage, no ellipses; a score above 0 needs one); for **every must-have it was shown** a `finding` (`met`, `not_met`, `unclear`) with a rationale and quotes (`met` needs one). Replaces the agent's earlier assessment of the bid. Write config: unknown arguments refused. Refused once the bid is rejected (`bid_rejected`), the call finished (`bid_call_finished`) or no longer open or assessing (`bid_call_not_assessable`). |

c22 for `assess_bid` runs: `bid_id` must be the **run's bid** (else `ai_run_not_active`,
checked with the run before anything is looked up), the run's reads are those two tools
only (`ASSESS_RUN_READ_TOOLS`; `get_idea`, `search_ideas` and the rest:
`ai_run_not_active`), the one write is `submit_bid_assessment`; no other run kind may call
the bid tools. A question or must-have of another call, a pricing must-have, a missing
one, one twice, or a quote citing a document it wasn't given: `validation_error`.

### 9.3 Evidence checks

On submission the server checks **every quote** against its document's extracted text,
both **whitespace-normalised** (every run of whitespace as one space, ends trimmed; case
and punctuation count; at least 20 characters once normalised): `found: false` is stored
and shown as "Not found in the document", `found: true` as "Found in the document" (the
words are there; whether they support the score is the people's judgement);
`quotes_not_found` counts them (in the tool's result too). The stored text is already
`visible_text` (section 6.3), so a quote copied from what MCP returned is found. The check
is `quotes_found` (`app/schemas/bids.py`): **each cited document is normalised once**, and
it runs **off the event loop** (`anyio.to_thread.run_sync`; review S2: 420 quotes over
2,000,000-character texts took 33 s quote by quote). Agent text (rationales, quotes)
loses bidi and zero-width characters before it is stored (Phase 6) and is shown as
untrusted text.

### 9.4 Inclusion

AI assessments start **out of every total** (`included: false`). `set_bid_ai_inclusion`
(`{"include": true}`; call managers) includes one for its bid, idempotent, audited
`bid_assessment.include_ai`; a re-submission that changes any score leaves it out again.
Must-have findings are **only suggestions**: shown beside the result, never changing it.
A call manager who owes an assessment of the bid doesn't see the AI's scores for those
sections (and can't include it: 404) until they submit.

## 10. Who sees what

The rules are table M of the role matrix, with section 3a (blind and price) and table L's
rows for the guest researcher (404 for every bid route and tool). In short:

| Principal | Sees |
|---|---|
| Call manager (owner, PAd, PA) | everything, except (*B*, *S*) scores while they owe that assessment themselves, and no ranks while they owe any (3a) |
| Section assessor (+Asr, c28 live) | the call and its template, every bid that isn't rejected (bidder, received, documents and text, must-have results, the AI's findings), their own assessments; prices and pricing documents only as an assessor of the price section (else "present (restricted)"); others' scores for (*B*, *S*) after submitting *S* for *B*; never totals, ranks, contacts, notes, rejection reasons or rejected bids |
| Member, viewer, internal non-member | the summary: title, status, deadline, number of bids (and the feed's `bid_call_changed`) |
| Guest researcher (R) | nothing (404) |
| An agent | only through its assess run's tools (9.2) |
| A person's API key | owner ∩ scopes ∩ projects; session-only routes refused (403 `insufficient_scope`) |

## 11. Notifications and My work (L10)

| Type | To | When | Dedupe |
|---|---|---|---|
| `assessor_assigned` "Asked to assess bids" | a person newly added to sections (not the actor) | `set_bid_assessors` | one per request that added them (`assessor_assigned:<call>:<request>`) |
| `assessment_reminder` | an assessor with unsubmitted assessments (sections they assess × bids not rejected) | 2 days before and on `assessment_due_at`, at the digest hour, while the call is assessing | one per call, person, due date and day |
| `assessments_complete` | the idea's owner and the call's creator (lead default: not every admin) | when nothing expected is outstanding (section 8: after a submission, a rejection or an assessor change) | one per call |

Inbox items carry `call` (`BidCallRef`), section titles, `due_at`, counts: **never
scores, prices, bidders or document text**. Recipients are re-checked when shown and
emailed (still an assessor, still `bid.manage`). Preferences, digest, unsubscribe scopes
(`UnsubscribeScope`) and email templates follow Phase 3; the defaults are `immediate`;
someone who had every type off gets `off` rows for the three (migration 0016). Links:
`/ideas/{key}?tab=bids`.

My work: `bids_to_assess` (`WorkBidAssessment`: idea, call, your sections, due date,
overdue, your progress), for calls being assessed where you owe assessments, first 50 by
due date; `WorkCounts.bid_assessments_due` / `_overdue` (cheap: one grouped count from
`ix_bid_section_assessors_user_id_call_id`). The Phase 8b statement budgets (`me.work` 11,
`me.work.counts` 4) may grow by one statement each; the p95 budgets (150 ms) stay.
Reminders, My work and the counts **skip** calls on closed ideas and in archived projects,
and assignments that fail c28 now (review S10).

## 12. Feed and audit

`bid_call_changed` (`BidCallChangedActivity`: `call`, `from_status`, `to_status`) on
start and each move (cancelling included); readable by everyone with `bid.view_call`;
never in a guest's feed (`BID_ACTIVITY_TYPES`, not in `RESEARCH_GUEST_ACTIVITY_TYPES`).
Bids, rejections, documents and assessments are **not** in the feed, and don't bump the
idea's activity (section 2.1).

Audit actions (19): `project.bid_template_replace`, `bid_call.create`, `.update`,
`.template_replace`, `.status_change` (cancelling too), `.award`, `.delete`,
`.assessors_change`, `bid.create`, `.update`, `.delete`, `.reject`, `.reinstate`,
`.must_have_decide`, `bid_document.upload`, `.update` (the link and the pricing mark),
`.delete`, `bid_assessment.submit`, `.include_ai`. Details hold ids, fields changed,
flags (`pricing`) and counts; never document names, contents, prices, scores or reasons'
text. Automatic AI runs aren't audited (nobody asked; their events say "Started
automatically").

## 13. Export (L11)

`export_bid_report_markdown` / `_pdf` (`bid.view_scores`: call managers only): the call,
the ranking, each bid's section scores and total, the price scores, for each bid its
must-have **counts** (met, not met, missing, unchecked) plus the items missing or not met
by name (not the full bids × must-haves grid: at the maximum, 50 × 20, it passed the PDF's
5,000-box bound; review S15), rejected bids with their reasons, the assessors per section
and their progress, whether each bid's AI assessment was included, and the award with
its reason. Scored the same way before and after the award (section 5.2). A manager who
owes an assessment gets the report without that bid's scores ("Hidden until you submit")
**and without any ranks** (section 7.3). Text people or bidders wrote (bidder names,
reasons, section and must-have titles) is **escaped** in the Markdown (shown as text,
never markup) and rendered as text in the PDF. `<KEY>-bid-evaluation.md` / `.pdf`; the
PDF through the existing child process (branding, fonts, the 5,000-box bound, tested at
the maximum: 50 bids, 20 must-haves, 8 sections of 15 questions); shares the export
throttle (429) and `export_busy` (503).

## 14. Changed shapes (additive)

| Schema | Change |
|---|---|
| `IdeaDetail` | `bid_call: BidCallSummary \| null` (null without a call, and for a guest researcher) |
| `IdeaPermissions` | `can_view_bid_call`, `can_create_bid_call` |
| `Work`, `WorkCounts` | `bids_to_assess`; `bid_assessments_due`, `bid_assessments_overdue` |
| `AiRun`, `AiRunResult` | `bid_id`, `automatic`; `bid_ai_assessment_id` |
| `AiRunKind` (purposes) | `assess_bid` (agents: 1-4 purposes) |
| `AiBlockedReason` | `bid_call_state`, `bid_rejected` |
| `NotificationType`, `EmailType`, `UnsubscribeScope`, `NotificationPreferencesUpdate`, `NotificationItem` | the three types |
| `ActivityItem` | `BidCallChangedActivity` |
| `AuditAction` | the 19 actions |
| `list_audit_entries` | the `action` filter takes up to every action (`len(AuditAction)`, now 73; was 64, which the actions outgrew) |

## 15. Error codes (new)

`bid_call_exists`, `bid_call_not_available`, `bid_call_finished`, `bid_call_not_open`,
`bid_call_not_assessing`, `bid_call_not_assessable`, `invalid_bid_call_transition`,
`bid_call_template_locked`, `assessments_submitted`, `bid_call_deadline_required`,
`bid_call_active`, `bid_rejected`, `bid_not_qualified`, `document_missing`,
`price_not_asked`, `too_many_bids`, `unsupported_document_type`, `macro_document`,
`content_too_large` (now also 413 for uploads), `upload_timeout` (408),
`too_many_documents`, `call_storage_full`, `project_storage_full`, `duplicate_document`,
`invalid_must_have`, `upload_busy`, `assessment_incomplete`, `unknown_question`,
`not_assessable`, `unknown_template_item`, `assessor_not_eligible`,
`not_section_assessor`, `assessor_has_submitted`; reused: `cannot_remove_self` (Phase 1's
c16, now also for sections), `unknown_section`, `not_found`, `forbidden`,
`insufficient_scope`, `idea_closed`, `project_archived`, `awaiting_moderation`,
`ai_unavailable`, `too_many_attempts`, `export_busy`, `ai_run_not_active`. MCP tool
errors of `submit_bid_assessment`: `bid_rejected`, `bid_call_finished`,
`bid_call_not_assessable`. Dropped by the review: `document_type_mismatch` (the type comes
from the bytes alone).

## 16. Minimum tests (tests first)

- **Access table** over principal kinds × every route and tool (role matrix table M's
  route list): call manager (owner, PAd, PA), section assessor before and after submitting,
  an assessor of another section, the price section's assessor, member, viewer, internal
  non-member, NMp, guest researcher, an agent in its assess run / another run / no run, a
  person's key per scope (`read`, `write`, `evaluate`, `mcp`), session-only routes with a
  key.
- **Leaks**: score data, prices, pricing documents (file, text, name, quotes), bidder
  names and document text never reach the idea detail, the feed, notifications, emails,
  digests, search, ⌘K, SSE, AI runs (list, get, stream, cancel) for people without
  `bid.view_bids`, MCP `get_idea` / `search_ideas`, My work, counts, the report for a
  pending manager; a guest researcher's 404 everywhere (the meta-tests); a member gets
  the same 403 for a real and an unknown bid id.
- **Blind (3a)**: a pending assessor (draft and none) per surface, then after submitting;
  a manager who assesses (no ranks at all while they owe one bid: `ranking_hidden`); a
  rejected and reinstated bid stays hidden; `cannot_remove_self` (rejected bids
  included), `assessor_has_submitted`, drafts going with the assignment.
- **c28 live**: an assessor who leaves a private project but is the idea's researcher
  (column R) gets nothing of the call; a deactivated assessor stops counting as owing.
- **Pricing documents**: per principal kind (manager, price-section assessor, another
  section's assessor, the AI in its run): listed or not, download and text 404,
  "present (restricted)", marking deletes the AI assessments and cancels runs.
- **Uploads**: every type by its bytes, a renamed executable, a macro DOCM renamed
  `.docx`, an embedded `oleObject1.bin` and an embedded `.docm`, an ODT with `Basic/`, an
  encrypted Office file (OLE), a ZIP whose end record claims more than 2,000 entries, an
  oversized `[Content_Types].xml`, an empty file, 25 MiB + 1 byte, a lying
  `Content-Length`, a chunked body, a body slower than 120 s, a duplicate, the 30 and 500
  MiB caps (text counted) and the 5 GiB project cap, filenames with `../`, `\`, a leading
  dot, CR/LF, bidi, and a 200-character name that gets an extension; no transaction is
  open while the body is read; the download headers.
- **Extraction**: each type, a zip bomb (ratio, one entry and the total, counted as they
  stream), 2,001 entries, a nested archive, a DOCTYPE, a damaged file, an encrypted PDF,
  the timeout, the memory cap, the text cap, NULs and hidden characters removed, the
  child's environment, active content flagged (PDF JavaScript, a remote template), three
  crashes then `internal_error`, all in the child.
- **Quote checks**: found across line breaks and no-break spaces, invented, too short (under
  20), another bid's document, a pricing document, text with soft hyphens copied from MCP;
  420 quotes over 30 documents of 2,000,000 characters well under a second, off the loop.
- **Scoring**: section 8.1, ties, rounding, rejected bids out of the price formula, the
  AI in and out, a re-submission excluded again, **the comparison and the report after
  the award** (same numbers and ranks).
- **Lifecycle and locks**: every transition and refusal, cancel's own route, the deadline
  frozen while assessing, the template lock by a person's submission and not by the AI's,
  AI assessments cleared and runs cancelled by a template change, a rejection, the award,
  cancelling and a pricing mark, read-only after the award, deleting (an awarded call by a
  platform admin only).
- **Must-haves**: automatic missing/met, `document_missing`, the last file deleted or
  unlinked (a person's met back to missing, not met kept), reject/reinstate before the
  award (the last rejection kept), reject suggested (also by an AI not met).
- **Automatic AI assessor**: one run per bid once nothing is pending and the quiet period
  passed, not counted toward the hourly limit, never a second one, none for a rejected bid
  or a draft call.
- **Report**: at the maximum size within the 5,000-box bound; bidder names and reasons
  with Markdown in them escaped.
- **Migration**: 0016 up on 0.2.0's demo data (templates for every project), down
  (`tests/test_domain_schema_phase10.py`), up, `alembic check`.

## 17. Demo data (backend's seed, L12)

**TOOLS-3** ("its proposal ends with the research appendix") in the private Internal
Tools project: it already has a proposal in Proposal, and a private project shows that
assessors must have a role there. Call "Data platform build", **assessing**, deadline
passed, assessment due in a few days, no AI assessor named (the demo runs without AI);
Technical: carol, mateo; Commercial (with the price): priya; Delivery: sven, alice. Three
fictional suppliers: **Northwind Data Ltd** (complete and strong, 120,000), **Tessellate
Software** (complete, cheaper at 96,000, weaker technically; carol and mateo disagree on
its first question), **Quillfield Systems** (no insurance certificate: flagged missing,
rejected with "No insurance certificate provided."). Each complete bid has a form of
tender, a **pricing schedule** (a pricing document: carol, mateo, sven and alice see
"present (restricted)", priya opens it) and an insurance certificate. Most assessments
submitted; **alice owes her Delivery assessments** (My work), so her comparison is fully
hidden (no ranks) as she is a platform admin: **walk the comparison as kenji (the owner) or
dave (the project admin)**; an AI assessment of Tessellate left out of the totals. Small
PDF and DOCX files under `backend/app/seed/bids/` (a few KB each), extracted at seed time.
`dev/README.md`'s who's who gains the call. All five assessors are members of Internal
Tools in the seed (dave its admin, kenji the idea's owner); zanele, a viewer there, sees
the summary only.

## 18. Contract mechanics

- 34 stubs answer 501 until built (`STUBS`); `PHASE10_OPERATIONS` pins their names and
  the tag `bids`.
- `ROUTE_KEY_ACCESS` has a row for each (section 2); `RESEARCH_GUEST_ACCESS` hides all of
  them and the three MCP tools (`hidden`), so the guest meta-tests pass.
- The three MCP tools are defined (`PHASE10_MCP_TOOLS`, `BID_ASSESSMENT_INSTRUCTION`) but
  **not in `MCP_TOOLS`** until backend adds their handlers (the catalogue's tests require a
  handler per tool). `bid_call_changed` is in `PHASE10_ACTIVITY_TYPES` until backend adds
  its `PAYLOAD_KEYS` row and emits it.
- `make gen-api` regenerated `frontend/src/api/generated/`.

## 19. Requests to builders

- **identity**:
  - the rules of table M and `project.edit_bid_template` in the policy (deny by default),
    including the review's `bid.view_own_assessment` (`read`) and `bid.delete_call` (c30);
  - **+Asr live** (review M6): from `bid_section_assessors`, held only while c28 holds now:
    an active person with a role in a private project (internal: any signed-in person),
    **never through column R**; a test with an assessor who left the private project but
    researches the idea;
  - `ROUTE_RULES` rows for the 34 operations (`cancel_bid_call` is `bid.decide`,
    `delete_bid_call` `bid.delete_call`, `update_bid_document` `bid.upload_document`,
    `get_my_bid_assessment` `bid.view_own_assessment`); `set_bid_assessors` in the
    session-only-by-decision list; the matrix test's MATRIX (with the +Asr column), table
    L rows and their tests;
  - `bid.view_bids` checked **before** a bid is looked up (section 2.1, step 3).
- **backend**:
  - the services, migrations' consumers (`create_project` inserts a template), the
    comparison and scoring (`is_scored`, `rank_bids`, `ranking_hidden`; the pure functions
    in `app/schemas/bids.py`), the report (counts plus failing items, escaping, tested at
    the maximum);
  - the upload route (section 6.1: its own 25 MiB body limit in `app/middleware.py`, the
    slot before the body, no transaction while reading, 120 s, the ZIP inspection in a
    thread with `BID_REFUSED_ARCHIVE_ENTRY`, the storage caps with text counted);
  - the extraction queue and child (section 6.3: one at a time, the numbers, an
    allow-listed environment, stdin/stdout, `visible_text`, `active_content`,
    `extraction_attempts`); `pypdf` as a runtime dependency;
  - pricing documents (section 6.4) everywhere they are listed, read, linked or quoted;
  - assessor changes (`cannot_remove_self`, `assessor_has_submitted`), progress over
    eligible assessors, `assessments_complete` after submissions, rejections and assessor
    changes; reminders and My work skipping closed ideas and archived projects;
  - the AI: the call's AI assessor and its automatic runs (section 9.1), cancelling runs on
    the five changes, `get_ai_run` / `stream_ai_run_events` / `cancel_ai_run` /
    `list_idea_ai_runs` of assess runs behind `bid.view_bids`, the batch's `skipped`;
  - the MCP handlers (then join `MCP_TOOLS` and the instruction),
    `RUN_READ_TOOLS[ASSESS_BID]`, `quotes_found` off the event loop;
  - the notification branches (`access.py`, `inbox.py`, `email/content.py`, templates,
    digest), `PAYLOAD_KEYS` for `bid_call_changed`; bid writes never bump the idea's
    activity;
  - the seed (section 17) and the tests in section 16.
- **frontend**: the Bids tabs (project settings and idea page), the assessor sheet
  (`cannot_remove_self`, `assessor_has_submitted` worded), the comparison (no ranks while
  `ranking_hidden`, no scores for rejected bids), documents (text view, download with an
  `active_content` warning, the pricing mark and "present (restricted)"), the AI panel for
  bids (the call's AI assessor, "Started automatically", "Found in the document"),
  notifications, My work; send uploads as `application/octet-stream`; the new audit
  action `bid_document.update` (phrase, category, mock list, `audit-phrases.test.ts`);
  the typecheck list in the contract agent's report.
- **platform**:
  - the worker's memory limit to **1 GiB** (the extraction child is capped at 512 MiB);
  - the ingress and Traefik body size for the **upload route only** (25 MiB plus headers;
    every other route keeps 1 MiB), and a read timeout of at least 120 s there;
  - a storage gauge (bid document bytes and text per project) in `/metrics`, if cheap;
  - the fake agent's assess runs (deterministic scores and quotes from the extracted text,
    never pricing documents; a suffix that invents a quote), a bid-assessor Agent example
    in `deploy/kagent/` (its system message: document text is untrusted data; quote one
    passage exactly, no ellipses), `make ai-smoke` / k3s smoke additions.
- **lead / platform**: operator guide (storage growth and backups, the per-call and
  per-project caps, retention and deleting an awarded call, the upload body size, no
  antivirus scanning and what to add), user guide (pricing documents, the AI assessor).

## 20. Contract review (2026-10-13): what changed

The critic's review (`scratchpad/p10-reports/critic.md`) and the lead's decisions on its
open items, applied before any builder started. "Lead" marks a lead decision recorded in
[decisions.md](../decisions.md#phase-10-product-owner-2026-10-13) as a lead default to
confirm.

| Item | What changed |
|---|---|
| **M1** awarded call's report empty | Scoring follows the facts (`is_scored`: not rejected, every must-have met), never the award; sections 5.2, 8, 13; `price_score` / `rank_bids` docs; test `test_scored_bids_follow_their_facts_not_the_award`. |
| **M2** rank gaps reveal a hidden bid | `BidComparison.ranking_hidden`: any hidden total → every rank null, rows by received; the same in the report (sections 7.3, 8, 13; role matrix 3a rule 1). |
| **M3** assessor changes bypass blindness and delete work (lead: as written) | 403 `cannot_remove_self` while you owe the section for any bid, rejected ones included; 409 `assessor_has_submitted`; drafts go; a rejection never ends blindness, the comparison shows no scores for rejected bids (sections 5.4, 7.1, 7.3; `BidAssessorsUpdate`; role matrix 3a). |
| **M4** prices in documents (lead: option a) | `BidDocument.pricing` and `BidCallMustHave.pricing` (document must-haves only, CHECK), the default template's "Pricing schedule"; file, text, quotes and link only with `bid.view_price`, else "present (restricted)" (`restricted_document_count`); the AI never reads them (`get_bid_for_assessment` leaves them and pricing must-haves out); marking deletes the bid's AI assessments; `update_bid_document` is session only and audited (`bid_document.update`); rule 6 reworded "never the price field or a pricing document" (section 6.4). |
| **M5** ZIP inspection unbounded in the API | End-record entry count first (> 2,000: 415), central-directory names only, two bounded reads checked by substring, in a thread; no PDF parsed in the API (an encrypted PDF ends `failed` `encrypted`); `BID_ARCHIVE_MAX_ENTRIES`, `BID_CONTENT_TYPES_MAX_BYTES`, `BID_ODF_MIMETYPE_MAX_BYTES` (section 6.1, ADR 0018). |
| **M6** a former member who researches the idea keeps the bids | +Asr and c28 checked live, never through column R (sections 7.1, 19; role matrix +Asr, c28). |
| **S1** quote checks fail on genuine quotes | The child stores `visible_text` of the extraction (no NULs, no hidden characters); REST, MCP and quote checks read one text; "no ellipses" in the instructions (sections 6.3, 9.3; `run_message`, MCP descriptions). |
| **S2** quote checks too slow | `quotes_found` normalises each cited document once; run off the event loop (section 9.3). |
| **S3** active content beyond macros | Refused by name: embedded OLE (`embeddings/*.bin`, `oleObject*.bin`), nested macro-enabled files, `vbaData.xml` (`BID_REFUSED_ARCHIVE_ENTRY`); the child sets `BidDocument.active_content` (PDF JavaScript, launch, attached files; remote templates, external links, DDE); the SPA warns before download (sections 6.1, 6.3). |
| **S4** extraction child underspecified | The numbers (2,000 entries, 50 MiB a part, 200 MiB in total as streamed, ratio 100, no nesting, `iterparse`), one at a time per worker, 512 MiB cap in a 1 GiB worker (platform request), allow-listed environment, stdin/stdout with a bound, 3 attempts (`extraction_attempts`) then `internal_error` (section 6.3). |
| **S5** upload mechanics | Auth, 404/403 and the slot before the body; no transaction while reading; 120 s (408 `upload_timeout`); one buffer; the stub's order fixed (sections 2.1, 6.1; `api/v1/bids.py` docstring). |
| **S6** storage exhaustion | Text counted toward 500 MiB a call; 5 GiB a project (409 `project_storage_full`); a gauge requested from platform (section 6.1). |
| **S7** rows can mix two calls | `UNIQUE (id, call_id)` on sections, must-haves, bids, `(id, idea_id)` on calls; composite foreign keys from questions, assessors, results (+`call_id`), documents, assessments (+`call_id`) and AI runs (+`bid_call_id`); tested live (`test_no_row_mixes_two_calls`). |
| **S8** runs not cancelled by later changes | Reject, a pricing mark, a template change, the award and cancel cancel active assess runs; `submit_bid_assessment` refuses with `bid_rejected`, `bid_call_finished`, `bid_call_not_assessable`; lock order ends with the run (sections 2.1, 9.1, 9.2). |
| **S9** other AI run routes leak assess runs | `get_ai_run`, `stream_ai_run_events`, `cancel_ai_run` of an assess run need `bid.view_bids` (404 otherwise; section 9.1). |
| **S10** departed assessors block completion | Progress counts eligible assessors only (their submitted scores still count); reminders, My work and counts skip closed ideas and archived projects (sections 8, 11). |
| **S11** `update_bid` resets `received_at` | `BidUpdate` with `received_at` required; the stored value always accepted (section 5.1). |
| **S12** filename overflow | The stem is cut so name and extension fit 200 characters (`BidDocumentFilename`). |
| **S13** late flags change after the fact | The deadline changes only in draft and open (409 `bid_call_not_open`; section 3.2). |
| **S14** an awarded call can't be deleted | `bid.delete_call` with c30: platform admins may delete an awarded call (session only, audited; section 3.2). |
| **S15** the report at the maximum, Markdown not escaped | Must-have counts plus the failing items; escaping; tested at the maximum (section 13). |
| **S16** deleting the last file leaves "met" | A must-have losing its last file is `missing` again, a person's met included; not met kept (section 5.3). |
| **C1** `document_type_mismatch` | Dropped: the request's Content-Type is ignored; CSV vs TXT by the given name, text by the bytes (section 6.1). |
| **C2** cancelling inside the status route | `cancel_bid_call` (POST `…/cancellation`, `bid.decide`, session only); `BidCallStatusChange` takes open and assessing only (34 operations). |
| **C3** small duplicates | One writer of `assessment_due_at` (`set_bid_assessors`); no currency lock (a label); `BidComparisonRow.price_hidden` and `BidCallPermissions.can_export` dropped; `BidTemplate.is_default` dropped. |
| **C4** small inconsistencies | `mean` 2 decimals; `contact_email` 254 in the model too; the models' "human or AI" lock wording fixed; `require_unique_lower` named for the call copy (section 4.1). |
| **C5** own assessment needs `evaluate` | `bid.view_own_assessment` (`read`) for `get_my_bid_assessment`. |
| **C6** "Assess all" never starts above 20 bids | Starts what fits, the rest `skipped` (`AiRunBatch.skipped`); 429 only when none fits. |
| **C7** the assessor queue | `Bid.my_sections` on every bid (moved from `BidDetail`); `ranking_hidden` (M2). |
| **C8** quote checks prove presence only; P2's AI pre-check | "Found in the document"; quotes at least 20 characters; an AI `not_met` also suggests rejection (`reject_suggested`); **lead**: the call's AI assessor runs automatically once per bid (section 9.1), with a 5-minute quiet period after uploads (lead default, to confirm). |
| **C9** range reads | `bid_document_contents.data` `SET STORAGE EXTERNAL` (migration 0016). |
| **C10** small oracles | Bid writes don't bump the idea's activity; the call-level rule is checked before a bid is looked up (section 2.1). |
| **C11** reinstating erases the reason | The last rejection stays (`reinstated_at`, `reinstated_by`; CHECKs `rejected_has_rejection`, `reinstated_after_rejection`). |
| **C12** the demo's walkthrough | Walk the comparison as kenji or dave; alice's is fully hidden (section 17). |
| Platform requests | Worker memory 1 GiB; the upload route's body size and timeout only (section 19). |

## 21. Changes after the contract

Builders record additive changes here (date, owner, what and why).

- **2026-10-13, backend (core):** `bid_call_changed` joins `ACTIVITY_TYPES`
  (`app/schemas/activity.py`), as section 12 planned.
- **2026-10-13, backend (documents and AI):** the three bid tools join `MCP_TOOLS` and
  their bullet `MCP_INSTRUCTIONS` (section 10, as planned); `normalise_quote_text` is
  `" ".join(text.split())` (the same result for every code point, about 4x faster). No
  field, type or route changed.
- **2026-10-13, integration (QA P10-QA-F1):** `BidAiAssessmentList.can_include` is false
  while the principal owes a section of the bid, as well as after the award: the inclusion
  PUT is 404 then (section 9.4), so the switch isn't offered. Description only; the field
  is unchanged.
- **2026-10-13, integration (QA P10-QA-N3):** `BidAiFindingView.must_have_id` (additive,
  required): which must-have a finding is about, in `BidAiAssessment.findings` and
  `BidMustHaveState.ai_findings` alike.
- **2026-10-13, integration (QA P10-QA-N2):** 422 `assessor_not_eligible` names the
  person by display name ("That person" for an unknown id), never by id:
  `errors[0].msg` is "<name> can't assess bids on this idea" (what the SPA shows),
  `detail` adds why. Wording only.
- **2026-10-13, integration (QA P10-QA-V1):** the evaluation report's ranking table no
  longer carries the section scores: a "Section scores" section follows "Ranking", at most
  four sections a table, so A4 portrait holds every column (section 13's contents are
  unchanged).
