# API contract: Phase 3 (email and notifications)

The REST contract and business rules for Phase 3 (SPEC sections 6 and 13): SMTP
configuration, the transactional outbox and worker, branded templates, per-user
preferences, daily digests, evaluation reminders, @mentions, in-app notifications and
the test email. It extends [contract-phase1.md](contract-phase1.md) and
[contract-phase2.md](contract-phase2.md), whose conventions all still apply. Source of
truth, in order: the Pydantic schemas in `backend/app/schemas/` (`notifications`,
`email`, plus the mention syntax in `comments`), the route stubs in
`backend/app/api/v1/` (`notifications`, `unsubscribe`, `admin_email`), the models in
`backend/app/models/notification.py` with migration `0005`, and the settings in
`backend/app/config.py`, exported to `frontend/src/api/generated/openapi.json` /
`schema.d.ts` (`make gen-api`). Rules are named as in [role-matrix.md](../role-matrix.md);
tables in [erd.md](../erd.md); the outbox design in
[ADR 0003](../adr/0003-background-jobs-procrastinate-and-email-outbox.md) (amended for
this phase).

`backend/tests/test_contract_routes.py` pins every method, path and `operation_id` and
keeps a valid request per unimplemented route (`STUBS`, answered with 501
`not_implemented`): delete a stub row when you implement its endpoint.
`tests/authz/test_route_rules.py` names the rule of every operation.

**Who builds what (suggested):** backend: everything in section 3 (fan-out, outbox,
worker jobs and the worker's job cleanup in `app/worker.py`, templates, digests,
reminders, mentions, the endpoints); identity: the non-sliding session resolution for
the summary poll (§3.2) and the `evaluation.submit_own` checks the fan-out reuses;
frontend: the bell and inbox, the Notifications section of personal Settings, the
public unsubscribe page, Admin settings → Email, the SMTP and "email failing" banners,
the mention picker in comments; platform: Helm values and env for the new settings
(`smtp.port` empty by default, §3.1), Mailpit in the e2e stack; qa: section 3.14 as e2e
against Mailpit, plus the email rendering checks.

## 1. Conventions (new in Phase 3)

| Topic | Rule |
|---|---|
| Two channels, one fan-out | Every notification lands in the recipient's **in-app inbox**. Their **email preference** for its type (immediate, daily digest, off) decides whether it is also emailed. Both are written by the same fan-out, in the same database transaction as the event that causes them (§3.3). |
| Email is optional | `smtp_configured` = `SOUNDINGS_SMTP_HOST` (and the then-required `_FROM`) is set. When it isn't, nothing is written to the outbox, every notification is recorded with `email_mode = off`, the app works with in-app notifications only, and platform admins see a banner (§3.1). |
| Authorisation, twice | A user is notified only if they pass `idea.view` (and the type's own condition, a named policy rule where one applies) **when the notification is created**, and an email goes out only if they still do **when it is sent**, still want that type by email, and the email isn't out of date (§3.9 step 3). The inbox lists only notifications about ideas the user can view **now**. |
| Blind-safe | No notification, email or digest ever contains score data (role matrix §3 rules 1 and 8): no scores, aggregate, `n`, per-criterion data, disagreement flag, recommendations, rank, or evaluation comments. "All evaluations are in" carries a count of submissions only. |
| Never the actor | Nobody is notified about their own action. Service accounts, the break-glass account and deactivated users are never notified. |
| Privacy | Never log or audit email addresses, subjects, bodies, unsubscribe tokens, SMTP credentials or the SMTP server's reply text. Logs carry outbox ids, types, statuses, attempt numbers and error classes (§3.12). |
| Public routes | `get_unsubscribe` and `confirm_unsubscribe` need no session and no CSRF token: the signed token in the link is the authority (rule `self.unsubscribe`, c14). Everything else needs a session; `/admin/email/*` and the preferences need a **session** (no API keys: `platform.*`, `self.manage_profile`). |
| Times | Stored in UTC. Digests and reminders follow the **instance time zone** `SOUNDINGS_TIMEZONE` (default `UTC`); emails show dates in it with its name ("Fri 9 Oct, 17:00 (Europe/London)"). No per-user time zones. |
| Polling isn't activity | `get_notification_summary` (the bell's poll) resolves the session **without** moving `last_seen_at`, so an open tab still idle-expires (12 h by default, 1 h for break-glass; contract-phase2 §3.9). Every other request keeps the session alive as before. |
| One recipient per email | Every address an email goes to (a user's, a test email's `to`) must be one plain ASCII address (`app.config.MAIL_ADDRESS_PATTERN`) and is passed to SMTP explicitly; nothing can name a second recipient (§3.9 step 2, §3.11). |

## 2. Endpoints

Common errors (401, 403 `csrf_failed`, 422 `validation_error`, 400 `invalid_cursor`) are
not repeated per row.

### Inbox (`tags: notifications`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /me/notifications?unread=&cursor=&limit=` | `list_notifications` | signed in; rows by `idea.view` | → `NotificationPage` of `NotificationItem`, newest first (§3.2) | |
| `GET /me/notifications/summary` | `get_notification_summary` | signed in (session not kept alive); counts by `idea.view` | → `NotificationSummary {unread_count (≤ 100), email_available, email_trouble}` | |
| `POST /me/notifications/{notification_id}/read` | `mark_notification_read` | signed in, own notification, `idea.view` | → 204; idempotent | 404 |
| `POST /me/notifications/read-all?idea=` | `mark_all_notifications_read` | signed in; `idea` needs `idea.view` | → `NotificationSummary` after the change | 404 (idea) |

### Email preferences (`tags: notifications`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /me/notification-preferences` | `get_notification_preferences` | `self.manage_profile` | → `NotificationPreferences {email_available, digest_hour, timezone, items: [{type, mode, default_mode}]}`, one item per type in `NotificationType` order | |
| `PATCH /me/notification-preferences` | `update_notification_preferences` | `self.manage_profile` | `NotificationPreferencesUpdate {<type>?: mode}` (omitted or null = unchanged) → `NotificationPreferences` | |

### Unsubscribe links (`tags: notifications`, public)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /unsubscribe?token=` | `get_unsubscribe` | `self.unsubscribe` (c14) | → `UnsubscribeInfo {scope, types, unsubscribed, email_hint}`; changes nothing. A browser navigation (`Accept` lists `text/html`) → 303 to the SPA page `/unsubscribe?token=…` (§3.5) | 404 invalid token or inactive user |
| `POST /unsubscribe?token=&all=` | `confirm_unsubscribe` | `self.unsubscribe` (c14) | no body (an RFC 8058 form body is accepted and ignored) → `UnsubscribeInfo` after the change; idempotent | 404 |

### Admin: email (`tags: admin`)

