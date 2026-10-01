# ADR 0003: Background jobs with procrastinate on Postgres + transactional email outbox

- Status: Accepted · Date: 2026-09-30

## Context

We need background work for email (SPEC section 6), reminders and digests, and kagent
runs (section 9). Postgres is the only stateful dependency we want to operate. SPEC
requires that no email is lost when SMTP is briefly down, and that failed sends are
visible to admins with a retry button.

## Decision

- **procrastinate 3.x on the application database** is the job queue; no Redis, no
  broker. The worker is `soundings worker` (same image, see ADR 0004). Its schema is the
  vendored `schema.sql`, applied once by an Alembic migration (it is not idempotent).
- **Outbox table is the source of truth.** Any change that sends mail inserts an
  `outbound_email` row (status, attempts, `next_attempt_at`, `last_error`, fixed
  `Message-ID`) in the *same transaction* as the domain change, and defers
  `send_email(outbox_id)` on the *same psycopg connection*
  (`task.configure(connection=pg).defer_async(...)`). Commit keeps both; rollback drops
  both (verified in [research R1](../research/backend-libraries.md)).
- The `send_email` task locks its row (`SELECT … FOR UPDATE`), sends only if it is
  still pending, and records the result. Retries use exponential backoff with a cap
  (a small custom retry strategy; procrastinate's built-in one has no cap or jitter).
  4xx/connection errors retry; 5xx, refused recipients and auth failures are permanent.
- A periodic `sweep_outbox` job re-defers stale pending rows as a safety net. Admin
  "retry" resets a failed row and defers a new job.
- No `queueing_lock` on in-transaction defers: a lock conflict would abort the whole
  request transaction.
- Tests use procrastinate's `InMemoryConnector`, plus one real-Postgres test of the
  atomic defer.

## Consequences

- Email delivery survives SMTP outages and worker restarts; the Phase 3 acceptance test
  (stop Mailpit, restart, mail arrives) follows from this design.
- Send is at-least-once. Duplicate delivery is possible if the worker dies after SMTP
  accepts but before commit; the fixed `Message-ID` lets mail clients de-duplicate.
- Job load adds to the one Postgres; fine at our scale, and one less service to run.

## Amendment (2026-10-01, Phase 3 contract)

Status: Accepted. Details: [contract-phase3 §3.9](../api/contract-phase3.md#39-the-outbox-and-the-worker).

- **Claim with a lease instead of holding the row lock while sending.** `send_email`
  claims its row in a short transaction (`UPDATE … SET status = 'sending', attempts =
  attempts + 1, next_attempt_at = now() + 5 minutes WHERE status = 'queued' AND
  next_attempt_at <= now()`), commits, talks to SMTP, then records `sent`, the next
  attempt or `failed` in a new transaction. No transaction spans the SMTP
  conversation; in-flight mail is visible as `sending`; two jobs can't send one
  attempt. The attempt (load, render, SMTP) must finish within 4 minutes
  (`asyncio.timeout`), so a slow but live worker never overlaps a re-claim.
  `sweep_outbox` (every minute, and only while SMTP is configured) re-queues `sending`
  rows whose lease expired (a crashed worker) and re-defers queued rows whose job was
  lost, with `queueing_lock = "send_email:<id>"` so each row has at most one waiting
  sweep job.
- **Bounded job table.** The worker runs with `delete_jobs="successful"` and a daily
  `remove_old_jobs` (failed, cancelled and aborted jobs after a week): procrastinate
  keeps every job by default, and the sweep alone would add 1,440 a day.
- **Each attempt is its own job.** Failures don't raise into procrastinate's retry:
  the task computes the backoff (30 s doubling to a 1-hour cap, jitter, 12 attempts)
  and defers the next `send_email` with `schedule_at`. The row stays the source of
  truth; procrastinate only wakes the worker.
- **Rendered at send time.** The row stores no subject or body; the worker renders
  from the notifications that point at it, after re-checking the recipient's access,
  their current preference and the mail's age (3 days; digests 2), and cancels the
  email (without contacting SMTP) when nothing may be sent or it is out of date.
- **One recipient.** Every address must be one plain ASCII address; `To` is built with
  `Address(addr_spec=…)` and the SMTP envelope is passed explicitly
  (`recipients=[address]`), so no address can name a second recipient.
- **No rows without SMTP.** When `SOUNDINGS_SMTP_HOST` is unset nothing is enqueued
  (in-app notifications only); rows queued before SMTP was switched off wait untouched.
- **Classification refined:** 4xx replies, connection-level errors (refused, timeout,
  disconnect, TLS handshake or certificate), the attempt deadline, authentication
  failures (530/534/535/538: a password rotation shouldn't fail the queue) and SMTP
  errors without a code retry; other 5xx replies (refused recipients, sender or
  message) are permanent; any non-SMTP exception after the claim fails the row at once
  ("Internal error"). `last_error` is a phrase built by our code, never the server's
  text or an exception message.
- Unchanged: in-transaction defer on the request's psycopg connection, no
  `queueing_lock` on it, at-least-once delivery with a fixed Message-ID, admin retry
  (of failed mail that is still recent enough; there is no admin cancel).
