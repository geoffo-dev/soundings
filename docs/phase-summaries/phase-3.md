# Phase 3 summary: email and notifications

**Status:** closed on 2026-10-01, waiting for the product owner's review before Phase 4.
**Scope (SPEC sections 6 and 13):** SMTP to any server (host, port, `none` / `starttls` /
`tls`, optional credentials from a Secret, from address and name, optional reply-to and
CA bundle, timeout) configured through Helm values; a read-only admin view with a test
email; a transactional outbox sent by the worker with retries and backoff, failed sends
visible with Retry; branded HTML and plain-text templates with a footer and working
unsubscribe and preferences links; per-user preferences (immediate, daily digest, off)
per notification type; the seven notification types; in-app notifications when SMTP
isn't configured, with an admin banner.
**Acceptance:** with Mailpit, assigning an evaluator sends a branded email whose link
opens the evaluate sheet; stopping Mailpit then restarting it delivers queued mail. Met:
see [Acceptance evidence](#acceptance-evidence).

Commits: `4c2ac82` (contract), `c4480a1`, `c8923e4` (build and integration), `10df240`
(review fixes), `78863b8` (verification in progress), plus this close-out (lead
decisions L8 and input hygiene, final verification, docs).

## What was built

| Area | What | Where |
|---|---|---|
| Contract | 14 new operations (inbox, summary, preferences, unsubscribe, admin email and outbox), `NotificationType`, `EmailType`, `UnsubscribeScope`, two `AuditAction` values, migrations 0005 and 0006 | [contract-phase3.md](../api/contract-phase3.md), `backend/app/schemas/notifications.py`, `admin_email.py`, `frontend/src/api/generated/` |
| Fan-out | One before-commit hook over the request's activity events writes notifications and outbox rows (and their jobs) in the event's transaction, after the request's last write; recipients through the policy (`idea.view`, `evaluation.submit_own`), never the actor, service accounts or break-glass; idempotent by `dedupe_key`; events for more than 500 people go to a `notify_event` job | `app/notifications/fanout.py`, `access.py`, `app/db.py` |
| Outbox and worker | `outbound_email` rows rendered at send time (no bodies stored), claimed with a 5-minute lease, a 4-minute attempt deadline, 12 attempts with capped exponential backoff and jitter (about 5 hours), transient vs permanent SMTP errors, send-time re-checks (out of date, no longer applies, turned off, unusable address), a per-minute sweep (lost jobs, expired leases, crashed workers' jobs), a breaker that pauses sending after 5 connection failures, periodic jobs ahead of sends, a bounded job table | `app/email/outbox.py`, `delivery.py`, `smtp.py`, `tasks.py`, [ADR 0003](../adr/0003-background-jobs-procrastinate-and-email-outbox.md) |
| SMTP | aiosmtplib with `none` / `starttls` / `tls`, certificate and host name always verified (custom CA bundle replaces the trust store for SMTP), one explicit recipient, fixed Message-ID, `List-Unsubscribe` + one-click (RFC 8058), `Auto-Submitted`, quoted-printable parts, RFC 2047 subjects when needed; credentials only in worker pods | `app/email/smtp.py`, `message.py`, `app/config.py`, `deploy/helm/` |
| Templates | Jinja2 HTML (table layout, inline styles, 600 px card, Outlook fallbacks, dark `prefers-color-scheme`, no images or remote content) and plain text for 11 emails (7 types, the digest, the test email, 2 Phase 4 submitter emails); footer with the reason, preferences, "Unsubscribe from <type>" and "Unsubscribe from all email"; `soundings email-preview` | `app/templates/email/`, `app/email/content.py`, `render.py`, `preview.py` |
| Preferences, digests, reminders | Immediate / daily digest / off per type with defaults; one digest a day at the digest hour (instance time zone, DST-safe, a week of items at most); reminders 2 days before and on the due date by default, only on their own day; hourly cleanup | `app/notifications/preferences.py`, `schedule.py` |
| Unsubscribe | Signed tokens (HMAC, HKDF key from the secret key), not stored, no expiry; GET changes nothing, POST is one-click; a link turns off only its own scope (type, digest, or all from the footer's "all email" link) | `app/notifications/unsubscribe.py`, `api/v1/unsubscribe.py`, `features/notifications/unsubscribe-page.tsx` |
| @mentions | `@[Name](user:<id>)` tokens rewritten to current names, at most 20 people, only people with a project role notified, 50 mention emails per author per hour, a picker in the comment box that shows "@Name" with a tint, chips (never links) in comments | `app/notifications/mentions.py`, `features/idea/mention-picker.tsx`, `mention-highlights.tsx`, `lib/mentions.ts` |
| In-app inbox | The bell with an unread count (polled, never keeps the session alive), a popover (phones: a full-height sheet), the inbox page with All / Unread and Mark all read (with Undo), `g i`; items only for ideas the viewer can see now | `app/notifications/inbox.py`, `features/notifications/` |
| Admin → Email | Settings in effect (credentials as set / not set), status callout, outbox counters and list (recipient names, masked addresses, never bodies), Retry and Retry all failed, test email with polling, setup checklist without SMTP; banners for "not set up" and "some emails aren't going out" | `app/email/admin.py`, `api/v1/admin_email.py`, `features/admin/email/`, `features/notifications/email-banner.tsx` |
| Platform | Helm `smtp.*`, `notifications.*`, `timezone` values with schema, egress policy for the worker's SMTP port, NOTES; Mailpit in dev compose, the e2e stack, `make demo`, CI and k3s (`make k3s-mailpit`, `SMTP=1`), `scripts/email-smoke.sh` | `deploy/helm/`, `dev/`, `scripts/`, `e2e/scripts/` |
| Tests | Backend 3,746 (352 in the Phase 3 modules: notifications, the acceptance tests against a real Mailpit, schemas and email settings; tests first), frontend 358 unit + 241 page tests, e2e 141 (dev login) / 163 (SSO) against the real stack with the worker and Mailpit | `backend/tests/notifications/`, `tests/acceptance/test_phase3_acceptance.py`, `frontend/`, `e2e/tests/` |
| Docs | Contract, ERD, role matrix (c14), ADR 0003 amendment, decisions, user guide (bell, inbox, preferences, mentions, unsubscribing, Admin → Email), operator guide (SMTP and providers, security modes, CA bundles, failures and retry, digests and reminders, running without SMTP, worker), test plan | `docs/` |

## Acceptance evidence

All run on 2026-10-01 in the final verification, on the working tree that was committed.

| Criterion | Evidence (test names) |
|---|---|
| **Assigning an evaluator sends a branded email whose link opens the evaluate sheet**, in the browser | `e2e/tests/email-acceptance.spec.ts` AC3-01: Nora invites Theo; one email in Mailpit (subject with the due date, HTML and text, table layout, wordmark, no score data, `List-Unsubscribe` and one-click headers); Theo opens the button's link signed out, signs in and lands on the evaluate sheet of that idea |
| **Stopping Mailpit then restarting it delivers queued mail**, in the browser | AC3-02 `@smtp-outage`: Mailpit container stopped; the invitation stays queued with "connection refused" and growing attempts on Admin → Email (her name, never her address); Mailpit started: delivered once by the worker's own backoff (1.8 min dev login, 1.7 min SSO) |
| The same through the HTTP API and the real worker code | `backend/tests/acceptance/test_phase3_acceptance.py::test_an_invited_evaluator_gets_one_branded_email_with_the_evaluate_link`, `::test_mail_queued_while_smtp_is_down_is_delivered_once_when_it_is_back`, `::test_the_digest_hour_sends_reminders_and_digests_without_score_data` (Mailpit testcontainer) |
| The same on Kubernetes | k3s v1.31, Restricted PSS, NetworkPolicy and egress policies on, Mailpit in the cluster: `make k3s-smoke SMTP=1` (`scripts/email-smoke.sh`): branded email, evaluate link in both parts, `List-Unsubscribe` headers; Mailpit scaled to 0 → queued after 1 attempt, "connection refused"; scaled back → delivered once 31 s later; again after a `helm upgrade` with changed values (30 s) |
| Outbox atomicity, retries and backoff, no loss while SMTP is down, idempotent sending, no duplicate after a crash (tests first) | `tests/notifications/test_outbox.py` (26: `::test_two_jobs_for_one_row_send_it_once`, `::test_a_transient_failure_queues_the_next_attempt_with_backoff`, `::test_backoff_doubles_from_30_seconds_to_an_hour_with_at_most_10_percent_jitter`, `::test_mail_queued_while_smtp_is_down_goes_out_when_it_is_back`, `::test_a_crash_after_sending_resends_with_the_same_message_id`, `::test_the_sweep_redefers_a_lost_job_once`), `test_fanout.py::test_a_rolled_back_request_leaves_no_notification_email_or_job`, `test_worker.py::test_jobs_of_a_crashed_worker_are_finished_as_failed`, `test_breaker.py` (7) |
| Preference resolution, digests, reminders (tests first) | `test_preferences_unsubscribe.py::test_defaults_then_an_override_then_back_to_the_default`, `test_fanout.py::test_preference_digest_and_off_queue_no_email`, `test_digest.py` (12, e.g. `::test_one_digest_per_local_day_at_or_after_the_hour`, `::test_the_digest_hour_follows_daylight_saving_time`), `test_reminders.py` (9, e.g. `::test_the_worked_example`, `::test_a_moved_due_date_follows_the_new_schedule`, `::test_a_missed_day_is_not_caught_up`) |
| Blind safety: no scores in emails or the inbox (tests first) | `test_blind_safety.py::test_no_email_or_inbox_item_carries_score_data`; e2e BE-01, BE-02 (`blind-email.spec.ts`) |
| Recipients and authorisation at send time | `test_fanout.py` (22, e.g. `::test_people_who_lost_access_are_not_notified`, `::test_unwatching_stops_watcher_status_changes_but_not_the_owners`), `test_outbox.py::test_mail_about_an_idea_the_recipient_can_no_longer_view_is_cancelled`, `::test_an_invitation_to_a_removed_or_demoted_evaluator_is_cancelled`, `test_mentions.py::test_a_mention_email_is_cancelled_once_the_recipient_has_no_role` |
| Unsubscribe and preferences links work | `test_preferences_unsubscribe.py` (11, incl. `::test_one_click_post_without_cookies_turns_the_type_off`, `::test_the_all_link_turns_off_everything`, `::test_a_type_or_digest_link_cannot_turn_off_every_email`), `test_outbox.py::test_the_footer_links_turn_off_this_type_or_everything`; e2e UN-01…04, PR-01…04 |
| Without SMTP: in-app only, admin banner | `test_fanout.py::test_without_smtp_notifications_are_in_app_only`, `test_outbox.py::test_nothing_happens_while_smtp_is_not_configured`, `test_inbox.py::test_without_smtp_email_is_unavailable`; e2e with `E2E_SMTP=0` (PR-05, AE-04) in the screenshot run |
| Admin email page, test email, retry | `test_admin_email.py` (18, e.g. `::test_config_shows_the_effective_settings_with_credentials_masked`, `::test_at_most_five_test_emails_per_admin_in_ten_minutes`, `::test_retrying_a_test_email_counts_towards_the_test_email_limit`); e2e AE-01…03 |
| Final-verification decisions | L8: `test_preferences_unsubscribe.py::test_a_type_or_digest_link_cannot_turn_off_every_email`, `::test_the_all_link_turns_off_everything`, `test_outbox.py::test_the_footer_links_turn_off_this_type_or_everything`, `test_digest.py::test_the_digest_email`, `test_policy_matrix.py` (c14 `narrow_token`), frontend `notification-preferences.spec.ts` "the “all email” link stops every type", e2e UN-02; input hygiene: `test_input_robustness.py::test_control_characters_in_titles_and_display_names_are_a_422` (8 cases), `::test_one_line_names_allow_unicode_text_and_bidi_marks`, `::test_has_control_covers_every_listed_bidi_control`, `test_claims.py::test_display_name` |

### Checks (final verification, 2026-10-01)

| Check | Result |
|---|---|
| `make -C backend check` | pass: ruff, ruff format, mypy --strict (244 files), pytest 3,746 passed, 1 skipped (empty stub list), 1 deselected (slow) |
| `make -C backend test-slow` | pass (10k-idea performance, 51 s) |
| `npm --prefix frontend run check` | pass: tsc, eslint + prettier, vitest 48 files / 358 tests, build |
| `npm --prefix frontend run test:pw` | pass: 241 passed, 98 skipped (screenshot specs) |
| `npm --prefix e2e test` (dev login, break-glass, worker, Mailpit) | pass: 141 passed, 25 skipped (`@sso`, `E2E_SMTP=0`-only), incl. the `smtp-outage` project (AC3-02 1.8 min, AE-03 9 s) |
| `E2E_SSO=1 npm --prefix e2e test` | pass: 163 passed, 3 skipped, incl. `smtp-outage` |
| `npm --prefix e2e run check`, `make check-helm`, `make check-scripts` | pass (shellcheck through its container: clean) |
| `make gen-api` | no diff after the L8 contract change was generated |
| k3s | `make image` (sandbox: `RUNTIME_APT_PACKAGES=`), `k3s-up`, `k3s-mailpit`, `k3s-install SMTP=1` (demo seed, Restricted PSS, NetworkPolicy and egress on), `k3s-smoke SMTP=1` (standard smoke, break-glass, email smoke with Mailpit down and up, `helm test`), `helm upgrade` with changed values (digest hour, from name, log level: both Deployments rolled; the next email came from "Soundings Ideas") → `k3s-smoke SMTP=1` again, worker logs at DEBUG without addresses, subjects or tokens, `k3s-down`. The image was built before the last two cosmetic fixes (the email footer's own line for "Unsubscribe from all email", the preferences copy); everything after it ran on the final tree |

## Review findings and outcomes

Two reviews ran after the build: a security review (code, OWASP ASVS L2) and a UX review
(Linear-grade UX, WCAG 2.2 AA). Backend fixes were test-first; frontend fixes came with
unit and page tests and the e2e specs they touch.

### Security

| # | Finding | Outcome | Tests |
|---|---|---|---|
| H1 (high) | Crafted comments made excerpts super-linear: the inbox and `/auth/me` stalled for seconds | Fixed: excerpts read at most 2,000 characters, linear patterns (about 1 ms worst case) | `test_excerpt.py` (`::test_no_comment_makes_an_excerpt_slow`, `::test_a_page_of_crafted_comments_is_fast`) |
| M1 | A backlog of slow sends crowded out the sweep, reminders and digests | Fixed: periodic jobs first; a breaker pauses sending after 5 connection failures without using attempts | `test_breaker.py` (7) |
| M2 | Concurrent comments could exceed the 50-per-hour mention email cap | Fixed: per-author advisory lock | `test_the_mention_email_cap_holds_for_concurrent_comments` |
| L1 | Nested mention tokens kept a chosen label | Fixed on both sides: rewriting until stable; the SPA renders chips only for canonical tokens | `test_nested_tokens_*`, `test_every_token_left_in_a_comment_is_canonical`, `mentions.test.ts` |
| L2 | U+2028 and bidi controls could forge lines in the text part | Fixed: one-line values without C1 or bidi controls; **plus lead decision:** `SingleLine` rejects them on input | `test_values_cannot_start_a_line_in_the_text_part`, `test_bidi_controls_are_removed_from_values`, `test_input_robustness.py` |
| L3 | An encoded word in a title changed how the subject displayed | Fixed: such subjects are encoded as a whole | `test_encoded_words_in_a_subject_are_shown_as_typed` |
| L4 | API pods received SMTP credentials | Fixed: worker pods only; `*_SET` flags for the admin page | `test_api_pods_without_the_credentials_still_show_them_as_set`, `helm template` |
| L5 | An invalid CA bundle was accepted | Fixed: startup fails without a certificate | `test_ca_bundle_must_hold_a_certificate` |
| L6 | Fan-out cost one statement per recipient inside the request | Fixed: constant statements; above 500 people a `notify_event` job | `test_the_fan_out_costs_the_same_statements_for_many_watchers`, `test_a_large_audience_is_notified_by_the_worker` |
| L7 | Jobs of a crashed worker stayed `doing` | Fixed: the sweep fails them after 2 minutes without a heartbeat | `test_jobs_of_a_crashed_worker_are_finished_as_failed` |
| L8 | A type's unsubscribe link could turn off every email (`all=true`) | **Lead decision, fixed:** `all=true` only with an `all`-scoped token, which the footer's new "Unsubscribe from all email" link carries (403 `insufficient_scope` otherwise); no token versioning or expiry (trade-off in decisions.md) | see Acceptance evidence |
| L9 | Retry bypassed the test-email limit | Fixed: retries of test emails count | `test_retrying_a_test_email_counts_*`, `test_retry_all_includes_test_emails_only_within_the_limit` |
| Nits | Cleanup only in the digest hour; unindexed cleanup columns; IP base URLs in Message-IDs; CSS in branding colours; mention role not re-checked at send time | Fixed (migration 0006; hourly cleanup; address literals; hex only; send-time check) | `test_a_run_that_misses_the_digest_hour_still_cleans_up`, `test_message_ids_use_a_domain_or_an_address_literal`, `test_branding_colours_must_be_hex`, `test_a_mention_email_is_cancelled_once_the_recipient_has_no_role` |

### UX and accessibility

| # | Finding | Outcome |
|---|---|---|
| M1 | Retry moved the outbox list and dropped focus | Fixed: the filter stays, focus moves to the row's status, "Queued again" toast |
| M2 | Mark all read lost focus and had no Undo | Fixed: Undo toast (the write waits for it), focus stays on the button |
| M3 | Raw `@[Name](user:…)` tokens in the comment box | Fixed: "@Name" with a tint; the stored text keeps the tokens |
| M4 | The trouble banner landed at the top of the Email page | Fixed: status, outbox, test email, server, schedule; the banner links to `#outbox` |
| m1, m2, m7–m11 | Repeated titles in the inbox, type names, banner dismiss focus, SMTP-off page, attempts noise and "just now", outbox wording, test email feedback | Fixed |
| p1–p3, p9–p11 | Chip padding and self-mention, defaults copy and headings, 390 px sheet, focus back from an idea, "@ to mention" hint, silent evaluate link | Fixed |
| p4 | Dates in emails differ from the app | Rejected: emails can't know the reader's locale |
| p7 | Undo on the "You're unsubscribed" page | Deferred: needs a public re-subscribe endpoint |
| m3–m6, p5, p6, p8 | Not in the fixers' reports (the frontend fixer took the app-screen items; the backend fixer received no UX items) | Not tracked item by item; this verification re-read every app screen and email render and fixed what it found (below) |

The integration before the reviews fixed QA's K3-1 to K3-5 ([test
plan](../test-plans/phase-3.md#known-issues)).

### Final verification (this close-out)

- **Lead decision L8** implemented test-first (backend, policy c14, footer link in HTML
  and text, SPA page, mock, e2e UN-02); the contract change is additive (a documented
  403 on `confirm_unsubscribe`) and recorded in [contract-phase3.md
  §7](../api/contract-phase3.md#7-changes-after-the-contract).
- **Input hygiene:** `SingleLine` rejects U+2028 / U+2029 and bidi controls; SSO names
  drop them. No OpenAPI change.
- **Email footer at 390 px:** with three links the separator dangled at a line end;
  "Unsubscribe from all email" now has its own line.
- **Preferences page copy:** "Every email has links to turn off just that kind of email,
  or all email."
- **Design-system rule:** the bell popover's arbitrary `max-h-[…]` became the theme
  utility `max-h-popover-tall`.
- **Flaky page test:** `my-work.spec.ts` "shows an error with a retry" waited 5 s for an
  error shown after the client's retries; it failed once on a loaded machine and now
  allows 10 s.
- **Screenshot spec:** the preferences heading is "Email notifications" (frontend's
  request).
- Docs: this summary, contract §2, §3.1, §3.5, §3.8–3.10, §4, §5, §7, ERD (migration
  0006), role matrix (c14), decisions, user and operator guides, test plan, CLAUDE.md.

## Known issues and deferred items

| Item | Why / when |
|---|---|
| Undo on the unsubscribe page (UX p7) | Needs a public re-subscribe endpoint; people sign in to their preferences meanwhile. |
| Unsubscribe tokens never expire and have no per-user version | Decided trade-off (decisions.md); rotating the secret key invalidates every link. |
| The worker counts `soundings_emails_*` metrics but serves no metrics port | A worker metrics listener and ServiceMonitor are a small platform follow-up. |
| Mailpit's chaos mode isn't used; GitLab's Mailpit service can't be stopped, so the two outage specs skip there | GitHub CI stops the demo's Mailpit container; the API acceptance test covers the outage everywhere. |
| The breaker is per worker process | Each process pauses on its own; with several workers each probes the server. |
| Events for more than 500 people reach the inbox only when the worker runs `notify_event` | By design (review L6); a stopped worker delays those inbox items as it delays email. |
| No bounce handling, weekly digest, per-user time zones, push for the bell, "mark unread" | Out of scope (contract §6). |
| Image builds here skip the runtime apt packages (no Debian mirror); the GitLab pipeline was not run in this sandbox | Sandbox only. |

## Simplifications proposed (SPEC section 15, item 3)

Each avoided a settings screen or a moving part; all are in [decisions.md](../decisions.md).

1. **SMTP only through Helm values**; the admin page is read-only plus a test email and
   Retry. No SMTP settings screen.
2. **Render at send time; store no bodies.** Authorisation is re-checked anyway, so the
   content follows what the recipient may see then.
3. **No admin cancel:** retry only; the send-time checks cancel what shouldn't go out.
4. **One instance time zone and digest hour** for digests and reminders; reminder days
   an operator setting, no per-user time zones.
5. **Preferences govern email only;** the inbox always gets everything.
6. **No outbox rows without SMTP:** nothing piles up to be sent by surprise later.
7. **Signed, stateless unsubscribe tokens** instead of a token table.
8. **A polled unread count** instead of WebSockets or SSE.

Questions for the product owner: keep "Unsubscribe from all email" as a separate footer
link (the decision behind L8), or only offer "all" through the signed-in preferences?
Should digest and comment defaults stay "Daily digest" for everyone?

## Screenshot index

Real app, freshly seeded demo data, the real worker and Mailpit (`npm --prefix e2e run
screenshots:phase3`: an SMTP run, then `E2E_SMTP=0` for the two "not set up" screens);
1440 × 900 light and dark, 390 × 844 light. Emails: every template from `soundings
email-preview` (sample data) and three real emails from Mailpit, at 1024 and 390 px,
light and dark. Every PNG was read; after the last fixes (footer line, preferences copy)
the whole set was captured again, and every image that changed was read again (the rest
were byte-identical). The frontend's mock set is in
[`mock/`](../screenshots/phase-3/mock/) (24, also refreshed).

| Screen | Light | Dark | Phone |
|---|---|---|---|
| Bell popover (inbox) | [1440](../screenshots/phase-3/inbox-open-1440-light.png) | [1440](../screenshots/phase-3/inbox-open-1440-dark.png) | [390](../screenshots/phase-3/inbox-open-390-light.png) |
| Inbox page | [1440](../screenshots/phase-3/inbox-page-1440-light.png) | [1440](../screenshots/phase-3/inbox-page-1440-dark.png) | [390](../screenshots/phase-3/inbox-page-390-light.png) |
| Settings → Notifications (Carol's choices) | [1440](../screenshots/phase-3/notification-preferences-1440-light.png) | [1440](../screenshots/phase-3/notification-preferences-1440-dark.png) | [390](../screenshots/phase-3/notification-preferences-390-light.png) |
| Admin → Email: a failed test email (Mailpit stopped) | [1440](../screenshots/phase-3/admin-email-failed-send-1440-light.png) | [1440](../screenshots/phase-3/admin-email-failed-send-1440-dark.png) | [390](../screenshots/phase-3/admin-email-failed-send-390-light.png) |
| Admin → Email: status and the whole outbox | [1440](../screenshots/phase-3/admin-email-all-1440-light.png) | [1440](../screenshots/phase-3/admin-email-all-1440-dark.png) | [390](../screenshots/phase-3/admin-email-all-390-light.png) |
| Banner: some emails aren't going out | [1440](../screenshots/phase-3/smtp-banner-trouble-1440-light.png) | [1440](../screenshots/phase-3/smtp-banner-trouble-1440-dark.png) | [390](../screenshots/phase-3/smtp-banner-trouble-390-light.png) |
| Unsubscribe page (a real link) | [1440](../screenshots/phase-3/unsubscribe-1440-light.png) | [1440](../screenshots/phase-3/unsubscribe-1440-dark.png) | [390](../screenshots/phase-3/unsubscribe-390-light.png) |
| Unsubscribe page: broken link | [1440](../screenshots/phase-3/unsubscribe-broken-link-1440-light.png) | [1440](../screenshots/phase-3/unsubscribe-broken-link-1440-dark.png) | [390](../screenshots/phase-3/unsubscribe-broken-link-390-light.png) |
| Mention picker | [1440](../screenshots/phase-3/mention-picker-1440-light.png) | [1440](../screenshots/phase-3/mention-picker-1440-dark.png) | [390](../screenshots/phase-3/mention-picker-390-light.png) |
| Banner: email isn't set up (`E2E_SMTP=0`) | [1440](../screenshots/phase-3/smtp-banner-not-configured-1440-light.png) | [1440](../screenshots/phase-3/smtp-banner-not-configured-1440-dark.png) | [390](../screenshots/phase-3/smtp-banner-not-configured-390-light.png) |
| Admin → Email without SMTP (setup steps) | [1440](../screenshots/phase-3/admin-email-not-configured-1440-light.png) | [1440](../screenshots/phase-3/admin-email-not-configured-1440-dark.png) | [390](../screenshots/phase-3/admin-email-not-configured-390-light.png) |

| Email | Desktop light | Desktop dark | 390 light | 390 dark |
|---|---|---|---|---|
| Asked to evaluate | [1024](../screenshots/phase-3/emails/evaluator_invited-desktop-light.png) | [1024](../screenshots/phase-3/emails/evaluator_invited-desktop-dark.png) | [390](../screenshots/phase-3/emails/evaluator_invited-390-light.png) | [390](../screenshots/phase-3/emails/evaluator_invited-390-dark.png) |
| Made owner | [1024](../screenshots/phase-3/emails/owner_assigned-desktop-light.png) | [1024](../screenshots/phase-3/emails/owner_assigned-desktop-dark.png) | [390](../screenshots/phase-3/emails/owner_assigned-390-light.png) | [390](../screenshots/phase-3/emails/owner_assigned-390-dark.png) |
| Evaluation reminder | [1024](../screenshots/phase-3/emails/evaluation_reminder-desktop-light.png) | [1024](../screenshots/phase-3/emails/evaluation_reminder-desktop-dark.png) | [390](../screenshots/phase-3/emails/evaluation_reminder-390-light.png) | [390](../screenshots/phase-3/emails/evaluation_reminder-390-dark.png) |
| All evaluations in | [1024](../screenshots/phase-3/emails/evaluations_complete-desktop-light.png) | [1024](../screenshots/phase-3/emails/evaluations_complete-desktop-dark.png) | [390](../screenshots/phase-3/emails/evaluations_complete-390-light.png) | [390](../screenshots/phase-3/emails/evaluations_complete-390-dark.png) |
| Status changed | [1024](../screenshots/phase-3/emails/status_changed-desktop-light.png) | [1024](../screenshots/phase-3/emails/status_changed-desktop-dark.png) | [390](../screenshots/phase-3/emails/status_changed-390-light.png) | [390](../screenshots/phase-3/emails/status_changed-390-dark.png) |
| New comment | [1024](../screenshots/phase-3/emails/comment-desktop-light.png) | [1024](../screenshots/phase-3/emails/comment-desktop-dark.png) | [390](../screenshots/phase-3/emails/comment-390-light.png) | [390](../screenshots/phase-3/emails/comment-390-dark.png) |
| @mention | [1024](../screenshots/phase-3/emails/mention-desktop-light.png) | [1024](../screenshots/phase-3/emails/mention-desktop-dark.png) | [390](../screenshots/phase-3/emails/mention-390-light.png) | [390](../screenshots/phase-3/emails/mention-390-dark.png) |
| Daily digest | [1024](../screenshots/phase-3/emails/digest-desktop-light.png) | [1024](../screenshots/phase-3/emails/digest-desktop-dark.png) | [390](../screenshots/phase-3/emails/digest-390-light.png) | [390](../screenshots/phase-3/emails/digest-390-dark.png) |
| Test email | [1024](../screenshots/phase-3/emails/test-desktop-light.png) | [1024](../screenshots/phase-3/emails/test-desktop-dark.png) | [390](../screenshots/phase-3/emails/test-390-light.png) | [390](../screenshots/phase-3/emails/test-390-dark.png) |
| Submission received (Phase 4) | [1024](../screenshots/phase-3/emails/submission_received-desktop-light.png) | [1024](../screenshots/phase-3/emails/submission_received-desktop-dark.png) | [390](../screenshots/phase-3/emails/submission_received-390-light.png) | [390](../screenshots/phase-3/emails/submission_received-390-dark.png) |
| Submission status changed (Phase 4) | [1024](../screenshots/phase-3/emails/submission_status_changed-desktop-light.png) | [1024](../screenshots/phase-3/emails/submission_status_changed-desktop-dark.png) | [390](../screenshots/phase-3/emails/submission_status_changed-390-light.png) | [390](../screenshots/phase-3/emails/submission_status_changed-390-dark.png) |
| Real (Mailpit): asked to evaluate | [1024](../screenshots/phase-3/emails/mailpit-please-evaluate-gift-returns-without-a-r-desktop-light.png) | [1024](../screenshots/phase-3/emails/mailpit-please-evaluate-gift-returns-without-a-r-desktop-dark.png) | [390](../screenshots/phase-3/emails/mailpit-please-evaluate-gift-returns-without-a-r-390-light.png) | [390](../screenshots/phase-3/emails/mailpit-please-evaluate-gift-returns-without-a-r-390-dark.png) |
| Real (Mailpit): @mention | [1024](../screenshots/phase-3/emails/mailpit-alice-anders-mentioned-you-on-gift-retur-desktop-light.png) | [1024](../screenshots/phase-3/emails/mailpit-alice-anders-mentioned-you-on-gift-retur-desktop-dark.png) | [390](../screenshots/phase-3/emails/mailpit-alice-anders-mentioned-you-on-gift-retur-390-light.png) | [390](../screenshots/phase-3/emails/mailpit-alice-anders-mentioned-you-on-gift-retur-390-dark.png) |
| Real (Mailpit): made owner | [1024](../screenshots/phase-3/emails/mailpit-you-re-now-the-owner-of-gift-returns-wit-desktop-light.png) | [1024](../screenshots/phase-3/emails/mailpit-you-re-now-the-owner-of-gift-returns-wit-desktop-dark.png) | [390](../screenshots/phase-3/emails/mailpit-you-re-now-the-owner-of-gift-returns-wit-390-light.png) | [390](../screenshots/phase-3/emails/mailpit-you-re-now-the-owner-of-gift-returns-wit-390-dark.png) |
