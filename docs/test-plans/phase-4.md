# Test plan: Phase 4 (proposals, public submission, branding)

Owner: qa. Source of truth for behaviour: [SPEC.md](../../SPEC.md) sections 2, 5 (screens
5–7), 10 and 13, [contract-phase4.md](../api/contract-phase4.md) (business rules §3,
error codes §4, minimum tests §3.15, acceptance §3.16), [role-matrix.md](../role-matrix.md)
(row E, c7–c9, c12, c19, §3 blind evaluation) and ADRs
[0011](../adr/0011-ubuntu-runtime-image-and-weasyprint.md) /
[0012](../adr/0012-branding-and-uploaded-images.md). Each row has an ID used in the test
names, so a failing test points back here. The Phase 1–3 plans
([phase-1.md](phase-1.md), [phase-2.md](phase-2.md), [phase-3.md](phase-3.md)) still
apply; their suites run in every mode next to the Phase 4 specs.

## Acceptance criterion

> Anonymous idea → evaluated → shortlisted → exported branded proposal.
> (SPEC section 13, Phase 4; contract-phase4 §3.16)

It is tested at two levels, each adding something the other can't:

| Level | Test | What it adds |
|---|---|---|
| Browser, real stack | `e2e/tests/public-acceptance.spec.ts` (AC4-01, `@serial`) | Alice sets the global branding on Settings → Branding (live preview before Save, the shell after: colour, font, title), turns the project's form on and gives it its own colour in project settings; a visitor on a **phone viewport, signed out**, sends the idea while the SPA's own ALTCHA worker solves the real proof of work; the receipt's private link; the fixed-text confirmation email from **Mailpit** and the Confirm click on `/verify`; a member's empty board, Alice's "1 idea … waiting for review" → queue → Approve (after its Undo toast); three evaluations; the "is now Shortlisted" email and the tracking page (only what was sent, the history); Start proposal (→ Proposal, another email), sections typed in the editor, a margin comment by a member resolved by the owner; **Export → PDF and Markdown downloaded and inspected** (pdf.js text and metadata, the project's colour in the content streams, IBM Plex Sans embedded, the PNG logo, page numbers, the aggregate line); a pending evaluator's exports without score; the admin erases the submitter's details in the idea's panel and the tracking link dies. About 45 s. |
| HTTP API + worker + PDF child | `backend/tests/acceptance/test_phase4_acceptance.py` (AC4-API-1) | The same story through the API only, with the Python `altcha` library solving the challenge as the widget does, procrastinate running the deferred `send_email` jobs through the real SMTP transport into a real Mailpit, and the real WeasyPrint child rendering the PDF, read back with **pypdf** (metadata title/author/creator, page texts, "Page n of N" with the app name and key in the running header, the project's colour on the cover and not the global one, an image XObject for the logo, the embedded font program's own name table saying "IBM Plex Sans"); the replayed solution refused; exact receipt and `PublicProject` bodies; every list, count, search, My work and inbox without the held idea for the platform admin, the project admin and a member; 409 `awaiting_moderation`; the tracking response's exact key set and no internal value in it; erasure's columns, its outbox rows deleted, idempotence, the identical 404, the audit entry without personal data; and **no token, address, name or idea text in any log record** captured during the whole story. About 7 s. Runs in `make check-backend`. |

The rules behind it are unit-tested by their owners (tests first): `backend/tests/public/`
(identity: ALTCHA, throttles, honeypot, holds, tokens, tracking, erasure and retention,
about 100 tests), `backend/tests/proposals/` (backend: about 240, permissions,
concurrency, comments, Markdown, PDF safety and limits), `backend/tests/branding/` and
`backend/tests/moderation/` (backend: images, settings, uploads, cleanup, emails, queue,
form settings), and the SPA's page tests in `frontend/tests/` (MSW). The tables below map
each rule to them; the e2e suite covers what only a browser, the real worker, Mailpit and
the real PDF renderer can show.

## How to run