| Method & path | operation_id | Rule | Request → response | Errors |
|---|---|---|---|---|
| `GET /admin/email` | `get_email_config` | `platform.configure_email` | → `EmailConfig` (effective SMTP settings, credentials as `*_set` booleans, schedule, `outbox: OutboxStats`) (§3.10) | 403 |
| `POST /admin/email/test` | `send_test_email` | `platform.configure_email` | `EmailTestRequest {to?: MailAddress}` (one plain ASCII address; omitted: yourself) → 202 `OutboxEmail` (queued, one attempt) | 403; 409 `smtp_not_configured`; 422 `validation_error` (bad, reserved, multiple or unusable address); 429 `too_many_attempts` + `Retry-After` |
| `GET /admin/email/outbox?status=&type=&cursor=&limit=` | `list_outbox_emails` | `platform.configure_email` | → `OutboxEmailPage` of `OutboxEmail` (with `retryable`), newest first; `status`, `type` repeatable (OR) | 403 |
| `GET /admin/email/outbox/{email_id}` | `get_outbox_email` | `platform.configure_email` | → `OutboxEmail` (the test email's progress) | 403, 404 |
| `POST /admin/email/outbox/{email_id}/retry` | `retry_outbox_email` | `platform.configure_email` | → `OutboxEmail` queued again, attempts reset | 403, 404; 409 `email_not_retryable` (not `failed`, or out of date), `smtp_not_configured` |
| `POST /admin/email/outbox/retry-failed` | `retry_failed_outbox_emails` | `platform.configure_email` | → `OutboxRetryResult {retried}` (retryable failed emails only) | 403; 409 `smtp_not_configured` |

Admin routes follow the Phase 2 order: 401 → 422 shape → 403 `forbidden` (not a platform
admin) → 404 → 422 business → 409 → 429.

### Unchanged endpoints with new behaviour

- `POST /ideas/{idea}/comments`, `PATCH /comments/{comment_id}`: comment bodies may contain
  @mentions (§3.8); mention labels are rewritten; more than 20 distinct mentions → 422
  `too_many_mentions`; a body longer than 10,000 characters **after** rewriting → 422
  `validation_error` at `["body", "body_md"]`. The `CommentActivity` returned carries
  the rewritten `body_md`.
- **Mention autocomplete reuses `GET /users?project=<slug>&q=`** (`search_users`):
  people with a role in the idea's project. No new endpoint.
- Every Phase 1 write that emits an activity event (§3.3 table) now also fans out
  notifications in the same transaction, after its last write; the HTTP responses are
  unchanged.

## 3. Business rules

Tests first (SPEC section 15) for 3.3 (fan-out: recipients, exclusions, dedupe, access),
3.4 (preference resolution), 3.6 (digests), 3.7 (reminder scheduling), 3.9 (the outbox:
atomicity, retries and backoff, no loss while SMTP is down, idempotent sending, no
duplicate send after a worker crash, bounded job table, one recipient per email) and
3.11 (blind safety of content). §3.13 lists the minimum cases.

### 3.1 Settings and "email available"

Configured only by Helm values / environment (no settings screen; the admin page is
read-only). Names match `deploy/helm/README.md`:

| Variable | Default | Notes |
|---|---|---|
| `SOUNDINGS_SMTP_HOST` | unset | Host name or IP (no scheme, no port). Unset or empty: email off. |
| `SOUNDINGS_SMTP_PORT` | `465` with `tls`, else `587` | Unset or empty: by the security mode (`app.config.SMTP_DEFAULT_PORTS`). An explicit value always wins. |
| `SOUNDINGS_SMTP_SECURITY` | `starttls` | `none` (plain: in-cluster relay, Mailpit), `starttls`, `tls` (implicit, usually 465). TLS verifies the certificate and host name. With `none`, pass `start_tls=False` explicitly to aiosmtplib (its default is opportunistic STARTTLS; research R1 §5). |
| `SOUNDINGS_SMTP_USERNAME` / `_PASSWORD` | unset | From the chart's Secret (`smtp.existingSecret`). Empty = unset. Production refuses a password with `security=none`. |
| `SOUNDINGS_SMTP_FROM` | unset | Required when the host is set (startup error otherwise). One plain ASCII address (`MAIL_ADDRESS_PATTERN`). |
| `SOUNDINGS_SMTP_FROM_NAME` | `Soundings` | No control characters. |
| `SOUNDINGS_SMTP_REPLY_TO` | unset | One plain ASCII address; no Reply-To header when unset. |
| `SOUNDINGS_SMTP_CA_BUNDLE` | unset | PEM file path (the chart mounts it); must exist at startup. Unset: system trust store. |
| `SOUNDINGS_SMTP_TIMEOUT` | `10` | Seconds, for the connection and each command (0 < t ≤ 120). |
| `SOUNDINGS_TIMEZONE` | `UTC` | IANA name; digests, reminders and dates in emails. |
| `SOUNDINGS_DIGEST_HOUR` | `8` | 0–23 in that zone: daily digests and reminders go out then. |
| `SOUNDINGS_REMINDER_DAYS` | `2,0` | Days before the due date (0 = on the due date), 0–30, at most 5; empty = no reminders. Stored descending, de-duplicated. |

Links in emails use `settings.public_base_url` = the first of `SOUNDINGS_BASE_URLS`.
`settings.smtp_configured`, `settings.tz` and `settings.public_base_url` are the derived
values.

**When SMTP is not configured:** the fan-out still writes notifications (with
`email_mode = off`) but no outbox rows; reminders still create in-app notifications;
digests are not built; the sweep does nothing (§3.9 step 6); `send_test_email`,
`retry_*` return 409 `smtp_not_configured`; `NotificationSummary.email_available` and
`NotificationPreferences.email_available` are false and `email_trouble` is false. The
shell shows platform admins a calm, dismissible banner ("Email isn't set up: people only
get in-app notifications." with a link to Settings → Email); the preferences page says
nothing is emailed for now (controls stay usable). Rows queued before SMTP was switched
off stay `queued` and untouched (no attempts counted, no jobs deferred) until it is
configured again; by then most are out of date and are cancelled at send time
(§3.9 step 3) rather than sent late.

**When email is failing:** `NotificationSummary.email_trouble` is true for platform
admins (only) while email is configured and an email **failed in the last 24 hours**
(`status = failed`, `updated_at`) or one has been **queued for more than 15 minutes**
(`created_at`; SMTP down, worker stopped, or a backlog). Both are index lookups on
`(status, created_at, id)`, run only for platform admins. The shell shows them a calm,
dismissible banner ("Some emails aren't going out." → Settings → Email); it clears by
itself once mail flows again and no failure is newer than a day.

### 3.2 The inbox

- `list_notifications`: the caller's notifications, newest first by `(created_at, id)`
  (keyset cursor), only where the caller passes `idea.view` on the notification's idea
  **now** (same SQL filter as lists: `app.authz.queries.viewable_ideas`); `unread=true`
  keeps `read_at IS NULL` only. Rows the caller can't view are skipped (no gaps or
  placeholders). Each item resolves `idea` (`IdeaRef`, current title and status),
  `actor` (`UserRef`), and per type the fields in `NotificationItem`:
  `status_changed` labels use the project's current labels (closed: the resolution's
  label, as `IdeaRef.status_label`); `comment`/`mention` carry `CommentExcerpt` (plain
  text, Markdown removed, mentions as `@Name`, ≤ 200 characters; empty with
  `deleted: true` for a deleted comment). Resolve in batched queries per page.
- `get_notification_summary`: `unread_count` = unread notifications the caller can view,
  counted up to 100 (`SELECT count(*) FROM (… LIMIT 100)`, served by
  `ix_notifications_user_id_unread`); `email_available` = `smtp_configured`;
  `email_trouble` per §3.1 (false unless the caller is a platform admin). The shell
  polls it about once a minute and on window focus (no push in Phase 3).
  **The poll doesn't keep the session alive:** this route resolves the session without
  updating `last_seen_at` (session or user), so the idle timeout (12 h default; 1 h for
  break-glass sessions) still ends a session left open in a tab. Mechanism: a
  non-touching principal dependency for this one route (`resolve_session(…,
  touch=False)` via the session source; identity and backend). A 401 from the poll is
  handled like any 401 (back to sign-in).
- `mark_notification_read`: sets `read_at = now()` if null; 404 when the notification
  isn't the caller's or its idea isn't viewable; idempotent (204 either way).
- `mark_all_notifications_read`: sets `read_at` on every unread notification of the
  caller (viewable or not), or with `idea` (UUID or key; 404 if the caller can't view
  it) only those about that idea. The idea page calls it with `idea` when it opens, so
  visiting an idea clears its notifications. Returns the new summary.
- The bell shows the count ("99+" above 99). Suggested SPA routes: a popover from the
  bell and a full page `/notifications` (phones, "See all"); clicking an item marks it
  read and opens its link (§3.11).
- Notifications are deleted after **90 days** (read or not) by the daily cleanup
  (§3.9).

### 3.3 Fan-out: which events notify whom

