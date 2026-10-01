"""One delivery attempt and the outbox sweep (contract-phase3 section 3.9).

:func:`send_email`:

1. **claim** the row in its own short transaction (``queued`` and due -> ``sending``,
   ``attempts + 1``, a 5-minute lease); no row, no work (sent, cancelled, not due, or
   another worker has it). Nothing happens while SMTP isn't configured;
2-4. under a 4-minute deadline: load and re-check (:func:`app.email.content.prepare`),
   render, send to exactly one recipient;
5. **record** the outcome in a new transaction, only if the row is still ``sending``
   with this attempt: ``sent``; ``cancelled`` (not sent, never will be); a transient
   failure -> ``queued`` again after :func:`~app.email.outbox.backoff`, with the next
   job deferred in the same transaction; a permanent failure, the last attempt, or
   an internal error -> ``failed``.

Delivery is at-least-once: a crash between the server's acceptance and step 5 leaves
the row ``sending``; the sweep re-queues it after the lease, and the resend has the
same Message-ID. Logs carry ids, types, attempt numbers and error classes only.

While the server is unreachable (five connection failures in a row: refused, timed
out, cut off) the worker's :class:`Breaker` is open: due emails are **postponed** to the
end of the pause without being claimed (no attempt used, no connection made), and the
first attempt after the pause probes the server. A blackholed server then costs one
connection timeout per pause instead of one per email, and sends never crowd out the
sweep or the schedule (which also run first: their jobs have a higher priority). Test
emails are always tried: an admin's test is a probe.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Literal
from uuid import UUID

import aiosmtplib
from procrastinate import App
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import SessionMaker, session_scope
from app.email import content, outbox
from app.email.message import build_message
from app.email.model import DEFAULT_BRANDING
from app.email.render import render
from app.email.smtp import Failure, SmtpTransport, Transport, classify, internal_failure
from app.models.base import utcnow
from app.models.enums import EmailStatus, EmailType
from app.models.notification import OutboundEmail
from app.observability import EMAILS_CANCELLED, EMAILS_FAILED, EMAILS_QUEUED, EMAILS_SENT

__all__ = [
    "WORKER_STOPPED",
    "Breaker",
    "Outcome",
    "Runtime",
    "SweepResult",
    "send_email",
    "sweep_outbox",
]

logger = logging.getLogger("soundings.email")

WORKER_STOPPED: Final = "Worker stopped while sending"
LOST_JOB_GRACE: Final = timedelta(minutes=1)


@dataclass(slots=True)
class Breaker:
    """A circuit breaker for one worker's SMTP server.

    Opens after :attr:`threshold` unreachable attempts in a row, for :attr:`cooldown`
    (doubling on each reopening up to :attr:`max_cooldown`); afterwards the next
    attempts probe the server: one more unreachable attempt reopens it, any attempt
    that reached the server (sent, or a reply such as 451) closes it.
    """

    threshold: int = 5
    cooldown: timedelta = timedelta(seconds=30)
    max_cooldown: timedelta = timedelta(minutes=5)
    failures: int = 0
    pause: timedelta = timedelta(0)
    open_until: datetime | None = None

    def is_open(self, now: datetime) -> bool:
        return self.open_until is not None and now < self.open_until

    def failed(self, now: datetime) -> None:
        """An attempt that couldn't reach the server."""
        self.failures += 1
        if self.failures < self.threshold:
            return
        self.pause = min(self.pause * 2, self.max_cooldown) if self.pause else self.cooldown
        self.open_until = now + self.pause
        self.failures = self.threshold - 1  # half-open afterwards: one failure reopens
        logger.warning(
            "SMTP server unreachable: pausing sends",
            extra={"pause_seconds": int(self.pause.total_seconds())},
        )

    def succeeded(self) -> None:
        """An attempt that reached the server."""
        if self.open_until is not None:
            logger.info("SMTP server reachable again: sending")
        self.failures = 0
        self.pause = timedelta(0)
        self.open_until = None


