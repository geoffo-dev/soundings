# Soundings release notes

Soundings is a calm, fast web app where people submit ideas, anonymously too through a
public form. Each idea gets one accountable owner and several evaluators, who score it
blind against a short rubric. Strong ideas become a commercial proposal exported to PDF
or Markdown, and once a proposal is agreed, a call for bids collects the bids that come in
and has them assessed section by section, blind. It is one container image and one Helm
chart, needs only PostgreSQL, sends mail through any SMTP server and runs air-gapped.
Tour: [README](../README.md#a-tour). Guides: [user](user-guide.md),
[operator](operator-guide.md), [MCP](mcp.md).

## Unreleased

**Not released.** Phase 11, **talking to public submitters** (the product owner's change
of 2026-10-16), on top of 0.3.0, with its reviews' fixes. No version bump: whether and when
to tag it is the product owner's call (`scripts/deploy.sh check-release` needs the versions
bumped first). Waiting for the product owner's review.

**Verified on 2026-10-17** (the build machine, not a real CI runner), after the security and
UX reviews' fixes: backend (10,542 tests, `test-slow`), frontend check (747 vitest) +
`test:pw` (487), e2e in all three modes (default 381, `E2E_SSO=1` 402, `E2E_AI=1` 422 passed)
and against `make demo` (420 passed; none failed anywhere), then CI's MCP, AI, bid and public
smokes on that image (the public smoke with Mailpit: the link email, a message, the reply),
every `make check-*`, `make gen-api` (no diff), `make image` (535 MB); on k3s 0.3.0 with its
demo data upgraded by `make k3s-deploy`'s path (0016 → 0017, row counts unchanged, nothing
retroactive, the public smoke's conversation and its emails on the migrated data, the
rollback across 0017 refused), as CI (`SSO=1 SMTP=1 MCP=1 AI=1`) and `PROD=1`. The real-stack
screenshots of the changed screens (Phase 11, 4 and 3 with their emails) and the tour
re-captured. Not run: a real CI runner, a real kagent, `scripts/ci-local/`.
[Contract](api/contract-phase11.md), [ADR 0019](adr/0019-public-submitter-messages.md),
[test plan](test-plans/phase-11.md), [Phase 11 summary](phase-summaries/phase-11.md).

### What's new

- **Message the person who sent an idea.** The idea's owner and the project's and
  platform admins write to the sender of a public idea from the submission panel's new
  **Messages** part, without anyone seeing their address. Messages are plain text (up to
  4,000 characters, never formatted), signed "The <project> team" (never a person's name),
  shown on the sender's tracking page and also emailed in the project's branding once
  their address is confirmed and email is set up; each message says "By email too" or
  "Tracking page only", and before sending the sheet says plainly when they won't get an
  email. Each one is in the audit log ("… messaged the submitter of CUST-21"), never its
  text. Nobody else sees the conversation or that one exists: not members, viewers, a
  guest researcher, API keys, MCP or AI agents, the feed, search, ⌘K, exports or "recently
  updated". It works on closed ideas and on ideas still waiting for review (ask before
  approving), read-only in an archived project.
- **They reply on their tracking page**, once the team has written (at most 10 replies
  after each team message, 10 a day; the page warns two replies before a limit); the
  tracking page shows the whole conversation ("The <project> team" and "You"), and the
  message email's **Reply** button opens it at the reply box. **"The submitter replied"**,
  a new notification type (preferences, inbox, digest, unsubscribe), goes to the idea's
  owner and everyone who has written to them: one inbox item per idea while unread, at
  most one email per person and idea an hour, subject `[KEY] The submitter replied`, and
  never what they wrote. While an idea waits for review the queue shows "They replied"
  instead.
- **The tracking link by email**: the first time a sender confirms their address, Soundings
  emails them their private tracking link ("Your link to follow your idea for <project>").
  The confirmation email still carries no link (anyone can type any address into the form);
  it now says the link follows, and so do the receipt ("Open the link we've just emailed
  you") and the confirm page.
- **"Remove my email address"** on the tracking page stops every email about the idea and
  deletes the address, keeping the link and the conversation. **Delete my details** and an
  admin's **Erase submitter details** now delete the conversation too, and so does the
  retention cleanup.
- **Limits** (fixed): the team sends at most 20 messages a day to one sender and each person
  30 an hour to senders in all; a conversation holds 100 messages; replies are limited to 30
  an hour per address.
- The public form's email help says what the address is for (the link, and the team
  writing to them about this idea; they reply on the tracking page) and that only the
  team's admins see it; Project settings → Public form names its intro field **Intro text**,
  says it is shown at the top of the form (Markdown) and previews it.
- **Changed:** a member can no longer volunteer ("I'll own this") to own an idea sent
  through the public form, since its owner reads the conversation: a project admin names
  the owner (403 `public_idea_owner_needs_admin`; owners who volunteered before keep their
  ideas). Project names refuse line breaks and other control characters (422), like idea
  titles; existing names are kept.

### Known issues