| What | Command | Needs |
|---|---|---|
| API acceptance (part of `make check-backend`) | `cd backend && uv run pytest tests/acceptance/test_phase4_acceptance.py` | Docker (Postgres, Mailpit testcontainers) or `TEST_DATABASE_URL` + `SOUNDINGS_TEST_MAILPIT_SMTP` / `_URL`; Pango on the host (else it skips, like `tests/proposals/test_pdf.py`) |
| E2E (Phases 1–4), dev login | `npm --prefix e2e test` | Docker (Postgres, Mailpit), `uv`, Node 22, Chromium |
| E2E with SSO | `E2E_SSO=1 npm --prefix e2e test` | + Keycloak 26 |
| E2E without SMTP | `E2E_SMTP=0 npm --prefix e2e test` | the specs that need mail skip |
| Only the Phase 4 specs | `npx --prefix e2e playwright test public- moderation-leaks proposal branding a11y-phase4 --project=e2e --project=serial --no-deps` | |
| The per-address submission limit (PA-06) | `E2E_PUBLIC_PER_IP=5 npx --prefix e2e playwright test public-abuse --grep PA-06` | restarts the API with a low limit (other specs would hit it: run it alone, then restart normally) |
| Screenshots | `npm --prefix e2e run screenshots:phase4` → `docs/screenshots/phase-4/` (+ `pdf/`, `emails/`) | SMTP (Mailpit), fresh demo data |

**Projects.** Phase 4 adds a `serial` Playwright project between `e2e` and `smtp-outage`:
specs tagged `@serial` change what every other spec would see (the **global branding**:
"Acme Ideas" in every title and email), so they run after `e2e`, one at a time, and put
the profile back in `finally` (AC4-01, BR-01). `smtp-outage` now depends on `serial`.

**Client addresses.** Every request of a run comes from 127.0.0.1, which the stack's API
trusts as its proxy (one hop: the app's defaults, now spelled out in
`e2e/scripts/stack-env.sh`). PA-05 and PA-06 therefore act as **clients of their own**
(`X-Forwarded-For` with a random IPv6 /64) and exhaust per-address throttles without
blocking the rest of the run. Against `E2E_BASE_URL` the peer is a container gateway the
app doesn't trust, so PA-05 skips unless `E2E_TRUSTS_FORWARDED=1`. The stack allows
`E2E_PUBLIC_PER_IP` (1000) submissions an hour; challenges are throttled at 30 a minute
per address, so specs fetch one only per submission.

**Data.** Specs that change data create their own projects (`projectWithPublicForm` in
`tests/support/public.ts`: form on, moderated unless said otherwise, an optional branding
override) and visitors without accounts (`Visitor`: no session, no CSRF, JSON bodies;
`solveAltcha` does the PBKDF2 proof of work in Node exactly as the widget does). The
seeded Customer Innovation form (CUST-21 approved, CUST-22/23 waiting, the green
branding with its SVG logo) is only read, except by the screenshots (a fresh seed).
Mail is always filtered by recipient and time. PDFs are read with **pdf.js**
(`pdfjs-dist`, e2e dev dependency) in Node and rendered by it in Chromium for the
screenshots (`tests/support/pdf.ts`); there is no poppler on the machine or in CI.

## Key rules and where they are tested

### Public form and anti-abuse (contract §1, §3.5)