@dataclass(slots=True)
class Runtime:
    """What the jobs need: settings, a session factory, the SMTP transport, the opened
    job queue (for the sweep's own defers) and a clock (tests inject one)."""

    settings: Settings
    sessionmaker: SessionMaker
    jobs: App | None = None
    transport: Transport | None = None
    clock: Callable[[], datetime] = utcnow
    rng: random.Random = field(default_factory=random.Random)
    deadline: timedelta = outbox.ATTEMPT_DEADLINE
    breaker: Breaker = field(default_factory=Breaker)

    def __post_init__(self) -> None:
        if self.transport is None:
            self.transport = SmtpTransport(self.settings)


Outcome = Literal[
    "skipped", "not_claimed", "postponed", "sent", "cancelled", "retry", "failed", "lost"
]
"""``lost``: the row changed under us (its lease was re-claimed); nothing recorded.
``postponed``: the breaker is open; the row waits for the end of the pause."""
POSTPONE_SPREAD: Final = 0.25
"""Postponed rows are spread over the first quarter of a pause after it ends, so they
don't all reach the server at the same moment."""


async def _claim(runtime: Runtime, email_id: UUID) -> content.OutboxRow | None:
    now = runtime.clock()
    async with session_scope(runtime.sessionmaker) as db:
        row = (
            await db.execute(
                update(OutboundEmail)
                .where(
                    OutboundEmail.id == email_id,
                    OutboundEmail.status == EmailStatus.QUEUED,
                    OutboundEmail.next_attempt_at <= now,
                )
                .values(
                    status=EmailStatus.SENDING,
                    attempts=OutboundEmail.attempts + 1,
                    next_attempt_at=now + outbox.LEASE,
                    updated_at=now,
                )
                .returning(
                    OutboundEmail.id,
                    OutboundEmail.type,
                    OutboundEmail.attempts,
                    OutboundEmail.max_attempts,
                    OutboundEmail.created_at,
                    OutboundEmail.message_id,
                    OutboundEmail.recipient_user_id,
                    OutboundEmail.to_address,
                    OutboundEmail.requested_by_id,
                    OutboundEmail.payload,
                )
                .execution_options(synchronize_session=False)
            )
        ).first()
    if row is None:
        return None
    return content.OutboxRow(
        id=row.id,
        type=row.type,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        created_at=row.created_at,
        message_id=row.message_id,
        recipient_user_id=row.recipient_user_id,
        to_address=row.to_address,
        requested_by_id=row.requested_by_id,
        payload=row.payload or {},
    )


async def _attempt(runtime: Runtime, email: content.OutboxRow) -> content.Cancelled | None:
    """Steps 2-4: ``None`` when the server accepted the message."""
    settings = runtime.settings
    async with runtime.sessionmaker() as db:
        prepared = await content.prepare(db, settings, email, now=runtime.clock())
        await db.rollback()  # read-only
    if isinstance(prepared, content.Cancelled):
        return prepared
    rendered = render(prepared.content, DEFAULT_BRANDING)
    message = build_message(
        rendered,
        prepared.content,
        settings=settings,
        to_address=prepared.address,
        message_id=email.message_id,
        now=runtime.clock(),
    )
    assert runtime.transport is not None  # noqa: S101 - set in __post_init__
    assert settings.smtp_from is not None  # noqa: S101 - smtp_configured
    await runtime.transport.send(message, sender=settings.smtp_from, recipient=prepared.address)
    return None


async def send_email(runtime: Runtime, email_id: UUID) -> Outcome:
    """One attempt at one outbox email (the ``send_email`` job). Never raises for SMTP
    errors: the row records them and the next attempt is its own job."""
    if not runtime.settings.smtp_configured:
        return "skipped"  # the row waits, untouched, until SMTP is configured again
    if runtime.breaker.is_open(runtime.clock()) and await _postpone(runtime, email_id):
        return "postponed"
    email = await _claim(runtime, email_id)
    if email is None:
        return "not_claimed"
    failure: Failure | None = None
    cancelled: content.Cancelled | None = None
    try:
        async with asyncio.timeout(runtime.deadline.total_seconds()):
            cancelled = await _attempt(runtime, email)
    except TimeoutError as exc:
        # aiosmtplib's own timeouts are TimeoutErrors too: classify those as SMTP.
        failure = classify(exc) if _is_smtp(exc) else Failure(True, "timed out", "AttemptDeadline")
    except OSError as exc:  # aiosmtplib's connection errors, TLS errors, refused
        failure = classify(exc)
    except Exception as exc:  # noqa: BLE001 - recorded as an internal error, below
        failure = classify(exc) if _is_smtp(exc) else internal_failure(exc)
    return await _record(runtime, email, failure=failure, cancelled=cancelled)


