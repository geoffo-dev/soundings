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