| Item | Detail |
|---|---|
| **Replies only on the tracking page** | Emails to the sender have no `Reply-To` and say replies aren't read; a sender who replies by email writes to `smtp.from`. Make it a no-reply mailbox, or handle it as personal data (the [operator guide](operator-guide.md#smtp-settings-and-existingsecret)): Soundings' erasure doesn't reach it. |
| **No notification while an idea waits for review** | Held ideas are in nobody's inbox; a moderator who asked a question sees the answer as "They replied" in the review queue only. |
| **Two narrow windows** | An erasure racing an email already being sent, and mail link rewriters (such as Safe Links) logging the whole `/track#` link, as for status emails since 0.1.0 ([ADR 0019](adr/0019-public-submitter-messages.md)). |
| **Nothing retroactive** | Senders who confirmed their address before this release get no tracking-link email; members who volunteered to own public ideas before it keep them. |
| The demo's message reads "By email too" | Demo data only: priya's seeded message to CUST-21's sender reads as emailed (his address is confirmed), but the seed queues no email. |
| **A forced rollback across 0017 with the bundled Postgres** | `DEPLOY_FORCE=1 scripts/deploy.sh rollback` to 0.3.0 doesn't start the old pods: with the chart's bundled Postgres they migrate in an init container, and 0.3.0's `soundings migrate` stops at "Can't locate revision identified by '0017'"; Helm's rollback times out while the new pods keep serving, and rolling forward works. With an external database (the production setup: migrations in a pre-upgrade hook Job, which a rollback doesn't run) it doesn't apply. Not new in this release (any migration since Phase 9 behaves so); `scripts/deploy.sh` refuses the rollback unless forced. |
| As in 0.3.0 | [0.3.0's known issues](#known-issues-in-030) otherwise apply. |

### Upgrading from 0.3.0

- **Migration 0017** runs before the new pods serve: one new table (`submission_messages`)
  and `CHECK` constraints that accept the new notification type `submitter_replied` and the
  submitter email types `submission_link` and `submission_message` (anyone who had every
  notification type off gets the new one off too). It is expand only, so 0.3.0's pods keep
  working during the rollout and `scripts/deploy.sh` can roll a failed deploy back; a
  rollback across it is refused unless forced (`DEPLOY_FORCE=1`), as for every migration
  (and with the bundled Postgres a forced one doesn't start the old pods: known issues).
  A submitter erased by a 0.3.0 pod during that window leaves their conversation and the
  new emails behind: the hourly cleanup deletes them. Downgrading below 0017 **deletes**
  every message, the new emails and the `submitter_replied` notifications and preferences.
- **No new settings or Helm values.** The two new emails go through the usual outbox and
  worker; they never carry `SOUNDINGS_SMTP_REPLY_TO`. Check that `smtp.from` is a no-reply
  mailbox (above).
- **API (additive)**: `GET`/`POST /api/v1/ideas/{idea}/submission/messages` (session only;
  API keys get 403), `POST /api/v1/public/track/messages` and `POST
  /api/v1/public/track/forget-email` (JSON only), new fields on the submission panel,
  the moderation queue, the tracking page and the confirm answer, the `submitter_replied`
  type and the `submission.message` audit action; MCP is unchanged
  ([contract-phase11](api/contract-phase11.md), its §20 for the changes after the contract).
  Two behaviour changes for API clients: `POST /ideas/{idea}/volunteer` by a member on an
  idea sent through the public form is 403 `public_idea_owner_needs_admin`, and a project
  name with a line break is 422.

### Decisions to confirm (unreleased)

The product owner decided (a) messaging the submitter and (b) emailing the tracking link
once the address is confirmed ("Yeah maybe have both"), and that the form's intro needs no
new feature ("oh both are there!"). The rest are the lead's defaults ("lead default, to
confirm" in [decisions.md](decisions.md), sections I and J of "Phase 11 (product owner,
2026-10-16)", "2026-10-17 · Phase 11 build and integration" and "2026-10-17 · Phase 11
review decisions"), built that way and easy to change:

1. **D1, the tracking-link email** on the first confirmation only, nothing retroactive,
   never in the confirmation email (which gains one sentence; the receipt and the confirm
   page say the link follows).
2. **D2, who**: the idea's owner, project and platform admins, in a session only; never AI
   agents or the break-glass account (c31); nobody else sees that a conversation exists.
3. **D2, delivery**: every team message on the tracking page, also emailed to a confirmed
   address whatever the status-email switch says; signed by the team, never a person; no
   `Reply-To` on the two new emails.
4. **D2, replies** only after the team has written, and at most **10 after each team
   message** (contract review S6; 409 `awaiting_team` either way).
5. **D2, limits**: 20 a day per sender and 30 an hour per person for the team; 10 a day per
   sender and 30 an hour per address for replies; **100 messages a conversation, all shown**
   (contract review C1, instead of 200 with the latest 100 shown); the per-action limits
   answer 429 **`too_many_attempts`** (not `rate_limited`, the session-write limiter's code).
6. **D2, "The submitter replied"** to the owner and everyone who wrote, never the text;
   **none while the idea waits for review** (the queue shows "They replied").
7. **"Remove my email address"** for the sender (contract review M2: what the 3-day rule does
   to an unconfirmed address), linked from both new emails' footers.
8. **Erasure and retention**: the conversation goes with the sender's details (all three
   ways); a closed idea's latest message counts as activity for the 180-day rule; a rule 5
   sweeps what an older release's erasure left.
9. **Not in** the feed, search, ⌘K, MCP, exports or the idea's activity time; team
   messages refused while public submission is off for the instance.
10. **D3**: the intro needs no new feature (its label "Intro text", help and a preview).
    **D4**: migration 0017 expand only, no settings or Helm values, no version bump.
11. **The demo**: CUST-21's message is from priya (a project admin: CUST-21 has no owner),
    with Sam's reply; earlier e2e counts unchanged.
12. **The conversation opens in a side sheet** from the submission panel (the panel is too
    narrow for 4,000-character messages), oldest at the top.
13. **c32 (security review M1)**: members can't volunteer to own an idea sent through the
    public form; admins name its owner.
14. **One unread "The submitter replied" per recipient and idea** (UX review M2), brought up
    to date by each reply; email at most one an hour.
15. **The reply email's subject without the title** (`[KEY] The submitter replied`; security
    review L1): the title is the submitter's own text.
16. **"By email too" / "Tracking page only"** on each team message (UX review m1), instead
    of "Email queued"; **"They won't get an email"** above the box when it reaches the
    tracking page only (UX M1); the form says "Only the team's admins can see your address."
    (UX m5).

## 0.3.0

**Released:** 2026-10-14. The product owner's change after 0.2.0: Phase 10, **bid
evaluation** (the product owner's ask of 2026-10-13), with its reviews' fixes, plus the
fixes from the first CI run on GitHub. Waiting for the product owner's review.

**Verified on 2026-10-14** (the build machine, not a real CI runner): backend (10,254 tests,
`test-slow`), frontend check (713 vitest) + `test:pw` (471), e2e in all three modes
(default 353, `E2E_SSO=1` 374, `E2E_AI=1` 394 passed) and against `make demo` with the
0.3.0 image (392 passed, none failed anywhere) followed by CI's MCP, AI and bid smokes,
every `make check-*`, `make image` (533 MB); on k3s 0.2.0 with its demo data upgraded to
0.3.0 by `make k3s-deploy`'s path (0015 → 0016, see [Upgrading](#upgrading-from-020)) and
as CI (`SSO=1 SMTP=1 MCP=1 AI=1` with the bid smoke and a slow upload, two API replicas,
`PROD=1`). Every real-stack screenshot set and the tour re-captured. Not verified: a real
kagent and LLM, GitHub's and GitLab Premium's delivery features, `scripts/ci-local/`.
[Phase 10 summary](phase-summaries/phase-10.md).

### What's new in 0.3.0

#### Calls for bids (Phase 10)

- Once an idea is in **Proposal** and has a proposal, its new **Bids** tab runs **one call
  for bids**: draft → **open** (bids are entered until a deadline; late ones are marked,
  not refused) → **assessing** (no new bids; back to open while nothing is submitted) →
  **awarded** or **cancelled** (read-only). The idea's owner and the project's and
  platform admins run it (call managers). Closing the idea makes its call read-only;
  reopening it lets the call go on.
- **The evaluation template**: Project settings → **Bids** holds each project's default:
  1-8 weighted sections (weights add up to 100), 1-15 questions each (**score** 0-5 with
  the scale's six labels shown to assessors, at most one **price** question, scored from
  the prices, and **comment**), and 0-20 **must-haves** (a required **document**, or a
  **confirmation** a person checks). Every project starts from Technical 40 / Commercial
  40 (with the price) / Delivery 20, a few sample questions, and "Signed form of tender",
  "Pricing schedule", "Insurance certificate" and "Accepts our standard terms". A call
  **copies** the template and may change its own copy until the first person submits an
  assessment; later changes to the project's template never touch a call.

#### Bids, documents and must-haves (Phase 10)

- **Bids are entered by the team** (no bidder accounts or portal): the bidder, a contact
  (never emailed), when it arrived, the price (when there is a price question) and notes.
- **Documents** (PDF, Word, Excel, PowerPoint, OpenDocument, text, CSV, PNG, JPEG; up to
  25 MB each, 30 a bid, 500 MB a call, 5 GB a project) are uploaded by call managers with
  progress, by drag and drop or the keyboard, and matched to the must-have their name
  points to. The type is decided from the file's bytes, never its name: macro-enabled,
  encrypted and OLE-carrying Office files, Excel macro sheets and anything else are
  refused, with the reason beside the file. Files are stored in PostgreSQL, downloaded
  only as attachments, and never opened in the browser: the worker reads each file's
  text in a time- and memory-limited child process, and the app shows that text as plain
  text (a file with active content asks before it downloads).
- **Pricing documents** (the pricing schedule, or any file marked as pricing) and the
  price are for call managers and the assessors of the section with the price only;
  everyone else sees "present (restricted)". The AI never reads them.
- **Must-haves are flagged at once**: a required document with no file is **Missing**
  the moment the bid is entered; confirmations wait for a person (the AI pre-checks them
  as suggestions). **Reject…** is one click, with the reason filled in ("Missing:
  Insurance certificate."), audited, and **Reinstate** undoes it until the award. A
  rejected bid leaves the queues, the totals, the price formula and the ranking.

#### Assessors, blind, scoring and the award (Phase 10)

- **Assessors per section** (for example Technical, Commercial, Delivery), with one
  assessment due date: each section's assessors score it for every bid. They are told
  ("Asked to assess bids"), reminded 2 days before and on the day, and the call's managers
  hear when every assessment is in; My work's **Bids to assess** and the sidebar's badge
  list what each person owes. No email or inbox item carries a score, a price, a bidder or
  document text.
- **Blind per bid and section**, as idea evaluations: until you submit a section for a
  bid you see nobody's scores for it (people's or the AI's), anywhere (the app, the API,
  MCP, exports, emails); assessors never see totals or ranks, and a call manager who still
  owes an assessment sees no ranking. Once the call is awarded or cancelled nobody can
  score, so nothing is hidden any more (except from agents).
- **Scoring**: a question's score is the mean of the submitted scores; a section's score
  the weighted mean of its questions (0-5, shown as 0-100); the total weights the
  sections; the price question scores lowest qualified price ÷ this bid's price × 5.
  Worked out in exact fractions and rounded half up only for display; equal totals share a
  rank ("1="); "Disagree" when two assessors' scores on a question differ by 2 or more.
  Only bids that meet every must-have get a total.
- **The comparison** (call managers): ranks, prices and price scores, section scores and
  totals, "n of m assessed", and each section's assessments one click away (who scored
  what and why). **Award…** picks one qualifying bid with an optional reason (it says how
  many assessments are outstanding and never breaks a tie for you); the others become
  unsuccessful; audited and in the idea's feed.
- **The evaluation report** (Markdown and PDF through the existing PDF renderer, call
  managers only): the ranking, each bid's section scores and total, must-have results,
  rejected bids with their reasons, the assessors and their progress, whether the AI was
  counted, and the award.

#### The AI assessor (Phase 10)

- Agents with the new purpose **Assess bids** score every question of a bid with a
  rationale and quotes from its documents and check its must-haves, through three new MCP
  tools that reach **only their run's bid** (never other bids, people's scores, prices or
  pricing documents). **Every quote is checked** against the document's text and shown
  "Found in the document" or "Not found in the document".
