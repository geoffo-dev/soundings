# API contract: Phase 11 (talking to public submitters)

Phase 11 is a change the product owner asked for on 2026-10-16
([decisions.md](../decisions.md#phase-11-product-owner-2026-10-16); SPEC.md is read-only).
Trying the app, the product owner asked for an email on the public form "where the link
could be emailed, but also used to contact the submitter", and for the text at the top of
the form to be customisable. Both basics exist since Phase 4 (the optional or required
address, shown when email is set up and visible to admins in the submission panel; the
intro in Project settings → Public form). The two follow-ups the lead offered, which the
product owner accepted ("Yeah maybe have both"), are this phase:

- **(a) "Message the submitter"**: the idea's owner and admins write to the person who sent
  a public idea **through Soundings**, in the project's branding, signed "The <project>
  team", without anyone seeing the submitter's address; the submitter reads and answers on
  their private tracking page; replies notify the team; every team message is audited.
- **(b) The tracking link by email**, once, when the submitter's address is confirmed for the
  first time. The confirmation email itself stays link-free (Phase 4).

Everything in [contract-phase1.md](contract-phase1.md) to
[contract-phase10.md](contract-phase10.md) still applies unless a section below changes it.

Source of truth, in order: the Pydantic schemas (`backend/app/schemas/public.py`, the Phase 11
parts of `notifications.py` and `audit.py`), the route stubs (`backend/app/api/v1/submissions.py`
`list_submission_messages` / `send_submission_message`, `backend/app/api/v1/public.py`
`send_tracking_reply`), the models and migration 0017 (`backend/app/models/public.py`
`SubmissionMessage`, `enums.py`, `notification.py`;
`migrations/versions/20261016_0017_submitter_messages.py`), the rule
(`app/authz/rules.py` `public.message_submitter`, its row and c31 in `app/authz/policy.py`), all
exported to `frontend/src/api/generated/` (`make gen-api`). Rules are named as in
[role-matrix.md](../role-matrix.md) (new: `public.message_submitter` in table G, c31, the trait
`principal.named_person`). Decision record: [ADR 0019](../adr/0019-public-submitter-messages.md).
Tests that pin it: `backend/tests/test_contract_routes.py` (`PHASE11_OPERATIONS`, `STUBS`, the
invalid-request tables), `tests/test_schemas_phase11.py` (text rules, limits, shapes, the rule,
c31, key and guest rows), `tests/test_domain_schema_phase11.py` (the table, constraints and the
migration on data), `tests/authz/test_policy_matrix.py` (the row, every column).

## 1. What changes, in one table

| Area | Change |
|---|---|
| Data | `submission_messages` (one conversation per public submission: `submission_id`, `direction` team \| submitter, `author_id` for team messages, `body`, `emailed`, `created_at`), referencing `public_submissions` with `ON DELETE CASCADE`; email types `submission_link`, `submission_message` (submitter emails: they name their idea) and the notification type `submitter_replied`. Migration **0017** (expand only), head 0017. |
| Submission panel | A **Messages** section for the idea's owner and project and platform admins (`public.message_submitter`, session only): the conversation, a composer, where the message goes ("Emailed and on their tracking page" / "Only on their tracking page"), why sending is impossible when it is. Everyone else sees nothing of it, not even that it exists. |
| Tracking page | A **Messages** section once the team has written: the team's messages as "The <project> team", the submitter's as "You", and a reply box. **"Remove my email address"** (review M2): stops every email about the idea and keeps the link and the conversation. |
| Emails to the submitter | `submission_link` (the tracking link, once, after the first confirmation); `submission_message` (each team message, when the address is confirmed and email is set up). Neither carries a `Reply-To` (review S1); their footer link reads "Stop emails about this idea" and opens the tracking page, where "Remove my email address" is. The confirmation email gains one fixed sentence. |
| Notifications | "The submitter replied" (`submitter_replied`) to the idea's owner and everyone who has written to the submitter: inbox, email (default immediate, at most one an hour per recipient and idea), digest, unsubscribe. Never the reply's text. |
| Audit | `submission.message` for each team message (never the text). |
| Erasure, retention | Erasing the details (all three paths) deletes the conversation and all four submitter email types; retention rule 4 counts the conversation's latest message (in its candidate query: review S3); a new rule 5 sweeps the conversations and submitter emails left on erased submissions (review S2). |
| Copy | The form's email help (what the address is for and that only administrators see it: review M1), the receipt, the confirmation email and the confirm page say the link is emailed once confirmed. |
| Not changed | The intro text (D3: it exists; only its label and the user guide are checked). No settings, no Helm values, no MCP tool, no key access. |

## 2. Endpoints

All under `/api/v1`.

| Operation | Method and path | Rule | Keys | Answer |
|---|---|---|---|---|
| `list_submission_messages` | GET `/ideas/{idea}/submission/messages?cursor=&limit=` | `public.message_submitter` | session only | 200 `SubmissionMessagePage`, **newest first** |
| `send_submission_message` | POST `/ideas/{idea}/submission/messages` | `public.message_submitter` | session only | 201 `SubmissionMessage` |
| `send_tracking_reply` | POST `/public/track/messages` | `public.track` (c9: the token) | public (keys never read) | 201 `TrackedSubmission` (the page, updated) |
| `forget_submission_email` | POST `/public/track/forget-email` (review M2) | `public.track` (c9: the token) | public (keys never read) | 200 `TrackedSubmission` (the page, updated) |

Changed (additive): `get_idea_submission`, `approve_submission`, `erase_submitter` and the
moderation queue (`IdeaSubmission.messages`, `permissions.can_message`); `track_submission`,
`set_submission_updates`, `resend_verification_email` (`TrackedSubmission`: `can_remove_email`,
`messages`, `team_messages_emailed`, `can_reply`, `reply_blocked`);
`verify_submission_email` (`EmailVerified.tracking_link_emailed`; the first confirmation
queues the link email); `submit_public_idea` (no shape change: `email_sent`'s meaning is
described anew); the notification routes and preferences (`submitter_replied`); the audit log
(`submission.message`); Admin → Email (the two new submitter types and the new notification
type in the outbox). **The four new operations return 501** until backend builds them.

Pagination of `list_submission_messages`: the house cursor (`items`, `next_cursor`), ordered
`(created_at, id)` **descending**; `limit` 1-200 (default 50, as everywhere). The panel shows
the first page oldest at the top and loads earlier messages with `next_cursor` ("Show earlier
messages"). A conversation holds at most 100 messages, so `limit=100` reads it all.

### 2.1 Order of checks and locks

**Team routes** (`list_submission_messages`, `send_submission_message`):

1. 401 (no session; an API key on these routes: 403 `insufficient_scope` from
   `ROUTE_KEY_ACCESS` before anything else, whatever the key's scopes; an agent's key is
   refused on REST anyway, c22).
2. 404: the idea (`idea.view`: NMp, a guest researcher through `RESEARCH_GUEST_ACCESS`, an idea
   held for **email confirmation** for everyone), then "didn't come through the public form"
   (no `public_submissions` row; `idea.view` holders can tell that already from
   `get_idea_submission`).
3. 403 `forbidden`: `public.message_submitter` (members, viewers, internal non-members, a
   demoted owner), then c31 (the break-glass account, an AI agent's service account).
4. 422: the body (FastAPI validates it before the route runs, so a malformed body is 422 even
   where a later step would refuse; `limit` and `cursor` too: 422 / 400 `invalid_cursor`).
5. Send only, 409: `project_archived` (the archived project leads the 409s, as in the policy:
   review C6), then `submitter_erased`, then `public_submission_off` (the instance's
   `SOUNDINGS_PUBLIC_SUBMISSION_ENABLED` is off, so no tracking link opens and nobody could
   read or answer: review C4), then `conversation_full`.
6. Send only, 429 `too_many_attempts` with `Retry-After`: 20 team messages to this submission
   in 24 hours, then 30 messages of yours an hour (section 5).

The idea may be **closed** or **held for moderation** (c19 doesn't apply: a moderator may ask
before approving). Reading works in an **archived** project; sending is 409 there.

Send locks project (`FOR KEY SHARE`) → idea (`load_idea(for_update=True)`) → submission
(`FOR UPDATE`), then counts the limits, inserts the message, queues its email (section 7)
and audits it, in one transaction. The per-submission counts are therefore exact; the
per-person count is read in the same transaction but not serialised across submissions (two
sends at the same moment to two submissions may both pass at 29; the session write limit of
120 a minute bounds it).

**Public reply** (`send_tracking_reply`), in order: 415 `unsupported_media_type` (not JSON;
`JsonOnlyRoute`) → 422 (body) → 429 the tracking routes' shared per-IP throttle
(`PUBLIC_TOKEN_THROTTLE`, 60 a minute, before the token is looked up) → 404 (c9: unknown or
erased token, or public submission off for the instance; one answer for all) → 429 30 replies
per client address an hour (a new in-process throttle `("public_reply", 30, 3600)` keyed by
`client_key`, counted for every attempt that got past the token) → 409 `project_archived`,
`awaiting_team` (the team hasn't written, or 10 replies since its latest message: review
S6), `conversation_full` → 429 10 replies per submission in 24 hours (counted in the
database) → insert, queue the notifications (section 6), answer 201 with the tracking
page. It locks as every tracking write does (`tracking.find(lock=True)`: project → idea →
submission). Not audited (no actor; the row is the record). Refusals are logged like the
other public routes (`public reply refused`, `reason=rate_limited`, never the address, token
or text).

**"Remove my email address"** (`forget_submission_email`, review M2), in order: 415 → 422
(`TrackingRequest`: the token only) → 429 the shared per-IP throttle → 404 (c9) → 409
`awaiting_confirmation` while the idea is held for email confirmation (that address is what
sends it to the team: "Your idea reaches the team once you confirm this address. To withdraw it,
delete your details.") → 200 with the tracking page. Without an address on file: 200, nothing
changes (idempotent). Locks as every tracking write (`tracking.find(lock=True)`). It does
exactly what retention rule 3 does to an unconfirmed address: `email`, `email_verified_at`
null, `wants_updates` false, and the idea's outbox rows of every `SUBMITTER_EMAIL_TYPES` type
deleted, queued and sent (no address lingers in the outbox). The link, the idea and the
conversation stay; team messages then reach the tracking page only (`delivery:
tracking_page`, `team_messages_emailed` false). Not audited (like rule 3 and the updates
switch); never logs the address.

## 3. Messages

- **One conversation per public submission** (`submission_messages`, keyed by the submission;
  one submission per idea). A message is `team` (written through the panel by a holder of
  `public.message_submitter`; `author_id`) or `submitter` (a reply on the tracking page; no
  author).
- **Plain text only** (`MessageBody`, `app/schemas/public.py`): 1-4,000 characters with at
  least one visible one (`VisibleText`: NUL and Unicode tag characters are a 422, other
  invisible characters are removed, the ends trimmed); `\r\n`, `\r`, U+2028 and U+2029 become
  `\n`. Never
  rendered as Markdown or HTML anywhere: the SPA shows it with its line breaks as plain text
  (no autolinking: a submitter's text is **untrusted public input** everywhere, and the
  team's is shown to the public), emails escape it (HTML: escaped with `<br>` for line
  breaks; text part as is). Never logged, audited, put in a notification, the feed, search,
  an export or an MCP result.
- **The public never starts a conversation**: the submitter may reply only after the team
  has written (409 `awaiting_team`; the tracking page shows no Messages section until then),
  and at most **10 replies after each team message** (review S6: then `awaiting_team` again
  until the team writes back), so the replies, and the notifications they send the team, stay
  what the team invited, and the submitter alone can't fill the conversation.
- **At most 100 messages** in a conversation, both directions (409 `conversation_full`; review
  C1: one cap, and the tracking page shows them all).
- **Held ideas**: held for moderation, the moderators (project and platform admins, who see
  it, c12) may message and the submitter may reply (useful to ask before approving; c19
  doesn't apply); held for email confirmation: 404 for the team as today (nobody sees it),
  and the submitter can't reply (`awaiting_team`, since nobody could have written).
- **Closed ideas**: allowed both ways. **Archived project**: reading only (409
  `project_archived` both ways; the tracking page says "The team isn't taking messages about
  this idea any more"). **Public submission off for the instance**: the panel reads, sending
  is 409 `public_submission_off` (no tracking link opens; review C4).
- **Erased details**: the conversation is deleted with them (section 10); sending is 409
  `submitter_erased` ("Their details were erased: there's no one to write to."); the panel
  says so; the tracking link no longer works (404).
- **Delivery** (`SubmissionMessagesSummary.delivery`): every team message appears on the
  submitter's tracking page; it is **also emailed** (`submission_message`, section 8) when the
  submission has an address that is confirmed (`email` and `email_verified_at` set) and email
  is set up (`smtp_configured`), whatever `wants_updates` says (that switch is for automatic
  status emails; the address was given "for the team to contact them about this idea"; to
  stop all email the submitter removes the address on the tracking page, review M2).
  Otherwise the panel says before sending "They'll see it only on their tracking page." The
  reason isn't given (no address, unconfirmed, removed, email off): contact details are
  `public.erase_submitter`'s, and the owner may not hold that. `SubmissionMessage.emailed`
  says, per team message, whether an email was **queued** for it: the panel says "Email
  queued", never "Emailed" (the send may still fail, which only Admin → Email shows; review
  C10).
- **The tracking page** (`TrackedSubmission.messages`): the whole conversation, oldest first
  (100 at most); team messages as "The <project name> team", the submitter's as "You";
  `team_messages_emailed` says whether the team's messages also reach their inbox ("We'll
  also email you when the team writes."); `can_reply` / `reply_blocked` (`project_archived`,
  `awaiting_team`, `conversation_full`, `daily_limit`, in the order they are checked) decide
  the reply box; the Messages section shows whenever `messages` isn't empty. `awaiting_team`
  with messages: "You can reply again once the team writes back." `can_remove_email` offers
  "Remove my email address" (a confirmation dialog: "We'll stop emailing you about this idea
  and delete your address. Your link and your messages stay. You can't add an address again.").
- **Not in** the feed, search, ⌘K, My work, MCP, the proposal and bid exports or the idea's
  `last_activity_at` / `updated_at` (a hidden conversation must not move the idea in
  "recently updated" sorts or reveal itself to members); not in `IdeaDetail` either.
- The panel's composer is a **plain textarea** (review S5): no @mention picker, no toolbar, no
  Markdown preview (a comment composer's `@[Name](user:<id>)` tokens would send a colleague's
  name and id to the public); text that looks like a mention is sent as typed and notifies
  nobody. It saves its unsent text as a draft (`lib/drafts.ts`, `draftKey(user,
  "submission-message:<idea id>")`) and sends with Ctrl/Cmd+Enter. The tracking page's reply
  box is a plain textarea too.
- **Rendering** (review C8): every message keeps its line breaks and wraps anywhere
  (`whitespace-pre-wrap wrap-anywhere`) and each message's box clips what overflows it
  (`overflow-hidden`: a letter with thousands of combining marks can't paint over the page),
  in the panel and on the tracking page. The schema turns U+2028 and U+2029 into `\n`.
- **Double submits** (review C9): Send and Reply stay busy while their request runs (`Button
  loading`; Ctrl/Cmd+Enter does nothing meanwhile); the server doesn't deduplicate, so a retry
  after a lost answer may send twice.

Example, `send_submission_message`:

```http
POST /api/v1/ideas/CUST-21/submission/messages
Content-Type: application/json

{"body": "Thanks, Sam! Which stores did you have in mind?\nWe'd like to try it in two."}
```

```json
HTTP/1.1 201 Created
{
  "id": "5d6f8a1e-3b2c-4e7d-9a10-2c4b6e8f0a13",
  "direction": "team",
  "body": "Thanks, Sam! Which stores did you have in mind?\nWe'd like to try it in two.",
  "created_at": "2026-10-16T10:12:00Z",
  "author": {"id": "…", "display_name": "Priya Raman", "avatar_url": null, "initials": "PR"},
  "emailed": true
}
```

`get_idea_submission` for a holder (admin) then carries:

```json
"permissions": {"can_moderate": false, "can_erase": true, "can_message": true},
"messages": {
  "count": 2,
  "last_message_at": "2026-10-16T11:40:00Z",
  "last_direction": "submitter",
  "delivery": "email",
  "blocked": null
}
```

and for a member `"messages": null` with `"can_message": false`.

`send_tracking_reply`:

```http
POST /api/v1/public/track/messages
Content-Type: application/json

{"token": "Zq3v9Xb2Lk7Wm4Np8Rt6Yc1Hd5Gf0Js_Ua-Ee2Oo4Ii", "body": "All of them, ideally."}
```

→ 201 with the tracking page, whose new fields read:

```json
"messages": [
  {"id": "…", "direction": "team", "body": "Thanks, Sam! Which stores…", "created_at": "…"},
  {"id": "…", "direction": "submitter", "body": "All of them, ideally.", "created_at": "…"}
],
"team_messages_emailed": true,
"can_reply": true,
"reply_blocked": null
```

## 4. Who: `public.message_submitter` (role matrix table G, c31)

| | PA | PAd | Mem | Vwr | NMi | NMp | Pub | +Own | +Evl | R |
|---|---|---|---|---|---|---|---|---|---|---|
| `public.message_submitter` | Y | Y | 403 | 403 | 403 | 404 | 401 | + | · | 404 |

- Reading **and** writing the conversation, and `IdeaSubmission.messages` /
  `permissions.can_message`. The idea's **owner** holds it while they hold member or admin
  (the overlay rule of section 1); project and platform admins always.
- **Session only**: not in `RULE_SCOPES`; `ROUTE_KEY_ACCESS` rows `session` (any key, every
  scope: 403 `insufficient_scope`); no MCP tool. The submitter's reply route is `public`.
- **c31, a named person** (`app.authz.is_named_person`, trait `principal.named_person`):
  never an AI agent's service account, never the break-glass account (403 `forbidden`;
  `NAMED_PEOPLE_ONLY`). The break-glass account is a platform admin (column PA) but an
  emergency login, not someone a submitter's conversation should come from; an agent holds no
  admin role or ownership anyway. Neither reads the conversation's text (`messages` null; the
  routes 403). The break-glass account, a platform admin, still sees the `submission.message`
  audit entries and the outbox rows in Admin → Email (type, masked address), like every
  platform admin, but never a message's text (review C13).
- **Not an idea write** (`idea_write` false): reading works in an archived project and on a
  held or closed idea; sending's refusals (`project_archived`, `submitter_erased`,
  `public_submission_off`, `conversation_full`, the limits) are the service's 409s and 429s,
  not conditions. Not in `FROZEN_WHILE_HELD` (c19 doesn't apply).
- **Guest researcher (R)**: 404 (`RESEARCH_GUEST_ACCESS` hides both routes; the submission
  panel is hidden already).

The outcome per principal kind for every new route is the role matrix's
[table G notes](../role-matrix.md#g-public-submission) ("Phase 11: who reaches the
conversation"), which the access-table tests follow.

## 5. Limits (constants, not settings; `app/schemas/public.py`)

| Limit | Value | Where counted | Refusal |
|---|---|---|---|
| Message length | 1-4,000 characters | schema + `ck_submission_messages_body_length` | 422 |
| Messages in a conversation (both directions) | 100 (review C1) | database, under the submission lock | 409 `conversation_full` |
| Team messages to one submission | 20 in any 24 hours | database (`ix_submission_messages_submission_id_created_at`) | 429 `too_many_attempts`, `Retry-After` |
| Messages one person sends to public submitters | 30 in any hour, all ideas | database (`ix_submission_messages_author_id_created_at`) | 429 `too_many_attempts`, `Retry-After` |
| Replies to one submission | 10 in any 24 hours | database | 429 `too_many_attempts`, `Retry-After` |
| Replies since the team's latest message | 10 (review S6) | database, under the submission lock | 409 `awaiting_team` (until the team writes) |
| Replies from one client address | 30 in any hour | in-process throttle (trusted-proxy address, IPv6 per /64; no address is stored) | 429 `too_many_attempts`, `Retry-After` |
| Tracking routes, shared | 60 a minute per client address | in-process (Phase 4) | 429 `too_many_attempts` |
| "The submitter replied" email | one immediate email per recipient and idea an hour | the inbox index `ix_notifications_user_id_created_at` (the recipient's last hour; review C3) | later ones inbox only |

`Retry-After` is the whole seconds until the oldest counted message leaves the window (at
least 1). **Code**: `too_many_attempts`, as every other per-action limit (AI runs, exports,
uploads, the public routes); `rate_limited` stays the session-write limiter's (120 a minute),
which applies on top. The panel words them: "You've sent 20 messages to this person today.
You can write again tomorrow." / "You've sent a lot of messages in the last hour. Try again
in a few minutes."; the tracking page: "You've replied 10 times today. You can reply again
tomorrow." `SendBlocked.daily_limit` / `ReplyBlocked.daily_limit` say it before anyone types.
`SUBMITTER_MESSAGES_SINCE_TEAM_MESSAGE` is the S6 constant.

## 6. "The submitter replied" (`submitter_replied`)

| | |
|---|---|
| Label | "The submitter replied" (preferences, Admin → Email, the unsubscribe page) |
| To | the idea's **owner** and **everyone who has sent a team message** in that conversation (`author_id`s), deduplicated, each **holding `public.message_submitter` when it is written and again when it is shown or sent** (so a member who left the project, or an owner who lost the role, stops getting them). The usual exclusions: inactive, service and break-glass accounts never (c31 means they never wrote either). May be nobody (an unowned idea whose writers lost the rule): the panel still shows the reply. |
| When | each reply, queued by the reply service (`app/notifications/submitter.py`, a before-commit hook through the usual `NotificationWriter`, like Phase 10's bid notifications), **not** from feed events (there are none). **Not while the idea is held for moderation** (lead default: held ideas are in nobody's inbox, role matrix 2c; the moderation queue shows "They replied" from `messages.last_direction`, so a moderator who asked before approving learns of the answer there and nowhere else: accepted, review C5). |
| Shown (the inbox, SQL) | `inbox.py` `_mine` (the list) and `_unread_count` (the bell) filter in SQL, so the rule's **SQL form** is named here (review S4): a `submitter_replied` row is shown and counted only while the caller is a platform admin, or holds `admin` in the idea's project, or is the idea's owner (`ideas.owner_id`) with `member` there (`project_effective_roles`, groups included): exactly the "manager" predicate `_bid_items` already uses for `assessments_complete`, reused, plus `viewable_ideas` as for every type (held ideas are in nobody's inbox). An owner demoted to viewer, a writer who left a private project or lost the admin role, and anyone else see no item and a count of 0 (test: a writer who left the project). The reply needn't still exist: after an erasure the item stays and the panel says the details were erased. The fan-out, the digest build and the send-time check use the Python form (`access.applies`: `can(PUBLIC_MESSAGE_SUBMITTER)` on the live facts), which must agree with the SQL form. |
| Dedupe | `submitter_replied:<message id>` per recipient; `payload` = `{"message_id": "<id>"}` (never text). |
| Email | default **immediate**; **at most one immediate email per recipient and idea an hour** (`SUBMITTER_REPLIED_EMAIL_INTERVAL`): a later reply within the hour of the last one that was emailed is written with `email_mode = 'off'` (inbox only). Digest recipients get one line per reply. Someone who had every type off gets it off (migration 0017). Unsubscribe scope `submitter_replied`. |
| Inbox (`SubmitterRepliedNotification`) | no fields beyond the base (`actor` always null); the SPA says "The person who sent CUST-21 through the public form replied to the team." Link `/ideas/{key}?submission=1` (the idea at its submission panel's Messages). |
| Email text | Subject `[CUST-21] The submitter replied about "<idea title>"` (the idea's title as for every notification, `subject_title`). Body: "The person who sent CUST-21 through the public form replied to the team." Button **Read the reply** (`/ideas/CUST-21?submission=1`). Reason: "You get this because you own CUST-21 or have written to the person who sent it." Unsubscribe line "replies from public submitters". Global branding (an email to staff). |
| Digest line | "The submitter replied" (no actor). |
| Send-time checks | still holds the rule; the reply still exists (an erasure deleted it: cancelled "no longer applies"); the idea not held for moderation. |
| Never | the reply's text, the submitter's name or address, the team's text: the reply is untrusted public input, and a notification carrying it would be a phishing channel into staff inboxes. |

`SUBMITTER_NOTIFICATION_TYPES` (`app/schemas/notifications.py`) lists it; it is **not** in
`RESEARCH_GUEST_NOTIFICATION_TYPES` or `BID_NOTIFICATION_TYPES`.

## 7. The tracking-link email (`submission_link`, D1)

- **Queued** in the same transaction when `verify_submission_email` moves `email_verified_at`
  from null to now (the **first** confirmation), and only when email is set up
  (`smtp_configured`) and the submission still has its sealed tracking token. Never on a
  repeated confirmation (`EmailVerified` 200 again), a resend, at submission, or by the
  hourly cleanup; **nothing retroactive** (submissions confirmed before 0017 get none; the
  migration backfills nothing). Idempotency key `submission_link:<submission id>`, so at most
  one ever. Not limited by the per-address confirmation limit (it goes only to an address that
  proved itself, once per submission). Sent whatever `wants_updates` says (it is their link).
- **`EmailVerified.tracking_link_emailed`**: true when **this** confirmation queued it; the
  page then says "We've emailed you a private link to follow your idea." False on a repeat
  and without email.
- **Rendered at send time** from the submission (`app/public/emails.py`): cancelled ("no
  longer applies") when the submission was erased, its address changed or was removed (rule 3
  or "Remove my email address", which also delete the row), it is no longer confirmed or the
  token is gone.
- **Why it is safe** (ADR 0019): the confirmation email can't carry the link, because anyone
  can type anyone's address into the form, and whoever opens that email would read what a
  stranger typed on our domain in our branding. The link email goes only to an address that
  has **proved itself by clicking Confirm**, exactly as status emails already carry the link
  (Phase 4). The address owner is then, by our own definition, the submitter.
- Rows: `to_address` = the confirmed address, `idea_id` = the idea, `payload` = `{}`.

## 8. Emails to the submitter: the exact fixed text

Every submitter email uses the project's effective branding, one plain ASCII recipient, no
`List-Unsubscribe` and no unsubscribe token (the tracking page is the opt-out), `idea_id` set,
`to_address` the address, and names **no person** (public pages and submitter emails never
show people). **No `Reply-To` on the two new types** (review S1): `EmailContent` gains a flag
(`allow_reply_to`, default true) that `submission_link` and `submission_message` set false, so
`build_message` leaves `SOUNDINGS_SMTP_REPLY_TO` out (a reply would otherwise carry the
submitter's address and text into an operator mailbox that erasure never reaches, against
"Replies to this email aren't read"); Phase 4's two types keep it, unchanged. Subjects go
through `render()`'s `clean_subject` like every subject, so a line break in a project name
becomes a space (review C7: nothing to add). The new types' footer link (`stop_url`, the
tracking page) reads **"Stop emails about this idea"** (an `EmailContent` label next to
`stop_url`; status emails keep "Stop these emails", which their switch does).

`<project>` = the project's name, `<title>` = the title **as they sent it**
(`submitted_title`), `<tracking>` = `<public base URL>/track#<token>` (the token only in the
fragment, unsealed at send time). Without a sealed token (seeded demo submissions only) the
button and the stop link are left out, as status emails do.

**Confirmation email (`submission_received`), one sentence added** after "what confirming
does": "Once you confirm, we'll email you a private link to follow your idea." Still no
tracking link and nothing the submitter typed.

**`submission_link`**

- Subject: `Your link to follow your idea for <project>`
- Preheader: `Your private link to follow the idea you sent to <project>.`
- Heading: `Your link to follow your idea`
- Body: `Thanks for confirming your address. This is your private link to follow the idea you
  sent to <project>, "<title>":`
- Button: **See where your idea stands** → `<tracking>`
- Line: `Keep this link private: anyone who has it can see where your idea stands, reply to
  the team and delete your details.`
- Footer reason: `You confirmed this address on the public idea form of <project>.`; stop link
  (`EmailContent.stop_url`) → `<tracking>` ("Stop emails about this idea": review M2).

**`submission_message`**

- Subject: `A message about your idea for <project>`
- Preheader: `The <project> team wrote to you about your idea.`
- Heading: `A message from the <project> team`
- Body: `About your idea "<title>":`, then the message text (escaped; line breaks kept), then
  `The <project> team` (never a person's name or address).
- Button: **Reply** → `<tracking>`
- Line: `Replies to this email aren't read: reply on your tracking page.`
- Footer reason: `You sent an idea to <project> through its public form.`; stop link →
  `<tracking>` ("Stop emails about this idea") with the line `To stop all email about this
  idea, remove your email address on your tracking page.` (review M2: that keeps the link and
  the conversation; "Delete my details" would end both).
- Payload `{"message_id": "<id>"}` only; idempotency key `submission_message:<message id>`;
  rendered at send time from the message (an erased conversation cancels it: "no longer
  applies"); checks as for status emails (not erased, still that address, still confirmed),
  except that an idea held for moderation **is** allowed. `SubmissionMessage.emailed` = queued.

**The tracking page, receipt and form copy** (frontend): the form's email help (review M1:
administrators do see the address, so the old line "We never show it to anyone else." is
not used): optional address "We'll ask you to confirm it, then email you your private link to
follow your idea. The team may also use it to contact you about this idea. Only
administrators can see your address."; required address "We email you a link to confirm your
idea; it reaches the team once you do. Then we'll email you your private link to follow it,
and the team may use your address to contact you about this idea. Only administrators can see
your address."; the receipt with `email_sent`: "Once you confirm your address, we'll email you
this link too."; the confirm page with `tracking_link_emailed`: "We've emailed you a private
link to follow your idea."; the tracking page's email section: the "Remove my email address"
button (`can_remove_email`) with the dialog of section 3, and after it "We don't have an email
address for you any more. Check this page for news." (the section then shows no switch).

`SUBMITTER_EMAIL_TYPES` (`app/models/enums.py`) is the one list of submitter email types:
the outbox's `ck_outbound_email_idea_iff_submission_type`, erasure, retention rule 3,
branding's submitter lookup (`app/services/branding.py`), the send-time renderer and Admin →
Email use it (builders replace their own copies).

## 9. Audit

`submission.message` per team message: actor = the sender, target = the idea
(`target_type: "idea"`), `project_id`, `details` = `{"rule": "public.message_submitter",
"message_id": "<id>", "emailed": true|false}`; never the text, the submitter's name or
address. Replies are not audited (no actor; the row is the record). The SPA phrase: "<Actor>
messaged the submitter of <KEY>" (category Public submissions); the mock list and the
exhaustive `Record` in `audit-phrases.test.ts` gain it.

## 10. Erasure and retention

- **Erasure** (all three paths: the admin's `erase_submitter`, the submitter's "Delete my
  details", retention rule 4; `app/public/erasure.py`) also **deletes the whole conversation**
  (`DELETE FROM submission_messages WHERE submission_id = …`) and the idea's outbox rows of
  every `SUBMITTER_EMAIL_TYPES` type, queued and sent (`submission_link` and
  `submission_message` too). `submitter_replied` notifications stay (they hold no text); their
  queued emails are cancelled at send time (the reply is gone).
- **Rule 3** (an unconfirmed address forgotten after 3 days) keeps the conversation (the
  tracking page still works) but message emails stop (no address: `delivery` becomes
  `tracking_page`); its delete of submitter emails uses the one list. **"Remove my email
  address"** (`forget_submission_email`, review M2) does exactly the same on the submitter's
  request, for a confirmed address too (section 2.1).
- **Rule 4** (closed idea, 180 days without activity) counts the conversation's **latest
  message** as activity too: a submission is erased only when `ideas.last_activity_at` **and**
  its newest message are older than 180 days. The `NOT EXISTS (… submission_messages WHERE
  submission_id = s.id AND created_at >= now() - 180 days)` (on
  `ix_submission_messages_submission_id_created_at`) belongs **in the candidate `SELECT`**
  (review S3: checked only in the loop, 500 closed ideas with live conversations would fill
  every batch and nothing else would ever be erased) **and again after the idea and submission
  are locked** (a reply takes the same locks, so one committed in between is seen then). Test:
  with `BATCH = 1`, a live conversation on the oldest closed idea doesn't stop the next one
  from being erased.
- **Rule 5 (new, belt and braces)**: the hourly cleanup deletes, for submissions already erased
  (`erased_at` set), their messages **and the idea's outbox rows of every
  `SUBMITTER_EMAIL_TYPES` type** (review S2: `ix_outbound_email_idea_id`), batched like the
  other rules. Nothing should be left, but an erasure made by the previous release during a
  rollback window (section 17) leaves its conversation and its `submission_link` /
  `submission_message` rows, whose `to_address` is the erased address (0.3.0's erasure knows
  two types only).
- **Deleting the idea or rejecting it in moderation** deletes the conversation with the
  submission (cascade).

## 11. Where a message, or that one exists, could leak (tests: section 14)

| Surface | Holder of the rule | Everyone else (member, viewer, NMi, guest R, agent, break-glass, keys) |
|---|---|---|
| `get_idea_submission`, the moderation queue | `messages` summary, `can_message` | `messages: null`, `can_message: false` |
| `list_submission_messages`, `send_submission_message` | 200 / 201 | 403 (Mem, Vwr, NMi, c31), 404 (NMp, R), 403 `insufficient_scope` (keys), 401 |
| `get_idea` (`IdeaDetail`), board, lists, search, ⌘K, My work | nothing new | nothing new |
| The feed | no event | no event |
| `last_activity_at`, `updated_at`, "recently updated" sorts | unchanged by messages | unchanged |
| Notifications, their emails, digests | `submitter_replied`, no text | none |
| MCP (every tool) | no tool; `get_idea` unchanged | the same |
| Proposal and bid exports | not included | not included |
| Another submission's tracking page | only that submission's conversation (its token) | the same |
| Audit log, Admin → Email | platform admins, the break-glass account included, see `submission.message` entries and the outbox rows (type, masked address), never a message's text (review C13) | not visible (platform only) |

## 12. Changed shapes (additive)

| Schema | Change |
|---|---|
| `IdeaSubmission` | `messages: SubmissionMessagesSummary \| null` (null unless you hold the rule) |
| `IdeaSubmissionPermissions` | `can_message` (the rule and `messages.blocked` null) |
| `SubmissionMessagesSummary` (new) | `count`, `last_message_at`, `last_direction`, `delivery` (`MessageDelivery`: `email`, `tracking_page`), `blocked` (`SendBlocked`, in the order checked: `project_archived`, `submitter_erased`, `public_submission_off`, `conversation_full`, `daily_limit`) |
| `SubmissionMessage`, `SubmissionMessagePage`, `SubmissionMessageCreate` (new) | the team's view (`author`, `emailed`) and the request (`body`) |
| `TrackedSubmission` | `can_remove_email` (review M2), `messages: TrackedMessage[]` (no author; the whole conversation), `team_messages_emailed`, `can_reply`, `reply_blocked` (`ReplyBlocked`, in the order checked: `project_archived`, `awaiting_team`, `conversation_full`, `daily_limit`) |
| `TrackingReplyRequest` (new) | `token`, `body` (`forget_submission_email` takes Phase 4's `TrackingRequest`) |
| `EmailVerified` | `tracking_link_emailed` |
| `PublicSubmissionReceipt` | descriptions only (`email_sent`: the link follows the confirmation) |
| `PublicFormSettings`, `PublicFormSettingsUpdate` | descriptions only (`intro_md`: "The text shown at the top of the public form") |
| `MessageDirection` (new) | `team`, `submitter` |
| `NotificationType`, `EmailType`, `UnsubscribeScope`, `NotificationPreferencesUpdate`, `NotificationItem` | `submitter_replied` (`SubmitterRepliedNotification`); `EmailType` also `submission_link`, `submission_message` |
| `AuditAction` | `submission.message` |

## 13. Error codes

New: `submitter_erased` (409), `public_submission_off` (409, a team message while the
instance's public submission is off), `conversation_full` (409), `awaiting_team` (409, the
public reply before the team wrote or after 10 replies since its latest message),
`awaiting_confirmation` (409, "Remove my email address" while the idea waits for that
address's confirmation). Reused: `project_archived` (409), `too_many_attempts` (429),
`not_found`, `forbidden` (the rule and c31), `insufficient_scope` (keys), `unauthorized`,
`validation_error`, `unsupported_media_type` (415), `invalid_cursor` (400).

## 14. Minimum tests (tests first)

- **Access table** over principal kinds (the idea's owner as member, a demoted owner, a
  project admin, a platform admin, a member, a viewer, an internal non-member, a private
  non-member, a guest researcher, an AI agent's service account, the break-glass account, a
  person's API key with each scope alone and all four, anonymous) × the two team routes and
  `get_idea_submission` / the moderation queue (`messages`, `can_message`): the outcomes of
  section 11 and the role matrix's table G notes; and × every place a message or its existence
  could leak (section 11's rows: idea detail, the feed, notifications and emails, digests,
  search, ⌘K, My work, MCP tools, exports, `last_activity_at` ordering, another submission's
  tracking page).
- **Holds and states**: held for moderation (admins message, submitter replies, no
  notification), held for email confirmation (404 / `awaiting_team`), closed (allowed),
  archived (read 200, send 409 both ways), erased (`submitter_erased`, list empty, link 404),
  public submission off for the instance (read 200, send 409 `public_submission_off`); the
  409s in their order when several apply (archived first).
- **The tracking-link email**: queued on the first confirmation only (not on the repeat, a
  resend, at submission, without email, after erasure); never in the confirmation email
  (whose text gains only the sentence); rendered at send time and cancelled by erasure or a
  forgotten address; `tracking_link_emailed` true only on the first; no backfill.
- **The public reply route**: token checks (unknown, erased, instance switch off: 404),
  `can_reply` and each `reply_blocked`, the throttles (shared per-IP, 30 an hour per address
  with a forwarded address the stack trusts, 10 a day per submission), the 11th reply since
  the team's latest message (409 `awaiting_team`; the team writes, a reply works again), JSON
  only (415), the body rules (422), 201 with the page.
- **"Remove my email address"**: token checks (404), JSON only, 409 `awaiting_confirmation`
  while held for confirmation, 200 and nothing changed without an address; afterwards no
  address, no confirmation, no opt-in, no outbox row of any submitter type for the idea
  (queued or sent), `delivery: tracking_page`, the link and the conversation still there, a
  confirmation link for the old address 404.
- **The limits**: 20 / 24 h per submission, 30 / h per person across ideas, 100 per
  conversation, `Retry-After`; concurrent sends to one submission never pass 20 (the lock).
- **Erasure completeness**: after each of the three paths, no `submission_messages` row and no
  outbox row of any `SUBMITTER_EMAIL_TYPES` type for the idea; rule 5 deletes a conversation
  and `submission_link` / `submission_message` rows left on an erased submission (as 0.3.0's
  erasure leaves them).
- **Retention**: rule 3 keeps the conversation and stops the emails; rule 4 skips a closed idea
  whose conversation had a message in the last 180 days, erases once both are older, and with
  `BATCH = 1` a skipped idea doesn't block the next (the `NOT EXISTS` is in the candidate
  query); a reply committed between the candidate query and the lock is seen.
- **Notifications**: recipients (owner + writers, deduplicated, re-checked at write and send:
  a writer who left the project, a demoted owner, a deactivated user get nothing; the
  break-glass account and agents never), the hourly coalescing (second reply within the hour:
  inbox only; after the hour: emailed again), digest lines, unsubscribe scope, no text in the
  inbox item, the email or the digest; no notification while held for moderation; the inbox's
  SQL form: a writer who left the private project (and a demoted owner) sees no item and an
  unread count of 0.
- **No mentions** (review S5): a team message whose body is `@[Name](user:<id>)` is stored and
  emailed as typed and notifies nobody (no `mention` notification, no watcher added).
- **No `Reply-To`** (review S1): with `smtp_reply_to` set, `submission_link` and
  `submission_message` have no `Reply-To` header; the other emails keep it.
- **No submitter email names a person**: render every submitter type with a team message from
  a named person and check the HTML and text parts for the author's name and address.
- **Rendering**: a message with `<script>`, Markdown, links and line breaks arrives escaped in
  the email (HTML and text) and as plain text in the SPA (no anchors).
- **Audit**: one `submission.message` per team message, no text in `details`; none for
  replies.

## 15. Demo data (backend's seed)

CUST-21 ("Reusable delivery boxes with a deposit", approved from the public form; Sam
Okafor's confirmed address) gets a short conversation, written straight in the database by
the seed (it reads no SMTP settings and CUST-21 has no tracking link, so no email is queued):
a team message from **priya** (a Customer Innovation admin) "Thanks, Sam! Which of our stores
did you have in mind? We'd like to try it in two first." and, an hour later, Sam's reply "The
two in the city centre see the most deliveries. Happy to help with the trial." CUST-21 has no
owner and keeps none (an owner would change My work's and the board's counts that e2e reads);
priya gets one unread "The submitter replied" in her inbox (no e2e spec counts priya's inbox;
alice's, which several specs read, is unchanged); the audit log gains one `submission.message`
by priya. `dev/README.md` says where to look.

## 16. The intro text (D3)

No new feature. Project settings → Public form → **Intro** already says "Shown above the form:
what kind of ideas you're after. Markdown works." (the frontend keeps that line visible next
to the character count near the limit); the schema now describes `intro_md` as "The text shown
at the top of the public form". The user guide's "Public form, moderation and erasing
submitter details" names the field and where it shows; it gains the path in one line.

## 17. Rollback window (0.3.0 code on the 0017 schema)

Expand only, so 0.3.0 runs on it: it ignores `submission_messages`, writes nothing of the new
types and reads the widened `CHECK`s. What it doesn't know: its erasure leaves a conversation
and the `submission_link` / `submission_message` rows with the erased address (rule 5 sweeps
both once the next release runs again: review S2), and its Admin → Email may fail to list an
outbox row of a type it doesn't know (as with 0016's types after a rollback to 0.2.0); its
worker leaves such rows queued. Downgrading below 0017 deletes the conversations and the new
rows (the migration's docstring).

Locks while upgrading (review C12, declined): the type `CHECK` swaps hold `ACCESS EXCLUSIVE` on
`notifications`, `notification_preferences` and `outbound_email` while each new constraint is
validated, as 0015 and 0016 did. The hourly cleanup bounds those tables (notifications 90
days, emails 30, failed ones 90), and `NOT VALID` + `VALIDATE` wouldn't shorten the lock inside
Alembic's single transaction (it would need autocommit blocks, a new pattern for one
constraint swap).

## 18. Contract mechanics

- Four stubs answer 501 (`STUBS`; `PHASE11_OPERATIONS`); `send_tracking_reply` and
  `forget_submission_email` apply the shared tracking throttle before their 501 and are in
  `PUBLIC_OPERATIONS`.
- `ROUTE_KEY_ACCESS`: the two team routes `session`, the reply and `forget_submission_email`
  `public` (`ROUTE_RULES`: `public.track`);
  `RESEARCH_GUEST_ACCESS`: the two team routes `hidden`; `ROUTE_RULES` rows
  (`tests/authz/test_route_rules.py`); the matrix test's row; table L's row.
- The rule's policy row, c31 (`NAMED_PEOPLE_ONLY`) and the trait `is_named_person` are in
  `app/authz/policy.py`; the services that use them are the builders'.
- `tests/research/test_guest_access.py` probes the two team routes as a guest (404) and pins
  them in `STILL_STUBS` (strict expected failures: they answer 501 until built; then delete
  them from `STILL_STUBS`); `tests/bids/test_route_guards.py` takes only Phase 10's rows from
  `STUBS`.
- The new fields of Phase 4's response models have **defaults** (`IdeaSubmission.messages`
  null, `permissions.can_message` false; `TrackedSubmission.can_remove_email` false,
  `messages` `[]`, `team_messages_emailed` false, `can_reply` false, `reply_blocked`
  `awaiting_team`;
  `EmailVerified.tracking_link_emailed` false): the routes built in Phase 4 keep answering,
  with "no conversation, no link email", until Phase 11's services fill them. They are still
  **required in responses** (`json_schema_serialization_defaults_required`), so the SPA's
  types say they are always there.
- `make gen-api` regenerated `frontend/src/api/generated/`.

## 19. Requests to builders

- **backend**:
  - the services: `app/public/messages.py` (list, send, reply; the checks of section 2.1, the
    locks, the limits with `Retry-After`, the email queue, the audit), the summary in
    `app/public/submissions.py` (`idea_submission` gains `messages` and `can_message`; the
    moderation queue's page in one grouped statement), `tracking.tracked_submission` (the
    whole conversation, `can_reply`, `reply_blocked` with S6's count since the team's latest
    message, `team_messages_emailed`, `can_remove_email`), `verify_email` (queue
    `submission_link` on the first confirmation; `tracking_link_emailed`), the send's 409 order
    (archived first) and `public_submission_off`;
  - `forget_submission_email` (`tracking.forget_email`: section 2.1, rule 3's effect, the one
    list of submitter emails; `awaiting_confirmation`);
  - the throttle `("public_reply", 30, 3600)` in `app/auth/throttle.py`;
  - the emails (section 8): `app/public/emails.py` (`queue_link_email`, `queue_message_email`,
    rendering both types, the confirmation sentence), templates
    `submission_link.{html,txt}` and `submission_message.{html,txt}` (the text escaped with
    line breaks), `app/email/render.py`, `preview.py` (both, plus `submitter_replied`); the
    `EmailContent` flag that leaves `Reply-To` out and the footer label "Stop emails about this
    idea" for the two new types (`app/email/model.py`, `message.py`, `_layout.html/.txt`), with a
    test that has `smtp_reply_to` set (review S1, M2);
  - `submitter_replied` end to end: `app/notifications/submitter.py` (queue + before-commit
    hook + the hourly coalescing over the inbox index), the exhaustive matches in
    `app/notifications/access.py`, `inbox.py` (the SQL form of section 6 in `_mine`, so the
    list and the unread count agree with `applies`: review S4), `app/email/content.py`
    (content, digest line), its template, preferences, unsubscribe; nothing while held for
    moderation;
  - `SUBMITTER_EMAIL_TYPES` everywhere (erasure, retention, branding, the renderer, Admin →
    Email); erasure deletes the conversation; retention rule 4 with the `NOT EXISTS` in the
    candidate query and again under the lock (review S3, a `BATCH = 1` test) and rule 5 for
    messages and submitter outbox rows (review S2);
  - the "no mentions" test (review S5: a mention-shaped body is stored and emailed as typed
    and notifies nobody);
  - the seed (section 15) and its `dev/README.md` line; the tests of section 14.
- **identity** (if a separate owner): the access-table tests of section 14 over the policy and
  the routes; nothing in the policy beyond the row, c31 and the trait should be needed.
- **frontend**: the submission panel's Messages (`features/moderation/idea-submission.tsx`:
  the conversation newest page oldest-on-top with "Show earlier messages", the composer, a
  **plain textarea** without @mention picker or toolbar (review S5), with Ctrl/Cmd+Enter and
  `lib/drafts.ts`, Send busy while it runs (review C9), the delivery line, "Email queued" per
  team message (review C10), `blocked` and the 409/429s in plain words, `?submission=1`
  opening it), the tracking page's Messages and reply box (plain, busy while sending; the
  section whenever `messages` isn't empty; "You can reply again once the team writes back."),
  "Remove my email address" with its dialog (`can_remove_email`, review M2), messages wrapped
  anywhere and clipped (review C8), the receipt, confirm page and form copy (section 8, the
  corrected email help of review M1), the notification type (label "The submitter replied",
  preferences, inbox sentence, link), the audit phrase, Admin → Email's type names
  (`submission_link` "Tracking link (public submitter)", `submission_message` "Message to a
  public submitter", `submitter_replied` "The submitter replied"), MSW mocks and fixtures; the
  typecheck list in the contract agent's report.
- **qa**: `docs/test-plans/phase-11.md`, e2e specs (the tracking page reply with a real
  submission through the form, the panel for owner/admin/member, the link email in Mailpit),
  `docs/screenshots/phase-11/`.
- **lead**: user guide (Messages, the link email, "Remove my email address", the intro's
  path), operator guide (rule 5, the throttle, no `Reply-To` on the two new submitter emails),
  `docs/RELEASE-NOTES.md` "Unreleased".

## 20. Changes after the contract

### 20.1 The contract review (2026-10-16)

The adversarial review of this contract (verified on 0.3.0's demo data, migration up, probes,
down and up) and what changed. Items the critic left to the lead are decided in the direction
of simple and safe and recorded in [decisions.md](../decisions.md#phase-11-product-owner-2026-10-16)
("J. Talking to public submitters: the contract review") as lead defaults to confirm.

| Item | What changed |
|---|---|
| **M1** False privacy promise in the form's email help | §8: the help says what the address is for and "Only administrators can see your address." (admins do see it); "We never show it to anyone else." is not used. |
| **M2** "Stop these emails" can't stop message emails | New public route `forget_submission_email` (POST `/public/track/forget-email`, `TrackingRequest`, 200 `TrackedSubmission`; 409 `awaiting_confirmation` while held for that address's confirmation): exactly rule 3's effect, on request, for a confirmed address too; `TrackedSubmission.can_remove_email`; the two new emails' footer link reads "Stop emails about this idea" and the message email's line points at "Remove my email address". Key row `public`, route rule `public.track`. §2, §2.1, §3, §8, §10, §12, §13, §14. The alternative (letting `wants_updates` govern messages) was not taken: it drops email for anyone who didn't tick the status box, against "used to contact the submitter". |
| **S1** `Reply-To` contradicts the copy and leaks replies | §8: `EmailContent` flag; `submission_link` and `submission_message` carry no `Reply-To`; test with `smtp_reply_to` set (§14). ADR 0019 says so precisely. Phase 4's types unchanged. |
| **S2** Rule 5 leaves addresses behind | §10: rule 5 also deletes the idea's `SUBMITTER_EMAIL_TYPES` outbox rows of erased submissions; §17. |
| **S3** Rule 4 can starve | §10: the `NOT EXISTS` in the candidate query and again under the lock; a `BATCH = 1` test (§14). |
| **S4** The inbox's SQL form unnamed | §6 "Shown (the inbox, SQL)": the `_bid_items` manager predicate reused for `_mine` / `_unread_count`; `applies` for fan-out, digest and send; test with a writer who left (§14). |
| **S5** The composer must be plain | §3, §19: a plain textarea, no @mention picker or toolbar; a backend test that a mention-shaped body is stored and emailed as typed and notifies nobody (§14); a schema test keeps the token as typed. |
| **S6** One team message permits weeks of replies | `SUBMITTER_MESSAGES_SINCE_TEAM_MESSAGE = 10`: the 11th reply since the team's latest message is 409 `awaiting_team` (no new state, the 10 a day stays). §2.1, §3, §5, `ReplyBlocked.awaiting_team`. |
| C1 One cap instead of two | Taken: `CONVERSATION_MAX_MESSAGES = 100`, the tracking page shows the whole conversation; `TRACKED_MESSAGES_SHOWN` and `TrackedSubmission.message_count` removed. |
| C2 Simpler foreign key | Taken: `submission_messages.idea_id`, the composite foreign key and `uq_public_submissions_id_idea_id` removed; `submission_id` → `public_submissions` `ON DELETE CASCADE`. Migration 0017, model, erd, schema tests. |
| C3 One index fewer | Taken: `ix_notifications_submitter_replied` removed; the hourly coalescing reads the inbox index `(user_id, created_at, id)`. |
| C4 Instance switch off | Taken: `SendBlocked.public_submission_off`, 409 `public_submission_off` for team sends while `SOUNDINGS_PUBLIC_SUBMISSION_ENABLED` is off (reading stays). |
| C5 No signal while held for moderation | Kept as decided (no notification while held: held ideas are in nobody's inbox); the queue's "They replied" is the signal, and the trade-off is now written down (§6, decisions). |
| C6 Order of 409s | Taken: `project_archived` first for both senders; `SendBlocked` and `ReplyBlocked` list their values in the order checked. |
| C7 Project names in subjects | No change needed: `render()` passes every subject through `clean_subject` (line breaks become spaces); §8 says so. |
| C8 Rendering | Taken: `normalise_line_breaks` turns U+2028/U+2029 into `\n`; the SPA wraps anywhere and clips each message (§3). Emails carry only team text (the reply never reaches an email), so no email-side clipping. |
| C9 Double submits | Taken for the SPA (busy buttons, §3, §19); no server-side deduplication (simple; a retry after a lost answer may send twice). |
| C10 "Emailed" means queued | Taken: "Email queued" (§3, `SubmissionMessage.emailed`). |
| C11 Two narrow windows | Written in ADR 0019's consequences (erasure racing an email already rendered; link rewriters logging the fragment). |
| C12 Migration locks | Declined: inside Alembic's one transaction `NOT VALID` + `VALIDATE` doesn't shorten the lock; the tables are bounded by the cleanup; written in §17 and the migration's docstring. |
| C13 Break-glass wording | Taken: "never reads its text" (§4, §11, role matrix); it sees audit entries and outbox rows like any platform admin. |
| C14 Accepted deviations | Kept: `too_many_attempts`, priya's demo message, the owner learning the "confirmed" bit through `delivery` (decisions). |

Also from this round: the critic counted the builder-owned test failures at 12 (the contract
report said 13; the cases add up to 12).
