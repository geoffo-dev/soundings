# ADR 0019: Talking to public submitters through Soundings, and the tracking link by email after confirmation

- Status: Proposed · Date: 2026-10-16 · Extends ADR 0003, 0010 and 0012
  ([decisions](../decisions.md#phase-11-product-owner-2026-10-16), [contract-phase11](../api/contract-phase11.md))

## Context

A public idea's sender may give an address (Phase 4): it confirms the idea, carries status
emails and is shown to project and platform admins. The product owner wants the team to be
able to **contact** the submitter, and the tracking link to be **emailed**. The address is
personal data of someone without an account; the form can be filled in with anyone's
address; whatever the submitter writes is untrusted public text; public pages and submitter
emails never show people. Soundings has no inbound email.

## Decision

1. **Relay through Soundings, never the address.** The idea's owner and admins
   (`public.message_submitter`, session only, never an agent or the break-glass account: c31)
   write in the submission panel; Soundings emails the text from `SOUNDINGS_SMTP_FROM` in the
   project's branding, signed "The <project> team". No `Reply-To` with a person's address, no
   `mailto:` with the submitter's, no address shown to the owner: the address stays visible to
   admins only, as in Phase 4, and nobody's mailbox becomes the record. Every team message is
   audited (`submission.message`, never the text) and kept with the idea until the details are
   erased.
2. **Replies on the tracking page, not by inbound email.** The email's Reply button opens the
   private tracking page, where the submitter reads the whole conversation and answers. Inbound
   mail would need a mailbox, parsing, spoofing defences and bounce handling: one more service
   to run air-gapped, against "simple beats configurable". The token already proves who the
   submitter is; replies reuse the tracking routes' JSON-only rule and throttles. The public
   never starts a conversation (replies only after the team wrote), so the form can't become a
   chat channel for spam.
3. **The link email goes only to a proven address.** The confirmation email stays link-free
   (Phase 4: anyone can type any address, and whoever opens that email would read a stranger's
   text on our domain). The tracking link is emailed **once**, when the address is confirmed
   for the first time, which means its owner clicked Confirm: the same proof that already lets
   status emails carry the link. Nothing is backfilled.
4. **Untrusted text, plain everywhere.** Messages are plain text (visible characters, 1-4,000),
   never Markdown or HTML, escaped in emails, shown without links in the SPA; a reply never
   reaches a notification ("The person who sent CUST-21 through the public form replied", no
   text: a staff inbox must not become a phishing channel), the feed, search, MCP or exports.
5. **Hidden from everyone else.** Members and viewers see no sign of a conversation
   (`IdeaSubmission.messages` null, no feed event, no activity time change), guests and keys
   none. Limits are constants: 20 team messages a day per submission, 30 an hour per person,
   10 replies a day per submission, 30 an hour per address, 200 messages in all.
6. **Erasure takes the conversation.** Every erasure path deletes it and every submitter email
   (one list, `SUBMITTER_EMAIL_TYPES`); retention counts its latest message as activity.

## Consequences

- The team can ask a question before approving a held idea and the submitter can answer; a
  submitter without a confirmed address still reads messages on their tracking page.
- One table, two email types, one notification type; no new service, setting or Helm value.
- A submitter who lost their link can't read replies until the team writes again (their email
  carries the link); erasing details ends the conversation for good.
