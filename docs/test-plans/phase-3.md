# Test plan: Phase 3 (email and notifications)

Owner: qa. Source of truth for behaviour: [SPEC.md](../../SPEC.md) sections 6 and 13,
[contract-phase3.md](../api/contract-phase3.md) (business rules §3, error codes §4),
[role-matrix.md](../role-matrix.md) §3 (blind evaluation: rules 1 and 8 cover emails and
in-app notifications) and [ADR 0003](../adr/0003-background-jobs-procrastinate-and-email-outbox.md)
(the outbox, amended). Each row has an ID used in the test names, so a failing test
points back here. The Phase 1 and 2 plans ([phase-1.md](phase-1.md),
[phase-2.md](phase-2.md)) still apply; their suites run in both e2e modes.

## Acceptance criterion

> With Mailpit, assigning an evaluator sends a branded email whose link opens the
> evaluate sheet; stopping Mailpit then restarting it delivers queued mail.
> (SPEC section 13, Phase 3; contract-phase3 §3.14)

It is tested at two levels, each adding something the other can't:

| Level | Test | Mail | What it adds |
|---|---|---|---|
| Browser, real stack | `e2e/tests/email-acceptance.spec.ts` (AC3-01, AC3-02) | the stack's Mailpit container, the running `soundings worker` | The owner invites in the browser; the email is read back from Mailpit (subject with the due date, HTML and text parts, `List-Unsubscribe` headers, the button's link); the evaluator opens the link **signed out**, signs in on the login page and lands on the evaluate sheet of that idea. Then Mailpit is **really stopped**: the invitation stays queued with growing attempts and "connection refused" (shown on Admin → Email), and after `docker start` the worker's own backoff delivers it, **once**, in real time (about 1.5 minutes). |
| HTTP API + worker code | `backend/tests/acceptance/test_phase3_acceptance.py` (AC3-API-*) | a real Mailpit (testcontainer, or CI's service) | Everything through the HTTP API; procrastinate runs the job the invitation deferred **in the same transaction**; the real `SmtpTransport` (aiosmtplib) talks to Mailpit; the MIME structure, Message-ID and headers checked on the raw message; the outage driven by a clock moved past each backoff (exact backoff values, the retry job's `scheduled_at`, duplicate jobs and the sweep sending nothing more); the hourly schedule's reminder and digests delivered through Mailpit. Runs in `make check-backend` (about 10 s). |

The rules behind it are unit-tested by backend in `backend/tests/notifications/` (about
210 tests, tests first): the right level for fan-out recipients, preference resolution,
digests, reminder scheduling, outbox atomicity, retries, crashes and blind safety. The
tables below map each rule to its tests; the e2e suite covers what only a browser, a
real worker and a real SMTP server can show.

## How to run

| What | Command | Needs |
|---|---|---|
| API acceptance (part of `make check-backend`) | `cd backend && uv run pytest tests/acceptance/test_phase3_acceptance.py` | Docker (Postgres and Mailpit testcontainers), or `SOUNDINGS_TEST_MAILPIT_SMTP=host:port` + `SOUNDINGS_TEST_MAILPIT_URL` (CI); `SOUNDINGS_TEST_MAILPIT=0` skips |
| E2E (Phase 1–3), dev login | `npm --prefix e2e test` | Docker (Postgres, Mailpit), `uv`, Node 22, Chromium |
| E2E with SSO | `E2E_SSO=1 npm --prefix e2e test` | + Keycloak 26 |
| E2E without SMTP (banner, in-app only) | `E2E_SMTP=0 npm --prefix e2e test` | the email specs skip; PR-05 and AE-04 run |
| Only the SMTP-outage specs | `npx --prefix e2e playwright test --project=smtp-outage --no-deps` | a Mailpit container the run may stop |
| Screenshots | `npm --prefix e2e run screenshots:phase3` → `docs/screenshots/phase-3/` | a run with SMTP, then one with `E2E_SMTP=0` (`@no-smtp`) |