The fan-out runs **in the request's transaction, once, after the request's last write
and before commit**, over the activity events the request emitted
(`app.services.activity.emit` collects them on the session, e.g. in `session.info`; the
service or route calls the fan-out at its end). So the event, the notifications, the
outbox rows and their jobs commit or roll back together, and every check and payload
reads the state **after all of the request's writes** (`add_evaluators` emits
`evaluator_added` before it sets the due date; the invitation must carry the final
date). For each candidate recipient *R*:

1. drop *R* if *R* is the actor, inactive, a service account or the break-glass
   account, or doesn't pass `idea.view` on the idea now (one SQL query for the set);
2. check the type's condition (table), through the policy where it names a rule
   (`app.authz.can(principal_of(R), rule, resource_for(R))`, ADR 0010; no role checks
   in notification code);
3. insert the notification with `INSERT … ON CONFLICT (user_id, dedupe_key) DO NOTHING`
   (a retried job or request never notifies twice);
4. resolve *R*'s email mode (§3.4), recorded as `email_mode`; it is `off` whatever
   the preference when SMTP isn't configured, *R*'s address can't receive mail (under
   `.invalid`, or not a plain address, §3.9 step 2), or, for `mention`, the author has
   reached the mention-email cap (§3.8). `immediate`: insert an `outbound_email` row
   (`type` = the notification type, `recipient_user_id` = *R*), set the notification's
   `email_id` to it, and defer `send_email` on the same connection (§3.9). `digest`:
   `email_id` stays null until the digest claims it. `off`: nothing more.

One person gets **at most one notification per event**: when *R* qualifies for several
roles (owner and watcher), they get the single notification of that event's type.

| Type | Trigger (activity event) | Candidate recipients | Type condition (at creation and at send) | Payload | `dedupe_key` |
|---|---|---|---|---|---|
| `owner_assigned` | `owner_changed` with a new owner | the new owner (not when they volunteered: they are the actor) | *R* is the idea's owner (a fact, `ideas.owner_id`) | `{}` | `owner_assigned:<event id>` |
| `evaluator_invited` | `evaluator_added` | the evaluator | *R* passes **`evaluation.submit_own`** on the idea (an assigned evaluator holding member or admin, c6 evaluation open, project not archived) and hasn't submitted | `{due_at}` (the idea's due date after the request, may be null) | `evaluator_invited:<event id>` |
| `evaluation_reminder` | the reminder scan (§3.7), no event | pending evaluators | as `evaluator_invited`, plus the due date is still `due_at` and *now* < `due_at` | `{due_at, days_before}` | `evaluation_reminder:<idea id>:<local due date>:<days_before>` |
| `evaluations_complete` | `evaluation_submitted` (first submission) or `evaluator_removed`, when afterwards the idea has ≥ 1 evaluator and **every** assigned evaluator has submitted | the owner | *R* is the idea's owner | `{evaluator_count}` (submitted = assigned) | `evaluations_complete:<event id>` |
| `status_changed` | `status_changed` | the owner and every assigned evaluator (always), and every watcher | `idea.view` only | `{from_status, from_resolution, to_status, to_resolution}` | `status_changed:<event id>` |
| `comment` | `comment` (creation only; not edits) | every watcher, **minus** users this comment mentions who get a `mention` | the comment isn't deleted | `{}` + `comment_id` column | `comment:<event id>` |
| `mention` | comment created, or edited to add a mention (§3.8) | each newly mentioned user with a role in the idea's project | the comment isn't deleted and still mentions *R* | `{}` + `comment_id` column | `mention:<comment id>` |

Notes:

- Watchers are added automatically (Phase 1 §3.13: submitter, owner, evaluators,
  commenters); anyone who can view may unwatch. **Unwatching stops `comment`
  notifications and the `status_changed` notifications a person gets only as a
  watcher.** The owner and assigned evaluators get `status_changed` whether or not they
  watch (they have a job on the idea); everything addressed to someone personally
  (owner, evaluator, mention) is unaffected by watching.
- "Every assigned evaluator has submitted" counts all assignments, AI evaluators
  (service accounts) included; it fires once per triggering event, so the owner hears
  again only after another evaluator was invited and the set completed again. Phase 1
  §6 already required it for the removal case. The owner gets nothing if they are the
  actor (they submitted last, or removed the last pending evaluator). **No race:** the
  check runs in the fan-out of `save_my_evaluation` (submit) and `remove_evaluator`,
  which already load the idea with `load_idea(for_update=True)` (the idea row lock), so
  of two concurrent final submissions the second sees the first, and exactly one event
  completes the set. Keep that lock when building on these routes.
