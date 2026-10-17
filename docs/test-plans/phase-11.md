# Test plan: Phase 11 (talking to public submitters)

Owner: qa. Source of truth for behaviour: the product owner's decisions in
[decisions.md](../decisions.md) ("Phase 11 (product owner, 2026-10-16)": "Message the
submitter" and the tracking link by email, with the lead defaults D1-D4 to confirm),
[contract-phase11.md](../api/contract-phase11.md) (endpoints and the order of checks §2,
messages §3, who §4, limits §5, "The submitter replied" §6, the tracking-link email §7, the
submitter emails' fixed text §8, audit §9, erasure and retention §10, where a message could
leak §11, minimum tests §14, the demo §15, the intro §16), [role-matrix.md](../role-matrix.md)
(table G: `public.message_submitter`, c31, the trait `principal.named_person`) and
[ADR 0019](../adr/0019-public-submitter-messages.md). Each row has an ID used in the test
names, so a failing test points back here. The Phase 1-10 plans still apply; their suites run
in every mode next to the Phase 11 specs.

## What the product owner asked for, and where it is tested

| Requirement (decisions, Phase 11) | Acceptance (HTTP, Mailpit) | Browser (real stack) | Rules (owners' unit tests) |
|---|---|---|---|
| **The tracking link by email** (D1): queued on the **first** confirmation only (`tracking_link_emailed` true once), never in the confirmation email (which gains one sentence), never on a repeat, a resend or at submission; fixed text in the project's branding, the button to `/track#<token>`, the "Keep this link private" line, the stop link "Stop emails about this idea"; no `Reply-To`; cancelled by erasure | AC11-API-1 (Mailpit: both emails, the repeat, the resend, headers), AC11-API-3 (queued, then erased: never sent) | SM-01 (the receipt, the confirm page's line, both emails), SM-08 (twice: once) | `tests/public/test_submitter_emails.py`, `tests/public/test_tracking.py` |
| **Message the submitter** (D2), the owner and admins in a session (`public.message_submitter`), signed "The <project> team", plain text, emailed when the address is confirmed, otherwise on the tracking page only (the panel says which before sending), "Email queued" per message | AC11-API-1 (the email escaped, line breaks kept, signed by the team, no person's name or address, Reply to the tracking page), AC11-API-2 (an unconfirmed address: `tracking_page`, `emailed` false, no email) | SM-02 (the panel, the sheet, Ctrl+Enter, the draft, plain text), SM-03 (the unconfirmed line), SM-07 (held for moderation: an admin asks) | `tests/public/test_messages.py` |
| **The tracking page's Messages and the reply** (D2): the team as "The <project> team", the submitter as "You", replies only after the team wrote, at most 10 since the team's latest message and 10 a day; JSON only, the token rules | AC11-API-1 (the page's shape: no author, no names), AC11-API-2 (`awaiting_team`, `daily_limit`, `conversation_full`) | SM-01 (reply with Ctrl+Enter on a phone), K11-01 (keyboard only) | `tests/public/test_tracking_messages.py` (415, 422, 404, the throttles) |
| **Who sees a conversation** (§4, §11): only the owner, project admins and platform admins, in a session; members, viewers, a guest researcher, keys of every scope, an AI agent and break-glass see nothing of it, not even that it exists: the panel (`messages` null), the routes (403 / 404 / `insufficient_scope`), idea detail, the feed, search, My work, the inbox, MCP, `last_activity_at` | AC11-API-1 (mia, vic, gus the guest researcher, alice's key of each scope on REST and MCP, an agent in its own research run, every surface) | SM-02 (Theo, a member: no Messages part, `?submission=1` opens nothing, no request) | `tests/public/test_messages.py` (the table over principal kinds), `tests/mcp/test_submitter_messages.py`, `tests/authz/test_policy_matrix.py`, `tests/research/test_guest_access.py` |
| **"The submitter replied"** (D2): to the owner and everyone who wrote, never the reply's text, the button to the submission panel; at most one immediate email per recipient and idea an hour (later ones inbox only); a preference; none while the idea is held for moderation | AC11-API-1 (olive and alice: inbox items, one email each, the second reply inbox only; none while held) | SM-05 (the inbox row opens the conversation, Mailpit once, a member nothing, the preference), SM-07 (none while held) | `tests/notifications/test_submitter_replied.py` |
| **The limits** (§5): 20 team messages a submission a day and 30 a person an hour (429 `too_many_attempts`, `Retry-After`), 10 replies a day (429), 10 since the team's latest (409 `awaiting_team`), 100 a conversation (409 `conversation_full`, both ways) | AC11-API-2 | — | `tests/public/test_messages.py`, `tests/public/test_tracking_messages.py` |
| **Erasure** (all three paths) deletes the conversation and every submitter email, queued and sent; a queued "The submitter replied" email is cancelled at send time; the panel says "Their details were erased" (409 `submitter_erased`) | AC11-API-3 ("Delete my details", rule 4) | SM-04 | `tests/public/test_message_erasure.py` |
| **"Remove my email address"** (review M2): no more email, the link and the conversation stay, the panel then says the tracking page only | AC11-API-3 | SM-06 | `tests/public/test_tracking_messages.py` |
| **Retention**: rule 3 (an unconfirmed address forgotten after 3 days) keeps the conversation; rule 4 (closed, 180 days) counts the conversation's latest message | AC11-API-3 (`retention.cleanup` with a moved clock) | — | `tests/public/test_message_erasure.py` (`BATCH = 1`, the re-check under the lock, rule 5) |
| **Audit** `submission.message` per team message, never the text; nothing personal in the logs | AC11-API-1 | — | `tests/public/test_messages.py` |
| **Copy** (review M1, D1): the form's email help ("Only administrators can see your address."), the receipt ("Once you confirm your address, we'll email you this link too."), the confirm page ("We've emailed you a private link to follow your idea.") | AC11-API-1 (the confirmation email's sentence) | SM-01, A11Y11 | `frontend/src/features/public/submit-page.test.tsx` |
| **The intro text** (D3): labelled "Intro text", its help says where it shows and that Markdown works | — | AC4-01 (the field by its new label), the phase-4 screenshots | `frontend/src/features/public/public-form-settings.test.ts` |
| **Demo** (§15): CUST-21's conversation (priya's message, Sam's reply), priya's one unread "The submitter replied" | — | A11Y11 (as priya), the screenshots | `tests/test_seed.py` |
| Calm UI: loading, empty and error states, dark mode, keyboard, 390 px, WCAG 2.2 AA | — | A11Y11-*, MO11-01, MO11-02, K11-01 | `frontend/tests/submitter-messages.spec.ts` (MSW mock) |

## Acceptance through the HTTP API (`backend/tests/acceptance/test_phase11_acceptance.py`)

The app in-process (`httpx.ASGITransport`, its lifespan running), people signed in with the
dev login (session cookie, CSRF header), the visitor signed out solving the real ALTCHA with
the Python `altcha` library; API keys as bearer tokens, the official MCP SDK client on
`/mcp`; the worker's own code sends the email (procrastinate runs the deferred `send_email`
jobs through the real SMTP transport) to a **real Mailpit** (the Phase 3 acceptance's
fixtures: a container, or CI's service), and every email is read back from it.
`smtp_reply_to` is set, to show the two new submitter emails leave it out. About 13 s for the
three.

| ID | Story | What it checks |
|---|---|---|
| AC11-API-1 | The team talks to a public submitter | A private project (alice admin; olive member and later owner; mia member; vic viewer; gus without a role), its research step on so that gus can be the idea's guest researcher, its public form moderated. **The submission**: an address, held for moderation, `email_sent`. **The confirmation email**: the new sentence, no `/track` link, no token, Phase 4's `Reply-To` kept. **The link email**: `tracking_link_emailed` true on the first confirmation, false on the second, a resend sends nothing; exactly two emails reach the address; the heading, the title as sent, "See where your idea stands", "Keep this link private…", "Stop emails about this idea", the private link as the button and the stop link, no `Reply-To`, no `List-Unsubscribe`. **Held**: the queue's `can_message` and an empty summary; alice asks (201, `emailed`); the tracking page shows it, `can_reply`, `team_messages_emailed`; the submitter replies; **no notification while held**; the queue's `last_direction: submitter`; approved. **Owned**: olive owns it, gus researches it; the panel's `delivery: email`; olive's message with `<script>`, Markdown and a link: newest first in the list; two message emails, each naming nobody (olive, alice, the platform admin: names, first names, addresses), no `Reply-To`; olive's escaped (`&lt;script&gt;`, no anchor for the link, the Markdown as typed), its line break a `<br>`, the text part as typed, "A message from the <project> team", "About your idea "<title>"", signed "The <project> team", "Replies to this email aren't read…", the stop line, Reply and the stop link to the tracking page. **The tracking page**: team, submitter, team; messages carry only id, direction, body and time; no name or id of anyone. **The reply**: olive and alice each get one `submitter_replied` (no actor, no text) and one email (the subject, the sentence, "Read the reply" to `?submission=1`, no reply text, no address or name of the submitter); a second reply within the hour: two inbox items each, still one outbox row and one email each. **Nobody else**: mia and vic `messages: null`, `can_message: false`, 403 for both routes, no notification; gus reads the idea and gets 404 for the submission and both routes, no notification; for olive, alice, the platform admin, mia, vic and gus the idea detail, search, My work and the inbox carry no message text; the feed's events unchanged; `last_activity_at` unchanged. alice's keys (read, write, evaluate, mcp, all four): both routes 403 `insufficient_scope`, the panel null; over MCP `get_idea` / `search_ideas` carry no message text (`mcp` alone: `insufficient_scope`) and no tool names messages. An AI agent's key in its own research run: REST 403, `get_idea` / `search_ideas` without the text. **Audit**: one `submission.message` by alice and one by olive, no text, address, name or token. **Logs**: no token, confirmation token, address, name or message text. |
| AC11-API-2 | An unconfirmed address and the limits | **Unconfirmed**: `delivery: tracking_page`, `emailed` false, `team_messages_emailed` false, only the confirmation email reaches the address, no `submission_message` row. **Replies**: 10 accepted, the 11th 409 `awaiting_team` (`reply_blocked: awaiting_team`); the team writes back; the next reply 429 `too_many_attempts` with `Retry-After` (10 a day; `reply_blocked: daily_limit`). **30 a person an hour**: 30 of alice's messages on two other submissions (written in the database), her next 429 with `Retry-After` ≤ 3,600; olive not limited. **20 a submission a day**: the 21st 429 with `Retry-After` ≤ 86,400; the panel's `blocked: daily_limit`, `can_message` false; still no message email. **100 a conversation**: 99 two days old plus one, then 409 `conversation_full` for the team and the submitter; the tracking page shows all 100, `reply_blocked: conversation_full`, the panel's `blocked: conversation_full`. |
| AC11-API-3 | Erasure and retention | **"Delete my details"** after the confirmation, link and a message were sent and with a reply's "The submitter replied" and a second message queued: 204; no conversation row, no outbox row of any submitter type for the idea, none to the address; the tracking link 404; the panel `blocked: submitter_erased`, `count` 0, `can_message` false; sending 409 `submitter_erased`; the list empty; olive's inbox item stays and its queued email is **cancelled** at send time; nothing more reaches the address. **A link email queued, then erased**: never sent. **"Remove my email address"** on a confirmed address: no hint, `can_remove_email` false, `team_messages_emailed` false, the conversation kept, no submitter outbox row; the panel `tracking_page`; the next message not emailed; a reply still works; no message email received. **Rule 3** (`cleanup` 4 days ahead): the unconfirmed address forgotten, not erased, the conversation and the tracking page kept, `tracking_page`. **Rule 4**: a closed idea whose `last_activity_at` is 200 days old but whose conversation is live is kept; 181 days later both are old: erased, the conversation deleted, the link 404, `submitter_erased`, audited `submission.erase`; the team's notification stays. |

## Browser, real stack (`e2e/tests/`)

Every spec has a private project of its own (`tests/support/messages.ts` `messagingTeam`:
Nora Quinn, a new person, owns its ideas; Theo Marsh is a member), so nobody seeded gets mail
or notifications; ideas come in as a `Visitor` (the public API) or a signed-out phone, with
run-unique addresses read back from Mailpit. A11Y11 reads the seeded CUST-21 as priya without
changing it.

| ID | Spec | What it checks |
|---|---|---|
| SM-01 | `submitter-messages.spec.ts` | A signed-out phone: the form's email help (and not the old "never show it" line); the receipt's "Once you confirm your address, we'll email you this link too."; the confirmation email's sentence and no tracking link; Confirm → "We've emailed you a private link to follow your idea."; the link email (button = the receipt's private link, "Keep this link private…", nobody named, no `Reply-To`); a second Confirm says the tracking link line; Nora's message (`<b>` shown as typed, signed by the team, Reply = the private link, nobody named, no key); the tracking page's Messages ("The <project> team", no link, nobody named); the reply with Ctrl+Enter as "You", the box emptied; Nora's one "The submitter replied"; axe on the receipt, the confirm page and the tracking page. |
| SM-02 | | Nora's panel: "No messages yet.", "Message the submitter…" opens `?submission=1`, the sheet's empty state and delivery line (email), the box focused; Ctrl+Enter sends (her name, "Email queued", a URL as plain text, no link), the box emptied and focused; a draft survives Escape (focus back on "Open messages", "1 message · Last sent") and a reload, then sends; the order (oldest first on screen, newest first in the API). Theo (member): no Messages part, `?submission=1` dropped, no dialog, no request for the messages, `messages: null`, 403. axe and best practice on the panel, axe on the sheet. |
| SM-03 | | An unconfirmed address: the sheet's "They'll see it only on their tracking page…", "Tracking page only"; the tracking page's "confirm your email address to get them by email too"; only the confirmation email in Mailpit once the outbox is settled. |
| SM-04 | | "Delete my details" (204, the link 404): the panel's "None: their details were erased." without a button; the sheet's "Their details were erased", "Any messages with them were deleted with their details.", no box; the list empty; sending 409 `submitter_erased`. |
| SM-05 | | A reply: Nora's email (the subject, the sentence, the link to `?submission=1`, not the reply's text or the phone number in it); the inbox row (no reply text) opens the conversation sheet; a second reply: two inbox items, still one email; Theo nothing; Settings → Notifications "The submitter replied" Immediate by default, set to Daily digest and saved. |
| SM-06 | | "Remove my email address" on a phone: the dialog ("Your link and your messages stay."), then "We don't have an email address for you any more…", the Messages section kept; the panel then says the tracking page only; the next message not emailed. |
| SM-07 | | A moderated project: alice (its admin) asks before approving, the submitter replies; no notification while held; the review queue's "They replied: the messages about <KEY>" opens the sheet with both messages; axe. |
| SM-08 | | Confirming twice: `tracking_link_emailed` true then false; exactly the confirmation and one link email. |
| SM-09 | | Admin → Email: the outbox names "Message to a public submitter" and "Tracking link (public submitter)", the rows carry neither the address nor the text; the audit log's "<Owner> messaged the submitter of <KEY>" (one entry, no text, no address). |
| A11Y11-* | `a11y-phase11.spec.ts` | axe (serious and critical) light and dark, best practice in light without overlays: the submission panel's Messages and the conversation sheet (priya, CUST-21), priya's inbox with "The submitter replied", the public form's email help, the tracking page with the conversation and the reply box, an unconfirmed address's tracking page, the "Remove my email address" dialog, the confirm page after a first confirmation. |
| MO11-01 | | The same screens at 390 px: no sideways scrolling, axe. |
| MO11-02 | | On a phone, Details → Open messages opens the conversation; the sheet, not the box, takes focus. |
| K11-01 | | The reply with the keyboard only: Tab to the box, Ctrl+Enter sends, "Reply sent" announced, the box emptied and focused; the owner (a new person) is the one told. |

Earlier specs changed with the story (not the behaviour they test): the notification
preferences have **13** rows ("The submitter replied"): `a11y-phase3.spec.ts`,
`preferences.spec.ts`, `research-assignment.spec.ts` (RA-11) and `screenshots/phase-3.spec.ts`;
`public-acceptance.spec.ts` (AC4-01) finds the intro field by its new label "Intro text";
`public-tracking.spec.ts` (PT-01) lists the tracking page's five new fields (`messages`,
`can_reply`, `reply_blocked`, `team_messages_emailed`, `can_remove_email`) among the keys it
allows, and checks a page without messages says `awaiting_team`.
The demo's CUST-21 conversation changes no count an earlier spec reads (alice's inbox and My
work are unchanged; priya's inbox has one more unread item, which no spec counts).

## Screenshots (`npm --prefix e2e run screenshots:phase11`)

`docs/screenshots/phase-11/<screen>-<1440-light|1440-dark|390-light>.png`: the submission
panel's Messages and the conversation sheet with a message being written (priya, CUST-21),
priya's inbox with "The submitter replied"; on a project of its own ("Home Delivery", HOME,
archived afterwards; Nora Quinn owns its ideas) the sheet for an unconfirmed address ("only on
their tracking page"), the tracking page with the conversation and the reply box, the confirm
page's new line; `emails/`: `submission-link`, `submission-message` and `submitter-replied` as
Mailpit received them (desktop light and dark, 390 light). `npm --prefix e2e run
screenshots:phase4` re-captures Phase 4's public pages and emails whose copy changed (the form's
email help, the receipt, the confirm page, the tracking page's "Remove my email address", the
"Intro text" field, the confirmation email's sentence).

## Defects and nits found (2026-10-17, real stack)

No defect in the built behaviour: every Phase 11 rule above passed on the real stack (API,
worker, Mailpit) in the first run that had the specs. Earlier specs changed only where the
story did (above). Visual review of `docs/screenshots/phase-11/` and the re-captured
`phase-4/` sets:

| ID | Owner | What |
|---|---|---|
| P11-QA-V1 | backend (seed) | CUST-21's seeded team message says "Tracking page only" in the sheet although Sam's address is confirmed (the seed writes through the services with email off, so `emailed` is false); beside the composer's "Emailed to them and shown on their tracking page" it reads oddly in the demo (`messages-sheet-composer-*`). Accept, or seed it as emailed. |
| P11-QA-V2 | lead (note) | CUST-21 has no owner, so the seeded team message is priya's (a project admin), not "its owner's" as D2 put it. Its panel offers "Assign owner" next to the conversation. |
| P11-QA-V3 | frontend (nit) | The public form says twice who sees the address: the section line "Your email address is only for contacting you: it isn't shown with your idea." and the email help "…Only administrators can see your address." (`phase-4/public-submit-*`). |
| P11-QA-V4 | qa (note) | Phase 4's receipt shot is sent without an address, so the receipt's new line ("Once you confirm your address, we'll email you this link too.") is in no screenshot; SM-01 checks it on a phone. |

## Results

Local e2e stack (prefix `p11-qa-`, default ports), freshly seeded, from the tree at `6620a12`
plus the screenshot spec's names (2026-10-17).

| Check | Result |
|---|---|
| `test_phase11_acceptance.py` (real Mailpit) | 3 passed (22 s); Phase 3 and 4 acceptance 4 passed |
| e2e default (`e2e`, `serial`, `smtp-outage`) | 381 passed, 67 skipped, none failed (15.0 min); Phase 10's 353 + SM-01…09 + 19 in `a11y-phase11.spec.ts` |
| e2e `E2E_SSO=1` | 402 passed, 46 skipped, none failed (18.2 min); Phase 10's 374 + 28 |
| e2e `E2E_AI=1` | 422 passed, 26 skipped, none failed (17.0 min); Phase 10's 394 + 28 |
| `npm --prefix e2e run check` | pass |
| `screenshots:phase11`, `screenshots:phase4` | 19 and 37 passed; every PNG read (above) |
| `frontend`: `SCREENSHOTS=1 npx playwright test submitter-messages-screenshots` (MSW mock) | 39 passed into `docs/screenshots/phase-11/mock/` (13 screens; the full-page `track-remove-email-390` shows the dialog's overlay over the first screen only, a capture artefact) |

Earlier runs on the way: the first full default run (before the Phase 11 specs) failed PT-01 (the
tracking page's new keys: the spec's list updated) and RS-02 once (the drag library's "is over"
announcement timed out; it passed in the two runs since); the second (lost to a container
restart) failed SM-03/05/08/09 waiting for the whole outbox to drain behind other specs' held or
retried email (they now wait only for their own idea's email, `ideaEmailsSettled`).