def _is_smtp(exc: BaseException) -> bool:
    return isinstance(exc, aiosmtplib.SMTPException)


async def _postpone(runtime: Runtime, email_id: UUID) -> bool:
    """While the breaker is open: move a due, queued row (not a test email) to the end
    of the pause, with its next job, without claiming it. ``False``: nothing to do here
    (not due, not queued, or a test email to try now)."""
    breaker = runtime.breaker
    assert breaker.open_until is not None  # noqa: S101 - only while open
    now = runtime.clock()
    spread = breaker.pause * runtime.rng.uniform(0, POSTPONE_SPREAD)
    retry_at = breaker.open_until + spread
    async with session_scope(runtime.sessionmaker) as db:
        postponed = await db.scalar(
            update(OutboundEmail)
            .where(
                OutboundEmail.id == email_id,
                OutboundEmail.status == EmailStatus.QUEUED,
                OutboundEmail.next_attempt_at <= now,
                OutboundEmail.type != EmailType.TEST,
            )
            .values(next_attempt_at=retry_at, updated_at=now)
            .returning(OutboundEmail.id)
            .execution_options(synchronize_session=False)
        )
        if postponed is not None:
            await outbox.defer_send(db, [email_id], schedule_at=retry_at)
    return postponed is not None


async def _record(
    runtime: Runtime,
    email: content.OutboxRow,
    *,
    failure: Failure | None,
    cancelled: content.Cancelled | None,
) -> Outcome:
    now = runtime.clock()
    outcome: Outcome
    values: dict[str, object] = {"updated_at": now}
    retry_at: datetime | None = None
    if failure is None and cancelled is None:
        outcome = "sent"
        values |= {
            "status": EmailStatus.SENT,
            "sent_at": now,
            "next_attempt_at": None,
            "last_error": None,
        }
    elif cancelled is not None:
        outcome = "cancelled"
        values |= {
            "status": EmailStatus.CANCELLED,
            "next_attempt_at": None,
            "last_error": cancelled.reason,
        }
    else:
        assert failure is not None  # noqa: S101
        if failure.transient and email.attempts < email.max_attempts:
            outcome = "retry"
            retry_at = now + outbox.backoff(email.attempts, rng=runtime.rng)
            values |= {
                "status": EmailStatus.QUEUED,
                "next_attempt_at": retry_at,
                "last_error": failure.last_error,
            }
        else:
            outcome = "failed"
            values |= {
                "status": EmailStatus.FAILED,
                "next_attempt_at": None,
                "last_error": failure.last_error,
            }
    async with session_scope(runtime.sessionmaker) as db:
        recorded = await db.scalar(
            update(OutboundEmail)
            .where(
                OutboundEmail.id == email.id,
                OutboundEmail.status == EmailStatus.SENDING,
                OutboundEmail.attempts == email.attempts,
            )
            .values(values)
            .returning(OutboundEmail.id)
            .execution_options(synchronize_session=False)
        )
        if recorded is not None and retry_at is not None:
            await outbox.defer_send(db, [email.id], schedule_at=retry_at)
    if failure is not None and failure.unreachable:
        runtime.breaker.failed(now)
    elif cancelled is None and (failure is None or failure.code is not None):
        runtime.breaker.succeeded()  # the server answered
    if recorded is None:
        logger.warning(
            "email outcome not recorded: the row changed",
            extra={"outbound_email_id": str(email.id), "attempt": email.attempts},
        )
        return "lost"
    _observe(email, outcome, failure, cancelled)
    return outcome