- Type conditions that are permissions are named policy rules (ADR 0010):
  `evaluation.submit_own` for the evaluator types; facts about the idea (owner, the due
  date, a comment's state) are plain data checks. The reminder scan and the send-time
  re-check (§3.9 step 3) use the same function per type.
- A removed evaluator stops getting evaluator notifications at once (the condition
  fails at send time); they may still be a watcher.
- No notifications for: idea created or edited, evaluator removed, due date changed,
  evaluation closed or reopened, votes, watching, comment deletion. The due date
  reaches evaluators through the reminders, which follow the current date, and the
  invitation email, which shows the idea's due date when it is sent (§3.11).
- Phase 4: status changes also email an opted-in public submitter (an
  `outbound_email` of type `submission_status_changed` with `to_address` and an idea
  reference that Phase 4's migration adds, no notification row); design the fan-out so
  that is one more branch.

### 3.4 Email preferences

- Modes: `immediate` (one email per notification, as it happens), `digest` (collected
  into the daily digest), `off` (no email; the inbox still shows it). Preferences govern
  **email only**.
- Defaults (`app.schemas.notifications.DEFAULT_MODES`): `owner_assigned`,
  `evaluator_invited`, `evaluation_reminder`, `evaluations_complete` and `mention` are
  `immediate` (things you must act on); `status_changed` and `comment` are `digest`
  (things you follow).
- Stored: only choices that differ from the default (`notification_preferences`, one
  row per user and type). `PATCH` with a type's default deletes the row; with another
  mode upserts it. Resolution: row if present, else the default.
- The mode is resolved **when the notification is created** and recorded as
  `notifications.email_mode`. A later switch to `off` (in Settings or by an unsubscribe
  link) also stops mail already queued: at send time an immediate email whose type is
  now `off` for the recipient is cancelled (§3.9 step 3), and digest items of such types
  are dropped (§3.6). A switch to `immediate` or `digest` doesn't re-send anything, and
  an immediate email already queued still goes out after a switch to `digest`.
- `GET` returns every type in `NotificationType` order with `mode` and `default_mode`,
  plus `email_available`, `digest_hour` and `timezone` for the copy ("Daily digest at
  08:00, Europe/London").

### 3.5 Unsubscribe links

- **Token:** signed, not stored: `base64url(payload) "." base64url(HMAC-SHA256(key,
  base64url(payload)))`, payload compact JSON `{"v": 1, "u": "<user id>", "s":
  "<scope>"}`, key derived from `SOUNDINGS_SECRET_KEY` by HKDF-SHA256 with info
  `soundings/unsubscribe/v1` (purpose-separated, like `app/auth/sealing.py`), compared
  in constant time. No expiry (mail sits in inboxes for months); rotating the secret key
  invalidates every link (the page then says the link no longer works and offers
  sign-in → preferences). Charset `[A-Za-z0-9_.-]`, 16–512 characters (else 422).
- **Scope:** an immediate email's link turns off its own type; the digest's link turns
  off every type currently in `digest` mode (`digest`); `all` turns off every type.
  Test emails and Phase 4 submitter emails carry no such link.
- `GET` validates the token (404 if invalid, or the user is unknown or inactive) and
  returns `scope`, `types` (the link's type; for `digest` the types now in digest mode;
  for `all` every type), `unsubscribed` (all of `types` already off) and `email_hint`
  (the user's address masked: first character, `•••`, `@domain`). **It never changes
  anything**: link scanners prefetch.
- `POST` (idempotent) sets `off` for the scope's types (`all=true`: every type) and
  returns the same shape (for `digest`, `types` = the types it just switched off). It is
  also the **RFC 8058 one-click** target: mail clients POST
  `List-Unsubscribe=One-Click` as `application/x-www-form-urlencoded` with no cookies;
  the body is ignored; no session or CSRF check applies (the route takes no principal).
- **Browsers opening the header's URL:** mail clients without one-click support open
  `List-Unsubscribe`'s URL (`/api/v1/unsubscribe?token=…`) in a browser. A `GET` whose
  `Accept` header lists `text/html` is answered with **303** to
  `<public_base_url>/unsubscribe?token=<the same token>` (the SPA page), without checking
  the token (the page does, through the JSON `GET`). The SPA's client sends `Accept:
  application/json`, so it gets the JSON. `POST` never redirects.
- Not audited (a user's own preference). Not throttled (tokens can't be guessed).
- The SPA page `/unsubscribe?token=…` (outside the signed-in shell, like `/login`)
  shows what stops, one primary "Unsubscribe" button (POST), a secondary "Unsubscribe
  from all Soundings email" (`all=true`), and a link to the preferences (sign-in).

### 3.6 Daily digest

- The hourly `notification_schedule` job (§3.9) builds digests once the local hour
  (`SOUNDINGS_TIMEZONE`) is ≥ `SOUNDINGS_DIGEST_HOUR`, for every user with **pending**
  notifications (`email_mode = 'digest' AND email_id IS NULL`, created before the run
  **and within the last 7 days**) and no digest yet for that local date. A missed hour
  (worker down) is caught up on the next run that day; a missed day rolls into the next
  digest.
- **Never older than a week, never twice.** Pending items older than 7 days are never
  collected, and the daily cleanup (§3.9) sets `email_mode = 'off'` on them. This also
  covers items whose digest row the cleanup deleted (30 days after sending, which sets
  their `email_id` back to null via `ON DELETE SET NULL`): they are at least 30 days old,
  so they can't look pending again and be mailed a second time. And when SMTP comes
  back after a long gap, at most a week of items goes out in one digest.
- Per user, in one transaction: drop pending items whose type is now `off`, whose idea
  the user can't view, or that were **read in the app** already (set their
  `email_mode = off`); if any remain, insert one `outbound_email` of type `digest`
  (`idempotency_key = digest:<user id>:<local date YYYY-MM-DD>`, `ON CONFLICT DO
  NOTHING`) and set `email_id` on the remaining items; defer `send_email`. No items, no
  email.
- Content: grouped by idea (key, title, project), newest idea activity first, one line
  per notification ("Bob commented: “excerpt…”", "Moved from Evaluating to
  Shortlisted"); at most 50 lines, then "and N more in Soundings" linking to the inbox.
  Subject: "Soundings digest: 5 updates on 3 ideas". At send time items whose idea the
  user can no longer view are left out; if none remain the email is cancelled.
- Unsubscribe link scope `digest` (§3.5).

### 3.7 Evaluation reminders

- The same hourly job scans open evaluations with a due date
  (`ix_ideas_evaluation_due_at_open`; not closed, evaluation not closed) and their
  **pending** evaluators: assigned, no submitted evaluation, active, not a service
  account, and passing `evaluation.submit_own` on the idea (the §3.3 type condition,
  through the policy).
- For due time *D* (local date *d* in `SOUNDINGS_TIMEZONE`) and each *n* in
  `SOUNDINGS_REMINDER_DAYS`, the reminder's time is `fire(n)` = local date *d − n* at
  `SOUNDINGS_DIGEST_HOUR`:00. At a run at time *now* (local date *t*), the **eligible**
  offset is the *n* with **d − n = t** and `fire(n) ≤ now`: a reminder goes out only
  **on its own local day** (at most one per day, since the offsets are distinct; a day
  missed while the worker was down is not caught up later, so a moved due date or an
  outage never produces a reminder that names the wrong distance). Send it when also
  `now < D` (never for overdue evaluations: My work shows those), `fire(n) >
  invited_at` of the assignment (the invitation already gave the date), and no
  notification with its `dedupe_key` exists.
- **Phrased as a date, not a countdown:** "due Fri 9 Oct" (or "due today, Fri 9 Oct" in
  an email sent on that date); the inbox shows the date. `days_before` only identifies
  which reminder it was.
- A changed due **date** gives new keys, so reminders follow the new schedule; a changed
  time on the same date doesn't repeat them. DST is handled by computing in the zone.
- Worked example (zone Europe/London, hour 08:00, days 2,0): invited Mon 09:00, due Fri
  17:00 → reminders Wed 08:00 ("due Fri 9 Oct") and Fri 08:00 ("due today, Fri 9 Oct").
  Invited Thu 10:00 for the same date → only Fri 08:00. Due Fri 07:00 → Wed 08:00 only
  (Fri's would be after the due time). Worker down Tue–Fri 09:00 → one "due today" at
  Fri 09:00 (Wed's is not caught up). Due date moved on Wed 10:00 from next Mon to Thu
  17:00 → nothing on Wed (Thu's 2-day reminder was Tue's), Thu 08:00 "due today".
- Each reminder is a notification of type `evaluation_reminder` (inbox), emailed by
  the evaluator's preference (default immediate; `digest` puts it in that day's digest,
  which the job builds after the reminders).

### 3.8 @mentions

- Syntax (`app.schemas.comments.MENTION_PATTERN`): `@[Display Name](user:<uuid>)`,
  inserted by the SPA's picker (`search_users?project=<slug>&q=`). Anywhere in the
  text, code included. Anything else (`@ada`) is plain text.
- On create and edit, before saving: more than `MAX_MENTIONS` (20) distinct users →
  422 `too_many_mentions`. Each token naming an **active, non-service** user is
  rewritten with `mention_token(user_id, current display name)`, so labels can't
  impersonate anyone; a token naming anyone else becomes its label as plain text
  (`@Label`, no link). The length limit (10,000 characters) applies to the text
  **after** rewriting (422 `validation_error` at `["body", "body_md"]`), so a stored
  comment always fits the next edit.
- Recipients: mentioned users (not the author) who have a **role in the idea's
  project** (effective, direct or through a group: exactly whom the picker offers) and
  pass `idea.view` now; on edit only users not mentioned in the previous text.
  Mentioning anyone else (a platform admin or an organisation member who can view an
  internal project without having a role in it, someone who can't view the idea)
  notifies nobody (the text stays). `dedupe_key
  mention:<comment id>`: at most one mention notification per comment and person,
  however often it is edited.
- **Mention-email cap:** at most **50** of an author's mention notifications per
  rolling hour are emailed (immediate or digest); beyond that, new mention
  notifications from that author are recorded with `email_mode = off` (in-app only).
  Counted from `notifications` (`type = 'mention'`, `actor_id` = the author,
  `created_at` in the last hour, `email_mode <> 'off'`) on
  `ix_notifications_mention_actor`. No error to the author.
- Mentioned users don't start watching. The SPA renders tokens as a name chip and
  never as a link with the `user:` scheme; emails and excerpts show `@Name`.

### 3.9 The outbox and the worker

Normative design for ADR 0003 (amended).

**Rows.** `outbound_email` (erd.md): `type`, `status`, recipient (`recipient_user_id`
**or** `to_address`), `requested_by_id` (test email), `payload` (never scores; Phase 4:
what can't be looked up later, sealed), `message_id` `<uuid4-hex@host-of-public_base_url>`
fixed at insert, `idempotency_key`, `attempts`/`max_attempts` (12; test emails 1),
`next_attempt_at`, `last_error`, `sent_at`. **Rendered at send time**: the content is
built from the notification(s) whose `email_id` is this row, from the current idea,
people and labels, after the re-checks, so nothing a recipient may no longer see goes
out, template fixes apply to queued mail, and no bodies are stored. (Phase 4's migration
adds the idea reference its submitter emails need.)

**Constants** (in code, no settings): lease **5 min**; attempt deadline **4 min**;
`max_attempts` 12; maximum age **3 days** (`digest` **2 days**); sweep batch 500.

**Jobs** (procrastinate, defined in a module listed in `app.worker.TASK_MODULES`):

| Task | Queue | When | Does |
|---|---|---|---|
| `send_email(email_id)` | `email` | deferred with each row, retries and sweeps | one attempt, steps 1–5 below |
| `sweep_outbox` | `email` | periodic, every minute (`queueing_lock`) | step 6 |
| `notification_schedule` | `notifications` | periodic, hourly | reminders (§3.7), then digests (§3.6), then cleanup |
| `remove_old_jobs` | `notifications` | periodic, daily | procrastinate's builtin (`procrastinate.builtin_tasks.remove_old_jobs`, `max_hours=168`, `remove_failed`, `remove_cancelled`, `remove_aborted` all true) |

**The job table stays bounded.** The worker runs with `run_worker_async(…,
delete_jobs="successful")` (procrastinate's default keeps every finished job), so the
1,440 sweep runs a day and every `send_email` that finished leave nothing behind;
`remove_old_jobs` clears failed, cancelled and aborted jobs after a week. procrastinate
prunes its own periodic-defer bookkeeping.

**Enqueue** (in the event's transaction): insert the row (`status = queued`,
`next_attempt_at = now()`), then `send_email.configure(connection=<the request's psycopg
connection>).defer_async(email_id=…)`. Commit keeps both, rollback drops both (research
R1 §2). No `queueing_lock` on this defer (the row is new, nothing can conflict; a
conflict would abort the request's transaction).

**`send_email`:**

1. **Claim** in its own short transaction: `UPDATE outbound_email SET status='sending',
   attempts = attempts + 1, next_attempt_at = now() + interval '5 minutes' (the lease),
   updated_at = now() WHERE id = :id AND status = 'queued' AND next_attempt_at <= now()
   RETURNING …`; commit. No row → stop (sent, cancelled, not due yet, or another worker
   has it). Two jobs for one row can't both claim it. If SMTP isn't configured, stop
   before claiming (the job succeeds and is deleted; the row waits untouched).
   **Everything from here to step 5 runs under `asyncio.timeout(4 minutes)`** (lease −
   1 minute): load, render and the whole SMTP conversation (`smtp_timeout` up to 120 s
   applies per command, and a conversation has about eight). Exceeding it is a
   transient failure ("timed out"), recorded before the lease can expire, so the sweep
   never re-queues a row whose worker is still talking to the server.
2. **Load** recipient and content: the user (active, not service or break-glass) or
   `to_address`; the notification(s) by `email_id`. **The address** must be one plain
   address: `app.config.is_mail_address(address)` (ASCII dot-atom, ≤ 254 characters),
   not under `.invalid` (`app.schemas.admin_users.is_reserved_email`), **and**
   `email.headerregistry.Address(addr_spec=address)` succeeds with `addr_spec ==
   address`. Otherwise → `cancelled`, `last_error` "Not sent: unusable address" (no
   SMTP; the exception text echoes the address, so it is never logged). This is the
   guard for addresses from SSO claims and older rows.
3. **Re-check** (no SMTP for any of these; `cancelled` with the `last_error` shown):
   - **out of date:** `created_at` older than 3 days (`digest`: 2 days) → "Not sent: out
     of date" (an outage longer than the retries, SMTP configured again after a long
     gap, a retry days later);
   - **no longer applies**, per notification: `idea.view` for the recipient now plus
     the §3.3 type condition (for `evaluation_reminder` also *now* < `due_at`). An
     immediate email failing it → "Not sent: no longer applies". Digest: drop failing
     items; none left → "Not sent: nothing left to send";
   - **turned off:** an immediate notification email whose type the recipient has now
     set to `off` (Settings or an unsubscribe link) → "Not sent: turned off by the
     recipient". Digest items of now-`off` types are dropped as above.
4. **Render** HTML and text (§3.11) and **send** with aiosmtplib: `send_message(message,
   sender=smtp_from, recipients=[address], hostname, port, use_tls = security == "tls",
   start_tls = security == "starttls"` (explicit `False` for none), `tls_context` from
   the CA bundle, `username`/`password` when set, `timeout)`. **`recipients` is always
   passed explicitly** (one address), never derived from the headers. The sender is
   `smtp_from` for every email (Reply-To optional).
5. **Record** in a new transaction:
   - accepted → `sent`, `sent_at = now()`, `next_attempt_at = null`, `last_error = null`;
   - **transient** failure and `attempts < max_attempts` → `queued`, `next_attempt_at =
     now() + backoff(attempts)`, `last_error` set, and in the same transaction (on its
     connection, like the enqueue) defer a new `send_email` with `schedule_at =
     next_attempt_at` (the job itself never raises for SMTP errors, so procrastinate's
     own retry is unused);
   - **permanent** failure, or out of attempts → `failed`, `next_attempt_at = null`;
   - **internal error** (any other exception after the claim: a template, data or
     programming error) → `failed` at once, `last_error` "Internal error"; the log line
     carries the outbox id and the exception class only (no message text). An admin
     retries after the fix. (A database outage that prevents recording leaves the row
     `sending`; the sweep re-queues it after the lease.)

   Record only if the row is still `sending` with this attempt number.
6. **`sweep_outbox`** (the safety net, every minute). **Does nothing while SMTP isn't
   configured.** Otherwise:
   - `sending` rows whose lease expired (a worker died): back to `queued` with
     `next_attempt_at = now()` (the attempt counts; out of attempts → `failed`,
     `last_error` "Worker stopped while sending");
   - `queued` rows with `next_attempt_at ≤ now() − 1 minute` (job lost, worker was
     down), oldest first, at most 500 per run: defer `send_email` again with
     **`queueing_lock = "send_email:<id>"`**, each defer on its own (autocommit, outside
     any SQLAlchemy transaction), ignoring `procrastinate.exceptions.AlreadyEnqueued`. At
     most one sweep job waits per row, so a backlog or a long outage doesn't add a job
     per row per minute. Duplicate jobs (the original plus one sweep job) are harmless
     (step 1).

**Backoff:** `backoff(a) = min(30 s × 2^(a−1), 1 hour)`, plus up to 10 % random jitter:
30 s, 1 min, 2, 4, 8, 16, 32 min, then hourly; 12 attempts span about 5 hours. Longer
outages end in `failed`, and admins use "Retry all failed" (§3.10) while the mail is
recent enough to send.

**Transient vs permanent** (research R1 §5; catch `(aiosmtplib.SMTPException, OSError,
TimeoutError)`):

| Transient (retry) | Permanent (failed now) |
|---|---|
| connection refused / reset / timeout (`SMTPConnectError`, `SMTPConnectTimeoutError`, `SMTPTimeoutError`, `SMTPServerDisconnected`, other `OSError`, including TLS handshake and certificate errors), the 4-minute deadline | any other **5xx** reply (`SMTPResponseException.code` 500–599): recipients or sender refused with 5xx, message refused |
| any **4xx** reply (greylisting 451, busy 421/450), recipients refused with 4xx | |
| **authentication**: `SMTPAuthenticationError` and the codes 530, 534, 535, 538 wherever they occur (a password being rotated, or credentials missing, shouldn't fail every queued email at once; after 12 attempts they fail) | |
| `SMTPNotSupported` (e.g. the server offers no STARTTLS or AUTH: a configuration fix and a redeploy, which the retries outlast) and any other `SMTPException` without a reply code | |

(Not SMTP: an unusable address and the re-checks cancel; other exceptions are internal
errors, step 5.)

**`last_error`** is built by our code: `"SMTP <code>: <fixed phrase>"` (phrases:
authentication failed, recipient refused, sender refused, message refused, server busy,
server error) or a fixed phrase for the exception class (connection refused, connection
timed out, timed out, server disconnected, TLS certificate not trusted, TLS handshake
failed, server doesn't support STARTTLS or AUTH, SMTP error, internal error) or a "Not
sent: …" reason (steps 2–3). Never the server's reply text or an exception message (they
can echo addresses), at most 200 characters.

**Idempotency and crashes:** a worker that dies after the server accepted the message
but before step 5 leaves the row `sending`; the sweep re-queues it after the lease and it
is sent again with the **same Message-ID** (most clients and Gmail drop the duplicate).
Delivery is at-least-once; duplicates need a crash in that window (the 4-minute deadline
keeps a slow but live worker from overlapping the next claim). A `sent` row is never
sent again (admins can retry only `failed` rows).

**Not lost while SMTP is down:** while the server is unreachable every attempt is
transient: rows stay `queued`, backing off, and go out when it is back (the Phase 3
acceptance test). The admin page shows queued count, oldest queued time and the last
error meanwhile, and admins see the `email_trouble` banner (§3.1).

**Cleanup** (daily, in `notification_schedule` at the digest hour), in this order:
delete `outbound_email` rows `sent` or `cancelled` more than 30 days ago (by
`updated_at`) and `failed` ones after 90 days; then set `email_mode = 'off'` on
notifications still pending for a digest (`email_mode = 'digest' AND email_id IS NULL`)
that are older than 7 days (this includes those whose digest row was just deleted,
§3.6); then delete notifications older than 90 days. Constants in code, no settings.

### 3.10 Admin: email page

Admin settings → Email (`platform.configure_email`, sessions only), read-only config
plus three actions: test email, retry, retry all failed (no cancel: SPEC asks for
retry, and the send-time checks already cancel what shouldn't go out).

- `get_email_config` maps the settings one to one: `configured`, `host`, `port`,
  `security`, `username_set`, `password_set` (the username is from a Secret and not
  shown either), `from_address`, `from_name`, `reply_to`, `ca_bundle` (path),
  `timeout_seconds`, `links_base_url`, `timezone`, `digest_hour`, `reminder_days`, and
  `outbox: OutboxStats` (`queued`, `sending`, `failed`, `sent_last_24h`,
  `oldest_queued_at`, `last_sent_at`: one grouped query). Not configured: the page shows
  how to set `smtp.host` and `smtp.from` in the Helm values.
- **Test email** (`send_test_email`): 409 `smtp_not_configured` when off. Recipient:
  `to`, or the admin's own address (422 `validation_error` at `["body", "to"]` when
  that is unusable, e.g. the break-glass account's `.invalid` address). At most **5
  per admin per 10 minutes**, counted from `outbound_email` (`type = test`,
  `requested_by_id`), else 429 `too_many_attempts` with `Retry-After` (seconds until the
  oldest counted one is 10 minutes old). Inserts a `test` row (`max_attempts = 1`,
  `to_address` or `recipient_user_id`, `requested_by_id`) and defers it in the same
  transaction; returns 202 with the row. The SPA polls `get_outbox_email` every 2 s for
  up to 30 s: "Sent", the `last_error`, or "Still queued: is the worker running?".
  Content: "This is a test email from Soundings at <links_base_url>", who sent it and
  when; **no server details** (host, port and security are on the admin page, and the
  email may go to any address); no unsubscribe link.
- **Outbox list:** newest first by `(created_at, id)`; filters `status`, `type`
  (repeatable, OR). `OutboxEmail`: `recipient` (`UserRef`) or `address_hint` (masked,
  never the full address), `idea` (`IdeaRef` from its notification; null for digests,
  tests, or when the idea or notification is gone), `requested_by`, attempts,
  timestamps, `last_error`, `retryable`. No subject or body (not stored). The page opens
  on failed emails when there are any.
- **Retryable** = `status = failed` and `created_at` within the maximum age (3 days;
  digests 2 days, §3.9 step 3): older mail would only be cancelled as out of date.
- **Retry** (409 `email_not_retryable` unless retryable): `queued`, `attempts = 0`,
  `next_attempt_at = now()`, `last_error = null`, a job deferred in the same
  transaction. **Retry all failed** does that for every retryable row (the rest stay
  `failed` until the cleanup) and returns the count. Failed rows are kept 90 days for
  support questions; `email_trouble` (§3.1) only looks at the last 24 hours, so old
  failures don't keep the banner up.
- **Audit** (in the same transaction; actor the admin; target none, so no address or
  person is attached): `email.test_send` `{outbound_email_id, to_self}` and
  `email.retry` `{outbound_email_id}` or `{count}` (retry all). These `AuditAction`
  values land at integration with the frontend's audit phrases (§7).

### 3.11 Email content and rendering

- **Templates:** Jinja2 (already a dependency), one HTML and one plain-text template per
  email type, sharing a layout; in the backend package (shipped in the wheel). HTML
  autoescaping on; nothing user-written is ever rendered as HTML or Markdown (titles,
  names and excerpts are escaped text).
- **HTML that survives mail clients:** a table-based layout, max width 600 px, all
  styles inline (no `<style>` dependence, no CSS classes needed), system font stack (no
  web fonts: air-gapped), no images, no external resources, no tracking pixels or
  rewritten links. One bulletproof button (a table cell with a background colour and a
  link). Dark-mode safe: `<meta name="color-scheme" content="light dark">` and
  `supported-color-schemes`, explicit background and text colours on the outer table
  (contrast ≥ 4.5:1 either way), no colour-only meaning. A hidden preheader line.
  `lang="en"`. The **plain-text part** carries the same content with full URLs.
- **Branding (Phase 3):** the app name "Soundings" as a text wordmark and a footer; Phase
  4 branding replaces the name, colour and footer text.
- **Footer:** why you get it ("You're the owner of CUST-12", "You're evaluating …",
  "You watch …", "You were mentioned …"), "Email preferences" →
  `<base>/settings/notifications`, and "Unsubscribe from <type label>" → the unsubscribe
  page.
- **Headers:** `From: "<from_name>" <from>` (built with `email.headerregistry`, never
  by string concatenation), `To` = `Address(addr_spec=<the one checked address>)` (the
  address only; §3.9 step 2: if that raises, the email is cancelled as "unusable
  address"), and the SMTP envelope is `recipients=[that address]`, passed explicitly,
  `Reply-To` when set, `Subject` (CR/LF stripped, titles cut to 80 characters with "…"),
  `Message-ID` (the row's), `Date`, `Auto-Submitted: auto-generated` (RFC 3834), and for
  notification and digest emails `List-Unsubscribe: <<base>/api/v1/unsubscribe?token=…>`
  with `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058; opening that URL
  in a browser redirects to the page, §3.5). Notification emails about one idea should
  also set `References: <idea-<idea id>@<host>>` so clients thread them.
- **Subjects:** `[CUST-12] You're now the owner of "<title>"`; `[CUST-12] Please
  evaluate "<title>" by Fri 9 Oct` (the idea's due date **when the email is sent**; none:
  without "by …"); `[CUST-12] Reminder: your evaluation of "<title>" is due Fri 9 Oct` /
  `… is due today, Fri 9 Oct` (always the date, §3.7); `[CUST-12] All 3 evaluations are
  in for "<title>"`; `[CUST-12] "<title>" moved to Shortlisted`; `[CUST-12] Bob Baker
  commented on "<title>"`; `[CUST-12] Bob Baker mentioned you on "<title>"`; `Soundings
  digest: 5 updates on 3 ideas`; `Soundings test email`.
- **Content rules:** idea key and title, project name, people's display names, status
  labels, due dates, and for comments and mentions a plain-text excerpt of at most 200
  characters (the same text every viewer sees in the feed). **Never:** scores or any
  score data (§1), evaluation comments or recommendations, the idea's summary or
  description, email addresses of others, tokens other than the recipient's own
  unsubscribe link.
- **Links** (absolute, `public_base_url`): idea `/ideas/<KEY>`; evaluation emails
  (`evaluator_invited`, `evaluation_reminder`) `/ideas/<KEY>?evaluate=1`, which opens the
  evaluate sheet (after sign-in: the `next` parameter keeps the query); comments and
  mentions `/ideas/<KEY>#comment-<comment id>`; inbox `/notifications`; preferences
  `/settings/notifications`; unsubscribe `/unsubscribe?token=…`.

### 3.12 Audit, logging and privacy

- Audited: the admin email actions (§3.10: test email, retry, retry all). Not
  audited: notifications, emails sent, preference changes, unsubscribes (none is an
  admin change; the outbox itself is the delivery record).
- Logs: `outbound_email.id`, type, status, attempt, error class and SMTP code only;
  never an exception's message (address parsing and SMTP errors echo addresses).
  Metrics (optional, `app.observability`): sent and failed counters by type and
  transient/permanent, a queued gauge.
- `to_address` is kept only for non-user recipients and goes with the row (30–90 days);
  the API shows it masked. Phase 4's "erase submitter" must also delete that idea's
  outbox rows.
- No email content is stored; the outbox is not a mail archive.

### 3.13 Tests first (minimum)

- **Fan-out:** per type, the recipients and exclusions in §3.3 (the actor, inactive,
  service and break-glass users, someone without `idea.view` — a private project member
  removed, a viewer for evaluator types, an evaluator demoted to viewer — and a watcher
  who unwatched; the owner and evaluators still get `status_changed` after unwatching);
  one notification per person per event; a repeated fan-out inserts nothing (dedupe);
  rollback of the request leaves no notification, outbox row or job; inviting with a
  `due_at` records that date in the invitation (the fan-out runs after the request's
  last write).
- **Preferences:** defaults, an override, resetting to the default deletes the row;
  `immediate` creates an outbox row, `digest` none until the digest, `off` none; SMTP not
  configured → no outbox rows and `email_mode = off`.
- **Outbox:** atomic insert + defer (real Postgres: rollback drops both); claim is
  exclusive (two jobs, one send); transient error → queued with the backoff schedule
  (and its next job), permanent → failed, out of attempts → failed, authentication
  (535) → transient, an exception in rendering → failed "Internal error" at once; an
  attempt over the 4-minute deadline → transient, before the lease expires; the sweep
  re-queues an expired `sending` lease and re-defers lost queued rows **once** (two
  sweeps while the job waits → one sweep job), does nothing with SMTP unconfigured;
  `delete_jobs="successful"` leaves no finished job rows; a row no longer `sending` with
  that attempt isn't overwritten by the record step; SMTP down (connection refused)
  then up → sent with the same Message-ID; at send time access lost, a removed
  evaluator, a reminder past its due time, the type turned `off`, a row older than 3
  days (digest 2) → cancelled without SMTP; a recipient address
  `victim@corp.com,postmaster` (e.g. from SSO claims) → cancelled "unusable address",
  and the SMTP envelope never has more than one recipient. Use a fake SMTP (aiosmtplib
  against a local test server, or a stub of the send function) in unit tests and
  Mailpit in the acceptance test.
- **Digests:** built once per local day at or after the hour (two runs → one email);
  catch-up after a missed hour; read items, now-`off` types and no-longer-viewable ideas
  are left out; items older than 7 days are left out; **a digest pruned by the cleanup
  after 30 days is not sent again** (its items stay out of later digests); no pending
  items → no email; DST day in Europe/London.
- **Reminders:** the worked example of §3.7 (including the moved due date and the
  missed day that isn't caught up), plus: submitted or removed evaluators get none; an
  evaluator demoted to viewer gets none; closed evaluation gets none; overdue gets none;
  a moved due date reschedules; two scans in one hour send one.
- **Mentions:** label rewriting (impersonation), unknown users become plain text, 21
  distinct mentions → 422, a body over 10,000 characters after rewriting → 422, edit
  notifies only new mentions, no mention notification for non-viewers, people without
  a project role, or the author; the 51st mention notification of an author within an
  hour is in-app only (`email_mode = off`).
- **Sessions:** polling `get_notification_summary` doesn't move `last_seen_at`; a
  session idle past its timeout gets 401 from it.
- **Blind safety:** render every email type (HTML and text), every inbox item and a
  digest for an idea with submitted evaluations, an aggregate (e.g. 4.2), disagreement
  and recommendations present, for a pending evaluator and for the owner: no score
  value, no "score", "aggregate" or recommendation text appears.
- **Unsubscribe:** forged, truncated and other-key tokens → 404; GET changes nothing;
  GET with `Accept: text/html` → 303 to `/unsubscribe?token=…`; POST with the RFC 8058
  form body and no cookies works; `digest` and `all` scopes.
- **Admin:** non-admin 403; test email rate limit and `Retry-After`; a `to` with two
  addresses → 422; retry state rules (`retryable`: failed and recent; else 409);
  retry-all skips out-of-date rows; `email_trouble` for admins only, on a failure in the
  last 24 h or a 15-minute-old queued row; audit entries hold no addresses.

### 3.14 Acceptance (SPEC Phase 3) with Mailpit

1. With `SOUNDINGS_SMTP_HOST=<mailpit>`, `_PORT=1025`, `_SECURITY=none`, `_FROM=…` and
   the worker running, Alice (owner) invites Bob as evaluator.
2. Mailpit receives one email to Bob within seconds: subject `[CUST-n] Please evaluate
   "…" by …`, the HTML and text parts, `List-Unsubscribe` headers, and a button linking
   to `<base>/ideas/CUST-n?evaluate=1`. Opening that link signed in as Bob shows the idea
   with the evaluate sheet open.
3. Stop Mailpit; invite Carol. The outbox row stays `queued` with a growing `attempts`
   and a `last_error` like "connection refused" (Admin → Email shows it). Start Mailpit
   again: within the next backoff interval (≤ 2 minutes early on) Carol's email arrives,
   once.
4. No email anywhere contains a score.

The e2e stack runs Mailpit (platform) and the worker; Mailpit's API
(`GET /api/v1/messages`, `GET /api/v1/message/{id}`, `DELETE /api/v1/messages`) reads
the mail back.

## 4. Error codes

New in Phase 3:

| Status | `code` | When |
|---|---|---|
| 404 | `not_found` | an invalid unsubscribe token, or its user is unknown or inactive; someone else's notification; an unknown outbox email |
| 409 | `smtp_not_configured` | test email or retry while email is off |
| 409 | `email_not_retryable` | retrying an email that is not `failed`, or is out of date (older than 3 days; digests 2) |
| 422 | `too_many_mentions` | a comment mentioning more than 20 distinct people |
| 422 | `validation_error` | also: a test email to a reserved (`.invalid`), malformed or multiple address, or to yourself when your address can't receive mail; a comment over 10,000 characters after mention labels are rewritten |
| 429 | `too_many_attempts` | more than 5 test emails per admin in 10 minutes, with `Retry-After` |

## 5. Decisions

Simpler option chosen each time; the lead may revisit (also logged in
[decisions.md](../decisions.md#2026-10-01--phase-3-contract)).

| Decision | Why |
|---|---|
| Emails are **rendered at send time** from the notification rows; the outbox stores no subject or body. | Authorisation must be re-checked at send time anyway, so the content follows what the recipient may see then; template fixes reach queued mail; no message bodies (personal data, idea titles, comment text) sit in the database. Retries can render slightly newer titles, which is fine. |
| The outbox row, not the job, is the source of truth; each attempt is its own `send_email` job; claims use a `sending` status with a 5-minute lease instead of holding `SELECT … FOR UPDATE` across the SMTP conversation, and an attempt must finish within 4 minutes. | No long transactions; "in flight" is visible to admins; a crashed worker's email is re-queued by the sweep; two jobs can never send the same attempt, and a slow live worker can't overlap a re-claim. |
| The job table is bounded: finished jobs are deleted (`delete_jobs="successful"`), failed ones after a week (`remove_old_jobs`), and the sweep re-defers each row at most once (`queueing_lock`) and only while SMTP is configured. | procrastinate keeps every job by default; a per-minute sweep would otherwise add rows for ever, and faster during an outage. |
| At-least-once delivery with a fixed Message-ID. | Exactly-once over SMTP is impossible; a duplicate needs a crash between the server's 250 and our commit, and clients drop it by Message-ID. |
| 12 attempts with capped exponential backoff (30 s doubling to 1 h, jitter), about 5 hours; then `failed` with "Retry all failed". Authentication failures retry too. | Covers SMTP being "briefly down" without hammering it; a password rotation shouldn't fail the whole queue; longer outages are an admin decision, visible on one page. |
| Mail older than 3 days (digests 2) is cancelled at send time and can't be retried; reminders past their due time and types the recipient turned off are cancelled too. | Late mail is worse than none: a reminder after the deadline, an invitation from last week, or mail someone unsubscribed from. |
| Admins are told when email is failing (`email_trouble` on the summary: a failure in the last 24 hours or a queued email older than 15 minutes). | A failure nobody sees is a lost email in practice; the window keeps old failures from nagging. |
| When SMTP is not configured, **no outbox rows** are written (in-app only, `email_mode = off`), not rows parked as "skipped". | Nothing piles up to be sent by surprise when someone configures SMTP months later. |
| Preferences govern **email only**; the inbox always gets everything (unwatching stops follow-type notifications). | One setting per type, as SPEC says; a quiet counter is not an interruption. |
| Defaults: act-on types immediate; status changes and comments in the daily digest. | Invitations and mentions need action; following an idea shouldn't flood anyone. |
| `comment` and `mention` are separate types (SPEC lists "new comment / @mention" as one line). | People want mentions now and comments in a digest. |
| One instance time zone (`SOUNDINGS_TIMEZONE`) and digest hour (`SOUNDINGS_DIGEST_HOUR`) for digests and reminders; reminder offsets `SOUNDINGS_REMINDER_DAYS` (default 2,0). Operator settings, no UI. | Simple beats configurable; one organisation per instance usually shares working hours. Amends the Phase 0 "fixed" reminder schedule only by making it an env setting. |
| Reminder and digest bookkeeping live in `notifications` (dedupe keys, `email_mode`/`email_id`) and the outbox's idempotency key; no extra tables. | Fewer tables; the same uniqueness that dedupes the fan-out makes both jobs idempotent. |
| A reminder goes out only on its own day, phrased as a date; never for overdue evaluations or before the invitation. | No bursts after an outage, and no "due in 2 days" a day before the (moved) due date; overdue items are on My work. |
| The digest collects at most a week of items, and the cleanup turns older pending items off. | Pruned digest rows can't make old items look pending again; SMTP coming back after weeks doesn't send a month of news. |
| Unsubscribe tokens are signed (HMAC, key derived from the secret key), not stored, and don't expire; GET never changes anything; POST is RFC 8058 one-click. | No table; links in old mail keep working; link scanners can't unsubscribe anyone; Gmail and Yahoo require one-click for bulk senders. |
| @mentions are tokens `@[Name](user:<id>)` parsed when the comment is written; labels rewritten to current names; no mentions table. | Unambiguous (no `@ada` collisions), can't impersonate, and the notification rows record who was told. |
| Mention autocomplete reuses `search_users?project=`, and only people with a role in the project are notified; at most 50 mention emails per author per hour (beyond: in-app only). | No new endpoint; the server notifies whom the picker offers, not the whole organisation of an internal project; mentions can't be used to flood mailboxes. |
| The inbox shows only ideas you can view now; `read-all?idea=` lets the idea page clear its notifications. | Lost access hides old titles; visiting an idea is reading its news. |
| The unread count is polled (`get_notification_summary`), capped at 100; the poll doesn't keep the session alive. | No WebSockets/SSE in Phase 3; the count query stays cheap; an open tab must not defeat the idle timeout (Phase 2's break-glass hour included). |
| The SMTP banner flag is `email_available` on the summary (all users), not a field on `CurrentUser`. | Adding a field to `CurrentUser` breaks Phase 1/2 tests and mocks; the preferences page needs the flag too. |
| The test email goes through the outbox with one attempt, and the page polls its row. | Tests the real path (worker, SMTP, TLS) and still gives a quick, specific answer. |
| Emails carry no idea summary or description, only key, title, names, statuses, dates and comment excerpts. | Mail leaves the system; enough to decide to click, nothing confidential beyond what the subject already says. |
| No admin cancel: retry only (of failed mail still recent enough). | SPEC asks for retry; the send-time checks cancel what shouldn't go out; one less state rule and audit action. |
| One recipient per email: every address must be one plain ASCII address and is passed to SMTP explicitly. | A crafted address (`a@x.com,b@y.com`) must not turn one email into several. |
| The SMTP port defaults by security mode (465 for `tls`). | The usual pairing; one less misconfiguration. |
| Outbox rows kept 30 days (failed 90), notifications 90 days; constants, not settings. | Enough for support questions, little personal data at rest. |
| Admin email actions are audited without addresses (`to_self` flag and outbox id only). | Audit entries never hold emails (Phase 2 rule); the outbox row has the address while it lives. |

## 6. Room for later phases

- **Phase 4 (public submission, branding):** `submission_received` (confirmation with
  the tracking link; optional verification) and `submission_status_changed` (opt-in) are
  `EmailType` values already: `to_address` plus an `outbound_email.idea_id` column
  (with a partial index) that Phase 4's migration adds, no notification row, no user
  preferences; the tracking token travels sealed in `payload` (never plain); an opt-out
  link per submission instead of the unsubscribe token; "erase submitter" deletes that
  idea's outbox rows. Branding replaces the wordmark, accent colour and footer text in
  the shared layout.
- **Phase 5 (API keys):** the inbox endpoints accept API keys like My work (contents
  filtered the same way); preferences and admin email stay session-only.
- **Phase 6 (kagent):** AI runs may notify the owner when done (a new type, default
  immediate); service accounts still never receive notifications.
- **Later, if needed:** per-user time zones, push (SSE) for the bell, a "mark unread",
  bounce handling (DSN parsing), a weekly digest. All out of scope now.

## 7. Changes after the contract

Builders record additive contract changes here (date, change, why), then run
`make gen-api`.

**2026-10-01, contract (agreed, not yet in the schema):**

- **`AuditAction` gains `email.test_send` and `email.retry`** (§3.10), one line each in
  `app/schemas/audit.py` plus `make gen-api`. Not added yet: a new value breaks the
  frontend's typecheck until it has a phrase for it (`audit-phrases.test.ts` keeps a
  `Record<AuditAction, true>`). The lead lands the two values in one integration step
  with frontend's phrases (and an "Email" audit category) and backend's `audit.record`
  calls for §3.10; until then backend builds and tests the admin endpoints without the
  audit call.

**2026-10-01, contract review** (applied before any builder started; schema, stubs,
migration `0005` and client regenerated):

- **Added** `NotificationSummary.email_trouble` (admins: email failing, §3.1) and
  `OutboxEmail.retryable` (§3.10).
- **Removed** `cancel_outbox_email` (`POST /admin/email/outbox/{email_id}/cancel`), the
  `email_not_cancellable` code and the planned `email.cancel` audit action; retry
  accepts `failed` rows only.
- **Changed** `EmailTestRequest.to` to `MailAddress`: one plain ASCII address
  (`app.config.MAIL_ADDRESS_PATTERN`, also used for From / Reply-To and at send time).
- **Migration 0005:** dropped `outbound_email.idea_id` and its index (Phase 4 adds
  them); added `ix_notifications_mention_actor` (partial, `type = 'mention'`).
- **Settings:** `SOUNDINGS_SMTP_PORT` unset or empty → 465 for `tls`, else 587.
- **Rules:** digest window and cleanup (§3.6, §3.9), bounded job table and sweep
  locking (§3.9), the 4-minute attempt deadline, one-recipient addresses, send-time
  out-of-date / due / unsubscribe checks, internal-error and authentication handling
  (§3.9), the non-sliding summary poll (§3.2), fan-out after the last write and policy
  rules for type conditions (§3.3), unwatching clarified (§3.3), reminders on their own
  day phrased as dates (§3.7), mention recipients and email cap, length after rewriting
  (§3.8), the unsubscribe URL's 303 for browsers (§3.5), no server details in the test
  email (§3.10).