| Rule | Unit (backend) | E2E / acceptance |
|---|---|---|
| Public writes are JSON only: no type, `text/plain`, form, multipart → 415 before anything | `test_submit.py::test_public_writes_must_be_json`, `test_415_comes_before_the_bodys_shape` | PA-04 (submissions and `/track`, nothing stored) |
| Form not available (off, archived, unknown, reserved, instance off) → the same 404 everywhere | `test_an_unavailable_form_is_an_unknown_project`, `test_public_form_settings.py::test_the_instance_switch_keeps_forms_off`, `test_a_reserved_slug_can_not_have_a_form` | PA-03 (identical bodies for project, challenge and submit; the page says "This form isn’t available" without the name) |
| Honeypot checked last, any value, lookalike receipt, nothing kept, no email | `test_a_filled_honeypot_gets_a_lookalike_receipt_and_keeps_nothing`, `…answers_like_a_real_submission`, `…on_a_saturated_project_is_429`, `test_tokens.py::test_any_honeypot_value_counts` | PA-01 (the off-screen `hp_ref` field in a phone browser: receipt, dead link, no idea, no email; 5,000 characters via API; a filled honeypot with a bad proof of work is 422) |
| ALTCHA: once, own form, unexpired, signed, well-formed | `test_altcha.py` (14) | PA-02 (replay, another form's challenge, tampered expiry, malformed: 422 `challenge_failed`; the SPA refetches and retries once on a refused solution), AC4-01, AC4-API-1 |
| Per-address limit, trusted-proxy aware, IPv6 /64 | `test_the_eleventh_attempt_from_one_address_in_an_hour_is_refused`, `test_a_spoofed_forwarded_for_from_an_untrusted_peer_is_ignored`, `test_ipv6_clients_count_per_64` | PA-06 (low-limit stack: 429 + `Retry-After`, another client fine, the page's "You’ve sent several ideas in a short time" keeping the text) |
| Tracking/confirmation throttle 60/min, challenges 30/min | `test_tracking.py::test_link_requests_are_throttled_per_address` | PA-05 (real 429s with `Retry-After`; another address of the same /64 and a prepended address are the same client; other clients unaffected; "Too many requests just now" and "We couldn’t verify this browser · Retry"; both recover about a minute later) |
| Per-project limit across replicas | `test_the_per_project_limit_holds_across_replicas` | — (100 an hour: a backend test) |
| Email required / updates need an address / unknown fields | `test_a_required_address_must_be_given`, `test_updates_need_an_address` | PA-04 (422s; the page focuses the required address field) |
| The form on a phone | — | MO4-02 (fields 44 px tall, the button full width, `inputmode=email`, 16 px text: no zoom on focus), AC4-01 (phone viewport, real taps) |

### Holds and moderation (contract §3.6; role matrix c12, c19)

| Rule | Unit | E2E / acceptance |
|---|---|---|
| Held ideas are in no list, board, search, count, tag list, My work, owned ideas or inbox, for anyone | `test_holds.py::test_held_ideas_are_listed_nowhere` | ML-01 (API for member, viewer and admin: list, board, `idea_count`, search, My work, owned, tags, inbox; the browser's board, list, ⌘K and My work as a member), AC4-01, AC4-API-1 |
| Members 404, admins read-only (only `can_delete`), writes 409 `awaiting_moderation` incl. watch and proposal | `test_an_idea_held_for_moderation_is_404_for_non_admins`, `test_admins_open_…_read_only`, `test_idea_writes_on_an_idea_held_for_moderation_are_409` | ML-01 (member 404 page and API 404 for the idea, activity, submission, proposal; viewer 404), ML-02 (eight writes → 409; the banner with Approve / Reject; no Watch, no comment box) |
| Held for confirmation: 404 for everyone, released by the Confirm click, also after the form is turned off | `test_an_idea_held_for_confirmation_is_404_for_everyone`, `test_confirming_releases_an_idea_held_for_it`, `test_confirming_still_works_after_the_form_is_turned_off` | ML-04 (not in the queue or `awaiting_moderation`, 404 for the admin; the tracking page says what to do; confirmed after the form is off → in the queue) |
| Approve → visible, first in New; reject → deleted, tracking 404 | `test_moderation.py` (8) | ML-02 (approve from the idea page), ML-03 (reject from the queue; the tracking page says "We can’t find this submission"), AC4-01 |

### Tracking, confirmation, submitter email, erasure (contract §3.7–3.9)

| Rule | Unit | E2E / acceptance |
|---|---|---|
| Tracking shows only what was sent, never the team's work | `test_tracking.py::test_after_the_team_edits_the_idea_the_page_shows_what_was_sent` | PT-01 (after edits, tags, owner, evaluation, comment: exact key set, nothing internal in JSON or page), AC4-01, AC4-API-1 |
| Tokens only in fragments and bodies, stored hashed and sealed | `test_tokens.py`, `test_the_token_is_stored_only_hashed_and_sealed`, `test_contract_routes.py` | PT-01 (no request URL carries the token; the fragment stays for bookmarking) |
| Confirmation: fixed-text email, both links, ≤ 3 a day; `/verify` posts only on the click | `test_emails.py::test_the_confirmation_email_is_fixed_text_with_both_links`, `test_the_confirmation_email_can_be_sent_three_times_a_day` | AC4-01, AC4-API-1, PT-02 (resend from the tracking page: a second email, its link confirms), PT-03 (nothing posted on load; a forged token → the expired/invalid page) |
| Status emails only to a confirmed, opted-in address; off stops them | `test_status_emails_go_to_an_opted_in_confirmed_submitter`, `test_turning_updates_off_cancels_…` | PT-02 (none while unconfirmed; "is now Shortlisted" after confirming with "Stop these emails"; none after the switch is off), AC4-01, AC4-API-1 |
| Erasure: admin (idempotent) and submitter (second call 404); link dead; idea and proposal stay; emails deleted; audit without personal data | `test_erasure.py`, `test_the_submitter_can_erase_their_details` | AC4-01 (admin, from the idea panel), PT-02 ("Delete my details" on a phone; audit `reason: submitter`, no actor), AC4-API-1 (columns, outbox rows, audit) |
| Retention (3 days unconfirmed, 180 days closed) | `test_erasure.py` (clock moved) | — (a clock: backend) |

### Proposals (contract §3.1–3.4; role matrix E)

| Rule | Unit | E2E / acceptance |
|---|---|---|
| Start: template in order, Shortlisted → Proposal with event, email | `test_proposals.py::test_starting_…`, `test_submitter_email.py` | AC4-01 (Start proposal button; "is now Proposal" email), AC4-API-1 |
| Who writes, comments, exports; c7 read-only | `test_only_the_owner_and_admins_start_a_proposal`, `test_c7_…`, `test_comments.py::test_viewers_and_outsiders_cannot_comment` | PR4-03 (viewer: rendered Markdown and Export only, API 403s; member: comments, no editor; back to Evaluating: the read-only note, 409 `proposal_not_available`, still exportable; before Shortlisted: "Available once the idea is shortlisted") |
| Concurrency: stale save 409 with `current`; different sections never conflict; text verbatim | `test_two_saves_from_the_same_version_one_wins_one_conflicts`, `test_saves_to_different_sections_never_conflict`, `test_a_save_stores_the_text_verbatim_…` | PR4-01 (two browsers: the conflict prompt with both versions, Keep mine → version 3, Use theirs; two sections at once; indentation and trailing blank lines kept) |
| Margin threads: reply, resolve, reopen by reply, delete own, `not_author` | `test_comments.py` (14) | PR4-02 (Markdown rendered, resolve collapses, a reply reopens, Undo then "Comment deleted", Bob's 403 on Carol's comment), AC4-01 |
| Editor at 390 px | — | PR4-04 (Preview first, jump list, no sideways scroll, comments in a sheet) |
| Exports: aggregate line only with `score.view_aggregate`; Markdown verbatim; PDF branded | `test_exports.py`, `test_document.py`, `test_pdf.py` | AC4-01 (downloads), AC4-API-1, BR-04 (project colour and Source Serif 4 in the PDF) |
| Export safety: no fetch, HTML dropped, images as links, bounded tables, 20 s kill | `test_pdf.py::test_a_hostile_proposal_fetches_nothing_…`, `test_markdown.py`, `test_a_render_over_the_limit_is_killed_…` | — (backend; the e2e PDFs come from ordinary proposals) |
| Moving around the editor scrolls the editor, not the app | — | PR4-05 (K4-1, fixed in integration) |

### Branding and images (contract §3.10–3.11)

| Rule | Unit | E2E / acceptance |
|---|---|---|
| Global branding on the shell, sign-in page, favicon, title; staff email | `test_settings.py::test_a_global_save_applies_at_once_…`, `test_emails.py::test_staff_emails_use_the_global_branding_…` | BR-01 (`@serial`: another user's next load, `/login` signed out, `link[rel=icon]`, the test email's name, colour and footer), AC4-01 |
| Project override only where it faces outward; live preview | `test_a_project_override_inherits_field_by_field` | BR-02 (preview before Save; public form and tracking page in the override; the signed-in app keeps the global colour), AC4-01 |
| Submitter emails and PDFs in the project's branding | `test_emails.py`, `test_exports.py::test_the_pdf_export_is_a_branded_download` | BR-04, AC4-01, AC4-API-1 |
| No CSS injection; hex colours, enum fonts, one-line names | `test_settings.py::test_values_that_could_reach_css_are_validated`, `test_document.py::test_only_validated_hex_colours_reach_the_stylesheet` | BR-03 (422s through the API) |
| SVG allow-list, PNG only, served sandboxed, ETag/304, images of another profile refused | `test_images.py` (16), `test_uploads.py` (11) | BR-02 (served headers, 304; the logo only as `<img>`, no inline SVG), BR-03 (script, onload, external image, DOCTYPE/entity, style `url()`, HTML as PNG → 422 `invalid_image`; another project's image → 422 `invalid_asset`; the page's "That image can’t be used") |

### Accessibility and phones

| ID | Case |
|---|---|
| A11Y4 | axe (WCAG 2.2 AA tags), light and dark, no serious or critical violations: the seeded branded form, the receipt (a real submission), the tracking page, a dead tracking link, the confirm page, the proposal editor with margin threads, the export menu open, a viewer's proposal, the review queue, an idea waiting for review, the public-submission panel, Settings → Branding with its preview, project Public form and Branding settings. |
| MO4-01 | The same 14 screens at 390 px (touch): no sideways scrolling. |
| MO4-02 | The public form with a thumb: field and button sizes, the email keyboard, 16 px text. |

## Test cases

### AC4: acceptance in the browser (`public-acceptance.spec.ts`)

| ID | Case |
|---|---|
| AC4-01 `@serial` | The seven steps of contract §3.16 as described above, with the global profile put back afterwards. |

### AC4-API: acceptance through the API (`test_phase4_acceptance.py`)

| ID | Case |
|---|---|
| AC4-API-1 | Pat (platform admin) uploads a PNG logo and saves "Acme Ideas", violet, IBM Plex Sans, a footer; `GET /branding` and the served logo; Alice's project with a moderated form and a green override; the visitor's `PublicProject` (exact), challenge bound to the form, receipt (exact), replay 422, one submission row; the confirmation email (exact subject, none of title/summary/description/name/"packaging", wordmark, inherited footer, project colour, no `<img>`, both links in HTML and text, the tracking link's token = the receipt's, no `List-Unsubscribe`, `Auto-Submitted`); opening the link changes nothing, the confirm call does; held: the queue (total 1, the name), nothing in any list for Pat, Alice and Olive, member 404, admin flags, member 403 on the queue, 409; approved → New; the owner edits the summary, four evaluators invited, three submit blind; Shortlisted → exactly three emails so far, the status email with only the submitted title and the tracking link and no score data; the tracking body (exact keys, as submitted, history labels, nothing internal); the proposal (template order and titles, Proposal status, all sections saved, a thread on Problem resolved by the owner) and the "is now Proposal" email; Markdown (headers, owner, aggregate line from 3, every section, no comment) and PDF (metadata, cover, sections, page numbers with app name and key, project colour not the global one, logo image, IBM Plex Sans); a pending evaluator's exports without score; erasure (fields, idempotent, the identical 404, idea and proposal kept, the row's columns, outbox rows, audit without personal data, the approval audited, `branding.update` without values); no secret or personal value in any log record. |

### PA: anti-abuse (`public-abuse.spec.ts`)

| ID | Case |
|---|---|
| PA-01 | Honeypot in a phone browser (receipt "The team can see it now", private link tracks nothing, no idea, no email); via the API with 5,000 characters (same receipt shape, `held_for` and `email_sent` as a real one, queue 1); with a bad proof of work → 422. |
| PA-02 | Replayed (twice), another form's, tampered, malformed solutions → 422 `challenge_failed`, queues unchanged; the browser's first send carries a used solution → refused, refetched, sent again: one receipt, two requests, the second with a new solution. |
| PA-03 | Off, archived, unknown and reserved (`settings`): identical 404 documents for project, challenge and submit; the page says "This form isn’t available" without the name. Turning the form off keeps tracking links working. |
| PA-04 | 415 for `text/plain`, form, multipart and no type (submissions and `/track`), nothing stored; 422 `email_required`, updates without an address, an unknown field; the page focuses the required address. |
| PA-05 | Throttles as a client of its own: tracking 429 within 62 requests with `Retry-After` ≤ 60, the same /64 and a prepended address still 429, another /64 and loopback fine; challenges 429 within 32; the tracking page's and the form's messages; both recover within 90 s; then sending works. |
| PA-06 | Per-address submission limit (low-limit stack only): 429 with `Retry-After` after `limit` submissions, the queue holds `limit`, another client fine, the page's message keeps the text. |

### ML: held ideas (`moderation-leaks.spec.ts`)

| ID | Case |
|---|---|
| ML-01 | One visible and one held idea: every API list and count for member, viewer and admin; board, list, ⌘K, My work and member 404s in the browser; 403 on the queue. |
| ML-02 | The admin's read-only page: only `can_delete`, eight writes 409 `awaiting_moderation`, the banner, no Watch or comment box; Approve → first in New for a member, writes work again. |
| ML-03 | Reject from the queue (Undo toast) → 404, "Nothing waiting for review", the tracking link says the submission is gone. |
| ML-04 | Held for confirmation: invisible to the admin (queue, counts, page); the tracking page's instruction; confirmed after the form is turned off → in the queue; still nothing for a member. |

### PT: tracking (`public-tracking.spec.ts`)

| ID | Case |
|---|---|
| PT-01 | After the team edits, tags, assigns, evaluates and comments: the API response's exact keys and values as sent, nothing internal (key, new text, tag, names, comment, evaluation, the submitter's own name); the page likewise, no score number; no request URL holds the token; the fragment survives a reload. |
| PT-02 | Phone: the masked address "s•••@example.com · not confirmed yet"; no status email while unconfirmed; resend → a second confirmation that confirms; "is now Shortlisted" with "Stop these emails"; the switch off → no "is now Proposal" email; "Delete my details" asks, confirms, focuses "Your details are deleted", the link is dead; the admin's panel says "Submitter’s details erased" without the Erase button; audit `submission.erase` with no actor and `reason: submitter`, no address or name. |
| PT-03 | A forged confirmation link: opening `/verify#…` posts nothing; Confirm → one POST and "This link has expired or isn’t valid" pointing to the tracking link; `/verify` without a token says the same. |

### PR4: proposals (`proposal.spec.ts`)

| ID | Case |
|---|---|
| PR4-01 | Bob and Alice edit Problem from version 1: Alice's save → the conflict prompt naming Bob with both versions, nothing saved until she chooses; Keep mine → version 3; Bob's stale edit → Use theirs puts Alice's text in his editor. Two sections at once both save; indentation and trailing blank lines kept. |
| PR4-02 | Carol comments (⌘/Ctrl+Enter; Markdown rendered); Bob replies and resolves (collapsed, `aria-expanded=false`, `resolved_by` Bob); Bob can't delete Carol's comment (403 `not_author`); Carol's reply reopens it; Carol deletes her comment (Undo toast, then "Comment deleted"). |
| PR4-03 | Viewer, member, owner after the move back to Evaluating, and a member before shortlisting (see the table above). |
| PR4-04 | 390 px: Preview first, jump list, no sideways scroll, the comments sheet. |
| PR4-05 | Clicking an outline item scrolls the editor, not the document (K4-1; the `test.fail` mark came off with the fix). |

### BR: branding (`branding.spec.ts`)

| ID | Case |
|---|---|
| BR-01 `@serial` | Global: Teal, Atkinson Hyperlegible, a PNG favicon and a footer saved in the UI; Bob's next load (title, colour, font, favicon), `/login` signed out; the test email's subject, footer and colour, no image. |
| BR-02 | Project: Brick, Source Serif 4, an SVG logo; preview before Save (no App tab); after Save the app keeps the global colour; the public form and tracking page use the override and show the logo only as `<img>`; the served SVG's headers and 304. |
| BR-03 | Hostile SVGs and an HTML "PNG" → 422 `invalid_image`; CSS-injecting colour, a short hex, a hostile font, a two-line name → 422; another project's image → 422 `invalid_asset`; the page's reason. |
| BR-04 | A project's confirmation email in its colour and footer with the global app name, no image or `url(`; its PDF in its colour and Source Serif 4, creator = app name. |

### SS: screenshots (`e2e/screenshots/phase-4.spec.ts`)

`npm --prefix e2e run screenshots:phase4`: 1440 light, 1440 dark and 390 light of
`public-submit` (the seeded Customer Innovation form, typed and verified),
`public-success`, `public-tracking` (a real submission confirmed, approved and
shortlisted), `public-verify`, `proposal-editor` (CUST-6 with margin threads),
`proposal-export-menu`, `branding-settings` (an unsaved change in the live preview),
`project-public-form-settings`, `project-branding-settings`, `moderation-queue`,
`moderation-board-notice`, `idea-held-for-review`; `pdf/CUST-6-proposal-page-1..3.png`
(and the PDF itself) rendered by pdf.js; `emails/mailpit-*`: the confirmation and the
status-change email as Mailpit received them, desktop light and dark and 390 px. The
SPA's mock screenshots are in `mock/` (frontend's).