- "Ask AI to assess" on a bid and "Assess all with AI" on the call (each counts toward
  the 20 AI requests an hour); a call may name one AI assessor, which assesses each bid
  **once by itself** when its documents are read and nothing was uploaded for 5 minutes.
- Its scores are shown next to the people's but **left out of every total** until a call
  manager switches on **Count in the totals** for that bid; a changed re-submission is
  left out again. Its must-have findings are suggestions a person confirms.
  `deploy/kagent/` has a bid-assessor Agent example whose system message treats document
  text as untrusted data.

#### Review fixes

Phase 10 had a contract review before any code, then security and code, access and UX
reviews of the build; every finding was fixed or decided by the lead
([decisions.md](decisions.md), "2026-10-14 · Phase 10 review decisions"). The main ones:

- **Security and code:** a closed idea's call is read-only for everyone, the AI too;
  scoring the largest call reads its answers once; PDF active-content flags no longer
  fire on compressed bytes (and survive a damaged file); Excel 4.0 macro and dialog
  sheets, OpenDocument event scripts and ZIPs naming one entry twice are refused or
  flagged; one upload per person per API process, and a trickling upload is cut off
  (under 16 KiB/s after 15 s); the extraction child's time limit holds when it stops
  reading; quote checks read one document at a time; one call's backlog can't starve
  the other calls' extraction; edits to a submitted assessment are audited.
- **Access:** the AI's must-have reasons and quotes are hidden from anyone who still owes
  a section of the bid (only the verdict shows); a rejected bid's AI runs leave with it; a
  pricing must-have's note and decider are for price viewers only; a finished call ends
  everyone's blindness (agents excepted); leaving a private project takes away one's
  unsubmitted sections there.
- **UX:** the bid form says what is wrong as you type; uploads link to their must-haves by
  name, with an "Answers" choice on every file; prices aren't exposed by default (an
  unmatched file in a call with a price question goes up as pricing until you say it
  isn't); call managers can read every assessment from the bid and the comparison; the
  Bids tab follows the idea's status; due dates are the instance's days everywhere (the
  app, emails, the report); focus lands on the next sensible control after every action.
- **Release verification (this release):** the SPA sends the file's name in the
  `X-Filename` header (percent-encoded) instead of the query string, so bidders' file
  names stay out of ingress access logs; the audit log words an edited assessment, a bid
  edit that changed whether it is late, and assessors taken off a call because they left
  the project (and counts the assessors added and removed, which it had shown as none);
  the image's version label now follows `backend/pyproject.toml` (0.2.0's image said
  0.1.0). The e2e bid specs take turns (`bids.spec.ts` in order): two of them uploading as
  the same person side by side met the new one-upload-per-person limit (503).

#### CI fixes since 0.2.0

The first run of `.github/workflows/ci.yml` on GitHub's runners (2026-10-10) found three
things the build machine hadn't:

- **The PDF renderer kept restarting**: the warm child process that renders PDF exports
  retired itself after every export in a large API process, because it measured the
  parent's peak memory (`ru_maxrss` carries it across `spawn`); it now measures its own
  (`VmHWM`) and is reused as designed.
