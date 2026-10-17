# Phase 11 summary: talking to public submitters (unreleased)

**Status:** built on 2026-10-16 and 2026-10-17, reviewed and verified on 2026-10-17, not
released (no version bump: [RELEASE-NOTES.md](../RELEASE-NOTES.md) "Unreleased"; whether and
when to tag is the product owner's call). Waiting for the product owner's review.
**Scope (the product owner's change after 0.3.0, 2026-10-16):** "1) Add an email in the
public form where the link could be emailed, but also used to contact the submitter 2) Make
the text at the top of the public form customisable". Both basics existed since Phase 4 ("oh
both are there!"); the two follow-ups the lead offered were accepted ("Yeah maybe have
both"): **(a)** the team messages the submitter through Soundings, in the project's branding,
without showing their address, audited; **(b)** the tracking link emailed once the address
is confirmed. Decisions: [decisions.md](../decisions.md#phase-11-product-owner-2026-10-16)
(H the product owner's; I the lead's defaults D1-D4; J the contract review; "Phase 11 build
and integration"; "Phase 11 review decisions"). Contract:
[contract-phase11.md](../api/contract-phase11.md) (§20 the changes after it); design:
[ADR 0019](../adr/0019-public-submitter-messages.md); rules: [role matrix](../role-matrix.md)
table G (`public.message_submitter`), c31 (`principal.named_person`), c32; test plan:
[phase-11.md](../test-plans/phase-11.md).

Commits: `0a4c72e`, `bdbfd5d`, `0b51f92` (the contract, after a critic's review), `16ebdb0`,
`6620a12` (backend, frontend, platform), `7854e4c`, `6f976d9` (QA), `9cbb0de`, `257e373`
(integration), `621fac8`, `c2ecc5b` (the review fixes), plus this final verification.

## What was built

| Area | What | Where |
|---|---|---|
| The conversation | One per public submission (`submission_messages`: direction team \| submitter, the team member for team messages, plain text 1-4,000 characters, `emailed`), `ON DELETE CASCADE` from the submission (deleting or rejecting the idea deletes it); U+2028/U+2029 become `\n`; never Markdown or HTML anywhere | `app/public/messages.py`, `app/models/public.py`, migration 0017 |
| Who | `public.message_submitter`: the idea's owner, project and platform admins, in a session only (no key row, no MCP tool, no guest row; c31: never service accounts or the break-glass account); nobody else sees a conversation or that one exists (`IdeaSubmission.messages` null). Works on closed ideas and on ideas held for moderation (c19 doesn't apply), read-only in an archived project. **c32** (review): a member can't volunteer to own an idea sent through the public form (403 `public_idea_owner_needs_admin`) | `app/authz/policy.py`, `rules.py`, `keys.py`, `guest.py`, `app/services/ideas.py` |
| The team's side | The submission panel's **Messages** part (summary, "Message the submitter…" / "Open messages") and the conversation in a side sheet (`?submission=1`, dropped silently for anyone without the rule): oldest at the top, "By email too" / "Tracking page only" per team message, a plain composer (no @mentions, Ctrl/Cmd+Enter, drafts, busy Send), the delivery line and "They won't get an email" when it reaches the tracking page only, refusals in plain words; the review queue's "They replied" | `features/moderation/submitter-messages.tsx`, `message-copy.ts`, `idea-submission.tsx`, `features/idea/idea-page.tsx` |
| The submitter's side | The tracking page's **Messages** ("The <project> team", "You"), **Reply to the team** once the team has written (10 after each team message, 10 a day), "You can send N more replies…", `/track?reply=1#…` lands on the box; **Remove my email address** (stops every email, keeps the link and the conversation) | `app/public/tracking.py`, `features/public/track-messages.tsx`, `track-page.tsx`, `routes/track.tsx` |
| Emails to the submitter | `submission_message` (each team message to a confirmed address: escaped text, signed "The <project> team", Reply to the tracking page, "Replies to this email aren't read", no `Reply-To`) and `submission_link` (the tracking link once, at the first confirmation; no `Reply-To`); the confirmation email stays link-free and gains one sentence; rendered at send time from the submission | `app/public/emails.py`, `app/email/`, `app/templates/email/submission_*.{html,txt}` |
| "The submitter replied" | A notification type (preferences, inbox, immediate email or digest, unsubscribe, Admin → Email) to the idea's owner and everyone who wrote, re-checked against the rule when written and when sent; never the reply's text; subject `[KEY] The submitter replied`; one unread item per recipient and idea, email at most once an hour; none while the idea is held for moderation | `app/notifications/submitter.py`, `fanout.py`, `inbox.py`, `access.py`, `features/notifications/` |
| Limits | Constants: the team 20 a day per submission and 30 an hour per person (429 `too_many_attempts`, the sender's advisory lock), replies 10 a day per submission (429), 10 after each team message (409 `awaiting_team`) and 30 an hour per address, 100 a conversation (409 `conversation_full`); 409 `submitter_erased`, `public_submission_off`, `project_archived` | `app/schemas/public.py`, `app/public/messages.py`, `app/auth/throttle.py` |
| Audit, erasure, retention | `submission.message` per team message (never the text); erasure (admin, "Delete my details", retention) deletes the conversation and all four submitter email types (`SUBMITTER_EMAIL_TYPES`); rule 3 keeps the conversation; rule 4 counts its latest message; rule 5 sweeps what an older release's erasure left | `app/public/erasure.py`, `retention.py`, `app/services/audit.py` |
| Copy | The form's email help, the receipt ("Open the link we've just emailed you"), the confirm page ("We've emailed you a private link to follow your idea."), "Intro text" with its help and a preview (D3) | `features/public/submit-page.tsx`, `receipt.tsx`, `verify-page.tsx`, `public-form-settings.tsx` |
| Platform | `public-smoke.sh` gains the conversation and, with `MAILPIT_URL`, the emails; `k3s-smoke SMTP=1` passes it; GitHub's e2e job runs the public smoke against `make demo`; no Helm value or route (a comment: `smtp.from` should be a no-reply mailbox) | `scripts/public-smoke.sh`, `scripts/k3s-smoke.sh`, `.github/workflows/ci.yml`, `deploy/helm/values.yaml` |
| Demo | CUST-21 (approved from the public form, no owner): priya's message to its sender ("By email too") and Sam's reply an hour later, written through the services without email; priya has one unread "The submitter replied" | `app/seed/runner.py`, `app/seed/public.py`, `dev/README.md` |

Migration **0017** (expand only; head 0017): the table, and `CHECK` constraints that accept
`submitter_replied`, `submission_link` and `submission_message` (anyone who had every type
off gets the new one off). No new setting, Helm value or MCP tool.

## Acceptance evidence

| What | Evidence |
|---|---|
| The whole story through the API, with a real Mailpit | `tests/acceptance/test_phase11_acceptance.py` **AC11-API-1** (the link email on the first confirmation only, never in the confirmation email; a question before approving; the owner's message escaped and signed by the team; the reply; "The submitter replied" to the owner and the writer; nobody else: members, a viewer, a guest researcher, keys of every scope on REST and MCP, an agent in its own run; audit; logs), **AC11-API-2** (an unconfirmed address and every limit), **AC11-API-3** (erasure by "Delete my details" and rule 4, a queued link email never sent, "Remove my email address", rule 3) |
| The rule over principal kinds | `tests/public/test_messages.py` (owner, project admin, platform admin, member, viewer, internal non-member, guest researcher, service account, break-glass, keys of every scope, anonymous × both routes and the panel), `tests/authz/test_policy_matrix.py` (the row, c31, c32), `tests/authz/test_policy_rules.py` (c32), `tests/research/test_guest_access.py`, `tests/authz/test_key_scopes.py`, `tests/mcp/test_submitter_messages.py` (no tool, no text) |
| Where a message could leak | `test_messages.py` `test_a_message_moves_nothing_others_can_see` (idea detail, the feed, search, `last_activity_at`) and the moderation queue's test; `tests/mcp/test_submitter_messages.py` (no tool, `get_idea` / `search_ideas` without the text, the proposal's exports); `tests/public/test_tracking_messages.py` (`test_one_submissions_page_shows_only_its_own_conversation`, unknown and erased tokens, can_reply, 415, 422, the throttles, `test_a_throttled_reply_takes_no_lock`); AC11-API-1 (detail, search, My work and the inbox for six people) |
| The emails | `tests/public/test_submitter_emails.py` (the link email's first confirmation only; no `Reply-To` with `smtp_reply_to` set; escaping; the "-- " line; nobody named; the Reply link `?reply=1`) |
| Notifications | `tests/notifications/test_submitter_replied.py` (recipients re-checked when written and sent, the subject, the reason line, one unread item brought up to date, an email an hour from the last one, digests) |
| Erasure and retention | `tests/public/test_message_erasure.py` (all three paths, rows and outbox, rule 4 with `BATCH = 1` and the re-check under the lock, rule 5) |
| Browser, real stack | `e2e/tests/submitter-messages.spec.ts` SM-01 … SM-09, `a11y-phase11.spec.ts` A11Y11-*, MO11-01, MO11-02, K11-01; earlier specs updated for the 13 preference rows and the tracking page's new keys |
| SPA | `frontend/tests/submitter-messages.spec.ts` (page tests against the mock, axe), vitest (`mocks/phase11.test.ts`, `features/moderation/message-copy.test.ts`, `notification-text.test.ts`, `audit-phrases.test.ts`, `submit-page.test.tsx`) |

**Final verification (2026-10-17):** see [the test plan](../test-plans/phase-11.md#final-verification-2026-10-17)
and the table below.

FINAL_VERIFICATION_TABLE

## Reviews and outcomes

- **The contract review** (a critic, before any builder started; contract §20.1): M1 a false
  privacy promise on the form (fixed: says who sees the address), M2 "Stop these emails"
  couldn't stop message emails (fixed: "Remove my email address"), S1 `Reply-To` (left out of
  the two new emails), S2 rule 5, S3 rule 4 in the candidate query, S4 the inbox's SQL
  re-check, S5 a plain composer, S6 10 replies after each team message; C1-C13 decided in
  decisions.md J (one cap of 100, no `idea_id`, no index of its own, 409 while public
  submission is off, the 409 order, U+2028/U+2029, busy buttons, two windows written down,
  the migration's locks as in 0015/0016, break-glass wording); C14 accepted as it was.
- **QA** (2026-10-17): no defect in the built behaviour; V1 (the seeded message's label),
  V3 (the form said twice who sees the address) and V4 (no receipt-with-address shot) fixed,
  V2 (the seed message is priya's, CUST-21 has no owner) accepted.
- **Integration** (2026-10-17): a run card's Cancel keyed so React never relabels it "Try
  again" (`test:pw`'s cancel test failed under load), no key hint on the tracking page's
  Send reply, tour shots 21-22.
- **Security, abuse and privacy review** (live; no critical or high): **M1** a member could
  read the conversation by volunteering to own the idea (fixed: c32); **L1** the public could
  set off staff email with a subject it wrote (fixed: no title in the reply email); **L2**
  replies to an email reach `smtp.from` (documented: a no-reply mailbox); N1 a "-- " line hid
  the rest of the email, N2 the inbox checked the rule per row, N3 the per-person hourly limit
  could be overshot by one under a race, N4 the reply route locked before its throttle, N5
  project names accepted line breaks (all fixed). Verified live and unchanged: the link email
  on the first confirmation only, no `Reply-To`, escaping, nobody named, the access table,
  keys and break-glass refused, no text in MCP, search or the feed, `last_activity_at`
  unchanged, the limits exact under concurrency (20 of 26 parallel sends, 10 of 15 replies),
  erasure complete, migration 0016 → 0017 on 0.3.0's demo data and back.
- **UX and accessibility review** (axe clean on 18 pages and sheets; focus, keyboard, dark
  mode, 390 px fine): **M1** nothing said plainly that the submitter gets no email (fixed:
  "They won't get an email"); **M2** one inbox row per reply (fixed: one unread item per
  recipient and idea); m1 "Email queued" (now "By email too" / "Tracking page only"), m2 the
  confirm step buried on the receipt, m3 an incomplete link warning, m4 Reply landing at the
  top of the page (`/track?reply=1#…`), m5 the form's email help, m6 the Public form
  settings' line and preview; p1-p9 (the footer's double "stop", the erased sheet's double
  message, the preference sentence and the reply email's reason line, the tracking page
  after removing the address, the panel's order and "The team wrote …", Admin → Email's type
  names, the phone's Details → Messages focus, a warning before the reply limit): all fixed.
- **Final verification** (2026-10-17): FINAL_FIXES

## Known issues

- **Replies only on the tracking page**: the emails have no `Reply-To` and say replies aren't
  read; a submitter who answers by email writes to `smtp.from` (operators: a no-reply
  mailbox, or handle it as personal data).
- **No notification while an idea waits for review**: a moderator who asked a question sees
  the answer as "They replied" in the review queue only.
- **Two narrow windows**, as for status emails since Phase 4 (ADR 0019): an erasure racing an
  email already rendered, and mail link rewriters logging the whole `/track#…` link.
- **Nothing retroactive**: senders who confirmed before this change get no link email.
- **Members who volunteered** as owners of public ideas before c32 keep them (and the
  conversation).
- The seeded message reads "By email too" although the seed queues no email (demo data only).
- KNOWN_FINAL

## Screenshots

Real stack (`npm --prefix e2e run screenshots:phase11`), each at 1440 light, 1440 dark and 390
light, in `docs/screenshots/phase-11/`:

| Screen | Files |
|---|---|
| The submission panel's Messages part (priya, CUST-21) | `submission-panel-messages-*` |
| The conversation sheet with a message being written (priya, CUST-21) | `messages-sheet-composer-*` |
| priya's inbox with "The submitter replied" | `inbox-submitter-replied-*` |
| The sheet for an unconfirmed address ("They won't get an email") | `messages-sheet-tracking-page-only-*` |
| The tracking page with the conversation and the reply box | `tracking-page-messages-*` |
| The receipt of an idea sent with an address | `public-receipt-with-address-*` |
| The confirm page after a first confirmation | `public-verify-link-emailed-*` |
| The tracking link, a team message and "The submitter replied" as Mailpit received them | `emails/submission-link-*`, `emails/submission-message-*`, `emails/submitter-replied-*` (desktop light and dark, 390 light) |

Against the mock (`SCREENSHOTS=1 npx playwright test submitter-messages-screenshots` in
`frontend/`): `docs/screenshots/phase-11/mock/` (`panel-owner`, `panel-member`,
`sheet-emailed`, `sheet-tracking-page-only`, `sheet-erased`, `review-queue-replied`,
`inbox-submitter-replied`, `preferences`, `settings-public-form`, `track-messages`,
`track-messages-unconfirmed`, `track-remove-email`, `verify-link-emailed`). The tour's 21-22
(`docs/screenshots/tour/`): priya's conversation with CUST-21's sender, and a sender's
tracking page. Re-captured with the phase: phase-3 (+ `emails/`: the three new templates and
the changed ones), phase-4 (the form, receipt, tracking page and Public form settings whose
copy changed) and the tour. SCREENSHOT_NOTE