def _observe(
    email: content.OutboxRow,
    outcome: Outcome,
    failure: Failure | None,
    cancelled: content.Cancelled | None,
) -> None:
    extra: dict[str, object] = {
        "outbound_email_id": str(email.id),
        "type": email.type.value,
        "attempt": email.attempts,
        "outcome": outcome,
    }
    if outcome == "sent":
        EMAILS_SENT.labels(type=email.type.value).inc()
        logger.info("email sent", extra=extra)
    elif cancelled is not None:
        EMAILS_CANCELLED.labels(type=email.type.value).inc()
        logger.info("email cancelled", extra=extra | {"reason": cancelled.reason})
    elif failure is not None:
        kind = (
            "internal"
            if failure.last_error == "Internal error"
            else ("transient" if failure.transient else "permanent")
        )
        EMAILS_FAILED.labels(type=email.type.value, kind=kind).inc()
        log = logger.error if kind == "internal" else logger.warning
        log(
            "email attempt failed",
            extra=extra
            | {"error_class": failure.error_class, "smtp_code": failure.code, "kind": kind},
        )


# --- The sweep -------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SweepResult:
    requeued: int = 0
    failed: int = 0
    deferred: int = 0
    already_waiting: int = 0


async def sweep_outbox(runtime: Runtime) -> SweepResult:
    """The safety net, every minute: re-queue ``sending`` rows whose lease expired (a
    worker died) and re-defer queued rows whose job was lost, at most one waiting
    sweep job per row (``queueing_lock``). Does nothing while SMTP isn't configured."""
    if not runtime.settings.smtp_configured:
        return SweepResult()
    now = runtime.clock()
    async with session_scope(runtime.sessionmaker) as db:
        expired = (OutboundEmail.status == EmailStatus.SENDING) & (
            OutboundEmail.next_attempt_at <= now
        )
        requeued = list(
            await db.scalars(
                update(OutboundEmail)
                .where(expired, OutboundEmail.attempts < OutboundEmail.max_attempts)
                .values(status=EmailStatus.QUEUED, next_attempt_at=now, updated_at=now)
                .returning(OutboundEmail.id)
                .execution_options(synchronize_session=False)
            )
        )
        failed = list(
            await db.scalars(
                update(OutboundEmail)
                .where(expired, OutboundEmail.attempts >= OutboundEmail.max_attempts)
                .values(
                    status=EmailStatus.FAILED,
                    next_attempt_at=None,
                    last_error=WORKER_STOPPED,
                    updated_at=now,
                )
                .returning(OutboundEmail.id)
                .execution_options(synchronize_session=False)
            )
        )
        lost = list(
            await db.scalars(
                select(OutboundEmail.id)
                .where(
                    OutboundEmail.status == EmailStatus.QUEUED,
                    OutboundEmail.next_attempt_at <= now - LOST_JOB_GRACE,
                )
                .order_by(OutboundEmail.next_attempt_at)
                .limit(outbox.SWEEP_BATCH)
            )
        )
        queued = await _queued_count(db)
    EMAILS_QUEUED.set(queued)
    deferred = waiting = 0
    for email_id in list(dict.fromkeys([*requeued, *lost]))[: outbox.SWEEP_BATCH]:
        if await _defer_once(runtime, email_id):
            deferred += 1
        else:
            waiting += 1
    if requeued or failed or deferred:
        logger.info(
            "outbox swept",
            extra={
                "requeued": len(requeued),
                "failed": len(failed),
                "deferred": deferred,
                "already_waiting": waiting,
            },
        )
    return SweepResult(len(requeued), len(failed), deferred, waiting)


async def _queued_count(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(OutboundEmail)
            .where(OutboundEmail.status == EmailStatus.QUEUED)
        )
        or 0
    )


async def _defer_once(runtime: Runtime, email_id: UUID) -> bool:
    """Defer a sweep job for the row on its own (autocommit); ``False`` if one is
    already waiting."""
    assert runtime.jobs is not None  # noqa: S101 - the worker opens the job queue
    try:
        await runtime.jobs.configure_task(
            outbox.SEND_EMAIL_TASK, queueing_lock=f"send_email:{email_id}"
        ).defer_async(email_id=str(email_id))
    except AlreadyEnqueued:
        return False
    return True