- **shellcheck 0.9** (GitHub's ubuntu-24.04) names two warnings differently from 0.11 and
  flags `A && B || C`: the scripts are clean with 0.9, 0.10 and 0.11.
- **An email outage test across the hour**: the worker's send breaker counts every
  failure and the hourly schedule sends the day's digests at minute 0, so the e2e outage
  specs now wait for a quiet outbox before stopping Mailpit.

### Known issues in 0.3.0

| Item | Detail |
|---|---|
| **No antivirus scanning** | Uploads are allowed by their bytes and never executed, rendered or opened on the server except by the extraction child; macro and OLE content is refused and active content flagged. Where policy needs a virus scan, put a scanning proxy (ICAP, ClamAV) in front of the upload path or scan backups ([operator guide](operator-guide.md#no-antivirus-scanning)). |
| **No OCR** | Images and scanned PDFs have no text: the AI can't read them and quotes from them can't be checked. |
| **No bidder portal** | Bids are entered by the team (P1); bidders have no accounts, links or uploads of their own, and Soundings never emails them. |
| **The AI assessor is verified against Soundings' fake agent only** | As for every AI feature: no kagent controller or LLM has carried an assess run here. The fake agent (`dev/fake-agent`) runs the real MCP tools with deterministic scores and quotes taken from the extracted text (and invented ones for the `-invents` suffix); the bid-assessor manifest is validated against kagent v0.10.2's CRDs. How well a real model scores, quotes exactly and resists instructions hidden in bid documents is untested. |
| **Database growth** | Documents and their text are stored in PostgreSQL (up to 5 GiB a project): size the volume and every backup for them. Bidders' documents may hold personal data; they live as long as the call (delete the call, or the idea, to remove them). |
| **The upload route needs its ingress settings** | 25 MiB bodies for up to 180 s on one path: the chart's `ingress.uploads` does it for ingress-nginx; Traefik (k3s) needs its entryPoint `readTimeout` raised; other controllers by annotation. Through Traefik an oversized *chunked* upload may get 502 instead of 413. |
| **One call per idea; one currency label per call** | A second purchase from the same idea needs another idea. The currency is a label: no conversion. |
| Not changed from the reviews | The bid count everyone who sees the idea gets includes rejected bids (ACC-6, declined); the first submitted scores of an edited assessment aren't kept (only the audit entry); the Bids, Comparison and Rejected lists stay three views (one table is a later change). |
| The demo's bid assessor warns "Removed: can't work there" | Demo data only: in Admin → AI agents the seeded, disabled "Bid assessor (demo)" has no role in Internal Tools (the seed skips the membership that registering an agent gives), so its Projects cell says it can't work there. Agents registered in the app get the role. |
| As in 0.2.0 | GitLab Premium's environments and approvals, the Kubernetes executor, cosign, GitHub's runners/GHCR/ARC/environments and `scripts/ci-local/` weren't run again for this release; [0.2.0's known issues](#known-issues-in-020) otherwise apply. `make -C backend test-slow` passed within its budgets (150 ms p95) on a quiet machine. |
| The image is 533 MB | Ubuntu 24.04 with the PDF libraries and `pypdf`; a slimmer final stage is still deferred. |

### Upgrading from 0.2.0

- **Migration 0016** runs before the new pods serve (`helm upgrade` or
  `scripts/deploy.sh`): new tables for calls, bids, documents, assessments and AI
  assessments, four columns on `ai_runs`, the `assess_bid` run kind and agent purpose,
  and three notification types (anyone who had every type off gets them off too). It
  gives **every existing project the default bid evaluation template** and changes no
  existing row otherwise. It is expand only, so 0.2.0's pods keep working during the
  rollout and `scripts/deploy.sh` can roll a failed deploy back. Rehearsed on k3s with
  0.2.0's demo data (0015 to 0016 through `scripts/deploy.sh` as the deployer
  ServiceAccount; the row counts of eleven tables unchanged; all three projects got the
  default template, none without; a call on TOOLS-3, whose proposal was written on
  0.2.0, took a bid and a PDF whose text the worker read, and the bid smoke assessed,
  compared and awarded a call on the migrated data; the rollback to 0.2.0's revision was
  refused because it crosses 0016). Downgrading below 0016 is an emergency only (restore
  a backup if you can): it **deletes** every call, bid, document, assessment and AI
  assessment, the `assess_bid` runs and the three types' notifications.
- **Database growth from documents**: up to 25 MiB a file, 500 MiB a call and 5 GiB a
  project, extracted text counted; stored uncompressed in `bid_document_contents`. Size
  `postgresql.persistence.size` (or your database) and your backups before people start
  calls ([operator guide](operator-guide.md#storage-limits-and-backups)).
- **The upload route's ingress body size and timeout**: `POST
  /api/v1/ideas/{idea}/bid-call/bids/{bid}/documents` takes a 25 MiB raw body within
  120 s; everything else keeps the 1 MiB limit. With ingress-nginx the chart's new
  `ingress.uploads` (on with `ingress.enabled`) adds a fourth Ingress for that path only
  (26 MiB, 180 s, no request buffering; its default path is a regular expression, and
  ingress-nginx's `use-regex` then applies to every path of the host: the chart README
  says what that means); with Traefik raise the entryPoint's
  `respondingTimeouts.readTimeout` to 180 s (60 s by default since v2.11.2); with other
  controllers set `ingress.uploads.path`, `.pathType` and `.annotations`
  ([operator guide](operator-guide.md#the-upload-routes-body-size-and-timeout)). File
  names travel in the `X-Filename` header from the SPA; scripts that send `?filename=`
  put the name in your access log.
- **The worker needs 1 GiB of memory** (the chart's new default; the extraction child is
  capped at 512 MiB). Extraction runs on the worker's own `bid_documents` queue, one
  document at a time per worker pod.
- **New Helm values**: `ingress.uploads.*`, `kagent.agents.bidAssessor` (the example
  Agent), the worker's resources; see the [chart README](../deploy/helm/README.md#bid-evaluation).
  `pypdf` moved from a development to a runtime dependency (BSD-3-Clause).
- **API (additive)**: 34 operations under `/api/v1/ideas/{idea}/bid-call` and
  `/api/v1/projects/{slug}/bid-template`, new fields on ideas, My work and AI runs, three
  notification types, 19 audit actions and new error codes; MCP gains
  `get_bid_for_assessment`, `get_bid_document_text` and `submit_bid_assessment`, usable only
  inside an `assess_bid` run ([contract-phase10](api/contract-phase10.md), its §21 for the
  changes after the contract; [mcp.md](mcp.md)).

### Decisions to confirm in 0.3.0

The product owner decided P1-P4 (bids entered by the team; must-haves flagged and a bid
rejected by a person in one click; assessors per section; the AI's scores out of the
totals until included). The rest are the lead's defaults ("lead default, to confirm" in
[decisions.md](decisions.md), sections F and G of "Phase 10 (product owner,
2026-10-13)", "2026-10-13 · Phase 10 build and integration" and "2026-10-14 · Phase 10
review decisions"), built that way and easy to change:

**The call and its template**
1. **One call per idea**, on an idea in Proposal with a proposal (L1); closing the idea
   makes the call read-only, reopening resumes it.
2. **The lifecycle** draft → open → assessing → awarded | cancelled, back to open only
   while nothing is submitted; late bids marked, not refused (L2).
3. **The default template** (Technical 40 / Commercial 40 with the price / Delivery 20;
   four must-haves including "Pricing schedule"); a call's copy locks at the first
   **person's** submitted assessment, and changing it deletes the AI's assessments (L3).
4. **Question types** score / price / comment, one price question at most (L4).

**Who does what**
5. **Call managers** = the idea's owner, project admins and platform admins; uploads,
   rejecting, reinstating, the award, cancelling, deleting and assigning assessors are
   **session only** (L5).
6. **Assessors must be able to view the idea in their own right** (in a private project: a
   role there; never agents, the break-glass account or deactivated people), and **a
   platform admin may be an assessor** without a role in the project.
7. **Assessors per section** with one due date per call; nobody removes themselves from a
   section they owe; someone who submitted keeps their section.
8. **Blind per (bid, section)**; assessors never see totals, ranks, contacts, notes or
   rejection reasons; no ranks for a manager who owes an assessment.
9. **ACC-4**: a finished (awarded or cancelled) call has no pending assessors: nothing is
   hidden any more, except from agents.
10. **ACC-5**: leaving a private project removes one's unsubmitted section assignments on
    its unfinished calls (drafts too), audited.
11. **ACC-6** (finding declined): everyone who sees the idea sees the bid count, rejected
    bids included.
12. **L7**: edits after submitting are audited (which questions changed); the first scores
    aren't kept.

**Bids and documents**
13. **Documents in PostgreSQL** (no object store), with the limits above; type from the
    bytes; the SPA never renders a document.
14. **No antivirus scanning** and **no OCR** in this phase.
15. **Pricing documents**: a document can be marked pricing (or answers a pricing
    must-have); it and the price are for call managers and the price section's assessors
    only, and the AI never reads it; in a call with a price question an unmatched upload
    is pricing until someone says it isn't.
16. A must-have **document** is met automatically by a file and **missing** without one; a
    **confirmation** waits for a person; AI findings never change a result.

**Scoring and the award**
17. **The price formula**: lowest qualified price ÷ this bid's price × 5.
18. Exact fractions, rounded half up for display (scores 2 decimals, section scores and
    totals 1); ranks by the rounded total, equal totals share a rank and the award breaks
    the tie; disagreement at a spread of 2; scored bids follow the facts (not rejected,
    every must-have met), not the award.

**The AI assessor**
19. **AI inclusion per bid**, by a call manager, and not while that manager still owes a
    section of the bid; a changed re-submission is left out again.
20. **The automatic AI pre-check**: a call may name one AI assessor, which runs once per
    bid after a **5-minute quiet period** with every document read, outside anyone's 20
    requests an hour; further runs are manual and counted.
21. The AI's must-have reasons and quotes are hidden from anyone who owes a section of the
    bid (the verdict shows); quotes are at least 20 characters and checked whitespace
    aside.

**Notifications and the report**
22. "Bid assessments complete" goes to the idea's owner and the call's creator, not every
    admin; reminders 2 days before and on the due date at the digest hour.
23. The evaluation report is for call managers only; a manager who owes an assessment
    gets it without that bid's scores and ranks.
24. Due dates are the end of the chosen day in the instance's time zone, shown as the day
    in emails.

## 0.2.0

**Released:** 2026-10-10. The product owner's changes after reviewing 0.1.0: Phase 8
(per-project proposal templates and a research step), Phase 8b (the research assigned to
a person, also from outside the project) and Phase 9 (continuous delivery), with their
reviews' fixes. Waiting for the product owner's review.

**Verified on 2026-10-09/10** (the build machine; GitLab's pipeline also on a self-managed
GitLab CE, not GitHub's): every check (8,282 backend tests, 661 unit and 442 page tests
in the SPA, the end-to-end suite in its three modes: 315 tests, 336 with single sign-on
and 355 with the AI agent, none failed), the image `soundings:0.2.0` (525 MB), and on
k3s an upgrade of 0.1.0 with its demo data to 0.2.0 through `scripts/deploy.sh`
(migrations 0011 → 0015, row counts unchanged, the new features working on the migrated
data), then the smoke tests as CI runs them, production mode and two API replicas:
[Phase 8 and 8b summary](phase-summaries/phase-8.md),
[Phase 9 summary](phase-summaries/phase-9.md).

### What's new in 0.2.0

#### Per-project proposal templates (Phase 8)

- Project settings → **Proposal template**: project admins add, remove, rename and
  reorder the sections every proposal in the project has (1–12, each with a title and a
  one-line hint shown in the editor). New and existing projects start from the eight
  sections 0.1.0 had.
- Sections keep a stable key, so renaming or reordering keeps their text, margin threads
  and suggestions. **Removing a section loses nothing**: its text is kept, hidden, under
  "Removed sections", and **Restore** brings it back where it was, with its text.
- One template per project, live: the editor, margin threads, suggestions, "Draft with
  AI", MCP (`get_proposal`, `propose_proposal_section`) and both exports follow it at
  once.

#### The research step (Phase 8)

- Optional per project (Project settings → **Research**): **before evaluation**
  (New → Research → Evaluating …) or **before the proposal** (… Shortlisted → Research →
  Proposal). Off by default; projects without it see nothing new.
- A **checklist** (1–10 items, title, hint, required or not; three defaults: "Not already
  being done elsewhere", "Departments or teams consulted", "Data protection considered")
  answered in plain text on the idea's **Research** panel, with who answered and when.
- **The gate**: an idea can't cross into a status after Research while a required item is
  open (a status change, a board drag, the first evaluator invite, "Ask AI to evaluate",
  starting the proposal). Moving back or closing is never held up. Project and platform
  admins may **Move anyway** (also Invite, Ask, Start anyway), with an optional reason,
  in the audit log and the feed.
- **Similar ideas** (similar titles and summaries in every project you can see, archived
  ones too, never held ideas, no scores) and **Ask AI to research** help with the check.
- The board's **Research column** and cards show "2 open" or "Ready"; the proposal editor
  and both exports end with a **Research and consultation** appendix; public submitters
  never see Research (their tracking page keeps the stage before it).

#### The research assigned to a person, outside researchers (Phase 8b)

- **One researcher per idea** (nobody = the owner does it) with an optional **research
  due date**. The owner, project admins and platform admins ask someone (in a session);
  in a **private** project only admins may ask someone without a role there. The
  researcher can **Hand back**. "Start research" asks who and by when.
- **Asked to research** and **Research reminder** notifications (2 days before and on the
  due date, at the digest hour, while required items are open): in the app and by email,
  with per-type preferences, the digest and unsubscribe links; never score data.
- My work's **Research to do** (overdue first) and the sidebar's Research badge; Research
  cards show the researcher.
- **An outside researcher** (no role in a private project) sees **that one idea** only:
  its overview, comments, the feed's allow-listed events, the checklist and Similar ideas
  among what they could see anyway. Never scores, the evaluation area, the proposal, the
  AI panel or the project (404), through REST, MCP, search, ⌘K, My work and the inbox
  alike. Access ends at the next request when they are unassigned or hand it back, the
  idea is closed or the step turned off, they are deactivated, they leave the private
  project, or the project is made private (its admin is warned first with how many people
  lose access).
- Once an idea is **past Research**, the research is done: a researcher who isn't the
  owner or an admin can no longer change the answers, nobody new can be asked (the panel
  offers Remove), and a required answer can be changed but not cleared.

#### Continuous delivery from self-managed GitLab and GitHub (Phase 9)

- Every **push to main** builds the image (rootless BuildKit, or `docker buildx` on dind),
  scans it (Trivy: `HIGH,CRITICAL` with a fix fail the pipeline; a CycloneDX SBOM), and
  deploys **staging**. A **`vX.Y.Z` tag** checks the versions, rebuilds with that version,
  deploys staging, publishes the release (SBOM, chart) and waits at the **production
  gate**, which deploys the very digest staging ran.
- **GitLab self-managed** reaches the cluster only through the GitLab agent for
  Kubernetes (one agent per environment, namespace-scoped rights, protected refs only; no
  cluster credential in GitLab). **GitHub Actions** deploys from self-hosted runners in
  your network (ARC) whose pods have no rights, with a namespaced kubeconfig per
  environment.
- One script, **`scripts/deploy.sh`** (deploy, rollback, smoke, status), for both CIs and
  people: a render check, `helm upgrade --atomic` by digest, `helm test`, a
  production-safe smoke, and an automatic rollback when any of them fails; migration
  heads recorded on every revision, so a rollback across a migration is refused unless
  forced; one CI per environment.
- Rehearsals: `make k3s-deploy` (the script as a namespaced deployer on a local k3s) and
  `scripts/ci-local/` (a whole self-managed GitLab with its registry, agents and a runner,
  on which the pipeline ran end to end). `.gitlab/CODEOWNERS`, `make check-workflows`
  (actionlint, zizmor, gitlab-ci-local) and `make check-migrations` (expand/contract
  lint) keep the delivery path reviewed.

#### Review fixes

Each phase had security, code and UX reviews (Phase 8b also a guest-access review and an
adversarial check of the follow-ups); every finding was fixed or decided by the lead
([decisions.md](decisions.md), the summaries list each one). The main ones:

- **Phase 8:** a required answer can't be cleared once the idea is past Research;
  blank-looking answers and titles (only invisible characters) are refused; titles that
  Postgres folds together ("Idea", "İdea") are a 422, not a 500; public tracking history
  keeps the step a move happened under; unsaved answers are kept as drafts; focus never
  drops to the page after removing a row; calmer badges and warnings; hints visible, not
  placeholders; 390 px fixes; My work faster (migration 0014's indexes, 10 ideas per owned
  group).
- **Phase 8b:** an AI research run reads only what the idea's guest researcher can
  (`search_ideas`, `get_idea`); a guest's "last activity" comes from their own feed;
  "Asked to research" emails wait 5 minutes when the idea was just passed round, and one
  person's requests email at most 20 people an hour; overdue due dates stay choosable; a
  guest's @mentions list only people on the idea; focus after Hand back and when access
  ends; one feed line per assignment; the researcher's answers lock after Research (D1);
  outsiders leave when a project goes private (D2); nobody new is asked past Research.
- **Phase 9:** 3 high, 8 medium and 12 low findings (who can deploy production, runner
  pods' standing rights, cache poisoning, deploy-only runners, pipeline variables,
  migration labels after a rollback, schema breaks, GitHub's production gate, the air
  gap, run order, concurrent deploys) and 9 defects the live GitLab run found, all fixed
  or documented.
- **Release verification (this release):** the CI k3s job's external-database test
  (`scripts/k3s-test-external-db.sh`) couldn't create its database since Phase 7's
  non-superuser Postgres role, nor reach it through the bundled Postgres's NetworkPolicy;
  one notification test failed between midnight and 08:00 UTC. The re-captured
  screenshots found two lines the research work had missed: the unsubscribe page's
  footer didn't name research, and Admin → Email didn't list the research reminders.

### Known issues in 0.2.0

| Item | Detail |
|---|---|
| **Not verified: GitLab Premium's protected environments and deployment approvals** | The live run used GitLab CE (the Free tier): the gate there was the protected tag's manual job. The Premium setup the operator guide now leads with (protected environments, a required approval, Code Owners) is from GitLab 19.4's documentation and source, not a run. |
| **Not verified: the GitLab-specific changes after the live run** | Cache flags by protected ref, `DEPLOY_RUNNER_TAG`, the 90-minute timeouts, production refusing a `CD_ONLY` pipeline and the `migrations:lint` job were checked with gitlab-ci-local, GitLab's source and linters only. The local GitLab (`scripts/ci-local/`) wasn't run again for 0.2.0: it needs about 12 GB of free disk and the build machine had 7. |
| **Not verified: the Kubernetes executor, cosign, alpine/k8s** | Both build paths ran on GitLab's Docker executor (rootless BuildKit unprivileged, dind privileged); the Kubernetes executor's settings are documented, not run. cosign's image is on ghcr.io, whose blobs can't be fetched here: signing never ran. The default `DEPLOY_IMAGE` (alpine/k8s, 1.3 GB) didn't fit the disk; the live jobs used the `tools` target. |
| **Not verified: GitHub's runners, GHCR, ARC, environments** | No GitHub runner can register here. The workflows lint clean (actionlint, zizmor), and `deploy-env.yml`'s step ran in the cluster as an ARC runner (in-cluster identity) and with `KUBECONFIG_DATA`, but no workflow ran on GitHub: not the image build on GitHub's runners, GHCR, ARC itself, environments with required reviewers or `deploy.yml`'s `gh release download`. |
| **kagent is still verified against its CRDs and Soundings' fake agent only** | As in 0.1.0: no kagent controller or LLM has carried a run; "Ask AI to research" now reads only what a guest researcher could, against the fake. |
| The long CI jobs haven't run in a pipeline | The live GitLab run skipped lint, tests, e2e and the k3s job (`CD_ONLY`) to fit the disk; every command they run passed on the build machine. |
| Guest researchers in no project at all | The demo's two internal projects are visible to everyone, so "a researcher in no project" is tested on the SPA's mock only. Reminders by date are tested with a moved clock (the acceptance test), not by waiting. |
| Accepted from the reviews | A guest's open AI progress stream ends at its next 30 s re-check, not at once; a 404 for a hidden idea and one for a missing idea take different times (keys are sequential anyway); research answers aren't audited (who and when are recorded). |
| Per-pod limits, the 20-people p95, interaction timings at 4x CPU throttling, kagent's cancel, retention, invented sources, the Radix arrow-key case | As in [0.1.0](#known-issues-and-limitations). Unchanged by 0.2.0; `make -C backend test-slow` meets every 150 ms budget one request at a time on a quiet machine (My work for an owner and the board by score had 200 ms during Phase 8 and are back at 150). |
| The image is 525 MB | Ubuntu 24.04 with the PDF libraries; a slimmer final stage is still deferred. |

### Upgrading from 0.1.0

- **Migrations 0012 to 0015** run in one go before the new pods serve (`helm upgrade` or
  `scripts/deploy.sh`), rehearsed on 0.1.0's demo data: row counts unchanged. 0012 gives
  every existing project the eight proposal sections it had and leaves the research step off,
  so nothing changes for anyone until a project admin edits them; 0013 adds two trigram
  indexes for Similar ideas (seconds per 10,000 ideas); 0014 swaps indexes for My work
  and the cards' counts; 0015 adds the research assignment and two notification types
  (anyone who had every type off gets them off too). Downgrading is an emergency only
  (restore a backup if you can): below 0015 every research assignment and due date is
  lost, below 0012 custom template sections, checklists and answers.
- **The image defaults to production** (`SOUNDINGS_ENVIRONMENT=production`, since
  0.1.0): `soundings api` and `worker` refuse the built-in development key unless the
  environment says `development` (the chart's `devLogin=true` does).
- **No new Helm values.** The bundled Postgres's pod no longer carries the version and
  chart labels, so it restarts once on this upgrade (and never again on a deploy).
- **Moving a hand-installed release to continuous delivery**: create `soundings-app`
  and `soundings-break-glass` from the release's generated Secret first, or the secret
  key and break-glass password change ([operator guide, "Upgrades and
  migrations"](operator-guide.md#upgrades-and-migrations-pre-upgrade-hook-argo-cd-presync));
  `scripts/deploy.sh` then takes the release over, and refuses a rollback to the
  hand-installed revision (its migrations are unknown).
- **API (additive)**: proposal templates (`GET/PUT /projects/{slug}/proposal-template`),
  the research step (`GET/PUT /projects/{slug}/research`, `GET /ideas/{idea}/research`,
  answers `PUT/DELETE /ideas/{idea}/research/items/{item_id}`, `GET
  /ideas/{idea}/similar-ideas`), the assignment (`PUT/DELETE
  /ideas/{idea}/research/assignment`, `GET /me/research-to-do`), the `research` status,
  new fields on ideas, summaries, projects and My work, new error codes
  (`research_incomplete`, `research_step_off`, `ideas_in_research`, `unknown_section`,
  `research_answer_required`, `research_finished`, `researcher_not_eligible`,
  `outside_researcher_needs_admin`) and audit actions (`project.proposal_template_replace`,
  `project.research_step_change`, `project.research_checklist_replace`,
  `idea.research_override`, `idea.researcher_change`); MCP's `get_idea` carries the
  research and `research_guest` ([contract-phase8](api/contract-phase8.md),
  [contract-phase8b](api/contract-phase8b.md)). "Research this" is now called "Ask AI to
  research".
- **New checks**: `make check` also runs `check-workflows` and `check-migrations`; new
  migrations (0016 on) must be expand/contract safe, so a failed deploy can roll back.

### Decisions to confirm in 0.2.0

The lead's defaults ("Proposed" or "Decided (lead)" in [decisions.md](decisions.md)),
built that way and easy to change; the product owner already decided the research
step's purpose and shape, outsiders as researchers, S1 (a, b), S8, the GitLab tier and
the scan gate.

**Research step and templates**
1. **"Crossing only"**: the gate guards moves *into* a status after Research; ideas
   already past it (before the step was turned on, or moved on anyway) move freely among
   later statuses, and reopening counts from the status the idea was closed from.
2. Similar ideas include **archived projects**; public tracking shows **the stage before
   Research**; answers are plain text, last write wins, not audited or notified.
3. Template and checklist saves are last write wins; no "Reset to the default eight";
   removed sections and items come back where they were.

**The researcher and guest access**
4. **What a guest researcher sees** (role matrix column R, table L): the idea's overview,
   comments, the feed without its evaluation events, the checklist, Similar ideas among
   what they see anyway; the inbox only status changes, comments, @mentions and the
   research notifications; their @mentions list only people on the idea. In an internal
   project an outsider keeps the non-member view and gains answering, commenting and
   Hand back.
5. **D1**: past Research a researcher who isn't the owner or an admin can't change the
   answers (409 `research_finished`).
6. **D2**: making an internal project private ends the research of everyone without a
   role in it, after a warning.
7. **D3**: "Asked to research" emails wait 5 minutes when the idea asked someone less
   than 5 minutes before; one person's requests email at most 20 people an hour (then
   in-app only); one notification per assignment.
8. **D4**: an owner asked by name stays the researcher when the idea changes owner.
9. **L2**: past Research nobody new can be asked (Remove only; moving the idea back lets
   the owner ask again).

**Continuous delivery**
10. **One CI per environment** (`SOUNDINGS_DEPLOY`; production needs staging in the same
    CI); tags are rebuilt with their version, and production deploys the digest staging
    ran.
11. **The deploy script's refusals**: across a migration head, an older pipeline's or an
    older `X.Y.Z`'s deploy, another CI's release, each unless `DEPLOY_FORCE=1`; *Prevent
    outdated deployment jobs* stays off on GitLab.
12. **Images and signing**: `DEPLOY_IMAGE` defaults to alpine/k8s by digest (the `tools`
    image recommended for production); cosign optional, with a key and no transparency
    log, verified by an admission policy rather than in the CI.
13. **GitHub**: a 30-day namespaced token per environment (`KUBECONFIG_DATA`, renewed
    monthly); on Pro and Team the production gate is one listed person
    (`SOUNDINGS_PRODUCTION_DEPLOYERS`), not two; private Free repositories aren't
    supported for production.
14. The rollback jobs stay `action: access` (protected environments and approvals still
    apply to them), and the deployer's optional kinds (kagent, Gateway API,
    ServiceMonitor) stay in its one ClusterRole.

## 0.1.0

**Released:** 2026-10-07 (the end of Phase 7, SPEC section 13). It is the first release:
Phases 0–7 complete, waiting for the product owner's review.

Soundings is a calm, fast web app where people submit ideas, anonymously too through a
public form. Each idea gets one accountable owner and several evaluators, who score it
blind against a short rubric. Strong ideas become a commercial proposal exported to PDF
or Markdown. kagent agents can act as an extra evaluator or research assistant. It is
one container image and one Helm chart, needs only PostgreSQL, sends mail through any
SMTP server and runs air-gapped. Tour: [README](../README.md#a-tour). Guides:
[user](user-guide.md), [operator](operator-guide.md), [MCP](mcp.md).

**Verified on 2026-10-07** (the build machine, not yet a real CI runner): every check
(6,336 backend tests, 589 unit and 387 page tests in the SPA, the end-to-end suite in its
three modes), the image `soundings:0.1.0`, and on k3s the operator guide's one-command
`helm install`, `helm test`, an upgrade with SSO, SMTP, MCP and AI, then two API
replicas, with every smoke test passing:
[Phase 7 summary](phase-summaries/phase-7.md#acceptance-evidence-final-verification-2026-10-07).

### What's in it, by area

#### Ideas, owners and evaluators (Phase 1)

- **Projects**, private or internal, with members by person or by group (admin,
  member, viewer). The rubric has 3–6 weighted criteria (some inverted, such as Effort
  and Risk). The status labels can be renamed, but the five statuses are fixed: New,
  Evaluating, Shortlisted, Proposal, Closed (Accepted, Rejected or Parked).
- **Ideas** have a title, a summary, a Markdown description, tags, comments with
  @mentions, votes and watching. Each idea has one **owner**, assigned by an admin or
  volunteered for ("I'll own this"). The owner invites **evaluators** with a due date,
  moves the idea between statuses, and closes or reopens evaluation.
- **Blind evaluation.** Evaluators score each criterion 1–5 with an optional comment
  and recommend Go, Maybe or No. Until they submit they see no score data anywhere:
  not in the app, emails, search, exports, the API, MCP or AI run progress. The
  **aggregate** is the weighted mean, with the number of evaluations and a "high
  disagreement" flag (a spread of 2 or more points on any criterion).
- **Screens:** My work, the board and the list (sort by score, filters, search), the
  idea page, the evaluate sheet, the command palette (⌘K) and keyboard shortcuts (`?`).
  Every screen has dark mode and works at 390 px.

#### Sign-in and access (Phase 2)

- **Single sign-on** with OIDC (code flow with PKCE): Keycloak, Microsoft Entra ID,
  Google. Accounts are matched by an external ID claim, then by a verified email, or
  optionally created at first sign-in. Pre-created users are linked at their first
  sign-in.
- **Groups and IdP mappings**: managed mappings follow the directory at each sign-in,
  additive ones only add. Projects grant roles to groups.
- A **break-glass admin** works only while SSO is not configured. A **development login**
  exists only in development mode.
- Sessions last 24 hours at most and end after 12 hours idle. `__Host-` cookies are
  used in production. The **audit log** records sign-ins, admin and access changes,
  assignments and evaluations.

#### Email and notifications (Phase 3)

- Seven notification types, in the app (the bell and the inbox) and by email, chosen
  per type: immediately, in a daily digest, or off. Reminders arrive before and on the
  due date, at a set hour in the instance's time zone.
- A **transactional outbox** sent by the worker, with retries and backoff. An SMTP
  outage delays mail; it never loses it. Admin → Email shows the settings in effect,
  the outbox and a test email.
- Branded HTML and text emails with one-click unsubscribe (RFC 8058) and scoped
  unsubscribe links. **Emails never carry scores.**

#### Proposals, public submission and branding (Phase 4)

- **Proposals** follow a fixed eight-section template, saved per section with conflict
  detection. Comments sit in the margin, suggestions are accepted or discarded, and the
  proposal exports to **Markdown or a branded, tagged PDF**. The PDF uses bundled fonts
  and renders in a time-limited child process that fetches nothing.
- **Public form** at `/<project>/submit`, with a honeypot, an ALTCHA proof of work,
  per-address and per-project limits, optional email confirmation and moderation (on by
  default). Submitters get a private tracking link (the token stays after `#`), status
  emails and "Delete my details". Admins can erase a submitter's details, and retention
  rules run hourly.
- **Branding**: a global profile and per-project overrides (colours, four bundled
  fonts, a PNG or SVG logo, a favicon, an email footer). They apply to the app, public
  pages, emails and PDFs.

#### API keys and MCP (Phase 5)

- **Personal API keys** have scopes (`read`, `write`, `evaluate`, `mcp`), an optional
  expiry and an optional restriction to some projects. A key is shown once and can't be
  changed afterwards. It never does more than its owner may do right now, and revoking
  it cuts access at the next call.
- An **MCP server** at `/mcp` offers ten tools over the same services and policy as the
  REST API: search and read ideas (blind), create ideas, comment, evaluate, propose
  proposal text, and more. Every call is audited. Claude Code, Claude Desktop and the
  SDKs connect with a key ([mcp.md](mcp.md)).

#### AI assistance through kagent (Phase 6)

- Platform admins **register kagent agents** (namespace and name, protocol, purposes,
  projects). Each agent gets a service account and one key, shown once with its Secret
  and `RemoteMCPServer` manifests.
- Owners can use **Ask AI to evaluate**, **Research this** and **Draft a section**.
  These start durable runs that the worker sends over A2A, with a deadline, cancel,
  retries and live progress over SSE.
- Agents act through `/mcp`, confined to the idea of their open run and **always
  blind**. An AI evaluation carries a rationale and cited sources per criterion and an
  AI badge. It stays **out of the aggregate until the owner includes it**.

#### Polish and hardening (Phase 7)

- **Accessibility (WCAG 2.2 AA audit):**
  - a switch to turn off single-key shortcuts;
  - one highlight ring and a 3:1 control colour;
  - focus never hidden under sticky bars, and moved to the page heading after
    navigation;
  - Undo messages last 10 s and pause while you are on them;
  - rubric criteria can be moved without dragging;
  - tagged PDFs and email landmarks.
  - axe checks (WCAG and best-practice rules) cover the main screens on the mock and on
    the real stack.
- **UX:**
  - **Settings** is about you; platform admins get **Admin**;
  - four project settings tabs;
  - one API keys page;
  - the idea's main button follows its status;
  - a first-run welcome;
  - pickers open on the current value;
  - a phone-first project header;
  - one layout for public messages;
  - many smaller fixes ([decisions](decisions.md#2026-10-07--phase-7-fixes-frontend)).
- **Performance with 10,000 ideas** ([performance.md](test-plans/performance.md)):
  - the sidebar's counts come from their own endpoint;
  - My work pages its evaluations due and shows 10 ideas per owned group;
  - faster short searches and tag counts;
  - first-load JavaScript cut from 1,026 kB to 636 kB;
  - Brotli and gzip for the SPA, and gzip for JSON;
  - smoother list scrolling.
- **Security (OWASP ASVS L2 review):**
  - the image starts in production mode and refuses the development key;
  - ALTCHA bounds;
  - a 120-a-minute write limit per person;
  - the bundled Postgres app role is not a superuser;
  - API docs only for signed-in callers in production;
  - bounded SSO callback parameters;
  - NetworkPolicy guidance for trusted proxies;
  - a CI audit job (pip-audit, npm audit, Trivy);
  - `soundings anonymise-user` for leavers, with a table of what is stored about users.
- **Docs:** the [user guide](user-guide.md), the [operator guide](operator-guide.md)
  and this README, all checked against the running app.

### Known issues and limitations

| Item | Detail |
|---|---|
| **kagent is verified against its CRDs and a fake agent only** | No kagent controller or LLM has carried a run. The A2A client, the MCP side and the manifests are tested against Soundings' fake agent (`dev/fake-agent`, a2a-sdk 1.2.1 at kagent v0.10.2's paths) and a server-side dry run of every manifest against kagent v0.10.2's real CRDs. On a cluster with kagent, start with `deploy/kagent/fake-agent-byo.yaml` ([deploy/kagent/README.md](../deploy/kagent/README.md)). |
| **The CI pipelines haven't run** | `.github/workflows/ci.yml` and `.gitlab-ci.yml` were written and every command they run passed on the build machine, but neither pipeline has run on a real runner. Trivy (the image scan) couldn't run here at all. |
| 20 people at once on one API pod: reads at p95 206–255 ms (budget 150 ms) | Medians are well inside the budget. The tail is overlapping requests sharing one event loop per pod. Scale with `api.replicas`. Two workers per pod was declined: it doubles memory. |
| Some interactions take longer than 100 ms at 4x CPU throttling (budget 100 ms) | Input to the next frame on a 10,000-idea list: sort 200 ms, filter 160 ms, opening ⌘K 272 ms, opening an idea from the list 208 ms, the evaluate sheet 592 ms; list scrolling drops 70 % of frames. Opening an idea paints the page in the click's frame on purpose: the page shows about 250 ms sooner than when the click only starts a download. Numbers: [performance.md §8–9](test-plans/performance.md#9-final-verification-2026-10-07). |
| Throttles and stream caps are per API pod's memory | With N replicas, a client gets up to N times as much: sign-in, public form, key failures, writes, SSE streams. |
| kagent's Python runtime can't cancel a task | Soundings ends the run anyway and refuses its late writes. kagent keeps what agents read in its own session store, outside Soundings' retention. |
| AI runs, their events and the audit log (except `mcp.call`, 90 days) are kept indefinitely | Back up and prune with your own policy. |
| Agent-cited sources may be invented | They are shown as "Cited by AI, not checked", with their host. |
| Radix radio groups: an arrow key whose key-up arrives with its key-down moves focus without selecting | Normal typing works (low priority in the audit). |
| The image is 524 MB (Ubuntu 24.04 with the PDF libraries) | A slimmer final stage was deferred (security review N5). Rebuild regularly for Ubuntu's security fixes. |
| No in-app help, no started proposal in the demo seed, no licence chosen yet | |
| Out of scope (SPEC non-goals) | Workflow engines, custom fields, webhooks, duplicate detection, attachments, multi-tenancy, a built-in LLM. |

### Upgrade notes

0.1.0 is the first release, so no upgrade path is supported yet. `helm upgrade` runs
the database migrations before new pods serve, and later releases will keep that path.
If you ran a build from before Phase 7, these changes affect you:

- **The image defaults to production** (`SOUNDINGS_ENVIRONMENT=production`).
  `soundings api` and `worker` refuse to start with the built-in development key when
  the environment isn't set. Development setups must set
  `SOUNDINGS_ENVIRONMENT=development`. The chart's `devLogin=true` does this for you.
- **The bundled Postgres:** a fresh volume gets a non-superuser app role. An existing
  volume keeps its roles. To harden one, dump, reinstall with a new volume and restore
  ([operator guide](operator-guide.md#bundled-postgres-vs-external-or-cloudnativepg-database)).
- **New limits:** a signed-in person may make 120 changes a minute per API pod
  (`SOUNDINGS_SESSION_WRITES_PER_MINUTE`). In production, `/api/docs` and the OpenAPI
  document need a session or a key with `read`.
- **NetworkPolicy:** the metrics port admits only `networkPolicy.metricsFrom`. Set
  `networkPolicy.ingressFrom` to your ingress controller's namespace: NOTES warns while
  it is empty.
- **Moved pages:**
  - the admin pages are under **Admin** in the sidebar (old `/settings/...` links still
    work);
  - **All API keys** is now **Settings → API keys → Everyone's keys** (the old address
    redirects);
  - project settings have four tabs (old `?tab=statuses` and `?tab=branding` links open
    the right section).
- **API (additive):** `GET /me/work/counts`, `GET /me/evaluations-due`,
  `ProjectSummary.pending_moderation_count`. `GET /me/work` now lists the first 50
  evaluations due, with `evaluations_due_next_cursor`
  ([contract-phase7.md](api/contract-phase7.md)).

### Decisions to confirm

The calls below were made without the product owner. Each one is the lead's default
("Proposed" in [decisions.md](decisions.md)), built that way and easy to change. Please
confirm or overrule them in one pass.

**Product and access**
1. Only **platform admins create projects**, and they name the first project admin.
2. **Members may volunteer** to own ideas (`allow_volunteer_owners`, default on per
   project). **Evaluators must be project members** (member or admin role).
3. Evaluations are **due 7 days** after the first invite (per project). Reminders go out
   **2 days before and on the due date** (an operator setting, not in the UI).
4. **Only the owner and admins** can ask AI to evaluate, research or draft.
5. "Anonymous" submission means **the public form**. The internal form always records
   the submitter.
6. Submitters may edit their idea only while it is **New**. Owners and admins can edit
   until it is closed.
7. **No classification markings** on ideas or exported proposals.
8. The product name **Soundings**, deep ocean blue `#1d5fa8` and Inter. Wordmark only;
   admins upload a logo.

**Email and notifications**

9. **Defaults:** status changes and new comments arrive in the **daily digest**;
   everything else is emailed immediately. The digest goes out at 08:00 in the instance
   time zone (default UTC).
10. Every email's footer has an **"Unsubscribe from all email"** link. A type's own
    link turns off only that type.
11. Mail older than 3 days (digests: 2) is cancelled rather than sent late. Outbox rows
    are kept 30 days (failed: 90), notifications 90 days.

**Public form and branding**

12. **Moderation is on by default** for a new public form. Email confirmation is off.
    Rejecting deletes the idea, and approving or rejecting sends no email.
13. Contact details of closed public ideas are erased after **180 days idle**.
    Unconfirmed addresses are dropped after 3 days.
14. A project override with its own logo and no app name uses **the project's name as
    the public wordmark** (form, emails, PDF).
15. Emails carry **no logo** (no remote images): the app name is the wordmark.

**Sign-in and keys**

16. Break-glass works **only while SSO is not configured**. In an SSO outage, the
    operator unsets `oidc.issuer`.
17. **Profile fields aren't synced** from the IdP after the first sign-in, and an
    Entra ID group overage denies the sign-in.
18. A person's API key **pauses after 30 days** without a sign-in. A user has at most
    25 keys, and keys can't be edited.
19. The **audit log is kept indefinitely** (except MCP calls, 90 days).

**Declined or deferred in Phase 7** (reasons in [decisions.md](decisions.md))

20. Declined:
    - two uvicorn workers per pod (scale with replicas);
    - one save model everywhere: forms whose fields belong together keep a Save button,
      while preferences and documents save as you go;
    - a Help item in the account menu;
    - a minimum search length and hiding emails in `GET /users`.
21. Deferred:
    - a slimmer image without apt, dpkg, perl and bash;
    - the Radix radio-group arrow-key edge case.
