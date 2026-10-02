# Phase 4 summary: proposals, public submission, branding

**Status:** closed on 2026-10-02, waiting for the product owner's review before Phase 5.
**Scope (SPEC sections 2, 5 screens 5–7, 10 and 13):** once an idea is Shortlisted its
owner writes a proposal from the fixed eight-section template (Summary, Problem,
Solution, Market & users, Cost & effort, Benefits / revenue, Risks, Next steps / the
ask) in a calm Markdown editor with an outline and margin comment threads, and exports
it to PDF or Markdown; anyone can send an idea through a project's public form at
`/{project}/submit` (honeypot, trusted-proxy-aware per-address and per-project limits,
ALTCHA proof of work that works offline, optional email confirmation and moderation),
follows it through a private tracking link with optional status emails, and can erase
their details (UK GDPR); branding (app name, logo, favicon, primary and accent colour,
a bundled font, email footer) globally with per-project overrides, applied at runtime
with a live preview, and to emails, the public form and exported PDFs.
**Acceptance:** anonymous idea → evaluated → shortlisted → exported branded proposal.
Met: see [Acceptance evidence](#acceptance-evidence).

Commits: `5c324ee` (contract), `c2ebae1`, `7d95f53` (build and integration), `f738a07`
(security and UX review fixes), plus this close-out (lead decisions on the UX review,
final verification, k3s, docs).

## What was built

| Area | What | Where |
|---|---|---|
| Contract | 34 operations (proposals, sections, threads and exports; the public form, challenge, submission, tracking, updates, resend, erase, confirm; public-form settings, the moderation queue, approve, reject, the submission panel and admin erasure; global and project branding, uploads and served images), migrations 0007–0009, four audit actions, `IdeaDetail.held_for` / `via_public_form`, `TrackedSubmission.reached_team_at` | [contract-phase4.md](../api/contract-phase4.md) (§7 lists every change after the contract), `backend/app/schemas/proposals.py`, `public.py`, `branding.py` |
| Proposals | One Markdown text per fixed section, saved per section with `base_version` (409 `proposal_conflict` with the current text), autosave, margin threads that resolve and reopen; the editor is one auto-growing textarea per section with Write / Preview, a toolbar, the outline (`j` / `k`), a jump list and a comments sheet on phones; focus follows every action | `app/proposals/`, `features/proposal/`, `features/idea/proposal-tab.tsx` |
| Exports | Markdown (front matter, details, sections, headings demoted through the parser) and a branded A4 PDF (cover with logo or wordmark, contents on the cover when short, running header, "Page X of Y", PDF metadata, the aggregate line only for people who may see scores) rendered by WeasyPrint in a warm `spawn`ed child with a 20 s limit, a layout budget of 5,000 boxes, a memory cap and a local-only fetcher (bundled fonts and the `data:` logo only); Markdown is sanitised exactly as the SPA renders it | `app/proposals/document.py`, `markdown.py`, `pdf.py`, `pdf_child.py`, `fonts.py`, `app/templates/pdf/proposal.html`, [ADR 0011](../adr/0011-ubuntu-runtime-image-and-weasyprint.md) |
| Public form | `/{slug}/submit` with an intro, privacy notice and the project's branding; JSON-only writes (415), the per-address form throttle (120/min), ALTCHA bound to the form with replay protection, per-address (10/h, trusted proxies, IPv6 per /64) and per-project (100/h, in the database) limits, the honeypot checked last; receipt with the private link | `app/public/submit.py`, `forms.py`, `app/auth/public_form.py`, `altcha.py`, `throttle.py`, `features/public/` |
| Holds and moderation | `ideas.held_for`: ideas waiting for confirmation or moderation are in no list, count, search, My work, inbox or notification for anyone (`listed_ideas`); admins approve or reject in the queue (Undo), see "Review n" in the sidebar and "Waiting for review" in My work; writes on a held idea are 409 (c19) | `app/authz/`, `app/services/moderation.py`, `features/moderation/`, `features/work/waiting-for-review.tsx` |
| Tracking, confirmation, erasure | `/track#<token>` (hashed and sealed token): the title and summary as sent, the status in plain words, Sent → With the team (dated) → status changes, email updates on or off, resend, "Delete my details"; `/<slug>/verify#<token>` confirms only on a click (signed token, 3 days); submitter emails through the Phase 3 outbox in the project's branding (fixed-text confirmation without a tracking link, status emails with "Stop these emails"); admin erasure and retention (3 days unconfirmed, 180 days after a closed idea's last activity) | `app/public/tracking.py`, `emails.py`, `erasure.py`, `retention.py`, `app/auth/submission_tokens.py`, `features/public/track-page.tsx`, `verify-page.tsx` |
| Branding | Global profile and per-project overrides resolved field by field (cached 5 s per process; a project with its own logo and no app name is named after itself); hex colours and four bundled fonts only; PNG (re-encoded) or allow-listed SVG (re-serialised) logos and favicons stored in PostgreSQL and served sandboxed and immutable; applied through CSS variables at runtime, live previews of the app, public form and the real email layout | `app/services/branding.py`, `brand_assets.py`, `app/api/v1/branding.py`, `features/branding/`, `lib/branding.ts`, [ADR 0012](../adr/0012-branding-and-uploaded-images.md) |
| Platform | Runtime image on Ubuntu 24.04 with Ubuntu's Python 3.12, Pango and HarfBuzz (507 MB; setuid bits stripped); Helm values for the public form, ALTCHA, limits and uploads, an optional edge rate limit Ingress, API memory 1Gi; `make public-smoke` (also in `k3s-smoke`) | `Dockerfile`, `deploy/helm/`, `scripts/public-smoke.sh` |
| Tests | Backend 4,917 (765 in the Phase 4 modules: public, proposals, moderation, branding, the API acceptance, schemas and settings; tests first for anti-abuse, holds, tokens, erasure, permissions and export safety), frontend 468 unit + 298 page tests, e2e 198 (dev login) / 220 (SSO) against the real stack with the worker, Mailpit and the PDF renderer | `backend/tests/`, `frontend/`, `e2e/tests/` |
| Docs | Contract, ERD (0007–0009), role matrix (c8, c9, c12, c19), ADR 0011 and 0012, decisions, user guide (proposals, public form and tracking, moderation, erasure, branding), operator guide (image and fonts, public submission exposure and limits behind proxies, branding and uploads, PDF memory), test plan | `docs/` |