## Known issues

| # | Owner | Issue | Reproduce | Status |
|---|---|---|---|---|
| K4-1 | frontend (`features/proposal/threads.tsx`) | On the Proposal tab the **document itself scrolls** (1,360 px taller than the viewport at 1440 × 900 with a resolved thread): the thread card's `sr-only` heading ("Thread by … on …") and the resolved thread's `sr-only` count have no positioned ancestor, so they are laid out against the initial containing block far down the page. Clicking an outline item (or `j`/`k`, or `c`) then scrolls the whole app shell: the top bar, sidebar, outline and Export bar move off-screen and a blank grey area fills the lower half. | `/ideas/CUST-6?tab=proposal` after a thread is resolved; `document.documentElement.scrollHeight` ≫ `clientHeight`; click "Next steps / the ask" in the outline → `window.scrollY` 521. Fix: `relative` on the thread `article` and the resolved-thread button (or on the editor's scroll container). PR4-05 (marked `test.fail`). | Fixed (integration): `<main>` in the app shell is `relative`, so every absolutely positioned descendant belongs to the scroller; PR4-05 passes without `test.fail`. |
| K4-2 | frontend (`features/public/public-layout.tsx`, branding previews) and backend (seed logo) | **Dark mode hides a logo's dark text**: the seeded Customer Innovation logo (an SVG wordmark with `#0b2e24` text) is unreadable on the dark public pages, the project branding preview and the logo field's thumbnail. And the header shows the logo **and** the app name side by side ("[Customer Innovation] Soundings"), which reads as two brands; the PDF cover shows the logo alone. | `public-submit-1440-dark.png`, `public-tracking-1440-dark.png`, `project-branding-settings-1440-dark.png`. Suggest: a light plate behind logos in dark mode (simple, works for any upload) and the logo alone when one is set (app name as its alt text); the seed's logo text in a colour readable on both. | Fixed (integration): uploaded logos sit on a light plate in dark mode (`logo-plate` utility: header, previews, thumbnail, sidebar), and a public header with a logo shows it alone (the app name for screen readers only); the public form preview does the same. The seed logo is unchanged (it is now readable everywhere). |
| K4-3 | frontend (`features/branding/`) | Same root cause as K4-1, not yet visible: on Settings → Branding four hidden inputs (Radix radio bubble inputs / file inputs) with no positioned ancestor make the document 1,268 px tall at 900. | `/settings/branding`, `document.documentElement.scrollHeight` 1268. | Fixed (integration): same fix as K4-1. |
| K4-4 | frontend (`features/public/submit-page.tsx`) | On phones the fields are 44 px tall but "Send idea" is 40 px (`size="lg"`). | MO4-02 measures it; `public-submit-390-light.png`. | Fixed (integration): `h-11` below `sm`. |
| K4-5 | frontend (`lib/activity.ts`) | A public idea's activity reads "Someone submitted the idea" (already reported by frontend-public-branding). | `idea-held-for-review-1440-light.png`. | Fixed (integration): "A visitor sent it through the public form" (unit test in `lib/activity.test.ts`). |

Test-infrastructure notes: the `serial` project sits between `e2e` and `smtp-outage`, so
a failure in `e2e` skips both (Playwright's dependency rule; rerun with
`--project=serial --no-deps`). PA-05 needs an app that trusts the runner as its proxy
(the local stack); CI's `make demo` and GitLab services don't, so it skips there unless
`E2E_TRUSTS_FORWARDED=1`.

## Screenshot review (2026-10-02)

Every PNG in `docs/screenshots/phase-4/` (36 screens, 3 PDF pages, 6 emails) was opened
and read. The public pages are calm and on-brand: one centred column, the project's
green on the button and focus rings, IBM Plex Sans, the fixed privacy notice under the
form, "Verified you’re human" as a quiet status line, a receipt that leads with the
private link and Copy; the tracking page shows the status badge and a dated history
without people; at 390 px nothing overflows and the fields are thumb-sized. The proposal
editor reads like a document: the outline with ticks and thread counts, Write/Preview per
section, margin threads beside their section, the sticky "Saved · edited just now" bar
with Export; at 390 px it opens in Preview with a jump list. The branding page's preview
follows unsaved values (plum button, the new name) while the app stays blue; contrast
advice is shown under each colour. The review queue and the held idea's banner are
clear about who can see what. The PDF has a green band, the logo, a metadata table with
the aggregate line, a contents page with page numbers, and the sections with green rules
and a real table; the running header has the app name and key, the footer "Page n of
N". The emails are the Phase 3 card in the project's green with its footer, and the
confirmation email contains nothing the visitor typed. Visual problems: K4-1 (seen while
framing the editor shot), K4-2, K4-4, K4-5 above; and, as nits for backend's PDF
template, table cells print smaller than body text, and the cover names the project
three times (band, logo, metadata). Both nits were fixed in integration: the cover's band
holds no text and table cells print at the body size.

## Results (2026-10-02)

Real stack (`E2E_PREFIX=p4-qa-`: API on 8100, Postgres 55433, Mailpit 8125/1125, the
worker; Keycloak 8180 in SSO mode):

| Run | Result |
|---|---|
| `npm --prefix e2e test` (dev login, break-glass, SMTP) | 197 passed, 26 skipped (23 `@sso`; PR-05 and AE-04 need `E2E_SMTP=0`; PA-06 needs a low limit), incl. `serial` (BR-01, AC4-01 about 45 s) and `smtp-outage`; 8.2 min |
| `E2E_SSO=1 npm --prefix e2e test` | 220 passed, 4 skipped (BG-02, PR-05, AE-04, PA-06), incl. `serial` and `smtp-outage`; 8.9 min |
| `E2E_SMTP=0 npm --prefix e2e test` | 178 passed, 46 skipped (the email specs, `@sso`, AC4-01, ML-04, PT-02, BR-04, MO4-02, PA-06); 5.7 min |
| `E2E_PUBLIC_PER_IP=5 … public-abuse --grep PA-06` | 1 passed |
| `uv run pytest tests/acceptance/` (Phases 1–4) | 8 passed in 27 s with a Mailpit testcontainer; AC4-API-1 alone about 7 s, also against the e2e stack's Mailpit (`SOUNDINGS_TEST_MAILPIT_SMTP/_URL`) |
| `ruff check`, `ruff format --check` (acceptance), `mypy --strict` (314 files) | clean |
| `npm --prefix e2e run check`, shellcheck `e2e/scripts/stack-env.sh` | clean |
| `npm --prefix e2e run screenshots:phase4` | 37 passed: 36 screens, 3 PDF pages (+ the PDF), 6 email renders; every PNG read |

Phase 4 adds 58 e2e tests (`public-acceptance` 1, `public-abuse` 10, `public-tracking` 3,
`moderation-leaks` 4, `proposal` 6, `branding` 4, `a11y-phase4` 30, screenshots aside)
and AC4-API-1. The first full run had two failures in Phase 1's `list.spec.ts` (LF-01,
LF-03/05): the Phase 4 seed adds CUST-21, an approved public idea in New with nobody
invited, so the list says 21 ideas and "Needs evaluators" 6; the expectations were updated
(CUST-22 and CUST-23, held, are rightly in no count). Every other Phase 1–3 spec passed
unchanged in all three modes.

### Integration rerun (2026-10-02, after the K4 fixes)

| Run | Result |
|---|---|
| `make -C backend check` | ruff, ruff format, mypy --strict (313 files), pytest 4,861 passed, 1 skipped (the empty Phase 4 stub list), Keycloak and Mailpit testcontainers included; 11.7 min |
| `npm --prefix frontend run check` / `test:pw` | 446 vitest; page tests 292 passed, 151 skipped (screenshot specs), incl. the new K4-3 check; before the scroll-spy fix one j/k test was flaky under load |
| `npm --prefix e2e test` (dev login, SMTP) | 198 passed, 26 skipped; PR4-05 passes without `test.fail`; BR-02 also checks the logo stands alone and sits on a light plate in dark mode |
| `E2E_SSO=1 npm --prefix e2e test` | 220 passed, 4 skipped |
| `npm --prefix e2e run screenshots:phase4` | 37 passed; every PNG re-read (logo plate and logo-only header in dark mode, the new activity line, the text-less PDF cover band, body-size table cells) |