**The stack** (`e2e/scripts/start-stack.sh`, platform's): the API, **`soundings worker`**
and **Mailpit** `<E2E_PREFIX>mailpit` (SMTP `127.0.0.1:1125`, web and API
`http://localhost:8125`, emptied on every start; its messages survive `docker stop` /
`start`), instance time zone `Europe/London` (`E2E_TIMEZONE`). `E2E_SMTP=0` runs without
SMTP. Against a given app (`E2E_BASE_URL`, CI's `make demo`) set `E2E_MAILPIT_URL` and,
to allow the outage specs, `E2E_MAILPIT_CONTAINER`. QA ran it with `E2E_PREFIX=p3-qa-`.

**The SMTP-outage specs** (AC3-02, AE-03) are tagged `@smtp-outage` and run in their own
Playwright project, `smtp-outage`, which depends on `e2e` (so it starts after every other
spec) and has one worker: while Mailpit is stopped no other spec waits for mail. They
skip when the run can't control Mailpit (`canControlMailpit()`: GitLab's services). A
failing spec in `e2e` skips them (Playwright's dependency rule): rerun them with
`--project=smtp-outage --no-deps`.

**Data.** Mailpit's inbox is shared by the whole run and preferences are per person, so
every Phase 3 spec that reads mail or changes preferences works with **new people**
(`tests/support/email.ts` `newPeople`: Nora Quinn, Theo Marsh, Iris Vale, Owen Pike, Lena
Ford, Ravi Shah, created through Alice's admin API with run-unique addresses such as
`theo.k3x9a@example.com`) in a fresh private project (archived afterwards). Mail is
always filtered by recipient and time (`since`). Test emails are sent by a new platform
admin each time (the limit is 5 per admin per 10 minutes). The seeded story is only read
(Alice's inbox, CUST-2 / CUST-7 for the picker, CUST-11 / CUST-14 for blindness).

## Key rules and where they are tested

### Notification types: recipients and exclusions (contract §3.3)

| Type | Recipients | Exclusions | Unit (backend) | E2E / acceptance |
|---|---|---|---|---|
| `owner_assigned` | the new owner | volunteering (actor); inactive, service, break-glass users | `test_fanout.py::test_assigning_an_owner_…`, `test_volunteering_notifies_nobody`, `test_service_accounts_inactive_and_break_glass_…` | NO-02 (inbox), SS emails (real email) |
| `evaluator_invited` | the evaluator (passes `evaluation.submit_own`) | actor; a viewer; access lost; type `off` | `test_invitation_carries_the_due_date_…`, `test_people_who_lost_access_…`, `test_preference_digest_and_off_queue_no_email` | AC3-01, AC3-API-1, NO-01, PR-02, UN-01 |
| `evaluation_reminder` | pending evaluators, on the reminder's own local day | submitted, removed, demoted, closed, overdue; a missed day isn't caught up | `test_reminders.py` (the worked example of §3.7 and every exclusion) | AC3-API-3 (through Mailpit: Bob, who submitted, gets none) |
| `evaluations_complete` | the owner, once, when every evaluator has submitted | the owner as actor | `test_the_last_submission_tells_the_owner_once`, `test_removing_the_last_pending_evaluator_…` | BE-01 (count only, no scores) |
| `status_changed` | owner and evaluators always; watchers | the actor; unwatching stops the watcher's copy only | `test_status_change_reaches_owner_evaluators_and_watchers_…`, `test_unwatching_stops_watcher_status_changes_…` | PR-04 (immediate vs digest), BE-01 |
| `comment` | watchers | the author; people this comment mentions (they get `mention`) | `test_a_comment_notifies_watchers_except_its_author`, `test_mentioned_watchers_get_a_mention_instead_…` | BE-01, AC3-API-3 (digest line) |
| `mention` | mentioned people with a role in the project who can view the idea | the author; no role (internal viewers); no access; on edit, people already mentioned; the 51st email per author-hour is in-app only | `test_mentions.py` | ME-01, ME-02, ME-03, PR-03 |
| public submitter (Phase 4) | template and plumbing only | — | `test_phase_4_submitter_emails_go_to_an_address_…`, `test_templates.py` | SS emails (`submission_*` previews) |

One notification per person per event, dedupe on retries, rollback leaves nothing:
`test_a_repeated_fan_out_inserts_nothing`, `test_a_rolled_back_request_leaves_no_notification_email_or_job`.

### Preferences, digests, reminders

| Rule | Unit | E2E / acceptance |
|---|---|---|
| Defaults: act-on types immediate, status and comments in the digest; a change saves; choosing the default deletes the row | `test_preferences_unsubscribe.py::test_defaults_then_an_override_…` | PR-01 |
| `immediate` → outbox row now; `digest` and `off` → none (in-app always) | `test_preference_digest_and_off_queue_no_email` | PR-02 (off), PR-03 (digest), PR-04 (immediate) |
| Turned off after queueing → cancelled at send time | `test_outbox.py::test_a_type_turned_off_after_queueing_is_cancelled` | UN-01 (the next invitation queues nothing) |
| Digest: once per local day at or after the hour; read, off and no-longer-viewable items left out; a week at most; never twice after cleanup; DST | `test_digest.py` | AC3-API-3 (one digest each for Carol and Alice, through Mailpit; a second run in the hour: nothing) |
| Reminders: on their own day, phrased as a date, never overdue | `test_reminders.py` | AC3-API-3, BE-02 (seeded CUST-14 reminder) |
| Without SMTP: in-app only, the page says so | `test_without_smtp_notifications_are_in_app_only`, `test_preferences_say_when_email_is_off` | PR-05, AE-04 (`E2E_SMTP=0`) |

### Outbox, worker, SMTP down and up

| Rule | Unit | E2E / acceptance |
|---|---|---|
| Row and job written in the event's transaction; rollback drops both | `test_a_rolled_back_request_leaves_no_notification_email_or_job` | AC3-API-1 (row `queued` + job `todo` after the request; the worker sends it) |
| Transient failure → queued, backoff 30 s, 1 min, … (≤ 10 % jitter), next job scheduled then | `test_a_transient_failure_queues_…`, `test_backoff_doubles_…` | AC3-API-2 (exact waits and the job's `scheduled_at`), AC3-02 (real time) |
| SMTP down then up → sent once, same Message-ID | `test_mail_queued_while_smtp_is_down_goes_out_when_it_is_back` | AC3-API-2 (Mailpit stopped or the relay closed), AC3-02 (container stopped) |
| Claim is exclusive; duplicate and sweep jobs send nothing more | `test_two_jobs_for_one_row_send_it_once`, `test_the_sweep_redefers_a_lost_job_once` | AC3-API-1/2 (`not_claimed`), AC3-01/02 (count stays 1) |
| Crash after the server's 250 → resent with the same Message-ID | `test_a_crash_after_sending_resends_with_the_same_message_id` | — |
| Permanent, auth (transient), last attempt, internal error, deadline | `test_outbox.py`, `test_smtp.py` | AE-03 (a test email has one attempt: fails at once) |
| One recipient per email; unusable addresses cancelled | `test_an_unusable_address_is_cancelled_without_smtp`, `test_plain_smtp_sends_to_exactly_one_recipient` | AE-02 (a list → 422) |

### Blind safety (role matrix §3; contract §1, §3.11)

| Rule | Unit | E2E / acceptance |
|---|---|---|
| No email type (HTML and text), inbox item or digest carries score data, recommendations or evaluation comments, for a pending evaluator or the owner | `test_blind_safety.py::test_no_email_or_inbox_item_carries_score_data` | BE-01 (invitation, mention, comment and status emails to a pending evaluator; inbox JSON and page; the owner's "all in" email), BE-02 (seeded CUST-11/14), AC3-API-1/3, AC3-01, ME-01, AE-02 |

### Unsubscribe, admin page, banners

| Rule | Unit | E2E |
|---|---|---|
| Footer link → page that changes nothing until confirmed; masked address | `test_get_describes_the_link_and_changes_nothing` | UN-01 |
| Reuse ("already unsubscribed"), "all" | `test_all_turns_off_everything` | UN-02 |
| Header URL: browser 303 → page; RFC 8058 POST without cookies, idempotent | `test_a_browser_opening_the_header_url_…`, `test_one_click_post_without_cookies_…` | UN-03, AC3-API-1 |
| Forged, tampered, truncated, malformed → 404/422, a calm page | `test_invalid_tokens_and_inactive_users_get_404` | UN-04 |
| Admin page: effective config, credentials never; 403 / 404 for others | `test_admin_email.py` | AE-01 |
| Test email: arrives, no server details or unsubscribe link, audited without the address, rate limit | `test_a_test_email_…`, `test_at_most_five_…` | AE-02 |
| Failed send visible with its reason; Retry; `email_trouble` banner for admins only, clears by itself | `test_retry_requeues_a_recent_failed_email`, `test_email_trouble_is_for_platform_admins_only` | AE-03 (`@smtp-outage`) |
| Queued mail visible on Admin → Email during an outage | `test_stats` | AC3-02 |
| SMTP unset: banner for admins, setup steps, 409 on test email | `test_without_smtp_the_actions_are_409` | AE-04 (`E2E_SMTP=0`) |
| Polling the summary doesn't keep the session alive | `test_inbox.py::test_polling_the_summary_does_not_keep_the_session_alive`, `test_an_idle_session_gets_401_from_the_poll` | — (needs a 12-hour clock) |

## Test cases

### AC3: acceptance in the browser (`email-acceptance.spec.ts`)

| ID | Case |
|---|---|
| AC3-01 | Nora (owner) invites Theo from the idea page with a due date a week out. One email to Theo: subject `[KEY] Please evaluate "<title>" by <Thu 8 Oct>` (the due date in the instance zone), multipart/alternative with text and HTML, table layout and `color-scheme` meta, wordmark, title, key and inviter in both parts, no score data; the button and the text part link to `<links_base_url>/ideas/KEY?evaluate=1`; footer links to preferences and `/unsubscribe?token=`; `List-Unsubscribe` (`/api/v1/unsubscribe?token=`), `List-Unsubscribe-Post: List-Unsubscribe=One-Click`, `Auto-Submitted`. Still exactly one two seconds later. Theo opens the link in a browser that isn't signed in → `/login?next=…` → picks himself → `/ideas/KEY?evaluate=1` with the evaluate sheet open on that idea (key and title in the sheet, the rubric). |
| AC3-02 `@smtp-outage` | Mailpit stopped (API unreachable). Nora invites Iris; the outbox row is `queued` with 2 attempts and "connection refused" (or "connection failed" where the container's name stops resolving: `make demo`); Admin → Email (`?status=queued`) shows Iris Vale, the idea, "2 of 12 attempts", the error and "Next try", never her address. Mailpit started: the invitation arrives (within 2.5 minutes), the row is `sent` after 3 attempts with no error, Iris has exactly one email, and the outbox shows it Sent. |

### AC3-API: acceptance through the API (`test_phase3_acceptance.py`)

| ID | Case |
|---|---|
| AC3-API-1 | Platform admin creates Alice, Bob, Carol and a project through the admin API; Alice invites Bob with a due date. Right after the request: one `queued` row, its `send_email` job `todo`, the notification pointing at it. The worker (procrastinate, `wait=False`) sends it: in Mailpit one message to Bob, exact subject, From "Soundings", To Bob only, `multipart/alternative` (text/plain then text/html), the evaluate link in the button and the text, wordmark, project, title, preferences link, table layout, `color-scheme`, no score words or numbers in the visible text; `Message-Id` = the row's, `Auto-Submitted`, `List-Unsubscribe-Post`, the header token = the footer's. The row is `sent` after 1 attempt, the finished job deleted, a second claim does nothing, still one message. Bob's evaluation is `invited`, editable, with that due date. The header URL redirects a browser (303) to the SPA page; a one-click POST without cookies turns invitations off. |
| AC3-API-2 | Bob's email delivered; SMTP down (Mailpit container stopped, or the relay closed for CI's service). Carol's invitation: attempt 1 → `queued`, "connection refused", next try in 29–35 s, the retry job scheduled for exactly then; Admin → Email: 1 queued, oldest set, Carol by name (no address), the idea, not retryable. Attempt 2 at that time → wait doubles (59–67 s); early duplicates claim nothing. Mailpit back: still nothing for Carol; attempt 3 → sent, same Message-ID; the waiting retry jobs and a sweep send nothing more; Carol has exactly one email, Bob's survived the restart; Admin → Email: 0 queued, 0 failed, 2 sent. |
| AC3-API-3 | Carol takes mentions in the digest; Alice invites Bob and Carol (due in 3 days, 17:00 London); Bob submits (score data now exists) and mentions Carol. At 08:30 local two days before the due date the schedule queues 1 reminder (Carol; not Bob, who submitted) and 2 digests (Carol: the mention; Alice: the comment). Sent through Mailpit: Carol has the invitation, `[KEY] Reminder: your evaluation of "…" is due <day>` with the evaluate link, and `Soundings digest: 1 update on 1 idea` with "@Carol Chen over to you" and a `digest`-scope unsubscribe link; Alice's digest says "Bob Brown commented"; no score data or evaluation comment anywhere; Bob got only his invitation. A second run in the hour: nothing. |

### NO: in-app notifications (`notifications.spec.ts`)

| ID | Case |
|---|---|
| NO-01 | Theo (invited by Alice, mentioned by Nora): the bell says "Notifications, 2 unread"; the popover groups by day ("Today") and shows "Nora Quinn mentioned you: “@Theo Marsh can you check…”" with key and title, and "Alice Anders asked you to evaluate, due …". The invitation opens `?evaluate=1` with the sheet; visiting the idea reads both (bell back to "Notifications", API count 0). The (read) mention opens `#comment-<id>`, the comment focused, the mention a chip "@Theo Marsh". |
| NO-02 | Three items (two invitations, made owner) on the inbox page: day group, sentences with dates (never a countdown), `j` focuses the first row; "Unread (3)" → `?unread=1`; opening one reads that idea only (bell "2 unread"); "Mark all read" → "You’re all caught up", bell clear, API: 0 unread of 3. |
| NO-03 | Theo removed from the project: count 0, the inbox empty ("No notifications yet"), the key nowhere. |
| NO-04 | Alice's seeded inbox through "g i": several items, no score numbers. |

### PR: email preferences (`preferences.spec.ts`)

| ID | Case |
|---|---|
| PR-01 | Defaults (five types Immediate, status changes and comments Daily digest), the digest time "08:00 (Europe/London)"; "New comments" → Off saves (API), "Reset" → default (row gone: mode = default); a choice survives a reload. |
| PR-02 | Invitations Off (through the page): an invitation lands in the inbox (bell "1 unread"), no outbox row, no email. |
| PR-03 | Mentions in the digest: Nora mentions Theo and Iris; Iris (default) gets the email now, Theo gets the inbox item only (no outbox row, no email). |
| PR-04 | Status changes Immediate for Theo (evaluator): `[KEY] "<title>" moved to Shortlisted` with both labels; Nora (owner, default digest): in-app only, no outbox row, no email. |
| PR-05 | `E2E_SMTP=0` only: the page says "Email isn’t set up on this server yet"; choices still save. |

### UN: unsubscribe (`unsubscribe.spec.ts`)

| ID | Case |
|---|---|
| UN-01 | The invitation's footer link (also in the text part; token 16–512 safe characters) in a signed-out browser: "Unsubscribe from “You’re asked to evaluate” emails?", the address masked (`t•••@example.com`, never in full), title "Unsubscribe · Soundings"; nothing changed yet. "Unsubscribe" → "You’re unsubscribed" (focused), only that type off. The next invitation: in the inbox, no outbox row, no email. |
| UN-02 | The same link again: "You’re already unsubscribed", no "all" button; the type's token with `all=true` → 403 `insufficient_scope`, nothing else changed (lead decision L8); the footer's "Unsubscribe from all email" link (HTML and text, a different token) → "Unsubscribe from all Soundings email?" → every type off; "Email preferences" → sign-in with `next=/settings/notifications`. |
| UN-03 | The `List-Unsubscribe` URL (same token as the footer): a browser lands on the SPA page and nothing changes; a mail client's POST (form body `List-Unsubscribe=One-Click`, no cookies, no CSRF) → 200 `{scope: evaluator_invited, unsubscribed: true}`, twice (idempotent), masked hint. |
| UN-04 | Someone else's id with a valid signature, a tampered signature, a truncated token, a malformed one: API GET and POST → 404/422 problem+json; the page says "This unsubscribe link doesn’t work" with "Sign in to your email preferences"; nobody's preferences changed. |

### ME: @mentions (`mentions.spec.ts`)

| ID | Case |
|---|---|
| ME-01 | Nora's picker doesn't offer Owen (no role) or herself, offers Theo; Enter inserts `@[Theo Marsh](user:<id>)`; posted with Ctrl/⌘+Enter, shown as a chip, never a `user:` link. Theo: one `mention` in the inbox; email `[KEY] Nora Quinn mentioned you on "<title>"` with "@Theo Marsh can you check the courier API?" (no token syntax), no score data, link `<base>/ideas/KEY#comment-<id>` (button and text); Owen nothing. Theo opens the link: the comment focused and in view. |
| ME-02 | Private project: mentioning Theo (member), Owen (no access) and herself → only Theo. Edited to add Lena (viewer: has a role) → only Lena hears; Theo still one. Internal project Owen can view but has no role in → nothing. |
| ME-03 | `@[Alice Anders (CEO)](user:<Theo>)` is stored as `@[Theo Marsh](user:<Theo>)`; an unknown id becomes plain `@Ghost`; the excerpt reads "@Theo Marsh and @Ghost approve"; the page shows the chip "@Theo Marsh", never "CEO". |

### AE: Admin → Email and banners (`admin-email.spec.ts`)

| ID | Case |
|---|---|
| AE-01 | The settings in effect: Email in the section row (current), "Email is on", server `host:port`, security label, From, links base URL, "Not set"/"Set (never shown)" for the password (the API has no username or password fields), the digest schedule. Bob: 403 from `/admin/email` and the test route, a plain 404 page, no banner. |
| AE-02 | A new platform admin: a list of addresses → 422; a test email to `ops.<run>@example.com` through the page → "Sent to o•••@example.com"; Mailpit: "Soundings test email" naming the sender and the links URL, no `host:port`, no unsubscribe link or header, no score data, exactly one; audit `email.test_send` `{to_self: false}` without the address; the outbox shows it Sent with the masked address only. |
| AE-03 `@smtp-outage` | Mailpit stopped: the test email fails at once ("The test email failed", "connection refused/failed", the hint "check the host, port…"); the admin sees "Some emails aren’t going out." on My work (`email_trouble` true), Bob doesn't (false, no banner). Mailpit started: the banner's link opens the page on failed email; the row "Failed · 1 of 1 attempt · connection refused"; Retry → queued → delivered once; the row `sent`; audit `email.retry` without the address; `email_trouble` false and the banner gone. |
| AE-04 | `E2E_SMTP=0` only: "Email isn’t set up: people only get in-app notifications." for Alice → "Set up email" with `smtp.host`, the button disabled; POST test → 409 `smtp_not_configured`; `configured: false`; Bob sees no banner. |

### BE: blind safety (`blind-email.spec.ts`)

| ID | Case |
|---|---|
| BE-01 | Theo submits (scores, Go, a private comment): the owner sees an aggregate, Iris (pending) `score_hidden`. Iris (status and comments immediate) gets the invitation, mention, comment and status-change emails: no score words (score, aggregate, recommend…, disagree…) or numbers like 3.8 in subject, visible HTML or text; never the private comment. Her inbox items (API) have no score keys; her inbox page shows the title but no score number, word or comment. Iris submits: Nora's `[KEY] All 2 evaluations are in for "<title>"` carries no score data or either comment; her inbox items no score keys. |
| BE-02 | Seeded: Alice (pending on CUST-11 and CUST-14): her inbox items have no score keys; any CUST-14 reminder in Mailpit has no score data; the inbox page shows no score number. |

### A11Y3 / MO3: accessibility and phones (`a11y-phase3.spec.ts`)

| ID | Case |
|---|---|
| A11Y3 | axe (WCAG 2.2 AA tags), light and dark, no serious or critical violations: the inbox page, the bell's popover, Settings → Notifications, Admin → Email (whole outbox), the mention picker open, the unsubscribe page from a real email, a broken unsubscribe link. |
| MO3-01 | The same screens at 390 px (touch): no sideways scrolling. |
| MO3-02 | At 390 px the bell opens a full-height sheet (axe clean); "See all notifications" goes to `/notifications` and closes it. |

### P12: Phase 1 and 2 suites

Both earlier suites run unchanged in both modes (dev login with break-glass, and
`E2E_SSO=1`) next to the Phase 3 specs, with the worker and Mailpit running. One change:
AU-03 now checks that a non-admin's Settings row lists exactly Account and Notifications
(Phase 3 shows the row to everyone); its old `toHaveCount(0)` passed only because it
looked before the row rendered.

### SS: screenshots (`e2e/screenshots/phase-3.spec.ts`)

`npm --prefix e2e run screenshots:phase3`: 1440 light, 1440 dark and 390 light of
`inbox-open`, `inbox-page`, `notification-preferences` (Carol, with her own choices),
`admin-email-failed-send` (Mailpit stopped for one test email), `admin-email-all`,
`smtp-banner-trouble`, `unsubscribe` (a real link), `unsubscribe-broken-link`,
`mention-picker`; with `E2E_SMTP=0`: `smtp-banner-not-configured`,
`admin-email-not-configured`. Emails in `emails/`: every template from
`soundings email-preview` (sample data, all eleven types) at desktop (1024) and 390 px,
light and dark (the templates have a dark `prefers-color-scheme` style), plus
`mailpit-*`: real emails of the run (invitation, mention, made owner) as Mailpit
received them.

## Known issues

No Phase 3 behaviour failed against the real stack. Found while testing (low severity):

| # | Owner | Issue | Reproduce | Status |
|---|---|---|---|---|
| K3-1 | lead (`app/schemas/admin_users.py`) / backend | Display names and idea titles accept CR/LF. Email is safe: the subject strips them, no extra header, nothing reached the injected address; but the raw text reaches plain-text emails and the UI. | `POST /api/v1/admin/users {"email": "x@example.com", "display_name": "Ravi\r\nBcc: x@evil.test"}` → 201 with the newline kept; same for an idea title, then invite someone: the subject reads `"Line one Bcc: victim@evil.test"`. | Fixed at integration: 422 for control characters (`SingleLine`), SSO names collapsed to one line (`test_control_characters_in_titles_and_display_names_are_a_422`, `test_claims.py::test_display_name`). |
| K3-2 | frontend (`features/admin/settings-frame.tsx`) | At 390 px the Settings section row doesn't bring the current section into view: on Email (or Audit log) the active tab is off-screen to the right, with no hint that the row scrolls. | Phone width, platform admin, `/settings/email`: the row ends at "SSO" (`admin-email-*-390-light.png`). | Fixed: the row scrolls the current section into view. |
| K3-3 | frontend (`features/notifications/email-banner.tsx`) | The "Some emails aren’t going out" banner says "Soundings keeps retrying" also when the cause is a failed email, which is not retried until an admin does (a test email has one attempt). | Stop Mailpit, send a test email, open My work (`smtp-banner-trouble-*.png`). | Fixed: "See why in the outbox and retry any that failed." |
| K3-4 | frontend (`notification-bell.tsx`) | In the bell's popover idea titles are cut to ~20 characters (key, title and time share one line) and a due date can wrap its last word ("due Sat, 3 / Oct"). | `inbox-open-1440-light.png`. | Fixed: a 28rem popover, the time on the sentence line, `text-wrap: pretty`. |
| K3-5 | backend (`app/email/preview.py`) | The `status_changed` preview sample says "Moved to Shortlisted" over a card reading "Status: Evaluating" (sample data only: real emails show the status at send time, e.g. "Status: Rejected"). | `soundings email-preview`, `emails/status_changed-*.png`. | Fixed in the sample. |

Test-infrastructure notes: by Playwright's dependency rule a failure anywhere in `e2e`
skips the two `@smtp-outage` specs (rerun them with `--project=smtp-outage --no-deps`);
GitLab's Mailpit is a service that can't be stopped, so they skip there (GitHub CI stops
`soundings-demo-mailpit`). Where the worker reaches Mailpit by container name
(`make demo`), a stopped Mailpit reads "connection failed" (DNS) rather than "connection
refused"; the specs accept both.

## Screenshot review (2026-10-01)

Every PNG in `docs/screenshots/phase-3/` and `emails/` was opened and read. Calm and
consistent with Phases 1–2 in light, dark and at 390 px: the inbox groups by day with
avatars, keys and one plain sentence; preferences are a clear three-way choice per type
with the default and "Reset"; the unsubscribe page is the login page's card, with the
address masked; Admin → Email shows the settings in effect, "Not set" for credentials,
the failed test email with its reason and Retry, and the setup steps when SMTP is unset;
both admin banners are one quiet line. The emails are a centred 600 px card (table
layout), one blue button, a small footer with the reason, preferences and the
unsubscribe link; dark mode (`prefers-color-scheme`) keeps contrast; at 390 px nothing
overflows; user text is escaped (`<script>` shows as text in the mention sample). Visual
problems: K3-2, K3-3, K3-4 and K3-5 above. No score data appears in any email or inbox
screenshot (the only scores visible are on the idea page and My work, where Alice may
see them).

## Results (2026-10-01)

Real stack (`E2E_PREFIX=p3-qa-`: API on 8100, Postgres 55433, Mailpit 8125/1125, the
worker; Keycloak 8180 in SSO mode):

| Run | Result |
|---|---|
| `npm --prefix e2e test` (dev login, break-glass, SMTP) | 141 passed, 25 skipped (23 `@sso`, PR-05 and AE-04 need `E2E_SMTP=0`), incl. the `smtp-outage` project (AC3-02 about 1.6 minutes, AE-03 10 s) |
| `E2E_SSO=1 npm --prefix e2e test` | 163 passed, 3 skipped (BG-02 needs break-glass, PR-05 and AE-04 need `E2E_SMTP=0`), incl. `smtp-outage` (ME-01's first run raced the optimistic comment id: fixed in the spec) |
| `E2E_SMTP=0` (the whole suite, through the dependency rule) | 127 passed, 39 skipped (the email specs, `@sso`): PR-05 and AE-04 pass |
| `uv run pytest tests/acceptance/test_phase3_acceptance.py` | 3 passed (about 10 s) with a Mailpit testcontainer, and again with `SOUNDINGS_TEST_MAILPIT_SMTP/_URL` (the relay path) |
| `npm --prefix e2e run check` | tsc + prettier clean |
| `npm --prefix e2e run screenshots:phase3` | 34 screens + 56 emails, both runs |

Also checked live: the worker log has outbox ids, types, attempts and error classes, and
no address, token or subject (`grep @example.com` and `token=` on `worker.log`: none);
titles over 80 characters are cut with "…" in subjects; a resolution label is used for
closed ideas ("moved to Rejected").

## Integration (2026-10-01)

Rerun after the integration fixes (K3-1 to K3-5, the plain-text layout, the digest's
hanging bullets, Outlook's fixed-width table and button padding), on the final tree
(`E2E_PREFIX=p3-int-`):

| Run | Result |
|---|---|
| `make -C backend check` | ruff, ruff format, mypy --strict (240 files), pytest 3,646 passed, 1 skipped (empty stub list), 1 deselected (slow) |
| `npm --prefix frontend run check` | tsc, eslint, prettier, vitest 347 passed, build |
| `npm --prefix frontend run test:pw` | 240 passed, 98 skipped (screenshot specs) |
| `npm --prefix e2e test` (dev login, SMTP) | 141 passed, 25 skipped, incl. `smtp-outage` (AC3-02 1.8 min, AE-03 7 s) |
| `E2E_SSO=1 npm --prefix e2e test` | 163 passed, 3 skipped, incl. `smtp-outage` |
| `npm --prefix e2e run check`, `make check-helm`, `make check-scripts` (+ shellcheck from its container), `make gen-api` | clean; no diff |
| `npm --prefix e2e run screenshots:phase3` | 34 screens + 56 emails, read and reviewed; mock screenshots in `mock/` (24) |

New tests: `test_control_characters_in_titles_and_display_names_are_a_422` (K3-1),
`test_claims.py::test_display_name` (one-line SSO names), the text-part layout in
`test_templates.py::test_text_has_the_same_content_with_full_urls`; frontend
`admin-email.spec.ts` "the settings row scrolls … into view" at 390 px (K3-2, fails
without the fix) and the banner copy (K3-3); `notification-text.test.ts` keeps the due
date together (K3-4).

## Final verification (2026-10-01)

On the final tree (`E2E_PREFIX=p3-final-`), after the review fixes and the lead's
decisions (scoped unsubscribe links with a footer "Unsubscribe from all email", L8;
`SingleLine` also rejecting U+2028/U+2029 and bidi controls):

| Run | Result |
|---|---|
| `make -C backend check`, `make -C backend test-slow` | pass (3,746 passed, 1 skipped; slow 1 passed) |
| `npm --prefix frontend run check`, `test:pw` | pass (vitest 358; page tests 241 passed, 98 skipped) |
| `npm --prefix e2e test` (dev login) | 141 passed, 25 skipped, incl. `smtp-outage` (AC3-02 1.8 min) |
| `E2E_SSO=1 npm --prefix e2e test` | 163 passed, 3 skipped, incl. `smtp-outage` |
| k3s with Mailpit in the cluster | `k3s-install SMTP=1`, `k3s-smoke SMTP=1` (outage drill: delivered once 31 s after Mailpit came back), `helm upgrade` with changed values, smoke again (30 s) |
| Screenshots | Phase 1 (42), Phase 2 (39), Phase 3 (33 screens + 56 emails) and the Phase 3 mock set (24) captured again from fresh data; every Phase 3 PNG read |

Changed or added cases: UN-02 (above); `notification-preferences.spec.ts` "the “all
email” link stops every type"; backend `test_a_type_or_digest_link_cannot_turn_off_every_email`,
`test_the_all_link_turns_off_everything`, `test_the_footer_links_turn_off_this_type_or_everything`,
the digest footer in `test_the_digest_email`, c14 `narrow_token` in `test_policy_matrix.py`,
and the input-hygiene cases in `test_input_robustness.py` and `test_claims.py`. The
email footer puts "Unsubscribe from all email" on its own line (at 390 px a third link
left a separator dangling at a line end).