## Acceptance evidence

All run on 2026-10-02 in the final verification, on the working tree that was committed.

| Criterion | Evidence (test names) |
|---|---|
| **Anonymous idea → evaluated → shortlisted → exported branded proposal**, in the browser | `e2e/tests/public-acceptance.spec.ts` AC4-01 (`@serial`): global branding saved with a live preview; a signed-out visitor on a phone viewport sends the idea while the SPA's ALTCHA worker solves the real proof of work; the fixed-text confirmation email from Mailpit and the Confirm click on `/<slug>/verify`; Approve from the queue; three blind evaluations; Shortlisted (status email, tracking page); Start proposal, sections typed, a margin comment resolved; **Export → PDF and Markdown downloaded and inspected** (metadata, the project's colour, IBM Plex Sans embedded, the logo, page numbers, the aggregate line); a pending evaluator's exports without score; admin erasure kills the tracking link |
| The same through the HTTP API, the real worker, Mailpit and the PDF child | `backend/tests/acceptance/test_phase4_acceptance.py::test_an_anonymous_idea_becomes_an_exported_branded_proposal` (Python `altcha` solves the challenge; procrastinate sends through a Mailpit testcontainer; WeasyPrint renders, read back with pypdf; no token, address, name or idea text in any log record) |
| The same on Kubernetes, through the ingress | k3s: `make k3s-smoke SMTP=1` runs `scripts/public-smoke.sh` (anonymous form, branding, served logo headers, 404 and 415; a real ALTCHA submission, replay refused, tracking, approve, shortlist, proposal, PDF and Markdown export, a 5,000-item PDF bounded) — see [Checks](#checks-final-verification-2026-10-02) |
| Anti-abuse: honeypot, rate limits, ALTCHA replay and expiry, JSON only (tests first) | `tests/public/test_submit.py` (`::test_a_filled_honeypot_gets_a_lookalike_receipt_and_keeps_nothing`, `::test_the_eleventh_attempt_from_one_address_in_an_hour_is_refused`, `::test_a_spoofed_forwarded_for_from_an_untrusted_peer_is_ignored`, `::test_ipv6_clients_count_per_64`, `::test_the_per_project_limit_holds_across_replicas`, `::test_form_lookups_are_throttled_per_address_before_the_form_is_loaded`, `::test_public_writes_must_be_json`), `test_altcha.py` (`::test_a_solved_challenge_is_accepted_once`, `::test_an_expired_challenge_is_refused`, `::test_a_challenge_for_another_form_is_refused`, `::test_concurrent_replays_accept_one`, `::test_the_library_alone_would_accept_a_replay`); e2e PA-01…06 |
| Email verification and the confirmation limit | `test_tracking.py::test_confirming_releases_an_idea_held_for_it`, `::test_invalid_confirmation_tokens_are_404`, `::test_a_confirmation_link_is_spent_when_the_details_are_erased`, `::test_the_per_address_limit_counts_sub_addresses_and_resends_silently`, `::test_erasing_or_rejecting_does_not_reset_the_per_address_limit`, `::test_the_per_address_limit_folds_provider_variants`; `test_emails.py::test_the_confirmation_email_is_fixed_text_with_the_confirmation_link_only`; e2e PT-02, PT-03 |
| Moderation visibility everywhere (lists, search, My work, notifications) | `test_holds.py::test_held_ideas_are_listed_nowhere`, `::test_an_idea_held_for_confirmation_is_404_for_everyone`, `::test_idea_writes_on_an_idea_held_for_moderation_are_409`, `test_tracking.py::test_a_confirmed_idea_reaches_the_team`, `tests/moderation/test_moderation.py`; e2e ML-01…04 |
| Tracking-link secrecy | `test_tokens.py::test_tracking_tokens_are_kept_hashed_and_sealed_for_one_purpose`, `test_tracking.py::test_the_tracking_page_shows_the_submitters_own_words_and_status`, `::test_after_the_team_edits_the_idea_the_page_shows_what_was_sent`, `::test_unknown_and_erased_tokens_are_the_same_404`, `::test_the_token_is_stored_only_hashed_and_sealed`, `tests/test_contract_routes.py` (no token in a path or query); e2e PT-01 (no request URL holds the token) |
| PII erasure and retention | `test_erasure.py::test_an_admin_erases_the_submitters_details`, `::test_only_admins_may_erase`, `::test_unconfirmed_addresses_are_forgotten_after_three_days`, `::test_details_are_erased_180_days_after_a_closed_ideas_last_activity`, `test_tracking.py::test_the_submitter_can_erase_their_details`; e2e PT-02 |
| Proposal permissions and concurrency | `tests/proposals/test_proposals.py` (24, e.g. `::test_only_the_owner_and_admins_start_a_proposal`, `::test_c7_a_proposal_needs_shortlisted_or_proposal`, `::test_two_saves_from_the_same_version_one_wins_one_conflicts`, `::test_a_status_change_waits_for_a_save_in_flight_and_vice_versa`), `test_comments.py`; e2e PR4-01…05 |
| Export safety: no fetches or SSRF, sanitised Markdown, bounded layout | `test_pdf.py::test_the_fetcher_refuses_everything_else`, `::test_the_fetcher_never_uses_urllib`, `::test_a_hostile_proposal_fetches_nothing_and_renders_like_the_spa`, `::test_only_the_bundled_fonts_are_embedded`, `::test_hostile_layouts_render_well_within_the_limit`, `::test_a_render_over_the_limit_is_killed_and_the_next_one_works`, `::test_the_child_memory_limit_is_half_the_containers`, `::test_the_child_gets_no_secrets_from_the_environment`; `test_markdown.py` (raw HTML dropped, unsafe links and images, `::test_a_document_renders_a_bounded_number_of_boxes`); `test_exports.py::test_a_hostile_proposal_exports_safely` |
| Branding inputs validated (CSS injection, SVG XSS) | `tests/branding/test_settings.py::test_values_that_could_reach_css_are_validated`, `test_images.py::test_svgs_outside_the_allow_list_are_refused`, `::test_decompression_bombs_are_refused_before_decoding`, `test_uploads.py::test_an_svg_is_stored_re_serialised_and_sandboxed`, `test_document.py::test_only_validated_hex_colours_reach_the_stylesheet`; e2e BR-03 |
| Final-verification decisions | M1: `test_emails.py::test_the_confirmation_email_is_fixed_text_with_the_confirmation_link_only` (`/<slug>/verify#`); M3: `test_settings.py::test_a_project_logo_without_an_app_name_makes_the_project_name_the_wordmark`, `test_exports.py::test_the_pdf_export_is_a_branded_download` (creator = the project's name), `branding-form.test.ts` "names a project with its own logo and no app name after the project", e2e BR-02; M4 / m4 / m5: `test_markdown.py::test_headings_move_down_one_level_below_the_sections_capped_at_six`, `::test_links_keep_only_http_https_and_mailto_targets`, `::test_a_long_printed_url_wraps_and_is_escaped`, `test_pdf.py::test_a_short_documents_contents_are_on_the_cover`, `::test_headings_and_links_in_a_section_print_as_the_spa_shows_them`, `::test_the_pdf_has_cover_contents_sections_page_numbers_and_metadata`, `test_document.py::test_links_in_a_light_primary_are_darkened_to_read_on_white`, `markdown.test.tsx` "keeps nested section headings one level down…"; p6: `test_emails.py` (Confirm link order, "Stop these emails" in the footer); reached_team_at: `test_tracking.py::test_the_tracking_page_dates_when_the_idea_reached_the_team`, `::test_confirming_releases_an_idea_held_for_it`, the acceptance test, `frontend/tests/public.spec.ts` (dated "With the team") |

### Checks (final verification, 2026-10-02)

| Check | Result |
|---|---|
| `make -C backend check` | pass: ruff, ruff format (318 files), mypy --strict (315 files), pytest 4,917 passed, 1 skipped (the empty stub list), 1 deselected (slow); Postgres, Mailpit and Keycloak testcontainers; 12.6 min |
| `make -C backend test-slow` | pass (10k-idea performance, 47 s) |
| `npm --prefix frontend run check` | pass: tsc, eslint + prettier, vitest 60 files / 468 tests, build (entry chunk 309 kB + React 219 kB, no size warning) |
| `npm --prefix frontend run test:pw` | pass: 298 passed, 151 skipped (screenshot specs), 11.7 min; after the last mock and branding-form changes the public, branding and moderation specs again (39 passed) |
| `npm --prefix e2e test` (dev login, break-glass, worker, Mailpit) | pass: 198 passed, 26 skipped (`@sso`, `E2E_SMTP=0`-only, PA-06) — the `e2e` project 195 in one run, then `serial` (2) and `smtp-outage` (2) rerun after updating AC4-01's stale expectations (below) |
| `E2E_SSO=1 npm --prefix e2e test` | pass: 220 passed, 4 skipped, incl. `serial` and `smtp-outage`, 9.0 min |
| `npm --prefix e2e run check`, `make check-helm`, `make check-scripts`, shellcheck (container) on `scripts/`, `scripts/lib/`, `e2e/scripts/` | pass |
| `make gen-api` | no diff (after the additive `reached_team_at` was generated) |
| `make image` + PDF in the container | `soundings:p4-final`, 507 MB, builds with no workaround (the build renders a PDF); a proposal rendered inside it with a read-only root, `/tmp` tmpfs, no network and no capabilities in 1.2 s, embedding only the bundled fonts |
| k3s | `k3s-up` (`K3S_NAME=p4-final-k3s`), `k3s-mailpit`, `k3s-install SMTP=1` (demo seed Job, Restricted PSS, NetworkPolicy and egress on), `k3s-smoke SMTP=1`: standard smoke, break-glass, **public submission through the ingress** (anonymous form and branding, logo headers and 304, 404 and 415, a real ALTCHA solve, replay 422, tracking, approve, shortlist, proposal, **PDF export 2 s**, Markdown, a 5,000-item PDF bounded at 4 s, "with the team", clean-up), Traefik's edge limit (39 of 80 burst requests 429), email smoke with Mailpit down and up (delivered once, 32 s), `helm test`; `helm upgrade` with changed values (ALTCHA cost 8,000, log level DEBUG; both Deployments rolled, the pods saw the values) → `k3s-smoke SMTP=1` again (the solve used 8,000 iterations; PDF 1 s, 5,000-item PDF 5 s); API and worker logs at DEBUG held no address or token; `k3s-down` |

## Review findings and outcomes

Two reviews ran after the build: a security review (code, OWASP ASVS L2) and a UX and
accessibility review (Linear-grade UX, WCAG 2.2 AA; the real stack at 1440 light and
dark and 390 px with 4× CPU throttling; axe found 0 violations in 47 scans). Backend
fixes were test-first; frontend fixes came with unit and page tests and the e2e specs
they touch. The UX findings on the PDF and email templates had no fixer; the lead
decided them and this close-out applied them.

### Security

| # | Finding | Outcome | Tests |
|---|---|---|---|
| H1 (high) | Ordinary-looking proposal text (5,000 list items, hard breaks, `a*b*` runs, one long word, narrow characters) took 9–25 s and up to 250 MB per section: every export a 503, the child could be OOM-killed | Fixed: a 5,000-box layout budget (a section over it is cut with a note), break opportunities every 32 characters, text in pieces, `overflow-wrap: normal`; the child caps its memory at half the container's and is replaced when it grows; API memory 1Gi. A PDF cache was declined (each PDF names its exporter and date) | `test_markdown.py::test_a_document_renders_a_bounded_number_of_boxes` (10 cases), `::test_long_runs_*`, `::test_long_text_prints_in_pieces*`, `test_pdf.py::test_hostile_layouts_render_well_within_the_limit`, `::test_the_child_memory_limit_is_half_the_containers`, `::test_a_child_that_grew_large_is_replaced_by_a_fresh_one` |
| M1 | Erasure, rejection and retention deleted the outbox rows the per-address confirmation limit counted: submit → erase reset it (5 emails to one address in a minute) | Fixed: `confirmation_email_sends` (keyed hash of the address, migration 0008), pruned only by the 24-hour cleanup | `test_tracking.py::test_erasing_or_rejecting_does_not_reset_the_per_address_limit`, `::test_the_limit_keeps_a_keyed_hash_not_the_address_and_forgets_it_after_a_day` |
| L1 | Provider address variants escaped the limit | Fixed: Gmail dots and `googlemail.com`, Yahoo `-keyword` folded | `test_tracking.py::test_the_per_address_limit_folds_provider_variants`, `test_emails.py::test_canonical_address` |
| L2 | The confirmation email's tracking link showed whoever got it what a stranger typed, on our domain | Fixed: no tracking link in it; `/verify` shows no submitted text | `test_emails.py::test_the_confirmation_email_is_fixed_text_with_the_confirmation_link_only` |
| L3 | Open forms (and private projects' names) could be enumerated at full speed | Fixed: form, challenge and submission share a per-address limit of 120 a minute, counted before the lookup | `test_submit.py::test_form_lookups_are_throttled_per_address_before_the_form_is_loaded` |
| N1–N5 | Setuid binaries in the image; ALTCHA verified on the event loop; SPA and PDF link rules differed; the renderer inherited secrets; a stale comment | Fixed (setuid bits stripped; worker thread; the SPA keeps only http/https/mailto; environment allow-list; comment) | `test_submit.py::test_the_proof_of_work_is_checked_off_the_event_loop`, `markdown.test.tsx`, `test_pdf.py::test_the_child_gets_no_secrets_from_the_environment` |

### UX and accessibility

| # | Finding | Outcome |
|---|---|---|
| M1 | `/verify` showed the global look before Confirm and the project's after: looked like phishing | **Lead decision, fixed:** links are `/<slug>/verify#<token>` (backend), the page loads the project's branding first (frontend); `/verify#` still works |
| M2 | The branding email preview didn't match the real email | Fixed: the real layout, light and dark; submitter emails show "Stop these emails" in the footer |
| M3 | Logo on the form, "Soundings" / "Acme Ideas" in the emails and the PDF header | **Lead decision, fixed:** a project with its own logo and no app name is named after itself everywhere (resolver, settings preview, screen-reader name) |
| M4 | `###` printed as `h5` at body weight in the PDF; flat in the app | **Lead decision, fixed:** one level down, never above h3, in the PDF, Markdown export and editor preview; every level semibold with its own size |
| M5 | Moderation easy to miss | Fixed: "Review n" in the sidebar, "Waiting for review" in My work |
| M6 | Focus dropped to `<body>` after Start, post, Resolve, conflict choices, queue actions, a failed send | Fixed (`lib/focus.ts`) |
| M7 | "Close evaluation" competed with the proposal; the phone's sticky bar covered writing | Fixed |
| m1–m3, m6–m9 | Preview far away at 390; silent bad colour; bare tracking badge; raw Markdown in excerpts; send error far from the button; glaring logo plate; a serif font restyled the dense UI | Fixed (m3 also with the new `reached_team_at` date for "With the team") |
| m4 | A contents page in front of a two-page body; empty sections unannounced | **Lead decision, fixed:** contents on the cover for short proposals, "· Not written yet." in the contents, "n of 8 sections are still empty" in the Export menu |
| m5 | PDF links in the accent colour, no URL | **Lead decision, fixed:** primary colour (darkened to 4.5:1), URL in brackets |
| p1–p5, p8 | Form copy, receipt at 390 (Share), conflict labels, repeated hint, queue polish, verified ALTCHA box | Fixed |
| p6 | Confirm link last in the text part; "Stop these emails" above the button | **Lead decision, fixed** |
| p7 | No proposal in the demo seed | Deferred (below) |

### Final verification (this close-out)

- **Lead decisions on the UX review**, test-first where they touch the API:
  - **M1:** confirmation links are `<base>/<slug>/verify#<token>`
    (`app/public/emails.py` `confirmation_url`); `/verify#` keeps working.
  - **M3:** `app/services/branding.py` names a project with its own logo and no app
    name after itself (resolver and settings `effective`); the project branding form's
    preview, placeholder and caption and the mock do the same.
  - **M4 / m4 / m5:** headings one level down and never above h3 in the PDF, the
    Markdown export and the editor preview (`markdown.tsx`); h3–h6 at 13 / 11.5 /
    10.5 / 9.5 pt, all semibold; links in the darkened primary colour with the URL in
    brackets (three boxes per link in the budget); contents on the cover for short
    proposals (title ≤ 90, sections ≤ 8,000 characters), "· Not written yet." after
    empty sections in the contents.
  - **p6:** the Confirm link right after the first paragraph of the confirmation
    email's text part; "Stop these emails" in the status email's footer
    (`EmailContent.stop_url`, both parts; the branding email preview shows it).
  - **m3:** `TrackedSubmission.reached_team_at` (additive), the
    `public_submissions.reached_team_at` column and migration 0009 (backfilled from the
    approval's audit entry), set at submission, confirmation and approval; the tracking
    page dates "With the team"; `make gen-api` run.
  - **p7** (a seeded proposal) stays deferred; every other backend-owned UX item (M3,
    M4, m4, m5, p6) is applied.
- **Stale tests found by the full runs:** e2e BR-02 (softened dark logo plate), PT-01
  and AC4-01 (`reached_team_at`, "With the team"), AC4-01 (no tracking link in the
  confirmation email since review L2; the backend fixer had asked QA for this), the
  backend acceptance test's key set.
- **Screenshot review:** the project branding page's empty app name said "Soundings",
  though the project's own logo makes its name the wordmark; the placeholder and hint
  now say so (re-captured).
- **Docs:** contract §1, §2, §3.4, §3.5, §3.7, §3.8, §3.10 and a §7 entry; ERD
  (0008, 0009, `confirmation_email_sends`); ADR 0011 (layout budget, renderer memory and
  environment); role matrix (confirmation link); decisions; user guide; operator guide
  (limits, links, project wordmark, PDF memory 1Gi); test plan; frontend README;
  CLAUDE.md.

## Known issues and deferred items

| Item | Why / when |
|---|---|
| No started proposal in the demo seed (UX p7) | Seeding one changes Phase 1–3 test expectations; the screenshot run and the smokes start one through the API. Next time the seed changes. |
| The per-address submission limit is in memory, per API pod | By design (no IP address at rest); the per-project limit in the database is the backstop. |
| `EmailVerified.title` is returned but no longer shown | Contract rule: no removals; drop it in a later contract. |
| `reached_team_at` for ideas released by confirmation before migration 0009 is their submission time | The release wasn't recorded; development data only. |
| One PDF render at a time per API pod, about a second for a cold child | Exports are rare; scale API replicas for more. |
| The mock (MSW) ALTCHA checks replay only | The real widget is tested against the backend (e2e). |
| CJK fonts for PDFs, an add-an-address flow on the tracking page, notifications for margin threads, bulk reject, a privacy-policy link setting | Out of scope (contract §6). |
| The GitLab pipeline was not run in this sandbox | Sandbox only. |

## Simplifications proposed (SPEC section 15, item 3)

Each avoided a settings screen, a dependency or a moving part; all are in
[decisions.md](../decisions.md).

1. **No proposal status:** the idea's status (Shortlisted / Proposal) decides whether
   it is editable.
2. **One native textarea per section** instead of a rich-text editor dependency.
3. **Reject deletes;** genuine but unwanted ideas are approved and closed as Rejected.
4. **Images in PostgreSQL,** PNG and SVG only, no object storage or delete endpoint
   (unused images expire).
5. **Four bundled fonts, hex colours, a plain-text footer:** no free-form CSS anywhere.
6. **Branding per project only where it faces outward;** the signed-in app is one product.
7. **No token tables:** tracking tokens hashed and sealed, confirmation tokens signed.
8. **No address-change flow** on the tracking page: no address → no updates.

Questions for the product owner: should moderation stay on by default for new public
forms? Is "a project with its own logo and no app name is named after itself" the
identity rule you want, or should projects always name themselves in emails?

## Screenshot index

Real app, freshly seeded demo data, the real worker, Mailpit and PDF renderer (`npm
--prefix e2e run screenshots:phase4`); 1440 × 900 light and dark, 390 × 844 light. Every
PNG was read; after the last fix (the project branding page's app-name placeholder) the
set was captured again and the changed screens read again. Phases 1–3 were re-captured
too (`screenshots`, `screenshots:phase2`, `screenshots:phase3`, which also renders both
submitter email templates from `soundings email-preview` in `phase-3/emails/`); no stale
files remained. The frontend's mock set is in [`mock/`](../screenshots/phase-4/mock/)
(53, refreshed, including the proposal editor's).

| Screen | Light | Dark | Phone |
|---|---|---|---|
| Public form (Customer Innovation's branding, typed, verified) | [1440](../screenshots/phase-4/public-submit-1440-light.png) | [1440](../screenshots/phase-4/public-submit-1440-dark.png) | [390](../screenshots/phase-4/public-submit-390-light.png) |
| Receipt with the private link | [1440](../screenshots/phase-4/public-success-1440-light.png) | [1440](../screenshots/phase-4/public-success-1440-dark.png) | [390](../screenshots/phase-4/public-success-390-light.png) |
| Tracking page (confirmed, approved, shortlisted; dated history) | [1440](../screenshots/phase-4/public-tracking-1440-light.png) | [1440](../screenshots/phase-4/public-tracking-1440-dark.png) | [390](../screenshots/phase-4/public-tracking-390-light.png) |
| Confirmation page before the click (`/customer-innovation/verify#…`) | [1440](../screenshots/phase-4/public-verify-1440-light.png) | [1440](../screenshots/phase-4/public-verify-1440-dark.png) | [390](../screenshots/phase-4/public-verify-390-light.png) |
| Proposal editor (CUST-6, margin threads) | [1440](../screenshots/phase-4/proposal-editor-1440-light.png) | [1440](../screenshots/phase-4/proposal-editor-1440-dark.png) | [390](../screenshots/phase-4/proposal-editor-390-light.png) |
| Export menu | [1440](../screenshots/phase-4/proposal-export-menu-1440-light.png) | [1440](../screenshots/phase-4/proposal-export-menu-1440-dark.png) | [390](../screenshots/phase-4/proposal-export-menu-390-light.png) |
| Settings → Branding, an unsaved change in the preview | [1440](../screenshots/phase-4/branding-settings-1440-light.png) | [1440](../screenshots/phase-4/branding-settings-1440-dark.png) | [390](../screenshots/phase-4/branding-settings-390-light.png) |
| Project settings → Public form | [1440](../screenshots/phase-4/project-public-form-settings-1440-light.png) | [1440](../screenshots/phase-4/project-public-form-settings-1440-dark.png) | [390](../screenshots/phase-4/project-public-form-settings-390-light.png) |
| Project settings → Branding (own logo: the project's name is the wordmark) | [1440](../screenshots/phase-4/project-branding-settings-1440-light.png) | [1440](../screenshots/phase-4/project-branding-settings-1440-dark.png) | [390](../screenshots/phase-4/project-branding-settings-390-light.png) |
| Review queue | [1440](../screenshots/phase-4/moderation-queue-1440-light.png) | [1440](../screenshots/phase-4/moderation-queue-1440-dark.png) | [390](../screenshots/phase-4/moderation-queue-390-light.png) |
| Board with "2 ideas … waiting for review" and the sidebar's Review count | [1440](../screenshots/phase-4/moderation-board-notice-1440-light.png) | [1440](../screenshots/phase-4/moderation-board-notice-1440-dark.png) | [390](../screenshots/phase-4/moderation-board-notice-390-light.png) |
| An idea waiting for review (admin) | [1440](../screenshots/phase-4/idea-held-for-review-1440-light.png) | [1440](../screenshots/phase-4/idea-held-for-review-1440-dark.png) | [390](../screenshots/phase-4/idea-held-for-review-390-light.png) |

| PDF (CUST-6, the project's branding) | Page |
|---|---|
| Cover with the details and the contents (short proposal) | [1](../screenshots/phase-4/pdf/CUST-6-proposal-page-1.png) |
| Sections, table, running header "Customer Innovation · CUST-6", footer | [2](../screenshots/phase-4/pdf/CUST-6-proposal-page-2.png), [3](../screenshots/phase-4/pdf/CUST-6-proposal-page-3.png) |
| The PDF itself | [CUST-6-proposal.pdf](../screenshots/phase-4/pdf/CUST-6-proposal.pdf) |

| Email (as Mailpit received it) | Desktop light | Desktop dark | 390 light |
|---|---|---|---|
| Confirm your idea for Customer Innovation | [1024](../screenshots/phase-4/emails/mailpit-confirm-your-idea-for-customer-innovation-desktop-light.png) | [1024](../screenshots/phase-4/emails/mailpit-confirm-your-idea-for-customer-innovation-desktop-dark.png) | [390](../screenshots/phase-4/emails/mailpit-confirm-your-idea-for-customer-innovation-390-light.png) |
| Your idea "…" is now Shortlisted | [1024](../screenshots/phase-4/emails/mailpit-your-idea-is-now-shortlisted-desktop-light.png) | [1024](../screenshots/phase-4/emails/mailpit-your-idea-is-now-shortlisted-desktop-dark.png) | [390](../screenshots/phase-4/emails/mailpit-your-idea-is-now-shortlisted-390-light.png) |
